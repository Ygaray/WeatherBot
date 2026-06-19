---
phase: 14-uv-index-on-demand-daily-briefing
verified: 2026-06-19T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run `uv <loc>` on the live CLI (host yahir-mint, editable install) for a configured location"
    expected: "Exit 0, prints UV summary (Now/Today's max + category, Peak, Crosses/Protect or 'stays below N today') PLUS a compact daytime hourly UV line; unknown location exits 1 with hint; fetch failure exits 3"
    why_human: "Requires a restarted live daemon + real OpenWeather fetch; only confirmable on the running host"
  - test: "Send `!uv <loc>` on Discord against the live bot"
    expected: "Discord embed returns the UV summary + compact hourly line; a raising handler stays isolated (no briefing disruption)"
    why_human: "Requires the live Discord bot connection on the restarted daemon; embed delivery + guard ladder only observable on the live surface"
  - test: "Observe a real daily briefing on the live daemon with a populated hourly[] from OpenWeather"
    expected: "Briefing renders current UV, today's max + WHO category, and the interpolated crossing time (or 'stays below N today'); sunscreen hint fires at the configured [uv] threshold"
    why_human: "Live scheduled-send delivery against real API data on host yahir-mint; only confirmable on a restarted live daemon"
  - test: "Edit [uv] threshold + pre_warn_lead_minutes in the live config.toml and trigger the existing reload"
    expected: "New threshold is picked up without restart (hot-reload); a malformed [uv] table is rejected and the last-good config is retained"
    why_human: "Reload behavior against the live ConfigHolder on the running host; code-level reload path verified but live pickup needs the daemon"
---

# Phase 14: UV Index — On-Demand & Daily Briefing Verification Report

**Phase Goal:** The user gets UV/sunscreen awareness on demand and in the daily briefing — an on-demand `uv <loc>` command plus current UV, today's max forecasted UV, and the predicted local time UV first crosses a configurable sunscreen threshold in the daily briefing — with the threshold and pre-warning lead editable in config without code changes.
**Verified:** 2026-06-19
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User can request current + max UV on demand via `uv <loc>` on CLI and Discord | ✓ VERIFIED (code) | `def uv(result, threshold, *, now)` in `weather_views.py:263`; registry `CommandSpec("uv", "Weather", ..., True)` at `registry.py:60-65` + wired at `:108`; CLI dispatch `cli.py:623-624` and Discord dispatch `bot.py:317-318` both thread `config.uv.threshold`. Reply carries Now/max+category/Peak/Crosses/Protect + compact Hourly line. Live delivery → human. |
| 2 | Daily briefing includes current UV, today's max UV, interpolated crossing time (or "stays below") | ✓ VERIFIED (code) | `Forecast.from_payloads` calls `compute_uv` (`models.py:317`), `_format_uv` builds six display strings; `placeholders()` (`models.py:400-421`) emits `uv_now/uv_max/uv_cross/uv_window/uv_peak/uv_category`; all three briefing templates carry `{uv_*}` lines. Spot-check render confirmed. Live briefing → human. |
| 3 | User sets UV threshold + pre-warn lead in config.toml, editable without code, picked up by reload | ✓ VERIFIED (code) | `UvConfig` frozen `extra="forbid"` (`models.py:381-421`): `threshold: float = 6.0`, `pre_warn_lead_minutes: int = 30`, range validator (0-20) + non-negative-lead validator; `Config.uv = Field(default_factory=UvConfig)` (`:456`) → absent table = defaults, whole-Config reload path picks up edits. Live hot-reload → human. |
| 4 | UV reuses already-fetched One Call data — no additional OpenWeather call | ✓ VERIFIED | `compute_uv` is a pure helper reading the passed-in dict; the `uv` command reads `result.forecast.raw_onecall_imp` (`weather_views.py:284`); briefing reuses the payload already fetched in `from_payloads`. Only `fetch_onecall` calls remain the dual imp+met pair in `lookup.py:117-118`. Regression canary `test_fetch_onecall_keeps_hourly_regression_canary` (`test_client.py:61`) proves the Phase-12 `exclude:"minutely"` widening is intact. |

**Score:** 4/4 truths code-verified (live-daemon delivery routed to human verification per phase context)

### PLAN must_haves (additional detail)

| Truth (from PLAN frontmatter) | Status | Evidence |
|-------------------------------|--------|----------|
| `[uv]` table loads/validates fail-loud/hot-reloads | ✓ VERIFIED | UvConfig validators raise on threshold 25, lead -5, unknown key (spot-check confirmed) |
| Absent `[uv]` table → defaults (threshold 6.0) under extra="forbid" | ✓ VERIFIED | `Config(locations=[]).uv.threshold == 6.0` (spot-check) |
| `compute_uv` pure, frozen `UvSummary`, interactive-layer-free | ✓ VERIFIED | `uv.py` imports only stdlib/dataclasses; `grep "from weatherbot.interactive" uv.py` → 0 |
| Crossing time linearly interpolated to ~minute precision | ✓ VERIFIED | uvcross fixture → crossing `10:20` (non-whole-hour), window_end `15:20` (spot-check); `_first_up_cross` uses `t0 + (t1-t0)*(threshold-u0)/(u1-u0)` |
| Stays-below → `stays_below=True`, crossing/window None | ✓ VERIFIED | Spot-checks A1–A4 all return `stays_below=True` with `None` crossing |
| Time math uses CONFIGURED location IANA tz, not API tz | ✓ VERIFIED | `compute_uv(..., tz=ZoneInfo(loc.timezone))`; `_today_daytime_points` uses passed `tz` only |
| Sunscreen hint fires at configured threshold, not literal 6 | ✓ VERIFIED | `models.py:103` `if uvi_max >= uv_threshold`; `grep "uvi_max >= 6"` → 0 |
| UV tokens lockstep CANONICAL ↔ placeholders | ✓ VERIFIED | `renderer.py:54-59` six tokens in CANONICAL; `placeholders()` emits same six; `UV_TOKENS <= CANONICAL` and `<= placeholders()` asserted in `test_renderer.py:130-137` and `test_models.py:426` |
| Missing/empty hourly[] → UV line collapses, briefing never raises | ✓ VERIFIED | Spot-check E: stripped-hourly payload renders `uv_now='8'`, `uv_cross='stays below 6 today'`, no raise |
| `uv` command read-only, no store import, no second fetch | ✓ VERIFIED | `grep "import store"` → 0 actual imports (only a docstring mention); reads `raw_onecall_imp` |
| Raising uv handler isolated by existing envelope | ✓ VERIFIED | `test_bot.py:434` `test_raising_command_handler_is_isolated` (CMD-16); dispatch sits inside existing non-propagating envelope |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `weatherbot/config/models.py` | UvConfig frozen + Config.uv | ✓ VERIFIED | `class UvConfig` + `default_factory=UvConfig` + 2 validators |
| `weatherbot/weather/uv.py` | compute_uv + UvSummary + uv_category | ✓ VERIFIED | 232 lines; frozen dataclass; interactive-layer-free |
| `tests/fixtures/onecall_imperial_uvcross.json` | crossing fixture w/ hourly[].uvi | ✓ VERIFIED | 15 hourly buckets, crossing interpolates to 10:20 |
| `tests/fixtures/onecall_imperial_uvbelow.json` | stays-below fixture | ✓ VERIFIED | exists, max uvi < 6 |
| `weatherbot/weather/models.py` (briefing) | UV fields + threshold hint + compute_uv | ✓ VERIFIED | 6 `uv_*` fields, `_format_uv`, compute_uv call |
| `templates/renderer.py` | UV tokens in CANONICAL | ✓ VERIFIED | `uv_now`..`uv_category` at `:54-59` |
| `templates/briefing-*.txt` (×3) | UV line | ✓ VERIFIED | all three carry `{uv_*}` bare tokens |
| `weatherbot/interactive/commands/weather_views.py` | uv handler | ✓ VERIFIED | `def uv` at `:263`, summary + hourly line |
| `weatherbot/interactive/registry.py` | uv CommandSpec + wiring | ✓ VERIFIED | spec at `:60-65`, handler at `:108` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `Config` | `UvConfig` | `default_factory=UvConfig` | ✓ WIRED | `models.py:456` |
| `Forecast.from_payloads` | `compute_uv` | threshold + tz threaded | ✓ WIRED | `models.py:317-319` |
| `lookup_weather` | `from_payloads` | `uv_threshold=config.uv.threshold` | ✓ WIRED | `lookup.py:128` |
| `uv` handler | `compute_uv` | over `raw_onecall_imp` | ✓ WIRED | `weather_views.py:291` |
| `cli.py` + `bot.py` | `uv` handler | `config.uv.threshold` dispatch | ✓ WIRED | `cli.py:623-624`, `bot.py:317-318` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| Briefing UV line | `uv_*` placeholders | `compute_uv(onecall_imp.hourly[])` | Yes (fixture render → real strings); degrades to "stays below" on empty | ✓ FLOWING |
| `uv` command reply | `UvSummary` fields | `result.forecast.raw_onecall_imp` (already-fetched) | Yes — no second fetch | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| compute_uv never raises on missing/empty/null hourly | python compute_uv on 4 degraded payloads | all `stays_below=True`, current/max still populate, no raise | ✓ PASS |
| uv_category round-then-band | `uv_category([1.4,2,5.6,6,8,11])` | `['Low','Low','High','High','Very High','Extreme']` | ✓ PASS |
| Config defaults | `Config(locations=[]).uv` | threshold 6.0, lead 30 | ✓ PASS |
| Config fail-loud | UvConfig(threshold=25 / lead=-5 / foo=1) | all raise ValidationError | ✓ PASS |
| Interpolation minute-precision | compute_uv on uvcross fixture | crossing 10:20 (non-whole-hour), window 10:20–15:20, peak 9.6@13:00 | ✓ PASS |
| Briefing spine isolation | from_payloads with hourly stripped | renders uv_now='8', uv_cross='stays below 6 today', no raise | ✓ PASS |
| Full test suite | `uv run pytest` | 509 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| UV-01 | 14-03, 14-04 | On-demand `uv <loc>` current + max UV, CLI + Discord | ✓ SATISFIED | uv handler + registry + dual dispatch; threshold-driven sunscreen hint |
| UV-02 | 14-02, 14-03 | Daily briefing: current/max UV + interpolated crossing time | ✓ SATISFIED | compute_uv math + briefing UV line render + lockstep tokens |
| UV-03 | 14-01 | Configurable UV threshold + pre-warn lead, editable w/o code | ✓ SATISFIED | UvConfig frozen table, validators, default-factory, reload path |

All three declared requirement IDs (UV-01, UV-02, UV-03) are accounted for and SATISFIED at code level. REQUIREMENTS.md maps exactly these three to Phase 14 (line 100-102). No orphaned requirements. Live UI delivery for UV-01/UV-02 routed to human verification.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TBD/FIXME/XXX in any phase-modified file | — | — |

Deferred-items.md lists 2 pre-existing ruff F401 lint warnings in unrelated test files (`test_cache.py`, `test_reload.py`) untouched by this phase — not Phase-14 anti-patterns.

### Human Verification Required

Four live-daemon items (see frontmatter) — all gated on a restarted live daemon on host yahir-mint with real OpenWeather data:

1. **CLI `uv <loc>`** — exit codes + summary + hourly line against real fetch
2. **Discord `!uv <loc>`** — embed delivery + guard ladder + isolation
3. **Live daily briefing UV line** — real hourly[] crossing render + configured-threshold hint
4. **Live `[uv]` hot-reload** — edit threshold/lead in config.toml, confirm pickup; malformed rejected with last-good retained

### Gaps Summary

No code-verifiable gaps. All four ROADMAP success criteria and all PLAN must_haves are satisfied at the code level: UvConfig validates/defaults/fail-loud; compute_uv interpolates to minute precision, is interactive-layer-free, and degrades to `stays_below` (never raises) on missing/empty hourly[] — the briefing-spine isolation guarantee is confirmed by spot-check (briefing renders without raising on stripped hourly). UV tokens are lockstep in CANONICAL ↔ placeholders. The sunscreen hint and command both read the configured threshold (no hardcoded 6). The `uv` command is read-only on both surfaces, adds no extra OpenWeather fetch, and rides the existing registry/guard/isolation machinery. Full suite is 509 passing as expected.

The only open items are live-daemon delivery confirmations (the `uv` command on Discord/CLI and the UV section in a live scheduled briefing on host yahir-mint), which by their nature require a restarted live daemon + real API data — routed to human verification per the phase context.

---

_Verified: 2026-06-19_
_Verifier: Claude (gsd-verifier)_
