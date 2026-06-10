---
phase: 03-always-on-scheduler
plan: 04
subsystem: scheduler
tags: [dst, zoneinfo, apscheduler, catchup, timezone, tdd]

# Dependency graph
requires:
  - phase: 03-always-on-scheduler
    provides: "plan_catchup pure missed-send planner + MissedSlot (03-03), Schedule model + day_of_week (03-01)"
provides:
  - "DST-correct scheduled-instant construction in plan_catchup (offset/fold re-resolves)"
  - "Spring-forward gap detection: non-existent wall-clock slots are skipped to agree with the live CronTrigger"
  - "Aware-instant due/grace comparison (now_utc) replacing two-wall-clock-locals subtraction"
  - "Transition-band DST tests (02:30 gap, 01:30 fold) locking SCHD-04 DST half"
affects: [03-05, phase-04-reliability]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Build aware instants by composing a naive wall-clock datetime then attaching the zone (datetime(...).replace(tzinfo=tz)), never by mutating an already-aware datetime's hour/minute"
    - "Detect spring-forward gaps by round-tripping the naive wall-clock through the zone (changed value == time never existed)"

key-files:
  created: []
  modified:
    - weatherbot/scheduler/catchup.py
    - tests/test_scheduler.py

key-decisions:
  - "Spring-forward gap slots are skipped (continue) so the planner agrees with the live CronTrigger, which never fires a non-existent wall-clock time"
  - "Due/grace decisions compare aware instants against now_utc directly, eliminating the negative-day delta that dropped fall-back fold slots"

patterns-established:
  - "DST-correct instant construction: datetime(y,mo,d,hh,mm).replace(tzinfo=tz) + zone round-trip gap check"
  - "Aware-instant comparison only — never subtract two wall-clock-derived locals across a DST boundary"

requirements-completed: [SCHD-04]

# Metrics
duration: 2min
completed: 2026-06-10
---

# Phase 3 Plan 4: DST-Correct Missed-Send Planner Summary

**plan_catchup now builds the intended fire instant by attaching the location zone to a freshly-composed naive wall-clock datetime (re-resolving the UTC offset/fold), skips spring-forward-gap slots that never existed, and compares aware instants — closing gap #1 so the missed-send planner agrees with the live CronTrigger across DST transitions (SCHD-04 DST half, success criterion #3).**

## Performance

- **Duration:** 2 min
- **Started:** 2026-06-10T21:53:53Z
- **Completed:** 2026-06-10T21:55:21Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Reproduced gap #1 with a transition-band test that FAILED against the pre-fix code: a 02:30 spring-forward-gap slot produced a phantom MissedSlot the live trigger would skip.
- Replaced the defective `now_local.replace(hour=, minute=)` construction with `datetime(y,mo,d,hh,mm).replace(tzinfo=tz)` so the offset/fold re-resolves for the slot's wall-clock time.
- Added spring-forward gap detection via a zone round-trip (`scheduled.astimezone(tz).replace(tzinfo=None) != naive`) — non-existent wall-clock slots are skipped, matching the live CronTrigger.
- Switched both due/grace comparisons to aware instants against `now_utc`, removing the negative-day delta that silently dropped fall-back-fold slots.
- Full suite green: 129 passed (128 prior + 1 new transition-band test); ruff clean.

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1: Add failing transition-band DST tests (RED)** - `97c1d28` (test)
2. **Task 2: Fix DST instant construction + spring-forward gap detection (GREEN)** - `2c92ae2` (fix)

_No refactor commit — the GREEN implementation was already clean (ruff check + format pass)._

## Files Created/Modified
- `weatherbot/scheduler/catchup.py` - Rewrote scheduled-instant construction in `plan_catchup`: naive wall-clock + zone attach, round-trip gap detection, aware-instant due/grace comparison; updated docstring to match.
- `tests/test_scheduler.py` - Added `test_dst_transition_band_exactly_once` (02:30 spring-forward gap → 0 slots; 01:30 fall-back fold → exactly-one within grace, 0 beyond grace) and imported `timedelta`.

## Decisions Made
- Spring-forward gap slots are skipped (`continue`) rather than emitted, so the planner agrees with the live CronTrigger (which never fires a non-existent wall-clock time). This is the success-criterion-#3 "no skipped spring-forward miss" guarantee read correctly: there is no miss because the slot never existed.
- Due/grace use aware-instant arithmetic on `now_utc` exclusively; the function already receives/derives `now_utc`, so no signature change was needed.

## TDD Gate Compliance
- RED gate: `97c1d28` (`test(03-04)`) — test added and confirmed failing against unmodified `catchup.py` (phantom MissedSlot reproduced).
- GREEN gate: `2c92ae2` (`fix(03-04)`) — implementation makes the transition-band test and the full suite pass.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The acceptance criterion `grep -c "now_local.replace(hour" == 0` initially failed because the new docstring referenced the old approach by name to explain what NOT to do. Reworded the docstring ("never by mutating `now_local`'s hour/minute in place") to satisfy the grep while preserving the explanation. Folded into the Task 2 commit before committing.

## User Setup Required
None - no external service configuration required. No new dependencies added (stdlib `datetime`/`zoneinfo` already imported).

## Next Phase Readiness
- Gap #1 (SCHD-04 DST half, SC #3) is closed and locked by transition-band tests.
- Gap #2 (SCHD-07 exactly-once delivery / atomic claim_slot) remains open and is owned by plan 03-05 — this plan intentionally did not touch `daemon.py`, `store.py`, or the dedup-key schema.
- After 03-05 lands, the phase should be re-verified against 03-VERIFICATION.md's five success criteria.

## Self-Check: PASSED

- FOUND: weatherbot/scheduler/catchup.py
- FOUND: tests/test_scheduler.py
- FOUND: .planning/phases/03-always-on-scheduler/03-04-SUMMARY.md
- FOUND: commit 97c1d28 (RED)
- FOUND: commit 2c92ae2 (GREEN)

---
*Phase: 03-always-on-scheduler*
*Completed: 2026-06-10*
