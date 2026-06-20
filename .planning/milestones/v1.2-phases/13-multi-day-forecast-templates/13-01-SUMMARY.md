---
phase: 13-multi-day-forecast-templates
plan: 01
subsystem: weather
tags: [forecast, multiday, extraction, window-selection, pure-logic]
requirements-completed: [FCAST-01, FCAST-02, FCAST-04, FCAST-07]
dependency-graph:
  requires: []
  provides:
    - "ForecastDay per-day extraction model (weatherbot/weather/models.py)"
    - "multiday.select_days window/roll-forward selector (weatherbot/weather/multiday.py)"
    - "8-element daily[] fixtures (imperial + metric)"
  affects:
    - "Plan 13-02 renderer (consumes ForecastDay.day_tokens + select_days indices)"
    - "Plan 13-04/05 forecast handler + scheduled forecast (day labels + window)"
tech-stack:
  added: []
  patterns:
    - "Pure dependency-free logic module (mirror scheduler/days.py)"
    - "Defensive .get(...) or default daily[i] read (mirror Forecast.from_payloads)"
    - "_temp_str verbatim copy for byte-identical imperial-primary display"
    - "Local-date->index resolution (never positional daily[] math)"
key-files:
  created:
    - weatherbot/weather/multiday.py
    - tests/fixtures/onecall_8day_imperial.json
    - tests/fixtures/onecall_8day_metric.json
    - tests/test_multiday.py
  modified:
    - weatherbot/weather/models.py
decisions:
  - "ForecastDay.from_daily takes label as a parameter (caller computes Today/Tomorrow) — Plan 04/05 owns labeling"
  - "select_days accepts a tz NAME string and resolves ZoneInfo internally (UTC fallback), keeping the module pure"
  - "Whole-block roll-forward only when EVERY base day is past; +day flags always use next-occurrence (so an added past day rolls forward and may become a horizon notice)"
  - "16-point compass duplicated into weather.models (not imported from interactive) to keep weather layer free of the interactive layer"
metrics:
  duration: ~25 min
  tasks: 2
  files: 5
  tests-added: 16
  completed: 2026-06-19
---

# Phase 13 Plan 01: Multi-Day Forecast Foundations Summary

Built the two genuinely-new pure-logic foundations every other Phase 13 plan consumes: the `ForecastDay` per-day extraction model (reads `daily[i]`, mirrors `Forecast._temp_str` for byte-identical imperial-primary display, derives feels-like hi/lo from dayparts) and the `multiday.select_days` window/roll-forward selector (D-01 still-upcoming-days + whole-block roll-forward, D-03 out-of-horizon notices), plus the Wave-0 8-element dated `daily[]` fixtures that drive deterministic window tests.

## What Was Built

### Task 1 — 8-day fixtures + `ForecastDay`
- `tests/fixtures/onecall_8day_imperial.json` / `_metric.json`: 8 dated `daily[]` entries spanning Fri 2026-06-19 → Fri 2026-06-26 in `America/New_York`, with distinguishable per-day temp/pop/sky/feels-like so window and extraction tests are unambiguous. Metric twin carries the same dates with exact °F→°C / mph→m/s conversions.
- `ForecastDay` dataclass + `from_daily(day_imp, day_met, *, label, primary, tz_name)`: defensive `.get(...) or default` reads (T-13-01); feels-like high/low = `max`/`min` over the four `feels_like` dayparts (Pitfall 3 — no `feels_like.max`); `_temp_str` copied verbatim from `Forecast`; `day_tokens(detailed)` returns the 4 compact / 11 detailed flat `str→str` keys; sunrise/sunset rendered as local `HH:MM` in the configured tz.

### Task 2 — `multiday.select_days`
- New pure dependency-free module (no config/apscheduler/store import), mirroring `scheduler/days.py`. Reuses `days._DAYS` as the `+day`/`-day` token vocabulary (one source of truth) and sanitizes flag tokens against it.
- `select_days(kind, today_local, daily, add, drop, tz)` → `(indices, notices)`: base block by kind (ValueError on unknown — T-13-03), apply drop then add, dedup; keep still-upcoming days, roll the whole block forward one week only when every base day is past; resolve each desired date to its `daily[]` index by matching the entry's local date (Pitfall 1 — never positional math); dates with no in-window entry become `"… is beyond the 7-day forecast horizon"` notices (Pitfall 2). `today` authority is the configured IANA tz (Pitfall 6).

## Verification

- `uv run pytest tests/test_multiday.py -x -q` → 16 passed.
- `uv run pytest -q` full suite → **374 passed** (was 358; +16), no regressions.
- `grep -c "import" weatherbot/weather/multiday.py` shows no config/apscheduler/store import (acyclic, pure).
- `ruff check` clean on all touched files.

### Acceptance criteria
- `class ForecastDay` present; 8-day fixture asserts `len(daily)==8`.
- compact `day_tokens` keys == `{label,high,low,sky}`; detailed == 11 keys.
- imperial-primary high display byte-identical to `_temp_str` (`"76°F (24°C)"`).
- `feels_high` == max of dayparts (no KeyError).
- `def select_days` present; reuses `days._DAYS`; zero `date.today()`.
- weekday Monday run → 5 indices/0 notices; weekend → Fri-Sat-Sun; `+sat` beyond horizon → notice; Saturday weekday run rolls forward, no IndexError; `-mon +sat` deduped+sorted.

## Deviations from Plan

None — plan executed as written. (The compass helper for per-day wind was duplicated into `weather/models.py` rather than imported from `interactive/commands/weather_views.py`, to avoid the weather layer depending on the interactive layer — consistent with the PATTERNS "keep `multiday`/model layers acyclic" guidance; not a behavior deviation.)

## TDD Gate Compliance

Both tasks followed RED → GREEN. Git log shows the required gate commits per task:
- Task 1: `test(13-01)` (6e06082) → `feat(13-01)` (bf527d0).
- Task 2: `test(13-01)` (1915aa6) → `feat(13-01)` (6733c6b).

No REFACTOR commits were needed (implementations were clean on first GREEN).

## Known Stubs

None. Both modules are fully wired pure logic with passing tests; consumers (renderer, handler, scheduler) land in Plans 02–05.

## Self-Check: PASSED

- FOUND: weatherbot/weather/multiday.py
- FOUND: tests/fixtures/onecall_8day_imperial.json
- FOUND: tests/fixtures/onecall_8day_metric.json
- FOUND: tests/test_multiday.py
- FOUND: weatherbot/weather/models.py (ForecastDay)
- FOUND commit: 6e06082, bf527d0, 1915aa6, 6733c6b
