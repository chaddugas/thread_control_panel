"""In-memory cache of the latest message per typed key.

Keys are chosen per message type so multiple rows of the same type coexist
in the snapshot: sensors key by `type:name`, entity state by
`entity_state:entity_id`, singletons (roster, ha_availability) by `type`.

Source of truth lives on the C6 / Pi sensors / HA — the cache exists so a
fresh WebSocket client can see the current state immediately without
round-tripping the C6.
"""

from __future__ import annotations


class StateCache:
    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}

    def update(self, msg: dict) -> None:
        """Store a message in the cache, keyed by type[:name]."""
        key = self._key(msg)
        if key is not None:
            self._cache[key] = msg

    def snapshot(self) -> list[dict]:
        """Point-in-time copy of every cached message."""
        return list(self._cache.values())

    def ha_availability(self) -> str | None:
        """Latest value of the ha_availability signal, or None if we haven't
        seen one yet."""
        msg = self._cache.get("ha_availability")
        if not msg:
            return None
        v = msg.get("value")
        return v if isinstance(v, str) else None

    @staticmethod
    def _key(msg: dict) -> str | None:
        t = msg.get("type")
        if not t:
            return None
        # Per-type subkeys so multiple rows of the same type coexist in
        # the snapshot instead of overwriting each other.
        if t == "sensor":
            name = msg.get("name")
            return f"sensor:{name}" if name else None
        if t == "entity_state":
            eid = msg.get("entity_id")
            return f"entity_state:{eid}" if eid else None
        if t == "panel_state":
            # panel_state covers many distinct controls (wifi_ssids,
            # version, screen_on, etc.) — key by name so they coexist.
            # Without this, the version envelope gets overwritten by the
            # next panel_state and verify-c6-version.py can never find it.
            name = msg.get("name")
            return f"panel_state:{name}" if name else None
        # Singletons (roster, ha_availability, etc.) key by type alone.
        return t
