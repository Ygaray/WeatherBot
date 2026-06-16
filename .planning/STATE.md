---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Interactive & Live-Config
status: verifying
stopped_at: Completed 08-03-PLAN.md (ConfigHolder)
last_updated: "2026-06-16T01:15:25.114Z"
last_activity: 2026-06-16
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 10
  completed_plans: 10
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-15 after v1.0 milestone)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Phase 08 — configholder-fire-slot-reads-from-holder-refactor

## Current Position

Phase: 9
Plan: Not started
Status: Phase complete — ready for verification
Last activity: 2026-06-16

Progress: [██░░░░░░░░] 25% (v1.1 Phase 08)

## v1.1 Roadmap at a Glance

| Phase | Goal (short) | Requirements |
|-------|--------------|--------------|
| 6 | Shared lookup core + `weather <loc>` parser (foundation) | — (underpins CMD-01..05, CMD-02/06/07) |
| 7 | CLI `weather [location]` one-shot (no daemon) | CMD-01, CMD-03, CMD-04, CMD-05 |
| 8 | ConfigHolder + `fire_slot` holder refactor (prerequisite) | — (unblocks CFG-01/05) |
| 9 | Reload engine + explicit trigger + `--check-config` | CFG-01, CFG-02, CFG-04, CFG-05, CFG-06, CFG-08 |
| 10 | watchfiles auto-reload (debounce) | CFG-03 |
| 11 | Discord inbound gateway bot + reload confirm | CMD-02, CMD-06, CMD-07, CMD-08, CFG-07 |

**Research flags:** Phase 9 (exactly-once idempotency key under reload — Pitfall #8, HIGH RISK) and Phase 11 (asyncio-thread coexistence + bot lifecycle — Pitfalls #1/#4) are deeper-research candidates — consider `/gsd-plan-phase --research-phase {9|11}`.

## Performance Metrics

**Velocity (v1.0 — shipped):**

- Total plans completed: 28 (across Phases 1–5)
- v1.0 timeline: 11 days (2026-06-04 → 2026-06-15), ~7.9k LOC, 186 tests green

**v1.1:** no plans executed yet.

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Recent decisions affecting current work:

- [Roadmap v1.1]: Phase numbering CONTINUES from v1.0 — v1.1 is Phases 6–11 (no reset).
- [Roadmap v1.1]: Dependency-ordered build sequence preserved — shared core (6) before its consumers (7, 11); ConfigHolder/`fire_slot` refactor (8) BEFORE reload logic (9); explicit-trigger reload (9) BEFORE file-watch (10); the async Discord bot (11) LAST on proven foundations.
- [Roadmap v1.1]: Only two NEW runtime deps planned — `discord.py 2.7.x` (Phase 11) + `watchfiles 1.2.x` (Phase 10); everything else reuses the v1.0 stack. `BackgroundScheduler` stays sync (no AsyncIOScheduler migration).
- [Roadmap v1.1]: Highest risk = CFG-05 / Pitfall #8 — hot-reload must not break the exactly-once `(location, send_time, local_date)` key on a name/tz/send_time change; Phase 9 carries an explicit exactly-once-across-reload success criterion.
- [Phase ?]: [Phase 6-01]: Command parser is parse-don't-validate (D-01) — config-free, I/O-free; classifies into NOT_A_COMMAND/DEFAULT/LOCATED and extracts raw-case location, validating nothing against config.
- [Phase ?]: [Phase 6-01]: Word-boundary guard on the 'weather' keyword (whitespace required after keyword) prevents briefing-feedback loops (weatherman/weather: -> NOT_A_COMMAND, T-06-02).
- [Phase ?]: [Phase 6-02]: lookup_weather is the read-only fetch->render core (D-06: no db path, no store import) returning a LookupResult value object (D-05); P7 CLI prints .text and P11 Discord builds an embed from .forecast without re-fetching.
- [Phase ?]: [Phase 6-02]: UnknownLocationError subclasses ValueError, carries .requested + .valid_names (D-07), raised from the upgraded resolve_location; every existing except-ValueError caller stays green (Pitfall 5).
- [Phase ?]: 06-03: send_now delegates read-only HEAD to lookup_weather (D-08); deliver+persist TAIL byte-identical, scheduled timing via extra_placeholders
- [Phase ?]: [Phase 7-01]: Used hatchling (PyPA-canonical) build backend + single [project.scripts] entry weatherbot=weatherbot.cli:main; uv sync materializes .venv/bin/weatherbot. No new runtime deps.
- [Phase 07]: [Phase 7-03] Fixed a real D-09 bug: structlog default ignored the stdlib level and rendered to STDOUT, defeating quiet mode AND polluting the weather command's pipeable STDOUT; configured structlog to honor the effective level and render to STDERR via a live-stderr proxy.
- [Phase 08]: [Phase 8-01] Wave-0 RED scaffold deferred the `ConfigHolder` import into a per-test `_holder()` helper (not top-of-module) so all six VALIDATION node IDs COLLECT while each still fails RED on a real `ModuleNotFoundError` — a top-level import would error at collection and hide the node IDs.
- [Phase 08]: [Phase 8-01] frozen-mutation guard asserts `pydantic.ValidationError` (type `frozen_instance`), never `dataclasses.FrozenInstanceError` (Pitfall 2 — pydantic BaseModels); config B built via `model_copy(update=...)`, no Config hashing (Pitfall 1).
- [Phase 08]: [Phase 8-02] frozen=True added to all 5 config models' ConfigDict(extra="forbid") (D-02) — config snapshots are immutable-by-type; field rebind raises pydantic.ValidationError(frozen_instance), the precondition for ConfigHolder lock-free shared reads. No config hashing introduced (Pitfall 1: list-bearing models stay unhashable).
- [Phase ?]: [Phase 8-03] ConfigHolder: lock-free current() (atomic LOAD_ATTR under GIL) + threading.Lock-guarded replace() that does NOT validate (deferred to Phase 9/CFG-04); canonical name replace (D-04); owns Config only, no Settings/secrets (Pitfall #12).
- [Phase ?]: [08-04] fire_slot reads the config snapshot ONCE per fire (override-wins: config= beats holder.current(), both-None raises ValueError) and threads that same object through the reliability budget read AND send_now(config=snapshot) — a mid-fire replace() cannot tear a delivery (Pitfall #9).
- [Phase ?]: [08-04] add_job now carries {holder: holder} not {config: config}, so an UNCHANGED fire_slot job re-reads holder.current() every fire; replace() changes what it renders (the phase core proof). Stable job id and _heartbeat_tick byte-identical; catchup.py unchanged (pure-input, A3).

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- [Phase 9]: Exact policy for tz/send_time changes mid-day on an already-sent slot, plus the stable-location-id key change vs the v1 sent-log schema, needs a decision + dedicated test during Phase 9 planning (Pitfall #8, HIGH RISK).
- [Phase 11]: Prefix vs slash command-type (message_content privileged intent) and the `client.start()`-in-a-thread lifecycle/shutdown wiring to pick during Phase 11 planning (Pitfalls #1/#3/#4).

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260615-fac | Resolve milestone-audit tech debt: drop dead `record_sent` + migrate idempotency test to `claim_slot`; backfill `requirements-completed` frontmatter on 11 plan SUMMARYs | 2026-06-15 | 7842e9e | [260615-fac-resolve-two-milestone-audit-tech-debt-it](./quick/260615-fac-resolve-two-milestone-audit-tech-debt-it/) |
| Phase 06 P01 | 3min | 2 tasks | 2 files |
| Phase 06 P02 | 12m | 3 tasks | 3 files |
| Phase 06 P03 | 2min | 3 tasks | 3 files |
| Phase 07 P01 | 4min | 1 tasks | 2 files |
| Phase 07 P02 | 2 min | 2 tasks | 1 files |
| Phase 07 P03 | ~10 min | 3 tasks | 6 files |
| Phase 08 P01 | ~12 min | 2 tasks | 2 files |
| Phase 08 P02 | ~8min | 1 tasks | 1 files |
| Phase 08 P03 | ~6 min | 1 tasks | 1 files |
| Phase 08 P04 | ~9 min | 2 tasks | 3 files |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Host UAT | OPS-01 SC#1 live `sudo reboot` power-cycle on host `yahir-mint`. | ✅ CONFIRMED 2026-06-15 | 05-02 (2026-06-11) |
| Data semantics | DATA-03 delivered-only persistence — confirm when v2 analysis (ANLY-V2-01) reads the store. | Open (v2) | v1.0 close |

## Session Continuity

Last session: 2026-06-16T01:07:19.477Z
Stopped at: Completed 08-03-PLAN.md (ConfigHolder)
Resume file: None

## Operator Next Steps

- Plan the first v1.1 phase with `/gsd-plan-phase 6`.
- For Phase 9 and Phase 11, consider `/gsd-plan-phase --research-phase {9|11}` given the flagged high-risk integration pitfalls.
