---
phase: 32-timezone-date-boundary-correctness
plan: 03
subsystem: scheduler
tags: [catchup, dst, zoneinfo, fold, timezone, apscheduler, exactly-once]

# Dependency graph
requires:
  - phase: 32-01
    provides: "Wave-0 failing-first (RED) regression tests test_catchup_prior_local_day + test_catchup_fold_grace_not_inflated, and the injected-now_utc catch-up test conventions"
provides:
  - "plan_catchup recovers a slot missed across local midnight (23:45 missed → 00:15 next day recovered within grace), keyed on the CANDIDATE (yesterday) local date (D-01/F14)"
  - "A regression test that PINS the fold=0 / live-CronTrigger agreement across a DST fall-back repeated hour, so the D-01 candidate loop (or any future edit) can never silently introduce a fold=1 divergence (D-02/F91)"
affects: [scheduler, catchup, dst, "32-04", "32-05", verify-work]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Candidate-date loop {today, yesterday-local} keyed on the candidate day, reusing the existing gap/fold roundtrip compose verbatim"
    - "fold=0 compose kept aligned with the live apscheduler 3.11.2 CronTrigger; agreement pinned by a regression test rather than 'fixed' with both-folds math"

key-files:
  created: []
  modified:
    - "weatherbot/scheduler/catchup.py — plan_catchup gained the {today, yesterday} candidate loop + candidate-day keying + per-slot emitted_dates dedup (Task 1); a clarifying comment documenting the verified fold=0/CronTrigger agreement (Task 2, no behavior change)"
    - "tests/test_scheduler.py — test_catchup_fold_grace_not_inflated rewritten to pin the fold=0 agreement instead of the disproven keep-at-100-min behavior (Task 2)"

key-decisions:
  - "D-01: plan_catchup evaluates {today, yesterday-local} candidate days per slot, composing each candidate's naive wall-clock, attaching the location zone, running the SAME gates, and keying MissedSlot/was_sent on the CANDIDATE day — so a 23:45 slot recovered at 00:15 next day is caught up within grace instead of skipped as 'not due yet'."
  - "D-02 (orchestrator override / Rule-3): the plan's mandated both-folds min() grace was NOT implemented. A live apscheduler 3.11.2 probe verified CronTrigger fires the DST fall-back slot at fold=0, and catchup already composes fold=0 — they agree, so there is no grace inflation to correct. Both-folds min() would regress the locked SCHD-04 band test. Delivered protection = a rewritten test that pins the fold=0 agreement."

patterns-established:
  - "Pattern: pin an external-tool agreement (CronTrigger fold) with a regression test rather than adding defensive math that can regress a locked sibling test"
  - "Pattern: per-slot emitted_dates dedup guarantees a single slot never emits twice even when both today and yesterday candidates fall within grace"

requirements-completed: [HARD-TZ-01]

coverage:
  - id: D1
    description: "A 23:45 daily slot missed the prior local day and evaluated at 00:15 the next local day yields exactly ONE MissedSlot keyed on YESTERDAY's local_date, within GRACE; per-slot dedup + candidate-day was_sent keep it exactly-once (D-01/F14)."
    requirement: "HARD-TZ-01"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py::test_catchup_prior_local_day"
        status: pass
    human_judgment: false
  - id: D2
    description: "Catch-up composes the DST fall-back repeated-hour slot at the fold=0 instant the live CronTrigger fires (verified apscheduler 3.11.2); a slot within grace of that fold=0 instant is due, one beyond grace is skipped; the fold=0 agreement is pinned so a future edit cannot introduce a fold=1 divergence (D-02/F91)."
    requirement: "HARD-TZ-01"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py::test_catchup_fold_grace_not_inflated"
        status: pass
      - kind: unit
        ref: "tests/test_scheduler.py::test_dst_transition_band_exactly_once"
        status: pass
    human_judgment: false

metrics:
  duration: "~12 min (Task 1 + Task 2 execution window; Task 1 committed 01:30, Task 2 01:42)"
  completed: "2026-07-11"
  tasks_completed: 2
  files_touched: 2

status: complete
---

# Phase 32 Plan 03: Catch-up across local midnight + DST fall-back grace Summary

`plan_catchup` now survives local midnight (a 23:45 slot recovered at 00:15 the next day is caught up within grace, keyed on yesterday's local date) via a `{today, yesterday-local}` candidate loop; and the fold=0 / live-CronTrigger agreement across a DST fall-back repeated hour is pinned by a regression test — the plan's mandated both-folds `min()` grace was overridden as a non-bug once the live fold behavior was measured.

## Accomplishments

- **Task 1 (D-01/F14, committed `2276bd2`):** Wrapped the compose/gates block in a `for cand_date in (now_local.date(), now_local.date() - timedelta(days=1))` loop, composing each candidate's naive wall-clock, keying `MissedSlot`/`was_sent` on the CANDIDATE day (never `now_local.date()`), evaluating `fires_on` per-candidate-day (so a weekend-only slot is never recovered on a weekday it does not run), and adding a per-slot `emitted_dates` dedup. The spring-forward GAP skip and fold=0 compose are preserved unchanged. `test_catchup_prior_local_day` turned GREEN.
- **Task 2 (D-02/F91, committed `c5f9cc6`):** Rewrote `test_catchup_fold_grace_not_inflated` to pin the fold=0/CronTrigger agreement (see deviation below) and added a clarifying comment in `catchup.py` documenting the verified agreement and why both-folds `min()` was rejected. No production behavior change — the grace formula stays `now_utc - scheduled > GRACE` at fold=0.

## Deviations from Plan

### Overrides / Rule-3 deviations

**1. [Rule 3 - Orchestrator override] Did NOT implement the plan's mandated both-folds `min()` grace comparison (D-02/F91)**

- **Found during:** Task 2 (the previous executor correctly escalated a genuine spec contradiction; the orchestrator resolved it as Option B).
- **Issue — F91's premise is disproven by the research's own live probe.** F91 assumed the live APScheduler `CronTrigger` fires a DST fall-back slot at `fold=1`, so a `fold=0` compose would inflate lateness ~60 min. The probe in `32-RESEARCH.md` verified `CronTrigger` actually fires at **`fold=0`**, and `catchup.py` already composes `scheduled` at `fold=0` — **they already agree**. A slot 100 min past fold=0 is genuinely 100 min late (past the 90-min GRACE) and is correctly skipped; there is no grace-inflation bug.
- **Issue — the both-folds `min()` "fix" regresses established correct behavior.** It would make the LOCKED SCHD-04 test `test_dst_transition_band_exactly_once` fail: that test correctly SKIPS a slot 120 min past fold=0, but `min(120, 60)=60 ≤ GRACE` would wrongly KEEP it. Both tests cannot hold; the band test is the correct one.
- **Resolution (Option B — F91 is a non-bug given verified fold=0 behavior):**
  - The grace formula in `catchup.py` was left **UNCHANGED** (`now_utc - scheduled > GRACE`, fold=0). No both-folds `min()` code was added. Task 1's candidate-date loop stays.
  - The locked `test_dst_transition_band_exactly_once` was **not touched**.
  - `test_catchup_fold_grace_not_inflated` (same name — preserves the VALIDATION.md mapping) had its body/docstring replaced to assert the CORRECT, probe-verified invariant: for a fall-back 01:30 slot scanned within grace of the fold=0 instant, `plan_catchup` returns exactly ONE `MissedSlot` whose `scheduled_dt` equals the fold=0 instant (== what CronTrigger fires) and `local_date == "2026-11-01"`; a scan beyond grace of fold=0 returns `[]`. This fails if catch-up ever composes fold=1 (`scheduled_dt` would equal `second_0130_est`), pinning the agreement against a future D-01/refactor divergence. It no longer asserts the disproven keep-at-100-min behavior.
  - A clarifying comment was added at `catchup.py`'s grace gate documenting the verified fold=0/CronTrigger agreement and why both-folds `min()` was considered and rejected (no behavior change).
- **D-02's invariant is satisfied:** "a slot minutes-late in the repeated hour is not dropped by a spurious inflation" holds because catch-up's fold=0 compose stays aligned with CronTrigger — there IS no spurious inflation, since fold=0 is the correct reference. The delivered protection is the fold=0-agreement pin.
- **Files modified:** `weatherbot/scheduler/catchup.py` (comment only), `tests/test_scheduler.py` (test rewrite).
- **Commit:** `c5f9cc6`.

### Incidental fix

**2. [Rule 1 - Test correctness] UTC-normalized instant comparison in the rewritten test**

- When asserting `scheduled_dt` equals the fold=0 instant, an aware `==` between a fold-ambiguous `ZoneInfo` wall-clock (`datetime(2026,11,1,1,30, tzinfo=NY)`) and a UTC instant returns `False` even for the same moment. The rewritten test normalizes both sides to UTC (`.astimezone(ZoneInfo("UTC"))`) before comparing. This is a test-only correctness detail, not a production change.

## Verification

- `uv run pytest tests/test_scheduler.py -q` → **63 passed** (full scheduler suite green, including `test_catchup_prior_local_day`, the rewritten `test_catchup_fold_grace_not_inflated`, the untouched locked `test_dst_transition_band_exactly_once`, and `test_dst_exactly_once`).
- `uv run pytest -q` → **836 passed, 7 failed**. The 7 failures are the later-plan (32-04/32-05) Wave-0 failing-first RED tests (`test_import_hygiene::test_dates_single_helper_no_local_copies`, `test_models::{test_daily0_not_today_degrades, test_naive_now_utc_treated_as_utc}`, `test_uv::{test_compute_uv_daily0_today_guard, test_hourly_points_sorted_before_interpolation}`, `test_uv_monitor::{test_allclear_not_latched_on_momentary_dip, test_lifecycle_full_day_no_never_fire_gap}`). Confirmed identical at the Task-1 baseline (stash-and-rerun) — **no new regression**; this plan's rewrite moved `test_catchup_fold_grace_not_inflated` from RED→GREEN (835→836 passing).
- `grep` confirms `catchup.py` has the `for cand_date in (now_local.date(), now_local.date() - timedelta(days=1))` loop and NO both-folds `min()` grace code; the compose stays `naive.replace(tzinfo=tz)` (fold=0).

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file access, or schema changes. The exactly-once catch-up dedup (T-32-06) and the missed-briefing DoS surface (T-32-07) are addressed: candidate-day keying + per-slot dedup + fold=0 CronTrigger agreement.

## Self-Check: PASSED

- FOUND: `.planning/phases/32-timezone-date-boundary-correctness/32-03-SUMMARY.md`
- FOUND: `weatherbot/scheduler/catchup.py`
- FOUND: commit `2276bd2` (Task 1, D-01/F14)
- FOUND: commit `c5f9cc6` (Task 2, D-02/F91 fold=0 pin)
