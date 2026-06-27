---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Bot Module Extraction
status: planning
last_updated: "2026-06-27T17:30:00.000Z"
last_activity: 2026-06-27
progress:
  total_phases: 8
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-27 — v2.0 "The Great Decoupling" milestone started)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** v2.0 Bot Module Extraction — roadmap created (Phases 21–28); ready to plan Phase 21.

## Current Position

Phase: 21 of 28 (Characterization / Golden-Test Harness) — first v2.0 phase
Plan: — (ready to plan)
Status: Roadmap created — ready to plan Phase 21
Last activity: 2026-06-27 — v2.0 roadmap created, 14/14 requirements mapped (no orphans)

Progress: [░░░░░░░░░░] 0%

## v2.0 Roadmap at a Glance

| Phase | Goal (short) | Requirements |
|-------|--------------|--------------|
| 21 | Lay byte-identical golden/characterization snapshots (embeds, CLI, schedule plan, DB rows, custom_ids, exception identity) — the oracle every later phase re-runs | BHV-02, BHV-01 |
| 22 | Extract `Channel` + delivery-reliability into the clean in-place module boundary; stand up the import-lint/litmus-grep hygiene gate | SEAM-01, PKG-01 |
| 23 | Generic `SchedulerEngine.register(...)` + `OccurrenceStore` exactly-once + serialization-clean `JobStore` Protocol (in-memory impl only) | SEAM-02, SEAM-03 |
| 24 | Generic `ConfigHolder[T]` + `ReloadEngine` over an app-defined schema via injected `validate` / `desired_jobs` hooks | SEAM-04 |
| 25 | Lifecycle READY-gate on an app health-check + single composition root; prove the 4 leak-points are injected (litmus-grep clean) | SEAM-05, APP-01, APP-02 |
| 26 | Move the self-describing registry + shared dispatcher into the module; app registers commands; CLI/Discord/help derive, drift impossible | SEAM-06 |
| 27 | Relocate Discord adapter (`BotThread` + `PanelKit` + `SelectedContext`); inject `render` to fix the cycle by ownership; freeze custom_ids + `discord.py==2.7.1` | SEAM-07 |
| 28 | Physical split to `YahirReusableBot` repo + uv git dep + EXTENSION-GUIDE + live `yahir-mint` restart UAT | PKG-02, DOCS-01 |

**Dependency notes:** Leaf-seams-first, split-last. Goldens (21) before any move. Channel (22) is the lowest-risk warm-up and establishes the boundary + import-hygiene gate. Scheduler (23) before config-reload (24) because reload reconciles *jobs* through the engine. Lifecycle + composition root (25) follows config (it depends on the holder) and is where the four leak-points get wired/proven. Registry (26) registers commands at that root. The Discord adapter (27) is near-last — it consumes the registry *and* the relocated `render_embed`. The physical split (28) is strictly last, re-running the Phase-21 goldens against the git-pinned module. **Cross-cutting:** BHV-01 (suite green) re-runs every phase; PKG-01 import-hygiene + APP-02 litmus-grep are standing gates on every seam phase (22–27).

**Research flags (`--research-phase` candidates):** **Phase 23** (APScheduler serialization-clean `JobStore` seam — importable callable + picklable args + fire-time lookup, design-now/build-later), **Phase 24** (pydantic-v2 generic-validation pitfall + `validate`/`desired_jobs`/rollback hook shapes — highest-coupling seam), **Phase 27** (resolve the render cycle by ownership while preserving every v1.3 persistent-view/clone-path/custom_id invariant byte-identically), **Phase 28** (packaging/namespace/entry-point/dev-vs-deploy mechanics + live-host UAT — most "works locally, breaks on host" surface). Phases 21/22/25/26 have HIGH-confidence patterns (skip research-phase).

**Reuse anchors (brownfield — pure extraction, byte-identical):** the runtime stack is unchanged (httpx, APScheduler 3.x, tenacity, structlog, discord.py 2.7.1, watchfiles, cachetools, pydantic, SQLite). Existing seams to un-braid in place: `channels/base.py` + `reliability/retry.py` (→ Channel, Phase 22); `scheduler/daemon.py` `fire_slot`/`claim_slot`/`_register_jobs`/`_reconcile_jobs` (→ SchedulerEngine/OccurrenceStore, Phase 23); `config/holder.py` + `_do_reload`/`validate_config_and_templates`/`_desired_job_ids` (→ ConfigHolder[T]/ReloadEngine, Phase 24); `ops/sdnotify.py` + `ops/selfcheck.py` `gate_until_healthy`/`run_self_check` (→ Lifecycle + injected HealthCheck, Phase 25); `interactive/dispatch.py` + `registry.COMMANDS` (→ registry/dispatch seam, Phase 26); `interactive/bot.py` `render_embed` + `interactive/panel.py` `PanelView` (→ Discord adapter + PanelKit, cycle fix by DI, Phase 27). The litmus on every seam: *"could a reminder bot use this with zero weather assumptions?"*

## Performance Metrics

**Velocity (shipped):** v1.0 — 47 plans / Phases 1–5 / 11 days / 186 tests. v1.1 — 22 plans / Phases 6–11 / ~4 days / 291 tests. v1.2 — 15 plans / Phases 12–15 / 575 tests. v1.3 — 11 plans / Phases 16–20 / ~4 days / 649 tests / 18 feat commits.

**v2.0:** 0/8 phases, 0 plans complete. Baseline at milestone start: 652 tests green on `main` (649 + 3 from Gate-2 quick tasks).

## Accumulated Context

### Decisions

Full decision log lives in PROJECT.md Key Decisions. v2.0-specific governing decisions (from milestone scope + research):

- **Pure extraction, byte-identical (whole milestone):** the existing suite + new golden tests are the acceptance contract — "tests green" is necessary but NOT sufficient; the Phase-21 goldens (embed bytes, CLI stdout/exit, schedule plan, DB rows, custom_ids, exception identity) are the byte-identical oracle. Never edit a test to make a "pure" refactor pass.
- **In-place seam first, physical split LAST:** un-braid mechanism from content into a clean internal package boundary (tests green) *before* the `git mv` to `YahirReusableBot`. The boundary subpackage is named what the extracted package will be, so the split is a `git mv` not a rename.
- **Module name decided up front:** `YahirReusableBot` (dist) / `yahir_reusable_bot` (import root), distinct from `weatherbot` (never shadow the import namespace). Ships NO console script — `weatherbot` console entry point stays app-side.
- **Layered core → adapters → app, one-way deps:** Core imports neither app nor adapter; every app behavior arrives via a PEP 544 Protocol or bare callable defined in the module's `seams.py`. The panel lives in the Discord *adapter* (SMS/Slack have no buttons).
- **JobStore: seam designed now, durable impl deferred (JOBSTORE-V2-01):** ship the Protocol + in-memory impl only; shape `register()` serialization-clean (importable callable + picklable identity-style args, live collaborators looked up at fire time) so the durable backend is a drop-in, not a redesign. No speculative backend built (YAGNI / rule-of-three).
- **Resolve the `render_embed`↔`PanelView` cycle by ownership, not a deferred import:** move `render_embed` app-side and inject it into `PanelKit` as `render`. Don't port the in-function import across the boundary.
- **Pin `discord.py==2.7.1` in the module; freeze `custom_id`s as a wire contract:** loose ranges let the host resolve an unverified version; re-namespacing custom_ids kills the live pinned panel. If they must change, ship a `!panel` re-summon migration + re-run the live UAT.
- **Lifecycle/config stay app-policy-free:** lifecycle gates READY on an app-provided health-check (no OpenWeather in the module), identity (PID path/runtime dir/unit/console name) parameterized, `.service` is a template; "which config keys are restart-only" stays app-side.

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

- **[Phase 28] Live module-split restart UAT on host `yahir-mint`:** after the split + repin, deploy → `sudo systemctl restart weatherbot` → confirm the bot runs against the pinned module sha (startup-version-log line) and every button/dropdown on the already-pinned panel still routes (custom_id contract + persistent-view re-bind), correct default location. The clean-venv `uv sync --frozen` install + `weatherbot check`/`--help` + full suite is the gate that turns "works locally" into "works on host."

### Blockers/Concerns

[Issues that affect future work]

- **Carry-forward `[bot]` read-once-at-startup tech debt:** `[bot] operator_id` / `[reload] watch` / `panel_channel_id` are read once at startup (restart boundary). Keep this restart-boundary *policy* app-side during the config-reload extraction (Phase 24) — the generic holder must not enshrine a specific key list.
- **DATA-03 delivered-only persistence semantics** (open since v1.0): confirm when v2 analysis (ANLY-V2-01) reads the store — deferred beyond v2.0, not in extraction scope.

## Deferred Items

Items acknowledged and carried forward:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Data semantics | DATA-03 delivered-only persistence — confirm when v2 analysis (ANLY-V2-01) reads the store. | Open (post-v2.0) | v1.0 close |
| Extension point | Durable/dynamic `JobStore` impl (JOBSTORE-V2-01) — seam designed in v2.0, impl deferred to a reminder-style consumer. | Deferred (designed in Phase 23) | v2.0 scope |
| Extension point | 2nd `Channel` adapter (Telegram/SMS/Slack — CHAN-V2-01/02/03) — abstraction shipped, impls deferred to their own milestones. | Deferred | v2.0 scope |

_All v1.0–v1.3 host UATs were resolved at v1.3 Gate-2 close (2026-06-27); see milestones/*-MILESTONE-AUDIT.md._

## Session Continuity

Last session: 2026-06-27T17:30:00.000Z
Stopped at: v2.0 roadmap created (Phases 21–28); REQUIREMENTS.md traceability filled (14/14)
Resume file: None

## Operator Next Steps

- Plan the first v2.0 phase with `/gsd-plan-phase 21` (the golden harness — the byte-identical oracle for the whole milestone).
