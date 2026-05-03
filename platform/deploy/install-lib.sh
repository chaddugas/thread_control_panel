#!/bin/bash
# install-lib.sh — shared install helpers, sourced by install-pi.sh and
# panel-update.sh. NOT directly executable.
#
# Functions assume the caller has set:
#   PANEL_ROOT     — typically /opt/panel
#   PANEL_ID       — which panel this Pi is (e.g. feeding_control); seeded
#                    by install-pi.sh into /opt/panel/panel_id and exported
#                    by both callers. Drives per-panel artifact selection.
#   REPO           — github org/repo, e.g. chaddugas/thread_control_panel
#   INSTALL_USER   — the user that runs the services (templated into units)
#   STAGING        — temp dir for downloads (caller creates + cleans up)
#   VERSION        — target release tag, with v prefix (e.g. v2.0.0-beta.4)
#   VERSION_DIR    — destination dir, e.g. /opt/panel/versions/v2.0.0-beta.4
#
# All functions return non-zero on failure; callers should run with
# `set -e` or check exit codes.

# Resolve "latest" → actual tag name via GitHub API. Pass through any
# explicit tag unchanged. Latest excludes prereleases (GitHub default).
lib_resolve_version() {
    local target="$1"
    if [ "$target" = "latest" ]; then
        curl -sSL "https://api.github.com/repos/$REPO/releases/latest" \
            | python3 -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))"
    else
        echo "$target"
    fi
}

# Download manifest.json for $VERSION into $STAGING.
lib_download_manifest() {
    curl -fsSL -o "$STAGING/manifest.json" \
        "https://github.com/$REPO/releases/download/$VERSION/manifest.json"
}

# Emit "filename sha256" pairs for every Pi-side artifact in the manifest
# (skips the integration zip — that's HACS-side, not ours). Per-panel
# artifacts are filtered to $PANEL_ID; non-matching panels are skipped so
# a Pi never downloads firmware/UI for panels it isn't.
lib_manifest_artifacts() {
    python3 - "$STAGING/manifest.json" "$PANEL_ID" <<'PY'
import json, sys
manifest_path, panel_id = sys.argv[1], sys.argv[2]
m = json.load(open(manifest_path))
for name, meta in m.get("components", {}).items():
    if name == "integration":
        continue  # HACS-side, not Pi-side
    print(f"{meta['filename']} {meta['sha256']}")
panels = m.get("panels", {})
if panel_id not in panels:
    sys.stderr.write(
        f"install-lib: panel_id '{panel_id}' not in release manifest. "
        f"Available: {sorted(panels)}\n"
    )
    sys.exit(1)
for cname, meta in panels[panel_id].items():
    print(f"{meta['filename']} {meta['sha256']}")
PY
}

# Download every Pi-side artifact into $STAGING and verify its sha256.
# Returns non-zero on first mismatch. Also runs lib_verify_firmware_signature
# at the end — sha256 covers transit corruption, signature covers
# authenticity (Group D).
lib_download_artifacts() {
    local filename expected_sha actual_sha
    while IFS=' ' read -r filename expected_sha; do
        [ -n "$filename" ] || continue
        echo "    $filename"
        curl -fsSL -o "$STAGING/$filename" \
            "https://github.com/$REPO/releases/download/$VERSION/$filename"
        actual_sha=$(shasum -a 256 "$STAGING/$filename" | awk '{print $1}')
        if [ "$actual_sha" != "$expected_sha" ]; then
            echo "install-lib: sha256 mismatch on $filename" >&2
            echo "  expected: $expected_sha" >&2
            echo "  got:      $actual_sha" >&2
            return 1
        fi
    done < <(lib_manifest_artifacts)

    lib_verify_firmware_signature || return 1
}

# Download the per-release public key + each firmware's .minisig, then
# verify with `minisign -V`. Pubkey is a top-level artifact (not in
# manifest.json) — it's the trust anchor for that release's signing, and
# direct download avoids a chicken-and-egg with the deploy tarball not yet
# being extracted at this point. Convention: every <panel>-firmware-*.bin
# has a sibling .minisig in the same release.
lib_verify_firmware_signature() {
    if ! command -v minisign >/dev/null 2>&1; then
        echo "install-lib: minisign not installed — required for firmware signature verification (apt install minisign)" >&2
        return 1
    fi

    local pubkey="$STAGING/firmware-signing.pub"
    if [ ! -f "$pubkey" ]; then
        echo "    firmware-signing.pub"
        curl -fsSL -o "$pubkey" \
            "https://github.com/$REPO/releases/download/$VERSION/firmware-signing.pub" \
            || { echo "install-lib: failed to download firmware-signing.pub" >&2; return 1; }
    fi

    local firmware_bin sig
    for firmware_bin in "$STAGING"/*-firmware-*.bin; do
        [ -f "$firmware_bin" ] || continue
        sig="${firmware_bin}.minisig"
        if [ ! -f "$sig" ]; then
            echo "    $(basename "$sig")"
            curl -fsSL -o "$sig" \
                "https://github.com/$REPO/releases/download/$VERSION/$(basename "$sig")" \
                || { echo "install-lib: failed to download $(basename "$sig")" >&2; return 1; }
        fi
        echo "    verifying signature: $(basename "$firmware_bin")"
        if ! minisign -V -p "$pubkey" -m "$firmware_bin" -q >/dev/null 2>&1; then
            echo "install-lib: minisign verification FAILED for $(basename "$firmware_bin")" >&2
            echo "  pubkey: $pubkey" >&2
            echo "  signature: $sig" >&2
            return 1
        fi
    done
}

# Extract the downloaded artifacts into $VERSION_DIR. Wipes $VERSION_DIR
# if it already exists so we always start from a clean tree.
lib_extract_artifacts() {
    rm -rf "$VERSION_DIR"
    mkdir -p "$VERSION_DIR/bridge" "$VERSION_DIR/ui-dist" "$VERSION_DIR/deploy"

    local bridge_tar
    bridge_tar=$(find "$STAGING" -maxdepth 1 -name 'panel-bridge-*.tar.gz' | head -n1)
    [ -n "$bridge_tar" ] || { echo "install-lib: bridge tarball missing" >&2; return 1; }
    tar -xzf "$bridge_tar" -C "$VERSION_DIR/bridge"

    local deploy_tar
    deploy_tar=$(find "$STAGING" -maxdepth 1 -name 'panel-deploy-*.tar.gz' | head -n1)
    [ -n "$deploy_tar" ] || { echo "install-lib: deploy tarball missing" >&2; return 1; }
    tar -xzf "$deploy_tar" -C "$VERSION_DIR/deploy"

    # Per-panel UI + firmware. lib_manifest_artifacts already filtered the
    # download set to $PANEL_ID's artifacts, so the panel-specific glob is
    # belt-and-suspenders against any future stray file in $STAGING.
    local ui_tar
    ui_tar=$(find "$STAGING" -maxdepth 1 -name "${PANEL_ID}-ui-*.tar.gz" | head -n1)
    [ -n "$ui_tar" ] || { echo "install-lib: ${PANEL_ID} UI tarball missing in $STAGING" >&2; return 1; }
    tar -xzf "$ui_tar" -C "$VERSION_DIR/ui-dist"

    local firmware_bin
    firmware_bin=$(find "$STAGING" -maxdepth 1 -name "${PANEL_ID}-firmware-*.bin" | head -n1)
    [ -n "$firmware_bin" ] || { echo "install-lib: ${PANEL_ID} firmware bin missing in $STAGING" >&2; return 1; }
    cp "$firmware_bin" "$VERSION_DIR/firmware.bin"

    cp "$STAGING/manifest.json" "$VERSION_DIR/manifest.json"
}

# Create a venv inside $VERSION_DIR/bridge/ and install bridge package.
# pip install needs network — must run while WiFi is up.
lib_create_venv() {
    if ! python3 -m venv --help | grep -q -- '--system-site-packages'; then
        echo "install-lib: python3-venv unavailable. Install: sudo apt install python3-venv" >&2
        return 1
    fi
    python3 -m venv "$VERSION_DIR/bridge/.venv"
    "$VERSION_DIR/bridge/.venv/bin/pip" install --quiet --upgrade pip
    "$VERSION_DIR/bridge/.venv/bin/pip" install --quiet -e "$VERSION_DIR/bridge"
}

# Atomic: ln -sfn (create or replace symlink) + mv -T (atomic rename).
# If anything before this point failed, /opt/panel/current still points
# at the previous version.
lib_swap_symlink() {
    ln -sfn "$VERSION_DIR" "$PANEL_ROOT/current.new"
    mv -T "$PANEL_ROOT/current.new" "$PANEL_ROOT/current"
}

# Render systemd units from $VERSION_DIR/deploy/*.service into
# /etc/systemd/system/, templating User=. Removes legacy units that an
# earlier (V1) install may have placed there.
lib_render_units() {
    local units=(panel-bridge.service panel-ui.service cog.service)
    local legacy_units=(cage.service)
    local unit src target

    for unit in "${legacy_units[@]}"; do
        target="/etc/systemd/system/$unit"
        if [ -L "$target" ] || [ -f "$target" ]; then
            sudo systemctl stop "$unit" 2>/dev/null || true
            sudo systemctl disable "$unit" 2>/dev/null || true
            sudo rm -f "$target"
        fi
    done

    for unit in "${units[@]}"; do
        src="$VERSION_DIR/deploy/$unit"
        target="/etc/systemd/system/$unit"
        if [ ! -f "$src" ]; then
            echo "install-lib: unit file missing: $src" >&2
            return 1
        fi
        # Earlier (V1) install may have symlinked. Replace with copy.
        if [ -L "$target" ]; then
            sudo rm "$target"
        fi
        sed -e "s|^User=pi$|User=$INSTALL_USER|" "$src" \
            | sudo tee "$target" > /dev/null
        sudo chmod 0644 "$target"
    done

    # Always reload after rewriting unit files. Without this, a subsequent
    # `systemctl restart` emits "the unit file changed on disk" even though
    # restart works correctly (the rewritten content is structurally
    # identical and ExecStart points through the /opt/panel/current
    # symlink). Reload makes systemd's in-memory config match disk so the
    # warning goes away.
    sudo systemctl daemon-reload
}

# Top-level snapshot of what's currently installed. Useful for debugging
# and for panel-update.sh to compare versions across runs.
lib_update_installed_json() {
    cp "$STAGING/manifest.json" "$PANEL_ROOT/installed.json"
}

# Prune all version dirs except the new one and the previous one. Caller
# must capture the previous symlink target BEFORE calling lib_swap_symlink
# and pass it as $1 (basename or full path; both handled).
lib_prune_old_versions() {
    local prev_target="${1:-}"
    local new_basename
    new_basename=$(basename "$VERSION_DIR")
    local prev_basename=""
    if [ -n "$prev_target" ]; then
        prev_basename=$(basename "$prev_target")
    fi

    [ -d "$PANEL_ROOT/versions" ] || return 0

    local v
    for v in $(ls -1 "$PANEL_ROOT/versions/" 2>/dev/null); do
        if [ "$v" = "$new_basename" ] || [ "$v" = "$prev_basename" ]; then
            continue
        fi
        echo "→ Pruning old version $v"
        rm -rf "$PANEL_ROOT/versions/$v"
    done
}
