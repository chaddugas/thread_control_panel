#!/bin/bash
#
# panel-update.sh — HA-driven update orchestrator.
#
# Spawned detached by the bridge when it receives a `cmd/update` MQTT
# message. Runs independently of the bridge so it survives the bridge
# restart partway through.
#
# Flow:
#   1. Stop sway, take over tty1, set up big rotated font for status
#   2. Enable WiFi, wait for DNS
#   3. Use install-lib.sh to download + verify + install the target version
#   4. Restart bridge + UI services on the new version, healthcheck
#   5. Flash C6 via panel-flash (the new bridge has the new panel-flash)
#   6. Disable WiFi
#   7. Restart sway / cog (kiosk back up on new UI)
#
# Status updates are appended to /opt/panel/update.status (one JSON line
# per phase). The bridge tails this file and republishes lines as
# `state/update_status` MQTT for HA's update.panel_firmware entity.
#
# __REPO__ is substituted by cut-release with the github org/repo.

set -u  # don't `set -e` — we want explicit error handling for rollback

REPO="${REPO:-__REPO__}"
PANEL_ROOT="/opt/panel"
TARGET_VERSION="${1:-latest}"
STATUS_FILE="$PANEL_ROOT/update.status"
LOCKFILE="/var/run/panel-update.pid"

# ===== concurrent-update protection =====

if [ -f "$LOCKFILE" ]; then
    OLD_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "panel-update: already running (pid $OLD_PID), refusing"
        exit 1
    fi
    rm -f "$LOCKFILE"
fi
echo $$ > "$LOCKFILE"

# Always release lock + restart kiosk on exit (success or failure)
cleanup() {
    rm -f "$LOCKFILE"
    sudo systemctl start cog.service 2>/dev/null || true
}
trap cleanup EXIT

# ===== status reporting =====

publish_status() {
    local phase="$1"
    local detail="${2:-}"
    local now
    now=$(date +%s)
    if [ -n "$detail" ]; then
        # Escape any " in the detail to keep the JSON valid (rare in practice).
        detail=${detail//\"/\\\"}
        printf '{"phase":"%s","detail":"%s","ts":%d}\n' "$phase" "$detail" "$now" >> "$STATUS_FILE"
    else
        printf '{"phase":"%s","ts":%d}\n' "$phase" "$now" >> "$STATUS_FILE"
    fi
    # Also write to the screen — the user is probably watching the panel.
    if [ -n "$detail" ]; then
        echo "[$phase] $detail"
    else
        echo "[$phase]"
    fi
}

fail() {
    publish_status "failed" "$1"
    exit 1
}

# ===== console takeover =====
#
# Stop the kiosk so we can write status to tty1. Cog will be restarted on
# script exit by the trap above. fbcon=rotate:3 (set in cmdline.txt by
# install-pi.sh) means tty1 renders rotated to match the panel orientation.

sudo systemctl stop cog.service 2>/dev/null || true
sudo chvt 1 2>/dev/null || true
exec > /dev/tty1 2>&1
sudo setfont ter-132n 2>/dev/null || true

# Initialize a fresh status file for this run
: > "$STATUS_FILE"

publish_status "starting" "$TARGET_VERSION"

# ===== bring up network =====

publish_status "enabling_wifi"
sudo nmcli radio wifi on || fail "nmcli radio wifi on returned non-zero"

publish_status "waiting_for_dns"
DNS_OK=0
for _ in $(seq 1 30); do
    if getent hosts api.github.com >/dev/null 2>&1; then
        DNS_OK=1
        break
    fi
    sleep 2
done
if [ "$DNS_OK" -eq 0 ]; then
    fail "DNS for api.github.com unresolvable after 60s"
fi

# ===== source helper lib =====
#
# install-lib.sh ships in the deploy tarball; the existing install put it
# at /opt/panel/current/deploy/. Source it now for the install functions.

# install-lib expects these globals
INSTALL_USER=$(stat -c %U "$PANEL_ROOT" 2>/dev/null || echo "$USER")
PREV_TARGET=""
[ -L "$PANEL_ROOT/current" ] && PREV_TARGET=$(readlink "$PANEL_ROOT/current")

# shellcheck source=install-lib.sh
source "$PANEL_ROOT/current/deploy/install-lib.sh" || fail "install-lib.sh missing or unreadable"

# Resolve target version BEFORE creating staging dirs so VERSION is set
publish_status "resolving_version" "$TARGET_VERSION"
VERSION=$(lib_resolve_version "$TARGET_VERSION")
if [ -z "$VERSION" ] || [ "$VERSION" = "null" ]; then
    fail "couldn't resolve $TARGET_VERSION to a release tag"
fi
publish_status "resolved" "$VERSION"

VERSION_DIR="$PANEL_ROOT/versions/$VERSION"
STAGING="/tmp/panel-update-$VERSION"

# ===== download =====

mkdir -p "$PANEL_ROOT/versions"
rm -rf "$STAGING"
mkdir -p "$STAGING"

publish_status "downloading_manifest"
lib_download_manifest || fail "manifest download failed"

publish_status "downloading_artifacts"
lib_download_artifacts || fail "artifact download / sha256 verification failed"

# ===== install =====

publish_status "extracting"
lib_extract_artifacts || fail "extract failed"

publish_status "creating_venv"
lib_create_venv || fail "venv create / pip install failed"

publish_status "swapping_symlink"
lib_swap_symlink || fail "symlink swap failed"

publish_status "rendering_units"
lib_render_units || fail "systemd unit render failed"

lib_update_installed_json

# ===== restart services on new version =====

publish_status "restarting_bridge"
sudo systemctl restart panel-bridge.service || fail "panel-bridge restart returned non-zero"

publish_status "restarting_ui"
sudo systemctl restart panel-ui.service || fail "panel-ui restart returned non-zero"

# ===== healthcheck =====
#
# Both services should stabilize within ~30s. If either bounces, roll back
# to the previous version.

publish_status "healthcheck"
HEALTH_OK=0
for _ in $(seq 1 30); do
    if sudo systemctl is-active --quiet panel-bridge.service \
        && sudo systemctl is-active --quiet panel-ui.service; then
        HEALTH_OK=1
        sleep 1
    else
        HEALTH_OK=0
        break
    fi
done
if [ "$HEALTH_OK" -eq 0 ]; then
    publish_status "rolling_back" "services failed healthcheck on $VERSION"
    if [ -n "$PREV_TARGET" ] && [ -d "$PREV_TARGET" ]; then
        ln -sfn "$PREV_TARGET" "$PANEL_ROOT/current.new"
        mv -T "$PANEL_ROOT/current.new" "$PANEL_ROOT/current"
        sudo systemctl restart panel-bridge.service panel-ui.service 2>/dev/null || true
        # Restore previous installed.json snapshot if we can find it.
        [ -f "$PREV_TARGET/manifest.json" ] && cp "$PREV_TARGET/manifest.json" "$PANEL_ROOT/installed.json"
    fi
    fail "service healthcheck failed"
fi

# ===== flash C6 over UART =====
#
# The new bridge ships with the new panel-flash CLI. Use it to push the
# new firmware to the C6.

publish_status "flashing_c6"
if "$PANEL_ROOT/current/bridge/.venv/bin/panel-flash" \
    "$PANEL_ROOT/current/firmware.bin"; then
    publish_status "c6_flashed"
else
    # The C6 still runs the old firmware; the Pi is on the new version.
    # That's a valid intermediate state — HA will see version mismatch
    # but the panel still works. Don't roll back the Pi for this.
    publish_status "c6_flash_failed" "panel-flash exited non-zero; C6 still on old firmware"
    # Continue to cleanup — don't fail outright.
fi

# Brief pause for the C6 to come back online and republish state/version.
publish_status "waiting_for_c6"
sleep 10

# ===== prune + cleanup =====

lib_prune_old_versions "$PREV_TARGET"
rm -rf "$STAGING"

# ===== bring network back down =====

publish_status "disabling_wifi"
sudo nmcli radio wifi off || true

publish_status "done" "$VERSION"

# trap will restart cog
