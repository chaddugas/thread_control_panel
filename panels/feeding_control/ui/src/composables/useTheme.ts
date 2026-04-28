import { onMounted, onUnmounted, ref, watch } from "vue";
import { usePanelStore } from "@thread-panel/ui-core";

export type Theme = "dark" | "light";

function envNumber(raw: string | undefined, fallback: number): number {
  if (raw === undefined) return fallback;
  const n = Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

const LIGHT_AT = envNumber(import.meta.env.VITE_THEME_LIGHT_AT, 55);
const DARK_AT = envNumber(import.meta.env.VITE_THEME_DARK_AT, 40);

/**
 * Choose theme from the ambient-brightness reading with hysteresis:
 * stay in `current` while the reading sits in the dead zone between
 * DARK_AT and LIGHT_AT — only flip once it crosses the far threshold.
 */
function chooseTheme(value: number, current: Theme): Theme {
  if (value >= LIGHT_AT) return "light";
  if (value <= DARK_AT) return "dark";
  return current;
}

export function useTheme() {
  const panel = usePanelStore();
  const theme = ref<Theme>("dark");

  function apply(t: Theme): void {
    theme.value = t;
    document.documentElement.dataset.theme = t;
  }

  let stop: (() => void) | null = null;

  onMounted(() => {
    apply(theme.value);
    stop = watch(
      () => panel.ambient?.value ?? null,
      (v) => {
        if (v === null) return;
        const next = chooseTheme(v, theme.value);
        if (next !== theme.value) apply(next);
      },
      { immediate: true },
    );
  });

  onUnmounted(() => {
    stop?.();
    stop = null;
  });

  return { theme };
}
