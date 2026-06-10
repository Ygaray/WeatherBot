# Phase 2: Real Config — Locations, Content & Templates - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 2 turns the single-location Phase 1 slice into real, file-driven configuration:
the user defines **two or more independent locations** (each with name, lat/lon, IANA
timezone, and an optional units override), receives a **fully-featured briefing**
(feels-like + actionable hints + any active severe-weather line), and controls the
wording through a **safe editable template** with strict placeholder validation. A
`--check` command validates the whole config (and reachability) without sending.

Requirements covered: LOC-01, LOC-02, LOC-03, FCST-05, FCST-06, TMPL-01, TMPL-02,
CONF-01, CONF-03, CONF-05.

**The headline decision (D-01):** this phase **migrates the data source fully from the
free OpenWeather 2.5 endpoints to One Call 3.0.** This supersedes the "free 2.5 / no
credit card" decision locked in PROJECT.md and the research docs. The user already has
a card on file, so there is no friction, and One Call 3.0 is a functional superset of
the two 2.5 endpoints for this bot (current conditions, ready-made daily high/low/pop,
UV index, IANA timezone string, and — critically — the `alerts[]` array that 2.5 cannot
provide). Same `OPENWEATHER_API_KEY`; only the One Call by Call subscription must be
active on that account.

**Explicitly NOT this phase** (later phases): the scheduler / day-of-week / DST / missed-
send recovery / idempotency (Phase 3), retry-then-alert reliability + heartbeat (Phase 4),
deployment & reboot survival + the startup self-check (Phase 5), weather-pattern analysis
(v2). SMS/Telegram channels remain v2.
</domain>

<decisions>
## Implementation Decisions

### Data source — migrate fully to One Call 3.0 (FCST-06, supersedes Phase 1 stack)
- **D-01:** Replace the two 2.5 calls (`/data/2.5/weather` + `/data/2.5/forecast`) and the
  3-hour **bucket aggregation** with a single **One Call 3.0** fetch (`/data/3.0/onecall`).
  Pull current conditions, `daily[0]` for today's high/low and `pop` (rain chance), `uvi`
  (UV index) and `current.feels_like`, and `alerts[]` for severe weather. This is a real
  rework, not an add-on:
  - **Retire** `weatherbot/weather/aggregate.py` and its tests (`tests/test_aggregate.py`,
    plus the bucket-offset fixtures) — `daily[0]` provides high/low/pop ready-made.
  - **Reshape** the persisted raw payload + normalized fields (DATA-01/02): the stored raw
    JSON is now the One Call 3.0 payload. Keep the same normalized-field shape the renderer
    and store already consume. Preserve the **forecast-vs-actual** analysis axis (Phase 1
    D-10): One Call's `daily`/`hourly` are forecasts keyed by target time — retain enough to
    join later "actuals." Researcher: design the schema migration so v2 analysis still reads
    a clean per-location time series.
  - **Same key, same `.env`** (CONF-02): no new secret; the existing `OPENWEATHER_API_KEY`
    works once the One Call by Call subscription is active (new subs can take time to
    propagate — see `--check` reachability, D-12).
- **D-02:** **Dual-unit display** (imperial-primary + metric, FCST-04) still needs both unit
  systems and One Call 3.0 returns only one `units=` system per call. Planner's discretion:
  either make two 3.0 calls (imperial + metric, mirroring Phase 1's no-drift approach) or
  fetch one system and convert the other in code. Lean toward whichever keeps the call
  count low without introducing conversion drift on displayed values.

### Locations & timezone (LOC-01/02/03)
- **D-03:** `Location` gains **`timezone`** (IANA string, e.g. `America/New_York`) and an
  **optional per-location `units`** override. The config-provided IANA timezone is
  **authoritative** for computing the location's "today" (and for Phase 3 scheduling),
  independent of any value the API returns. One Call 3.0's `timezone` field may be used to
  cross-check/validate but does not replace the configured value. Locations stay a **list**
  (already so since Phase 1 D-06) — Phase 2 just adds ≥2 real entries.
- **D-04:** **Geocoding is a dedicated helper command**: `weatherbot --geocode "Austin, TX"`
  calls OpenWeather's free Geocoding API (`/geo/1.0/direct`, same key) and **prints** the
  resolved lat/lon (and name) for the user to paste into `config.toml`. Config stores **only
  coordinates** — a scheduled send NEVER geocodes (LOC-03 quota protection holds by
  construction). No auto-rewrite of the config file.

### Briefing content — feels-like + hints (FCST-05)
- **D-05:** Add a **`{feels_like}`** placeholder, rendered imperial-primary + metric like
  `{temp}` (e.g. `feels 68°F (20°C)`). It is its own placeholder (not folded into `{temp}`).
- **D-06:** Compute **five code-driven hints** with **hardcoded** (non-config) default
  thresholds:
  | Hint | Trigger (default) | Text (sample) |
  |------|-------------------|---------------|
  | Umbrella | rain chance > 40% | Bring an umbrella ☔ |
  | Cold | feels-like < 40°F | Bundle up, it's cold 🧥 |
  | Heat | feels-like > 90°F | Stay hydrated, it's hot 🥵 |
  | Wind | wind > 25 mph | Windy out there 💨 |
  | Sunscreen | day's max UV (`daily[0].uvi`) ≥ 6 (WHO "High") | Wear sunscreen 🧴 |
  Sunscreen uses the day's **max** UV so it naturally skips days that stay below the
  threshold. Cold/heat use **feels-like**, not raw temp.
- **D-07:** Multiple applicable hints render **one per line** into the single `{hint}`
  placeholder; when none apply, `{hint}` is **empty** and the line collapses cleanly. Exact
  wording/emoji of each hint is Claude's discretion (sensible defaults; user will edit).

### Severe-weather line (FCST-06)
- **D-08:** Surface any active alert via a new **`{alert}`** placeholder, populated from One
  Call 3.0 `alerts[]`, **empty when there is no active alert** (same collapse behavior as
  `{hint}`). Passive only — read from the same briefing fetch, **no separate monitoring
  loop**. If multiple alerts are active, summarize concisely (Claude's discretion;
  e.g. the alert `event` name(s)). Real-time push monitoring is explicitly v2 (ENH-V2-03).

### Templating & validation (TMPL-01/02, CONF-03/05)
- **D-09:** **Canonical placeholder set** for Phase 2 = `{temp}`, `{feels_like}`, `{high}`,
  `{low}`, `{rain}`, `{wind}`, `{humidity}`, `{conditions}`, `{location}`, `{date}`,
  `{hint}`, `{alert}`. (Phase 1's set + `feels_like`, `hint`, `alert`.)
- **D-10:** **TMPL-02 validation wraps `templates/renderer.py:render`, it does not replace
  it** (Phase 1 D-04 seam holds). The guarded substitution stays the rendering engine; a new
  validation layer scans the selected template and **errors on any `{token}` not in the
  canonical set** (catches typos like `{temprature}`). The renderer's "leave unknown token
  visible" remains as defense-in-depth, but validation catches it first.
- **D-11:** Template validation fires at **every config load — including `--send-now`** — so
  a typo'd template **aborts the send loudly** and can never silently render blank at send
  time. (Stronger than Phase 1's lenient runtime behavior.)
- **D-12:** **`--check`** (CONF-05) validates, without delivering a briefing:
  1. **Config schema & types** (CONF-03): TOML parses, required fields present, lat/lon
     numeric, **IANA timezone is a real zone**, units value valid.
  2. **Template placeholders** (D-10): selected template uses only canonical fields.
  3. **Live API reachability**: ONE lightweight One Call 3.0 request confirming the key works
     AND the subscription is active — catches the "key/subscription not yet propagated" case.
     This makes a network call (a weather fetch) but **delivers no briefing**. (A lighter
     precursor to Phase 5's OPS-02 startup self-check — keep it simple here.)
  4. **Locations resolve**: each location well-formed and **names unique**, so
     `--send-now <name>` matches exactly one.

### Claude's Discretion
- Exact hint wording/emoji and the `{alert}` summary phrasing (sensible defaults; user edits).
- Dual-unit fetch strategy for One Call 3.0 (two calls vs fetch-one-convert-other) — D-02.
- One Call 3.0 → normalized-field mapping, the persistence schema migration specifics, and
  module/package layout — defer to research + planner (grounded by canonical refs).
- Rounding/precision of displayed values (carry Phase 1's whole-degree convention).
- Whether `--geocode` accepts a `--limit`/country hint when a city name is ambiguous.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 2: Real Config — Locations, Content & Templates" — goal, mode (mvp), success criteria
- `.planning/REQUIREMENTS.md` — LOC-01/02/03, FCST-05/06, TMPL-01/02, CONF-01/03/05 (and the v2 / out-of-scope boundaries this phase must not cross, incl. ENH-V2-03 real-time alerts)
- `.planning/PROJECT.md` — core value + locked project decisions. **NOTE:** the "free 2.5 / no-credit-card" decision is **superseded** by D-01 (full One Call 3.0 migration); planner/transition should update PROJECT.md's Key Decisions and the research docs accordingly.

### Prior phase context (foundation this phase extends)
- `.planning/phases/01-first-briefing-end-to-end/01-CONTEXT.md` — D-01..14: the `templates/` directory + `{placeholder}` render seam (D-04 stable seam this phase wraps), `Channel.send(text)` contract, dual-unit/imperial-primary display, SQLite store + the four analysis axes (D-10), locations-as-a-list (D-06)

### Research (technical grounding — note the 2.5→3.0 shift)
- `.planning/research/STACK.md` — Python/uv stack, httpx, Jinja2/templating, discord-webhook, pydantic config + `.env` secrets. **Its OpenWeather-2.5/no-card endpoint recommendation is overridden by D-01** — One Call 3.0 is now the source.
- `.planning/research/ARCHITECTURE.md` — scheduler→fetch→render→dispatch boundaries, the `Channel.send(text)` contract, data-layer shape, build order
- `.planning/research/PITFALLS.md` — OpenWeather key-activation/quota gotchas (relevant to the One Call by Call subscription-propagation case D-12 guards), template-formatting pitfalls, timezone/day-boundary edges (now resolved via config IANA tz + `daily[0]`)
- `.planning/research/FEATURES.md` — table-stakes vs anti-features (avoid a full template *engine*; plain-text-first; hints are code-computed, not template logic)

### OpenWeather One Call 3.0 (NEW — research this for the migration)
- Endpoint `GET https://api.openweathermap.org/data/3.0/onecall` — fields used: `current` (incl. `feels_like`, `uvi`), `daily[0]` (high/low/`pop`/`uvi`), `alerts[]`, `timezone`. Subscription: "One Call by Call" (card on file, 1k/day free, set a usage cap). Same `appid` key.
- Geocoding `GET https://api.openweathermap.org/geo/1.0/direct` — for the `--geocode` helper (D-04).

No external ADRs/specs beyond the planning + OpenWeather docs above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `templates/renderer.py` (`render`, `load_template`) — the guarded `{token}` substitution engine. TMPL-02 validation **wraps** this (D-10); do not rewrite it.
- `weatherbot/weather/models.py` (`Forecast`, `placeholders()`) — the normalized model + flat `str→str` placeholder map. Extend `placeholders()` with `feels_like`/`hint`/`alert` (D-05/07/08); rebuild `from_payloads` to read One Call 3.0 instead of the four 2.5 payloads.
- `weatherbot/config/models.py` (`Location`, `Config`) — `Location` is `extra="forbid"`; add `timezone` (required) + optional `units`. `Config` already holds a `locations` list and `template` field.
- `weatherbot/config/loader.py` (`load_config`, `resolve_location`) — `resolve_location` already does case-insensitive name matching; reuse for the `--check` "locations resolve / names unique" check.
- `weatherbot/weather/client.py` — httpx client with secret-safe logging (httpx logger pinned to WARNING so `appid` never leaks). Repoint from 2.5 to One Call 3.0 + add the geocoding call; keep the no-leak logging discipline.
- `weatherbot/weather/store.py` (`persist`) — persistence sink to reshape for the One Call payload (D-01).
- `weatherbot/cli.py` (`main`, `send_now`) — the composition root + argparse. Add `--check` and `--geocode` subcommands; `send_now` keeps its single-fetch→persist→render→deliver shape.

### Established Patterns (from Phase 1 — keep)
- Secrets live ONLY on `Settings` (env/`.env`), never in `config.toml` (CONF-02).
- Fail-loud-at-load via pydantic validation (extends to IANA tz + units + template — D-11/12).
- Single-fetch reuse: the one fetch feeds both persist and render (DATA-03) — preserve with One Call.
- Dual-unit, imperial-primary display in `Forecast` display properties (FCST-04).
- `tests/fixtures/*.json` recorded-payload pattern for unit tests — add One Call 3.0 fixtures (with/without `alerts[]`, varying `uvi`); retire the 2.5 bucket fixtures.

### Integration Points
- `.env` provides `OPENWEATHER_API_KEY` (now also gating the One Call subscription) and the Discord webhook URL.
- `config.toml` / `config.example.toml` — add `timezone` + optional `units` per location, document `--geocode` and `--check`, add ≥2 example locations.
- `data/weatherbot.db` — schema migration for the One Call payload (D-01).
- `templates/*.txt` — the three starter templates may reference the new `{feels_like}`/`{hint}`/`{alert}` placeholders.
</code_context>

<specifics>
## Specific Ideas

- Hint emoji palette the user reacted to: ☔ umbrella, 🧥 cold, 🥵 heat, 💨 wind, 🧴 sunscreen.
- Feels-like reads like `Now: 72°F (22°C), feels 68°F (20°C)` — actual primary, feels-like secondary.
- `--geocode` output format the user liked: `Austin, TX, US -> lat=30.2672  lon=-97.7431`, with a paste-ready snippet.
- The user's weekday-home / weekend-travel-city split is the live driver for ≥2 locations with independent timezones.
</specifics>

<deferred>
## Deferred Ideas

- **Configurable hint thresholds** — user chose hardcoded defaults for v1 (D-06). Exposing thresholds in config is a clean later enhancement (would grow `--check`'s surface). Not in this phase.
- **Real-time / push severe-weather monitoring** — the `{alert}` line here is passive (read from the briefing fetch only). A continuous monitoring loop with dedup/alert-state is v2 (ENH-V2-03), explicitly a separate product from the morning briefing.
- **Auto-resolve + cache geocoding** (config rewrites itself) — considered and rejected in favor of the explicit `--geocode` helper (D-04). Note if manual lookups ever become a pain point.
- **Extra template fields** (sunrise/sunset, today's range) — One Call 3.0 actually returns these now (`sunrise`/`sunset`), but they remain v2 scope (ENH-V2-02). Don't add them to the canonical placeholder set in this phase.
- **Richer `--check` / startup self-check** — the live-reachability check here is intentionally light; the full startup self-check (key-not-active vs genuine auth error distinction) is Phase 5 OPS-02.

</deferred>

---

*Phase: 2-Real Config — Locations, Content & Templates*
*Context gathered: 2026-06-09*
