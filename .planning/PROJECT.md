# WeatherBot

## What This Is

WeatherBot is a personal, always-on morning weather briefing bot. It pulls forecast
data from the OpenWeather API and delivers a templated daily briefing to the user
across messaging channels (Discord first; SMS and Telegram designed to slot in later).
It is built for one person who splits time between a home city on weekdays and a travel
city on weekends, so each location is configured independently with its own send
schedule. As of v1.1 it is also interactive and live-editable — the user can ask for a
location's briefing on demand (standalone CLI or an in-channel Discord `!weather` command)
and edit config/templates while the daemon picks them up live, with no restart.

## Core Value

Every morning, the user reliably receives a clear, correctly-located weather briefing
for the place they'll actually be that day — without lifting a finger.

## Current Milestone: v1.2 Forecasts, Commands & UV

**Goal:** Turn WeatherBot from a daily-briefing daemon into a multi-forecast,
command-driven assistant with proactive UV/sunscreen guidance — every new output
reachable both on a schedule and on demand.

**Target features:**
- Multi-day forecast templates — weekday (Mon–Fri) and weekend (Fri–Sat–Sun), each in
  detailed (default) and compact (`--compact`) variants, with additive day flags
  (e.g. `weekday-forecast +sat`); on-demand (CLI + Discord) and fully-configurable
  per-location schedule slots. Reuses One Call 3.0's `daily` array (no new fetch).
- UV index + proactive sunscreen monitor — on-demand `uv <loc>`; daily briefing gains
  current UV, max forecasted UV, and the predicted time UV crosses a configurable
  sunscreen threshold; a new daylight-only intraday monitor loop (poll ~15 min,
  configurable) watching today's active location(s) that pre-warns (configurable lead)
  and alerts on threshold crossing, once/day/location, failure-isolated from briefings.
  (Realizes deferred ENH-V2-02.)
- Expanded command surface (CLI + Discord, operator-guarded) — `help` (auto-generated
  command list), `alerts`, `locations`, `status`, `sun`, `uv`, `wind`, and `next-cloudy`
  (configurable cloud-cover threshold); existing `weather <loc>` retained.

The original v2.0 candidates (Telegram/SMS channels, geocoded-anywhere lookup, SQLite
weather-pattern analysis/export) stay deferred to a later milestone.

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

All v1.1 requirements shipped and verified (16/16 — see milestones/v1.1-REQUIREMENTS.md):

- ✓ On-demand `weather [location]` standalone CLI (no daemon), bare-`weather` default, unknown→configured-names error, reuses v1 template — v1.1 (Phase 7; CMD-01/03/04/05)
- ✓ Discord `!weather <location>` in-channel reply with short-TTL cache, command-only guard ladder (no feedback loop), failure-isolated from the briefing path — v1.1 (Phase 11; CMD-02/06/07/08)
- ✓ Config hot-reload (schedules, locations, units, templates) without restart via SIGHUP / `weatherbot reload`; validate-and-keep-old, all-or-nothing apply; exactly-once preserved across reloads; `check-config` dry-run — v1.1 (Phase 8 holder prereq + Phase 9; CFG-01/02/04/05/06/08)
- ✓ Auto-reload on file save (debounced file-watch absorbing editor save-storms) — v1.1 (Phase 10; CFG-03)
- ✓ Each reload outcome posted to Discord (success summary / rejection reason) — v1.1 (Phase 11; CFG-07)

### Active

**Milestone v1.2 Forecasts, Commands & UV** — requirements defined in REQUIREMENTS.md
(grouped under FCAST / UV / CMD categories). Realizes deferred ENH-V2-02 (UV index +
sunrise/sunset fields). See REQUIREMENTS.md for the scoped list and traceability.

**Future candidates (deferred — to be defined in a later milestone):**

- [ ] Telegram delivery channel (validates the channel abstraction with a second free channel) — CHAN-V2-01
- [ ] SMS delivery via Twilio — CHAN-V2-02
- [ ] On-demand lookup for *arbitrary / geocoded-anywhere* locations (extends CMD-V2-01 beyond configured names) — CMD-V2-02
- [ ] Weather-pattern analysis over the v1-persisted SQLite store (trends, history queries) — ANLY-V2-01
- [ ] History query/export interface (e.g. CSV dump) — ANLY-V2-02
- [ ] Real-time severe-weather push alerts (continuous monitoring loop) — ENH-V2-03 (the v1.2 UV monitor establishes the intraday-loop pattern this would extend)

### Out of Scope

- Web/GUI configuration — config is file-based for a single personal user; a UI adds disproportionate complexity
- Multi-user / accounts — this is a personal single-user tool
- Full multi-user interactive Discord gateway bot — config file is the interface; the v1.1 bot is a single-operator command→reply surface only (operator-id guarded), not a multi-user bot
- Full templating engine (logic/loops/conditionals) — named placeholders + code-computed derived fields instead
- Hot-reloading secrets / the bot token — secret rotation is a restart boundary; `DISCORD_BOT_TOKEN` lives in git-ignored `.env` like the v1 webhook URL (v1.1 decision)
- Two-way config editing via Discord chat — config stays file-based; the bot reads weather and reports reload outcomes, it does not edit config (v1.1 decision)
- Migrating the briefing scheduler to `AsyncIOScheduler` — the verified sync scheduler spine stays; the inbound bot runs in its own thread instead (v1.1 decision)

## Current State

**Shipped v1.1** (2026-06-19) — the interactive, live-editable evolution of the daemon. ~13.5k LOC Python across `weatherbot/` + `tests/`; 291 tests green; deployed and running supervised under systemd on host `yahir-mint` (inbound Discord bot + live reload confirmed live, including a UAT-found PID-file/RuntimeDirectory startup fix).

Tech stack as built: Python 3.12+, uv, httpx (OpenWeather One Call 3.0), APScheduler 3.x, tenacity, structlog, SQLite (stdlib), discord-webhook (outbound), **discord.py** (inbound gateway bot, new in v1.1), **watchfiles** (file-watch, new in v1.1), **cachetools** (forecast TTL cache, new in v1.1), systemd `Type=notify`. All 37 v1.0 + 16 v1.1 requirements validated.

**v1.1 delivered** (Phases 6–11): a single shared read-only fetch→render core (`interactive/lookup.py`) feeds both a standalone `weatherbot weather [location]` CLI one-shot and an isolated Discord `!weather` gateway bot (`interactive/bot.py`, off-loop fetch + TTL cache + guard ladder, started after the systemd READY signal and torn down in `finally` so it can never stop a briefing). Config hot-reload is owned by a lock-guarded `ConfigHolder` of immutable snapshots; `_do_reload` validates → atomic-swaps → diff-reconciles jobs by stable id, keeping the old config on any failure and preserving exactly-once across reloads (the sent-log key moved name→stable `location.id`). Reloads trigger via SIGHUP / `weatherbot reload` / debounced file-watch, ship a `check-config` dry-run, and post each outcome to Discord.

**Known tech debt** (non-blocking, tracked in milestones/v1.1-MILESTONE-AUDIT.md): Phase 9 advisory hardening (`/proc`-absent guard fails open on non-Linux; rollback re-invokes the same `_register_jobs`); `[bot] operator_id` and `[reload] watch` are read once at startup so changing them needs a restart (within CFG-01's enumerated scope — schedules/locations/units/templates are all live).

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
| File-watch as a thin trigger over the Phase 9 reload engine (`watchfiles`, flag-set-only) | Auto-reload on save should reuse the trusted validate/swap/reconcile/keep-old path, not re-implement reload; the observer must never run reload on its own thread | ✓ Phase 10 — `watchfiles` directory-watch (non-recursive, `.env` excluded) → `request_reload()` sets the existing `reload_requested` Event; reload runs on the main thread; live watch-set re-derive (D-04); chose `watchfiles` over `watchdog` for built-in debounce |
| One shared read-only fetch→render core for every on-demand surface | CLI and Discord bot must give identical answers with no duplicated fetch/render/error logic; on-demand reads must not pollute the scheduled time series | ✓ Phase 6 — `interactive/lookup.py` (`lookup_weather`); provably zero store writes; `send_now` delegates byte-identically; both CLI and bot route through it |
| `weatherbot` as a real installed console command (argparse subcommands) | A daemon-free one-shot needs a first-class entry point, not a `--flag` on the daemon | ✓ Phase 7 — hatchling `[build-system]` + `[project.scripts]`; `weather`/`run`/`check`/`send-now`/`geocode` subcommands; 0/1/2/3 exit contract; quiet-by-default |
| Live config behind a lock-guarded `ConfigHolder` of immutable snapshots; `fire_slot` reads `holder.current()` once per job | A reload must change what unchanged jobs render without races or torn reads; per-job snapshot keeps an in-flight briefing consistent | ✓ Phase 8 — all 5 config models `frozen=True`; lock-free `current()` / lock-guarded `replace()`; concurrent-swap + mid-job-snapshot tests |
| Validate → atomic swap → diff-reconcile, keep-old on any failure | A bad edit must never half-apply or break a live daemon; identical config must produce zero job churn | ✓ Phase 9 — `_do_reload` two-phase apply with rollback; jobs reconciled by stable `(location, send_time, days)` id; shared offline `validate_config_and_templates`; `check-config` dry-run |
| Move the exactly-once key from mutable `location.name` to stable `location.id` (raw-name default, zero migration) | Renaming a location or shifting its tz during a reload must not double-fire or skip an already-sent slot | ✓ Phase 9 — `location.id` at all sent-log/alert + catchup callsites in lockstep; byte-identical rows; SC#4 exactly-once-across-reload test |
| Inbound Discord bot in its own thread, isolated from the briefing path | Receiving commands needs a persistent gateway + bot token (flips v1's webhook-only stance), but bot health must never gate or stop a briefing | ✓ Phase 11 — `BotThread` started after systemd READY, torn down in `finally`, swallows all failures; off-loop fetch via `run_in_executor`; short-TTL `ForecastCache`; operator-id + `author.bot` guard ladder (no feedback loop) |
| Reload outcomes posted to Discord best-effort | The operator shouldn't have to tail logs to know a reload applied or why it was rejected | ✓ Phase 11 — `_do_reload` posts success summary / rejection reason on both branches; a failed post never aborts the reload |

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
*Last updated: 2026-06-18 — started milestone v1.2 Forecasts, Commands & UV*
