import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
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

type DocWithVT = Document & {
  startViewTransition?: (
    cb: () => void | Promise<void>,
  ) => { finished: Promise<void> };
};

function startSplashTransition(commit: () => void | Promise<void>): void {
  const start = (document as DocWithVT).startViewTransition;
  if (typeof start !== "function") {
    void commit();
    return;
  }
  document.documentElement.classList.add("vt-splash");
  const t = start.call(document, async () => {
    await commit();
    await nextTick();
  });
  t.finished.finally(() => {
    document.documentElement.classList.remove("vt-splash");
  });
}

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

  function setEngaged(next: boolean): void {
    if (engaged.value === next) return;
    startSplashTransition(() => {
      engaged.value = next;
      document.documentElement.classList.toggle("splash-on", !next);
    });
  }

  function recordTap(): void {
    lastTapAt.value = Date.now();
    setEngaged(true);
    clearFarTimer();
  }

  onMounted(() => {
    stopWatch = watch(
      () => panel.proximity?.value ?? null,
      (cm) => {
        if (cm === null || cm === 0) return;
        if (cm <= NEAR_CM) {
          clearFarTimer();
          setEngaged(true);
          return;
        }
        if (cm >= FAR_CM) {
          if (farTimer !== null || !engaged.value) return;
          farTimer = window.setTimeout(() => {
            farTimer = null;
            if (!tapHoldActive()) setEngaged(false);
          }, FAR_DEBOUNCE_MS);
          return;
        }
        clearFarTimer();
      },
      { immediate: true },
    );

    tapTick = window.setInterval(() => {
      if (!tapHoldActive() && (panel.proximity?.value ?? 0) >= FAR_CM) {
        setEngaged(false);
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
