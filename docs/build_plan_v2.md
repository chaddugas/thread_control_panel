# Thread Control Panel — Build Plan V2

> **Status: V2 active.** Step 17 (Phases 1, 2, 3a, 3b) and Step 17b shipped — production runs v2.0.0-beta.28 with WiFi state surface, persistent journals, and HA-orchestrated remote updates. **Phase 1 — Security** is up next. See [build_plan_v1.md](build_plan_v1.md) for the V1 historical record + production-state reference.

## Table of contents

- [Status](#status)
- [Keeping this current](#keeping-this-current)
- [Goals](#goals)
- [Non-goals](#non-goals)
- [Architecture (V2 end-state)](#architecture-v2-end-state)
- [Phase 1 — Security](#phase-1--security)
- [Phase 2 — Polish & cleanup](#phase-2--polish--cleanup)
- [Phase 3+ — Themed groups](#phase-3--themed-groups)
- [Future / new panel ideas](#future--new-panel-ideas)
- [Completed work (historical reference)](#completed-work-historical-reference)
- [Reference](#reference)
- [Lessons Learned](#lessons-learned)
- [Proven Facts](#proven-facts)
- [Technical Debt](#technical-debt)

## Status

V2 development is active. Shipped through v2.0.0-beta.28:

- **Step 17 Phase 1**: artifact-based releases + repo restructure ✅
- **Step 17 Phase 2**: C6 UART OTA receiver + panel-flash CLI ✅
- **Step 17 Phase 3a**: Pi-side update orchestration ✅
- **Step 17 Phase 3b**: HA-side `update.PanelUpdateEntity` ✅
- **Step 17b**: WiFi state surface + observability ✅

**In flight**: [Phase 1 Group A — Move MQTT credentials out of firmware](#group-a-move-mqtt-credentials-out-of-firmware). Five commits on main covering the C6 NVS-credential path, bridge file-watcher + delivery, install-pi.sh prompt, Kconfig cleanup, and a periodic re-send (so the first Phase-1 OTA succeeds without manual recovery). Beta.29 cut + production OTA validation are the next steps.

**After Group A ships**: [Group B](#group-b-rotate-credentials--scrub-historical-leakage) (rotate the leaked password, scrub historical `firmware.bin` assets), then Groups C and D in Phase 1, followed by [Phase 2 — Polish & cleanup](#phase-2--polish--cleanup) and the themed groups beyond.

## Keeping this current

Same convention as V1. After completing a step or making a non-trivial decision:

- Strike through the finished step (`~~**Step name**~~`) and append `✅ DONE`.
- Move the `(next up)` marker.
- Record meaningful learnings in **Lessons Learned**, validated invariants in **Proven Facts**, and known-but-deferred problems in **Technical Debt**.
- Refresh **Status** when a major capability lands or changes.
- Edit/remove anything the work has invalidated rather than leaving stale guidance behind.

When V2 ships and the V2 patterns become "current production state," migrate the still-authoritative bits (MQTT topic additions, UART protocol additions, etc.) into a consolidated reference (likely a successor `build_plan_v3.md`) so v1 + v2 don't drift into mutual contradiction.

## Goals

V2 has shipped its core reshape — artifact-based releases, HA-orchestrated remote updates, and the WiFi state surface that closed Step 17b. Goals still in flight:

1. **Security hardening** — move MQTT credentials out of the firmware binary, rotate the leaked password, scrub historical artifacts, tighten the authorization surface, sign OTA payloads. Detailed in [Phase 1](#phase-1--security).
2. **Code quality + multi-panel readiness** — reorganize `panels/<id>/` for clean drop-in of new panels, sweep dead code, DRY where natural, comment hygiene, foundational tests. Detailed in [Phase 2](#phase-2--polish--cleanup).
3. **Iterative improvements** — themed groups beyond Phase 2 (small fixes, robustness, HA UX, hardware affordances, etc.). Detailed in [Phase 3+](#phase-3--themed-groups).

## Non-goals

- **HACS publication to the default community store.** The project depends on custom-assembled hardware that almost no one else can use; HACS distribution adds packaging burden without real audience. Stays as private install (manual zip, or HACS as a custom repository).
- **Auto-install on a schedule** (cron-style "install at 3am Sunday"). Manual-trigger only — HA notices the new version and surfaces it in the entity, the user clicks Install when ready.
- **CI-based builds.** `cut-release` runs on the Mac (where dev work happens anyway). Moving to GitHub Actions is a V3 question.

## Architecture (V2 end-state)

```
GitHub Release v2.0.0
├── feeding_control-firmware-2.0.0.bin
├── feeding_control-ui-2.0.0.tar.gz
├── panel-bridge-2.0.0.tar.gz
├── thread_panel.zip                # integration, for HACS-as-custom-repo or manual install (static filename, no version suffix — HACS doesn't substitute placeholders)
├── panel-update.sh                  # orchestration script (versioned with releases)
└── manifest.json                    # versions + sha256 + sizes per component

Pi (offline by default):
/opt/panel/
├── current → versions/v2.0.0/      # symlink, atomic swap on update
├── versions/
│   ├── v1.4.0/                     # previous, retained for rollback
│   └── v2.0.0/
│       ├── bridge/                  # python sources
│       ├── ui-dist/                 # built Vue bundle
│       ├── firmware.bin             # C6 firmware
│       ├── panel-update.sh
│       └── manifest.json
└── installed.json                   # what's currently running per-component (versions + sha256)

systemd units reference /opt/panel/current/* — symlink swap + restart = new version live.
No git on the Pi. No source files on the Pi.

HA box:
custom_components/thread_panel/      # extracted from release zip (manual or HACS-as-custom-repo)
```

---

## Phase 1 — Security

The MQTT broker password is published in every `firmware.bin` release artifact and trivially extractable with `strings`. Phase 1 closes that hole, rotates the leaked credential, and tightens the surrounding authorization surface so a future leak has less reach.

Confirmed scope (no deferred items — every group is committed Phase 1 work).

### Group A: Move MQTT credentials out of firmware

**Status (2026-05-01)**: All 5 commits on main. Beta.29 release cut + first-OTA validation are the remaining steps.

Today the C6 firmware has `CONFIG_MQTT_USERNAME` and `CONFIG_MQTT_PASSWORD` baked in via sdkconfig. Every published `firmware.bin` carries them. `strings firmware.bin | grep -i myvxan` returns the password instantly.

- C6 firmware: reads MQTT creds from NVS at startup (namespace `panel_mqtt`, keys `user` / `pass`). "Provisioning required" state when NVS is empty — firmware sits idle (Thread up, no MQTT client) until it receives provisioning over UART.
- New UART envelope `panel_set_creds` (Pi → C6) carrying `{username, password}`. C6 writes to NVS only on change (no-op when identical), then (re)starts its MQTT client. C6 sends `panel_set_creds_ack` back over UART for bridge-side debug visibility.
- Bridge: reads `/opt/panel/mqtt_creds.json` (mode 0600, owned by install user) at startup; sends via the new UART envelope. Re-sends on file mtime change AND every 60s as a safety net so a freshly-booted C6 (post-OTA-flash, post-power-cycle, post-reboot) gets provisioned without manual intervention.
- `install-pi.sh`: prompts for MQTT username + password, writes to `/opt/panel/mqtt_creds.json` atomically (mktemp + 0600 + mv). Validation: username 1–64 chars; password 12–128 chars + at least 2 of {letter, digit, symbol}; neither field may contain `"` or `\` (the C6's substring-based JSON parser doesn't handle escapes); ASCII-printable only.
- Kconfig: `MQTT_USERNAME` and `MQTT_PASSWORD` config options removed entirely. `MQTT_BROKER_URI` and `MQTT_CLIENT_ID` stay (public, no secrets).
- Acceptance: `strings firmware.bin | grep -i myvxan` returns nothing for the next firmware build.

**Commits on main**:

| SHA | Subject |
|---|---|
| `da4d2dd` | panel_net + panel_app: NVS-backed MQTT credentials + panel_set_creds UART |
| `f0d6293` | panel_bridge: NVS-credential delivery via mqtt_creds.json + panel_set_creds UART |
| `6581c88` | install-pi.sh + Kconfig: collect MQTT creds at install time, drop CONFIG_MQTT_USERNAME / PASSWORD |
| (next) | panel_bridge.mqtt_creds: periodic re-send so OTA C6-flash provisioning works without manual recovery |

**Validation plan** — when beta.29 is cut:

1. **Local build (Mac)**:
   ```bash
   cd panels/feeding_control/firmware && idf
   idf.py reconfigure                                          # purge orphaned CONFIG_MQTT_USERNAME/PASSWORD
   grep -E '^CONFIG_MQTT_(USERNAME|PASSWORD)' sdkconfig        # must return nothing
   idf.py build
   strings build/feeding_control.bin | grep -i myvxan          # must return nothing — security acceptance
   ```
2. **Pre-OTA migration on production Pi** (SSH in):
   ```bash
   sudo tee /opt/panel/mqtt_creds.json >/dev/null <<'EOF'
   {"username": "mqtt_user", "password": "<current-password>"}
   EOF
   sudo chown $USER /opt/panel/mqtt_creds.json
   sudo chmod 0600 /opt/panel/mqtt_creds.json
   ```
3. **Cut beta.29** from Mac with a release-notes block describing this migration step for anyone else following along.
4. **HACS** update Thread Panel integration → restart HA.
5. **Trigger OTA** from HA's update entity. Should succeed end-to-end thanks to the periodic re-send (within 60s of the C6 booting new firmware, the bridge re-sends `panel_set_creds`, C6 writes NVS + commits the partition + connects MQTT, `verifying_c6` sees `state/version`).
6. **Power-cycle test**: unplug + replug the panel. On cold boot, C6 reads NVS → has creds → connects MQTT immediately. Confirms NVS persistence across reboots.
7. **(Optional) In-place rotation smoke test**: `sudo touch /opt/panel/mqtt_creds.json` → bridge file-watcher fires within 5s → C6 receives `panel_set_creds` → no-ops on identical creds. Confirms the rotation path is wired up for Group B.

### Group B: Rotate credentials + scrub historical leakage

- Generate a new MQTT username + password.
- Update broker config + the production panel's `mqtt_creds.json`. Verify the panel reconnects.
- Delete (or replace with sanitized binaries) the `firmware.bin` and `panel-bridge-*.tar.gz` assets in all published GitHub releases. Tags can stay — assets are what carry the credentials.
- Note: the credential rotation is what actually closes the hole. GitHub CDN may keep cached copies briefly; asset deletion is hygiene, not the primary fix.

### Group C: Authorization surface tightening

- Replace wildcards in `/etc/sudoers.d/panel-bridge` with the specific subcommands actually used:
  - `/usr/bin/nmcli *` → individual nmcli commands (`radio wifi on|off`, `connection delete`, `connection add`, `connection up`, `device wifi list`, `device status`, `device show wlan0`, `monitor`).
  - `/usr/bin/systemctl is-active *` → specific services.
  - `/usr/bin/chvt *`, `/usr/bin/setfont *`, `/usr/bin/setterm *` — audit and tighten where possible.
- Override Pi-imager's `/etc/sudoers.d/010_pi-nopasswd` (NOPASSWD: ALL, noted under Proven Facts) — remove or override during install-pi.sh hardening so our restrictive entries are the only allowance.
- Default-exclude `text.thread_panel_*_wifi_password` from HA's recorder — ship a recorder-exclude rule with the integration rather than asking users to opt out via global config.

### Group D: OTA tamper-resistance (firmware signing)

- Generate an ed25519 signing keypair (offline; private key stored only on the build machine).
- During `cut-release`: sign `firmware.bin` with the private key; attach `firmware.bin.sig` as a release artifact.
- During `panel-update.sh`: download the signature alongside the binary; verify against the bundled public key (compiled into the bridge or stored under `/opt/panel/`) before forwarding to the C6.
- Public key bundled in the bridge tarball; rotated only if the private key is suspected compromised.
- Decision: not pursuing C6 hardware secure boot in this phase. The bridge-verified pipeline closes the OTA-tamper threat without invasive C6 changes; secure boot stays available as a future hardening step if the threat model warrants.

---

## Phase 2 — Polish & cleanup

No new features in this phase. Goal: well-organized, dead-code-free, DRYed, simplified, accurately commented, ready for new panels to drop in.

### Group A: Repo organization + multi-panel prep

- Move `panels/<id>/firmware/main/panel_app.c` shim contents into `platform/firmware/` driven by config. End state: `panels/<id>/` contains a UI directory + manifest + small config snippet only.
- Same treatment for `panels/<id>/ha/manifest.yaml` (becomes a manifest reference, no code).
- Acceptance: dropping in a new panel = UI bundle + manifest + a few lines of config, zero firmware fork.

### Group B: Dead code & file removal sweep

- Audit each top-level dir for unreferenced files. Known: V1 fallbacks (`tools/panel-ota` Thread-OTA path) superseded by V2 — flagged for removal once V2 is proven, which it now is.
- Audit Python imports for unused, dead conditionals.
- Remove HACS-validation workflow remnants if any remain.

### Group C: DRY + simplification pass

- Bridge: per-control sudo wrappers and similar mqtt subscription patterns — fold to shared helpers where natural.
- Integration: per-entity MQTT subscribe boilerplate is heavily repeated; consider an entity-base helper.
- Firmware: panel_state forwarding pattern repeated in many places.
- Cross-cutting: search for "look at where this is duplicated" with fresh eyes.

### Group D: Comment hygiene

- Sweep for stale comments referencing pre-Step-17b assumptions.
- Remove "this is for X" comments where X has changed.
- Update CLAUDE.md and the architecture paragraph in build_plan to reflect today's reality.

### Group E: Test foundation

- Bridge unit tests for the state cache + WS broadcast logic (pytest, minimal mocking).
- Integration tests that `_handle_resync` republishes everything (HA test framework supports this).
- UI component tests on the data-shape parsing in `useFeeder` (Vitest).
- Note: firmware build verification + end-to-end smoke tests stay deferred to V3 CI work.

---

## Phase 3+ — Themed groups

Named groups, no strict ordering. Pick whichever fits the moment when each becomes the right time.

### Quality of life (small fixes & polish)

- Bump OTA `waiting_for_connection` timeout to 120s (real-world observation of 63s connection-up suggests current 60s is too tight).
- Refine `PHASE_PERCENTAGES` based on real OTA timing data (creating_venv currently dominates; bar jumps 0→60% then hangs).
- Switch cut-release notes editor from vim to nano (vim `:q` cancels the release while still incrementing the version counter).
- Investigate GitHub release sort order weirdness on the releases page + HACS picker (current order: beta.28, beta.26, beta.9-4, beta.25, beta.24, ... — neither chronological nor alphabetical).
- Persistent journald on existing panels — document the manual one-liner in the README, or wire into install-pi.sh hardening.

### Robustness & correctness

- C6 `panel_state` envelope schema split into event vs state types — closes the retain-everything gap that beta.22 papered over.
- MQTT message fragmentation handling on the C6 — multi-callback assembly removes the 8 KB buffer band-aid.
- C6 UART rx state machine ignoring boot noise — start accumulating after seeing `{`, drop bytes that don't fit a JSON-line pattern.
- Slow post-power-cycle data backfill — needs landmark instrumentation before it's fixable. Add timestamped log lines at C6 thread-up, mqtt-connected, first-state-published; bridge ws-up, first-mqtt-msg-received; UI mount, first-entity-render.

### HA integration UX features

- Replace YAML-paste manifest with a real config flow (interactive entity picker, multi-select, attribute allowlists).
- "Unconfigured panel" splash in `platform/ui-core` (friendly setup-instructions screen instead of blank/directory listing).
- Configurable presence/theme thresholds via HA `number` entities (replaces `.env.production` constants — tune without rebuilding).
- WiFi UX: known-networks select + disable password field for known networks (don't require a password on already-saved profiles).

### Pi-side observability + correctness

- Pi clock drift fix: have the C6 broadcast time-of-day over MQTT; UI reads from there instead of local `Date()`.
- Ambient light sensor sensitivity bump — lower the C6 ADC publish threshold (companion to HA-driven thresholds in the UX group).

### Release pipeline maturity

- Per-component release cadence: sha-skipping approach where cut-release only re-uploads components whose content changed, and `update.py` compares the integration's sha across releases.
- Tag-based filtering improvements that fall out of the GitHub sort fix.

### Hardware affordances (mostly opportunistic)

- Software brightness control (hardware-gated on a swappable display).
- Thread mesh resilience monitoring (OpenThread mesh-error counters as HA diagnostic sensor).
- Cold-start LCD streakiness investigation (thermal test, PSU rail scope).

### Developer ergonomics

- `install-pi.sh` full bootstrap from fresh Pi OS Lite (folds in `dtoverlay=disable-bt`, NetworkManager, console-setup, installing any dependencies, all the V1-step prose).
- Kiosk-renderer choice via flag (`--cog` vs `--cage`).
- WPE bubblewrap sandbox proper fix (currently bypassed via `WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1`).
- Direnv + shell helper cleanup; cut-release sourced-function staleness.

### Multi-device support (triggered by panel #2 actually existing)

- Per-device MQTT credentials + per-device Mosquitto ACLs. install-pi.sh's prompt grows a panel_id input and generates a random per-device password if not supplied. Mosquitto ACL grants each per-device user only `thread_panel/<panel_id>/*`.
- Consistent device ↔ Pi ↔ UI association layer (probably a `device/<hostname>.conf` linking panel_id, hardware variant, served UI).

---

## Future / new panel ideas

Idea-track items, not yet scheduled. They'll likely act as hardness tests for V2 and provide feature ideas for V3. When either gets scheduled, it triggers the [multi-device support](#multi-device-support-triggered-by-panel-2-actually-existing) group above.

- **Panel 2: Home kiosk for light/scene control.** General-purpose home-automation surface — pick scenes, dim lights, etc.
- **Panel 3: Desk calendar / meeting status.** Work calendar display with meeting alerts.

---

## Completed work (historical reference)

The following phases shipped during V2 active development. Their detailed plans are kept here for archaeology — current state of each is the source of truth.

### Step 17 Phase 1 — Repo restructure + artifact releases ✅ DONE

**No behavior change on the Pi yet — just changes how artifacts are produced and where source lives.**

#### Repo moves

- `custom_components/thread_panel/` → `platform/integration/thread_panel/`
- Add `hacs.json` at the repo root (only thing left at root that exists for HACS):

  ```json
  {
    "name": "Thread Panel",
    "zip_release": true,
    "filename": "thread_panel.zip",
    "content_in_root": false
  }
  ```

  `content_in_root: false` means HACS validates that the GitHub tree at the release tag contains `custom_components/<domain>/manifest.json`. The zip itself contains the integration files at root (`manifest.json`, `__init__.py`, ...) — HACS extracts the zip directly into `<config>/custom_components/<domain>/`, so the zip layout is independent of `content_in_root`.

  Note: the integration source on `main` lives at `platform/integration/thread_panel/`, not `custom_components/thread_panel/`. The tag's tree satisfies HACS via a synthetic off-main release commit (see "Off-main release commit" below) — main stays clean of the duplicate.

#### `cut-release` extensions

Today: `yarn build` UIs, commit dist/, tag, push. After Phase 1:

1. Interactive version-bump prompt (see **Versioning scheme** below).
2. `yarn build` for every panel UI (existing).
3. `idf.py build` for every panel firmware (new).
4. `tar -czf panel-bridge-X.Y.Z.tar.gz -C platform/bridge .` (new).
5. **Off-main release commit for HACS layout** (new): `cp -r platform/integration/thread_panel custom_components/thread_panel`, substitute `__REPO__` in `update.py`, `git add custom_components/`, `git commit -m "Release vX.Y.Z (HACS layout)"`. The version-bump commit on main becomes the parent of this commit; main stays clean.
6. `cd platform/integration/thread_panel && zip -r ../../../thread_panel.zip .` (files at zip root — HACS extracts directly to `<config>/custom_components/<domain>/`. Static filename, no version suffix: HACS reads `filename` from hacs.json as a literal string and doesn't substitute `{version}` or any other placeholder.)
7. Generate `manifest.json` with version, sha256, size, and filename per component.
8. `git tag -a vX.Y.Z` at the off-main commit, then `git reset --hard <main-tip>` so main loses the duplicate. `git push origin HEAD vX.Y.Z` carries main + tag (and the off-main commit transitively, via the tag ref).
9. `gh release create vX.Y.Z [--prerelease] --notes-from-tag <artifacts...>`.
10. **Stop committing built artifacts to git** — UI dist/ and firmware bins are in releases now. Repo gets lean.

`cut-release` adopts [`gum`](https://github.com/charmbracelet/gum) (`brew install gum`) for arrow-key prompts.

#### Off-main release commit

HACS validates the GitHub tree at the release tag, expecting `custom_components/<domain>/manifest.json` (`content_in_root: false`) or `manifest.json` at repo root (`content_in_root: true`). The `HacsManifest` dataclass has no `subfolder`/`path` field — those are the only two layouts HACS supports.

Our `main` keeps the integration at `platform/integration/thread_panel/` for the platform/product split. Reconciling: cut-release creates a release commit *off* main that mirrors the integration into `custom_components/thread_panel/`, tags that commit, then resets main back. The off-main commit has the version-bump commit as its parent and is reachable only via the tag (git's gc respects tag-reachable objects the same as branch-reachable).

```
main:    A ── B ── C ── D        (tip after version bump)
                          \
                           E      ← tag vX.Y.Z (off-main, has custom_components/)
```

Effects:
- `git log main` shows A–D, no E.
- `git checkout main` shows the source of truth (`platform/integration/`, no `custom_components/`).
- `git checkout vX.Y.Z` shows what was released (detached HEAD at E with both `platform/integration/` and `custom_components/`).
- HACS's tree-API call at the tag returns E's tree → finds `custom_components/thread_panel/manifest.json` → validates.
- The zip artifact extracts as before, regardless of where the source lives.

This pattern is well-precedented (maven-release-plugin, sbt-release, etc. do variants). The one care point: cut-release must reset main back even on partial failure — the script handles this with explicit cleanup on the failure paths between commit and reset.

#### Pi install path

Update `install-pi.sh` to switch from git-clone to release-artifact pull:

```bash
# fetch the latest release manifest (or a specific version if --version given)
curl -L $(gh release view --json assets -q '.assets[] | select(.name=="manifest.json") | .url') -o /tmp/manifest.json

# for each component, download artifact, verify sha256, unpack into /opt/panel/versions/<version>/
# atomic symlink swap to /opt/panel/current
# render systemd units pointing at /opt/panel/current/*
# restart services
```

#### HA-box install

One-liner, documented in README:

```bash
curl -L "$(gh release view --json assets -q '.assets[] | select(.name|test("^thread_panel.*zip$")) | .url')" -o /tmp/tp.zip \
  && rm -rf /config/custom_components/thread_panel \
  && mkdir -p /config/custom_components/thread_panel \
  && unzip -o /tmp/tp.zip -d /config/custom_components/thread_panel/
```

The zip ships with files at its root (no inner `thread_panel/` wrapper), matching what HACS itself extracts into `<config>/custom_components/<domain>/`. The pre-clean (`rm -rf` + `mkdir -p`) ensures stale files from a previous install don't linger. Restart HA after. Once HACS-as-custom-repo is set up, this becomes "click update in HACS."

---

### Step 17 Phase 2 — C6 UART OTA receiver ✅ DONE

**No new hardware. Pi can flash C6 manually via a CLI; HA integration unchanged from Phase 1.**

#### Wire protocol

Extends the line-based JSON UART protocol with one binary mode for the firmware payload. Reuses existing OTA partition setup from V1 step 13 (E1 — partition table doesn't change). Reuses ESP-IDF rollback machinery (E2 — self-validation + bootloader revert).

```
Pi → C6: {"type":"ota_begin","size":1462320,"sha256":"abc..."}    [line, 115200]
C6 → Pi: {"type":"ota_ready"}                                      [line, 115200]
[both sides switch UART to 921600; C6 enters raw-pass-through mode]
Pi → C6: <exactly N raw firmware bytes>                            [raw, 921600]
[after N bytes received, both switch back to 115200 + line mode]
C6 → Pi: {"type":"ota_result","status":"ok|error","detail":"..."}  [line, 115200]
[on success: esp_ota_set_boot_partition() + esp_restart() after a 1s drain]
[on next boot, C6 self-validates: MQTT reconnect → esp_ota_mark_app_valid_cancel_rollback()]
[if self-validation fails, bootloader reverts on next reset]
```

Simplifications vs. the original sketch:

- **No `ota_progress` interleaved during raw transfer.** Once we're in raw mode at 921600, anything looking like `{` is just firmware bytes — JSON envelopes can't be distinguished. Progress UI is the Pi's job (it knows how many bytes it's sent).
- **No `ota_end`.** C6 already knows how many bytes to expect from `ota_begin.size`; it switches back to line mode after exactly N bytes.
- **No baud field in `ota_ready`.** Both sides hard-code OTA_BAUD_TRANSFER=921600. If we ever want to bump it, change the constant in both places in lockstep.
- **`ota_begin` handled even when `ha_availability == offline`.** Recovery path needs to work when HA is unreachable.

#### C6 firmware additions (`platform/firmware/components/panel_platform/`)

- `panel_ota_uart.{c,h}` — ota_begin parser, OTA partition write loop, sha256 verification (PSA Crypto — IDF v6.0 dropped the legacy `mbedtls/sha256.h` direct API in favor of PSA), baud switching, worker task.
- `panel_uart.{c,h}` extended with raw-mode callback API (`panel_uart_set_raw_mode` / `clear`) and runtime baud-switch (`panel_uart_set_baud`). Bumped RX ring buffer from 1 KB to 4 KB for headroom at 921600.
- `panel_version.h` — committed stub `v0.0.0-dev`; `cut-release` overwrites it as part of the version-bump phase, alongside the integration's `manifest.json`.
- `panel_app.c` wires the OTA dispatcher (handled before the ha_availability gate so OTA works during HA outages), publishes `state/version` retained on each MQTT connect, and gates every UART forward through `forward_to_pi_uart()` which drops sends while OTA is active. `sensors_publish_task` early-skips its body during OTA so it doesn't contend for CPU or spam the monitor.
- `mbedtls` added to `panel_platform/CMakeLists.txt` PRIV_REQUIRES for sha256.

**Hardening discovered during chunk 2b on-device testing:**

- `panel_uart`'s RX ring + chunk size: previously 4 KB ring + 256-byte reads. At 921600 baud (~92 KB/s) `rx_task` couldn't sweep the ESP-IDF UART driver's ring fast enough — a single 4 KB OTA chunk arrived in ~44 ms but each rx_task wakeup drained only 256 bytes, so the ring filled and the driver dropped bytes silently before they ever reached our stream buffer. Bumped to 16 KB ring + 4 KB chunks (8 KB task stack to hold them).
- `panel_ota_uart` stream buffer bumped from 16 KB → 64 KB to absorb worst-case `esp_ota_write` stalls (sector erase + write spikes to 100+ ms). Allocated only during the OTA window, freed on completion; 64 KB is fine on a C6 with 512 KB SRAM.
- `panel_net_pause()` / `panel_net_resume()` (new public API on `panel_net`): `esp_mqtt_client_stop` / `start`. Called from `panel_ota_uart_handle_begin` and `cleanup_and_release` respectively. esp-mqtt's TLS-handshake reconnect attempts directly competed with the OTA stream for Thread bandwidth + CPU.
- `panel_lidar_pause()` / `panel_lidar_resume()` (new public API on `panel_lidar`): `vTaskSuspend` + `uart_disable_rx_intr` (and reverse on resume, with `uart_flush_input` to drain stale bytes before unmasking). The lidar's per-byte UART0 reads (~900 B/s) generated interrupt traffic that contributed to UART1 RX latency. Same call sites as `panel_net_pause`.
- `panel_uart_set_baud` now no-ops when already at the target baud, suppressing duplicate "UART baud → X" log entries from the redundant `cleanup_and_release` call after the explicit set in `ota_task`.

#### Pi additions (`platform/bridge/`)

- `panel_bridge/ota.py` — `run_ota(uart, broadcast, bin_path)` reads the bin, computes sha256, drives the wire protocol via an `OtaSession` from `uart_link`. Emits `ota_status` and `ota_progress` envelopes via the broadcast hook so connected clients (and Phase 3's HA `update.panel_firmware`) can show progress.
- `panel_bridge/uart_link.py` extended:
  - `ota_session()` async context manager — routes incoming `ota_*` messages into a dedicated queue (other types keep flowing through the normal handler so UI clients still see sensors / state). Idempotent guard prevents concurrent OTA sessions.
  - `OtaSession.recv_json(expected_type, timeout)` — async wait-for-typed-message.
  - `write_raw(bytes)` and `set_baud(int)` — primitives the OTA driver needs; not exposed beyond the session.
- `panel_bridge/__main__.py` dispatches `{"type":"ota_request","path":"…"}` from any WS client by spawning `run_ota` as a detached task. The bridge reads the bin from disk — the binary doesn't traverse WS.
- `panel_bridge/cli/panel_flash.py` + `pyproject.toml` console script — `panel-flash [path]` connects to the bridge, sends `ota_request`, prints status + progress until complete/failed. Defaults to `/opt/panel/current/firmware.bin` and `ws://localhost:8765`.

---

### Step 17 Phase 3 — HA-orchestrated update flow ✅ DONE

Bringing it all together. HA orchestrates, bridge executes, GitHub is the source.

#### HA integration additions (in `platform/integration/thread_panel/`)

- New file: `update.py` — `PanelUpdateEntity(UpdateEntity)`:
  - `installed_version` — from C6's retained `state/version` topic
  - `latest_version` — from polling `https://api.github.com/repos/<owner>/<repo>/releases/latest` every hour
  - `release_summary` — from release body (markdown)
  - `release_url` — link to the release page
  - `async_install(version)` — publishes `cmd/update` with target version
  - Subscribes to `state/update_status` to drive the entity's progress display
- Config flow option: `Include prereleases` (boolean, default off). When off, latest_version filters to releases where GitHub's `prerelease: false`.

#### MQTT topics added (extending V1's panel-itself schema)

| Topic | Direction | Retain | Payload |
|---|---|---|---|
| `thread_panel/<id>/state/version` | C6 → MQTT | yes | `{"version":"v2.0.0-beta.1","build_time":"..."}` |
| `thread_panel/<id>/cmd/update` | HA → C6 → Pi | no | `{"version":"v2.0.0"}` |
| `thread_panel/<id>/state/update_status` | Pi → C6 → MQTT | no (high churn) | `{"phase":"flashing_c6","step":5,"of":9,"elapsed":12,"total_elapsed":34,"detail":"..."}` |
| `thread_panel/<id>/state/wifi_state` | Pi → C6 → MQTT | yes | `{"value":"connected"}` (added in Step 17b) |

#### Pi orchestration (chunk 3a)

Lives at `/opt/panel/current/deploy/panel-update.sh`, shipped in the panel-deploy tarball with each release. Sources the new shared `install-lib.sh` for the download/install primitives so install-pi.sh and panel-update.sh share ~80 lines of bash without duplication.

- Bridge subscribes to `cmd/update` via the existing UART-bridged `set/`/`cmd/` machinery. On `panel_cmd update`, the new `controls/update.py` handler spawns `panel-update.sh` with `start_new_session=True` so it survives the bridge restart that happens partway through. Combined with `KillMode=process` on `panel-bridge.service`, systemd doesn't drag the script down when the bridge restarts.
- Status reporting: panel-update.sh appends one JSON line per phase to `/opt/panel/update.status`. `panel_bridge/update_status.py` background task tails the file and republishes new lines as `state/update_status` panel_state envelopes through the existing pipeline.

Script flow (real implementation):

```
 0. PID lockfile check (refuse if previous panel-update.sh still alive)
 1. systemctl stop cog (kiosk → console)
 2. chvt 1 + setfont Lat15-TerminusBold32x16
 3. nmcli radio wifi on
 4. Wait for wlan0:connected (60s; added Step 17b)
 5. getent hosts api.github.com (10s; tightened Step 17b)
 6. lib_resolve_version (latest or arg → tag)
 7. lib_download_manifest
 8. lib_download_artifacts (sha256 verified)
 9. lib_extract_artifacts (into /opt/panel/versions/<v>/)
10. lib_create_venv + pip install bridge in-place
11. lib_swap_symlink (atomic ln -sfn + mv -T)
12. lib_render_units (templating User=)
13. lib_update_installed_json
14. systemctl restart panel-bridge.service  ← bridge restarts mid-script
15. systemctl restart panel-ui.service
16. healthcheck (both services active for 30s)
17. panel-flash $PANEL_ROOT/current/firmware.bin  (uses NEW bridge's panel-flash)
18. wait 10s for C6 to reboot + reconnect
19. lib_prune_old_versions (current + previous-1)
20. nmcli radio wifi off
21. trap restarts cog.service on exit (success or failure)

on healthcheck failure: roll back symlink to previous version, restart services
on C6 flash failure: log + continue (Pi is on new version, C6 still on old — valid intermediate)
```

Status events: `starting`, `enabling_wifi`, `waiting_for_connection`, `waiting_for_dns`, `resolving_version`, `resolved`, `downloading_manifest`, `downloading_artifacts`, `extracting`, `creating_venv`, `swapping_symlink`, `rendering_units`, `restarting_bridge`, `restarting_ui`, `healthcheck`, `flashing_c6`, `c6_flashed` / `c6_flash_failed`, `verifying_c6`, `c6_verified`, `disabling_wifi`, `done`, `rebooting`. On failure: `failed` with detail. On healthcheck rollback: `rolling_back` then `failed`.

#### Console update display (chunk 3a)

Added to `install-pi.sh`'s bootstrap-only setup phase, idempotent:

- Append `fbcon=rotate:3` to `/boot/firmware/cmdline.txt` if not already present — rotates the kernel framebuffer console independently of the KMS display driver.
- `apt install console-setup` if not already installed — pulls in Terminus fonts including `Lat15-TerminusBold32x16` (~32px tall, double-wide, legible on the small panel from across the room).
- Writes `/etc/sudoers.d/panel-bridge` with the entries panel-update.sh needs.

`panel-update.sh` uses `sudo setfont Lat15-TerminusBold32x16` at the start. The font reverts on the next sway start (cog regains the framebuffer).

#### Repo identity

Avoids hardcoded `chaddugas/thread_control_panel` strings in source. cut-release substitutes `__REPO__` placeholder at release-build time using `git remote get-url origin`. Touched at substitution time:

- `platform/deploy/install-pi.sh` — loose top-level artifact
- `platform/deploy/panel-update.sh` — in deploy tarball
- `platform/integration/thread_panel/update.py`

For local testing without cut-release, both scripts honor `REPO=foo/bar` env var override.

#### Phase 3a validation result

Full HA-triggered OTA round-trip (cmd/update → script → C6 reboot into new firmware → state/version reports new version → no manual intervention) **verified end-to-end** through v2.0.0-beta.11 with the panel screen showing live phase status the entire time. Two originally-blocking bugs (success-path `esp_restart()` blocked by fresh esp-mqtt TLS handshake, and `/dev/tty1` permissions reverting after `cog stop`) were fixed and validated by real OTAs.

#### Phase 3b validation result

`PanelUpdateEntity` shipped through betas 13–25 with the following blocking issues all resolved:

1. ✅ FIXED in beta.18 — OptionsFlow ordering bug. Replaced manual reload with `entry.add_update_listener(_async_reload_on_change)` so the framework triggers reload on options changes.
2. HACS state caching across `content_in_root` flips — HACS bug; workaround is delete + re-add the custom repo.
3. ✅ FIXED in beta.19 — Doubled-path `custom_components/thread_panel/thread_panel/`. `git reset --hard` doesn't remove now-untracked empty dirs; added `rm -rf custom_components` pre-clean before the cp.
4. ✅ FIXED in beta.19 — HACS doesn't substitute `{version}` in hacs.json's filename. Filename is now static `thread_panel.zip`.
5. ✅ FIXED in beta.20 — Most-recent release wasn't actually most-recent. GitHub's `/releases` endpoint sorts by tag name (lex desc), not chronological. update.py now sorts by `created_at` itself before picking.
6. ✅ FIXED in beta.21 — "Unknown error" alert on the entity panel. Cause: `RELEASE_NOTES` feature declared without overriding `async_release_notes`. Override added.
7. ✅ FIXED in beta.22 — `update_percentage` not rendering progress bar. Added `UpdateEntityFeature.PROGRESS` + `PHASE_PERCENTAGES` map driven from `state/update_status`.
8. ✅ FIXED in beta.22 — Ghost installs from retained `state/update_status` at HA startup. Cause: panel_app.c publishes all panel_state envelopes with retain=1; on HA restart the broker replays the last terminal phase. Fix: `_on_update_status_message` ignores retained messages. Architectural debt logged: firmware should distinguish event-stream vs state topics — captured in [Robustness & correctness](#robustness--correctness) for later.
9. ✅ FIXED in beta.23-25 — Various OTA polish items: post-`done` version-match hold (in_progress stays True until `state/version` reports the target); flip `in_progress=True` before awaiting MQTT publish (button disables immediately on click); aiohttp `ClientTimeout` typing fix.

---

### Step 17b — WiFi state surface and observability ✅ DONE

Sibling to Step 17. Promoted out of backlog mid-V2 because (a) the OTA flow's `enabling_wifi → waiting_for_dns` step is one of the slow phases users see and we don't have visibility into where the time goes, and (b) the bridge's WiFi entity surface was unreliable enough that observed state could lie ("connected to main network" while SSH times out, stays "connected" minutes after toggling off, etc.).

#### Motivation (observed 2026-04-30)

Symptoms that drove this step:

- Network entity reported "connected to main network" while SSH timed out — entity claimed connectivity that didn't exist at IP layer.
- Toggle WiFi switch OFF → entity stayed at "main network" for several minutes before flipping to "Unknown".
- Toggle WiFi switch ON → 4+ minutes later, switch entity still reported off, scan-for-networks button produced no visible networks.
- `wifi_error` entity has been at "Unknown" since added — never reported a real value.
- Network select entity shows last-user-selected network, not currently-connected SSID.
- OTA's `enabling_wifi → waiting_for_dns` lumps connection-up time (scan + auth + DHCP, ~50-60s) into the DNS-resolution phase, so the user can't tell what's actually slow.
- Pi journals are tmpfs by default; reboots and power cycles lose all bridge logs from the prior boot, making post-mortem debugging hard.

#### Plan (commit-by-commit) — all DONE

**~~Commit A — Persistent journals + structured-event logger helper.~~** ✅ DONE. Configures `Storage=persistent` in `journald.conf` via `install-pi.sh` (creates `/var/log/journal/`, sets retention caps, restarts journald). Adds `panel_bridge/events.py` with `log_event(logger, name, **fields)` emitting `event=<name> k=v` lines greppable via `journalctl --grep`. Zero new dependencies — traded clean structured fields for greppability.

**~~Commit B — `nmcli` timeouts.~~** ✅ DONE. New `controls/nmcli_util.py` centralizes subprocess execution that previously lived inline in wifi.py + privately in wifi_manage.py; default 30s `asyncio.wait_for` ceiling on every call. On timeout, kills the subprocess, emits `nmcli_timeout` structured event, and returns rc=124 (GNU `timeout` convention) so callers handle it as a normal failure. Verified `nmcli_timeout` count = 0 in steady-state validation.

**~~Commit C — Live connection state + on-toggle full refresh.~~** ✅ DONE. `_current_ssid` now queries `nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION device show wlan0` and only returns a name when GENERAL.STATE starts with "100" (NM's `ACTIVATED`). `apply_wifi_enabled` calls a new public `wifi_manage.refresh_state(bridge)` after toggling, so SSID + scan + error all update immediately rather than waiting for the next periodic tick.

**~~Commit D — Event-driven updates via `nmcli monitor` + `wifi_state` enum.~~** ✅ DONE. New `controls/wifi_state.py` runs `nmcli monitor` as a long-lived background task (each line is a generic edge trigger to re-read state); publishes a single `state/wifi_state` topic carrying one of disabled/disconnected/connecting/connected/error. Reconcile loop at 60s is the safety net.

**~~Commit E — Split `enabling_wifi → waiting_for_connection → waiting_for_dns` in panel-update.sh.~~** ✅ DONE. New `waiting_for_connection` phase polls `nmcli -t -f DEVICE,STATE device status` for `wlan0:connected` (60s timeout); `waiting_for_dns` is now a tight 10s DNS-only check post-connection. Real-world observation: NM connection-up can take ~63s on this panel — bumping to 120s captured in [Quality of life](#quality-of-life-small-fixes--polish).

**~~Commit F — Tighten periodic loop to 10s.~~** ✅ DONE. `wifi_manage.SCAN_INTERVAL_S` 30s → 10s. Safe to tighten now that timeouts protect against hangs and event-driven updates carry the live state path.

**~~Commit G — HA integration entity polish for "Disconnected" surface.~~** ✅ DONE. New `PanelWifiStateSensor` (SensorDeviceClass.ENUM, options Disabled/Disconnected/Connecting/Connected/Error) subscribes to `state/wifi_state`; `PanelWifiSsidSensor` shows "Disconnected" instead of None when SSID is empty; `PanelWifiErrorSensor` shows "No error" instead of None when empty.

#### Success criteria (validated through v2.0.0-beta.25–28 — initial cut + a series of no-op cuts to exercise the new panel-update.sh on a second OTA, per the spawn-at-request-time gotcha)

1. ✅ WiFi switch entity flips state within ~1s of any nmcli-side change. Journal shows `wifi_state_change` events arriving sub-second after `wifi_action`.
2. ✅ SSID entity reflects actual connection state — toggling off transitions `connected → disabled` within 200ms in the journal.
3. ✅ `wifi_state` enum queryable in HA, walks through Disabled → Disconnected → Connecting → Connected on toggle.
4. ✅ Entities surface "Disconnected"/"No error" not "Unknown" when WiFi is disabled.
5. ✅ OTA's `waiting_for_connection` phase visible in HA's progress bar (validated via no-op beta cut + second OTA per the spawn-at-request-time gotcha).
6. ✅ Persistent journals landing on disk (`/var/log/journal/<machine-id>/system.journal`).
7. ✅ Structured WiFi events flow as expected: `journalctl --grep 'event='` shows `wifi_action` + `wifi_state_change` lines with the source module preserved, fields unambiguous.

---

## Reference

### Versioning scheme

Standard semver including prerelease syntax: `v<MAJOR>.<MINOR>.<PATCH>` for stable, `v<MAJOR>.<MINOR>.<PATCH>-<tag>.<N>` for prereleases. Tags: `alpha`, `beta`, `rc` per software-release-engineering convention.

| Tag | Convention | When to use |
|---|---|---|
| alpha | feature-incomplete, knowingly broken paths | dogfooding to yourself only |
| beta | feature-complete, unproven | shared with opt-in testers; bugs expected |
| rc | believed done | each rc.N fixes only what rc.(N-1) surfaced |

Repo-wide version (one number for all components per release). The manifest's per-component sha256 lets the Pi skip unchanged components on update.

GitHub Releases has a built-in `prerelease: true` flag — `cut-release` sets it for any version with a `-` in it. The integration's `Include prereleases` option toggles whether prerelease versions are considered for `latest_version`.

### `cut-release` interactive prompt

When current version is stable (e.g., `v1.4.0`):

```
Current: v1.4.0
Bump:
  patch          → v1.4.1
  minor          → v1.5.0
  major          → v2.0.0
  pre-patch      → v1.4.1-?.1     (asks alpha/beta/rc)
  pre-minor      → v1.5.0-?.1     (asks alpha/beta/rc)
  pre-major      → v2.0.0-?.1     (asks alpha/beta/rc)
  custom
```

When current version is a prerelease (e.g., `v2.0.0-beta.1`), two extra options at the top:

```
Current: v2.0.0-beta.1
Bump:
  prerelease     → v2.0.0-beta.2     (iterate same pre)
  promote        → v2.0.0            (drop prerelease suffix)
  patch          → v2.0.1
  minor          → v2.1.0
  major          → v3.0.0
  pre-patch      → v2.0.1-?.1
  pre-minor      → v2.1.0-?.1
  pre-major      → v3.0.0-?.1
  custom
```

Convention chosen over a two-stage flow (release-type then bump) because it matches `npm version` / `cargo` muscle memory and avoids forcing a stable-vs-pre decision before deciding the bump magnitude.

### File changes summary (snapshot through Step 17b)

#### Created

| Path | Purpose |
|---|---|
| `hacs.json` | Repo-root HACS config: `zip_release: true`, points at integration zip artifact |
| `platform/integration/thread_panel/` | Integration source (moved from `custom_components/`) |
| `platform/integration/thread_panel/update.py` | `PanelUpdateEntity` |
| `platform/firmware/components/panel_platform/panel_ota_uart.c` | C6 UART OTA receiver |
| `platform/firmware/components/panel_platform/panel_version.h` | Generated at build time from `git describe` |
| `platform/bridge/panel_bridge/ota.py` | Pi-side firmware-over-UART sender |
| `platform/bridge/panel_bridge/cli/panel_flash.py` | Manual flash CLI |
| `platform/bridge/panel_bridge/events.py` | Structured-event logger helper (Step 17b) |
| `platform/bridge/panel_bridge/controls/nmcli_util.py` | Shared nmcli runner with timeout (Step 17b) |
| `platform/bridge/panel_bridge/controls/wifi_state.py` | wifi_state enum + nmcli monitor task (Step 17b) |
| `platform/deploy/panel-update.sh` | Orchestration script |
| `docs/build_plan_v2.md` | This document |

#### Modified

| Path | Change |
|---|---|
| `tools/cut-release.zsh` | Add interactive bump prompt (gum), firmware build, tarballing, zip, manifest.json, gh release create with --prerelease flag |
| `platform/deploy/install-pi.sh` | Switch from git-clone to release-artifact pull; add `fbcon=rotate:3` + console-setup; render systemd units pointing at `/opt/panel/current/`; configure persistent journald (Step 17b) |
| `platform/deploy/panel-bridge.service` | `ExecStart=/opt/panel/current/bridge/...` |
| `platform/deploy/panel-ui.service` | Root at `/opt/panel/current/ui-dist/` |
| `platform/firmware/components/panel_platform/panel_app.c` | Wire ota_uart handler; publish state/version on connect |
| `panels/feeding_control/firmware/main/panel_app.c` | Subscribe to cmd/update; forward over UART |
| `README.md` | Document new install paths (Pi + HA box) from release artifacts |
| `CLAUDE.md` | Reference both build_plan docs; note V2 is active work |

#### Removed (during Phase 1)

| Path | Why |
|---|---|
| `custom_components/thread_panel/` | Moved to `platform/integration/thread_panel/` |
| `panels/feeding_control/ui/dist/` | Built artifacts now in releases, not git |
| `.github/workflows/validate.yml` | HACS validation that always failed on main (per off-main commit pattern) — removed in beta.23 |

### Resolved decisions

1. **Where does `cut-release` run?** Mac. CI is V3.
2. **Auto-install vs. manual?** Manual only. HA polls GitHub releases hourly, surfaces "update available" via the entity, user clicks Install. Scheduled auto-install removed from scope.
3. **Version retention on Pi.** Keep `current` + `previous-1`, prune older. `/opt/panel/versions/` cleanup runs at end of successful update.
4. **Repo-wide vs per-component versions.** Repo-wide. Per-component sha256 in manifest handles "only re-flash if changed."
5. **HACS publication.** Skipped — project is too hardware-specific to be useful as a default-store integration. HACS-as-custom-repo (user adds the repo URL) stays available.
6. **Update transport for C6.** UART at 921600 baud during transfer (~15s for ~1.5 MB). Thread-OTA stays in tree as fallback until V2 proven.
7. **Console display approach.** tty1 takeover with `fbcon=rotate:3` + `setfont Lat15-TerminusBold32x16`, not a web UI overlay. Doesn't depend on the kiosk being healthy (which matters precisely when you're updating to fix it).
8. **Beta versioning scheme.** Standard semver prereleases (`-beta.N`), npm-style flat bump menu in cut-release, integration toggle for `Include prereleases`.

### Open questions

- Healthcheck thresholds in `panel-update.sh`. "Bridge active for 30s" is a starting point — may need tuning. Same for "C6 reconnect within N seconds after flash." Set conservative defaults, log actuals during test releases, tune from data.
- Concurrent-update protection. If `cmd/update` arrives while one is in flight, what happens? Probably: write a `/var/run/panel-update.pid` lockfile in step 1, refuse to start if it exists, publish `state/update_status: rejected, detail: in_progress`. Keep simple.
- `panel-update.sh` log retention. Each run should write a full log to `/var/log/panel-update/<timestamp>.log` for post-mortem. Retention policy TBD (keep last 10? last 30 days?). Easy to add later.
- Whether to include the bridge tarball *in* the bridge's own version directory (so the source-of-truth tarball is preserved on disk) or just unpack-and-discard. Probably preserve — useful for debugging "did I actually install what I think I installed."

---

## Lessons Learned

- **`esp_restart()` runs registered shutdown handlers, and a fresh esp-mqtt TLS handshake will block them.** During chunk 3a's OTA path, the success-path `cleanup_and_release()` was calling `panel_net_resume()` → `esp_mqtt_client_start()` right before `esp_restart()`. The shutdown handlers registered by `esp_mqtt_client_start` blocked `esp_restart()` while the brand-new TLS handshake was in flight. Symptom: `esp_ota_set_boot_partition()` succeeded but the chip kept running on the old firmware indefinitely. **Rule for any "we're about to reboot" path:** don't bring services back up; the chip is about to wipe RAM anyway. Skip the resume, send the result envelope, brief delay for UART drain, `esp_restart()`. Failure paths still need `cleanup_and_release` to keep the chip running.

- **Bash with `set -u` (no `set -e`) silently continues past `exec >` redirect failure.** Verified directly: `bash -c 'set -u; exec > /etc/shadow 2>&1; echo after'` exits 0 with `after` going to original stdout. If that original stdout is DEVNULL (as it is for any service spawned by systemd-managed bridge with `stdout=DEVNULL`), every subsequent echo vanishes. **Rule:** any `exec > <file>` in a script that may run unattended needs a `[ -t 1 ]` (or equivalent) check after, with a fallback that surfaces the failure somewhere durable. Otherwise the failure mode is invisible.

- **`/dev/tty1` ownership reverts to `root:tty` mode 600 the moment cog/sway with `PAMName=login` stops.** Adding the install user to the `tty` group does NOT help — mode 600 means group has no permissions either. The fix on a service-spawned (non-tty) script that wants to write to /dev/tty1 is `sudo chown $USER /dev/tty1` between `chvt 1` and the `exec` redirect. Don't get pulled down rabbit holes about screen blanking, framebuffer rotation, or VT disallocation when the symptom is "nothing on screen": test the permissions first.

- **Bridge spawns `/opt/panel/current/deploy/panel-update.sh` at request time, which is the OLD version's script — the symlink swap to the new version happens partway through.** Practical implication: any change to `panel-update.sh` only takes effect on the OTA *after* the one that installs it. To validate a fix to `panel-update.sh`, you need two OTAs: cut N → trigger OTA, then cut N+1 → trigger OTA. The first one installs the fix, the second one runs it. C6-firmware fixes don't have this delay because the C6 is already running the firmware that handles the post-flash reboot.

- **Commit subject scope prefixes should be unambiguous in any rendering context.** Commits prefixed `update entity:` were displayed as bullet points inside HA's update entity dialog (auto-generated release notes), where they read as if HA was announcing something about the entity itself. Use file/class names (`PanelUpdateEntity:`, `update.py:`, `panel_app.c:`) over loose noun phrases for any future scope prefix.

## Proven Facts

- **OTA round-trip latency:** beta.9 → beta.10 took ~140s end-to-end on the production Pi/C6: download + extract ~10s, venv + symlink swap ~65s, healthcheck 30s, panel-flash ~22s, C6 reboot + MQTT reconnect + republish ~6s, wifi-off skip + done ~1s. Healthcheck dominates the wait — could be tightened if iteration speed becomes a bottleneck (currently it's a feature: catches a bouncing service before we flash the C6).

- **NM connection-up takes ~60s on this panel after a radio cycle.** Observed 2026-04-30: WiFi state machine walked from `connecting` to `connected` in 63s after a fresh `nmcli radio wifi on`. Sits 3s under the OTA's 60s `waiting_for_connection` timeout; bumping to 120s captured in the Quality of life group.

- **Broker is not externally reachable.** Verified 2026-04-30: cellular `openssl s_client -connect the-interstitial-space.duckdns.org:8883` and `:1883` both time out on v4. No AAAA record on the duckdns subdomain. HA box has only ULA + link-local v6 (no globally-routable v6 address). MQTT credential leak via `firmware.bin` published in public releases is therefore LAN-blast-radius only — not zero risk, but bounded to anyone already on the LAN.

- **`chaddugas` user has wide-open `NOPASSWD:ALL` via `/etc/sudoers.d/010_pi-nopasswd`** (Pi-imager first-boot drop-in). This is what makes `sudo chown $USER /dev/tty1` work on the production Pi without our explicit sudoers entry. The entry we added in `install-pi.sh`'s drop-in is for cleanliness on Pis that don't have the imager's wide-open rule. Phase 1 Group C plans to override this.

- **Git history is clean of MQTT credentials.** `git log -S 'myvxan' --all` returns nothing — sdkconfig has been gitignored from the start. The only credential leak path is the published `firmware.bin` artifacts on GitHub releases.

## Technical Debt

### Outstanding

(empty — all known debt items have been re-homed into Phase 1, Phase 2, or Phase 3+ above)

### Resolved

(empty — populated as items get closed out)
