---
phase: 14-uv-index-on-demand-daily-briefing
plan: 03
subsystem: weather
tags: [uv, briefing, placeholders, renderer-canonical, sunscreen-hint, threshold, empty-collapse, briefing-spine-isolation]

# Dependency graph
requires:
  - phase: 14-01
    provides: "UvConfig [uv] table (threshold default 6.0) + three deterministic hourly[] fixtures (uvcross/uvbelow/highuv)"
  - phase: 14-02
    provides: "Pure compute_uv(onecall_imp, onecall_met, threshold, *, tz, now) -> frozen UvSummary + uv_category WHO bands"
provides:
  - "Six UV briefing display strings on Forecast (uv_now/uv_max/uv_cross/uv_window/uv_peak/uv_category), formatted in code via _format_uv from compute_uv"
  - "Forecast.from_payloads keyword-only uv_threshold (default 6.0) calling compute_uv + threading the threshold into the sunscreen hint (D-01 single source of truth)"
  - "Six UV tokens in renderer.CANONICAL in lockstep with placeholders()"
  - "A UV line in all three editable briefing templates (sectioned/multiline/compact), empty-collapsing the same way as {hint}/{alert}"
  - "lookup_weather passing config.uv.threshold to from_payloads"
affects: [14-04-uv-command, 15-uv-monitor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Display-string formatting in CODE (_format_uv), never in the template (no-logic-in-templates rule); non-applicable UV field -> '' (empty-collapse precedent of {hint}/{alert})"
    - "CANONICAL <-> placeholders() lockstep for every new token, asserted by a renderer test (Pitfall 3)"
    - "Briefing-spine isolation: a missing/empty hourly[] degrades the UV line to 'stays below' and NEVER raises during render (T-14-07)"
    - "%-I:%M %p wall-clock idiom (_UV_TIME_FMT) reused from scheduler.context for crossing/window/peak clocks"

key-files:
  created: []
  modified:
    - weatherbot/weather/models.py
    - weatherbot/interactive/lookup.py
    - templates/renderer.py
    - templates/briefing-sectioned.txt
    - templates/briefing-multiline.txt
    - templates/briefing-compact.txt
    - tests/test_models.py
    - tests/test_renderer.py

decisions:
  - "Peak DISPLAY value uses the day's max (daily[0].uvi, == uv_max) while the peak CLOCK comes from compute_uv's hourly argmax (peak_time) — the 14-02 summary left this display choice to 14-03"
  - "uv_cross renders a literal 'stays below {threshold} today' line on stays_below (not '') so the briefing actively says the threshold won't be hit; uv_window collapses to '' in that case"
  - "Threshold is displayed as an integer when whole (round) else %g, so 'above 6' not 'above 6.0'"
  - "compute_uv called with the CONFIGURED location tz (ZoneInfo(loc.timezone), UTC fallback), never the API timezone field (Pitfall 3)"
  - "Pre-existing CANONICAL_PLACEHOLDERS equality assertions in test_models extended with the six UV tokens (in-scope: directly caused by extending placeholders())"

# Metrics
duration: ~18min
completed: 2026-06-19
---

# Phase 14 Plan 03: Briefing UV Line + Threshold-Driven Sunscreen Hint Summary

**The daily briefing now renders current UV, today's max UV with its WHO category, the linearly-interpolated threshold-crossing time + protect window (or a clear "stays below threshold today" line), via six new `{uv_*}` tokens formatted in code from `compute_uv` and emitted in lockstep with `renderer.CANONICAL`; the sunscreen hint and the briefing UV line both derive from the configured `config.uv.threshold` (D-01 single source of truth), and a missing/empty `hourly[]` degrades the UV line gracefully without ever crashing the render (briefing-spine isolation).**

## Performance
- **Duration:** ~18 min
- **Completed:** 2026-06-19
- **Tasks:** 2 (Task 1 TDD: RED -> GREEN; Task 2 auto)
- **Files modified:** 8

## Accomplishments
- `_hints` gained a `uv_threshold: float = 6.0` param and the hardcoded `uvi_max >= 6` became `uvi_max >= uv_threshold` (D-01 "unify three consumers"); the default preserves byte-identical existing behavior.
- `Forecast` gained six UV display-string fields; `from_payloads` gained a keyword-only `uv_threshold` (default 6.0), calls `compute_uv` with the configured location tz, and formats the six strings via a new `_format_uv` helper (category word, "climbs above 6 around 10:20 AM", "protect 10:20 AM–3:20 PM", "stays below 6 today", "peak 10 at 1:00 PM").
- `placeholders()` emits the six UV tokens alongside `{hint}`/`{alert}`; the `_UV_TIME_FMT = "%-I:%M %p"` idiom is reused from `scheduler.context`.
- `lookup_weather` threads `config.uv.threshold` into `from_payloads` (the live call site).
- The six UV tokens added to `renderer.CANONICAL` (daily-briefing scope only; `FORECAST_TOKENS`/`FORECAST_DAY_TOKENS_*` untouched).
- A UV line added to all three editable briefing templates — `briefing-sectioned.txt`/`briefing-multiline.txt` (emoji ok) and `briefing-compact.txt` (SMS-safe, no emoji) — empty-collapsing exactly like `{hint}`/`{alert}`.
- Briefing-spine isolation (T-14-07) verified: a payload with `hourly[]` removed renders the briefing without raising; `uv_now`/`uv_max` still populate (read verbatim from `current.uvi`/`daily[0].uvi`), crossing/window/peak collapse.

## Task Commits
1. **Task 1 (RED): failing UV briefing + threshold-driven hint tests** — `7ceee60` (test)
2. **Task 1 (GREEN): UV fields + threshold-driven hint + compute_uv in from_payloads** — `1c35ccb` (feat)
3. **Task 2: UV tokens in CANONICAL + UV line in three templates** — `8daaf71` (feat)

**Plan metadata:** see final docs commit.

## Files Created/Modified
- `weatherbot/weather/models.py` — `_hints` threshold param; six `Forecast.uv_*` fields; `_format_uv` + `_uv_hhmm` helpers; `compute_uv` call + threshold threading in `from_payloads`; UV tokens in `placeholders()`; `_UV_TIME_FMT`.
- `weatherbot/interactive/lookup.py` — `lookup_weather` passes `uv_threshold=config.uv.threshold`.
- `templates/renderer.py` — six UV tokens added to `CANONICAL` (lockstep).
- `templates/briefing-sectioned.txt`, `briefing-multiline.txt`, `briefing-compact.txt` — UV line.
- `tests/test_models.py` — threshold-driven-hint cases, UV-placeholder presence + lockstep, crossing/stays-below/missing-hourly rendering; `CANONICAL_PLACEHOLDERS` extended.
- `tests/test_renderer.py` — UV tokens in CANONICAL, lockstep CANONICAL↔placeholders, all three templates validate cleanly, no literal UV token survives render.

## Decisions Made
- Peak display value uses `uv_max` (the day's max, `daily[0].uvi`) with the clock from compute_uv's hourly argmax — the 14-02 summary explicitly deferred this display choice here.
- `uv_cross` emits an explicit "stays below {threshold} today" line on `stays_below` (informative), while `uv_window`/`uv_peak`'s non-applicable cases collapse to `""`.
- Threshold display: integer when whole, else `%g` ("above 6", not "6.0").

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Extended two pre-existing exact-equality placeholder assertions**
- **Found during:** Task 1
- **Issue:** `tests/test_models.py::test_from_payloads_metric_primary_displays` and `test_placeholders_is_flat_canonical_map` asserted `set(ph.keys()) == CANONICAL_PLACEHOLDERS` exactly; extending `placeholders()` with the six UV tokens broke the equality (extra keys on the left).
- **Fix:** Added the six UV tokens to the test's `CANONICAL_PLACEHOLDERS` set — the intended new canonical surface, directly caused by this plan's `placeholders()` extension (in scope).
- **Files modified:** `tests/test_models.py`
- **Commit:** `1c35ccb`

(Note: a docstring in `models.py` originally referenced the old literal as `` `uvi_max >= 6` ``, which tripped the plan's intentionally-broad `grep -cE "uvi_max >= 6"` acceptance check. Reworded to "literal-six" so the grep returns 0 — the actual code literal was removed.)

## Known Stubs
None. Every UV token is wired to real `compute_uv` output; the only empty/"stays below" paths are the intentional, tested empty-collapse / briefing-spine degradation (T-14-07).

## Threat Flags
None. No new network endpoint, auth path, or trust boundary introduced — only the user-edited-template→renderer boundary (T-14-06, unchanged guarded regex + CANONICAL allow-list) and the compute_uv→render boundary (T-14-07, briefing-spine isolation, tested). T-14-08 (hint/briefing threshold divergence) is closed: both derive from `config.uv.threshold`, asserted by a test.

## Issues Encountered
- The plan's acceptance `grep -cE "uvi_max >= 6"` matched a docstring mention of the old literal (false positive). Reworded the docstring; the code literal is gone (grep now 0).

## User Setup Required
None for this plan (code + templates only). Deploying to the live host (`yahir-mint`) requires a daemon restart — the new `models.py`/`lookup.py` modules load only on the NEXT process start (hot-reload covers config/templates, not modules); operators who customized their briefing templates can optionally add the new `{uv_*}` tokens, but the shipped starter templates already carry the UV line.

## Next Phase Readiness
- Plan 14-04 (`uv <loc>` command) reuses the same `compute_uv` helper + `config.uv.threshold` dispatch; the briefing line and the command stay consistent because both format from one `UvSummary`.
- Phase 15's monitor reuses `compute_uv` verbatim with the same threshold (interactive-layer-free guarantee from 14-02).

## Self-Check: PASSED
- `weatherbot/weather/models.py`, `weatherbot/interactive/lookup.py`, `templates/renderer.py`, all three `briefing-*.txt`, `tests/test_models.py`, `tests/test_renderer.py` present on disk.
- Commits `7ceee60` (test), `1c35ccb` (feat), `8daaf71` (feat) found in git history.
- Full suite: 497 passed; `ruff check` clean. CANONICAL ⊇ the six UV tokens (`True`); all three templates `validate_template` cleanly.

---
*Phase: 14-uv-index-on-demand-daily-briefing*
*Completed: 2026-06-19*
