# platform/bridge/

Long-running daemon on the Pi: bridges the C6 (UART) ↔ panel UI (WebSocket).

## What it does

- Reads JSON lines from `/dev/serial0`, parses, caches the latest per typed key (sensors by `type:name`, entities by `entity_state:entity_id`, everything else by `type`), broadcasts to every connected WebSocket client.
- Receives JSON messages over WebSocket, writes them to UART for the C6 to publish to MQTT. Gates `call_service` commands on the last-known `ha_availability` — drops with a warning when HA is offline so commands don't fire into the void.
- On a fresh WebSocket connection, replays the cached state so the UI gets current values immediately.
- Auto-reconnects the UART if the link drops.

Eventually it'll also own the panel-itself control state (brightness, screen on/off, wifi config) — those are deferred until we wire up `nmcli`/backlight handlers in step 14.

## Layout

```
panel_bridge/
├── __main__.py     # entry point — wires everything together, gates call_service on ha_availability
├── config.py       # env-var overrides (UART port/baud, WS host/port)
├── state.py        # in-memory cache + ha_availability accessor
├── uart_link.py    # async UART reader/writer (pyserial-asyncio)
└── ws_server.py    # WebSocket server (websockets) with snapshot-on-connect
```

## Install (one time on the Pi)

Pi OS Bookworm enforces PEP 668; use a venv.

```bash
cd ~/thread_control_panel/platform/bridge
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Run

Foreground (for dev):

```bash
.venv/bin/python -m panel_bridge
```

You should see:

```
INFO panel_bridge: Starting panel_bridge — UART /dev/serial0 @ 115200, WS ws://0.0.0.0:8765
INFO panel_bridge.uart_link: UART link up on /dev/serial0 @ 115200
INFO panel_bridge.ws_server: WS server listening on ws://0.0.0.0:8765
```

Override defaults with env vars:

```bash
PANEL_UART_PORT=/dev/ttyUSB0 PANEL_WS_PORT=9000 PANEL_LOG_LEVEL=DEBUG \
  .venv/bin/python -m panel_bridge
```

## Test the round trip

In a second shell:

```bash
.venv/bin/python test_client.py
# or from your Mac:
.venv/bin/python test_client.py ws://thread-panel.local:8765
```

What you should see:

- On connect, an immediate burst of `[RX]` lines — the cached state replay (roster + per-entity state + sensors + ha_availability).
- After that, a `[RX]` line every second for proximity, every 5s for ambient, and whenever any forwarded HA entity changes state.
- Type a JSON line like `{"type":"call_service","entity_id":"light.foo","action":"light.toggle","data":{}}` + Enter — it'll be forwarded to the C6 → MQTT → integration → HA service call. (Only works when `ha_availability` is `online`.)

## Production

The bridge runs under [`../deploy/panel-bridge.service`](../deploy/panel-bridge.service) on the Pi, installed by [`../deploy/install-pi.sh`](../deploy/install-pi.sh). On the Pi it lives at `/opt/panel/current/bridge/` (V2 artifact-based install). See [`../deploy/README.md`](../deploy/README.md) for the install/upgrade flow.
