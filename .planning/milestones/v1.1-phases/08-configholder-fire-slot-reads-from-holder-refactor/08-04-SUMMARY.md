---
phase: 08-configholder-fire-slot-reads-from-holder-refactor
plan: 04
subsystem: scheduler
tags: [configholder, fire_slot, hot-reload-seam, single-snapshot-per-fire, daemon]
requirements-completed: none (prerequisite — unblocks CFG-01/CFG-05 in Phase 9)
requires:
  - "weatherbot/config/holder.py (ConfigHolder.current()/replace() — Plan 03)"
  - "weatherbot/config/models.py (frozen Config snapshots — Plan 02)"
provides:
  - "fire_slot(holder=, config=) — single-snapshot-per-fire read with override-wins"
  - "holder-threaded _register_jobs/_announce_schedule/_run_catchup"
  - "run_daemon constructs one ConfigHolder and threads it into the three readers"
affects:
  - "Phase 9 reload engine (replace() now changes what every live job renders)"
tech-stack:
  added: []
  patterns:
    - "single-read-per-fire: resolve the config snapshot ONCE at the top of fire_slot and thread that same object through reliability budget read + send_now(config=snapshot)"
    - "override-wins resolution: config= beats holder.current(); raise ValueError if both None"
    - "holder-in-kwargs: add_job carries {\"holder\": holder} so an unchanged job re-reads holder.current() at every fire"
key-files:
  created: []
  modified:
    - "weatherbot/scheduler/daemon.py"
    - "tests/test_scheduler.py"
    - "tests/test_reliability.py"
decisions:
  - "[08-04] fire_slot resolves the snapshot via override-wins (config= beats holder.current()); both-None raises a clear ValueError so the contract is explicit, not a silent AttributeError."
  - "[08-04] ConfigHolder is imported at daemon module top-level (cycle-free: holder.py imports models only under TYPE_CHECKING) for the run_daemon runtime construction; removed from the TYPE_CHECKING block to avoid a redefinition."
  - "[08-04] catchup.py left byte-identical — _run_catchup reads holder.current() once to feed the PURE-INPUT plan_catchup planner, then fires each missed slot with holder=holder so each recovered send resolves the live snapshot at its own fire time (Assumption A3)."
metrics:
  duration: "~9 min"
  completed: "2026-06-16"
  tasks: 2
  files: 3
---

# Phase 8 Plan 04: ConfigHolder fire_slot Refactor Summary

Wired the daemon to read live config from the `ConfigHolder` at fire time: `fire_slot` now takes `holder=` plus an optional `config=` override, reads one snapshot per fire, and threads that single object through the reliability budget read and `send_now(config=snapshot)` so a mid-fire `replace()` can never tear a delivery; `_register_jobs`/`_announce_schedule`/`_run_catchup` and `run_daemon` all source config from the holder, and `add_job` now carries `{"holder": holder}` instead of a baked-in config — closing the seam the whole hot-reload milestone rests on.

## What Was Built

- **`fire_slot` single-snapshot read (D-01 / Pitfall #9):** New keyword-only `holder: ConfigHolder | None = None` and `config: Config | None = None`. At the top of the try-body: `snapshot = config if config is not None else holder.current()`, with a `ValueError("fire_slot requires holder= or config=")` when both are None. The reliability budget read (`snapshot.reliability.*`) and the `send_now(config=snapshot)` forward both use that SAME object — never re-read — so a `replace()` landing mid-fire cannot mix an old budget with a new template.
- **Three holder-reading registrars (D-03):** `_register_jobs` takes `holder: ConfigHolder`, reads `holder.current()` once to enumerate jobs, and registers `kwargs={"holder": holder}`. `_announce_schedule` and `_run_catchup` likewise read `holder.current()` once at the top. The stable job `id=f"{name}|{time}|{days}"` and `_heartbeat_tick` are byte-identical (Phase 9's job-diff and the claim key depend on this).
- **`run_daemon` constructs one holder (Discretion #4):** A top-level `from weatherbot.config.holder import ConfigHolder` import (cycle-free) and `holder = ConfigHolder(config)` right after `stop = threading.Event()`, threaded into all three readers. `gate_until_healthy(config=config)` is left unchanged (not a per-fire reader; identical to `holder.current()` at startup).
- **Test callsites updated:** Both positional `_register_jobs(scheduler, cfg, ...)` callsites (in `test_scheduler.py` and `test_reliability.py`) now pass `ConfigHolder(cfg)`. The `fire_slot(config=...)` and `run_daemon(config=...)` callsites are unchanged — they keep working via the D-01 override path and run_daemon's internal holder.

## The Phase's Core Proof (now GREEN)

- `test_unchanged_job_renders_after_replace` — an UNCHANGED job renders `config_b` after `holder.replace(config_b)`.
- `test_inflight_job_keeps_snapshot` — an in-flight fire that already read its snapshot keeps `config_a` even when `replace(config_b)` lands mid-fire.
- `test_config_override_wins` — an explicit `config=config_a` beats a holder holding `config_b`.

## Threat Mitigations Applied

| Threat ID | Mitigation |
|-----------|------------|
| T-08-08 (mid-fire tear) | Single-read-per-fire: one `snapshot` threaded through reliability read + `send_now`. Proven by `test_inflight_job_keeps_snapshot`. |
| T-08-09 (stale captured config) | `kwargs={"holder": holder}` replaces `{"config": config}`; an unchanged job re-reads `holder.current()` every fire. Proven by `test_unchanged_job_renders_after_replace`. |
| T-08-10 (job-id disturbance) | `id=f"{name}|{time}|{days}"` left byte-identical (grep-verified, 1 occurrence). |
| T-08-02 (secret leak) | Holder carries `Config` only; `settings=` still threaded separately into `fire_slot`/`send_now`. |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Second `_register_jobs` positional callsite in tests/test_reliability.py**
- **Found during:** Task 1 (verify suite `tests/test_reliability.py` failed with `'Config' object has no attribute 'current'`).
- **Issue:** The plan stated there was a single `_register_jobs(scheduler, cfg, ...)` positional callsite (in `test_scheduler.py`). A second one exists in `tests/test_reliability.py::test_heartbeat_job_registered_with_slots` (line 627), which passed a `Config` positionally and broke once `_register_jobs` expected a holder. This blocked Task 1's own verify gate.
- **Fix:** Added `from weatherbot.config.holder import ConfigHolder` to `tests/test_reliability.py` and changed the callsite to `ConfigHolder(config)`. No assertion weakened — the test still asserts the heartbeat + slot jobs coexist (2 jobs).
- **Files modified:** tests/test_reliability.py
- **Commit:** df0bb86

## TDD Gate Compliance

This plan landed the GREEN phase of a multi-wave TDD cycle. The RED tests (`test_inflight_job_keeps_snapshot`, `test_unchanged_job_renders_after_replace`, `test_config_override_wins`) were authored in an earlier wave and were verified RED at this wave's start (3 failed, 223 passed, `TypeError: fire_slot() got an unexpected keyword argument 'holder'`). Task 1's `feat(08-04)` commit (df0bb86) and Task 2's `test(08-04)` commit (79e7545) turned them GREEN. The full suite is green at 226 (= 223 prior-green this wave + 3 integration tests). No `refactor` commit was needed.

## Verification

- `grep '"holder": holder' weatherbot/scheduler/daemon.py` matches; `grep '"config": config'` returns nothing.
- Stable id grep matches exactly once; `git diff --stat weatherbot/scheduler/catchup.py` empty (unchanged).
- `holder.current()` appears in fire_slot + all three readers (≥4 call occurrences).
- `.venv/bin/python -m pytest -q` → **226 passed, 0 failed**.

## Self-Check: PASSED

- FOUND: weatherbot/scheduler/daemon.py (holder-threaded)
- FOUND: tests/test_scheduler.py (ConfigHolder(cfg) callsite)
- FOUND: tests/test_reliability.py (ConfigHolder(config) callsite)
- FOUND commit: df0bb86 (feat — Task 1)
- FOUND commit: 79e7545 (test — Task 2)
