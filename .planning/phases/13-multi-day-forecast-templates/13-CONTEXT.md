# Phase 13: Multi-Day Forecast Templates - Context

**Gathered:** 2026-06-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Add multi-day **weekday forecast (Mon–Fri)** and **weekend forecast (Fri–Sat–Sun)**, each in a **detailed (default)** and **compact** variant, with **additive/subtractive day flags**. Reachable **on demand** (CLI + Discord, via the Phase 12 registry) and **scheduled per-location** with their own toggleable config slots and chosen variant. Rendered from **editable templates** reusing the already-fetched One Call 3.0 `daily[]` array — no extra API call, no writes to the SQLite time series.

Covers: **FCAST-01, FCAST-02, FCAST-03, FCAST-04, FCAST-05, FCAST-06, FCAST-07.**
</domain>

<decisions>
## Implementation Decisions

### Date window (D-01)
- **Remaining days now, roll forward when empty.** A forecast shows the still-upcoming days of its block: weekday run on Wed → Wed–Fri; weekend run on Sat → Sat–Sun. Once a block has no days left (e.g. weekday run on Sat), show **next week's full block**.
- Bounded by One Call availability (today = `daily[0]`, +7 days). Past days within the current week are never shown (not fetchable).

### Detailed vs compact (D-02, FCAST-03)
- **Compact**: per day → day label + high/low + a single sky condition word/icon.
- **Detailed (default)**: per day → high/low, sky condition, rain%, **wind**, **UV max**, **feels-like high/low**, **sunrise/sunset**.
- On demand, **detailed is default**; `--compact` (Discord: `+compact`) selects compact. Scheduled slots name the variant in config.

### Day flags (D-03, FCAST-04)
- Support **multiple flags, both add and subtract**: e.g. `weekday-forecast +sat +sun`, `weekday-forecast -mon +sat`.
- `+day` appends, `-day` drops a default day; final set is **sorted into calendar order and deduped** (adding a day already in range is a no-op).
- Day tokens are the weekday abbreviations (mon..sun). Out-of-window days (beyond the +7 horizon) → a clear notice rather than a silent drop.

### Day labels (D-04)
- **Relative for near days, weekday+date after**: "Today" / "Tomorrow" for the first two days, then "Wed 6/25" (weekday abbrev + M/D) for the rest.

### Scheduling (D-05, FCAST-06)
- Each forecast type gets its **own per-location schedule slots** (time/days/enabled + variant), modeled like the existing `[[locations.schedule]]` daily-briefing slots, fully editable in `config.toml` and picked up by the existing reload/reconcile path.
- Forecast jobs fire through the **same scheduler spine** (a `fire_slot`-style callback) and obey the same exactly-once / DST discipline as briefings.

### Templates (D-06, FCAST-01/02/07)
- Each forecast type + variant is an **editable template file** (like `templates/briefing-*.txt`). Because the project forbids logic in templates, the **per-day line is code-rendered**; the template controls the **header/footer and the per-day line format string** (a small, documented multi-day token set distinct from the daily-briefing `CANONICAL` set). `validate_template` gets a forecast-specific allowed-token set.
- Reuses One Call `daily[]` already fetched by `lookup_weather` — **no new endpoint/call** (FCAST-07).

### Claude's Discretion
- Exact multi-day template token design (per-day sub-template vs format-string), and how the renderer's `CANONICAL` validation is parameterized for the new token set — planner/researcher decides.
- How forecast schedule slots are represented in config models (new `[[locations.forecast]]`-style table vs extending `Schedule` with a `kind`/`variant`) — planner decides; must stay `frozen=True` snapshot-compatible with `ConfigHolder` and reconcilable by stable job id.
- Whether on-demand forecasts share the `ForecastCache` (likely yes — same off-loop, read-only path).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §Forecasts — FCAST-01..07
- `.planning/ROADMAP.md` §"Phase 13" — goal + 5 success criteria

### Existing seams to extend
- `weatherbot/weather/models.py` — `Forecast.from_payloads` reads `daily[0]`; multi-day needs `daily[1..7]` per-day extraction (temp.max/min, weather, pop, uvi, wind, sunrise/sunset, clouds). Likely a new per-day model or a list builder alongside `Forecast`.
- `templates/renderer.py` — `load_template`/`render`/`validate_template` + the `CANONICAL` token set (currently daily-briefing only). Needs a forecast token set + render path.
- `templates/briefing-*.txt` — the editable-template precedent to mirror for forecast templates.
- `weatherbot/interactive/lookup.py` — read-only fetch→render core; forecast lookups extend this (reuse `daily[]` from the same payloads).
- `weatherbot/config/models.py` — `Schedule` / `Location` models (all `frozen=True`); forecast schedule slots added here.
- `weatherbot/scheduler/daemon.py` — `fire_slot`, `_register_jobs`, `_reconcile_jobs`, `_desired_job_ids` (stable-id reconciliation). Forecast jobs register/reconcile through this same machinery.
- Phase 12 command registry (`12-CONTEXT.md`) — the on-demand forecast commands plug into it.

No external specs — requirements fully captured in decisions above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The whole `daily[]` array is already in `raw_onecall_imp/met` on every fetch — multi-day rendering is pure extraction + formatting, zero new API cost.
- Scheduler reconcile-by-stable-id machinery handles add/remove/replace of jobs on reload — forecast slots reuse it as new job kinds.
- Editable-template + fail-loud `validate_template` pattern — forecast templates inherit it.

### Established Patterns
- Imperial-primary-with-metric display (`_temp_str`, `primary` flag) — per-day temps reuse it.
- Exactly-once / DST-safe scheduling and the `ConfigHolder` frozen-snapshot reload — forecast slots must remain compatible.
- Read-only on-demand discipline (no store writes).

### Integration Points
- New forecast job kind(s) in `_register_jobs` / `_desired_job_ids` (stable id must encode location + forecast type + slot + variant so reconcile is churn-free on no-op reloads).
- New forecast command handlers in the Phase 12 registry (CLI subparsers + Discord dispatch), incl. `--compact`/`+compact` and `+day`/`-day` flag parsing.
- Renderer gains a forecast token set; `validate_template` parameterized per template kind.
</code_context>

<specifics>
## Specific Ideas

- "detail should be maximum" — the detailed variant intentionally includes the full per-day field set (wind, UV, feels-like hi/lo, sun times) on top of hi/lo/sky/rain.
- Day-flag examples the user gave: `weekday-forecast +sat` (append Saturday), and by extension `-mon +sat`, `+sat +sun`.
</specifics>

<deferred>
## Deferred Ideas

- Hourly-granularity forecast output — explicitly out of scope (daily granularity only).
- A combined "whole week" single command — not requested; weekday/weekend + day-flags cover it.

None blocking — discussion stayed within phase scope.
</deferred>

---

*Phase: 13-multi-day-forecast-templates*
*Context gathered: 2026-06-18*
