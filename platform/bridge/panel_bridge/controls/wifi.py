"""Wi-Fi radio control via nmcli.

`nmcli radio wifi on|off` toggles the radio. Reads don't need privilege
but WRITES require PolicyKit authorization — on headless Trixie there's
no polkit agent, so we go through sudo instead. Needs a sudoers entry
(see panel-bridge sudoers doc in reboot.py).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

NMCLI = "/usr/bin/nmcli"


async def _read_wifi_enabled() -> bool | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            NMCLI, "-t", "radio", "wifi",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    except OSError as e:
        log.warning("wifi: nmcli not executable: %s", e)
        return None
    if proc.returncode != 0:
        log.warning("wifi: nmcli read failed: %s", err.decode(errors="replace"))
        return None
    text = out.decode().strip()
    return text == "enabled"


async def _set_wifi_enabled(on: bool) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", NMCLI, "radio", "wifi", "on" if on else "off",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
    except OSError as e:
        log.warning("wifi: sudo/nmcli not executable: %s", e)
        return False
    if proc.returncode != 0:
        log.warning(
            "wifi: sudo nmcli failed (is passwordless sudo configured?): %s",
            err.decode(errors="replace"),
        )
        return False
    return True


async def apply_wifi_enabled(bridge, payload: dict[str, Any]) -> None:
    value = payload.get("value")
    if not isinstance(value, bool):
        log.warning("wifi_enabled: expected bool, got %r", value)
        return
    ok = await _set_wifi_enabled(value)
    if not ok:
        return
    await bridge.send_panel_state("wifi_enabled", {"value": value})


async def emit_initial(bridge) -> None:
    value = await _read_wifi_enabled()
    if value is None:
        return
    await bridge.send_panel_state("wifi_enabled", {"value": value})
