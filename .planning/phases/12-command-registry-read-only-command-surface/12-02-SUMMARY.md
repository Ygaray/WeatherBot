---
phase: 12-command-registry-read-only-command-surface
plan: 02
subsystem: interactive-command-surface
tags: [handlers, weather-views, status, daemon-state, read-only]
requirements-completed: [CMD-10, CMD-11, CMD-12, CMD-13, CMD-14, CMD-15, CMD-16]
requires:
  - "weatherbot/interactive/registry.py — render_help (Plan 01)"
  - "weatherbot/weather/store.py read_heartbeat (Plan 01)"
  - "weatherbot/weather/models.py Forecast.raw_onecall_imp + wind_display"
  - "weatherbot/interactive/lookup.py LookupResult (.forecast/.location)"
provides:
  - "weatherbot/interactive/commands/ — CommandReply surface-agnostic reply type"
  - "weatherbot/interactive/commands/weather_views.py — alerts/sun/wind/next_cloudy + compass + _is_daytime"
  - "weatherbot/interactive/commands/info.py — help_cmd/locations"
  - "weatherbot/interactive/commands/status.py — status handler"
  - "weatherbot/interactive/state.py — DaemonState read-only accessor (next_fires/uptime)"
affects:
  - "Plan 12-03 (wires these handlers into COMMANDS, dispatches on parse_command, threads DaemonState through the daemon/bot/CLI)"
  - "Phase 14/15 (reuse _is_daytime helper + DaemonState.monitor_alive slot)"
tech-stack:
  added: []
  patterns:
    - "frozen-dataclass surface-agnostic reply (CommandReply title/lines/text)"
    - "read-off-retained-payload handlers (no second fetch); zero-store-writes spy"
    - "16-point compass pure table lookup (no bearing library)"
    - "read-only DaemonState accessor reusing _announce_schedule next-fire logic"
key-files:
  created:
    - weatherbot/interactive/commands/__init__.py
    - weatherbot/interactive/commands/weather_views.py
    - weatherbot/interactive/commands/info.py
    - weatherbot/interactive/commands/status.py
    - weatherbot/interactive/state.py
    - tests/test_command_views.py
    - tests/test_status.py
    - tests/fixtures/onecall_imperial_cloudy_hourly.json
    - tests/fixtures/onecall_imperial_cloudy_daily.json
    - tests/fixtures/onecall_imperial_clouds_clear.json
  modified: []
decisions:
  - "CommandReply is a new frozen dataclass (title/lines/text) — the D-04 same-content seam Plan 03 renders to embed vs plain text"
  - "next-cloudy daytime gating uses daily[].sunrise/sunset with a fixed 06:00-20:00 local fallback (CONTEXT D-05 permits simpler Phase-12 approach)"
  - "DaemonState takes the ConfigHolder (read via current()) rather than a frozen config snapshot, so status always reports the live reloaded config"
  - "dedicated next-cloudy clouds fixtures (own files) rather than mutating shared clear/alert fixtures other suites assert against"
metrics:
  duration: "~12 min"
  completed: "2026-06-19"
  tasks: 3
  files-created: 10
  files-modified: 0
  tests-added: 25
---

# Phase 12 Plan 02: Read-Only Command Handlers & DaemonState Summary

Implemented the seven read-only command handlers (the body of the command surface)
and the read-only `DaemonState` accessor `status` needs. The weather views read
fields straight off the already-fetched One Call payload retained on `Forecast`
(no second fetch); the info handlers read the registry/config; `status` reads the
live scheduler + heartbeat + bot liveness through a frozen injected accessor.
Every handler is store-free (D-06 / SC#5) and returns a surface-agnostic
`CommandReply` (D-04) that Plan 03 renders as a Discord embed or CLI plain text.

## What Was Built

### Task 1 — Weather-view handlers (commit `7d93e01`)
- New `commands/__init__.py`: frozen `CommandReply` (`title`, `lines: tuple[(name,
  value)]`, optional `text`) — the D-04 "same content both surfaces" seam.
- New `commands/weather_views.py`: `alerts`/`sun`/`wind`/`next_cloudy` handlers, the
  pure `compass(deg)` 16-point table lookup, and a reusable `_is_daytime(dt, raw)`
  helper (daily sunrise/sunset with a fixed-window fallback, kept in one place for
  Phases 14/15). Each reads `result.forecast.raw_onecall_imp` only — no second fetch.
- `next_cloudy` hybrid (D-03): first daytime `hourly[]` bucket ≥ threshold, falling
  back to `daily[]` days 3-8 (`[2:]` slice), then a clear "no cloudy day in the next
  N days" reply.
- Three dedicated clouds fixtures with realistic `hourly[]` (`dt`+`clouds`): an
  hourly-hit (daytime 12:00 EDT clouds=80), a daily-fallback (hourly clear, daily
  day-3 clouds=85), and an all-clear (no cloudy day). Own files so the shared
  clear/alert fixtures other suites assert against stay untouched.
- `tests/test_command_views.py`: alerts present/clear, sun local-time, compass
  N/E/S/W (+NE, 360→N), wind speed+compass, next-cloudy hourly-hit/daily-fallback/
  none, and an extended zero-store-writes spy across every handler.

### Task 2 — Info handlers (commit `d324dda`)
- New `commands/info.py`: `help_cmd()` delegates to `registry.render_help()` (the
  registry owns the grouping — no duplicate logic, CMD-09 anti-drift); `locations(
  config)` lists `config.locations` (name + timezone) with no fetch/cache/store.
- Tests assert `help_cmd()` contains every `registry.COMMANDS` summary and that
  `locations` returns all configured names fetch-free/store-free.

### Task 3 — DaemonState + status (commit `7d6e74e`)
- New `interactive/state.py`: frozen read-only `DaemonState` (`scheduler`, `holder`,
  `db_path`, `started_at`, `bot_alive`, plus a `monitor_alive=None` Phase-15 slot).
  `next_fires()` mirrors `_announce_schedule` verbatim (running `next_run_time` →
  `trigger.get_next_fire_time` fallback), keyed by `f"{name}|{time}|{days}"`,
  reporting the earliest upcoming fire per location. `uptime()` = now − started_at.
  No `add_job`/`remove_job`/`holder.replace`/store write anywhere (D-02 read-only).
- New `commands/status.py`: `status(daemon_state)` reports the four D-02 sections —
  next send per location, alive+uptime, Discord-bot + UV-monitor liveness (monitor
  "not running" until Phase 15 supplies the callable, A4), and last-briefing via the
  one `read_heartbeat` reader ("none yet" when unstamped).
- `tests/test_status.py`: a fake scheduler (running `next_run_time` + pending
  trigger-fallback jobs), stamped/unstamped heartbeat, bot alive/down, monitor
  not-running, and per-location next-send.

## Verification

- `uv run pytest tests/test_command_views.py tests/test_status.py` → **25 passed**.
- Full suite `uv run pytest` → **344 passed** (up from 319 in Plan 01; +25), 1
  pre-existing audioop warning.
- `grep -L 'weather.store\|import store' weatherbot/interactive/commands/weather_views.py` → lists the file (NO store import, D-06).
- `grep -c 'def alerts\|def sun\|def wind\|def next_cloudy\|def compass' .../weather_views.py` → 5.
- `grep -c 'render_help' .../info.py` → 3 (delegates; no duplicate grouping).
- `grep -L 'fetch_onecall\|lookup_weather\|weather.store' .../info.py` → lists the file (no fetch/store).
- `grep -c 'def next_fires\|def uptime\|class DaemonState' .../state.py` → 3.
- Read-only gate: no `add_job`/`remove_job`/`holder.replace`/`stamp_`/`persist(` CODE calls in `state.py`/`status.py` (only docstring mentions in state.py describing the constraint).
- `ruff check` + `ruff format` clean on all changed files.

## Deviations from Plan

None — no bugs, no missing critical functionality, no blocking issues, no
architectural changes. The plan executed exactly as written.

**Note (in-scope clarification, not a deviation):** `info.py` was created during
Task 1's GREEN phase (not a separate file write) because `tests/test_command_views.py`
— the single shared test file the plan lists under BOTH Task 1 and Task 2 — imports
`info` at module top, so the file had to exist for the Task-1 test collection to
succeed. The two implementations were still committed atomically per task
(`7d93e01` weather_views, `d324dda` info), preserving the per-task commit boundary.

## Notes for Downstream Plans (12-03)

- Handlers are NOT yet wired into `registry.COMMANDS` (handlers stay `None`); Plan 03
  wires the callables and dispatches on `parse_command(...).spec`/`.arg`.
- `DaemonState` must be constructed in `run_daemon` (capture `started_at` at start,
  pass `scheduler`/`holder`/`db_path`/`bot.is_alive`) and threaded into the bot/CLI
  context alongside `cache` — the construction site is `daemon.py:1037-1062`.
- Location-taking handlers (`alerts`/`sun`/`wind`/`next_cloudy`) receive a
  `LookupResult` from `cache.lookup`; Plan 03 resolves None→default and catches
  `UnknownLocationError` in the existing bot envelope. `next_cloudy` also needs
  `config.cloud_threshold` passed as its `threshold` arg.
- `_is_daytime` in `weather_views.py` is the reusable daytime helper for Phases 14/15.
- `DaemonState.monitor_alive` is the clean Phase-15 UV-monitor liveness slot.

## Self-Check: PASSED

- FOUND: weatherbot/interactive/commands/__init__.py
- FOUND: weatherbot/interactive/commands/weather_views.py
- FOUND: weatherbot/interactive/commands/info.py
- FOUND: weatherbot/interactive/commands/status.py
- FOUND: weatherbot/interactive/state.py
- FOUND: tests/test_command_views.py, tests/test_status.py
- FOUND: 3 clouds fixtures
- FOUND commit 7d93e01 (weather views), d324dda (info), 7d6e74e (status + DaemonState)
