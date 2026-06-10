---
phase: 02-real-config-locations-content-templates
verified: 2026-06-10T17:10:00Z
status: passed
score: 5/5 must-haves verified
human_verification_resolved: "Both live items confirmed via UAT 2026-06-10 (see 02-UAT.md): --check exits 0 on a valid+reachable config with no Discord send; --send-now renders Carlsbad imperial-primary and El Paso metric-primary. Per-location units override works end-to-end."
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 4/5
  gaps_closed:
    - "Each location's optional units override produces the correct (metric-primary) briefing per location — Success Criterion #1 / LOC-02 / CONF-03"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Run `weatherbot --check` against a real config.toml with a live OpenWeather One Call key"
    expected: "Exits 0 on a valid+reachable config; exits 1 with the subscription-not-propagated message on a 401/403; delivers no Discord briefing"
    why_human: "Requires a live OpenWeather One Call 3.0 subscription and network; the reachability probe cannot be exercised offline"
  - test: "Run `weatherbot --send-now Home` (imperial/unset) and `weatherbot --send-now Weekend` (units=\"metric\") against the live API and inspect the delivered Discord messages"
    expected: "Home's message leads with °F/mph (imperial-primary); Weekend's message leads with °C/m/s (metric-primary). Each shows the correct location, today's high/low/rain, feels-like, any firing hints, and any active severe-weather alert line"
    why_human: "End-to-end delivery, real payload content, the per-location units override visible effect, and visual correctness of the briefing require a live key and the Discord channel"
---

# Phase 2: Real Config, Locations, Content & Templates — Verification Report (Re-verification)

**Phase Goal:** The user can configure two or more independent locations — each with its own name, lat/lon, IANA timezone, and units — receive a fully-featured briefing (with actionable hints and any active severe-weather line), and control the wording through a safe editable template.
**Verified:** 2026-06-10T17:10:00Z
**Status:** passed (human verification completed via UAT 2026-06-10 — see 02-UAT.md)
**Re-verification:** Yes — after gap closure (02-05). Previous: gaps_found (4/5). The single blocking gap (inert per-location `units` override, CR-01) is now CLOSED. The two live-only items previously deferred to human verification both PASSED in UAT.

## Re-verification Outcome

The prior verification returned `gaps_found (4/5)` with one BLOCKER: `Location.units` was validated/documented/tested but **inert** — no send path read it, so a `units="metric"` location still rendered imperial-primary (`72°F (22°C)`). Gap-closure plan 02-05 threaded `location.units` end-to-end.

**The gap is genuinely closed in the codebase — confirmed at source level, by grep, and by a behavioral spot-check (not by trusting SUMMARY.md):**

1. **Send path now reads the override:** `weatherbot/cli.py:114` — `primary = location.units or "imperial"` — passed into `Forecast.from_payloads(..., primary=primary)` at line 116. The prior verification's grep for `location.units` outside the validator returned ZERO; it now returns exactly this production consumer.
2. **Display axis exists:** `weatherbot/weather/models.py` — `Forecast.primary` dataclass field (line 140, default `"imperial"`); `from_payloads(..., primary="imperial")` (line 149); `_temp_str`/`temp_display`/`feels_like_display`/`high_display`/`low_display`/`wind_display` all branch on `self.primary == "metric"` (lines 228-259).
3. **Behavioral spot-check (the exact one that previously FAILED):** a `Location(units="metric")` now renders `temp = "22°C (72°F)"`, `wind = "3.6 m/s (8 mph)"`, `feels = "21°C (70°F)"`, `high = "24°C (75°F)"` — metric-primary. An unset/imperial location renders `"72°F (22°C)"` / `"8 mph (3.6 m/s)"` — imperial-primary, byte-identical to pre-override output.
4. **WR-01 folded in and fixed:** null `current.feels_like`/`wind_speed` (both payloads) → `fc.hint == ""` (no fabricated "cold"/"Windy"). Confirmed at runtime.
5. **Dual fetch preserved:** `send_now` still calls `fetch_onecall(location, "imperial")` and `fetch_onecall(location, "metric")` (DATA-03/FCST-04); the override flips display only.
6. **Example teaches a working override:** `config.example.toml:41` ships `units = "metric"` on the Weekend location with a comment explaining the metric-primary effect (was the inert `units = "imperial"`).

## Goal Achievement

### Observable Truths (Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | ≥2 independent locations in config (no code changes), each with name/lat/lon/IANA tz + **optional per-location units override**, and `--send-now` produces the correct briefing for each | ✓ VERIFIED | Multi-location + tz works (config.example.toml ships Home/Weekend in distinct IANA zones; resolve_location matches case-insensitively). **Units override now honored:** `cli.py:114` reads `location.units`, threaded into `from_payloads(primary=...)`; spot-check renders metric location `22°C (72°F)` and imperial/unset `72°F (22°C)`. Closes the prior gap. |
| 2 | City-name → lat/lon resolution happens once at setup time; scheduled sends never geocode | ✓ VERIFIED | `geocode()` lives only in client.py, called only by `do_geocode` (`--geocode`). `send_now` never imports/calls geocode; reads `loc.lat`/`loc.lon` directly. Unchanged from prior PASS. |
| 3 | Briefing includes "feels like" + threshold-driven hints (rain>40% → umbrella) and surfaces active severe-weather alerts, no separate monitoring loop | ✓ VERIFIED | `feels_like` placeholder present; `_hints` fires 5 thresholds (rain>40, feels<40, feels>90, wind>25, uvi>=6); `_alert_line` summarizes `alerts[]` passively in the single One Call fetch. WR-01 now fixed: null feels_like/wind no longer fabricate a hint (`fc.hint == ""`). |
| 4 | User edits the template with named placeholders; substitution runs no arbitrary logic; a missing field fails loud at validation rather than rendering blank | ✓ VERIFIED | `render` does regex `{\w+}` substitution against a whitelist; `validate_template` raises `ValueError` on non-canonical tokens, wired into `send_now` (line 127) and `do_check` (line 216). Unchanged from prior PASS. |
| 5 | `--check` validates config and reports malformed input loudly without sending | ✓ VERIFIED | `do_check` validates config (IANA tz + units at load), template, unique names, per-location resolve, and ONE reachability probe; never calls `send*`; returns 1 on any failure. `--check` argparse path wired in `main`. Unchanged from prior PASS. |

**Score:** 5/5 truths verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `weatherbot/weather/models.py` | One Call mapping + feels_like/hint/alert + **primary-unit axis** | ✓ VERIFIED | `Forecast.primary` field + `from_payloads(primary=)`; all display props honor `self.primary`; `_hints` None-guards (WR-01) |
| `weatherbot/cli.py` | --send-now threads location.units; --check + --geocode handlers | ✓ VERIFIED | `send_now` computes `primary = location.units or "imperial"` (line 114) and threads it (line 116); dual fetch preserved; do_check probe unchanged |
| `weatherbot/config/models.py` | Location.timezone (required IANA) + units (optional, **now consumed**) | ✓ VERIFIED | `units` validator (`{imperial, metric, None}`) fires at load AND the value is now read on the send path |
| `templates/renderer.py` | validate_template + CANONICAL | ✓ VERIFIED | CANONICAL == placeholders().keys(); wired at send + check boundaries |
| `config.example.toml` | ≥2 locations w/ tz/units; **working override example** | ✓ VERIFIED | Home (imperial default) + Weekend (`units = "metric"`, metric-primary, with explanatory comment) |
| `tests/test_models.py`, `tests/test_send_now.py` | metric-primary + WR-01 regression assertions | ✓ VERIFIED | `test_from_payloads_metric_primary_displays`, `test_from_payloads_imperial_primary_is_default`, `test_null_feels_like_no_fabricated_cold_hint`, `test_send_now_metric_location_renders_metric_primary` (asserts `°C` leads, `temp_display == "20°C (68°F)"`) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| cli.py:send_now | client.fetch_onecall | 2 calls (imp+met) | ✓ WIRED | Both calls present; persist reuses single forecast (DATA-03) |
| cli.py:send_now | Forecast.from_payloads | `primary=location.units or "imperial"` | ✓ WIRED | **The closed gap** — line 114→116; previously NOT_WIRED |
| Forecast.placeholders | display properties | `self.primary` selection | ✓ WIRED | All `*_display` props branch on `primary`; placeholders() inherits it |
| cli.py:--geocode | client.geocode | setup-time only | ✓ WIRED | Only `do_geocode` calls geocode; not on send path |
| cli.py:--check | client.fetch_onecall | one reachability probe | ✓ WIRED | Single probe, 401/403 distinguished, no delivery |
| cli.py / send_now | renderer.validate_template | send-boundary guard | ✓ WIRED | Fires on `--send-now` and `--check` |
| config.Location | zoneinfo.ZoneInfo | field_validator | ✓ WIRED | Invalid IANA zone fails loud at load |
| config.Location.units | Forecast.primary | cli.py:114 | ✓ WIRED | Previously NOT_WIRED — now consumed |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Forecast display | `temp_imp/temp_met/...` | One Call 3.0 dual fetch via `fetch_onecall` | Yes (real API payload mapped in `from_payloads`) | ✓ FLOWING |
| Forecast.primary | `self.primary` | `location.units` (pydantic-validated) → cli.py:114 | Yes (config-driven, default imperial) | ✓ FLOWING |
| `{hint}` | `_hints(...)` | raw None-guarded imperial current values + daily[0] | Yes; degraded payload → "" (WR-01) | ✓ FLOWING |
| `{alert}` | `_alert_line(alerts)` | `onecall_imp["alerts"]` | Yes; clear day → "" | ✓ FLOWING (IN-02: imperial-only source, non-blocking) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite | `uv run pytest -q` | 96 passed in 1.72s | ✓ PASS |
| Units-relevant subset | `pytest -k "metric or imperial or feels or cold or wind or units or send_now"` | 8 passed | ✓ PASS |
| **metric Location → metric-primary** (the prior FAIL) | `Location(units="metric")` → placeholders() | `temp="22°C (72°F)"`, `wind="3.6 m/s (8 mph)"` | ✓ PASS (gap closed) |
| imperial/unset → imperial-primary | `Location()` → placeholders() | `temp="72°F (22°C)"`, `wind="8 mph (3.6 m/s)"` | ✓ PASS |
| WR-01: null feels_like → no cold hint | null current → from_payloads().hint | `""` (no "cold"/"Windy") | ✓ PASS |
| send_now reads location.units | `grep "location.units" cli.py` | `cli.py:114` match | ✓ PASS |
| Ruff lint | `uv run ruff check weatherbot/ tests/` | All checks passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| LOC-01 | 02-03 | Multiple independent locations (≥2) | ✓ SATISFIED | config.example.toml ships Home + Weekend; multi_location test resolves both |
| LOC-02 | 02-03/05 | name + lat/lon + IANA tz + optional units override | ✓ SATISFIED | name/lat/lon/tz work; **units override now honored end-to-end** (cli.py:114). Schedules are out-of-phase. |
| LOC-03 | 02-01/02/04 | Geocode once at setup, never per send | ✓ SATISFIED | geocode only via `--geocode`; send path never geocodes |
| FCST-05 | 02-01/02/05 | feels-like + threshold hints | ✓ SATISFIED | feels_like placeholder + 5 hints; WR-01 fixed (no fabricated hint on degraded payload) |
| FCST-06 | 02-01/02 | surfaces active severe-weather alert, no monitoring loop | ✓ SATISFIED | `_alert_line` from `alerts[]` in the single fetch |
| TMPL-01 | 02-03 | edit template with named placeholders | ✓ SATISFIED | templates use {temp}/{feels_like}/{hint}/{alert}; render substitutes |
| TMPL-02 | 02-03 | safe substitution, missing field fails loud | ✓ SATISFIED | regex-only render + validate_template raises on unknown token |
| CONF-01 | 02-03/05 | all settings in editable config, no code changes | ✓ SATISFIED | structure editable; the `units` knob now takes visible effect (no longer a no-op) |
| CONF-03 | 02-03/04/05 | config validated on load, fails loud | ✓ SATISFIED | tz/schema/template/units fail loud; the validated `units` value now has a real downstream effect |
| CONF-05 | 02-04 | `--check` validates without sending | ✓ SATISFIED | do_check validates + probes + delivers nothing |

No ORPHANED requirements: all 10 phase IDs appear in plan frontmatter, in REQUIREMENTS.md (all marked [x]/Complete), and are accounted for above.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| weatherbot/weather/models.py | 228-246 | `primary` selection unvalidated; non-`"metric"` silently → imperial | ⚠️ Warning | 02-05-REVIEW WR-01: contained today (pydantic validates `units` upstream), but the model mis-renders rather than failing loud on a bad value |
| weatherbot/weather/models.py | 189-192 | display `or 0.0` coalesce can pair contradictory units (`0°F (19°C)`) on partial-degrade | ⚠️ Warning | 02-05-REVIEW WR-02: hint guard avoids fabricating a hint, but a partial payload can show a mismatched display pair |
| weatherbot/cli.py | 231 | `--check` probes imperial only; never builds a Forecast, so a units regression escapes `--check` | ⚠️ Warning | 02-05-REVIEW WR-03: regression coverage lives in pytest, not the user-facing check |
| weatherbot/cli.py | 122-127 | fetch+persist run before validate_template | ⚠️ Warning | Prior WR-02: bad template burns API calls + DB rows before aborting (deferred) |
| weatherbot/cli.py | 163-168 | do_geocode catches only HTTPStatusError | ⚠️ Warning | Prior WR-03: network error crashes with traceback (deferred) |
| config.example.toml | 46 | `avatar_url = ""` | ⚠️ Warning | Prior WR-04: empty string ≠ None (deferred) |
| weatherbot/cli.py | 187 | hardcoded `timezone = "America/Chicago"` in geocode snippet | ⚠️ Warning | Prior WR-05: verbatim paste = wrong tz (deferred) |

No `TODO`/`FIXME`/`XXX`/`TBD` debt markers found in phase-modified production files. All warnings are robustness-only and non-blocking; none reintroduces the closed CR-01 gap in the production path (`location.units` is pydantic-validated to `{imperial, metric, None}` before reaching the model).

### Human Verification — COMPLETED (UAT 2026-06-10, see 02-UAT.md)

Both live-only items below were exercised by the user during UAT and **both PASSED** — resolving the `human_needed` status to `passed`.

#### 1. Live `--check` reachability probe — ✅ PASSED

**Test:** Run `weatherbot --check` against a real config.toml with a live OpenWeather One Call 3.0 key.
**Expected:** Exit 0 on a valid+reachable config; exit 1 with the subscription-not-propagated message on a 401/403; no Discord briefing delivered.
**Result:** Exit 0, `config check passed locations=2`, no Discord send — confirmed. (UAT additionally surfaced a malformed-config traceback gap, fixed in-session: `cli.py` `_load_config_reporting`, commit `2437b44`, +4 regression tests.)

#### 2. End-to-end per-location briefing delivery (with units override visible) — ✅ PASSED

**Test:** Run `weatherbot --send-now <imperial-location>` and `weatherbot --send-now <metric-location>` against the live API; inspect the delivered Discord messages.
**Result:** User confirmed Carlsbad (units unset) rendered imperial-primary (°F/mph) and El Paso (`units = "metric"`) rendered metric-primary (°C/m/s) in Discord. The per-location units override works end-to-end.

### Gaps Summary

**No gaps remain.** The single prior blocker — the inert per-location `units` override (CR-01) — is independently confirmed CLOSED at source level (`cli.py:114` reads `location.units`; `models.py` `primary` axis drives all display props), by grep (production consumer now present where there was previously zero), and by the exact behavioral spot-check that previously failed (a metric location now renders `22°C (72°F)` instead of `72°F (22°C)`). Imperial/unset output is byte-identical to before. WR-01 (false cold hint on null payload) is fixed. The suite grew from 91 to 96 tests, all green, with metric-primary regression assertions at both the model and send-now layers — so a regression to inert would fail the suite.

The 02-05-REVIEW raised three new non-blocking robustness warnings (unvalidated `primary` fallback, contradictory display pair on partial-degrade, `--check` not exercising metric) plus the previously-deferred WR-02..WR-05. None blocks the goal; all are candidates for a future hardening pass.

Status is `passed`: all 5/5 automated truths verified, and both live-only behaviors confirmed via UAT 2026-06-10 (see 02-UAT.md). Security review subsequently closed 12/12 threats (see 02-SECURITY.md).

---

_Verified: 2026-06-10T16:20:00Z (automated) · human items confirmed via UAT 2026-06-10T17:05:00Z_
_Verifier: Claude (gsd-verifier) + user UAT_
