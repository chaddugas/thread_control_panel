# Completed work (historical reference)

The following phases shipped during V2 active development. Their detailed plans are kept here for archaeology — current state of each is the source of truth.

## Step 17 Phase 1 — Repo restructure + artifact releases ✅ DONE

**No behavior change on the Pi yet — just changes how artifacts are produced and where source lives.**

### Repo moves

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

### `cut-release` extensions

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

### Off-main release commit

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

### Pi install path

Update `install-pi.sh` to switch from git-clone to release-artifact pull:

```bash
# fetch the latest release manifest (or a specific version if --version given)
curl -L $(gh release view --json assets -q '.assets[] | select(.name=="manifest.json") | .url') -o /tmp/manifest.json

# for each component, download artifact, verify sha256, unpack into /opt/panel/versions/<version>/
# atomic symlink swap to /opt/panel/current
# render systemd units pointing at /opt/panel/current/*
# restart services
```

### HA-box install

One-liner, documented in README:

```bash
curl -L "$(gh release view --json assets -q '.assets[] | select(.name|test("^thread_panel.*zip$")) | .url')" -o /tmp/tp.zip \
  && rm -rf /config/custom_components/thread_panel \
  && mkdir -p /config/custom_components/thread_panel \
  && unzip -o /tmp/tp.zip -d /config/custom_components/thread_panel/
```

The zip ships with files at its root (no inner `thread_panel/` wrapper), matching what HACS itself extracts into `<config>/custom_components/<domain>/`. The pre-clean (`rm -rf` + `mkdir -p`) ensures stale files from a previous install don't linger. Restart HA after. Once HACS-as-custom-repo is set up, this becomes "click update in HACS."

---

## Step 17 Phase 2 — C6 UART OTA receiver ✅ DONE

**No new hardware. Pi can flash C6 manually via a CLI; HA integration unchanged from Phase 1.**

### Wire protocol

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
- `panel_app.c` wires the OTA dispatcher (handled before the ha_availability gate so OTA works during HA outages), publishes `state/version` retained on each MQTT connect, and gates every UART forward through `forward_to_pi_uart()` which drops sends while OTA is active. `sensors_publish_task` early-skips its body during OTA so it doesn't contend for CPU or spam the monitor.
- `mbedtls` added to `panel_platform/CMakeLists.txt` PRIV_REQUIRES for sha256.

**Hardening discovered during chunk 2b on-device testing:**

- `panel_uart`'s RX ring + chunk size: previously 4 KB ring + 256-byte reads. At 921600 baud (~92 KB/s) `rx_task` couldn't sweep the ESP-IDF UART driver's ring fast enough — a single 4 KB OTA chunk arrived in ~44 ms but each rx_task wakeup drained only 256 bytes, so the ring filled and the driver dropped bytes silently before they ever reached our stream buffer. Bumped to 16 KB ring + 4 KB chunks (8 KB task stack to hold them).
- `panel_ota_uart` stream buffer bumped from 16 KB → 64 KB to absorb worst-case `esp_ota_write` stalls (sector erase + write spikes to 100+ ms). Allocated only during the OTA window, freed on completion; 64 KB is fine on a C6 with 512 KB SRAM.
- `panel_net_pause()` / `panel_net_resume()` (new public API on `panel_net`): `esp_mqtt_client_stop` / `start`. Called from `panel_ota_uart_handle_begin` and `cleanup_and_release` respectively. esp-mqtt's TLS-handshake reconnect attempts directly competed with the OTA stream for Thread bandwidth + CPU.
- `panel_lidar_pause()` / `panel_lidar_resume()` (new public API on `panel_lidar`): `vTaskSuspend` + `uart_disable_rx_intr` (and reverse on resume, with `uart_flush_input` to drain stale bytes before unmasking). The lidar's per-byte UART0 reads (~900 B/s) generated interrupt traffic that contributed to UART1 RX latency. Same call sites as `panel_net_pause`.
- `panel_uart_set_baud` now no-ops when already at the target baud, suppressing duplicate "UART baud → X" log entries from the redundant `cleanup_and_release` call after the explicit set in `ota_task`.

### Pi additions (`platform/bridge/`)

- `panel_bridge/ota.py` — `run_ota(uart, broadcast, bin_path)` reads the bin, computes sha256, drives the wire protocol via an `OtaSession` from `uart_link`. Emits `ota_status` and `ota_progress` envelopes via the broadcast hook so connected clients (and Phase 3's HA `update.panel_firmware`) can show progress.
- `panel_bridge/uart_link.py` extended:
  - `ota_session()` async context manager — routes incoming `ota_*` messages into a dedicated queue (other types keep flowing through the normal handler so UI clients still see sensors / state). Idempotent guard prevents concurrent OTA sessions.
  - `OtaSession.recv_json(expected_type, timeout)` — async wait-for-typed-message.
  - `write_raw(bytes)` and `set_baud(int)` — primitives the OTA driver needs; not exposed beyond the session.
- `panel_bridge/__main__.py` dispatches `{"type":"ota_request","path":"…"}` from any WS client by spawning `run_ota` as a detached task. The bridge reads the bin from disk — the binary doesn't traverse WS.
- `panel_bridge/cli/panel_flash.py` + `pyproject.toml` console script — `panel-flash [path]` connects to the bridge, sends `ota_request`, prints status + progress until complete/failed. Defaults to `/opt/panel/current/firmware.bin` and `ws://localhost:8765`.

---

## Step 17 Phase 3 — HA-orchestrated update flow ✅ DONE

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
| `thread_panel/<id>/state/wifi_state` | Pi → C6 → MQTT | yes | `{"value":"connected"}` (added in Step 17b) |

### Pi orchestration (chunk 3a)

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

### Console update display (chunk 3a)

Added to `install-pi.sh`'s bootstrap-only setup phase, idempotent:

- Append `fbcon=rotate:3` to `/boot/firmware/cmdline.txt` if not already present — rotates the kernel framebuffer console independently of the KMS display driver.
- `apt install console-setup` if not already installed — pulls in Terminus fonts including `Lat15-TerminusBold32x16` (~32px tall, double-wide, legible on the small panel from across the room).
- Writes `/etc/sudoers.d/panel-bridge` with the entries panel-update.sh needs.

`panel-update.sh` uses `sudo setfont Lat15-TerminusBold32x16` at the start. The font reverts on the next sway start (cog regains the framebuffer).

### Repo identity

Avoids hardcoded `chaddugas/thread_control_panel` strings in source. cut-release substitutes `__REPO__` placeholder at release-build time using `git remote get-url origin`. Touched at substitution time:

- `platform/deploy/install-pi.sh` — loose top-level artifact
- `platform/deploy/panel-update.sh` — in deploy tarball
- `platform/integration/thread_panel/update.py`

For local testing without cut-release, both scripts honor `REPO=foo/bar` env var override.

### Phase 3a validation result

Full HA-triggered OTA round-trip (cmd/update → script → C6 reboot into new firmware → state/version reports new version → no manual intervention) **verified end-to-end** through v2.0.0-beta.11 with the panel screen showing live phase status the entire time. Two originally-blocking bugs (success-path `esp_restart()` blocked by fresh esp-mqtt TLS handshake, and `/dev/tty1` permissions reverting after `cog stop`) were fixed and validated by real OTAs.

### Phase 3b validation result

`PanelUpdateEntity` shipped through betas 13–25 with the following blocking issues all resolved:

1. ✅ FIXED in beta.18 — OptionsFlow ordering bug. Replaced manual reload with `entry.add_update_listener(_async_reload_on_change)` so the framework triggers reload on options changes.
2. HACS state caching across `content_in_root` flips — HACS bug; workaround is delete + re-add the custom repo.
3. ✅ FIXED in beta.19 — Doubled-path `custom_components/thread_panel/thread_panel/`. `git reset --hard` doesn't remove now-untracked empty dirs; added `rm -rf custom_components` pre-clean before the cp.
4. ✅ FIXED in beta.19 — HACS doesn't substitute `{version}` in hacs.json's filename. Filename is now static `thread_panel.zip`.
5. ✅ FIXED in beta.20 — Most-recent release wasn't actually most-recent. GitHub's `/releases` endpoint sorts by tag name (lex desc), not chronological. update.py now sorts by `created_at` itself before picking.
6. ✅ FIXED in beta.21 — "Unknown error" alert on the entity panel. Cause: `RELEASE_NOTES` feature declared without overriding `async_release_notes`. Override added.
7. ✅ FIXED in beta.22 — `update_percentage` not rendering progress bar. Added `UpdateEntityFeature.PROGRESS` + `PHASE_PERCENTAGES` map driven from `state/update_status`.
8. ✅ FIXED in beta.22 — Ghost installs from retained `state/update_status` at HA startup. Cause: panel_app.c publishes all panel_state envelopes with retain=1; on HA restart the broker replays the last terminal phase. Fix: `_on_update_status_message` ignores retained messages. Architectural debt logged: firmware should distinguish event-stream vs state topics — captured in [Robustness & correctness](phase3_themed.md#robustness--correctness) for later.
9. ✅ FIXED in beta.23-25 — Various OTA polish items: post-`done` version-match hold (in_progress stays True until `state/version` reports the target); flip `in_progress=True` before awaiting MQTT publish (button disables immediately on click); aiohttp `ClientTimeout` typing fix.

---

## Step 17b — WiFi state surface and observability ✅ DONE

Sibling to Step 17. Promoted out of backlog mid-V2 because (a) the OTA flow's `enabling_wifi → waiting_for_dns` step is one of the slow phases users see and we don't have visibility into where the time goes, and (b) the bridge's WiFi entity surface was unreliable enough that observed state could lie ("connected to main network" while SSH times out, stays "connected" minutes after toggling off, etc.).

### Motivation (observed 2026-04-30)

Symptoms that drove this step:

- Network entity reported "connected to main network" while SSH timed out — entity claimed connectivity that didn't exist at IP layer.
- Toggle WiFi switch OFF → entity stayed at "main network" for several minutes before flipping to "Unknown".
- Toggle WiFi switch ON → 4+ minutes later, switch entity still reported off, scan-for-networks button produced no visible networks.
- `wifi_error` entity has been at "Unknown" since added — never reported a real value.
- Network select entity shows last-user-selected network, not currently-connected SSID.
- OTA's `enabling_wifi → waiting_for_dns` lumps connection-up time (scan + auth + DHCP, ~50-60s) into the DNS-resolution phase, so the user can't tell what's actually slow.
- Pi journals are tmpfs by default; reboots and power cycles lose all bridge logs from the prior boot, making post-mortem debugging hard.

### Plan (commit-by-commit) — all DONE

**~~Commit A — Persistent journals + structured-event logger helper.~~** ✅ DONE. Configures `Storage=persistent` in `journald.conf` via `install-pi.sh` (creates `/var/log/journal/`, sets retention caps, restarts journald). Adds `panel_bridge/events.py` with `log_event(logger, name, **fields)` emitting `event=<name> k=v` lines greppable via `journalctl --grep`. Zero new dependencies — traded clean structured fields for greppability.

**~~Commit B — `nmcli` timeouts.~~** ✅ DONE. New `controls/nmcli_util.py` centralizes subprocess execution that previously lived inline in wifi.py + privately in wifi_manage.py; default 30s `asyncio.wait_for` ceiling on every call. On timeout, kills the subprocess, emits `nmcli_timeout` structured event, and returns rc=124 (GNU `timeout` convention) so callers handle it as a normal failure. Verified `nmcli_timeout` count = 0 in steady-state validation.

**~~Commit C — Live connection state + on-toggle full refresh.~~** ✅ DONE. `_current_ssid` now queries `nmcli -t -f GENERAL.STATE,GENERAL.CONNECTION device show wlan0` and only returns a name when GENERAL.STATE starts with "100" (NM's `ACTIVATED`). `apply_wifi_enabled` calls a new public `wifi_manage.refresh_state(bridge)` after toggling, so SSID + scan + error all update immediately rather than waiting for the next periodic tick.

**~~Commit D — Event-driven updates via `nmcli monitor` + `wifi_state` enum.~~** ✅ DONE. New `controls/wifi_state.py` runs `nmcli monitor` as a long-lived background task (each line is a generic edge trigger to re-read state); publishes a single `state/wifi_state` topic carrying one of disabled/disconnected/connecting/connected/error. Reconcile loop at 60s is the safety net.

**~~Commit E — Split `enabling_wifi → waiting_for_connection → waiting_for_dns` in panel-update.sh.~~** ✅ DONE. New `waiting_for_connection` phase polls `nmcli -t -f DEVICE,STATE device status` for `wlan0:connected` (60s timeout); `waiting_for_dns` is now a tight 10s DNS-only check post-connection. Real-world observation: NM connection-up can take ~63s on this panel — bumping to 120s captured in [Quality of life](phase3_themed.md#quality-of-life-small-fixes--polish).

**~~Commit F — Tighten periodic loop to 10s.~~** ✅ DONE. `wifi_manage.SCAN_INTERVAL_S` 30s → 10s. Safe to tighten now that timeouts protect against hangs and event-driven updates carry the live state path.

**~~Commit G — HA integration entity polish for "Disconnected" surface.~~** ✅ DONE. New `PanelWifiStateSensor` (SensorDeviceClass.ENUM, options Disabled/Disconnected/Connecting/Connected/Error) subscribes to `state/wifi_state`; `PanelWifiSsidSensor` shows "Disconnected" instead of None when SSID is empty; `PanelWifiErrorSensor` shows "No error" instead of None when empty.

### Success criteria (validated through v2.0.0-beta.25–28 — initial cut + a series of no-op cuts to exercise the new panel-update.sh on a second OTA, per the spawn-at-request-time gotcha)

1. ✅ WiFi switch entity flips state within ~1s of any nmcli-side change. Journal shows `wifi_state_change` events arriving sub-second after `wifi_action`.
2. ✅ SSID entity reflects actual connection state — toggling off transitions `connected → disabled` within 200ms in the journal.
3. ✅ `wifi_state` enum queryable in HA, walks through Disabled → Disconnected → Connecting → Connected on toggle.
4. ✅ Entities surface "Disconnected"/"No error" not "Unknown" when WiFi is disabled.
5. ✅ OTA's `waiting_for_connection` phase visible in HA's progress bar (validated via no-op beta cut + second OTA per the spawn-at-request-time gotcha).
6. ✅ Persistent journals landing on disk (`/var/log/journal/<machine-id>/system.journal`).
7. ✅ Structured WiFi events flow as expected: `journalctl --grep 'event='` shows `wifi_action` + `wifi_state_change` lines with the source module preserved, fields unambiguous.
