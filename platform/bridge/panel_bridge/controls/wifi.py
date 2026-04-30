"""Wi-Fi radio control via nmcli.

`nmcli radio wifi on|off` toggles the radio. Reads don't need privilege
but WRITES require PolicyKit authorization — on headless Trixie there's
no polkit agent, so we go through sudo instead. Needs a sudoers entry
(see panel-bridge sudoers doc in reboot.py).
"""

from __future__ import annotations

import logging
from typing import Any

from .nmcli_util import run_nmcli

log = logging.getLogger(__name__)


async def _read_wifi_enabled() -> bool | None:
    rc, out, err = await run_nmcli("-t", "radio", "wifi")
    if rc != 0:
        log.warning("wifi: nmcli read failed (rc=%d): %s", rc, err.strip())
        return None
    return out.strip() == "enabled"


async def _set_wifi_enabled(on: bool) -> bool:
    rc, _, err = await run_nmcli(
        "radio", "wifi", "on" if on else "off", sudo=True
    )
    if rc != 0:
        log.warning(
            "wifi: sudo nmcli failed (rc=%d, is passwordless sudo configured?): %s",
            rc, err.strip(),
        )
        return False
    return True


async def apply_wifi_enabled(bridge, payload: dict[str, Any]) -> None:
    value = payload.get("value")
    if not isinstance(value, bool):
        log.warning("wifi_enabled: expected bool, got %r", value)
        return
    # Attempt the change. Whether it succeeds or not, we read the actual
    # state back below — so a failed action naturally reverts HA's
    # optimistic update on the next round trip.
    await _set_wifi_enabled(value)
    await emit_initial(bridge)


async def emit_initial(bridge) -> None:
    value = await _read_wifi_enabled()
    if value is None:
        return
    await bridge.send_panel_state("wifi_enabled", {"value": value})
