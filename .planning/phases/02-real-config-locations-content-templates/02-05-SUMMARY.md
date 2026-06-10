---
phase: 02-real-config-locations-content-templates
plan: 05
subsystem: weather
tags: [units-override, forecast-display, openweather, jinja-render, cli, tdd]

# Dependency graph
requires:
  - phase: 02-real-config-locations-content-templates
    provides: "Forecast.from_payloads dual-unit (imp+met) display + placeholders() (02-02); validate_template/render send boundary + Location.units validated-but-inert field (02-03); --send-now composition root (02-01/02)"
provides:
  - "Per-location units override honored end-to-end: metric -> metric-primary, imperial/unset -> imperial-primary"
  - "Forecast.from_payloads(..., primary=) + Forecast.primary field selecting display order"
  - "Unit-order-aware display properties (temp/feels_like/high/low/wind)"
  - "_hints guarded against None feels_like/wind (WR-01 fix — no fabricated cold/wind line on degraded payload)"
  - "send_now threads location.units (default imperial) into the forecast build"
  - "config.example.toml advertises a working metric override"
affects: [scheduling, channels, templates]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Display-order axis: a single primary field flips presentation without re-fetching or converting (dual-unit fetch stays FCST-04 drift-free)"
    - "Threshold hints evaluate raw not-None-guarded values, separate from the or-0.0-coalesced display fields, so degraded payloads never fabricate hints"

key-files:
  created: []
  modified:
    - weatherbot/weather/models.py
    - weatherbot/cli.py
    - config.example.toml
    - tests/test_models.py
    - tests/test_send_now.py

key-decisions:
  - "primary defaults to 'imperial' so an unset Location.units keeps prior byte-identical output; only 'metric' flips the lead unit"
  - "Dual imperial+metric One Call fetch is preserved — the override selects display primary, never drops a call (DATA-03/FCST-04)"
  - "WR-01 folded in because it lives on the same _hints path this plan rewrote; remaining WR-02..06/IN-01..03 left deferred"
  - "do_check's literal 'imperial' reachability probe left unchanged (liveness probe, not a display path)"

patterns-established:
  - "Per-unit rounding preserved regardless of lead order (whole degrees; wind imperial whole, metric one decimal)"
  - "Raw-vs-coalesced split: hint thresholds read raw None-guarded values; display tolerates 0.0 coalesce"

requirements-completed: [LOC-02, CONF-03, CONF-01]

# Metrics
duration: 9min
completed: 2026-06-10
---

# Phase 02 Plan 05: Honor Per-Location units Override Summary

**The validated-but-inert `Location.units` override is now threaded end-to-end so a `units = "metric"` location renders a metric-primary briefing (`20°C (68°F)`, `3.6 m/s (8 mph)`) while imperial/unset stays imperial-primary — and a null `feels_like` no longer fabricates a false "cold" hint (WR-01).**

## Performance

- **Duration:** ~9 min
- **Tasks:** 2 (both TDD)
- **Files modified:** 5

## Accomplishments
- `Forecast.from_payloads` gained a `primary: str = "imperial"` keyword and a `Forecast.primary` dataclass field; the temp/feels_like/high/low/wind display properties and `placeholders()` now lead with the configured primary unit and keep the secondary in parens — canonical placeholder key set unchanged.
- `send_now` computes `primary = location.units or "imperial"` and passes it into the forecast build, closing CR-01: a metric location now delivers a metric-primary body end-to-end. The dual imperial+metric fetch (DATA-03 single round, FCST-04 no drift) is preserved.
- WR-01 fixed: `_hints` reads the raw, not-None-guarded imperial `feels_like`/`wind_speed`, so a degraded `current` payload produces no fabricated cold/wind line.
- `config.example.toml` now demonstrates a working `units = "metric"` override (Weekend location) with a comment explaining the metric-primary effect, instead of advertising an inert setting.

## Task Commits

Each task was committed atomically (TDD: test -> feat):

1. **Task 1 (RED): metric-primary display + WR-01 hint tests** - `73c30ee` (test)
2. **Task 1 (GREEN): primary-unit display axis + _hints guard** - `979182a` (feat)
3. **Task 2 (RED): metric-primary --send-now end-to-end test** - `fa0cbdd` (test)
4. **Task 2 (GREEN): thread location.units; example metric override** - `1ff0903` (feat)

## Files Created/Modified
- `weatherbot/weather/models.py` - Added `primary` field + `from_payloads` kwarg; unit-order-aware `_temp_str`/`wind_display`/temp/feels/high/low; `_hints` None-guards for feels_like/wind (WR-01).
- `weatherbot/cli.py` - `send_now` computes `primary = location.units or "imperial"` and threads it into `Forecast.from_payloads`; docstring updated.
- `config.example.toml` - Weekend location switched to `units = "metric"` with an explanatory comment.
- `tests/test_models.py` - New metric-primary display test, imperial-is-default test, null-feels_like + null-wind no-fabricated-hint tests.
- `tests/test_send_now.py` - New metric-primary `--send-now` end-to-end test asserting a °C-leading body and preserved dual fetch.

## Decisions Made
- `primary` defaults to `"imperial"` so unset `units` stays byte-identical to pre-plan output; existing imperial assertions pass unchanged.
- Override flips display order only — both One Call payloads are still fetched (DATA-03/FCST-04 preserved); `do_check`'s liveness probe stays literal `"imperial"`.
- WR-01 folded in (shared `_hints` path); other review warnings remain deferred.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. Both TDD cycles went RED -> GREEN cleanly with no refactor commit needed; full suite (96 tests) green and ruff clean.

## TDD Gate Compliance
Both behavior-adding tasks followed RED -> GREEN: failing `test(...)` commits (`73c30ee`, `fa0cbdd`) precede their `feat(...)` implementation commits (`979182a`, `1ff0903`). No REFACTOR commit was required.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Success Criterion #1's units clause is closed; LOC-02 / CONF-03 / CONF-01 satisfied. The suite would FAIL if the override regressed to inert (metric-primary assertions exist at both the model and send-now layers).
- Deferred review warnings remain open and documented in 02-05-PLAN.md: WR-02 (fetch-before-validate ordering), WR-03 (geocode network-error handling), WR-04 (`avatar_url = ""`), WR-05 (`--geocode` hardcoded timezone), WR-06/IN-01..03 (non-blocking cleanups).

---
*Phase: 02-real-config-locations-content-templates*
*Completed: 2026-06-10*
