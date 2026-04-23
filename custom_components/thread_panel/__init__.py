"""Thread Panel: generic per-entity forwarder between HA and a touchscreen panel."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MANIFEST_YAML, DOMAIN
from .forwarder import PanelForwarder
from .manifest_loader import ManifestError, parse_manifest

_LOGGER = logging.getLogger(__name__)


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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    forwarder: PanelForwarder | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if forwarder is not None:
        await forwarder.async_stop()
    return True
