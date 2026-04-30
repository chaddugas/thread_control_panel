"""Shared nmcli runner for the WiFi control modules.

Wraps `asyncio.create_subprocess_exec` + `communicate()` with a hard
timeout so a wedged nmcli (observed when NetworkManager itself enters a
degraded state) can't freeze the bridge's periodic loops indefinitely.
On timeout, emits an `nmcli_timeout` structured event and returns a
synthetic failure result so callers handle it as a normal nmcli error.

Default timeout is 30s — comfortable upper bound for any nmcli call we
currently make (radio toggle, status read, scan, connect). Callers can
override via `timeout_s` if a specific call legitimately needs longer
(or shorter — Commit F tightens the periodic loop and may want lower).

Return shape preserves what the previous in-line callers expected:
`(returncode, stdout_str, stderr_str)`. Special return codes:
  - 124: nmcli was killed after exceeding `timeout_s` (GNU `timeout`
    convention so callers can distinguish from nmcli's own non-zero
    exits).
  - 127: nmcli (or sudo) wasn't found / failed to exec.
"""

from __future__ import annotations

import asyncio
import logging

from ..events import log_event

log = logging.getLogger(__name__)

NMCLI = "/usr/bin/nmcli"
DEFAULT_TIMEOUT_S = 30.0
TIMEOUT_RC = 124


async def run_nmcli(
    *args: str,
    sudo: bool = False,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[int, str, str]:
    """Run nmcli with a hard timeout. Returns (rc, stdout, stderr)."""
    cmd: list[str] = ["sudo", "-n", NMCLI, *args] if sudo else [NMCLI, *args]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        return 127, "", str(e)

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        log_event(log, "nmcli_timeout", cmd=" ".join(cmd), timeout_s=timeout_s)
        proc.kill()
        # Drain after kill so we don't leak a zombie. Bounded so this
        # itself can't hang if SIGKILL doesn't take effect.
        try:
            await asyncio.wait_for(proc.communicate(), timeout=2.0)
        except Exception:
            pass
        return TIMEOUT_RC, "", f"nmcli timed out after {timeout_s}s"

    return (
        proc.returncode if proc.returncode is not None else -1,
        out.decode(errors="replace"),
        err.decode(errors="replace"),
    )
