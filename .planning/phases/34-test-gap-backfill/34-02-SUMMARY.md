---
phase: 34-test-gap-backfill
plan: 02
subsystem: testing
tags: [pytest, reliability, retry, heartbeat, regression-tests, false-green]

# Dependency graph
requires:
  - phase: 34-test-gap-backfill (34-01)
    provides: test-gap-backfill wave already underway; shared RETRY constants + _State/_Outcome/_status_error stand-ins in tests/test_reliability.py
provides:
  - "F114: heartbeat tick/success COLUMN separation pinned (bare tick leaves last_success_utc NULL)"
  - "F112: within-burst wait bounded by constant-derived step..step*1.5 ceiling (no loose < 150.0)"
  - "F110: Retry-After 429 on attempt==BURST_SIZE proven to collapse the 2700s mid-pause to the 120s cap"
affects: [test-gap-backfill, reliability, cleanup, hub-findings-handoff]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Constant-derived bounds over magic literals (step = BURST_SPREAD_S/(BURST_SIZE-1), ceiling = step*1.5)"
    - "Assertion-by-construction: each test asserts the exact value the bug violated so it is red against pre-fix/weakened behavior"

key-files:
  created: []
  modified:
    - tests/test_reliability.py

key-decisions:
  - "F112 bound derived from live constants (85.71..128.57), never the literal 128.57 — a literal would re-hide regressions"
  - "F110 drives the hub retry symbol (two_burst_wait) via the app-side weatherbot.reliability.retry shim import — no hub source edited (ECOSYSTEM.md human-gated rule respected)"

patterns-established:
  - "Tick/success separation assertion: a bare heartbeat tick must leave last_success_utc NULL, only stamp_success fills it (last_tick_utc unchanged)"
  - "Within-burst wait ceiling asserted as step <= wait <= step*1.5 derived from BURST_SIZE/BURST_SPREAD_S"

requirements-completed: [HARD-TEST-01, HARD-TEST-02]

coverage:
  - id: D1
    description: "F114: test_heartbeat_upsert asserts last_success_utc is None after a bare _heartbeat_tick, and last_success_utc becomes non-None (tick unchanged) only after stamp_success"
    requirement: "HARD-TEST-01"
    verification:
      - kind: unit
        ref: "tests/test_reliability.py::test_heartbeat_upsert"
        status: pass
    human_judgment: false
  - id: D2
    description: "F112: test_two_burst_wait_shape bounds every within-burst wait by step <= wait <= step*1.5 (85.71..128.57), derived from constants, retaining attempt==BURST_SIZE == MID_PAUSE_S"
    requirement: "HARD-TEST-01"
    verification:
      - kind: unit
        ref: "tests/test_reliability.py::test_two_burst_wait_shape"
        status: pass
    human_judgment: false
  - id: D3
    description: "F110: test_retry_after_collapses_mid_pause proves a capped Retry-After 429 on attempt==BURST_SIZE collapses the 2700s mid-pause to the 120s cap while a bare mid-pause attempt stays 2700"
    requirement: "HARD-TEST-02"
    verification:
      - kind: unit
        ref: "tests/test_reliability.py::test_retry_after_collapses_mid_pause"
        status: pass
    human_judgment: false

# Metrics
duration: 2min
completed: 2026-07-13
status: complete
---

# Phase 34 Plan 02: Reliability test-gap backfill (F114/F112/F110) Summary

**Corrected two false-green reliability tests (F114 tick/success separation, F112 constant-derived within-burst ceiling) and added the missing F110 Retry-After-collapses-mid-pause regression — all tests-only, hub source untouched.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-07-13T16:34:39Z
- **Completed:** 2026-07-13T16:36:26Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments
- **F114 (HARD-TEST-01):** `test_heartbeat_upsert` now asserts `last_success_utc is None` after a bare `_heartbeat_tick` (tick/success column separation), then that `stamp_success` fills `last_success_utc` while leaving `last_tick_utc` unchanged. A bug stamping success on every tick would now be caught.
- **F112 (HARD-TEST-01):** `test_two_burst_wait_shape` replaced the loose `assert 0.0 <= wait < 150.0` with the constant-derived `step <= wait <= step*1.5` (85.71..128.57), computed from `BURST_SPREAD_S/(BURST_SIZE-1)` — no magic literal. The `attempt==BURST_SIZE == MID_PAUSE_S` boundary assertion is retained.
- **F110 (HARD-TEST-02):** new `test_retry_after_collapses_mid_pause` proves a capped `Retry-After` 429 on `attempt==BURST_SIZE` collapses the 2700s mid-pause to `RETRY_AFTER_CAP_S` (120s), with a contrast assertion that a bare mid-pause attempt stays `MID_PAUSE_S` (2700).

## Task Commits

Each task was committed atomically:

1. **Task 1: Strengthen heartbeat tick/success separation (F114)** - `4b3b754` (test)
2. **Task 2: Tighten within-burst wait to derived step..step*1.5 bound (F112)** - `571f1f5` (test)
3. **Task 3: Add Retry-After 429 mid-pause collapse test (F110)** - `6c8217c` (test)

_These are assertion-strengthening / new-test changes; the red state was proven via in-process spot-checks rather than a separate RED commit (no production code exists to make green)._

## Files Created/Modified
- `tests/test_reliability.py` - strengthened `test_heartbeat_upsert` (F114), tightened `test_two_burst_wait_shape` (F112), added `test_retry_after_collapses_mid_pause` (F110); each tagged with its finding id + requirement.

## Decisions Made
- **F112 bound derived, not literal:** the ceiling is computed live from `BURST_SPREAD_S`/`BURST_SIZE` (85.71..128.57), never hard-coded `128.57` — a literal would re-hide the exact regressions the finding targets.
- **F110 stays app-side:** the test drives the hub-owned `two_burst_wait` through the app's `weatherbot.reliability.retry` import surface; no hub source was edited (ECOSYSTEM.md human-gated rule respected). No genuine hub bug was surfaced — the collapse behavior is correct, so no hub handoff was triggered.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## Gate-1 Self-UAT (D-06 red→green spot-checks)

- **F114 red→green:** In-process shim of `_heartbeat_tick` to also call `store.stamp_success` turned the new `assert row["last_success_utc"] is None` RED (`assert 1783960503 is None`). The shim was in-process only (no source edit); the real test is GREEN. Confirms the assertion is sensitive to a success-on-every-tick bug.
- **F112 red→green:** A synthetic `149.0` wait passes the old `< 150.0` bound (`True`) but fails the new derived `<= step*1.5` (128.57) bound (`False`), proving the tightened bound rejects a regression the loose bound silently accepted.
- **F110:** assertion-by-construction (D-05) — no red-mutation spot-check required; the two-sided assert (`== RETRY_AFTER_CAP_S` and contrast `== MID_PAUSE_S`) is red against any weakened collapse.
- No mutation-testing dependency added.

**Verification:** `uv run pytest tests/test_reliability.py -k "heartbeat or two_burst_wait or retry_after" -q` → 9 passed. `uv run pytest tests/test_reliability.py -q` → 25 passed (exit 0).

## Next Phase Readiness
- Plan 34-02 complete; remaining phase-34 plans (34-03..34-07) back-fill the other uncovered high-risk paths (midnight catch-up, rename-safe id, store atomicity).
- No blockers. Hub source untouched, so no hub handoff obligation created by this plan.

## Self-Check: PASSED

- FOUND: tests/test_reliability.py
- FOUND: 34-02-SUMMARY.md
- FOUND commits: 4b3b754, 571f1f5, 6c8217c

---
*Phase: 34-test-gap-backfill*
*Completed: 2026-07-13*
