"""Wi-Fi password text input.

Mode = password so the value is masked in the HA frontend. The typed value
is held in hass.data and never written to the entity's state — that path
goes to the recorder DB, where the password would persist as plaintext
history. PanelWifiConnectButton reads from hass.data at press time.

Trade-off vs. recording the value in state: the password doesn't survive
HA frontend navigation. If the user types it, navigates away, and comes
back, they have to retype. Acceptable since the typical flow is type +
immediately press Connect, and the existing post-press auto-clear already
treats the value as ephemeral.

HA's recorder filter is built once at startup from configuration.yaml and
isn't extensible from an integration, so storing-outside-state is the only
way to keep this entity's value out of the recorder DB without asking the
user to maintain a `recorder.exclude` config block.
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
# Separate slot in the per-panel registry under hass.data — holds the
# actual typed password while it's pending Connect. Imported by button.py.
VALUE_REGISTRY_KEY = "wifi_password_value"


class PanelWifiPasswordText(PanelEntityBase, TextEntity):
    """Single-line password input.

    State is intentionally always empty. The typed value is held in
    hass.data so it never enters the state machine (and therefore never
    reaches the recorder DB). The Connect button reads the password
    from hass.data, not from `hass.states.get(...).state`.
    """

    _attr_name = "Wi-Fi Password"
    _attr_icon = "mdi:form-textbox-password"
    _attr_mode = TextMode.PASSWORD
    _attr_native_max = 64
    _attr_native_value = ""  # always — actual value lives in hass.data

    def __init__(self, panel_id: str) -> None:
        super().__init__(panel_id)
        self._attr_unique_id = f"thread_panel_{panel_id}_wifi_password"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.hass.data.setdefault(DOMAIN, {}).setdefault(
            DATA_ENTITIES, {}
        ).setdefault(self._panel_id, {})[REGISTRY_KEY] = self.entity_id

    async def async_set_value(self, value: str) -> None:
        # Park the value in hass.data — never call async_write_ha_state, so
        # the state machine (and recorder) never see it. Connect reads from
        # the same registry slot at press time; setting "" here also clears
        # the slot, which is how the post-press auto-clear takes effect.
        self.hass.data.setdefault(DOMAIN, {}).setdefault(
            DATA_ENTITIES, {}
        ).setdefault(self._panel_id, {})[VALUE_REGISTRY_KEY] = value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    panel_id: str = entry.data[CONF_PANEL_ID]
    async_add_entities([PanelWifiPasswordText(panel_id)])
