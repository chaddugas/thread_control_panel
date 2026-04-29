# platform/

Shared code consumed by every panel in the fleet. Anything here must be device-agnostic — if it would only ever be used by `feeding_control`, it belongs in `panels/feeding_control/` instead.

| Subdir | Lives where | Role |
|---|---|---|
| `firmware/` | C6 | ESP-IDF component (`panel_platform`) — Thread/MQTT/UART infrastructure |
| `bridge/` | Pi | Python WS+UART bridge core |
| `ui-core/` | Pi (browser) | Vue+Pinia primitives shared across panel UIs (TBD — extracted in step 14) |
| `deploy/` | Pi | systemd units, install scripts (TBD — landed in step 15) |
| `diagnostics/` | Pi | Hardware smoke-test scripts |

The `thread_panel` HA custom integration lives at [`integration/thread_panel/`](integration/thread_panel/). HACS consumes it via release-zip artifacts (configured by [`../hacs.json`](../hacs.json) `zip_release: true`), so the source is no longer constrained to the repo root. See [`../docs/build_plan_v2.md`](../docs/build_plan_v2.md) for the artifact-based release flow.
