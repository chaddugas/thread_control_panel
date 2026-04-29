"""Shared entity base for panel-itself entities (sensor, switch, button).

Handles the two things every panel entity needs: the device identity
(so they all appear under one HA device card) and the availability
subscription (so they flip to "unavailable" when the C6 drops off the
broker).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, TOPIC_PANEL_AVAILABILITY

_LOGGER = logging.getLogger(__name__)


def panel_device_info(panel_id: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, panel_id)},
        name=f"Thread Panel: {panel_id}",
        manufacturer="thread_panel",
        model="Thread Control Panel",
    )


class PanelEntityBase(Entity):
    """Device identity + C6-availability subscription.

    Subclasses should call super().async_added_to_hass() first, then
    install any additional subscriptions they need.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, panel_id: str) -> None:
        self._panel_id = panel_id
        self._attr_available = False
        self._attr_device_info = panel_device_info(panel_id)
        self._unsubs: list[Any] = []

    async def async_added_to_hass(self) -> None:
        availability_topic = TOPIC_PANEL_AVAILABILITY.format(panel_id=self._panel_id)
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, availability_topic, self._on_availability_message
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
