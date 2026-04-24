# platform/ui-core/

Shared Vue + Pinia primitives consumed by every panel's UI.

Consumed via a Vite / TS path alias — no separate package.json, no yarn workspace; `panels/<id>/ui` imports from `@thread-panel/ui-core` and the aliases in its vite.config.ts + tsconfig.json map that to this directory's `src/`.

## Contents

```
src/
├── types.ts           # WS message discriminated unions (incoming + outgoing)
├── panel-store.ts     # Pinia store — WS lifecycle, ha_availability, roster,
│                      #   per-entity state, generic callService helper
└── index.ts           # barrel export
```

Per-panel UIs (`panels/<id>/ui/`) consume `usePanelStore` directly and add product-specific views + layout on top. If/when a panel needs a product-specific extension to the store (e.g. a derived schedule timeline for feeding_control), wrap `usePanelStore` in a product store rather than forking this one.
