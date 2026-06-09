---
phase: 01-first-briefing-end-to-end
plan: 03
subsystem: persistence-and-templating
tags: [sqlite, generated-columns, time-series, raw-json, templating, renderer, guarded-substitution, tdd]
requires:
  - "weatherbot.weather.models.Forecast: from_payloads(...) + four retained raw payloads (raw_current_imp/met, raw_forecast_imp/met)"
  - "weatherbot.weather.models.Forecast.placeholders(): flat str->str D-01 map"
  - "weatherbot.config.models.Location: name/lat/lon"
  - "tests/conftest.py: tmp_db + load_fixture fixtures"
provides:
  - "weatherbot.weather.store: init_db(db_path), persist(db_path, location, forecast)"
  - "weatherbot.weather.store: SQLite schema weather_current + weather_forecast (raw_json + GENERATED VIRTUAL columns + indexes)"
  - "templates/renderer.py: render(template_text, values) -> str (guarded), load_template(name, templates_dir) -> str"
  - "templates/briefing-sectioned.txt (DEFAULT), briefing-multiline.txt, briefing-compact.txt (plain/SMS-safe)"
affects:
  - "Plan 04 (send_now composition): calls persist(db_path, location, forecast) from the same fetch + render(load_template(cfg.template), forecast.placeholders())"
  - "Phase 2 (TMPL-02): wraps render() with strict missing-field validation — extends the stable signature, does not replace it (D-04)"
  - "v2 (ANLY-V2-01/02): reads weather_forecast.target_ts_utc vs weather_current.observed_at_utc for the forecast-vs-actual join — no migration"
tech-stack:
  added: []
  patterns:
    - "SQLite raw-JSON TEXT + GENERATED ALWAYS AS (json_extract(...)) VIRTUAL columns: queryable view always matches stored JSON; v2 columns add with no back-fill (DATA-02)"
    - "Per-bucket forecast rows (RESEARCH Open Question 4): one weather_forecast row per 3-hour bucket per units variant"
    - "Single-fetch dual-consumer persist: writes from Forecast's four retained payloads — zero network calls (DATA-03)"
    - "local_date/target_local_date computed at write time from unix dt + tz offset (indexed equality for 'today's buckets')"
    - "units-tagged rows ('imperial'/'metric') so analysis is unambiguous across the FCST-04 dual fetch"
    - "Secret hygiene: only response payloads stored as raw_json — never the appid-bearing request URL (T-03-01)"
    - "Guarded _Safe(dict) mapping over string.Formatter().vformat: missing key stays visible as {key}, never str.format(**obj)/eval (T-03-02/03)"
key-files:
  created:
    - weatherbot/weather/store.py
    - templates/renderer.py
    - templates/briefing-sectioned.txt
    - templates/briefing-multiline.txt
    - templates/briefing-compact.txt
    - tests/test_store.py
    - tests/test_renderer.py
  modified: []
decisions:
  - "Per-bucket forecast rows (not parent-payload + child rows) — simplest, satisfies D-08/D-09 directly (RESEARCH Open Question 4)"
  - "Generated VIRTUAL columns expose normalized fields from raw_json — the no-migration DATA-02 guarantee comes from storing raw JSON; generated columns are the elegant queryable surface"
  - "persist tags each row with its units variant ('imperial'/'metric'), matching the Plan 02 dual-unit fetch"
  - "Renderer keeps the str-substitution approach (guarded _Safe mapping) over Jinja2 — D-01 wants {placeholder} substitution; the stable render(text, values) signature is what Phase 2 extends (D-04)"
  - "Compact template authored plain (no emoji) as the SMS-safe seam per <specifics>; sectioned/multiline use light emoji"
metrics:
  duration: "~1 session (sequential executor, single pass)"
  completed: "2026-06-09"
  tasks: 2
  files: 7
---

# Phase 1 Plan 3: Persistence & Templating Summary

Built the analysis-ready SQLite store and the guarded plain-text renderer — the two
consumers of the Plan 02 `Forecast`. The store persists one briefing fetch as a
current row + N forecast-bucket rows (both units) from the Forecast's four retained
payloads with zero network calls (DATA-01/02/03), using a raw-JSON + GENERATED-column
schema whose `target_ts_utc` key makes the deferred v2 forecast-vs-actual join
migration-free. The renderer substitutes the flat `placeholders()` map into three
editable `.txt` templates via a guarded `_Safe` mapping — a missing placeholder stays
visible rather than crashing or rendering blank.

## What Was Built

- **Task 1 — SQLite store (TDD RED 642d287 / GREEN 8df3edb, DATA-01/02/03):**
  `weatherbot/weather/store.py` with stdlib `sqlite3`. `init_db(db_path)` runs the exact
  RESEARCH DDL: `weather_current` (id, location_name, lat, lon, fetched_at_utc,
  observed_at_utc, tz_offset_sec, local_date, units, raw_json + GENERATED VIRTUAL
  temp/humidity/wind_speed/conditions) and `weather_forecast` (… target_ts_utc,
  target_local_date, … + GENERATED temp/temp_min/temp_max/pop/humidity/wind_speed/
  conditions), plus all five `CREATE INDEX IF NOT EXISTS` statements — idempotent via
  `IF NOT EXISTS`. `persist(db_path, location, forecast)` reuses the Forecast's four
  retained raw payloads (no fetch — DATA-03), writing one current row per units variant
  and one forecast row per 3-hour bucket per units variant, computing
  `local_date`/`target_local_date` at write time from each unix `dt` + its `timezone`
  offset, and tagging each row with `units`. Only response payloads are stored as
  `raw_json` — never the appid-bearing request URL (T-03-01). Eight tests: schema +
  index creation, idempotent re-init, current+forecast row counts and units, `test_target_ts`
  (non-null `target_ts_utc`/`target_local_date` + queryable generated `temp`/`pop`),
  generated-column ↔ raw-JSON agreement, current-row JSON round-trip, no-network, and
  the secret-hygiene assertion (no `appid`/`api.openweathermap.org` in any stored blob).
- **Task 2 — Templates + guarded renderer (67e06f3, D-01/02/03/04):** `templates/renderer.py`
  with a `render(template_text, values) -> str` over `string.Formatter().vformat` and a
  `_Safe(dict)` whose `__missing__` returns `"{" + key + "}"` (missing key visible, never
  crashes — T-03-03), and `load_template(name, templates_dir=TEMPLATES_DIR) -> str`. Three
  editable `.txt` layouts using the D-01 `{placeholder}` set: `briefing-sectioned.txt`
  (DEFAULT — `☀️ WEATHER — {location}` header + date + grouped current / high-low /
  rain-wind-humidity sections, light emoji), `briefing-multiline.txt` (one labeled field
  per line), and `briefing-compact.txt` (dense one-liner, PLAIN — no emoji — the SMS-safe
  seam). Six tests: each template renders imperial-primary from `placeholders()`, default
  contains `{location}`/`{high}`, missing key stays visible without raising, extra values
  ignored, compact is emoji-free, and the renderer source contains no `eval(`/`.format(**`.

## Verification

- `uv run pytest tests/test_store.py tests/test_renderer.py -x -q` → all green (8 + 6 = 14 new tests).
- `uv run pytest -q` → **40 passed, 1 xfailed** (`test_send_now_posts_briefing` strict-xfail
  remains, as expected — wired in Plan 04).
- `uv run ruff check .` → **All checks passed.**
- `grep -nP '[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}]' templates/briefing-compact.txt` → empty (compact is plain/SMS-safe).
- `grep -nE 'eval\(|\.format\(\*\*' templates/renderer.py` → empty (anti-pattern guard).
- `data/` already gitignored — store's `.db` files never reach git; tests use the `tmp_db` fixture.

## Acceptance Criteria

- [x] `uv run pytest tests/test_store.py tests/test_renderer.py -x` exits 0 including `test_target_ts`.
- [x] A persisted forecast row exposes a queryable generated column (`temp`/`pop`) AND carries `target_ts_utc`.
- [x] The default template renders an imperial-primary plain-text briefing from a Forecast.
- [x] `persist` performs zero network calls (no `httpx` reference in the store module — DATA-03).
- [x] No stored `raw_json` contains `appid` or the request URL (T-03-01).
- [x] Three templates exist; default contains `{location}` and `{high}`; compact is emoji-free.
- [x] `render` with a missing key returns a string containing the literal `{missingkey}` and does not raise.
- [x] `renderer.py` contains no `eval(` and no `.format(**`.
- [x] Full suite green; `test_send_now` xfail still xfailed; ruff clean.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test correctness] Renderer docstring tripped the anti-pattern source guard**
- **Found during:** Task 2, when `test_renderer_uses_no_dangerous_substitution` failed.
- **Issue:** The renderer's module docstring described the anti-pattern it avoids using the
  literal token `str.format(**obj)`. The acceptance-criterion guard asserts the renderer
  source contains no `.format(**` — the prose mention (not executable code) tripped it.
- **Fix:** Reworded the docstring to "never unpacking a real object into `str.format`" so the
  literal `.format(**` token no longer appears anywhere in the source. The guard now passes
  and remains a meaningful source-level check (no executable use of the anti-pattern exists,
  and never did). No behavior change to `render`.
- **Files modified:** `templates/renderer.py`
- **Commit:** 67e06f3 (folded into the Task 2 commit before it was made)

No other deviations — both tasks were built as written.

## Threat Model Coverage

- **T-03-01 (secret leak via persisted payload):** mitigated — `persist` stores ONLY response
  JSON (current payload / single bucket), never the request URL; `test_no_secret_in_stored_json`
  asserts no `appid` and no `api.openweathermap.org` in any stored `raw_json`.
- **T-03-02 (format-string/template injection):** mitigated — substitution is a guarded `_Safe`
  mapping over `string.Formatter().vformat` of a flat str→str whitelist; no `str.format(**obj)`,
  no `eval`; `test_renderer_uses_no_dangerous_substitution` asserts the source is clean.
- **T-03-03 (missing placeholder crashes the render):** mitigated — `_Safe.__missing__` returns
  the visible `{key}`; `test_missing_placeholder_stays_visible_and_does_not_raise` covers it.

No new threat surface introduced beyond the plan's `<threat_model>`.

## Known Stubs

None. The store writes from real retained payloads; the renderer substitutes the real
`placeholders()` map. No placeholder/empty data paths.

## TDD Gate Compliance

- Task 1 (store) followed RED → GREEN: `test(01-03)` 642d287 (failing, module absent) →
  `feat(01-03)` 8df3edb (8 tests green). No refactor commit needed.
- Task 2 (renderer/templates) is `type="auto"` (not `tdd="true"`): templates + renderer + tests
  landed in one `feat(01-03)` commit 67e06f3, suite green.

## Self-Check: PASSED

- Created files verified present on disk: `weatherbot/weather/store.py`, `templates/renderer.py`,
  `templates/briefing-{sectioned,multiline,compact}.txt`, `tests/test_{store,renderer}.py`, and this SUMMARY.
- Per-task commits verified in git log: 642d287 (RED store), 8df3edb (GREEN store), 67e06f3 (templates+renderer).
