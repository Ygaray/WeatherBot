---
phase: 32-timezone-date-boundary-correctness
plan: 04
subsystem: weather
tags: [timezone, date-boundary, D-05, D-06, D-07, F35, F33, F31, F32, tdd-green]
status: complete
requires:
  - "32-01 RED tests (daily0-not-today / naive-now_utc / daily0 guard / hourly sort)"
  - "32-02 weatherbot.weather.dates (select_today_daily, local_date_for)"
provides:
  - "models.from_payloads today-entry selection by own local date (D-05/F35)"
  - "models.from_payloads local_date via shared local_date_for (D-06/F33)"
  - "uv._today_daytime_points window bound anchored to today entry + time-sorted (D-05/F31, D-07/F32)"
  - "uv.compute_uv display-max anchored to today entry (D-05)"
affects:
  - "32-05 (uvmonitor) — last _local_date_iso holdout; import_hygiene turns fully GREEN once it lands"
tech-stack:
  added: []
  patterns:
    - "Select daily[] by each entry's OWN local date via shared select_today_daily, never positional daily[0]"
    - "Route local_date through shared local_date_for so naive now_utc is UTC-interpreted (D-06/F33)"
    - "Sort today's daytime hourly points by timestamp before zip-based interpolation (D-07/F32)"
    - "Degrade to existing empty/None/stays_below/fixed-window fallback when no today entry matches (never fabricate)"
key-files:
  created: []
  modified:
    - "weatherbot/weather/models.py — deleted local _local_date_iso; imported select_today_daily + local_date_for; from_payloads resolves the configured tz once, selects today's daily entry (day_i/day_m) by its own local date, and writes local_date via local_date_for"
    - "weatherbot/weather/uv.py — imported select_today_daily; _today_daytime_points sources its [sunrise,sunset] window bound from the today entry (F31 defect site) and sorts points before return (F32); compute_uv display-max daily0 today-anchored"
    - "tests/test_golden_embeds.py — re-date clear/highuv fixtures onto FROZEN day + freeze from_payloads/uv-dispatch build clock for the weather/uv command goldens (D-05 exposed positional-daily0 reliance)"
    - "tests/test_oracle_selfproof.py — same re-date + freeze for the field-reorder oracle's real render"
decisions:
  - "D-05: models + uv select today's daily entry by its own local date; degrade (None/{}) when none matches — never ship a non-today entry as today's"
  - "D-06: local_date routes through local_date_for so a naive now_utc is UTC-interpreted, not host-shifted"
  - "D-07: today's daytime points sorted by timestamp before interpolation so a wrong-pair straddle can't emit a bogus crossing/window"
metrics:
  duration_minutes: 9
  completed: 2026-07-11
  tasks_completed: 2
  files_created: 0
  files_modified: 4
---

# Phase 32 Plan 04: Anchor briefing + UV today-entry to configured tz Summary

One-liner: `models.from_payloads` and `uv.compute_uv`/`_today_daytime_points` stop trusting positional `daily[0]` and instead select today's `daily[]` entry by its OWN configured-tz local date (via the shared `select_today_daily`), route the briefing `local_date` through `local_date_for` (naive→UTC), and time-sort today's hourly points before interpolation — closing F35 (yesterday's numbers shipped as today's), F31 (false `stays_below` off a stale sunset), F33 (host-shifted local_date), and F32 (wrong-pair interpolation straddle).

## What was built

- **`models.py` (Task 1, D-05/D-06/F35/F33):** Deleted the local `_local_date_iso`; imported `select_today_daily` + `local_date_for` from `weather.dates`. `from_payloads` now resolves the configured location tz once (reused by the selector, the `local_date` write, and the UV line), selects `day_i`/`day_m` via `select_today_daily(..., loc_tz, local_date)` (degrading to `{}` → the existing empty/None high/low/rain path when no today entry matches), and writes `local_date = local_date_for(loc, now_utc)` so a naive `now_utc` is UTC-interpreted.
- **`uv.py` (Task 2, D-05/D-07/F31/F32):** Imported `select_today_daily`. **The F31 defect site** — `_today_daytime_points`'s positional `daily0` at :109 that supplied the `[sunrise, sunset]` window bound — is now `select_today_daily(raw.get("daily"), tz, today.isoformat()) or {}`, so a yesterday-dated `daily[0]` no longer contributes a ~24h-stale sunset that filters out today's afternoon buckets; when no entry matches, `has_sun=False` degrades to the EXISTING fixed 06:00–20:00 fallback (never fabricated). Added `points.sort(key=lambda p: p[0])` immediately before `return tuple(points)` (F32/D-07). `compute_uv`'s display-max `daily0` at :219 is likewise today-anchored, degrading to `0.0` when none matches. The per-bucket `local.date() != today` filter was left untouched (already correct).

## Verification (plan-level acceptance)

- `grep`: `def _local_date_iso` in models.py → **0**; `select_today_daily` used in models.py (3 hits) AND both uv.py sites (import + 2 calls); `points.sort(key=lambda p: p[0])` present before `return tuple(points)`; no bare `(raw.get("daily") or [{}])[0]` remains in uv.py; `local_date_for` used for the local_date write.
- The four owned tests are GREEN: `test_daily0_not_today_degrades`, `test_naive_now_utc_treated_as_utc`, `test_compute_uv_daily0_today_guard` (asserts `stays_below is False` + `crossing_time == 10:20` over a real today crossing — a display-only swap could not turn it green), `test_hourly_points_sorted_before_interpolation`.
- `uv run python -c "from weatherbot.weather import models, uv, dates"` → imports clean, no cycle.
- `ruff check` clean on all four modified files.
- `tests/test_models.py` (43) + `tests/test_uv.py` (38) fully green.

## Suite state (regression evidence)

| | pre-32-04 (9a48387) | after 32-04 |
|---|---|---|
| passed | 837 | **840** (+3: the four owned tests green — 2 in models, 2 in uv — net after prior baseline count) |
| failed | 6 | **3** (all owned by plan 32-05) |

Remaining 3 failures are all owned by plan 32-05 (uvmonitor), untouched by this plan:
- `test_import_hygiene::test_dates_single_helper_no_local_copies` → now reports ONLY `scheduler/uvmonitor.py` still carrying `_local_date_iso` (models.py cleared here). Turns fully GREEN when 32-05 migrates uvmonitor.
- `test_uv_monitor.py::test_allclear_not_latched_on_momentary_dip`, `::test_lifecycle_full_day_no_never_fire_gap` → 32-05's RED tests.

The "2 snapshots failed" line in the report summary is the pre-existing syrupy report-summary quirk (all snapshot *tests* pass; exit is driven only by the 3 real 32-05 failures) — consistent with the 32-02 SUMMARY note.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Re-dated golden/oracle fixtures exposed by the correct F35 selector**
- **Found during:** Full-suite regression check after Task 2
- **Issue:** `tests/test_golden_embeds.py` (`weather`/`uv` command goldens) and `tests/test_oracle_selfproof.py` (field-reorder oracle) build a real `Forecast` via `lookup_weather`, which calls `from_payloads` with real `datetime.now()`. Their recorded `clear`/`highuv` fixtures are dated 2024-06-14, so once `from_payloads`/`compute_uv` select today's entry by its OWN local date (the F35 fix), no entry matched "today" and High/Low/Rain/UV-max correctly degraded (`76/58`→`68/68`, `10%`→`0%`, `10 (Very High)`→`0 (Low)`). These goldens were silently relying on the positional-`daily[0]` bug this plan removes. Root cause: `lookup_weather` doesn't inject a frozen build clock, and the fixtures aren't date-relative — so the selector had no matching entry.
- **Fix:** Added an opt-in `_redate_daily_to_frozen` helper that shifts the fixture `daily[]` (dt/sunrise/sunset) onto FROZEN's (2026-06-20) day by whole 24h (DST-preserving), and froze the `from_payloads`/uv-dispatch build clock to FROZEN in the `weather`/`uv` command goldens and the oracle's real render — so the today-selector matches the fixture entry and the goldens keep asserting the recorded DISPLAY values (they exercise display/ordering, not the F35 date guard). The forecast-variant goldens keep the raw fixture calendar (`redate=False`) since they drive multiday logic off the recorded dates via their handler's `now=FROZEN` seam. No golden value was re-blessed; the recorded snapshots are unchanged.
- **Files modified:** `tests/test_golden_embeds.py`, `tests/test_oracle_selfproof.py`
- **Commit:** 8e426a1

Scope note: these two test files were directly and solely broken by this plan's F35 change (they passed at 9a48387), so fixing them is in-scope per the scope-boundary rule.

## Known Stubs

None. Every changed path is fully wired; degrade paths reuse existing empty/None/stays_below/fixed-window fallbacks.

## Threat surface

No new security-relevant surface beyond the plan's `<threat_model>`. Implements T-32-08 (F35 positional-trust → own-local-date select), T-32-09 (F31 stale-sunset window bound → today-entry anchor), T-32-10 (F32 out-of-order straddle → time-sort), T-32-11 (F33 naive now_utc → UTC-interpret via local_date_for). No package installs (stdlib + already-present shared helper only).

## Commits

- 89288ab: feat(32-04): anchor from_payloads today-entry to configured tz (D-05/D-06/F35/F33)
- 80fdbce: feat(32-04): anchor UV today-window + display-max to configured tz, sort points (D-05/D-07/F31/F32)
- 8e426a1: test(32-04): re-date golden/oracle fixtures onto FROZEN day for D-05 today-selector

## Self-Check: PASSED

- FOUND: weatherbot/weather/models.py (no _local_date_iso; select_today_daily + local_date_for wired)
- FOUND: weatherbot/weather/uv.py (select_today_daily at both sites; points.sort present)
- FOUND: .planning/phases/32-timezone-date-boundary-correctness/32-04-SUMMARY.md
- FOUND commit: 89288ab
- FOUND commit: 80fdbce
- FOUND commit: 8e426a1
