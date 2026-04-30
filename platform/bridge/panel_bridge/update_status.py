"""Tail /opt/panel/update.status and republish new lines as
state/update_status panel_state envelopes.

panel-update.sh appends one JSON line per status phase. We tail those
into the existing panel_state pipeline so HA's update.panel_firmware
entity (Phase 3b) sees progress without needing direct access to the Pi
filesystem.

Tail behavior:
- On first sight of the file, seek to END (don't republish history from a
  previous update — those phases are stale).
- On truncation (panel-update.sh does `: > $STATUS_FILE` at the start of
  each run), restart from beginning.
- On inode change (file replaced), restart from beginning.
- Polls every 0.5 s. Tracking inotify-style would be sharper but adds a
  dependency for marginal benefit on a low-event-rate file.
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


async def run(bridge: Any) -> None:
    """Tail loop. Run forever as a background task; cancel to stop."""
    pos: int | None = None
    last_inode: int | None = None

    while True:
        try:
            if not STATUS_FILE.exists():
                pos = None
                last_inode = None
                await asyncio.sleep(POLL_INTERVAL_SEC)
                continue

            stat = STATUS_FILE.stat()

            if pos is None:
                # First time seeing this file — start from end so we
                # don't replay old completed-update history.
                pos = stat.st_size
                last_inode = stat.st_ino
                await asyncio.sleep(POLL_INTERVAL_SEC)
                continue

            # File replaced (new inode)? Re-read from start.
            if stat.st_ino != last_inode:
                pos = 0
                last_inode = stat.st_ino

            # File truncated? Re-read from start.
            if stat.st_size < pos:
                pos = 0

            if stat.st_size > pos:
                with STATUS_FILE.open("r") as f:
                    f.seek(pos)
                    new_data = f.read()
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
