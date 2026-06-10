---
phase: 02-real-config-locations-content-templates
plan: 03
subsystem: config/templating
tags: [iana-timezone, units-override, multi-location, validate-template, canonical-set, d-03, d-09, d-10, d-11]
requires:
  - weatherbot/config/models.py (Location model w/ optional timezone from 02-02)
  - weatherbot/weather/models.py (Forecast.placeholders 12-key map from 02-02)
  - tests/fixtures/onecall_*.json (One Call fixtures from 02-01)
provides:
  - Location.timezone (required, IANA-validated) + Location.units (optional imperial/metric)
  - assert_unique_names(config) casefold duplicate-name guard (re-exported from config)
  - validate_template + CANONICAL 12-key set in templates/renderer.py (D-09/10)
  - validate_template wired at the send_now load boundary (D-11 — --send-now aborts on typo)
  - config.example.toml with 2 locations (timezone/units) + --geocode/--check docs
  - starter templates referencing {feels_like}/{hint}/{alert} (collapse cleanly when empty)
affects:
  - Plan 02-04 (--check reuses assert_unique_names + validate_template + Location validators)
tech-stack:
  added: []
  patterns:
    - "zoneinfo.ZoneInfo in a field_validator owns IANA validity (no hand-rolled zone list)"
    - "validate_template WRAPS render sharing the _TOKEN grammar (D-10 defense-in-depth)"
    - "template validation fires at the load boundary so a typo aborts the send (D-11)"
key-files:
  created: []
  modified:
    - weatherbot/config/models.py
    - weatherbot/config/loader.py
    - weatherbot/config/__init__.py
    - templates/renderer.py
    - templates/briefing-sectioned.txt
    - templates/briefing-multiline.txt
    - templates/briefing-compact.txt
    - config.example.toml
    - weatherbot/cli.py
    - tests/test_config.py
    - tests/test_renderer.py
  deleted:
    - tests/fixtures/current_imperial_clear.json
    - tests/fixtures/current_metric_clear.json
    - tests/fixtures/forecast_imperial_clear.json
    - tests/fixtures/forecast_metric_clear.json
    - tests/fixtures/forecast_imperial_rainy.json
decisions:
  - "D-03 enacted: Location.timezone promoted from optional (02-02) to REQUIRED + zoneinfo-validated; optional units override added (imperial/metric only, A6 — no Kelvin)."
  - "D-09/10 enacted: CANONICAL = the 12 Forecast.placeholders() keys; validate_template wraps render sharing _TOKEN, render left unchanged as defense-in-depth."
  - "D-11 enacted: validate_template fires in send_now before render so --send-now aborts loudly on a non-canonical {token}."
  - "WARNING 2 boundary closed: test_renderer.py's _forecast helper + module LOC repointed to onecall_* fixtures (+timezone); the 5 obsolete 2.5 fixtures (last reachable only here) deleted; unconditional full-suite gate restored green."
metrics:
  duration_min: 7
  completed: "2026-06-10"
  tasks: 2
  files_changed: 16
---

# Phase 2 Plan 03: Real Config — Locations + Template Validation Summary

Makes the configuration "real" and closes the templating-safety gap: `Location` now requires an IANA-validated `timezone` and accepts an optional `imperial`/`metric` `units` override (both fail loud at load), a `config.example.toml` ships ≥2 independent locations, and a new `validate_template`/`CANONICAL` layer wraps the guarded renderer so a typo'd `{token}` aborts the send loudly at every load including `--send-now`. The deferred full-suite gate from Plan 02-02 is restored green by repointing `test_renderer.py` to the One Call fixtures.

## What Was Built

### Task 1 — Location timezone/units validators + unique-name helper + multi-location example (abe7fe3)
- **config/models.py:** `Location.timezone` is now REQUIRED (`str`) with a `@field_validator` that constructs `zoneinfo.ZoneInfo(v)` in a try/except and raises `ValueError("… is not a valid IANA timezone")` on `ZoneInfoNotFoundError`/`ValueError` — the stdlib owns the IANA database (Don't Hand-Roll). Added optional `units: str | None = None` with a `@field_validator` rejecting anything outside `{"imperial", "metric"}` (A6 — `standard`/Kelvin intentionally excluded).
- **config/loader.py:** added `assert_unique_names(config) -> None` that casefolds each `location.name` and raises a clear `ValueError` naming the colliding duplicate (matching `resolve_location`'s message style).
- **config/__init__.py:** re-exported `assert_unique_names` (barrel `from .loader import (...)` + `__all__`).
- **config.example.toml:** `Home` block gained `timezone` (+ commented optional `units`); a second `[[locations]]` "Weekend" block in a different IANA zone (`America/Los_Angeles`) with a `units` override; header comments documenting the `--geocode "City, ST"` and `--check` commands (which land in Plan 04).
- **tests/test_config.py:** existing `Location(...)`/TOML fixtures given a `timezone`; new cases — `location_fields` (timezone+units parse), `units` optional default, `missing_timezone` fails loud, `bad_timezone` raises `ValidationError`, `invalid` units (kelvin/standard) fail loud, `multi_location` load+resolve, `assert_unique_names` distinct/duplicate, and `example_config` (the shipped `config.example.toml` loads cleanly — proves CONF-01).

### Task 2 — validate_template + CANONICAL, send-boundary wiring, new template placeholders (4bbd14a test / 3f782f5 feat)
- **templates/renderer.py:** added `CANONICAL` (the 12-key set = exactly `Forecast.placeholders()` keys, D-09) and `validate_template(template_text, allowed=CANONICAL) -> None` computing `unknown = {tokens} - allowed` and raising a clear `ValueError` listing the offenders + the allowed set. Reuses the EXISTING `_TOKEN` regex so validator and renderer agree on the grammar; `render`/`load_template` left UNCHANGED (D-10 defense-in-depth).
- **starter templates:** `briefing-sectioned.txt` `Now:` line now includes `feels {feels_like}`, with `{hint}` and `{alert}` each on their own trailing line (empty → line collapses); same `{feels_like}`/`{hint}`/`{alert}` added to `briefing-multiline.txt` and `briefing-compact.txt`. The compact template's literal text stays emoji-free (hint/alert emoji come from the model strings, placed on their own trailing lines).
- **weatherbot/cli.py:** `send_now` now loads the template once, calls `validate_template(template_text)` before `render(...)`, so `--send-now` aborts loudly on a non-canonical `{token}` (D-11).
- **tests/test_renderer.py:** `_forecast` helper + module-level `LOC` repointed to the One Call `from_payloads(LOC, onecall_imperial_clear, onecall_metric_clear)` signature (+ `timezone="America/New_York"` on `LOC`, now required); new `validate` cases (non-canonical raises, clean passes, all shipped templates pass), `CANONICAL == placeholders().keys()` equality, new-placeholder substitution, and empty hint/alert collapse. Existing `test_renderer_uses_no_dangerous_substitution` and `test_compact_template_has_no_emoji` retained.
- **deleted:** the 5 obsolete 2.5 fixtures (`current_imperial_clear`, `current_metric_clear`, `forecast_imperial_clear`, `forecast_metric_clear`, `forecast_imperial_rainy`) — reachable only from the old `_forecast` helper, now removed.

## Verification Results

- `uv run pytest tests/test_config.py -x -q` → 18 passed (timezone/units/multi-location/unique-name/example-config).
- `uv run pytest tests/test_renderer.py -x -q` → 12 passed (validate + CANONICAL-equality + new-placeholder + emoji + no-dangerous-substitution).
- **Full-suite gate** `uv run pytest -q` → **80 passed, 6 xfailed** — the deferred unconditional full-suite-green gate from Plan 02-02 is RESTORED. The 6 xfails are the `test_cli.py` `--geocode`/`--check`/bad-template-abort scaffolds (`strict=False`, owned by 02-03/02-04).
- `grep -c "validate_template" weatherbot/cli.py` → 2 (import + call). `grep -c "onecall_" tests/test_renderer.py` → 2; `grep -c "current_imperial_clear\|forecast_imperial_clear" tests/test_renderer.py` → 0. `grep -rn "current_*/forecast_* 2.5 fixtures" tests/` → NONE remaining.
- `grep -c '\[\[locations\]\]' config.example.toml` → 3 (≥2). `grep -c "timezone" config.example.toml` → 4 (≥1).
- CANONICAL = `['alert','conditions','date','feels_like','high','hint','humidity','location','low','rain','temp','wind']` (12 keys, equals `placeholders()`).
- Compact template literal text confirmed emoji-free.
- `uv run ruff check weatherbot/ templates/renderer.py tests/` → All checks passed.

## Deviations from Plan

None — plan executed exactly as written. (The 5 obsolete 2.5-fixture deletions were explicitly mandated by the plan's `<artifacts_this_phase_produces>` and acceptance criteria, not a deviation.)

## Note on CLI xfail scaffolds

The plan's `files_modified` does NOT include `tests/test_cli.py`, so the 6 `strict=False` xfail scaffolds there were left untouched. Two carry "02-03" reasons (`--geocode`, geocode-on-send guard) and one a bad-template-abort reason; the wiring `validate_template` adds to `send_now` is the D-11 send-path validation. Because those xfails are `strict=False`, any that now incidentally pass become XPASS (not a suite failure), and they remain owned/removed by Plan 02-04's CLI work. The send-path template-validation behavior itself is fully covered by this plan's renderer + cli changes and the green full suite.

## Self-Check: PASSED
- FOUND: weatherbot/config/models.py, weatherbot/config/loader.py, templates/renderer.py, config.example.toml, weatherbot/cli.py (all modified)
- FOUND commits: abe7fe3 (Task 1 feat), 8dd0573 (Task 1 test), 4bbd14a (Task 2 test), 3f782f5 (Task 2 feat)
- FOUND deletions: 5 obsolete 2.5 fixtures removed and confirmed unreferenced
