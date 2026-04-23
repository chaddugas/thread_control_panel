"""Pi reboot via sudo shutdown.

This module and the wifi/screen modules all require passwordless sudo
for specific commands. Add to /etc/sudoers.d/panel-bridge via
`sudo visudo -f /etc/sudoers.d/panel-bridge`:

    chaddugas ALL=(root) NOPASSWD: /sbin/shutdown -r now
    chaddugas ALL=(root) NOPASSWD: /usr/bin/nmcli radio wifi *
    chaddugas ALL=(root) NOPASSWD: /usr/bin/tee /sys/class/graphics/fb0/blank

(Replace `chaddugas` with your bridge user if different.)

Without these, the buttons quietly log "sudo failed — is passwordless
sudo configured?" and nothing happens. No state to report for reboot
(the Pi is on its way out), so no emit_initial.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

SHUTDOWN = "/sbin/shutdown"


async def apply_reboot_pi(bridge, payload: dict[str, Any]) -> None:
    log.warning("reboot_pi: rebooting")
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", SHUTDOWN, "-r", "now",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
    except OSError as e:
        log.warning("reboot_pi: cannot invoke sudo: %s", e)
        return
    if proc.returncode != 0:
        log.warning(
            "reboot_pi: shutdown failed (is passwordless sudo configured?): %s",
            err.decode(errors="replace"),
        )
