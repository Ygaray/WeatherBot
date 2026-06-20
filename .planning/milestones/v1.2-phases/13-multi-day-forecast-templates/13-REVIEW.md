---
phase: 13-multi-day-forecast-templates
reviewed: 2026-06-19T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - weatherbot/weather/models.py
  - weatherbot/weather/multiday.py
  - templates/renderer.py
  - weatherbot/interactive/command.py
  - weatherbot/interactive/commands/forecast.py
  - weatherbot/interactive/lookup.py
  - weatherbot/interactive/cache.py
  - weatherbot/interactive/registry.py
  - weatherbot/interactive/bot.py
  - weatherbot/cli.py
  - weatherbot/config/models.py
  - weatherbot/config/loader.py
  - weatherbot/scheduler/daemon.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-06-19
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed the Phase 13 multi-day forecast surface against the six designated risk
areas: window/roll-forward correctness in `multiday.select_days`, template-injection
safety in `render_forecast`, `parse_forecast_flags` injection safety on untrusted
input, read-only/zero-store-write discipline, the namespaced forecast job-id, and
`fire_forecast_slot` isolation from the briefing spine.

The six headline risk areas are, on the whole, handled correctly and defensibly:

- **Window/roll-forward** — verified by simulation across Mon/Sat (weekday roll-forward),
  Fri/Sun/Mon (weekend partial-window). Dates are matched to `daily[i]` by local-date
  map (no positional day-of-week math), and `add` flags beyond the horizon become
  notices rather than `IndexError`. Correct.
- **Template injection** — `render`/`render_forecast` use a `\w`-only regex substitution
  against an allow-list; never `str.format`/`Formatter`/`eval`/Jinja2. Typo'd tokens are
  rejected fail-loud by `validate_template` at load and stay visible at render. Correct.
- **`parse_forecast_flags`** — only `str.split`/`str.casefold`/slicing; an unknown day
  token raises a fail-loud `ValueError` that both surfaces catch. No interpolation of
  untrusted text. Correct.
- **Read-only discipline** — `forecast.py`, `lookup_forecast`, and `fire_forecast_slot`
  import nothing from `weatherbot.weather.store` and call no claim/write. Correct.
- **Forecast job-id namespace** — the `|fc|` segment cannot collide with a briefing's
  `name|time|days` because `time` is validated `HH:MM` (never `"fc"`). Correct in the
  common case (see WR-04 for a pathological-input caveat).
- **`fire_forecast_slot` isolation** — the whole body is wrapped in a non-propagating
  `try/except` returning `None`; it never claims, never alerts, never gates a briefing.
  Correct.

The findings below are robustness/maintainability defects, not correctness breaks in
the happy path. The most material are imperial/metric `daily[]` index misalignment
(WR-01) and detailed-forecast field-value truncation on Discord (WR-02).

## Warnings

### WR-01: imperial/metric `daily[]` arrays indexed by the same position without a date cross-check

**File:** `weatherbot/interactive/commands/forecast.py:113-118`
**Issue:** `select_days` maps the desired calendar dates to indices using ONLY the
imperial `daily[]` (`daily_imp` is passed to `multiday.select_days`). The render loop
then pulls `day_met = daily_met[i]` using that same index `i`:

```python
day_imp = daily_imp[i] if i < len(daily_imp) else {}
day_met = daily_met[i] if i < len(daily_met) else {}
```

This assumes the metric payload's `daily[]` is the same length AND in the same date
order as the imperial payload. They come from two SEPARATE `fetch_onecall` calls
(`lookup_weather` fetches imperial then metric independently). If the two responses
ever differ in length or day ordering — e.g. one fetch crosses a local-midnight
boundary the other does not, or the API returns a differing horizon — index `i` will
pair the imperial day with the WRONG metric day, silently producing a temperature like
`72°F (3°C)`. There is no date assertion tying `daily_imp[i].dt` to `daily_met[i].dt`.
**Fix:** Cross-check the `dt` (or local date) of `daily_met[i]` against `daily_imp[i]`
before pairing, and fall back to `{}` (which `ForecastDay.from_daily` tolerates) on a
mismatch:
```python
day_imp = daily_imp[i] if i < len(daily_imp) else {}
dt_i = (day_imp or {}).get("dt")
day_met = next((d for d in daily_met if (d or {}).get("dt") == dt_i), {})
```

### WR-02: detailed multi-day forecast can be truncated to Discord's 1024-char field limit

**File:** `weatherbot/interactive/bot.py:122-127` (interaction with `forecast.py` `CommandReply.text`)
**Issue:** `forecast.weekday_forecast`/`weekend_forecast` return a `CommandReply` with the
entire rendered multi-day block in `.text` and empty `.lines`. `render_embed` puts the
whole body into a SINGLE non-inline field whose value is clipped to `_MAX_FIELD_VALUE`
(1024) — the `add_field(...)` call at bot.py:125-127 uses a zero-width-space field name
and `value=_clip(reply.text, _MAX_FIELD_VALUE)`. A detailed line renders to ~120-150 chars
(`📆 {label} — 🌡️ {high} / {low} · {sky} · 🌧️ {rain} · 💨 {wind} · ☀️ UV {uvi} · feels {feels_high} / {feels_low} · 🌅 {sunrise} 🌇 {sunset}`). Five days plus the
header/range_label/notice easily approaches or exceeds 1024 chars, at which point the
operator silently loses the last day(s) of the forecast — the exact data the command
exists to deliver — with only a trailing ellipsis. The wide emoji also count toward the
limit. This is graceful (no crash) but lossy.
**Fix:** For forecast replies, render each day as its OWN embed field (the per-day line as
the field value, the label as the field name), reusing the existing `_MAX_FIELDS`/overflow
machinery in `render_embed`, OR split the body across multiple `<=1024`-char fields. Either
keeps the full forecast visible within Discord's per-field cap.

### WR-03: `render_embed` field-name limit constant reused for the embed TITLE (wrong cap)

**File:** `weatherbot/interactive/bot.py:98-100`
**Issue:** The embed title is clipped with the field-NAME limit:
```python
embed = discord.Embed(title=_clip(reply.title, _MAX_FIELD_NAME), color=BRIEFING_COLOR_INT)
```
`_MAX_FIELD_NAME` (256) is the limit for a field name, not the embed title. Discord's
title limit is 256 as well today, so the value is coincidentally correct, but the
constant is semantically wrong — a future reader adjusting `_MAX_FIELD_NAME` for field
names would unknowingly change the title clip, and the title cap is not documented by
the constant's name. Forecast titles (`"Weekday forecast — {location}"`) are short, so
no current truncation, but the coupling is a latent defect.
**Fix:** Introduce a dedicated `_MAX_TITLE = 256` constant and clip the title against it,
decoupling title and field-name caps.

### WR-04: forecast job-id and briefing job-id share a `|`-delimited namespace vulnerable to `|`-bearing location names

**File:** `weatherbot/scheduler/daemon.py:471-486` and `:560`, `:613`
**Issue:** Both ids interpolate `location.name` directly into a `|`-delimited string:
- briefing: `f"{location.name}|{slot.time}|{slot.days}"`
- forecast: `f"{location.name}|fc|{fc.kind}|{fc.variant}|{fc.time}|{fc.days}"`

The `|fc|` segment correctly prevents a forecast/briefing collision when names are
ordinary (because `slot.time` is validated `HH:MM` and can never be `"fc"`). However,
`Location.name` is free-form user config text with no restriction on `|`. Two distinct
locations whose names contain `|` (e.g. a location literally named
`Home|fc|weekday|detailed|09:00`) could be crafted to collide a briefing id with a
forecast id, or two forecast slots across locations could collide — APScheduler would
then silently overwrite one job via `replace_existing=True`, dropping a scheduled send.
This is low-likelihood (self-hosted, single operator) but it is an unvalidated-input →
silent-job-loss path.
**Fix:** Either forbid `|` in `Location.name` at config-validation time (a `field_validator`
that rejects `|`), or build the job id from the collision-safe `location.id` with a
delimiter that the name cannot contain, or hash the components. Validating `|` out of
`name`/`id` is the cheapest fix and matches the existing fail-loud-at-load posture.

### WR-05: `fire_forecast_slot` swallows ALL exceptions including a misconfigured channel, with no alert

**File:** `weatherbot/scheduler/daemon.py:457-468`
**Issue:** The forecast fire's `except Exception` logs and returns `None` — correct for
isolation from the briefing spine (a forecast must never crash the scheduler). But unlike
`fire_slot`, which records a durable `alert` row on failure, a scheduled forecast that
fails EVERY day (e.g. a persistent channel auth failure, or an `UnknownLocationError`
from a renamed location) produces only a log line and silently never delivers. There is
no operator-visible signal that a configured forecast slot has been dead for days. Given
the project's core reliability constraint ("must retry and then alert rather than silently
miss a briefing"), a silently-dead forecast slot is a weaker-than-spec failure mode for a
scheduled delivery. (It is acceptable that forecasts are off the exactly-once SQLite path;
the gap is the absence of ANY liveness signal, not the lack of claim/catch-up.)
**Fix:** At minimum, distinguish an expected-transient failure from a persistent one and
emit a throttled CRITICAL/alert (mirroring `fire_slot`'s `record_alert` self-first guard)
when a forecast slot fails, so a chronically broken forecast slot is discoverable without
tailing logs. Document explicitly if silent-drop is the accepted v1 behavior.

## Info

### IN-01: dead/redundant `else` branch in `select_days` roll-forward

**File:** `weatherbot/weather/multiday.py:103-110`
**Issue:** `upcoming` is computed at line 103, then the `else` branch (lines 108-110)
recomputes it with the identical comprehension:
```python
upcoming = [delta for delta in base_deltas if delta >= 0]   # 103
if base_tokens and not upcoming:
    base_deltas = [delta + 7 for delta in base_deltas]
    upcoming = base_deltas                                  # 106-107
else:
    upcoming = [delta for delta in base_deltas if delta >= 0]  # 110 — redundant
```
The `else` is dead work — `upcoming` already holds exactly that value. Harmless but
confusing.
**Fix:** Drop the `else` branch entirely; keep only the `if base_tokens and not upcoming`
roll-forward block.

### IN-02: duplicated HH:MM validator and `parsed_time`/`day_of_week` across `Schedule` and `ForecastSchedule`

**File:** `weatherbot/config/models.py:57-86` and `:118-165`
**Issue:** `ForecastSchedule` copies the `_hhmm` field validator, `parsed_time`, and
`day_of_week` verbatim from `Schedule` (the docstrings even say "verbatim"). The duplication
is intentional-by-design (separate models so job ids never collide), but the HH:MM
parsing logic now lives in two places and can drift.
**Fix:** Extract the shared HH:MM validator + `parsed_time`/`day_of_week` into a small mixin
or a module-level helper both models call, keeping the two distinct model TYPES while
sharing one implementation of the time grammar.

### IN-03: `_COMPASS`/`_compass` and `_temp_str` duplicated between `Forecast` and `ForecastDay`

**File:** `weatherbot/weather/models.py:34-44`, `:241-245`, `:395-403`
**Issue:** `ForecastDay._temp_str` is copied "VERBATIM" from `Forecast._temp_str`, and
`_COMPASS` is duplicated from `weather_views._COMPASS` (per the module comment). The
verbatim-copy guarantees byte-identical output today but is a maintenance hazard: a
rounding/format change must be made in three places or output silently diverges between
the daily briefing and the per-day forecast line.
**Fix:** Promote `_temp_str` and the compass helper to a shared module-level function
(e.g. `weatherbot/weather/_display.py`) imported by both dataclasses, so the
"byte-identical" invariant is enforced by construction rather than by comment.

### IN-04: `forecast.py` recomputes `detailed`/`variant` guard already guaranteed by the parser

**File:** `weatherbot/interactive/commands/forecast.py:108-110`
**Issue:** `variant = flags.variant if flags.variant in ("detailed", "compact") else "detailed"`
re-guards a value the `ForecastFlags` parser already constrains to exactly those two
strings (and `ForecastSchedule._variant_valid` constrains the scheduled path). The guard
is harmless defense-in-depth but signals uncertainty about the invariant.
**Fix:** Either trust the upstream validation and drop the re-guard, or add a comment
naming it as deliberate defense-in-depth so a reader does not assume `flags.variant` is
untrusted here.

---

_Reviewed: 2026-06-19_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
