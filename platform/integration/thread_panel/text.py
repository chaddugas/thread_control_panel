"""Wi-Fi password text input.

Mode = password so the value is masked in the HA frontend. State is
purely HA-local: nothing goes to MQTT until the Connect button bundles
SSID + password into a cmd/wifi_connect payload. The button optimistically
clears this entity (via `text.set_value` service) immediately on press.

Note: HA's recorder will capture state changes by default. If that
matters for your threat model, exclude `text.thread_panel_*_wifi_password`
from the recorder via your HA config — the integration doesn't try to do
this for you, since recorder config is global.
"""

from __future__ import annotations

import logging

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PANEL_ID, DATA_ENTITIES, DOMAIN
from .entity import PanelEntityBase

_LOGGER = logging.getLogger(__name__)

REGISTRY_KEY = "wifi_password"


class PanelWifiPasswordText(PanelEntityBase, TextEntity):
    """Single-line password input. Cleared after every Connect press."""

    _attr_name = "Wi-Fi Password"
    _attr_icon = "mdi:form-textbox-password"
    _attr_mode = TextMode.PASSWORD
    _attr_native_max = 64
    _attr_native_value = ""

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_wifi_password"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.hass.data.setdefault(DOMAIN, {}).setdefault(
            DATA_ENTITIES, {}
        ).setdefault(self._panel_id, {})[REGISTRY_KEY] = self.entity_id

    async def async_set_value(self, value: str) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    panel_id: str = entry.data[CONF_PANEL_ID]
    async_add_entities([PanelWifiPasswordText(panel_id)])
