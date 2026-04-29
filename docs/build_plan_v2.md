# Thread Control Panel — Build Plan V2

> **Status: planning, no code changes yet.** V1 shipped 2026-04-28 (see [build_plan_v1.md](build_plan_v1.md) for the historical record + current production state).
>
> V2 has two parts:
>
> 1. **Step 17 — Artifact-based releases + HA-orchestrated remote updates.** The headline reshape: instead of the Pi pulling the full repo over `git`, releases are published as artifact bundles on GitHub Releases and the Pi installs only what it needs. Updates are triggered remotely via a HA `update.panel_firmware` entity that orchestrates the whole sequence: WiFi on, pull artifacts, flash C6 over UART, swap UI, restart services, WiFi off — without anyone touching the panel. Detailed phased plan below.
>
> 2. **Steps 18–22 — Backlog promoted from V1's "V2 / Post-V1 follow-ups" section.** Coarser-grained items grouped by theme (setup/deploy, architecture, multi-device, robustness, hardware) that accumulated during V1 build. They sit at the end of this doc as a backlog for V2-era work; we'll detail and re-phase individually as each comes up. Some have natural dependencies on Step 17 and should land after it; others are independent.

## Keeping this current

Same convention as V1. After completing a step or making a non-trivial decision:

- Strike through the finished step (`~~**Step name**~~`) and append `✅ DONE`.
- Move the `(next up)` marker.
- Record meaningful learnings in **Lessons Learned**, validated invariants in **Proven Facts**, and known-but-deferred problems in **Technical Debt**.
- Refresh **Current Status** when a major capability lands or changes.
- Edit/remove anything the work has invalidated rather than leaving stale guidance behind.

When V2 ships and the V2 patterns become "current production state," migrate the still-authoritative bits (MQTT topic additions, UART protocol additions, etc.) into a consolidated reference (likely a successor `build_plan_v3.md`) so v1 + v2 don't drift into mutual contradiction.

## Current Status

Planning complete; implementation not started. Phase 1 is the next action.

## Goals

**Step 17 (the headline reshape):**

1. **Eliminate full-repo presence on the Pi.** Pi carries only runnable artifacts (~5–10 MB per release vs. hundreds of MB of source/git history accumulated under the V1 git-pull model).
2. **Trigger updates remotely from HA** via the native `update` entity domain — no SSH, no Mac required at deploy time. Click "Install" in HA, watch progress on the panel screen.
3. **Pi spends <60s online per update window**; offline by default. The orchestration script enables WiFi, does its work, and disables WiFi at the end (success or failure with a healthcheck pass).
4. **C6 firmware rides the existing UART link at high baud** (~15s for a full firmware) — supersedes the Thread-OTA path from V1 step 13. The HTTP-OTA-over-Thread machinery stays in the tree as a fallback (~15–20 min, slow but functional) until V2 is proven; it is no longer the primary path.
5. **Move `custom_components/thread_panel/` into `platform/integration/`** where it architecturally belongs. HACS consumes a release-zip artifact via `hacs.json` `zip_release: true`, so the integration source is no longer constrained to live at the repo root.
6. **Beta-friendly versioning** so iteration on V2 itself can ship as `v2.0.0-beta.N` releases without confusing the stable update channel.

**Backlog (Steps 18–22) — additional V2 goals carried over from V1:**

7. **One-command Pi bootstrap** from a fresh Pi OS Lite image, plus per-host kiosk-renderer choice and a long-overdue cleanup of dev shell helpers. (Step 18)
8. **Tighter platform/product separation in the integration and repo layout** — interactive config flow instead of YAML paste, unified device↔Pi↔UI association, ui-core "unconfigured panel" splash, possibly collapsing `panels/<id>/firmware` and `panels/<id>/ha` into platform-driven configs. (Step 19)
9. **Per-device identity** so the system can scale past a single panel — NVS-provisioned per-device MQTT credentials at first boot. (Step 20)
10. **Robustness** — automated tests, MQTT fragmentation handling, C6 UART boot-noise filter, WPE bubblewrap proper fix, runtime-tunable presence/theme thresholds via HA. (Step 21)
11. **Hardware affordances** — backlight brightness control if the display gets swapped or a software dim works, Thread mesh resilience monitoring as a HA diagnostic sensor. (Step 22)

## Non-goals (V2)

- HACS publication to the default community store. The project depends on custom-assembled hardware that almost no one else can use; HACS distribution adds packaging burden without real audience. Stays as private install (manual zip, or HACS as a custom repository).
- Auto-install on a schedule (cron-style "install at 3am Sunday"). Manual-trigger only — HA notices the new version and surfaces it in the entity, the user clicks Install when ready.
- CI-based builds. `cut-release` runs on the Mac (where dev work happens anyway). Moving to GitHub Actions is a V3 question.

## End-state architecture

```
GitHub Release v2.0.0
├── feeding_control-firmware-2.0.0.bin
├── feeding_control-ui-2.0.0.tar.gz
├── panel-bridge-2.0.0.tar.gz
├── thread_panel-2.0.0.zip          # integration, for HACS-as-custom-repo or manual install
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

## Phasing

Land in this order, each as its own commit + release. Each phase leaves the system in a working, releasable state.

- **Phase 1** — Repo restructure + artifact-based releases. Manual SSH update on Pi until Phase 3.
- **Phase 2** — C6 UART OTA receiver. Validated via a manual `panel-flash` Pi-side CLI. Independent of Phase 3, immediately useful.
- **Phase 3** — HA-orchestrated update flow. Wires everything together.

Each phase is roughly 1–2 days of work.

---

## Phase 1 — Repo restructure + artifact releases

**No behavior change on the Pi yet — just changes how artifacts are produced and where source lives.**

### Repo moves

- `custom_components/thread_panel/` → `platform/integration/thread_panel/`
- Add `hacs.json` at the repo root (5-line file, only thing left at root that exists for HACS):

  ```json
  {
    "name": "Thread Panel",
    "zip_release": true,
    "filename": "thread_panel-{version}.zip",
    "content_in_root": false
  }
  ```

### `cut-release` extensions

Today: `yarn build` UIs, commit dist/, tag, push. After Phase 1:

1. Interactive version-bump prompt (see **Versioning scheme** below).
2. `yarn build` for every panel UI (existing).
3. `idf.py build` for every panel firmware (new).
4. `tar -czf panel-bridge-X.Y.Z.tar.gz -C platform/bridge .` (new).
5. `cd platform/integration && zip -r thread_panel-X.Y.Z.zip thread_panel/` (new).
6. Generate `manifest.json` with version, sha256, size, and filename per component.
7. `git tag vX.Y.Z && git push --tags`
8. `gh release create vX.Y.Z [--prerelease] --notes-from-tag <artifacts...>`
9. **Stop committing built artifacts to git** — UI dist/ and firmware bins are in releases now. Repo gets lean.

`cut-release` adopts [`gum`](https://github.com/charmbracelet/gum) (`brew install gum`) for arrow-key prompts.

### Pi install path (Phase 1 form)

Update `install-pi.sh` to switch from git-clone to release-artifact pull:

```bash
# fetch the latest release manifest (or a specific version if --version given)
curl -L $(gh release view --json assets -q '.assets[] | select(.name=="manifest.json") | .url') -o /tmp/manifest.json

# for each component, download artifact, verify sha256, unpack into /opt/panel/versions/<version>/
# atomic symlink swap to /opt/panel/current
# render systemd units pointing at /opt/panel/current/*
# restart services
```

Manual-update flow during Phase 1 = `ssh pi 'sudo install-pi.sh --version v2.0.0-beta.N'`. Phase 3 wraps this in HA.

### HA-box install (Phase 1 form)

One-liner, documented in README:

```bash
curl -L "$(gh release view --json assets -q '.assets[] | select(.name|test("^thread_panel.*zip$")) | .url')" -o /tmp/tp.zip \
  && unzip -o /tmp/tp.zip -d /config/custom_components/
```

Restart HA after. Once we set up HACS-as-custom-repo (optional, post-V2), this becomes "click update in HACS."

### Validation

- Cut `v2.0.0-beta.1`, verify the GitHub release page shows all five artifacts with correct sha256 in `manifest.json`.
- Manually install integration from zip on HA box; verify it loads.
- Manually run `install-pi.sh --version v2.0.0-beta.1` on a test Pi; verify `/opt/panel/current` is populated, services restart, kiosk comes up.

---

## Phase 2 — C6 UART OTA receiver

**No new hardware. Pi can flash C6 manually via a CLI; HA integration unchanged from Phase 1.**

### Wire protocol (as implemented in chunk 2a)

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

### C6 firmware additions (`platform/firmware/components/panel_platform/`)

- `panel_ota_uart.{c,h}` — ota_begin parser, OTA partition write loop, sha256 verification (PSA Crypto — IDF v6.0 dropped the legacy `mbedtls/sha256.h` direct API in favor of PSA), baud switching, worker task.
- `panel_uart.{c,h}` extended with raw-mode callback API (`panel_uart_set_raw_mode` / `clear`) and runtime baud-switch (`panel_uart_set_baud`). Bumped RX ring buffer from 1 KB to 4 KB for headroom at 921600.
- `panel_version.h` — committed stub `v0.0.0-dev`; `cut-release` overwrites it as part of the version-bump phase, alongside the integration's `manifest.json`.
- `panel_app.c` wires the OTA dispatcher (handled before the ha_availability gate so OTA works during HA outages), publishes `state/version` retained on each MQTT connect, and gates every UART forward through `forward_to_pi_uart()` which drops sends while OTA is active.
- `mbedtls` added to `panel_platform/CMakeLists.txt` PRIV_REQUIRES for sha256.

### Pi additions (`platform/bridge/`, chunk 2b)

- `panel_bridge/ota.py` — `run_ota(uart, broadcast, bin_path)` reads the bin, computes sha256, drives the wire protocol via an `OtaSession` from `uart_link`. Emits `ota_status` and `ota_progress` envelopes via the broadcast hook so connected clients (and Phase 3's HA `update.panel_firmware`) can show progress.
- `panel_bridge/uart_link.py` extended:
  - `ota_session()` async context manager — routes incoming `ota_*` messages into a dedicated queue (other types keep flowing through the normal handler so UI clients still see sensors / state). Idempotent guard prevents concurrent OTA sessions.
  - `OtaSession.recv_json(expected_type, timeout)` — async wait-for-typed-message.
  - `write_raw(bytes)` and `set_baud(int)` — primitives the OTA driver needs; not exposed beyond the session.
- `panel_bridge/__main__.py` dispatches `{"type":"ota_request","path":"…"}` from any WS client by spawning `run_ota` as a detached task. The bridge reads the bin from disk — the binary doesn't traverse WS.
- `panel_bridge/cli/panel_flash.py` + `pyproject.toml` console script — `panel-flash [path]` connects to the bridge, sends `ota_request`, prints status + progress until complete/failed. Defaults to `/opt/panel/current/firmware.bin` and `ws://localhost:8765`.

### Validation

- `panel-flash /opt/panel/current/firmware.bin` on the Pi flashes the C6, reboots, version topic reports the new value.
- Rollback: intentionally break new firmware (e.g., kill MQTT in startup before mark-valid), confirm bootloader reverts on next reset.

---

## Phase 3 — HA-orchestrated update flow

Bringing it all together. HA orchestrates, bridge executes, GitHub is the source.

### HA integration additions (in `platform/integration/thread_panel/`)

- New file: `update.py` — `PanelUpdateEntity(UpdateEntity)`:
  - `installed_version` — from C6's retained `state/version` topic
  - `latest_version` — from polling `https://api.github.com/repos/<owner>/<repo>/releases/latest` every hour
  - `release_summary` — from release body (markdown)
  - `release_url` — link to the release page
  - `async_install(version)` — publishes `cmd/update` with target version
  - Subscribes to `state/update_status` to drive the entity's progress display
- Config flow option: `Include prereleases` (boolean, default off). When off, latest_version filters to releases where GitHub's `prerelease: false`.

### MQTT topics added (extending V1's panel-itself schema)

| Topic | Direction | Retain | Payload |
|---|---|---|---|
| `thread_panel/<id>/state/version` | C6 → MQTT | yes | `{"version":"v2.0.0-beta.1","build_time":"..."}` |
| `thread_panel/<id>/cmd/update` | HA → C6 → Pi | no | `{"version":"v2.0.0"}` |
| `thread_panel/<id>/state/update_status` | Pi → C6 → MQTT | no (high churn) | `{"phase":"flashing_c6","step":5,"of":9,"elapsed":12,"total_elapsed":34,"detail":"..."}` |

`cmd/update` rides the existing UART-bridged `set/`/`cmd/` machinery with no new C6 logic beyond a topic-name addition. `state/update_status` is non-retained because it's high-churn ephemeral progress data; the integration tracks the update-in-progress in HA state.

### Pi orchestration (`panel-update.sh`)

Lives at `/opt/panel/current/panel-update.sh` — versioned with releases so a release can ship its own updated installer.

- Bridge subscribes to `cmd/update`, on receipt spawns `panel-update.sh` detached (nohup), exits cleanly. The script lives independently of the bridge process so the bridge can be restarted mid-update without killing the orchestration.

Script flow (each step writes to `/dev/tty1` with elapsed timer + checklist; each phase publishes `state/update_status`):

```
 1. systemctl stop sway                     # kiosk → console
 2. setfont ter-132n                        # giant font for visibility
 3. nmcli radio wifi on
 4. wait up to 60s for getent hosts api.github.com
 5. curl release manifest.json + verify shape
 6. for each component where sha256 differs from installed.json:
       download artifact → /opt/panel/staging/
       verify sha256
       unpack to /opt/panel/versions/<new>/
 7. ln -sfn versions/<new> /opt/panel/current.new && mv -T /opt/panel/current.new /opt/panel/current
 8. if firmware.sha256 changed: panel-flash, wait for C6 reconnect + version match
 9. if ui.sha256 changed:        systemctl restart panel-ui
10. if bridge.sha256 changed:    systemctl restart panel-bridge
11. healthcheck: bridge active for 30s, panel-ui responds 200, MQTT connected, C6 version matches target
12. write installed.json
13. nmcli radio wifi off
14. setfont (default)
15. systemctl start sway                    # back to kiosk
16. publish state/update_status: done

on any failure between steps 7–11:
  - rollback symlink to previous version
  - restart services with old version
  - leave WiFi on for diagnostics
  - publish state/update_status: failed, detail: <step name>
```

### Console update display

Add to `install-pi.sh` (one-time setup):

- Append `fbcon=rotate:3` to `/boot/firmware/cmdline.txt` — rotates the kernel framebuffer console independently of the KMS display driver. (V1 lessons confirm `video=...rotate=N` does NOT work on Bookworm's vc4-kms-v3d; `fbcon=rotate=N` is a different mechanism that does.)
- `apt install console-setup` — pulls in Terminus fonts including `ter-132n` (~32px tall, double-wide, ideal for the small physical display when rotated).

`panel-update.sh` uses `setfont ter-132n` at the start and restores default at the end — giant font only during updates, normal at all other times.

Output format on the panel during an update:

```
Panel Update: v1.4.0 → v2.0.0
─────────────────────────────
✓ Enabling WiFi              (2s)
✓ Waiting for DNS            (4s)
✓ Downloading v2.0.0         (8s)
✓ Verifying checksums        (1s)
⠋ Flashing C6 firmware...    (12s)
```

Spinner + timer redraws current line via `\r` + `\033[K`. Completed steps get a checkmark and elapsed time, leaving a running history visible. After failure, the failed step gets `✗` and the script writes a longer error block below.

### Validation

- From HA, click Install on `update.panel_firmware`, watch the panel screen show the sequence.
- Verify WiFi turns off after success.
- Force a failure (e.g., point at an artifact with wrong sha256), verify rollback happens, WiFi stays on, HA shows failure.

---

## Versioning scheme

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

For the immediate path: cut V2 work as `v2.0.0-beta.1` → iterate as `v2.0.0-beta.N` → promote to `v2.0.0` when stable. Any V1 patches (unlikely but possible) cut from a separate branch as `v1.4.x`.

---

## File changes summary

### Created

| Path | Purpose |
|---|---|
| `hacs.json` | Repo-root HACS config: `zip_release: true`, points at integration zip artifact |
| `platform/integration/thread_panel/` | Integration source (moved from `custom_components/`) |
| `platform/integration/thread_panel/update.py` | `PanelUpdateEntity` |
| `platform/firmware/components/panel_platform/panel_ota_uart.c` | C6 UART OTA receiver |
| `platform/firmware/components/panel_platform/panel_version.h` | Generated at build time from `git describe` |
| `platform/bridge/panel_bridge/ota.py` | Pi-side firmware-over-UART sender |
| `platform/bridge/panel_bridge/cli/panel_flash.py` | Manual flash CLI |
| `platform/deploy/panel-update.sh` | Orchestration script |
| `platform/deploy/console-display.sh` | Helper: tty1 progress UI primitives (writeline, mark-done, etc.) |
| `docs/build_plan_v2.md` | This document |

### Modified

| Path | Change |
|---|---|
| `tools/cut-release.zsh` | Add interactive bump prompt (gum), firmware build, tarballing, zip, manifest.json, gh release create with --prerelease flag |
| `platform/deploy/install-pi.sh` | Switch from git-clone to release-artifact pull; add `fbcon=rotate:3` + console-setup; render systemd units pointing at `/opt/panel/current/` |
| `platform/deploy/panel-bridge.service` | `ExecStart=/opt/panel/current/bridge/...` |
| `platform/deploy/panel-ui.service` | Root at `/opt/panel/current/ui-dist/` |
| `platform/firmware/components/panel_platform/panel_app.c` | Wire ota_uart handler; publish state/version on connect |
| `panels/feeding_control/firmware/main/panel_app.c` | Subscribe to cmd/update; forward over UART |
| `README.md` | Document new install paths (Pi + HA box) from release artifacts |
| `CLAUDE.md` | Reference both build_plan docs; note V2 is active work |

### Removed (during Phase 1, with care)

| Path | Why |
|---|---|
| `custom_components/thread_panel/` | Moved to `platform/integration/thread_panel/` |
| `panels/feeding_control/ui/dist/` | Built artifacts now in releases, not git |
| (eventually) `tools/panel-ota` | Mac-side Thread-OTA tool, superseded — leave during Phase 1+2 as fallback, remove during Phase 4 once V2 path is proven on hardware |

---

## Resolved decisions (from planning conversation)

1. **Where does `cut-release` run?** Mac. CI is V3.
2. **Auto-install vs. manual?** Manual only. HA polls GitHub releases hourly, surfaces "update available" via the entity, user clicks Install. Scheduled auto-install removed from scope.
3. **Version retention on Pi.** Keep `current` + `previous-1`, prune older. `/opt/panel/versions/` cleanup runs at end of successful update.
4. **Repo-wide vs per-component versions.** Repo-wide. Per-component sha256 in manifest handles "only re-flash if changed."
5. **HACS publication.** Skipped — project is too hardware-specific to be useful as a default-store integration. HACS-as-custom-repo (user adds the repo URL) stays available.
6. **Update transport for C6.** UART at 921600 baud during transfer (~15s for ~1.5 MB). Thread-OTA stays in tree as fallback until V2 proven.
7. **Console display approach.** tty1 takeover with `fbcon=rotate:3` + `setfont ter-132n`, not a web UI overlay. Doesn't depend on the kiosk being healthy (which matters precisely when you're updating to fix it).
8. **Beta versioning scheme.** Standard semver prereleases (`-beta.N`), npm-style flat bump menu in cut-release, integration toggle for `Include prereleases`.

## Open questions (to answer during build)

- Healthcheck thresholds in `panel-update.sh` step 11. "Bridge active for 30s" is a starting point — may need tuning. Same for "C6 reconnect within N seconds after flash." Set conservative defaults, log actuals during test releases, tune from data.
- Concurrent-update protection. If `cmd/update` arrives while one is in flight, what happens? Probably: write a `/var/run/panel-update.pid` lockfile in step 1, refuse to start if it exists, publish `state/update_status: rejected, detail: in_progress`. Keep simple.
- `panel-update.sh` log retention. Each run should write a full log to `/var/log/panel-update/<timestamp>.log` for post-mortem. Retention policy TBD (keep last 10? last 30 days?). Easy to add later.
- Whether to include the bridge tarball *in* the bridge's own version directory (so the source-of-truth tarball is preserved on disk) or just unpack-and-discard. Probably preserve — useful for debugging "did I actually install what I think I installed."

---

# Backlog: additional V2 work (promoted from V1)

The items below were collected during V1 build under "V2 / Post-V1 follow-ups" + "Outstanding (V2)" in [build_plan_v1.md](build_plan_v1.md). They're grouped by theme as Steps 18–22 so each can be picked up, scoped, and tracked independently. Most are coarser than Step 17's phased plan — flesh out the detail when you start the step.

Several items have natural relationships with Step 17 (noted inline). A few from the original V1 list have been dropped or rolled into Step 17:

- ~~"GitHub Action / artifact-based deploy instead of full repo clone"~~ — promoted to Step 17 Phase 1.
- ~~"HACS distribution of `thread_panel` integration"~~ — explicit V2 non-goal (project is too hardware-specific to be useful as default-store integration; HACS-as-custom-repo stays available via Step 17's `hacs.json`).
- ~~"MQTT credentials in sdkconfig (plaintext)"~~ from Outstanding tech debt — consolidated into Step 20's NVS provisioning item; same root issue.

## Step 18 — Setup & deploy improvements

- **`install-pi.sh` full bootstrap from a fresh Pi OS Lite.** Today the script assumes the user has already cloned the repo, set up the bridge venv, and apt-installed cog. Fold all of that in so a brand-new Pi can be brought up with one command. While we're there, fold in the steps from earlier V1 build phases that still live as prose in [build_plan_v1.md](build_plan_v1.md): `dtoverlay=disable-bt` for PL011 on GPIO 14/15 (V1 step 4), serial-console disable, NetworkManager bring-up, and any other one-time setup. End state: image SD → boot → ssh in → run script → reboot → kiosk runs. Should be device-agnostic to whatever extent is possible. **Step 17 dependency:** Step 17 already replaces the git-pull install path with artifact pulls; this step extends that script to also handle first-boot system setup.
- **Kiosk-renderer choice via flag.** `install-pi.sh --cog` (Pi Zero 2 W, 512 MB) vs `install-pi.sh --cage` (Pi 4+, 1 GB+) so the same script works across hardware. Default to cog on detected ≤768 MB, cage on more. Either path apt-installs the right packages and renders the matching systemd unit. **Step 17 dependency:** depends on Step 17's install-pi.sh refactor; layer this on top.
- **Direnv + shell helper cleanup.** Several issues with the current `.envrc` / source aliases (interactive `panel-bridge`, `idf` activation, etc.) — paths, ordering, environment leaks. Audit and fix in one pass. (User knows the specifics; revisit when we get there.) Independent of Step 17.

## Step 19 — Architecture & abstraction

- **HA integration: replace pure-YAML manifest with a real config flow.** Today the integration's manifest lives in `panels/<id>/ha/manifest.yaml` and gets pasted into the config flow as text. Move to an interactive picker — list installed devices, let the user multi-select entities and per-entity attribute allowlists, store as proper `ConfigEntry.options`. YAML stays as a power-user import path but isn't the default. Independent of Step 17 (but coordinate so the new options shape is forward-compatible with whatever `update` entity options Step 17 adds).
- **Consistent device ↔ Pi ↔ UI/interface association.** Right now the link between a HA Device (per `panel_id` in the integration), a physical Pi (its hostname), and the served UI (hard-coded `panels/feeding_control/ui/dist/`) is implicit and split across three places. Unify under a single concept ("a panel = these three things linked together"). Probably surfaces as a `device/<hostname>.conf` (or per-Pi config in HA) that names: which product UI to serve, which `panel_id` this device claims, and which physical hardware variant (panel size, sensors present). Rolls up the older "device → product binding" item. **Step 17 dependency:** Step 17 puts the UI under `/opt/panel/current/ui-dist/` regardless of product — this association layer determines *which* product's UI gets installed there.
- **"Unconfigured panel" splash in `platform/ui-core`.** When a panel boots without a product UI configured (`panel-ui.service` serving an empty/missing dist/, or no panel selected), show a friendly splash with setup instructions instead of a directory listing or blank screen. The splash itself ships as part of ui-core so every panel inherits it for free. Couples with the device-association work above.
- **Repo reorg: tighter platform / product separation.** Likely outcome (subject to refinement): only the UI is genuinely product-specific. The current `panels/<id>/firmware/` is mostly platform code with a ~20-line `panel_app.c` shim — that shim could live in `platform/firmware/` driven by config. Same for `panels/<id>/ha/` (manifest only). End state: `panels/<id>/` contains a UI directory and a manifest file, nothing else. Couples with the device-association work above; tackle together. **Step 17 dependency:** Step 17 already moves the integration into `platform/integration/`; this is the firmware/manifest equivalent of that move.

## Step 20 — Multi-device / fleet

- **NVS-provisioned per-device MQTT credentials.** Currently every device built from this tree shares the credentials baked into `sdkconfig`. Fine for one device. Before scaling to a fleet, switch to a provisioning flow that writes per-device credentials to NVS at first boot (USB serial provisioning tool, BLE captive provisioning, or a Mac-side `panel-provision` CLI). Fix in tandem with the device-association work in Step 19 since both touch device identity. (Consolidates the V1 "Outstanding tech debt" item about plaintext sdkconfig credentials — same root issue, single fix.)

## Step 21 — Robustness

- **Tests & CI.** No automated tests anywhere right now. Most useful additions, in rough order: (1) bridge unit tests for the state cache + WS broadcast logic (pytest, minimal mocking); (2) integration tests that the HA `_handle_resync` actually republishes everything (HA test framework supports this); (3) UI component tests on the data-shape parsing in `useFeeder` (Vitest); (4) firmware build verification via GitHub Actions (no hardware in CI, just `idf.py build`); (5) end-to-end smoke test that a fresh Mac + Pi + C6 deploy yields a kiosk with data within N seconds. **Step 17 relationship:** Step 17 explicitly defers CI as a V3 question, but the test-writing piece (1–3) is independent and worthwhile in V2.
- **MQTT message fragmentation handling on the C6.** We currently rely on `buffer.size = 8 KB` being big enough for any single payload. esp-mqtt actually delivers oversized payloads as multiple `MQTT_EVENT_DATA` callbacks with `current_data_offset` / `total_data_len` set; our `forward_*` helpers just look at the first chunk. Real fix: accumulate fragments in `panel_app_on_data` until `data_len + offset == total_data_len`, then forward. Removes the buffer-tuning band-aid and handles arbitrarily large entity snapshots correctly. Independent of Step 17.
- **C6 UART rx state machine to ignore boot noise.** Companion to the bridge-side leading-`\n` fix. Currently `panel_uart.c::rx_task` accumulates everything between newlines; if Pi boot noise has no newlines, it sits in the buffer until the bridge's first newline-terminated write flushes it. Cleaner: only start accumulating after seeing `{`, drop bytes that don't fit a JSON-line pattern. Removes the bridge-side workaround. Independent of Step 17.
- **WPE bubblewrap sandbox proper fix.** `cog.service` currently sets `WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1` to bypass Debian's misconfigured bubblewrap. The real fix is `setcap -r /usr/bin/bwrap` (let bwrap fall back to unprivileged userns) plus a check in `install-pi.sh` to re-apply after apt updates of `bubblewrap` clobber the caps. Low priority — sandbox is mostly defense against malicious sites we don't load — but cleaner. Coordinate with Step 18's `install-pi.sh` overhaul so the setcap check lands in the same script.
- **Configurable presence/theme thresholds via HA, not `.env.production`.** Today the splash distance, theme switch points, etc. are baked into the bundle at build time. For tuning on-site without a rebuild, expose them as HA `number` entities the bridge subscribes to and the UI reads from `panel.entity()`. Single-device benefit: tune without rebuilding. Multi-device benefit: each Pi has its own settings synced through HA. Independent of Step 17.

## Step 22 — Hardware

- **Brightness control.** Waveshare 6.25" has no software-controllable backlight. If the hardware is swapped or a Wayland gamma overlay turns out to work, revisit and add a `number` entity the cog kiosk reads. Hardware-gated.
- **Thread mesh resilience monitoring.** V1 step 11's "Thread mesh flapping under load" was fixed by switching the C6 to MTD, but we have no ongoing visibility. Surface OpenThread mesh-error counters as a diagnostic sensor in HA so degradation shows up before it manifests as command latency. Independent of Step 17.

---

## Technical Debt

### Outstanding

(none yet — V2 work hasn't started)

### Resolved

(none yet)

## Lessons Learned

(empty — fill in during build)

## Proven Facts

(empty — fill in during build)
