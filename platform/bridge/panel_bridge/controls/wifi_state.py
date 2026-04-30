"""WiFi state monitor: single source of truth for `state/wifi_state`.

Owns one MQTT topic — `state/wifi_state` — carrying a single enum
value that captures "what's the WiFi doing right now":

    disabled      radio off
    disconnected  radio on, NM device state 30
    connecting    radio on, NM device state 0/10/20/40-90/110
    connected     radio on, NM device state 100 (NM's ACTIVATED)
    error         radio on, NM device state 120 (NM's FAILED), OR
                   any nmcli read failed (timeout, exec error, etc.)

Updates are driven by two complementary mechanisms:

    1. `nmcli monitor` event stream — push-driven. nmcli monitor's
       output format isn't documented as stable, so we treat each
       emitted line as a generic edge trigger and re-read state.
       Only re-publish when the derived enum actually changes,
       so a single connect (which produces 5+ monitor lines) is
       a single wifi_state_change event in the journal.

    2. Reconcile poll every WIFI_STATE_RECONCILE_INTERVAL_S — safety
       net in case the monitor process exits silently. Always
       publishes (not just on change) so a broker that lost the
       retained message picks the value back up at the next tick.

State changes are also logged via the structured-event helper as
`event=wifi_state_change from=... to=...`, so the journal is
queryable for "what was the WiFi doing around 11:14 today" without
having to splice nmcli logs together.
"""

from __future__ import annotations

import asyncio
import logging

from ..events import log_event
from . import wifi_manage
from .nmcli_util import NMCLI, run_nmcli

log = logging.getLogger(__name__)

WLAN_IFNAME = "wlan0"
WIFI_STATE_RECONCILE_INTERVAL_S = 60
MONITOR_RESPAWN_DELAY_S = 2

STATE_DISABLED = "disabled"
STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_ERROR = "error"

# Module-level guards so emit_initial can be called more than once (e.g.,
# on UART link reconnect) without spawning duplicate background tasks.
_loop_started = False
_last_published: str | None = None


async def emit_initial(bridge) -> None:
    """Publish initial state and start monitor + reconcile background tasks."""
    global _loop_started
    if _loop_started:
        # Re-emit the last known state so a UART reconnect catches HA up
        # without restarting the bridge.
        if _last_published is not None:
            await bridge.send_panel_state(
                "wifi_state", {"value": _last_published}
            )
        return
    _loop_started = True

    await _publish_state(bridge, force=True)
    asyncio.create_task(_monitor_loop(bridge))
    asyncio.create_task(_reconcile_loop(bridge))


async def _read_state() -> str:
    """Derive the wifi_state enum from current NM state."""
    # Radio first — `disabled` short-circuits the device check.
    rc, out, _ = await run_nmcli("-t", "radio", "wifi")
    if rc != 0:
        return STATE_ERROR
    if out.strip() != "enabled":
        return STATE_DISABLED

    rc, out, _ = await run_nmcli(
        "-t", "-f", "GENERAL.STATE", "device", "show", WLAN_IFNAME
    )
    if rc != 0:
        return STATE_ERROR

    state_field = ""
    for line in out.splitlines():
        if line.startswith("GENERAL.STATE:"):
            state_field = line[len("GENERAL.STATE:"):]
            break

    if state_field.startswith("100"):
        return STATE_CONNECTED
    if state_field.startswith("120"):
        return STATE_ERROR
    if state_field.startswith("30"):
        return STATE_DISCONNECTED
    # 0 unknown, 10 unmanaged, 20 unavailable, 40-90 mid-connect, 110 deactivating
    return STATE_CONNECTING


async def _publish_state(bridge, force: bool = False) -> bool:
    """Read current state and publish if changed (or force=True).

    Returns True iff the state value changed. Callers use that to
    decide whether to also kick wifi_manage.refresh_state() — pointless
    to refresh ssid/scan if wifi_state didn't actually move.
    """
    global _last_published
    state = await _read_state()
    changed = state != _last_published
    if changed:
        log_event(
            log, "wifi_state_change",
            from_=_last_published or "<unknown>",
            to=state,
        )
        _last_published = state
    if changed or force:
        await bridge.send_panel_state("wifi_state", {"value": state})
    return changed


async def _monitor_loop(bridge) -> None:
    """Run `nmcli monitor` and react to each emitted line.

    nmcli monitor output isn't a stable schema across NM versions, so
    we don't parse it — each line is just an edge trigger to re-read
    state. The monitor process is long-lived; on EOF or error we wait
    MONITOR_RESPAWN_DELAY_S and respawn so a transient nmcli failure
    doesn't permanently lose event-driven updates.
    """
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                NMCLI, "monitor",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            log.exception("wifi_state: failed to start nmcli monitor")
            await asyncio.sleep(MONITOR_RESPAWN_DELAY_S)
            continue

        try:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break  # EOF — monitor exited
                changed = await _publish_state(bridge)
                if changed:
                    # State actually moved — refresh ssid + scan too so
                    # all WiFi entities reflect the new reality together.
                    await wifi_manage.refresh_state(bridge)
        except asyncio.CancelledError:
            proc.kill()
            raise
        except Exception:
            log.exception("wifi_state: monitor read loop failed")
        finally:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except Exception:
                pass

        await asyncio.sleep(MONITOR_RESPAWN_DELAY_S)


async def _reconcile_loop(bridge) -> None:
    """Safety-net poll. Always publishes so a broker that lost the
    retained value picks it back up; catches drift if the monitor
    process exited and we're between respawns."""
    while True:
        try:
            await asyncio.sleep(WIFI_STATE_RECONCILE_INTERVAL_S)
            await _publish_state(bridge, force=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("wifi_state: reconcile loop iteration failed")
