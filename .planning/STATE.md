---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Forecasts, Commands & UV
status: executing
stopped_at: Phases 12-15 context batch-gathered (ready for chained plan+execute)
last_updated: "2026-06-19T05:00:00.000Z"
last_activity: 2026-06-19 -- Phase 12 Plan 01 complete (registry + contract layer)
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 3
  completed_plans: 1
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-19 after v1.1 milestone)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Phase 12 — command-registry-read-only-command-surface

## Current Position

Phase: 12 (command-registry-read-only-command-surface) — EXECUTING
Plan: 2 of 3
Status: Executing Phase 12 (Plan 01 complete)
Last activity: 2026-06-19 -- Phase 12 Plan 01 complete (registry + contract layer)

## v1.2 Roadmap at a Glance

| Phase | Goal (short) | Requirements |
|-------|--------------|--------------|
| 12 | Command registry + read-only command surface (`help`/`alerts`/`locations`/`status`/`sun`/`wind`/`next-cloudy`) on CLI + Discord behind the guard ladder | CMD-09..16 |
| 13 | Multi-day forecast templates (weekday + weekend, detailed/compact, additive day flags) on demand + per-location scheduled, reusing One Call `daily` | FCAST-01..07 |
| 14 | UV index — `uv <loc>` command + current/max UV + threshold-crossing time in daily briefing; configurable threshold + lead | UV-01, UV-02, UV-03 |
| 15 | Proactive UV sunscreen monitor — daylight-only intraday poll loop, pre-warn + crossing alerts once/day/location, failure-isolated | UV-04, UV-05, UV-06 |

**Dependency notes:** Phase 12's command registry underpins the on-demand forecast (Phase 13) and `uv` (Phase 14) commands. Phase 15 (UV monitor) builds on Phase 14's UV render/threshold/lead config and reuses the v1.1 failure-isolated background-thread pattern (BotThread discipline). Phase 15 is the highest-risk phase (new intraday loop, daylight-only gating, once/day/location dedup, isolation) — consider `/gsd-plan-phase --research-phase 15`.

**Reuse anchors (brownfield):** shared read-only `interactive/lookup.py` core, argparse CLI subcommands, `interactive/bot.py` BotThread + operator guard ladder + ForecastCache, APScheduler briefing spine + per-location schedule slots, lock-guarded ConfigHolder + `_do_reload` hot-reload, editable fail-loud templates, `alerts` table + Discord outcome posting. New work reuses the already-fetched One Call 3.0 `daily[]`/`hourly[]`/`current` (incl. `uvi`, `clouds`, `sunrise`/`sunset`) — no new endpoints.

## Performance Metrics

**Velocity (v1.0 — shipped):**

- Total plans completed: 21 (across Phases 1–5)
- v1.0 timeline: 11 days (2026-06-04 → 2026-06-15), ~7.9k LOC, 186 tests green

**Velocity (v1.1 — shipped):**

- Total plans completed: 22 (across Phases 6–11), 29 tasks
- v1.1 timeline: ~4 days (2026-06-15 → 2026-06-18), ~13.5k LOC, 291 tests green

*Updated after each plan completion*

## Accumulated Context

### Decisions

All v1.0/v1.1 phase-level decisions are archived in PROJECT.md Key Decisions and the milestone ROADMAPs. STATE.md keeps only decisions affecting *upcoming* work:

- **Command registry first (Phase 12):** `help` (CMD-09) must auto-generate from a registry, and all new commands route through one guard ladder (CMD-16) — so a shared command-registry foundation lands before the per-command views and before the on-demand forecast/`uv` commands depend on it.
- **UV render/config before the monitor:** UV threshold + lead config and UV field rendering (Phase 14) are a prerequisite for the Phase 15 monitor's threshold-crossing detection and pre-warn lead.
- **Monitor reuses the v1.1 isolation pattern:** the new intraday UV loop must be failure-isolated like BotThread (UV-06) — never gate/delay/stop a briefing.

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

None open. Carry-forward tech debt from v1.1 is tracked in milestones/v1.1-MILESTONE-AUDIT.md (non-blocking): Phase 9 advisory hardening; `[bot] operator_id` / `[reload] watch` restart-deferred. Note for Phase 12 `status` (CMD-12): the daemon must expose next-scheduled-send time(s) — confirm the scheduler surfaces this without restart coupling.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260615-fac | Resolve milestone-audit tech debt: drop dead `record_sent` + migrate idempotency test to `claim_slot`; backfill `requirements-completed` frontmatter on 11 plan SUMMARYs | 2026-06-15 | 7842e9e | [260615-fac-resolve-two-milestone-audit-tech-debt-it](./quick/260615-fac-resolve-two-milestone-audit-tech-debt-it/) |
| 260617-fua | Wire `ForecastCache.invalidate()` into the daemon reload path (closes Phase 11 code-review CR-01; reverses the Q2/D-12 cache-invalidation deferral) + daemon-level integration test | 2026-06-17 | 7ba1ff4 | [260617-fua-wire-forecastcache-invalidate-into-the-d](./quick/260617-fua-wire-forecastcache-invalidate-into-the-d/) |
| 260617-idm | Fix daemon startup crash-loop (Phase 11 UAT blocker): non-root service couldn't write PID file to root-owned `/run` — repoint `PID_FILE` to `/run/weatherbot/weatherbot.pid` + add `RuntimeDirectory=weatherbot` to the unit (requires manual root re-install of installed unit) | 2026-06-17 | 5dcec80 | [260617-idm-fix-daemon-startup-crash-loop-pid-file-w](./quick/260617-idm-fix-daemon-startup-crash-loop-pid-file-w/) |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Host UAT | OPS-01 SC#1 live `sudo reboot` power-cycle on host `yahir-mint`. | ✅ CONFIRMED 2026-06-15 | 05-02 (2026-06-11) |
| Data semantics | DATA-03 delivered-only persistence — confirm when v2 analysis (ANLY-V2-01) reads the store. | Open (v2) | v1.0 close |

## Session Continuity

Last session: 2026-06-19T05:00:00.000Z
Stopped at: Completed 12-01-PLAN.md (registry + parser + One Call hourly seam + store readers + cloud_threshold)
Resume file: None

## Operator Next Steps

- Plan the first v1.2 phase with `/gsd-plan-phase 12`
- Consider `/gsd-plan-phase --research-phase 15` for the new intraday UV monitor loop (highest-risk phase)
