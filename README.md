# Thread Control Panel — releases

Release assets for the [Thread Control Panel](https://github.com/chaddugas/thread_control_panel) platform: no-WiFi, Thread-based touchscreen control panels for Home Assistant. This repo carries releases only — no source.

**Install a panel** (Raspberry Pi OS Lite, panel plugged in over USB):

```bash
curl -sSL https://github.com/chaddugas/thread_control_panel/releases/latest/download/install-pi.sh | bash
```

**Build your own panel UI:** download `ui-starter.zip` from the latest release — a working foundation in any framework against the panel's contracts. Author docs, republished here per release:

- [Build your own UI](docs/build-your-own-ui.md) — the guided walkthrough
- [The store API](docs/store-api.md) — the data surface a UI programs against
- [The ui-bundle contract](docs/ui-bundle.md) — what a UI ships and how the panel mounts it
