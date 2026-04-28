# platform/deploy/

Deployment artifacts shared across panels.

| File | Role |
|---|---|
| `panel-bridge.sh` | Runner script for the bridge service. Pulls latest, syncs deps if `pyproject.toml` changed, execs the bridge. Mirrors the interactive `panel-bridge` bashrc alias. |
| `panel-bridge.service` | systemd unit that invokes `panel-bridge.sh` on boot and restarts on failure. |
| `panel-ui.service` | systemd unit that serves the committed UI bundle (`panels/feeding_control/ui/dist/`) on `127.0.0.1:8080` via Python's built-in `http.server`. |
| `cog.service` | systemd unit that launches the kiosk stack: [sway](https://swaywm.org) Wayland compositor running [cog](https://github.com/Igalia/cog) (WPE WebKit single-app launcher) as its sole client. Sway applies the output transform to rotate the panel from its native portrait orientation to landscape; cog renders via WPE-FDO into the rotated surface. Combined ~150-180 MB resident vs Chromium's 300+ MB. Conflicts with `getty@tty1.service` so sway owns the framebuffer. |
| `sway-kiosk.config` | Sway config used by `cog.service`. Sets the output rotation, suppresses all decorations/borders, hides the cursor, and autostarts cog. |
| `install-pi.sh` | Idempotent Pi-side bootstrap. Renders the unit files into `/etc/systemd/system/` with the current user templated in, adds the user to graphics/input groups, disables getty on tty1, and starts the bridge + UI server. Tears down legacy units (e.g. an earlier `cage.service`) on re-run. |

## How the kiosk gets its UI

The UI is built on the Mac as part of `cut-release` (see [tools/cut-release.zsh](../../tools/cut-release.zsh)), and the resulting `dist/` is committed to git. The Pi pulls dist/ along with everything else on each `panel-bridge.service` start, and `panel-ui.service` serves it. No node, no yarn, no Vite on the Pi.

If you push UI source changes between releases, the kiosk keeps serving the last release's dist/ until you cut a new release. That's intentional — releases are the deploy unit.

## First-time Pi setup

```bash
# 1. Clone the repo if it's not already there.
cd ~ && git clone https://github.com/chaddugas/thread_control_panel.git

# 2. Bridge venv + deps.
cd ~/thread_control_panel/platform/bridge
python3 -m venv .venv
.venv/bin/pip install -e .

# 3. apt install the kiosk stack.
sudo apt update
sudo apt install -y sway cog

# 4. Bootstrap the systemd units, group memberships, getty handoff.
~/thread_control_panel/platform/deploy/install-pi.sh

# 5. Reboot so sway takes over tty1 and group memberships apply.
sudo reboot
```

After reboot, the kiosk launches automatically. Verify with:

```bash
systemctl status panel-bridge panel-ui cog
journalctl -u cog -f      # if the kiosk misbehaves
```

`install-pi.sh` is idempotent — re-run it after pulling unit-file updates and it'll re-render the units into `/etc/systemd/system/` and reload. Tracked unit files in `platform/deploy/` stay clean (templating happens at install time, not in the working tree), so `git pull` keeps working without dirty-tree conflicts.

## Restarting after a code change

```bash
sudo systemctl restart panel-bridge.service     # picks up bridge code on next start (git pull built in)
sudo systemctl restart panel-ui.service         # picks up newly-pulled UI dist/
sudo systemctl restart cog.service              # reloads the kiosk
```

The bridge runner pulls latest on each start, so a `cut-release` on your Mac + `restart panel-bridge` on the Pi is the whole deploy cycle. If you pushed a `pyproject.toml` change, deps sync automatically.

## Relationship with the `panel-bridge` bashrc alias

Both call the same logic. Use the bashrc alias to iterate interactively (foreground, Ctrl-C to stop); use `systemctl restart panel-bridge` to re-deploy the service. Don't run both at once — they'd fight over `/dev/serial0` and the WS port.

If you're about to do a `panel-bridge` interactive session, stop the service first:

```bash
sudo systemctl stop panel-bridge.service
panel-bridge      # bashrc alias, foreground
# Ctrl-C when done
sudo systemctl start panel-bridge.service
```
