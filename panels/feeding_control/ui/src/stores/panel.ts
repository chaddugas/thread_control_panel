/**
 * Panel store — single source of truth for what the UI knows about the
 * panel. Wraps the bridge WebSocket: connects on app mount, replays
 * cached state on connect, broadcasts updates as Pinia state, exposes
 * action helpers for outgoing commands.
 *
 * Most of this file is platform-shaped (WS lifecycle, reconnect, sensor
 * state). When a second panel exists, the WS plumbing + sensor state
 * should promote to `platform/ui-core/`. The product-specific bits are
 * the action helpers (feed, skip, toggle_feeder).
 */

import { defineStore } from "pinia";
import { ref } from "vue";
import type {
  IncomingMessage,
  OutgoingCommand,
  SensorAmbientMessage,
  SensorProximityMessage,
} from "@/types";

interface ProximityState extends SensorProximityMessage {
  receivedAt: number;
}
interface AmbientState extends SensorAmbientMessage {
  receivedAt: number;
}

const RECONNECT_DELAY_MS = 1000;

const wsUrl =
  import.meta.env.VITE_WS_URL ?? `ws://${location.hostname}:8765`;

export const usePanelStore = defineStore("panel", () => {
  // ---- reactive state ----
  const connected = ref(false);
  const lastError = ref<string | null>(null);
  const proximity = ref<ProximityState | null>(null);
  const ambient = ref<AmbientState | null>(null);

  // ---- non-reactive WS plumbing ----
  let ws: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let manualDisconnect = false;

  function connect(): void {
    if (ws !== null) return;
    manualDisconnect = false;

    try {
      ws = new WebSocket(wsUrl);
    } catch (e) {
      lastError.value = `WebSocket construct failed: ${(e as Error).message}`;
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      connected.value = true;
      lastError.value = null;
    };

    ws.onmessage = (ev) => {
      let msg: IncomingMessage;
      try {
        msg = JSON.parse(ev.data) as IncomingMessage;
      } catch {
        console.warn("non-JSON from bridge:", ev.data);
        return;
      }
      handleMessage(msg);
    };

    ws.onerror = () => {
      // Browsers don't surface useful detail in onerror — close handler
      // gives us the actionable signal.
      lastError.value = "WebSocket error (see console)";
    };

    ws.onclose = () => {
      connected.value = false;
      ws = null;
      if (!manualDisconnect) scheduleReconnect();
    };
  }

  function disconnect(): void {
    manualDisconnect = true;
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    ws?.close();
    ws = null;
    connected.value = false;
  }

  function scheduleReconnect(): void {
    if (reconnectTimer !== null) return;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECONNECT_DELAY_MS);
  }

  function handleMessage(msg: IncomingMessage): void {
    if (msg.type === "sensor") {
      const now = Date.now();
      if (msg.name === "proximity") {
        proximity.value = { ...msg, receivedAt: now };
      } else if (msg.name === "ambient") {
        ambient.value = { ...msg, receivedAt: now };
      }
    }
    // Unknown types are silently ignored at this layer — log if useful.
  }

  function send(cmd: OutgoingCommand | Record<string, unknown>): boolean {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(cmd));
    return true;
  }

  // ---- product-specific action helpers ----

  function feed(quantity: number): boolean {
    return send({ type: "feed", quantity });
  }

  function skip(feedingId: string): boolean {
    return send({ type: "skip", feeding_id: feedingId });
  }

  function toggleFeeder(): boolean {
    return send({ type: "toggle_feeder" });
  }

  return {
    // state
    connected,
    lastError,
    proximity,
    ambient,
    // lifecycle
    connect,
    disconnect,
    // I/O
    send,
    // actions
    feed,
    skip,
    toggleFeeder,
    // diagnostic
    wsUrl,
  };
});
