---
phase: 13-multi-day-forecast-templates
verified: 2026-06-19T00:00:00Z
status: human_needed
score: 18/18 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Restart the live daemon on host yahir-mint and run !weekday-forecast <loc> and !weekend-forecast <loc> in Discord"
    expected: "A multi-day forecast embed/message is posted to the Discord channel with one line per in-window day (detailed by default)"
    why_human: "Live Discord webhook delivery against the running daemon cannot be confirmed from code/tests; the live process must be restarted to load the new forecast commands"
  - test: "Run weatherbot weekday-forecast <loc> +compact +sat on the host CLI"
    expected: "A compact forecast prints to stdout; +sat appends Saturday (or surfaces a horizon notice if beyond today+7); exit 0; no SQLite write"
    why_human: "End-to-end CLI delivery against the live editable install + real OpenWeather One Call payload is environment-dependent; tests use fixtures/spies"
  - test: "Add a [[locations.forecast]] slot (kind/variant/time/days/enabled) to the live config.toml and let the daemon reload"
    expected: "A namespaced forecast cron job registers at the location tz (id contains |fc|), fires at the configured time, posts the scheduled forecast, and never collides with or delays the briefing job"
    why_human: "Scheduled-slot firing on the live always-on daemon over wall-clock time can only be confirmed on the restarted live process"
  - test: "Edit a forecast template file (e.g. templates/forecast-weekday-detailed.txt) on the host"
    expected: "The file-watch triggers a reload; a typo'd {token} is rejected keep-old; a valid edit takes effect on the next fire"
    why_human: "File-watch + live reload behavior on the running daemon is observable only against the live process"
---

# Phase 13: Multi-Day Forecast Templates Verification Report

**Phase Goal:** The user can get a multi-day weekday (Mon–Fri) and weekend (Fri–Sat–Sun) forecast — in a detailed (default) or compact variant, with additive day flags — on demand from the CLI and Discord bot and on a per-location schedule, all rendered from editable templates reusing the One Call 3.0 `daily` array with no extra API call.
**Verified:** 2026-06-19
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
| -- | ----- | ------ | -------- |
| 1  | Weekday forecast resolves to still-upcoming Mon–Fri, rolling forward when block exhausted | ✓ VERIFIED | `multiday.select_days` lines 83–134: base `_WEEKDAY_DAYS`, signed-delta upcoming filter + whole-block `+7` roll-forward (lines 102–111); `test_forecast_slot_*`/multiday window tests green |
| 2  | Weekend forecast resolves to still-upcoming Fri–Sat–Sun, rolling forward when exhausted | ✓ VERIFIED | `_WEEKEND_DAYS = ("fri","sat","sun")` line 33; same roll-forward path; `test_weekend_forecast_renders_fri_sat_sun` green |
| 3  | +day appends, -day drops; final set deduped + calendar-sorted | ✓ VERIFIED | `select_days` drop-then-add into a `set`, `sorted(desired)` line 125, `sorted(indices)` return line 134; flag tests green |
| 4  | A +day beyond today+7 horizon yields a clear notice, never silent drop/IndexError | ✓ VERIFIED | Date→index map (no positional math) lines 49–58; unmatched date → notice string line 128–130; `test_out_of_window_flag_renders_notice` asserts `"horizon" in reply.text` |
| 5  | Each day exposes compact (hi/lo/sky) + detailed (wind/uvi/feels/sun) fields, imperial-primary byte-identical to briefing | ✓ VERIFIED | Live check: compact keys `{high,label,low,sky}`, detailed = 11 keys, high `76°F (24°C)`; `ForecastDay._temp_str` copied verbatim from `Forecast._temp_str` (models.py 241 & 395) |
| 6  | Each type+variant renders from its own editable .txt + sibling .line.txt | ✓ VERIFIED | 8 files exist; `FORECAST_TEMPLATE_NAMES` maps `(kind,variant)→(txt,line)`; contents are `{token}`-only |
| 7  | Detailed carries full set; compact carries only label/hi/lo/sky | ✓ VERIFIED | `forecast-*-compact.line.txt` = `{label}: {high}/{low} {sky}`; detailed line carries rain/wind/uvi/feels/sunrise/sunset |
| 8  | A typo'd {token} aborts loudly at validate time | ✓ VERIFIED | `render_forecast` calls `validate_template(line_fmt, day_allowed)` + `validate_template(template_text, FORECAST_TOKENS)` before render (renderer 184); `test_validate_rejects_bad_forecast_template` green |
| 9  | Per-day block is code-iterated/joined; no str.format/Jinja2/loop in any template | ✓ VERIFIED | Templates contain only `{token}`; `render_forecast` joins via code; no `str.format`/`eval`/`Formatter` in renderer code (only docstring mentions) |
| 10 | On-demand arg parses into variant/add/drop/location | ✓ VERIFIED | `parse_forecast_flags` + frozen `ForecastFlags` (command.py 118/138); test_flags.py green |
| 11 | +day/-day accept only mon..sun; unknown token fails loud | ✓ VERIFIED | Validates against `_DAYS` imported from `scheduler.days`; raises `ValueError` listing `sorted(_DAYS)` (line 205–207) |
| 12 | Flag parser uses only str ops (no format/eval/exec/shell) | ✓ VERIFIED | No `str.format`/`eval`/`exec`/`subprocess`/`os.system` in command.py code (only docstring contract mentions) |
| 13 | ForecastSchedule is frozen, fail-loud; absent [[locations.forecast]] loads as [] | ✓ VERIFIED | `class ForecastSchedule(BaseModel)` `ConfigDict(extra="forbid", frozen=True)`; `Location.forecast: list[ForecastSchedule] = Field(default_factory=list)` (models.py 88/197); test_config forecast tests green |
| 14 | User runs weekday/weekend-forecast on CLI and Discord for a configured location | ✓ VERIFIED (code) | CLI `--help` lists both subcommands with flag args; both surfaces dispatch via `spec.group == "Forecast"` + `parse_forecast_flags` (cli.py 578, bot.py 221). Live delivery → human |
| 15 | Variant + add/drop flags honored end-to-end | ✓ VERIFIED | `_render` selects `(kind,variant)` template pair + day-token map by `flags.variant`; injects `flags.add/drop` into `select_days`; lookup tests green |
| 16 | On-demand path writes NOTHING to SQLite store (no store import, no db_path) | ✓ VERIFIED | `forecast.py` has no store import (only docstring mentions); `lookup_forecast` takes no db_path; `test_forecast_path_writes_nothing_to_store` + `test_forecast_module_imports_no_store` green |
| 17 | Forecast reuses already-fetched One Call daily[] — no extra API call | ✓ VERIFIED | `lookup_forecast` delegates to `lookup_weather` (dual fetch, no new endpoint); `test_lookup_forecast_no_extra_fetch` asserts unchanged `fetch_onecall` count |
| 18 | Scheduled slots register namespaced cron jobs (no briefing collision), churn-free reconcile, store-free fire, briefing-isolated | ✓ VERIFIED (code) | `_forecast_job_id` returns `...|fc|...` (daemon 486), called from both `_register_jobs` (575) and `_desired_job_ids` (624); `fire_forecast_slot` reuses on-demand render path, no claim/store, try/except→None; collision/churn/variant-edit/isolation tests green. Live firing → human |

**Score:** 18/18 truths verified (code-checkable); 4 live-daemon items routed to human verification.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `weatherbot/weather/multiday.py` | `select_days` window/roll-forward selector | ✓ VERIFIED | Pure dependency-free module; imports `_DAYS`; date→index map; horizon notices |
| `weatherbot/weather/models.py` | `ForecastDay` per-day extraction | ✓ VERIFIED | `from_daily` + `day_tokens` + verbatim `_temp_str`; live key/display check passed |
| `tests/fixtures/onecall_8day_{imperial,metric}.json` | 8-element dated daily[] | ✓ VERIFIED | 8 daily entries each, distinct temps/sky/pop |
| `templates/renderer.py` | `FORECAST_TOKENS`/`_DETAILED`/`_COMPACT` + `render_forecast` | ✓ VERIFIED | 3 token sets + `render_forecast` + `forecast_day_allowed` + `FORECAST_TEMPLATE_NAMES` |
| `templates/forecast-{weekday,weekend}-{detailed,compact}.{txt,.line.txt}` | 8 editable templates | ✓ VERIFIED | All 8 present, `{token}`-only, compact drops rain |
| `weatherbot/interactive/command.py` | `parse_forecast_flags` + `ForecastFlags` | ✓ VERIFIED | Frozen result; `_DAYS`-validated; str-ops-only |
| `weatherbot/config/models.py` | `ForecastSchedule` + `Location.forecast` | ✓ VERIFIED | Frozen fail-loud model; empty-default list |
| `weatherbot/interactive/commands/forecast.py` | read-only weekday/weekend handlers | ✓ VERIFIED | Both handlers; no store import; reuses selector+extractor+renderer |
| `weatherbot/interactive/lookup.py` | `lookup_forecast` reusing dual fetch | ✓ VERIFIED | Delegates to `lookup_weather`; no new endpoint |
| `weatherbot/interactive/registry.py` | weekday/weekend-forecast specs wired | ✓ VERIFIED | Both specs in `_SPECS` + lazy handler wiring |
| `weatherbot/interactive/cache.py` | widened key | ✓ VERIFIED | `lookup(..., suffix=None)` → `(loc_id, suffix)` |
| `weatherbot/scheduler/daemon.py` | `_forecast_job_id` + loops + `fire_forecast_slot` | ✓ VERIFIED | Helper called ≥3×; two enumeration loops; isolated fire |
| `weatherbot/config/loader.py` | forecast templates in validate set | ✓ VERIFIED | Iterates `location.forecast`, validates txt + line against token sets |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| `multiday.py` | `scheduler.days._DAYS` | import | ✓ WIRED (line 29) |
| `forecast.py` | `select_days` + `ForecastDay` + `render_forecast` | selects/extracts/renders | ✓ WIRED |
| `registry._wire_handlers` | `forecast.weekday/weekend_forecast` | lazy import | ✓ WIRED (lines 102–103) |
| cli.py + bot.py dispatch | `parse_forecast_flags` | `spec.group=="Forecast"` special-case | ✓ WIRED (cli 578, bot 221) |
| `daemon._register_jobs` + `_desired_job_ids` | `_forecast_job_id` | single shared helper, both sites | ✓ WIRED (6 refs) |
| `fire_forecast_slot` | `lookup_forecast` + on-demand handler | renders+posts, no store write | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Full test suite | `uv run pytest -q` | 437 passed | ✓ PASS |
| Phase-13 requirement tests | `pytest test_multiday/forecast_render/flags/forecast_lookup/config` | 96 passed | ✓ PASS |
| Scheduler forecast tests | `pytest test_scheduler -k forecast` | 10 passed | ✓ PASS |
| Registry forecast tests | `pytest test_registry -k forecast` | 3 passed | ✓ PASS |
| CLI exposes forecast subcommands | `weatherbot weekday-forecast --help` | lists +day/-day/+compact arg | ✓ PASS |
| ForecastDay token sets (live) | python import | compact 4 keys, detailed 11, `76°F (24°C)` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| ----------- | ----------- | ------ | -------- |
| FCAST-01 weekday forecast from editable template | 01,02,04 | ✓ SATISFIED | Truths 1,6,14; weekday render test |
| FCAST-02 weekend forecast from own editable template | 01,02,04 | ✓ SATISFIED | Truths 2,6,14; weekend render test |
| FCAST-03 detailed default + compact variant | 02,03,04 | ✓ SATISFIED | Truths 7,15; variant template pairs |
| FCAST-04 additive day flags | 01,03,04 | ✓ SATISFIED | Truths 3,4,11; flag + horizon tests |
| FCAST-05 on-demand, read-only no SQLite write | 03,04,05 | ✓ SATISFIED | Truths 16,18; no-store spies green |
| FCAST-06 schedulable per-location, config-only | 03,05 | ✓ SATISFIED | Truths 13,18; ForecastSchedule + cron jobs |
| FCAST-07 reuse already-fetched daily[], no extra call | 01,04,05 | ✓ SATISFIED | Truth 17; no-extra-fetch test |

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| (none in phase-13 modified files) | — | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers found |

Note: `deferred-items.md` records a pre-existing unrelated ruff F401 in `tests/test_cache.py` that predates Plan 13-04 and is not caused by forecast changes. Not a phase-13 gap.

### Human Verification Required

1. **Live Discord on-demand delivery** — restart daemon on yahir-mint, run `!weekday-forecast`/`!weekend-forecast`; expect a posted multi-day forecast. (Webhook delivery not code-verifiable.)
2. **Live CLI on-demand delivery** — `weatherbot weekday-forecast <loc> +compact +sat`; expect compact output + appended Saturday (or horizon notice), exit 0, no DB write.
3. **Scheduled forecast slot firing** — add a `[[locations.forecast]]` slot, reload; expect a `|fc|`-namespaced cron job to fire at the configured time, post, and never delay the briefing.
4. **Forecast template live reload** — edit a forecast template; expect file-watch reload, typo keep-old rejection, valid edit applied on next fire.

### Gaps Summary

No code-verifiable gaps. All 18 observable truths, 13 artifacts, 6 key links, and 7 requirements verified against the codebase; 437/437 tests pass. The phase goal is achieved in code. Status is `human_needed` solely because four delivery behaviors (Discord post, CLI run, scheduled-slot fire, live template reload) can only be confirmed on the restarted live daemon on host yahir-mint, consistent with the phase's live-daemon delivery model.

---

_Verified: 2026-06-19_
_Verifier: Claude (gsd-verifier)_
