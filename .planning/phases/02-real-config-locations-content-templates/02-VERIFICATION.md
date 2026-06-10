---
phase: 02-real-config-locations-content-templates
verified: 2026-06-10T05:49:45Z
status: gaps_found
score: 4/5 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Each location's optional units override produces the correct (metric-primary) briefing per location — Success Criterion #1 / LOC-02 / CONF-03"
    status: failed
    reason: >-
      Location.units is validated (_units_valid), documented in
      config.example.toml (Weekend: units = "imperial", plus the commented Home
      hint), and tested at the model layer — but no send/check code path ever
      reads it. send_now unconditionally fetches imperial+metric and
      Forecast.from_payloads / placeholders() hardcode imperial-as-primary
      (°F-then-°C, mph-then-m/s) and imperial hint thresholds. A grep for
      `.units` / `location.units` / `loc.units` across weatherbot/ and templates/
      returns ZERO production references outside the validator. A behavioral
      spot-check (a Location with units="metric") still renders "72°F (22°C)".
      The setting is inert; a user who configures metric is silently misled.
    artifacts:
      - path: "weatherbot/cli.py"
        issue: "send_now (lines 106-109) calls fetch_onecall imperial+metric and from_payloads unconditionally; never reads location.units"
      - path: "weatherbot/weather/models.py"
        issue: "_hints uses hardcoded imperial thresholds; temp_display/feels_like_display/wind_display/high_display/low_display all hardcode imperial-primary; from_payloads/placeholders ignore loc.units"
      - path: "config.example.toml"
        issue: "Ships units = \"imperial\" on Weekend (line 38) — advertises a setting that does nothing"
    missing:
      - "Thread location.units into the display choice so a metric location renders metric-primary"
      - "Make _hints thresholds compare against the selected primary unit scale"
      - "OR (if deferred) remove `units` from Location, config.example.toml, and docstrings so no user can set a no-op"
human_verification:
  - test: "Run `weatherbot --check` against a real config.toml with a live OpenWeather One Call key"
    expected: "Exits 0 on a valid+reachable config; exits 1 with the subscription-not-propagated message on a 401/403; delivers no Discord briefing"
    why_human: "Requires a live OpenWeather One Call 3.0 subscription and network; the reachability probe cannot be exercised offline"
  - test: "Run `weatherbot --send-now Home` and `weatherbot --send-now Weekend` against the live API and inspect the delivered Discord messages"
    expected: "Each message shows the correct location, today's high/low/rain, feels-like, any firing hints, and any active severe-weather alert line"
    why_human: "End-to-end delivery, real payload content, and visual correctness of the briefing require a live key and the Discord channel"
---

# Phase 2: Real Config, Locations, Content & Templates — Verification Report

**Phase Goal:** The user can configure two or more independent locations — each with its own name, lat/lon, IANA timezone, and units — receive a fully-featured briefing (with actionable hints and any active severe-weather line), and control the wording through a safe editable template.
**Verified:** 2026-06-10T05:49:45Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ≥2 independent locations in config (no code changes), each with name/lat/lon/IANA tz + **optional per-location units override**, and `--send-now` produces the correct briefing for each | ✗ FAILED | Multi-location + tz works (config.example.toml ships Home/Weekend in distinct IANA zones; resolve_location matches case-insensitively; example_config test loads cleanly). BUT the **units override is inert** — see CR-01 below. The criterion explicitly requires the override to produce the correct briefing; it does not. |
| 2 | City-name → lat/lon resolution happens once at setup time; scheduled sends never geocode | ✓ VERIFIED | `geocode()` lives only in client.py and is called only by `do_geocode` (`--geocode`). `send_now` never imports/calls geocode; it reads `loc.lat`/`loc.lon` directly. cli.py docstrings + LOC-03 wiring confirm. |
| 3 | Briefing includes "feels like" + threshold-driven hints (rain>40% → umbrella) and surfaces active severe-weather alerts, no separate monitoring loop | ✓ VERIFIED | `feels_like` placeholder present; `_hints` fires 5 hardcoded thresholds (rain>40, feels<40, feels>90, wind>25, uvi>=6), collapses to "" when none; `_alert_line` summarizes `alerts[]` passively inside the single One Call fetch — no monitoring loop. (Caveat: WR-01 — null `current` fabricates a false "cold" hint; thresholds are imperial-only, tied to gap #1.) |
| 4 | User edits the template with named placeholders; substitution runs no arbitrary logic; a missing field fails loudly at validation rather than rendering blank | ✓ VERIFIED | `render` does plain regex `{\w+}` substitution against a whitelist — no `str.format`/`eval`/attribute/index access. `validate_template` raises `ValueError` on any non-canonical token and is wired into `send_now` (line 119) and `do_check` (line 208). Spot-check: `validate_template('{bogus_field}')` raised as expected. |
| 5 | `--check` validates config and reports malformed input loudly without sending | ✓ VERIFIED | `do_check` validates config (IANA tz + units at load), template, unique names, per-location resolve, and ONE reachability probe; never calls `channel.send*`; returns 1 on any failure. `--check` argparse path wired in `main`. |

**Score:** 4/5 truths verified.

### CR-01 Adjudication (the contested finding)

**The code review's BLOCKER is CONFIRMED.** Independent evidence:

1. **Source:** `send_now` (cli.py:106-109) calls `fetch_onecall(location, "imperial")` and `fetch_onecall(location, "metric")` with literal unit strings, then `Forecast.from_payloads(location, ...)`. Nowhere is `location.units` read.
2. **Display:** `Forecast._temp_str`, `temp_display`, `feels_like_display`, `wind_display`, `high_display`, `low_display` (models.py:199-226) all hardcode imperial-primary (`°F (°C)`, `mph (m/s)`). `_hints` (models.py:52-71) uses imperial thresholds against `feels_imp`/`wind_imp`.
3. **Grep:** `grep -rnE "\.units|location\.units|loc\.units" weatherbot/ templates/ | grep -v test` returns **zero** matches outside `models.py`'s field declaration + validator.
4. **Behavioral spot-check:** A `Location(units="metric")` rendered `temp = "72°F (22°C)"`, `feels_like = "70°F (21°C)"`, `high = "75°F (24°C)"` — imperial primary, contradicting the configured metric override.

A documented, validated, example-file setting silently does nothing. This violates the project's core contract ("all user-facing settings must be editable" and behave as configured) and fails the units clause of Success Criterion #1, LOC-02, and CONF-03.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `weatherbot/weather/client.py` | One Call 3.0 fetch + geocode | ✓ VERIFIED | `data/3.0/onecall` + `geo/1.0/direct`; explicit timeout; httpx logger pinned WARNING (no key leak) |
| `weatherbot/weather/models.py` | One Call mapping + feels_like/hint/alert | ⚠️ Wired but units-blind | from_payloads/hints/display all present and working — but ignore `loc.units` (gap #1) |
| `weatherbot/config/models.py` | Location.timezone (required IANA) + units (optional) | ⚠️ Validated, not consumed | Both validators present and fire at load; `units` is never read downstream |
| `templates/renderer.py` | validate_template + CANONICAL | ✓ VERIFIED | CANONICAL == placeholders().keys(); wired at send + check boundaries |
| `config.example.toml` | ≥2 locations w/ tz/units | ⚠️ Present | 2 locations in distinct zones; but `units="imperial"` advertises an inert setting (and `avatar_url=""` WR-04) |
| `weatherbot/cli.py` | --check + --geocode handlers | ✓ VERIFIED | Both argparse paths + handlers present and dispatched |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| cli.py:send_now | client.fetch_onecall | 2 calls (imp+met) | ✓ WIRED | Both calls present; persist reuses single forecast (DATA-03) |
| cli.py:--geocode | client.geocode | setup-time only | ✓ WIRED | Only `do_geocode` calls geocode; not on send path |
| cli.py:--check | client.fetch_onecall | one reachability probe | ✓ WIRED | Single probe, 401/403 distinguished, no delivery |
| cli.py / send_now | renderer.validate_template | send-boundary guard | ✓ WIRED | Fires on `--send-now` and `--check` (WR-02: runs after fetch/persist, not before) |
| config.Location | zoneinfo.ZoneInfo | field_validator | ✓ WIRED | Invalid IANA zone fails loud at load |
| config.Location.units | (any consumer) | — | ✗ NOT_WIRED | Validated but never consumed — the gap |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite | `uv run pytest -q` | 91 passed in 1.57s | ✓ PASS |
| Template rejects unknown token | `validate_template('{bogus_field}')` | raised ValueError | ✓ PASS |
| Canonical tokens pass | `validate_template('{temp}{hint}{alert}{feels_like}')` | no error | ✓ PASS |
| units override affects briefing | metric Location → placeholders() | "72°F (22°C)" (imperial) | ✗ FAIL (proves CR-01) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| LOC-01 | 02-03 | Multiple independent locations (≥2) | ✓ SATISFIED | config.example.toml ships Home + Weekend; multi_location test resolves both |
| LOC-02 | 02-03 | name + lat/lon + IANA tz + optional units override (+ schedules) | ✗ BLOCKED | name/lat/lon/tz work; **units override inert** (CR-01). Schedules are out-of-phase. |
| LOC-03 | 02-01/02/04 | Geocode once at setup, never per send | ✓ SATISFIED | geocode only via `--geocode`; send path never geocodes |
| FCST-05 | 02-01/02 | feels-like + threshold hints | ✓ SATISFIED | feels_like placeholder + 5 hints fire; collapse to "" (WR-01 caveat) |
| FCST-06 | 02-01/02 | surfaces active severe-weather alert, no monitoring loop | ✓ SATISFIED | `_alert_line` from `alerts[]` in the single fetch |
| TMPL-01 | 02-03 | edit template with named placeholders | ✓ SATISFIED | 3 templates use {temp}/{feels_like}/{hint}/{alert}; render substitutes |
| TMPL-02 | 02-03 | safe substitution, missing field fails loud | ✓ SATISFIED | regex-only render + validate_template raises on unknown token |
| CONF-01 | 02-03 | all settings in editable config, no code changes | ⚠️ PARTIAL | structure editable, but `units` config knob is a no-op (CR-01) |
| CONF-03 | 02-03/04 | config validated on load, fails loud | ✗ BLOCKED (units clause) | tz/schema/template fail loud correctly; but a validated `units` value silently has no effect — validation that does nothing for one field |
| CONF-05 | 02-04 | `--check` validates without sending | ✓ SATISFIED | do_check validates + probes + delivers nothing |

No ORPHANED requirements: all 10 phase IDs appear in plan frontmatter and are accounted for above.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| weatherbot/config/models.py | 40, 52-57 | Validated config field (`units`) with no consumer | 🛑 Blocker | Inert user-facing setting (CR-01) |
| config.example.toml | 38 | `units = "imperial"` advertises the no-op | 🛑 Blocker | Teaches users a setting that does nothing |
| weatherbot/weather/models.py | 167-170, 190 | Null `current` → `0.0` → false "cold" hint | ⚠️ Warning | WR-01: fabricated hint on degraded payload |
| weatherbot/cli.py | 106-119 | fetch+persist run before validate_template | ⚠️ Warning | WR-02: bad template burns 2 API calls + 2 DB rows before aborting |
| weatherbot/cli.py | 155-160 | do_geocode catches only HTTPStatusError | ⚠️ Warning | WR-03: network error crashes with traceback |
| config.example.toml | 43 | `avatar_url = ""` | ⚠️ Warning | WR-04: empty string ≠ None |
| weatherbot/cli.py | 179 | hardcoded `timezone = "America/Chicago"` in geocode snippet | ⚠️ Warning | WR-05: verbatim paste = wrong tz, validates silently |

No `TODO`/`FIXME`/`XXX`/`TBD` debt markers found in phase-modified production files.

### Human Verification Required

#### 1. Live `--check` reachability probe

**Test:** Run `weatherbot --check` against a real config.toml with a live OpenWeather One Call 3.0 key.
**Expected:** Exit 0 on a valid+reachable config; exit 1 with the subscription-not-propagated message on a 401/403; no Discord briefing delivered.
**Why human:** Needs a live One Call subscription + network; the probe cannot run offline.

#### 2. End-to-end per-location briefing delivery

**Test:** Run `weatherbot --send-now Home` and `weatherbot --send-now Weekend` against the live API; inspect the delivered Discord messages.
**Expected:** Each message shows the correct location, today's high/low/rain, feels-like, firing hints, and any active alert line.
**Why human:** Live key + Discord channel; real payload content and visual correctness can't be verified by grep.

### Gaps Summary

The phase delivers the bulk of its goal: two independent locations with required IANA timezones, a fully One-Call-3.0-sourced briefing with feels-like, five threshold hints, and a passive severe-weather line, plus a safe editable template with fail-loud validation and working `--geocode`/`--check` subcommands. The test suite (91 tests) passes.

The single blocking gap is the **inert per-location `units` override** (CR-01), independently confirmed at source level, by grep, and by a behavioral spot-check. Because Success Criterion #1 *explicitly* requires the units override to "produce the correct briefing for each" location — and a `units = "metric"` location still renders imperial-primary — Success Criterion #1 is not met, and LOC-02 / CONF-03 are blocked on their units clauses. A validated, documented, example-file setting that silently does nothing is a correctness/contract defect.

**Resolution path:** either honor the override (thread `location.units` into display + hint-threshold selection) or, if per-location primary-unit selection is deferred, remove `units` from `Location`, `config.example.toml`, and the docstrings so no user can set a no-op.

The WR-01..WR-05 warnings (false cold-hint on null payload, validation ordering, geocode error handling, example avatar/timezone hints) are non-blocking but should be addressed in the same gap-closure pass since several share the units root cause.

---

_Verified: 2026-06-10T05:49:45Z_
_Verifier: Claude (gsd-verifier)_
