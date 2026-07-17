---
phase: 35-cleanup-sweep
plan: 02
subsystem: ops
tags: [cleanup, dead-code, F46, F92, HARD-CLEAN-01]
requires:
  - 35-01  # Wave-0 dead-code drift-back gate (test_dead_code_removed.py)
provides:
  - "ops/pidfile.py free of the dead F46 _argv_is_weatherbot guard copy"
  - "ops/selfcheck.py free of the discarded F92 is_transient(exc) call"
affects:
  - weatherbot/ops/pidfile.py
  - weatherbot/ops/selfcheck.py
  - tests/test_golden_coverage_fill.py
tech-stack:
  added: []
  patterns:
    - "Behavior-preserving dead-code removal (D-06): full-suite-green is the sufficient guard when the removed symbol has zero production callers"
key-files:
  created: []
  modified:
    - weatherbot/ops/pidfile.py
    - weatherbot/ops/selfcheck.py
    - tests/test_golden_coverage_fill.py
decisions:
  - "F46: removed the WB dead COPY of the -m guard; did NOT port the hub's corrected -m match (H01, human-gated, out of scope)"
  - "F92: pruned the now-unused is_transient import after deleting the discarded call; is_auth_failure retained (still classifies the 401/403 branch)"
metrics:
  duration: 2min
  completed: 2026-07-13
status: complete
---

# Phase 35 Plan 02: Cleanup Sweep — Dead ops-cluster code (F46 + F92) Summary

Removed the two genuinely-open dead-code items in the ops cluster: the dead WeatherBot copy of the `-m` PID guard `_argv_is_weatherbot` (F46, ops/pidfile.py) plus its exclusive test, and the result-discarding `is_transient(exc)` call (F92, ops/selfcheck.py). Both removals are behavior-preserving — the full suite stays green (exit 0) with no regression test needed, because neither symbol had a production caller.

## What Was Built

- **Task 1 (F46):** Deleted the entire `_argv_is_weatherbot` function from `weatherbot/ops/pidfile.py`. Confirmed via grep it had zero production callers (only its own def + the one exclusive test). Removed `test_argv_is_weatherbot_empty_and_forms` from `tests/test_golden_coverage_fill.py` — it exercised only the dead function, no live path (D-05). The `Path` import stays (used by `write_pid_atomic`/`read_pid`/`_read_proc_cmdline`). The live PID guard remains the hub's `_argv_matches_marker` (H01), untouched. Commit `fe6fe8d`.

- **Task 2 (F92):** Removed the standalone discarded `is_transient(exc)` statement (selfcheck.py:142) and its two explanatory comment lines. Both branches of the `except Exception` arm already return `NETWORK_NOT_READY` regardless, so removal is byte-identical in classification output. Pruned the now-unused `is_transient` import (ruff-confirmed F401), keeping `is_auth_failure` which still classifies the 401/403 branch. The `is_auth_failure` branch and the `NETWORK_NOT_READY` return path are unchanged. Commit `6eb76b6`.

## Verification

- `grep -rc "_argv_is_weatherbot" weatherbot/ tests/` → 0 across all files.
- `uv run pytest tests/test_golden_coverage_fill.py -q` → 38 passed.
- `uv run pytest tests/test_ops_selfcheck.py -q` → 17 passed.
- `uv run ruff check weatherbot/ops/selfcheck.py` → All checks passed (no unused-import error).
- `uv run pytest tests/test_dead_code_removed.py -q` (Wave-0 drift-back gate) → 4 passed.
- `uv run pytest -q` → exit 0, 891 passed. The "2 snapshots failed" line is the known pre-existing syrupy quirk (trust the exit code, not the snapshot summary line).
- `git diff --name-only` on both tasks showed no `yahir_reusable_bot/` or `../Reusable/` file — hub boundary untouched.

## Deviations from Plan

None — plan executed exactly as written. The optional import prune anticipated in Task 2 was required (ruff flagged `is_transient` as F401 after the discarded call was deleted) and applied per the plan's conditional instruction.

## Self-Check: PASSED

- FOUND: weatherbot/ops/pidfile.py (F46 symbol removed)
- FOUND: weatherbot/ops/selfcheck.py (F92 discarded call removed)
- FOUND: tests/test_golden_coverage_fill.py (orphaned F46 test removed)
- FOUND commit: fe6fe8d
- FOUND commit: 6eb76b6
