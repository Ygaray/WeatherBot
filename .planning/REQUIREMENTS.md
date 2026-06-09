# Requirements: WeatherBot

**Defined:** 2026-06-09
**Core Value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Forecast

- [ ] **FCST-01**: System fetches weather from the free OpenWeather 2.5 endpoints (current + 5-day/3-hour forecast) for a location's lat/lon
- [ ] **FCST-02**: System aggregates 3-hour forecast buckets into today's high, low, and rain chance for the location's local date
- [ ] **FCST-03**: Briefing includes temperature, today's high/low, sky conditions, rain chance, wind, and humidity
- [ ] **FCST-04**: Values display imperial-primary with metric in parentheses (e.g. `72°F (22°C)`, `8 mph (3.6 m/s)`)
- [ ] **FCST-05**: Briefing includes derived actionable hints — "feels like" plus umbrella/coat guidance from simple thresholds (e.g. rain chance > 40% → bring an umbrella)
- [ ] **FCST-06**: Briefing surfaces any active severe-weather alert for the location (passive, no separate monitoring loop)

### Locations

- [ ] **LOC-01**: User can configure multiple independent locations (at least two)
- [ ] **LOC-02**: Each location is configured with a name, lat/lon, IANA timezone, optional units override, and its own schedules
- [ ] **LOC-03**: City-name → lat/lon resolution happens once at config/setup time, not per scheduled call (protects API quota)

### Scheduling

- [ ] **SCHD-01**: Each location owns its own schedule entries, supporting multiple send-times per day
- [ ] **SCHD-02**: Each schedule entry can be toggled on/off without deleting it
- [ ] **SCHD-03**: Each schedule entry supports day-of-week selection (e.g. home Mon–Fri, travel city Sat–Sun)
- [ ] **SCHD-04**: Each send-time fires at the location's local wall-clock time and survives DST transitions (IANA timezone)
- [ ] **SCHD-05**: An always-on in-process scheduler computes the next run per location timezone
- [ ] **SCHD-06**: After downtime, the bot sends any missed briefing on recovery (always send late)
- [ ] **SCHD-07**: A send is idempotent per `(location, schedule-slot, local-date)` so a slot is never sent twice (prevents DST double-fire and restart replay)

### Delivery

- [ ] **DELV-01**: System delivers briefings via a Discord incoming webhook (v1 channel)
- [ ] **DELV-02**: Delivery sits behind a pluggable channel interface (`send(text)`), with Discord as one implementation, so SMS/Telegram can be added later without rework
- [ ] **DELV-03**: Messages are plain-text-first (SMS-compatible); any Discord embed is an optional presentation enrichment only

### Templating

- [ ] **TMPL-01**: User can edit the message template using named placeholders (e.g. `{temp}`, `{high}`, `{low}`, `{rain}`, `{wind}`, `{humidity}`, `{conditions}`, `{hint}`)
- [ ] **TMPL-02**: Placeholder substitution is safe — no arbitrary logic/loops in templates, and a missing field fails loudly at validation rather than silently producing blanks

### Reliability

- [ ] **RELY-01**: Weather fetch and channel send retry with bounded exponential backoff on transient failure
- [ ] **RELY-02**: Auth failures (401/403) are never retried; the bot honors `Retry-After` on rate limits
- [ ] **RELY-03**: If delivery still fails after retries, the bot alerts the user that a briefing was missed
- [ ] **RELY-04**: The failure alert is delivered out-of-band — via a path independent of the failing primary channel — so a Discord outage can't swallow its own alert
- [ ] **RELY-05**: The bot emits a heartbeat/liveness signal (per successful run or daily) so silence is distinguishable from a crash
- [ ] **RELY-06**: Each scheduled job is exception-isolated so one bad run cannot kill the scheduler loop

### Configuration & Operation

- [ ] **CONF-01**: All user-facing settings (locations, schedules, units, templates) live in an editable config file — no code changes required
- [ ] **CONF-02**: Secrets (OpenWeather API key, Discord webhook URL) are loaded from the environment / `.env`, never stored in the config file or committed to git
- [ ] **CONF-03**: Config is validated on load and fails loudly on malformed input
- [ ] **CONF-04**: User can run `--send-now <location>` to send a briefing immediately for setup/testing
- [ ] **CONF-05**: User can run a `--check` command to validate config without sending
- [ ] **OPS-01**: The bot runs as a long-running supervised process that survives crashes and host reboot (e.g. systemd `Restart=always` / container `restart: always`)
- [ ] **OPS-02**: On startup the bot self-checks (config valid + OpenWeather key reachable) and emits an "online" signal so a silent death is detectable

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Channels

- **CHAN-V2-01**: Telegram delivery channel (bot token) — validates the channel abstraction with a second free channel
- **CHAN-V2-02**: SMS delivery via Twilio — paid provider + number setup

### Interaction

- **CMD-V2-01**: On-demand command interface — user sends a text command (e.g. `weather <location>`) and WeatherBot replies with a current briefing on demand, in addition to the scheduled briefings. (Lightweight request→reply, not a full multi-user gateway bot.)

### Enhancements

- **ENH-V2-01**: Config hot-reload (edit schedules without restart)
- **ENH-V2-02**: Optional extra template fields (sunrise/sunset, UV index, today's range)
- **ENH-V2-03**: Real-time severe-weather push alerts (continuous monitoring loop, dedup, alert-state) — a separate product from the morning briefing

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Full multi-user interactive Discord bot (gateway + token, command registration, per-server state) | Single-user tool; config file is the interface. NOTE: a lightweight on-demand command→reply interface is wanted later and tracked as **CMD-V2-01**, distinct from a full gateway bot |
| Web / GUI configuration dashboard | Disproportionate complexity for a single personal user; file config + `--check`/`--send-now` covers it |
| Multi-user / accounts / per-user defaults | Single-user tool; "locations" replace "users" |
| Historical weather storage / analytics DB | Briefings are fire-and-forward, not a data warehouse |
| Full templating engine (logic, loops, conditionals) | Conditional logic in user-edited templates is a footgun; named placeholders + code-computed derived fields instead |
| Rich auto-rotating embeds / images / charts | Couples the message to Discord and breaks the plain-text channel abstraction needed for SMS |
| One Call 3.0 as the default data source | Requires a credit card on file even on its free tier; free 2.5 + bucket-aggregation is the v1 default (3.0 remains an optional later upgrade) |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| _(to be filled by roadmapper)_ | — | Pending |

**Coverage:**
- v1 requirements: 30 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 30 ⚠️

---
*Requirements defined: 2026-06-09*
*Last updated: 2026-06-09 after initial definition*
