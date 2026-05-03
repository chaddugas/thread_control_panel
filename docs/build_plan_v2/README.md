# Thread Control Panel — Build Plan V2

> **Status: V2 active.** Step 17 (Phases 1, 2, 3a, 3b), Step 17b, and Phase 1 (Security) shipped — production runs v2.0.0-beta.34 with HA-orchestrated remote updates, NVS-backed MQTT credentials, narrowed authorization surface, and ed25519-signed firmware. **Phase 2 — Polish & cleanup** is in flight (Group B closed in beta.34). See [build_plan_v1.md](../build_plan_v1.md) for the V1 historical record + production-state reference.

## Where things live

| File | What's in it |
|---|---|
| [overview.md](overview.md) | Goals, non-goals, V2 end-state architecture |
| [phase1_security.md](phase1_security.md) | **Closed.** Group A–D: NVS creds, password rotation, sudoers tightening, ed25519 firmware signing |
| [phase2_polish.md](phase2_polish.md) | **Active.** Group A (multi-panel) / B ✅ DONE / C (DRY) / D (comments) / E (tests) |
| [phase2_groupA_multipanel.md](phase2_groupA_multipanel.md) | Group A design doc: hardware abstraction, panel.toml, codegen, capability discovery, A.1/A.2/A.3 sub-phases |
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
> **The conventions below apply to any major project doc under `docs/`** — `build_plan_v1.md`, this directory, future `build_plan_v3/` or successors, and any other multi-section reference doc. They live here because this is where they originated; copy or link to them when you spin up a new doc set.

- **Surface non-discussed additions via AskUserQuestion.** When Claude adds details to any file in `docs/` beyond what was explicitly discussed — deferred decisions, scope cuts, default values, validation criteria, success metrics, open questions, technical assertions you can't verify, anything decided on the user's behalf — surface each as an AskUserQuestion with options **Approve** (proceed as written), **Discuss** (keep in the doc but mark inline as `**[discuss]**` so it's revisited later), **Reject** (remove from the doc; if future agents are likely to re-propose, leave a brief rejected-idea flag with a one-line "why not"). Skip this for: content from the same conversation, mark-as-done updates, breadcrumbs, formatting, mechanical reorganization. AskUserQuestion supports up to 4 questions per call — **if there are more than 4 important items, do multiple rounds rather than dropping items into a bullet summary.** Truly low-stakes additions (small wording, marker formatting, file placement) can still go in a brief end-of-response bullet. Reason: future agents read these docs as decided fact; the user has been surprised by future agents citing "decisions" that were buried agent additions.
- **`#doc:` shorthand for slot-this-in additions.** Anywhere in the user's message, a line beginning with `#doc:` followed by bullets means "add these items to the appropriate doc, slotted into the section where each fits naturally — phase, group, themed-backlog entry, notes, wherever." Default: just process each bullet and brief-confirm in the response (no AskUserQuestion needed). **`#ask` per-bullet escape hatch**: if a bullet ends with `#ask`, surface it as an AskUserQuestion (Approve / Discuss / Reject) — the user appends `#ask` to items they're unsure about. **Agent-initiated escape**: if you encounter a non-`#ask` bullet but you have genuine ambiguity (unclear slotting, or adding it forces a real architectural decision), don't silently guess — flag inline or lift to an AskUserQuestion.
- **Split when a section gets large or is naturally standalone.** Two heuristics, applied together:
  - **Word count**: when a phase or themed-group section reaches roughly the size of `phase2_groupA_multipanel.md` (~3000+ words) OR is anticipated to balloon (many open questions, unknown scope, big design discussion ahead), it earns its own file.
  - **Standalone-load intent**: would an agent ever want to load this section *without* needing the rest of the doc? If yes (e.g. a focused reference on one topic that gets grepped up alone, a design doc for a specific group), promote it even if the word count is modest. Keeping standalone-useful chunks in their own files cuts agent context window when only one topic is in play.
  
  When promoting, leave a short summary + pointer in the parent (see how `phase2_polish.md` Group A points at `phase2_groupA_multipanel.md`). Keeps the parent doc readable as an index.

When V2 ships and the V2 patterns become "current production state," migrate the still-authoritative bits (MQTT topic additions, UART protocol additions, etc.) into a consolidated reference (likely a successor `build_plan_v3/`) so v1 + v2 don't drift into mutual contradiction.
