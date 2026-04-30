"""HA-driven update dispatcher.

Spawns panel-update.sh detached when a panel_cmd update arrives. The
script runs independently of the bridge — survives the bridge restart
that happens partway through. Status lines the script writes to
/opt/panel/update.status are picked up by panel_bridge.update_status
and republished as state/update_status MQTT.

The bridge service must use KillMode=process so systemd doesn't murder
the spawned script when the script restarts the bridge mid-update.
panel-bridge.service sets this; install-pi.sh renders it.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

log = logging.getLogger(__name__)

UPDATE_SCRIPT = "/opt/panel/current/deploy/panel-update.sh"


async def apply_update(bridge: Any, payload: dict) -> None:
    version = payload.get("version", "latest")
    if not isinstance(version, str) or not version:
        log.warning(
            "panel_cmd update: bad version field, defaulting to latest: %r",
            version,
        )
        version = "latest"

    if not os.path.isfile(UPDATE_SCRIPT):
        log.error("panel_cmd update: %s not found — can't dispatch", UPDATE_SCRIPT)
        return

    log.info("panel_cmd update: spawning %s %s (detached)", UPDATE_SCRIPT, version)
    # start_new_session=True puts the child in a new session + process
    # group so it isn't tied to the bridge's tty / process group, which
    # combined with KillMode=process in panel-bridge.service means the
    # script survives the systemctl restart panel-bridge that happens
    # partway through its own flow.
    subprocess.Popen(  # noqa: S603 — UPDATE_SCRIPT is a fixed path
        [UPDATE_SCRIPT, version],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
