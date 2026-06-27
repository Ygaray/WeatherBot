---
phase: 20-isolation-hardening-polish
plan: 01
subsystem: testing
tags: [apscheduler, asyncio, failure-isolation, discord, panel, executor, pytest]

# Dependency graph
requires:
  - phase: 15-uv-monitor
    provides: "live-scheduler raising-tick isolation proof (test_raising_uvmonitor_tick_never_stops_scheduler) — the skeleton mirrored here"
  - phase: 17-panel-core
    provides: "PanelView.on_command + the per-callback non-propagating isolation envelope the hanging case inherits unchanged"
  - phase: 16-shared-dispatch
    provides: "dispatch_spec seam (the only caller of the asyncio default executor) audited by D-08b"
provides:
  - "Live-scheduler hanging-callback isolation proof (test_hanging_callback_never_stops_live_briefing) — closes the hanging half of PANEL-11"
  - "D-08b executor-sharing audit (test_briefing_path_not_on_default_executor) — proves the briefing spine never borrows the asyncio default pool"
affects: [polish, milestone-audit, isolation, panel]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Hanging-callback live-scheduler proof: monkeypatch the awaited dispatch seam to await asyncio.Event().wait() (D-08a, never a CPU spin), drive the callback on a daemon thread via asyncio.run so it never returns, then assert a real BackgroundScheduler sentinel still fires"
    - "Structural source-level executor audit: rglob weatherbot/ for run_in_executor(None, …) call sites and assert the set equals exactly {interactive/dispatch.py}, with the scheduler/ package having zero"

key-files:
  created: []
  modified:
    - tests/test_scheduler.py
    - tests/test_dispatch.py

key-decisions:
  - "The hanging wedge yields via await asyncio.Event().wait() (D-08a), not a while-True CPU spin — all blocking panel work is already off-loop via run_in_executor, so the realistic hang is a never-completing await; a spin would prove GIL-throttling, a different thing (Pitfall 3)"
  - "Wedge seam: monkeypatch panel.dispatch_spec (the awaited call inside on_command's non-propagating envelope) rather than _stub_handler — the handler runs inside the executor thread, so hanging there would not model an await-level loop wedge (D-08a)"
  - "D-08b audit implemented as a structural source assertion (run_in_executor(None, …) appears only in dispatch.py; scheduler/ has zero) over fragile APScheduler executor-object introspection — concrete regression insurance (Pitfall 4), no bounded executor introduced (Option C out of scope)"

patterns-established:
  - "Test-only isolation re-proof: prove a load-bearing failure-isolation property against a LIVE BackgroundScheduler with zero production change (D-08)"

requirements-completed: [PANEL-11]

# Metrics
duration: ~7min
completed: 2026-06-26
status: complete
---

# Phase 20 Plan 01: Isolation Hardening (hanging-callback proof + executor audit) Summary

**Two test-only proofs closing PANEL-11's hanging case: a live `BackgroundScheduler` sentinel briefing keeps firing while a panel `on_command` callback is wedged on `await asyncio.Event().wait()`, and a structural audit confirms the briefing spine never borrows the asyncio default executor the panel's read-only fetch uses — zero `weatherbot/` change.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-06-26 (execution)
- **Completed:** 2026-06-26
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Closed the **hanging** half of the milestone's load-bearing failure-isolation guarantee (the raising half was already proven in Phase 15) against a *live* scheduler — the briefing fires on time and `scheduler.running is True` while a panel callback hangs forever on a loop-yielding await.
- Added the D-08b executor-sharing audit: a structural assertion that `run_in_executor(None, …)` (the asyncio default `ThreadPoolExecutor`) is reached ONLY from `interactive/dispatch.py` (the panel's read-only fetch) and that the entire `weatherbot/scheduler/` briefing spine contains zero `run_in_executor` calls.
- Honored D-08 (test-only, zero production change), D-08a (await-shaped wedge, not a CPU spin), and D-09 (no callback timeout/watchdog added to production).

## Task Commits

Each task was committed atomically:

1. **Task 1: Live-scheduler hanging-callback isolation proof** - `a68de01` (test)
2. **Task 2: D-08b executor-sharing audit assertion** - `c1ac147` (test)

_TDD note: this is a test-only plan re-proving an existing production property, so each task is a single `test(...)` commit — the proofs pass against the unchanged isolation path (the GREEN target already exists from Phases 15-17)._

## Files Created/Modified
- `tests/test_scheduler.py` - Added `test_hanging_callback_never_stops_live_briefing`: a real `BackgroundScheduler` sentinel job (sub-second `IntervalTrigger`) fires within a 5s deadline poll while `panel.dispatch_spec` is monkeypatched to `await asyncio.Event().wait()` and `on_command` is driven on a daemon thread that never returns.
- `tests/test_dispatch.py` - Added `test_briefing_path_not_on_default_executor`: rglobs `weatherbot/` and asserts `run_in_executor(None, …)` call sites equal exactly `["interactive/dispatch.py"]`, and that `weatherbot/scheduler/` has zero `run_in_executor` references.

## Decisions Made
- **Await-shaped wedge (D-08a):** the hang uses `await asyncio.Event().wait()`, documented in the test docstring with the rationale (all blocking panel work is already off-loop, so a never-completing await is the realistic wedge; a `while True: pass` would prove GIL-throttling instead — Pitfall 3).
- **Wedge at the dispatch seam, not the handler:** `_stub_handler` swaps the registry handler which runs inside the executor thread — hanging there would not model an await-level loop wedge. Monkeypatching `panel.dispatch_spec` hangs the `on_command` coroutine at the `await` itself, inside the inherited non-propagating envelope.
- **Structural audit over runtime introspection (Pitfall 4):** APScheduler populates its executor pool only after `start()` and exposes it via private internals; a source-level structural assertion is both more robust and a clearer regression tripwire. No bounded executor (Option C) was introduced — the audit came back clean as expected.
- **Self-contained stand-ins:** `tests/` has no `__init__.py`, so cross-importing the `test_panel.py` harness is fragile; the new scheduler test defines minimal local `_FakeHolder`/`_FakeConfig`/`_SpyCache` and an inline `MagicMock` interaction instead.

## Deviations from Plan

None - plan executed exactly as written. Both `<automated>` verification commands pass, the full suite is green (637 passed), and the `git diff --name-only` production-change gate shows only `tests/test_scheduler.py` and `tests/test_dispatch.py` (zero `weatherbot/` change, D-08 satisfied).

## Issues Encountered
None.

## Known Stubs
None — these are pure test additions proving an existing production property; no placeholder values, no unwired data sources.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ROADMAP SC#1 (isolation re-proof) for the interaction path is satisfied: a hanging panel callback fired concurrently with a live `BackgroundScheduler` briefing leaves the briefing firing on time and the scheduler running, with no production change.
- The D-08b coupling audit is clean — the only genuine cross-thread coupling (the asyncio default executor) is panel-only.
- Remaining Phase 20 polish (PANEL-12 selected-location indicator + emoji labels, PANEL-13 "updated" stamp) is independent of this isolation proof and proceeds in subsequent plans.

## Self-Check: PASSED

- `tests/test_scheduler.py::test_hanging_callback_never_stops_live_briefing` — FOUND, PASSES
- `tests/test_dispatch.py::test_briefing_path_not_on_default_executor` — FOUND, PASSES
- Commit `a68de01` — FOUND
- Commit `c1ac147` — FOUND
- Full suite: 637 passed
- Production-change gate: only `tests/` modified (D-08 satisfied)

---
*Phase: 20-isolation-hardening-polish*
*Completed: 2026-06-26*
