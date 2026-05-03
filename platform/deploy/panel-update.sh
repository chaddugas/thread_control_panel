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
LOG_FILE="$PANEL_ROOT/update.log"
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
    local detail_esc=""
    if [ -n "$detail" ]; then
        # Escape any " in the detail to keep the JSON valid.
        detail_esc=${detail//\"/\\\"}
        printf '{"phase":"%s","detail":"%s","ts":%d}\n' "$phase" "$detail_esc" "$now" >> "$STATUS_FILE"
    else
        printf '{"phase":"%s","ts":%d}\n' "$phase" "$now" >> "$STATUS_FILE"
    fi
    local screen_msg
    if [ -n "$detail" ]; then
        screen_msg="[$phase] $detail"
    else
        screen_msg="[$phase]"
    fi
    # To screen (stdout = /dev/tty1) AND to $LOG_FILE.
    echo "$screen_msg"
    echo "$screen_msg" >> "$LOG_FILE"
}

fail() {
    local detail="$1"
    # Brief pause so any pending stderr from the failing command makes
    # it through tee into the log before we read.
    sleep 0.3
    if [ -s "$LOG_FILE" ]; then
        # Cram the last few log lines into the status detail so HA's
        # update entity (and anyone reading update.status) gets actual
        # error text, not just a phase name. Newlines collapsed to | for
        # JSON-friendliness; capped at 250 chars; full output stays in
        # $LOG_FILE for `cat` after the fact.
        local tail_text
        tail_text=$(tail -8 "$LOG_FILE" \
                     | tr -d '\r' \
                     | tr '\n' '|' \
                     | head -c 250)
        publish_status "failed" "$detail — log tail: $tail_text"
    else
        publish_status "failed" "$detail"
    fi
    exit 1
}

# Note: previously this script had an early same-version refusal here that
# exited before console takeover when TARGET_VERSION matched the current
# symlink. That blocked HA-driven OTAs from flashing the C6 when the Pi was
# already current but the C6 wasn't (caught during Group A validation —
# install-pi.sh-then-OTA path stranded the C6). Now handled lower down via
# SKIP_PI_INSTALL: skip the destructive Pi-side phases when version matches,
# but always run the C6 flash phase since that's the work the user actually
# wants done. HA's UpdateEntity already disables the Install button when
# installed_version >= latest_version, so the only way to land here with
# same version is a deliberate manual MQTT publish.

# ===== console takeover =====
#
# Stop the kiosk so we can write status to tty1. Cog is restarted on script
# exit by the trap above. fbcon=rotate:3 (set in cmdline.txt by
# install-pi.sh) means tty1 renders rotated to match the panel orientation.
#
# stdout/stderr go directly to /dev/tty1 so the screen shows live progress.
# publish_status separately appends to $LOG_FILE so post-mortem inspection
# survives the cog restart that hides tty1 after we exit. Subprocess
# output (pip etc.) is teed via run_logged() below for the same reason —
# we earlier tried `exec > >(tee ...)` for one-stop-shop dual output but
# the process substitution caused silent SIGPIPE termination.
#
# /dev/tty1 ownership: while cog runs, PAM (PAMName=login) chowns it to
# the kiosk user. When cog stops, ownership reverts to root:tty 600 — and
# the `tty` group has no permissions either, so just being in tty group
# doesn't help. We sudo-chown the tty back to ourselves so `exec >` works.
# The sudoers entry pinning user-and-target is in install-pi.sh's drop-in.

sudo systemctl stop cog.service 2>/dev/null || true
sudo chvt 1 2>/dev/null || true
sudo chown "$USER" /dev/tty1 2>/dev/null || true
exec > /dev/tty1 2>&1
# Bash with `set -u` (and no `set -e`) does NOT exit on `exec >` redirect
# failure — it just leaves stdout untouched and continues silently. If the
# tty takeover above didn't actually land us on a tty, surface that fact
# in update.status so the failure mode is debuggable instead of invisible.
if [ ! -t 1 ]; then
    printf '{"phase":"console_takeover_failed","detail":"exec > /dev/tty1 did not yield a tty (chown failed? sudoers missing chown /dev/tty1?)","ts":%d}\n' "$(date +%s)" >> "$STATUS_FILE"
fi
# Largest Terminus available on Debian Bookworm's console-setup package
# (32px tall, 16px wide, bold). Upstream Terminus naming is "ter-132b" —
# Debian renames as <charset>-Terminus<HxW>. Lat15 covers ASCII + western
# European; if a panel ever needs Cyrillic/Greek/etc, swap charset prefix.
sudo setfont Lat15-TerminusBold32x16 2>/dev/null || true
# Disable console blanking + DPMS so the screen doesn't go dark during
# long quiet phases (creating_venv can sit silent for ~60s while pip
# installs). --term linux to apply to /dev/tty1 specifically.
sudo setterm --term linux --blank 0 --powerdown 0 2>/dev/null || true

# Initialize fresh log + status files for this run
: > "$LOG_FILE"
: > "$STATUS_FILE"

# Run a command, copy its stdout+stderr to both the screen (our stdout)
# and $LOG_FILE. Returns the command's exit code. Use this around any
# subprocess whose output we want captured (pip, tar, etc.).
run_logged() {
    "$@" 2>&1 | tee -a "$LOG_FILE"
    return "${PIPESTATUS[0]}"
}

publish_status "starting" "$TARGET_VERSION"

# ===== bring up network =====

publish_status "enabling_wifi"
sudo nmcli radio wifi on || fail "nmcli radio wifi on returned non-zero"

# `nmcli radio wifi on` returns immediately (just flips the radio bit);
# the actual scan + auth + DHCP can take 30-60s. Wait for NM to report
# wlan0 as "connected" before checking DNS — the previous code lumped
# both phases into waiting_for_dns, hiding where the time went.
publish_status "waiting_for_connection"
WIFI_CONNECTED=0
for _ in $(seq 1 30); do
    if nmcli -t -f DEVICE,STATE device status 2>/dev/null \
        | grep -q '^wlan0:connected$'; then
        WIFI_CONNECTED=1
        break
    fi
    sleep 2
done
if [ "$WIFI_CONNECTED" -eq 0 ]; then
    fail "wlan0 did not reach connected state within 60s"
fi

# Once wlan0 is fully connected, DNS should resolve in well under a
# second; the tighter 10s timeout catches genuine DNS issues quickly
# without lumping in connection-up time.
publish_status "waiting_for_dns"
DNS_OK=0
for _ in $(seq 1 10); do
    if getent hosts api.github.com >/dev/null 2>&1; then
        DNS_OK=1
        break
    fi
    sleep 1
done
if [ "$DNS_OK" -eq 0 ]; then
    fail "DNS for api.github.com unresolvable within 10s of WiFi connecting"
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

# Per-panel artifact selection. install-lib's lib_manifest_artifacts +
# lib_extract_artifacts read $PANEL_ID to pull only this panel's
# firmware + UI bundle. /opt/panel/panel_id is seeded by install-pi.sh
# at first install; missing here means the Pi is still on a pre-A.1.b
# layout — fail with a clear remediation step rather than silently
# defaulting (which could mask a real misconfiguration on a multi-panel
# fleet). One-time fix: `echo feeding_control > /opt/panel/panel_id`
# (or run install-pi.sh from the new release once).
if [ ! -f "$PANEL_ROOT/panel_id" ]; then
    fail "$PANEL_ROOT/panel_id missing — re-run install-pi.sh from this release once to seed it (or echo feeding_control > $PANEL_ROOT/panel_id)"
fi
PANEL_ID=$(tr -d '[:space:]' < "$PANEL_ROOT/panel_id")
export PANEL_ID

# Resolve target version BEFORE creating staging dirs so VERSION is set
publish_status "resolving_version" "$TARGET_VERSION"
VERSION=$(lib_resolve_version "$TARGET_VERSION")
if [ -z "$VERSION" ] || [ "$VERSION" = "null" ]; then
    fail "couldn't resolve $TARGET_VERSION to a release tag"
fi
publish_status "resolved" "$VERSION"

# If the resolved version is already running, skip the Pi-side install
# phases — lib_extract_artifacts does `rm -rf "$VERSION_DIR"` and
# VERSION_DIR == current symlink target in this case, which would wipe the
# live install mid-flight. But still run the C6 flash phase: the C6 may
# legitimately be on a different version (Group A scenario:
# install-pi.sh installs Pi-side ahead of an HA-driven OTA, and only the
# C6 actually needs flashing). HA's UpdateEntity gates the Install button
# on installed_version (read from C6's state/version) ≠ latest_version, so
# arriving here at all means the C6 is most likely behind.
SKIP_PI_INSTALL=false
if [ -n "$PREV_TARGET" ]; then
    PREV_VERSION=$(basename "$PREV_TARGET")
    if [ "$VERSION" = "$PREV_VERSION" ]; then
        publish_status "pi_already_current" "$VERSION — skipping Pi-side install, will re-flash C6"
        SKIP_PI_INSTALL=true
    fi
fi

VERSION_DIR="$PANEL_ROOT/versions/$VERSION"
STAGING="/tmp/panel-update-$VERSION"

if [ "$SKIP_PI_INSTALL" = false ]; then
    # ===== download =====

    mkdir -p "$PANEL_ROOT/versions"
    rm -rf "$STAGING"
    mkdir -p "$STAGING"

    publish_status "downloading_manifest"
    run_logged lib_download_manifest || fail "manifest download failed"

    publish_status "downloading_artifacts"
    run_logged lib_download_artifacts || fail "artifact download / sha256 verification failed"

    # ===== install =====

    publish_status "extracting"
    run_logged lib_extract_artifacts || fail "extract failed"

    publish_status "creating_venv"
    run_logged lib_create_venv || fail "venv create / pip install failed"

    publish_status "swapping_symlink"
    run_logged lib_swap_symlink || fail "symlink swap failed"

    publish_status "rendering_units"
    run_logged lib_render_units || fail "systemd unit render failed"

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

# Wait for the C6 to come back online and republish state/version with
# the new version. Until this fires, the C6 is in PENDING_VERIFY state
# and will revert to the previous firmware on any reboot — so verifying
# is what tells us the OTA actually stuck. Without this, panel-update.sh
# could declare success while the C6 was about to roll back.
#
# Times out at 90s — covers boot + Thread attach + DNS + TLS + MQTT auth
# with comfortable headroom. Bumps higher than the underlying mark-valid
# trigger because verify-c6-version.py only sees the version after the
# C6 publishes it via UART (which happens AFTER mark_valid in
# panel_app_on_connected).
VERIFY_TIMEOUT_SEC=90
publish_status "verifying_c6"
if "$PANEL_ROOT/current/bridge/.venv/bin/python" \
    "$PANEL_ROOT/current/deploy/verify-c6-version.py" \
    "$VERSION" "$VERIFY_TIMEOUT_SEC"; then
    publish_status "c6_verified" "$VERSION"
else
    fail "C6 didn't report $VERSION within ${VERIFY_TIMEOUT_SEC}s — possible flash failure or rollback"
fi

# ===== prune + cleanup =====

lib_prune_old_versions "$PREV_TARGET"
rm -rf "$STAGING"

# ===== bring network back down =====
#
# Default behavior matches V2's "Pi is offline in production" goal —
# disable WiFi after the update. Dev override: PANEL_KEEP_WIFI_ON=1 in
# the script's env (passed by controls/update.py from the cmd/update
# payload's keep_wifi_on field). Lets the user iterate without losing
# SSH after every test update.

if [ "${PANEL_KEEP_WIFI_ON:-}" = "1" ]; then
    publish_status "wifi_off_skipped" "PANEL_KEEP_WIFI_ON=1"
else
    publish_status "disabling_wifi"
    sudo nmcli radio wifi off || true
fi

publish_status "done" "$VERSION"

# Reboot to make the new install fully fresh:
#  - cog restart at script exit reloads the UI bundle, but WPE-WebKit's
#    HTTP cache has been observed to hold stale content even with
#    Cache-Control: no-cache (see panel-ui-server.py); reboot bypasses
#    that entirely.
#  - localStorage / cookies / any in-process kiosk state survive a cog
#    restart but not a reboot — clears any UI state that might be
#    incompatible with the new bundle.
#  - HA's update entity already shows success at this point because
#    state/version flipped during verifying_c6 above; the ~30-45s
#    "panel offline" during reboot is purely cosmetic.
# Failure paths (rollback, healthcheck fail, etc.) intentionally do NOT
# reboot — they exit via fail() which keeps the system up so the user
# can SSH in and inspect.
publish_status "rebooting"
sudo /sbin/shutdown -r now
# shutdown returns immediately; trap fires, then init takes over.
