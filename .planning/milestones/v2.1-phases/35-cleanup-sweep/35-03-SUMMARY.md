---
phase: 35-cleanup-sweep
plan: 03
subsystem: cli
tags: [cleanup, dead-code, latent-fix, accept-with-rationale]
status: complete
requires:
  - 35-01  # Wave-0 dead-code drift-back gate (F76 clause reddens on drift)
provides:
  - "weatherbot/cli.py cluster swept (F76 removed, F78 guarded, F77 accepted)"
affects:
  - weatherbot/cli.py
tech-stack:
  added: []
  patterns:
    - "# ACCEPTED (F##, v2.1): <rationale> in-code annotation (mirrors daemon.py noqa house-style)"
    - "explicit dispatch guard against implicit fallthrough (AssertionError on unreachable command)"
key-files:
  created: []
  modified:
    - weatherbot/cli.py
    - tests/test_cli.py
decisions:
  - "D-05/D-06 (F76): removed inert run_weather(verbose=...) param + call-site pass-through; live -v plumbing (main()/_configure_logging) untouched — behavior-preserving"
  - "D-01 (F78): send-now fallthrough guarded with an explicit `args.command != 'send-now'` AssertionError so a future command can't silently run the send pipeline"
  - "D-01/D-02 (F77): check exit-1 vs registry exit-2 divergence ACCEPTED-with-rationale via in-code # ACCEPTED (F77, v2.1) marker — no behavior change"
metrics:
  duration: ~5min
  completed: 2026-07-13
requirements:
  - HARD-CLEAN-01
  - HARD-CLEAN-02
---

# Phase 35 Plan 03: cli.py Cleanup Sweep Summary

Swept the `weatherbot/cli.py` cluster — removed the dead `verbose` param from `run_weather` (F76), added an explicit `send-now` dispatch guard against future fallthrough (F78), and annotated the intentional `check`/registry exit-code divergence as accepted (F77). All three changes are behavior-preserving; full suite stays green at 891 passed.

## What Was Built

- **F76 (dead-param removal, HARD-CLEAN-01):** Dropped the inert `verbose: bool = False` parameter from the `run_weather` signature (it was accepted but never read — the real `-v` level is applied in `main()` via `_configure_logging`). Removed the `verbose=args.verbose` pass-through at the `_cmd_weather` call site. The `-v/--verbose` argparse flag and `main()`/`_configure_logging` verbosity plumbing are untouched.
- **F78 (latent fix, HARD-CLEAN-02):** Added an explicit dispatch guard before the send-now pipeline. `send-now` reaches the send pipeline by fallthrough (it has no explicit `if args.command == "send-now"` arm), so a future subcommand lacking a `location` attr could have silently run the send pipeline. The guard `if args.command != "send-now": raise AssertionError(...)` makes the dispatch explicit. Behavior-preserving for every current command — `send-now` is the only command that falls through and it carries a `location` attr.
- **F77 (accept-with-rationale, HARD-CLEAN-02):** Annotated the `check` exit-1 vs registry exit-2 divergence with an in-code `# ACCEPTED (F77, v2.1): ...` marker at the `check` exit-1 site. Both per-command exit-code conventions are documented-intentional and a monitor keying on the exact code is hypothetical. Annotation-only, no behavior change.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Remove dead `verbose` param from run_weather + call site (F76) | e81eb21 | weatherbot/cli.py, tests/test_cli.py |
| 2 | Send-now dispatch guard (F78) + accept check/registry exit-code divergence (F77) | fa262da | weatherbot/cli.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated `_patched_run_weather` test shim to the pruned signature**
- **Found during:** Task 1
- **Issue:** The F76 removal broke `tests/test_cli.py:748` — its `_patched_run_weather` monkeypatch shim mirrored the old signature (accepted `verbose=False`) and passed `verbose=verbose` into the real `run_weather`. With the param removed, that call would raise `TypeError`.
- **Fix:** Removed `verbose=False` from the shim signature and `verbose=verbose` from its inner `run_weather(...)` call. The verbose-quiet-logging test (`-v` vs no-`-v`) still exercises the live path via `main()`/`_configure_logging`, which is unchanged, so coverage is preserved.
- **Files modified:** tests/test_cli.py
- **Commit:** e81eb21

No other deviations — plan executed as written otherwise.

## Verification

- `tests/test_dead_code_removed.py` (Plan 01 drift-back gate) — 4 passed (F76 clause stays green: 0 `verbose: bool` in the `run_weather` signature region after removal).
- `grep -q "# ACCEPTED (F77, v2.1):" weatherbot/cli.py` — present.
- `grep -q "\"--verbose\"" weatherbot/cli.py` — live `-v` flag intact.
- `! grep -qE "run_weather\([^)]*verbose" weatherbot/ tests/` — no caller passes `verbose=`.
- `uv run pytest tests/test_cli.py -q` — 57 passed.
- `uv run pytest -q` — **891 passed, exit 0** (the "2 snapshots failed" line is the known syrupy report quirk; trust the exit code).
- No hub-path (`yahir_reusable_bot/`, `../Reusable/`) file in the diff.

## Self-Check: PASSED

- FOUND: weatherbot/cli.py (modified, both tasks)
- FOUND: tests/test_cli.py (modified, Rule-3 shim fix)
- FOUND commit e81eb21 (Task 1)
- FOUND commit fa262da (Task 2)
- SUMMARY written to .planning/phases/35-cleanup-sweep/35-03-SUMMARY.md
