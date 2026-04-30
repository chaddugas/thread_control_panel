#!/bin/bash
#
# Pi-side first-install / manual-recovery installer.
#
# Usage:
#   curl -sSL https://github.com/__REPO__/releases/latest/download/install-pi.sh | bash
#   curl -sSL https://github.com/__REPO__/releases/download/v2.0.0-beta.4/install-pi.sh | bash -s -- v2.0.0-beta.4
#   ./install-pi.sh                     # latest stable release
#   ./install-pi.sh v2.0.0-beta.4       # specific version
#
# For ongoing updates after a panel is bootstrapped, use HA's
# update.panel_firmware entity which triggers panel-update.sh internally.
# install-pi.sh is for first-install or manual recovery — anything that
# needs to run before /opt/panel/ + the bridge exist.
#
# __REPO__ is substituted by cut-release with the github org/repo (parsed
# from `git remote get-url origin`). When editing this file in source, you
# can run with REPO=foo/bar overriding to test locally.

set -euo pipefail

REPO="${REPO:-__REPO__}"
PANEL_ROOT="/opt/panel"
INSTALL_USER="$USER"
TARGET_VERSION="${1:-latest}"

# ===== sanity checks =====

if [ "$INSTALL_USER" = "root" ]; then
    echo "install-pi.sh: run as your normal user (not root). sudo is invoked when needed." >&2
    exit 1
fi

for tool in curl python3 tar shasum sudo; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "install-pi.sh: required tool '$tool' not found on PATH" >&2
        exit 1
    fi
done

# ===== resolve version (inline — no lib yet) =====

if [ "$TARGET_VERSION" = "latest" ]; then
    echo "→ Resolving latest release..."
    VERSION=$(curl -sSL "https://api.github.com/repos/$REPO/releases/latest" \
        | python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))")
    if [ -z "$VERSION" ] || [ "$VERSION" = "null" ]; then
        echo "install-pi.sh: couldn't resolve latest release for $REPO" >&2
        echo "  (no published releases yet? https://github.com/$REPO/releases)" >&2
        exit 1
    fi
else
    VERSION="$TARGET_VERSION"
fi

echo "→ Installing $VERSION"

VERSION_DIR="$PANEL_ROOT/versions/$VERSION"
STAGING="/tmp/panel-install-$VERSION"
PREV_TARGET=""
[ -L "$PANEL_ROOT/current" ] && PREV_TARGET=$(readlink "$PANEL_ROOT/current")

# ===== set up /opt/panel/ =====

if [ ! -d "$PANEL_ROOT" ]; then
    echo "→ Creating $PANEL_ROOT (sudo)..."
    sudo mkdir -p "$PANEL_ROOT"
    sudo chown "$INSTALL_USER:$INSTALL_USER" "$PANEL_ROOT"
fi
mkdir -p "$PANEL_ROOT/versions"

rm -rf "$STAGING"
mkdir -p "$STAGING"

# ===== bootstrap the helper lib =====
#
# We download manifest.json + the deploy tarball first, extract just enough
# to source install-lib.sh, then use lib functions for everything else.
# Avoids duplicating ~80 lines between install-pi.sh and panel-update.sh.

echo "→ Downloading manifest.json..."
curl -fsSL -o "$STAGING/manifest.json" \
    "https://github.com/$REPO/releases/download/$VERSION/manifest.json"

echo "→ Bootstrapping helper library..."
DEPLOY_TAR_NAME=$(python3 - "$STAGING/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
print(m["components"]["deploy"]["filename"])
PY
)
curl -fsSL -o "$STAGING/$DEPLOY_TAR_NAME" \
    "https://github.com/$REPO/releases/download/$VERSION/$DEPLOY_TAR_NAME"
mkdir -p "$STAGING/deploy-bootstrap"
tar -xzf "$STAGING/$DEPLOY_TAR_NAME" -C "$STAGING/deploy-bootstrap"

# install-lib expects PANEL_ROOT, REPO, INSTALL_USER, STAGING, VERSION,
# VERSION_DIR set as globals (all are above). source it now.
# shellcheck source=install-lib.sh
source "$STAGING/deploy-bootstrap/install-lib.sh"

# ===== install =====

echo "→ Downloading + verifying remaining artifacts..."
lib_download_artifacts

echo "→ Extracting into $VERSION_DIR..."
lib_extract_artifacts

echo "→ Creating venv + installing bridge deps..."
lib_create_venv

echo "→ Swapping current → $VERSION..."
lib_swap_symlink

echo "→ Rendering systemd units into /etc/systemd/system/..."
lib_render_units

lib_update_installed_json

# ===== bootstrap-only OS setup =====

echo "→ Adding $INSTALL_USER to graphics/input groups..."
sudo usermod -aG video,input,render "$INSTALL_USER"

echo "→ Disabling getty on tty1 (so sway/cog can own the framebuffer)..."
sudo systemctl disable getty@tty1.service 2>/dev/null || true
sudo systemctl stop getty@tty1.service 2>/dev/null || true

# fbcon=rotate:N rotates the kernel framebuffer console independently of
# the KMS display driver. Needed for the panel-update.sh status display
# (which writes to /dev/tty1) to render correctly on the Waveshare's
# native-portrait panel. Idempotent: skip if already present.
if ! grep -q "fbcon=rotate" /boot/firmware/cmdline.txt 2>/dev/null; then
    echo "→ Adding fbcon=rotate:3 to cmdline.txt for rotated console..."
    sudo sed -i 's/$/ fbcon=rotate:3/' /boot/firmware/cmdline.txt
fi

# console-setup brings in the Terminus console fonts. Debian names them
# <charset>-Terminus<HxW>; we use Lat15-TerminusBold32x16 (the largest
# available — 32px tall, 16px wide, bold). Idempotent via dpkg.
if ! dpkg -l console-setup >/dev/null 2>&1; then
    echo "→ Installing console-setup for Terminus fonts..."
    sudo apt update
    sudo apt install -y console-setup
fi

# Sudoers entries panel-update.sh needs (also covers the existing bridge
# control modules — see V1 step 12). Written as a single drop-in file so
# `sudo visudo -c` validates atomically. Idempotent: replaces if exists.
echo "→ Installing /etc/sudoers.d/panel-bridge..."
sudo tee /etc/sudoers.d/panel-bridge >/dev/null <<EOF
$INSTALL_USER ALL=(root) NOPASSWD: /sbin/shutdown -r now
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/nmcli *
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/tee /sys/class/graphics/fb0/blank
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart panel-bridge.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart panel-ui.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart cog.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop cog.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start cog.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active *
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/chvt *
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/setfont *
EOF
sudo chmod 0440 /etc/sudoers.d/panel-bridge

# ===== reload + restart =====

echo "→ Reloading systemd..."
sudo systemctl daemon-reload

echo "→ Enabling units..."
sudo systemctl enable panel-bridge.service panel-ui.service cog.service

echo "→ Restarting bridge + UI server..."
sudo systemctl restart panel-bridge.service panel-ui.service
# cog.service is restarted on reboot (sway expects to own tty1 from boot).

# ===== prune old versions =====

lib_prune_old_versions "$PREV_TARGET"

# ===== cleanup =====

rm -rf "$STAGING"

# ===== done =====

cat <<EOF

✓ Installed $VERSION
  current → $(readlink "$PANEL_ROOT/current")

The bridge and UI server are running on the new version. Cog (the kiosk)
restarts on next reboot — reboot now to pick up the new UI:

    sudo reboot

Verify after reboot:
    systemctl status panel-bridge panel-ui cog
    journalctl -u panel-bridge -f
EOF
