#!/usr/bin/env python3
"""Smoke-test WebSocket client. Connects to the bridge, prints every message
it receives, and on stdin reads JSON lines and forwards them to the bridge.

Usage:
    python3 test_client.py [ws://host:port]

Defaults to ws://localhost:8765. Run on the Pi or from another machine on
the LAN — the bridge defaults to listening on 0.0.0.0 during dev.
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets


async def reader(ws) -> None:
    async for msg in ws:
        print(f"[RX] {msg}")


async def writer(ws) -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)  # validate
        except json.JSONDecodeError as e:
            print(f"[ERR] not valid JSON: {e}", file=sys.stderr)
            continue
        await ws.send(line)


async def main(uri: str) -> None:
    print(f"Connecting to {uri}")
    async with websockets.connect(uri) as ws:
        print("Connected. Type a JSON line + Enter to send. Ctrl+D to quit.")
        await asyncio.gather(reader(ws), writer(ws))


if __name__ == "__main__":
    uri = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8765"
    try:
        asyncio.run(main(uri))
    except KeyboardInterrupt:
        pass
