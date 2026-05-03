[Build Plan V2](README.md) › Phase 3+ — Themed groups

# Phase 3+ — Themed groups

Named groups, no strict ordering. Pick whichever fits the moment when each becomes the right time.

## Quality of life (small fixes & polish)

- Bump OTA `waiting_for_connection` timeout to 120s (real-world observation of 63s connection-up suggests current 60s is too tight).
- Refine `PHASE_PERCENTAGES` based on real OTA timing data (creating_venv currently dominates; bar jumps 0→60% then hangs).
- Switch cut-release notes editor from vim to nano (vim `:q` cancels the release while still incrementing the version counter).
- Investigate GitHub release sort order weirdness on the releases page + HACS picker (current order: beta.28, beta.26, beta.9-4, beta.25, beta.24, ... — neither chronological nor alphabetical).
- Persistent journald on existing panels — document the manual one-liner in the README, or wire into install-pi.sh hardening.
- Suppress the `LIBARCHIVE.xattr.com.apple.provenance` tar warnings during install-pi.sh / panel-update.sh extract phases. They come from macOS's BSD tar adding extended-attribute headers that GNU tar on the Pi doesn't recognize; extracts succeed cleanly but the output gets noisy. Two fix options on the cut-release side: (a) set `COPYFILE_DISABLE=1` in the env before invoking `tar` (tells macOS to skip extended attributes — simplest, no new tooling); (b) `brew install gnu-tar` and call `gtar` instead of system `tar` (cross-platform-clean but adds a dependency). Lean: option (a).

## Robustness & correctness

- C6 `panel_state` envelope schema split into event vs state types — closes the retain-everything gap that beta.22 papered over.
- MQTT message fragmentation handling on the C6 — multi-callback assembly removes the 8 KB buffer band-aid.
- C6 UART rx state machine ignoring boot noise — start accumulating after seeing `{`, drop bytes that don't fit a JSON-line pattern.
- Slow post-power-cycle data backfill — needs landmark instrumentation before it's fixable. Add timestamped log lines at C6 thread-up, mqtt-connected, first-state-published; bridge ws-up, first-mqtt-msg-received; UI mount, first-entity-render.
- Bridge's `_current_ssid()` (`platform/bridge/panel_bridge/controls/wifi_manage.py`) returns the NM **connection profile name**, not the actual 802.11 SSID. The two match only when the profile was created via the bridge's `wifi_connect` path (which sets `con-name = ssid`); profiles created from a direct `nmcli connection add` show their profile name in HA. Symptom caught during Group A validation: HA's wifi_ssid sensor showed `iot` while `iwgetid -r` on the Pi reported `The Matrix`. Bug is isolated to `_current_ssid()` — the `wifi_ssids` scan list correctly reports the true SSID + `in_use: true` from `nmcli device wifi list` (confirmed in same-session bridge journal). Fix: after reading the active connection name, query `nmcli -t -f 802-11-wireless.ssid connection show <name>` for the actual SSID, fall back to the profile name only on error.
- `install-pi.sh`'s "latest" version resolution skips prereleases. Same shape as the bug `update.py` had pre-beta.20 — the script's `TARGET_VERSION="${1:-latest}"` default hits `https://api.github.com/repos/$REPO/releases/latest`, which excludes prereleases. Caught during Group A validation when running install-pi.sh from beta.29 without an explicit version arg fell back to v1.4.0 and 404'd on the manifest download. Fix: mirror update.py's approach (sort `/releases` by `created_at` desc, take the first), with an optional flag to filter to non-prereleases for users who explicitly want stable. Documented workaround: pass the version as a positional arg via `bash -s -- <version>`.
- `install-pi.sh`'s MQTT-credentials prompt fails silently when the script is run via `curl | bash` — stdin is the script body (already consumed), so every `read` call returns empty and the validation loop spins forever printing "passwords don't match" / "username can't be empty". Caught during Group A validation. Fix: redirect each `read` from `/dev/tty` (e.g. `read -r -p "..." mqtt_user </dev/tty`) so prompts always come from the user's terminal regardless of stdin source. Documented workaround: download the script first (`curl -o /tmp/install-pi.sh`) and run it directly with `bash /tmp/install-pi.sh <version>`.
- Each Install click in HA emits `cmd/update` twice within ~200ms (observed in bridge journal during Group A validation). The bridge spawns panel-update.sh twice as a result; the second spawn would hit the planned PID-lockfile guard ([Open questions](reference.md#open-questions)) once that's wired up, but the upstream double-publish should still be tracked down. Likely candidates: the integration's `async_install` firing twice, or the C6 forwarding the same MQTT message twice. Track the publish at the broker (`mosquitto_sub -t 'thread_panel/+/cmd/update'`) during a single click to localize.
- `panel_bridge.mqtt_creds` doesn't send at startup as documented — observed gap of ~5 minutes between bridge-fully-up (`Sent panel_cmd resync to C6` log line) and first `mqtt_creds_sent` event after a power-cycle. The Group A design intent ([Group A](phase1_security.md#group-a-move-mqtt-credentials-out-of-firmware)) was "sends at startup AND on mtime change AND every 60s". Either the implementation in `panel_bridge/mqtt_creds.py` is skipping the startup send (and only firing after the first interval/file-event), or it's blocking on something at startup. Make sure first send fires within a few seconds of bridge startup so a freshly-flashed C6 doesn't have to wait through the full interval before getting provisioned. Side benefit: this would also strengthen step 5's "OTA-flash works without manual recovery" guarantee — currently the periodic 60s tick is doing the heavy lifting, but a startup send would catch the C6 even faster.

## HA integration UX features

- Replace YAML-paste manifest with a real config flow (interactive entity picker, multi-select, attribute allowlists).
- "Unconfigured panel" splash in `platform/ui-core` (friendly setup-instructions screen instead of blank/directory listing).
- Tunable behavioral values surfaced as HA `number` entities — see [A.2.g](phase2_groupA_multipanel.md#a2g--tunable-values-surface-as-ha-entities-not-paneltoml) for the mechanism. Initial set ships in A.2 itself (lidar_publish_hz, ambient_publish_period_s, ambient_mv_ceiling); Phase 3+ work adds the behavioral thresholds: presence/proximity threshold (cm), theme dim/wake thresholds (% ambient), replaces `.env.production` constants.
- WiFi UX: known-networks select + disable password field for known networks (don't require a password on already-saved profiles).

## Pi-side observability + correctness

- Pi clock drift fix: have the C6 broadcast time-of-day over MQTT; UI reads from there instead of local `Date()`.
- Ambient light sensor default calibration — once `ambient_mv_ceiling` lands as an HA tunable per [A.2.g](phase2_groupA_multipanel.md#a2g--tunable-values-surface-as-ha-entities-not-paneltoml), validate the 500 mV default in real rooms and consider lowering the C6's per-tick filter threshold so smaller delta values from low-light environments still propagate.

## Release pipeline maturity

- Per-component release cadence: sha-skipping approach where cut-release only re-uploads components whose content changed, and `update.py` compares the integration's sha across releases.
- Tag-based filtering improvements that fall out of the GitHub sort fix.

## Hardware affordances (mostly opportunistic)

- Software brightness control (hardware-gated on a swappable display).
- Thread mesh resilience monitoring (OpenThread mesh-error counters as HA diagnostic sensor).
- Cold-start LCD streakiness investigation (thermal test, PSU rail scope).

## Developer ergonomics

- `install-pi.sh` full bootstrap from fresh Pi OS Lite (folds in `dtoverlay=disable-bt`, NetworkManager, console-setup, installing any dependencies, all the V1-step prose).
- Kiosk-renderer choice via flag (`--cog` vs `--cage`).
- WPE bubblewrap sandbox proper fix (currently bypassed via `WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1`).
- Direnv + shell helper cleanup; cut-release sourced-function staleness.
- ~~`cut-release --rollback` flag: `gh release list --limit 5` → gum chooser → `gh release delete <tag> --yes` (release page + assets removed; tag and commits stay so a re-cut at the same tag is possible). Useful when iterating no-op betas (e.g. for the spawn-at-request-time gotcha) without polluting the releases page. ~30–60 lines of bash.~~ ✅ DONE (2026-05-03). Shipped as `_cr_rollback` helper + `--rollback` subcommand dispatch in `tools/cut-release`. Multi-select via `gum choose --no-limit`, gum-confirm before destructive action, releases listed newest-first with `(prerelease|stable, YYYY-MM-DD)` annotations.
- Split `docs/build_plan_v1.md` into a per-section folder structure matching `docs/build_plan_v2/` (README + breadcrumbs + per-topic files like overview / hardware / mqtt_topics / uart_protocol / c6_firmware_state / build_order / promoted_to_v2 / notes). Pure mechanical reorganization — no content changes. Benefits: easier to reference individual sections, smaller context window when an agent only needs one topic.

## Multi-device support (triggered by panel #2 actually existing)

- Per-device MQTT credentials + per-device Mosquitto ACLs. install-pi.sh's prompt grows a panel_id input and generates a random per-device password if not supplied. Mosquitto ACL grants each per-device user only `thread_panel/<panel_id>/*`.
- Consistent device ↔ Pi ↔ UI association layer (probably a `device/<hostname>.conf` linking panel_id, hardware variant, served UI).
