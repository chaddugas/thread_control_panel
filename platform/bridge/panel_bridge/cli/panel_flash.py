"""panel-flash CLI: stream a firmware bin to the C6 via the running bridge.

Usage:
    panel-flash                           # uses /opt/panel/current/firmware.bin
    panel-flash /path/to/firmware.bin
    panel-flash --bridge ws://other:8765  # default ws://localhost:8765

Connects to the bridge over WS, sends an `ota_request` envelope with the
binary path (the bridge reads the file from disk — no transferring the
binary over WS), and prints status + progress until complete or failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import websockets

DEFAULT_BIN = "/opt/panel/current/firmware.bin"
DEFAULT_BRIDGE = "ws://localhost:8765"


async def _drive(bin_path: Path, bridge_url: str) -> int:
    if not bin_path.is_file():
        print(f"panel-flash: {bin_path} does not exist", file=sys.stderr)
        return 1

    print(f"→ Connecting to {bridge_url}...")
    try:
        async with websockets.connect(bridge_url) as ws:
            print(f"→ Requesting OTA: {bin_path}")
            await ws.send(
                json.dumps({"type": "ota_request", "path": str(bin_path)})
            )

            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue

                t = msg.get("type")
                if t == "ota_status":
                    phase = msg.get("phase", "?")
                    detail = msg.get("detail")
                    if detail:
                        print(f"  [{phase}] {detail}")
                    else:
                        print(f"  [{phase}]")
                    if phase == "complete":
                        return 0
                    if phase == "failed":
                        return 1
                elif t == "ota_progress":
                    bytes_ = msg.get("bytes", 0)
                    total = msg.get("total", 0)
                    rate = msg.get("rate_bps", 0)
                    pct = (bytes_ * 100 / total) if total else 0
                    rate_kb = rate / 1024
                    # Carriage return so successive progress lines overwrite,
                    # then newline at the end of the last one (handled by
                    # the next non-progress line printing normally).
                    print(
                        f"\r    {bytes_:>10,} / {total:,} "
                        f"({pct:5.1f}%)   {rate_kb:6.1f} KB/s",
                        end="",
                        flush=True,
                    )
                # Other message types (sensor, panel_state, entity_state,
                # etc.) are also broadcast over the same WS — ignore them
                # silently.
    except OSError as e:
        print(f"\npanel-flash: couldn't connect to bridge ({bridge_url}): {e}",
              file=sys.stderr)
        return 1
    except websockets.ConnectionClosed:
        print("\npanel-flash: bridge closed the connection", file=sys.stderr)
        return 1

    # Fell off the message loop without seeing complete/failed.
    print("\npanel-flash: connection ended unexpectedly", file=sys.stderr)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Flash C6 firmware via the panel bridge."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_BIN,
        help=f"Firmware .bin path (default: {DEFAULT_BIN})",
    )
    parser.add_argument(
        "--bridge",
        default=DEFAULT_BRIDGE,
        help=f"Bridge WebSocket URL (default: {DEFAULT_BRIDGE})",
    )
    args = parser.parse_args()

    sys.exit(asyncio.run(_drive(Path(args.path).expanduser(), args.bridge)))


if __name__ == "__main__":
    main()
