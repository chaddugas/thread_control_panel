"""Display power control via /sys/class/graphics/fb0/blank.

On modern Pi OS (Bookworm/Trixie with the KMS display driver), the old
`vcgencmd display_power` call succeeds silently but has no actual effect
— it was part of the firmware-driven DispmanX path that KMS replaces.

The closest userspace equivalent that works without a running compositor
is writing to fb0's blank sysfs attribute:
    0 = unblanked   4 = powerdown
The file is root-owned, so we go through sudo (see the sudoers entry in
reboot.py).

CAVEAT: whether this actually changes the visible state depends on the
attached display. Some panels honor FB blank and go dark; others keep
their backlight lit and just show "no signal." If it doesn't visually
blank the Waveshare, we'll revisit in step 16 when cage + wlr-randr
give us a proper Wayland-level display-power primitive.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

BLANK_PATH = "/sys/class/graphics/fb0/blank"
TEE = "/usr/bin/tee"


async def _read_blank() -> str | None:
    """Return the current blank state as a string ("0".."4"), or None if
    the file hasn't been written to yet (some kernels return empty until
    first write)."""
    try:
        with open(BLANK_PATH, "r") as f:
            value = f.read().strip()
    except OSError as e:
        log.warning("screen: cannot read %s: %s", BLANK_PATH, e)
        return None
    return value or None


async def _write_blank(value: int) -> bool:
    """Write value to the blank sysfs via sudo tee. Returns True on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", TEE, BLANK_PATH,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate(input=f"{value}\n".encode())
    except OSError as e:
        log.warning("screen: cannot invoke sudo tee: %s", e)
        return False
    if proc.returncode != 0:
        log.warning(
            "screen: sudo tee failed (is passwordless sudo configured?): %s",
            err.decode(errors="replace"),
        )
        return False
    return True


async def apply_screen_on(bridge, payload: dict[str, Any]) -> None:
    value = payload.get("value")
    if not isinstance(value, bool):
        log.warning("screen_on: expected bool, got %r", value)
        return
    # 0 = unblanked, 4 = powerdown (full off).
    ok = await _write_blank(0 if value else 4)
    if not ok:
        return
    await bridge.send_panel_state("screen_on", {"value": value})


async def emit_initial(bridge) -> None:
    raw = await _read_blank()
    if raw is None:
        # No state written yet — assume unblanked (boot default).
        await bridge.send_panel_state("screen_on", {"value": True})
        return
    try:
        value = int(raw) == 0
    except ValueError:
        log.warning("screen: unparseable blank value %r", raw)
        return
    await bridge.send_panel_state("screen_on", {"value": value})
