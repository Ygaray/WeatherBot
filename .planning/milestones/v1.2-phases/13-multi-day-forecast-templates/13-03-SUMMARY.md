---
phase: 13-multi-day-forecast-templates
plan: 03
subsystem: interactive
tags: [forecast, flag-parser, config-model, parse-dont-validate, shared-core]
requirements-completed: [FCAST-03, FCAST-04, FCAST-06]
dependency-graph:
  requires:
    - "weatherbot/scheduler/days._DAYS (the mon..sun token vocabulary)"
    - "weatherbot/config/models.Schedule validators (_hhmm, parse_days, accessors)"
  provides:
    - "parse_forecast_flags() + frozen ForecastFlags (weatherbot/interactive/command.py)"
    - "ForecastSchedule config model + Location.forecast list (weatherbot/config/models.py)"
  affects:
    - "Plan 13-04 on-demand forecast handler (consumes ForecastFlags variant/add/drop/location)"
    - "Plan 13-05 scheduled forecast jobs (consume Location.forecast + ForecastSchedule accessors)"
tech-stack:
  added: []
  patterns:
    - "Frozen result dataclass (mirror ParsedCommand) for surface-agnostic parse output"
    - "Parse-don't-validate, string-ops-only flag grammar (T-13-07 / T-06-01 contract)"
    - "Separate frozen config model reusing Schedule validators verbatim (NOT extending Schedule)"
    - "Enum field_validator idiom (mirror Location._units_valid) for kind/variant"
    - "default_factory=list -> absent table = [] (zero-migration config extension)"
key-files:
  created:
    - tests/test_flags.py
  modified:
    - weatherbot/interactive/command.py
    - weatherbot/config/models.py
    - weatherbot/config/__init__.py
    - tests/test_config.py
decisions:
  - "ForecastFlags is a separate frozen dataclass (not reusing ParsedCommand) — distinct fields (variant/add/drop) and parsed differently (flag classification, not registry keyword match)"
  - "+day/-day tokens validated against days._DAYS (abbreviations only, A4); presets like 'weekends' are NOT valid flag tokens and fail loud"
  - "ForecastSchedule duplicates the Schedule _hhmm/_days_valid/parsed_time/day_of_week bodies verbatim rather than subclassing — RESEARCH Alternatives: a separate model avoids forecast/briefing job-id collision and keeps the briefing slot un-polluted"
  - "Exported both ForecastSchedule AND the previously-unexported Schedule from the config package __init__ for downstream Plan 04/05 imports"
metrics:
  duration: ~12 min
  tasks: 2
  files: 5
  tests-added: 25
  completed: 2026-06-19
---

# Phase 13 Plan 03: Forecast Flag Grammar + Schedule Config Model Summary

Defined the two disjoint, consumer-free contracts the on-demand (Plan 04) and scheduled (Plan 05) forecast paths both depend on, ahead of either consumer (interface-first): a shared injection-safe `+day`/`-day`/`+compact` flag grammar returning a frozen `ForecastFlags` (CLI and Discord parse identically — Phase 6 shared-core principle), and the `ForecastSchedule` config model + `Location.forecast` list as a separate frozen, fail-loud model so forecast and briefing job ids never collide.

## What Was Built

### Task 1 — `parse_forecast_flags` + `ForecastFlags` (weatherbot/interactive/command.py)
- Frozen `ForecastFlags(variant, add: frozenset[str], drop: frozenset[str], location)` mirroring `ParsedCommand`'s `@dataclass(frozen=True)` house style; `variant` defaults `"detailed"`.
- `parse_forecast_flags(arg)`: splits on whitespace, classifies each token case-insensitively — `+compact`/`--compact` -> compact, `+detailed`/`--detailed` -> detailed (both spellings: `+` for Discord, `--` for CLI); `+<day>`/`-<day>` collect raw add/drop sets via a `_day_token` helper that validates against `days._DAYS` and raises `ValueError` listing `sorted(_DAYS)` on an unknown token (A4 abbreviations-only, T-13-07 fail-loud); remaining non-flag tokens form the raw-case location substring. `None` -> all defaults.
- Copies the T-06-01 security contract: only `str.split`/`str.casefold`/slicing — never `str.format`/`eval`/`exec`/shell. Dedup/calendar-sort is deliberately NOT done here (that is `multiday.select_days`' job, Plan 01).

### Task 2 — `ForecastSchedule` + `Location.forecast` (weatherbot/config/models.py)
- `ForecastSchedule(BaseModel)` with `model_config = ConfigDict(extra="forbid", frozen=True)` and fields `kind`, `variant="detailed"`, `time`, `days`, `enabled=True`. Reuses the `Schedule` `_hhmm` time validator and `parse_days`-backed `_days_valid` verbatim, plus identical `parsed_time()`/`day_of_week`. Two enum `field_validator`s (the `_units_valid` idiom) gate `kind ∈ {weekday,weekend}` and `variant ∈ {detailed,compact}`, each raising `ValueError` listing the allowed values.
- `Location.forecast: list[ForecastSchedule] = Field(default_factory=list)` next to `schedule`, so an absent `[[locations.forecast]]` table loads as `[]` (zero migration). `Schedule` was NOT mutated. Both `ForecastSchedule` and `Schedule` are now exported from the `weatherbot.config` package.

## Verification

- `uv run pytest tests/test_flags.py -x -q` -> 15 passed.
- `uv run pytest tests/test_config.py -k "forecast or schedule" -x -q` -> 11 passed.
- `uv run pytest -q` full suite -> **411 passed** (no regressions; ConfigHolder snapshot compatibility unbroken — frozen models).
- `grep -c "^class Schedule" weatherbot/config/models.py` -> 1 (Schedule not mutated to carry forecast fields).
- `ruff check` clean on all touched files.

### Acceptance criteria
- `def parse_forecast_flags` + `class ForecastFlags` both present (2 matches); `from weatherbot.scheduler.days import _DAYS` present.
- No new `str.format`/`eval`/`exec`/`subprocess`/`os.system` in code (the 3 grep hits are docstring prose describing the security contract — consistent with the pre-existing `parse_command` docstrings).
- `+compact` and `--compact` both -> compact; `+sat +sun` -> add={sat,sun}; `-mon` -> drop={mon}; `+xyz` raises naming allowed tokens; `None` -> detailed/empty/empty/None.
- `class ForecastSchedule` + `forecast: list[ForecastSchedule]` present; new model carries `ConfigDict(extra="forbid", frozen=True)`.
- Valid `[[locations.forecast]]` loads with `day_of_week` matching `parse_days`; bad `kind`/`variant`/`time`/`days`/unknown key all raise at load; absent table -> `forecast == []`.

## Deviations from Plan

None — plan executed as written. (The `ForecastSchedule` validator bodies are copied verbatim from `Schedule` per the plan's explicit "copy verbatim, do NOT extend Schedule" instruction and RESEARCH Alternatives Considered; this duplication is intentional, not a deviation. Additionally exported the previously-unexported `Schedule` alongside `ForecastSchedule` from the config package `__init__` so Plans 04/05 can import both — a non-behavioral convenience addition.)

## TDD Gate Compliance

Both tasks followed RED -> GREEN. Git log shows the required gate commits per task:
- Task 1: `test(13-03)` (949980d) -> `feat(13-03)` (1900bfe).
- Task 2: `test(13-03)` (73a1e14) -> `feat(13-03)` (4923164).

No REFACTOR commits were needed (both implementations were clean on first GREEN).

## Known Stubs

None. Both contracts are fully implemented with passing tests; their consumers (the on-demand handler in Plan 04 and the scheduled forecast jobs in Plan 05) land in later plans this phase.

## Threat Flags

None. The threat surface introduced (`parse_forecast_flags` input handling, `ForecastSchedule` config validation) is exactly the surface enumerated in the plan's threat model (T-13-07/T-13-08/T-13-09), all mitigated as specified.

## Self-Check: PASSED

- FOUND: tests/test_flags.py
- FOUND: weatherbot/interactive/command.py (parse_forecast_flags, ForecastFlags)
- FOUND: weatherbot/config/models.py (ForecastSchedule, Location.forecast)
- FOUND commit: 949980d, 1900bfe, 73a1e14, 4923164
