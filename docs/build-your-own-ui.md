# Build your own UI

A panel's product UI is a **bundle of assets the panel downloads and mounts** — any framework, or none. The platform owns the kiosk page (pairing, updates, health, failure screens); your app is a tenant it mounts into a node it hands you. The data side is the [store API](store-api.md); the handoff side — what you ship and how the panel mounts it — is covered end-to-end by this guide.

The shape of it:

- Your build emits **`panel-ui.js`** (an ES module exporting `mount(el)`) and optionally **`panel-ui.css`** + an `assets/` directory, tarred at the **root** of a `.tar.gz`.
- You publish that tarball as a GitHub release asset and point the panel at `owner/repo` from Home Assistant (Configure → Panel UI source). The panel downloads, validates, installs, and hot-reloads into it — no reboot.
- On the panel there is no internet: the document's CSP allows same-origin + the panel's own websocket, nothing else. Fonts and images ship in your bundle; data arrives through the store.
- Don't self-mount, don't `connect()` in production, don't style `html`/`body` — the shell owns the document and the store connection. And if your app wedges the panel's main thread, the platform restarts the browser twice and then quarantines your bundle behind a failure screen until you ship a fixed one.

### The store, in one example

The store is a self-contained ES module the panel serves at `/_panel/store.v1.js` — subscribable [nanostores](https://github.com/nanostores/nanostores) stores for everything the panel knows, plus command helpers back to HA.

```js
// panel-ui.js — the complete contract, no framework, no build step
import { $entities, callService } from "/_panel/store.v1.js";

export function mount(el) {
  const h1 = document.createElement("h1");
  el.appendChild(h1);
  $entities.subscribe((all) => {
    h1.textContent = all["switch.pet_feeder"]?.state ?? "…";
  });
}
```

`tar -czf my-ui.tar.gz panel-ui.js`, publish, configure — that's a shippable UI.

**Or skip the setup entirely:** every platform release carries **[`ui-starter.zip`](https://github.com/chaddugas/thread_control_panel/releases/latest)** — this scaffold as a working repo (contract Vite config, dev harness, release workflow, typed store). Unzip, `git init`, push, point the panel at it.

### Developing against a live panel

Dev runs your app as a normal page on your machine, talking to a real panel over the LAN. One knob: `VITE_PANEL_HOST` (the panel's mDNS name, shown on its health screen). The panel must have WiFi on while you develop (`switch.panel_wifi` in HA) — production panels are Thread-only.

Keep the dev entry out of the bundle: `index.html` points at a `dev.ts` harness that connects and self-mounts; the build's input is `main.ts`, which only exports `mount`.

```js
// src/dev.ts — dev-only; the build never references it
import { connect } from "/_panel/store.v1.js";
import { mount } from "./main";

const host = import.meta.env.VITE_PANEL_HOST;
connect(host ? { url: `ws://${host}:8765` } : {});
mount(document.getElementById("app"));
```

### The Vite config (any bundler equivalent works)

```js
import { defineConfig, loadEnv } from "vite";
import { fileURLToPath, URL } from "node:url";

const STORE = "/_panel/store.v1.js";

// Dev import-analysis resolves rooted specifiers before the proxy can serve
// them; this marks the store import resolved and feeds the analyzer an empty
// shim. The browser's real request still hits server.proxy → the panel.
const panelStoreDevShim = () => ({
  name: "panel-store-dev-shim",
  apply: "serve",
  resolveId: (id) => (id === STORE ? id : undefined),
  load: (id) => (id === STORE ? "export {};" : undefined),
});

export default defineConfig(({ command, mode }) => {
  const panelHost = loadEnv(mode, process.cwd(), "").VITE_PANEL_HOST;
  return {
    plugins: [/* your framework plugin, */ panelStoreDevShim()],
    // Nothing re-bundles the artifact and browsers have no `process`.
    define:
      command === "build"
        ? { "process.env.NODE_ENV": JSON.stringify("production") }
        : undefined,
    build: {
      // Not lib mode (it force-inlines assets); fixed names are the contract.
      cssCodeSplit: false,
      rollupOptions: {
        external: [STORE],
        input: fileURLToPath(new URL("./src/main.ts", import.meta.url)),
        // The entry's exports ARE the contract (mount).
        preserveEntrySignatures: "exports-only",
        output: {
          format: "es",
          entryFileNames: "panel-ui.js",
          chunkFileNames: "assets/[name]-[hash].js",
          assetFileNames: (info) =>
            (info.names?.[0] ?? "").endsWith(".css")
              ? "panel-ui.css"
              : "assets/[name]-[hash][extname]",
        },
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: panelHost ? { "/_panel": `http://${panelHost}:8080` } : undefined,
    },
  };
});
```

Converting an existing Vite app is exactly four touches: this config, `main.ts` exporting `mount(el)` instead of self-mounting, the `dev.ts` harness, and `index.html` pointing at it.

### Framework glue

The served stores are real nanostores stores, so your framework's official adapter consumes them directly — no glue code in your repo:

```js
import { useStore } from "@nanostores/vue";   // or /react, /preact, /solid, /lit…
import { $entities } from "/_panel/store.v1.js";

const entities = useStore($entities);          // reactive in your framework
```

Adapters: [@nanostores/vue](https://github.com/nanostores/vue), [@nanostores/react](https://github.com/nanostores/react), and the rest of the [nanostores integrations](https://github.com/nanostores/nanostores#integration). No framework at all: `$entities.subscribe(render)` is the whole API.

### TypeScript

The declarations ship in `ui-starter.zip`, live in this repo as [`store.v1.d.ts`](../store.v1.d.ts) (republished per release), and are served by any WiFi-up panel (`curl -O http://<panel-host>:8080/_panel/store.v1.d.ts`). Map the specifier to the file:

```jsonc
// tsconfig.json
{ "compilerOptions": { "paths": { "/_panel/store.v1.js": ["./store.v1.d.ts"] } } }
```

### Shipping

Tar the build output **at its root** (`tar -czf my-ui.tar.gz -C dist .`) and attach it to a GitHub release. In Home Assistant: the panel's device page → Configure → **Panel UI source** → `owner/repo` (plus a read-only token for a private repo — it's pushed to the panel and never stored in HA). Saving installs immediately; the **Update UI** button re-fetches the latest release any time; emptying the source removes the downloaded UI and the panel falls back to its health screen. A release with several `.tar.gz` assets just means picking yours from a dropdown. Want publishing a release to press that button for you? See [auto-update](auto-update.md).

### Debugging like the kiosk

The panel's own browser has no devtools, but your desktop's do: `ssh -L 8080:127.0.0.1:8080 -L 8765:127.0.0.1:8765 <user>@<panel-host>`, then open `http://localhost:8080` — the exact page the kiosk runs, console and network tabs included. Your app's uncaught errors and `console.error` also land in the panel's journald (`panel-logs --scope ui`), and — if your app ever freezes the panel into quarantine — on the failure screen itself.
