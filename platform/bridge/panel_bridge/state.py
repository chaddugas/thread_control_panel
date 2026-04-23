"""In-memory cache of the latest message per (type, name) key.

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

    @staticmethod
    def _key(msg: dict) -> str | None:
        t = msg.get("type")
        if not t:
            return None
        name = msg.get("name")
        return f"{t}:{name}" if name else t
