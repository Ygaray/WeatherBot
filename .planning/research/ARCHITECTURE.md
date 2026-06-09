# Architecture Research

**Domain:** Always-on, config-driven scheduled-briefing bot (multi-location, multi-channel)
**Researched:** 2026-06-09
**Confidence:** HIGH

## Standard Architecture

This is a textbook **scheduler → producer → renderer → dispatcher** pipeline wrapped around a
config layer, with a cross-cutting reliability concern (retry-then-alert). Every component
has a single job and a narrow interface, which is what keeps SMS/Telegram pluggable later.

The system is a single long-running process. There is no web server, no database, no user
accounts — state lives in config files plus a small in-memory cache. Treat it as a daemon.

### System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         CONFIG LAYER (load + validate at boot)     │
│   config.yaml/.toml  +  .env (secrets)  ──►  typed Config object   │
│   locations[]  schedules[]  channels[]  templates{}  api_key       │
└───────────────────────────────┬──────────────────────────────────┘
                                 │ (validated config injected once)
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                         SCHEDULER (in-process, always-on)          │
│  expands  locations × send-times × day-of-week × tz  into jobs     │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐                      │
│  │ job: Home  │ │ job: Home  │ │ job: Travel│  ... fires send_job()│
│  │ 07:00 M–F  │ │ 18:00 M–F  │ │ 08:00 S–S  │     at wall-clock    │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘                      │
└────────┼──────────────┼──────────────┼────────────────────────────┘
         └──────────────┴──────────────┘
                        ▼  send_job(location, channels, template)
┌──────────────────────────────────────────────────────────────────┐
│  WEATHER DATA LAYER          │  TEMPLATE RENDERER                  │
│  fetch(location) ──► Forecast│  render(template, Forecast) ──► str │
│  ┌────────────────────────┐  │  substitutes {temp} {high} {rain}…  │
│  │ TTL cache / dedup       │  │  pure, no I/O                       │
│  │ keyed by (lat,lon)      │  │                                     │
│  └─────────┬──────────────┘  └──────────────┬──────────────────────┘
│            │ HTTP (OpenWeather)              │ message text         │
└────────────┼─────────────────────────────────┼──────────────────────┘
             ▼                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                    CHANNEL DISPATCH (pluggable)                    │
│   Channel interface: send(message) -> DeliveryResult              │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│   │ DiscordWebhook│  │ TwilioSMS    │  │ TelegramBot  │            │
│   │   (v1)        │  │  (later)     │  │  (later)     │            │
│   └──────────────┘  └──────────────┘  └──────────────┘            │
└───────────────────────────────┬──────────────────────────────────┘
                                 │ wrapped by
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│        RELIABILITY (cross-cutting): retry-then-alert              │
│  retry(fetch) , retry(send)  → on final failure → ALERT channel   │
└──────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **Config layer** | Load file + secrets, validate shape, produce typed objects. Fail loudly at boot, never at send-time. | Pydantic models over YAML/TOML; secrets from `.env` / env vars via `python-dotenv` |
| **Scheduler** | Own wall-clock. Expand `locations × send-times × days × tz` into concrete jobs; fire `send_job` callbacks. Knows nothing about weather or channels. | `APScheduler` `BackgroundScheduler` (or `BlockingScheduler`) with one `CronTrigger` per send-time |
| **Weather data layer** | Given a location, return a normalized `Forecast` object. Hide OpenWeather endpoint/HTTP/JSON. Cache + dedup across locations sharing a time. | `requests`/`httpx` client + TTL cache keyed by `(lat,lon)` |
| **Template renderer** | Given a template string + `Forecast`, produce final message text. Pure function, no I/O. | `str.format_map` with a safe dict, or Jinja2 if richer logic wanted |
| **Channel dispatch** | Abstract "send this text somewhere." One class per provider implementing a shared `Channel` interface. | Webhook POST (Discord), Twilio SDK (SMS), Telegram Bot API (Telegram) |
| **Reliability wrapper** | Retry transient failures with backoff; on exhaustion, route an alert to the user. Cross-cuts fetch and dispatch. | `tenacity` decorators/retrying + a dedicated alert channel |
| **Composition root / `main`** | Wire everything: load config → build data layer + channels → register jobs → start scheduler → block forever. | A thin `app.py` / `__main__.py` |

## Recommended Project Structure

```
weatherbot/
├── __main__.py            # entrypoint: load config, wire deps, start scheduler, block
├── config/
│   ├── models.py          # Pydantic models: Config, Location, ScheduleSlot, ChannelConfig
│   └── loader.py          # read YAML/TOML + .env, validate, return typed Config
├── scheduler/
│   └── runner.py          # build APScheduler jobs from config; defines send_job()
├── weather/
│   ├── client.py          # OpenWeather HTTP calls
│   ├── cache.py           # TTL cache / dedup keyed by (lat,lon)
│   └── models.py          # Forecast dataclass (temp, high, low, sky, rain, wind, humidity)
├── templates/
│   └── renderer.py        # render(template_str, forecast) -> str ; placeholder map
├── channels/
│   ├── base.py            # Channel ABC: send(message) -> DeliveryResult
│   ├── discord.py         # DiscordWebhookChannel  (v1)
│   ├── sms.py             # TwilioSmsChannel        (later)
│   ├── telegram.py        # TelegramChannel         (later)
│   └── factory.py         # build_channel(config) -> Channel  (registry by "type")
├── reliability/
│   └── retry.py           # retry policy (tenacity) + alert dispatch on failure
└── config.example.yaml    # documented sample config the user copies & edits
.env.example               # OPENWEATHER_API_KEY, DISCORD_WEBHOOK_URL, etc.
```

### Structure Rationale

- **`config/` isolates loading + validation** so the rest of the app receives only typed,
  already-valid objects. No component re-parses raw config or re-reads `.env`.
- **`scheduler/` depends on everything but is depended on by nothing** — it is the orchestrator
  edge. The `send_job` callback is the one place fetch → render → dispatch are composed.
- **`weather/`, `templates/`, `channels/` are sibling, independent units.** None imports another.
  This is what lets you build/test them in isolation and swap channels freely.
- **`channels/factory.py` + `base.py` are the pluggability seam.** Adding SMS/Telegram means
  adding one file and one registry entry — zero changes elsewhere. This is the load-bearing
  design decision for the project's stated "no rework" requirement.
- **`reliability/` is cross-cutting**, so it lives apart and is applied *around* fetch and send
  rather than baked into them.

## Architectural Patterns

### Pattern 1: Config-as-jobs expansion (declarative schedule → concrete triggers)

**What:** At boot, walk the config and register one scheduler job per
`(location, send-time, day-of-week set, timezone)` tuple. The config is the source of truth;
the scheduler holds derived state only.
**When to use:** Whenever schedule lives in editable config and must support day-of-week and
multiple toggleable send-times per location — exactly this project.
**Trade-offs:** Re-reading config requires re-registering jobs (restart or a reload hook).
Acceptable for a single-user file-config tool; simpler than a dynamic job store.

**Example:**
```python
for loc in config.locations:
    for slot in loc.schedule:
        if not slot.enabled:
            continue
        scheduler.add_job(
            send_job,
            trigger=CronTrigger(
                hour=slot.hour, minute=slot.minute,
                day_of_week=slot.days,        # e.g. "mon-fri" or "sat,sun"
                timezone=loc.timezone,        # per-location tz, not host tz
            ),
            args=[loc, config.channels, config.template],
            id=f"{loc.name}-{slot.hour:02d}{slot.minute:02d}-{slot.days}",
        )
```

> **Timezone note (HIGH confidence):** APScheduler's `CronTrigger` accepts a per-job
> `timezone`. Set it per *location*, not from the host clock — the home and travel cities may
> differ, and the user wants "weather for where they'll be." Never schedule in naive local time.

### Pattern 2: Channel interface (Strategy pattern over delivery providers)

**What:** A single abstract contract every provider implements. The dispatch step holds a list
of `Channel` objects and calls `send()` without knowing which provider it is.
**When to use:** Multiple interchangeable delivery backends, added incrementally — the core
"pluggable channels" requirement.
**Trade-offs:** Slight upfront abstraction cost; pays for itself the moment the second channel
lands. Keep the contract minimal so Discord/SMS/Telegram can all satisfy it honestly.

**Example:**
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class DeliveryResult:
    ok: bool
    detail: str = ""        # error text / message id, for logging + alerting

class Channel(ABC):
    name: str               # "discord", "sms", "telegram" — for logs/alerts

    @abstractmethod
    def send(self, message: str) -> DeliveryResult:
        """Deliver final message text. Must not raise for expected failures —
        return DeliveryResult(ok=False, detail=...). May raise only on bugs."""
```

> **Contract rules that keep it pluggable:**
> 1. Input is **already-rendered text** (a `str`), never a `Forecast`. Channels do not format.
> 2. Output is a `DeliveryResult`, not `None`/exception — the reliability layer decides retries
>    from `ok`, uniformly across providers.
> 3. Construction (webhook URL, Twilio creds, bot token) happens in the **factory** from config;
>    the interface itself takes no provider-specific args.
> 4. Channels are **stateless per-send** and hold only their own credentials/endpoint.

### Pattern 3: Fetch dedup + TTL cache keyed by coordinates

**What:** Cache `Forecast` by `(lat, lon)` with a short TTL. If two locations share the same
send-time (or the same place is configured twice), one API call serves both.
**When to use:** Any time multiple jobs can fire near-simultaneously against a rate-limited or
quota-limited API. OpenWeather's free tier is 60 calls/min and 1M/month; data updates only
every ~10 min, so caching is free accuracy-wise and protects the quota.
**Trade-offs:** Stale-within-TTL data, which is fine for a briefing (10-min source cadence).
Keep TTL ≤ source update interval (e.g. 10 min).

**Example:**
```python
# weather/cache.py
def get_forecast(loc) -> Forecast:
    key = (round(loc.lat, 3), round(loc.lon, 3))
    cached = _cache.get(key)               # honors TTL
    if cached:
        return cached
    forecast = client.fetch(loc)           # one HTTP call
    _cache.set(key, forecast, ttl=600)
    return forecast
```

## Data Flow

### Request Flow (the send pipeline)

```
[Scheduler fires CronTrigger at wall-clock for a location]
    ↓
send_job(location, channels, template)
    ↓
weather.get_forecast(location)        ─► cache hit? return : HTTP fetch ─► Forecast
    ↓                                       (wrapped in retry)
templates.render(template, forecast)  ─► final message text  (pure, no I/O)
    ↓
for channel in channels:
    channel.send(text)                ─► DeliveryResult       (wrapped in retry)
    ↓
if not result.ok after retries:
    alert_channel.send("WeatherBot: briefing for <loc> failed: <detail>")
```

Direction is strictly **one-way**: scheduler → data → render → dispatch → (on failure) alert.
No component calls "upstream." Config flows *into* construction only, once, at boot.

### State Management

```
config files + .env  ──(boot, validate once)──►  immutable Config object
                                                       │
                              ┌────────────────────────┴───────────────┐
                              ▼                                         ▼
                     scheduler job registry                  in-memory TTL forecast cache
                     (derived from config)                   (only mutable runtime state)
```

There is **no persistent application state** beyond config. The forecast cache is the sole
mutable runtime state and is disposable (lost on restart, repopulated on next fetch). This is a
deliberate simplicity win — no DB, no migrations, no state corruption to recover from.

### Key Data Flows

1. **Boot flow:** read config file + `.env` → validate into typed `Config` → build weather
   client, channel objects (via factory), alert channel → expand schedule into jobs → start
   scheduler → block forever.
2. **Send flow:** trigger → fetch (cached) → render → dispatch to each channel → on exhausted
   retry, alert. (Detailed above.)
3. **Secrets flow:** API key + webhook URL/token live in `.env`/env vars, read *only* by the
   config loader, injected into the weather client and channel factory at construction. Secrets
   never appear in the YAML config the user edits, never in logs, never in templates.

## Scaling Considerations

This is a single-user personal tool; "scale" means **number of locations × send-times**, not users.

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1–5 locations, a few send-times (target) | In-process `BackgroundScheduler`, in-memory cache — the design above, nothing more |
| Dozens of jobs | Still fine; APScheduler handles many cron jobs. Ensure cache TTL is set so simultaneous jobs dedup against the 60/min limit |
| Many locations / very frequent sends | Watch the 1M/month + 60/min OpenWeather caps; cache dedup is the lever. Only then consider a persistent job store or batching |

### Scaling Priorities

1. **First bottleneck: OpenWeather quota/rate limit**, not CPU. Mitigation already in design:
   TTL cache + coordinate-keyed dedup. Round coordinates so "same city" collapses to one call.
2. **Second bottleneck: process longevity** (memory leaks, dropped network over days). Mitigation:
   keep the process stateless-ish, add a supervisor (systemd / `Restart=always`) so a crash or
   the host rebooting auto-restarts the daemon. This is an ops concern, not a code redesign.

## Anti-Patterns

### Anti-Pattern 1: OS cron instead of an in-process scheduler

**What people do:** Schedule sends with system `cron` and a one-shot script.
**Why it's wrong:** The project explicitly wants reliability independent of OS wakefulness and a
single always-on process; cron fragments state, complicates per-location timezones, and makes
retry/alert and shared caching awkward. PROJECT.md already rules this out.
**Do this instead:** One long-running process with APScheduler; supervise it with systemd for
auto-restart.

### Anti-Pattern 2: Channels that format their own messages

**What people do:** Pass the `Forecast` (or raw API JSON) into each channel and let Discord/SMS
build its own text.
**Why it's wrong:** Formatting logic duplicates across providers and drifts; the editable-template
requirement gets violated; testing explodes.
**Do this instead:** Render once in the template layer to a `str`; channels receive only final
text. (Discord-specific niceties like embeds can be an *optional* channel capability layered on
top, but plain text must always work.)

### Anti-Pattern 3: Validating config lazily / scattering `os.getenv` everywhere

**What people do:** Read env vars and config fields ad hoc deep inside fetch/send code.
**Why it's wrong:** A typo or missing key surfaces at 7am as a silently missed briefing instead
of at boot. Secrets leak across modules.
**Do this instead:** Load + validate everything once at startup (Pydantic), fail loudly with a
clear message if anything is missing/malformed, and inject typed config into constructors.

### Anti-Pattern 4: Retry without an alert ceiling (or alert via the failing path)

**What people do:** Retry forever, or send the failure alert through the same channel that just
failed.
**Why it's wrong:** Infinite retries hide outages; alerting via the broken channel means the user
never learns of the failure.
**Do this instead:** Bounded retries with backoff (`tenacity` `stop_after_attempt` +
`wait_exponential`); route the final alert through a **designated alert channel** (ideally the
most reliable one, e.g. the Discord webhook) and log it regardless.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **OpenWeather** | HTTPS GET, API key in query param. v1 should use the **no-credit-card free endpoints**: current weather `GET /data/2.5/weather` + 5-day/3-hour `GET /data/2.5/forecast` (60 calls/min, 1M/month). | Today's high/low and rain-chance come from aggregating the 3-hour forecast buckets for the local day. One Call 3.0 gives daily summaries directly but **requires a credit card** even on the free 1k/day tier — defer it. Wrap behind `weather/client.py` so the endpoint choice is swappable. Data refreshes ~every 10 min → set cache TTL accordingly. |
| **Discord** | Incoming webhook: HTTPS POST JSON `{"content": "..."}` to the webhook URL. | Free, no SDK needed (`requests`/`httpx`). v1 channel. 2000-char content limit; respect `429` Retry-After. |
| **Twilio (SMS, later)** | Twilio Python SDK; account SID + auth token + from-number from config. | Per-message cost; concise templates matter. Drops into `channels/sms.py` behind the same `Channel` interface. |
| **Telegram (later)** | Bot API `sendMessage` with bot token + chat id. | Free; token in `.env`. Drops into `channels/telegram.py`, same interface. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| config loader → everything | Typed `Config` object injected at construction | One-way; nothing reads raw config later |
| scheduler → send pipeline | Direct call: `send_job(location, channels, template)` | The single composition point of fetch/render/dispatch |
| send_job → weather layer | `get_forecast(location) -> Forecast` | Cache/dedup hidden behind this call |
| send_job → renderer | `render(template, forecast) -> str` | Pure function boundary |
| send_job → channels | `channel.send(text) -> DeliveryResult` | The pluggability seam; uniform across providers |
| reliability ↔ fetch/dispatch | Decorator/wrapper around the two I/O calls | Cross-cutting; channels/fetch stay retry-agnostic and just report `ok` |

## Suggested Build Order

Dependency-driven, each step independently testable, end-to-end pipeline reachable early:

1. **Config layer** (`config/`) — models + loader. Everything depends on typed config; build it
   first so later components receive real objects. Testable with sample YAML + `.env`.
2. **Weather data layer** (`weather/`) — client + `Forecast` model (cache can be a stub first).
   Verifiable in isolation by fetching one location and printing the normalized `Forecast`.
3. **Template renderer** (`templates/`) — pure function; trivially unit-testable against a
   fixture `Forecast`. No dependencies beyond the `Forecast` model.
4. **Channel interface + Discord** (`channels/base.py`, `discord.py`, `factory.py`) — define the
   contract, then implement only Discord. This is the moment the abstraction must be right.
5. **Composition: `send_job`** — wire fetch → render → dispatch for a single location. Now you
   have a manually-invokable end-to-end briefing. Ship-able as a CLI "send now" before scheduling.
6. **Scheduler** (`scheduler/`) — expand config into cron jobs calling `send_job`. Turns the
   manual pipeline into the always-on daemon. Depends on 1–5 being done.
7. **Reliability** (`reliability/`) — wrap fetch + dispatch with `tenacity`; add the alert path.
   Layered last because it wraps existing, working calls.
8. **Cache/dedup** in `weather/cache.py` — promote the stub from step 2 to a real TTL cache once
   multiple locations/times exist. (Can be pulled earlier if convenient.)
9. **Later channels** (`sms.py`, `telegram.py`) — post-v1, each a single file behind the existing
   interface, proving the abstraction.

> **Why this order:** config → leaf services (weather, render, channel) → composition (send_job)
> → scheduler → reliability. The end-to-end "send one briefing now" milestone is reachable at
> step 5, *before* scheduling — the highest-value early checkpoint. Reliability and dedup are
> deliberately last because they wrap already-working code rather than block it.

## Sources

- [APScheduler CronTrigger docs — day_of_week, per-job timezone, scheduler types](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html) — HIGH (official)
- [APScheduler User Guide — BackgroundScheduler vs BlockingScheduler](https://apscheduler.readthedocs.io/en/3.x/userguide.html) — HIGH (official)
- [OpenWeather 5-day/3-hour forecast endpoint](https://openweathermap.org/api/forecast5) — HIGH (official)
- [OpenWeather API overview / free access (no credit card) limits](https://openweathermap.org/api) — HIGH (official)
- [OpenWeather One Call 3.0 (requires subscription/card)](https://openweathermap.org/api/one-call-3) — HIGH (official)
- [OpenWeatherMap Free Tier Limits 2026 — 60/min, 1M/month, 429 enforcement](https://apiscout.dev/guides/openweathermap-free-tier-limits-2026) — MEDIUM (third-party, corroborates official)
- [Tenacity retry library (exponential backoff, stop conditions)](https://github.com/jd/tenacity) — HIGH (official repo)
- [Tenacity documentation](https://tenacity.readthedocs.io/) — HIGH (official)

---
*Architecture research for: scheduled multi-location multi-channel briefing bot*
*Researched: 2026-06-09*
