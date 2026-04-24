/**
 * WebSocket message shapes.
 *
 * The bridge forwards every JSON line from the C6 verbatim, so these
 * shapes mirror what the firmware emits in `panel_app.c`.
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

export interface RosterEntry {
  entity_id: string;
  friendly_name: string | null;
  area: string | null;
}

export interface RosterMessage {
  type: "roster";
  entities: RosterEntry[];
}

export interface EntityStateMessage {
  type: "entity_state";
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

export interface HaAvailabilityMessage {
  type: "ha_availability";
  value: "online" | "offline";
}

export type IncomingMessage =
  | SensorMessage
  | RosterMessage
  | EntityStateMessage
  | HaAvailabilityMessage;

// ---- Outgoing (UI → bridge → C6 → MQTT) ----

/**
 * Generic service-call command. The HA integration only dispatches for
 * entity_ids in its manifest; unknown entity_ids are logged and dropped.
 */
export interface CallServiceCommand {
  type: "call_service";
  entity_id: string;
  action: string; // "light.turn_on", "switch.toggle", etc.
  data: Record<string, unknown>;
}

export type OutgoingCommand = CallServiceCommand;

// ---- Derived state shapes used by the store ----

export interface EntityState {
  state: string;
  attributes: Record<string, unknown>;
}
