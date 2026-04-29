#!/bin/bash
#
# Pi-side installer for thread_control_panel.
#
# Downloads + installs a release version into /opt/panel/. Idempotent:
# safe to re-run for the same version; running with a new version installs
# it side-by-side, atomically swaps the `current` symlink, and prunes the
# previous-previous version (keeps current + previous-1 for rollback).
#
# Usage:
#   curl -sSL https://github.com/chaddugas/thread_control_panel/releases/latest/download/install-pi.sh | bash
#   curl -sSL https://github.com/chaddugas/thread_control_panel/releases/download/v2.0.0-beta.1/install-pi.sh | bash
#   ./install-pi.sh                     # install latest stable release
#   ./install-pi.sh v2.0.0-beta.1       # install specific version
#
# Layout produced:
#   /opt/panel/
#   ├── current → versions/<v>/         # atomic symlink
#   ├── versions/<v>/
#   │   ├── bridge/         # panel-bridge-<v>.tar.gz extracted; .venv created in-place
#   │   ├── ui-dist/        # feeding_control-ui-<v>.tar.gz extracted
#   │   ├── deploy/         # panel-deploy-<v>.tar.gz extracted (units, scripts, sway config)
#   │   ├── firmware.bin    # feeding_control-firmware-<v>.bin
#   │   └── manifest.json   # release manifest snapshot
#   └── installed.json      # mirror of current/manifest.json (top-level convenience copy)
#
# Run as your normal user (NOT as root). sudo is invoked where actually needed.
# Assumes apt-installed prereqs are already present (sway, cog, python3-venv) —
# Step 18 of the V2 build plan will fold first-time apt setup into this script;
# until then, install those manually for fresh Pis.

set -euo pipefail

REPO="chaddugas/thread_control_panel"
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

# ===== resolve version =====

if [ "$TARGET_VERSION" = "latest" ]; then
    echo "→ Resolving latest release..."
    VERSION=$(curl -sSL "https://api.github.com/repos/$REPO/releases/latest" \
        | python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))")
    if [ -z "$VERSION" ] || [ "$VERSION" = "null" ]; then
        echo "install-pi.sh: couldn't resolve latest release for $REPO" >&2
        echo "  (no published releases yet? check https://github.com/$REPO/releases)" >&2
        exit 1
    fi
else
    VERSION="$TARGET_VERSION"
fi

echo "→ Installing $VERSION"

VERSION_DIR="$PANEL_ROOT/versions/$VERSION"
STAGING="/tmp/panel-install-$VERSION"

# Capture the previous symlink target before we touch anything (used later
# for the keep-current-plus-previous prune step).
PREV_TARGET=""
if [ -L "$PANEL_ROOT/current" ]; then
    PREV_TARGET=$(readlink "$PANEL_ROOT/current")
fi

# ===== set up /opt/panel/ =====

if [ ! -d "$PANEL_ROOT" ]; then
    echo "→ Creating $PANEL_ROOT (sudo)..."
    sudo mkdir -p "$PANEL_ROOT"
    sudo chown "$INSTALL_USER:$INSTALL_USER" "$PANEL_ROOT"
fi
mkdir -p "$PANEL_ROOT/versions"

# ===== download + verify =====

rm -rf "$STAGING"
mkdir -p "$STAGING"

echo "→ Downloading manifest.json..."
curl -fsSL -o "$STAGING/manifest.json" \
    "https://github.com/$REPO/releases/download/$VERSION/manifest.json"

# Emit "filename sha256" pairs for every artifact in the manifest. install-pi.sh
# downloads + verifies each one. The integration zip is HACS-side (HA box),
# not Pi-side, so we skip it here.
ARTIFACTS=$(python3 - "$STAGING/manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
out = []
for name, meta in m.get("components", {}).items():
    if name == "integration":
        continue  # HACS-side, not Pi-side
    out.append(f"{meta['filename']} {meta['sha256']}")
for panel_id, comps in m.get("panels", {}).items():
    for cname, meta in comps.items():
        out.append(f"{meta['filename']} {meta['sha256']}")
print("\n".join(out))
PY
)

echo "→ Downloading + verifying artifacts..."
while IFS=' ' read -r filename expected_sha; do
    [ -n "$filename" ] || continue
    echo "    $filename"
    curl -fsSL -o "$STAGING/$filename" \
        "https://github.com/$REPO/releases/download/$VERSION/$filename"
    actual_sha=$(shasum -a 256 "$STAGING/$filename" | awk '{print $1}')
    if [ "$actual_sha" != "$expected_sha" ]; then
        echo "install-pi.sh: sha256 mismatch on $filename" >&2
        echo "  expected: $expected_sha" >&2
        echo "  got:      $actual_sha" >&2
        exit 1
    fi
done <<< "$ARTIFACTS"

# ===== extract into version dir =====

echo "→ Extracting into $VERSION_DIR..."
rm -rf "$VERSION_DIR"
mkdir -p "$VERSION_DIR/bridge" "$VERSION_DIR/ui-dist" "$VERSION_DIR/deploy"

# bridge tarball → bridge/
bridge_tar=$(find "$STAGING" -maxdepth 1 -name 'panel-bridge-*.tar.gz' | head -n1)
[ -n "$bridge_tar" ] || { echo "install-pi.sh: bridge tarball missing in staging"; exit 1; }
tar -xzf "$bridge_tar" -C "$VERSION_DIR/bridge"

# deploy tarball → deploy/
deploy_tar=$(find "$STAGING" -maxdepth 1 -name 'panel-deploy-*.tar.gz' | head -n1)
[ -n "$deploy_tar" ] || { echo "install-pi.sh: deploy tarball missing in staging"; exit 1; }
tar -xzf "$deploy_tar" -C "$VERSION_DIR/deploy"

# UI tarball → ui-dist/. Currently single-panel; if multiple panels are ever
# built, this Pi only serves one — pick the first matching the panel-id this
# device claims. For chunk 3 / Phase 1, just take the first/only UI tarball.
ui_tar=$(find "$STAGING" -maxdepth 1 -name '*-ui-*.tar.gz' | head -n1)
[ -n "$ui_tar" ] || { echo "install-pi.sh: UI tarball missing in staging"; exit 1; }
tar -xzf "$ui_tar" -C "$VERSION_DIR/ui-dist"

# Firmware bin (named per-panel, just copy whichever is in staging)
firmware_bin=$(find "$STAGING" -maxdepth 1 -name '*-firmware-*.bin' | head -n1)
[ -n "$firmware_bin" ] || { echo "install-pi.sh: firmware bin missing in staging"; exit 1; }
cp "$firmware_bin" "$VERSION_DIR/firmware.bin"

# Snapshot the manifest into the version dir
cp "$STAGING/manifest.json" "$VERSION_DIR/manifest.json"

# ===== bridge venv =====

echo "→ Creating venv + installing bridge deps..."
if ! python3 -m venv --help | grep -q -- '--system-site-packages'; then
    echo "install-pi.sh: python3-venv module unavailable. Install with: sudo apt install python3-venv" >&2
    exit 1
fi
python3 -m venv "$VERSION_DIR/bridge/.venv"
"$VERSION_DIR/bridge/.venv/bin/pip" install --quiet --upgrade pip
"$VERSION_DIR/bridge/.venv/bin/pip" install --quiet -e "$VERSION_DIR/bridge"

# ===== atomic symlink swap =====

echo "→ Swapping current → $VERSION..."
ln -sfn "$VERSION_DIR" "$PANEL_ROOT/current.new"
mv -T "$PANEL_ROOT/current.new" "$PANEL_ROOT/current"

# ===== render systemd units =====

echo "→ Rendering systemd units into /etc/systemd/system/..."
# Replace any prior install's unit files (V1 git-clone setup or older V2).
# Templating: tracked unit files use `User=pi` as a placeholder; we render
# substituted copies so the on-disk source stays clean.
UNITS=(panel-bridge.service panel-ui.service cog.service)
LEGACY_UNITS=(cage.service)

for unit in "${LEGACY_UNITS[@]}"; do
    target="/etc/systemd/system/$unit"
    if [ -L "$target" ] || [ -f "$target" ]; then
        echo "    removing legacy $unit"
        sudo systemctl stop "$unit" 2>/dev/null || true
        sudo systemctl disable "$unit" 2>/dev/null || true
        sudo rm -f "$target"
    fi
done

for unit in "${UNITS[@]}"; do
    src="$VERSION_DIR/deploy/$unit"
    target="/etc/systemd/system/$unit"
    if [ ! -f "$src" ]; then
        echo "install-pi.sh: unit file missing: $src" >&2
        exit 1
    fi
    # An earlier (V1) install may have symlinked the source file rather than
    # rendering a copy. Replace any such symlink.
    if [ -L "$target" ]; then
        sudo rm "$target"
    fi
    sed -e "s|^User=pi$|User=$INSTALL_USER|" "$src" \
        | sudo tee "$target" > /dev/null
    sudo chmod 0644 "$target"
done

# ===== installed.json (top-level snapshot) =====

cp "$STAGING/manifest.json" "$PANEL_ROOT/installed.json"

# ===== idempotent OS-level setup =====

echo "→ Adding $INSTALL_USER to graphics/input groups..."
sudo usermod -aG video,input,render "$INSTALL_USER"

echo "→ Disabling getty on tty1 (so sway/cog can own the framebuffer)..."
sudo systemctl disable getty@tty1.service 2>/dev/null || true
sudo systemctl stop getty@tty1.service 2>/dev/null || true

# ===== reload + restart =====

echo "→ Reloading systemd..."
sudo systemctl daemon-reload

echo "→ Enabling units..."
sudo systemctl enable "${UNITS[@]}"

echo "→ Restarting bridge + UI server..."
sudo systemctl restart panel-bridge.service panel-ui.service
# cog.service is restarted on reboot (sway expects to own tty1 from boot,
# restarting it mid-session leaves the screen in a weird state).

# ===== prune old versions (keep current + previous-1) =====

NEW_BASENAME=$(basename "$VERSION_DIR")
PREV_BASENAME=""
if [ -n "$PREV_TARGET" ]; then
    PREV_BASENAME=$(basename "$PREV_TARGET")
fi

if [ -d "$PANEL_ROOT/versions" ]; then
    for v in $(ls -1 "$PANEL_ROOT/versions/" 2>/dev/null); do
        if [ "$v" = "$NEW_BASENAME" ] || [ "$v" = "$PREV_BASENAME" ]; then
            continue
        fi
        echo "→ Pruning old version $v"
        rm -rf "$PANEL_ROOT/versions/$v"
    done
fi

# ===== cleanup staging =====

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
