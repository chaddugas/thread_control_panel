# Thread Control Panel — agent notes

A platform for building no-WiFi, Thread-based touchscreen control panels for Home Assistant, plus its first product (`feeding_control` — pet feeder UI).

## Read this first

**Two build-plan docs:**

- **[`docs/build_plan_v1.md`](docs/build_plan_v1.md)** — historical record of V1 (shipped 2026-04-28) and reference for current production state: MQTT topic schema, UART protocol, sensor wiring, panel-itself entity contract, lessons learned. Read this for context on how things currently work.
- **[`docs/build_plan_v2/`](docs/build_plan_v2/)** — active work, split into per-section files. Start at [`README.md`](docs/build_plan_v2/README.md) for status + navigation; the active phase is [`phase2_polish.md`](docs/build_plan_v2/phase2_polish.md), with cross-cutting notes (lessons / proven facts / tech debt) in [`notes.md`](docs/build_plan_v2/notes.md).

Treat updating the active doc (v2) as part of every meaningful change — strike through finished steps with `✅ DONE`, move the `(next up)` marker, log learnings/invariants/debt in the existing sections. The "Keeping this current" section near the top of each doc spells out the convention. Edit v1 only when correcting historical inaccuracies, or when V2 has shipped a piece that supersedes a v1 invariant (mark the v1 section as superseded with a pointer to v2).

## Architecture (one-paragraph)

XIAO ESP32-C6 (Thread + MQTT-over-TLS to Mosquitto on the HA box) ↔ UART ↔ Raspberry Pi Zero 2 W (Vue 3 + Vite + Pinia in Chromium-kiosk under `cage`, Python WebSocket bridge, sensors). HA-side is a custom integration (`thread_panel`) that bridges per-panel data sources to MQTT. Sensors live on the C6 (TEMT6000 ambient on ADC, TF-Mini Plus LiDAR on UART), not the Pi.

## Repo layout

```
hacs.json                       # HACS metadata (zip_release: true — HACS pulls release artifacts)
platform/                       # device-agnostic, shared by every panel
├── firmware/components/panel_platform/   # ESP-IDF component
├── bridge/                     # Pi Python WS+UART daemon (panel_bridge package)
├── integration/thread_panel/   # HA custom integration (V2: moved from repo root)
├── ui-core/                    # Shared Vue+Pinia primitives (TBD)
├── deploy/                     # systemd units, install scripts (TBD)
└── diagnostics/                # panel_test.py, touch_test.py
panels/feeding_control/         # first product
├── firmware/                   # ESP-IDF project; depends on panel_platform
├── ui/                         # Vue+Vite+TS+Pinia app
└── ha/                         # reference manifest template + hatch for product-specific HA-side Python
```

## Conventions

1. **Platform/product split is the architectural backbone.** Anything device-agnostic (would be identical for any future panel) goes in `platform/`. Anything product-specific (UI, MQTT topic specifics, `panel_app.c` behavior, reference manifest) goes in `panels/<id>/`. The `thread_panel` HA integration is platform (one install handles every panel) and lives under `platform/integration/thread_panel/`. HACS consumes it via release-zip artifacts (`hacs.json` `zip_release: true`) rather than reading the repo root.

2. **MQTT topic schema:** `thread_panel/<panel_id>/{state,set,cmd}/<entity>` plus `availability` and `ha_availability` at the top level. Panel-itself entities (reboot, wifi, brightness, screen, sensors) are platform-shared. Product entities are forwarded generically via `state/entity/<entity_id>` + `cmd/call_service`, driven by a per-panel manifest.

3. **Custom HA integration over pyscript or automations** for HA-side bridging. Integration is a generic entity forwarder; per-product reference manifests live in `panels/<id>/ha/` and are pasted into the config flow.

4. **Sensors are on the C6**, not the Pi. C6 has SAR ADC1 (D0/D1/D2 = ADC) and spare UARTs. Data flow: sensor → C6 → MQTT (HA) and sensor → C6 → UART → Pi (UI). Originally planned via MCP3008 on the Pi; pivoted because the C6 has built-in ADC and the path is more direct.

## How the user works

- **Always read both build-plan docs first** ([v1](docs/build_plan_v1.md) for current state, [v2](docs/build_plan_v2/README.md) for active work). They capture decisions and rationale that don't appear elsewhere.
- **Stop at "ready to build" on firmware work** — the user runs builds, flashes, and hardware-in-the-loop verification themselves. Don't auto-run `idf.py build/flash/monitor`.
- **One focused step per message during debugging or hardware bring-up.** Bundling "try A, then B, then C" forces the user to either skip ahead blindly or stop mid-list. Wait for the result before proposing the next step.
- **Use the `idf` shell alias** to enter the ESP-IDF v6.0 environment when builds are required (don't source the activate script directly).
- **Maintain `.gitmessage.txt` as you change things.** It's the staging area for the next commit message — first line is the subject, the rest is the body, written in the style of recent commits (per-file/per-component description, technical detail, why-not-just-what). Update it when you make a meaningful change and again any time you make follow-up changes that affect what the next commit should say. The user reads from this file when running the actual commit, so a stale or missing message means they get the previous commit's text or no message at all.
- **No code shortcuts.** The user is using this project as a learning vehicle for ESP-IDF / C / Python / Vue / shell — and explicitly wants to be able to write firmware and Pi-side code with less agentic assistance over time. Don't take shortcuts or insert non-best-practice patterns just to ship faster. Write canonical, idiomatic code; surface trade-offs honestly when the "right" approach is significantly more work; leave existing code better than you found it on natural opportunities (single related improvement when you're already in the file, not a sweeping refactor). "It's quicker this way — we'll fix it later" is not a valid reason. Real exceptions exist (one-line workarounds for documented upstream bugs with a tracked ticket and explanatory comment) but need to be specific.
- **End action-requiring messages with a numbered checklist.** When a response asks the user to take action — run a command, flash firmware, observe a journal, click in HA, paste back results — keep all the explanatory prose / context / expected results above, then add a `## What I need you to do` section at the end that reiterates the steps as a numbered list. Each step prefixed with a context tag (`**[Mac]**`, `**[Pi SSH]**`, `**[HA UI]**`, etc.) so it's obvious where the action happens. Sequential by default; mark tandem / "leave running" steps explicitly ("While #N is running, ..."); commands inline as code blocks. Reason: prevents the user from executing snippets out of order while reading the message top-to-bottom.
- **Major-doc editing conventions** — see [`docs/build_plan_v2/README.md` "Keeping this current"](docs/build_plan_v2/README.md) (applies to any doc under `docs/`, not just v2). Highlights: surface non-discussed additions via `AskUserQuestion` (Approve / Discuss / Reject), with multi-round if >4 important items; process the user's `#doc:` shorthand by default (with `#ask` per-bullet escape for items the user wants AskUserQuestion-confirmed); split sections to their own files when they exceed ~3000 words or are naturally standalone-loadable.

## Useful commands

| Task | From | Command |
|---|---|---|
| Build/flash firmware | Mac | `cd panels/feeding_control/firmware && idf && idf.py build flash monitor` |
| Install/upgrade panel | Pi | `curl -sSL https://github.com/chaddugas/thread_control_panel/releases/latest/download/install-pi.sh \| bash` (or pass a specific version) |
| Run bridge foreground | Pi | `sudo systemctl stop panel-bridge && cd /opt/panel/current/bridge && .venv/bin/python -m panel_bridge` (Ctrl-C to stop, then `sudo systemctl start panel-bridge`) |
| Bridge smoke test | Pi or Mac | `python test_client.py [ws://host:8765]` |
| Run UI dev server | Mac | `cd panels/feeding_control/ui && yarn dev` |
| Type-check UI | Mac | `cd panels/feeding_control/ui && yarn type-check` |

## Lessons worth not re-discovering

(See [`docs/build_plan_v1.md`](docs/build_plan_v1.md) for the full V1 list under each "Lessons Learned" section; V2 lessons accumulate in [`docs/build_plan_v2/notes.md`](docs/build_plan_v2/notes.md). Highlights:)

- **Floating UART RX = phantom bytes.** Garbled bytes appearing seconds after the last expected transmission, with nothing else on the bus, means the RX line isn't being driven (loose wire / cold solder joint). Truly disconnected line shows zero bytes; floating shows phantom bytes.
- **TLS hostname in MQTT URI + AdGuard split-horizon DNS** is what makes IPv6-only Thread devices reachable over TLS. Embed ISRG Root X1 (not the leaf), override OpenThread's discovered DNS with AdGuard's ULA.
- **Trust the root, not the leaf.** Cert renewal every 60 days happens automatically; root is good until 2035.
- **Pi's 3V3 pin can't source a XIAO C6.** Use Pi 5V → C6 5V instead. The 3V3 rail sags.
- **HA custom integrations don't need broker config.** Run inside HA Core, use `hass.services.async_call("mqtt", "publish", ...)`. The "easy MQTT" patterns from add-ons (Supervisor Services API) and ESPHome (native protocol over Thread) don't apply to external devices like the C6 — but the integration code stays trivially simple.
