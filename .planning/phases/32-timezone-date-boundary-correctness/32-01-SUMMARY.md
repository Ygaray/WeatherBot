---
phase: 32-timezone-date-boundary-correctness
plan: 01
subsystem: testing
tags: [pytest, timezone, dst, zoneinfo, failing-first, regression, catchup, uv-monitor]

# Dependency graph
requires:
  - phase: 32-RESEARCH / 32-VALIDATION / 32-PATTERNS
    provides: verified F14/F15/F31/F32/F33/F35/F69/F91 reproductions, injected-now_utc test conventions, and the fold=0 CronTrigger-agreement fact
provides:
  - Nine failing-first (RED) regression tests (10 test functions) pinning every locked decision (D-01..D-08) for phase 32
  - The two CONFIRMED scenarios (F14 catch-up-across-midnight, F15 UV all-clear latch) each have a RED test
  - An un-cheatable F31 test (asserts stays_below/crossing_time, not max) that only a window-bound anchor can turn green
affects: [32-02, 32-03, 32-04, 32-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Failing-first (TDD RED) Wave-0 scaffold — tests assert the correct-but-not-yet-implemented behavior; later waves turn them GREEN"
    - "Un-cheatable window-bound assertion (stays_below/crossing_time, never max) so a display-only fix cannot false-pass F31"
    - "Both-folds min() grace scenario encoded so a fold-0-only grace check stays RED (D-02 un-cheatable)"

key-files:
  created: []
  modified:
    - tests/test_scheduler.py
    - tests/test_uv_monitor.py
    - tests/test_models.py
    - tests/test_uv.py
    - tests/test_import_hygiene.py

key-decisions:
  - "Used days='daily' (not the plan's literal 'mon-sun') because the Schedule validator rejects 'mon-sun' as an INPUT preset (it normalizes to 'mon-sun' internally). Same coverage, valid config."
  - "F33 naive-now_utc test asserts the deterministic UTC-interpreted local_date (2024-06-13); it is genuinely RED on this MST/MDT dev host and GREEN everywhere after the fix (host-independent assertion)."
  - "The dates same-output test ImportErrors inside the test body (dates.py absent) — an acceptable RED per the plan; it becomes an assertion once 32-02 lands the module."

patterns-established:
  - "Wave-0 failing-first regression: each locked decision ships with a test that FAILS against pre-fix behavior and turns GREEN in the fix wave"
  - "Traceability comment tags (#D-01/#D-02/#F14/#F15/#F31/#F32/#F91) on load-bearing asserts"

requirements-completed: []  # Wave-0 authors the RED tests; the requirements (HARD-TZ-01..04) are marked complete when the fix waves (32-02..32-05) turn these tests GREEN.

coverage:
  - id: D1
    description: "23:45 slot recovered at 00:15 next local day → exactly ONE MissedSlot keyed on YESTERDAY (F14/D-01) + boundary edges"
    requirement: "HARD-TZ-01"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py::test_catchup_prior_local_day"
        status: fail   # RED by design — turns GREEN in 32-03
    human_judgment: false
  - id: D2
    description: "Fall-back 01:30 slot minutes-late in the repeated hour stays due (fold-union grace, not inflated 60 min) (F91/D-02)"
    requirement: "HARD-TZ-01"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py::test_catchup_fold_grace_not_inflated"
        status: fail
    human_judgment: false
  - id: D3
    description: "Momentary solar-noon UV dip (5.8<6.0) while still peaking does NOT post/claim all-clear (F15/D-03)"
    requirement: "HARD-TZ-02"
    verification:
      - kind: unit
        ref: "tests/test_uv_monitor.py::test_allclear_not_latched_on_momentary_dip"
        status: fail
    human_judgment: false
  - id: D4
    description: "Full-day tick walk: prewarn/crossing/all-clear each fire exactly once, all-clear anchored to genuine window-end, no never-fire gap (D-04)"
    requirement: "HARD-TZ-02"
    verification:
      - kind: unit
        ref: "tests/test_uv_monitor.py::test_lifecycle_full_day_no_never_fire_gap"
        status: fail
    human_judgment: false
  - id: D5
    description: "A yesterday-dated daily[0] degrades (high/low None) instead of shipping yesterday's numbers as today's (F35/D-05)"
    requirement: "HARD-TZ-03"
    verification:
      - kind: unit
        ref: "tests/test_models.py::test_daily0_not_today_degrades"
        status: fail
    human_judgment: false
  - id: D6
    description: "Naive now_utc treated as UTC so local_date is not host-tz shifted (F33/D-06)"
    requirement: "HARD-TZ-03"
    verification:
      - kind: unit
        ref: "tests/test_models.py::test_naive_now_utc_treated_as_utc"
        status: fail
    human_judgment: false
  - id: D7
    description: "compute_uv with yesterday daily[0] (sunset predating today's crossing) does NOT falsely report stays_below; asserts stays_below/crossing_time NOT max — un-cheatable by a display-only swap (F31/D-05)"
    requirement: "HARD-TZ-03"
    verification:
      - kind: unit
        ref: "tests/test_uv.py::test_compute_uv_daily0_today_guard"
        status: fail
    human_judgment: false
  - id: D8
    description: "Out-of-order hourly buckets yield a time-sorted crossing/window (F32/D-07)"
    requirement: "HARD-TZ-03"
    verification:
      - kind: unit
        ref: "tests/test_uv.py::test_hourly_points_sorted_before_interpolation"
        status: fail
    human_judgment: false
  - id: D9
    description: "ONE weatherbot.weather.dates helper: three callers import it / none defines _local_date_iso; pure/deterministic same-output contract (F69/D-08)"
    requirement: "HARD-TZ-04"
    verification:
      - kind: unit
        ref: "tests/test_import_hygiene.py::test_dates_single_helper_no_local_copies"
        status: fail
      - kind: unit
        ref: "tests/test_import_hygiene.py::test_dates_helper_same_output_and_deterministic"
        status: fail
    human_judgment: false

# Metrics
duration: 25min
completed: 2026-07-11
status: complete
---

# Phase 32 Plan 01: Wave-0 Failing-First Regression Tests Summary

**Authored nine failing-first (RED) regression tests (10 functions across five test files) that pin every locked timezone/date-boundary decision (D-01..D-08) — including both CONFIRMED scenarios (F14 catch-up-across-midnight, F15 UV all-clear latch) — with the F31 test made un-cheatable by asserting stays_below/crossing_time instead of max.**

## Performance

- **Duration:** ~25 min
- **Tasks:** 3 completed
- **Files modified:** 5 (all test files; zero production code)

## Accomplishments

- **Task 1 (catch-up, D-01/D-02):** `test_catchup_prior_local_day` (23:45→00:15 recovery keyed on YESTERDAY, + scheduled==now / now-GRACE / one-second-past-GRACE edges) and `test_catchup_fold_grace_not_inflated` (fall-back 01:30 slot 100 min past fold=0 but 40 min past fold=1 stays due — a fold-0-only grace check keeps it RED, so the test is un-cheatable).
- **Task 2 (UV monitor, D-03/D-04):** `test_allclear_not_latched_on_momentary_dip` (a 5.8<6.0 dip at solar-noon while still peaking posts nothing AND claims no `allclear` row) and `test_lifecycle_full_day_no_never_fire_gap` (prewarn@10:00 → crossing@11:00 → mid-window dip@12:00 posts nothing → genuine all-clear@16:00, each kind exactly once; + empty-hourly no-latch/no-raise edge).
- **Task 3 (models/uv/import-hygiene, D-05/D-06/D-07/D-08):** `test_daily0_not_today_degrades`, `test_naive_now_utc_treated_as_utc`, `test_compute_uv_daily0_today_guard` (un-cheatable F31), `test_hourly_points_sorted_before_interpolation`, and two import-hygiene tests (`test_dates_single_helper_no_local_copies`, `test_dates_helper_same_output_and_deterministic`).
- **Reproduction-verified every scenario** against live pre-fix behavior with `uv run python` probes before writing the assertion, so each test is RED for the RIGHT reason (asserting the correct behavior), never a bug in the test.

## RED status (expected and correct at Wave 0)

Full suite after this plan: **833 passed, 10 failed** — the 10 failures are EXACTLY the new failing-first tests; zero pre-existing tests regressed. The "2 snapshots failed" line is the known pre-existing syrupy quirk (not a golden diff).

| Test | Decision | Why RED now | Turns GREEN in |
|------|----------|-------------|----------------|
| test_catchup_prior_local_day | D-01/F14 | plan_catchup composes only today's date → the 23:45 slot is future → 0 MissedSlots | 32-03 |
| test_catchup_fold_grace_not_inflated | D-02/F91 | bare `now-scheduled>GRACE` inflates 60 min across the fall-back hour (fold=0 only) | 32-03 |
| test_allclear_not_latched_on_momentary_dip | D-03/F15 | branch 3 latches on the instantaneous dip (uvmonitor.py:318) | 32-05 |
| test_lifecycle_full_day_no_never_fire_gap | D-04 | the 12:00 mid-window dip fires a premature all-clear | 32-05 |
| test_daily0_not_today_degrades | D-05/F35 | from_payloads hard-indexes daily[0] (models.py:302) | 32-02/32-04 |
| test_naive_now_utc_treated_as_utc | D-06/F33 | astimezone() reinterprets a naive value in the host tz | 32-02/32-04 |
| test_compute_uv_daily0_today_guard | D-05/F31 | _today_daytime_points window bound is positional daily[0] (uv.py:109/135) | 32-04 |
| test_hourly_points_sorted_before_interpolation | D-07/F32 | _today_daytime_points appends in raw order (uv.py:145) | 32-04 |
| test_dates_single_helper_no_local_copies | D-08/F69 | three files still define their own _local_date_iso | 32-02/32-04 |
| test_dates_helper_same_output_and_deterministic | D-08/HARD-TZ-04 | weatherbot/weather/dates.py does not exist yet (ImportError in body) | 32-02 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Config validator rejects `days="mon-sun"` as an input preset**
- **Found during:** Task 1
- **Issue:** The plan text prescribed `_home_config(days="mon-sun", time="23:45")`, but `Schedule.days` validation only accepts the INPUT presets `['daily', 'mon-fri', 'weekdays', 'weekends']` or a comma list — `'mon-sun'` is the NORMALIZED internal value, not a valid input (it raises a pydantic ValidationError at config build).
- **Fix:** Used `days="daily"` (which normalizes to `mon-sun`), matching the existing `test_dst_exactly_once`/`test_dst_transition_band_exactly_once` convention. Identical daily-coverage semantics; no impact on what the test pins.
- **Files modified:** tests/test_scheduler.py
- **Commit:** ebfab66

No other deviations. No architectural changes, no auth gates, no package installs.

## Known Stubs

None. These are tests, not production code; no placeholder data flows anywhere.

## Threat Flags

None. No new security surface — the tests synthesize malformed/adversarial payloads (yesterday daily[0], out-of-order/empty hourly, naive now_utc) to pin the defensive-degrade posture the later fixes must honor (T-32-01/T-32-02 in the plan's threat register). No live network, no new inputs/sinks/auth.

## Notes for downstream waves

- The F31 test (`test_compute_uv_daily0_today_guard`) asserts on `stays_below is False` AND `crossing_time is not None` — a display-only swap of `compute_uv:219`'s `max_uvi` will NOT turn it green; only anchoring `_today_daytime_points`' `sunrise`/`sunset` window bound to the today daily entry (32-04 task 2 part a) can.
- The D-02 test (`test_catchup_fold_grace_not_inflated`) requires the both-folds `min()` grace check AND the fold=0 composed `scheduled` (asserts `missed[0].scheduled_dt == first_0130_edt`) — do NOT switch the compose to fold=1.
- The catch-up tests use `days="daily"`, not `"mon-sun"` — reuse this when extending.

## Self-Check: PASSED
- All five modified test files exist and were committed (ebfab66, d4adf39, 4e2b060).
- 10 new test functions collect and are RED; 833 pre-existing tests pass; zero regressions.
- No file under `weatherbot/` was modified (verified via `git diff --name-only`).
