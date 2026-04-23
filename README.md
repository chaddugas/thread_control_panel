# Thread Control Panel

> ⚠️ This is a personal project for my own homelab. I'm not accepting issues, PRs, or support requests. You're welcome to fork and adapt — you're on your own.

A platform for building no-WiFi, Thread-based touchscreen control panels for Home Assistant.

Each panel pairs a Raspberry Pi Zero 2 W (display + touch + sensors) with a Seeed XIAO ESP32-C6 (Thread + MQTT-over-TLS). The Pi has no network in production; all HA traffic flows through the C6 over the Thread mesh.

## Repo layout

```
custom_components/thread_panel/ # HA integration (at repo root — HACS requirement)

platform/                       # device-agnostic, shared across every panel
├── firmware/                   # ESP-IDF component (panel_platform)
├── bridge/                     # Pi-side Python WS+UART bridge
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

The platform/product split is the architectural backbone: anything in `platform/` should be device-agnostic (works for any future thread_panel product); anything in `panels/<id>/` is specific to that product. The HA integration sits at the repo root rather than under `platform/` because HACS validates `custom_components/<domain>/` at that path.

See `docs/build_plan.md` for the canonical project state, build order, and decisions.
