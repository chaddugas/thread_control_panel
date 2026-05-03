[Build Plan V2](README.md) › Phase 1 — Security

# Phase 1 — Security ✅ CLOSED

The MQTT broker password is published in every `firmware.bin` release artifact and trivially extractable with `strings`. Phase 1 closes that hole, rotates the leaked credential, and tightens the surrounding authorization surface so a future leak has less reach.

Confirmed scope (no deferred items — every group is committed Phase 1 work).

## Group A: Move MQTT credentials out of firmware ✅ DONE

**Status (2026-05-01)**: Shipped in v2.0.0-beta.29. Validated end-to-end in production: strings test on local build (no `myvxan` substring), install-pi.sh prompt path, panel-flash C6 firmware delivery, periodic re-send delivered creds within 60s of fresh-NVS C6 boot, NVS persistence across power-cycle (C6 reconnected to MQTT in 5-15s with no bridge involvement), file-watcher rotation path (validates Group B). Validation surfaced 6 tech-debt items, all filed in [Robustness & correctness](phase3_themed.md#robustness--correctness).

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

1. **Local build (Mac)** — confirms creds are gone from the binary:
   ```bash
   cd panels/feeding_control/firmware && idf
   idf.py reconfigure                                          # purge orphaned CONFIG_MQTT_USERNAME/PASSWORD
   grep -E '^CONFIG_MQTT_(USERNAME|PASSWORD)' sdkconfig        # must return nothing
   idf.py build
   strings build/thread_panel_feeding_control.bin | grep -i myvxan  # must return nothing — security acceptance
   ```
2. **Cut beta.29** from the Mac. Release notes describe the migration step for existing Pis (re-run install-pi.sh from this release to seed `mqtt_creds.json`).
3. **HACS** update Thread Panel integration → restart HA.
4. **Run install-pi.sh from beta.29 on production Pi** (SSH in). Two gotchas apply: (a) the explicit-tag URL is required since `releases/latest` skips prereleases, AND the script's internal "latest" default does too; (b) the credentials prompt reads from stdin, which is consumed by curl when piped — so download the script first, then run it directly so stdin is the terminal:
   ```bash
   curl -sSL https://github.com/chaddugas/thread_control_panel/releases/download/v2.0.0-beta.29/install-pi.sh -o /tmp/install-pi.sh
   bash /tmp/install-pi.sh v2.0.0-beta.29
   ```
   The MQTT-creds prompt fires (the file doesn't exist on a pre-Group-A Pi), enter the current Mosquitto user/pass. install-pi.sh validates per the new rules (12–128 char password, 2-of-3 char classes, no `"`/`\`), writes `/opt/panel/mqtt_creds.json` at 0600, installs beta.29 bridge + UI, restarts services. The new bridge begins re-sending `panel_set_creds` over UART; the still-running OLD C6 firmware ignores the unknown envelope harmlessly. Chosen over a manual `tee`-pre-seed because it exercises the canonical install path including the validation rules.
5. **Flash the C6 via panel-flash directly** (at the time of Group A validation, the OTA-from-HA path was blocked by `panel-update.sh`'s same-version rejection — that bug was fixed in [Group C](#group-c-authorization-surface-tightening), so post-Group-C the OTA-from-HA path also works for this step). On the Pi:
   ```bash
   /opt/panel/current/bridge/.venv/bin/panel-flash
   ```
   Defaults to `/opt/panel/current/firmware.bin` + `ws://localhost:8765`, no args needed. Talks to the bridge over WS, drives the UART OTA at 921600 baud (~22s for ~1.5 MB), C6 self-validates on next boot. Within 60s of the C6 booting new firmware, the bridge's periodic re-send delivers `panel_set_creds`, C6 writes NVS + commits the partition + connects MQTT, publishes `state/version`. HA's update entity should flip `installed_version` to beta.29 once `state/version` lands. Once the panel-update.sh bug is fixed, this step reverts to "Trigger OTA from HA's update entity."
6. **Power-cycle test**: unplug + replug the panel. On cold boot, C6 reads NVS → has creds → connects MQTT immediately. Confirms NVS persistence across reboots.
7. **(Optional) In-place rotation smoke test**: `sudo touch /opt/panel/mqtt_creds.json` → bridge file-watcher fires within 5s → C6 receives `panel_set_creds` → no-ops on identical creds. Confirms the rotation path is wired up for Group B.

## Group B: Rotate credentials + scrub historical leakage ✅ DONE

**Status (2026-05-01)**: Both halves complete.

- ✅ Rotated MQTT user `mqtt_user` → `feeding-panel` with a new ~32-char password (stored in user's password manager). Pi `mqtt_creds.json` updated; Group A's file-watcher + `panel_set_creds` path delivered the new creds to the C6, which wrote NVS and reconnected with the new user. Old `mqtt_user` removed from broker after fresh-data flow confirmed (proximity values updating in HA in real time).
- ✅ Scrubbed `feeding_control-firmware-2.0.0-beta.<N>.bin` from every pre-beta.29 release (27 assets across beta.1 through beta.28, skipping beta.27 which never existed). beta.29's firmware.bin retained as the canonical clean build. Tags + other assets (UI tarballs, install-pi.sh, manifest.json, panel-bridge tarballs, thread_panel.zip, panel-deploy tarballs) stayed put.
- ✅ Audited `panel-bridge-*.tar.gz` for credential content — confirmed clean (only benign references to "passwordless sudo" comments and runtime WiFi-password handling). No deletion needed.

The rotation is what actually closes the hole. Asset deletion is hygiene — GitHub CDN may serve cached copies briefly; anyone who already pulled the old binaries still has them, but the leaked credential is now dead. Per [Proven Facts](notes.md#proven-facts), the broker isn't externally reachable anyway, so the original blast radius was bounded to LAN.

## Group C: Authorization surface tightening ✅ DONE

**Status (2026-05-02)**: Functional changes shipped in v2.0.0-beta.30; follow-up corrections (Pi-imager content-scan, attribution comment fix, update_status tail-race fix, README + cut-release install-command surfacing) land in v2.0.0-beta.31; install-lib.sh audit gap caught during a beta.30→beta.31 OTA + 13 missing sudoers rules added in v2.0.0-beta.32. Validated end-to-end on the production Pi: narrowed sudoers exercised through reboot button, screen toggle, wifi toggle, scan, connect, and a full same-version OTA round-trip; wide-open `NOPASSWD: ALL` drop-in confirmed gone (`sudo grep -rE 'NOPASSWD:[[:space:]]*ALL' /etc/sudoers /etc/sudoers.d/` returns nothing); wifi password typed, navigated away, never persisted (recorder DB clean of the test value, activity-panel quiet — the goal). The same-version OTA-rejection bug originally filed in [Robustness & correctness](phase3_themed.md#robustness--correctness) was fixed as part of this work and removed from that list.

**Lesson learned**: the original C1 audit covered `panel_bridge/controls/` and `panel-update.sh` but missed `install-lib.sh`, which is sourced by panel-update.sh and contains its own sudo invocations in `lib_render_units` (writing systemd unit files via `sudo tee`, `sudo chmod`, `sudo rm`, plus `sudo systemctl daemon-reload` after). A first-time OTA across a real version bump (rather than the same-version test) hit `rendering_units` and prompted for password on the screen with no NOPASSWD coverage; the OTA failed at that phase. Fixed by adding 13 explicit per-unit/per-target rules to the sudoers heredoc. Per-command rules (rather than wildcards like `/etc/systemd/system/*`) keep the surface tight: only the three known panel units can be written through this path.

- ✅ **C1 — Narrow `/etc/sudoers.d/panel-bridge`**. 13 wildcard rules → 19 narrower rules grouped by purpose. `nmcli *` → 5 specific subcommands (`radio wifi on/off` + `connection delete/up/add type wifi ifname wlan0 *` with the interface anchored). `systemctl is-active *` → 2 specific services. `chvt *`, `setfont *`, `setterm *` → exact-arg matches. `nmcli monitor` and `nmcli device wifi list` dropped from the rule list — both are invoked without sudo in current code.
- ✅ **C2 — Remove wide-open `NOPASSWD: ALL` drop-ins**. install-pi.sh scrubs any `/etc/sudoers.d/*` file containing `NOPASSWD: ALL` (anywhere on the line, anchored to end-of-line so per-command rules in our own panel-bridge file aren't matched). Detection is content-based rather than filename-based since the originating tooling varies (manual setup, Pi-imager defaults, prior rewrites). Done at the end of install-pi.sh so all earlier sudo-needing setup runs without prompting; subsequent sudo prompts for password as normal Linux behavior.
- ✅ **C3 — Wifi password kept out of recorder**. **Plan changed mid-flight**: the original V2 plan said "ship a recorder-exclude rule with the integration", but HA's recorder filter is built once at startup from `configuration.yaml` and isn't extensible from an integration (verified via HA developer docs + recorder docs + community feature-request threads — no programmatic API exists). Storing-outside-state is the only way to actually keep the value out of the recorder DB. `PanelWifiPasswordText.async_set_value` now stashes the typed value in `hass.data[DOMAIN][DATA_ENTITIES][panel_id][VALUE_REGISTRY_KEY]` and never calls `async_write_ha_state` — state stays empty for the entity's lifetime. `PanelWifiConnectButton` reads from `hass.data` instead of `hass.states.get(text_id).state`. Trade-off: password doesn't survive HA frontend navigation (typed-then-navigate-away clears it), but the typical flow is type-and-immediately-press-Connect, so this matches existing UX.
- ✅ **Bonus — same-version OTA fix**. Closes the bug originally filed in [Robustness & correctness](phase3_themed.md#robustness--correctness): `panel-update.sh` refused same-version OTAs wholesale, even when only the C6 needed flashing. Now skips the destructive Pi-side phases (download/extract/venv/symlink-swap/restart) when version matches current via a `SKIP_PI_INSTALL` flag, but still runs the C6 flash unconditionally. Validated via OTA-from-HA when Pi was already on the target version: `pi_already_current` → `flashing_c6` → `c6_verified` → `done`.

## Group D: OTA tamper-resistance (firmware signing) ✅ DONE

**Status (2026-05-02)**: Shipped in v2.0.0-beta.33. Validated end-to-end on the production Pi: install-pi.sh from beta.33 apt-installed minisign, downloaded `firmware-signing.pub` + the `<firmware>.bin.minisig` sibling, ran `minisign -V` against each firmware bin successfully; same path then exercised through panel-update.sh's OTA flow (lib_download_artifacts is the shared verification entry point). beta.33's release initially missed the signature artifacts due to the [cut-release sourced-function staleness bug](phase3_themed.md#developer-ergonomics) — recovered by manually signing the existing `firmware.bin` locally and `gh release upload`-ing the `.minisig` + `.pub` directly to beta.33 (same shape as cut-release would have produced).

### Implementation summary

- **Signing tool**: minisign (ed25519). `brew install minisign` on the Mac, `apt install minisign` on the Pi (added to install-pi.sh's bootstrap).
- **Signing key**: plaintext at `~/.config/thread_control_panel/firmware-signing.key` (mode 0600), keygen with `minisign -G -W` so no passphrase prompt at every cut-release. Override path via `PANEL_SIGNING_KEY` env var.
- **Public key**: committed at [`platform/deploy/firmware-signing.pub`](../../platform/deploy/firmware-signing.pub) (key id `33DEA140A371B656`); cut-release ships it as a top-level loose release artifact alongside `install-pi.sh`.
- **Signature artifact**: `<firmware>.bin.minisig` — sibling of each panel's firmware bin. Convention-named, not listed in `manifest.json` (lib_download_artifacts derives the URL by sibling lookup).
- **Trust model**: pubkey ships with each release as the top-level `firmware-signing.pub` and is downloaded fresh by lib_download_artifacts each time. Protects against transit corruption / CDN tampering — sha256 already covers integrity, signing adds authenticity (the binary came from someone with the signing key, not just from someone who can recompute sha256s). Doesn't protect against a release-write-access compromise (attacker swapping pubkey + binary together) — that's the future "pinned trust anchor at first install" hardening step, deferred per the user's threat model (personal home use, broker not externally reachable).
- **C6 hardware secure boot**: deferred to V3. ESP32-C6 secure boot v2 burns keys to one-time-programmable eFuses — irreversible, fragile to set up, and the bridge-verified path already covers the realistic threat model. Revisit if/when the project ever ships to other people.

### Key generation (one-time on the Mac)

```bash
brew install minisign
mkdir -p ~/.config/thread_control_panel
minisign -G -W \
  -p ~/.config/thread_control_panel/firmware-signing.pub \
  -s ~/.config/thread_control_panel/firmware-signing.key
chmod 600 ~/.config/thread_control_panel/firmware-signing.key
cp ~/.config/thread_control_panel/firmware-signing.pub \
   "$(git rev-parse --show-toplevel)/platform/deploy/firmware-signing.pub"
git add platform/deploy/firmware-signing.pub && git commit
```

`-W` skips passphrase encryption on the secret key. Back up the secret key to your password manager — losing it means rotation.

### Rotation procedure

If the signing key is suspected compromised, or if you just want to roll keys periodically:

1. Generate a new keypair (see above) — **do not** overwrite the old `~/.config/thread_control_panel/firmware-signing.key` until step 4 is done; you'll need it to verify any in-flight artifacts mid-rollout.
2. Replace `platform/deploy/firmware-signing.pub` with the new public key, commit, push.
3. Cut a new release (`cut-release`) — the new release ships the new pubkey + a firmware.bin signed with the new private key.
4. Run `install-pi.sh` from the new release on each Pi — downloads the new pubkey, verifies the new firmware.bin against it. Successful install means the rotation is live on that Pi.
5. Rotate the old `~/.config/.../firmware-signing.key` to a backup location (or destroy if the rotation was due to compromise).

Subsequent OTAs verify against whatever pubkey is in the current release — no per-Pi rotation step needed.

### Recovery if the private key is lost

There's no recovery path — without the private key, no new firmware can be signed, which means no OTAs can be issued. To get out of this state:

1. Generate a new keypair (above).
2. Cut a release with the new pubkey baked in. **This release will not be installable via OTA on any existing Pi** (their lib_download_artifacts will fail to verify the new firmware against the old pubkey shipped in their last installed release's deploy state).
3. On each Pi, manually run `install-pi.sh` from the new release. This downloads the new pubkey directly and bootstraps fresh — no verification chain back to the lost key needed.
4. Future OTAs work normally from that point.

The recovery cost is one manual `install-pi.sh` run per Pi, which is acceptable for a personal-scale fleet. (Future hardening: pinned-on-first-install trust anchor would make this strictly impossible without physical access; for now, the trust model deliberately allows this recovery path.)
