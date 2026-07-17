---
phase: 34-test-gap-backfill
plan: 04
subsystem: weather
tags: [testing, coverage, dt-pairing, today-selector, HARD-TEST-02]
requires:
  - weatherbot/weather/models.py::Forecast.from_payloads
  - weatherbot/weather/dates.py::select_today_daily
provides:
  - "F107 [EXISTS] citation: test_dt_paired_briefing pins dt-anchored pairing + degrade-not-mispair guard"
  - "F109 positive pin: today-not-at-daily[0] is selected by date, not position"
affects:
  - tests/test_models.py
tech-stack:
  added: []
  patterns:
    - "Discriminating positive/negative test twins for date-anchored daily selection"
    - "Assert-by-construction: decoy entries at daily[0]/[1] catch any positional regression"
key-files:
  created: []
  modified:
    - tests/test_models.py
decisions:
  - "F107 confirmed [EXISTS] (D-08) — no duplicate; only the HARD-TEST-02 tag added to the docstring"
  - "F109 GREEN against current code — select_today_daily is already date-anchored; no D-07 fold-in, dates.py untouched"
metrics:
  duration: "~4 min"
  completed: "2026-07-13"
  tasks: 2
  files: 1
status: complete
---

# Phase 34 Plan 04: F107/F109 daily selection + pairing coverage Summary

Confirmed F107 dt-anchored imperial/metric daily pairing is already pinned [EXISTS] and added a discriminating F109 positive test proving the today-selector is date-anchored (today at `daily[2]` is selected, not positional `daily[0]`) — both cite HARD-TEST-02.

## What Was Done

### Task 1 — F107 dt-pairing confirmed [EXISTS] (commit `5cf41c2`)
`test_dt_paired_briefing` (test_models.py:141) already asserts BOTH the imperial anchor (`high_display == "76°F"` / `low_display == "58°F"`) AND the degrade-not-mispair guard (`fc.high_display != "76°F (100°C)"`, :163). Per D-08 this is confirmed [EXISTS] and cited for SC-3 — **not duplicated**. The only change was adding the `HARD-TEST-02` requirement tag to the docstring (D-02). Verified green: `pytest -k dt_pair` → 1 passed.

### Task 2 — F109 positive test added (commit `4ea11ae`)
Added `test_daily0_today_not_at_index_zero_selects_today` (the discriminating positive twin of the negative `test_daily0_not_today_degrades`). A `_place_today_at_index_two` helper builds a `daily` array with two earlier-dated decoy entries (day-before at index 0 with 111/99, yesterday at index 1 with 222/200) and the real 2024-06-14 TODAY entry at index 2 (76/58). The test asserts `fc.high_imp == 76.0` / `fc.low_imp == 58.0` (the index-2 today values, NOT the index-0 decoy) and `fc.local_date == "2024-06-14"`.

**D-07 watchpoint outcome:** the test is **GREEN against current code** — `select_today_daily` (dates.py:77) correctly derives each entry's own local date from its `dt` and matches today by date, never by position. No real escape was found, so **no minimal fix was folded in and `weatherbot/weather/dates.py` was left untouched** (confirmed by an empty `git diff` on dates.py across both commits).

## Deviations from Plan

None — plan executed exactly as written. F107 was [EXISTS] as anticipated (no strengthening needed beyond the tag); F109 passed as written (no D-07 correctness fold-in required).

## Verification

- `uv run pytest tests/test_models.py -k dt_pair -x -q` → 1 passed (F107).
- `uv run pytest tests/test_models.py -k daily0_today_not_at_index_zero -x -q` → 1 passed; narrowed `-k` uniquely gates the NEW test (negative twin not matched — SC-3 pre-fix-red guarantee preserved).
- `uv run pytest tests/test_models.py -k "dt_pair or daily0" -x -q` → 3 passed.
- `uv run pytest tests/test_models.py -q` → 46 passed (full module green).

## Known Stubs

None.

## Self-Check: PASSED

- Commits `5cf41c2`, `4ea11ae` — FOUND.
- `tests/test_models.py` — FOUND.
- `weatherbot/weather/dates.py` — unchanged (empty diff), consistent with "no D-07 escape" claim.
