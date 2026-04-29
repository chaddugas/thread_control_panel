# feeding_control

Touchscreen control panel for the PetLibro auto feeder.

This is the **first product** on the Thread Control Panel platform — all HA state forwarding, availability handshake, MQTT schema, and UI plumbing are platform-shared; only the UI's layout and the reference manifest are product-specific.

## Layout

```
feeding_control/
├── firmware/      # ESP-IDF project (depends on platform/firmware/components/panel_platform)
├── ui/            # Vue+Vite app (smoke-test scaffold, real layout comes in step 14)
├── ha/            # reference manifest template + hatch for product-specific HA-side Python
└── README.md
```

## How product state reaches the panel

The `thread_panel` custom HA integration takes a YAML manifest ([ha/manifest.yaml](ha/manifest.yaml) is a template — paste into HA's config flow), forwards every declared HA entity over MQTT + UART to the panel, and dispatches any `call_service` the panel fires back. The panel shows real PetLibro entities from HA rather than replicating any petlibro-specific logic on-device.

See [`../../docs/build_plan_v1.md`](../../docs/build_plan_v1.md) for current production state and architecture, and [`../../docs/build_plan_v2.md`](../../docs/build_plan_v2.md) for the active V2 work.
