# platform/

Shared code consumed by every panel in the fleet. Anything here must be device-agnostic — if it would only ever be used by `feeding_control`, it belongs in `panels/feeding_control/` instead.

| Subdir | Lives where | Role |
|---|---|---|
| `firmware/` | C6 | ESP-IDF component (`panel_platform`) — Thread/MQTT/UART infrastructure |
| `bridge/` | Pi | Python WS+UART bridge core |
| `ui-core/` | Pi (browser) | Vue+Pinia primitives shared across panel UIs (TBD — extracted in step 14) |
| `deploy/` | Pi | systemd units, install scripts (TBD — landed in step 15) |
| `diagnostics/` | Pi | Hardware smoke-test scripts |

The `thread_panel` HA custom integration lives at the repo root (`custom_components/thread_panel/`) rather than under `platform/` because HACS validates that path for repo compliance — see `../docs/build_plan.md`.
