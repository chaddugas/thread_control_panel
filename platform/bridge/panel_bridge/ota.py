"""OTA driver: streams a firmware bin to the C6 over the existing UART link.

Wire protocol mirrors what panel_ota_uart on the C6 implements:

    Pi → C6: {"type":"ota_begin","size":N,"sha256":"..."}     [line, 115200]
    C6 → Pi: {"type":"ota_ready"}                              [line, 115200]
    [both → 921600, C6 enters raw pass-through]
    Pi → C6: <exactly N raw bytes>
    [after N bytes, both → 115200 + line]
    C6 → Pi: {"type":"ota_result","status":"ok|error","detail":"..."}
    [on success, C6 reboots into the new partition]

Progress + status events are broadcast over WS so panel-flash (and any
other connected client) can show progress.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable

from .uart_link import UartLink

log = logging.getLogger(__name__)

OTA_BAUD_STEADY = 115200
OTA_BAUD_TRANSFER = 921600

# 4 KB chunks align with the C6 OTA partition's flash sector size and
# work nicely with the C6-side stream buffer drain loop.
WRITE_CHUNK_BYTES = 4096
# Pacing: sleep this much after each chunk write so the Pi doesn't outrun
# the C6's flash write throughput. ESP32-C6 esp_ota_write per 4 KB sector
# is normally 30-50 ms but spikes higher during sector erases. Pi sleep
# overlaps with the 921600-baud transmit (~45 ms for 4 KB) since the OS
# UART buffers the bytes, so effective per-chunk time = max(transmit, sleep).
# 80 ms paces effective throughput to ~50 KB/s — leaves the C6 with ~30 ms
# of headroom per chunk to absorb occasional slow flash writes without
# silently dropping bytes at its ESP-IDF UART RX ring (which doesn't log
# overflow warnings the way our stream buffer does).
INTER_CHUNK_PACING_SEC = 0.08
# How often to broadcast a progress envelope during the raw transfer.
PROGRESS_INTERVAL_SEC = 0.5

READY_TIMEOUT_SEC = 10.0
RESULT_TIMEOUT_SEC = 30.0

# Type for the broadcast hook — bridge passes ws.broadcast bound, but we
# stay decoupled from WsServer so this module stays testable in isolation.
Broadcast = Callable[[dict], Awaitable[None]]


async def run_ota(uart: UartLink, broadcast: Broadcast, bin_path: str) -> bool:
    """Execute the OTA wire protocol against the C6. Returns True on
    success (C6 reported ok and is rebooting), False on any failure.

    Emits ota_status / ota_progress envelopes via `broadcast` throughout.
    """
    path = Path(bin_path).expanduser()
    if not path.is_file():
        await _emit_status(broadcast, "failed", f"file not found: {path}")
        return False

    try:
        data = path.read_bytes()
    except OSError as e:
        await _emit_status(broadcast, "failed", f"read failed: {e}")
        return False

    size = len(data)
    if size == 0:
        await _emit_status(broadcast, "failed", "file is empty")
        return False

    sha256 = hashlib.sha256(data).hexdigest()

    log.info("OTA starting: %s (%d bytes, sha256=%s)", path, size, sha256)
    await _emit_status(
        broadcast, "starting", f"{path.name} ({size} bytes, sha256={sha256[:12]}…)"
    )

    try:
        async with uart.ota_session() as session:
            # 1. Send ota_begin and wait for the C6 to ack with ota_ready.
            await _emit_status(broadcast, "awaiting_ack", None)
            ok = await session.send_json(
                {
                    "type": "ota_begin",
                    "size": size,
                    "sha256": sha256,
                }
            )
            if not ok:
                await _emit_status(broadcast, "failed", "UART send failed")
                return False

            try:
                await session.recv_json("ota_ready", timeout=READY_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                await _emit_status(
                    broadcast,
                    "failed",
                    f"no ota_ready from C6 within {READY_TIMEOUT_SEC:.0f}s",
                )
                return False

            # 2. Switch baud, give the C6 a beat to also switch.
            session.set_baud(OTA_BAUD_TRANSFER)
            await asyncio.sleep(0.1)

            # 3. Stream raw bytes. We always switch back, even on
            #    exception — otherwise the next normal UART traffic
            #    would go out at 921600 to a 115200 listener.
            await _emit_status(broadcast, "transferring", f"{size} bytes")
            start = time.monotonic()
            sent = 0
            last_progress = start
            try:
                for offset in range(0, size, WRITE_CHUNK_BYTES):
                    chunk = data[offset : offset + WRITE_CHUNK_BYTES]
                    await session.write_raw(chunk)
                    sent += len(chunk)
                    # Pace so the C6's drain task can keep up with flash
                    # writes — without this, stream buffer overflows and
                    # bytes get dropped → drain loop rx timeout.
                    await asyncio.sleep(INTER_CHUNK_PACING_SEC)
                    now = time.monotonic()
                    if now - last_progress >= PROGRESS_INTERVAL_SEC:
                        await _emit_progress(broadcast, sent, size, now - start)
                        last_progress = now
            except Exception as e:
                log.exception("raw transfer failed")
                # Switch back before reporting so the link is sane again.
                try:
                    await session.wait_tx_done()
                    session.set_baud(OTA_BAUD_STEADY)
                except Exception:
                    pass
                await _emit_status(broadcast, "failed", f"transfer error: {e}")
                return False
            finally:
                # Critical: wait for ALL queued bytes to physically transmit
                # at 921600 BEFORE switching baud back. drain() only flushes
                # the asyncio buffer to the OS — kernel buffer (several KB)
                # would otherwise drain at the new (115200) baud, garbling
                # the last bytes the C6 reads as firmware payload and
                # causing a sha256 mismatch.
                #
                # set_baud is called in its own try so wait_tx_done failing
                # never leaves the Pi stuck at 921600 — that wedges the link
                # because the C6 (at 115200) reads everything as garbage and
                # we lose ota_result + all subsequent traffic until reboot.
                try:
                    await asyncio.wait_for(session.wait_tx_done(), timeout=5.0)
                    await asyncio.sleep(0.02)  # HW FIFO padding
                except (asyncio.TimeoutError, Exception):
                    log.exception("OTA: wait_tx_done failed (continuing)")
                try:
                    session.set_baud(OTA_BAUD_STEADY)
                except Exception:
                    log.exception("OTA: set_baud back to steady failed")

            elapsed = time.monotonic() - start
            await _emit_progress(broadcast, sent, size, elapsed)

            # 4. Wait for the C6's final ota_result envelope.
            await _emit_status(broadcast, "awaiting_result", None)
            try:
                result = await session.recv_json(
                    "ota_result", timeout=RESULT_TIMEOUT_SEC
                )
            except asyncio.TimeoutError:
                await _emit_status(
                    broadcast,
                    "failed",
                    f"no ota_result from C6 within {RESULT_TIMEOUT_SEC:.0f}s",
                )
                return False

            status = result.get("status")
            if status == "ok":
                await _emit_status(
                    broadcast,
                    "complete",
                    f"transferred in {elapsed:.1f}s ({size / elapsed / 1024:.1f} KB/s); C6 rebooting",
                )
                return True
            else:
                detail = result.get("detail", "(no detail)")
                await _emit_status(broadcast, "failed", f"C6 error: {detail}")
                return False
    except RuntimeError as e:
        # ota_session raises if a session is already active.
        await _emit_status(broadcast, "failed", str(e))
        return False
    except Exception as e:
        log.exception("OTA driver crashed")
        await _emit_status(broadcast, "failed", f"driver error: {e}")
        return False


async def _emit_status(broadcast: Broadcast, phase: str, detail: str | None) -> None:
    msg: dict = {"type": "ota_status", "phase": phase}
    if detail is not None:
        msg["detail"] = detail
    await broadcast(msg)


async def _emit_progress(
    broadcast: Broadcast, sent: int, total: int, elapsed: float
) -> None:
    rate = sent / elapsed if elapsed > 0 else 0
    await broadcast(
        {
            "type": "ota_progress",
            "bytes": sent,
            "total": total,
            "elapsed": round(elapsed, 2),
            "rate_bps": round(rate),
        }
    )
