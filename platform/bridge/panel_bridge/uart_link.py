"""Async UART reader/writer. Parses incoming '\\n'-terminated JSON lines
from the C6 and emits dicts via a callback. Outgoing messages are written
as JSON lines back to the same port."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import serial
import serial_asyncio

log = logging.getLogger(__name__)

OnMessage = Callable[[dict], Awaitable[None]]


class UartLink:
    def __init__(self, port: str, baud: int, on_message: OnMessage) -> None:
        self._port = port
        self._baud = baud
        self._on_message = on_message
        self._writer: asyncio.StreamWriter | None = None

    async def run(self) -> None:
        """Connect and read forever. Reconnects on UART error after 1s backoff."""
        while True:
            try:
                reader, writer = await serial_asyncio.open_serial_connection(
                    url=self._port, baudrate=self._baud
                )
            except (OSError, serial.SerialException) as e:
                log.warning("UART open failed (%s): %s — retrying in 1s", self._port, e)
                await asyncio.sleep(1.0)
                continue

            self._writer = writer
            log.info("UART link up on %s @ %d", self._port, self._baud)
            try:
                await self._read_loop(reader)
            except (OSError, serial.SerialException) as e:
                log.warning("UART read error: %s", e)
            finally:
                self._writer = None
                writer.close()
            log.info("UART link down — reconnecting in 1s")
            await asyncio.sleep(1.0)

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        while True:
            line = await reader.readline()
            if not line:
                return  # EOF
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                log.debug("non-JSON line: %r", text)
                continue
            if not isinstance(msg, dict):
                log.debug("non-object JSON: %r", text)
                continue
            try:
                await self._on_message(msg)
            except Exception:
                log.exception("on_message handler raised")

    async def send(self, msg: dict) -> bool:
        """Encode msg as a JSON line and write to UART. Returns False if the
        link is currently down (caller can decide to drop or queue)."""
        if self._writer is None:
            return False
        line = (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self._writer.write(line)
            await self._writer.drain()
        except (OSError, ConnectionResetError) as e:
            log.warning("UART write error: %s", e)
            return False
        return True
