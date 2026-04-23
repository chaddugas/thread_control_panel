"""Bridge entry point: `python -m panel_bridge`.

Wires the UART link, state cache, and WebSocket server into a single
asyncio event loop."""

from __future__ import annotations

import asyncio
import logging

from .config import LOG_LEVEL, UART_BAUD, UART_PORT, WS_HOST, WS_PORT
from .state import StateCache
from .uart_link import UartLink
from .ws_server import WsServer

log = logging.getLogger("panel_bridge")


async def main() -> None:
    cache = StateCache()

    # Forward declarations so the callbacks can reference each other.
    uart: UartLink
    ws: WsServer

    async def on_uart_message(msg: dict) -> None:
        cache.update(msg)
        await ws.broadcast(msg)

    async def on_client_message(msg: dict) -> None:
        ok = await uart.send(msg)
        if not ok:
            log.warning("client message dropped — UART link is down: %s", msg)

    uart = UartLink(UART_PORT, UART_BAUD, on_uart_message)
    ws = WsServer(WS_HOST, WS_PORT, cache.snapshot, on_client_message)

    log.info("Starting panel_bridge — UART %s @ %d, WS ws://%s:%d",
             UART_PORT, UART_BAUD, WS_HOST, WS_PORT)

    await asyncio.gather(uart.run(), ws.run())


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
