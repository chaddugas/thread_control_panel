"""Structured-event logging for panel_bridge.

Goal: make high-signal moments (WiFi state changes, OTA phase
transitions, MQTT reconnects, nmcli timeouts) easy to filter out of
journal logs for post-mortem debugging.

Convention: every event log line has the form

    event=<name> k1=v1 k2=v2 ...

emitted via the standard stdlib logging module so journald captures it
via stdout (panel-bridge runs as a systemd service). No new dependency
on python-systemd; we trade clean structured fields for zero-deps and
greppability.

Query examples:

    journalctl -u panel-bridge.service --grep 'event=wifi_state_change'
    journalctl -u panel-bridge.service --grep 'event=wifi_state_change' \\
        --output=json | jq '.MESSAGE'

Defined event names (extend as call sites need new categories):

    bridge_started      — bridge boot marker (version, etc.)
    wifi_state_change   — WiFi connection state transition
    wifi_action         — user-driven WiFi action (toggle, scan, connect)
    nmcli_timeout       — _run_nmcli hit its asyncio.wait_for timeout
    mqtt_reconnect      — bridge re-established MQTT connection
    ota_phase           — panel-update.sh phase boundary

Field-name convention: Python keywords (`from`, `class`, etc.) can be
passed with a trailing underscore — `log_event(log, ..., from_=old)` —
which gets stripped before formatting so the journal line reads
`from=...` cleanly.
"""

from __future__ import annotations

import logging
from typing import Any


def log_event(logger: logging.Logger, name: str, **fields: Any) -> None:
    """Emit a structured event line through the caller's logger.

    The caller's logger name is preserved in the journal entry so the
    source module is visible — pass `log` from the calling module
    rather than a centralized one.

    Logged at INFO level. Use `log_event_debug` for high-frequency
    events that shouldn't be in the default journal stream.
    """
    logger.info(_format(name, fields))


def log_event_debug(logger: logging.Logger, name: str, **fields: Any) -> None:
    """Same as `log_event` but at DEBUG level."""
    logger.debug(_format(name, fields))


def _format(name: str, fields: dict[str, Any]) -> str:
    parts = [f"event={name}"]
    for k, v in fields.items():
        parts.append(f"{_normalize_key(k)}={_format_value(v)}")
    return " ".join(parts)


def _normalize_key(k: str) -> str:
    # Trailing underscore convention for Python-keyword field names
    # (`from_`, `class_`, etc.). Strip exactly one trailing `_`,
    # leaving dunder-style names alone.
    if k.endswith("_") and not k.endswith("__"):
        return k[:-1]
    return k


def _format_value(v: Any) -> str:
    if v is None:
        return "<none>"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if not s:
        return '""'
    if any(c in s for c in ' ="'):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s
