# Feature Research

**Domain:** Personal scheduled weather-briefing / notification bot (single-user, self-hosted, Discord-first)
**Researched:** 2026-06-09
**Confidence:** HIGH (table stakes / API facts verified against OpenWeather docs and multiple real bot implementations; differentiator/anti-feature framing is MEDIUM — reasoned from the single-user constraint in PROJECT.md plus ecosystem patterns)

## Feature Landscape

The ecosystem splits into two product shapes, and this distinction drives the whole analysis:

1. **Multi-tenant Discord weather bots** (Weather Bot, smmhrdmn/WeatherBot, yannickkirschen/discord-weather-bot, lacanlale/DiscordWeatherBot). These optimize for many users in many servers: slash commands, per-user default locations, anti-spam expiry, interactive setup dashboards.
2. **Personal/self-hosted briefing daemons** (Meshbot_weather on a Raspberry Pi, cron-driven scripts). These optimize for *reliable unattended delivery* to one person.

WeatherBot is firmly the second shape. Many "table stakes" of category 1 (slash commands, interactive dashboards, per-server defaults, anti-spam) are **anti-features** here, because there is no interactive audience — config is a file the owner edits. Table stakes below are scoped to "a personal scheduled briefing tool," not "a public Discord bot."

### Table Stakes (Users Expect These)

Missing any of these and the tool fails its core promise: *a clear, correctly-located briefing for where you'll be today, delivered reliably without intervention.*

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Core forecast content: temp, today's high/low, conditions, rain chance, wind, humidity | This *is* the briefing; PROJECT.md names exactly these six fields | LOW | All available in one OpenWeather One Call 3.0 `daily[0]` object (`temp.max/min`, `weather[].description`, `pop`, `wind_speed`, `humidity`). `pop` is 0–1, multiply by 100 for % |
| Multiple independent locations | Central use case: weekday home city + weekend travel city | LOW | Each location = `{name, lat, lon, units, schedules}`. Resolve city name → lat/lon **once at config time**, not per-call, to save API quota |
| Per-location scheduling, multiple send-times/day, each toggleable | Explicitly required; models the two-city pattern | MEDIUM | Each location owns a list of schedule entries; each entry has time(s) + enabled flag. Toggle = boolean, not deletion (preserves config) |
| Day-of-week awareness | Home Mon–Fri, travel Sat–Sun is the literal use case | MEDIUM | Schedule entry needs a `days` field (e.g. `["mon","tue",...]` or `weekdays`/`weekends`). Without this the two-city split must be done by manual enable/disable toggling — defeats the purpose |
| Correct timezone handling (IANA tz per location) | A "morning" briefing must fire at the location's local 7am, surviving DST | MEDIUM-HIGH | **#1 ecosystem gap.** Store IANA id (`America/Denver`), never fixed UTC offsets. Survives DST automatically. See Pitfalls |
| Units selection (metric/imperial) per location | Fahrenheit-vs-Celsius is a hard expectation; raw Kelvin is unusable | LOW | OpenWeather `units=metric|imperial` does temp **and** wind (m/s vs mph). Make it per-location (travel city may differ) defaulting to one global value |
| Always-on in-process scheduler | "Every morning" reliability can't depend on a laptop being awake | MEDIUM | In-process scheduler (APScheduler-style) on a Pi/server, per Key Decisions. Must compute next run in each location's tz |
| Editable config without code changes | Required constraint; locations/schedules/templates/secrets all file-driven | LOW-MEDIUM | One config file (YAML/TOML) + secrets via env/`.env`. Validate on load and fail loudly on malformed config |
| Discord webhook delivery | v1 channel — free, no per-message cost | LOW | Single HTTPS POST with JSON `{content}` or `{embeds}`. No bot token, no gateway connection needed for outbound-only |
| Retry-then-alert on failure | A missed briefing must be visible, not silent | MEDIUM | Retry API fetch and webhook POST with backoff; if still failing, send a failure notice. See differentiators for where the alert goes |
| Editable message template with placeholders | Explicitly wanted; `{temp}`, `{high}`, `{rain}` etc. | LOW-MEDIUM | Simple string `.format()` / named-placeholder substitution over the forecast dict. Avoid a full template *engine* (anti-feature) |

### Differentiators (Competitive Advantage)

For a personal tool, "differentiator" means *meaningfully improves the daily experience or reliability* without multi-user scope creep. Align to Core Value: reliable, correctly-located, effortless.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Channel abstraction (pluggable delivery interface) | Lets SMS (Twilio) + Telegram slot in without rework; explicitly required design goal | MEDIUM | A `Channel` interface with `send(message)`; Discord is one impl. Keep the interface plain-text-first so SMS works; treat embeds as a Discord-only enrichment |
| Failure alert delivered out-of-band | If Discord is the only channel and Discord is the failing path, the failure alert never arrives — a silent miss | MEDIUM | Send failure alerts via a *different* mechanism than the primary briefing where possible (e.g. a separate webhook, or log+heartbeat). This is the "dead man's switch" insight from monitoring practice |
| Liveness / heartbeat (the daemon proves it's alive) | Distinguishes "no weather today" from "bot crashed days ago." Silence looks identical to death | LOW-MEDIUM | Optional ping to a free uptime service (Healthchecks.io-style) on each successful run, OR a daily "still alive" line. High value for an unattended Pi |
| Human-readable "feels like" + actionable summary (umbrella/coat hints) | Turns data into a decision ("bring a jacket"). OpenWeather 3.0 even offers a summary string | LOW | `feels_like` is in the API. Simple rules (`pop > 0.4 → bring umbrella`, `temp.min < 5 → coat`) add outsized daily value cheaply |
| Sunrise/sunset, UV index, "today's range" extras | Light enrichment that morning-briefing users appreciate | LOW | All in One Call 3.0 `daily[0]` (`sunrise`, `sunset`, `uvi`). Strictly optional template placeholders |
| Config hot-reload / validate-on-edit | Edit schedule, no manual restart; catch typos before a missed briefing | MEDIUM | Watch the config file or provide a `--check` validation command. Reduces the "I edited config and broke tomorrow's briefing silently" failure |
| Single combined briefing per send-window | If two locations fire at the same time, one message beats two pings | LOW | Minor UX nicety; only relevant if multiple locations share a send-time |
| Dry-run / send-now command | Test template + delivery without waiting for 7am | LOW | A `--send-now <location>` invocation. Huge for setup confidence and template iteration |

### Anti-Features (Commonly Requested, Often Problematic)

These are table stakes for *multi-tenant* weather bots but are wrong for this single-user tool. Documenting them prevents importing complexity from the category-1 bots found in research.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Slash commands / interactive Discord bot (gateway connection, command parsing) | Every public Discord weather bot has them | Requires a persistent gateway connection, bot token, command registration, permission scopes — far more than an outbound webhook. There is no interactive audience; the owner edits a file | Outbound webhook only. Config file is the "interface" |
| Web / GUI configuration dashboard | Public bots ship setup dashboards | PROJECT.md explicitly scopes this out — "disproportionate complexity" for one user | File-based config + a `--check` validator and `--send-now` tester |
| Multi-user / per-user defaults / accounts | Standard in category-1 bots (per-server default location, DMs) | This is a single-user tool; accounts, permissions, and per-user state are pure overhead | Single config owner; "locations" replace "users" |
| Anti-spam / alert expiry / rate-of-interaction limits | Public bots auto-expire alerts to avoid spamming dead servers | No spam surface with one consenting recipient. Adds state and logic for a non-problem | None needed; owner controls their own schedules |
| Full templating engine (Jinja2 logic, loops, conditionals in templates) | "Editable templates" can be over-read as needing a DSL | Conditional logic in a user-edited template is a footgun and a maintenance surface; turns config into code | Named placeholder substitution + a small fixed set of derived fields (`{umbrella_hint}`) computed in code |
| Historical weather storage / analytics / trends DB | "It'd be cool to track trends" | PROJECT.md scopes it out — briefings are fire-and-forward, not a warehouse. Adds a DB, retention, schema | Stateless: fetch, format, send, forget |
| Real-time severe-weather push alerts (always-on monitoring beyond schedule) | NWS-style watches/warnings are compelling | PROJECT.md scopes this as future, not core. Requires continuous polling, dedup, alert-state tracking, region matching — a separate product from "morning briefing" | Defer to v2. Note OpenWeather One Call 3.0 *does* include an `alerts` array, so a *passive* "include any active alert in the briefing" is a cheap middle ground (see v1.x) |
| Rich auto-rotating embeds / images / charts | Looks impressive | Couples the message format to Discord and breaks the plain-text channel abstraction needed for SMS | Plain-text-first template; optional Discord embed as a thin presentation layer |

## Feature Dependencies

```
Core forecast content (temp/high/low/conditions/rain/wind/humidity)
    └──requires──> OpenWeather One Call 3.0 fetch + API key

Per-location scheduling (multi-time, toggleable)
    └──requires──> Multiple independent locations
    └──requires──> Correct timezone handling (IANA per location)
                       └──requires──> Always-on in-process scheduler
    └──enhanced-by──> Day-of-week awareness  (the weekday/weekend split)

Units selection (metric/imperial)
    └──requires──> per-location config field (passed to API + template)

Message template with placeholders
    └──requires──> Core forecast content (placeholders map to forecast fields)
    └──enhanced-by──> Derived fields (feels-like, umbrella hint)

Discord webhook delivery
    └──requires──> Channel abstraction interface  (so SMS/Telegram slot in later)

Retry-then-alert on failure
    └──requires──> Channel abstraction (to send the alert)
    └──enhanced-by──> Out-of-band failure channel / heartbeat
                          (so a Discord outage doesn't swallow its own alert)

Editable config without code changes
    └──enables──> locations, schedules, units, templates, secrets
    └──enhanced-by──> validate-on-load + --check + --send-now
```

### Dependency Notes

- **Scheduling requires correct timezone handling:** "Multiple times per day" is meaningless unless each time is anchored to the location's IANA timezone. Build tz-aware scheduling first; bolting it on later forces reworking every stored schedule. This is the single highest-risk ordering decision.
- **Day-of-week awareness rides on the schedule model:** It's a field on the schedule entry, not a separate subsystem — but the schedule data model must include it from day one, or the two-city use case can't be expressed without manual toggling.
- **Retry-then-alert depends on the channel abstraction, and is weakened if it shares the failing channel:** If the only channel is Discord and Discord delivery is what failed, a same-channel alert is also likely to fail. The abstraction should allow a distinct alert sink (even just stderr + a heartbeat ping) so failures are never fully silent.
- **Template placeholders depend on the forecast field set:** Lock the canonical forecast dict (field names) before exposing placeholders, or template syntax churns as fields are renamed.
- **Channel abstraction must be plain-text-first:** SMS has no embeds. If v1 leans on Discord embeds, the abstraction is a fiction. Design the message as text; let Discord optionally upgrade it.

## MVP Definition

### Launch With (v1)

The smallest thing that delivers the Core Value reliably for the two-city user.

- [ ] OpenWeather One Call 3.0 fetch — source of all six required fields in one call
- [ ] Core forecast content (temp, high/low, conditions, rain %, wind, humidity) — the briefing itself
- [ ] Multiple independent locations (≥2) with pre-resolved lat/lon — the central use case
- [ ] Per-location, multi-time, toggleable schedules **with day-of-week** — models weekday/weekend split
- [ ] IANA timezone per location + always-on in-process scheduler — "morning" must mean local morning, DST-safe
- [ ] Units (metric/imperial) per location — Fahrenheit/Celsius is non-negotiable
- [ ] Editable message template with named placeholders — explicitly required
- [ ] Discord webhook delivery behind a channel interface — v1 channel + the abstraction for later
- [ ] Retry-then-alert on fetch/send failure — missed briefing must be visible
- [ ] File-based config (locations, schedules, templates) + secrets via env — required constraint
- [ ] `--send-now` / dry-run + config validation on load — setup confidence; prevents silent broken config

### Add After Validation (v1.x)

- [ ] Heartbeat / liveness ping to a free uptime service — trigger: once it's running unattended on the Pi and you want "is it alive?" certainty
- [ ] Out-of-band failure alert sink — trigger: first time a Discord-side failure swallows its own alert
- [ ] Derived/actionable fields (feels-like, umbrella/coat hint, sunrise/sunset, UV) — trigger: when the bare-data briefing feels too sterile
- [ ] Passive severe-weather line (surface OpenWeather `alerts[]` inside the scheduled briefing) — trigger: cheap win, no new polling loop; do this *before* any real-time alert product
- [ ] Telegram channel (bot token) — trigger: want a second free channel; validates the abstraction
- [ ] Config hot-reload — trigger: editing schedules becomes frequent enough that restarts annoy

### Future Consideration (v2+)

- [ ] SMS via Twilio — defer: paid provider + number setup; only when a push-to-phone need is proven
- [ ] Real-time severe-weather push alerts (continuous monitoring, dedup, alert-state) — defer: a separate product from morning briefing; PROJECT.md scopes it out of core
- [ ] Multi-week / hourly forecast views — defer: outside the "daily morning briefing" promise

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Core forecast content (6 fields) | HIGH | LOW | P1 |
| Multiple independent locations | HIGH | LOW | P1 |
| Per-location multi-time toggleable schedules | HIGH | MEDIUM | P1 |
| Day-of-week awareness | HIGH | LOW-MEDIUM | P1 |
| IANA timezone handling + scheduler | HIGH | MEDIUM-HIGH | P1 |
| Units metric/imperial per location | HIGH | LOW | P1 |
| Editable template (named placeholders) | HIGH | LOW-MEDIUM | P1 |
| Discord webhook behind channel interface | HIGH | LOW-MEDIUM | P1 |
| Retry-then-alert on failure | HIGH | MEDIUM | P1 |
| File config + secrets + validation | HIGH | LOW-MEDIUM | P1 |
| `--send-now` / dry-run tester | MEDIUM-HIGH | LOW | P1 |
| Heartbeat / liveness ping | MEDIUM | LOW-MEDIUM | P2 |
| Out-of-band failure sink | MEDIUM | MEDIUM | P2 |
| Derived/actionable fields (feels-like, hints) | MEDIUM | LOW | P2 |
| Passive severe-weather line (`alerts[]`) | MEDIUM | LOW | P2 |
| Telegram channel | MEDIUM | LOW-MEDIUM | P2 |
| Config hot-reload | LOW-MEDIUM | MEDIUM | P3 |
| SMS via Twilio | MEDIUM | MEDIUM-HIGH | P3 |
| Real-time severe-weather push alerts | MEDIUM | HIGH | P3 |
| Slash commands / GUI / multi-user / history DB | LOW (here) | HIGH | Anti-feature — do not build |

## Competitor Feature Analysis

| Feature | Multi-tenant Discord bots (Weather Bot, smmhrdmn/WeatherBot) | Personal self-hosted daemons (Meshbot_weather, cron scripts) | Our Approach (WeatherBot) |
|---------|------------------------------------------------------------|--------------------------------------------------------------|---------------------------|
| Interaction model | Slash/text commands, interactive dashboard | None — config file, runs headless | File config only (anti-feature: commands) |
| Scheduling | `/addschedule` with time + tz, stored in JSON | cron / interval in config | In-process tz-aware scheduler, per-location, day-of-week |
| Multi-location | Saved locations per user | Single coords (often) or list | First-class, ≥2, independently scheduled |
| Timezone | Per-schedule tz param, 12h/24h | Server local time (DST-fragile) | IANA id per location, DST-safe |
| Units | Often hardcoded (gap observed in smmhrdmn) | Config flag | Per-location metric/imperial |
| Message format | Rich embeds, emoji, dynamic colors | Plain text | Plain-text-first template + optional Discord embed |
| Failure handling | Mostly implicit / none | Varies; Pi reliability focus | Explicit retry-then-alert + heartbeat (v1.x) |
| Severe alerts | NWS integration (some) | Some (Meshbot has alerts) | Passive `alerts[]` line later; no real-time loop in v1 |
| Delivery | Discord gateway + token | Channel-specific | Webhook now, pluggable channel for SMS/Telegram |

## Sources

- [smmhrdmn/WeatherBot](https://github.com/smmhrdmn/WeatherBot) — `/addschedule` time+tz+location model, multi-location, JSON persistence, embeds; units configurability is a notable gap (MEDIUM)
- [yannickkirschen/discord-weather-bot](https://github.com/yannickkirschen/discord-weather-bot), [lacanlale/DiscordWeatherBot](https://github.com/lacanlale/DiscordWeatherBot) — daily scheduled briefing to a channel (MEDIUM)
- [Weather Bot (discordbotlist)](https://discordbotlist.com/bots/weather-bot-3454) — daily/weekly subscriptions, local-tz alert time with 12h/24h, default location persistence, anti-spam expiry (MEDIUM)
- [Meshbot_weather](https://github.com/oasis6212/Meshbot_weather) — Raspberry Pi always-on personal weather bot with alerts + forecast, config-param driven (MEDIUM)
- [OpenWeather One Call API 3.0](https://openweathermap.org/api/one-call-3) — 8-day daily forecast, `temp.max/min`, `pop`, `wind_speed`, `humidity`, `feels_like`, `uvi`, `sunrise/sunset`, `alerts[]`; 1,000 free calls/day (HIGH)
- [OpenWeather units handling](https://openweathermap.org/api/one-call-3) — `units=metric|imperial|standard` controls temp and wind; default is Kelvin (HIGH)
- [Probability of precipitation (`pop`)](https://openweather.co.uk/blog/post/new-probability-precipitation-openweather-forecasts) — `daily.pop` is 0–1 (HIGH)
- [Handling Timezone Issues in Cron Jobs (2025)](https://dev.to/cronmonitor/handling-timezone-issues-in-cron-jobs-2025-guide-52ii), [CronBase timezone guide](https://cronbase.dev/guides/cron-timezone-guide/) — store IANA ids; application-level schedulers handle DST via tz libraries; avoid 1–3 AM on DST dates (HIGH)
- [Heartbeat & Dead Man's Switch alerts (OneUptime)](https://oneuptime.com/blog/post/2026-02-06-heartbeat-dead-man-switch-opentelemetry-pipeline/view) — silent failure is the worst failure; alert via a path independent of the thing being monitored (HIGH, applied as the out-of-band failure-channel recommendation)

---
*Feature research for: personal scheduled weather-briefing bot*
*Researched: 2026-06-09*
