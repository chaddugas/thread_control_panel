"""Wi-Fi connection manager: scan + connect + current-SSID + error tracking.

Sibling to `wifi.py`, which only owns the radio rfkill toggle. This
module owns credential-bearing operations: scanning visible networks,
adding/replacing connection profiles, and reporting back the current
SSID and the most recent connect error.

Topics owned:
  state/wifi_ssid   — currently connected SSID, "" when disconnected
  state/wifi_ssids  — last scan: [{ssid, security, in_use}, ...]
  state/wifi_error  — last connect error, "" on success
  cmd/wifi_scan     — force an immediate scan + republish
  cmd/wifi_connect  — {ssid, password, security?} create profile + activate

`security` in scan output is normalized to a NetworkManager key-mgmt
string (`wpa-psk`, `sae`, `none`) or `null` for enterprise (802.1X) APs
that V1 doesn't support. The HA select forwards this back on connect so
the bridge knows which key-mgmt to set without a second scan.

All write operations go through `sudo -n nmcli ...`. Required sudoers:
    chaddugas ALL=(root) NOPASSWD: /usr/bin/nmcli *
(the broader rule replaces the narrow `radio wifi *` entry from
reboot.py's docstring).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .nmcli_util import run_nmcli

log = logging.getLogger(__name__)

WLAN_IFNAME = "wlan0"
SCAN_INTERVAL_S = 30

# Guard against multiple emit_initial calls spawning duplicate loops.
_loop_started = False


async def emit_initial(bridge) -> None:
    global _loop_started
    if _loop_started:
        return
    _loop_started = True
    asyncio.create_task(_periodic_loop(bridge))


async def apply_wifi_scan(bridge, payload: dict[str, Any]) -> None:
    await _publish_scan(bridge, force_rescan=True)
    await _publish_current_ssid(bridge)


async def apply_wifi_connect(bridge, payload: dict[str, Any]) -> None:
    ssid = payload.get("ssid")
    password = payload.get("password") or ""
    security = payload.get("security")

    if not isinstance(ssid, str) or not ssid:
        await _publish_error(bridge, "No network selected")
        return

    if security not in ("wpa-psk", "sae", "none"):
        # Unknown / enterprise / stale — best guess that covers most home APs.
        log.info("wifi_connect: unknown security %r, defaulting to wpa-psk", security)
        security = "wpa-psk"

    if security != "none" and not isinstance(password, str):
        await _publish_error(bridge, "Password required")
        return
    if security != "none" and not password:
        await _publish_error(bridge, "Password required")
        return

    log.info("wifi_connect: ssid=%r security=%s", ssid, security)

    # Replace any existing profile with the same name so credentials are fresh.
    rc, _, err = await run_nmcli("connection", "delete", ssid, sudo=True)
    if rc != 0 and "unknown connection" not in err.lower():
        log.info("wifi_connect: delete %r returned (rc=%d): %s", ssid, rc, err.strip())

    add_args: list[str] = [
        "connection", "add",
        "type", "wifi",
        "ifname", WLAN_IFNAME,
        "con-name", ssid,
        "ssid", ssid,
    ]
    if security == "sae":
        # WPA3-SAE requires Protected Management Frames. Default policy is 0
        # (let NM decide); some kernels/cards refuse SAE without explicit pmf.
        add_args += [
            "wifi-sec.key-mgmt", "sae",
            "wifi-sec.psk", password,
            "wifi-sec.pmf", "3",
        ]
    elif security == "wpa-psk":
        add_args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    else:  # "none" — open network
        add_args += ["wifi-sec.key-mgmt", "none"]

    rc, _, err = await run_nmcli(*add_args, sudo=True)
    if rc != 0:
        await _publish_error(bridge, _trim_nm_error(err) or "Failed to create profile")
        return

    rc, _, err = await run_nmcli("connection", "up", ssid, sudo=True)
    if rc != 0:
        # Profile was created but activation failed; leave it in place so the
        # user can retry with a corrected password without re-scanning.
        await _publish_error(bridge, _trim_nm_error(err) or "Connect failed")
        return

    await _publish_error(bridge, "")
    await _publish_current_ssid(bridge)


async def refresh_state(bridge) -> None:
    """Re-publish current WiFi state immediately.

    Called from sibling modules after actions that should produce an
    immediate user-visible state change (e.g. radio toggle in wifi.py),
    so HA sees the result without waiting up to SCAN_INTERVAL_S for the
    next periodic loop tick. wifi_error is intentionally NOT touched —
    that channel is sticky until the next connect attempt clears it.
    """
    await _publish_current_ssid(bridge)
    await _publish_scan(bridge, force_rescan=False)


# ------------------------------ internals ------------------------------


async def _periodic_loop(bridge) -> None:
    # Initial pass with a forced rescan so the user has a fresh list at boot
    # without having to press the refresh button.
    await _publish_scan(bridge, force_rescan=True)
    await _publish_current_ssid(bridge)
    await _publish_error(bridge, "")
    while True:
        try:
            await asyncio.sleep(SCAN_INTERVAL_S)
            await _publish_scan(bridge, force_rescan=False)
            await _publish_current_ssid(bridge)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("wifi_manage: periodic loop iteration failed")


async def _publish_scan(bridge, force_rescan: bool) -> None:
    networks, err = await _scan_wifi(force_rescan)
    if err:
        log.warning("wifi_manage: scan failed: %s", err)
        # Don't push scan errors into wifi_error — that channel is reserved
        # for connect-attempt outcomes so the integration can clear the
        # password input on any update without false positives from scan.
    await bridge.send_panel_state("wifi_ssids", {"value": networks})


async def _publish_current_ssid(bridge) -> None:
    ssid = await _current_ssid()
    await bridge.send_panel_state("wifi_ssid", {"value": ssid})


async def _publish_error(bridge, message: str) -> None:
    await bridge.send_panel_state("wifi_error", {"value": message})


async def _scan_wifi(force_rescan: bool) -> tuple[list[dict[str, Any]], str | None]:
    rc, out, err = await run_nmcli(
        "-t", "-f", "IN-USE,SSID,SECURITY",
        "device", "wifi", "list",
        "--rescan", "auto" if force_rescan else "no",
    )
    if rc != 0:
        return [], err.strip() or "scan failed"

    seen: dict[str, dict[str, Any]] = {}
    for line in out.splitlines():
        if not line:
            continue
        parts = _parse_t_line(line)
        if len(parts) < 3:
            continue
        in_use, ssid, security = parts[0], parts[1], parts[2]
        if not ssid:
            # Hidden SSIDs come back as empty in -t output; broadcast-only V1.
            continue
        if ssid in seen:
            # Same SSID on multiple BSSIDs — the first one wins (typically
            # the strongest signal NM has cached).
            continue
        seen[ssid] = {
            "ssid": ssid,
            "security": _security_to_keymgmt(security),
            "in_use": in_use == "*",
        }
    return list(seen.values()), None


async def _current_ssid() -> str:
    """Currently-connected SSID, or '' if not fully connected at IP layer.

    Reads NM's actual device state rather than the scan-list IN-USE flag.
    The scan-list flag stays set on the last AP even when the connection
    has dropped at IP layer, which made the entity report "connected"
    while SSH was timing out (see build_plan_v2.md Step 17b).

    NM device state values (GENERAL.STATE field):
        20   unavailable   (radio off)
        30   disconnected  (radio on, no profile active)
        40-90 connecting   (preparing / config / auth / IP setup)
        100  connected     (fully up at IP layer)
        110  deactivating
        120  failed

    Return the connection name only when STATE=100; anything else, "".
    """
    rc, out, _ = await run_nmcli(
        "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION",
        "device", "show", WLAN_IFNAME,
    )
    if rc != 0:
        return ""
    state = ""
    connection = ""
    for line in out.splitlines():
        if line.startswith("GENERAL.STATE:"):
            state = line[len("GENERAL.STATE:"):]
        elif line.startswith("GENERAL.CONNECTION:"):
            connection = line[len("GENERAL.CONNECTION:"):]
    if not state.startswith("100"):
        return ""
    # Connection profile name. For panels created via apply_wifi_connect
    # this matches the SSID exactly (con-name = ssid in our `nmcli
    # connection add` invocation).
    return connection


def _security_to_keymgmt(sec: str) -> str | None:
    """Map nmcli SECURITY field → NM key-mgmt name. None = unsupported."""
    s = sec.upper().strip()
    if not s or s == "--":
        return "none"
    if "802.1X" in s:
        return None
    # Mixed WPA2/WPA3 networks list both — prefer wpa-psk because most
    # supplicants negotiate the WPA2 fallback successfully and SAE has more
    # ways to fail (PMF mismatch, kernel quirks).
    if "WPA2" in s or "WPA1" in s or "WEP" in s:
        return "wpa-psk"
    if "WPA3" in s or "SAE" in s:
        return "sae"
    return "wpa-psk"


def _parse_t_line(line: str) -> list[str]:
    """Split nmcli -t output by ':', honoring backslash escapes."""
    fields: list[str] = []
    cur: list[str] = []
    i = 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
        elif c == ":":
            fields.append("".join(cur))
            cur = []
            i += 1
        else:
            cur.append(c)
            i += 1
    fields.append("".join(cur))
    return fields


def _trim_nm_error(err: str) -> str:
    # NM errors look like "Error: Connection activation failed: Secrets were
    # required, but not provided.\n". Strip the "Error: " prefix and trailing
    # whitespace for a tidier surface in HA.
    text = err.strip()
    if text.lower().startswith("error:"):
        text = text[len("error:"):].lstrip()
    # HA entity state has a 255-char limit; clamp defensively.
    if len(text) > 240:
        text = text[:237] + "..."
    return text
