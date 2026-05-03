[Build Plan V2](README.md) › Phase 2 — Polish & cleanup

# Phase 2 — Polish & cleanup

No new features in this phase. Goal: well-organized, dead-code-free, DRYed, simplified, accurately commented, ready for new panels to drop in.

## Group A: Repo organization + multi-panel prep

**Design**: see [phase2_groupA_multipanel.md](phase2_groupA_multipanel.md) for the full A.1 / A.2 / A.3 sub-phase breakdown, panel.toml schema, codegen tool design, capability discovery wire format, and validation plan.

Original v2-doc bullets, scope-expanded by the May 2026 design discussion to cover Pi model + display type/driver + sensor presence/type + MCU target + per-panel HA entity gating + integration release-train split:

- **A.1**: Integration release train splits off (cut-release sha-compares the integration vs previous release, doesn't bump `manifest.json` version on no-change → no HACS prompt) **+** per-Pi panel identity (`/opt/panel/panel_id` written at install time, install-lib.sh downloads only that panel's artifacts).
- **A.2**: `panels/<id>/panel.toml` as single source of truth for hardware/build/capability config; codegen produces `panel_config.h` + `sdkconfig.defaults`; firmware platform/product split (panel_app.c shim shrinks); sensor optional via `#ifdef`; lidar driver parameterized for Benewake-family compatibility (TF-Mini Plus / TF-Luna / TF-Nova share a UART protocol); MCU target switching (ESP32-C6 vs ESP32-H2 via `idf.py set-target`); bridge publishes `state/_capabilities` retained, integration consumes for entity gating; `panels/<id>/ha/manifest.yaml` deleted (it's a stale reference template, not actually loaded — the YAML manifest is pasted into HA's config flow at panel onboarding).
- **A.3**: Pi-side install templating from `panel.toml` — per-display-type `/boot/firmware/config.txt` snippets (HDMI / DSI / DPI), console framebuffer rotation, sway output transform. Lands just-in-time when panel 2 or 3 is being deployed.

Acceptance: dropping in a new panel = `panels/<new_id>/{panel.toml, ui/, README.md}` + a couple of HA-side config-entry steps. Zero firmware fork. Zero install-script fork. Zero integration code changes.

## ~~Group B: Dead code & file removal sweep~~ ✅ DONE

**Status (2026-05-02)**: Closed in v2.0.0-beta.34. Validated end-to-end: real OTA round-trip on the production panel exercised the V2 OTA path with the V1 Thread-OTA shim removed and completed cleanly through phase progression to `done` + `state/version` reporting beta.34. Build was clean (`idf.py build` had nothing to say about the dropped includes / requires).

- ✅ **V1 Thread-OTA path removed** (90ce900): `tools/panel-ota` Mac CLI deleted; `panel_app.c` lost ~230 lines (`esp_http_client.h` / `esp_ota_ops.h` / `esp_partition.h` includes, `s_ota_active` flag and the two MQTT-publish gates that ORed it with `panel_ota_uart_is_active()`, `download_ota_image()`, V1 `ota_task()`, `handle_ota_command()`, the `cmd/ota` subscribe and dispatch); `panel_config.h` lost `PANEL_TOPIC_CMD_OTA`; `main/CMakeLists.txt` lost `esp_http_client` (V1-only) and `app_update` (V2's panel_ota_uart.c still requires it via `panel_platform`'s PRIV_REQUIRES, where it correctly lives) from main's PRIV_REQUIRES.
- ✅ **Python unused-import audit via ruff** (post-beta.34): 7 findings total — 2 real (unused `import os` in `platform/diagnostics/touch_test.py`, unused `from typing import Any` in `platform/integration/thread_panel/select.py`) + 5 false positives in `tools/thread_panel_dump.py` (pyscript runtime globals like `service`, `hass`, `log`; suppressed file-wide via `# ruff: noqa: F821`). All cleared; `ruff check platform/ tools/thread_panel_dump.py` returns "All checks passed!".
- ✅ **HACS-validation workflow remnants confirmed gone**: `.github/workflows/` directory doesn't exist on disk (workflow was removed in beta.23 per Step 17 Phase 3b validation note 3).
- ✅ **Hygiene cleanups landed alongside** (90ce900): dead `panels/feeding_control/firmware/sdkconfig.ci.{cli,disable_cli,ext_coex}` (leftovers from the original ot_cli example fork; ESP-IDF's `idf_build_apps` would auto-discover them for matrix builds, but cut-release runs locally on the Mac so they were doing nothing); `tools/thread_panel_dump.py`'s stale "Future (v2)" header note about migrating into the integration as a service.

## Group C: DRY + simplification pass

- Bridge: per-control sudo wrappers and similar mqtt subscription patterns — fold to shared helpers where natural.
- Integration: per-entity MQTT subscribe boilerplate is heavily repeated; consider an entity-base helper.
- Firmware: panel_state forwarding pattern repeated in many places.
- Cross-cutting: search for "look at where this is duplicated" with fresh eyes.

## Group D: Comment hygiene

- Sweep for stale comments referencing pre-Step-17b assumptions.
- Remove "this is for X" comments where X has changed.
- Update CLAUDE.md and the architecture paragraph in build_plan to reflect today's reality.

## Group E: Test foundation

- Bridge unit tests for the state cache + WS broadcast logic (pytest, minimal mocking).
- Integration tests that `_handle_resync` republishes everything (HA test framework supports this).
- UI component tests on the data-shape parsing in `useFeeder` (Vitest).
- Note: firmware build verification + end-to-end smoke tests stay deferred to V3 CI work.
