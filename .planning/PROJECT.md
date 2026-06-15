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

## Current Milestone: v1.1 Interactive & Live-Config

**Goal:** Make the running daemon responsive without a restart — answer on-demand
weather requests and pick up config edits live.

**Target features:**
- On-demand command interface (`weather <location>`) for configured locations, available
  both as a local CLI command and as a lightweight Discord bot that replies in-channel —
  WeatherBot's first interactive/inbound surface (v1 was outbound-only).
- Full-config hot-reload: edit schedules, locations, units, or templates and have the
  daemon pick them up via file-watch (auto on save) and/or an explicit trigger, with
  validate-on-load and keep-the-old-config-on-failure so a bad edit never breaks a live daemon.

**Key context for this milestone:**
- The Discord *bot* (inbound) is distinct from the v1 Discord *webhook* (outbound). Receiving
  commands needs a persistent gateway connection + bot token — this flips the v1 "don't use
  discord.py" guidance, which applied only to fire-and-forget webhook sends. The outbound
  briefing path stays on the existing webhook.
- On-demand queries target configured locations only (e.g. `weather home`). Arbitrary /
  geocoded-anywhere lookups are deferred (see Active → future) to keep this milestone scoped.
- CLI lookup should work standalone (one-shot, no running daemon required); the Discord bot
  path lives inside / alongside the long-running daemon.

## Requirements

### Validated

All v1.0 requirements shipped and verified (37/37 — see milestones/v1.0-REQUIREMENTS.md):

- ✓ Fetch forecast data from OpenWeather for a location's lat/lon — v1.0 (Phase 1; migrated to One Call 3.0 in Phase 2)
- ✓ Briefing includes temperature, today's high/low, sky conditions, rain chance, wind, humidity — v1.0 (Phase 1)
- ✓ Imperial-primary values with metric in parentheses, plus per-location units override — v1.0 (Phase 1/2)
- ✓ Feels-like + threshold-driven hints + passive severe-weather alert line — v1.0 (Phase 2)
- ✓ Multiple independent locations (≥2), each with name/lat/lon/IANA tz/units/schedules — v1.0 (Phase 2)
- ✓ Geocode once at config/setup time, never per scheduled send — v1.0 (Phase 2)
- ✓ Pluggable `Channel.send(text)` abstraction; Discord webhook implemented first; plain-text-first — v1.0 (Phase 1)
- ✓ Editable templates with named placeholders; safe substitution, fail-loud on missing field — v1.0 (Phase 2)
- ✓ Per-location scheduling, multiple toggleable send-times, day-of-week selection — v1.0 (Phase 3)
- ✓ Always-on in-process scheduler, local wall-clock firing, DST-safe exactly-once, missed-send catch-up — v1.0 (Phase 3)
- ✓ Retry with bounded backoff (honor Retry-After, never retry 401/403); out-of-band alert; heartbeat; exception isolation — v1.0 (Phase 4)
- ✓ Config-driven settings, secrets from env/.env, validate-on-load fail-loud, `--send-now`/`--check` — v1.0 (Phase 1/2)
- ✓ Persist every fetch to SQLite from day one with an analysis-ready schema, reusing the briefing's calls — v1.0 (Phase 1)
- ✓ Supervised process surviving crash + reboot (systemd `Restart=always`); startup self-check + "online" signal — v1.0 (Phase 5; live reboot confirmed on host `yahir-mint`)

### Active

**Milestone v1.1 (in scope — see REQUIREMENTS.md for the full breakdown):**

- [ ] On-demand command interface (`weather <location>` → reply), CLI + Discord bot, configured locations only — CMD-V2-01
- [ ] Config hot-reload (full config: schedules, locations, units, templates; file-watch + explicit trigger) — ENH-V2-01

**Future candidates (deferred — to be defined in a later milestone):**

- [ ] Telegram delivery channel (validates the channel abstraction with a second free channel) — CHAN-V2-01
- [ ] SMS delivery via Twilio — CHAN-V2-02
- [ ] On-demand lookup for *arbitrary / geocoded-anywhere* locations (extends CMD-V2-01 beyond configured names) — CMD-V2-02
- [ ] Weather-pattern analysis over the v1-persisted SQLite store (trends, history queries) — ANLY-V2-01
- [ ] History query/export interface (e.g. CSV dump) — ANLY-V2-02
- [ ] Optional extra template fields (sunrise/sunset, UV index, today's range) — ENH-V2-02
- [ ] Real-time severe-weather push alerts (continuous monitoring loop) — ENH-V2-03

### Out of Scope

- Web/GUI configuration — config is file-based for a single personal user; a UI adds disproportionate complexity
- Multi-user / accounts — this is a personal single-user tool
- Full multi-user interactive Discord gateway bot — config file is the interface (a lightweight command→reply is tracked separately as CMD-V2-01)
- Full templating engine (logic/loops/conditionals) — named placeholders + code-computed derived fields instead

## Current State

**Shipped v1.0** (2026-06-15) — the complete hands-off morning-briefing daemon. ~7.9k LOC Python across `weatherbot/` + `tests/`; 186 tests green; deployed and running supervised under systemd on host `yahir-mint` (live reboot survival confirmed).

Tech stack as built: Python 3.12+, uv, httpx (OpenWeather One Call 3.0), APScheduler 3.x, tenacity, structlog, SQLite (stdlib), discord-webhook, systemd `Type=notify`. All 37 v1 requirements validated.

**v1.1 in progress** — Phase 6 (Shared Lookup Core & Command Parser) complete (2026-06-15): extracted the read-only fetch→render core into `weatherbot/interactive/lookup.py` and added the surface-agnostic `weather <loc>` parser in `weatherbot/interactive/command.py`; `send_now` now delegates to the shared core. Foundation phase (closes no requirement); 206 tests green. Underpins CMD-01..07 in Phases 7 and 11.

## Context

- Single personal user. Weekday/weekend split between two cities is the central use case
  driving multi-location, per-location scheduling.
- Forecast data comes from the OpenWeather API. v1 migrated to **One Call 3.0** (Phase 2)
  for ready-made daily aggregates + feels-like + alerts — this requires a card-on-file
  One Call subscription, which the operator accepted (reversing the original 2.5-default plan).
- Discord delivery uses a free incoming webhook — no per-message cost — which is why it's
  the v1 channel. SMS would require a paid provider (Twilio) and number setup; Telegram
  requires a bot token. Both are deferred (v2) but fit the same `Channel.send(text)` interface.
- Runs on an always-on machine; scheduling is handled by an in-process scheduler rather than
  relying on the OS being awake at send-time. systemd keeps the *process* alive; the
  in-process scheduler owns the *briefing* timing.
- Known carry-forward: persistence is gated on successful delivery (one persisted round per
  delivered briefing), so a fetch whose delivery ultimately fails is not retained — confirm
  this interpretation holds when v2 analysis (ANLY-V2-01) reads the store.

## Constraints

- **Dependency**: OpenWeather API — requires an API key and is subject to its rate limits and free-tier quotas
- **Delivery**: Discord incoming webhook for v1; channel layer must stay provider-agnostic for SMS/Telegram later
- **Runtime**: Long-running process on an always-on host (server/Pi) with an internal scheduler — must survive across days without manual restarts
- **Reliability**: Network/API calls can fail at send-time; must retry and then alert rather than silently miss a briefing
- **Config**: All user-facing settings (locations, schedules, templates, secrets) must be editable without code changes

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Discord webhook as the first delivery channel | Free, no per-message cost, trivial setup — fastest path to a working end-to-end pipeline | ✓ Phase 1 — `DiscordWebhookChannel`; live end-to-end send verified |
| Pluggable channel abstraction over hardcoding | SMS + Telegram are wanted later; a clean interface avoids rework | ✓ Phase 1 — `Channel.send(text)` seam; embed kept internal; plain-text-first |
| Migrate data source to OpenWeather One Call 3.0 | Cleaner per-day aggregates + feels-like + alerts in one call vs hand-aggregating 2.5 3-hour buckets | ✓ Phase 2 — two-call (imperial+metric) One Call round; 2.5 `aggregate.py` retired (reverses the original CLAUDE.md 2.5-default guidance — operator accepted the One Call 3.0 key requirement) |
| In-process scheduler on an always-on host (not OS cron) | Reliability of "every morning" shouldn't depend on a laptop being awake | ✓ Phase 3 — APScheduler `BackgroundScheduler` + per-location-tz `CronTrigger`; `weatherbot --run` foreground daemon, clean SIGTERM shutdown |
| Per-location schedules with multiple toggleable send-times | Directly models the weekday-home / weekend-travel pattern | ✓ Phase 3 — `[[locations.schedule]]` (time/days/enabled); disabled slots skip registration; UAT-verified |
| Exactly-once delivery via sent-log + atomic claim | A restart, DST transition, or overlapping fire must not double-send or silently miss | ✓ Phase 3 — `(location, send_time, local_date)` idempotency key + atomic `claim_slot`; 90-min startup catch-up; UAT-verified |
| Editable templates with placeholders | User explicitly wants to control message wording | ✓ Phase 2 — regex-only substitution; `validate_template` raises on unknown token at every load |
| Retry-then-alert on failure | A missed briefing should be visible, not silent | ✓ Phase 4 — two-burst tenacity backoff (honors Retry-After, no retry on 401/403) + CRITICAL log/alert on exhaustion |
| Out-of-band alert = conspicuous log + DB row (not a second webhook) | A second Discord webhook isn't independent of a Discord outage | ✓ Phase 4 — `alerts` table + structlog CRITICAL, `INSERT OR IGNORE` dedup (no alert loop) |
| Persist all fetches to SQLite from v1 (analyze in v2) | History only accrues if writing starts now; deferring storage to v2 would discard v1-era data | ✓ Phase 1 — `weather_onecall` rows (raw + normalized) written from the briefing's own fetch (persisted on successful delivery) |
| SQLite as the long-term store | Zero-setup, single-file, ideal for an always-on Pi/server; easy to back up and query later | ✓ Phase 1 — analysis-ready per-location time series |
| Supervise with systemd `Type=notify` + `Restart=always` | READY=1 must reach systemd only after the startup self-check passes, so a bad key/network never reports "active" | ✓ Phase 5 — `gate_until_healthy` blocks `emit_online`/READY=1; live reboot auto-start confirmed on host `yahir-mint` |

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
*Last updated: 2026-06-15 — Phase 6 (Shared Lookup Core & Command Parser) complete*
