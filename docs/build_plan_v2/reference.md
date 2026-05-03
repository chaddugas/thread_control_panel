[Build Plan V2](README.md) › Reference

# Reference

## Versioning scheme

Standard semver including prerelease syntax: `v<MAJOR>.<MINOR>.<PATCH>` for stable, `v<MAJOR>.<MINOR>.<PATCH>-<tag>.<N>` for prereleases. Tags: `alpha`, `beta`, `rc` per software-release-engineering convention.

| Tag | Convention | When to use |
|---|---|---|
| alpha | feature-incomplete, knowingly broken paths | dogfooding to yourself only |
| beta | feature-complete, unproven | shared with opt-in testers; bugs expected |
| rc | believed done | each rc.N fixes only what rc.(N-1) surfaced |

Repo-wide version (one number for all components per release). The manifest's per-component sha256 lets the Pi skip unchanged components on update.

GitHub Releases has a built-in `prerelease: true` flag — `cut-release` sets it for any version with a `-` in it. The integration's `Include prereleases` option toggles whether prerelease versions are considered for `latest_version`.

## `cut-release` interactive prompt

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

## File changes summary (snapshot through Step 17b)

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
| `platform/bridge/panel_bridge/events.py` | Structured-event logger helper (Step 17b) |
| `platform/bridge/panel_bridge/controls/nmcli_util.py` | Shared nmcli runner with timeout (Step 17b) |
| `platform/bridge/panel_bridge/controls/wifi_state.py` | wifi_state enum + nmcli monitor task (Step 17b) |
| `platform/deploy/panel-update.sh` | Orchestration script |
| `docs/build_plan_v2/` | This document set (split out from monolithic `docs/build_plan_v2.md` post-beta.34) |

### Modified

| Path | Change |
|---|---|
| `tools/cut-release` | Add interactive bump prompt (gum), firmware build, tarballing, zip, manifest.json, gh release create with --prerelease flag |
| `platform/deploy/install-pi.sh` | Switch from git-clone to release-artifact pull; add `fbcon=rotate:3` + console-setup; render systemd units pointing at `/opt/panel/current/`; configure persistent journald (Step 17b) |
| `platform/deploy/panel-bridge.service` | `ExecStart=/opt/panel/current/bridge/...` |
| `platform/deploy/panel-ui.service` | Root at `/opt/panel/current/ui-dist/` |
| `platform/firmware/components/panel_platform/panel_app.c` | Wire ota_uart handler; publish state/version on connect |
| `panels/feeding_control/firmware/main/panel_app.c` | Subscribe to cmd/update; forward over UART |
| `README.md` | Document new install paths (Pi + HA box) from release artifacts |
| `CLAUDE.md` | Reference both build_plan docs; note V2 is active work |

### Removed (during Phase 1)

| Path | Why |
|---|---|
| `custom_components/thread_panel/` | Moved to `platform/integration/thread_panel/` |
| `panels/feeding_control/ui/dist/` | Built artifacts now in releases, not git |
| `.github/workflows/validate.yml` | HACS validation that always failed on main (per off-main commit pattern) — removed in beta.23 |

## Resolved decisions

1. **Where does `cut-release` run?** Mac. CI is V3.
2. **Auto-install vs. manual?** Manual only. HA polls GitHub releases hourly, surfaces "update available" via the entity, user clicks Install. Scheduled auto-install removed from scope.
3. **Version retention on Pi.** Keep `current` + `previous-1`, prune older. `/opt/panel/versions/` cleanup runs at end of successful update.
4. **Repo-wide vs per-component versions.** Repo-wide. Per-component sha256 in manifest handles "only re-flash if changed."
5. **HACS publication.** Skipped — project is too hardware-specific to be useful as a default-store integration. HACS-as-custom-repo (user adds the repo URL) stays available.
6. **Update transport for C6.** UART at 921600 baud during transfer (~15s for ~1.5 MB). Thread-OTA stays in tree as fallback until V2 proven.
7. **Console display approach.** tty1 takeover with `fbcon=rotate:3` + `setfont Lat15-TerminusBold32x16`, not a web UI overlay. Doesn't depend on the kiosk being healthy (which matters precisely when you're updating to fix it).
8. **Beta versioning scheme.** Standard semver prereleases (`-beta.N`), npm-style flat bump menu in cut-release, integration toggle for `Include prereleases`.

## Open questions

- Healthcheck thresholds in `panel-update.sh`. "Bridge active for 30s" is a starting point — may need tuning. Same for "C6 reconnect within N seconds after flash." Set conservative defaults, log actuals during test releases, tune from data.
- Concurrent-update protection. If `cmd/update` arrives while one is in flight, what happens? Probably: write a `/var/run/panel-update.pid` lockfile in step 1, refuse to start if it exists, publish `state/update_status: rejected, detail: in_progress`. Keep simple.
- `panel-update.sh` log retention. Each run should write a full log to `/var/log/panel-update/<timestamp>.log` for post-mortem. Retention policy TBD (keep last 10? last 30 days?). Easy to add later.
- Whether to include the bridge tarball *in* the bridge's own version directory (so the source-of-truth tarball is preserved on disk) or just unpack-and-discard. Probably preserve — useful for debugging "did I actually install what I think I installed."
