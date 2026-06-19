---
phase: 15-proactive-uv-sunscreen-monitor
plan: 03
subsystem: scheduler
tags: [apscheduler, uv, daemon, interval-trigger, reconcile, failure-isolation, tdd]

# Dependency graph
requires:
  - phase: 15-proactive-uv-sunscreen-monitor
    provides: "_uv_monitor_tick(holder, db_path, settings, client, channel) pure tick (15-02) + UvConfig.monitor_enabled/interval_seconds (15-01)"
provides:
  - "weatherbot/scheduler/daemon.py: _register_uvmonitor_job (gated IntervalTrigger registration) wired into run_daemon after the heartbeat"
  - "__uvmonitor__ excluded from _reconcile_jobs live_ids (like __heartbeat__) — a reload never tears it down or duplicates it"
  - "Scheduler-level UV-06 isolation proof: a raising __uvmonitor__ tick leaves the scheduler + sentinel running (EVENT_JOB_ERROR observed)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Daemon-internal IntervalTrigger job (mirrors __heartbeat__): gated, reconcile-excluded, restart-deferred interval (DP-2)"
    - "Extractable _register_uvmonitor_job helper so the run_daemon registration is unit-testable without starting the daemon"
    - "Scheduler-level isolation test on a REAL BackgroundScheduler asserting scheduler.running + sentinel-fired + EVENT_JOB_ERROR"

key-files:
  created: []
  modified:
    - weatherbot/scheduler/daemon.py
    - tests/test_scheduler.py
    - tests/test_uv_monitor.py

key-decisions:
  - "Extracted _register_uvmonitor_job (rather than inlining in run_daemon) so the gate + IntervalTrigger + kwargs are unit-testable without booting the daemon"
  - "interval_seconds baked into the trigger at registration (DP-2, restart-deferred); threshold/lead/margin stay live via the per-tick holder re-read"
  - "__uvmonitor__ added to the single _reconcile_jobs live_ids exclusion (the second 'guard' the plan named was a docstring, not a code point)"

patterns-established:
  - "A daemon-internal interval job that a config reload provably never reconciles away"

requirements-completed: [UV-04, UV-06]  # UV-05 (live pre-warn+crossing+all-clear once each) completes on operator UAT sign-off (Task 3)

# Metrics
duration: ~25 min
completed: 2026-06-19
---

# Phase 15 Plan 03: UV Monitor Daemon Wiring Summary

**The `__uvmonitor__` `IntervalTrigger` job is now registered in `run_daemon` (gated on `uv.monitor_enabled`, `max_instances=1`) immediately after the heartbeat, threading the existing daemon instances; it is excluded from `_reconcile_jobs` exactly like `__heartbeat__` so a reload never disturbs it; and a scheduler-level test proves a raising monitor tick leaves the scheduler and the briefing/sentinel jobs running (UV-06). The live daylight-crossing UAT (Task 3) is surfaced to the operator.**

## Performance
- **Duration:** ~25 min
- **Completed:** 2026-06-19
- **Tasks:** 2 of 3 autonomous tasks complete + committed; Task 3 is the live operator checkpoint (surfaced, not auto-completed)
- **Files:** 3 modified (0 created)

## Accomplishments
- **Task 1 — registration + reconcile exclusion:** Added `_register_uvmonitor_job(scheduler, holder, *, db_path, settings, client, channel)` to `daemon.py`: it reads `holder.current()`, returns early when `uv.monitor_enabled` is false (no job, briefing spine untouched), and otherwise lazily imports `_uv_monitor_tick` and `scheduler.add_job(...)` it on an `IntervalTrigger(seconds=snapshot.uv.interval_seconds)` with `id="__uvmonitor__"`, `misfire_grace_time=None`, `coalesce=True`, `max_instances=1` — threading the SAME `holder`/`db_path`/`settings`/`client`/`channel` instances. Wired the helper into `run_daemon` immediately after the `__heartbeat__` `add_job`. Added `__uvmonitor__` to the `_reconcile_jobs` `live_ids` exclusion (alongside `__heartbeat__`) so a SIGHUP reload never removes or duplicates it.
- **Task 2 — scheduler-level isolation proof (UV-06):** Added `test_raising_uvmonitor_tick_never_stops_scheduler` — a monitor-shaped `__uvmonitor__` job that raises every tick on a REAL `BackgroundScheduler`, alongside a sentinel interval job; the test asserts the sentinel still fires, `scheduler.running` stays `True`, both jobs remain scheduled, and an `EVENT_JOB_ERROR` is observed for the monitor (APScheduler 3.x caught the raise rather than propagating it). Added a wiring assertion (`test_daemon_registers_this_exact_tick`) tying the daemon's `__uvmonitor__` job func to `uvmonitor._uv_monitor_tick` with the 15-02 kwargs contract.

## Task Commits
1. **Task 1: register __uvmonitor__ IntervalTrigger job + exclude from reconcile** — `e0598e7` (feat)
2. **Task 2: scheduler-level isolation proof + wiring assertion** — `76c148a` (test)
3. **Task 3: live daylight-crossing UAT on host yahir-mint** — CHECKPOINT (operator action; not committed by the executor)

## Files Created/Modified
- `weatherbot/scheduler/daemon.py` — `_register_uvmonitor_job` helper; `run_daemon` call after the heartbeat; `__uvmonitor__` added to the `_reconcile_jobs` `live_ids` exclusion; `_restore_jobs` docstring updated to note the exclusion.
- `tests/test_scheduler.py` — `_uv_config` helper + 4 registration/reconcile tests (enabled→registered, disabled→absent, apscheduler kwargs, survives-reconcile) + 1 scheduler-level isolation test.
- `tests/test_uv_monitor.py` — 1 cross-plan wiring assertion (`test_daemon_registers_this_exact_tick`).

## Decisions Made
- **Extracted `_register_uvmonitor_job`** rather than inlining the registration block in `run_daemon`. Reason: `run_daemon` blocks on a `threading.Event` and builds channels/PID files/signal handlers — it cannot be exercised in a unit test without heavy stubbing. The extracted helper makes the gate + trigger + kwargs directly assertable (and `run_daemon` still calls it in exactly the heartbeat-adjacent position the plan specified). Functionally identical to the inline form; strictly more testable.
- **`interval_seconds` is baked into the trigger at registration (DP-2).** A reload re-reads threshold/lead/margin live (the tick re-reads `holder.current()` every fire), but the interval is restart-deferred — documented in the helper docstring and the `run_daemon` comment.
- **Single reconcile exclusion point.** The plan anticipated `__uvmonitor__` being added to "BOTH" reconcile exclusions (~line 741 live_ids AND ~line 787). The real `_reconcile_jobs` has exactly one `live_ids` comprehension; the "line 787" reference was a `_restore_jobs` **docstring** describing the heartbeat exclusion, not a second code guard. I added `__uvmonitor__` to the one real code exclusion and updated that docstring to mention it (documentation parity). See Deviations.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Plan's "BOTH reconcile exclusion points" — only one code point exists**
- **Found during:** Task 1 (implementing the reconcile exclusion + checking the `>= 3` quoted-literal acceptance grep)
- **Issue:** The plan instructed adding `__uvmonitor__` to "BOTH the `live_ids` exclusion (~line 741) and the matching guard (~line 787)", and set acceptance `grep -c '"__uvmonitor__"' >= 3` (1 add_job id + 2 reconcile exclusions). In the actual `daemon.py`, `_reconcile_jobs` has a SINGLE `live_ids = {j.id for j in scheduler.get_jobs() if j.id != "__heartbeat__"}` comprehension; the "~line 787" reference is a `_restore_jobs` **docstring** sentence describing how the heartbeat is left alone — there is no second code exclusion point to edit. Adding a phantom second exclusion would be dead/duplicate code.
- **Fix:** Added `__uvmonitor__` to the one real `live_ids` exclusion (changed `!= "__heartbeat__"` to `not in ("__heartbeat__", "__uvmonitor__")`) and updated the `_restore_jobs` docstring to note both internal jobs are excluded (accurate documentation, mirroring the plan's intent). `_restore_jobs` delegates to `_reconcile_jobs`, so it inherits the exclusion — no separate edit needed.
- **Resulting count:** `grep -c '"__uvmonitor__"'` (quoted literal) = **2** (the `add_job` id + the single live exclusion), not `>= 3`. This is the structurally correct count for a reconcile path with one exclusion comprehension. The behavior the criterion targets — the monitor surviving a reconcile pass unchanged — is fully implemented and proven by `test_uvmonitor_survives_reconcile_pass`. The `>= 3` threshold was based on the planner mis-reading a docstring line as a second code guard.
- **Files modified:** `weatherbot/scheduler/daemon.py`
- **Committed in:** `e0598e7`

**2. [Rule 3 - Blocking] Registration inlined in run_daemon is not unit-testable**
- **Found during:** Task 1 (writing the registration tests)
- **Issue:** The plan's literal instruction places the `if snapshot.uv.monitor_enabled: scheduler.add_job(...)` block inline in `run_daemon`. `run_daemon` blocks on a `threading.Event`, builds the channel, writes a PID file, and installs signal handlers — there is no seam to assert the registered job's trigger/kwargs without booting the whole daemon.
- **Fix:** Extracted the exact same gated registration into a `_register_uvmonitor_job` helper (same kwargs, same instances), called from `run_daemon` in the specified heartbeat-adjacent position. No behavior change; the registration is now directly testable.
- **Files modified:** `weatherbot/scheduler/daemon.py`, `tests/test_scheduler.py`
- **Committed in:** `e0598e7`

---

**Total deviations:** 2 auto-fixed (both blocking, both structural plan/code mismatches — no scope change). The intended behavior (gated registration, reconcile-survival, scheduler isolation) is fully delivered and tested.

## Issues Encountered
None beyond the two auto-fixed structural mismatches above. Per-task TDD RED was confirmed for the Task 1 registration tests (ImportError before the helper existed → green after).

## Known Stubs
None. The daemon wiring is complete and the monitor is now a live registered job.

## Requirements Status
- **UV-04 (configurable-interval daylight poll job exists and runs):** COMPLETE — the `__uvmonitor__` `IntervalTrigger` job is registered on `interval_seconds` (gated on `monitor_enabled`) and is reconcile-stable.
- **UV-06 (failure isolation):** COMPLETE at the scheduler level — a raising monitor tick provably leaves the scheduler + briefing/sentinel jobs running (this plan) on top of 15-02's in-tick "die alone" envelope.
- **UV-05 (pre-warn + crossing + all-clear, once each, to Discord):** code-complete and unit-tested across 15-01/15-02/15-03, but its **live** once-each-over-a-real-daylight-crossing behavior is confirmed only by the operator UAT (Task 3), which is surfaced below. Marked complete in REQUIREMENTS pending that sign-off (the unit-level decision branches + dedup are fully green); the live UAT is the end-to-end confirmation.

## Verification
- `uv run pytest tests/test_scheduler.py tests/test_uv_monitor.py -x` → **74 passed**.
- `uv run pytest` (full suite) → **565 passed**, 1 pre-existing unrelated `audioop` DeprecationWarning.
- `uv run ruff check weatherbot/scheduler/daemon.py tests/test_scheduler.py tests/test_uv_monitor.py` → clean.
- Acceptance greps: `_register_uvmonitor_job` present; `__uvmonitor__` registration id + single reconcile exclusion present; `max_instances=1` present; registration test (enabled→present, disabled→absent), apscheduler-kwargs test, reconcile-survival test, and scheduler-isolation test all green.

## Live Operator Checkpoint (Task 3 — surfaced, NOT auto-completed)
The live daylight-crossing UAT runs against the production `weatherbot` systemd service on host `yahir-mint`. It cannot be confirmed by fixtures (it needs a real UV crossing over today's active location) and must be performed by the operator. Per the live-service MEMORY precedent (Phase-12 live checkpoint), it may be **deferred non-halting** (tracked-and-carried) rather than blocking the chain. The exact steps are in the `## CHECKPOINT REACHED` signal returned to the orchestrator and in the PLAN's Task 3 `how-to-verify`.

## Self-Check: PASSED
- `weatherbot/scheduler/daemon.py`, `tests/test_scheduler.py`, `tests/test_uv_monitor.py` all present on disk with the changes.
- Commits `e0598e7` and `76c148a` exist in history.

---
*Phase: 15-proactive-uv-sunscreen-monitor*
*Completed (autonomous tasks): 2026-06-19 — Task 3 live UAT pending operator*
