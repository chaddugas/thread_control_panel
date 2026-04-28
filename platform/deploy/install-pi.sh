#!/bin/bash
#
# Pi-side bootstrap for thread_control_panel kiosk. Idempotent — re-run
# after pulling unit-file updates and it'll just re-symlink and reload.
#
# Assumes you've already:
#   - Cloned the repo to ~/thread_control_panel
#   - Set up the bridge venv:
#       cd ~/thread_control_panel/platform/bridge
#       python3 -m venv .venv
#       .venv/bin/pip install -e .
#   - apt-installed cage and chromium
#
# Run as the user that'll run the kiosk (NOT as root) — sudo is invoked
# only where it's actually needed.

set -e

USER_NAME="${USER}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$SCRIPT_DIR"
UNITS=(panel-bridge.service panel-ui.service cage.service)

if [ "$USER_NAME" = "root" ]; then
    echo "Run as your normal user (not root). sudo will be invoked when needed." >&2
    exit 1
fi

# Each .service file is committed with `User=pi` + `/home/pi/...` paths as
# placeholders. If we're a different user, sed them in place once. The pull
# script tolerates the dirty working tree (it warns and continues), and a
# subsequent fresh pull on a unit-file change re-templates here.
if [ "$USER_NAME" != "pi" ]; then
    echo "→ Templating unit files for user '$USER_NAME'..."
    for unit in "${UNITS[@]}"; do
        sed -i.bak \
            -e "s|/home/pi/|/home/$USER_NAME/|g" \
            -e "s|^User=pi$|User=$USER_NAME|" \
            "$DEPLOY_DIR/$unit"
        rm -f "$DEPLOY_DIR/$unit.bak"
    done
fi

echo "→ Adding $USER_NAME to graphics/input groups (cage needs DRI + evdev)..."
sudo usermod -aG video,input,render "$USER_NAME"

echo "→ Disabling getty on tty1 so cage can own it..."
sudo systemctl disable getty@tty1.service 2>/dev/null || true
sudo systemctl stop getty@tty1.service 2>/dev/null || true

echo "→ Symlinking systemd units..."
for unit in "${UNITS[@]}"; do
    sudo ln -sf "$DEPLOY_DIR/$unit" "/etc/systemd/system/$unit"
done

echo "→ Reloading systemd..."
sudo systemctl daemon-reload

echo "→ Enabling units..."
sudo systemctl enable "${UNITS[@]}"

echo "→ Starting bridge + UI server..."
sudo systemctl restart panel-bridge.service panel-ui.service

cat <<EOF

Done.

Reboot now so:
  - cage takes over tty1 and the kiosk launches automatically
  - $USER_NAME's new group memberships apply

After reboot, verify with:
  systemctl status panel-bridge panel-ui cage
  journalctl -u cage -f      # if Chromium misbehaves
EOF
