# Phase 1: First Briefing End-to-End - Research

**Researched:** 2026-06-09
**Domain:** Python vertical-slice pipeline — OpenWeather free 2.5 fetch → bucket aggregation → SQLite persistence → plain-text render → Discord webhook delivery, behind a provider-agnostic `Channel.send(text)` seam
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Templating subsystem (foundation here; deepened in Phase 2)**
- **D-01:** Templates live in a top-level **`templates/`** directory as plain-text **`.txt`** files using simple **`{placeholder}`** substitution (e.g. `{temp}`, `{high}`, `{low}`, `{rain}`, `{wind}`, `{humidity}`, `{conditions}`, `{location}`, `{date}`). Editable from day one — rendering reads from files, never hardcoded strings.
- **D-02:** Flat naming convention **`{type}-{style}.txt`** so it scales to type × style (× platform later) without nesting churn.
- **D-03:** Author a **starter set of three daily-briefing layouts**, all editable:
  - `briefing-sectioned.txt` — **DEFAULT**. Header line + grouped sections, light emoji (e.g. `☀️ WEATHER — {location}` / date / sections).
  - `briefing-multiline.txt` — one labeled field per line with a light header.
  - `briefing-compact.txt` — dense one/two-liner, **plain (no emoji)**, sized for character-constrained channels (the SMS-safe variant seam).
- **D-04:** This pulls the *template-directory + file-based editable rendering* seam into Phase 1. Phase 2's TMPL-01/TMPL-02 formalize the editable-template contract (canonical placeholder set, missing-field-fails-loudly validation) and add richer content fields (hints, severe-weather). **Build Phase 1's renderer so Phase 2 EXTENDS it, not replaces it.**

**Location configuration**
- **D-05:** Phase 1 locations are specified by **raw `lat`/`lon` + a display `name`** in config. No geocoding code in Phase 1 (geocoding is Phase 2 / LOC-03).
- **D-06:** Config is a **list of locations** even in Phase 1 (one entry for now) — a clean seam into Phase 2 multi-location, no later refactor.
- **D-07:** `--send-now` takes an **optional** location argument: bare `--send-now` sends the default/first location; `--send-now <name>` targets a specific one.

**Persistence & analysis-ready schema (DATA-01/02/03)**
- **D-08:** Store **one row per API fetch** (not daily roll-ups), each with: location, fetch timestamp (**UTC + local**), the **raw JSON payload**, and **normalized fields**.
- **D-09:** Persist **both current conditions AND the forecast buckets** (the briefing already fetches both). Forecast rows must retain their **target/valid timestamp** so later "actuals" can be joined for forecast-accuracy analysis.
- **D-10:** Schema designed up front (DATA-02) to support four analysis axes: (1) temperature trends, (2) rain/precipitation frequency, (3) wind & humidity patterns, (4) **forecast-vs-actual accuracy** (the primary schema-shaping constraint — predicted-keyed-by-target-time + later actuals join). **Design table layout to avoid a v2 migration.** Analysis features themselves remain v2.
- **D-11:** Persistence **reuses the briefing's existing fetch** — no extra OpenWeather calls solely to store data (DATA-03).

**Discord delivery & styling**
- **D-12:** The rendered **plain-text template is the canonical message body** passed through `Channel.send(text)` — the exact text SMS/Telegram reuse later. Keep this path channel-agnostic.
- **D-13:** Additionally render a **basic Discord embed** (Discord-only enrichment) from the same forecast data. The embed is an implementation detail of the Discord channel and must NOT leak into the channel interface or the canonical text path (DELV-03).
- **D-14:** The webhook posts with a **custom identity**: username like `WeatherBot ☀️` plus a **configurable avatar URL**.

### Claude's Discretion
- Exact wording/spacing inside the three starter templates (sensible defaults; user will edit).
- Internal module/package layout, library wiring, and SQLite table/column specifics — defer to research + planner.
- Rounding/precision of displayed values (e.g. whole-degree temps) — pick a sensible default.

### Deferred Ideas (OUT OF SCOPE for Phase 1)
- Weekly-briefing message type (roadmap backlog; not in v1 requirements).
- Alert message templates (failure alerts = Phase 4; passive severe-weather line = Phase 2). `alert-{style}.txt` naming convention is ready for them.
- SMS / Telegram channel-specific templates & delivery (v2). The plain-text canonical body + `compact` template lay the seam.
- Per-platform template selection / character-budget enforcement (v2).
- On-demand `weather <location>` command interface (v2).
- Weather-pattern analysis / query / export (v2). Phase 1 only *stores* the data.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FCST-01 | Fetch from free OpenWeather 2.5 endpoints (current + 5-day/3-hour forecast) by lat/lon | Verified endpoint URLs, params (`lat`/`lon`/`appid`/`units`/`lang`), and JSON shapes — see Code Examples §Fetch |
| FCST-02 | Aggregate 3-hour forecast buckets into today's high, low, rain chance for the location's local date | Bucket-aggregation algorithm + local-date boundary handling using `city.timezone` offset — see Pitfall 1 & Code Examples §Aggregation |
| FCST-03 | Briefing includes temp, today's high/low, sky conditions, rain chance, wind, humidity | Field-source map: current temp/wind/humidity/sky from `/weather`; high/low/rain from aggregated `/forecast` buckets — see Architectural Responsibility Map |
| FCST-04 | Values display imperial-primary with metric in parentheses (`72°F (22°C)`, `8 mph (3.6 m/s)`) | Fetch both `units=imperial` AND `units=metric` (2 calls each endpoint) OR fetch imperial and convert — see Pitfall 4 |
| DATA-01 | Persist every fetch to SQLite: location, fetch time (UTC+local), raw payload, normalized fields | Schema design with raw-JSON TEXT + generated columns — see §SQLite Schema Design |
| DATA-02 | Schema designed up front as queryable per-location time series; no v2 migration | Generated-column strategy lets new analysis columns be added without back-fill — see §SQLite Schema Design |
| DATA-03 | Persistence reuses the briefing's existing fetch — no extra API calls | Fetch returns a payload object; persist + render both consume it — see Architecture Patterns §Pattern 2 |
| DELV-01 | Deliver via Discord incoming webhook | `discord-webhook` 1.4.1 verified API — see Code Examples §Discord |
| DELV-02 | Delivery behind a pluggable `send(text)` interface, Discord as one impl | `Channel` ABC contract — see Architecture Patterns §Pattern 1 |
| DELV-03 | Plain-text-first; Discord embed is optional enrichment only | Embed built inside `DiscordWebhookChannel`, never crosses the interface — see Pitfall 3 |
| CONF-02 | Secrets (API key, webhook URL) from env/`.env`, never in config or git | `pydantic-settings` `.env` layering + `.gitignore` — see §Config & Secrets |
| CONF-04 | `--send-now <location>` runs a briefing immediately | CLI entrypoint composing the send pipeline — see Architecture Patterns §Build Order |
</phase_requirements>

## Summary

Phase 1 is a Walking Skeleton: prove the *entire* pipeline end-to-end on demand before any scheduling, reliability, or multi-location machinery exists. The stack is fully locked by `CLAUDE.md` and the project research docs (Python 3.12+, uv, httpx, discord-webhook, pydantic/pydantic-settings, tomllib, structlog, Jinja2 OR plain `str` substitution, pytest, ruff) — this research investigates the **HOW** (request/response shapes, the bucket-aggregation algorithm, the analysis-ready SQLite schema, the channel seam, the embed-isolation rule), not the **WHAT**.

Three things carry essentially all the technical risk and deserve the planner's attention: **(1)** the **3-hour-bucket → today's-high/low/rain aggregation**, which must use the *location's local calendar date* (not UTC, not the current-moment `temp_min`/`temp_max`) and must survive a clear-sky day where the `rain` field is absent and `pop` may be 0; **(2)** the **SQLite schema**, which must persist one row per fetch with raw JSON + normalized fields AND retain forecast buckets keyed by their *target/valid timestamp* so a deferred v2 forecast-vs-actual accuracy join needs no migration — solved cleanly with raw-JSON-TEXT-plus-generated-columns; and **(3)** the **`Channel.send(text)` seam**, where the canonical plain-text body must flow through a provider-agnostic interface while the Discord embed stays an internal implementation detail of the Discord channel and never leaks into the interface.

For imperial-primary-with-metric display (FCST-04), the cleanest correct approach given the free 2.5 endpoints is to fetch each endpoint **twice** (once `units=imperial`, once `units=metric`) — 4 calls per briefing, trivially within the 1M/month, 60/min free quota — OR fetch imperial only and convert in code. Both are valid; fetching both avoids rounding drift and conversion bugs, converting saves 2 calls. This is a planner decision (flagged in Open Questions).

**Primary recommendation:** Build leaf-up in the architecture's order — config/secrets → weather client (with the aggregation as a focused, fixture-tested unit) → SQLite store → renderer → `Channel`+Discord → `send_now` composition. Use a raw-JSON + generated-column SQLite schema. Fetch imperial+metric (or imperial+convert) for FCST-04. Keep the embed strictly inside the Discord channel.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read config + secrets | Config layer (`config/`) | — | Load TOML + `.env` once, validate, hand typed objects downstream; nothing re-reads raw config or `os.getenv` later |
| Fetch current conditions | Weather data layer (`weather/client.py`) | — | `/data/2.5/weather` by lat/lon; owns HTTP, units param, defensive parsing |
| Fetch 3-hour forecast | Weather data layer (`weather/client.py`) | — | `/data/2.5/forecast` by lat/lon; same client, same defensive parsing |
| Aggregate buckets → today's high/low/rain | Weather data layer (`weather/aggregate.py`) | — | Pure function over forecast `list[]` + `city.timezone`; the highest-risk unit-testable piece — isolate it |
| Normalize into a `Forecast` object | Weather data layer (`weather/models.py`) | — | Hide endpoint/JSON shape; renderer + persistence consume the normalized object, not raw JSON |
| Persist the fetch | Data/persistence layer (`weather/store.py` or `store/`) | Weather layer | Writes raw payload + normalized fields from the *same* fetch (DATA-03); owns the SQLite schema |
| Render plain-text body | Template renderer (`templates/renderer.py`) | — | Pure function: template file + `Forecast` → `str`. No I/O, no Discord knowledge |
| Build Discord embed | Discord channel (`channels/discord.py`) | — | **Discord-only**; built from the same `Forecast`, never crosses the `Channel` interface (D-13/DELV-03) |
| Deliver text (+ optional embed) | Channel dispatch (`channels/`) | — | `Channel.send(text)` ABC; `DiscordWebhookChannel` is the one impl; embed is internal |
| Compose the send | Composition root / CLI (`__main__.py` / `cli.py`) | All of the above | `--send-now` wires fetch → persist → render → dispatch for one location |

## Standard Stack

> **Stack is LOCKED by `CLAUDE.md` and `.planning/research/STACK.md` — not re-litigated.** Versions below re-verified against the PyPI JSON API on 2026-06-09.

### Core (Phase 1 runtime deps)
| Library | Version (verified 2026-06-09) | Purpose | Why Standard |
|---------|-------------------------------|---------|--------------|
| Python | 3.12+ | Language/runtime | Locked; `tomllib`, `zoneinfo` are stdlib at 3.11+ |
| httpx | 0.28.1 | HTTP client for OpenWeather | Explicit timeouts so the process never hangs; one client, connection pooling |
| discord-webhook | 1.4.1 | Discord delivery (v1 channel) | Outbound webhook only, native `username`/`avatar_url`/embed support (D-14/D-13) |
| pydantic | 2.13.4 | Config models + validation | Fail-loud-at-boot validation of locations/template/paths |
| pydantic-settings | 2.14.1 | `.env` secrets layered over TOML | Keeps API key + webhook URL out of the committed config (CONF-02) |
| tomllib (stdlib) | built-in (3.11+) | Read `config.toml` | Zero-dependency, comment-friendly, hand-edited config |
| structlog | 26.1.0 | Structured logging | Better than `print` for diagnosing the send path; redact secrets in log fields |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Jinja2 | 3.1.6 | Template rendering engine | OPTIONAL — see Alternatives. Locked stack lists it, but D-01's `{placeholder}` substitution does NOT need a full engine; `str` substitution suffices for Phase 1 |
| python-dotenv | 1.2.2 | `.env` loading | Redundant if `pydantic-settings` is used (it reads `.env` natively). Do not add both. |
| zoneinfo (stdlib) | built-in (3.9+) | IANA tz handling | Phase 1 can derive local date from the payload's `city.timezone` offset; full IANA-per-location is Phase 2. See Open Questions. |
| sqlite3 (stdlib) | built-in | SQLite persistence | The whole DATA-01/02/03 layer; no external dependency needed |

### Dev
| Tool | Version | Purpose |
|------|---------|---------|
| pytest | 9.0.3 | Unit tests — drive bucket-aggregation with recorded JSON fixtures |
| ruff | 0.15.16 | Lint + format |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Jinja2 (full engine) | Python `str` `{placeholder}` substitution with a guarded mapping | D-01 specifies simple `{placeholder}` substitution and FEATURES.md lists a full template *engine* as an anti-feature. A guarded substitution (whitelisted keys, missing-key visible-but-safe) satisfies D-01/DELV-03 without engine weight. **Recommend a small guarded substituter in Phase 1** that Phase 2 can swap to Jinja2 if richer logic is ever needed — but keep the renderer's *signature* (`render(template_text, forecast) -> str`) stable so Phase 2 extends, not replaces (D-04). Either choice is acceptable; the seam matters more than the engine. |
| Fetch imperial+metric (4 calls) | Fetch imperial only + convert in code | 4 calls/briefing is a rounding error vs quota; avoids conversion bugs. Converting saves 2 calls and removes a double-fetch. Planner decision — see Open Questions. |
| `discord-webhook` lib | Raw `httpx` POST to webhook URL | The lib gives `username`/`avatar_url`/embed builders for free (D-13/D-14) and is already a locked dep. Raw POST is viable but you'd hand-build the embed JSON. **Recommend the library.** |

**Installation:**
```bash
uv add httpx discord-webhook pydantic pydantic-settings structlog
uv add --dev pytest ruff
# Jinja2 only if you choose the engine over guarded str-substitution:
# uv add jinja2
```

## Package Legitimacy Audit

> slopcheck could **not** be installed in this session (`pip install slopcheck` failed — no network/registry access for that package). Per the legitimacy-gate protocol, packages are therefore tagged `[ASSUMED]` and the planner SHOULD gate any *new* install behind a `checkpoint:human-verify` task. **Mitigating context:** every package below is a locked choice already vetted in `.planning/research/STACK.md` (version-checked 2026-06-09), is named in `CLAUDE.md`, has a known canonical source repo, and is a high-download, multi-year package — none is a newly-introduced or speculative dependency.

| Package | Registry | Latest (verified PyPI JSON 2026-06-09) | Source Repo | slopcheck | Disposition |
|---------|----------|----------------------------------------|-------------|-----------|-------------|
| httpx | PyPI | 0.28.1 | github.com/encode/httpx | unavailable | Approved [ASSUMED] |
| discord-webhook | PyPI | 1.4.1 | github.com/lovvskillz/python-discord-webhook | unavailable | Approved [ASSUMED] |
| pydantic | PyPI | 2.13.4 | github.com/pydantic/pydantic | unavailable | Approved [ASSUMED] |
| pydantic-settings | PyPI | 2.14.1 | github.com/pydantic/pydantic-settings | unavailable | Approved [ASSUMED] |
| structlog | PyPI | 26.1.0 | github.com/hynek/structlog | unavailable | Approved [ASSUMED] |
| jinja2 (optional) | PyPI | 3.1.6 | github.com/pallets/jinja | unavailable | Approved [ASSUMED] |
| python-dotenv (optional) | PyPI | 1.2.2 | github.com/theskumar/python-dotenv | unavailable | Approved [ASSUMED] |
| pytest (dev) | PyPI | 9.0.3 | github.com/pytest-dev/pytest | unavailable | Approved [ASSUMED] |
| ruff (dev) | PyPI | 0.15.16 | github.com/astral-sh/ruff | unavailable | Approved [ASSUMED] |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
**No postinstall-script ecosystem applies** (Python wheels; no npm-style postinstall). All names verified present on the correct registry (PyPI) via the PyPI JSON API.

## Architecture Patterns

### System Architecture Diagram

```
                         CONFIG LAYER (load + validate once, at startup)
   config.toml (locations[], template path, webhook identity)  +  .env (secrets)
                              │
                              ▼  typed Config + Secrets
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  CLI entrypoint:  --send-now [location]                                    │
   │     resolves which location (D-07: bare = first; <name> = match)           │
   └───────────────────────────────┬──────────────────────────────────────────┘
                                    ▼  send_now(location)
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  WEATHER DATA LAYER                                                         │
   │   client.fetch_current(loc)   ─► /data/2.5/weather   (raw JSON)            │
   │   client.fetch_forecast(loc)  ─► /data/2.5/forecast  (raw JSON, list[])    │
   │            │                                                                │
   │            ▼  aggregate(forecast.list, city.timezone) ─► today's hi/lo/rain │
   │   normalize ─► Forecast(temp, high, low, conditions, rain%, wind, humidity, │
   │                          + raw payloads kept for persistence)               │
   └───────────────┬───────────────────────────────────┬────────────────────────┘
                   │ (same fetch — DATA-03)             │ Forecast
                   ▼                                    ▼
   ┌───────────────────────────────┐     ┌──────────────────────────────────────┐
   │  PERSISTENCE (SQLite)          │     │  TEMPLATE RENDERER (pure, no I/O)     │
   │   insert current row           │     │   read templates/briefing-*.txt       │
   │   insert N forecast-bucket rows│     │   substitute {placeholder} ← Forecast │
   │   (raw JSON + normalized cols, │     │   ─► canonical plain-text body (str)  │
   │    target_ts on forecast rows) │     └──────────────────┬───────────────────┘
   └───────────────────────────────┘                        │ text (str)
                                                             ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  CHANNEL DISPATCH (pluggable)                                              │
   │   Channel.send(text) -> DeliveryResult       ◄── interface takes TEXT only │
   │   DiscordWebhookChannel:                                                    │
   │      • posts content=text  (canonical, SMS-reusable)                        │
   │      • ALSO builds a Discord embed from Forecast  ── internal only (D-13)   │
   │      • username="WeatherBot ☀️", avatar_url=config  (D-14)                  │
   └──────────────────────────────────────────────────────────────────────────┘
```

Trace the primary use case: `--send-now` → resolve location → fetch current + forecast → aggregate → normalize → (persist the same fetch) + (render text) → `channel.send(text)` posts to Discord with custom identity and an internal embed.

### Recommended Project Structure
```
weatherbot/
├── __main__.py            # entry: parse --send-now, load config, wire, run send_now()
├── cli.py                 # arg parsing + send_now(location) composition (DATA-03 happens here)
├── config/
│   ├── models.py          # Pydantic: Config, Location(name, lat, lon), WebhookIdentity
│   ├── loader.py          # tomllib read config.toml; pydantic-settings reads .env secrets
│   └── settings.py        # Settings(BaseSettings): OPENWEATHER_API_KEY, DISCORD_WEBHOOK_URL
├── weather/
│   ├── client.py          # httpx GET /data/2.5/weather + /data/2.5/forecast (defensive parse)
│   ├── aggregate.py       # PURE: buckets + tz offset -> (high, low, rain_chance). FIXTURE-TESTED
│   ├── models.py          # Forecast dataclass (normalized) + retains raw payloads for persistence
│   └── store.py           # SQLite: schema, insert current row + forecast-bucket rows
├── templates/
│   ├── briefing-sectioned.txt   # DEFAULT (light emoji)
│   ├── briefing-multiline.txt
│   ├── briefing-compact.txt     # plain, SMS-safe seam
│   └── renderer.py        # PURE: render(template_text, forecast) -> str (guarded substitution)
├── channels/
│   ├── base.py            # Channel ABC: send(text) -> DeliveryResult  (TEXT in, never Forecast)
│   ├── discord.py         # DiscordWebhookChannel: content + INTERNAL embed + identity
│   └── factory.py         # build_channel(config, secrets) -> Channel  (registry by "type")
├── config.example.toml    # documented sample (locations list, template choice, avatar URL)
└── .env.example           # OPENWEATHER_API_KEY=, DISCORD_WEBHOOK_URL=
```

> The `channels/factory.py` + `base.py` registry, the `templates/` directory, and the `Forecast` model are the load-bearing seams later phases extend. `scheduler/` and `reliability/` are intentionally ABSENT in Phase 1 (Phases 3–4).

### Pattern 1: `Channel.send(text)` — Strategy over delivery providers (DELV-02/03)
**What:** A minimal ABC every provider implements. Dispatch holds a `Channel` and calls `send(text)` without knowing the provider. **Input is already-rendered text (a `str`), never a `Forecast`.** Output is a `DeliveryResult`, not a raised exception for expected failures.
**When to use:** Now — Discord is the only impl, but the interface is the seam SMS/Telegram slot into (v2).
**Example:**
```python
# channels/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class DeliveryResult:
    ok: bool
    detail: str = ""          # error text / message id, for logging

class Channel(ABC):
    name: str                 # "discord" — for logs

    @abstractmethod
    def send(self, text: str) -> DeliveryResult:
        """Deliver final plain-text body. Return DeliveryResult(ok=False, ...) on
        expected failure; raise only on bugs."""
```
> **Contract rules that keep it pluggable (and keep the embed from leaking — D-13):**
> 1. Interface input is `str` text, never a `Forecast`. The Discord embed is built *inside* `DiscordWebhookChannel` from a `Forecast` it is handed at *construction or via a Discord-specific method* — it does NOT travel through `send(text)`.
> 2. Output is `DeliveryResult`, uniform across providers (Phase 4's retry layer reads `ok`).
> 3. Webhook URL / identity come from config at construction (factory), not through the interface.

> **Embed isolation note (load-bearing for DELV-03):** because `send(text)` only takes text, the Discord channel needs the `Forecast` by another path to build its embed. Two clean options the planner should pick from: **(a)** give `DiscordWebhookChannel` a `send_briefing(text, forecast)` method *in addition to* the ABC `send(text)` — the ABC stays text-only, the embed lives in a Discord-specific method; or **(b)** construct the channel per-send with the embed pre-built. Option (a) keeps the plain-text path identical for SMS and is recommended.

### Pattern 2: Single fetch, dual consumer (DATA-03)
**What:** `send_now` fetches once; the *same* returned payload/`Forecast` is handed to BOTH the persistence write AND the renderer. No second API call exists solely to persist.
**When to use:** Always — DATA-03 is explicit.
**Example:**
```python
# cli.py  (composition — the one place fetch/persist/render/dispatch meet)
forecast = weather.get_forecast(location)     # 1 fetch (current + forecast endpoints)
store.persist(location, forecast)             # writes raw payload + normalized cols
text = renderer.render(template_text, forecast)
result = channel.send(text)                   # DiscordWebhookChannel also builds its embed
```

### Pattern 3: Locations as a list from day one (D-06)
**What:** Config holds `locations: list[Location]` even with one entry. `--send-now` with no arg picks `locations[0]`; with a name, matches by `name`.
**Why:** Phase 2 multi-location needs zero schema refactor.

### Anti-Patterns to Avoid
- **Channel formats its own message:** passing `Forecast` (or raw JSON) into `Channel.send` and letting Discord build the text. Violates DELV-03 and the SMS seam. Render once to `str`; channels receive text. (Embed is the *one* sanctioned Discord-only extra, kept internal.)
- **Using current-endpoint `temp_min`/`temp_max` as today's high/low:** they are "min/max *at the current moment*" (verified, official docs) — a silent correctness bug. Aggregate the forecast buckets instead (FCST-02).
- **Computing the day boundary in UTC or host-local time:** today's buckets must be selected by the *location's* local date (Pitfall 1).
- **Unguarded `str.format(**data)` on a user-editable template:** format-string injection / `KeyError` crash. Use a guarded substituter with a whitelisted key set.
- **Scattering `os.getenv`:** read secrets once in the settings object; inject typed values.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Loading + validating config and secrets | Manual `os.getenv` + ad-hoc dict parsing | `pydantic` + `pydantic-settings` over `tomllib` | Fail-loud-at-boot validation; `.env` layering keeps secrets out of config (CONF-02) |
| HTTP with timeouts/retries-ready | `urllib` + manual timeout plumbing | `httpx.Client(timeout=...)` | Explicit timeouts so the process never hangs on slow OpenWeather |
| Discord webhook POST + embed + identity | Hand-built JSON body + `requests` | `discord-webhook` (`DiscordWebhook`, `DiscordEmbed`) | Native `username`/`avatar_url`/embed builders + `rate_limit_retry` (D-13/D-14) |
| Storing raw JSON + queryable normalized fields | Parallel columns you back-fill on every schema change | SQLite **raw-JSON TEXT + GENERATED columns + indexes** | New analysis columns added later with NO data migration (DATA-02) |
| Timezone-correct "today" | Manual offset math on `datetime` | `city.timezone` offset from payload (Phase 1) / `zoneinfo` (Phase 2) | DST-safe local-date selection for bucket aggregation |
| Template placeholder substitution | `eval` / raw `.format(**d)` | Guarded mapping substitution (or Jinja2 `StrictUndefined`) | Prevents format-string abuse and crash-on-missing-key |

**Key insight:** Every "deceptively simple" piece here (config validation, the day-boundary, the JSON-plus-normalized schema, the embed isolation) has a documented footgun. The libraries and the generated-column pattern eliminate them; hand-rolling re-introduces them.

## SQLite Schema Design (DATA-01/02/03 — the primary schema-shaping constraint)

> This is the most demanding axis (D-10): predicted-keyed-by-target-time + a later actuals join, with **no v2 migration**. Verified pattern: store the **raw JSON payload as a TEXT column**, expose queryable fields as **GENERATED (virtual) columns** via `json_extract`, and **index** them. Generated columns add no write overhead and require **zero back-fill** when new analysis columns are added later — exactly the DATA-02 "no migration" guarantee. [CITED: dbpro.app/blog/sqlite-json-virtual-columns-indexing] [CITED: moldstud.com — store timestamps as Unix integers, index timestamp columns]

### Recommended tables

Two tables — one for **observed/current** readings, one for **forecast buckets** — both per-location and time-indexed. They share the raw-JSON + generated-column shape. (A single-table design is possible but the forecast table's `target_ts` semantics differ enough that two tables read more cleanly and keep the future actuals-join obvious.)

```sql
-- Observed current conditions: one row per current-endpoint fetch
CREATE TABLE IF NOT EXISTS weather_current (
    id              INTEGER PRIMARY KEY,
    location_name   TEXT    NOT NULL,         -- D-06 list: store name (and/or a location_id later)
    lat             REAL    NOT NULL,
    lon             REAL    NOT NULL,
    fetched_at_utc  INTEGER NOT NULL,         -- unix seconds, UTC (the fetch moment)
    observed_at_utc INTEGER NOT NULL,         -- payload 'dt' (unix UTC)
    tz_offset_sec   INTEGER NOT NULL,         -- payload 'timezone' (shift from UTC)
    local_date      TEXT    NOT NULL,         -- 'YYYY-MM-DD' in location-local time (D-08 'local')
    units           TEXT    NOT NULL,         -- 'imperial' | 'metric' (which response this row is)
    raw_json        TEXT    NOT NULL,         -- full current-endpoint payload (D-08 raw)
    -- normalized/generated (queryable, zero back-fill when you add more later):
    temp            REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp')) VIRTUAL,
    humidity        REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.humidity')) VIRTUAL,
    wind_speed      REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.wind.speed')) VIRTUAL,
    conditions      TEXT GENERATED ALWAYS AS (json_extract(raw_json,'$.weather[0].main')) VIRTUAL
);
CREATE INDEX IF NOT EXISTS ix_current_loc_time
    ON weather_current(location_name, observed_at_utc);
CREATE INDEX IF NOT EXISTS ix_current_loc_date
    ON weather_current(location_name, local_date);

-- Forecast buckets: one row per 3-hour bucket per forecast fetch.
-- target_ts is the bucket's VALID time — the key a future actuals join uses (D-09/D-10).
CREATE TABLE IF NOT EXISTS weather_forecast (
    id              INTEGER PRIMARY KEY,
    location_name   TEXT    NOT NULL,
    lat             REAL    NOT NULL,
    lon             REAL    NOT NULL,
    fetched_at_utc  INTEGER NOT NULL,         -- when this forecast was retrieved
    target_ts_utc   INTEGER NOT NULL,         -- bucket 'dt' (unix UTC) = the time being forecast
    target_local_date TEXT  NOT NULL,         -- bucket's local 'YYYY-MM-DD' (for "today's buckets")
    tz_offset_sec   INTEGER NOT NULL,
    units           TEXT    NOT NULL,
    raw_json        TEXT    NOT NULL,         -- the single bucket object (or full payload — see note)
    temp            REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp')) VIRTUAL,
    temp_min        REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp_min')) VIRTUAL,
    temp_max        REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp_max')) VIRTUAL,
    pop             REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.pop')) VIRTUAL,
    humidity        REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.humidity')) VIRTUAL,
    wind_speed      REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.wind.speed')) VIRTUAL,
    conditions      TEXT GENERATED ALWAYS AS (json_extract(raw_json,'$.weather[0].main')) VIRTUAL
);
-- The forecast-accuracy join key: (location, target time). A future actuals query joins
-- weather_forecast.target_ts_utc against weather_current.observed_at_utc for the same location.
CREATE INDEX IF NOT EXISTS ix_forecast_loc_target
    ON weather_forecast(location_name, target_ts_utc);
CREATE INDEX IF NOT EXISTS ix_forecast_loc_targetdate
    ON weather_forecast(location_name, target_local_date);
CREATE INDEX IF NOT EXISTS ix_forecast_fetched
    ON weather_forecast(location_name, fetched_at_utc);
```

### Schema design notes for the planner
- **`raw_json` per forecast row:** store the *individual bucket object* (cleanest for generated columns) OR store the full forecast payload once in a parent `forecast_fetch` row and child bucket rows. The per-bucket approach above is simplest and satisfies D-08/D-09 directly; the parent/child variant saves storage if that ever matters (it won't at this volume). **Recommend per-bucket rows.**
- **Why generated columns, not plain columns you populate in Python:** plain columns also work, but generated columns guarantee the queryable view *always* matches the stored raw JSON and let v2 add `feels_like`, `uvi`, `pressure`, etc. with a single `ALTER TABLE ADD COLUMN ... GENERATED` and an index — **no UPDATE of historical rows** (the DATA-02 promise). If the planner prefers plain columns for portability, that is acceptable *provided* the raw JSON is still stored so v2 can derive anything — the migration guarantee comes from storing raw JSON, the generated columns are the elegant way to expose it.
- **`local_date` / `target_local_date`:** compute once at write time from `dt` + `tz_offset_sec`; storing it (rather than computing in every query) makes "today's buckets for this location" a simple indexed equality.
- **Units:** because FCST-04 may fetch both imperial and metric, tag each row with its `units` so analysis is unambiguous. If the planner instead fetches imperial-only + converts, store `units='imperial'` and the metric values are derived at render time (not stored) — document which.
- **Forecast-vs-actual accuracy (the v2 join this schema exists for):** later, for each forecast row, find the observed row whose `observed_at_utc` is nearest its `target_ts_utc` for the same location, and compare `temp`/`pop`/etc. The indexes `ix_forecast_loc_target` + `ix_current_loc_time` make that join cheap. **No migration needed** — the keys are present from the first Phase 1 write.
- **DB file location:** a gitignored data dir (e.g. `data/weatherbot.db`); ensure it is in `.gitignore` alongside `.env`.

## OpenWeather Free 2.5: Request/Response & Aggregation (FCST-01/02/03)

### Endpoints & params (verified against official docs)
- **Current:** `GET https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={key}&units={imperial|metric}&lang=en` [CITED: openweathermap.org/current]
- **Forecast (5-day / 3-hour):** `GET https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={key}&units={imperial|metric}&lang=en` [CITED: openweathermap.org/forecast5]
- **Auth:** API key in the `appid` query param. **Never log the full URL** — the key travels in the query string (Pitfall 5).
- **Units:** default is Kelvin (`standard`). ALWAYS pass `units`. Imperial → temp °F, wind mph; metric → temp °C, wind m/s. [VERIFIED: openweathermap.org/current — confirmed wind units differ by `units`]

### Response shapes (verified)
**Current `/weather`:** `main{temp,feels_like,temp_min,temp_max,pressure,humidity}`, `weather[]{id,main,description,icon}`, `wind{speed,deg,gust}`, `clouds.all`, `dt` (unix UTC), `sys{country,sunrise,sunset}`, `timezone` (shift in seconds from UTC), `name`, `coord{lat,lon}`. **`main.temp_min`/`temp_max` are "min/max at the current moment," NOT the day's range** [VERIFIED: openweathermap.org/current].

**Forecast `/forecast`:** `cod`, `message`, `cnt`, `list[]`, `city{id,name,coord,country,timezone,sunrise,sunset}`. Each `list[]` item: `dt` (unix UTC), `dt_txt` (ISO **UTC**), `main{temp,feels_like,temp_min,temp_max,pressure,humidity,...}`, `weather[]`, `wind{speed,deg,gust}`, `pop` (0–1, **present on every item**), `rain.3h` (**only present when raining**), `visibility`, `clouds.all`, `sys.pod` (n/d). **`city.timezone` is the location's UTC offset in seconds** — the value to use for the local-date boundary. [VERIFIED: openweathermap.org/forecast5]

### Bucket-aggregation algorithm (FCST-02 — the highest-risk piece)
```python
# weather/aggregate.py  — PURE function, fixture-tested
from datetime import datetime, timezone, timedelta

def today_aggregate(forecast_payload: dict) -> dict:
    """Compute today's (location-local) high, low, and rain chance from 3-hour buckets."""
    offset = timedelta(seconds=forecast_payload["city"]["timezone"])  # location UTC offset
    # "today" in the LOCATION's local time, not the host's:
    now_local = datetime.now(timezone.utc) + offset
    target_date = now_local.date()

    highs, lows, pops = [], [], []
    for item in forecast_payload.get("list", []):
        bucket_local = datetime.fromtimestamp(item["dt"], tz=timezone.utc) + offset
        if bucket_local.date() != target_date:
            continue
        main = item.get("main", {})
        if "temp" in main:                 # defensive: aggregate over main.temp
            highs.append(main["temp"])
            lows.append(main["temp"])
        pops.append(item.get("pop", 0.0))  # pop present on every item; default 0.0 defensively

    high = max(highs) if highs else None   # None => location-local "today" has no remaining buckets
    low  = min(lows) if lows else None
    rain_chance = round(max(pops) * 100) if pops else 0   # max pop across today's buckets, as %
    return {"high": high, "low": low, "rain_chance": rain_chance}
```
> **Edge cases the fixtures MUST cover (per SUMMARY.md):**
> 1. **Clear-sky day:** no `rain` field on any bucket, `pop` all 0.0 → `rain_chance == 0`, no `KeyError`.
> 2. **Rainy day:** some buckets have `rain.3h` and non-zero `pop` → `rain_chance == round(max(pop)*100)`.
> 3. **Local-midnight boundary:** a positive `city.timezone` (e.g. +14h Pacific) or negative (e.g. −10h Hawaii) where UTC "today" and local "today" differ — confirm buckets are selected by *local* date.
> 4. **Late-in-the-day fetch:** few or zero remaining buckets for local-today → `high`/`low` may be `None`; decide the fallback (e.g. fall back to current temp, or surface "no forecast remaining"). **Planner decision** — flagged in Open Questions.
> 5. **Units:** run the same fixtures for imperial and metric to confirm no unit assumptions leak into aggregation (aggregation is unit-agnostic — it just min/max/max the numbers).

> **Use `dt` (unix), not `dt_txt`:** `dt_txt` is ISO but in **UTC**; parsing it as local would be wrong. Always offset from the unix `dt`.

## Config & Secrets (CONF-02)

- **Secrets** (`OPENWEATHER_API_KEY`, `DISCORD_WEBHOOK_URL`) load from `.env` / environment via a `pydantic_settings.BaseSettings` subclass. They are NEVER in `config.toml` and NEVER committed. The Discord webhook URL is itself a credential (anyone with it can post) — treat it like the API key (Pitfall 5/7).
- **Non-secret config** (`config.toml`): `locations` list (`name`, `lat`, `lon`), chosen template filename, webhook display `username` + `avatar_url` (D-14). Validated by Pydantic at load; fail loud on malformed input.
- **`.gitignore` MUST contain `.env` and the SQLite data dir BEFORE the first real key is introduced.** (Already gitignored per repo: `API-key.md`, `.env`.) Provide `.env.example` + `config.example.toml` with placeholders.
- **Never log the full OpenWeather request URL or the webhook URL.** Redact in structlog fields.

## Code Examples

### Fetch (httpx, both endpoints, explicit timeout)
```python
# weather/client.py
import httpx

BASE = "https://api.openweathermap.org/data/2.5"

def _get(path: str, lat: float, lon: float, key: str, units: str) -> dict:
    with httpx.Client(timeout=10.0) as c:                    # never hang forever
        r = c.get(f"{BASE}/{path}",
                  params={"lat": lat, "lon": lon, "appid": key,
                          "units": units, "lang": "en"})
        r.raise_for_status()                                  # 401/403 surface here (Pitfall: key activation)
        return r.json()

def fetch_current(loc, key, units="imperial") -> dict:
    return _get("weather", loc.lat, loc.lon, key, units)

def fetch_forecast(loc, key, units="imperial") -> dict:
    return _get("forecast", loc.lat, loc.lon, key, units)
```
> [CITED: openweathermap.org/current, openweathermap.org/forecast5 — endpoint paths & params]

### Discord delivery with custom identity + internal embed (D-13/D-14)
```python
# channels/discord.py
from discord_webhook import DiscordWebhook, DiscordEmbed
from channels.base import Channel, DeliveryResult

class DiscordWebhookChannel(Channel):
    name = "discord"
    def __init__(self, webhook_url: str, username: str, avatar_url: str | None):
        self._url, self._username, self._avatar = webhook_url, username, avatar_url

    def send(self, text: str) -> DeliveryResult:               # ABC: TEXT ONLY (DELV-03)
        return self._post(text, embed=None)

    def send_briefing(self, text: str, forecast) -> DeliveryResult:  # Discord-only extra
        embed = DiscordEmbed(title=f"Weather — {forecast.location}", color="03b2f8")
        embed.add_embed_field(name="Now", value=forecast.temp_display)
        embed.add_embed_field(name="High / Low", value=f"{forecast.high_display} / {forecast.low_display}")
        embed.add_embed_field(name="Rain", value=f"{forecast.rain_chance}%")
        embed.set_timestamp()
        return self._post(text, embed=embed)

    def _post(self, text, embed) -> DeliveryResult:
        wh = DiscordWebhook(url=self._url, content=text,
                            username=self._username, avatar_url=self._avatar,
                            rate_limit_retry=True)             # honors Discord 429
        if embed is not None:
            wh.add_embed(embed)
        resp = wh.execute()                                    # returns requests.Response
        ok = 200 <= resp.status_code < 300
        return DeliveryResult(ok=ok, detail="" if ok else f"{resp.status_code} {resp.text[:200]}")
```
> [VERIFIED: pypi.org/project/discord-webhook — `DiscordWebhook(url, content, username, avatar_url, rate_limit_retry)`, `DiscordEmbed`, `add_embed_field`, `set_timestamp`, `.execute()` returns a `requests.Response`]
> Embed stays *inside* the Discord channel — it never touches the `Channel.send(text)` interface (DELV-03 satisfied).

### Guarded plain-text render (D-01, no engine needed)
```python
# templates/renderer.py  — PURE, no I/O beyond reading the template text passed in
import string

class _Safe(dict):
    def __missing__(self, key):     # missing placeholder stays visible, never crashes the send
        return "{" + key + "}"

def render(template_text: str, values: dict) -> str:
    # values = whitelisted {temp, high, low, rain, wind, humidity, conditions, location, date}
    return string.Formatter().vformat(template_text, (), _Safe(values))
```
> Avoids `str.format(**d)` format-string abuse by never exposing attribute/index access on real objects — `values` is a flat str→str map. Phase 2's TMPL-02 can add strict missing-field validation; this Phase-1 signature (`render(text, values) -> str`) is the seam Phase 2 extends (D-04).

### Imperial-primary with metric in parens (FCST-04)
```python
# If fetching BOTH units: pair the responses and format
temp_display = f"{round(imp['main']['temp'])}°F ({round(met['main']['temp'])}°C)"
wind_display = f"{round(imp['wind']['speed'])} mph ({round(met['wind']['speed'],1)} m/s)"
# If fetching imperial only + converting:
#   c = round((f - 32) * 5/9); mps = round(mph * 0.44704, 1)
```

## Common Pitfalls

### Pitfall 1: Day boundary computed in UTC / host-local instead of location-local
**What goes wrong:** Today's high/low/rain are aggregated over the wrong set of buckets — off by up to a full day near local midnight, especially for far-offset locations.
**Why it happens:** Reaching for `date.today()` (host clock) or parsing `dt_txt` (UTC ISO) as if local.
**How to avoid:** Offset the unix `dt` by `city.timezone` (seconds) and select buckets whose *local* date equals the location's local *today*. (See aggregation code.)
**Warning signs:** Tests pass in your timezone but a +13/−10 location returns yesterday's or tomorrow's range.

### Pitfall 2: Using current-endpoint `temp_min`/`temp_max` as today's high/low
**What goes wrong:** Briefing shows a tiny high/low spread (they're "at the current moment," not the day) — a silent correctness bug that looks done.
**How to avoid:** Always derive high/low from forecast-bucket aggregation. [VERIFIED: openweathermap.org/current]

### Pitfall 3: The Discord embed leaks into the channel interface
**What goes wrong:** Passing `Forecast`/embed through `Channel.send` couples the interface to Discord and breaks the SMS/Telegram plain-text seam (DELV-03).
**How to avoid:** `send(text)` takes a `str` only; the embed is built and attached *inside* `DiscordWebhookChannel` (e.g. a `send_briefing(text, forecast)` method). The ABC stays text-only.

### Pitfall 4: Mixing units / wrong units in display (FCST-04)
**What goes wrong:** `units` not passed → Kelvin (`"291°"`); or imperial/metric values crossed.
**How to avoid:** Always pass `units`. Decide imperial+metric-fetch vs imperial+convert and apply it consistently; tag persisted rows with `units`.
**Warning signs:** "It's 291 degrees"; wind in m/s under an °F temp.

### Pitfall 5: Secrets in logs/git
**What goes wrong:** API key (in the request URL query string) or webhook URL ends up in a log line, traceback, or git.
**How to avoid:** `.env` + `.gitignore` before first key; never log full request URLs or the webhook URL; redact in structlog. Treat the webhook URL as a credential. [from PITFALLS.md P7]

### Pitfall 6: Clear-sky `KeyError` on `rain`
**What goes wrong:** `item["rain"]["3h"]` crashes on a sunny day because `rain` is absent.
**How to avoid:** Drive rain chance off `pop` (always present); guard any `rain` access with `.get()`. Fixture-test a clear-sky day. [VERIFIED: openweathermap.org/forecast5 — `rain` only present when raining]

### Pitfall 7: New-key 401 misdiagnosed as a code bug
**What goes wrong:** A freshly created OpenWeather key returns 401 for up to ~2 hours while activating; you rewrite working code.
**How to avoid:** On a fresh-key 401, wait and retry before debugging. Document in setup notes. (A startup probe is Phase 5/OPS-02; for Phase 1, surface the 401 clearly.) [from PITFALLS.md P8]

## Runtime State Inventory

> Greenfield phase — no rename/refactor/migration. This section applies only to rename phases; included here to confirm explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore exists yet; Phase 1 *creates* the SQLite store | none |
| Live service config | None | none |
| OS-registered state | None (scheduling/supervision is Phase 3/5) | none |
| Secrets/env vars | `OPENWEATHER_API_KEY`, `DISCORD_WEBHOOK_URL` — new, loaded from `.env` (already gitignored) | create `.env` + `.env.example` |
| Build artifacts | None — greenfield; `uv init` creates `pyproject.toml`/`uv.lock` | none |

**Nothing found in categories 1–3, 5:** verified greenfield (only `.planning/`, `CLAUDE.md`, gitignored `API-key.md`/`.env` exist; no source code).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| OpenWeather One Call 2.5 for daily summaries | Free `2.5/weather`+`2.5/forecast` + bucket aggregation (no card), or One Call 3.0 (card) | 2.5 onecall deprecated/retiring | Phase 1 uses free 2.5 + aggregation per locked decision; do not reference `/data/2.5/onecall` |
| `requests` | `httpx` | ongoing | Cleaner timeout model, async-ready; locked choice |
| pip/Poetry | `uv` | 2025–2026 consensus | Locked tooling |
| Plain columns you back-fill | SQLite raw-JSON + GENERATED columns | SQLite 3.31+ (generated cols) / JSON1 | Add analysis columns later with no migration (DATA-02) |

**Deprecated/outdated:**
- `/data/2.5/onecall` — deprecated; never reference it.
- City-name (`q=`) lookups — deprecated by OpenWeather; Phase 1 uses lat/lon directly (D-05) so this is moot.

## Validation Architecture

> nyquist_validation is ENABLED (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | none yet — add `[tool.pytest.ini_options]` to `pyproject.toml` (Wave 0) |
| Quick run command | `uv run pytest -x -q` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FCST-02 | Buckets → today's high/low/rain on location-local date | unit | `uv run pytest tests/test_aggregate.py -x` | ❌ Wave 0 |
| FCST-02 | Clear-sky day (no `rain`, pop=0) → rain_chance 0, no error | unit | `uv run pytest tests/test_aggregate.py::test_clear_sky -x` | ❌ Wave 0 |
| FCST-02 | Local-midnight boundary (far +/- offset) selects local-today buckets | unit | `uv run pytest tests/test_aggregate.py::test_tz_boundary -x` | ❌ Wave 0 |
| FCST-01 | Client builds correct URL/params; parses current+forecast (mocked httpx) | unit | `uv run pytest tests/test_client.py -x` | ❌ Wave 0 |
| FCST-03/04 | Forecast normalized to imperial-primary display fields | unit | `uv run pytest tests/test_models.py -x` | ❌ Wave 0 |
| DATA-01/03 | Persist writes current + forecast rows from one fetch; raw JSON + normalized cols present | unit | `uv run pytest tests/test_store.py -x` | ❌ Wave 0 |
| DATA-02 | Generated columns queryable; forecast row carries `target_ts_utc` (accuracy-join key) | unit | `uv run pytest tests/test_store.py::test_target_ts -x` | ❌ Wave 0 |
| DELV-02/03 | `Channel.send(text)` takes str; embed never crosses interface (mock webhook) | unit | `uv run pytest tests/test_channel.py -x` | ❌ Wave 0 |
| D-01 | Renderer substitutes `{placeholder}`; missing key stays visible, no crash | unit | `uv run pytest tests/test_renderer.py -x` | ❌ Wave 0 |
| CONF-02 | Secrets load from env/`.env`, absent from config model | unit | `uv run pytest tests/test_config.py -x` | ❌ Wave 0 |
| CONF-04 | `--send-now` composition runs end-to-end (all I/O mocked) | integration | `uv run pytest tests/test_send_now.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest -x -q`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` — testpaths, etc.
- [ ] `tests/conftest.py` — shared fixtures + a tmp SQLite DB fixture
- [ ] `tests/fixtures/` — **recorded OpenWeather JSON** for: clear-sky day, rainy day, far +offset, far −offset, imperial & metric variants (drive FCST-02 per SUMMARY.md)
- [ ] `tests/test_aggregate.py`, `test_client.py`, `test_models.py`, `test_store.py`, `test_channel.py`, `test_renderer.py`, `test_config.py`, `test_send_now.py`
- [ ] Framework install: `uv add --dev pytest` (already in dev deps plan)

## Security Domain

> security_enforcement: true, ASVS level 1, block_on: high.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partial | OpenWeather API key + Discord webhook URL are bearer-style secrets — from `.env`, never committed/logged (CONF-02) |
| V3 Session Management | no | No sessions; single-user CLI/daemon |
| V4 Access Control | no | Single-user, single-tenant local tool |
| V5 Input Validation | yes | Pydantic validates config; OpenWeather payload treated as **untrusted shape** — defensive `.get()` parsing (Pitfall 6); render via guarded substitution (no format-string injection) |
| V6 Cryptography | no (hand-roll) | No custom crypto. Secrets are stored/transmitted, not encrypted by us; TLS via httpx/Discord is the transport |
| V7 Error/Logging | yes | **Never log the API key (in request URL) or webhook URL**; redact in structlog (Pitfall 5/7) |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leak via logged request URL (key in `appid` query) | Information Disclosure | Redact URLs/params in logs; never `print` the full request |
| Secret committed to git (`.env`, webhook URL) | Information Disclosure | `.gitignore` before first key; `.env.example` placeholders; webhook URL treated as credential |
| Format-string / template injection on user-editable template | Tampering / DoS | Guarded substitution over a flat str→str whitelist; never `eval`/raw `.format(**obj)` |
| Malformed/partial OpenWeather payload crashes the run | DoS | Defensive `.get()` parsing; clear-sky `rain`-absent handled; aggregation tolerates empty buckets |
| Discord webhook URL abuse if leaked | Spoofing | Treat as credential; rotate if exposed; out of Phase 1's active threat surface but documented |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | All listed package versions are current & legitimate (PyPI-verified, but slopcheck unavailable this session) | Stack / Legitimacy Audit | LOW — versions confirmed via PyPI JSON API and all are locked, multi-year, high-download packages with known repos; planner may add a verify checkpoint |
| A2 | Generated-column + raw-JSON SQLite schema fully satisfies the "no v2 migration" guarantee | SQLite Schema Design | LOW–MEDIUM — pattern is well-established (cited); if planner prefers plain columns, the migration guarantee still holds *because raw JSON is stored* |
| A3 | Fetching both imperial & metric (4 calls/briefing) is the recommended FCST-04 approach | Stack / Open Questions | LOW — well within quota; converting-in-code is an equally valid alternative the planner may pick |
| A4 | Using payload `city.timezone` offset (not a per-location IANA tz) is sufficient for the Phase-1 local-date boundary | Aggregation / Open Questions | LOW — offset is correct for *today's* boundary; IANA-per-location is a Phase-2 concern (LOC-02). DST edge only bites scheduling (Phase 3), not a single on-demand send |
| A5 | A guarded `str`-substitution renderer (not full Jinja2) best satisfies D-01 while remaining Phase-2-extensible | Stack / Renderer | LOW — both satisfy D-04; the stable `render(text, values)->str` signature is what matters |

## Open Questions

1. **Imperial+metric display: fetch both, or fetch imperial and convert?**
   - What we know: 4 calls/briefing is trivially within quota; converting saves 2 calls but adds conversion code.
   - Recommendation: **fetch both** for correctness/simplicity unless the planner wants minimal calls — then convert (`°C=(°F−32)·5/9`, `m/s=mph·0.44704`). Tag persisted rows with `units` accordingly.

2. **Late-in-the-day fetch with zero remaining local-today forecast buckets — fallback for high/low?**
   - What we know: after the last bucket for local-today, `today_aggregate` returns `high/low = None`.
   - Recommendation: fall back to the current temp for both, OR render "—"/"n/a". Pick one; fixture-test it (edge case #4).

3. **Phase-1 timezone source: payload `city.timezone` offset vs introducing IANA tz now?**
   - What we know: a single on-demand send only needs *today's* local boundary, which the offset gives correctly. IANA-per-location is a locked Phase-2 requirement (LOC-02).
   - Recommendation: use the payload offset in Phase 1; do NOT add a `timezone` config field yet (avoid pre-building Phase 2). If the planner wants the seam, an *optional* per-location tz field is harmless but unused in Phase 1.

4. **Forecast `raw_json`: per-bucket row vs parent-payload + child bucket rows?**
   - Recommendation: **per-bucket rows** (simplest, satisfies D-08/09 directly). Parent/child only if storage ever matters (it won't at this volume).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12+ | Entire phase | unverified (host) | — | Planner: confirm `python3 --version` ≥ 3.12 at Wave 0 |
| uv | Packaging/deps | unverified | — | `pip` + venv if uv absent (locked tooling prefers uv) |
| sqlite3 (stdlib) | Persistence | ✓ (Python stdlib) | bundled | — |
| Network → api.openweathermap.org | Live fetch | unverified | — | Tests use recorded fixtures (no network needed for unit tests) |
| Network → discord.com webhook | Live send | unverified | — | Tests mock the webhook; live send needs a real webhook URL |
| OpenWeather API key | Live fetch | user-provided | — | Unit tests don't need it; live `--send-now` does (note ~2h new-key activation) |
| Discord webhook URL | Live send | user-provided | — | Unit tests mock it |

**Missing dependencies with no fallback:** none for *development/testing* (fixtures + mocks cover it). A live `--send-now` smoke test needs a real API key + webhook URL (user-provided) — not blocking for building/testing the phase.
**Missing dependencies with fallback:** uv → pip+venv; live network → recorded fixtures/mocks.

> Note: package-version verification used the PyPI JSON API (reachable); `pip index versions` returned nothing in this sandbox, and `slopcheck` could not be installed — see Legitimacy Audit.

## Sources

### Primary (HIGH confidence)
- openweathermap.org/current — current endpoint JSON shape, params, units, `temp_min`/`temp_max` "current moment" semantic, `timezone` offset
- openweathermap.org/forecast5 — 5-day/3-hour forecast JSON shape, `list[]` items, `pop` (0–1, every item), `rain.3h` (only when raining), `dt` unix UTC, `dt_txt` ISO UTC, `city.timezone` offset
- pypi.org/project/discord-webhook — `DiscordWebhook(url,content,username,avatar_url,rate_limit_retry)`, `DiscordEmbed`, `add_embed_field`, `set_timestamp`, `.execute()` → `requests.Response`
- PyPI JSON API (2026-06-09) — version checks: httpx 0.28.1, discord-webhook 1.4.1, jinja2 3.1.6, pydantic 2.13.4, pydantic-settings 2.14.1, python-dotenv 1.2.2, structlog 26.1.0, tenacity 9.1.4, ruff 0.15.16, pytest 9.0.3
- Project research docs (`.planning/research/STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md`, `SUMMARY.md`, `FEATURES.md`) — stack, pipeline boundaries, `Channel.send` contract, pitfalls, reconciled endpoint decision

### Secondary (MEDIUM confidence)
- dbpro.app/blog/sqlite-json-virtual-columns-indexing — raw-JSON + generated (virtual) columns + indexing; no back-fill when adding columns
- moldstud.com — SQLite time-series: store unix timestamps, index timestamp columns
- ubos.tech, peter-hoffmann.com (SQLite + JSON) — corroborate the generated-column pattern

### Tertiary (LOW confidence)
- slopcheck — could not be installed this session; package legitimacy relies on PyPI registry confirmation + prior STACK.md vetting

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — locked by CLAUDE.md/STACK.md; versions re-verified against PyPI JSON API
- OpenWeather request/response & aggregation: HIGH — endpoint shapes verified against official docs; algorithm grounded in confirmed field semantics
- SQLite schema: HIGH (pattern) / MEDIUM (specific column choices are planner discretion) — generated-column approach cited; meets the no-migration constraint
- Channel seam & embed isolation: HIGH — discord-webhook API verified; contract follows ARCHITECTURE.md
- Pitfalls: HIGH — inherited from verified PITFALLS.md + official-doc confirmation of `temp_min`/`temp_max` and `rain`-absent

**Research date:** 2026-06-09
**Valid until:** 2026-07-09 (stable stack; OpenWeather endpoint behavior and package versions are slow-moving)
