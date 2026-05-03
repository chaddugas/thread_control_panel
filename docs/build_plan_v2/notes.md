# Notes — Lessons Learned, Proven Facts, Technical Debt

Cross-cutting accumulators. Add to these as work happens; don't tie to a specific phase.

## Lessons Learned

- **`esp_restart()` runs registered shutdown handlers, and a fresh esp-mqtt TLS handshake will block them.** During chunk 3a's OTA path, the success-path `cleanup_and_release()` was calling `panel_net_resume()` → `esp_mqtt_client_start()` right before `esp_restart()`. The shutdown handlers registered by `esp_mqtt_client_start` blocked `esp_restart()` while the brand-new TLS handshake was in flight. Symptom: `esp_ota_set_boot_partition()` succeeded but the chip kept running on the old firmware indefinitely. **Rule for any "we're about to reboot" path:** don't bring services back up; the chip is about to wipe RAM anyway. Skip the resume, send the result envelope, brief delay for UART drain, `esp_restart()`. Failure paths still need `cleanup_and_release` to keep the chip running.

- **Bash with `set -u` (no `set -e`) silently continues past `exec >` redirect failure.** Verified directly: `bash -c 'set -u; exec > /etc/shadow 2>&1; echo after'` exits 0 with `after` going to original stdout. If that original stdout is DEVNULL (as it is for any service spawned by systemd-managed bridge with `stdout=DEVNULL`), every subsequent echo vanishes. **Rule:** any `exec > <file>` in a script that may run unattended needs a `[ -t 1 ]` (or equivalent) check after, with a fallback that surfaces the failure somewhere durable. Otherwise the failure mode is invisible.

- **`/dev/tty1` ownership reverts to `root:tty` mode 600 the moment cog/sway with `PAMName=login` stops.** Adding the install user to the `tty` group does NOT help — mode 600 means group has no permissions either. The fix on a service-spawned (non-tty) script that wants to write to /dev/tty1 is `sudo chown $USER /dev/tty1` between `chvt 1` and the `exec` redirect. Don't get pulled down rabbit holes about screen blanking, framebuffer rotation, or VT disallocation when the symptom is "nothing on screen": test the permissions first.

- **Bridge spawns `/opt/panel/current/deploy/panel-update.sh` at request time, which is the OLD version's script — the symlink swap to the new version happens partway through.** Practical implication: any change to `panel-update.sh` only takes effect on the OTA *after* the one that installs it. To validate a fix to `panel-update.sh`, you need two OTAs: cut N → trigger OTA, then cut N+1 → trigger OTA. The first one installs the fix, the second one runs it. C6-firmware fixes don't have this delay because the C6 is already running the firmware that handles the post-flash reboot.

- **Commit subject scope prefixes should be unambiguous in any rendering context.** Commits prefixed `update entity:` were displayed as bullet points inside HA's update entity dialog (auto-generated release notes), where they read as if HA was announcing something about the entity itself. Use file/class names (`PanelUpdateEntity:`, `update.py:`, `panel_app.c:`) over loose noun phrases for any future scope prefix.

- **Don't gitignore paths that `tools/cut-release` `git add`s.** The off-main HACS-layout commit does `git add custom_components/` to stage the integration mirror; if that path is gitignored, `git add` silently drops everything, the next `git commit` fails with "nothing to commit", and cut-release bails after the version-bump has already landed on main. Caught when an attempt to quiet the leftover-`custom_components/` working-tree noise via `.gitignore` killed the beta.34 cut. Replacement: `rm -rf "$repo_root/custom_components"` at the end of cut-release's success path (alongside the existing `rm -rf "$staging"`); the failure paths already cleaned up, so the success path was the only gap that left the directory between releases.

## Proven Facts

- **OTA round-trip latency:** beta.9 → beta.10 took ~140s end-to-end on the production Pi/C6: download + extract ~10s, venv + symlink swap ~65s, healthcheck 30s, panel-flash ~22s, C6 reboot + MQTT reconnect + republish ~6s, wifi-off skip + done ~1s. Healthcheck dominates the wait — could be tightened if iteration speed becomes a bottleneck (currently it's a feature: catches a bouncing service before we flash the C6).

- **NM connection-up takes ~60s on this panel after a radio cycle.** Observed 2026-04-30: WiFi state machine walked from `connecting` to `connected` in 63s after a fresh `nmcli radio wifi on`. Sits 3s under the OTA's 60s `waiting_for_connection` timeout; bumping to 120s captured in the Quality of life group.

- **Broker is not externally reachable.** Verified 2026-04-30: cellular `openssl s_client -connect the-interstitial-space.duckdns.org:8883` and `:1883` both time out on v4. No AAAA record on the duckdns subdomain. HA box has only ULA + link-local v6 (no globally-routable v6 address). MQTT credential leak via `firmware.bin` published in public releases is therefore LAN-blast-radius only — not zero risk, but bounded to anyone already on the LAN.

- **Git history is clean of MQTT credentials.** `git log -S 'myvxan' --all` returns nothing — sdkconfig has been gitignored from the start. The only credential leak path was the published `firmware.bin` artifacts on GitHub releases (now scrubbed via Group B; rotation also invalidated the leaked password regardless).

- **Group A's credential delivery + rotation path works end-to-end in production.** Verified 2026-05-01 during Group B: writing new creds to `/opt/panel/mqtt_creds.json` fires the bridge's file-watcher within ~5s, bridge sends `panel_set_creds`, C6 writes NVS + restarts MQTT client, reconnects authenticating as the new user. `mqtt_user` → `feeding-panel` rotation completed without panel downtime visible in HA (entities continued updating throughout). Same path will work for any future rotation.

## Technical Debt

### Outstanding

(empty — all known debt items have been re-homed into [Phase 1](phase1_security.md), [Phase 2](phase2_polish.md), or [Phase 3+](phase3_themed.md))

### Resolved

(empty — populated as items get closed out)
