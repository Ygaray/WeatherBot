---
phase: 03-always-on-scheduler
plan: 02
subsystem: api
tags: [scheduler, templating, timezone, zoneinfo, dataclass, jinja-alternative]

# Dependency graph
requires:
  - phase: 03-always-on-scheduler (plan 01)
    provides: scheduler package (days.py parser, Schedule model, sent_log store)
  - phase: 02 (render boundary)
    provides: guarded renderer (CANONICAL/validate_template/render), Forecast.placeholders(), send_now composition root, Channel/DeliveryResult seam
provides:
  - "ScheduleContext dataclass + schedule_placeholders() merge helper (the render-boundary timing seam)"
  - "CANONICAL extended with {sent_at}/{checked_at}/{schedule_note} (validated, not weather-only)"
  - "send_now threads optional schedule_ctx; merges the 3 timing keys at the single render() call"
  - "Location-local timing footer on all three starter templates (compact stays emoji-free)"
affects: [scheduler-daemon, plan-03, catch-up, late-send]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Merge-at-call-site placeholder seam: Forecast.placeholders() stays weather-only; scheduler timing keys layered in at the render() call (Open Question 2)"
    - "ScheduleContext value object mirrors channels.base.DeliveryResult (frozen-ish dataclass travelling through the pipeline)"
    - "Empty-collapse rule reused for {schedule_note} (like {hint}/{alert}): empty unless ctx.late and scheduled_dt is not None"

key-files:
  created:
    - weatherbot/scheduler/context.py
  modified:
    - templates/renderer.py
    - weatherbot/cli.py
    - templates/briefing-sectioned.txt
    - templates/briefing-multiline.txt
    - templates/briefing-compact.txt
    - tests/test_renderer.py
    - tests/test_send_now.py
    - tests/test_scheduler.py

key-decisions:
  - "checked_dt is computed locally at the render call as a freshness proxy (within seconds of the single DATA-03 fetch) — Forecast does not expose a fetch instant; a fetched_at field is out of scope (D-12)"
  - "%-I:%M %p (GNU strftime extension) for '7:30 AM' — Linux is the deployment target (A2 / D-12 discretion)"
  - "When schedule_ctx is None, the render-time tz is derived from location.timezone so manual --send-now still renders location-local times (D-14)"
  - "em-dash U+2014 and middot U+00B7 are outside the _EMOJI range, so the footer is safe in the emoji-free compact template"

patterns-established:
  - "Merge-at-call-site seam: scheduler-derived render values are merged into the placeholder map at send_now's single render() call, keeping the weather model decoupled from the scheduler"
  - "ScheduleContext is the per-fire timing value object Plan 03's daemon will populate"

requirements-completed: [SCHD-04]

# Metrics
duration: 14min
completed: 2026-06-10
---

# Phase 3 Plan 02: Render-Boundary Timing Seam Summary

**ScheduleContext + schedule_placeholders() merge location-local {sent_at}/{checked_at}/{schedule_note} into every briefing at send_now's single render() call; CANONICAL validates them; manual --send-now renders timing with an empty, collapsible note.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-06-10T (plan execution)
- **Completed:** 2026-06-10
- **Tasks:** 3
- **Files modified:** 8 (1 created, 7 modified)

## Accomplishments
- New `weatherbot/scheduler/context.py`: `@dataclass ScheduleContext` (`scheduled_dt`/`tz`/`late`) + `schedule_placeholders(ctx, sent_dt, checked_dt)` returning location-local `sent_at`/`checked_at` and an empty-by-default `schedule_note`.
- `CANONICAL` extended with the three timing keys; `Forecast.placeholders()` deliberately left weather-only (merge-at-call-site seam).
- `send_now` gains `schedule_ctx: ScheduleContext | None = None` and merges `{**forecast.placeholders(), **schedule_placeholders(...)}` at the one `render()` call; manual sends derive the tz from `location.timezone`.
- All three starter templates carry a `— sent {sent_at} · weather checked {checked_at}` footer with `{schedule_note}` on its own collapsible line; compact stays emoji-free.

## Task Commits

Each task was committed atomically (TDD: tests + impl per task):

1. **Task 1: ScheduleContext + schedule_placeholders + CANONICAL extension (D-12/D-15)** - `bd12d7d` (feat)
2. **Task 2: Thread schedule_ctx through send_now + canonical-keys gotcha test (D-13/D-15)** - `a0713bf` (feat)
3. **Task 3: Timing footer on all three starter templates (D-15)** - `3e19639` (feat)

**Plan metadata:** see final docs commit below.

## Files Created/Modified
- `weatherbot/scheduler/context.py` - ScheduleContext dataclass + schedule_placeholders() merge helper (location-local formatting, empty/late note rule)
- `templates/renderer.py` - CANONICAL gains sent_at/checked_at/schedule_note (validate/render logic unchanged, read CANONICAL by reference)
- `weatherbot/cli.py` - send_now schedule_ctx seam; merge at the single render() call; tz/sent_dt/checked_dt derived locally
- `templates/briefing-sectioned.txt`, `briefing-multiline.txt`, `briefing-compact.txt` - timing footer + collapsible note line
- `tests/test_scheduler.py` - ScheduleContext/schedule_placeholders unit tests (manual empty note, None scheduled_dt no-crash, late populated, on-time empty, tz-local render)
- `tests/test_renderer.py` - test_new_placeholders_validate, updated canonical-keys gotcha test to the call-site seam, test_templates_carry_timing_footer
- `tests/test_send_now.py` - test_manual_send_schedule_placeholders (empty note) + test_send_now_late_context_populates_note (populated note)

## Decisions Made
- **Freshness proxy for `checked_at`:** `checked_dt = datetime.now(tz)` at the render call. `Forecast` does not retain its fetch instant (only `local_date`), and DATA-03 guarantees a single fetch-at-send, so this is within seconds of the real fetch. Adding a `fetched_at` field to `Forecast` was explicitly out of scope (D-12).
- **`%-I:%M %p` time format:** GNU strftime extension giving "7:30 AM" (no leading zero). Linux is the deployment target per CLAUDE.md (Pi/systemd), so the non-portable directive is acceptable (A2 / D-12 discretion).
- **Manual-send tz:** when `schedule_ctx is None`, the formatting tz is `ZoneInfo(location.timezone)` so manual sends still render location-local times (D-14).
- **Footer punctuation safety:** em-dash (U+2014) and middot (U+00B7) are both below U+2600, outside the `_EMOJI` range `[\U0001F300-\U0001FAFF☀-➿]`, so the compact template's footer keeps it emoji-free.

## Deviations from Plan

None - plan executed exactly as written. All three tasks implemented as specified; `Forecast.placeholders()` confirmed weather-only (acceptance grep returns nothing).

## Issues Encountered
- The canonical-keys gotcha test (`test_canonical_matches_forecast_placeholder_keys`) went red after Task 1 extended CANONICAL — this was anticipated; Task 2 updated the assertion to `CANONICAL == set(placeholders().keys()) | {sent_at,checked_at,schedule_note}` (the documented call-site seam), and it is green.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `ScheduleContext` is the per-fire timing value object Plan 03's daemon will populate (real scheduled/late values per cron fire).
- The render boundary now renders location-local timing on EVERY message; a recovered late send can render its intended-vs-actual time without any further render changes (SCHD-04 display half complete).
- Full suite green: 118 passed (was 109; +9 new tests).

## Threat Surface Scan
No new security-relevant surface beyond the plan's threat model. The three new keys are plain strings added to the existing whitelist substitution (no `str.format`/`eval`); `{schedule_note}` defaults empty and cannot leak a note or crash on a None `scheduled_dt` (test_manual_send_schedule_placeholders proves this, T-03-06). No credential crosses the render boundary (T-03-05).

## Self-Check: PASSED
- Files: all 4 key files present on disk.
- Commits: bd12d7d, a0713bf, 3e19639 all in git log.
- Acceptance: `grep -c` for the 3 keys in `weatherbot/weather/models.py` returns 0 (placeholders() stays weather-only).
- Full suite: 118 passed.
