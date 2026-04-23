"""Panel-itself sensor entities (proximity, ambient brightness).

Each panel exposes the two sensors the C6 publishes periodically to MQTT.
The entities subscribe to those retained topics and surface the `value`
field as the native value, with auxiliary fields exposed as extra state
attributes. Entity availability is gated on the C6's own `availability`
topic (LWT-backed), so an ungraceful disconnect shows the entities as
"unavailable" in HA within the broker keepalive window.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_PANEL_ID,
    DOMAIN,
    TOPIC_PANEL_AMBIENT_BRIGHTNESS,
    TOPIC_PANEL_AVAILABILITY,
    TOPIC_PANEL_PROXIMITY,
)

_LOGGER = logging.getLogger(__name__)


def _device_info(panel_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, panel_id)},
        name=f"Thread Panel: {panel_id}",
        manufacturer="thread_panel",
        model="Thread Control Panel",
    )


class _PanelSensorBase(SensorEntity):
    """Shared availability + state-subscription plumbing."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    _state_topic_template: str  # subclasses set this

    def __init__(self, panel_id: str) -> None:
        self._panel_id = panel_id
        self._attr_available = False
        self._attr_device_info = _device_info(panel_id)
        self._unsubs: list[Any] = []

    async def async_added_to_hass(self) -> None:
        availability_topic = TOPIC_PANEL_AVAILABILITY.format(panel_id=self._panel_id)
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, availability_topic, self._on_availability_message
            )
        )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass,
                self._state_topic_template.format(panel_id=self._panel_id),
                self._on_state_message,
            )
        )

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _on_availability_message(self, msg) -> None:
        payload = msg.payload if isinstance(msg.payload, str) else ""
        self._attr_available = payload.strip() == "online"
        self.async_write_ha_state()

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
        self._apply_state(data)
        self.async_write_ha_state()

    def _apply_state(self, data: dict[str, Any]) -> None:
        raise NotImplementedError


class PanelProximitySensor(_PanelSensorBase):
    """LiDAR distance reading from the TF-Mini Plus on the C6."""

    _attr_name = "Proximity"
    _attr_native_unit_of_measurement = UnitOfLength.CENTIMETERS
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _state_topic_template = TOPIC_PANEL_PROXIMITY

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_proximity"

    def _apply_state(self, data: dict[str, Any]) -> None:
        self._attr_native_value = data.get("value")
        strength = data.get("strength")
        self._attr_extra_state_attributes = (
            {"strength": strength} if strength is not None else {}
        )


class PanelAmbientBrightnessSensor(_PanelSensorBase):
    """TEMT6000 ambient brightness, normalized 0..100."""

    _attr_name = "Ambient brightness"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _state_topic_template = TOPIC_PANEL_AMBIENT_BRIGHTNESS

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_ambient_brightness"

    def _apply_state(self, data: dict[str, Any]) -> None:
        self._attr_native_value = data.get("value")
        attrs: dict[str, Any] = {}
        if "raw" in data:
            attrs["raw"] = data["raw"]
        if "mv" in data:
            attrs["mv"] = data["mv"]
        self._attr_extra_state_attributes = attrs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    panel_id: str = entry.data[CONF_PANEL_ID]
    async_add_entities(
        [PanelProximitySensor(panel_id), PanelAmbientBrightnessSensor(panel_id)]
    )
