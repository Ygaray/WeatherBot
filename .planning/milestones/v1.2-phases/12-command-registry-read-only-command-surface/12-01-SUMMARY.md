---
phase: 12-command-registry-read-only-command-surface
plan: 01
subsystem: interactive-command-surface
tags: [registry, parser, one-call, store-readers, config]
requirements-completed: [CMD-09, CMD-15, CMD-16]
requires:
  - "weatherbot/interactive/command.py parse_weather_command word-boundary guard"
  - "weatherbot/weather/store.py _SCHEMA heartbeat/health seeded rows"
  - "weatherbot/config/models.py Config + field_validator pattern"
provides:
  - "weatherbot/interactive/registry.py — CommandSpec/COMMANDS/BY_NAME/render_help (single source of truth)"
  - "weatherbot/interactive/command.py — parse_command + ParsedCommand (registry-driven, pure)"
  - "weatherbot/weather/client.py — One Call payload now retains hourly[]"
  - "weatherbot/weather/store.py — read_heartbeat/read_health (read-only)"
  - "weatherbot/config/models.py — Config.cloud_threshold knob (0-100, default 60)"
affects:
  - "Plans 12-02/12-03 (wire handlers into COMMANDS, dispatch on parse_command)"
  - "Phase 14/15 (hourly[] data seam now available)"
tech-stack:
  added: []
  patterns:
    - "frozen dataclass + immutable module-constant registry (mirrors command.py house style)"
    - "longest-keyword-first parse with preserved word-boundary guard"
    - "parameterized read-only SQLite readers (executescript-on-connect tolerance)"
    - "declared pydantic field + field_validator range check (Reliability tradition)"
key-files:
  created:
    - weatherbot/interactive/registry.py
    - tests/test_registry.py
  modified:
    - weatherbot/interactive/command.py
    - weatherbot/weather/client.py
    - weatherbot/weather/store.py
    - weatherbot/config/models.py
    - tests/test_command.py
    - tests/test_client.py
    - tests/test_store.py
    - tests/test_config.py
decisions:
  - "cloud_threshold is a single top-level Config field (Open Question 1) — minimal + reload-visible"
  - "handlers are None placeholders in this plan; Plans 02/03 wire callables (no handler imports in registry)"
metrics:
  duration: "~14 min"
  completed: "2026-06-19"
  tasks: 3
  files-created: 2
  files-modified: 8
  tests-added: 22
---

# Phase 12 Plan 01: Command Registry & Read-Only Contract Layer Summary

Built the Phase 12 contract layer: a single immutable `CommandSpec` registry that
`help`/CLI/Discord all derive from (CMD-09), a generalized pure registry-driven
`parse_command` (CMD-16), and the three data seams the read-only handlers need —
One Call now keeps `hourly[]` (CMD-15 + Phases 14/15), read-only
`read_heartbeat`/`read_health` store readers (CMD-12), and a validated
`cloud_threshold` config knob (CMD-15).

## What Was Built

### Task 1 — Command registry + registry-driven parser (commit `7cf2fa9`)
- New `weatherbot/interactive/registry.py`: frozen `CommandSpec` (name/group/summary/
  takes_location/handler), immutable `COMMANDS` tuple (7 specs: alerts/sun/wind/
  next-cloudy in group "Weather", help/locations/status in group "Info"), derived
  `BY_NAME` and `COMMANDS_BY_KEYWORD_LEN_DESC` indexes, and surface-agnostic
  `render_help()`. All handlers are `None` placeholders this plan (no handler imports).
- `command.py`: added frozen `ParsedCommand` + pure `parse_command(text)` — iterates
  longest-keyword-first, preserves the word-boundary guard so "sunny" never matches
  "sun" and "next-cloudy" beats any shorter prefix. Existing `parse_weather_command`
  kept for back-compat.
- `render_help` takes the command list as a parameter (default `COMMANDS`) purely so a
  test can prove the derive-from-one-list invariant against a throwaway spec.

### Task 2 — Widen One Call exclude + read-only store readers (commit `7e7065c`)
- `client.py`: `fetch_onecall` exclude changed `"minutely,hourly"` → `"minutely"`
  (keeps `hourly[]` for next-cloudy + Phases 14/15, D-06); corrected the now-false
  docstring; added a regression canary test asserting the client never excludes
  `hourly` and the parsed payload retains a non-empty `hourly[]`.
- `store.py`: added `read_heartbeat` and `read_health` — parameterized (`WHERE id=?`),
  read-only (zero writes), `executescript(_SCHEMA)`-on-connect so they tolerate a
  never-initialized db (the schema's `INSERT OR IGNORE` seeds the id=1 rows). Return
  plain dicts.

### Task 3 — Cloud-cover threshold config knob (commit `730019d`)
- `models.py`: declared `cloud_threshold: int = 60` on `Config` with a
  `@field_validator` enforcing `0 <= v <= 100` (fail-loud at load, matching the
  `Reliability` tradition). The default keeps existing keyless configs loading under
  `extra="forbid"` (Pitfall 6).
- **Reload confirmation:** because `cloud_threshold` is a plain field on `Config` and
  the reload path (`_do_reload`) re-reads and re-validates the entire `Config` from
  disk, the new knob is picked up on reload with **no reload-wiring change** — it
  rides the existing whole-config re-parse.

## Verification

- `uv run pytest tests/test_registry.py tests/test_command.py tests/test_client.py tests/test_store.py tests/test_config.py` → **92 passed**.
- Full suite: `uv run pytest` → **319 passed**, 1 (pre-existing audioop) warning.
- `grep -n 'exclude' weatherbot/weather/client.py` → only `"minutely"` excluded.
- `grep -c 'def read_heartbeat\|def read_health' weatherbot/weather/store.py` → 2; both use `WHERE id=?`.
- `grep -c 'cloud_threshold' weatherbot/config/models.py` → 4 (field + validator + decorator + comment).
- registry.py is the sole command-spec source; no second command list exists.
- `ruff check` + `ruff format` clean on all changed files.

## Deviations from Plan

**1. [Rule 3 - Blocking] Updated the existing client test's stale exclude assertion**
- **Found during:** Task 2
- **Issue:** `tests/test_client.py::test_fetch_onecall_builds_request` hard-asserted
  `exclude == "minutely,hourly"` — the old value. Widening the exclude (the planned
  Task 2 change) would have broken this pre-existing test.
- **Fix:** Updated the assertion to `== "minutely"` with a corrected comment. This is
  the same file/seam the task already modifies, in scope.
- **Files modified:** tests/test_client.py
- **Commit:** 7e7065c

No other deviations. No bugs, no missing critical functionality, no architectural
changes. The plan executed essentially as written.

## Notes for Downstream Plans

- `COMMANDS` handlers are `None` — Plans 02/03 wire the real callables and dispatch on
  `parse_command(...).spec`/`.arg`.
- `hourly[]` is now in the live One Call payload; the regression canary in
  `test_client.py` protects it for Phases 14/15.
- The existing One Call fixtures (`tests/fixtures/onecall_*.json`) still lack `hourly[]`
  — per D-06 the planner assigned fixture `hourly[]` enrichment to the `next-cloudy`
  implementation plan (12-02/03), not this contract plan. The code change + canary land
  here; realistic clouds fixtures land with the handler that consumes them.

## Self-Check: PASSED

- FOUND: weatherbot/interactive/registry.py
- FOUND: tests/test_registry.py
- FOUND commit 7cf2fa9 (registry + parser)
- FOUND commit 7e7065c (client + store readers)
- FOUND commit 730019d (cloud_threshold)
