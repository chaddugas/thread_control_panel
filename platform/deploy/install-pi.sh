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

# By default Pi OS journals live in /run/log/journal/ (tmpfs), so every
# reboot wipes bridge logs from the prior boot. Panels reboot frequently
# during dev and post-mortem debugging matters precisely after a
# problematic boot, so persistent journals are worth the disk cost.
# Cap retention at 200M total / 2-week age so SD cards don't slowly fill.
echo "→ Configuring persistent journald (/var/log/journal/, 200M / 2-week)..."
sudo mkdir -p /var/log/journal
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/panel.conf >/dev/null <<'EOF'
[Journal]
Storage=persistent
SystemMaxUse=200M
SystemMaxFileSize=20M
MaxRetentionSec=2week
EOF
sudo systemctl restart systemd-journald

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
# control modules — see V1 step 12). Each rule is an exact command +
# args match (or the tightest wildcard the use case allows) — Phase 1
# Group C narrowed the previous nmcli/systemctl/chvt/setfont/setterm
# wildcards. Written as a single drop-in file so `sudo visudo -c`
# validates atomically. Idempotent: replaces if exists.
echo "→ Installing /etc/sudoers.d/panel-bridge..."
sudo tee /etc/sudoers.d/panel-bridge >/dev/null <<EOF
# Reboot button
$INSTALL_USER ALL=(root) NOPASSWD: /sbin/shutdown -r now

# Screen blank/unblank via sysfs (controls/screen.py)
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/tee /sys/class/graphics/fb0/blank

# WiFi radio toggle (controls/wifi.py + panel-update.sh)
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/nmcli radio wifi on
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/nmcli radio wifi off

# WiFi profile management (controls/wifi_manage.py). SSID is the variable
# trailing arg so * is required; interface anchored to wlan0 in the add path.
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/nmcli connection delete *
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/nmcli connection up *
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/nmcli connection add type wifi ifname wlan0 *

# Service control (panel-update.sh + bridge bootstrap)
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart panel-bridge.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart panel-ui.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart cog.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart panel-bridge.service panel-ui.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop cog.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start cog.service

# Service health checks (panel-update.sh healthcheck loop)
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active --quiet panel-bridge.service
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active --quiet panel-ui.service

# Console + framebuffer for OTA progress display (panel-update.sh)
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/chvt 1
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/setfont Lat15-TerminusBold32x16
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/setterm --term linux --blank 0 --powerdown 0
$INSTALL_USER ALL=(root) NOPASSWD: /usr/bin/chown $INSTALL_USER /dev/tty1
EOF
sudo chmod 0440 /etc/sudoers.d/panel-bridge

# ===== MQTT credentials =====
#
# The C6 firmware reads its MQTT username + password from NVS, not from
# CONFIG_MQTT_USERNAME/CONFIG_MQTT_PASSWORD baked into firmware.bin. The
# bridge sends the values over UART (panel_set_creds envelope) at startup
# and on file-change. We collect the values here and write them to
# /opt/panel/mqtt_creds.json so the bridge can do that.
#
# Skipped if the file already exists — install-pi.sh is bootstrap-only,
# so a re-run shouldn't re-prompt over an existing valid config.

CREDS_FILE="$PANEL_ROOT/mqtt_creds.json"

if [ -f "$CREDS_FILE" ]; then
    echo "→ MQTT credentials already at $CREDS_FILE — skipping prompt"
else
    echo "→ Configuring MQTT credentials..."
    echo "  These get stored in $CREDS_FILE (mode 0600) and pushed to the C6"
    echo "  over UART. The C6 keeps them in NVS — no creds in firmware.bin."
    echo

    # Validation matches what panel_bridge/mqtt_creds.py and
    # panel_net.c enforce. Substring tests for `"` and `\` are required
    # because the C6's panel_app.c uses a substring-based JSON parser
    # that doesn't handle escapes.

    while true; do
        read -r -p "  MQTT username: " mqtt_user
        if [ -z "$mqtt_user" ]; then
            echo "    × username can't be empty"
            continue
        fi
        if [ "${#mqtt_user}" -gt 64 ]; then
            echo "    × username max length is 64 chars"
            continue
        fi
        case "$mqtt_user" in
            *'"'* | *'\'*)
                echo "    × username can't contain \" or \\"
                continue
                ;;
        esac
        if [[ "$mqtt_user" =~ [^[:print:]] ]]; then
            echo "    × username contains non-printable characters"
            continue
        fi
        break
    done

    while true; do
        read -r -s -p "  MQTT password (12-128 chars, 2 of {letters, digits, symbols}): " mqtt_pass
        echo
        if [ "${#mqtt_pass}" -lt 12 ]; then
            echo "    × password min length is 12"
            continue
        fi
        if [ "${#mqtt_pass}" -gt 128 ]; then
            echo "    × password max length is 128"
            continue
        fi
        case "$mqtt_pass" in
            *'"'* | *'\'*)
                echo "    × password can't contain \" or \\"
                continue
                ;;
        esac
        if [[ "$mqtt_pass" =~ [^[:print:]] ]]; then
            echo "    × password contains non-printable characters"
            continue
        fi
        # Class-diversity check: at least 2 of {letter, digit, symbol}
        classes=0
        [[ "$mqtt_pass" =~ [A-Za-z] ]] && classes=$((classes + 1))
        [[ "$mqtt_pass" =~ [0-9] ]] && classes=$((classes + 1))
        [[ "$mqtt_pass" =~ [^A-Za-z0-9] ]] && classes=$((classes + 1))
        if [ "$classes" -lt 2 ]; then
            echo "    × must contain at least 2 of {letters, digits, symbols}"
            continue
        fi
        read -r -s -p "  Confirm password: " mqtt_pass_confirm
        echo
        if [ "$mqtt_pass" != "$mqtt_pass_confirm" ]; then
            echo "    × passwords don't match"
            continue
        fi
        break
    done

    # Atomic write: temp file + rename. Use python3 so JSON encoding is
    # bulletproof (the validation above already rules out the cases
    # that would break the C6 parser, but proper json.dumps is cheap
    # defense-in-depth). umask + chmod tighten to 0600 BEFORE writing
    # so the password is never on disk world-readable.
    tmp_file=$(mktemp "$PANEL_ROOT/mqtt_creds.json.XXXXXX")
    chmod 0600 "$tmp_file"
    python3 -c '
import json, sys
print(json.dumps({"username": sys.argv[1], "password": sys.argv[2]}))
' "$mqtt_user" "$mqtt_pass" > "$tmp_file"
    mv "$tmp_file" "$CREDS_FILE"
    echo "  ✓ Credentials written to $CREDS_FILE"
    echo
fi

# ===== enable + restart =====
# (daemon-reload already ran inside lib_render_units after writing the units)

echo "→ Enabling units..."
sudo systemctl enable panel-bridge.service panel-ui.service cog.service

echo "→ Restarting bridge + UI server..."
sudo systemctl restart panel-bridge.service panel-ui.service
# cog.service is restarted on reboot (sway expects to own tty1 from boot).

# ===== prune old versions =====

lib_prune_old_versions "$PREV_TARGET"

# ===== cleanup =====

rm -rf "$STAGING"

# ===== remove any blanket NOPASSWD: ALL drop-ins =====
#
# Defense in depth: scrub any /etc/sudoers.d/* drop-in granting wide-open
# NOPASSWD: ALL so passwordless sudo is limited to what panel-bridge
# explicitly allows. Sources of such a drop-in vary — manual setup steps,
# Pi-imager defaults, prior tooling — so detect by content rather than
# filename. The regex matches lines ending in `NOPASSWD: ALL` (with
# optional surrounding whitespace), which catches the wide-open form
# without flagging the per-command rules in our own panel-bridge file
# (where each line ends with a specific command path, not `ALL`).
#
# Done at the end of install-pi.sh so all earlier sudo-needing setup runs
# without prompting on a fresh Pi (or one with an existing wide-open
# rule). After this, interactive sudo prompts for password as normal
# Linux behavior; sudo's ~15min credential cache covers a typical session.
# Idempotent: no-op once matching files are gone.

suspects=$(sudo grep -lrE 'NOPASSWD:[[:space:]]*ALL[[:space:]]*$' \
    /etc/sudoers.d/ 2>/dev/null \
    | grep -v '^/etc/sudoers.d/panel-bridge$' || true)

if [ -n "$suspects" ]; then
    for f in $suspects; do
        echo "→ Removing $f (grants NOPASSWD: ALL — defense-in-depth)..."
        sudo rm "$f"
    done
fi

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
