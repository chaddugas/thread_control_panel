"""Read and watch /opt/panel/mqtt_creds.json; send panel_set_creds to C6.

The bridge always sends credentials at startup (after the UART link is
up) and again whenever the file's mtime changes. The C6's
panel_net_set_credentials() no-ops on identical user+pass, so repeat
sends are cheap — that's the design contract that keeps this loop
simple.

File format (JSON):

    {"username": "...", "password": "..."}

Owner: install user, mode 0600 (set by install-pi.sh).

Validation matches what install-pi.sh enforces and what the C6's NVS
buffers can hold:
  - username: 1..64 chars
  - password: 12..128 chars, must contain at least 2 of 3 character
    classes (letter, digit, symbol)
  - neither field may contain `"` or `\\` — the C6's panel_app.c uses
    a substring-based JSON parser that doesn't handle escape sequences

If the file is missing, malformed, or fails validation we log a
warning and stay polling — the C6 stays in its "provisioning required"
state until a valid file appears.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from .events import log_event

log = logging.getLogger(__name__)

CREDS_FILE = Path("/opt/panel/mqtt_creds.json")
WATCH_INTERVAL_S = 5.0

# Even when the file hasn't changed, re-send creds to the C6 every
# RESEND_INTERVAL_S seconds. The C6 no-ops on identical user+pass, so
# the only cost is one ~100-byte UART message per minute. The benefit
# is that a freshly-booted C6 (e.g. after an OTA flash, after a
# manual cmd/reboot_c6, or after a power cycle that the bridge didn't
# witness) gets re-provisioned within the interval — no manual bridge
# bounce required to recover from "C6 lost NVS" or "C6 booted into a
# new firmware that hasn't been provisioned yet."
#
# 60s sits comfortably under panel-update.sh's 90s verifying_c6
# timeout, so a Phase-1 OTA can succeed without intervention.
RESEND_INTERVAL_S = 60.0

# Caps must stay in sync with panel_net.c's MQTT_USER_MAX_LEN /
# MQTT_PASS_MAX_LEN (those include the null terminator; these are
# pure character counts).
USERNAME_MAX_LEN = 64
PASSWORD_MIN_LEN = 12
PASSWORD_MAX_LEN = 128


def _has_class_diversity(pw: str) -> bool:
    """At least 2 of 3 character classes present: letter, digit, symbol."""
    classes = 0
    if any(c.isalpha() for c in pw):
        classes += 1
    if any(c.isdigit() for c in pw):
        classes += 1
    if any(not c.isalnum() for c in pw):
        classes += 1
    return classes >= 2


def _read_and_validate() -> tuple[str, str] | None:
    """Read the creds file and return (username, password) or None.

    None on: file missing, parse error, missing fields, wrong types,
    empty values, length limit exceeded, weak password, or unsupported
    characters. Logs a warning describing the specific failure so a
    misconfigured file is debuggable from journals alone.
    """
    try:
        text = CREDS_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        log.warning("mqtt_creds: read of %s failed: %s", CREDS_FILE, e)
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.warning("mqtt_creds: %s parse error: %s", CREDS_FILE, e)
        return None

    if not isinstance(data, dict):
        log.warning("mqtt_creds: %s top-level is not a JSON object", CREDS_FILE)
        return None

    user = data.get("username")
    pw = data.get("password")

    if not isinstance(user, str) or not user:
        log.warning("mqtt_creds: missing or empty 'username'")
        return None
    if not isinstance(pw, str) or not pw:
        log.warning("mqtt_creds: missing or empty 'password'")
        return None
    if len(user) > USERNAME_MAX_LEN:
        log.warning("mqtt_creds: username too long (>%d chars)", USERNAME_MAX_LEN)
        return None
    if len(pw) < PASSWORD_MIN_LEN or len(pw) > PASSWORD_MAX_LEN:
        log.warning(
            "mqtt_creds: password length %d outside [%d, %d]",
            len(pw), PASSWORD_MIN_LEN, PASSWORD_MAX_LEN,
        )
        return None
    if not _has_class_diversity(pw):
        log.warning(
            "mqtt_creds: password must contain at least 2 of "
            "{letters, digits, symbols}"
        )
        return None
    if any(c in user or c in pw for c in ('"', "\\")):
        log.warning(
            "mqtt_creds: '\"' or '\\' in username/password — the C6 parser "
            "doesn't handle JSON escapes; rotate to a value without them"
        )
        return None

    return user, pw


async def _send(uart: Any, user: str, pw: str) -> bool:
    """Send a panel_set_creds envelope. Returns True on UART send success."""
    msg = {"type": "panel_set_creds", "username": user, "password": pw}
    ok = await uart.send(msg)
    if ok:
        # Don't log the password; user is fine — knowing which user is
        # provisioned is useful for debugging mismatched-broker cases.
        log_event(log, "mqtt_creds_sent", user=user)
    else:
        log.warning("mqtt_creds: UART send failed — link not yet writable")
    return ok


async def run(uart: Any) -> None:
    """Background task: send creds at startup, on file change, and
    periodically as a safety net.

    Runs forever as part of the bridge's `asyncio.gather`. The C6
    no-ops on identical creds, so re-sending is cheap — that's the
    design contract that lets us keep the state machine here trivial:

      - Refresh `cached_creds` from disk only on file mtime change
        (validation-error logs don't repeat every iteration).
      - Send when (a) the file just changed AND we have valid creds,
        OR (b) RESEND_INTERVAL_S has elapsed since the last send AND
        we have valid creds. (b) is what lets a freshly-booted C6
        pick up provisioning without a bridge bounce.
    """
    last_mtime: float | None = None
    cached_creds: tuple[str, str] | None = None
    last_send_at: float = 0.0

    while True:
        try:
            now = time.monotonic()

            try:
                current_mtime = CREDS_FILE.stat().st_mtime
            except FileNotFoundError:
                current_mtime = None

            file_changed = current_mtime != last_mtime
            if file_changed:
                last_mtime = current_mtime
                if current_mtime is None:
                    log.warning(
                        "mqtt_creds: %s missing — C6 will stay unprovisioned "
                        "until install-pi.sh writes it",
                        CREDS_FILE,
                    )
                    cached_creds = None
                else:
                    cached_creds = _read_and_validate()
                    # _read_and_validate logs its own validation
                    # errors. We don't double-log here.

            if cached_creds is not None:
                due_for_resend = (now - last_send_at) >= RESEND_INTERVAL_S
                if file_changed or due_for_resend:
                    user, pw = cached_creds
                    if await _send(uart, user, pw):
                        last_send_at = now

            await asyncio.sleep(WATCH_INTERVAL_S)

        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("mqtt_creds: watch loop iteration failed")
            await asyncio.sleep(WATCH_INTERVAL_S)
