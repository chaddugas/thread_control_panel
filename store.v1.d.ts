// Spec: docs/specs/contracts/store-api.md
/**
 * Type declarations for the served panel store (`/_panel/store.v1.js`).
 *
 * TypeScript refuses ambient declarations for rooted specifiers, so this is
 * a plain declaration module: drop it anywhere in the project and map the
 * import specifier to it in tsconfig.json —
 *
 *   "compilerOptions": {
 *     "paths": { "/_panel/store.v1.js": ["./store.v1.d.ts"] }
 *   }
 *
 * No package install. Panels also serve the copy matching their running
 * platform at `/_panel/store.v1.d.ts`, one curl away.
 *
 * Hand-maintained against `src/` deliberately: the public surface is the
 * contract (docs/specs/contracts/store-api.md), so a surface change updates
 * this file and the contract doc in the same change set.
 */

/**
 * The readable face of a nanostores store. `subscribe` fires immediately
 * with the current value and on every change; `listen` skips the immediate
 * call. Every change emits a fresh object identity. Both return an
 * unsubscribe function.
 *
 * Everything below the first three members is nanostores' store lifecycle
 * surface — present on the runtime objects (they are real nanostores
 * stores) and declared so the official @nanostores/* framework adapters
 * type-check against these exports. Apps use get/subscribe/listen and
 * leave the rest alone.
 */
export interface PanelStore<T> {
  get(): T;
  subscribe(listener: (value: T, oldValue?: T) => void): () => void;
  listen(listener: (value: T, oldValue: T) => void): () => void;
  readonly value: T | undefined;
  readonly init: T | undefined;
  readonly lc: number;
  notify(oldValue?: T): void;
  off(): void;
}

// ---- lifecycle & raw I/O ----

export interface ConnectOptions {
  /** Bridge WS URL; defaults to `ws://${location.hostname}:8765`. */
  url?: string;
}

/**
 * Open the bridge connection. Auto-reconnects every 1 s until
 * disconnect(). Idempotent for the same URL; last-URL-wins for a
 * different one.
 */
export function connect(options?: ConnectOptions): void;
export function disconnect(): void;

/**
 * Send one envelope to the bridge. Returns false (envelope dropped)
 * while the WS is down — no queueing, by contract.
 */
export function send(
  envelope: OutgoingCommand | Record<string, unknown>,
): boolean;

/** The URL the store is (re)connecting to; empty before connect(). */
export function bridgeUrl(): string;

/** A diagnostic line into the panel's journald via the bridge. */
export function uiLog(message: string, scope?: string): boolean;

/** Contract version of this surface — matches the served filename. */
export const STORE_API: "v1";

// ---- commands ----

/**
 * HA service call against a rostered entity. HA rejects unrostered
 * entity_ids; the bridge drops calls while HA is offline — gate on
 * `$connection.ha` instead of firing blind.
 */
export function callService(
  entityId: string,
  action: string,
  data?: Record<string, unknown>,
): boolean;

/** Panel-field write (e.g. `wifi_enabled`), dispatched to a bridge control. */
export function setPanel(name: string, value: unknown): boolean;

/** Panel command (e.g. `reboot_pi`). Structured args ride under `value`. */
export function panelCommand(name: string, value?: unknown): boolean;

// ---- public state families ----

export interface ConnectionState {
  /** The store's WebSocket to the bridge is open. */
  bridge: boolean;
  /** HA availability as seen through the panel; null until first seen. */
  ha: "online" | "offline" | null;
  /** Arrival stamp of the most recent C6 heartbeat; null until first seen. */
  c6HeartbeatAt: number | null;
  /** Last WebSocket-level error, cleared on successful (re)connect. */
  lastError: string | null;
}
export const $connection: PanelStore<ConnectionState>;

export interface EntityState {
  state: string;
  attributes: Record<string, unknown>;
}
/** Latest full snapshot per forwarded HA entity — never diffs. */
export const $entities: PanelStore<Record<string, EntityState>>;

export interface RosterEntry {
  entity_id: string;
  friendly_name: string | null;
  area: string | null;
}
/** Which entities this panel receives (the service-call allowlist). */
export const $roster: PanelStore<RosterEntry[]>;

/** Panel-itself fields (`wifi_state`, `backlight`, `version`, …). */
export const $panelState: PanelStore<Record<string, unknown>>;

/** The panel's capabilities document; schema owned by the hw-config contract. */
export const $capabilities: PanelStore<Record<string, unknown> | null>;

export interface SensorReading {
  value: number;
  /** Arrival stamp (epoch ms). */
  receivedAt: number;
  /** Sensor-specific extras (e.g. proximity `strength`, ambient `raw`/`mv`). */
  [extra: string]: unknown;
}
/** Latest reading per declared sensor — names are open-ended by design. */
export const $sensors: PanelStore<Record<string, SensorReading>>;

/** HA-owned runtime tunables; absent names mean "not pushed yet". */
export const $tunes: PanelStore<Record<string, number>>;

export interface PanelInfoState {
  /** Board serial — the panel's only identity; null until seen. */
  serial: string | null;
  /** Running C6 firmware version, verbatim (carries the `v` prefix). */
  c6Version: string | null;
  /** The panel's mDNS name (`<hostname>.local`); null until seen. */
  lanHost: string | null;
}
export const $panelInfo: PanelStore<PanelInfoState>;

/** Shared 1 s epoch-ms tick; runs only while subscribed — never poll it. */
export const $now: PanelStore<number>;

/** A C6 heartbeat arrived within the last 30 s. Subscribe, don't poll. */
export const $c6LinkFresh: PanelStore<boolean>;

// ---- platform-internal families ----
// Shipped for the platform shell (pairing + OTA screens). NOT part of the
// public contract: shapes may change without a store.v2.

export interface ProvisioningState {
  phase: "unprovisioned" | "awaiting_seal" | "provisioned" | null;
  sas: string | null;
}
export const $provisioning: PanelStore<ProvisioningState>;

export interface UpdateState {
  phase: string | null;
  detail: string | null;
  progress: number | null;
}
export const $updateStatus: PanelStore<UpdateState>;
export const $otaActive: PanelStore<boolean>;

export interface UiQuarantineError {
  ts: number;
  scope: string;
  message: string;
}
export interface UiStatusState {
  /** null until the bridge's first ui_status arrives (unknown ≠ absent). */
  installed: boolean | null;
  source: "downloaded" | "release" | null;
  /** Changes on every install/OTA/remove — the shell's reload signal. */
  stamp: string | null;
  /** Watchdog quarantine — the shell never imports while true. */
  quarantined: boolean;
  /** Cog restarts issued before quarantine tripped. */
  failures: number | null;
  /** Quarantine start, epoch seconds. */
  since: number | null;
  /** Recent ui_log lines, frozen at quarantine time. */
  errors: UiQuarantineError[];
}
export const $uiStatus: PanelStore<UiStatusState>;

// ---- outbound wire shapes (for the raw `send` escape hatch) ----

export interface CallServiceCommand {
  type: "call_service";
  entity_id: string;
  action: string;
  data: Record<string, unknown>;
}
export interface PanelSetCommand {
  type: "panel_set";
  name: string;
  value: unknown;
}
export interface PanelCmdCommand {
  type: "panel_cmd";
  name: string;
  value?: unknown;
}
export interface UiLogCommand {
  type: "ui_log";
  message: string;
  scope: string;
}
/** Shell liveness beat for the bridge's UI watchdog — platform shell only. */
export interface UiHeartbeatCommand {
  type: "ui_heartbeat";
}
export type OutgoingCommand =
  | CallServiceCommand
  | PanelSetCommand
  | PanelCmdCommand
  | UiLogCommand
  | UiHeartbeatCommand;
