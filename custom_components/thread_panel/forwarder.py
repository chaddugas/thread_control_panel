"""Generic per-entity forwarder between HA and a thread_panel device."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    PAYLOAD_OFFLINE,
    PAYLOAD_ONLINE,
    STORAGE_KEY_FMT,
    STORAGE_VERSION,
    TOPIC_AVAILABILITY,
    TOPIC_CALL_SERVICE,
    TOPIC_ENTITY_STATE,
    TOPIC_ROSTER,
)
from .manifest_loader import EntityDecl, PanelManifest

_LOGGER = logging.getLogger(__name__)


class PanelForwarder:
    """One forwarder per configured panel."""

    def __init__(self, hass: HomeAssistant, manifest: PanelManifest) -> None:
        self.hass = hass
        self.manifest = manifest
        self.panel_id = manifest.panel_id
        self._entities_by_id: dict[str, EntityDecl] = {
            e.entity_id: e for e in manifest.entities
        }
        self._unsubs: list[Any] = []
        self._store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_FMT.format(panel_id=self.panel_id)
        )

    def _t_availability(self) -> str:
        return TOPIC_AVAILABILITY.format(panel_id=self.panel_id)

    def _t_roster(self) -> str:
        return TOPIC_ROSTER.format(panel_id=self.panel_id)

    def _t_entity(self, entity_id: str) -> str:
        return TOPIC_ENTITY_STATE.format(panel_id=self.panel_id, entity_id=entity_id)

    def _t_call_service(self) -> str:
        return TOPIC_CALL_SERVICE.format(panel_id=self.panel_id)

    async def async_start(self) -> None:
        # Start offline; flip to online only after initial state is fully published.
        await self._publish_availability(PAYLOAD_OFFLINE)

        await self._clear_stale_retained()

        self._unsubs.append(
            async_track_state_change_event(
                self.hass,
                [e.entity_id for e in self.manifest.entities],
                self._handle_state_event,
            )
        )

        for decl in self.manifest.entities:
            state = self.hass.states.get(decl.entity_id)
            if state is None:
                _LOGGER.warning(
                    "Panel %s: entity %s not found in HA; publishing 'unknown'",
                    self.panel_id,
                    decl.entity_id,
                )
            await self._publish_entity_snapshot(decl.entity_id, state)

        await self._publish_roster()

        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass, self._t_call_service(), self._handle_call_service
            )
        )

        await self._store.async_save(
            [self._t_entity(e.entity_id) for e in self.manifest.entities]
        )

        await self._publish_availability(PAYLOAD_ONLINE)
        _LOGGER.info(
            "Panel %s: forwarder online (%d entities)",
            self.panel_id,
            len(self.manifest.entities),
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._publish_availability(PAYLOAD_OFFLINE)
        _LOGGER.info("Panel %s: forwarder offline", self.panel_id)

    async def _publish_availability(self, value: str) -> None:
        await mqtt.async_publish(self.hass, self._t_availability(), value, retain=True)

    async def _publish_roster(self) -> None:
        entries = []
        for decl in self.manifest.entities:
            state = self.hass.states.get(decl.entity_id)
            entries.append(
                {
                    "entity_id": decl.entity_id,
                    "friendly_name": (
                        state.attributes.get("friendly_name") if state else None
                    ),
                }
            )
        await mqtt.async_publish(
            self.hass,
            self._t_roster(),
            json.dumps({"entities": entries}, separators=(",", ":")),
            retain=True,
        )

    async def _publish_entity_snapshot(
        self, entity_id: str, state: State | None
    ) -> None:
        decl = self._entities_by_id.get(entity_id)
        if decl is None:
            return
        if state is None:
            payload: dict[str, Any] = {"state": "unknown", "attributes": {}}
        else:
            if decl.attributes is None:
                attrs = dict(state.attributes)
            else:
                attrs = {
                    k: state.attributes[k]
                    for k in decl.attributes
                    if k in state.attributes
                }
            payload = {"state": state.state, "attributes": attrs}
        await mqtt.async_publish(
            self.hass,
            self._t_entity(entity_id),
            json.dumps(payload, separators=(",", ":"), default=str),
            retain=True,
        )

    async def _clear_stale_retained(self) -> None:
        """Clear retained state/entity/* topics we published last run but don't declare now."""
        previous: list[str] | None = await self._store.async_load()
        if not previous:
            return
        current = {self._t_entity(e.entity_id) for e in self.manifest.entities}
        stale = [t for t in previous if t not in current]
        for topic in stale:
            _LOGGER.info("Panel %s: clearing stale retained topic %s", self.panel_id, topic)
            await mqtt.async_publish(self.hass, topic, "", retain=True)

    @callback
    def _handle_state_event(self, event: Event) -> None:
        entity_id: str = event.data["entity_id"]
        decl = self._entities_by_id.get(entity_id)
        if decl is None:
            return
        old: State | None = event.data.get("old_state")
        new: State | None = event.data.get("new_state")
        if not self._changed(decl, old, new):
            return
        self.hass.async_create_task(self._publish_entity_snapshot(entity_id, new))

    @staticmethod
    def _changed(decl: EntityDecl, old: State | None, new: State | None) -> bool:
        if old is None or new is None:
            return True
        if old.state != new.state:
            return True
        if decl.attributes is None:
            # Forward-all — any attribute change triggers a publish.
            return old.attributes != new.attributes
        return any(
            old.attributes.get(a) != new.attributes.get(a) for a in decl.attributes
        )

    @callback
    def _handle_call_service(self, msg) -> None:
        try:
            payload = json.loads(msg.payload)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Panel %s: call_service payload is not JSON: %r",
                self.panel_id,
                msg.payload,
            )
            return

        entity_id = payload.get("entity_id")
        action = payload.get("action")
        data = payload.get("data") or {}

        if not isinstance(entity_id, str) or entity_id not in self._entities_by_id:
            _LOGGER.warning(
                "Panel %s: rejecting call_service for %r (not in manifest)",
                self.panel_id,
                entity_id,
            )
            return
        if not isinstance(action, str) or "." not in action:
            _LOGGER.warning("Panel %s: invalid action %r", self.panel_id, action)
            return
        if not isinstance(data, dict):
            _LOGGER.warning("Panel %s: data must be an object, got %r", self.panel_id, data)
            return

        domain, service = action.split(".", 1)
        service_data = {**data, "entity_id": entity_id}
        self.hass.async_create_task(
            self.hass.services.async_call(
                domain, service, service_data, blocking=False
            )
        )
