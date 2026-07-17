---
phase: 29-startup-validation-honest-alerting
plan: 03
subsystem: ops
tags: [selfcheck, classification, health, severity, daemon, config-validation]

# Dependency graph
requires:
  - phase: 29-01
    provides: "Wave-0 xfail(strict=False) guard tests in tests/test_ops_selfcheck.py for CONFIG_INVALID classification + severity map (red half of TDD)"
provides:
  - "CONFIG_INVALID = 'config_invalid' fatal reason constant in weatherbot/ops/selfcheck.py"
  - "Pre-probe config/template/empty-locations classification split (except (ValueError, FileNotFoundError) -> CONFIG_INVALID) BEFORE the network probe"
  - "to_health_result maps CONFIG_INVALID -> Severity.CRITICAL (alongside AUTH_FAILED)"
  - "CONFIG_INVALID re-exported from weatherbot.ops and resolvable as daemon.CONFIG_INVALID"
affects: [29-04, 29-05, wiring._on_fail, cli._fatal_config_exit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pre-probe fatal classification: split permanent config faults into their own except branch BEFORE the network probe so they never masquerade as transient NETWORK_NOT_READY"
    - "Daemon-namespace re-export (noqa F401) so a constant is resolvable as a module attribute for a later plan's hook comparison"

key-files:
  created: []
  modified:
    - weatherbot/ops/selfcheck.py
    - weatherbot/ops/__init__.py
    - weatherbot/scheduler/daemon.py
    - tests/test_golden_coverage_fill.py

key-decisions:
  - "The 'requires client or settings' ValueError stays inside the probe try (NETWORK_NOT_READY), not the config branch — it is a runtime wiring condition, not an operator config-file fault"
  - "detail=type(exc).__name__ for CONFIG_INVALID, never str(exc) — a config error can embed a filesystem path or config value (T-04-01)"
  - "Left the httpx.HTTPStatusError and trailing broad except Exception branches byte-identical to preserve D-03 (401/403->AUTH_FAILED, transient->NETWORK_NOT_READY)"

patterns-established:
  - "Pre-probe fatal-vs-transient classification split in run_self_check"
  - "noqa F401 daemon-namespace re-export for cross-plan hook resolution"

requirements-completed: [HARD-STARTUP-02]

coverage:
  - id: D1
    description: "run_self_check classifies permanent config/template/empty-locations faults as CONFIG_INVALID (not NETWORK_NOT_READY), before the network probe, with outcome-only detail"
    requirement: "HARD-STARTUP-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_selfcheck.py#test_config_invalid_on_bad_template"
        status: pass
      - kind: unit
        ref: "tests/test_ops_selfcheck.py#test_config_invalid_on_empty_locations"
        status: pass
      - kind: unit
        ref: "tests/test_golden_coverage_fill.py#test_self_check_no_locations_is_config_invalid"
        status: pass
    human_judgment: false
  - id: D2
    description: "D-03 preserved: a transient ConnectError still returns NETWORK_NOT_READY and a 401/403 still returns AUTH_FAILED after the split"
    requirement: "HARD-STARTUP-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_selfcheck.py#test_connect_error_still_network_not_ready"
        status: pass
      - kind: unit
        ref: "tests/test_ops_selfcheck.py#test_401_still_auth_failed"
        status: pass
    human_judgment: false
  - id: D3
    description: "to_health_result maps CONFIG_INVALID -> CRITICAL, AUTH_FAILED -> CRITICAL, NETWORK_NOT_READY -> WARNING"
    requirement: "HARD-STARTUP-02"
    verification:
      - kind: unit
        ref: "tests/test_ops_selfcheck.py#test_severity_map"
        status: pass
    human_judgment: false
  - id: D4
    description: "CONFIG_INVALID is importable from weatherbot.ops and resolvable as daemon.CONFIG_INVALID for wiring.py:_on_fail (29-05)"
    requirement: "HARD-STARTUP-02"
    verification:
      - kind: unit
        ref: "python -c 'from weatherbot.ops import CONFIG_INVALID; import weatherbot.scheduler.daemon as d; assert d.CONFIG_INVALID == \"config_invalid\"'"
        status: pass
    human_judgment: false

# Metrics
duration: 4min
completed: 2026-07-08
status: complete
---

# Phase 29 Plan 03: CONFIG_INVALID Fatal Classifier Summary

**Split the self-check's pre-probe config/template/empty-locations checks into their own CONFIG_INVALID (CRITICAL) branch so a permanent config fault stops warn-looping as a fake NETWORK_NOT_READY network fault, and re-exported the reason onto the daemon namespace for the 29-05 fatal hook.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-07-08T05:15:54Z
- **Completed:** 2026-07-08T05:20:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added `CONFIG_INVALID = "config_invalid"` reason constant next to `PASS`/`NETWORK_NOT_READY`/`AUTH_FAILED` (D-01).
- Wrapped the pre-network config checks (`config.locations` guard, `validate_template`, `assert_unique_names`, `resolve_location`) in their own `except (ValueError, FileNotFoundError)` → `CONFIG_INVALID` placed BEFORE the live probe, with `detail=type(exc).__name__` (never `str(exc)`, T-04-01).
- Extended `to_health_result` severity map: `CONFIG_INVALID` → `Severity.CRITICAL` (alongside `AUTH_FAILED`); `NETWORK_NOT_READY` stays `WARNING`.
- Re-exported `CONFIG_INVALID` from `weatherbot.ops` (`__init__` + `__all__`) and added it to the daemon's from-ops import so `daemon.CONFIG_INVALID` resolves for `wiring.py:_on_fail` (29-05).
- Completed the Wave-0 red→green transition: all 5 previously-xfail CONFIG_INVALID/severity guard tests now run plain green (the condition-based `xfail(not _CONFIG_INVALID_PRESENT)` marker went inert once the symbol became importable).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add CONFIG_INVALID reason, split classification, extend severity map** - `24b446e` (feat)
2. **Task 2: Re-export CONFIG_INVALID from weatherbot.ops (make daemon.CONFIG_INVALID resolvable)** - `fd27114` (feat)

_Note: This is the green (implementation) half of a TDD cycle whose red guard tests were authored in Wave 0 (29-01)._

## Files Created/Modified
- `weatherbot/ops/selfcheck.py` - New CONFIG_INVALID constant; pre-probe classification split; CRITICAL severity mapping.
- `weatherbot/ops/__init__.py` - CONFIG_INVALID added to re-export block and `__all__`.
- `weatherbot/scheduler/daemon.py` - CONFIG_INVALID added to from-ops import (noqa F401) so it resolves on the daemon namespace.
- `tests/test_golden_coverage_fill.py` - Updated a stale coverage-fill test that asserted empty-locations → NETWORK_NOT_READY (the pre-fix behavior) to assert the new CONFIG_INVALID contract.

## Decisions Made
- Kept the "requires client or settings" `ValueError` inside the probe `try` (still NETWORK_NOT_READY) rather than the config branch — it is a runtime wiring precondition, not an operator config-file fault. `test_self_check_requires_client_or_settings` stayed green, confirming this.
- Used `# noqa: F401` on the daemon's CONFIG_INVALID import: it exists purely as a namespace re-export for 29-05's `_on_fail` comparison and is not otherwise referenced in daemon.py yet.
- Left the `httpx.HTTPStatusError`/`is_auth_failure` and trailing broad `except Exception` branches byte-identical to guarantee D-03 (T-29-07 regression guard).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale coverage-fill test asserting the pre-fix behavior**
- **Found during:** Task 2 (full-suite run)
- **Issue:** `tests/test_golden_coverage_fill.py::test_self_check_no_locations_is_network_not_ready` asserted empty-locations → `NETWORK_NOT_READY`. This codified the exact pre-fix behavior HARD-STARTUP-02 corrects; the Wave-0 test `test_config_invalid_on_empty_locations` asserts the new CONFIG_INVALID contract, so the two directly contradicted and the suite went red (exit 1).
- **Fix:** Renamed the test to `test_self_check_no_locations_is_config_invalid` and updated its assertions to `reason == CONFIG_INVALID` + outcome-only `detail.isidentifier()`. In scope: the plan's `<behavior>` explicitly requires "Empty-locations config → CONFIG_INVALID."
- **Files modified:** tests/test_golden_coverage_fill.py
- **Verification:** `uv run pytest tests/test_golden_coverage_fill.py -k self_check -q` → 2 passed; full suite exit 0.
- **Committed in:** fd27114 (Task 2 commit)

**2. [Rule 3 - Blocking] Suppressed the F401 on the daemon CONFIG_INVALID re-export**
- **Found during:** Task 2 (ruff check)
- **Issue:** Adding CONFIG_INVALID to daemon's from-ops import triggered `F401 imported but unused` — the symbol is needed only as a daemon-namespace attribute for 29-05, not referenced in daemon.py yet. A future `ruff --fix` sweep could silently delete it and break 29-05's `_on_fail` comparison.
- **Fix:** Added `# noqa: F401` with an explanatory comment on the import line.
- **Files modified:** weatherbot/scheduler/daemon.py
- **Verification:** `uv run ruff check weatherbot/scheduler/daemon.py` no longer flags CONFIG_INVALID (only 3 pre-existing out-of-scope errors remain, logged to deferred-items.md).
- **Committed in:** fd27114 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both auto-fixes necessary for correctness (test now guards the intended contract) and durability of the 29-05 seam. No scope creep — both changes are within the plan's declared behavior and file set.

## Issues Encountered
- Three pre-existing `ruff` findings in `daemon.py` (`ReloadEngine`/`PID_FILE` F401, `notifier` F841) surfaced during the lint check but exist on HEAD before this plan and are unrelated to the CONFIG_INVALID change. Logged to `deferred-items.md`, not fixed (out of scope; likely consumed by later Phase-29 plans).

## Known Stubs
None.

## TDD Gate Compliance
The red guard tests (`test_config_invalid_*`, `test_severity_map`) were authored in Wave 0 (29-01) as `xfail(strict=False)`. This plan supplied the implementation (green). Because the Wave-0 markers are condition-gated on `_CONFIG_INVALID_PRESENT` (the presence of the importable symbol), re-exporting CONFIG_INVALID in Task 2 flipped the condition to False and the markers went inert — the tests now run as plain green guards (15 passed, 0 XPASS in `test_ops_selfcheck.py`). No manual xfail-marker edits were required. Markers for tests landing in 29-04/29-05/29-06 were left untouched (they remain XFAIL).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `daemon.CONFIG_INVALID` resolves as a module attribute — 29-05's `wiring.py:_on_fail` can now compare `result.reason == daemon.CONFIG_INVALID`.
- Severity map is ready: a CONFIG_INVALID health result carries `Severity.CRITICAL`, which the fatal branch in 29-05 keys on.
- No hub source was touched; classification stays entirely app-side.

## Self-Check: PASSED

---
*Phase: 29-startup-validation-honest-alerting*
*Completed: 2026-07-08*
