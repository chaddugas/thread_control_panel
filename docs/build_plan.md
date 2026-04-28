# Thread Control Panel — Build Plan

The project is a **platform** for building no-WiFi Thread-based touchscreen control panels for Home Assistant, plus its **first product** (`feeding_control` — a pet feeder UI). This doc covers both: the platform-level work and the product-level work for `feeding_control`. Future products will get their own short product-specific docs and reference this one.

## Keeping this current

This document is the source of truth for the project's state. Agents working on this project (Claude or otherwise) should treat updating it as part of the work, not a follow-up. After completing a step or making a non-trivial decision:

- Strike through the finished step (`~~**Step name**~~`) and append `✅ DONE` to its title.
- Move the `(next up)` marker to the new active step.
- Record meaningful learnings in **Lessons Learned**, validated invariants in **Proven Facts**, and known-but-deferred problems in **Technical Debt**.
- Refresh **Current Status** when a major capability lands or changes.
- Edit/remove anything the work has invalidated rather than leaving stale guidance behind.

Small mid-step edits are fine and encouraged — better a slightly noisy diff than a doc that no longer reflects reality.

## Current Status

- **MQTT-over-Thread proven end-to-end with proper TLS validation.** C6 firmware connects to Mosquitto on HA box via Thread → OTBR → LAN IPv6, authenticates with TLS using a Let's Encrypt cert chain validated against the ISRG Root X1 CA, publishes and subscribes successfully. Hostname verification is enabled (no `skip_cert_common_name_check`). The C6 resolves the broker via DNS through AdGuard, no IP literals in firmware.
- Thread architecture validated: XIAO ESP32-C6 joins mesh, gets routable IPv6 via OTBR.
- Pi Zero 2 W set up with SSH; PL011 enabled on GPIO 14/15 (Bluetooth disabled to free the full UART).
- **C6 ↔ Pi UART bridge proven end-to-end** at 115200 over the Pi's PL011. HA entity state flows HA → integration → MQTT → C6 → UART → Pi → WS → UI; UI `call_service` commands flow the reverse path and dispatch against real HA entities.
- **Waveshare 6.25" display + touch working** via direct framebuffer (`/dev/fb0`, RGB565) + evdev. See `platform/diagnostics/touch_test.py`. Pygame did not work on this setup; production UI will use Vue 3 + Vite + Pinia served via Chromium-kiosk under `cage`.
- **Monorepo scaffold landed.** `platform/` (firmware component, bridge, ui-core, ha-integration, deploy, diagnostics) + `panels/feeding_control/` (firmware, ui, ha, manifest). Existing firmware and Pi diagnostics migrated. App entrypoint (`panels/feeding_control/firmware/main/app_main.c`) is now three lines: `panel_platform_init() → panel_app_init() → panel_net_start()`.
- **Sensors live on the C6, not the Pi.** TEMT6000 ambient on ADC1 CH0 (D0). TF-Mini Plus LiDAR on UART0 routed to D3/D4 (115200). Both are read by `panel_platform`, published to MQTT (`thread_panel/feeding_control/state/{proximity,ambient_brightness}`), and forwarded as JSON lines over UART to the Pi. Originally planned to use MCP3008 ADC on the Pi; pivoted because the C6 has built-in ADC + spare UARTs and the data flow is more direct (no Pi-as-middleman for HA-bound state).

## Project Structure

```
custom_components/thread_panel/ # HA integration (at repo root for HACS)

platform/                       # shared across every panel
├── firmware/components/panel_platform/   # ESP-IDF component (panel_net, panel_uart, OT/MQTT bring-up)
├── bridge/                     # Pi-side Python WS+UART
├── ui-core/                    # Shared Vue+Pinia primitives (TBD)
├── deploy/                     # systemd units, install scripts (TBD)
└── diagnostics/                # panel_test.py, touch_test.py

panels/                         # per-product
└── feeding_control/
    ├── firmware/               # ESP-IDF project; depends on panel_platform
    ├── ui/                     # Vue+Vite app
    └── ha/                     # reference manifest template + hatch for product-specific HA-side Python
```

Anything device-agnostic lives in `platform/`. Anything product-specific (UI, MQTT topic specifics, panel_app implementation, reference manifest) lives in `panels/<id>/`. The dividing rule: if it would be identical for any future panel, it's platform.

The `thread_panel` custom HA integration is platform (single codebase handles N panels via N config entries), but lives at the repo root rather than under `platform/` — HACS requires `custom_components/<domain>/` at the root of the repo for validation. One install handles every panel.

## Hardware

| Component | Part | Role |
|---|---|---|
| Compute | Raspberry Pi Zero 2 W | Display + touch + sensor host |
| Display | Waveshare 6.25" capacitive touch (HDMI + USB touch) | UI |
| Radio | Seeed XIAO ESP32-C6 | Thread stack + MQTT client |
| Proximity | TF-Mini Plus LiDAR (UART or I2C) | Display wake |
| Ambient light | TEMT6000 analog sensor | Backlight dimming |
| Power | 5V 3A micro-USB to Pi, C6 on shared rail or own USB |

## Architecture

### Network topology (validated)

```
XIAO C6 (Thread node)
  └─ 802.15.4 ──► ZBT-2 (HA box)
                    └─ Spinel ──► OTBR add-on
                                    └─ IPv6 ──► Mosquitto add-on (TLS :8883)
                                                  └─► MQTT integration ──► HA entities
```

All traffic stays on the HA box after the ZBT-2 — the LAN and router are not involved in the data plane.

DNS resolution path (used at C6 connect time only):
```
C6 ──► OTBR ──► HA box static ULA ──► AdGuard add-on
                                        └─► returns rewritten AAAA
                                            for the-interstitial-space.duckdns.org
```

### Division of labor

**XIAO ESP32-C6** (ESP-IDF firmware — code in `platform/firmware/components/panel_platform/` + `panels/feeding_control/firmware/main/`)
- OpenThread stack joined to existing Thread network
- MQTT client → Mosquitto on HA box (TLS, authenticated)
- Publishes MQTT Discovery configs at boot for the **panel-itself entities** (reboot, wifi, brightness, screen, sensors)
- UART bridge to Pi: receives MQTT data, forwards as JSON; receives Pi events, publishes to MQTT
- LWT for availability

**Pi Zero 2 W** (Raspberry Pi OS Lite 64-bit — code in `platform/bridge/` + `panels/feeding_control/ui/` + `platform/ui-core/`)
- HDMI display output to Waveshare
- USB touch input via evdev
- Vue 3 + Vite + Pinia web app served via Chromium-kiosk under `cage` (Wayland kiosk compositor)
- Python bridge: WebSocket server for the UI, UART link to C6, mirrored state cache, panel-itself control owners (brightness, screen, wifi)
- I2C/analog reading for TEMT6000 (via MCP3008 ADC, since Pi lacks analog input)
- UART or I2C to TF-Mini Plus
- No network in production (WiFi for dev only, disabled once deployed, can be re-enabled via MQTT commands)

**Home Assistant** (code in `custom_components/thread_panel/`; per-product reference manifests under `panels/<id>/ha/`)
- Custom integration `thread_panel` represents each panel as a HA Device. One install, N config entries — one per panel.
- **Integration is a generic per-entity forwarder**, driven by a per-panel manifest that declares which entities to expose + which attributes of each to forward. The manifest is pasted into the config flow (YAML text) — `panels/<id>/ha/manifest.yaml` serves as a reference template users copy and adapt. `panels/<id>/ha/` stays as a hatch for the rare case where a product needs non-entity-shaped HA-side Python (e.g. a REST fetch); not built speculatively.
- Integration lives at the repo root (`custom_components/thread_panel/`) rather than under `platform/` because HACS validates that path for repo compliance.
- AdGuard add-on provides split-horizon DNS for the broker's duckdns hostname so Thread-only devices can resolve it

### Sensor wiring (validated — all on the C6)

Both environmental sensors land on the XIAO ESP32-C6, not the Pi. Reasons in the "Sensors-on-C6 pivot" lessons-learned section.

| Sensor | XIAO C6 pin | Function | Notes |
|---|---|---|---|
| **TEMT6000** VCC | 3V3 (output pin) | 3.3V power | NOT 5V — sensor's output is 0..VCC, must stay ≤ ADC's 3.3V max input |
| **TEMT6000** GND | any GND | shared ground | tied to Pi GND via the existing UART GND wire |
| **TEMT6000** SIG | D0 (GPIO0) | ADC1 CH0 | DB_12 attenuation, ~0..3.1V usable |
| **TF-Mini Plus** VCC (red) | 5V | 5V power | passthrough from USB while plugged in |
| **TF-Mini Plus** GND (black) | any GND | shared ground | |
| **TF-Mini Plus** TX (green) | D3 (GPIO21) | UART0 RX | TF-Mini streams 9-byte frames at 100 Hz; firmware syncs on `0x59 0x59` header |
| **TF-Mini Plus** RX (white) | D4 (GPIO22) | UART0 TX | wired but unused (we don't send commands) |

The UART link to the Pi remains on UART1 / D6 (TX) / D7 (RX). UART0 and UART1 coexist via the GPIO matrix.

## MQTT Topics

Three namespaces under `thread_panel/<panel_id>/`:

- **`state/`** — read-only, retained. Source of truth values.
- **`set/`** — write-to-mutate. Paired with the corresponding `state/` for read-write entities.
- **`cmd/`** — one-shot actions (verbs, not state).

Plus `availability` at the top level as the LWT.

### Panel-itself entities (every panel exposes these — defined by the platform)

Discovery configs published by the C6 at boot to `homeassistant/.../thread_panel_<panel_id>/.../config`. State lives on the Pi; the bridge owns it.

| Topic | Direction | Retain | Payload |
|---|---|---|---|
| `thread_panel/<id>/availability` | C6 LWT | yes | `online` / `offline` (C6's MQTT connection) |
| `thread_panel/<id>/ha_availability` | Integration LWT | yes | `online` / `offline` (integration is loaded and ready; flips `online` only after roster + initial state are published) |
| `thread_panel/<id>/state/wifi_enabled` | Pi → C6 → MQTT | yes | `{"value": true}` |
| `thread_panel/<id>/set/wifi_enabled` | HA → C6 → Pi | no | `{"value": true}` |
| `thread_panel/<id>/state/wifi_ssid` | Pi → C6 → MQTT | yes | `{"value": "..."}` (currently connected SSID; `""` when disconnected) |
| `thread_panel/<id>/state/wifi_ssids` | Pi → C6 → MQTT | yes | `{"value": [{"ssid": "...", "security": "wpa-psk"\|"sae"\|"none"\|null, "in_use": bool}, ...]}` |
| `thread_panel/<id>/state/wifi_error` | Pi → C6 → MQTT | yes | `{"value": "..."}` (last connect-attempt error; `""` on success) |
| `thread_panel/<id>/cmd/wifi_connect` | HA → C6 → Pi | no | `{"ssid": "...", "password": "...", "security": "wpa-psk"\|"sae"\|"none"\|null}` |
| `thread_panel/<id>/cmd/wifi_scan` | HA → C6 → Pi | no | `{}` (force immediate rescan + republish) |
| `thread_panel/<id>/state/brightness` | Pi → C6 → MQTT | yes | `{"value": 0..100}` |
| `thread_panel/<id>/set/brightness` | HA → C6 → Pi | no | `{"value": 50}` |
| `thread_panel/<id>/state/screen_on` | Pi → C6 → MQTT | yes | `{"value": true}` |
| `thread_panel/<id>/set/screen_on` | HA → C6 → Pi | no | `{"value": true}` |
| `thread_panel/<id>/state/proximity` | C6 → MQTT | yes | `{"value": cm}` (LiDAR distance; gated by `ha_availability`) |
| `thread_panel/<id>/state/ambient_brightness` | C6 → MQTT | yes | `{"value": 0..100}` (TEMT6000; gated by `ha_availability`) |
| `thread_panel/<id>/cmd/reboot_pi` | HA → C6 → Pi | no | `{}` |
| `thread_panel/<id>/cmd/reboot_c6` | HA → C6 | no | `{}` |

### Forwarded HA entities (generic platform feature)

The integration forwards a caller-specified list of HA entities to the panel, driven by a per-product manifest. No typed product topics — every product entity flows through the same two topics (`state/entity/<entity_id>` + `cmd/call_service`) regardless of domain.

| Topic | Direction | Retain | Payload |
|---|---|---|---|
| `thread_panel/<id>/state/_roster` | Integration → C6 | yes | `{"entities": [{"entity_id": "...", "friendly_name": "...", "area": "..."}, ...]}` — one entry per declared manifest entity |
| `thread_panel/<id>/state/entity/<entity_id>` | Integration → C6 | yes | `{"state": "...", "attributes": {...}}` — full snapshot of current state + allowlisted attrs; `state: "unknown"` if the entity doesn't exist (yet) |
| `thread_panel/<id>/cmd/call_service` | C6 → Integration | no | `{"entity_id": "...", "action": "switch.turn_on", "data": {...}}` — integration rejects any `entity_id` not in its manifest |

**Manifest shape** (lives at `panels/<id>/ha/manifest.yaml` for Day 1; migrates to the integration's config flow once interactive setup lands):

```yaml
panel_id: feeding_control
entities:
  - entity_id: switch.pet_feeder
    attributes: []               # state only, no attributes forwarded
  - entity_id: sensor.pet_feeder_schedule
    attributes: all              # forward every attribute
  - entity_id: sensor.pet_feeder_last_fed
    attributes: [timestamp, quantity]
```

Attribute forms:
- omitted or `[]` — state only, no attributes
- `[a, b, c]` — explicit allowlist
- `all` — forward every attribute. Intended for entities whose attribute keys are dynamic (e.g. a schedule whose keys vary per item) and can't be enumerated ahead of time. Trades payload bound + noise for flexibility; use only when an allowlist isn't practical.

**Publish semantics** (two dials, tuned independently):

- *Dial A — what triggers a publish:* aggressive filtering. Integration's state listener fires on any change; it only publishes if `old.state != new.state` OR any allowlisted attribute differs. Non-allowlisted attribute churn is dropped.
- *Dial B — what's in the payload:* always a full snapshot of `{state, allowlisted attributes}`. No diffs. Retained topics and reconnect replay work naturally; no shadow-state merge logic on the receiving side.

**Missing entities**: integration publishes `{"state": "unknown"}` at startup for any manifest entry without a corresponding HA state, logs a warning, and keeps the listener registered. If the entity later appears (HA restart ordering), real state lands automatically.

**Service dispatch**: integration subscribes to `cmd/call_service`. It validates `entity_id ∈ manifest entities` and dispatches via `hass.services.async_call(domain, service, data, target={entity_id})`. No per-action allowlist — the entity allowlist is sufficient boundary. Failures log on the HA side only; no error topic in V1.

### Availability & publish gating

Both sides expose availability retained-and-LWT-backed, and both gate behavior on the other's state:

- `availability` (C6 side): `online` on MQTT connect, `offline` via LWT.
- `ha_availability` (integration side): `online` only after roster + all initial entity states are published. `offline` via LWT or on shutdown.

This is the MQTT-idiomatic handshake — retained + LWT gives us startup-order independence (whoever comes up first is already "there" by the time the other subscribes), drop detection (~60s keepalive), and reconnect. No custom probes, timeouts, or heartbeats in V1. If stale-retained-`online` ever bites in practice, add a timestamp field + periodic republish (cheap addition, doesn't change the shape).

**What each side does with the signal:**

- **C6**: while `ha_availability == offline`, suppress periodic MQTT state publishes (sensors, UART-sourced echoes). Keep publishing its own `availability` topic and keep the MQTT connection alive (keepalives are tiny; reconnect cost isn't worth avoiding). Maintain a volatile-RAM "last known sensor values" cache — on the `offline → online` transition, republish current values once so retained state is fresh, then resume normal cadence. Forward `ha_availability` over UART so the bridge can consume it.
- **Bridge**: forward `ha_availability` to the UI over WS as a first-class field. Gate outgoing `call_service` commands on it — no-op or surface an error to the UI when HA is offline, so commands aren't fired into the void.
- **UI**: consume `ha_availability` from the bridge to show a loading/offline overlay and disable controls. Product UIs render however they like, but the signal comes from the platform uniformly.

Design principle: stop publishing into the void. Thread traffic volume here is small in absolute terms (~1 KB/min of sensors), but the goal is to respect that Thread wasn't designed for chatty MQTT fleets.

### Bidirectional state flow

Three distinct flows, all sharing the same transport:

1. **Panel-itself entities** (brightness, screen_on, wifi_*): Pi is source of truth.
   - HA-initiated: HA → `set/X` → C6 → UART → bridge → Pi adjusts → Pi → UART → C6 → `state/X` → HA sees the update.
   - UI-initiated: UI → WS → bridge adjusts Pi locally → bridge → UART → C6 → `state/X` → HA sees the update.

2. **Forwarded HA entities** (e.g. `switch.pet_feeder`): HA is source of truth.
   - HA state change → integration listener → `state/entity/<entity_id>` (retained) → C6 → UART → bridge → WS → UI.
   - UI command: UI → WS → bridge → UART → C6 → `cmd/call_service` → integration → `hass.services.async_call(...)`.

3. **Panel sensors** (proximity, ambient_brightness): C6 is source of truth.
   - Sensor → C6 → `state/<sensor>` (retained MQTT, subject to `ha_availability` gate) AND C6 → UART → bridge → WS → UI (not gated — local UI is always served).

The UI never publishes directly to MQTT. It speaks only to the bridge over WS. That keeps retained semantics, availability gating, and auth out of the UI entirely.

## UART Protocol (C6 ↔ Pi)

Line-based JSON over UART at 115200 baud. Keep it dumb.

**C6 → Pi** (state updates from HA, panel sensors, availability):
```
{"type":"roster","entities":[{"entity_id":"switch.pet_feeder","friendly_name":"Pet Feeder","area":"Kitchen"}, ...]}
{"type":"entity_state","entity_id":"switch.pet_feeder","state":"on","attributes":{}}
{"type":"ha_availability","value":"online"}
{"type":"proximity","value":42}
{"type":"ambient_brightness","value":85}
```

**Pi → C6** (user actions):
```
{"type":"call_service","entity_id":"switch.pet_feeder","action":"switch.turn_on","data":{}}
```

Either side can ignore messages it doesn't understand. Both sides log everything during dev.

## C6 Firmware State

**Project:** `panels/feeding_control/firmware/` (ESP-IDF). Depends on the shared `panel_platform` component at `platform/firmware/components/panel_platform/` via `EXTRA_COMPONENT_DIRS`.

**Working:**
- OpenThread auto-starts on boot, commissions from stored dataset
- MQTT client connects to `mqtts://the-interstitial-space.duckdns.org:8883` with TLS, with full hostname verification, over Thread
- DNS resolved via AdGuard at HA's static ULA (`PANEL_DNS_SERVER` in `panel_platform_config.h`), configured into lwIP at boot
- Authenticates via username/password (HA user: `mqtt_user`, note underscore)
- Subscribes to `thread_panel/<panel_id>/ha_availability`, `state/entity/#`, and `state/_roster`; wraps each payload with a typed envelope and forwards over UART to the Pi. Routes outbound `call_service` UART lines to `cmd/call_service` for the integration to dispatch.
- Gates its own state publishes (sensors) and command routing on `ha_availability == online`. Maintains cached last sensor values; republishes on `offline → online` transition.
- Verified in Mosquitto log: TLS negotiated, client authenticated, cert chain validated against ISRG Root X1
- MQTT start gated on **both** Thread role attach and an OMR address being acquired (avoids a premature `getaddrinfo()` race against OTBR's RA)
- Device role: MTD (Minimal Thread Device / child) — picks one parent, avoids the neighbor-maintenance obligations that were destabilizing the mesh under load when the C6 was an FTD router.

**Key sdkconfig flags (important — don't lose):**
- `CONFIG_ESP_CONSOLE_NONE=y` + `CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG=y` — USJ on the *secondary* (non-blocking) console slot, primary is none. Do **not** put USJ on the primary slot: primary TX is blocking, and when the C6 is powered from a dumb 5 V source (PD brick, Pi 5V header) with no USB host draining the CDC endpoint, log writes stall and drag OT/MQTT attach with them. Laptop hides this because the host drains the buffer. Both hardware UARTs are already claimed (UART0 = LiDAR, UART1 = Pi bridge), and the firmware doesn't use console input anywhere, so there's no reason to keep USJ as primary.
- `CONFIG_OPENTHREAD_CLI=n` — no CLI on this device. Required alongside `ESP_CONSOLE_NONE` because the `ot_examples_common` component's `ot_console.c` hard-errors at compile time when there's no primary console, and it's only compiled when `OPENTHREAD_CLI=y`. Disabling CLI also removes `otCliSetUserCommands` from the OT library, so we dropped the `esp_ot_cli_extension` managed-component dep in `platform/firmware/components/panel_platform/idf_component.yml` — the extension references those symbols unconditionally.
- `CONFIG_OPENTHREAD_NETWORK_AUTO_START=y` — brings up Thread on boot
- `CONFIG_OPENTHREAD_DNS_CLIENT=y` — enables OpenThread's DNS client (we override the discovered server but the infrastructure has to be present)
- `CONFIG_LWIP_USE_ESP_GETADDRINFO=y` — required; default resolver fails on IPv6-only networks
- `CONFIG_LWIP_IPV4` NOT set — disabled; Thread is IPv6-only, IPv4 in dual-stack causes `getaddrinfo` to fail the v4 lookup first and return error
- `CONFIG_LWIP_IPV6=y`
- `CONFIG_MQTT_BROKER_URI="mqtts://the-interstitial-space.duckdns.org:8883"`

**mqtt_cfg** lives in `platform/firmware/components/panel_platform/panel_net.c`:
```c
esp_mqtt_client_config_t mqtt_cfg = {
    .broker = {
        .address.uri = CONFIG_MQTT_BROKER_URI,
        .verification = {
            .certificate = (const char *)ca_cert_pem_start,
            // No skip_cert_common_name_check — full hostname verification on
        },
    },
    .credentials = {
        .username = CONFIG_MQTT_USERNAME,
        .client_id = CONFIG_MQTT_CLIENT_ID,
        .authentication = { .password = CONFIG_MQTT_PASSWORD },
    },
};
```

**Embedded cert:** `platform/firmware/components/panel_platform/certs/ca_cert.pem` contains ISRG Root X1 (Let's Encrypt root CA), valid until 2035-06-04. Source: https://letsencrypt.org/certs/isrgrootx1.pem. Trust the root, not the leaf — Mosquitto's cert renews every ~60 days via DuckDNS add-on, C6 doesn't notice because the chain still terminates at the same root.

## Build Order

1.  ~~**C6 firmware skeleton**~~ ✅ DONE
    - Fork ot_cli, add esp-mqtt
    - Connect to Mosquitto over Thread
    - Publish test message, verify from HA side

2.  ~~**HA IPv6 + TLS hostname verification**~~ ✅ DONE
    - Pinned static ULA on HA box
    - Set up AdGuard split-horizon DNS rewrite for the duckdns hostname → static ULA
    - Embedded ISRG Root X1 in C6 firmware (instead of leaf cert)
    - Removed `skip_cert_common_name_check`
    - Replaced fixed startup delay with OpenThread role-change callback
    - See "Lessons Learned" below for context

3.  ~~**UART protocol on C6**~~ ✅ DONE
    - Generic UART module (`panel_uart`) with line-framed protocol on UART1 @ 115200
    - MQTT data → UART lines, UART lines → MQTT publish (via `panel_net_publish`)
    - Verified loopback (TX↔RX jumper) end-to-end through HA
    - Also gated MQTT start on OMR address (not just role attach) so the first connect attempt no longer races OTBR's RA

4.  ~~**Pi dev workflow**~~ ✅ DONE (WiFi-disable deferred to deployment)
    - PL011 swapped onto GPIO 14/15 via `dtoverlay=disable-bt` in `/boot/firmware/config.txt`; serial console disabled
    - `platform/diagnostics/panel_test.py` — pyserial skeleton: reader thread prints incoming lines, stdin forwards to UART
    - WiFi-disable for production deferred until just before deployment (kept on for dev SSH)

5.  ~~**Wire C6 ↔ Pi**~~ ✅ DONE
    - C6 D6 (TX) ↔ Pi pin 10 (RXD), C6 D7 (RX) ↔ Pi pin 8 (TXD), GND shared on Pi pin 6
    - Verified both directions: `hello loopback` from HA reaches the Pi; `ping` from the Pi reaches `panel/test/from_pi` in HA

6.  ~~**Waveshare display**~~ ✅ DONE
    - HDMI display + USB touch working via direct framebuffer (`/dev/fb0`) + evdev
    - `platform/diagnostics/touch_test.py` draws crosshair + tap markers, scales `ABS_MT_POSITION_X/Y` to framebuffer dims, queries geometry via `FBIOGET_VSCREENINFO`

7.  ~~**UI framework decision + monorepo scaffold**~~ ✅ DONE
    - Vue 3 + Vite + Pinia chosen for the UI; served via Chromium-kiosk under `cage` Wayland compositor on Pi OS Lite
    - Custom HA integration chosen over pyscript / sprawling automations — better fits the multi-panel future
    - Topic schema locked to `state/` `set/` `cmd/` namespaces (Option B)
    - Monorepo skeleton landed: `platform/{firmware,bridge,ui-core,ha-integration,deploy,diagnostics}` + `panels/feeding_control/{firmware,ui,ha,manifest.yaml}`
    - Existing firmware migrated; `app_main.c` collapsed to three platform/product calls

8.  ~~**Sensors**~~ ✅ DONE (pivoted from Pi+MCP3008 to all-on-C6)
    - TEMT6000 on C6 ADC1 CH0 (D0) via `panel_platform/panel_sensors.c`
    - TF-Mini Plus on C6 UART0 (D3 RX, D4 TX) via `panel_platform/panel_lidar.c` — 9-byte protocol parser with checksum validation
    - `panel_app` periodic publisher: proximity at 1 Hz, ambient at 5 s; each emits both an MQTT state topic (retained) and a JSON UART line for the Pi
    - Console log shows `ambient raw=X mv=Y  lidar dist=Z cm strength=W` every 5 s; `mosquitto_sub` on `thread_panel/feeding_control/state/+` shows live values

9.  ~~**Pi bridge (`platform/bridge/`)**~~ ✅ DONE (control owners deferred)
    - asyncio daemon: `pyserial-asyncio` UART link + `websockets` server in one event loop
    - State cache (latest message per `type:name` key) replays on each new WS connect
    - Auto-reconnect on UART disconnect with 1s backoff
    - Snapshot/broadcast race fixed via `asyncio.Lock` (new client can't slip in between cache update and broadcast)
    - `platform/bridge/test_client.py` for smoke testing
    - Verified end-to-end: sensor data flows C6 → UART → bridge → WS → client; client → WS → bridge → UART → C6 also works
    - **Deferred**: panel-itself control owners (brightness, screen, wifi) — wire up after the UI exists and we know what controls actually need to act

10. ~~**UI scaffold (`panels/feeding_control/ui/`)**~~ ✅ DONE (real layout/components TBD)
    - Vue 3 + Vite + Pinia + TypeScript + bare scoped styles (no UI lib, no Tailwind)
    - `stores/panel.ts` wraps the bridge WebSocket: connect/reconnect with 1s backoff, snapshot replay on connect, reactive `haAvailability` / `roster` / `entities`, generic `callService(entityId, action, data)` action helper
    - `App.vue` scaffold view: connection pill, proximity card, ambient card, one "Toggle Light" smoke-test button wired to `callService`
    - Discriminated unions for incoming/outgoing WS messages in `src/types.ts`
    - WS URL via `import.meta.env.VITE_WS_URL`, defaults to `ws://${location.hostname}:8765`; `.env.local` for Mac→Pi dev
    - Real layout, controls, and `platform/ui-core` extraction are step 14's scope.

11. ~~**Custom HA integration: generic entity forwarder (`custom_components/thread_panel/`) + C6 availability gating**~~ ✅ DONE 2026-04-23 — end-to-end verified: toggle button in UI → WS → bridge → UART → C6 → MQTT → integration → HA service call → entity state update flows back through the same pipe and updates the UI store. Known parallel issue: Thread mesh flapping causes intermittent command loss (see Technical Debt → Outstanding).

    HA side (`custom_components/thread_panel/` — at the repo root so HACS accepts it):
    - Config flow accepts the manifest YAML pasted directly. Reference templates live at `panels/<id>/ha/manifest.yaml` in the repo; users copy, adjust entity_ids, paste. (Originally planned as path-based in Day 1 with paste as Day-2 migration — promoted to Day 1 because HACS doesn't deploy `panels/<id>/ha/` onto the HA box, so there's no filesystem path to point at. Day-2 now: an interactive entity picker.)
    - On setup:
      - Clean up any retained `state/entity/*` topics not in the current manifest (avoid zombie retained messages from prior configs).
      - Register `async_track_state_change_event` for each declared entity.
      - Publish initial `state/entity/<entity_id>` snapshots (retained). Missing entities get `{"state": "unknown"}` + a log warning.
      - Publish `state/_roster` (retained).
      - Flip `ha_availability → online` *last*, so "online" means "you can trust my retained topics."
    - State listener: apply Dial A filtering (state change OR allowlisted attribute change); publish full `{state, attributes}` snapshot.
    - Service dispatch: subscribe to `cmd/call_service`, validate entity_id, dispatch via `hass.services.async_call(...)`.
    - Shutdown: publish `ha_availability → offline`; LWT set for unclean exits.
    - `panels/<id>/ha/` is a hatch for non-entity-shaped product data; expected to be empty for `feeding_control` V1.

    Follow-ups (HA side — not blocking Phase B/C):
    - ~~Options flow for in-place reconfig~~ ✅ DONE 2026-04-24. `OptionsFlowHandler` lets users edit the manifest YAML in place; validation rejects any change that mutates `panel_id`. Stale-topic cleanup via the existing `Store` handles entity removal automatically on reload.
    - Roster `area` field — needs entity_registry + device_registry joins. Nice-to-have.

    C6 side (`panel_platform`):
    - Subscribe to `ha_availability`; forward value over UART as `{"type":"ha_availability","value":"..."}`.
    - Subscribe to `state/entity/#` and `state/_roster`. On every inbound message, wrap the payload with a typed envelope (`{"type":"entity_state","entity_id":"...",<state/attrs>}` or `{"type":"roster",<entities list>}`) and forward over UART. Retained semantics mean subscribe alone redelivers the full current snapshot to the Pi.
    - Route **outbound** UART commands from the Pi to the right MQTT topic. For V1: `{"type":"call_service",...}` lines publish to `thread_panel/<panel_id>/cmd/call_service` verbatim — the integration tolerates the extra `type` field.
    - Add in-RAM last-values cache for sensor publishes (ambient, proximity).
    - Gate periodic state publishes on `ha_availability == online`, and gate UART command routing on the same flag. On `offline → online` transition, republish current sensor values once before resuming normal cadence.

    Bridge side:
    - Consume `ha_availability` from UART, surface in WS snapshot + broadcasts.
    - Gate `call_service` commands: no-op (or reply with an error envelope) when `ha_availability != online`.

    UI side (platform-level only):
    - Expose `ha_availability` through the `panel` store so product UIs can render loading/offline overlays.
    - Product UIs choose their own UX for the offline state; platform just provides the signal.

12. **Panel-itself entity representation in HA** (in progress — approach chosen, MVP scope done 2026-04-23)

    Chosen approach: **Python entity classes inside `custom_components/thread_panel/`**. One device per panel (identified by `panel_id`), entities subscribe to the panel's own MQTT topics, availability gated on the C6's LWT-backed `availability` topic.

    Landed in the MVP:
    - `sensor.py` with `PanelProximitySensor` + `PanelAmbientBrightnessSensor`. They subscribe to `state/proximity` and `state/ambient_brightness` retained topics, expose `value` as the native reading and auxiliary fields (`strength`, `raw`, `mv`) as extra state attributes.
    - Device registration via `DeviceInfo(identifiers={(DOMAIN, panel_id)})`.
    - `__init__.py` forwards the SENSOR platform on config entry setup, unloads on teardown.
    - Firmware: `panel_net` now takes an availability topic via `panel_net_set_availability_topic()`. When set, the MQTT client is configured with an LWT that publishes `"offline"` retained on ungraceful disconnect, and `"online"` retained on each successful connect. `panel_app_init()` wires `PANEL_TOPIC_AVAILABILITY` through.

    Panel-itself controls landed 2026-04-23:
    - Firmware: C6 subscribes to `set/#` wildcard + `cmd/reboot_c6` + `cmd/reboot_pi`. Set/* gets wrapped as `panel_set` and forwarded over UART; cmd/reboot_c6 triggers `esp_restart()` locally; cmd/reboot_pi forwards as `panel_cmd`. Outbound UART `panel_state` messages get published to `state/<name>` retained.
    - Bridge: `panel_bridge/controls/` — one module per control (`screen.py`, `wifi.py`, `reboot.py`) + a dispatch registry. Each handler executes the system action (`vcgencmd`, `nmcli`, `sudo shutdown`) and emits `panel_state` back. Initial state is published at bridge startup so HA sees fresh values.
    - Integration: `switch.py` (screen_on, wifi_enabled) and `button.py` (reboot_pi, reboot_c6). Shared `entity.py` module hosts the device-info + availability subscription that all three platforms share.

    Sudoers note — reboot_pi + screen + wifi controls all need passwordless sudo. On the Pi, run `sudo visudo -f /etc/sudoers.d/panel-bridge` and add:

    ```
    chaddugas ALL=(root) NOPASSWD: /sbin/shutdown -r now
    chaddugas ALL=(root) NOPASSWD: /usr/bin/nmcli *
    chaddugas ALL=(root) NOPASSWD: /usr/bin/tee /sys/class/graphics/fb0/blank
    ```

    The broad `nmcli *` rule (vs. earlier narrow `nmcli radio wifi *`) is required by the wifi-credential-management work landed 2026-04-27 — see below.

    Wi-Fi credential management landed 2026-04-27:
    - **Motivation**: pet-feeder Pi lost its only NetworkManager connection profile (cause unconfirmed; bridge code only ever toggled the radio, never deleted profiles), leaving the device with no way back online except HDMI + USB keyboard on the tiny 6.25" display. Recovery was painful enough to justify building a HA-side recovery path.
    - Bridge: `controls/wifi_manage.py` — periodic 30 s scan via `nmcli -t -f IN-USE,SSID,SECURITY device wifi list --rescan no`, immediate scan via `cmd/wifi_scan`, profile add+activate via `cmd/wifi_connect`. Auto-detects `wpa-psk`/`sae`/`none` from the scan's SECURITY field; SAE adds `wifi-sec.pmf 3` since some kernels reject SAE without explicit PMF. Existing profile with the same name is deleted before re-add so credentials are always fresh.
    - Firmware: `panel_app.c` now subscribes to `cmd/wifi_connect` + `cmd/wifi_scan` and forwards both as `panel_cmd` envelopes over UART. The forwarding logic was generalized into a `forward_panel_cmd(name, data, ...)` helper (replacing the inline reboot_pi shape) so command payloads with data splice cleanly.
    - Integration: `select.py` (`PanelWifiNetworkSelect`) populated from retained `state/wifi_ssids`, with security info per SSID stashed in extra_state_attributes. `text.py` (`PanelWifiPasswordText`, mode=PASSWORD). `sensor.py` adds `PanelWifiSsidSensor` (current SSID) + `PanelWifiErrorSensor` (last connect error). `button.py` adds `PanelWifiScanButton` (one-shot rescan) and `PanelWifiConnectButton` (assembles `{ssid, password, security}` from the select+text and publishes to `cmd/wifi_connect`, then optimistically clears the password via `text.set_value`).
    - The select+text+button trio coordinates via a per-panel entity-id registry under `hass.data[DOMAIN]["entities"][panel_id]`, populated in each entity's `async_added_to_hass`. Avoids fragile entity_id slug guessing.

    Deferred:
    - **Brightness (NumberEntity)**: the Waveshare 6.25" HDMI display doesn't expose a `/sys/class/backlight/*` interface. Revisit when either (a) the hardware is swapped for something with a controllable backlight, or (b) we ship the kiosk compositor and can do a Wayland gamma-overlay software dim.
    - **Hidden SSIDs** in the network select: V1 only lists broadcast networks. Hidden SSIDs come back as empty strings in `nmcli -t` output and are filtered out. Add an "Other..." option that lets the user type an SSID into the password text alongside the password (or a second text entity) when there's a real need.
    - **Enterprise (802.1X) networks**: scan classifies them but the connect path rejects them (no key-mgmt mapping). Add when someone needs it.

13. ~~**OTA firmware updates over Thread**~~ ✅ DONE 2026-04-23
    - Motivation: the XIAO ESP32-C6 can't use USB and the 5V rail simultaneously. In the enclosure we can't easily pull the power-select pin, so USB flashing becomes impractical. Need a way to push new firmware without touching the board.
    - Approach decided 2026-04-23: **HTTP OTA over Thread, Mac-direct, no Pi involvement.** Mac builds, runs a transient HTTP server, publishes `cmd/ota` to the C6 with a firmware URL; C6 downloads via `esp_http_client`, writes to the idle OTA partition via ESP-IDF's `esp_ota_*` APIs, reboots. ESP-IDF's built-in app rollback: new firmware has a self-validation window after reboot; if it doesn't mark itself valid (crashes, fails to reach MQTT, etc.) the bootloader reverts on next reset. NAT64 on OTBR is enabled so the C6 can reach the Mac's IPv4 via its Thread IPv6 address. Pi is not in the OTA path; Pi WiFi can stay off.
    - Rejected alternative: UART flashing. XIAO C6 buttons (BOOT/RESET) aren't on pin headers, so automating the reset-into-download-mode sequence from the Pi would need fiddly SMD soldering to the button pads. HTTP OTA avoids all that.
    - Recovery if the firmware is bricked beyond rollback's reach: open the enclosure, disconnect 5V, plug USB, flash via `idf.py` as today. Inconvenient but not impossible.

    **E1 — Partition table + OTA-aware build config** (in progress): `partitions.csv` now has `nvs, otadata, phy_init, ota_0, ota_1`. NVS offset/size preserved so Thread credentials survive the migration. One USB flash (erasing just the otadata region, not NVS) moves the running firmware from `factory` to `ota_0`; after that, OTAs are self-sustaining.

    **E2 — OTA handler in firmware**: subscribe to `cmd/ota`, parse URL from payload, download via `esp_http_client` into the idle OTA partition, `esp_ota_set_boot_partition()`, reboot. After reboot on the new partition, the firmware's startup code runs self-checks (MQTT reconnect succeeds) and calls `esp_ota_mark_app_valid_cancel_rollback()` to commit. If the self-check fails or the app crashes before committing, bootloader reverts.

    **E3 — Mac-side `panel-ota` CLI tool**: lives in `tools/`. Builds firmware, starts `python3 -m http.server` in the build dir, detects Mac's LAN IP via kernel-route trick, publishes `cmd/ota` to `thread_panel/feeding_control/cmd/ota` with the URL, tails the MQTT `availability` topic to watch for the C6's reboot (offline flap then online), shuts down the HTTP server.

14. **`feeding_control` product UI (`panels/feeding_control/ui/`)**
    - Real UI for the pet feeder: schedule view, feed/skip/toggle controls, panel-itself surfaces (screen, wifi status), offline overlay driven by `ha_availability`.
    - Built against live data from steps 11/12.
    - ~~`platform/ui-core/` extraction~~ ✅ DONE 2026-04-24 as part of cleanup. Platform-shaped code (WS connection + reconnect, snapshot replay, availability, entity-state, `callService`) now lives in `platform/ui-core/src/` and is consumed via the `@thread-panel/ui-core` path alias. Product UIs only carry layout + product-specific behavior.
    - Panel-itself control owners in the bridge (screen, wifi, reboot) landed in step 11 D2 — UI can call them directly via the existing switch/button entities in HA or the WS `callService` (TBD: product UI decides which route).
    - Brightness remains deferred — Waveshare display has no software-controllable backlight; revisit in step 16 via Wayland gamma overlay after cage lands.

15. **Enclosure**
    - Shapr3D design
    - P1S print
    - Cable management

16. **Kiosk deployment** (in progress 2026-04-28)
    - ✅ Bridge systemd unit landed at `platform/deploy/panel-bridge.service` (2026-04-23) — the bridge auto-starts on boot, pulls latest on each start, and restarts on failure.
    - ✅ UI deploy path settled (2026-04-27): build via `yarn build` inside `cut-release`, commit `dist/` to git, Pi pulls dist/ on each `panel-bridge.service` restart. Releases are the deploy unit; UI source pushes between releases don't update what the kiosk serves until the next `cut-release`.
    - ✅ `panel-ui.service` (2026-04-27) — `python3 -m http.server` serving `panels/feeding_control/ui/dist/` on `127.0.0.1:8080`.
    - ✅ `install-pi.sh` (2026-04-27) — idempotent: templates units for non-`pi` users, adds the user to `video,input,render`, disables `getty@tty1`, symlinks units, restarts bridge + UI server.
    - ✅ Kiosk renderer pivot from Chromium to cog (2026-04-28). First attempt used cage + Chromium kiosk, but Chromium OOM-loops on the Pi Zero 2 W's 512 MB RAM (the boot loop visible on tty1 was systemd restarting cage every 2 s after Chromium got reaped). Switched to [`cog`](https://github.com/Igalia/cog), the WPE WebKit single-app launcher: ~100-150 MB resident, renders straight to DRM (no compositor), supports modern Vue 3 / WebSocket / variable fonts. cage dropped from the stack entirely. `cog.service` replaces `cage.service`; `install-pi.sh` cleans up the legacy cage symlink on re-run.

## V2 / Post-V1 follow-ups

Not blocking V1 ship, but called out so we don't lose them.

- **`install-pi.sh` full bootstrap from a fresh Pi OS Lite.** Currently the script assumes the user has already cloned the repo, set up the bridge venv, and apt-installed cog. Fold all of that in so a brand-new Pi can be brought up with one command. While we're there, fold in the steps from earlier build phases that still live as prose in this doc: `dtoverlay=disable-bt` for PL011 on GPIO 14/15 (step 4), serial-console disable, NetworkManager bring-up, and any other one-time setup. End state: image SD → boot → ssh in → run script → reboot → kiosk runs.
- **Kiosk-renderer choice via flag.** `install-pi.sh --cog` (Pi Zero 2 W, 512 MB) vs `install-pi.sh --cage` (Pi 4+, 1 GB+) so the same script works across hardware. Default to cog on detected ≤768 MB, cage on more. Either path apt-installs the right packages and symlinks the matching unit.
- **"Unconfigured panel" splash in `platform/ui-core`.** When a panel boots without a product UI configured (`panel-ui.service` serving an empty/missing `dist/`, or no panel selected), show a friendly splash with setup instructions instead of a directory listing or blank screen. The splash itself ships as part of ui-core so every panel inherits it for free.
- **Device → product binding.** Currently `panel-ui.service` and `cog.service` hard-code `panels/feeding_control/ui/dist/`. To support a fleet running different products (feeding_control on one Pi, something else on another), the device needs a way to declare which product it runs. Likely shape: a single config file (e.g. `/etc/thread_panel/device.conf` or a checked-in `device/<hostname>.conf`) that names the product; the systemd units read from it via `EnvironmentFile=`. Couples cleanly with the unconfigured-splash item — when no binding is set, the splash takes over.
- **Repo reorg to support the above.** Likely lifts more of the kiosk shell (Vue app entry, theme system, splash, presence) into `platform/ui-core/` so panels only carry product-specific surfaces, and introduces a top-level concept (folder or config layer) for "which device runs which product." Tackle this together with the items above — they're all the same shape.

## Technical Debt

### Resolved

- ~~USB-Serial-JTAG as primary console deadlocked Thread attach on non-host power~~ — fixed 2026-04-24. C6 appeared dead (lights on, no Thread) when powered from a PD wall-wart or the Pi's 5V header, but attached fine via laptop USB. Cause: `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` puts USJ on the *primary* console slot, whose TX path blocks when the CDC endpoint has no host draining it. Log writes during OT/MQTT bring-up filled the tiny FIFO and stalled the logging tasks. Fix: moved USJ to the *secondary* slot (`CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG=y`) whose TX path is non-blocking (drops bytes after 50 ms if no host reads), and set primary to NONE. No loss of functionality — firmware doesn't use console input, and both hardware UARTs were already claimed anyway.
- ~~panel-bridge.sh aborts on no-network pip install~~ — fixed 2026-04-24. `pip install -e` failure now logs a warning and continues with stale deps; marker isn't touched so next boot retries. Survives WiFi-off production boots where `pyproject.toml` may look newer-than-marker.
- ~~panel-bridge.sh git pull races DNS at boot~~ — fixed 2026-04-27. Even with `After=network-online.target` + `Wants=network-online.target` in the unit, NetworkManager-managed Pis can complete association before DNS is actually usable, so the first `git pull` attempt would fail with `Could not resolve hostname github.com` and the bridge would start with stale code (silently — the script already tolerates pull failure). Now retries the pull 5× with 5 s gaps before giving up. Symptom in logs: `ssh: Could not resolve hostname github.com: Temporary failure in name resolution` immediately after `→ Pulling latest...`, with `ping github.com` from the same shell working a few seconds later.
- ~~TLS hostname verification disabled~~ — fixed by switching to ISRG Root X1 as embedded CA + duckdns hostname in URI + AdGuard rewrite for resolution.
- ~~Hardcoded HA IPv6 fragility (regenerated on reboot)~~ — fixed by pinning static ULA `fd00:9db1:1410:d98c::10` on HA via `ha network update`. URI now uses hostname, not IP literal.
- ~~Thread mesh flapping under load~~ — fixed by switching C6 from FTD to MTD in `sdkconfig.defaults` (`CONFIG_OPENTHREAD_MTD=y`). As a Minimal Thread Device, the C6 picks one parent and stops juggling multi-router obligations. Verified 2026-04-23 via runtime `mode rn` test — mesh errors dropped to normal background levels, commands flowed reliably. The baseline of "occasional `Failed to process Link Request: InvalidState`" + "rare isolated `NoAck`" is expected Thread mesh noise, not our problem.
- ~~Forwarded entity payloads >1024 bytes silently dropped~~ — fixed 2026-04-27. esp-mqtt's default input buffer is 1024 bytes; anything larger is delivered as multiple `MQTT_EVENT_DATA` callbacks (one per buffer-full) with `current_data_offset` / `total_data_len` set. `panel_app.c`'s `forward_entity_state` / `forward_roster` / `forward_panel_set` helpers all treat each callback as a complete message and validate that the payload starts with `{` and ends with `}` — so the first chunk fails the trailing-`}` check, the second fails the leading-`{` check, both get dropped. Manifested as the PetLibro feeding-schedule binary_sensor (4 plans of nested attrs ≈ 1.3 KB) and the manual_feed_quantity select (48 unicode-fraction options) never reaching the UI while smaller sensors arrived fine. Fixed by setting `mqtt_cfg.buffer.size = 4096` in [`panel_net.c`](../platform/firmware/components/panel_platform/panel_net.c). Robust long-term fix would also handle multi-callback fragmentation in the forwarders, but bumping the buffer covers V1 payloads with headroom.

### Outstanding

- MQTT credentials in sdkconfig (plaintext) — keep sdkconfig out of version control. Move to NVS provisioning eventually, especially if scaling to multiple devices that should have distinct identities.
- Schedule data shape is deferred to whatever PetLibro's HA entity exposes as attributes — the manifest allowlist bounds what gets forwarded, but the UI still has to decode whatever shape HA hands us. Nail down when writing the product UI's schedule view.
- AdGuard's listen-interface scan happens at startup — adding new IPv6 addresses to HA after AdGuard is running requires an AdGuard restart for it to bind to the new address. Worth knowing if the static ULA is ever reassigned.
- C6 has no persistent state beyond the Thread dataset and build-time sdkconfig. If/when runtime-mutable state appears (per-panel identity, last-known-values across reboots, user-editable config), prefer stashing it on the Pi's SD card via a UART blob-store protocol over writing to C6 NVS — SD endurance beats ESP32 flash for frequent writes, and the Pi already has a filesystem. Not needed for anything currently planned.

## Lessons Learned (Step 2)

The original build doc framed this as "regenerate the cert with the IPv6 in SAN." The actual solution turned out to be cleaner because the duckdns/Let's Encrypt cert infrastructure was already in place from a previous project (the touch-kio Pi). The right move was to extend that infrastructure rather than build a parallel one.

Key decisions and their reasoning:

- **Trust the root, not the leaf.** Embedding `fullchain.pem` (the leaf cert) on the C6 would have broken every 60 days when LE renewed. Embedding ISRG Root X1 is stable until 2035 and survives unlimited renewals.
- **Use a hostname in the URI, not an IP literal.** Even with a static IP pinned, the literal-in-firmware approach is brittle for a fleet — every IP change requires reflashing every device. The duckdns hostname is stable and reusable across devices.
- **Split-horizon DNS via AdGuard handles the IPv6-on-LAN case.** Public DNS for the duckdns name returns the home's public IPv4, which is useless to a Thread-only IPv6 device. AdGuard rewrites the same name to the LAN IPv6, intercepting before the query leaves the LAN. Public and private resolutions don't collide.
- **OpenThread's default DNS server (Google) doesn't know about the AdGuard rewrite.** Had to override OpenThread's discovered DNS in firmware with AdGuard's IPv6 explicitly. If multiple Thread devices need this, consider whether it's worth investigating OTBR upstream DNS configuration once that becomes exposable in the HA add-on.
- **OpenThread role-change callback is the right startup signal.** A fixed `vTaskDelay(30s)` worked but was both slow and brittle. The callback approach (`otSetStateChangedCallback` watching for `OT_CHANGED_THREAD_ROLE` reaching child/router/leader) starts MQTT in <1 second of attach and adapts to slow joins gracefully.
- **First MQTT connect attempt may fail; reconnect logic handles it.** OTBR's route advertisement into Thread takes a few seconds after the C6 attaches. Default MQTT reconnect catches this transparently — the device shows MQTT_EVENT_CONNECTED on the second or third attempt without intervention. Fine to leave as-is for a panel; would need different handling for battery-powered transmit-and-sleep devices.

For future Thread devices in this fleet: the entire pattern (cert, hostname, AdGuard rewrite, DNS override) is reusable. New devices need only the firmware template, not new infrastructure.

## Lessons Learned (Step 8: Sensors-on-C6 pivot)

- **Original plan called for MCP3008 ADC on the Pi** because the Pi has zero analog inputs. Pivoted when the user noted they didn't have one on hand and asked if the C6 could do it. C6 has SAR ADC1 with 6 channels on GPIO0–6 — D0/D1/D2 on the XIAO are ADC-capable.
- **Sensors on C6 is genuinely better, not just "fine because no MCP3008."** The data flow is more direct: sensor → C6 → MQTT → HA *and* sensor → C6 → UART → Pi. The MCP3008 path would have routed sensor data Pi → UART → C6 → MQTT, with the Pi as middleman for state it doesn't really own.
- **Source-of-truth rule clarification.** "Pi owns panel-itself state" was for *bidirectional* entities (brightness, screen_on, wifi — things HA can both read and command). Read-only sensors (proximity, ambient) have no command side, so source-of-truth is wherever the sensor physically lives.
- **TEMT6000 needs 3.3V power** specifically because its output range is 0..VCC. Running it at 5V would put up to 5V on the C6's ADC pin (max 3.3V tolerant). The part *accepts* 5V supply per spec, but doing so would damage the MCU. Rule of thumb: any analog sensor feeding an MCU ADC, keep VCC ≤ ADC max input or add a divider.
- **TF-Mini Plus is 5V-supplied with 3.3V-compatible TTL output.** No level shifter needed on the UART line even though VCC is 5V — the signaling is 3.3V.
- **C6 UART0 is free for repurposing when console is on USB-Serial-JTAG.** ESP-IDF GPIO matrix lets us route UART0 to D3/D4 without conflicting with the UART1 (D6/D7) Pi link.

## Lessons Learned (Step 7: Architecture & scaffold)

- **Populate `platform/` from day one for things that are obviously device-agnostic.** "Don't extract until two consumers" is good general wisdom against premature abstraction, but it's overcautious when the platform definition is the project thesis. The C6 firmware infra, Pi bridge core, panel-itself entities, and kiosk launcher all qualify — they're identical for any future panel. The interfaces *between* platform and product (manifest schema, bridges registry, ui-core component vocabulary) are what should stay narrow until panel #2 forces them.
- **Custom HA integration over pyscript.** Pyscript is great for prototyping; it doesn't scale to multiple panel devices because it can't naturally express "this group of entities belongs to *this* panel." A custom integration with a config flow + per-panel bridges registry is ~500 LOC and pays back the moment you add panel #2. Migrating later is rewriting; doing it upfront is just doing it once.
- **HA integrations don't need broker config.** Running inside HA Core, an integration uses the existing MQTT integration via service calls — no host/port/auth/certs at all. The "easy MQTT" patterns you may remember from add-ons (Supervisor Services API) and from ESPHome devices (native API, not MQTT) don't apply to external devices like the C6 — but they do mean the HA-side code stays trivially simple.
- **Vue 3 + Vite + Pinia for the UI.** With Chromium-as-runtime, framework size is rounding error against Chromium's ~150–250 MB. Pick on DX, not bundle. Vite gives you SFCs + scoped styles + HMR. Pinia is the right level of state mgmt for a WS-driven app even though it might feel like overkill at first — the moment you want optimistic UI, derived state, or testable mutations it pays off.
- **Cage for the kiosk launcher**, not full X or a desktop environment. Wayland-native, purpose-built for "run one fullscreen app." `sudo apt install cage chromium` and a one-line systemd unit is the entire kiosk setup on Pi OS Lite.

## Lessons Learned (Steps 4–5: Pi UART bring-up)

- **Floating UART RX has a distinctive signature.** Garbled or partial bytes appearing seconds-to-minutes after the last expected transmission, with nothing else publishing on the bus, means the RX line isn't being driven — noise occasionally trips the start-bit detector. A truly disconnected line shows zero bytes; a *floating* line shows phantom bytes. Spent a session theorizing about mini-UART vs PL011 and HA publish behavior before recognizing this pattern.
- **Isolate the wire from the script first.** `stty -F /dev/serial0 115200 raw -echo && cat /dev/serial0` reads raw bytes from the kernel UART driver — no Python in the path. If `cat` and the script both show nothing, the script isn't the bug.
- **Pi headers may need to be soldered, and a cold joint is easy to miss.** A bad solder joint on the GPIO header gives the floating-RX signature above and looks correct visually. Multimeter continuity from the dupont end to the SoC pad on the underside is the definitive test.
- **One step per debug message.** Bundling "try A, then B, then C" into a single response forces the user to either skip ahead blindly when A produces an unexpected result or stop mid-list. One focused diagnostic per turn, wait for the result, then propose the next.

## What's Deliberately Not in V1

- Matter (rejected: HA integration doesn't auto-surface custom clusters)
- WiFi on Pi in production (dev only — re-enableable via MQTT command)
- OTBR Thread 1.4 + native mDNS beta (working setup is more valuable than possible feature improvements; revisit if/when it goes stable)
- HACS-installable distribution of the integration (manual `git clone` into `custom_components/` is fine for now; HACS later if anyone else wants it)
- OTA C6 firmware updates (USB flashing is fine for a fleet of single-digit panels)
- Per-panel unique device identities provisioned via NVS — currently every panel uses the same MQTT credentials from sdkconfig; needs revisiting if the fleet grows

## Open Questions (to answer during build)

- Manifest schema beyond v1 (entity_id + attribute allowlist) — pin down once a second panel or more exotic entity shape (e.g. a group, a template) forces real decisions.
- Bridge ↔ UI WebSocket message envelope (envelope vs. raw JSON, error/heartbeat semantics, how `call_service` failures surface back to the UI).
- Whether `cmd/call_service` ever needs a correlation id + reply topic. V1 is fire-and-forget (integration logs failures, nothing comes back). Revisit if a product UI actually wants per-command success/failure feedback.

## Proven Facts (to stop re-litigating)

- Thread mesh is healthy, routes to LAN, supports new devices
- C6 can reach HA box's LAN IPv6 over Thread
- C6 MQTT client connects to Mosquitto with full TLS auth + hostname verification over Thread
- C6 can do DNS resolution through Thread → AdGuard at HA's static ULA
- ESP-IDF on IPv6-only network requires `LWIP_USE_ESP_GETADDRINFO=y` + `LWIP_IPV4` disabled
- ESP-IDF v6.0 + EIM + XIAO C6 dev loop works on macOS 26
- OpenThread CLI dataset commissioning against existing OTBR works
- HA MQTT Discovery via a custom device is a standard, supported path
- HAOS static IPv6 is configurable via `ha network update <iface> --ipv6-method static --ipv6-address <addr>/<prefix>` from the Supervisor CLI; doesn't require host shell access
- AdGuard re-binds to interfaces only at startup; new HA IPv6 addresses require an AdGuard restart to be picked up
- Let's Encrypt cert chains via the E7 ECDSA intermediate terminate at ISRG Root X1 (the original RSA root), not X2 — embedding X1 is sufficient for current LE certs
- C6 ↔ Pi line-framed UART bridge works at 115200 over the Pi's PL011 (`ttyAMA0`/`/dev/serial0`) once `dtoverlay=disable-bt` is in `/boot/firmware/config.txt`
- Both ESP32-C6 (3.3V) and Raspberry Pi GPIO (3.3V) tolerate direct UART connection — no level shifter needed
- Pi's 3V3 pin cannot source a XIAO ESP32-C6 (sags below brownout); use the Pi's 5V pin into the C6's 5V pin instead
- Waveshare 6.25" display drives via plain HDMI (no special drivers); touch shows up as a USB HID evdev device whose name contains "waveshare", reports multitouch via `ABS_MT_POSITION_X/Y` + `BTN_TOUCH`
- Direct framebuffer rendering on Pi Zero 2 W via `/dev/fb0` + PIL `convert("BGR;16")` is viable for simple UI; expect that per-frame full-screen RGB565 conversion will be the bottleneck for high refresh rates
- HA custom integrations (running in HA Core) use HA's existing MQTT connection via `hass.services.async_call("mqtt", "publish", ...)` — no broker config, no Supervisor token, no certs. Distinct from add-ons (which use Supervisor Services API + internal Docker network) and from external devices (which need full broker auth + TLS).
- ESPHome devices over Thread use the ESPHome **native API** (not MQTT) — that's why no certs are required. Different protocol entirely; not a "MQTT minus the cert dance" pattern.
- ESP32-C6 has SAR ADC1 with channels on GPIO0–6 (XIAO C6: D0/D1/D2 are ADC-capable). DB_12 attenuation gives ~0..3.1V usable input range, plenty for 3.3V analog sensors.
- ESP32-C6 has 2 standard UARTs (UART0/UART1) plus an LP UART. UART0 is free for application use when the console is configured via USB-Serial-JTAG; pins are remappable via the GPIO matrix.
- TF-Mini Plus default UART output: 9-byte frames at 100 Hz, header `0x59 0x59`, distance in cm as little-endian uint16, checksum is sum of first 8 bytes & 0xFF.
