---
phase: 06-shared-lookup-core-command-parser
plan: 03
subsystem: interactive
tags: [package-barrel, send-now-delegation, byte-identical, import-cycle, D-08]

# Dependency graph
requires:
  - "weatherbot.interactive.command.{parse_weather_command,Command,CommandKind} (06-01)"
  - "weatherbot.interactive.lookup.{lookup_weather,LookupResult,UnknownLocationError} (06-02)"
  - "weatherbot.scheduler.context.schedule_placeholders (scheduled timing seam)"
provides:
  - "weatherbot/interactive/__init__.py — single barrel re-exporting all six public symbols"
  - "send_now delegates its read-only HEAD to lookup_weather (D-08); deliver+persist TAIL byte-identical"
  - "tests/test_interactive_package.py — barrel + ValueError-subclass + no-import-cycle smoke test"
affects:
  - "weatherbot/cli.py (send_now refactored; resolve_location/Forecast/template-render/ZoneInfo imports dropped)"
  - "phase-07-cli (can `from weatherbot.interactive import lookup_weather, parse_weather_command`)"
  - "phase-11-discord-bot (same single-barrel import surface)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Package barrel mirroring config/__init__.py house style (explicit __all__, re-export leaves)"
    - "extra_placeholders seam (Pattern 1 Option A): scheduled timing overrides lookup's on-demand timing keys, merge order preserved (Pitfall 1)"
    - "Manual --send-now path falls through to lookup_weather's own on-demand location-local timing (schedule_ctx None => extra_placeholders None)"

key-files:
  created:
    - weatherbot/interactive/__init__.py
    - tests/test_interactive_package.py
  modified:
    - weatherbot/cli.py

key-decisions:
  - "D-08 implemented: only send_now's read-only HEAD (resolve->fetch->Forecast->validate/render) was replaced by a lookup_weather call; the deliver+persist TAIL (send_briefing -> if result.ok: persist -> log -> return) is preserved verbatim"
  - "Scheduled timing layered via extra_placeholders=schedule_placeholders(schedule_ctx, sent_dt, checked_dt) ONLY when schedule_ctx is not None; for the manual path (schedule_ctx None) extra_placeholders is None so lookup_weather's own location-local schedule_placeholders(None, now, now) produces byte-identical timing keys"
  - "send_now no longer resolves location itself — it reads result_lr.location/.forecast/.text; resolve_location/Forecast/load_template/validate_template/render/ZoneInfo imports removed from cli.py as genuinely unreferenced (ruff-verified)"

requirements-completed: []

# Metrics
duration: ~2min
completed: 2026-06-15
tasks: 3
files: 3
---

# Phase 6 Plan 03: Send-Now Delegation + Package Barrel Summary

Shipped the `weatherbot.interactive` package barrel (re-exporting all six shared symbols from the two leaf modules) and refactored `send_now` to delegate its read-only fetch->render HEAD to `lookup_weather` via the `extra_placeholders` seam — keeping the v1.0 deliver+persist TAIL byte-identical so the unmodified `tests/test_send_now.py` stays green (criterion #4).

## Performance

- **Duration:** ~2 min
- **Started:** 2026-06-15T20:51:41Z
- **Completed:** 2026-06-15T20:53:57Z
- **Tasks:** 3
- **Files modified:** 2 created, 1 modified

## What Was Built

- **`weatherbot/interactive/__init__.py`** — the public barrel, mirroring `config/__init__.py` house style: `from .command import Command, CommandKind, parse_weather_command`, `from .lookup import LookupResult, UnknownLocationError, lookup_weather`, plus an explicit `__all__` listing all six names. Barrel-only, no logic. P7 and P11 now import the shared core + parser from one place.
- **`send_now` delegation (D-08)** — the read-only HEAD (resolve_location -> client guard'd dual fetch -> `Forecast.from_payloads` -> `load_template`/`validate_template` -> render merge) is now a single `lookup_weather(location_name, config=config, settings=settings, client=client, templates_dir=templates_dir, extra_placeholders=...)` call. The channel-build guard stays a send_now concern; the deliver+persist TAIL (`channel.send_briefing(result_lr.text, result_lr.forecast)` -> `if result.ok: persist(db_path, result_lr.location, result_lr.forecast)` -> log -> `return result`) is preserved verbatim, now reading off the `LookupResult`.
- **Scheduled-timing seam** — for the scheduled path (`schedule_ctx is not None`), `extra_placeholders=schedule_placeholders(schedule_ctx, sent_dt, checked_dt)` layers the scheduled `{sent_at}`/`{checked_at}`/`{schedule_note}` ON TOP of lookup's on-demand timing (Pattern 1 Option A; `values.update(extra_placeholders)` preserves merge order/precedence, Pitfall 1). For the manual `--send-now` path (`schedule_ctx is None`), `extra_placeholders` is left `None` so `lookup_weather`'s own `schedule_placeholders(None, now, now)` computes the identical location-local times that the old send_now computed via `ZoneInfo(location.timezone)`.
- **`tests/test_interactive_package.py`** — three plain-assert smoke tests: all six barrel symbols import and are non-None; `UnknownLocationError` is-a `ValueError` (D-07 re-checked at the package surface); and `weatherbot.cli` + `weatherbot.interactive` both import in one process with `send_now`/`lookup_weather` callable (no D-08 import cycle, Pitfall 3).

## Task Commits

1. **Task 1: Create the interactive package barrel** — `c0694e2` (feat)
2. **Task 2: Refactor send_now to delegate to lookup_weather (byte-identical)** — `3955ed2` (refactor)
3. **Task 3: Barrel re-export + no-import-cycle smoke test** — `78cf214` (test)

## Deviations from Plan

**1. [Rule 3 - Blocking] Manual-path timezone moved into lookup_weather instead of `ZoneInfo(location.timezone)` in send_now**
- **Found during:** Task 2
- **Issue:** The plan's literal call form kept `tz = schedule_ctx.tz if schedule_ctx is not None else ZoneInfo(location.timezone)` in send_now and passed `extra_placeholders=schedule_placeholders(...)` unconditionally. After delegation, send_now no longer resolves `location` (lookup_weather does), so `location.timezone` is not available there — referencing it would be a `NameError`.
- **Fix:** Compute scheduled timing and pass `extra_placeholders` ONLY when `schedule_ctx is not None`; for the manual path pass `extra_placeholders=None` and let `lookup_weather`'s own `schedule_placeholders(None, now, now)` (computed in `ZoneInfo(location.timezone)` internally) produce the timing keys. This is byte-identical to the old behavior — both compute location-local `now` in the same timezone — and is proven by the unmodified `tests/test_send_now.py` (including `test_manual_send_schedule_placeholders` and `test_send_now_late_context_populates_note`) staying green.
- **Files modified:** weatherbot/cli.py
- **Commit:** 3955ed2

**2. [Rule 3 - Blocking] Removed now-unused imports from cli.py**
- **Found during:** Task 2
- **Issue:** After delegation, `resolve_location`, `Forecast`, `load_template`, `validate_template`, `render`, and `ZoneInfo` were no longer referenced in cli.py (ruff F401).
- **Fix:** Removed all six unused imports (the plan explicitly authorized this: "remove any now-unused imports in cli.py ONLY if they are genuinely unreferenced … verify with ruff"). Confirmed none are referenced elsewhere in cli.py via grep before removal.
- **Files modified:** weatherbot/cli.py
- **Commit:** 3955ed2

## Verification

- `uv run pytest tests/test_send_now.py -q` — 4 passed; `git diff tests/test_send_now.py` empty (criterion #4 byte-identical gate).
- `uv run pytest -q` (full suite) — **206 passed** (203 prior + 3 new), no regression.
- `uv run pytest tests/test_interactive_package.py -x -q` — 3 passed.
- `uv run python -c "import weatherbot.cli, weatherbot.interactive"` — exits 0 (no import cycle).
- `grep -n 'lookup_weather' weatherbot/cli.py` — send_now calls lookup_weather (line 141).
- `grep -n 'extra_placeholders=' weatherbot/cli.py` — schedule_placeholders passed through extra_placeholders.
- `uv run ruff check` / `uv run ruff format --check` — clean on all three changed files.

## Threat Model Outcomes

- **T-06-08 (output drift):** Mitigated — `extra_placeholders` preserves the exact merge order; unmodified `tests/test_send_now.py` (body content, dual-fetch order, metric-primary temp_display, schedule-note, persist row count) passes and its diff is empty.
- **T-06-09 (import cycle):** Mitigated — top-level `from weatherbot.interactive import lookup_weather` in cli.py is safe (cli->interactive resolution is the lazy `build_client` edge on the lookup side); the no-import-cycle smoke test passes.
- **T-06-10 (persist ordering):** Mitigated — deliver -> `if result.ok: persist` -> log -> return preserved verbatim; persist still gated on `result.ok`.

## User Setup Required

None — no external service configuration, no package installs (zero `uv add`).

## Next Phase Readiness

- Phase 06 artifact inventory complete: `__init__.py` (here), `command.py` (06-01), `lookup.py` (06-02), `resolve_location` upgrade (06-02), `send_now` delegation (here), `test_command.py` (06-01), `test_lookup.py` (06-02), `test_interactive_package.py` (here).
- Both P7 (CLI) and P11 (Discord bot) can now `from weatherbot.interactive import lookup_weather, parse_weather_command` against a stable single barrel with no import cycle.

## Self-Check: PASSED

- FOUND: weatherbot/interactive/__init__.py
- FOUND: tests/test_interactive_package.py
- FOUND (modified): weatherbot/cli.py
- FOUND commit: c0694e2 (Task 1 barrel)
- FOUND commit: 3955ed2 (Task 2 send_now delegation)
- FOUND commit: 78cf214 (Task 3 smoke test)

---
*Phase: 06-shared-lookup-core-command-parser*
*Completed: 2026-06-15*
