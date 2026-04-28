import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { usePanelStore } from "@thread-panel/ui-core";

function envNumber(raw: string | undefined, fallback: number): number {
  if (raw === undefined) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

const NEAR_CM = envNumber(import.meta.env.VITE_PRESENCE_NEAR_CM, 110);
const FAR_CM = envNumber(import.meta.env.VITE_PRESENCE_FAR_CM, 140);
const FAR_DEBOUNCE_MS = envNumber(
  import.meta.env.VITE_PRESENCE_FAR_DEBOUNCE_MS,
  4000,
);
const TAP_HOLD_MS = envNumber(
  import.meta.env.VITE_PRESENCE_TAP_HOLD_MS,
  20_000,
);

/**
 * "Is someone interacting with the panel right now?" derived from the
 * TF-Mini distance reading.
 *
 * - Near (≤ NEAR_CM): engaged immediately, splash dismisses.
 * - Far  (≥ FAR_CM):  treated as engaged for FAR_DEBOUNCE_MS, then idle.
 * - Dead zone in between: stay in current state.
 * - No sensor data yet: treat as engaged so the panel boots into the full UI.
 * - Recent tap: forces engaged for TAP_HOLD_MS regardless of sensor.
 */
export function usePresence() {
  const panel = usePanelStore();
  const engaged = ref(true);
  const lastTapAt = ref(0);

  let farTimer: number | null = null;
  let tapTick: number | null = null;
  let stopWatch: (() => void) | null = null;

  function clearFarTimer(): void {
    if (farTimer !== null) {
      window.clearTimeout(farTimer);
      farTimer = null;
    }
  }

  function tapHoldActive(): boolean {
    return Date.now() - lastTapAt.value < TAP_HOLD_MS;
  }

  function recordTap(): void {
    lastTapAt.value = Date.now();
    engaged.value = true;
    clearFarTimer();
  }

  onMounted(() => {
    stopWatch = watch(
      () => panel.proximity?.value ?? null,
      (cm) => {
        if (cm === null || cm === 0) {
          // Sensor offline or invalid reading — keep current state.
          return;
        }
        if (cm <= NEAR_CM) {
          clearFarTimer();
          engaged.value = true;
          return;
        }
        if (cm >= FAR_CM) {
          if (farTimer !== null || !engaged.value) return;
          farTimer = window.setTimeout(() => {
            farTimer = null;
            if (!tapHoldActive()) engaged.value = false;
          }, FAR_DEBOUNCE_MS);
          return;
        }
        // Dead zone — cancel any pending far transition, hold current state.
        clearFarTimer();
      },
      { immediate: true },
    );

    // Re-check tap-hold expiry once a second so we drift into the splash
    // after the timeout if the sensor remains "far" the whole time.
    tapTick = window.setInterval(() => {
      if (!tapHoldActive() && (panel.proximity?.value ?? 0) >= FAR_CM) {
        engaged.value = false;
      }
    }, 1_000);

    window.addEventListener("pointerdown", recordTap, { capture: true });
  });

  onUnmounted(() => {
    stopWatch?.();
    stopWatch = null;
    clearFarTimer();
    if (tapTick !== null) {
      window.clearInterval(tapTick);
      tapTick = null;
    }
    window.removeEventListener("pointerdown", recordTap, { capture: true });
  });

  const showSplash = computed(() => !engaged.value);

  return { engaged, showSplash, recordTap };
}
