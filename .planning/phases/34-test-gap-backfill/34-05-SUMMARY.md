---
phase: 34-test-gap-backfill
plan: 05
subsystem: testing
tags: [pytest, multiday, select_days, regression-test, weather]

# Dependency graph
requires:
  - phase: 13-multiday (v1.x)
    provides: multiday.select_days window/roll-forward/horizon selector under test
provides:
  - F111 pinning test — weekend whole-block roll-forward (multiday.py:104-107) for kind='weekend'
  - F113 pinning test — null-dt entry skip in _date_index_map (multiday.py:52-56)
affects: [34-06, 34-07, 35-cleanup]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Assertion-by-construction pinning test (D-05): the exact observable the fix guarantees, deterministic against the 8-day recorded fixture."
    - "Finding-id + requirement tag (D-02) in each test docstring for fix↔test↔finding traceability."

key-files:
  created: []
  modified:
    - tests/test_multiday.py

key-decisions:
  - "F111 whole-block roll-forward for kind='weekend' is only reachable via a drop that leaves a wholly-past remainder — the full fri/sat/sun set never empties `upcoming` because sun's delta (6-weekday) is always >= 0. Tests use drop={sat,sun} / drop={fri,sun} to genuinely fire multiday.py:104-107 (deviation from the plan's literal add=set(),drop=set() call shape, justified by the must_haves demand that the roll-forward branch actually fire)."
  - "Both F111 and F113 tests are GREEN against current code — no D-07 latent escape; multiday.py unchanged (tests-only)."

patterns-established:
  - "Weekend roll-forward geometry documented inline in the test docstring so a future reader knows why a drop is required to reach the branch."

requirements-completed: [HARD-TEST-02]

coverage:
  - id: D1
    description: "F111 — kind='weekend' whole-block roll-forward (multiday.py:104-107): a wholly-past (post-drop) weekend block rolls +7 to next week's Friday (fixture idx 0), and a rolled target beyond the 7-day horizon emits a notice — never an IndexError."
    requirement: "HARD-TEST-02"
    verification:
      - kind: unit
        ref: "tests/test_multiday.py#test_weekend_run_on_monday_rolls_forward"
        status: pass
      - kind: unit
        ref: "tests/test_multiday.py#test_weekend_roll_forward_beyond_horizon_returns_notice"
        status: pass
    human_judgment: false
  - id: D2
    description: "F113 — a {dt:None} entry and a fully-null daily entry are skipped in _date_index_map (multiday.py:52-56), never appear in returned indices, and a desired date whose only candidate had a null dt yields a notice — never a TypeError/IndexError."
    requirement: "HARD-TEST-02"
    verification:
      - kind: unit
        ref: "tests/test_multiday.py#test_null_dt_entry_skipped_in_date_index"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-13
status: complete
---

# Phase 34 Plan 05: F111 weekend roll-forward + F113 null-dt skip Summary

**Two assertion-by-construction pinning tests in `tests/test_multiday.py` — one genuinely firing the weekend whole-block roll-forward branch (multiday.py:104-107), one exercising the null-dt skip in `_date_index_map` — both green, `multiday.py` untouched.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-13
- **Completed:** 2026-07-13
- **Tasks:** 2
- **Files modified:** 1 (tests/test_multiday.py)

## Accomplishments
- **F111 (weekend roll-forward):** added `test_weekend_run_on_monday_rolls_forward` and `test_weekend_roll_forward_beyond_horizon_returns_notice`. The first proves a wholly-past (post-drop) weekend block rolls +7 to next week's Friday (fixture idx 0) with no IndexError; the second proves a rolled target beyond the 7-day horizon degrades to a notice, not a crash. Both fire the previously test-dead whole-block roll-forward branch for `kind='weekend'`.
- **F113 (null-dt skip):** added `test_null_dt_entry_skipped_in_date_index`. Asserts both a `{"dt": None}` entry and a fully-null entry are absent from `_date_index_map` (indices `[0,2,4,5]`, skipping the null slots at 1 and 3), good entries still resolve, and a desired date whose only candidate had a null dt yields a horizon notice — no TypeError/IndexError.
- Full `tests/test_multiday.py` suite green: 19 passed, exit 0. `weatherbot/weather/multiday.py` unchanged (tests-only, per plan and T-34-05).

## Task Commits

Each task was committed atomically:

1. **Task 1: F111 weekend whole-block roll-forward** - `e325994` (test)
2. **Task 2: F113 null-dt skip in date-index map** - `3a0027a` (test)

_Both tasks are pinning/regression tests against already-shipped Phase 13 code, so each is GREEN on first run (no RED→GREEN implementation step; D-07 confirms no latent escape)._

## Files Created/Modified
- `tests/test_multiday.py` - +3 tests: `test_weekend_run_on_monday_rolls_forward`, `test_weekend_roll_forward_beyond_horizon_returns_notice` (F111), `test_null_dt_entry_skipped_in_date_index` (F113).

## Decisions Made
- **F111 requires a `drop` to reach the roll-forward branch.** `_WEEKEND_DAYS = (fri, sat, sun)`; `sun`'s signed delta is `6 - today.weekday()`, always >= 0 for every weekday, so the *full* weekend set never has an empty `upcoming` and the whole-block roll-forward branch (multiday.py:104-107) is unreachable for the full block. To genuinely fire that branch for `kind='weekend'`, the tests drop the trailing weekend day(s) — `drop={sat,sun}` (leaves wholly-past `fri` → rolls to next Fri idx 0) and `drop={fri,sun}` (leaves wholly-past `sat` → rolls beyond horizon → notice). This deviates from the plan's literal `add=set(), drop=set()` call shape but is required to satisfy the plan's own must_haves (D-05 / boundary edge: "F111 pins the whole-block-past branch … indices resolve to next week or emit horizon notices, never IndexError"). The geometry is documented inline in each test docstring.
- **No production fix folded (D-07):** both tests are green against current code, so no latent escape; `multiday.py` is unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking test construction] F111 call shape adjusted to reach the target branch**
- **Found during:** Task 1 (F111 weekend roll-forward)
- **Issue:** The plan's `<action>` specified `add=set(), drop=set()` for the weekend roll-forward test, but with an empty `drop` the whole-block roll-forward branch (multiday.py:104-107) is mathematically unreachable for `kind='weekend'` — `sun`'s delta (`6 - weekday`) is always >= 0, so `upcoming` is never empty and the branch never fires. The plan's must_haves (D-05 / boundary edge) explicitly require the whole-block-past branch to fire.
- **Fix:** Used `drop={sat,sun}` (and `drop={fri,sun}` for the horizon-notice variant) so the remaining weekend token is wholly past and the roll-forward branch genuinely executes. Documented the geometry inline in each docstring.
- **Files modified:** tests/test_multiday.py
- **Verification:** `uv run pytest tests/test_multiday.py -k weekend -x -q` → 3 passed, exit 0; the roll-forward path confirmed to resolve idx 0 (in-horizon) and a notice (beyond-horizon).
- **Committed in:** `e325994` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking test construction)
**Impact on plan:** The deviation is necessary to satisfy the plan's own acceptance criteria (the branch must actually fire). No scope creep — still tests-only, no production change, exactly the two findings (F111, F113) in scope.

## Issues Encountered
- None beyond the F111 construction geometry documented above. The "2 snapshots failed" syrupy report line does not appear for this module; the module suite exits 0 cleanly.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- F111 and F113 coverage landed; two of the HARD-TEST-02 cluster findings closed.
- Remaining phase-34 plans (34-06, 34-07) cover the rest of the HARD-TEST-01/02 ledger.
- No blockers introduced.

## Self-Check: PASSED

---
*Phase: 34-test-gap-backfill*
*Completed: 2026-07-13*
