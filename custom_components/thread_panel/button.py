"""Panel-itself button entities.

Two flavors:
  - Stateless one-shots that publish an empty payload to cmd/<name>
    (reboot_pi, reboot_c6, wifi_scan).
  - The Connect Wi-Fi button, which assembles a structured payload from
    the current values of the wifi_network select + wifi_password text
    before publishing, then optimistically clears the password.
"""

from __future__ import annotations

import json
import logging

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PANEL_ID, DATA_ENTITIES, DOMAIN, TOPIC_PANEL_CMD
from .entity import PanelEntityBase
from .select import ATTR_SECURITY_BY_SSID, REGISTRY_KEY as SELECT_REGISTRY_KEY
from .text import (
    REGISTRY_KEY as TEXT_REGISTRY_KEY,
    VALUE_REGISTRY_KEY as TEXT_VALUE_REGISTRY_KEY,
)

_LOGGER = logging.getLogger(__name__)


class _PanelButtonBase(PanelEntityBase, ButtonEntity):
    _command_name: str  # subclasses set this

    async def async_press(self) -> None:
        topic = TOPIC_PANEL_CMD.format(
            panel_id=self._panel_id, name=self._command_name
        )
        await mqtt.async_publish(self.hass, topic, "{}", qos=0, retain=False)


class PanelRebootPiButton(_PanelButtonBase):
    _attr_name = "Reboot Pi"
    _attr_icon = "mdi:restart"
    _command_name = "reboot_pi"

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_reboot_pi"


class PanelRebootC6Button(_PanelButtonBase):
    _attr_name = "Reboot C6"
    _attr_icon = "mdi:restart-alert"
    _command_name = "reboot_c6"

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_reboot_c6"


class PanelWifiScanButton(_PanelButtonBase):
    _attr_name = "Refresh Wi-Fi Networks"
    _attr_icon = "mdi:wifi-refresh"
    _command_name = "wifi_scan"

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_wifi_scan"


class PanelWifiConnectButton(PanelEntityBase, ButtonEntity):
    """Reads the current wifi_network select + wifi_password text and
    publishes their values together to cmd/wifi_connect, then clears
    the password optimistically. The bridge is the source of truth for
    success/failure (see Wi-Fi Error sensor)."""

    _attr_name = "Connect to Wi-Fi"
    _attr_icon = "mdi:wifi-arrow-up-down"

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_wifi_connect"

    async def async_press(self) -> None:
        registry = (
            self.hass.data.get(DOMAIN, {})
            .get(DATA_ENTITIES, {})
            .get(self._panel_id, {})
        )
        select_id = registry.get(SELECT_REGISTRY_KEY)
        text_id = registry.get(TEXT_REGISTRY_KEY)

        if not select_id or not text_id:
            _LOGGER.warning(
                "wifi_connect: companion entities not registered yet "
                "(select=%r, text=%r)",
                select_id,
                text_id,
            )
            return

        select_state = self.hass.states.get(select_id)

        if select_state is None or select_state.state in (
            None,
            "",
            "unknown",
            "unavailable",
        ):
            _LOGGER.warning("wifi_connect: no network selected")
            return

        ssid = select_state.state
        # Password lives in hass.data (intentionally not in state — see
        # text.py for the recorder-exclusion rationale). Empty string when
        # the user hasn't typed anything yet.
        password = registry.get(TEXT_VALUE_REGISTRY_KEY, "") or ""

        security_map = (
            select_state.attributes.get(ATTR_SECURITY_BY_SSID, {}) or {}
        )
        security = security_map.get(ssid)
        # The bridge tolerates missing/unknown security and falls back to
        # wpa-psk; passing it through verbatim lets it route correctly when
        # the scan info is available.

        payload = {
            "ssid": ssid,
            "password": password,
            "security": security,
        }
        topic = TOPIC_PANEL_CMD.format(
            panel_id=self._panel_id, name="wifi_connect"
        )
        await mqtt.async_publish(
            self.hass,
            topic,
            json.dumps(payload, separators=(",", ":")),
            qos=0,
            retain=False,
        )

        # Wipe the password optimistically. If the connect fails the user
        # has to retype, which is acceptable UX and avoids leaving creds
        # sitting in entity state any longer than necessary.
        await self.hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": text_id, "value": ""},
            blocking=False,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    panel_id: str = entry.data[CONF_PANEL_ID]
    async_add_entities(
        [
            PanelRebootPiButton(panel_id),
            PanelRebootC6Button(panel_id),
            PanelWifiScanButton(panel_id),
            PanelWifiConnectButton(panel_id),
        ]
    )
