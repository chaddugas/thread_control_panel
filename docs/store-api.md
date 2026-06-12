# Contract — store API

> **Mirrored copy.** The authoritative version of this document lives with the platform source (private); this copy is republished for UI authors at each platform release. Internal cross-references may point into the source repo.

The public surface of the served panel store: the state families, command helpers, and lifecycle a panel UI — any framework, any repo — programs against. The store module is the blessed client of [envelope-schema](envelope-schema.md)'s bridge↔UI pipe; that contract stays the wire-level ground truth, while this one is the surface UI authors actually touch. The root README carries the how-to (consumption recipes, dev workflow); this document is the authoritative *what*.

## Participants

- **Provider:** the panel. [`platform/panel-store`](../platform/panel-store.md) builds the module; the platform installs it; [`panel-ui-server.py`](../../../platform/deploy/panel-ui-server.py) serves it at the reserved, versioned path **`/_panel/store.v1.js`** (types beside it at `/_panel/store.v1.d.ts`), with CORS open for cross-origin dev imports ([deploy](../platform/deploy.md)).
- **Consumers:** any UI rendered on (or developed against) the panel. The exported stores are real nanostores stores and the declared `PanelStore` interface satisfies nanostores' `ReadableAtom`, so the **official `@nanostores/*` framework adapters are first-class consumers** (runtime + types verified against `@nanostores/vue`); bare `subscribe()` works framework-free; the platform shell uses [`ui-core`](../platform/ui-core.md)'s own glue.

## Definition

### URL surface

| Path | Content |
|---|---|
| `/_panel/store.v1.js` | the store module — self-contained ESM, no imports |
| `/_panel/store.v1.d.ts` | TypeScript declarations for the module specifier |

Production UIs import same-origin (`import { … } from "/_panel/store.v1.js"`); dev imports cross-origin from a WiFi-up panel or resolves the specifier through a bundler proxy/alias. The module's version always matches the running platform because both install from the same release.

### Lifecycle & raw I/O

| Export | Behavior |
|---|---|
| `connect(options?: {url?})` | opens the bridge WS (default `ws://${location.hostname}:8765`); auto-reconnects every 1 s; idempotent for the same URL, **last-URL-wins** for a different one |
| `disconnect()` | closes and stops reconnecting |
| `send(envelope)` | one raw envelope to the bridge; returns `false` (envelope dropped) while the WS is down — no queueing, matching the pipe's no-replay model |
| `bridgeUrl()` | the URL the store is (re)connecting to |
| `uiLog(message, scope?)` | a diagnostic line into the panel's journald via the bridge |
| `STORE_API` | `"v1"` — the contract version of this surface |

### Command helpers

| Export | Sends | Notes |
|---|---|---|
| `callService(entityId, action, data?)` | `call_service` | rejected by HA unless the entity is rostered; dropped bridge-side while HA is offline — gate UI on `$connection.ha` instead of firing blind |
| `setPanel(name, value)` | `panel_set` | panel-field write, dispatched to a bridge control |
| `panelCommand(name, value?)` | `panel_cmd` | e.g. `reboot_pi`; structured args ride under `value` |

### Public state families

Every family is a nanostores store: `get()` reads, `subscribe(fn)` reads + tracks (fires immediately), and every change emits a fresh object identity. Consumption details: the [nanostores docs](https://github.com/nanostores/nanostores).

| Store | Shape | Carries |
|---|---|---|
| `$connection` | `{bridge, ha, c6HeartbeatAt, lastError}` | WS-to-bridge state · HA availability (`"online"`/`"offline"`/`null`) · last C6 heartbeat stamp · last WS error |
| `$entities` | `Record<entity_id, {state, attributes}>` | latest full snapshot per forwarded HA entity — never diffs |
| `$roster` | `[{entity_id, friendly_name, area}]` | which entities this panel receives |
| `$panelState` | `Record<name, value>` | panel-itself fields (`wifi_state`, `backlight`, `version`, …) |
| `$capabilities` | `object \| null` | the panel's capabilities document ([hw-config](hw-config.md) owns the schema) |
| `$sensors` | `Record<name, {value, receivedAt, …extras}>` | latest reading per declared sensor, arrival-stamped |
| `$tunes` | `Record<name, number>` | HA-owned runtime tunables; absent names mean "not pushed yet — use your own default" |
| `$panelInfo` | `{serial, c6Version, lanHost}` | identity: board serial (the panel's only identity), running C6 firmware, the panel's mDNS name |
| `$now` | `number` | shared 1 s epoch-ms tick; runs only while subscribed |
| `$c6LinkFresh` | `boolean` | heartbeat seen within 30 s |

**The generic entity model is the point:** entity ids, sensor names, panel-state names, and the capabilities document are open-ended — a panel with newly declared hardware ([hardware-flexibility](../../tracks/hardware-flexibility.md)) flows through this surface without revision. A UI hardcodes *its* ids, never enumerates the platform's.

### Platform-internal families

`$provisioning`, `$updateStatus`/`$otaActive`, and `$uiStatus` ship in the module but are **not** part of this contract: the platform shell owns the pairing and OTA screens, and product UIs never reimplement them. Their shapes may change without a `v2`.

## Invariants & traps

- **`v1` is the surface version, not SemVer.** Additions (new families, new optional fields) ride the platform's `panel` version under the same filename; a breaking change to anything above ships `store.v2.js` beside v1, never under it.
- **No client-side queueing anywhere.** Every send while disconnected is dropped (returns `false`) by design — every recovery path on the pipe re-converges on current state, so a replayed stale command would be wrong, not helpful.
- **Subscribe, don't poll.** `$now`-derived stores (`$c6LinkFresh`) only re-evaluate while subscribed; a `.get()` poll sees stale values.
- **Null means "not seen yet", not "off".** `$connection.ha`, `$panelInfo.serial`/`lanHost`, and absent `$tunes` names are unknowns until the snapshot lands; render the unknown state, don't default to failure.
- **The roster is the service-call allowlist.** `callService` against an unrostered entity is silently useless — HA rejects it.
- **The store never throws on unknown envelopes** — forward-compatible by contract; a newer platform talking to an older UI degrades to "new data invisible", never to a crash.
- **`PanelStore` mirrors nanostores' `ReadableAtom` member-for-member** (including the lifecycle surface: `value`, `init`, `lc`, `notify`, `off`) — narrowing it breaks type-checking for every official adapter consumer. Apps still touch only `get`/`subscribe`/`listen`.

## Examples

```js
// Same-origin (production) or cross-origin (dev) — identical surface.
import { connect, callService, $entities, $connection } from "/_panel/store.v1.js";

connect(); // kiosk default; dev: connect({ url: "ws://<panel>.local:8765" })

const unsubscribe = $entities.subscribe((all) => {
  render(all["switch.pet_feeder"]?.state ?? "unknown");
});

if ($connection.get().ha === "online") {
  callService("switch.pet_feeder", "switch.toggle");
}
```

Characteristic mistake — polling a subscriber-gated store:

```js
setInterval(() => status($c6LinkFresh.get()), 1000); // stale: nothing mounted $now
$c6LinkFresh.subscribe(status);                      // correct
```

