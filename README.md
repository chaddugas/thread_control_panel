# Thread Control Panel

Touchscreen control panels for Home Assistant that connect over **Thread** — no WiFi network membership, no cloud, no apps. A panel is a Raspberry Pi touchscreen paired with an ESP32 radio that talks directly to your Home Assistant, showing whatever interface you give it.

This repository carries **releases and documentation only** — install scripts, firmware, and panel software. The platform source is private.

## Install a panel

Flash Raspberry Pi OS Lite, plug the panel in over USB, and run:

```bash
curl -sSL https://github.com/chaddugas/thread_control_panel/releases/latest/download/install-pi.sh | bash
```

Then pair from Home Assistant: the panel shows up under **Settings → Devices & Services** as a discovered Thread Panel — pick the entities it should see, paste its hardware config, confirm the 6-digit code on the panel's screen, done. (Your Home Assistant host needs the project CA at `/ssl/panel-ca.crt`.)

## Updates

Panels keep themselves current from this repository: each one exposes an update entity in Home Assistant, and you install from the device page whenever one is offered.

## Build your own UI

A panel's interface is a bundle of ordinary web assets you publish as a GitHub release — any framework, or none. The fastest start is **`ui-starter.zip`** from the [latest release](https://github.com/chaddugas/thread_control_panel/releases/latest): a working scaffold to unzip, push, and point a panel at.

- [Build your own UI](docs/build-your-own-ui.md) — the guided walkthrough, from blank repo to a panel running your app
- [Auto-update your panel UI](docs/auto-update.md) — make publishing a release install it on the panel by itself
- [Store API reference](docs/store-api.md) — every store and command helper, generated from the typings at each release
- [`store.v1.d.ts`](store.v1.d.ts) — the store's TypeScript declarations, republished per release
