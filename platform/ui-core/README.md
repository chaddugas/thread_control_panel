# platform/ui-core/

Shared Vue + Pinia primitives consumed by every panel's UI. Lives as a workspace package; per-panel UIs import from here.

Planned contents:

- `stores/ws.ts` — WebSocket client + reconnect handling
- `stores/panel.ts` — base store for panel-itself state (availability, brightness, screen on/off, wifi, sensors)
- `components/PanelStatus.vue`, `WifiConfig.vue`, `BrightnessSlider.vue` — common widgets every panel uses
- `styles/` — design tokens, CSS reset

Per-panel UIs (`panels/<id>/ui/`) extend the base store and add product-specific views.
