---
phase: 14-uv-index-on-demand-daily-briefing
plan: 02
subsystem: weather
tags: [uv, compute-uv, interpolation, who-category, pure-helper, openweather, onecall, hourly]

# Dependency graph
requires:
  - phase: 14-01
    provides: "Three deterministic hourly[].uvi fixtures (uvcross/uvbelow/highuv) anchored to 2024-06-14 NY + the UvConfig threshold source"
provides:
  - "Pure compute_uv(onecall_imp, onecall_met, threshold, *, tz, now) -> frozen UvSummary"
  - "uv_category() WHO round-then-band table (0-2 Low / 3-5 Moderate / 6-7 High / 8-10 Very High / 11+ Extreme)"
  - "Linear up-cross/down-cross interpolation to minute precision + daytime window bounding"
  - "Interactive-layer-free module so the Phase-15 monitor can reuse it without a cycle"
affects: [14-03-briefing-uv-line, 14-04-uv-command, 15-uv-monitor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure payload->frozen-value-object helper (no I/O, no interactive import) as the cross-phase reuse seam"
    - "Linear interpolation of a threshold crossing between hourly[] points: t0 + (t1-t0)*(threshold-u0)/(u1-u0)"
    - "Daytime bounding from daily[0] sunrise/sunset with a 06:00-20:00 local fallback (Pitfall 5)"

key-files:
  created:
    - weatherbot/weather/uv.py
    - tests/test_uv.py
  modified: []

key-decisions:
  - "current=current.uvi and max=daily[0].uvi read verbatim; hourly[] used ONLY for crossing/window/peak (Pitfall 6)"
  - "onecall_met accepted for signature parity with Forecast.from_payloads but ignored — UV is unitless (A1)"
  - "WHO category is round-then-band via an ordered (ceiling,label) table; round(5.6)=6 -> High (A2)"
  - "peak_uvi exposes the hourly-argmax value (clock from hourly); display value can prefer daily[0].uvi in Plan 14-03"
  - "Empty/missing/malformed hourly[] degrades to stays_below=True, never raises (T-14-04 briefing-spine isolation)"
  - "window_end is the interpolated down-cross, sunset-bounded by the last daytime point when UV never drops back below threshold"

patterns-established:
  - "compute_uv pure-helper reuse seam: payload + threshold + tz in, frozen UvSummary out, zero interactive-layer dependency"
  - "Sub-hour linear interpolation of threshold crossings (the one genuinely new piece of math in Phase 14)"

requirements-completed: [UV-02]

# Metrics
duration: ~12min
completed: 2026-06-19
---

# Phase 14 Plan 02: Pure compute_uv Helper + UvSummary + uv_category Summary

**A pure, stateless, interactive-layer-free `compute_uv()` (+ frozen `UvSummary` + WHO `uv_category()`) in a new `weatherbot/weather/uv.py` that reads the already-fetched One Call payload and emits current / today's max / WHO category / hourly-argmax peak / linearly-interpolated threshold-crossing time / sunset-bounded protect window / stays-below — the shared reuse seam for the briefing (14-03), the `uv` command (14-04), and the Phase-15 monitor.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-19
- **Tasks:** 1 (TDD: RED -> GREEN, no refactor needed)
- **Files modified:** 2 (both created)

## Accomplishments
- `compute_uv(onecall_imp, onecall_met, threshold, *, tz, now=None) -> UvSummary` — reads `current.uvi` for "now", `daily[0].uvi` for the day's max (verbatim, Pitfall 6), and today's daytime `hourly[]` points for peak/crossing/window.
- Linear interpolation of the **up-cross** (`crossing_time`) and the first subsequent **down-cross** (`window_end`) to minute precision — `t0 + (t1-t0)*(threshold-u0)/(u1-u0)`; verified 10:20 / 15:20 (uvcross) and 17:17 (highuv down-cross).
- Already-above-at-first-daytime-point short-circuit: `crossing_time == window_start ==` the first daytime point with no interpolation (highuv 05:00 @ 6.2).
- `stays_below=True` with `None` crossing/window when the threshold is never reached (uvbelow), peak still reflecting the hourly argmax.
- `uv_category()` as an ordered `(ceiling, label)` table, round-then-band (A2): `round(5.6)=6 -> High`.
- Daytime bounding from `daily[0]` sunrise/sunset with a fixed `06:00-20:00` local fallback when sun data is absent (Pitfall 5); configured tz for "today"/daytime, never the API `timezone` field (Pitfall 3).
- Hardened against malformed payloads (WR-01 / T-14-04): missing `hourly` key, empty list, `None`-`dt`/`uvi` buckets, and a completely empty payload all return a valid `UvSummary` (`stays_below=True`) instead of raising — the briefing-spine isolation guarantee Plan 14-03 relies on.
- Module imports only stdlib + dataclasses; **zero** `weatherbot.interactive` imports (Phase-15 reuse rule), asserted by a test that inspects the module source.

## Task Commits

Task 1 followed TDD RED -> GREEN:

1. **Task 1 (RED): failing compute_uv math coverage** — `7f7067b` (test)
2. **Task 1 (GREEN): compute_uv + UvSummary + uv_category** — `e4d65e6` (feat)

**Plan metadata:** see final docs commit.

## Files Created/Modified
- `weatherbot/weather/uv.py` — `UvSummary` frozen dataclass, `compute_uv`, `uv_category`, and internal helpers `_epoch_local`, `_today_daytime_points`, `_first_up_cross`, `_first_down_cross_after`.
- `tests/test_uv.py` — 31 tests: category boundaries (incl. 5.6->High), up-cross/down-cross/peak interpolation (uvcross), already-above (highuv), stays-below (uvbelow), missing-sunrise fallback, empty/missing/malformed hourly no-raise, tz-from-arg correctness, onecall_met-ignored, frozen-summary, daytime-points shape, and the interactive-layer-free assertion.

## Decisions Made
- `peak_uvi` exposes the **hourly-argmax** value (so it pairs naturally with `peak_time`). The plan notes the displayed peak value may prefer `daily[0].uvi` while the clock derives from hourly — that display choice belongs to Plan 14-03; this helper returns both `max` (= `daily[0].uvi`) and `peak_uvi` (= hourly argmax) so the renderer can pick.
- `window_end` falls back to the **last daytime point** (sunset-bounded) when UV crosses up but never drops back below the threshold within today's daytime horizon (Pattern 2 edge case).
- Kept the down-cross interpolation symmetric with the up-cross (`(u0-threshold)/(u0-u1)`), guarded to only consider segments at/after the up-cross instant.

## Deviations from Plan

None - plan executed exactly as written.

(Note: the plan's `<read_first>` referenced `_epoch_local` at `weather_views.py` lines 59-61; it was copied verbatim. The `_is_daytime` 06:00-20:00 fallback was reproduced inline in `_today_daytime_points` rather than importing `_is_daytime` — importing it would pull `weather_views` (interactive layer) and violate the Phase-15 reuse rule, so the small fixed-window check was reimplemented locally. This matches the plan's explicit "copy the structure, NO import from weatherbot.interactive" instruction and is not a deviation.)

## Known Stubs

None. `compute_uv` is fully wired against real fixture data; no placeholder/empty-return paths exist except the intentional `stays_below` degradation on malformed payloads (documented, tested, and required by T-14-04).

## Issues Encountered
- `round(2.5) == 2` (Python banker's rounding) — adjusted the one category-boundary test row accordingly (2.5 -> "Low"). The headline A2 case `round(5.6) == 6 -> "High"` is unaffected and explicitly asserted.

## User Setup Required
None for this plan (pure code). The downstream Phase-14 code that ships uv.py to the live host will require a daemon restart when deployed (config alone won't load a new module — per 14-RESEARCH Runtime State).

## Next Phase Readiness
- Plan 14-03 (briefing UV line) can call `compute_uv` from `Forecast.from_payloads` (it has `raw_onecall_imp` + the location tz + `config.uv.threshold`) and format the `{uv_now}/{uv_max}/{uv_cross}/{uv_window}/{uv_peak}/{uv_category}` tokens from the returned `UvSummary`.
- Plan 14-04 (`uv <loc>` command) can call the same helper and build its compact daytime hourly line from `UvSummary.hourly_points`.
- Phase 15's monitor reuses `compute_uv` verbatim with the same threshold — the interactive-layer-free guarantee is enforced by a test.

## Self-Check: PASSED

- `weatherbot/weather/uv.py` present on disk; `tests/test_uv.py` present on disk.
- Commits `7f7067b` (test) and `e4d65e6` (feat) found in git history.
- `def compute_uv` / `class UvSummary` / `def uv_category` each appear exactly once; zero `from weatherbot.interactive` imports.
- `tests/test_uv.py` 31 passed; full suite 484 passed; `ruff check` clean.

---
*Phase: 14-uv-index-on-demand-daily-briefing*
*Completed: 2026-06-19*
