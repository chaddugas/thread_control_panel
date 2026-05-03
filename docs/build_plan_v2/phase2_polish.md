# Phase 2 — Polish & cleanup

No new features in this phase. Goal: well-organized, dead-code-free, DRYed, simplified, accurately commented, ready for new panels to drop in.

## Group A: Repo organization + multi-panel prep

- Move `panels/<id>/firmware/main/panel_app.c` shim contents into `platform/firmware/` driven by config. End state: `panels/<id>/` contains a UI directory + manifest + small config snippet only.
- Same treatment for `panels/<id>/ha/manifest.yaml` (becomes a manifest reference, no code).
- Acceptance: dropping in a new panel = UI bundle + manifest + a few lines of config, zero firmware fork.

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
