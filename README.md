# Thread Control Panel

> ⚠️ This is a personal project for my own homelab. I'm not accepting issues, PRs, or support requests. You're welcome to fork and adapt — you're on your own.

A platform for building no-WiFi, Thread-based touchscreen control panels for Home Assistant.

Each panel pairs a Raspberry Pi Zero 2 W (display + touch + sensors) with a Seeed XIAO ESP32-C6 (Thread + MQTT-over-TLS). The Pi has no network in production; all HA traffic flows through the C6 over the Thread mesh.

## Install

### Pi (panel host)

SSH to the Pi, then download `install-pi.sh` from the appropriate release and run it. The script prompts for MQTT credentials on first run, downloads release artifacts from GitHub, sets up systemd units, and starts the bridge + UI services.

```bash
# Latest stable
curl -sSL https://github.com/chaddugas/thread_control_panel/releases/latest/download/install-pi.sh -o /tmp/install-pi.sh
bash /tmp/install-pi.sh

# Specific version (required for prereleases — the "latest" URL and the
# script's internal default both use GitHub's /releases/latest API, which
# skips prereleases)
curl -sSL https://github.com/chaddugas/thread_control_panel/releases/download/v<VERSION>/install-pi.sh -o /tmp/install-pi.sh
bash /tmp/install-pi.sh v<VERSION>
```

The download-then-run pattern (rather than `curl ... | bash`) is required for the credentials prompt to read from your terminal rather than the consumed script body.

### Home Assistant integration

Install via HACS as a custom repository — point HACS at this repo URL. Update notifications surface in HACS' UI; the integration ships as `thread_panel.zip` per release and HACS handles install + upgrade.

For a manual install (no HACS), download `thread_panel.zip` from a release and unzip into `/config/custom_components/thread_panel/`, then restart HA.

Each release page (Releases tab) auto-includes the exact install command for that tag, paste-ready.

## Repo layout

```
hacs.json                       # HACS metadata (zip_release: true)

platform/                       # device-agnostic, shared across every panel
├── firmware/                   # ESP-IDF component (panel_platform)
├── bridge/                     # Pi-side Python WS+UART bridge
├── integration/thread_panel/   # HA custom integration (V2: moved from repo root)
├── ui-core/                    # Shared Vue+Pinia primitives (TBD)
├── deploy/                     # systemd units, install scripts (TBD)
└── diagnostics/                # Pi-side smoke-test scripts

panels/                         # per-product directories
└── feeding_control/            # first product — pet feeder UI
    ├── firmware/               # ESP-IDF project (depends on panel_platform)
    ├── ui/                     # Vue+Vite app
    └── ha/                     # reference manifest template (pasted into the config flow)

docs/                           # architecture + build plan
tools/                          # cross-cutting deploy / dev scripts
```

The platform/product split is the architectural backbone: anything in `platform/` should be device-agnostic (works for any future thread_panel product); anything in `panels/<id>/` is specific to that product. The HA integration is platform code — HACS pulls it from a release-zip artifact via `hacs.json` `zip_release: true`, so it can live under `platform/integration/` rather than at the repo root.

See [`docs/build_plan_v1.md`](docs/build_plan_v1.md) for current production state and the V1 build history, and [`docs/build_plan_v2.md`](docs/build_plan_v2.md) for the active V2 work (artifact-based releases + HA-orchestrated remote updates).
