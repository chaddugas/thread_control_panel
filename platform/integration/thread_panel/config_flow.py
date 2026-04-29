"""Config flow for thread_panel: paste the panel manifest YAML.

Initial setup (ConfigFlow): user pastes a full manifest; we derive
panel_id and create the entry.

Reconfig (OptionsFlow): user edits the manifest YAML in place to add/
remove entities or tweak attribute allowlists. panel_id must not
change — it's the entry's stable identity.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_MANIFEST_YAML, CONF_PANEL_ID, DOMAIN
from .manifest_loader import ManifestError, parse_manifest

_LOGGER = logging.getLogger(__name__)

YAML_SELECTOR = TextSelector(
    TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
)


class ThreadPanelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            yaml_text = user_input[CONF_MANIFEST_YAML]
            try:
                manifest = await self.hass.async_add_executor_job(
                    parse_manifest, yaml_text
                )
            except ManifestError as err:
                _LOGGER.error("Manifest parse failed: %s", err)
                errors["base"] = "invalid_manifest"
            else:
                await self.async_set_unique_id(f"{DOMAIN}_{manifest.panel_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Thread Panel: {manifest.panel_id}",
                    data={
                        CONF_MANIFEST_YAML: yaml_text,
                        CONF_PANEL_ID: manifest.panel_id,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_MANIFEST_YAML): YAML_SELECTOR}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> "ThreadPanelOptionsFlow":
        return ThreadPanelOptionsFlow()


class ThreadPanelOptionsFlow(config_entries.OptionsFlow):
    """Edit an already-configured panel's manifest in place.

    On successful submit, updates the entry's data and triggers a reload
    so the forwarder picks up the new entities. panel_id must stay the
    same — it's the entry's unique_id anchor and changing it mid-flight
    would corrupt HA's record of the device.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        current_yaml = self.config_entry.data.get(CONF_MANIFEST_YAML, "")
        current_panel_id = self.config_entry.data.get(CONF_PANEL_ID)

        if user_input is not None:
            yaml_text = user_input[CONF_MANIFEST_YAML]
            try:
                manifest = await self.hass.async_add_executor_job(
                    parse_manifest, yaml_text
                )
            except ManifestError as err:
                _LOGGER.error("Options manifest parse failed: %s", err)
                errors["base"] = "invalid_manifest"
            else:
                if manifest.panel_id != current_panel_id:
                    _LOGGER.error(
                        "Options submit tried to change panel_id %s → %s; refused",
                        current_panel_id,
                        manifest.panel_id,
                    )
                    errors["base"] = "panel_id_mismatch"
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={
                            CONF_MANIFEST_YAML: yaml_text,
                            CONF_PANEL_ID: manifest.panel_id,
                        },
                    )
                    await self.hass.config_entries.async_reload(
                        self.config_entry.entry_id
                    )
                    return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MANIFEST_YAML, default=current_yaml
                    ): YAML_SELECTOR,
                }
            ),
            errors=errors,
        )
