# Phase 2: Real Config — Locations, Content & Templates - Research

**Researched:** 2026-06-09
**Domain:** OpenWeather One Call 3.0 migration, multi-location config, IANA timezone validation, template placeholder validation, derived briefing content (hints + alerts)
**Confidence:** HIGH (One Call 3.0 / Geocoding schemas verified against official docs; all stack and code-seam findings grounded in the existing Phase 1 codebase)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 (headline):** Migrate the data source FULLY from the free 2.5 endpoints (`/data/2.5/weather` + `/data/2.5/forecast`) and 3-hour **bucket aggregation** to a single **One Call 3.0** fetch (`/data/3.0/onecall`). Pull `current` (incl. `feels_like`, `uvi`), `daily[0]` (high/low/`pop`/`uvi`), and `alerts[]`. **Retire** `weatherbot/weather/aggregate.py` + `tests/test_aggregate.py` + the bucket-offset fixtures. Reshape the persisted raw payload to the One Call 3.0 JSON while preserving the forecast-vs-actual analysis axis (DATA-02). Same `OPENWEATHER_API_KEY`, same `.env` — only the "One Call by Call" subscription must be active.
- **D-02:** Dual-unit display (imperial-primary + metric, FCST-04) still needs both unit systems; One Call 3.0 returns only ONE `units=` system per call. **Planner's discretion:** two 3.0 calls (imperial + metric) vs one call + in-code conversion. Lean toward low call count without conversion drift.
- **D-03:** `Location` gains **`timezone`** (required IANA string) + optional per-location **`units`** override. The config IANA tz is **authoritative** for "today" / `daily[0]` selection and Phase 3 scheduling; the API `timezone` field may cross-check but does not replace it. Locations stay a **list** (≥2 real entries).
- **D-04:** Geocoding is a dedicated helper command `weatherbot --geocode "Austin, TX"` calling `/geo/1.0/direct` (same key), which **prints** resolved lat/lon for the user to paste. Config stores **only coordinates**. A scheduled send NEVER geocodes (LOC-03). No auto-rewrite of config.
- **D-05:** Add a `{feels_like}` placeholder, rendered imperial-primary + metric like `{temp}`. Its own placeholder, not folded into `{temp}`.
- **D-06:** Five code-driven hints with **hardcoded** default thresholds: Umbrella (rain > 40%), Cold (feels-like < 40°F), Heat (feels-like > 90°F), Wind (wind > 25 mph), Sunscreen (`daily[0].uvi` ≥ 6). Cold/heat use **feels-like**, not raw temp. Sunscreen uses the day's **max** UV.
- **D-07:** Multiple applicable hints render **one per line** into the single `{hint}` placeholder; none apply → `{hint}` empty, line collapses cleanly.
- **D-08:** Surface any active alert via a `{alert}` placeholder from One Call 3.0 `alerts[]`, **empty when no active alert**. Passive only — read from the same briefing fetch, NO separate monitoring loop. Multiple alerts → summarize concisely.
- **D-09:** Canonical placeholder set = `{temp}`, `{feels_like}`, `{high}`, `{low}`, `{rain}`, `{wind}`, `{humidity}`, `{conditions}`, `{location}`, `{date}`, `{hint}`, `{alert}`.
- **D-10:** TMPL-02 validation **wraps** `templates/renderer.py:render`, does not replace it. A new validation layer scans the template and **errors on any `{token}` not in the canonical set**. The renderer's "leave unknown token visible" stays as defense-in-depth.
- **D-11:** Template validation fires at **every config load — including `--send-now`** — so a typo'd template aborts the send loudly.
- **D-12:** `--check` validates without delivering: (1) config schema & types incl. IANA tz is a real zone + units valid; (2) template placeholders canonical; (3) ONE live One Call 3.0 reachability request (catches key/subscription not yet propagated), delivers no briefing; (4) locations resolve + names unique.

### Claude's Discretion

- Exact hint wording/emoji and `{alert}` summary phrasing (sensible defaults; user edits).
- Dual-unit fetch strategy for One Call 3.0 (two calls vs fetch-one-convert-other) — D-02.
- One Call 3.0 → normalized-field mapping, persistence schema migration specifics, module/package layout.
- Rounding/precision of displayed values (carry Phase 1's whole-degree convention).
- Whether `--geocode` accepts a `--limit`/country hint when a city name is ambiguous.

### Deferred Ideas (OUT OF SCOPE)

- Configurable hint thresholds (hardcoded for v1).
- Real-time / push severe-weather monitoring (ENH-V2-03) — `{alert}` here is passive only.
- Auto-resolve + cache geocoding (config rewrites itself) — rejected in favor of explicit `--geocode`.
- Extra template fields (sunrise/sunset, today's range) — One Call 3.0 returns them but they stay v2 (ENH-V2-02). Do NOT add to the canonical set this phase.
- Richer `--check` / startup self-check (auth vs not-active distinction) — Phase 5 OPS-02.
- Scheduler / day-of-week / DST / missed-send / idempotency (Phase 3); retry-then-alert / heartbeat (Phase 4); deployment / reboot survival (Phase 5); SMS/Telegram channels (v2).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LOC-01 | Configure multiple independent locations (≥2) | `Config.locations` is already a list (Phase 1 D-06); add ≥2 example entries. §Standard Stack, §Config Model Migration. No code-structure change — only data + per-location fields. |
| LOC-02 | Each location: name, lat/lon, IANA timezone, optional units override, own schedules | Add `timezone` (required, validated) + optional `units` to `Location` model. §IANA Timezone Validation, §Config Model Migration. (Schedules land in Phase 3 — only the per-location fields needed for content are this phase.) |
| LOC-03 | City-name → lat/lon resolution at config/setup time, not per scheduled call | `--geocode` helper (`/geo/1.0/direct`) prints coords; config stores only coords; send path never geocodes. §Geocoding API. Quota protection holds by construction. |
| FCST-05 | Derived actionable hints — "feels like" + umbrella/coat guidance from thresholds | One Call 3.0 `current.feels_like`, `daily[0].pop`, `current.wind_speed`, `daily[0].uvi` → five code-driven hints. §Derived Content — Hints, §Code Examples. |
| FCST-06 | Surface any active severe-weather alert (passive, no monitoring loop) | One Call 3.0 `alerts[]` (event/start/end/description) → `{alert}` placeholder, read from the same fetch. §Severe-Weather Alerts. |
| TMPL-01 | Editable message template with named placeholders | Existing `templates/*.txt` + guarded `render`. Extend canonical set with `{feels_like}`/`{hint}`/`{alert}`. §Template Placeholder Validation. |
| TMPL-02 | Safe substitution — missing field fails loudly at validation, not silent blanks | New validation layer wraps `render` (D-10); scans `{token}` set against canonical whitelist; fires at every load (D-11). §Template Placeholder Validation, §Code Examples. |
| CONF-01 | All user-facing settings in an editable config file, no code changes | TOML config holds locations/template/units; `config.example.toml` documents new fields + `--geocode`/`--check`. §Config Model Migration. |
| CONF-03 | Config validated on load, fails loudly on malformed input | pydantic `extra="forbid"` + custom validators (IANA tz, units enum). §IANA Timezone Validation, §Config Model Migration. |
| CONF-05 | `--check` command validates config without sending | Four-part check (D-12). §The `--check` Command, §Validation Architecture. |
</phase_requirements>

## Summary

Phase 2 is a **data-source rewrite plus a config/content/validation expansion** on a clean, well-factored Phase 1 codebase. The headline work is migrating from two free 2.5 endpoints + hand-rolled 3-hour bucket aggregation to a single **One Call 3.0** call that returns `current`, `daily[0]`, and `alerts[]` ready-made. This retires `aggregate.py` entirely and reshapes both the `Forecast` model's `from_payloads` constructor and the SQLite store's schema. Everything else (config model, renderer seam, CLI composition root, secret-safe httpx client) extends existing seams rather than replacing them.

**No new external dependencies are required.** The entire phase is built on already-installed `httpx 0.28.1`, `pydantic 2.13.4`/`pydantic-settings 2.14.1`, and Python 3.12 stdlib (`zoneinfo`, `re`, `sqlite3`, `tomllib`). The renderer is a custom regex substituter (not Jinja2), so placeholder validation is a stdlib regex scan. `tenacity` is a Phase 4 concern and is not added here.

The two genuine design decisions for the planner are: **(1) the dual-unit strategy under One Call 3.0** (two calls vs one-call-and-convert — this research recommends **two calls**, mirroring Phase 1's no-drift approach and staying trivially within quota), and **(2) the SQLite schema migration shape** (this research recommends a **new `weather_onecall` table** that stores the full One Call payload as `raw_json` with `json_extract` generated columns and a per-day forecast row layout, preserving the forecast-vs-actual time series without backfilling the old 2.5 tables).

**Primary recommendation:** Repoint `weather/client.py` to One Call 3.0 (+ a geocoding call), rewrite `Forecast.from_payloads` to read `current`/`daily[0]`/`alerts[]`, add a `timezone`+`units` to `Location` with a `zoneinfo` validator, add a template-placeholder validator that wraps `render`, add `--check` and `--geocode` subcommands, and migrate the store to a One Call schema. Use two One Call calls (imperial + metric) per send. No new packages.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| OpenWeather One Call 3.0 fetch | API client (`weather/client.py`) | — | All HTTP/endpoint/secret-handling is isolated here (single-place-to-change seam from Phase 1). |
| Geocoding lookup (`--geocode`) | API client (`weather/client.py`) | CLI (`cli.py`) | Same secret-safe HTTP discipline; invoked only by a setup-time CLI subcommand, never the send path. |
| Forecast normalization (One Call → flat fields) | Domain model (`weather/models.py`) | — | `Forecast` hides the API JSON shape from renderer/store/channel; `from_payloads` is the mapping boundary. |
| Hint computation (umbrella/cold/heat/wind/sunscreen) | Domain model (`weather/models.py`) | — | Code-computed derived fields belong with the normalized model, NOT in the template (anti-feature: template logic). |
| Alert summarization | Domain model (`weather/models.py`) | — | Reads `alerts[]` from the same fetch; produces a flat `{alert}` string. Passive read, no separate tier/loop. |
| Config schema + IANA tz / units validation | Config layer (`config/models.py`, `config/loader.py`) | — | Fail-loud-at-load pydantic validation; the authoritative tz lives here, not in the API response. |
| Template placeholder validation | Template layer (`templates/renderer.py` or a sibling) | Config loader / CLI | Wraps `render` (D-10); fires at every config load incl. `--send-now` (D-11). |
| `--check` orchestration | CLI / composition root (`cli.py`) | All of the above | `--check` composes config validation + template validation + ONE live reachability call + location resolution; it is an orchestration concern. |
| Persistence (One Call payload → SQLite) | Store (`weather/store.py`) | — | Reuses the single fetch (DATA-03); reshapes schema for the One Call payload while preserving the analysis time series. |
| Composition (`--send-now`, `--check`, `--geocode`) | CLI (`cli.py`) | — | The one place fetch/persist/render/deliver/validate meet. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12.3 | Language/runtime | `requires-python = ">=3.12"`; `zoneinfo`, `tomllib` are stdlib. [VERIFIED: `python3 --version` in env] |
| httpx | 0.28.1 | HTTP client for One Call 3.0 + Geocoding | Already the Phase 1 client; explicit timeouts; secret-safe (httpx logger pinned to WARNING). [VERIFIED: `uv pip list`] |
| pydantic | 2.13.4 | Config model validation (`Location`, `Config`) | Already in use; `extra="forbid"` + field validators give fail-loud-at-load. [VERIFIED: `uv pip list`] |
| pydantic-settings | 2.14.1 | Secret loading (`Settings`) | Unchanged this phase — same `OPENWEATHER_API_KEY`. [VERIFIED: `uv pip list`] |
| structlog | 26.1.0 | Structured logging | Outcome-only logging in the CLI; never logs URL/key. [VERIFIED: `uv pip list`] |
| discord-webhook | 1.4.1 | Discord delivery | Unchanged this phase. [VERIFIED: `uv pip list`] |

### Supporting (stdlib — no install)

| Library | Purpose | When to Use |
|---------|---------|-------------|
| `zoneinfo` | Validate that a configured IANA tz string is a real zone; compute location-local "today" for `daily[0]` selection | IANA tz validator + "today" derivation (D-03). `ZoneInfo("Bad/Zone")` raises `ZoneInfoNotFoundError`. [CITED: docs.python.org/3/library/zoneinfo.html] |
| `re` | Scan templates for `{token}` placeholders; substitute (existing `_TOKEN` regex) | Placeholder validation (D-10) reuses the same `\{(\w+)\}` token grammar as the renderer. [VERIFIED: templates/renderer.py] |
| `sqlite3` | Persistence | Store migration for the One Call payload. [VERIFIED: weatherbot/weather/store.py] |
| `tomllib` | Read `config.toml` | Unchanged loader. [VERIFIED: weatherbot/config/loader.py] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Two One Call calls (imperial + metric) | One call + in-code F↔C / mph↔m/s conversion | One call halves quota usage but introduces **conversion drift** on displayed values (e.g. round-trip rounding can disagree with what OpenWeather itself reports). Two calls mirror Phase 1's no-drift approach and cost 2 calls/send — trivially within the 2,000/day allowance. **Recommend two calls** (see §Dual-Unit Strategy). |
| Custom regex renderer + validator | Jinja2 with `StrictUndefined` | Jinja2's `StrictUndefined` raises on unknown vars, which would satisfy TMPL-02 — but it is a **full template engine with logic/loops**, an explicit anti-feature (FEATURES.md, REQUIREMENTS.md "Out of Scope"). The guarded regex renderer is the locked Phase 1 seam (D-04). **Keep the regex approach; add a scan-based validator.** |
| `zoneinfo` (stdlib) | `pytz`, `dateutil.tz` | `zoneinfo` is stdlib since 3.9 and is what APScheduler 3.x uses in Phase 3. No reason to add a dependency. **Use `zoneinfo`.** |

**Installation:**
```bash
# No new packages. Phase 2 uses only already-installed deps + stdlib.
# (Confirm nothing new is needed; do NOT add jinja2 or tenacity here.)
uv sync
```

**Version verification (env, 2026-06-09):** httpx 0.28.1, pydantic 2.13.4, pydantic-settings 2.14.1, structlog 26.1.0, discord-webhook 1.4.1, ruff 0.15.16, pytest 9.0.3 — all already installed and pinned in `pyproject.toml`. [VERIFIED: `uv pip list`]

## Package Legitimacy Audit

> **Not applicable.** Phase 2 installs **no external packages**. The One Call 3.0 migration and all new functionality (config fields, validators, hints, alerts, `--check`, `--geocode`) are built entirely on dependencies already present in `pyproject.toml` (httpx, pydantic, pydantic-settings, structlog, discord-webhook) plus Python 3.12 stdlib (`zoneinfo`, `re`, `sqlite3`, `tomllib`).

| Package | Registry | Disposition |
|---------|----------|-------------|
| *(none — no new installs this phase)* | — | N/A |

**Packages removed due to slopcheck [SLOP] verdict:** none (no candidates).
**Packages flagged as suspicious [SUS]:** none (no candidates).

*slopcheck was not run because no new packages are introduced. The planner does not need a `checkpoint:human-verify` install gate for this phase.*

## Architecture Patterns

### System Architecture Diagram

```
                 config.toml (locations[] + tz + units + template)        .env (OPENWEATHER_API_KEY, DISCORD_WEBHOOK_URL)
                          │                                                        │
                          ▼                                                        ▼
              ┌───────────────────────────┐                          ┌───────────────────────┐
              │  load_config + validators │                          │  load_settings        │
              │  - IANA tz is real zone   │                          │  (secrets only)       │
              │  - units enum valid       │                          └───────────┬───────────┘
              │  - names unique (--check) │                                      │
              └───────────┬───────────────┘                                      │
                          │ typed Config                                          │ api_key
   ┌──────────────────────┼──────────────────────────────────────────────────────┼─────────────┐
   │  CLI composition root (cli.py): --send-now | --check | --geocode             │             │
   └──────────────────────┼──────────────────────────────────────────────────────┼─────────────┘
                          │                                                        │
        template validation (D-10/11)                                  ┌───────────▼───────────┐
        scan {token} ⊆ canonical set                                  │ weather/client.py     │
        FIRES AT EVERY LOAD, ABORTS ON TYPO                           │  One Call 3.0 GET      │
                          │                                            │  (imperial + metric)   │
                          │                                            │  + /geo/1.0/direct     │
                          │                                            └───────────┬───────────┘
                          │                            raw imperial + metric payloads
                          │                                            │
                          ▼                                            ▼
              ┌───────────────────────────────────────────────────────────────────┐
              │  Forecast.from_payloads  (weather/models.py)                       │
              │    current{temp,feels_like,wind,humidity,uvi,weather}              │
              │    daily[0]{temp.max,temp.min,pop,uvi}                             │
              │    alerts[]{event,start,end,description}                           │
              │    ── derive hints (5 thresholds) ─► {hint}                        │
              │    ── summarize active alerts ─────► {alert}                       │
              │    .placeholders() → flat {12-key map}                             │
              └──────────────┬─────────────────────────────────┬──────────────────┘
                             │ (same object — DATA-03)          │
                             ▼                                  ▼
              ┌──────────────────────────┐        ┌──────────────────────────────┐
              │ store.persist            │        │ render(load_template, values)│
              │  One Call schema +       │        │  guarded {token} sub (D-04)  │
              │  json_extract columns    │        └──────────────┬───────────────┘
              │  per-location time series│                       ▼
              └──────────────────────────┘            channel.send_briefing(text, forecast)
```

### Recommended Project Structure (deltas only)

```
weatherbot/
├── weather/
│   ├── client.py        # REPOINT: 2.5 → One Call 3.0; ADD geocode(query, key, limit)
│   ├── models.py        # REWRITE from_payloads (One Call); ADD feels_like/hint/alert + hint/alert derivation
│   ├── store.py         # MIGRATE schema: weather_onecall table (raw + json_extract cols)
│   └── aggregate.py     # RETIRE (delete) — daily[0] replaces bucket aggregation
├── config/
│   ├── models.py        # Location: + timezone (required), + units (optional override)
│   └── loader.py        # ADD IANA tz validator path + unique-name check helper for --check
├── cli.py               # ADD --check and --geocode subcommands; --send-now unchanged in shape
templates/
├── renderer.py          # ADD validate_template(text, allowed) wrapping the {token} scan (D-10)
└── *.txt                # may reference new {feels_like}/{hint}/{alert} (line collapses when empty)
tests/
├── test_aggregate.py    # RETIRE (delete) with aggregate.py
└── fixtures/            # ADD onecall_*.json (with/without alerts[], varying uvi); RETIRE 2.5 bucket fixtures
```

### Pattern 1: Single-fetch reuse, repointed to One Call 3.0 (DATA-03 preserved)

**What:** One fetch round per send feeds BOTH `persist` and `render` — no second network call. Phase 1 did 4 calls (current+forecast × imperial+metric); Phase 2 does **2 calls** (One Call × imperial+metric).
**When to use:** Every `--send-now` and every scheduled send (Phase 3).
**Example:**
```python
# cli.py send_now (shape preserved; payload count drops 4 → 2)
onecall_imp = client.fetch_onecall(location, "imperial")
onecall_met = client.fetch_onecall(location, "metric")
forecast = Forecast.from_payloads(location, onecall_imp, onecall_met)
persist(db_path, location, forecast)   # same object — DATA-03
text = render(load_template(config.template), forecast.placeholders())
```

### Pattern 2: Code-computed derived fields → flat placeholder strings

**What:** Hints and the alert line are computed in Python from normalized fields and exposed as plain `{hint}`/`{alert}` strings. The template never contains logic (FEATURES.md anti-feature).
**When to use:** Any briefing content that depends on thresholds/conditions.
**Example:** see §Code Examples.

### Pattern 3: Validation-wraps-render (D-10), fail-at-load (D-11)

**What:** A scan-based validator checks `{token} ⊆ canonical_set` and raises before any send. The renderer's "unknown token stays visible" remains as defense-in-depth.
**When to use:** Every config load — `--send-now`, `--check`, and (Phase 3) scheduler startup.

### Anti-Patterns to Avoid

- **Template logic / a real template engine (Jinja2 conditionals):** explicitly out of scope. Hints/alerts are computed in code; the template only substitutes flat strings.
- **Geocoding on the send path:** LOC-03 requires resolution at setup time only. `--geocode` prints; the send path reads stored coords. Never call `/geo/1.0/direct` from `send_now`.
- **Trusting the API `timezone` for "today":** the configured IANA tz is authoritative (D-03). Use the API value only to optionally cross-check.
- **Retrying / hand-rolling retry here:** retry-then-alert is Phase 4. `--check`'s reachability probe is a single best-effort call; `raise_for_status()` surfaces failures clearly (as in Phase 1).
- **Logging the request URL or `appid`:** keep the Phase 1 discipline — httpx logger pinned to WARNING; log outcomes only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Today's high/low/rain-chance | 3-hour bucket aggregation (the retired `aggregate.py`) | `daily[0].temp.max` / `daily[0].temp.min` / `daily[0].pop` from One Call 3.0 | This is the whole point of D-01 — One Call gives ready-made daily aggregates; the bucket-offset edge cases (local-midnight boundary, late-day fallback) disappear. [VERIFIED: One Call docs] |
| IANA timezone validity check | A hardcoded list of zone names / string parsing | `zoneinfo.ZoneInfo(name)` in a try/except | The stdlib owns the IANA database; a manual list goes stale and misses aliases. [CITED: docs.python.org/3/library/zoneinfo.html] |
| Template-injection-safe substitution | `str.format(**values)` on a user file | Existing guarded regex `render` (D-04) | `.format` on user templates enables `{0.__class__...}` format-string abuse; the Phase 1 renderer already forbids attribute/index access. [VERIFIED: templates/renderer.py + test_renderer.py] |
| Unit conversion F↔C / mph↔m/s | Hand-rolled conversion math | A second One Call fetch with `units=metric` | Avoids rounding/conversion drift on displayed values; OpenWeather does the conversion authoritatively (D-02 recommendation). [VERIFIED: One Call `units` param] |
| Probability-of-precipitation scaling | Custom rain math | `daily[0].pop` (0–1) × 100, rounded | Same convention the retired aggregator used; One Call exposes `pop` directly. [VERIFIED: One Call docs] |

**Key insight:** Nearly every "compute it yourself" surface from Phase 1 is *removed* by the One Call migration. The remaining custom code is thin: hint thresholds (5 comparisons), an alert-summary string, a tz-validity try/except, and a placeholder-set scan. None of these warrant a library.

## Runtime State Inventory

> This phase migrates the persisted payload shape and retires a module, so a runtime-state pass applies.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `data/weatherbot.db` (gitignored) holds Phase 1 `weather_current` + `weather_forecast` rows keyed to the **2.5** payload shape. The store reshapes to a One Call schema (D-01). | **No data migration of old rows is required.** Recommended approach: add a NEW `weather_onecall` table (`CREATE TABLE IF NOT EXISTS`) and leave the old 2.5 tables in place untouched (they remain queryable historical data; DATA-02 time series is per-table). New writes go to `weather_onecall`. This avoids a destructive backfill and preserves the analysis axis cleanly. **Code edit** (new schema), not a data migration. |
| Live service config | None. No external service stores the config or schema. Discord webhook + OpenWeather key are unchanged (same `.env`). | None — verified: secrets and webhook identity are unchanged this phase. |
| OS-registered state | None. No scheduler / systemd unit / cron exists yet (Phase 5). `--send-now`/`--check`/`--geocode` are manual CLI invocations. | None — verified by absence of any scheduler in the repo. |
| Secrets/env vars | `OPENWEATHER_API_KEY` is **reused unchanged** — only the "One Call by Call" subscription must be active on that account (an OpenWeather-dashboard action, not a code/secret change). `DISCORD_WEBHOOK_URL` unchanged. | None in code. **Out-of-band:** the user must have the One Call subscription active (subscription propagation delay is what `--check` reachability guards — Pitfall below). |
| Build artifacts / installed packages | No new packages; `uv.lock`/`pyproject.toml` dependency set is unchanged. `aggregate.py` + `test_aggregate.py` + 2.5 bucket fixtures are deleted source files (no compiled/installed artifact carries the old name). | Delete the retired files; run `uv sync` (no-op for deps) and `pytest` to confirm the retired tests are gone and nothing imports `aggregate`. |

**The canonical question — after every file is updated, what runtime systems still hold old state?** Only `data/weatherbot.db`'s old 2.5 tables, which are intentionally retained as historical data (new writes go to a new table). Nothing else caches/registers the old shape.

## Common Pitfalls

### Pitfall 1: One Call subscription not yet propagated → 401/403 on a key that "works"
**What goes wrong:** The basic key works for any free endpoint, but `/data/3.0/onecall` returns 401/403 until the "One Call by Call" subscription is active. New subscriptions can take up to a couple of hours to propagate. The bot looks done, then silently never produces a real forecast.
**Why it happens:** A 401 from One Call is indistinguishable from a bad request without reading the FAQ note on activation latency.
**How to avoid:** This is exactly what `--check`'s reachability probe (D-12 step 3) catches. Make the probe's failure message distinguish "key/subscription not active or not yet propagated — wait and retry" from a generic auth error. Keep it light (the richer auth-vs-not-active distinction is Phase 5 OPS-02). [CITED: openweathermap.org/faq; PITFALLS.md Pitfall 2/8]
**Warning signs:** `{high}`/`{low}` render empty; 401 on One Call while a basic call works; brand-new subscription.

### Pitfall 2: Optional weather fields absent on a clear day
**What goes wrong:** `alerts[]` is **absent entirely** when there are no active alerts (not an empty array — the key may be missing). `rain`/`snow` sub-objects are absent when not precipitating. Unconditional access KeyErrors and kills the send.
**Why it happens:** Developers index `payload["alerts"]` or `daily[0]["rain"]` assuming presence.
**How to avoid:** Defensive `.get()` with `or []` / `or {}` everywhere (the Phase 1 model already does this — extend the same discipline to `alerts` and `daily`). `{hint}`/`{alert}` collapse cleanly to empty strings when their source is absent (D-07/08). [CITED: One Call docs note alerts only present when active; PITFALLS.md Pitfall 3]
**Warning signs:** Crash on a clear-sky / no-alert day; tests only cover the rainy/alerting fixture.

### Pitfall 3: Using the API `timezone` instead of the configured one for "today"
**What goes wrong:** One Call returns `timezone`/`timezone_offset`. Using it to pick `daily[0]` or compute the local date diverges from the configured IANA zone (D-03 makes config authoritative), and breaks Phase 3 scheduling consistency.
**Why it happens:** The API value is right there and convenient.
**How to avoid:** Compute "today" from the configured `Location.timezone` via `zoneinfo`. `daily[0]` is "today" in the location's tz per OpenWeather, but the **date string** for `{date}` and any date logic must derive from the configured zone. Optionally assert API `timezone` matches config and warn on mismatch. [Decision: D-03]
**Warning signs:** `{date}` off by a day near midnight; mismatch between configured and API tz unnoticed.

### Pitfall 4: Daily `pop` vs current — rain chance source
**What goes wrong:** Reading rain chance from `current` (there is none) or `hourly[0].pop` instead of `daily[0].pop` gives the wrong "today" rain chance.
**How to avoid:** Rain chance = `round(daily[0].pop * 100)`. The umbrella hint (rain > 40%) reads the same `daily[0].pop`. [VERIFIED: One Call docs — `pop` is 0–1 on daily]

### Pitfall 5: Template typo renders blank at send time
**What goes wrong:** `{temprature}` is not in the canonical set; the Phase 1 renderer leaves it visible (good) but a user might still ship a typo that degrades the message. D-11 strengthens this to **abort the send loudly** at load.
**How to avoid:** Run `validate_template` at every config load (incl. `--send-now`), raising on any non-canonical `{token}`. The renderer's leave-visible behavior stays as a second line of defense. [Decision: D-10/11]
**Warning signs:** A briefing ships with a literal `{token}` in it (means validation was skipped on that path).

### Pitfall 6: Secret leakage via request URL (carryover)
**What goes wrong:** One Call and Geocoding both carry `appid` in the query string; logging the full URL leaks the key.
**How to avoid:** Keep the Phase 1 discipline — `logging.getLogger("httpx").setLevel(logging.WARNING)` and never log URLs/params. Applies to the new geocode call too. [VERIFIED: weatherbot/weather/client.py; PITFALLS.md Pitfall 7]

## Code Examples

### One Call 3.0 client (repoint of `weather/client.py`)
```python
# Source pattern: existing weather/client.py (secret-safe), repointed per One Call 3.0 docs.
# https://openweathermap.org/api/one-call-3
import httpx, logging

ONECALL = "https://api.openweathermap.org/data/3.0/onecall"
GEOCODE = "https://api.openweathermap.org/geo/1.0/direct"
_TIMEOUT = 10.0
logging.getLogger("httpx").setLevel(logging.WARNING)  # never leak appid (Pitfall 6)

def fetch_onecall(lat: float, lon: float, key: str, units: str) -> dict:
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.get(ONECALL, params={
            "lat": lat, "lon": lon, "appid": key,
            "units": units, "lang": "en",
            "exclude": "minutely,hourly",   # trim unused blocks; keep current,daily,alerts
        })
        r.raise_for_status()   # surfaces 401/403 (subscription not active) clearly — Pitfall 1
        return r.json()

def geocode(query: str, key: str, limit: int = 5) -> list[dict]:
    with httpx.Client(timeout=_TIMEOUT) as c:
        r = c.get(GEOCODE, params={"q": query, "limit": limit, "appid": key})
        r.raise_for_status()
        return r.json()   # list of {name, lat, lon, country, state}
```

### Mapping One Call → normalized Forecast (rewrite of `from_payloads`)
```python
# Source: One Call 3.0 schema (openweathermap.org/api/one-call-3) + existing Forecast shape.
cur_i = payload_imp.get("current") or {}
cur_m = payload_met.get("current") or {}
day_i = (payload_imp.get("daily") or [{}])[0]
day_m = (payload_met.get("daily") or [{}])[0]
weather = (cur_i.get("weather") or [{}])
conditions = (weather[0] or {}).get("main", "")

temp_imp      = cur_i.get("temp", 0.0)
feels_imp     = cur_i.get("feels_like", 0.0)
wind_imp      = cur_i.get("wind_speed", 0.0)
humidity      = cur_i.get("humidity") or 0
high_imp      = (day_i.get("temp") or {}).get("max")
low_imp       = (day_i.get("temp") or {}).get("min")
rain_chance   = round((day_i.get("pop") or 0.0) * 100)
uvi_max       = day_i.get("uvi") or 0.0        # day's MAX uv → sunscreen hint
alerts        = payload_imp.get("alerts") or []  # ABSENT when none — Pitfall 2
```

### Five code-driven hints (D-06/07)
```python
# Hardcoded thresholds (deferred: configurable thresholds). Imperial values.
def _hints(rain_chance: int, feels_imp: float, wind_imp: float, uvi_max: float) -> str:
    lines = []
    if rain_chance > 40:   lines.append("Bring an umbrella ☔")
    if feels_imp  < 40:    lines.append("Bundle up, it's cold \U0001F9E5")
    if feels_imp  > 90:    lines.append("Stay hydrated, it's hot \U0001F975")
    if wind_imp   > 25:    lines.append("Windy out there \U0001F4A8")
    if uvi_max    >= 6:    lines.append("Wear sunscreen \U0001F9F4")
    return "\n".join(lines)   # empty string when none apply → {hint} line collapses (D-07)
```

### Alert summary (D-08)
```python
def _alert_line(alerts: list[dict]) -> str:
    if not alerts:
        return ""   # empty → {alert} line collapses (same as {hint})
    events = []
    for a in alerts:
        ev = (a or {}).get("event")
        if ev and ev not in events:
            events.append(ev)
    if not events:
        return ""
    # concise summary (Claude's discretion on phrasing)
    return "⚠️ " + "; ".join(events)
```

### Template placeholder validation (D-10/11)
```python
# templates/renderer.py — wraps render; reuses the SAME token grammar as the renderer.
import re
_TOKEN = re.compile(r"\{(\w+)\}")
CANONICAL = {
    "temp", "feels_like", "high", "low", "rain", "wind", "humidity",
    "conditions", "location", "date", "hint", "alert",
}

def validate_template(template_text: str, allowed: set[str] = CANONICAL) -> None:
    """Raise on any {token} not in the canonical set (D-10). Fires at every load (D-11)."""
    unknown = {m.group(1) for m in _TOKEN.finditer(template_text)} - allowed
    if unknown:
        raise ValueError(
            f"Template uses unknown placeholder(s): {sorted(unknown)}. "
            f"Allowed: {sorted(allowed)}"
        )
```

### IANA timezone + units validation on `Location` (D-03/12)
```python
# weatherbot/config/models.py
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import field_validator

_VALID_UNITS = {"imperial", "metric"}  # "standard" (Kelvin) intentionally excluded for a briefing

class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    lat: float
    lon: float
    timezone: str                          # required IANA zone (D-03)
    units: str | None = None               # optional per-location override (D-03)

    @field_validator("timezone")
    @classmethod
    def _tz_must_be_real(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"{v!r} is not a valid IANA timezone") from e
        return v

    @field_validator("units")
    @classmethod
    def _units_valid(cls, v):
        if v is not None and v not in _VALID_UNITS:
            raise ValueError(f"units must be one of {_VALID_UNITS}, got {v!r}")
        return v
```

### `--geocode` output (user-liked format)
```
$ weatherbot --geocode "Austin, TX"
Austin, TX, US -> lat=30.2672  lon=-97.7431
# paste into config.toml:
#   [[locations]]
#   name = "Austin"
#   lat = 30.2672
#   lon = -97.7431
#   timezone = "America/Chicago"
```

## State of the Art

| Old Approach (Phase 1) | Current Approach (Phase 2) | When Changed | Impact |
|------------------------|----------------------------|--------------|--------|
| Free 2.5 `weather` + `forecast`, 4 calls/send | One Call 3.0, 2 calls/send (imperial+metric) | D-01 | Ready-made daily aggregates; alerts available; requires One Call by Call subscription |
| 3-hour bucket aggregation (`aggregate.py`) | `daily[0]` direct fields | D-01 | Module retired; local-midnight/late-day edge cases gone |
| `Location{name,lat,lon}` | `+timezone (required), +units (optional)` | D-03 | Authoritative per-location tz; enables Phase 3 scheduling |
| Renderer leaves unknown tokens visible | Validation **aborts** on non-canonical tokens at load | D-10/11 | Typos fail loudly, never ship blank |
| 2.5 payload in `weather_current`/`weather_forecast` | One Call payload in a new `weather_onecall` table | D-01 | New table; old tables retained as history (no destructive backfill) |

**Deprecated/outdated (do NOT use):**
- One Call 2.5 (`/data/2.5/onecall`) — deprecated/retired. Use 3.0. [CITED: openweathermap.org/api/one-call-transfer]
- The "free 2.5 / no credit card" default recommendation in CLAUDE.md and ARCHITECTURE.md/STACK.md — **superseded by D-01**. Transition step should update PROJECT.md Key Decisions + research docs.
- `aggregate.py` + `test_aggregate.py` + 2.5 bucket-offset fixtures — retire.

## Project Constraints (from CLAUDE.md)

- **Stack:** Python 3.12+, `uv`, `httpx`, `pydantic`/`pydantic-settings`, `structlog`, `discord-webhook`. (`tenacity` is Phase 4; `Jinja2` not used — custom guarded renderer.)
- **Secrets:** `OPENWEATHER_API_KEY` + `DISCORD_WEBHOOK_URL` from `.env` only (CONF-02); never in `config.toml`, never committed, never logged (the webhook URL is a credential).
- **Config:** All user-facing settings editable without code changes (CONF-01); TOML preferred (stdlib `tomllib`); fail-loud at load.
- **OpenWeather:** API key as `appid` query param; pass `units` explicitly; treat payload shape as untrusted (defensive `.get()`); city-name `q=` lookups only at setup (`--geocode`), never on the send path.
- **GSD enforcement:** all file changes go through a GSD workflow command (this phase is `/gsd-execute-phase`).
- **NOTE — superseded:** CLAUDE.md's "free 2.5 endpoints / One Call 3.0 NOT the default" guidance is overridden by D-01 for this project going forward.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | One Call by Call default daily allowance is ~2,000 calls/day (CONTEXT.md cited 1,000); 2 calls/send is trivially within either. | §Summary, §Dual-Unit | LOW — quota headroom is enormous either way; exact number only matters if the user sets a dashboard cap. Verify on the OpenWeather pricing dashboard. |
| A2 | Recommended dual-unit strategy = TWO One Call calls (imperial + metric). | §Standard Stack, Pattern 1 | LOW — D-02 leaves this to the planner; two calls is the lower-risk default (no drift). Planner may choose one-call-convert if they accept conversion drift. |
| A3 | Recommended store migration = new `weather_onecall` table, old 2.5 tables retained untouched. | §Runtime State Inventory | MEDIUM — planner's discretion per D-01. Alternative (single unified table) is viable but riskier (backfill). This approach is the lowest-risk and preserves DATA-02. |
| A4 | `daily[0]` corresponds to the location's "today"; the configured IANA tz is used for the `{date}` string and any date logic. | Pitfall 3 | MEDIUM — confirm `daily[0]` is current-day (One Call docs say `daily` starts at the current day). Near a day boundary, cross-check against configured tz. |
| A5 | `alerts[]` may be absent (key missing) rather than `[]` when no alerts. | Pitfall 2 | LOW — defensive `or []` handles both; only affects test-fixture design (include a no-`alerts`-key fixture). |
| A6 | `"standard"` (Kelvin) units excluded from the allowed config enum (briefing is imperial/metric only). | §Code Examples | LOW — matches FCST-04; if the user ever wants Kelvin it's a one-line enum change. |

## Open Questions (RESOLVED)

1. **RESOLVED: Dual-unit strategy (D-02) — planner decision.**
   - What we know: One Call returns one unit system per call; two calls = no drift but 2× calls; one call + convert = 1 call but rounding drift.
   - Recommendation: **two calls** (matches Phase 1, trivially within quota). Documented as A2.

2. **RESOLVED: Store schema migration shape (D-01) — planner decision.**
   - What we know: old rows are 2.5-shaped; analysis axis must stay clean per-location.
   - Recommendation: **new `weather_onecall` table, leave old tables as history** (A3). Design generated columns for `current.temp/feels_like/humidity/wind_speed/uvi`, `daily[0].temp.max/min/pop/uvi`, and `target_local_date` from the configured tz so the forecast-vs-actual join needs no migration.

3. **RESOLVED: `--geocode` ambiguity handling (Claude's discretion).**
   - What we know: `/geo/1.0/direct` accepts `limit` (max 5); same city name in multiple countries is the ambiguity case.
   - Recommendation: default `limit=5`, print all matches with `name, state, country -> lat/lon` so the user picks. Optionally accept a trailing country/state in the query (`"London, GB"`). Low risk either way.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.12.3 | — |
| uv | dependency mgmt | ✓ | 0.11.19 | — |
| httpx | One Call + geocode | ✓ | 0.28.1 | — |
| pydantic / pydantic-settings | config validation | ✓ | 2.13.4 / 2.14.1 | — |
| structlog | logging | ✓ | 26.1.0 | — |
| discord-webhook | delivery | ✓ | 1.4.1 | — |
| pytest / ruff | dev | ✓ | 9.0.3 / 0.15.16 | — |
| `zoneinfo` (stdlib) | IANA tz validation | ✓ | 3.12 stdlib | — |
| OpenWeather One Call by Call subscription | live `/data/3.0/onecall` | ✗ (not verifiable from this env) | — | `--check` reachability probe surfaces a not-active/not-propagated key clearly (Pitfall 1). Unit tests run fully offline against recorded fixtures + mocked httpx — no live key needed for the build. |

**Missing dependencies with no fallback:** none for the build/test surface (all unit-testable offline).
**Missing dependencies with fallback:** live One Call access depends on the user's subscription being active; `--check` is the in-product fallback that diagnoses it. Do NOT gate CI/unit tests on a live key.

## Validation Architecture

> nyquist_validation is enabled (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| Quick run command | `uv run pytest tests/test_models.py tests/test_config.py tests/test_renderer.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LOC-01 | ≥2 locations load and resolve by name | unit | `uv run pytest tests/test_config.py -k multi_location -x` | ❌ Wave 0 |
| LOC-02 | `Location` requires `timezone`; optional `units` parsed | unit | `uv run pytest tests/test_config.py -k location_fields -x` | ❌ Wave 0 |
| LOC-02 | Invalid IANA tz fails loudly at load | unit | `uv run pytest tests/test_config.py -k bad_timezone -x` | ❌ Wave 0 |
| LOC-03 | Send path never calls geocode; `--geocode` prints coords | unit | `uv run pytest tests/test_cli.py -k geocode -x` | ❌ Wave 0 |
| FCST-05 | feels_like placeholder + each of 5 hints fires at threshold | unit | `uv run pytest tests/test_models.py -k hints -x` | ❌ Wave 0 |
| FCST-05 | No hints apply → `{hint}` empty, line collapses | unit | `uv run pytest tests/test_models.py -k hints_empty -x` | ❌ Wave 0 |
| FCST-06 | Active alert → `{alert}` summary; no alert → empty | unit | `uv run pytest tests/test_models.py -k alert -x` | ❌ Wave 0 |
| TMPL-01 | Templates render with new placeholders, imperial-primary | unit | `uv run pytest tests/test_renderer.py -x` | ✅ (extend) |
| TMPL-02 | Non-canonical `{token}` raises at validation | unit | `uv run pytest tests/test_renderer.py -k validate -x` | ❌ Wave 0 |
| TMPL-02 | Validation fires on `--send-now` path (aborts send) | unit | `uv run pytest tests/test_cli.py -k send_now_bad_template -x` | ❌ Wave 0 |
| CONF-01 | All new settings editable via config.toml (no code change) | unit | `uv run pytest tests/test_config.py -k example_config -x` | ❌ Wave 0 |
| CONF-03 | Malformed config (extra key, bad units) fails loudly | unit | `uv run pytest tests/test_config.py -k invalid -x` | ✅ (extend) |
| CONF-05 | `--check` validates config+template+resolve; unique names | unit | `uv run pytest tests/test_cli.py -k check -x` | ❌ Wave 0 |
| CONF-05 | `--check` makes ONE live reachability call, no delivery | unit (mock httpx) | `uv run pytest tests/test_cli.py -k check_reachability -x` | ❌ Wave 0 |
| DATA-01/02/03 | One Call payload persists; single fetch reused; analysis cols populate | unit | `uv run pytest tests/test_store.py -k onecall -x` | ✅ (rewrite) |
| (mapping) | `Forecast.from_payloads` reads One Call current/daily[0]/alerts | unit | `uv run pytest tests/test_models.py -k from_payloads -x` | ✅ (rewrite) |

### Required Test Fixtures (recorded payloads — mock httpx, no live key)
- `onecall_imperial_clear.json` / `onecall_metric_clear.json` — clear day, no alerts key, low uvi (no hints/alert).
- `onecall_imperial_rainy.json` / `onecall_metric_rainy.json` — `daily[0].pop > 0.4` (umbrella), conditions=Rain.
- `onecall_imperial_alert.json` — includes `alerts[]` with one event (and a multi-alert variant for the summary).
- `onecall_imperial_highuv.json` — `daily[0].uvi >= 6` (sunscreen hint).
- `onecall_imperial_extreme.json` — feels_like < 40 OR > 90, wind_speed > 25 (cold/heat/wind hints).
- `geocode_austin.json` — `/geo/1.0/direct` array (single + ambiguous-multi variants).
- **Mock target:** the httpx call in `weather/client.py` (inject the client/payloads as Phase 1 tests do; `client`/`channel` are already injectable in `send_now`).

### Sampling Rate
- **Per task commit:** quick run (`test_models.py test_config.py test_renderer.py -x`).
- **Per wave merge:** full suite (`uv run pytest`).
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_cli.py` — `--check` and `--geocode` behavior (NEW file; Phase 1 had no CLI-subcommand tests beyond `test_send_now.py`).
- [ ] `tests/fixtures/onecall_*.json` + `geocode_*.json` — recorded One Call / geocoding payloads (above).
- [ ] Extend `tests/test_config.py` — `timezone` required, IANA validity, units enum, multi-location, unique-name.
- [ ] Extend `tests/test_models.py` — One Call mapping, 5 hints, alert summary.
- [ ] Extend `tests/test_renderer.py` — `validate_template` canonical-set enforcement.
- [ ] Rewrite `tests/test_store.py` — One Call schema + generated columns.
- [ ] **RETIRE** `tests/test_aggregate.py` + 2.5 bucket fixtures (with `aggregate.py`).
- [ ] Framework install: none — pytest already configured.

## Security Domain

> security_enforcement is enabled (config.json `workflow.security_enforcement: true`, `security_asvs_level: 1`, `security_block_on: high`).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Single-user local tool; OpenWeather key is the only credential, handled in V6/secrets. |
| V3 Session Management | no | No sessions, no web surface. |
| V4 Access Control | no | No multi-user / authz surface. |
| V5 Input Validation | yes | Config (`config.toml`) and template files are user input. pydantic `extra="forbid"` + IANA/units validators (CONF-03); template placeholder whitelist scan + guarded regex substitution (TMPL-02/D-10). Geocode `q` is passed only as an httpx query param (no shell/SQL). |
| V6 Cryptography / Secrets | yes | `OPENWEATHER_API_KEY` + webhook URL from `.env` only (CONF-02); never logged (httpx logger pinned WARNING); never persisted (only response payloads stored). No hand-rolled crypto. |
| V7 Error Handling / Logging | yes | Log outcomes only; never the request URL/params (carries `appid`). `--check` error messages must not echo the key. |
| V12 Files / Resources | yes | Template files are read and scanned, never executed; no `eval`/`str.format(**obj)` on user templates (existing renderer guards this — `test_renderer.py` asserts it). |

### Known Threat Patterns for {Python CLI + OpenWeather + SQLite + user-editable templates}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Format-string / template injection via user-editable template (`{0.__class__...}`) | Tampering / Info-disclosure | Guarded regex substitution + canonical-token whitelist; never `str.format(**obj)`/`eval` (existing guard, asserted by `test_renderer.py`). |
| Secret leak via logged request URL (`appid` in query) | Info-disclosure | httpx logger pinned to WARNING; log outcomes only; `--check`/`--geocode` follow the same rule. |
| Secret leak via persisted payload | Info-disclosure | Store only OpenWeather **response** JSON, never the request URL (existing store discipline; carries to the One Call payload). |
| SQL injection into SQLite store | Tampering | Parameterized `?` inserts only (existing store uses them); no string-built SQL. New One Call columns stay parameterized. |
| Malformed/hostile API payload crashes the send | DoS | Defensive `.get()` with `or []`/`or {}`; absent `alerts`/`rain` handled (Pitfall 2). |
| Config with extra/unexpected keys silently ignored | Tampering | `extra="forbid"` on all config models fails loudly (CONF-03). |

**Security block-on note:** `security_block_on: high` — the highest-severity item here is template-injection (already mitigated by the locked guarded renderer) and secret-leak-via-log (already mitigated by the pinned httpx logger). No new high-severity surface is introduced by this phase; the new geocode call and `--check` probe must inherit the same no-URL-logging discipline.

## Sources

### Primary (HIGH confidence)
- [openweathermap.org/api/one-call-3](https://openweathermap.org/api/one-call-3) — One Call 3.0 request params (`lat,lon,units,appid,exclude,lang`), `current` (temp/feels_like/humidity/wind_speed/uvi/weather), `daily[].temp.max/min/pop/uvi`, `alerts[]` (sender_name/event/start/end/description/tags), `timezone`/`timezone_offset`; one unit system per call; "One Call by Call" subscription, ~2,000 calls/day default. [VERIFIED via WebFetch 2026-06-09]
- [openweathermap.org/api/geocoding-api](https://openweathermap.org/api/geocoding-api) — `/geo/1.0/direct` params (`q,limit,appid`), response array (name/local_names/lat/lon/country/state), `limit` max 5 for ambiguous names. [VERIFIED via WebFetch 2026-06-09]
- Existing codebase (read this session): `weather/client.py`, `weather/models.py`, `weather/store.py`, `weather/aggregate.py`, `config/models.py`, `config/loader.py`, `config/settings.py`, `templates/renderer.py`, `cli.py`, `tests/*`, `templates/*.txt`, `pyproject.toml`. [VERIFIED]
- Environment probes: `python3 3.12.3`, `uv 0.11.19`, installed package versions. [VERIFIED via Bash]
- [docs.python.org/3/library/zoneinfo.html] — `ZoneInfo` raises `ZoneInfoNotFoundError` on an unknown zone (IANA validation). [CITED]

### Secondary (MEDIUM confidence)
- `.planning/research/PITFALLS.md` — One Call subscription/activation (Pitfall 2/8), optional-field absence, secret hygiene, tz/DST.
- `.planning/research/ARCHITECTURE.md` — scheduler→fetch→render→dispatch boundaries, channel seam, build order.
- `.planning/research/FEATURES.md` (referenced via CONTEXT.md) — avoid a full template engine; hints are code-computed.

### Tertiary (LOW confidence)
- One Call daily allowance exact number (1,000 vs 2,000) — CONTEXT.md says 1,000; One Call 3.0 page says ~2,000 default. Verify on the user's pricing dashboard (A1). Immaterial to the design.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all deps already installed and verified; no new packages.
- One Call 3.0 / Geocoding schema: HIGH — verified against official OpenWeather docs this session.
- Architecture / code seams: HIGH — grounded directly in the read Phase 1 source.
- Store migration shape & dual-unit strategy: MEDIUM — recommendations within D-01/D-02 planner discretion (A2/A3); both are explicitly planner decisions.
- Pitfalls: HIGH — corroborated by official docs + existing PITFALLS.md.

**Research date:** 2026-06-09
**Valid until:** ~2026-07-09 (OpenWeather One Call 3.0 is stable; re-verify the subscription/quota figures if the user reports a 401 on a key that should work).
