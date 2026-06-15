---
phase: 06-shared-lookup-core-command-parser
plan: 02
subsystem: interactive
tags: [lookup-core, read-only, typed-errors, tdd]
requirements-completed: []
requires:
  - weatherbot.config.resolve_location
  - weatherbot.weather.models.Forecast.from_payloads
  - weatherbot.scheduler.context.schedule_placeholders
  - templates.renderer.{load_template,validate_template,render}
provides:
  - weatherbot.interactive.lookup.lookup_weather
  - weatherbot.interactive.lookup.LookupResult
  - weatherbot.interactive.lookup.UnknownLocationError
affects:
  - weatherbot/config/loader.py (resolve_location raise-type upgrade)
tech-stack:
  added: []
  patterns:
    - "Read-only fetch->render core (no store import, no db path) — D-06"
    - "Typed ValueError subclass for backward-compatible richer errors — D-07"
    - "Lazy build_client import inside client-is-None branch to break cli<->interactive cycle"
    - "extra_placeholders merged LAST so callers can override timing keys"
key-files:
  created:
    - weatherbot/interactive/lookup.py
    - tests/test_lookup.py
  modified:
    - weatherbot/config/loader.py
decisions:
  - "D-05: LookupResult is a plain @dataclass exposing text/forecast/location"
  - "D-06: lookup_weather takes no database path and imports nothing from the store package"
  - "D-07: UnknownLocationError(ValueError) carries .requested + .valid_names; raised from the upgraded resolve_location so the whole v1.0 path inherits it"
  - "Open Question 1: lookup computes its own location-local sent_at/checked_at (schedule_ctx=None form), matching a manual --send-now briefing"
  - "Pitfall 3: build_client lazy-imported inside the client-is-None branch"
  - "Pitfall 5 / T-06-07: resolve_location lazy-imports UnknownLocationError at raise time, keeping the config<-interactive edge non-cyclic"
metrics:
  duration: ~12m
  completed: 2026-06-15
  tasks: 3
  files: 3
---

# Phase 6 Plan 02: Shared Read-Only Lookup Core Summary

Created `weatherbot/interactive/lookup.py` — the read-only `lookup_weather()` fetch->render core (resolve location, dual-unit One Call fetch, build `Forecast`, render the exact v1 template) returning a `LookupResult(text, forecast, location)` value object that writes nothing to the store and raises a typed `UnknownLocationError(ValueError)` on an unknown name.

## What Was Built

- **`lookup_weather(name, *, config, settings=None, client=None, templates_dir=None, extra_placeholders=None) -> LookupResult`** — resolves the configured location (`None` -> first/default), fetches imperial then metric via the injected One Call client (DATA-03 dual-fetch, imperial first), builds one `Forecast` with the per-location `units` override selecting the display primary (CR-01), validates + renders the v1 template, and returns the result. Location-local `{sent_at}`/`{checked_at}` are computed via `schedule_placeholders(None, now, now)` (Open Question 1); `extra_placeholders` merges last so a future caller can override the timing keys.
- **`LookupResult`** — plain `@dataclass` with `text: str`, `forecast: Forecast`, `location: Location` (D-05), so P7's CLI prints `.text` and P11's Discord bot builds an embed from `.forecast` without re-fetching.
- **`UnknownLocationError(ValueError)`** — carries `.requested` + `.valid_names`, with a message identical to the previous loader raise (D-07). Subclassing `ValueError` keeps every existing `except ValueError` caller green (Pitfall 5).
- **`resolve_location` raise-upgrade** — the final no-match `raise` now raises `UnknownLocationError(name, [loc.name for loc in config.locations])`, so the whole v1.0 path inherits the richer error backward-compatibly.

## Key Implementation Notes

- **Read-only proof (D-06 / T-06-04):** `lookup.py` takes no database path and imports nothing from the store package. Verified by the no-store-import grep gate (count 0), the no-`db_path` grep gate (count 0), and the zero-store-writes spy test that monkeypatches all 7 store write functions (`persist`, `claim_slot`, `record_alert`, `resolve_alert`, `stamp_tick`, `stamp_success`, `stamp_health`) to raise — `lookup_weather` completes without tripping any.
- **Import-cycle breaks:** `build_client` is lazy-imported inside the `client is None` branch (Pitfall 3, matching cli.py's lazy-daemon precedent); `resolve_location` lazy-imports `UnknownLocationError` at raise time. The `import weatherbot.config.loader, weatherbot.interactive.lookup` smoke check passes — no fallback to the ValueError-wrap alternative was needed.
- **No `weatherbot/interactive/__init__.py` created** — that barrel is owned by plan 06-03 so 06-01/06-02 run in parallel without a shared-file conflict. Tests import directly from the submodule; `pythonpath=["."]` makes it importable.

## TDD Flow

1. **RED** (`313a64a`): `tests/test_lookup.py` written first — failed with `ModuleNotFoundError` (lookup.py absent), confirming RED.
2. **GREEN** (`b0aad9f`): implemented `lookup.py`; criteria #1 (imperial + metric-primary) and #2 (zero store writes) went green immediately. The D-07 test stayed red pending Task 3 (loader still raised plain `ValueError`).
3. **GREEN** (`06d28e8`): upgraded `resolve_location`; the D-07 typed-error test went green. All 5 lookup tests pass.

## Deviations from Plan

None — plan executed exactly as written. The Task 3 ValueError-wrap fallback was available but unnecessary (no import cycle materialized).

## Verification

- `uv run pytest tests/test_lookup.py -x -q` — 5 passed (criteria #1, #2, D-07).
- `uv run pytest tests/test_config.py -q` — green (resolve_location upgrade backward-compatible, Pitfall 5).
- `uv run python -c "import weatherbot.config.loader, weatherbot.interactive.lookup"` — exits 0 (no import cycle).
- Full suite: `uv run pytest -q` — **203 passed**, no regressions.
- `grep` gates: 0 store imports, 0 `db_path` in lookup.py.
- `uv run ruff check` / `ruff format --check` — clean on all 3 changed files.

## Commits

- `313a64a` test(06-02): add failing lookup-core tests (criteria #1, #2, D-07)
- `b0aad9f` feat(06-02): implement read-only lookup_weather core (D-05/D-06)
- `06d28e8` feat(06-02): resolve_location raises UnknownLocationError (D-07)

## Self-Check: PASSED

- FOUND: weatherbot/interactive/lookup.py
- FOUND: tests/test_lookup.py
- FOUND (modified): weatherbot/config/loader.py
- FOUND commit: 313a64a
- FOUND commit: b0aad9f
- FOUND commit: 06d28e8
