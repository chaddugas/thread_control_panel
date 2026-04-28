/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_WS_URL?: string;

  /** Ambient brightness (0..100) at-or-above which the UI flips to light theme. */
  readonly VITE_THEME_LIGHT_AT?: string;
  /** Ambient brightness (0..100) at-or-below which the UI flips back to dark theme. */
  readonly VITE_THEME_DARK_AT?: string;

  /** Proximity (cm) at-or-below which the panel is "engaged" and the splash dismisses. */
  readonly VITE_PRESENCE_NEAR_CM?: string;
  /** Proximity (cm) at-or-above which the panel is "idle" and the splash shows. */
  readonly VITE_PRESENCE_FAR_CM?: string;
  /** Milliseconds the proximity reading must remain "far" before the splash takes over. */
  readonly VITE_PRESENCE_FAR_DEBOUNCE_MS?: string;
  /** Milliseconds after a tap during which presence is forced "engaged" regardless of sensor. */
  readonly VITE_PRESENCE_TAP_HOLD_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
