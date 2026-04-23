"""Panel-itself button entities (reboot_pi, reboot_c6).

Stateless one-shots. On press, we publish an empty payload to
`cmd/<name>`; the C6 either handles it directly (reboot_c6 → esp_restart)
or forwards it over UART as a panel_cmd for the bridge to act on
(reboot_pi → sudo shutdown -r now).
"""

from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PANEL_ID, TOPIC_PANEL_CMD
from .entity import PanelEntityBase

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    panel_id: str = entry.data[CONF_PANEL_ID]
    async_add_entities(
        [PanelRebootPiButton(panel_id), PanelRebootC6Button(panel_id)]
    )
