#!/bin/bash
#
# Runner for panel-bridge.service. V2 form: no git, no auto-update — just
# exec the bridge from /opt/panel/current/bridge/. Updates land via
# install-pi.sh (manual SSH) or panel-update.sh (HA-orchestrated, Phase 3).

set -e

PANEL_ROOT="${PANEL_ROOT:-/opt/panel}"
BRIDGE_DIR="$PANEL_ROOT/current/bridge"

if [ ! -d "$BRIDGE_DIR/.venv" ]; then
    echo "panel-bridge: venv missing at $BRIDGE_DIR/.venv" >&2
    echo "  Run install-pi.sh to install or repair." >&2
    exit 1
fi

cd "$BRIDGE_DIR"
exec "$BRIDGE_DIR/.venv/bin/python" -m panel_bridge
