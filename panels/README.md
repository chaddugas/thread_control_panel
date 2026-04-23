# panels/

Per-product directories. Each subdirectory is one physical panel type, all sharing the same hardware platform but with different UIs and HA integrations.

Per-panel structure:
```
<panel_id>/
├── firmware/      # ESP-IDF project; depends on platform/firmware/components/panel_platform
├── ui/            # Vue+Vite app; (imports platform/ui-core once extracted)
└── ha/            # reference manifest template + optional product-specific HA-side Python
```

To add a new panel: copy `feeding_control/` as a template, rename directories and `panel_id`, swap the product code (panel_app.c, UI views), and author the reference manifest under `ha/manifest.yaml`. The `thread_panel` HA integration at the repo root handles any new panel without code changes — each panel becomes an additional config entry.
