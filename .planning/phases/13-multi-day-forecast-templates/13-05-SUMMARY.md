---
phase: 13-multi-day-forecast-templates
plan: 05
subsystem: scheduler
tags: [forecast, scheduler, apscheduler, reconcile-by-id, read-only, failure-isolation, file-watch, config-validation]
requirements-completed: [FCAST-05, FCAST-06, FCAST-07]
dependency-graph:
  requires:
    - "ForecastSchedule + Location.forecast (Plan 13-03 — parsed_time()/day_of_week accessors)"
    - "weekday_forecast/weekend_forecast + lookup_forecast on-demand render path (Plan 13-04)"
    - "ForecastFlags (Plan 13-03)"
    - "_register_jobs / _desired_job_ids / _reconcile_jobs reconcile-by-stable-id spine (Phase 3/9)"
    - "validate_config_and_templates + _derive_watch_dirs / _make_watch_filter (Phase 9/10)"
    - "templates.renderer FORECAST_TOKENS + FORECAST_DAY_TOKENS_* + render_forecast (Plan 13-02)"
  provides:
    - "_forecast_job_id(location, fc) namespaced stable id (weatherbot/scheduler/daemon.py)"
    - "fire_forecast_slot read-only failure-isolated scheduled forecast callback (daemon.py)"
    - "forecast enumeration loops in _register_jobs + _desired_job_ids (daemon.py)"
    - "FORECAST_TEMPLATE_NAMES + forecast_day_allowed (templates/renderer.py) — one source of truth"
    - "_referenced_template_names(config) shared watched-set helper (daemon.py)"
    - "forecast templates added to validate_config_and_templates referenced set (config/loader.py)"
  affects:
    - "Future phases scheduling forecasts: per-location forecast slots are now live cron jobs"
tech-stack:
  added: []
  patterns:
    - "Single shared id helper called by BOTH enumeration sites (no register/desired drift, Pitfall 4)"
    - "Namespaced job id (|fc| segment) to guarantee no collision with a same-time/days briefing id"
    - "Read-only scheduled callback: fire_slot isolation envelope MINUS the claim/store writes (A1)"
    - "Reuse the on-demand render path (lookup_forecast + handler) so scheduled==on-demand output"
    - "Hoist the (kind,variant)->filenames map to the renderer as the ONE source the 3 surfaces share"
key-files:
  created: []
  modified:
    - weatherbot/scheduler/daemon.py
    - weatherbot/config/loader.py
    - templates/renderer.py
    - weatherbot/interactive/commands/forecast.py
    - tests/test_scheduler.py
decisions:
  - "fire_forecast_slot posts via channel.send (plain text) NOT send_briefing (forecasts are not briefing embeds); the _PlainSendChannel test fake asserts send_briefing is never called"
  - "FORECAST_TEMPLATE_NAMES + forecast_day_allowed hoisted from forecast.py to templates.renderer so daemon.py (watch set), loader.py (validate set), and forecast.py (render) share ONE map with zero cyclic-import cost (all three already import templates.renderer); forecast.py's _TEMPLATES now aliases it"
  - "_referenced_template_names(config) is the single helper both _derive_watch_dirs and _make_watch_filter build their set from, so the watched set and validated set never drift (Pitfall 5)"
  - "fire_forecast_slot reuses lookup_forecast (which delegates to lookup_weather's dual fetch) — no extra OpenWeather call, no client.py change (FCAST-07); the daily-briefing template render lookup_weather performs is harmless overhead the forecast handler ignores"
metrics:
  duration: ~18 min
  tasks: 2
  files: 5
  tests-added: 11
  completed: 2026-06-19
---

# Phase 13 Plan 05: Scheduled Forecast Slots Summary

Wired per-location forecast slots into the existing scheduler spine (FCAST-06): a single
namespaced `_forecast_job_id` feeds BOTH the register and desired-set enumeration loops (so
they can never drift), enabled `location.forecast` slots become APScheduler cron jobs at the
location's own timezone, and a `fire_forecast_slot` callback renders + posts through the SAME
on-demand render path as `!weekday-forecast`/`!weekend-forecast` — inside `fire_slot`'s
failure-isolation envelope but writing NOTHING to the SQLite store (FCAST-05/A1). Forecast
templates now validate at config load/reload (keep-old) and are watched for edits, exactly
like the briefing template.

## What Was Built

### Task 1 — `_forecast_job_id` helper + forecast loops in register/desired
- Module-level `_forecast_job_id(location, fc) -> str` returning
  `f"{location.name}|fc|{fc.kind}|{fc.variant}|{fc.time}|{fc.days}"`. The `|fc|` segment is the
  anti-collision namespace (Pitfall 4): a briefing's id is `name|time|days`, so a briefing and
  a forecast at the SAME time/days can never produce the same id. `kind`/`variant` are in the id
  so a variant edit yields a DIFFERENT id (diffs as one ADD + one REMOVE).
- A SECOND enumeration loop in `_register_jobs` (after the briefing-slot loop): `for fc in
  location.forecast` → skip disabled, `CronTrigger(hour, minute, day_of_week=fc.day_of_week,
  timezone=location.timezone)`, `add_job(fire_forecast_slot, ..., id=_forecast_job_id(...),
  misfire_grace_time=None, coalesce=True)`. The job carries the `holder` (not a baked config) so
  a `replace()` swaps what it renders.
- `_desired_job_ids` now unions the forecast ids built via the SAME `_forecast_job_id` + the same
  enabled filter, so a no-op reload reconciles churn-free and `_reconcile_jobs` needed NO body
  change (it reconciles any non-`__heartbeat__` id).

### Task 2 — `fire_forecast_slot` (read-only, isolated) + forecast templates in validate/watch
- `fire_forecast_slot(location, fc, *, holder=None, config=None, db_path=None, settings=None,
  client=None, channel=None, stop_event=None) -> None`: resolves the config snapshot ONCE
  (config override wins, else `holder.current()`), routes through `lookup_forecast` (reuses the
  dual One Call fetch — FCAST-07) + the `weekday_forecast`/`weekend_forecast` handler with a
  fixed-variant `ForecastFlags(variant=fc.variant)`, and POSTs `reply.text` via `channel.send`.
  The whole body is wrapped in a try/except that logs (outcome-only — location/kind/variant/time,
  T-13-19) and returns `None`, so one bad forecast can NEVER crash the scheduler thread or gate a
  briefing (T-13-15). Calls NO `claim_slot`/`release_claim`/store function and imports nothing
  from the store (A1/FCAST-05).
- `validate_config_and_templates` (loader.py) now validates every forecast template referenced by
  a `location.forecast` slot: the whole-message template against `FORECAST_TOKENS`, the sibling
  `.line.txt` against the variant's day-token scope (`forecast_day_allowed`), deduplicated by
  `(kind, variant)`. A typo'd forecast template is rejected at load AND reload (keep-old, Pitfall 5).
- `_derive_watch_dirs` and `_make_watch_filter` now build their watched set from a new shared
  `_referenced_template_names(config)` helper (briefing template + every forecast slot's two
  templates), so editing a forecast template triggers a reload and `.env` is still rejected.
- `FORECAST_TEMPLATE_NAMES` (the `(kind,variant)->filenames` map) + `forecast_day_allowed(variant)`
  were hoisted from `forecast.py` into `templates.renderer` as the ONE source of truth; `forecast.py`
  now aliases `_TEMPLATES = FORECAST_TEMPLATE_NAMES` and uses `forecast_day_allowed`.

## Verification

- `uv run pytest tests/test_scheduler.py -k "forecast" -x -q` → 6 passed (Task 1).
- `uv run pytest tests/test_scheduler.py -k "forecast or fire_forecast or isolation or watch" -q` → 11 passed.
- `uv run pytest -q` full suite → **437 passed** (was 432 after Plan 13-04; +5 net new node-IDs; no regressions — briefing register/reconcile/fire_slot tests unbroken).
- `grep -c "_forecast_job_id" weatherbot/scheduler/daemon.py` → 6 (helper def + register + desired + others ≥ 3).
- `grep -c "for fc in location.forecast" weatherbot/scheduler/daemon.py` → 2 (register AND desired).
- Store/claim grep over the `fire_forecast_slot` body → 0 (no `claim_slot`/`release_claim`/`record_alert`/`record_sent`/`stamp_success`/`persist` — FCAST-05/A1).
- `uv run ruff check weatherbot/ templates/` → clean.

### Acceptance criteria
- `def _forecast_job_id` + `def fire_forecast_slot` present; forecast id contains `|fc|`; a disabled slot registers no job.
- A no-op reload reports 0 forecast add/remove; a variant edit reports one ADD + one REMOVE; a forecast and a briefing at the same time/days produce DISTINCT ids and both appear in the desired set.
- `fire_forecast_slot` posts exactly once to a fake channel and trips none of the seven store writes; a raising fire returns `None` without propagating and posts nothing.
- `validate_config_and_templates` raises `ValueError` on a typo'd forecast `.line.txt` token; `_make_watch_filter` returns True for both forecast template filenames and False for `.env`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Stale `def` anchor left an empty function during the Task 2 GREEN edit**
- **Found during:** Task 2 (GREEN). Replacing the Task-1 `fire_forecast_slot` stub (which had been
  placed immediately above `_forecast_job_id`) left a duplicate `def _forecast_job_id` header line
  with no body, producing an `IndentationError` that broke the whole module import.
- **Fix:** Removed the orphaned duplicate header line so `_forecast_job_id` has exactly one
  definition with its body intact. No behavior change — purely a self-inflicted edit artifact
  fixed before any test could run against it.
- **Files modified:** weatherbot/scheduler/daemon.py
- **Commit:** 529c5b0

### Non-behavioral refactor (in scope, not a deviation)
Hoisting `FORECAST_TEMPLATE_NAMES`/`forecast_day_allowed` out of `forecast.py` into
`templates.renderer` is the plan's explicit "build over the SAME source so the watched set and the
validated set never drift" instruction realized as a single shared map rather than three copies of
the filename literals. `forecast.py`'s public behavior is unchanged (it now aliases the hoisted map),
proven by the unbroken Plan 13-04 forecast-lookup tests.

## TDD Gate Compliance

Both tasks (`tdd="true"`) followed RED → GREEN. Git log shows the required gate commits per task:
- Task 1: `test(13-05)` (c239d9c) → `feat(13-05)` (8a5a787).
- Task 2: `test(13-05)` (fe8f73c) → `feat(13-05)` (529c5b0).
No REFACTOR commits were needed (both implementations were clean on first GREEN; the Task-2
indentation fix landed inside the GREEN commit before any test ran).

## Known Stubs

None. `fire_forecast_slot` is fully implemented (the Task-1 `NotImplementedError` placeholder was
replaced in Task 2); enabled forecast slots register live cron jobs, forecast templates validate at
load/reload, and edits are watched. All 11 new tests assert live behavior.

## Threat Flags

None. The threat surface introduced is exactly the plan's `<threat_model>`:
- **T-13-15** (forecast crash gating the scheduler/briefing) — mitigated: `fire_forecast_slot` body
  wrapped in the `fire_slot` try/except (log + return `None`); proven by `test_fire_forecast_slot_isolates_exception`.
- **T-13-16** (scheduled forecast writing the SQLite time series) — mitigated: no claim/store call,
  no store import on the path; proven by the zero-store-writes spy in `test_fire_forecast_slot_posts_and_writes_no_store`.
- **T-13-17** (malformed forecast template crashing a fire) — mitigated: forecast templates validated
  at load/reload keep-old; proven by `test_validate_rejects_bad_forecast_template`.
- **T-13-18** (malformed slot reaching the scheduler) — mitigated by `ForecastSchedule`'s Plan-13-03 validators (unchanged here).
- **T-13-19** (secret leaking in a scheduled-forecast log) — mitigated: outcome-only logging
  (location/kind/variant/time); no appid/webhook constructed or logged on this path.
- **T-13-SC** (installs) — N/A: this plan installed ZERO packages.

## Self-Check: PASSED

- FOUND: weatherbot/scheduler/daemon.py (`def _forecast_job_id`, `def fire_forecast_slot`)
- FOUND: weatherbot/config/loader.py (forecast template validation)
- FOUND: templates/renderer.py (`FORECAST_TEMPLATE_NAMES`, `forecast_day_allowed`)
- FOUND: weatherbot/interactive/commands/forecast.py (aliases hoisted map)
- FOUND: tests/test_scheduler.py (11 forecast tests)
- FOUND commit: c239d9c (RED 1), 8a5a787 (GREEN 1), fe8f73c (RED 2), 529c5b0 (GREEN 2)
