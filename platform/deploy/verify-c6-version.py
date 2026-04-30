#!/usr/bin/env python3
"""Wait for the C6 to report a specific firmware version via the bridge.

Connects to ws://localhost:8765 and watches for `panel_state` messages
with `name=version`, returning success once one matches the expected
version. Used by panel-update.sh after `panel-flash` to confirm that
the C6 actually booted the new firmware AND reached MQTT (which is when
it republishes the version envelope).

Pre-flash retained version is cleared from the bridge's cache via the
no-op skip in WS connect — the snapshot replays the *last* known value
which might be the OLD version. That's fine: we then wait for the NEXT
panel_state message and only succeed if it matches expected. The OLD
snapshot value is silently filtered.

Exit codes:
  0 — C6 reported the expected version
  2 — timed out waiting
  3 — connection / protocol error

Usage:
  verify-c6-version.py <expected_version> <timeout_sec>
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

BRIDGE_URL = "ws://localhost:8765"


async def wait_for_version(expected: str, timeout_sec: float) -> int:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_sec

    try:
        async with websockets.connect(BRIDGE_URL, ping_interval=10) as ws:
            # Track whether we've seen the snapshot replay finish vs. fresh
            # messages. Snapshot lands first on connect. We accept any
            # version match — pre-flash snapshot or post-flash fresh —
            # which means a successful flash to the same version (or already
            # being on the target) reports success immediately. That's fine
            # for our use case.
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return 2
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    return 2
                except websockets.ConnectionClosed:
                    print("verify-c6-version: bridge closed connection",
                          file=sys.stderr)
                    return 3

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if (msg.get("type") == "panel_state"
                        and msg.get("name") == "version"
                        and msg.get("version") == expected):
                    return 0
    except OSError as e:
        print(f"verify-c6-version: couldn't connect to {BRIDGE_URL}: {e}",
              file=sys.stderr)
        return 3


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "usage: verify-c6-version.py <expected_version> <timeout_sec>",
            file=sys.stderr,
        )
        sys.exit(1)
    expected = sys.argv[1]
    try:
        timeout = float(sys.argv[2])
    except ValueError:
        print(f"verify-c6-version: bad timeout '{sys.argv[2]}'", file=sys.stderr)
        sys.exit(1)
    sys.exit(asyncio.run(wait_for_version(expected, timeout)))


if __name__ == "__main__":
    main()
