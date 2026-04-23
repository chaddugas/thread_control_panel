"""WebSocket server. On connect, replays the cached state to the new client
so the UI gets current values without round-tripping the C6. Broadcasts
incoming UART messages to every connected client. Forwards client messages
to a callback (which writes them to UART)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Iterable

import websockets

log = logging.getLogger(__name__)

SnapshotFn = Callable[[], Iterable[dict]]
OnClientMessage = Callable[[dict], Awaitable[None]]


class WsServer:
    def __init__(
        self,
        host: str,
        port: int,
        snapshot: SnapshotFn,
        on_client_message: OnClientMessage,
    ) -> None:
        self._host = host
        self._port = port
        self._snapshot = snapshot
        self._on_client_message = on_client_message
        self._clients: set = set()
        # Held during snapshot replay AND broadcast so a new client can't be
        # registered between a broadcast firing and the snapshot completing,
        # which would otherwise let stale snapshot data overwrite a fresher
        # broadcast on the wire.
        self._broadcast_lock = asyncio.Lock()

    async def run(self) -> None:
        log.info("WS server listening on ws://%s:%d", self._host, self._port)
        async with websockets.serve(self._handle, self._host, self._port):
            await asyncio.Future()  # serve forever

    async def _handle(self, ws) -> None:
        peer = getattr(ws, "remote_address", None)
        async with self._broadcast_lock:
            for msg in self._snapshot():
                await ws.send(json.dumps(msg, separators=(",", ":")))
            self._clients.add(ws)
        log.info("client connected from %s (%d total)", peer, len(self._clients))

        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    log.debug("non-JSON from client: %r", raw)
                    continue
                if not isinstance(msg, dict):
                    continue
                try:
                    await self._on_client_message(msg)
                except Exception:
                    log.exception("client message handler raised")
        except websockets.ConnectionClosed:
            pass
        finally:
            async with self._broadcast_lock:
                self._clients.discard(ws)
            log.info("client disconnected from %s (%d total)", peer, len(self._clients))

    async def broadcast(self, msg: dict) -> None:
        """Send msg to every connected client. Safe to call concurrently."""
        async with self._broadcast_lock:
            if not self._clients:
                return
            payload = json.dumps(msg, separators=(",", ":"))
            websockets.broadcast(self._clients, payload)
