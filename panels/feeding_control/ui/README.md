# feeding_control/ui

Vue 3 + Vite + Pinia. Connects to the bridge over WebSocket; mirrors panel state into a Pinia store; exposes action helpers for outgoing commands.

Smoke-test scaffold for now — real layout, schedule view, and feed/skip buttons land once HA bridging is wired up and the entity shapes are firm.

## Layout

```
src/
├── main.ts                # createApp + Pinia
├── App.vue                # smoke-test view: connection + sensor cards + send-hello button
├── style.css              # tiny global reset
├── env.d.ts               # Vite env type augmentation
├── types.ts               # WS message discriminated unions
└── stores/
    └── panel.ts           # WS lifecycle, sensor state, action helpers
```

The store's WS plumbing + sensor state are platform-shaped — likely candidates for promotion to `platform/ui-core/` when a second panel forces the abstraction.

## Install

```bash
cd panels/feeding_control/ui
npm install
```

## Dev workflow

The bridge defaults to listening on `0.0.0.0:8765`, so develop on the Mac against the Pi's running bridge:

```bash
# one-time per Mac, after cloning:
cp .env.example .env.local
# edit VITE_WS_URL if your Pi's hostname differs

npm run dev
# → http://localhost:5173
```

You should see "connected" within a second, then the proximity card update every ~1s and ambient every ~5s. Click "Send hello to C6" and confirm a `panel_app: UART RX (...)` line appears on the C6 monitor.

## Build for kiosk

```bash
npm run build
# → dist/ — static files served from somewhere on the Pi (TBD: cage step)
```

## Type check

```bash
npm run type-check
```

Run before committing if you've changed types or store shape — `vue-tsc` runs as part of `npm run build` too.
