# platform/deploy/

Deployment artifacts shared across panels.

| File | Role |
|---|---|
| `panel-bridge.sh` | Runner script for the bridge service. Pulls latest, syncs deps if pyproject.toml changed, execs the bridge. Mirrors the interactive `panel-bridge` bashrc alias. |
| `panel-bridge.service` | systemd unit that invokes `panel-bridge.sh` on boot and restarts on failure. |
| `cage.service` | systemd unit that launches the kiosk compositor. (Landed in step 15.) |
| `install-pi.sh` | One-shot Pi bootstrap (apt installs, group memberships, service enables). (Landed in step 15.) |

## Installing panel-bridge on the Pi

**First-time setup** (one time per Pi):

```bash
# 1. Clone the repo if it's not already there.
cd ~ && git clone https://github.com/chaddugas/thread_control_panel.git

# 2. Create the bridge venv + install deps.
cd ~/thread_control_panel/platform/bridge
python3 -m venv .venv
.venv/bin/pip install -e .

# 3. If your Pi username isn't `pi`, edit the unit first.
#    User= and ExecStart= both reference /home/pi/thread_control_panel —
#    sed once and you're done:
#      sed -i "s|/home/pi/|/home/$USER/|g; s|^User=pi|User=$USER|" \
#        ~/thread_control_panel/platform/deploy/panel-bridge.service

# 4. Symlink the unit into systemd and enable it.
sudo ln -s ~/thread_control_panel/platform/deploy/panel-bridge.service \
  /etc/systemd/system/panel-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable panel-bridge.service
sudo systemctl start panel-bridge.service
```

Symlinking (rather than copying) means future git-pulled updates to the unit file are picked up automatically on `daemon-reload`.

## Verifying it's running

```bash
systemctl status panel-bridge.service
journalctl -u panel-bridge.service -f     # follow live
```

Expected first lines on a clean start:

```
→ Pulling latest...
Already up to date.
→ Starting bridge...
INFO panel_bridge: Starting panel_bridge — UART /dev/serial0 @ 115200, WS ws://0.0.0.0:8765
INFO panel_bridge.uart_link: UART link up on /dev/serial0 @ 115200
INFO panel_bridge.ws_server: WS server listening on ws://0.0.0.0:8765
```

## Restarting after a code change

```bash
sudo systemctl restart panel-bridge.service
```

The runner pulls latest on each start, so a `git push` on your laptop + `restart` on the Pi is the whole deploy cycle. If you pushed a pyproject.toml change, deps sync automatically.

## Relationship with the `panel-bridge` bashrc alias

Both call the same logic. Use the bashrc alias to iterate interactively (foreground, Ctrl-C to stop); use `systemctl restart panel-bridge` to re-deploy the service. Don't run both at once — they'd fight over `/dev/serial0` and the WS port.

If you're about to do a `panel-bridge` interactive session, stop the service first:

```bash
sudo systemctl stop panel-bridge.service
panel-bridge      # bashrc alias, foreground
# Ctrl-C when done
sudo systemctl start panel-bridge.service
```
