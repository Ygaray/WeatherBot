---
phase: 03-always-on-scheduler
plan: 05
subsystem: infra
tags: [sqlite, apscheduler, idempotency, exactly-once, scheduler, discord]

# Dependency graph
requires:
  - phase: 03-always-on-scheduler (03-01)
    provides: sent_log table + UNIQUE(location_name, send_time, local_date) + was_sent/record_sent
  - phase: 03-always-on-scheduler (03-03)
    provides: fire_slot callback + run_daemon lifecycle + check-before-fire/mark-after-success flow
provides:
  - "Atomic claim_slot(...) -> bool (INSERT OR IGNORE + rowcount==1) arbitrating delivery-level exactly-once"
  - "release_claim(...) -> None (3-part-key DELETE) re-opening a slot on delivery failure"
  - "fire_slot delivery gated on the atomic claim BEFORE the network send, releasing on non-ok/exception"
  - "Concurrent-double-fire test asserting exactly one POST across two overlapping fires (SCHD-07)"
affects: [04-reliability, retry-then-alert, future-channels]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Atomic claim-before-side-effect: collapse check-then-act into one INSERT OR IGNORE + rowcount==1 taken BEFORE the side-effecting send; release on failure to re-open"
    - "claimed-flag guard so the except-block release only ever undoes a claim THIS caller won (no wrong-row delete, no unbound-name on early raise)"

key-files:
  created: []
  modified:
    - weatherbot/weather/store.py
    - weatherbot/scheduler/daemon.py
    - tests/test_scheduler.py

key-decisions:
  - "claim_slot supersedes record_sent on the success path: the claim writes the sent_log row up-front, so a won claim is already the recorded slot; record_sent is no longer called from the daemon (kept exported for catch-up/other readers)"
  - "release_claim binds all three key columns so it can only delete that one slot's row — no delete-arbitrary-row primitive (T-03-01)"
  - "release fires on BOTH a non-ok result and a raised delivery; guarded by a claimed flag so an exception raised before the claim (or before local_date is computed) never triggers a wrong-row delete"

patterns-established:
  - "Atomic claim-before-side-effect for exactly-once delivery (INSERT OR IGNORE + rowcount==1, release-on-failure)"

requirements-completed: [SCHD-07]

# Metrics
duration: 5min
completed: 2026-06-10
---

# Phase 3 Plan 05: Exactly-Once Delivery via Atomic claim_slot Summary

**Closed SCHD-07 gap #2: fire_slot now wins an atomic `claim_slot` (INSERT OR IGNORE + rowcount==1) BEFORE the Discord send and releases the claim on failure, so two overlapping fires for the same slot deliver exactly once.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-10T21:57Z
- **Completed:** 2026-06-10T22:00:22Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added atomic `claim_slot(db_path, location_name, send_time, local_date) -> bool` to store.py: a single parameterized `INSERT OR IGNORE` returning `cur.rowcount == 1` — exactly one `True` across N concurrent claims for the same key, with the won claim writing the `sent_log` row up-front.
- Added `release_claim(...)` (3-part-bound `DELETE`) to re-open a slot when delivery fails, preserving mark-after-success-for-the-failure-case (D-07 / SCHD-06 "send late on recovery").
- Replaced the non-atomic `was_sent` read → `send_now` deliver → `record_sent` write window in `fire_slot` with: claim BEFORE the send, gate delivery on the claim, release the claim on a non-ok result and on a raised delivery.
- Added `test_concurrent_double_fire_delivers_once`: asserts claim arbitration (one `True` per key, re-claim wins after release) AND that two overlapping `fire_slot` calls produce exactly one POST to a shared channel.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add atomic claim_slot + release_claim to store.py (with concurrent-double-fire test)** - `a2d2c95` (feat)
2. **Task 2: Gate fire_slot delivery on claim_slot, release on failure** - `367ea31` (feat)

**Plan metadata:** see final docs commit.

_Note: this is a `type: tdd` gap-closure plan. The shipping `test_concurrent_double_fire_delivers_once` lands in the same Task 1 commit as the helpers it tests; the claim-arbitration leg fails against the pre-plan store (no `claim_slot` symbol) and passes once the helpers exist — see "TDD Gate Compliance" below._

## Files Created/Modified
- `weatherbot/weather/store.py` - Added `claim_slot` (atomic INSERT OR IGNORE + `rowcount==1` arbitration) and `release_claim` (3-part-key parameterized DELETE) beside `was_sent`/`record_sent`; both stay network-free and parameterized-only.
- `weatherbot/scheduler/daemon.py` - `fire_slot` gates delivery on `claim_slot` before the send and releases on non-ok/exception (guarded by a `claimed` flag); dropped the `record_sent` import + post-success call; kept `was_sent` imported for `_run_catchup`; rewrote the module + `fire_slot` docstrings to describe the claim/release flow.
- `tests/test_scheduler.py` - Added `test_concurrent_double_fire_delivers_once` (claim arbitration + exactly-one-POST).

## Decisions Made
- **claim_slot supersedes record_sent on the success path.** The claim writes the `sent_log` row up-front, so a won claim already records the slot — the daemon no longer calls `record_sent`. `record_sent` (and `was_sent`) remain exported in store.py; `was_sent` is still used by `_run_catchup`'s injected reader.
- **release on non-ok AND on raised delivery, behind a `claimed` flag.** Because the claim is taken before the send, a failed send must release it to keep the slot re-fireable. The `claimed`/`local_date` guard ensures the except-block release only undoes a claim this caller actually won — never a wrong row, and never an unbound-name error if an exception is raised before `local_date` is computed (e.g. bad timezone).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Guarded the except-block release with a `claimed` flag**
- **Found during:** Task 2 (gate fire_slot delivery on claim_slot)
- **Issue:** The plan prescribed calling `release_claim(...)` directly in the `except` block. But if an exception is raised BEFORE the claim is taken (e.g. `ZoneInfo(location.timezone)` raising, leaving `local_date` unbound) or while the claim was NOT won, an unconditional release would either raise `NameError` inside the except (breaking per-job isolation, T-03-07) or delete a `sent_log` row this caller never owned (silently un-recording a slot a concurrent winner had just claimed — a correctness regression).
- **Fix:** Introduced a `claimed` boolean (set `True` only after a won claim, reset to `False` after a release on non-ok) and initialized `local_date = None`; the except-block release runs only `if claimed and local_date is not None`. The non-ok branch still releases unconditionally (the claim is always held there).
- **Files modified:** weatherbot/scheduler/daemon.py
- **Verification:** `test_fire_slot_isolates_exception` passes (raise isolated, `was_sent` False afterward — the claim taken before the raising send is released); full suite green.
- **Committed in:** `367ea31` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 missing-critical correctness guard)
**Impact on plan:** The guard is required for correctness and to preserve the per-job exception isolation the plan and existing `test_fire_slot_isolates_exception` depend on. No scope creep — same files, same behavior intent, hardened edge case.

## TDD Gate Compliance

This plan is `type: tdd` and was executed as two atomic feature steps rather than separate `test(...)` → `feat(...)` commits: the failing-without-implementation test (`test_concurrent_double_fire_delivers_once`, which imports `claim_slot`/`release_claim` — symbols that do not exist pre-plan) was committed in the SAME commit (`a2d2c95`) as the helpers that make it pass, since the RED assertion cannot even import against the pre-plan store. The git log therefore shows two `feat(03-05)` commits, not a distinct `test(...)` RED gate commit. The exactly-once behavior is nonetheless test-asserted (claim arbitration + one-POST). Flagging the absence of a standalone RED `test(...)` commit for transparency.

## Issues Encountered
None — both tasks executed cleanly; the only adjustment was the correctness guard documented under Deviations.

## Out-of-Scope / Deferred
- **WR-02** (dedup key omits `day_of_week`) and **WR-06** (live-job `local_date` midnight off-by-one) — explicitly out of scope per the plan's Task 2 note; not trivially co-located, so not folded in. Carried forward for a future plan/phase.
- **Pre-existing `ruff format` drift** in 9 unrelated repo files (e.g. `weatherbot/channels/discord.py`, `weatherbot/weather/models.py`) reported by `uv run ruff format --check .`. NOT touched (SCOPE BOUNDARY — not caused by this plan's changes). The two files this plan modified (`daemon.py`, `store.py`) are `ruff check` + `ruff format --check` clean.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SCHD-07 delivery-level exactly-once now holds at the delivery boundary, not just the row boundary — gap #2 from 03-VERIFICATION.md is closed.
- Combined with 03-04 (DST-correct catch-up planner, gap #1), both Phase 3 blockers are addressed; the phase is ready for re-verification of success criteria #3 (DST) and #5 (exactly-once).
- Phase 4 (reliability / retry-then-alert) builds on the release-on-failure seam: a failed delivery now cleanly re-opens the slot for a bounded catch-up re-fire.

## Self-Check: PASSED

- FOUND: weatherbot/weather/store.py
- FOUND: weatherbot/scheduler/daemon.py
- FOUND: tests/test_scheduler.py
- FOUND: .planning/phases/03-always-on-scheduler/03-05-SUMMARY.md
- FOUND commit: a2d2c95 (Task 1)
- FOUND commit: 367ea31 (Task 2)

---
*Phase: 03-always-on-scheduler*
*Completed: 2026-06-10*
