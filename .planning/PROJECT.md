# WeatherBot

## What This Is

WeatherBot is a personal, always-on morning weather briefing bot. It pulls forecast
data from the OpenWeather API and delivers a templated daily briefing to the user
across messaging channels (Discord first; SMS and Telegram designed to slot in later).
It is built for one person who splits time between a home city on weekdays and a travel
city on weekends, so each location is configured independently with its own send
schedule.

## Core Value

Every morning, the user reliably receives a clear, correctly-located weather briefing
for the place they'll actually be that day — without lifting a finger.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Fetch current + daily forecast data from the OpenWeather API for a given location
- [ ] Briefing includes temperature, today's high/low, sky conditions, rain chance, wind, and humidity
- [ ] Support multiple configured locations (at least two), each independently configured
- [ ] Per-location scheduling that supports multiple send-times per day, each toggleable on/off
- [ ] Scheduling design accommodates day-of-week awareness (e.g. home Mon–Fri, travel city Sat–Sun)
- [ ] Pluggable delivery channel abstraction; Discord webhook delivery implemented first
- [ ] Channel foundation designed so SMS (Twilio) and Telegram can be added later without rework
- [ ] Editable message templates with placeholders (e.g. `{temp}`, `{high}`, `{rain}`) controlling wording
- [ ] Runs continuously on an always-on machine (server / Raspberry Pi) with its own internal scheduler
- [ ] On OpenWeather or send failure: retry, then alert the user if delivery still fails
- [ ] Config-driven: locations, schedules, channel settings, templates, and API keys live in editable config

### Out of Scope

- SMS and Telegram delivery (v1) — Discord ships first to prove the pipeline; channel abstraction makes these straightforward follow-ups
- Web/GUI configuration — config is file-based for a single personal user; a UI adds disproportionate complexity
- Multi-user / accounts — this is a personal single-user tool
- Historical weather storage / analytics — briefings are fire-and-forward, not a data warehouse
- Severe-weather push alerts beyond scheduled briefings — possible future, not core to the morning-briefing value

## Context

- Single personal user. Weekday/weekend split between two cities is the central use case
  driving multi-location, per-location scheduling.
- Forecast data comes from the OpenWeather API (requires an API key).
- Discord delivery uses a free incoming webhook — no per-message cost — which is why it's
  the v1 channel. SMS would require a paid provider (Twilio) and number setup; Telegram
  requires a bot token. Both are deferred but must fit the same channel interface.
- Intended to run on an always-on machine, so scheduling is handled by an in-process
  scheduler rather than relying on the OS being awake at send-time.

## Constraints

- **Dependency**: OpenWeather API — requires an API key and is subject to its rate limits and free-tier quotas
- **Delivery**: Discord incoming webhook for v1; channel layer must stay provider-agnostic for SMS/Telegram later
- **Runtime**: Long-running process on an always-on host (server/Pi) with an internal scheduler — must survive across days without manual restarts
- **Reliability**: Network/API calls can fail at send-time; must retry and then alert rather than silently miss a briefing
- **Config**: All user-facing settings (locations, schedules, templates, secrets) must be editable without code changes

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Discord webhook as the first delivery channel | Free, no per-message cost, trivial setup — fastest path to a working end-to-end pipeline | — Pending |
| Pluggable channel abstraction over hardcoding | SMS + Telegram are wanted later; a clean interface avoids rework | — Pending |
| In-process scheduler on an always-on host (not OS cron) | Reliability of "every morning" shouldn't depend on a laptop being awake | — Pending |
| Per-location schedules with multiple toggleable send-times | Directly models the weekday-home / weekend-travel pattern | — Pending |
| Editable templates with placeholders | User explicitly wants to control message wording | — Pending |
| Retry-then-alert on failure | A missed briefing should be visible, not silent | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-09 after initialization*
