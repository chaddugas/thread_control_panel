"""Panel-itself switch entities (screen_on, wifi_enabled).

State comes from `state/<name>` (retained, published by the bridge via
panel_state envelope). On turn_on/turn_off, we publish `{"value": bool}`
to `set/<name>`; the C6 forwards as panel_set, the bridge runs the
system action, and then emits the new state back — so the "optimistic"
state we set here gets confirmed (or reverted) within a round trip.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PANEL_ID, TOPIC_PANEL_SET, TOPIC_PANEL_STATE
from .entity import PanelEntityBase

_LOGGER = logging.getLogger(__name__)


class _PanelSwitchBase(PanelEntityBase, SwitchEntity):
    """Bool state via state/<name>; set via set/<name>."""

    _control_name: str  # subclasses set this

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_is_on = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass,
                TOPIC_PANEL_STATE.format(panel_id=self._panel_id, name=self._control_name),
                self._on_state_message,
            )
        )

    @callback
    def _on_state_message(self, msg) -> None:
        try:
            data = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "%s: malformed state payload: %r", self.entity_id, msg.payload
            )
            return
        if not isinstance(data, dict):
            return
        value = data.get("value")
        if isinstance(value, bool):
            self._attr_is_on = value
            self.async_write_ha_state()

    async def _publish_set(self, value: bool) -> None:
        topic = TOPIC_PANEL_SET.format(panel_id=self._panel_id, name=self._control_name)
        await mqtt.async_publish(
            self.hass, topic, json.dumps({"value": value}), qos=0, retain=False
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._publish_set(True)
        # Optimistic — the bridge's panel_state publish will confirm (or
        # correct) this within a few hundred ms.
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._publish_set(False)
        self._attr_is_on = False
        self.async_write_ha_state()


class PanelScreenSwitch(_PanelSwitchBase):
    _attr_name = "Screen"
    _attr_icon = "mdi:monitor"
    _control_name = "screen_on"

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_screen_on"


class PanelWifiSwitch(_PanelSwitchBase):
    _attr_name = "Wi-Fi"
    _attr_icon = "mdi:wifi"
    _control_name = "wifi_enabled"

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_wifi_enabled"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    panel_id: str = entry.data[CONF_PANEL_ID]
    async_add_entities(
        [PanelScreenSwitch(panel_id), PanelWifiSwitch(panel_id)]
    )
