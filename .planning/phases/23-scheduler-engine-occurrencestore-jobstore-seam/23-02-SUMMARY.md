---
phase: 23-scheduler-engine-occurrencestore-jobstore-seam
plan: 02
subsystem: weatherbot.scheduler (daemon rebind — consuming half of the seam)
tags: [scheduler, daemon, apscheduler, seam, adapt-dont-rewrite, byte-identical]
requires:
  - yahir_reusable_bot.scheduler.SchedulerEngine (register/remove/list_live_ids — Wave 1)
provides:
  - "daemon.py: all 4 job registrations (briefing/forecast/uvmonitor/heartbeat) routed through engine.register"
  - "daemon.py: _reconcile_jobs read-throughs routed through engine.list_live_ids()/remove()"
  - "_register_jobs enumeration loop preserved app-side as the Phase-24 desired_jobs seed"
affects:
  - Phase 24 (desired_jobs seed + reconcile relocation build on this app-side enumeration boundary)
tech-stack:
  added: []
  patterns:
    - "Adapt-don't-rewrite: in-place call-site swap, enumeration loop stays app-side (D-15)"
    - "Thin non-owning registrar; app keeps scheduler lifecycle (D-15/A4)"
    - "Invariant kwargs centralized in engine.register, removed from all call sites (D-03)"
    - "Module-side import inside daemon.py, never at the package barrel top (Pitfall 4 / PEP-562)"
    - "Internal-id (__heartbeat__/__uvmonitor__) exclusion stays an app-side convention (D-04)"
key-files:
  created:
    - .planning/phases/23-scheduler-engine-occurrencestore-jobstore-seam/23-02-SELF-UAT.md
  modified:
    - weatherbot/scheduler/daemon.py
decisions:
  - "Read-only scheduler.get_jobs() reads OUTSIDE _reconcile_jobs (announce-time count at ~1039, daemon-started log at ~1560/1562) left byte-identical — the plan scopes the rebind to the reconcile read-throughs only; D-16 keeps run_daemon/_announce_schedule bodies untouched."
metrics:
  duration_min: 3
  tasks_completed: 3
  files_touched: 2
  tests_added: 0
  completed: 2026-06-28
status: complete
---

# Phase 23 Plan 02: Daemon Rebind onto SchedulerEngine Summary

Adapted (did not rewrite) `weatherbot/scheduler/daemon.py` so every WeatherBot job — briefing, forecast, uvmonitor, heartbeat — registers through `SchedulerEngine.register(...)` and `_reconcile_jobs` reads/removes through `engine.list_live_ids()`/`engine.remove()`, all byte-identically: the full 748-test suite and every Phase-21 golden stay green with zero non-empty snapshot diff.

## What Was Built

- **Module-side import** — `from yahir_reusable_bot.scheduler import SchedulerEngine` added INSIDE `daemon.py`'s import block (NOT at `weatherbot/scheduler/__init__.py` top). The barrel runs during `weatherbot.config.models`'s `parse_days` import via the PEP-562 lazy `run_daemon` export; an eager engine import there could re-introduce the cycle the lazy export dodges (Pitfall 4).
- **`_register_jobs` split (D-15)** — builds `engine = SchedulerEngine(scheduler)` once at the top; the enumeration loop (`for location ... for slot ...`) STAYS app-side as the Phase-24 `desired_jobs` seed. Both the briefing-loop and forecast-loop `scheduler.add_job(...)` calls become `engine.register(job_id, trigger, callback, args=, kwargs=, replace_existing=)`. The same `CronTrigger` object the caller builds passes straight through (D-01 — schedule-plan golden unchanged). The 3 invariant kwargs (`misfire_grace_time=None`, `coalesce=True`, baked `max_instances=1`) disappear from the call sites — they now live only in `engine.register`.
- **uvmonitor + heartbeat (D-04)** — both internal `IntervalTrigger` jobs re-register through the engine. The uvmonitor site's explicit `max_instances=1` is dropped (now baked); heartbeat (which omitted it) keeps the byte-identical default-of-1. Each builds a thin local `SchedulerEngine(scheduler)` over the same host scheduler — no change to which scheduler instance is used.
- **`_reconcile_jobs` read-through rebind (D-04, body otherwise untouched)** — live ids now come from `{jid for jid in engine.list_live_ids() if jid not in ("__heartbeat__", "__uvmonitor__")}` (the internal-id exclusion stays an app-side convention the engine never learns); removals go through `engine.remove(job_id)`. The diff logic, the `_register_jobs(..., replace_existing=True)` add/replace delegation, and the returned `(added, removed, changed, unchanged)` counters are byte-identical.
- **`23-02-SELF-UAT.md`** — Gate-1 self-UAT log: per-criterion command + evidence + verdict; live `yahir-mint` restart-catch-up recorded as a deferred Gate-2 obligation.

## What Was NOT Touched (prohibitions honored, git-proven)

- `fire_slot` / `fire_forecast_slot` bodies — unchanged (D-06a define-only; no `OccurrenceStore` instance threaded; they keep calling concrete `claim_slot`/`was_sent`/`release_claim`).
- `weatherbot/scheduler/catchup.py` and `weatherbot/weather/store.py` — `git diff` empty (D-14 `was_sent(name, time, date)` arg order intact; D-09 `sent_log` rows / `INSERT OR IGNORE` untouched).
- `_desired_job_ids`, `_restore_jobs`, `_do_reload`, and the `_reconcile_jobs` body — no diff hunks (D-16, Phase 24).
- `run_daemon` startup ordering (announce → register → heartbeat → uvmonitor → catch-up → `scheduler.start()`) — byte-identical; the app still constructs and `start()`/`shutdown()`s the scheduler (engine is a thin registrar).

## Verification

- `uv run pytest -q` → **748 passed**, 0 test failures. (The summary line "2 snapshots failed" is the pre-existing syrupy *unused-snapshot* artifact documented in 23-01-SUMMARY's deferred-items — present before any Phase-23 work, `0 failed` tests, unrelated to this rebind.)
- `uv run pytest tests/test_golden_schedule.py tests/test_golden_db.py tests/test_scheduler.py tests/test_reload.py -q` → 79 passed, **4 snapshots passed (byte-identical)** — schedule-plan, sent_log DB rows, all DST/catch-up, exactly-once-across-reload.
- `uv run pytest tests/test_import_hygiene.py -q` → 8 passed (grimp + isolated-import smoke + litmus).
- `uv run pytest tests/test_scheduler_engine.py tests/test_ports.py -q` → 8 passed (Wave-0 read-back oracle, proving the baked `max_instances=1` is byte-identical).
- `git diff weatherbot/scheduler/catchup.py weatherbot/weather/store.py` → empty.

## Deviations from Plan

None — plan executed exactly as written. All three tasks completed in order; no Rule 1–4 deviations were required.

## Decisions Made

- The three read-only `scheduler.get_jobs()` reads OUTSIDE `_reconcile_jobs` (the announce-time job count near L1039 and the two `daemon started` log lines near L1560/L1562) were left byte-identical. The plan scopes the engine rebind to (a) the 4 registration sites and (b) the two `_reconcile_jobs` read-throughs; D-16 keeps `run_daemon`/`_announce_schedule` bodies untouched, so rebinding those purely-read counting sites was out of scope.

## Self-Check: PASSED

- FOUND: weatherbot/scheduler/daemon.py (modified)
- FOUND: .planning/phases/23-scheduler-engine-occurrencestore-jobstore-seam/23-02-SELF-UAT.md
- FOUND commit e7438b5 (Task 1: 4 registrations → engine.register)
- FOUND commit ed6e213 (Task 2: reconcile read-throughs → engine)
- FOUND commit 01820f3 (Task 3: self-UAT log)
