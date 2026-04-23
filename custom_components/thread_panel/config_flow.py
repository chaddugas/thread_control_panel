"""Config flow for thread_panel: paste the panel manifest YAML."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_MANIFEST_YAML, CONF_PANEL_ID, DOMAIN
from .manifest_loader import ManifestError, parse_manifest

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_MANIFEST_YAML): TextSelector(
            TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
        )
    }
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
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
