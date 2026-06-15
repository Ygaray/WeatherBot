---
phase: 01-first-briefing-end-to-end
plan: 02
subsystem: weather-data-layer
tags: [weather, openweather, httpx, aggregation, forecast-model, tdd, fixtures]
requires:
  - "weatherbot.config.models: Location (lat/lon/name)"
  - "tests/conftest.py: load_fixture helper"
  - "tests/fixtures/*.json: recorded OpenWeather payloads (FCST-02 edge matrix)"
provides:
  - "weatherbot.weather.aggregate: today_aggregate(forecast_payload, now_utc=None) -> {high, low, rain_chance}"
  - "weatherbot.weather.client: fetch_current(loc, key, units), fetch_forecast(loc, key, units), BASE"
  - "weatherbot.weather.models: Forecast dataclass + Forecast.from_payloads(...) + placeholders()"
affects:
  - "Plan 03 (store): consumes Forecast retained raw payloads (DATA-03) + aggregation outputs"
  - "Plan 04 (renderer/embed/send_now): consumes Forecast.placeholders() (D-04) + display fields"
tech-stack:
  added: []
  patterns:
    - "PURE today_aggregate: local-date selection via city.timezone offset on unix dt (never dt_txt)"
    - "high/low from forecast-bucket aggregation, never current-endpoint temp_min/temp_max (Pitfall 2)"
    - "Defensive .get() parsing of untrusted-shape payloads (T-02-02); clear-sky rain-absent tolerated"
    - "httpx.Client with explicit 10s timeout (T-02-03); raise_for_status surfaces 401 (Pitfall 7)"
    - "httpx logger raised to WARNING so the appid in the request URL never leaks (T-02-01)"
    - "Forecast fetches BOTH imperial+metric for imperial-primary display (FCST-04), no conversion drift"
    - "Late-day high/low None -> display falls back to current temp (Open Question 2)"
    - "now_utc injection makes tz-boundary aggregation deterministic against recorded fixtures"
key-files:
  created:
    - weatherbot/weather/__init__.py
    - weatherbot/weather/aggregate.py
    - weatherbot/weather/client.py
    - weatherbot/weather/models.py
    - tests/test_aggregate.py
    - tests/test_client.py
    - tests/test_models.py
  modified: []
decisions:
  - "Aggregation derives target_date from city.timezone offset (not IANA tz) per Phase-1 Open Question 3"
  - "Fetch both imperial+metric (Open Question 1) so high/low/temp/wind have native values in each unit"
  - "Late-day (no local-today buckets): high/low None at aggregate; Forecast falls back to current temp"
  - "Redacted httpx request-URL logging at module import (logging level), not per-call, to close T-02-01"
metrics:
  duration: "~1 session (sequential executor, single pass)"
  completed: "2026-06-09"
  tasks: 3
  files: 7
requirements-completed: [FCST-01, FCST-02, FCST-03, FCST-04]
---

# Phase 1 Plan 2: Weather Data Layer Summary

Built the correctness core of the briefing — the httpx OpenWeather 2.5 client, the PURE
3-hour-bucket aggregation (today's high/low/rain on the location's LOCAL date), and the
normalized `Forecast` model that exposes imperial-primary-with-metric display fields, a flat
D-01 placeholder map, and the four retained raw payloads. All three pieces were built TDD
(RED → GREEN) against the seven recorded fixtures from Plan 01.

## What Was Built

- **Task 1 — `today_aggregate` (RED 8f51b62 / GREEN 9a68abd, FCST-02):** A PURE
  `today_aggregate(forecast_payload, now_utc=None) -> {"high", "low", "rain_chance"}`.
  Derives the location offset from `forecast_payload["city"]["timezone"]`, computes
  `target_date` as location-local today, and selects buckets by offsetting each bucket's
  unix `dt` (never `dt_txt`). `high = max(main.temp)`, `low = min(main.temp)` over selected
  buckets; `rain_chance = round(max(pop)*100)` with `pop` defaulted to 0.0. Returns
  `high`/`low` as `None` when no buckets match (late-day). All dict access guarded with
  `.get()` so a clear-sky day with no `rain` field aggregates without error. Six tests:
  rainy base, clear-sky, +offset (Sydney) and −offset (Honolulu) boundary, late-day-None,
  and a metric unit-agnostic case.
- **Task 2 — httpx client (RED a5696b3 / GREEN 4379081, FCST-01):** `weatherbot/weather/client.py`
  with `BASE`, a private `_get(path, lat, lon, key, units)` using `httpx.Client(timeout=10.0)`,
  passing `{lat, lon, appid, units, lang="en"}`, calling `raise_for_status()`, returning
  `r.json()`. `fetch_current`/`fetch_forecast` wrap it. Five offline tests via
  `httpx.MockTransport`: correct path/params for both endpoints, explicit-timeout assertion,
  401 raises and is not retried, and the `appid` never appears in any log record.
- **Task 3 — `Forecast` model (RED 47902f3 / GREEN 17c561a, FCST-03/04):** A `Forecast`
  dataclass with normalized current fields (temp imp+met, conditions, wind imp+met, humidity),
  aggregated high/low (imp+met) + `rain_chance`, the location-local `date`, and the four
  retained raw payloads. `from_payloads(...)` runs `today_aggregate` on BOTH the imperial and
  metric forecast payloads. Display properties `temp_display`/`wind_display`/`high_display`/
  `low_display` produce imperial-primary-with-metric strings (`68°F (20°C)`, `8 mph (3.6 m/s)`);
  `high_display`/`low_display` fall back to the current temp when aggregation returns `None`.
  `placeholders()` returns the flat str→str D-01 map. Six tests covering normalization,
  display strings, clear-sky, late-day fallback, retained payloads, and the placeholder set.

## Verification

- `uv run pytest tests/test_aggregate.py tests/test_client.py tests/test_models.py -x` → all green
  (6 + 5 + 6 = 17 new tests pass).
- `uv run pytest -q` → **26 passed, 1 xfailed** (`test_send_now_posts_briefing` strict-xfail
  remains, as expected — the pipeline is wired in Plan 04).
- `uv run ruff check .` → **All checks passed.**
- `grep -n 'dt_txt' weatherbot/weather/aggregate.py` and
  `grep -nE 'temp_min|temp_max' weatherbot/weather/aggregate.py` find only docstring/comment
  mentions; no code path reads those fields (verified separately — no `["dt_txt"]`/`.get("dt_txt")`
  or `temp_min`/`temp_max` access).
- `grep -n 'timeout' weatherbot/weather/client.py` shows the explicit `httpx.Client(timeout=_TIMEOUT)`.

## Acceptance Criteria

- [x] `uv run pytest tests/test_aggregate.py tests/test_client.py tests/test_models.py -x` exits 0.
- [x] Aggregation selects buckets by LOCAL date and survives the clear-sky and far-offset edges.
- [x] `Forecast` renders `72°F (22°C)` / `8 mph (3.6 m/s)`-style imperial-primary display.
- [x] Aggregation uses unix `dt` + `city.timezone`, never `dt_txt`, never current `temp_min`/`temp_max`.
- [x] Clear-sky and far-offset edges covered; rain_chance 0 on clear-sky with no exception.
- [x] Full suite green; the `test_send_now` xfail remains xfailed (not yet wired).
- [x] ruff clean.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical mitigation] httpx request-URL logging leaked the API key**
- **Found during:** Task 2 (GREEN), when `test_appid_not_logged` failed.
- **Issue:** `httpx` logs the FULL request URL at INFO on its `"httpx"` logger; that URL carries
  the secret `appid` query param. This is exactly the T-02-01 (Information Disclosure) threat the
  plan's threat model assigns `mitigate` to this file — the source had no redaction yet.
- **Fix:** Raised the `httpx` logger to `WARNING` at module import in `client.py` so the
  URL-bearing INFO line never emits; warnings/errors (which do not include the URL) still propagate.
- **Files modified:** `weatherbot/weather/client.py`
- **Commit:** 4379081

No other deviations — the three tasks were built as written.

## Threat Model Coverage

- **T-02-01 (key-in-URL leak):** mitigated — httpx logger raised to WARNING; asserted by
  `test_appid_not_logged`.
- **T-02-02 (malformed/partial payload crash):** mitigated — defensive `.get()` parsing throughout
  `aggregate.py` and `models.py`; clear-sky `rain`-absent and empty-bucket → `None` covered by
  `test_clear_sky` and `test_late_day_no_buckets`.
- **T-02-03 (slow/hanging response):** mitigated — explicit `httpx.Client(timeout=10.0)`; asserted by
  `test_explicit_timeout_set`.

No new threat surface introduced beyond the plan's `<threat_model>`.

## Known Stubs

None. Every function is fully wired against the recorded fixtures; no placeholder/empty data paths.

## TDD Gate Compliance

Each task followed RED → GREEN with the failing-test commit preceding implementation:
- Task 1: `test(01-02)` 8f51b62 → `feat(01-02)` 9a68abd
- Task 2: `test(01-02)` a5696b3 → `feat(01-02)` 4379081
- Task 3: `test(01-02)` 47902f3 → `feat(01-02)` 17c561a

No refactor commits were necessary.

## Self-Check: PASSED

- Created files verified present on disk: `weatherbot/weather/{__init__,aggregate,client,models}.py`,
  `tests/test_{aggregate,client,models}.py`, and this SUMMARY.
- All six per-task commits verified in git log: 8f51b62, 9a68abd, a5696b3, 4379081, 47902f3, 17c561a.
