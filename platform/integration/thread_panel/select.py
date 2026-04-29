"""Wi-Fi network select.

Options come from the Pi's last scan (state/wifi_ssids retained, refreshed
every 30 s and on demand via the Refresh Networks button). The user picks
one and presses the Connect button; the button reads this entity's
`current_option` and the security type from extra_state_attributes to
build the cmd/wifi_connect payload.

Selection state is HA-local — there's no MQTT round-trip on `async_select_option`.
The bridge doesn't need to know what's selected until Connect is pressed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_PANEL_ID,
    DATA_ENTITIES,
    DOMAIN,
    TOPIC_PANEL_STATE,
)
from .entity import PanelEntityBase

_LOGGER = logging.getLogger(__name__)

REGISTRY_KEY = "wifi_network"
ATTR_SECURITY_BY_SSID = "security_by_ssid"


class PanelWifiNetworkSelect(PanelEntityBase, SelectEntity):
    """Dropdown of broadcasting networks the Pi can see."""

    _attr_name = "Wi-Fi Network"
    _attr_icon = "mdi:wifi-cog"

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_wifi_network"
        self._attr_options = []
        self._attr_current_option = None
        self._attr_extra_state_attributes = {ATTR_SECURITY_BY_SSID: {}}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        topic = TOPIC_PANEL_STATE.format(
            panel_id=self._panel_id, name="wifi_ssids"
        )
        self._unsubs.append(
            await mqtt.async_subscribe(self.hass, topic, self._on_ssids_message)
        )
        # Register entity_id so the connect button can find us.
        self.hass.data.setdefault(DOMAIN, {}).setdefault(
            DATA_ENTITIES, {}
        ).setdefault(self._panel_id, {})[REGISTRY_KEY] = self.entity_id

    @callback
    def _on_ssids_message(self, msg) -> None:
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "%s: malformed wifi_ssids payload: %r", self.entity_id, msg.payload
            )
            return
        if not isinstance(data, dict):
            return
        networks = data.get("value")
        if not isinstance(networks, list):
            return

        options: list[str] = []
        security_by_ssid: dict[str, str | None] = {}
        for net in networks:
            if not isinstance(net, dict):
                continue
            ssid = net.get("ssid")
            if not isinstance(ssid, str) or not ssid:
                continue
            options.append(ssid)
            # security can be "wpa-psk", "sae", "none", or null (enterprise).
            # Stash either way; the connect button decides what to do.
            security_by_ssid[ssid] = net.get("security")

        self._attr_options = options
        self._attr_extra_state_attributes = {ATTR_SECURITY_BY_SSID: security_by_ssid}

        # If the previously-selected network has dropped out of range,
        # clear the selection so the dropdown reflects reality.
        if (
            self._attr_current_option is not None
            and self._attr_current_option not in options
        ):
            self._attr_current_option = None
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        if option not in self._attr_options:
            _LOGGER.warning(
                "%s: rejecting select of %r — not in current options",
                self.entity_id,
                option,
            )
            return
        self._attr_current_option = option
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    panel_id: str = entry.data[CONF_PANEL_ID]
    async_add_entities([PanelWifiNetworkSelect(panel_id)])
