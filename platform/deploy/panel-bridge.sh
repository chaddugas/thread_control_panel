#!/bin/bash
#
# Runner for the panel_bridge systemd service. Mirrors the `panel-bridge`
# shell function in ~/.bashrc so the interactive alias and the service
# behave identically — pull latest, sync deps if pyproject.toml changed,
# exec the bridge.
#
# Difference vs. the interactive alias: a transient `git pull` failure
# (network not yet up at boot, etc.) logs a warning and continues rather
# than aborting. Better to run stale code than no code.

set -e

REPO_DIR="${PANEL_BRIDGE_REPO:-$HOME/thread_control_panel}"
BRIDGE_DIR="$REPO_DIR/platform/bridge"
MARKER="$BRIDGE_DIR/.venv/.deps_installed"

if [ ! -d "$BRIDGE_DIR/.venv" ]; then
    echo "panel-bridge: venv missing at $BRIDGE_DIR/.venv" >&2
    echo "  First-time setup:  cd $BRIDGE_DIR && python3 -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi

echo "→ Pulling latest..."
# network-online.target on NetworkManager can fire before DNS is actually
# usable, so a fresh boot's first `git pull` often hits "Could not resolve
# hostname github.com". Retry a few times with short sleeps before giving
# up — by then either DNS is up or the network really is unavailable.
PULL_OK=0
for attempt in 1 2 3 4 5; do
    if git -C "$REPO_DIR" pull --ff-only; then
        PULL_OK=1
        break
    fi
    echo "panel-bridge: git pull attempt $attempt failed, retrying in 5s..." >&2
    sleep 5
done
if [ "$PULL_OK" -eq 0 ]; then
    echo "panel-bridge: git pull failed after retries — continuing with current checkout" >&2
fi

if [ ! -f "$MARKER" ] || [ "$BRIDGE_DIR/pyproject.toml" -nt "$MARKER" ]; then
    echo "→ Deps changed, syncing..."
    if "$BRIDGE_DIR/.venv/bin/python" -m pip install -e "$BRIDGE_DIR" --quiet; then
        touch "$MARKER"
    else
        echo "panel-bridge: pip install failed (no network?) — starting with stale deps" >&2
        # Intentionally don't touch the marker; we'll retry on the next
        # boot when network is available.
    fi
fi

echo "→ Starting bridge..."
cd "$BRIDGE_DIR"
exec "$BRIDGE_DIR/.venv/bin/python" -m panel_bridge
