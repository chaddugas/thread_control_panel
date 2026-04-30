"""HA-side `update` entity for the panel firmware/Pi/UI bundle.

Wires together the three pieces Phase 3a built (C6 firmware that publishes
state/version on MQTT connect; bridge-spawned panel-update.sh that runs the
flow when cmd/update arrives; status republished as state/update_status):

- `installed_version` ← `state/version` retained MQTT topic, set by C6 on
  every MQTT (re)connect.
- `latest_version` ← polling https://api.github.com/repos/<repo>/releases
  every hour, picking the most recent non-draft release that matches the
  prerelease filter (configurable via integration options).
- `release_summary` / `release_url` / `async_release_notes` ← release body
  / html_url from the same poll. release_summary is HA-truncated to 255
  chars; release_notes returns the full body for the more-info dialog.
- `async_install(version)` → publish cmd/update to MQTT with the requested
  version, which the C6 forwards over UART to the bridge, which spawns
  panel-update.sh.
- `in_progress` + `update_percentage` ← `state/update_status` non-retained
  MQTT topic. The bridge tails /opt/panel/update.status and republishes
  per-phase JSON lines; PHASE_PERCENTAGES maps each phase to a coarse
  percent-complete. Failure phases (TERMINAL_FAILURE_PHASES) flip
  in_progress False immediately. Success phases (TERMINAL_SUCCESS_PHASES,
  i.e. `done`/`rebooting`) hold in_progress True until state/version
  reports the install target — closing the window where HA's frontend
  evaluates the install before the C6 has rebooted and republished.

Each configured panel gets its own update entity. With multiple panels,
each polls GitHub independently — wasteful but correct, and we're not at
the scale where it matters yet.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import (
    CONF_INCLUDE_PRERELEASES,
    CONF_PANEL_ID,
    DEFAULT_INCLUDE_PRERELEASES,
    GITHUB_REPO,
    TOPIC_PANEL_CMD_UPDATE,
    TOPIC_PANEL_UPDATE_STATUS,
    TOPIC_PANEL_VERSION,
)
from .entity import PanelEntityBase

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(hours=1)
GITHUB_RELEASES_URL = "https://api.github.com/repos/{repo}/releases"
GITHUB_TIMEOUT_SEC = 15

# Mapping from each panel-update.sh `publish_status` phase name to a coarse
# percent-complete value, ordered roughly by elapsed wallclock during a real
# OTA run (download + venv dominate the middle, healthcheck/flash dominate
# the tail). HA's UpdateEntity uses `update_percentage` to drive a visible
# progress bar in the more-info dialog; without it, even with `in_progress`
# True, the UI shows no install affordance.
PHASE_PERCENTAGES: dict[str, int] = {
    "starting": 5,
    "enabling_wifi": 10,
    "waiting_for_dns": 15,
    "resolving_version": 20,
    "resolved": 25,
    "downloading_manifest": 30,
    "downloading_artifacts": 40,
    "extracting": 50,
    "creating_venv": 60,
    "swapping_symlink": 65,
    "rendering_units": 68,
    "restarting_bridge": 72,
    "restarting_ui": 76,
    "healthcheck": 80,
    "flashing_c6": 85,
    "c6_flashed": 90,
    "verifying_c6": 93,
    "c6_verified": 96,
    "disabling_wifi": 98,
    "wifi_off_skipped": 98,
    "rolling_back": 90,
    "c6_flash_failed": 90,
    "done": 100,
    "rebooting": 100,
}

# panel-update.sh phases that mean the script reached its end successfully.
# After these we keep `in_progress=True` until `state/version` reports the
# target (the C6 reboot + Thread re-attach + MQTT reconnect adds ~30-45s
# between `done` and the version republish). Without this hold, HA's
# frontend can evaluate "install completed but version didn't change" and
# cache a stale failure, surfacing as "Unknown error" on the entity panel.
TERMINAL_SUCCESS_PHASES = frozenset({"done", "rebooting"})

# Phases that mean the run failed and version won't change. Flip back to
# in_progress=False immediately and clear progress.
TERMINAL_FAILURE_PHASES = frozenset({
    "failed",
    "rejected",
    "console_takeover_failed",
})

# Hard cap on the wait-for-version-match window after a TERMINAL_SUCCESS
# phase. The script publishes `rebooting` ~immediately after `done`; the
# Pi reboot + C6 republish has been observed at 30-45s. 120s gives
# headroom without leaving the entity stuck in_progress forever if the
# republish path itself broke.
DONE_VERIFY_TIMEOUT_SEC = 120


class PanelUpdateEntity(PanelEntityBase, UpdateEntity):
    """Surfaces the panel's firmware/UI/bridge bundle as an `update` entity."""

    _attr_name = "Firmware"
    _attr_icon = "mdi:cloud-download-outline"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.SPECIFIC_VERSION
        | UpdateEntityFeature.RELEASE_NOTES
        | UpdateEntityFeature.PROGRESS
    )

    def __init__(self, panel_id: str, include_prereleases: bool) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_firmware"
        self._include_prereleases = include_prereleases
        self._attr_installed_version = None
        self._attr_latest_version = None
        self._attr_release_summary = None
        self._attr_release_url = None
        self._attr_in_progress = False
        self._attr_update_percentage = None
        # Full release body, kept separately from release_summary because HA
        # truncates release_summary to 255 characters but async_release_notes
        # can return arbitrarily long markdown. Without overriding
        # async_release_notes, declaring RELEASE_NOTES support left HA's
        # frontend fetching null notes via WebSocket — surfaced as "Unknown
        # error" on the entity panel even when the entity was otherwise
        # healthy.
        self._release_notes_full: str | None = None
        # Tracks the version requested by the most recent async_install. Used
        # to know when state/version has caught up after a TERMINAL_SUCCESS
        # phase so we can finally flip in_progress False.
        self._pending_target_version: str | None = None
        self._done_timer_unsub = None
        # Override base: this entity is always available — the C6 doesn't
        # have to be online for HA to know the latest GitHub release. (The
        # `installed_version` is None until we hear from MQTT, which gives
        # HA's UI the right "unknown" affordance.)
        self._attr_available = True
        self._poll_unsub = None

    async def async_added_to_hass(self) -> None:
        # Skip PanelEntityBase's availability subscription — see
        # _attr_available override above. We still want the device-info
        # binding from the base, which __init__ already set.
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass,
                TOPIC_PANEL_VERSION.format(panel_id=self._panel_id),
                self._on_version_message,
            )
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass,
                TOPIC_PANEL_UPDATE_STATUS.format(panel_id=self._panel_id),
                self._on_update_status_message,
            )
        )

        # Initial fetch so the entity has a latest_version on startup,
        # then schedule hourly refresh for the lifetime of the entry.
        await self._poll_github()
        self._poll_unsub = async_track_time_interval(
            self.hass, self._poll_github_callback, POLL_INTERVAL
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._poll_unsub is not None:
            self._poll_unsub()
            self._poll_unsub = None
        self._cancel_done_timer()
        await super().async_will_remove_from_hass()

    async def async_release_notes(self) -> str | None:
        """Return the full release body for HA to render in the more-info dialog.

        HA truncates `release_summary` to 255 characters; this method has no
        such limit. Declaring RELEASE_NOTES feature support without overriding
        this method previously caused HA's frontend to display "Unknown error"
        on the entity panel — the WS fetch returned the default None, which
        the frontend's render path didn't handle gracefully.
        """
        return self._release_notes_full

    @callback
    def _on_version_message(self, msg) -> None:
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "%s: malformed state/version payload: %r",
                self.entity_id,
                msg.payload,
            )
            return
        if not isinstance(data, dict):
            return
        version = data.get("version")
        if not (isinstance(version, str) and version):
            return

        self._attr_installed_version = version

        # If a pending install is waiting for the C6 to republish its version,
        # this is the signal that the OTA actually landed. Flip in_progress
        # off and clear progress so HA's frontend sees the install as
        # successfully completed.
        if (
            self._pending_target_version is not None
            and version == self._pending_target_version
        ):
            self._cancel_done_timer()
            self._pending_target_version = None
            self._attr_in_progress = False
            self._attr_update_percentage = None

        self.async_write_ha_state()

    @callback
    def _on_update_status_message(self, msg) -> None:
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        phase = data.get("phase")
        if not isinstance(phase, str):
            return

        if phase in PHASE_PERCENTAGES:
            self._attr_update_percentage = PHASE_PERCENTAGES[phase]

        if phase in TERMINAL_FAILURE_PHASES:
            self._cancel_done_timer()
            self._pending_target_version = None
            self._attr_in_progress = False
            self._attr_update_percentage = None
        elif phase in TERMINAL_SUCCESS_PHASES:
            # Hold in_progress True until state/version reports the target
            # (or the timeout below fires). Without this hold, HA's frontend
            # evaluates the install before the C6 has rebooted and republished
            # its version, then caches a stale failure as "Unknown error".
            self._attr_in_progress = True
            if self._done_timer_unsub is None:
                self._done_timer_unsub = async_call_later(
                    self.hass,
                    DONE_VERIFY_TIMEOUT_SEC,
                    self._on_done_timeout,
                )
        else:
            self._attr_in_progress = True

        self.async_write_ha_state()

    @callback
    def _on_done_timeout(self, _now) -> None:
        """Force in_progress False if the C6 never republished its version.

        Last-resort safety net. If we hit this, something in the C6 reboot
        path didn't republish state/version — either the OTA never reached
        the C6, or the new firmware crashed before reconnecting MQTT. Either
        way, leaving the entity stuck in_progress forever is worse than
        flipping it off and letting the user see installed != latest.
        """
        self._done_timer_unsub = None
        self._pending_target_version = None
        self._attr_in_progress = False
        self._attr_update_percentage = None
        self.async_write_ha_state()
        _LOGGER.warning(
            "%s: timed out waiting for C6 to republish version after install",
            self.entity_id,
        )

    def _cancel_done_timer(self) -> None:
        if self._done_timer_unsub is not None:
            self._done_timer_unsub()
            self._done_timer_unsub = None

    async def _poll_github_callback(self, _now) -> None:
        await self._poll_github()

    async def _poll_github(self) -> None:
        url = GITHUB_RELEASES_URL.format(repo=GITHUB_REPO)
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=GITHUB_TIMEOUT_SEC) as resp:
                resp.raise_for_status()
                releases = await resp.json()
        except Exception as err:  # noqa: BLE001 — network errors are routine
            _LOGGER.warning(
                "%s: GitHub releases poll failed: %s", self.entity_id, err
            )
            return

        if not isinstance(releases, list):
            _LOGGER.warning(
                "%s: GitHub releases response was not a list", self.entity_id
            )
            return

        # GitHub's /releases endpoint sorts by tag name (lex desc), NOT
        # by created_at, despite the docs' claim. With semver tags, this
        # means "v2.0.0-beta.9" sorts BEFORE "v2.0.0-beta.19" (because "9"
        # > "1" alphabetically), so picking the API's index 0 gives the
        # lex-greatest tag, not the most recently created. Sort defensively
        # by `created_at` desc here so the iteration below picks the
        # actually-most-recent release.
        sorted_releases = sorted(
            (r for r in releases if isinstance(r, dict)),
            key=lambda r: r.get("created_at") or "",
            reverse=True,
        )

        chosen = None
        for release in sorted_releases:
            if release.get("draft"):
                continue
            if release.get("prerelease") and not self._include_prereleases:
                continue
            chosen = release
            break

        if chosen is None:
            return

        tag = chosen.get("tag_name")
        if isinstance(tag, str) and tag:
            self._attr_latest_version = tag
        body = chosen.get("body")
        body_str = body if isinstance(body, str) and body else None
        # release_summary gets truncated to 255 chars by HA; release_notes
        # (via async_release_notes) renders the full body in the more-info
        # dialog. Both come from the same GitHub field.
        self._attr_release_summary = body_str
        self._release_notes_full = body_str
        url = chosen.get("html_url")
        self._attr_release_url = url if isinstance(url, str) and url else None
        self.async_write_ha_state()

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """User clicked Install. Publish cmd/update to start the OTA."""
        target = version or self._attr_latest_version
        if not target:
            _LOGGER.warning(
                "%s: install requested but no target version known",
                self.entity_id,
            )
            return

        topic = TOPIC_PANEL_CMD_UPDATE.format(panel_id=self._panel_id)
        payload = json.dumps({"version": target}, separators=(",", ":"))
        _LOGGER.info("%s: publishing %s ← %s", self.entity_id, topic, payload)
        await mqtt.async_publish(self.hass, topic, payload, qos=0, retain=False)
        # Optimistic in_progress + 0% flip — the first state/update_status
        # message will overwrite both with the real phase. Without it
        # there'd be a visible gap between the user clicking Install and
        # HA showing progress. Tracking _pending_target_version here lets
        # _on_version_message recognize when the install has actually
        # landed on the C6.
        self._pending_target_version = target
        self._attr_in_progress = True
        self._attr_update_percentage = 0
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    panel_id: str = entry.data[CONF_PANEL_ID]
    include_prereleases = bool(
        entry.options.get(CONF_INCLUDE_PRERELEASES, DEFAULT_INCLUDE_PRERELEASES)
    )
    async_add_entities([PanelUpdateEntity(panel_id, include_prereleases)])
