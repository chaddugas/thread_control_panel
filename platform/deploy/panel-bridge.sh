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

# network-online.target on NetworkManager can fire before DNS is actually
# usable, so a fresh boot's first `git pull` would hit "Could not resolve
# hostname github.com". The previous version of this script retried the
# pull itself 5 × 5s; that was sometimes still too short. Now we explicitly
# wait for DNS resolvability of github.com before attempting the pull.
# `getent hosts` uses the system NSS resolver, the same path git would
# take, so a successful lookup means git's about to succeed too.
#
# Bounded at ~60s. If the Pi is genuinely offline (production deploys with
# WiFi disabled) we skip the pull entirely and start the bridge with
# whatever code is already on disk — not a failure, just running stale.
echo "→ Waiting for DNS to resolve github.com..."
DNS_OK=0
for attempt in $(seq 1 30); do
    if getent hosts github.com >/dev/null 2>&1; then
        DNS_OK=1
        echo "→ DNS resolvable (after ${attempt} attempt$([ "$attempt" = "1" ] || echo s))"
        break
    fi
    sleep 2
done

if [ "$DNS_OK" -eq 0 ]; then
    echo "panel-bridge: DNS for github.com still not resolvable after 60s — skipping pull, starting bridge with current checkout" >&2
else
    echo "→ Pulling latest..."
    if ! git -C "$REPO_DIR" pull --ff-only; then
        echo "panel-bridge: git pull failed (auth? merge conflict?) — continuing with current checkout" >&2
    fi
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
