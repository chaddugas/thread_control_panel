# Thread Control Panel — Build Plan V2

> **Status: V2 active.** Step 17 (Phases 1, 2, 3a, 3b), Step 17b, and Phase 1 (Security) shipped — production runs v2.0.0-beta.34 with HA-orchestrated remote updates, NVS-backed MQTT credentials, narrowed authorization surface, and ed25519-signed firmware. **Phase 2 — Polish & cleanup** is in flight (Group B closed in beta.34). See [build_plan_v1.md](../build_plan_v1.md) for the V1 historical record + production-state reference.

## Where things live

| File | What's in it |
|---|---|
| [overview.md](overview.md) | Goals, non-goals, V2 end-state architecture |
| [phase1_security.md](phase1_security.md) | **Closed.** Group A–D: NVS creds, password rotation, sudoers tightening, ed25519 firmware signing |
| [phase2_polish.md](phase2_polish.md) | **Active.** Group A (multi-panel) / B ✅ DONE / C (DRY) / D (comments) / E (tests) |
| [phase3_themed.md](phase3_themed.md) | Backlog organized by theme — quality of life, robustness, HA UX, hardware, dev ergonomics, multi-device |
| [future_panels.md](future_panels.md) | Idea track for panels 2 + 3 |
| [completed_steps.md](completed_steps.md) | Historical detail for Step 17 (Phases 1, 2, 3a, 3b) and Step 17b |
| [reference.md](reference.md) | Versioning scheme, cut-release prompt, file-changes summary, resolved decisions, open questions |
| [notes.md](notes.md) | Lessons Learned, Proven Facts, Technical Debt — cross-cutting, accumulate over time |

## Status

V2 development is active. **Phase 1 — Security closed in v2.0.0-beta.33.** Shipped:

- **Step 17 Phase 1**: artifact-based releases + repo restructure ✅
- **Step 17 Phase 2**: C6 UART OTA receiver + panel-flash CLI ✅
- **Step 17 Phase 3a**: Pi-side update orchestration ✅
- **Step 17 Phase 3b**: HA-side `update.PanelUpdateEntity` ✅
- **Step 17b**: WiFi state surface + observability ✅
- **Phase 1 Group A**: MQTT credentials out of firmware (NVS-backed) ✅
- **Phase 1 Group B**: rotate leaked password + scrub historical `firmware.bin` assets ✅
- **Phase 1 Group C**: authorization surface tightening — narrowed sudoers, removed wide-open NOPASSWD: ALL drop-in, kept wifi password out of recorder, fixed same-version OTA rejection ✅
- **Phase 1 Group D**: OTA tamper-resistance — ed25519 firmware signing via minisign, sign in cut-release, verify in `lib_download_artifacts` ✅

**In flight**: [Phase 2 — Polish & cleanup](phase2_polish.md). Group B (dead code & file removal) closed in v2.0.0-beta.34. Remaining: Group A (repo organization for multi-panel readiness), Group C (DRY pass), Group D (comment hygiene), Group E (test foundation). After Phase 2: themed groups under [Phase 3+](phase3_themed.md) (no strict ordering — pick whichever fits the moment).

## Keeping this current

Same convention as V1. After completing a step or making a non-trivial decision:

- Strike through the finished step (`~~**Step name**~~`) and append `✅ DONE` in whichever phase file it lives.
- Move the `(next up)` marker.
- Record meaningful learnings in [notes.md → Lessons Learned](notes.md#lessons-learned), validated invariants in [Proven Facts](notes.md#proven-facts), and known-but-deferred problems in [Technical Debt](notes.md#technical-debt).
- Refresh **Status** above when a major capability lands or changes.
- Edit/remove anything the work has invalidated rather than leaving stale guidance behind.

When V2 ships and the V2 patterns become "current production state," migrate the still-authoritative bits (MQTT topic additions, UART protocol additions, etc.) into a consolidated reference (likely a successor `build_plan_v3/`) so v1 + v2 don't drift into mutual contradiction.
