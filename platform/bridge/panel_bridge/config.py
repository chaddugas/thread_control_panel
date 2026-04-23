"""Bridge configuration. Env-var overrides for everything so a systemd unit
can pin values without editing source."""

import os

UART_PORT = os.environ.get("PANEL_UART_PORT", "/dev/serial0")
UART_BAUD = int(os.environ.get("PANEL_UART_BAUD", "115200"))

# Default to listening on all interfaces so the UI can be developed on a Mac
# and pointed at the Pi during bring-up. Tighten to 127.0.0.1 in production
# once the kiosk Chromium is the only client.
WS_HOST = os.environ.get("PANEL_WS_HOST", "0.0.0.0")
WS_PORT = int(os.environ.get("PANEL_WS_PORT", "8765"))

LOG_LEVEL = os.environ.get("PANEL_LOG_LEVEL", "INFO")
