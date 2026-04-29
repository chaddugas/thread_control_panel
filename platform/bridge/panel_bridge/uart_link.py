"""Async UART reader/writer. Parses incoming '\\n'-terminated JSON lines
from the C6 and emits dicts via a callback. Outgoing messages are written
as JSON lines back to the same port.

Also exposes an `ota_session()` context manager that the OTA driver uses
to drive the wire protocol — pauses normal `ota_*` message routing and
exposes raw write + baud-switch primitives the rest of the bridge doesn't
need."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import AsyncIterator, Awaitable, Callable

import serial
import serial_asyncio

log = logging.getLogger(__name__)

OnMessage = Callable[[dict], Awaitable[None]]
OnLinkUp = Callable[[], Awaitable[None]]


class UartLink:
    def __init__(
        self,
        port: str,
        baud: int,
        on_message: OnMessage,
        on_link_up: OnLinkUp | None = None,
    ) -> None:
        self._port = port
        self._baud = baud
        self._on_message = on_message
        # Fired after each successful UART open. Used by the bridge to
        # send a `cmd/resync` to the integration so the kiosk catches up
        # on retained state that may have been lost during the boot-time
        # race (Pi UART not ready when C6 first subscribed to MQTT).
        self._on_link_up = on_link_up
        self._writer: asyncio.StreamWriter | None = None
        # When non-None, incoming `ota_*` messages get routed to this
        # queue instead of the normal on_message callback. Set by an
        # active OtaSession; cleared on session exit.
        self._ota_queue: asyncio.Queue[dict] | None = None

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
            if self._on_link_up is not None:
                try:
                    await self._on_link_up()
                except Exception:
                    log.exception("on_link_up handler raised")
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
            # Route ota_* types to the active OTA session if any. Other
            # messages (sensor, panel_state, entity_state, etc.) keep
            # flowing to the normal handler — UI clients still get them.
            mtype = msg.get("type")
            if (
                self._ota_queue is not None
                and isinstance(mtype, str)
                and mtype.startswith("ota_")
            ):
                await self._ota_queue.put(msg)
                continue
            try:
                await self._on_message(msg)
            except Exception:
                log.exception("on_message handler raised")

    async def send(self, msg: dict) -> bool:
        """Encode msg as a JSON line and write to UART. Returns False if the
        link is currently down (caller can decide to drop or queue).

        A leading newline is prepended to every send. Reason: the Pi's UART
        line carries noise during early boot (kernel BREAK, possible early
        console output) before any reader is attached. The C6's rx_task
        accumulates those bytes into its line buffer because nothing
        terminates them with `\\n`. The first byte we write that ends with
        `\\n` would otherwise dispatch the accumulated garbage *together*
        with our valid message, and the C6's substring match would fail
        on the garbled prefix. Prepending `\\n` flushes the boot junk first
        (dispatched as a no-op since the C6 ignores empty lines), then our
        real content lands in a clean buffer. Cheap (one byte) and bombproof.
        """
        if self._writer is None:
            return False
        # While an OTA session has the link, suppress any non-ota_* writes.
        # During the raw transfer phase the C6 is interpreting incoming
        # bytes as firmware payload — a stray call_service line would be
        # written straight into the OTA partition and the sha256 would
        # mismatch. ota_* envelopes (ota_begin) are still allowed because
        # the OTA driver itself uses this path.
        mtype = msg.get("type", "")
        if self._ota_queue is not None and not (
            isinstance(mtype, str) and mtype.startswith("ota_")
        ):
            log.debug("UART send suppressed during OTA: type=%s", mtype)
            return False
        line = ("\n" + json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self._writer.write(line)
            await self._writer.drain()
        except (OSError, ConnectionResetError) as e:
            log.warning("UART write error: %s", e)
            return False
        return True

    # ----- OTA primitives -----

    async def write_raw(self, data: bytes) -> None:
        """Write raw bytes (no framing, no leading newline). Used during
        OTA after raw mode + high baud has been negotiated. Raises if the
        link is down — OTA can't recover from that mid-transfer."""
        if self._writer is None:
            raise RuntimeError("UART link down")
        self._writer.write(data)
        await self._writer.drain()

    async def wait_tx_done(self) -> None:
        """Block until ALL queued TX bytes have actually been transmitted
        on the wire — not just flushed from the asyncio buffer to the OS
        buffer. drain() only does the latter; without this, switching baud
        right after writing raw bytes causes the OS-buffered bytes (which
        can be several KB) to be transmitted at the NEW baud, garbling them
        on the receiver. Uses pyserial's serial.flush() (which calls
        tcdrain under the hood) on a worker thread so the event loop
        keeps running."""
        if self._writer is None:
            return
        serial_obj = self._writer.transport.serial
        await asyncio.to_thread(serial_obj.flush)

    def set_baud(self, baud: int) -> None:
        """Reconfigure the serial port's baud rate at runtime. Used during
        OTA to switch between steady-state 115200 and the OTA transfer's
        921600. Both peers must change in lockstep — there's no in-band
        handshake once one side has switched."""
        if self._writer is None:
            raise RuntimeError("UART link down")
        # serial_asyncio's writer.transport.serial is the underlying
        # pyserial Serial object; setting .baudrate reconfigures live.
        self._writer.transport.serial.baudrate = baud
        self._baud = baud
        log.info("UART baud → %d", baud)

    @contextlib.asynccontextmanager
    async def ota_session(self) -> AsyncIterator["OtaSession"]:
        """Acquire the link for an OTA. Routes incoming `ota_*` messages
        into the session's queue; other messages keep flowing through the
        normal handler so UI clients still see sensor / state updates.
        Idempotent guard: only one session at a time."""
        if self._ota_queue is not None:
            raise RuntimeError("OTA session already active")
        queue: asyncio.Queue[dict] = asyncio.Queue()
        self._ota_queue = queue
        try:
            yield OtaSession(self, queue)
        finally:
            self._ota_queue = None


class OtaSession:
    """Thin wrapper around UartLink for the OTA driver. Hides the queue
    and exposes a recv_json that filters by expected message type."""

    def __init__(self, link: "UartLink", queue: asyncio.Queue[dict]) -> None:
        self._link = link
        self._queue = queue

    async def send_json(self, msg: dict) -> bool:
        return await self._link.send(msg)

    async def recv_json(self, expected_type: str, timeout: float) -> dict:
        """Wait for an ota_* message of the given type. Other ota_* types
        are logged and skipped (shouldn't happen; defensive). Raises
        asyncio.TimeoutError on timeout."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise asyncio.TimeoutError(f"timeout waiting for {expected_type}")
            msg = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            if msg.get("type") == expected_type:
                return msg
            log.warning("OTA: ignored unexpected message: %s", msg)

    async def write_raw(self, data: bytes) -> None:
        await self._link.write_raw(data)

    async def wait_tx_done(self) -> None:
        await self._link.wait_tx_done()

    def set_baud(self, baud: int) -> None:
        self._link.set_baud(baud)
