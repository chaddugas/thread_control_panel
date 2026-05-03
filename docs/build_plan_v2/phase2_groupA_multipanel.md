[Build Plan V2](README.md) › [Phase 2 — Polish & cleanup](phase2_polish.md) › Group A — Multi-panel readiness

# Phase 2 Group A — Multi-panel readiness (design)

> **Companion to [phase2_polish.md](phase2_polish.md) Group A.** The original v2-doc bullet was just "collapse the panel_app.c shim into platform driven by config." Discussion in May 2026 expanded scope to a hardware abstraction layer that also covers Pi model, display type, sensor presence/type, MCU target, and per-panel HA entity gating. This doc is the design.

## Why this exists

Today the project ships a single panel (`feeding_control`) and most "what hardware is on the panel" lives as hardcoded values across `panel_app.c`, `install-pi.sh`, and pin defines. Adding a second panel currently means forking the firmware, hand-editing the install script, and hoping nothing drifts. The user has two more panels in the near pipeline:

- **Panel 2**: Pi 5 + 7" official RPi touchscreen + TF-Nova lidar + TEMT6000 ambient
- **Panel 3**: Pi 3B+/4 + 5" Waveshare DSI or 4" Pimoroni HyperPixel + maybe TF-Luna + maybe TEMT6000

The variation surface is real but smaller than feared. All three panels share: same C6 family, same kiosk pipeline (sway+cog rendering whatever framebuffer the kernel provides), same Benewake UART lidar protocol (TF-Mini Plus / TF-Luna / TF-Nova all use the 9-byte `0x59 0x59` frame format), same TEMT6000 (or absent), same `thread_panel` HA integration. Variation collapses to: a few hardware-identity strings, sensor-presence flags, a boot-config template, and a per-panel UI bundle.

Group A's job: turn that variation into config, not code.

## End-state architecture

```
panels/<id>/
├── panel.toml              # all per-panel config: hardware + build + capabilities
├── ui/                     # Vue app, unchanged
├── firmware/main/
│   ├── app_main.c          # unchanged (3-line entrypoint)
│   ├── CMakeLists.txt      # unchanged
│   ├── Kconfig.projbuild   # unchanged (MQTT_BROKER_URI, MQTT_CLIENT_ID)
│   └── panel_app.c         # shrinks to product-specific dispatch only (or empty)
└── README.md
```

`panels/<id>/firmware/main/panel_config.h` and `sdkconfig.defaults` get **codegen'd from `panel.toml`** at build time. `panel_app.c`'s panel-itself dispatch (cmd/reboot, cmd/wifi_*, cmd/update, set/* wildcard, panel_set_creds, ha_availability) moves into `platform/firmware/components/panel_platform/`. Sensor presence becomes `#ifdef PANEL_HAS_LIDAR` / `#ifdef PANEL_HAS_AMBIENT`. The lidar driver is parameterized for Benewake-family compatibility.

On the Pi: `/opt/panel/panel_id` written at install-time from a prompt; install-lib.sh's `lib_download_artifacts` consumes it to fetch only `<panel_id>-firmware-*.bin` + `<panel_id>-ui-*.tar.gz`. The deploy tarball ships `panel.toml` so the bridge can read hardware metadata at runtime.

On HA: bridge publishes a `state/_capabilities` retained topic (routed through C6 over UART per the established no-WiFi-on-Pi pattern); integration subscribes and gates entity creation by capability. Integration release train splits off — cut-release sha-compares the integration zip vs the previous release and only bumps the integration's manifest.json version when content actually changed, so HACS stops prompting for updates on every panel/firmware/UI release.

The `panels/<id>/ha/manifest.yaml` reference template is **deleted entirely** — the user clarified it's a stale unused file. The HA integration is generic; the YAML manifest is user input pasted into HA's config flow at panel onboarding, and there's no panel-specific HA-side source code.

---

## A.1 — Integration release train split + per-Pi panel identity

**Smallest blast radius, highest immediate value.** Solves the "every UI on every Pi" question and the "HA prompts to update the integration on every cut" annoyance. Doesn't touch firmware. Ships before A.2 starts.

### A.1.a — Integration release train split

**Goal**: HACS prompts for an integration update only when the integration content actually changed, not on every cut-release.

**Mechanism**:

1. cut-release builds `thread_panel.zip` as today.
2. After build, fetch the previous release's `manifest.json` from `gh release view <prev_tag>`. Compare integration sha256 (already computed in our manifest).
3. **If unchanged**: revert the version bump cut-release made to [`platform/integration/thread_panel/manifest.json`](../../platform/integration/thread_panel/manifest.json) so the integration's `version` field stays at whatever it was last time the integration actually changed. Still ship the zip in the release (artifact set stays uniform), but with the unchanged version internally.
4. **If changed**: keep the bump — same as today.
5. The off-main HACS-layout commit still happens unconditionally — the tag tree always contains `custom_components/thread_panel/`. Only the `version` field inside it is conditional.

HACS reads the integration's `version` field from `manifest.json` to decide whether to prompt. Stable version = no prompt.

**Trade-off**: integration version becomes "stuck at the last release tag where the integration content moved" — slightly odd cosmetically (integration says v2.0.0-beta.30 while latest release is v2.0.0-beta.40), but that's the desired semantic and accurate.

PanelUpdateEntity (the firmware/UI/bridge prompt) keeps working off the release tag — that side is unchanged. Only the HACS prompt splits off.

**Files touched**: `tools/cut-release` only. ~30 lines of new bash for the sha-compare + revert logic.

**Validation**: cut a beta with no integration changes → confirm `manifest.json` still says the prior version → confirm HACS doesn't prompt. Then make a trivial integration change (whitespace) → cut → confirm version bumps and HACS prompts.

### A.1.b — Per-Pi panel identity + selective artifact download

**Goal**: each Pi knows which panel it is, downloads only its panel's artifacts.

**Mechanism**:

1. **`/opt/panel/panel_id`** — a single-line file containing the panel id (e.g. `feeding_control`). Owned by install user, mode 0644 (not secret).
2. **install-pi.sh** prompts for `panel_id` if the file doesn't exist, defaulting to `feeding_control` for back-compat with the existing single-panel install. Validates against the manifest's `panels` keys (rejects unknown ids).
3. **install-lib.sh's `lib_download_artifacts`**: reads `/opt/panel/panel_id`, derives the artifact filenames (`<panel_id>-firmware-<v>.bin`, `<panel_id>-ui-<v>.tar.gz`), downloads only those. Shared artifacts (panel-bridge, panel-deploy, integration zip) are unchanged.
4. **`lib_extract_artifacts`** extracts the per-panel UI to `/opt/panel/versions/<v>/ui-dist/` and the firmware to `/opt/panel/versions/<v>/firmware.bin` — same paths as today, no service config changes needed.

**Files touched**:
- `platform/deploy/install-pi.sh` — add panel_id prompt + write to /opt/panel/panel_id
- `platform/deploy/install-lib.sh` — read panel_id, parameterize artifact URL derivation in `lib_download_artifacts` and `lib_extract_artifacts`
- `platform/deploy/panel-update.sh` — sources install-lib.sh, transparently inherits the panel-aware behavior

The release manifest is already per-panel-keyed (`{"panels": {"feeding_control": {"firmware": {...}, "ui": {...}}}}`), so the script changes are surgical lookups against existing structure.

**Validation**: production Pi runs install-pi.sh from the new beta → prompted for panel_id (defaults to `feeding_control`) → /opt/panel/panel_id exists → install completes pulling only feeding_control artifacts → diff total bytes downloaded vs. previous beta to confirm shared bits are unchanged and per-panel bits are panel-only.

### A.1 commits estimate

3 commits, one beta:

1. cut-release: sha-compare integration vs previous release, conditional version bump.
2. install-pi.sh + install-lib.sh: panel_id prompt + selective artifact download.
3. README/docs updates if needed.

---

## A.2 — panel.toml + codegen + firmware platform/product split + capability discovery + MCU target

**The biggest sub-phase by far.** Hardware abstraction lives here. Will likely span 5–7 betas with hardware verification at each step.

### A.2.a — `panel.toml` schema

Single source of truth for per-panel config. Lives at `panels/<id>/panel.toml`. TOML over YAML for simpler parsing (no Python dep at firmware build time — see codegen below) and stricter type semantics.

```toml
schema_version = 1                    # forward-compat insurance

[panel]
id = "feeding_control"
name = "Pet Feeder Panel"

[firmware.mcu]
target = "esp32c6"                    # or "esp32h2"
board = "xiao_c6"                     # informational; future board-profiles layer

[firmware.pins]
pi_link_uart = 1
pi_link_rx = 7                        # GPIO numbers, not XIAO D-numbering
pi_link_tx = 6

[firmware.sensors.lidar]
present = true
driver = "benewake_uart"              # only option today; covers TF-Mini Plus / TF-Luna / TF-Nova UART
model_name = "tfmini_plus"            # for HA reporting (device info field)
uart = 0
rx_pin = 21
tx_pin = 22                           # wired but unused; lidar UART is RX-only for us
default_publish_hz = 1                # per-panel default; HA tunable overrides at runtime (A.2.g)

[firmware.sensors.ambient]
present = true
adc_unit = 1
adc_channel = 0                       # ADC1 CH0 = D0 on XIAO C6
default_publish_period_s = 5          # per-panel default; HA tunable overrides at runtime (A.2.g)
default_mv_ceiling = 500              # per-panel default (TEMT6000 calibration); HA tunable overrides at runtime (A.2.g)

[bridge.controls]
brightness = false                    # not implemented yet; A.2 leaves this gated off
screen = true
wifi = true
reboot = true                         # always true today; declared for symmetry

[hardware.pi]
model = "zero2w"                      # informational; A.3 may use it for kiosk-renderer defaults

[hardware.display]
type = "hdmi"                         # or "dsi", "dpi"
driver = "waveshare_625"              # informational; A.3 uses it for config.txt templating
resolution = "720x1280"               # native
rotation = 270                        # to landscape
touch = "usb_hid"                     # or "i2c", "none"
```

**Schema rules**:
- Hard-fail on unknown top-level keys, unknown subsection keys, or missing required fields. No silent defaults.
- `schema_version` reserved for future forward-compat; version 1 is current.
- Validation runs at codegen time (firmware build) AND at bridge startup (with an early-exit log message + service-restart loop on failure).

### A.2.b — Codegen tool

`tools/codegen-panel-config.py` — single-file Python script. No external deps beyond stdlib (uses `tomllib` from Python 3.11+).

**Inputs**: `panels/<id>/panel.toml`
**Outputs**:
- `panels/<id>/firmware/main/panel_config.h` — `#define`s for everything panel_app.c + panel_platform need
- `panels/<id>/firmware/sdkconfig.defaults` — appends/updates `CONFIG_IDF_TARGET="esp32c6"` (or h2) and any per-MCU sdkconfig overrides

**Hand-rolled validation**:
- Required fields present
- Unknown fields rejected
- Type checks (int/string/bool)
- Enum constraints (`target ∈ {esp32c6, esp32h2}`, `lidar.driver ∈ {benewake_uart}`, `display.type ∈ {hdmi, dsi, dpi}`, etc.)
- Cross-field consistency (`sensors.lidar.present == true` requires `uart`, `rx_pin` defined)

**Build integration**:
- CMake `add_custom_command` in `panels/<id>/firmware/main/CMakeLists.txt` runs codegen whenever `panel.toml` changes, regenerating `panel_config.h` before compile. So `idf.py build` Just Works after editing `panel.toml`; no separate manual codegen step.
- cut-release also runs codegen explicitly in its per-panel firmware-build phase, mostly defensively (CMake should already have done it, but cut-release shouldn't depend on local CMake state being clean).
- Local-dev: edit `panel.toml`, `idf.py build`, done. Same loop as today, just more knobs.

**Failure mode**: codegen exits non-zero with a clear message. CMake fails the build. The error surface is right where the developer is looking.

### A.2.c — Firmware platform/product split

Today `panels/feeding_control/firmware/main/panel_app.c` is 762 lines (post-Group-B-cleanup). Most of it is panel-itself plumbing that's identical for any panel: cmd/reboot dispatch, cmd/wifi_* forwarding, cmd/update forwarding, set/* wildcard, panel_set_creds handler, ha_availability gate, sensor publish loop, forward_to_pi_uart helper.

**Move into `platform/firmware/components/panel_platform/`**:
- The whole `panel_app_on_data` dispatch table (everything except product-specific commands)
- Sensor publish task (already references panel_lidar/panel_ambient which are platform)
- panel_set_creds parsing + ack
- forward_to_pi_uart helper
- ha_availability handler + sensor republish-on-online
- The MQTT subscribe list for all panel-itself topics

**Keep in `panels/<id>/firmware/main/panel_app.c`** (likely 50–100 lines):
- Empty by default if the panel has no product-specific MQTT topics
- A small `product_dispatch(topic, data)` callback registered with platform if the panel has product-specific commands
- `panels/feeding_control/` for example: has no product-specific MQTT subscribes today (the integration handles forwarded entities through `cmd/call_service`, which is already platform), so its `panel_app.c` could collapse to near-empty.

**Sensor optional via #ifdef**:
- `panel_platform/panel_sensors.c` and `panel_lidar.c` get `#ifdef PANEL_HAS_AMBIENT` / `#ifdef PANEL_HAS_LIDAR` guards around their init + read functions.
- Calling code (sensor publish task) is also `#ifdef`-guarded so a panel without lidar doesn't run the lidar publish branch.
- Build-time selection: zero runtime overhead, no driver bytes shipped you don't use.

**Lidar driver parameterization**:
- Rename `panel_platform/panel_lidar.c` → `panel_platform/panel_lidar_benewake_uart.c` (reflects it's a driver, not a generic interface).
- Add `panel_platform/include/panel_lidar.h` as a thin interface header (init, read_distance_cm, read_strength, pause, resume — same shape as today, just exposed as an interface). Driver file implements it.
- Future second driver (e.g. TF-Luna I2C if/when) drops in as `panel_lidar_benewake_i2c.c`; build picks one based on `panel.toml`'s `lidar.driver`.

For Group A's scope: only `benewake_uart` exists. The interface exists for forward-compat without being exercised yet.

### A.2.d — MCU target switching

panel.toml's `firmware.mcu.target` drives `idf.py set-target $TARGET` per panel.

**cut-release per-panel build phase** (already loops over `panels/*`):
- Before each `idf.py build`, run `idf.py set-target $(toml_get firmware.mcu.target)`. This is a no-op if already set, full reconfigure if changing.
- Each panel has its own build directory anyway (`panels/<id>/firmware/build/`), so target state doesn't bleed across panels.

**Local-dev**:
- Same pattern: edit `panel.toml`, run `idf.py set-target ...` once, then `idf.py build` as normal. CMake hook re-runs codegen as needed.
- `tools/codegen-panel-config.py` could optionally invoke `set-target` itself if invoked outside CMake context, but that's nice-to-have.

**H2 caveats** (known unknown until you actually have an H2 in the loop):
- Different ADC layout — TEMT6000 wiring may need different `adc_unit`/`adc_channel` in panel.toml.
- Fewer GPIOs — pin assignments more constrained.
- No WiFi (which we don't use anyway, but some sdkconfig defaults differ).
- OpenThread sdkconfig is mostly the same (both C6 and H2 are OT-capable).
- Mechanical part is `set-target esp32h2`; capability differences surface only at build/runtime.

### A.2.e — Capability discovery

**Wire format**: bridge sends `{"type":"panel_state","name":"_capabilities","value":{...}}` over UART at startup. C6 publishes to `thread_panel/<panel_id>/state/_capabilities` retained.

**Routing**: same as every bridge-originated state today. Bridge → UART → C6 → MQTT. The no-WiFi-on-Pi-in-production constraint stays load-bearing.

**Payload schema**:

```json
{
  "schema_version": 1,
  "sensors": {
    "lidar": true,
    "ambient": true
  },
  "controls": {
    "screen": true,
    "brightness": false,
    "wifi": true,
    "reboot": true
  },
  "hardware": {
    "pi_model": "zero2w",
    "mcu_target": "esp32c6",
    "lidar_model": "tfmini_plus",
    "display": {
      "type": "hdmi",
      "driver": "waveshare_625",
      "resolution": "720x1280",
      "rotation": 270
    }
  },
  "versions": {
    "bridge": "v2.0.0-beta.40"
  }
}
```

**Bridge implementation**:
- New module `panel_bridge/capabilities.py`. Reads `/opt/panel/panel.toml` (extracted from the deploy tarball at install time). Builds the JSON. Sends on bridge startup via UART.
- Re-sends on file change (mtime watch) the same way `mqtt_creds.py` does — supports panel.toml edits without manual restart.
- Includes its own bridge package version (`importlib.metadata.version("panel-bridge")`) in the `versions` block so HA device-info has a bridge version separate from C6 firmware version.

**Integration consumption**:
- New module `platform/integration/thread_panel/capabilities.py`. Subscribes to `state/_capabilities` (per-panel) on config-entry setup.
- Caches last-seen capabilities in HA's `Store` keyed by panel_id, so cold-start (HA reboot before bridge has republished) uses cached values and reconciles on first live message.
- Entity creation in each platform (`button.py`, `select.py`, `sensor.py`, `switch.py`, `text.py`) consults capabilities and skips creation for absent items. E.g. `PanelLidarSensor` only created if `sensors.lidar == true`.
- Hardware metadata feeds HA's device registry (`model = display.driver`, `sw_version = versions.firmware`, `hw_version = mcu_target`, etc.) — no new entities, just better diagnostics.

**Race handling**: on first install or fresh config-entry setup with no cache, integration creates entities optimistically based on a "all true" default + logs a warning, then reconciles on first `_capabilities` message (entity removal is a normal HA operation). For cold-start with cache, the cache wins until live data arrives — same pattern as the integration's manifest stale-cleanup.

### A.2.f — `panels/<id>/ha/manifest.yaml` removal

Per the user's clarification, `panels/feeding_control/ha/manifest.yaml` is a stale reference template that's not actually loaded by the integration — the YAML manifest is pasted directly into HA's config flow. Delete the file as part of this group. `panels/<id>/ha/` directory may stay empty as a "hatch for future product-specific HA-side Python" or get removed entirely (lean: remove).

### A.2.g — Tunable values surface as HA entities, not panel.toml

**Principle**: `panel.toml` declares hardware capabilities + presence (build-time fact). It does NOT carry tuning values — anything that might want adjustment on a deployed panel after the fact lives as an HA `number` (or `select`) entity gated by the corresponding capability. Changing a tunable from HA = 10 seconds on a phone. Changing a value in panel.toml = a release cut + OTA.

**The split:**

- **panel.toml (build-time hardware fact):** sensor presence/driver/pins, MCU target, display type/driver/rotation, control capability flags. Things that wouldn't change without disassembling the panel.
- **HA entities (runtime tuning):** publish cadences, calibration ceilings, behavioral thresholds (presence/theme thresholds, dim thresholds, etc.).

**Initial tunable set** — created as HA `number` entities under each panel's device, gated by the corresponding capability (per A.2.f's capability-driven entity creation):

| Tunable | Capability gate | Default | Range | What it does |
|---|---|---|---|---|
| `lidar_publish_hz` | `sensors.lidar` | 1 Hz | 0.1–10 | Cadence at which C6 publishes proximity |
| `ambient_publish_period_s` | `sensors.ambient` | 5 s | 1–60 | Cadence at which C6 publishes ambient brightness |
| `ambient_mv_ceiling` | `sensors.ambient` | 500 mV | 100–3000 | Calibration: mV that maps to 100% brightness (TEMT6000-specific; tune to your room) |

Behavioral-threshold tunables (presence threshold, theme dim/wake thresholds) are Phase 3+ HA UX work and follow the same pattern — see [phase3_themed.md → HA integration UX features](phase3_themed.md#ha-integration-ux-features).

**Mechanism**:
- New MQTT topic family: `thread_panel/<id>/cmd/tune/<param>`, payload `{"value": <number>}`, **retained** so HA's value survives broker restart and replays to the bridge on reconnect.
- Integration publishes on entity-value change.
- Bridge subscribes via existing UART-bridged `cmd/*` machinery; on receipt updates its in-memory state and (for cadence/calibration values the C6 controls) forwards to C6 via new UART envelope `{"type":"panel_set_tunable","name":"...","value":...}`.
- C6 picks up new value next tick; no restart needed.

**Three-tier value resolution at boot** (lowest to highest priority):

1. **Firmware compile-time fallback**: every tunable has a `#define DEFAULT_<NAME>` baked into the firmware (e.g. `#define DEFAULT_LIDAR_PUBLISH_HZ 1`). Last-resort value if panel.toml is somehow malformed or missing the field. Baked at build time from the table-default column above.
2. **panel.toml `default_*` (per-panel)**: optional fields in `[firmware.sensors.*]` (`default_publish_hz`, `default_publish_period_s`, `default_mv_ceiling`) capture the per-panel starting point in version control. Codegen'd into the same `#define` slots, overriding the firmware fallback for that specific panel build. Useful when a panel is deployed in non-default conditions (a bright sunroom needs `default_mv_ceiling = 1200` to prevent constant 100% saturation; a low-light closet needs 200) and you want sensible behavior even before HA tuning is configured. Still build-time — changing requires a rebuild + OTA — but the value lives with the panel definition rather than scattered as `#define` overrides.
3. **HA retained `cmd/tune/*` (runtime override)**: published by HA when the user changes the corresponding `number` entity. Broker replays on bridge reconnect, so the override survives panel reboots, broker restarts, and HA restarts. This is the one you actually use to retune day-to-day; the panel.toml defaults exist as a "good starting point if HA has never tuned" and the firmware fallback exists as "the panel still works if the toml is broken."

When HA is offline / has never tuned, the panel.toml default (or firmware fallback) stays in effect. When HA reconnects with a previously-published tune, the override applies within seconds. No fallback churn.

### A.2 commits estimate

5–7 commits, 3–5 betas (each commit potentially shippable; pace dictated by hardware-verification cycles):

1. **panel.toml schema + codegen tool** (no firmware behavior change yet — codegen produces panel_config.h that matches the existing hand-edited one byte-for-byte).
2. **CMake hook + cut-release codegen call** + sdkconfig.defaults regen (still no behavior change; just driving config via the new mechanism).
3. **Sensor optional via `#ifdef`** + lidar driver rename + interface header (panels still all have both sensors true, so no behavior change; just refactor).
4. **Move panel-itself dispatch into platform** (the big one; panel_app.c shrinks). Likely the highest-risk single commit; needs careful before/after testing on production.
5. **Bridge capability publishing**.
6. **Integration capability consumption + entity gating** (entities are unconditionally created today; this commit makes them conditional. Validate that with capabilities all-true, the entity set is identical to today.)
7. **Tunables: `cmd/tune/*` topic family + `panel_set_tunable` UART envelope + initial three HA `number` entities (lidar_publish_hz, ambient_publish_period_s, ambient_mv_ceiling).** Per A.2.g.
8. **MCU target switching in cut-release** + delete `panels/feeding_control/ha/manifest.yaml`. Validate H2 build works (even if no H2 hardware to test against yet).

Each commit shippable independently. Hardware verification at boundaries (especially after #4 and #6).

---

## A.3 — Pi-side hardware-variant install templating

**Smallest of the three**, mostly shell scripting against the established panel.toml format.

### A.3.a — `install-pi.sh` consumes panel.toml

`install-pi.sh` reads `panel.toml` from the deploy tarball at install time (or `/opt/panel/panel.toml` post-install) and templates the right hardware-variant config based on `hardware.display.type` + `hardware.display.driver`.

**Per-display-type config.txt snippets**:

- **HDMI** (current Waveshare 6.25"):
  ```
  hdmi_force_hotplug=1
  hdmi_cvt=720 1280 60 6 0 0 0
  hdmi_group=2
  hdmi_mode=87
  ```

- **DSI** (official RPi 7", Waveshare 5"):
  ```
  dtoverlay=vc4-kms-v3d            # likely already present on bookworm
  display_lcd_rotate=<rotation>    # if needed
  dtparam=i2c_arm=on               # for capacitive touch
  ```

- **DPI** (HyperPixel 4 / 4 inch):
  ```
  dtoverlay=hyperpixel4
  display_lcd_rotate=<rotation>
  ```

These get appended to `/boot/firmware/config.txt` if not already present (idempotent — same pattern as the existing `fbcon=rotate:3` append for console rotation).

**Console framebuffer rotation** (`fbcon=rotate:N` in `/boot/firmware/cmdline.txt`) derives from `hardware.display.rotation` per panel.

**Sway output transform** — for the kiosk renderer to rotate the rendered output to match the physical orientation. Today's `output * transform 270` in `sway-kiosk.config` becomes `output * transform $(rotation_to_sway_transform $rotation)` templated at install time.

**Touch input mapping**:
- USB HID: auto-discovered by libinput, no config needed.
- I2C touch: typically auto-discovered once the dtoverlay is loaded; if rotation needs a transform matrix, sway handles it via the output transform.
- HyperPixel: usually auto via `dtoverlay=hyperpixel4`.

### A.3.b — Validation

The trick: A.3 changes the install path on a panel that already has working hardware. Running A.3's install-pi.sh on the production feeding_control panel must produce IDENTICAL config.txt + cmdline.txt + sway config as today (because feeding_control's panel.toml describes its current hardware, and the templating should derive the current values). Acceptance test = diff before/after on the production panel = empty.

For panel 2/3, the validation path is: cut a release with their panel.toml entries, run install-pi.sh on the new hardware, see if the display comes up. Iterate on the templating until it does.

### A.3 commits estimate

2–3 commits, 1–2 betas:

1. install-pi.sh templating from panel.toml — display type/driver/rotation + console rotation.
2. Sway config templating.
3. (If needed) per-display dtoverlay logic for DSI + DPI variants.

A.3 doesn't ship until panel 2 or 3 is actually being deployed — the templating is dead weight without a non-feeding-control panel to use it on. Could land just-in-time.

---

## Open questions

- **Where does the bridge read panel.toml from?** Two options: (a) extracted to `/opt/panel/panel.toml` at install time and read directly; (b) cut-release pre-renders panel.toml to a JSON sidecar in the deploy tarball, bridge reads JSON. Lean: (a) — panel.toml is already valid TOML, Python's `tomllib` is stdlib in 3.11+, no preprocessing needed. The C6 codegen path uses panel.toml directly too, so single-file source of truth holds.
- **Where exactly does panel.toml live in the deploy tarball?** Probably `deploy/panel.toml` so install-pi.sh can find it predictably. install-pi.sh extracts to `/opt/panel/panel.toml` for runtime reads.
- **panel.toml validation strictness for unknown keys**: hard-error or warn? Lean: hard-error in codegen (build fails; user fixes immediately) but warn-and-skip in bridge runtime (degraded but not broken if a future field is missing handling).
- **Default panel.toml for back-compat**: should existing feeding_control installs without a panel.toml on disk get a synthesized default? Lean: no — install-pi.sh always extracts the deploy tarball's panel.toml, so the file is always present post-install. Only edge case: a Pi running pre-A.2 install reading the bridge's startup-capabilities flow before its first OTA. Handle that as: bridge logs an error and skips capability publishing (degraded but bridge stays up); next OTA fixes it.
- **HyperPixel touch matrix calibration**: HyperPixel's I2C touch may need a per-rotation transform that sway can't auto-derive. Defer the question until a HyperPixel panel is actually in the loop.
- **Codegen tool location**: `tools/codegen-panel-config.py` (called from CMake + cut-release) or `platform/firmware/codegen.py` (lives near what it generates)? Lean: `tools/` since it's a build-time tool not a runtime artifact, matches `tools/cut-release` placement.

## Risks & mitigations

- **Big firmware refactor in A.2.c (move dispatch to platform)** — single commit could break the production panel. Mitigation: keep the existing `panel_app.c` shim alongside the new platform-driven path under a build-time flag; verify both produce identical MQTT behavior; flip the flag in a separate commit; remove the shim in a third commit. Three small commits beat one big risky one.
- **Codegen as a build dependency** — local-dev friction if it breaks (every `idf.py build` fails). Mitigation: hard-fail with a clear message naming the offending field/value, and a one-line "fix: edit `panels/<id>/panel.toml` and re-run". Codegen is single-file Python with stdlib-only deps so the dependency surface itself is minimal.
- **Capability discovery race breaks existing entities** — if integration doesn't see the message before HA frontend renders, entities flicker or disappear. Mitigation: cache last-seen capabilities in HA Store, fall back to "all true" on fresh install with no cache (same observable behavior as today). Race window is ~seconds at HA startup; integration doesn't tear down existing entities until reconciled.
- **panel_id mismatch between Pi and panel.toml** — if user types `feeding_controll` (typo) at install prompt, lib_download_artifacts 404s on the typo'd filename. Mitigation: install-pi.sh fetches the manifest first, validates `panel_id` against the manifest's `panels` keys, re-prompts on mismatch.
- **H2 hardware that doesn't yet exist** — A.2 will add H2 as a target option without ever building+running it. Mitigation: validate the build path (`idf.py set-target esp32h2 && idf.py build` against feeding_control's panel.toml hypothetically configured for H2 pins) at cut-release time, but defer runtime validation until the user actually has an H2 in hand. Document the "H2 caveats" surface in panel.toml comments.

## Success criteria (Group A overall)

1. ✅ A new panel ships by adding `panels/<new_id>/{panel.toml, ui/, README.md}` and a couple of HA-side config-entry steps. Zero firmware fork. Zero install-script fork. Zero integration code changes.
2. ✅ The production feeding_control panel's behavior is unchanged through A.1, A.2, and A.3 (regression test: every existing MQTT topic, every HA entity, every OTA path identical to today).
3. ✅ HACS prompts for an integration update only when `platform/integration/thread_panel/` content actually changed across releases.
4. ✅ `state/_capabilities` retained on every panel, queryable via `mosquitto_sub`.
5. ✅ HA device registry shows accurate model + hardware variant strings per panel (different model strings for different display types, lidar models, etc.).
6. ✅ `idf.py set-target esp32h2 && idf.py build` succeeds against a hypothetical H2 panel.toml (build-only validation; runtime deferred to actual hardware).
7. ✅ Disabling lidar in panel.toml (`sensors.lidar.present = false`) produces a firmware bin that doesn't include lidar driver code (`strings firmware.bin | grep -i 'tf-mini'` returns nothing).
8. ✅ HACS-as-custom-repo install path still works after the integration release-train split (the off-main HACS-layout commit happens unconditionally; only `manifest.json`'s `version` field is conditional).
