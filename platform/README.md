# platform/

Shared code consumed by every panel in the fleet. Anything here must be device-agnostic — if it would only ever be used by `feeding_control`, it belongs in `panels/feeding_control/` instead.

| Subdir | Lives where | Role |
|---|---|---|
| `firmware/` | C6 | ESP-IDF component (`panel_platform`) — Thread/MQTT/UART/discovery infrastructure |
| `bridge/` | Pi | Python WS+UART bridge core |
| `ui-core/` | Pi (browser) | Vue+Pinia primitives shared across panel UIs |
| `ha-integration/` | HA | `custom_components/thread_panel/` |
| `deploy/` | Pi | systemd units, install scripts |
| `diagnostics/` | Pi | Hardware smoke-test scripts |
