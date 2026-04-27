"""Panel-itself control owners.

Each control module owns one piece of Pi-side state (display power, wifi
radio, reboot trigger, etc.), exposes:

  - an `async def apply(bridge, payload)` coroutine that performs the
    action described by a `panel_set` or `panel_cmd` UART message and
    publishes the resulting `panel_state` back so the C6 can retain it
    on the corresponding MQTT topic.
  - an `async def emit_initial(bridge)` coroutine that reports current
    state to the C6 at bridge startup, so HA sees a fresh value before
    the user touches anything.

The registry here maps names (matching `set/<name>` / `cmd/<name>`
MQTT topics) to handlers. `dispatch_set` / `dispatch_cmd` route an
incoming UART message to the right handler.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from . import reboot, screen, wifi, wifi_manage

log = logging.getLogger(__name__)

# bridge is typed loosely as Any here to avoid a cyclic import — at
# runtime it's a PanelBridge-like object providing send_panel_state().
ApplyFn = Callable[[Any, dict], Awaitable[None]]
EmitFn = Callable[[Any], Awaitable[None]]


# name → (apply, emit_initial) — emit_initial may be None for command-only
# controls like reboot_pi that have no state to report.
SET_HANDLERS: dict[str, tuple[ApplyFn, EmitFn | None]] = {
    "screen_on": (screen.apply_screen_on, screen.emit_initial),
    "wifi_enabled": (wifi.apply_wifi_enabled, wifi.emit_initial),
}

CMD_HANDLERS: dict[str, ApplyFn] = {
    "reboot_pi": reboot.apply_reboot_pi,
    "wifi_connect": wifi_manage.apply_wifi_connect,
    "wifi_scan": wifi_manage.apply_wifi_scan,
}

# Modules that need a one-shot kick at startup but don't fit the
# (set/state) pairing — typically because they own command-only topics
# plus a periodic background task.
EXTRA_EMITTERS: list[EmitFn] = [
    wifi_manage.emit_initial,
]


async def dispatch_set(bridge, name: str, payload: dict) -> None:
    handler = SET_HANDLERS.get(name)
    if handler is None:
        log.warning("panel_set: no handler for %r", name)
        return
    apply, _ = handler
    try:
        await apply(bridge, payload)
    except Exception:
        log.exception("panel_set %s failed", name)


async def dispatch_cmd(bridge, name: str, payload: dict) -> None:
    handler = CMD_HANDLERS.get(name)
    if handler is None:
        log.warning("panel_cmd: no handler for %r", name)
        return
    try:
        await handler(bridge, payload)
    except Exception:
        log.exception("panel_cmd %s failed", name)


async def emit_all_initial(bridge) -> None:
    """Report current state of every stateful control. Called at bridge
    startup and on UART reconnect so HA sees fresh panel_state."""
    for name, (_, emit) in SET_HANDLERS.items():
        if emit is None:
            continue
        try:
            await emit(bridge)
        except Exception:
            log.exception("emit_initial for %s failed", name)
    for emit in EXTRA_EMITTERS:
        try:
            await emit(bridge)
        except Exception:
            log.exception("emit_initial for %s failed", emit.__name__)
