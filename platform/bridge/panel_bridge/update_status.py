"""Tail /opt/panel/update.status and republish new lines as
state/update_status panel_state envelopes.

panel-update.sh appends one JSON line per status phase. We tail those
into the existing panel_state pipeline so HA's update.panel_firmware
entity (Phase 3b) sees progress without needing direct access to the Pi
filesystem.

Tail behavior:
- On first sight of the file, seek to END (don't republish history from a
  previous update — those phases are stale).
- On in-place truncation+rewrite (panel-update.sh does `: > $STATUS_FILE`
  at the start of each run), reset pos to 0 and re-read from the start.
- On inode change (file replaced), restart from beginning.
- Polls every 0.5 s. Tracking inotify-style would be sharper but adds a
  dependency for marginal benefit on a low-event-rate file.

Truncation detection:
The naive `st_size < pos` check misses the case where a new run's content
surpasses the previous run's size between polls. Example: previous run
errored early and only wrote ~80 bytes; new run truncates to 0 and writes
~150 bytes (e.g. "starting" + "enabling_wifi") before our poll fires;
st_size (150) > pos (80), so the size-only check passes and we read from
byte 80 of the new content — landing mid-line and producing a partial
that fails JSON parse. We additionally fingerprint the first 80 bytes of
the file each poll; if they change while the inode is stable, an in-place
truncation+rewrite happened and we reset pos to 0.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

STATUS_FILE = Path("/opt/panel/update.status")
POLL_INTERVAL_SEC = 0.5
FINGERPRINT_BYTES = 80


async def run(bridge: Any) -> None:
    """Tail loop. Run forever as a background task; cancel to stop."""
    pos: int | None = None
    last_inode: int | None = None
    last_fingerprint: bytes | None = None

    while True:
        try:
            if not STATUS_FILE.exists():
                pos = None
                last_inode = None
                last_fingerprint = None
                await asyncio.sleep(POLL_INTERVAL_SEC)
                continue

            stat = STATUS_FILE.stat()
            new_data = ""

            with STATUS_FILE.open("rb") as f:
                fingerprint = f.read(FINGERPRINT_BYTES)

                if pos is None:
                    # First time seeing this file — start from end so we
                    # don't republish old completed-update history.
                    pos = stat.st_size
                    last_inode = stat.st_ino
                    last_fingerprint = fingerprint
                else:
                    # Detect file replacement (new inode) or in-place
                    # truncation+rewrite (same inode, different first
                    # bytes). publish_status appends one full line per
                    # call, so the first line is stable until truncation
                    # — comparing fingerprints catches the case where new
                    # content surpasses old size before we polled, which
                    # bypasses the size < pos check.
                    if (
                        stat.st_ino != last_inode
                        or fingerprint != last_fingerprint
                    ):
                        pos = 0
                        last_inode = stat.st_ino
                        last_fingerprint = fingerprint
                    elif stat.st_size < pos:
                        # Defensive: truncation without subsequent writes.
                        pos = 0

                    if stat.st_size > pos:
                        f.seek(pos)
                        new_data = f.read().decode("utf-8", errors="replace")
                        pos = f.tell()

            for line in new_data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("update.status non-JSON line: %r", line)
                    continue
                if not isinstance(msg, dict):
                    continue
                # send_panel_state spreads msg into the envelope; the
                # C6 receives and publishes to state/update_status.
                await bridge.send_panel_state("update_status", msg)
        except Exception:
            log.exception("update_status tail loop error")

        await asyncio.sleep(POLL_INTERVAL_SEC)
