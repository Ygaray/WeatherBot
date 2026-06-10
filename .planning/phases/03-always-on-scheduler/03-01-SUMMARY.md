---
phase: 03-always-on-scheduler
plan: 01
subsystem: infra
tags: [apscheduler, pydantic, sqlite, scheduler, idempotency, time-machine]

# Dependency graph
requires:
  - phase: 02-briefing-pipeline
    provides: "Config/Location model with extra=forbid + field_validator fail-loud-at-load tradition; weather/store.py SQLite _SCHEMA + parameterized persist; tmp_db/load_fixture test fixtures"
provides:
  - "apscheduler 3.11.x (+ dev time-machine) as resolved deps (no 4.x)"
  - "weatherbot/scheduler/ package with dependency-free parse_days() days vocabulary parser/normalizer"
  - "Schedule config model (time/days/enabled) + Location.schedule field with parsed_time()/day_of_week accessors"
  - "sent_log idempotency table + was_sent/record_sent helpers (race-safe (location,send_time,local_date) dedup)"
  - "[[locations.schedule]] config examples (weekday-home/weekend-travel split)"
affects: [03-02, 03-daemon, catch-up-planner, cron-trigger]

# Tech tracking
tech-stack:
  added: [apscheduler>=3.11.2 <4, time-machine>=2.16 (dev)]
  patterns: ["dependency-free leaf validator module (days.py) imported by config to avoid cycle", "store-raw-normalize-at-use for days (human-friendly logs, parse_days at trigger)", "INSERT OR IGNORE on UNIQUE key for idempotent record_sent"]

key-files:
  created: [weatherbot/scheduler/__init__.py, weatherbot/scheduler/days.py, tests/test_scheduler.py]
  modified: [pyproject.toml, weatherbot/config/models.py, weatherbot/weather/store.py, config.example.toml, tests/test_config.py]

key-decisions:
  - "days stored RAW on Schedule, normalized at use via day_of_week property (keeps announce/log human-friendly; trigger+planner share parse_days)"
  - "scheduler/__init__.py exports parse_days (barrel) but days.py stays dependency-free to break the config<->scheduler import cycle"
  - "time-machine added to dev group up front (DST next-fire tests in Plan 03)"

patterns-established:
  - "Pattern 2 (days vocabulary): parse_days() preset/list whitelist validator, ValueError lists sorted vocabulary (mirrors Location._units_valid)"
  - "Pattern 4 (sent-log): was_sent check-before-fire + record_sent INSERT OR IGNORE after success; helpers self-create schema, fully parameterized"

requirements-completed: [SCHD-01, SCHD-02, SCHD-03, SCHD-07]

# Metrics
duration: 4min
completed: 2026-06-10
---

# Phase 03 Plan 01: Scheduler Foundation Summary

**APScheduler 3.11.x installed plus the validated, persisted scheduler foundation — a dependency-free `parse_days` vocabulary normalizer, a `Schedule` config model with `Location.schedule`, and a race-safe `sent_log` idempotency store — the pure pieces the daemon (Plan 03) consumes.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-10T19:21Z
- **Completed:** 2026-06-10T19:25Z
- **Tasks:** 3
- **Files modified:** 8 (3 created, 5 modified; config.toml edited locally — gitignored)

## Accomplishments
- `apscheduler>=3.11.2,<4` resolved as a project dependency (human-verified legitimate; no 4.x present) + dev `time-machine>=2.16`.
- `weatherbot/scheduler/days.py` `parse_days()` validates/normalizes the D-02 vocabulary (`daily`→`mon-sun`, `weekdays`→`mon-fri`, `weekends`→`sat,sun`, comma lists), case/space-insensitive, fail-loud on bad tokens.
- `Schedule` model (`time`/`days`/`enabled`, `extra="forbid"`) with HH:MM + days `field_validator`s and shared `parsed_time()`/`day_of_week` accessors; `Location.schedule: list[Schedule]` default_factory (multiple toggleable entries; `enabled=false` retained).
- `sent_log` table (`UNIQUE(location_name, send_time, local_date)`) + `was_sent`/`record_sent` helpers giving idempotent, race-safe dedup; schema self-creating; fully parameterized (T-03-01).
- `[[locations.schedule]]` blocks documenting the weekday-home / weekend-travel split in both `config.example.toml` and `config.toml`.

## Task Commits

1. **Task 1: Verify + install APScheduler** - `04228e1` (chore) — gate pre-approved by user
2. **Task 2: days parser + Schedule model + Location.schedule** - `6b9a0a6` (feat, TDD)
3. **Task 3: sent_log table + was_sent/record_sent + config examples** - `5c1b7d3` (feat, TDD)

_Note: tests/test_scheduler.py (incl. test_sent_log_idempotent) was authored and committed within Task 2 (`6b9a0a6`); its sent-log test went green once Task 3 added the store helpers._

## Files Created/Modified
- `weatherbot/scheduler/__init__.py` - package barrel exporting `parse_days`
- `weatherbot/scheduler/days.py` - dependency-free `parse_days()` + `_PRESETS`/`_DAYS`
- `weatherbot/config/models.py` - `Schedule` model + `Location.schedule` field; imports `parse_days`
- `weatherbot/weather/store.py` - `sent_log` DDL in `_SCHEMA` + `was_sent`/`record_sent`
- `config.example.toml` / `config.toml` - `[[locations.schedule]]` weekday/weekend examples
- `tests/test_scheduler.py` (new) - days-matrix + sent-log idempotency tests
- `tests/test_config.py` - multiple-entry / toggle / bad-days / bad-time Schedule tests
- `pyproject.toml` - apscheduler + dev time-machine deps

## Decisions Made
- Store `days` raw on `Schedule`, normalize at use via `day_of_week` (Open Question 1 recommendation) so logs/announce stay human-friendly while the trigger consumes `parse_days`.
- `days.py` kept dependency-free (no config/apscheduler import) to avoid the config↔scheduler import cycle; `scheduler/__init__.py` re-exports `parse_days`.
- HH:MM validator enforces `len==2` on both fields, rejecting `7:00`/`7am`/`24:00`/`07:60`.

## Deviations from Plan
None - plan executed exactly as written. (Task 1 install proceeded per the pre-resolved blocking-human gate; user approved both packages.)

## Issues Encountered
- `config.toml` is gitignored (user runtime file), so its `[[locations.schedule]]` edit is local-only and not part of any commit — expected, not a problem. `config.example.toml` (tracked) carries the same documented split and is asserted by `test_example_config_loads_cleanly`.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SCHD-01/02/03 (declarative per-location schedule + toggle + day-of-week normalization) and the SCHD-07 store half (dedup table) are validated-at-load and unit-tested — ready for Plan 03 to wire the daemon (cron trigger registration, catch-up planner, exactly-once fire via was_sent/record_sent).
- Full suite green: 109 passed. `apscheduler` importable at 3.11.2; no 4.x in the lockfile.

## Self-Check: PASSED

All created files present on disk; all task commits (04228e1, 6b9a0a6, 5c1b7d3) found in git history.

---
*Phase: 03-always-on-scheduler*
*Completed: 2026-06-10*
