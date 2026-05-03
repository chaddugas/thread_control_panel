[Build Plan V2](README.md) › Overview

# Overview — Goals, Non-goals, Architecture

## Goals

V2 has shipped its core reshape — artifact-based releases, HA-orchestrated remote updates, and the WiFi state surface that closed Step 17b. Goals still in flight:

1. **Security hardening** — move MQTT credentials out of the firmware binary, rotate the leaked password, scrub historical artifacts, tighten the authorization surface, sign OTA payloads. Detailed in [phase1_security.md](phase1_security.md).
2. **Code quality + multi-panel readiness** — reorganize `panels/<id>/` for clean drop-in of new panels, sweep dead code, DRY where natural, comment hygiene, foundational tests. Detailed in [phase2_polish.md](phase2_polish.md).
3. **Iterative improvements** — themed groups beyond Phase 2 (small fixes, robustness, HA UX, hardware affordances, etc.). Detailed in [phase3_themed.md](phase3_themed.md).

## Non-goals

- **HACS publication to the default community store.** The project depends on custom-assembled hardware that almost no one else can use; HACS distribution adds packaging burden without real audience. Stays as private install (manual zip, or HACS as a custom repository).
- **Auto-install on a schedule** (cron-style "install at 3am Sunday"). Manual-trigger only — HA notices the new version and surfaces it in the entity, the user clicks Install when ready.
- **CI-based builds.** `cut-release` runs on the Mac (where dev work happens anyway). Moving to GitHub Actions is a V3 question.

## Architecture (V2 end-state)

```
GitHub Release v2.0.0
├── feeding_control-firmware-2.0.0.bin
├── feeding_control-ui-2.0.0.tar.gz
├── panel-bridge-2.0.0.tar.gz
├── thread_panel.zip                # integration, for HACS-as-custom-repo or manual install (static filename, no version suffix — HACS doesn't substitute placeholders)
├── panel-update.sh                  # orchestration script (versioned with releases)
└── manifest.json                    # versions + sha256 + sizes per component

Pi (offline by default):
/opt/panel/
├── current → versions/v2.0.0/      # symlink, atomic swap on update
├── versions/
│   ├── v1.4.0/                     # previous, retained for rollback
│   └── v2.0.0/
│       ├── bridge/                  # python sources
│       ├── ui-dist/                 # built Vue bundle
│       ├── firmware.bin             # C6 firmware
│       ├── panel-update.sh
│       └── manifest.json
└── installed.json                   # what's currently running per-component (versions + sha256)

systemd units reference /opt/panel/current/* — symlink swap + restart = new version live.
No git on the Pi. No source files on the Pi.

HA box:
custom_components/thread_panel/      # extracted from release zip (manual or HACS-as-custom-repo)
```
