/**
 * WebSocket message shapes.
 *
 * The bridge forwards every JSON line from the C6 verbatim, so these
 * shapes mirror what the firmware emits in `panel_app.c`.
 *
 * Likely candidates for promotion to a shared `platform/ui-core/types.ts`
 * once panel #2 forces the abstraction.
 */

// ---- Incoming (bridge → UI) ----

export interface SensorProximityMessage {
  type: "sensor";
  name: "proximity";
  value: number; // cm
  strength: number; // signal strength
}

export interface SensorAmbientMessage {
  type: "sensor";
  name: "ambient";
  value: number; // 0..100 normalized
  raw: number; // raw ADC count
  mv: number; // millivolts
}

export type SensorMessage = SensorProximityMessage | SensorAmbientMessage;

/** Catch-all for messages we don't yet have a typed handler for. */
export interface UnknownMessage {
  type: string;
  [key: string]: unknown;
}

export type IncomingMessage = SensorMessage | UnknownMessage;

// ---- Outgoing (UI → bridge → C6 → MQTT) ----

export interface FeedCommand {
  type: "feed";
  quantity: number;
}

export interface SkipCommand {
  type: "skip";
  feeding_id: string;
}

export interface ToggleFeederCommand {
  type: "toggle_feeder";
}

export type OutgoingCommand =
  | FeedCommand
  | SkipCommand
  | ToggleFeederCommand;
