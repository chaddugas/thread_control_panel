"""Bridge entry point: `python -m panel_bridge`.

Wires the UART link, state cache, WebSocket server, and panel-itself
control owners into a single asyncio event loop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import controls
from .config import LOG_LEVEL, UART_BAUD, UART_PORT, WS_HOST, WS_PORT
from .state import StateCache
from .uart_link import UartLink
from .ws_server import WsServer

log = logging.getLogger("panel_bridge")


class PanelBridge:
    """Wrapper passed to control modules. Exposes the send primitive they
    need (publish a panel_state back to the C6 over UART) without dragging
    the whole module-global state in."""

    def __init__(self, uart: UartLink) -> None:
        self._uart = uart

    async def send_panel_state(self, name: str, payload: dict[str, Any]) -> None:
        """Emit a panel_state envelope over UART for the given control.
        The C6 peels the envelope and publishes payload to state/<name>
        retained on MQTT so HA sees current value."""
        msg = {"type": "panel_state", "name": name, **payload}
        ok = await self._uart.send(msg)
        if not ok:
            log.warning("panel_state %s dropped — UART link down: %s", name, payload)


async def main() -> None:
    cache = StateCache()

    uart: UartLink
    ws: WsServer
    bridge: PanelBridge

    async def on_uart_message(msg: dict) -> None:
        cache.update(msg)
        await ws.broadcast(msg)

        # Panel-itself controls: dispatch set/cmd envelopes that the C6
        # forwarded from MQTT. These do NOT go to the UI — they're
        # platform-owned controls the UI might also surface later.
        mtype = msg.get("type")
        name = msg.get("name")
        if isinstance(name, str):
            if mtype == "panel_set":
                await controls.dispatch_set(bridge, name, msg)
            elif mtype == "panel_cmd":
                await controls.dispatch_cmd(bridge, name, msg)

    async def on_client_message(msg: dict) -> None:
        if msg.get("type") == "call_service":
            ha_av = cache.ha_availability()
            if ha_av != "online":
                log.warning(
                    "call_service dropped — ha_availability=%s: %s", ha_av, msg
                )
                return
        ok = await uart.send(msg)
        if not ok:
            log.warning("client message dropped — UART link is down: %s", msg)

    async def on_uart_link_up() -> None:
        """Fired by UartLink each time it (re)opens the serial port.

        Asks the integration to republish every entity_state retained
        topic. This catches the boot-time race: the C6 boots faster
        than the Pi, subscribes to MQTT and receives all retained
        entity_state messages while the Pi UART driver isn't ready
        yet — so the bytes get dropped at the line and the kiosk
        starts blank. Without this resync, the kiosk only learns
        anything when HA next changes a state.

        Brief sleep first to let the C6 see the UART come back before
        we send anything (C6 has its own UART buffer; not strictly
        required but smooths out the cold-boot case).
        """
        await asyncio.sleep(2.0)
        ok = await uart.send({"type": "panel_cmd", "name": "resync"})
        if ok:
            log.info("Sent panel_cmd resync to C6 — kiosk should catch up shortly")
        else:
            log.warning("panel_cmd resync send failed — UART link not yet writable")

    uart = UartLink(UART_PORT, UART_BAUD, on_uart_message, on_link_up=on_uart_link_up)
    ws = WsServer(WS_HOST, WS_PORT, cache.snapshot, on_client_message)
    bridge = PanelBridge(uart)

    async def emit_initial_after_delay() -> None:
        """Give UART + C6 MQTT a chance to come up, then push current
        value of every stateful panel-itself control. If any send fails
        (UART down, C6 not on MQTT yet), that state just stays stale
        until the next bridge restart — rare enough to not matter."""
        await asyncio.sleep(3.0)
        await controls.emit_all_initial(bridge)

    log.info("Starting panel_bridge — UART %s @ %d, WS ws://%s:%d",
             UART_PORT, UART_BAUD, WS_HOST, WS_PORT)

    await asyncio.gather(
        uart.run(),
        ws.run(),
        emit_initial_after_delay(),
    )


def cli() -> None:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutdown requested")


if __name__ == "__main__":
    cli()
