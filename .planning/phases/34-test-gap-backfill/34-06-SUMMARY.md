---
phase: 34-test-gap-backfill
plan: 06
subsystem: testing
tags: [pytest, sqlite, transaction, atomicity, wal, exactly-once, monkeypatch]

# Dependency graph
requires:
  - phase: 31-store-hardening
    provides: transactional single-commit persist (F37/F63) + persistent WAL, and the daemon post-send best-effort bookkeeping swallow (F01)
provides:
  - test_persist_onecall_atomic_rollback — pins the two-INSERT persist as one both-or-neither transaction (mid-persist raise → zero committed rows) + WAL persistence
  - SC-3 coverage ledger citation [EXISTS] for the F01 post-send re-fire escape (test_scheduler.py::test_post_send_db_error_keeps_claim), tagged HARD-TEST-02
affects: [test-gap-backfill, hardening-milestone-audit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Atomicity regression via _connect monkeypatch: wrap the store connection so the SECOND weather_onecall INSERT raises mid-transaction, then a FRESH read connection proves zero committed rows (both-or-neither)."
    - "Force-commit RED proof: a temporary conn.commit() injected after the imperial INSERT flips the test to RED (assert 1 == 0), confirming the assertion gates rather than passing vacuously."

key-files:
  created: []
  modified:
    - tests/test_store.py
    - tests/test_scheduler.py

key-decisions:
  - "F01 pin lives in test_scheduler.py (fire_slot post-send tests), NOT test_reliability.py where the plan pointed — cited [EXISTS], tagged with HARD-TEST-02, not duplicated."
  - "Task 1 is a pure pin (the F37/F63 atomicity guarantee already shipped in Phase 31) — proven RED against a force-commit persist and GREEN against real store.py; no D-07 escape, no app-side fix folded."

patterns-established:
  - "Transactional both-or-neither test: monkeypatch _connect to raise on the second table-INSERT, undo the patch, then read committed count from a fresh connection."

requirements-completed: [HARD-TEST-02]

coverage:
  - id: D1
    description: "The two INSERTs inside persist are one transaction — a mid-persist raise (metric INSERT) commits ZERO weather_onecall rows (both-or-neither); a fresh raw connect reports journal_mode=wal and init_db stays idempotent (F37/F63)."
    requirement: "HARD-TEST-02"
    verification:
      - kind: unit
        ref: "tests/test_store.py#test_persist_onecall_atomic_rollback"
        status: pass
    human_judgment: false
  - id: D2
    description: "F01 post-send bookkeeping re-fire escape is pinned [EXISTS]: a raise in resolve_alert/stamp_success after result.ok keeps the delivered claim (was_sent True, no re-fire, no internal_error alert)."
    requirement: "HARD-TEST-02"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py#test_post_send_db_error_keeps_claim"
        status: pass
    human_judgment: false

# Metrics
duration: 3min
completed: 2026-07-13
status: complete
---

# Phase 34 Plan 06: Store-atomicity backfill (F37/F63) + F01 re-fire pin Summary

**Transactional both-or-neither `persist` regression (mid-INSERT raise → zero committed rows, WAL-persistent) added to test_store.py, and the F01 post-send re-fire escape confirmed [EXISTS] in test_scheduler.py and tagged for the SC-3 ledger.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-07-13T16:51:50Z
- **Completed:** 2026-07-13T16:54:56Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `test_persist_onecall_atomic_rollback` pins the F37/F63 atomicity contract: with the SECOND (metric) `weather_onecall` INSERT monkeypatched to raise mid-transaction, a fresh read connection sees ZERO committed rows — the imperial INSERT did NOT commit alone. Also asserts a fresh raw connect reports `journal_mode=wal` and `init_db` stays idempotent.
- Proved the new test genuinely gates: a temporarily injected force-commit after the imperial INSERT flips it RED (`assert 1 == 0`); reverted immediately — `store.py` untouched.
- Confirmed the F01 "raise-after-ok keeps the delivered claim" assertion already EXISTS (`test_scheduler.py::test_post_send_db_error_keeps_claim`, plus CR-01 companion `test_post_send_success_log_raise_keeps_claim`) and tagged it with `F01 / HARD-TEST-02 (34-06 D-08)` for the SC-3 ledger — no duplicate created.
- Full suite green: 877 passed, exit 0.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add transactional both-or-neither persist test (F37/F63)** - `fde62b6` (test)
2. **Task 2: Confirm F01 post-send bookkeeping pin [EXISTS]; tag for SC-3 (D-08)** - `5ffe709` (test)

**Plan metadata:** (docs commit follows this summary)

## Files Created/Modified
- `tests/test_store.py` - Added `test_persist_onecall_atomic_rollback` (mid-persist raise → zero committed rows + WAL persistence, tagged F37/F63/HARD-TEST-02).
- `tests/test_scheduler.py` - Added the SC-3 ledger / `F01 / HARD-TEST-02` citation note to the existing `test_post_send_db_error_keeps_claim` docstring (no behavior change, no duplicate).

## Decisions Made
- **Task 1 is a pure pin.** The F37/F63 transactional guarantee already shipped in Phase 31, so the test passes GREEN against current `store.py`. Rather than trust a possibly-vacuous pass, I proved it RED against a force-commit persist (temporary patch, reverted) — confirming the assertion locks out the escape. No D-07 real escape; no app-side fix folded.
- **F01 test location correction.** The plan pointed at `tests/test_reliability.py:428+`, but the actual F01 post-send re-fire pin lives in `tests/test_scheduler.py` (where the `fire_slot` post-send tests are). Cited [EXISTS] there and tagged it, per D-08 "add only if absent" — the assertion is present and comprehensive, so no test was added.

## Deviations from Plan

**1. [Rule 1 - Doc pointer correction] F01 pin is in test_scheduler.py, not test_reliability.py**
- **Found during:** Task 2 (F01 [EXISTS] confirmation)
- **Issue:** The plan's `read_first` and verify selector targeted `tests/test_reliability.py:428+` for the F01 "raise-after-ok keeps the claim" assertion, but that file has no such test — the plan's verify `-k` selector deselects all (0 tests, vacuous exit 0). The genuine F01 pin lives in `tests/test_scheduler.py::test_post_send_db_error_keeps_claim` (with CR-01 companion `test_post_send_success_log_raise_keeps_claim`).
- **Fix:** Located the real pin via grep, confirmed it asserts exactly F01 (`was_sent` True, no re-fire, no `internal_error` alert after a `stamp_success` raise post-`result.ok`), and added the `F01 / HARD-TEST-02 (34-06 D-08)` SC-3 ledger citation to its docstring. No duplicate test created (D-08 "only if absent" honored).
- **Files modified:** tests/test_scheduler.py
- **Verification:** `uv run pytest tests/test_scheduler.py -k post_send -q` → 2 passed.
- **Committed in:** `5ffe709`

---

**Total deviations:** 1 (doc-pointer correction — no production/behavior change).
**Impact on plan:** No scope creep. The F01 obligation is satisfied against the real, existing pin; the plan's stale file pointer was the only discrepancy.

## Issues Encountered
- The full suite prints "2 snapshots failed. 27 snapshots passed." but exits 0 — this is the known pre-existing syrupy report-line quirk (not a golden diff). Trusted the exit code per project memory.

## User Setup Required
None - tests-only, no external service configuration required.

## Next Phase Readiness
- SC-3 store-atomicity / data-loss ledger is now pinned for F37 (non-atomic write), F63 (executescript force-commit), and F01 (post-send re-fire) — all three findings have named-and-tagged regression coverage.
- One plan remains in phase 34 (34-07).

## Self-Check: PASSED

- FOUND: `.planning/phases/34-test-gap-backfill/34-06-SUMMARY.md`
- FOUND: `tests/test_store.py::test_persist_onecall_atomic_rollback`
- FOUND commit: `fde62b6` (Task 1)
- FOUND commit: `5ffe709` (Task 2)

---
*Phase: 34-test-gap-backfill*
*Completed: 2026-07-13*
