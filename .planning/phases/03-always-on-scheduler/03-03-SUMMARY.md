---
phase: 03-always-on-scheduler
plan: 03
subsystem: scheduler
tags: [daemon, apscheduler, catch-up, dst, idempotency, cli]
requires:
  - "weatherbot/scheduler/days.py::parse_days + Schedule.day_of_week/parsed_time (Plan 01)"
  - "weatherbot/weather/store.py::was_sent/record_sent (Plan 01)"
  - "weatherbot/scheduler/context.py::ScheduleContext + schedule_placeholders (Plan 02)"
  - "weatherbot/cli.py::send_now(..., schedule_ctx=) (Plan 02)"
provides:
  - "weatherbot/scheduler/catchup.py::plan_catchup + MissedSlot + _fires_on (pure missed-send planner)"
  - "weatherbot/scheduler/daemon.py::run_daemon + fire_slot (foreground lifecycle + per-fire callback)"
  - "weatherbot --run CLI branch (foreground always-on scheduler)"
  - "scheduler barrel exports: run_daemon, plan_catchup, MissedSlot"
affects:
  - "weatherbot/cli.py (added --run flag + dispatch branch)"
  - "weatherbot/scheduler/__init__.py (additive barrel exports)"
tech-stack:
  added: ["apscheduler 3.11.2 (BackgroundScheduler + CronTrigger) — first runtime use"]
  patterns:
    - "Config-as-jobs: one CronTrigger per enabled (location, slot) at the location's own IANA tz"
    - "Recovery owned by the sent-log + catch-up scan, not APScheduler misfire (misfire_grace_time=None)"
    - "Pure clock-injected planner (now_utc + was_sent reader injected) for deterministic DST tests"
    - "Per-job try/except isolation so one bad slot cannot crash the scheduler thread"
    - "Lazy import to break the cli<->daemon cycle"
key-files:
  created:
    - weatherbot/scheduler/catchup.py
    - weatherbot/scheduler/daemon.py
  modified:
    - weatherbot/scheduler/__init__.py
    - weatherbot/cli.py
    - tests/test_scheduler.py
decisions:
  - "GRACE=90min is a hardcoded module constant in catchup.py, never read from config (D-04)"
  - "_announce_schedule derives next_run_time from the CronTrigger pre-start (a not-yet-started APScheduler job exposes no next_run_time attribute)"
  - "daemon imports send_now lazily inside fire_slot to break the cli<->daemon import cycle"
metrics:
  duration: 5min
  completed: 2026-06-10
  tasks: 3
  files: 5
---

# Phase 3 Plan 03: Daemon Spine Summary

The always-on scheduler is realized: `weatherbot --run` registers one APScheduler `CronTrigger`
job per enabled `(location, schedule entry)` at each location's own IANA timezone, announces the
schedule with computed next-run times, runs a 90-minute startup catch-up scan, and blocks in the
foreground until SIGTERM/Ctrl-C with clean shutdown — completing SCHD-05/SCHD-06 and realizing
SCHD-03 DST exactly-once.

## What Was Built

**Task 1 — Pure catch-up planner (`weatherbot/scheduler/catchup.py`):**
`plan_catchup(config, was_sent, now_utc=None)` is a side-effect-free planner that returns the
slots whose local scheduled time passed less than 90 minutes ago today, are due (day-of-week
matches), and are not already in the sent-log. `GRACE = timedelta(minutes=90)` is a hardcoded
module constant (D-04). `_fires_on` is driven from the same normalized `day_of_week` string the
live `CronTrigger` consumes (via `Schedule.day_of_week` → `parse_days`), so the planner and the
trigger never disagree (Pitfall 3, Monday-first `date.weekday()` Mon=0). `MissedSlot` carries the
tz-aware `scheduled_dt` and the `local_date` dedup-key component. The module is APScheduler-free —
recovery is owned by the sent-log, not the scheduler. Clock and reader are injected, mirroring
`Forecast.from_payloads`, so the DST spring-forward (2026-03-08) and fall-back (2026-11-01) tests
need no wall-clock waits.

**Task 2 — Daemon spine (`weatherbot/scheduler/daemon.py`):**
`fire_slot(...)` is the single callback shared by the live cron job and the catch-up scan: it
checks `was_sent` before delivering (D-07), builds a `ScheduleContext`, calls `send_now(...)`
(which fetches CURRENT weather, so a recovered late send carries live data — D-05), and calls
`record_sent` ONLY when `result.ok` (mark-after-success). The whole body is wrapped in a
try/except that logs and returns `None` so one bad slot cannot crash the scheduler thread
(T-03-07). `run_daemon(...)` registers jobs (`misfire_grace_time=None`, per-location `timezone=`),
announces them, runs the catch-up scan, starts the scheduler, then blocks on a `threading.Event`
with a SIGTERM handler + KeyboardInterrupt catch and `scheduler.shutdown(wait=False)`. The barrel
now additively exports `run_daemon`, `plan_catchup`, `MissedSlot` (kept `parse_days`).

**Task 3 — `weatherbot --run` CLI branch (`weatherbot/cli.py`):**
A `--run` store_true flag (mirroring `--check`) dispatches to a branch that loads+validates config,
loads settings, prepares the sent-log DB dir, and calls `run_daemon(...)`. It does NOT
self-daemonize (D-09). `--send-now`/`--check`/`--geocode` are unchanged.

## Verification

- `uv run pytest -q` — 128 passed (full suite; no regression in send-now/check/geocode/config/store/renderer).
- `uv run pytest tests/test_scheduler.py -q` — 19 passed (catch-up window, DST exactly-once, days-match across all 7 weekdays, fire_slot record/idempotent/late-note/isolation, per-tz registration, --run dispatch).
- `uv run python -c "import weatherbot.cli; import weatherbot.scheduler.daemon; import weatherbot.scheduler.catchup"` — exits 0 (no circular import).
- `grep -v '^#' weatherbot/scheduler/daemon.py | grep -c "appid\|webhook_url"` — 0 (outcome-only logging, T-04-01).
- apscheduler 3.11.2 (stable 3.x line, not 4.x).
- ruff check + ruff format --check — clean.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_announce_schedule` read `job.next_run_time` on a not-yet-started scheduler**
- **Found during:** Task 2 (test_jobs_registered_per_location_tz / GREEN)
- **Issue:** APScheduler 3.x only computes/exposes `Job.next_run_time` AFTER `scheduler.start()`. The plan's announce runs BEFORE start (so the log reads cleanly), so `getattr(job, "next_run_time", None)` would always be `None` and the announce would log a useless `next_run_time=None`.
- **Fix:** `_announce_schedule` now prefers a running scheduler's computed value but falls back to `job.trigger.get_next_fire_time(None, datetime.now(tz))` — the tz-aware next fire derived straight from the CronTrigger. The test asserts the trigger-derived next fire is tz-aware in the location's zone.
- **Files modified:** `weatherbot/scheduler/daemon.py`, `tests/test_scheduler.py`
- **Commit:** 0b2d69d

**2. [Rule 3 - Blocking] cli<->daemon import cycle on a cold `import weatherbot.cli`**
- **Found during:** Task 3 (import-cycle acceptance check)
- **Issue:** `weatherbot.config.models` imports `weatherbot.scheduler.days`, which runs the scheduler package `__init__` (now exporting `run_daemon` from `daemon`); `daemon` had a top-level `from weatherbot.cli import send_now`, and `cli` imports `weatherbot.config` — a cycle that raised `ImportError: cannot import name 'send_now' from partially initialized module`. (The pytest run masked it because of import ordering; a cold `import weatherbot.cli` failed.)
- **Fix:** Moved daemon's `from weatherbot.cli import send_now` to a lazy import inside `fire_slot` (the only place it is used), and kept the `--run` branch's `run_daemon` import local-in-branch. The barrel can now eagerly import `daemon` safely (daemon no longer touches cli at module top).
- **Files modified:** `weatherbot/scheduler/daemon.py`, `weatherbot/cli.py`
- **Commit:** 5fe7e1e

## Threat Surface

All threat-register mitigations applied: outcome-only logging in daemon (T-04-01, grep-gated 0
secrets), per-job exception isolation (T-03-07, `test_fire_slot_isolates_exception`), and the
`(location, send_time, local_date)` idempotency key for DST/restart double-send prevention
(T-03-08, `test_fire_slot_idempotent_double_fire` + `test_dst_exactly_once`). No new security
surface introduced beyond the plan's `<threat_model>` — `--run` is a local foreground daemon with
no network listener.

## Commits

- ff76590: test(03-03): failing tests for plan_catchup + _fires_on (RED)
- 1c3cb3a: feat(03-03): pure catch-up planner (GREEN)
- 8f2711d: test(03-03): failing tests for fire_slot + run_daemon registration (RED)
- 0b2d69d: feat(03-03): daemon spine run_daemon + fire_slot (GREEN, incl. next_run_time fix)
- 5fe7e1e: feat(03-03): wire weatherbot --run into the CLI (incl. import-cycle fix)

## Self-Check: PASSED

All created files exist on disk; all 5 task commits present in git history.
