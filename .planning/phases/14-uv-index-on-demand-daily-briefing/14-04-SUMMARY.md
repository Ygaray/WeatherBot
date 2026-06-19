---
phase: 14-uv-index-on-demand-daily-briefing
plan: 04
subsystem: api
tags: [uv, command-registry, discord, cli, read-only, compute-uv, openweather, onecall]

# Dependency graph
requires:
  - phase: 14-01
    provides: "UvConfig [uv] table with config.uv.threshold (default 6.0) + anchored uvcross/uvbelow/highuv fixtures"
  - phase: 14-02
    provides: "Pure compute_uv(onecall_imp, onecall_met, threshold, *, tz, now) -> frozen UvSummary (current/max/category/peak/crossing/window/hourly_points)"
  - phase: 12-03
    provides: "Phase-12 command registry (CommandSpec/_wire_handlers/render_help), shared read-only lookup core, CLI subparser builder, Discord on_message guard ladder + non-propagating envelope, next-cloudy threshold special-case template"
  - phase: 13-04
    provides: "Read-only handler + shared lookup path precedent; forecast handlers' injectable now= idiom for deterministic tests"
provides:
  - "uv(result, threshold, *, now=None) read-only handler in weather_views.py: full summary (now/max/category/peak/crossing/protect-window) + compact daytime HH:UV hourly line (D-04)"
  - "uv CommandSpec registered in the Weather group + wired in _wire_handlers (derive-from-one-list: auto-appears in CLI subparser, Discord dispatch, and help)"
  - "config.uv.threshold dispatch branch in cli._run_registry_command and bot.on_message (mirrors next-cloudy's cloud_threshold)"
  - "CMD-16/T-14-10 isolation: a raising uv handler stays inside the existing envelope and never gates the briefing spine"
affects: [15-uv-monitor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "On-demand command = one CommandSpec on the Phase-12 registry + a read-only handler reusing the shared lookup core; zero new infrastructure"
    - "Dispatch special-case threads config.uv.threshold (NOT a literal) at both surfaces, exactly mirroring next-cloudy's cloud_threshold branch"
    - "Command-only richness (compact HH:UV hourly line) layered on top of the briefing's summary-only UV fields, both off the same compute_uv UvSummary (D-04)"

key-files:
  created: []
  modified:
    - weatherbot/interactive/commands/weather_views.py
    - weatherbot/interactive/registry.py
    - weatherbot/cli.py
    - weatherbot/interactive/bot.py
    - tests/test_command_views.py
    - tests/test_registry.py
    - tests/test_cli.py
    - tests/test_bot.py

key-decisions:
  - "Handler signature is uv(result, threshold, *, now=None): the keyword-only now mirrors the forecast handlers' injectable-now idiom (test the anchored UV fixtures deterministically) while the live dispatch passes nothing so compute_uv uses datetime.now(tz). The plan's positional uv(result, threshold) contract is preserved (grep `def uv` still == 1)."
  - "compute_uv is imported at module top in weather_views.py (not lazily): uv.py is interactive-layer-free (stdlib + dataclasses only, asserted by a 14-02 test), so there is no import cycle to guard against — unlike the registry's lazy handler imports."
  - "The compact hourly line renders raw HH:UV daytime pairs (Open Q2): `f'{dt:%H}:{round(uvi)}'` space-joined from UvSummary.hourly_points; omitted entirely when there are no daytime points."
  - "Threshold display reuses the briefing's `_format_uv` idiom (whole values drop the trailing .0): 6.0 -> '6', 4.5 -> '4.5'."

patterns-established:
  - "Adding a read-only command = (1) a handler in weather_views.py off the retained payload, (2) one CommandSpec + one _wire_handlers entry, (3) an optional dispatch special-case only when the handler needs a config value (threshold). The subparser + help + Discord dispatch derive for free (CMD-09)."

requirements-completed: [UV-01]

# Metrics
duration: ~22min
completed: 2026-06-19
---

# Phase 14 Plan 04: uv <loc> On-Demand Command Summary

**An on-demand `uv <loc>` command on both surfaces (CLI `uv <loc>` / Discord `!uv <loc>`) — a read-only `weather_views.uv` handler that reads the already-fetched One Call payload, calls the Plan 14-02 `compute_uv`, and returns the full UV summary (now/max/WHO category/peak/threshold-crossing/protect window) PLUS a compact daytime `HH:UV` hourly line; registered as one Weather `CommandSpec` so it auto-appears in the CLI subparser, Discord dispatch, and `help`, with both dispatch sites threading `config.uv.threshold`.**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-06-19T18:40:00Z (approx)
- **Completed:** 2026-06-19
- **Tasks:** 2 (Task 1 followed TDD RED → GREEN)
- **Files modified:** 8 (4 source, 4 test)

## Accomplishments
- `uv(result, threshold, *, now=None) -> CommandReply` in `weather_views.py`: reads ONLY `result.forecast.raw_onecall_imp` (no second fetch, store-free), calls `compute_uv(raw, raw_met, threshold, tz=tz, now=now)`, and builds a `CommandReply` with `Now`, `Today's max` (+ WHO category), `Peak` (value + clock), `Crosses`/`Protect` (or "stays below {threshold} today"), and a compact `Hourly` `HH:UV` line.
- Registered `CommandSpec("uv", "Weather", ..., True)` in `_SPECS` + `"uv": weather_views.uv` in `_wire_handlers` — derive-from-one-list (CMD-09): `uv` now appears in `COMMANDS`/`BY_NAME`, the generated CLI subparser, and `render_help` under Weather with no other edit.
- Threaded `config.uv.threshold` into the handler from BOTH dispatch sites via a sibling `elif spec.name == "uv":` branch in `cli._run_registry_command` and `bot.on_message`, mirroring next-cloudy's `cloud_threshold` special-case (single literal each, no second command list).
- Proved CMD-16 / T-14-10 isolation: a raising `uv` handler is caught by the existing non-propagating Discord envelope (and the clean CLI envelope) — `on_message` returns without raising and the operator gets the generic error reply; the briefing spine is never gated.
- Full suite green: 509 passed (was 484 after 14-02; +25 across the phase's plans, incl. the new uv handler/registry/CLI/bot cases).

## Task Commits

1. **Task 1 (RED): failing uv handler + registry tests** — `2680f5e` (test)
2. **Task 1 (GREEN): uv handler + registry spec** — `75c9b6f` (feat)
3. **Task 2: CLI + Discord dispatch threading config.uv.threshold** — `e81a743` (feat)

**Plan metadata:** see final docs commit.

## Files Created/Modified
- `weatherbot/interactive/commands/weather_views.py` — added `uv` handler + `_threshold_display` / `_uv_hourly_line` helpers; top-level `compute_uv` import.
- `weatherbot/interactive/registry.py` — added the `uv` Weather `CommandSpec` + its `_wire_handlers` entry.
- `weatherbot/cli.py` — added the `elif spec.name == "uv": reply = spec.handler(result, config.uv.threshold)` dispatch branch.
- `weatherbot/interactive/bot.py` — added the matching `uv` dispatch branch in `on_message`.
- `tests/test_command_views.py` — uv crossing / stays-below / threshold-threading / no-second-fetch handler cases; added uv to the zero-store-writes spy.
- `tests/test_registry.py` — uv added to the Weather-group + location-taking assertions; new uv-registered-and-wired + help-listed tests.
- `tests/test_cli.py` — uv prints + exit 0, unknown-location exit 1, config.uv.threshold threaded (spy).
- `tests/test_bot.py` — uv embed, config.uv.threshold threaded (spy), raising-uv-handler isolation.

## Decisions Made
- **Injectable `now` (keyword-only):** `uv(result, threshold, *, now=None)`. The UV fixtures are anchored to 2024-06-14 NY, so the handler tests pin `now=_UV_NOW` to resolve the anchored `hourly[]` as "today" — exactly the `from_payloads(now_utc=...)` / `weekday_forecast(now=...)` precedent established in 14-02/13-04. The live dispatch (`cli.py`/`bot.py`) passes only `(result, config.uv.threshold)`, so `compute_uv` defaults to `datetime.now(tz)` in production. The plan's positional contract `uv(result, threshold)` is preserved.
- **Top-level `compute_uv` import** in `weather_views.py` rather than a lazy import: `uv.py` is guaranteed interactive-layer-free (asserted by a 14-02 test), so it cannot create an import cycle — the lazy-import discipline only applies to the registry's handler-module imports.
- **Compact line shape** `HH:UV` (`f'{dt:%H}:{round(uvi)}'`) per RESEARCH Open Q2, omitted when `hourly_points` is empty (briefing-spine-safe, never raises).

## Deviations from Plan

None - plan executed exactly as written. (The keyword-only `now` parameter is an additive test-injection seam matching the codebase's established forecast-handler idiom, not a behavioral deviation; the live dispatch uses the plan's exact `(result, config.uv.threshold)` call.)

## Issues Encountered
- The acceptance grep `grep -c "weatherbot.weather.store\|import store"` on `weather_views.py` returns **1**, not 0 — but the single match is the **module docstring** line ("imports nothing from `weatherbot.weather.store`"), a pre-existing prose reference, not an import statement. The handler genuinely imports nothing from the store (read-only intent satisfied; the zero-store-writes spy test passes). Left the docstring untouched.
- `ruff check weatherbot tests` reports 4 errors in `tests/test_cache.py` + `tests/test_reload.py` (unused imports). These are **pre-existing** and in files untouched by this plan — logged to `deferred-items.md` per the executor scope boundary, not fixed. All files this plan touched are ruff-clean.

## User Setup Required
None for this plan (pure code). Deploying `uv <loc>` to the live host (`yahir-mint`) requires a daemon restart — a new handler/registry entry is a code change, and the running daemon won't load it from config alone (per 14-RESEARCH Runtime State). Manual UAT (`!uv <loc>` on Discord + `uv <loc>` on the CLI) is tracked in 14-VALIDATION.md post-restart.

## Next Phase Readiness
- UV-01 is closed: current + max UV (+ category/crossing/window/peak + compact hourly line) on both the CLI and the Discord bot, riding the Phase-12 registry, shared read-only lookup core, and guard ladder with zero new infrastructure.
- Phase 15 (UV monitor) can reuse `compute_uv` verbatim with `config.uv.threshold` + `config.uv.pre_warn_lead_minutes` (the latter is stored/validated but still behavior-less until Phase 15). The failure-isolation guarantee proven here (raising handler never gates the spine) is the same discipline the intraday monitor will need.

## Self-Check: PASSED

- All 8 touched source/test files + `14-04-SUMMARY.md` present on disk.
- Commits `2680f5e` (RED test), `75c9b6f` (GREEN feat), `e81a743` (dispatch feat) found in git history.
- `grep -c "def uv"` weather_views.py == 1; `grep -c '"uv"'` registry.py == 2; `BY_NAME['uv'].handler is weather_views.uv` and `takes_location` == `True True`.
- `config.uv.threshold` appears once each in `cli.py` and `bot.py`.
- `uv run pytest` full suite: 509 passed. Touched files ruff-clean.

---
*Phase: 14-uv-index-on-demand-daily-briefing*
*Completed: 2026-06-19*
