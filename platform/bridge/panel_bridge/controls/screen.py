"""Display power control via vcgencmd.

vcgencmd display_power {0|1} turns the HDMI output off/on. Good enough
for a pre-cage deployment; when the kiosk compositor lands we'll want to
revisit using DPMS/wlr-randr so the compositor cleans up cleanly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

VCGENCMD = "/usr/bin/vcgencmd"


async def _read_display_power() -> bool | None:
    """Return True if HDMI is on, False if off, None on error."""
    try:
        proc = await asyncio.create_subprocess_exec(
            VCGENCMD, "display_power",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except OSError as e:
        log.warning("screen: vcgencmd not executable: %s", e)
        return None
    if proc.returncode != 0:
        log.warning("screen: vcgencmd read failed: %s", err.decode(errors="replace"))
        return None
    # Output is "display_power=1" or "display_power=0"
    text = out.decode().strip()
    _, _, value = text.partition("=")
    return value.strip() == "1"


async def _set_display_power(on: bool) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            VCGENCMD, "display_power", "1" if on else "0",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
    except OSError as e:
        log.warning("screen: vcgencmd not executable: %s", e)
        return False
    if proc.returncode != 0:
        log.warning("screen: vcgencmd set failed: %s", err.decode(errors="replace"))
        return False
    return True


async def apply_screen_on(bridge, payload: dict[str, Any]) -> None:
    value = payload.get("value")
    if not isinstance(value, bool):
        log.warning("screen_on: expected bool, got %r", value)
        return
    ok = await _set_display_power(value)
    if not ok:
        return
    await bridge.send_panel_state("screen_on", {"value": value})


async def emit_initial(bridge) -> None:
    value = await _read_display_power()
    if value is None:
        return
    await bridge.send_panel_state("screen_on", {"value": value})
