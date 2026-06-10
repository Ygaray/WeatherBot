---
phase: 02-real-config-locations-content-templates
plan: 01
subsystem: weather/test-foundation
tags: [fixtures, one-call-3.0, geocoding, test-scaffold, migration, d-01]
requires:
  - weatherbot/weather/models.py (existing Forecast model)
  - tests/conftest.py:load_fixture (existing fixture loader)
provides:
  - 8 One Call 3.0 recorded fixtures (clear/rainy/alert/multialert/highuv/extreme)
  - 2 geocoding fixtures (single match + ambiguous multi-match)
  - tests/test_cli.py (6 xfail scaffolds named for research -k selectors)
  - models.py with the dead aggregate dependency severed (W1 boundary collectable)
  - migrated tests/test_review_hardening.py
affects:
  - Plan 02-02 (One Call from_payloads rewrite consumes these fixtures, fills placeholders)
  - Plan 02-03 (--geocode, timezone-required Location)
  - Plan 02-04 (--check subcommand)
tech-stack:
  added: []
  patterns:
    - "strict-xfail-then-remove test discipline (mirrors Phase 1 test_send_now.py)"
    - "recorded OpenWeather response fixtures loaded via conftest load_fixture"
key-files:
  created:
    - tests/fixtures/onecall_imperial_clear.json
    - tests/fixtures/onecall_metric_clear.json
    - tests/fixtures/onecall_imperial_rainy.json
    - tests/fixtures/onecall_metric_rainy.json
    - tests/fixtures/onecall_imperial_alert.json
    - tests/fixtures/onecall_imperial_multialert.json
    - tests/fixtures/onecall_imperial_highuv.json
    - tests/fixtures/onecall_imperial_extreme.json
    - tests/fixtures/geocode_austin.json
    - tests/fixtures/geocode_ambiguous.json
    - tests/test_cli.py
  modified:
    - weatherbot/weather/models.py
    - tests/test_review_hardening.py
  deleted:
    - weatherbot/weather/aggregate.py
    - tests/test_aggregate.py
    - tests/fixtures/forecast_imperial_offset_plus.json
    - tests/fixtures/forecast_imperial_offset_minus.json
decisions:
  - "D-01 enacted: the 2.5 bucket-aggregation module is retired; its high/low/rain logic is replaced by One Call daily[0] in Plan 02-02."
  - "models.py from_payloads emits placeholder high/low=None and rain_chance=0 this wave — deliberate, to keep the W1 boundary collectable until 02-02 supplies real values."
  - "The 2 from_payloads null-tolerance tests are xfail(strict=False) (not deleted) so 02-02/02-03 rewrite them for the One Call signature + timezone Location."
metrics:
  duration_min: 4
  completed: "2026-06-10"
  tasks: 2
  files_changed: 16
---

# Phase 2 Plan 01: One Call 3.0 Test Foundation Summary

Lays the offline test surface for the One Call 3.0 migration: 10 recorded fixtures (8 One Call + 2 geocoding) crossing the D-06 hint thresholds, a named `tests/test_cli.py` scaffold, retirement of the 2.5 bucket-aggregation module (D-01), and a migrated Phase 1 regression suite — leaving the W1 boundary collectable by severing `models.py`'s dependency on the deleted module in the same wave.

## What Was Built

### Task 1 — One Call 3.0 + Geocoding fixtures
Authored 10 recorded fixtures modeled on the Phase 1 New-York (`timezone_offset: -14400`) convention, shaped to the One Call 3.0 schema (`current{...}` + `daily[{temp:{max,min}, pop, uvi, weather}]}`):
- `onecall_imperial_clear` / `onecall_metric_clear` — no `alerts` key, `pop` ≤ 0.40, `uvi` < 6, `feels_like` in [40,90], `wind_speed` ≤ 25 (zero hints).
- `onecall_imperial_rainy` / `onecall_metric_rainy` — `daily[0].pop` = 0.85 (> 0.40), `weather.main` = "Rain" (umbrella hint).
- `onecall_imperial_alert` — single `alerts[]` entry (Heat Advisory).
- `onecall_imperial_multialert` — two distinct `event` names (Severe Thunderstorm Warning + Flash Flood Watch) for the concise-summary path (D-08).
- `onecall_imperial_highuv` — `daily[0].uvi` = 9.6 (≥ 6, sunscreen hint).
- `onecall_imperial_extreme` — `current.feels_like` = 14 (cold, outside [40,90]) AND `wind_speed` = 32 (> 25): both cold and wind hints fire.
- `geocode_austin` — single `/geo/1.0/direct` match with numeric lat/lon; `geocode_ambiguous` — 3 Springfield matches in different states.

### Task 2 — Scaffold, retire, sever, migrate
- **Scaffold:** `tests/test_cli.py` with 6 real pytest functions named for the research `-k` selectors (`test_geocode_prints_coords`, `test_send_now_never_geocodes`, `test_check_validates_config`, `test_check_reachability_one_call`, `test_send_now_bad_template_aborts`, `test_check_unique_names`), each `@pytest.mark.xfail(strict=False)` with a `_FakeClient`/`_FakeChannel` mirroring `test_send_now.py`.
- **Retire (D-01):** deleted `weatherbot/weather/aggregate.py`, `tests/test_aggregate.py`, and the obsolete 2.5 bucket-offset fixtures `forecast_imperial_offset_plus.json` / `forecast_imperial_offset_minus.json`.
- **Sever:** removed the `from weatherbot.weather.aggregate import today_aggregate` import and both `today_aggregate(...)` call sites in `from_payloads`; short-circuited `high_imp/high_met/low_imp/low_met=None` and `rain_chance=0`. Updated the now-stale module docstring/comments to reflect the placeholder state (also clearing the literal `grep -c aggregate` to 0).
- **Migrate:** `tests/test_review_hardening.py` — dropped the 3 CR-02 bucket-aggregation null-tolerance tests, kept the 5 CR-01 renderer-hardening tests unchanged, and xfail-marked (`strict=False`) the 2 `from_payloads` null-tolerance tests for rewrite in 02-02/02-03.

## Verification Results

- All 10 fixtures parse as valid JSON; threshold checks (no-alerts clear, alerts≥1, rainy pop>0.4, highuv uvi≥6, extreme wind>25 & feels_like outside [40,90], geocode numeric lat/lon, multialert ≥2 distinct events) all pass.
- `grep -rn "import aggregate\|weather.aggregate" weatherbot/ tests/` returns nothing; `grep -c aggregate` is 0 in both `models.py` and `test_review_hardening.py`.
- `uv run python -c "import weatherbot.weather.models"` exits 0.
- `uv run pytest tests/test_cli.py tests/test_review_hardening.py -q` collects with no ImportError/ModuleNotFoundError: **5 passed, 6 xfailed, 2 xpassed** (no failures, no errors). The scoped `-k "not (tolerates or skips)"` gate exits 0.
- `uv run ruff check` on all changed files: passed.

Note (expected, per plan): the FULL `uv run pytest` is intentionally NOT green at this wave — `from_payloads` now emits placeholder high/low/rain, so model/store/renderer assertions expecting real aggregates still fail until Plan 02-02 supplies the One Call `daily[0]` values. The full-suite-green gate is owned by Plan 02-02.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Correctness] Cleared stale `aggregate` references in docstrings/comments**
- **Found during:** Task 2 verification
- **Issue:** After severing the import/call-sites, the acceptance criterion `grep -c "aggregate" weatherbot/weather/models.py == 0` still matched 4 docstring/comment occurrences (and 1 in `test_review_hardening.py`) describing the now-retired bucket aggregation. Left as-is they were both inaccurate documentation and a literal acceptance-criterion miss.
- **Fix:** Rewrote the `Forecast` module docstring, the `from_payloads` docstring, and the inline placeholder comment to describe the One Call placeholder reality; reworded the migration comment in `test_review_hardening.py`. No behavior change.
- **Files modified:** weatherbot/weather/models.py, tests/test_review_hardening.py
- **Commit:** 44ecb65

## Known Stubs

| Stub | File | Reason |
|------|------|--------|
| `high_imp/high_met/low_imp/low_met=None`, `rain_chance=0` in `from_payloads` | weatherbot/weather/models.py | Intentional placeholder. The 2.5 bucket aggregation was retired (D-01); the real One Call `daily[0]` high/low/pop values are supplied by Plan 02-02's `from_payloads` rewrite. Documented in the plan's `<artifacts_this_phase_produces>` and `<verification>`. |
| 6 `xfail` scaffolds in tests/test_cli.py | tests/test_cli.py | Intentional. The `--check`/`--geocode` subcommands ship in Plans 02-03/02-04; scaffolds are named now so later slices fill them in and remove the marker. |

These stubs are by design and explicitly owned by downstream plans (02-02/02-03/02-04); they do not block this plan's goal (make the offline test surface exist before any production code reads One Call).

## Self-Check: PASSED
