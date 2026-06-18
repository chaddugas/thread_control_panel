# Store API — /_panel/store.v1.js

Type declarations for the served panel store (`/_panel/store.v1.js`).

TypeScript refuses ambient declarations for rooted specifiers, so this is
a plain declaration module: drop it anywhere in the project and map the
import specifier to it in tsconfig.json —

  "compilerOptions": {
    "paths": { "/_panel/store.v1.js": ["./store.v1.d.ts"] }
  }

No package install. Panels also serve the copy matching their running
platform at `/_panel/store.v1.d.ts`, one curl away.

## Store shape

### PanelStore

The readable face of a nanostores store. `subscribe` fires immediately
with the current value and on every change; `listen` skips the immediate
call. Every change emits a fresh object identity. Both return an
unsubscribe function.

Everything below the first three members is nanostores' store lifecycle
surface — present on the runtime objects (they are real nanostores
stores) and declared so the official @nanostores/* framework adapters
type-check against these exports. Apps use get/subscribe/listen and
leave the rest alone.

#### Type Parameters

##### T

`T`

#### Methods

##### get()

> **get**(): `T`

###### Returns

`T`

##### listen()

> **listen**(`listener`): () => `void`

###### Parameters

###### listener

(`value`, `oldValue`) => `void`

###### Returns

() => `void`

##### notify()

> **notify**(`oldValue?`): `void`

###### Parameters

###### oldValue?

`T`

###### Returns

`void`

##### off()

> **off**(): `void`

###### Returns

`void`

##### subscribe()

> **subscribe**(`listener`): () => `void`

###### Parameters

###### listener

(`value`, `oldValue?`) => `void`

###### Returns

() => `void`

#### Properties

##### init

> `readonly` **init**: `T` \| `undefined`

##### lc

> `readonly` **lc**: `number`

##### value

> `readonly` **value**: `T` \| `undefined`

## Lifecycle & raw I/O

### ConnectOptions

#### Properties

##### url?

> `optional` **url?**: `string`

Bridge WS URL; defaults to `ws://${location.hostname}:8765`.

***

### STORE\_API

> `const` **STORE\_API**: `"v1"`

Contract version of this surface — matches the served filename.

***

### bridgeUrl()

> **bridgeUrl**(): `string`

The URL the store is (re)connecting to; empty before connect().

#### Returns

`string`

***

### connect()

> **connect**(`options?`): `void`

Open the bridge connection. Auto-reconnects every 1 s until
disconnect(). Idempotent for the same URL; last-URL-wins for a
different one.

#### Parameters

##### options?

[`ConnectOptions`](#connectoptions)

#### Returns

`void`

***

### disconnect()

> **disconnect**(): `void`

#### Returns

`void`

***

### send()

> **send**(`envelope`): `boolean`

Send one envelope to the bridge. Returns false (envelope dropped)
while the WS is down — no queueing, by contract.

#### Parameters

##### envelope

[`OutgoingCommand`](#outgoingcommand) \| `Record`\<`string`, `unknown`\>

#### Returns

`boolean`

***

### uiLog()

> **uiLog**(`message`, `scope?`): `boolean`

A diagnostic line into the panel's journald via the bridge.

#### Parameters

##### message

`string`

##### scope?

`string`

#### Returns

`boolean`

## Commands

### callService()

> **callService**(`entityId`, `action`, `data?`): `boolean`

HA service call against a rostered entity. HA rejects unrostered
entity_ids; the bridge drops calls while HA is offline — gate on
`$connection.ha` instead of firing blind.

#### Parameters

##### entityId

`string`

##### action

`string`

##### data?

`Record`\<`string`, `unknown`\>

#### Returns

`boolean`

***

### panelCommand()

> **panelCommand**(`name`, `value?`): `boolean`

Panel command (e.g. `reboot_pi`). Structured args ride under `value`.

#### Parameters

##### name

`string`

##### value?

`unknown`

#### Returns

`boolean`

***

### setPanel()

> **setPanel**(`name`, `value`): `boolean`

Panel-field write (e.g. `wifi_enabled`), dispatched to a bridge control.

#### Parameters

##### name

`string`

##### value

`unknown`

#### Returns

`boolean`

## State families

### ConnectionState

#### Properties

##### bridge

> **bridge**: `boolean`

The store's WebSocket to the bridge is open.

##### c6HeartbeatAt

> **c6HeartbeatAt**: `number` \| `null`

Arrival stamp of the most recent C6 heartbeat; null until first seen.

##### ha

> **ha**: `"online"` \| `"offline"` \| `null`

HA availability as seen through the panel; null until first seen.

##### lastError

> **lastError**: `string` \| `null`

Last WebSocket-level error, cleared on successful (re)connect.

***

### EntityState

#### Properties

##### attributes

> **attributes**: `Record`\<`string`, `unknown`\>

##### state

> **state**: `string`

***

### PanelInfoState

#### Properties

##### c6Version

> **c6Version**: `string` \| `null`

Running C6 firmware version, verbatim (carries the `v` prefix).

##### lanHost

> **lanHost**: `string` \| `null`

The panel's mDNS name (`<hostname>.local`); null until seen.

##### name

> **name**: `string` \| `null`

Optional HA-side label (raw, no serial tail); null when unset → consumers
fall back to "Thread Panel". Cosmetic only — never an identity.

##### serial

> **serial**: `string` \| `null`

Board serial — the panel's only identity; null until seen.

***

### RosterEntry

#### Properties

##### area

> **area**: `string` \| `null`

##### entity\_id

> **entity\_id**: `string`

##### friendly\_name

> **friendly\_name**: `string` \| `null`

***

### SensorReading

#### Indexable

> \[`extra`: `string`\]: `unknown`

Sensor-specific extras (e.g. proximity `strength`, ambient `raw`/`mv`).

#### Properties

##### receivedAt

> **receivedAt**: `number`

Arrival stamp (epoch ms).

##### value

> **value**: `number`

***

### $c6LinkFresh

> `const` **$c6LinkFresh**: [`PanelStore`](#panelstore)\<`boolean`\>

A C6 heartbeat arrived within the last 30 s. Subscribe, don't poll.

***

### $capabilities

> `const` **$capabilities**: [`PanelStore`](#panelstore)\<`Record`\<`string`, `unknown`\> \| `null`\>

The panel's capabilities document; schema owned by the hw-config contract.

***

### $connection

> `const` **$connection**: [`PanelStore`](#panelstore)\<[`ConnectionState`](#connectionstate)\>

***

### $entities

> `const` **$entities**: [`PanelStore`](#panelstore)\<`Record`\<`string`, [`EntityState`](#entitystate)\>\>

Latest full snapshot per forwarded HA entity — never diffs.

***

### $now

> `const` **$now**: [`PanelStore`](#panelstore)\<`number`\>

Shared 1 s epoch-ms tick; runs only while subscribed — never poll it.

***

### $panelInfo

> `const` **$panelInfo**: [`PanelStore`](#panelstore)\<[`PanelInfoState`](#panelinfostate)\>

***

### $panelState

> `const` **$panelState**: [`PanelStore`](#panelstore)\<`Record`\<`string`, `unknown`\>\>

Panel-itself fields (`wifi_state`, `backlight`, `version`, …).

***

### $roster

> `const` **$roster**: [`PanelStore`](#panelstore)\<[`RosterEntry`](#rosterentry)[]\>

Which entities this panel receives (the service-call allowlist).

***

### $sensors

> `const` **$sensors**: [`PanelStore`](#panelstore)\<`Record`\<`string`, [`SensorReading`](#sensorreading)\>\>

Latest reading per declared sensor — names are open-ended by design.

***

### $tunes

> `const` **$tunes**: [`PanelStore`](#panelstore)\<`Record`\<`string`, `number`\>\>

HA-owned runtime tunables; absent names mean "not pushed yet".

## Wire shapes

### CallServiceCommand

#### Properties

##### action

> **action**: `string`

##### data

> **data**: `Record`\<`string`, `unknown`\>

##### entity\_id

> **entity\_id**: `string`

##### type

> **type**: `"call_service"`

***

### PanelCmdCommand

#### Properties

##### name

> **name**: `string`

##### type

> **type**: `"panel_cmd"`

##### value?

> `optional` **value?**: `unknown`

***

### PanelSetCommand

#### Properties

##### name

> **name**: `string`

##### type

> **type**: `"panel_set"`

##### value

> **value**: `unknown`

***

### UiLogCommand

#### Properties

##### message

> **message**: `string`

##### scope

> **scope**: `string`

##### type

> **type**: `"ui_log"`

***

### OutgoingCommand

> **OutgoingCommand** = [`CallServiceCommand`](#callservicecommand) \| [`PanelSetCommand`](#panelsetcommand) \| [`PanelCmdCommand`](#panelcmdcommand) \| [`UiLogCommand`](#uilogcommand) \| `UiHeartbeatCommand`
