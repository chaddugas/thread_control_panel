# feeding_control/ui

Vue 3 + Vite + Pinia. Connects to the bridge over WebSocket; mirrors panel state into a Pinia store; exposes action helpers for outgoing commands.

Layout is a minimal scaffold — a connection pill, sensor cards, and one smoke-test button that toggles an HA light via the generic `callService` helper. The real layout (schedule view, feed/skip controls, panel-itself surfaces) lands in step 14.

## Layout

```
src/
├── main.ts                # createApp + Pinia
├── App.vue                # scaffold view: connection + sensor cards + toggle-light smoke test
├── style.css              # tiny global reset
├── env.d.ts               # Vite env type augmentation
├── types.ts               # WS message discriminated unions
└── stores/
    └── panel.ts           # WS lifecycle, availability, roster, entity state, callService
```

The store's WS plumbing + availability/entity state are platform-shaped — they move to `platform/ui-core/` when that's extracted in step 14.

## Install

```bash
cd panels/feeding_control/ui
yarn install
```

## Dev workflow

The bridge defaults to listening on `0.0.0.0:8765`, so develop on the Mac against the Pi's running bridge:

```bash
# one-time per Mac, after cloning:
cp .env.example .env.local
# edit VITE_WS_URL if your Pi's hostname differs

yarn dev
# → http://localhost:5173
```

You should see "connected" within a second, the proximity card update every ~1s, ambient every ~5s, and the Pinia devtools show `haAvailability`, `roster`, and `entities` populated as the C6 forwards retained state from HA.

## Build for kiosk

```bash
yarn build
# → dist/ — static files served from somewhere on the Pi (TBD: step 15 / cage deploy)
```

## Type check

```bash
yarn type-check
```

Run before committing if you've changed types or store shape — `vue-tsc` runs as part of `yarn build` too.
