# Contract — ui-bundle

> **Mirrored copy.** The authoritative version of this document lives with the platform source (private); this copy is republished for UI authors at each platform release. Internal cross-references may point into the source repo.

The handoff between an implementation UI (any framework, any repo) and the panel platform: what a UI ships, how the shell mounts it, and what the document it lives in does and doesn't allow. The firmware owns the kiosk document — an implementation UI is a tenant that ships **assets, never a page**.

## Participants

- **Provider:** the UI author's repo. Builds the bundle artifact; publishes it as a GitHub release asset (or any HTTPS-reachable tarball). The repo's own CI cutting release assets is the blessed shape ([versioning-release](versioning-release.md) governs only the platform's releases, not the UI repo's).
- **Consumer:** the platform. [`ui-core`](../platform/ui-core.md)'s PanelRoot performs the mount; the [deploy](../platform/deploy.md) engines download/validate/install and serve `/ui/`; the [integration](../platform/integration.md)'s HA flow configures the source; the bridge's `ui_status`/watchdog ([bridge](../platform/bridge.md)) drive load, reload, and quarantine.

## Definition

### The artifact

A `.tar.gz` whose **root** carries the fixed entry names:

| Entry | Required | Content |
|---|---|---|
| `panel-ui.js` | yes — installs are refused without it | ESM entry exporting `mount` |
| `panel-ui.css` | no | the bundle's stylesheet, attached to the document head before mount |
| anything else (`assets/…`) | no | chunks, fonts, images — referenced relatively |

The platform serves the installed bundle under **`/ui/`**, so relative references inside `panel-ui.js`/`panel-ui.css` resolve as `/ui/<path>`. There is no `index.html` in the contract — a page in the tarball is dead weight; it is never served.

### The mount

```ts
export function mount(el: HTMLElement): void
```

- The shell imports `/ui/panel-ui.js` and calls `mount` **exactly once** per page lifetime, handing it a **light-DOM** node the shell owns. Nothing may self-execute at import time — the shell controls load timing, and a quarantined bundle is never imported at all.
- The node is **hidden, never unmounted**, while a platform screen (pairing, OTA, quarantine) has the display — tenant state survives.
- There is no unmount. A new install flips `ui_status.stamp` and the shell reloads the page (ESM modules can't be unloaded); the page also survives a platform OTA's file swap by design.

### The document (what the tenant gets, and doesn't)

- **Store:** import `"/_panel/store.v1.js"` ([store-api](store-api.md)) and keep it external in builds. The shell already owns the connection — a production bundle never calls `connect()`/`disconnect()`.
- **CSP, offline by design:** the document allows same-origin + the bridge WS, nothing else. Fonts, images, data — everything ships in the bundle or arrives through the store. A UI that wants the web is on the wrong firmware.
- **Shadow/light split:** the tenant mounts in light DOM (normal head styles and Teleport behavior); the platform screens are shadow-rooted and unreachable. Tenant CSS is global by selector — keep it under your mount, and never style `html`/`body`/document chrome: the shell owns the document.
- **Liveness:** the shell heartbeats the bridge; a bundle that wedges the main thread earns two cog restarts and then **quarantine** — the shell stops importing it and shows a failure screen until a new bundle is installed (or the panel reboots). Uncaught errors and `console.error` land in the panel's journald and in the quarantine screen's evidence ring.

### Delivery

The HA config flow sets the source — `owner/repo` (latest release's `.tar.gz`; the asset name is pinned when there are several) or a raw HTTPS URL — and pushes installs over the existing rails; `panel-ui-install` is the SSH-side equivalent. A private repo's download token lives only on the panel, 0600.

## Invariants & traps

- **`panel-ui.js` sits at the tar root** (`./panel-ui.js` counts) — the installer validates and refuses, so a nested `dist/` prefix is a failed install, not a broken panel.
- **The entry's exports ARE the contract.** App-mode bundlers strip them: Vite needs a plain rollup-input build with `preserveEntrySignatures: "exports-only"` (lib mode instead force-inlines every asset — a different trap).
- **Define `process.env.NODE_ENV` at build time.** Nothing re-bundles the artifact and browsers have no `process`; an undefined reference is a blank kiosk.
- **Fixed output names, relative asset refs.** `panel-ui.js` / `panel-ui.css` exactly; hashed names belong under `assets/`.
- **Never ship platform chrome, a page, or a CSP** — pairing/OTA/health/quarantine screens are the shell's, and the document policy is the platform's.
- **The dev harness is the only place `connect()` is yours** (no shell exists under `yarn dev`); it must never ship — keep it in a `dev.ts` the build never references.

## Examples

The minimal legal bundle:

```js
// panel-ui.js — no framework, no build step
import { $entities, callService } from "/_panel/store.v1.js";

export function mount(el) {
  const h1 = document.createElement("h1");
  el.appendChild(h1);
  $entities.subscribe((all) => {
    h1.textContent = all["switch.pet_feeder"]?.state ?? "…";
  });
}
```

Characteristic mistake — a page-era app self-mounting at import:

```js
createApp(App).mount("#app");          // wrong: no #app, no page, import ≠ permission
export function mount(el) {
  createApp(App).mount(el);            // correct: the shell decides when (and whether)
}
```

The root README carries the full authoring recipe (Vite config, dev flow, release shape); this document is the authoritative *what*.

