---
phase: 13-multi-day-forecast-templates
plan: 04
subsystem: interactive
tags: [forecast, on-demand, read-only, registry, cache-key, dispatch, shared-core]
requirements-completed: [FCAST-01, FCAST-02, FCAST-03, FCAST-04, FCAST-05, FCAST-07]
dependency-graph:
  requires:
    - "ForecastDay + multiday.select_days (Plan 13-01)"
    - "render_forecast + forecast token scopes + 8 templates (Plan 13-02)"
    - "parse_forecast_flags + ForecastFlags (Plan 13-03)"
    - "registry / CLI subparser-gen / Discord dispatch envelope + ForecastCache (Phase 12)"
  provides:
    - "weekday_forecast/weekend_forecast read-only handlers (weatherbot/interactive/commands/forecast.py)"
    - "lookup_forecast read-only path (weatherbot/interactive/lookup.py)"
    - "weekday-forecast/weekend-forecast registry specs (Forecast group, wired lazily)"
    - "widened ForecastCache.lookup key (optional suffix; A5 collision guard)"
    - "forecast_cache_suffix shared CLI+Discord key helper (weatherbot/interactive/command.py)"
  affects:
    - "Plan 13-05 scheduled forecast (reuses forecast.py render path + ForecastFlags)"
tech-stack:
  added: []
  patterns:
    - "Read-only LookupResult->CommandReply handler (mirror weather_views.py contract)"
    - "Derive-from-one-list dispatch: spec.group=='Forecast' special-case, no second command list"
    - "Shared flag grammar threaded identically through CLI (nargs='*') and Discord (raw arg)"
    - "Widened cache key via optional suffix (back-compat: weather lookups keep 2-arg call)"
    - "Injectable now= clock on handlers for deterministic window/notice tests"
key-files:
  created:
    - weatherbot/interactive/commands/forecast.py
    - tests/test_forecast_lookup.py
  modified:
    - weatherbot/interactive/lookup.py
    - weatherbot/interactive/registry.py
    - weatherbot/interactive/cache.py
    - weatherbot/interactive/bot.py
    - weatherbot/cli.py
    - weatherbot/interactive/command.py
    - weatherbot/interactive/__init__.py
    - tests/test_registry.py
    - tests/test_cli.py
    - tests/test_bot.py
    - tests/test_cache.py
decisions:
  - "lookup_forecast DELEGATES to lookup_weather (which already dual-fetches + retains both raw One Call payloads) — no extra fetch, no new endpoint, no client.py change (FCAST-07)"
  - "ForecastCache.lookup gained an OPTIONAL suffix arg (default None) so plain !weather lookups keep the original location-id-only key + 2-arg call; only forecast dispatch passes the 3rd arg — preserves every existing cache fake/test"
  - "Dispatch sites special-case spec.group=='Forecast' (NOT a hardcoded name list) so the derive-from-one-list invariant holds: cli.py/bot.py contain ZERO forecast command literals"
  - "Handlers accept an injectable keyword-only now= so window/notice logic is deterministically testable without freezing the system clock; production omits it"
  - "Day labels use an explicit _ABBR table + f-string (never strftime/%-m-%-d) per Pitfall 6"
metrics:
  duration: ~35 min
  tasks: 2
  files: 13
  tests-added: 12
  completed: 2026-06-19
---

# Phase 13 Plan 04: On-Demand Forecast Surface Summary

Wired the on-demand multi-day forecast end-to-end across BOTH surfaces: a read-only
`forecast.py` handler that consumes the Plan-01 selector/extraction model and the
Plan-02 renderer, a named `lookup_forecast` path that reuses the existing dual One Call
fetch (no extra OpenWeather call), the two registry specs (so the commands appear on the
CLI and Discord with no second list), a widened `ForecastCache` key so forecast results
never collide with a `!weather` result, and the CLI + Discord dispatch threading the
Plan-03 `+day`/`-day`/`+compact` flags through the SAME grammar. The whole path is
read-only (FCAST-05) and runs inside the existing Phase-12 guard ladder / non-propagating
envelope (CMD-16).

## What Was Built

### Task 1 — `forecast.py` handler + `lookup_forecast` (read-only)
- `weatherbot/interactive/commands/forecast.py`: `weekday_forecast(result, flags, *, now=None)`
  and `weekend_forecast(...)` read the already-fetched `daily[]` off
  `result.forecast.raw_onecall_imp`/`raw_onecall_met`, compute today in the location IANA
  tz, call `multiday.select_days(kind, today, daily_imp, add, drop, tz)`, build a
  `ForecastDay` per in-window index (imperial+metric twin), label the first two upcoming
  days "Today"/"Tomorrow" by local-date diff and the rest `f"{abbr} {m}/{d}"` (explicit
  f-string, no glibc `%-m/%-d`), pick the `(kind, variant)` template + sibling line-format
  pair, and render via `render_forecast`. Out-of-horizon `+day` notices render into
  `{notice}` (D-03). Imports nothing from the store; returns a surface-agnostic
  `CommandReply(title=..., text=rendered)`.
- `weatherbot/interactive/lookup.py`: `lookup_forecast(name, *, config, settings, client)`
  delegates to `lookup_weather` (which already performs the dual imperial+metric
  `fetch_onecall` and retains both raw payloads) — a NAMED read-only seam with no extra
  fetch and no new endpoint (FCAST-05/07).

### Task 2 — registry specs + widened cache key + CLI/Discord dispatch
- `registry.py`: two `CommandSpec`s in the "Forecast" group (`takes_location=True`) added to
  `_SPECS`; `_wire_handlers` lazily imports `commands.forecast` and wires both handlers.
- `cache.py`: `ForecastCache.lookup` gained an optional `suffix` arg → key becomes
  `(location.id, suffix)` for forecasts, plain `location.id` for weather (A5; back-compat).
- `command.py`: `forecast_cache_suffix(command, flags)` builds the
  `command|variant|+add|-drop` suffix — one source of truth for both surfaces.
- `cli.py`: forecast subparsers use `nargs="*"` to collect location + flag tokens;
  `_run_registry_command` special-cases `spec.group == "Forecast"`, parses via
  `parse_forecast_flags` (exit 1 on a bad day token), looks up the flag-stripped location,
  and calls `handler(result, flags)` inside the existing CLI envelope.
- `bot.py`: `on_message` special-cases the Forecast group, parses the raw arg via
  `parse_forecast_flags`, looks up off-loop with the widened suffix, and calls
  `handler(result, flags)` inside the existing non-propagating envelope (CMD-16).
- `interactive/__init__.py`: exported `ForecastFlags`, `parse_forecast_flags`,
  `forecast_cache_suffix`, `lookup_forecast`.

## Verification

- `uv run pytest tests/test_forecast_lookup.py tests/test_registry.py tests/test_cli.py tests/test_bot.py -k "forecast" -x -q` → 15 passed.
- `uv run pytest -q` full suite → **426 passed** (was 418; +8 net node-IDs after the two
  pre-existing registry tests were updated for the new Forecast group), no regressions.
- `grep -c "weekday-forecast" weatherbot/interactive/registry.py` → 2 (spec + wiring);
  `grep -c "weekday-forecast\|weekend-forecast" weatherbot/cli.py weatherbot/interactive/bot.py`
  → 0 (both surfaces derive from the one registry list — no second command list).
- `grep -c "weatherbot.weather.store\|import store" weatherbot/interactive/commands/forecast.py`
  → 0 (no store import; FCAST-05); `grep -c "strftime" forecast.py` → 0 (explicit labels).
- Zero-store-writes spy: `weekday_forecast` over a real `LookupResult` trips none of the
  seven store write functions (FCAST-05). Fetch-count assertion: `lookup_forecast` calls
  `client.fetch_onecall` exactly `["imperial","metric"]` (FCAST-07).
- `uv run ruff check weatherbot/` → clean.

### Acceptance criteria
- `def weekday_forecast`/`def weekend_forecast` present (2 matches).
- weekday/weekend render one line per selected day (FCAST-01/02); compact body strictly
  shorter than detailed and omits the UV token (FCAST-03); a `+sat` past the horizon
  renders the "horizon" notice (D-03).
- `BY_NAME["weekday-forecast"].handler is forecast.weekday_forecast`; both appear in
  `render_help` under a "Forecast" group (CMD-09 parity).
- CLI `weekday-forecast <loc> +compact` exit 0; a bad `+xyz` token exits 1 (T-13-07).
- Discord `!weekend-forecast <loc> +sat` returns an embed; a raising forecast handler is
  isolated by the existing envelope (CMD-16). Cache: a forecast suffix entry and a plain
  weather entry on the same location are distinct, repeats served from cache (A5).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test bug] Naive store/strftime substring assertions in the new test**
- **Found during:** Task 1 (GREEN). My first `test_forecast_module_imports_no_store`
  asserted the literal string `weatherbot.weather.store` was absent from the source — but
  the module's docstring legitimately references the store package to explain its
  read-only contract, so the assertion false-positived.
- **Fix:** Rewrote the test to parse the AST and scan only `Import`/`ImportFrom` nodes.
  Reworded two `forecast.py` comments so the grep-based acceptance criteria (`grep -c
  "strftime"`, store import) read 0 against prose as well as code.
- **Files modified:** tests/test_forecast_lookup.py, weatherbot/interactive/commands/forecast.py
- **Commit:** 3781419

**2. [Rule 2 - Testability] Injectable `now=` on the forecast handlers**
- **Found during:** Task 1. `select_days` keys off "today"; with a hard `datetime.now()`
  the weekday/weekend/notice tests were coupled to the real system date (non-deterministic
  on any day other than the fixture's 2026-06-19).
- **Fix:** Added a keyword-only `now: datetime | None = None` (defaults to the
  location-local wall clock) so tests pin a date; production callers omit it. Not a
  behavior change to the dispatch-facing signature.
- **Files modified:** weatherbot/interactive/commands/forecast.py, tests/test_forecast_lookup.py
- **Commit:** 3781419

**3. [Rule 1 - Updated assumptions] Two pre-existing registry tests**
- **Found during:** Task 2. Adding the two forecast specs introduced a "Forecast" group and
  made `weekday-forecast`/`weekend-forecast` (16 chars) the longest registry names — which
  invalidated `test_groups_are_weather_and_info` and `test_longest_keyword_first_ordering`.
  These failures were caused directly by this plan's intended additions (in scope).
- **Fix:** Updated both tests to expect the new group + longest-name head, and added
  `test_groups_are_weather_info_and_forecast`, `test_forecast_commands_wired`,
  `test_help_lists_forecast_commands`.
- **Files modified:** tests/test_registry.py
- **Commit:** 6ebf7a0

## Deferred Issues

- `tests/test_cache.py:21` carries a pre-existing unused `import pytest` (ruff F401) that
  predates this plan and is unrelated to the forecast changes (out of scope per the
  scope boundary). Logged to `deferred-items.md`.

## TDD Gate Compliance

Task 1 (`tdd="true"`) followed RED → GREEN:
- RED: `test(13-04)` (e5a1b3c) — import error on the not-yet-built `forecast` module /
  `lookup_forecast`, fails as expected.
- GREEN: `feat(13-04)` (3781419) — handler + `lookup_forecast`, Task-1 tests green.
No REFACTOR commit needed. Task 2 (`type="auto"`, not TDD-gated): `feat(13-04)` (6ebf7a0).

## Threat Surface

No new threat surface beyond the plan's `<threat_model>`. T-13-11 (no store write) proven
by the zero-store-writes spy; T-13-12 (handler crash isolation) proven by the
raising-forecast-handler bot test (existing envelope catches it); T-13-10 (guard-ladder
bypass) — the forecast dispatch sits INSIDE the existing operator-id/`!`-prefix/
non-propagating ladder, no new path. No appid/webhook/token is constructed or logged on
this path (T-13-13); content is config-sourced names + weather data + fixed labels (T-13-14).

## Known Stubs

None. Both handlers render live `ForecastDay.day_tokens(...)` via `render_forecast`; the
registry, cache, and both dispatch surfaces are fully wired with passing tests.

## Self-Check: PASSED

- FOUND: weatherbot/interactive/commands/forecast.py
- FOUND: tests/test_forecast_lookup.py
- FOUND: weatherbot/interactive/lookup.py (lookup_forecast)
- FOUND: weatherbot/interactive/registry.py (weekday-forecast/weekend-forecast)
- FOUND: weatherbot/interactive/cache.py (suffix-widened key)
- FOUND commits: e5a1b3c, 3781419, 6ebf7a0
