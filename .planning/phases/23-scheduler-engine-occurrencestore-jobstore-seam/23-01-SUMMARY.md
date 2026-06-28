---
phase: 23-scheduler-engine-occurrencestore-jobstore-seam
plan: 01
subsystem: yahir_reusable_bot (module extraction)
tags: [scheduler, ports, protocol, extraction, apscheduler, exactly-once]
requires:
  - yahir_reusable_bot/ports/alerts.py (AlertSink clone recipe)
  - yahir_reusable_bot/channels/__init__.py (barrel shape)
  - apscheduler (BackgroundScheduler.add_job)
provides:
  - SchedulerEngine (thin registrar: register/remove/list_live_ids)
  - OccurrenceStore Protocol (claim/was_fired/release)
  - JobStore Protocol + MemoryJobStore impl
  - Wave-0 job-options read-back oracle (test_scheduler_engine.py)
affects:
  - Plan 02 daemon rebind (consumes SchedulerEngine; the read-back oracle gates it)
tech-stack:
  added: []
  patterns:
    - "Thin non-owning registrar over host-owned scheduler (D-15)"
    - "Centralize-once invariant kwargs to prevent drift (D-03)"
    - "@runtime_checkable structural Protocol, no subclassing (D-08)"
    - "Define-only port ships unconsumed (D-06a / Phase-22 AlertSink precedent)"
key-files:
  created:
    - yahir_reusable_bot/scheduler/engine.py
    - yahir_reusable_bot/scheduler/__init__.py
    - yahir_reusable_bot/ports/occurrence.py
    - yahir_reusable_bot/ports/jobstore.py
    - tests/test_scheduler_engine.py
    - tests/test_ports.py
  modified:
    - yahir_reusable_bot/ports/__init__.py
decisions:
  - "Bare add_job default observed via start(paused=True), not pending read-back — APScheduler defers default materialization until the scheduler processes its queue"
metrics:
  duration_min: 6
  tasks_completed: 3
  files_touched: 7
  tests_added: 8
  completed: 2026-06-28
status: complete
---

# Phase 23 Plan 01: Scheduler Engine + OccurrenceStore + JobStore Seam Summary

Extracted the app-code-free module half of the scheduler seam: a `SchedulerEngine` thin registrar that bakes APScheduler's 4 copy-pasted invariant `add_job` kwargs into one place, plus `OccurrenceStore`/`JobStore` `@runtime_checkable` Protocols (with `MemoryJobStore`) that ship define-only per D-06a, guarded by a Wave-0 job-options read-back oracle.

## What Was Built

- **`SchedulerEngine`** (`scheduler/engine.py`) — non-owning facade over a host-built scheduler. `register(job_id, trigger, callback, *, args, kwargs, replace_existing)` forwards to `add_job` with `misfire_grace_time=None`, `coalesce=True`, `max_instances=1` baked in (D-03). `remove(job_id)` and `list_live_ids()` round out the surface. Owns no `start`/`shutdown` (D-15); trigger/callback/args/kwargs pass through opaquely (D-01/D-05); no cron/interval/date sugar (D-02).
- **`scheduler/__init__.py`** — barrel cloned from `channels/__init__.py`, re-exports `SchedulerEngine`, sibling-import only.
- **`OccurrenceStore`** (`ports/occurrence.py`) — `@runtime_checkable` Protocol cloning the `AlertSink` recipe. Names the full claim lifecycle (`claim`/`was_fired`/`release`) with neutral params (`handle`/`key`/`occurrence`); the store's domain-noun key is renamed `key` to stay litmus-clean. Structurally satisfied by the host's untouched `INSERT OR IGNORE` adapter (D-08).
- **`JobStore` + `MemoryJobStore`** (`ports/jobstore.py`) — Protocol whose docstring is the payload: the 3 serialization constraints (importable callback, picklable identity-style args, fire-time re-resolved keyword data) plus the named-but-unbuilt durable-store boundary (D-13) describing relocation of live runtime handles to a fire-time registry. `MemoryJobStore` is the define-only shipped impl that never serializes.
- **`ports/__init__.py`** — extended to re-export `OccurrenceStore`, `JobStore`, `MemoryJobStore`.
- **`tests/test_scheduler_engine.py`** — briefing-shaped read-back asserts all 3 invariant options; bare `add_job` default `max_instances == 1` pinned (A1); `list_live_ids()`/`remove()` covered.
- **`tests/test_ports.py`** — both Protocols `runtime_checkable`; instance-based structural satisfaction (Pitfall 6); `MemoryJobStore()` instantiates.

## Verification

- `uv run pytest tests/test_scheduler_engine.py tests/test_ports.py -q` → 8 passed.
- `uv run pytest tests/test_import_hygiene.py -q` → 8 passed (grimp confirms zero app-code imports in the new files; litmus confirms no weather noun in any new signature — gates auto-scaled by directory prefix, no gate edit).
- `uv run pytest -q` → **748 passed** (was 740 before these 8 tests; zero new failures).
- Import sanity: `from yahir_reusable_bot.scheduler import SchedulerEngine; from yahir_reusable_bot.ports import OccurrenceStore, JobStore, MemoryJobStore` succeeds.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Bare `add_job` default test could not read `max_instances` on a non-started scheduler**
- **Found during:** Task 3 (RED run).
- **Root cause:** APScheduler defers applying `add_job` option defaults until the scheduler processes its pending queue. On a non-started `BackgroundScheduler`, a job added WITHOUT explicit options is `pending=True` and has no `max_instances` attribute at all (`AttributeError`), so the plan's literal "register bare + read back on a non-started scheduler" cannot observe the default. (The engine read-back tests are unaffected — the engine passes the options EXPLICITLY, so they materialize immediately even while pending.)
- **Fix:** The bare-default test calls `scheduler.start(paused=True)`, which processes the pending queue and materializes the defaults WITHOUT firing any job (paused + far-future trigger), staying fast and deterministic. Added a bonus assert that bare `misfire_grace_time` defaults to `1` (NOT `None`) — concrete evidence of WHY the engine must bake `misfire_grace_time=None` in (D-03). The plan's "never call `scheduler.start()`" guidance was aimed at avoiding wall-clock waits in the engine read-back tests; `start(paused=True)` honors that intent (no firing, no sleep).
- **Files modified:** tests/test_scheduler_engine.py
- **Commit:** 0ec0523

## Deferred Issues (out of scope — see deferred-items.md)

- Pre-existing syrupy "2 snapshots failed" report-summary line — present on the full suite BEFORE any Phase-23 test files (verified via `--ignore` of both new files: still `740 passed, 2 snapshots failed`). These are syrupy "unused snapshot" detections, not test failures (`0 failed`), and are unrelated to this extraction. Logged for separate triage.

## Self-Check: PASSED

- FOUND: yahir_reusable_bot/scheduler/engine.py
- FOUND: yahir_reusable_bot/scheduler/__init__.py
- FOUND: yahir_reusable_bot/ports/occurrence.py
- FOUND: yahir_reusable_bot/ports/jobstore.py
- FOUND: yahir_reusable_bot/ports/__init__.py (modified)
- FOUND: tests/test_scheduler_engine.py
- FOUND: tests/test_ports.py
- FOUND commit a6c7abe (Task 1: SchedulerEngine + barrel)
- FOUND commit f1886f0 (Task 2: ports + MemoryJobStore)
- FOUND commit 0ec0523 (Task 3: Wave-0 tests)
