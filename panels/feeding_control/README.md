# feeding_control

Touchscreen control panel for the PetLibro auto feeder.

Panel-itself entities (reboot, wifi, brightness, screen, sensors) come from the shared platform discovery. Product-specific behavior:

- **State mirrored from HA**: feeder on/off, upcoming feeding schedule
- **Commands sent to HA**: `feed` (with quantity), `skip` (by feeding id), `toggle_feeder`

See `manifest.yaml` for the full entity list and `../../docs/build_plan.md` for project status.

```
feeding_control/
├── firmware/      # ESP-IDF project
├── ui/            # Vue+Vite app (TBD)
├── ha/            # PetLibro bridge for the thread_panel integration (TBD)
├── manifest.yaml
└── README.md
```
