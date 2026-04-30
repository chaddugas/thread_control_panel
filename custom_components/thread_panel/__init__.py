"""Thread Panel: generic per-entity forwarder between HA and a touchscreen panel."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_MANIFEST_YAML, DOMAIN
from .forwarder import PanelForwarder
from .manifest_loader import ManifestError, parse_manifest

_LOGGER = logging.getLogger(__name__)

# Platforms hosting the panel-itself entities (sensors, future switches/etc.).
# The generic entity forwarder is not a platform — it runs directly in
# async_setup_entry and publishes to MQTT topics the C6 subscribes to.
PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.TEXT,
    Platform.UPDATE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    yaml_text = entry.data[CONF_MANIFEST_YAML]
    try:
        manifest = await hass.async_add_executor_job(parse_manifest, yaml_text)
    except ManifestError as err:
        _LOGGER.error("Failed to parse stored manifest: %s", err)
        return False

    forwarder = PanelForwarder(hass, manifest)
    await forwarder.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = forwarder

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload the entry whenever data or options change. OptionsFlow updates
    # entry.options (include_prereleases) and entry.data (manifest YAML);
    # the reload re-runs async_setup_entry so platforms come back with the
    # new values. Without this, options changes only take effect on next
    # HA restart.
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_change))

    return True


async def _async_reload_on_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Called by HA when entry.data or entry.options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    forwarder: PanelForwarder | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if forwarder is not None:
        await forwarder.async_stop()
    return unload_ok
