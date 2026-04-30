"""HA-side `update` entity for the panel firmware/Pi/UI bundle.

Wires together the three pieces Phase 3a built (C6 firmware that publishes
state/version on MQTT connect; bridge-spawned panel-update.sh that runs the
flow when cmd/update arrives; status republished as state/update_status):

- `installed_version` ← `state/version` retained MQTT topic, set by C6 on
  every MQTT (re)connect.
- `latest_version` ← polling https://api.github.com/repos/<repo>/releases
  every hour, picking the most recent non-draft release that matches the
  prerelease filter (configurable via integration options).
- `release_summary` / `release_url` ← release body / html_url from the
  same poll.
- `async_install(version)` → publish cmd/update to MQTT with the requested
  version, which the C6 forwards over UART to the bridge, which spawns
  panel-update.sh.
- `in_progress` ← `state/update_status` non-retained MQTT topic, the
  bridge tails /opt/panel/update.status and republishes per-phase JSON
  lines. Terminal phases ("done", "failed", "rejected",
  "console_takeover_failed") flip in_progress back to False.

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
from homeassistant.helpers.event import async_track_time_interval

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

# Phases written by panel-update.sh that mean "the run is over." Anything
# else implies a phase is in progress.
TERMINAL_PHASES = frozenset({
    "done",
    "failed",
    "rejected",
    "console_takeover_failed",
})


class PanelUpdateEntity(PanelEntityBase, UpdateEntity):
    """Surfaces the panel's firmware/UI/bridge bundle as an `update` entity."""

    _attr_name = "Firmware"
    _attr_icon = "mdi:cloud-download-outline"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.SPECIFIC_VERSION
        | UpdateEntityFeature.RELEASE_NOTES
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
        await super().async_will_remove_from_hass()

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
        if isinstance(version, str) and version:
            self._attr_installed_version = version
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
        if phase is None:
            return
        # Map phase to in_progress. "starting" through anything pre-terminal
        # → True; terminal phases → False.
        self._attr_in_progress = phase not in TERMINAL_PHASES
        self.async_write_ha_state()

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

        chosen = None
        for release in releases:
            if not isinstance(release, dict):
                continue
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
        self._attr_release_summary = body if isinstance(body, str) and body else None
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
        # Optimistic in_progress flip — the first state/update_status
        # message will overwrite this with the real phase. Without it
        # there'd be a visible gap between the user clicking Install and
        # HA showing progress.
        self._attr_in_progress = True
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
