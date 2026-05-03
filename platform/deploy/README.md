# platform/deploy/

Deployment artifacts shared across panels. Bundled into `panel-deploy-X.Y.Z.tar.gz`
by `cut-release` and shipped as a release component; `install-pi.sh` extracts
it to `/opt/panel/versions/<v>/deploy/` on the Pi.

| File | Role |
|---|---|
| `install-pi.sh` | First-time installer + manual upgrade path. Downloaded loose from the GitHub release (not bundled in the deploy tarball). Resolves a target version, downloads + sha256-verifies all artifacts, sets up `/opt/panel/versions/<v>/`, creates the bridge venv, renders systemd units, atomically swaps `current → versions/<v>/`, restarts services. Prunes versions older than current+previous-1. |
| `panel-bridge.sh` | Runner for `panel-bridge.service`. V2 form: just exec the bridge from `/opt/panel/current/bridge/.venv`. No git pull — updates flow through `install-pi.sh` (manual) or `panel-update.sh` (Phase 3, HA-orchestrated). |
| `panel-bridge.service` | systemd unit invoking `panel-bridge.sh`; restarts on failure. |
| `panel-ui-server.py` | Static file server with proper cache headers (no-cache for index.html, immutable for hashed assets). Replaces `python3 -m http.server` which heuristic-cached index.html and hid post-deploy UI updates from WPE/cog. |
| `panel-ui.service` | Serves `/opt/panel/current/ui-dist/` on `127.0.0.1:8080` via `panel-ui-server.py`. |
| `cog.service` | Launches the kiosk: [sway](https://swaywm.org) Wayland compositor running [cog](https://github.com/Igalia/cog) (WPE WebKit single-app launcher) as its sole client. Sway applies the output transform to rotate the panel from native portrait to landscape; cog renders via WPE-FDO into the rotated surface. ~150-180 MB combined resident vs. Chromium's 300+. Conflicts with `getty@tty1.service` so sway owns the framebuffer. |
| `sway-kiosk.config` | Sway config used by `cog.service`. Sets the output rotation, suppresses decorations/borders, hides the cursor, autostarts cog. |

## Install / upgrade flow

The Pi has no source clone. Everything lives under `/opt/panel/`:

```
/opt/panel/
├── current → versions/v2.0.0/      # atomic symlink
├── versions/v2.0.0/
│   ├── bridge/         # panel-bridge-v2.0.0.tar.gz extracted; .venv created in-place
│   ├── ui-dist/        # feeding_control-ui-v2.0.0.tar.gz extracted
│   ├── deploy/         # panel-deploy-v2.0.0.tar.gz extracted
│   ├── firmware.bin    # feeding_control-firmware-v2.0.0.bin
│   └── manifest.json   # release manifest snapshot
└── installed.json      # mirror of current/manifest.json (top-level convenience)
```

### Latest release

```bash
curl -sSL https://github.com/chaddugas/thread_control_panel/releases/latest/download/install-pi.sh | bash
```

### Specific version (e.g. a beta)

```bash
curl -sSL https://github.com/chaddugas/thread_control_panel/releases/download/v2.0.0-beta.1/install-pi.sh \
  | bash -s -- v2.0.0-beta.1
```

`install-pi.sh` is idempotent — re-running with the same version is a no-op-ish (re-downloads, re-installs cleanly), and running with a new version installs side-by-side and swaps the symlink.

### First time on a fresh Pi

Until [the bootstrap-from-fresh-Pi-OS-Lite item](../../docs/build_plan_v2/phase3_themed.md#developer-ergonomics) folds apt setup into `install-pi.sh`, you need to install the kiosk stack manually first:

```bash
sudo apt update
sudo apt install -y sway cog python3-venv
```

Then run install-pi.sh as above. Reboot when it's done so sway takes ownership of tty1.

## Restarting after a release

The bridge no longer pulls latest on each start, so you have to explicitly install:

```bash
# Pi side
curl -sSL https://github.com/chaddugas/thread_control_panel/releases/latest/download/install-pi.sh | bash
```

That's the deploy cycle until Phase 3 wires the same flow into a HA-triggered `update.panel_firmware` entity.

## Migrating from V1 (git-clone install)

Old `~/thread_control_panel/` clone stays put — install-pi.sh ignores it. The systemd units get rewritten to point at `/opt/panel/current/...` so the V1 paths are no longer referenced. Once you've verified V2 works:

```bash
rm -rf ~/thread_control_panel
```

## Relationship with the `panel-bridge` bashrc alias

V1's bashrc alias did a git pull + venv sync + bridge launch in foreground. With V2, that alias is mostly defunct — there's no repo on the Pi to pull, and updates go through install-pi.sh.

If you want a foreground bridge for debugging, run it directly from the installed venv:

```bash
sudo systemctl stop panel-bridge.service
cd /opt/panel/current/bridge
.venv/bin/python -m panel_bridge       # Ctrl-C when done
sudo systemctl start panel-bridge.service
```
