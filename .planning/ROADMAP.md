# Roadmap: WeatherBot

## Overview

WeatherBot grows from a single correct briefing into a hands-off, always-on daemon. The journey starts by proving the whole pipeline end-to-end — config + secrets, an OpenWeather fetch with bucket-aggregation, long-term SQLite persistence of every fetch, an imperial-primary render, and a Discord webhook send — all triggerable on demand via `--send-now` (Phase 1). From that working slice we widen to real configuration: multiple independent locations with per-location IANA timezones and units, richer briefing content (hints + severe-weather), and editable templates (Phase 2). Next we turn the manual pipeline into a daemon with tz-aware, day-of-week, idempotent scheduling that survives DST and restarts (Phase 3), then wrap it in retry-then-alert reliability with an independent alert path and heartbeat (Phase 4), and finally make it survive reboots under a supervisor with a startup self-check (Phase 5). Foundational concerns — IANA timezone in the data model, secrets-from-env, the plain-text channel interface, and the analysis-ready persistence schema — are baked in from Phase 1 because retrofitting them is a migration, not a tweak.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: First Briefing End-to-End** - On-demand `--send-now` delivers one correct briefing to Discord and persists the fetch to SQLite
- [x] **Phase 2: Real Config — Locations, Content & Templates** - Multiple independent locations with units, rich content, and editable templates (verification 2026-06-10: passed 5/5 — units-override gap closed in 02-05, live UAT passed, security 12/12 closed; see 02-VERIFICATION.md) (completed 2026-06-10)
- [x] **Phase 3: Always-On Scheduler** - Briefings fire automatically at each location's local time, DST-safe and never duplicated (verification 2026-06-11: passed 5/5 — DST transition-band catch-up + exactly-once delivery closed in 03-04/03-05, UAT 8/8 passed, security 18/18 closed; see 03-VERIFICATION.md) (completed 2026-06-11)
- [ ] **Phase 4: Retry-then-Alert Reliability** - Transient failures retry; a missed briefing surfaces an alert and the daemon stays alive
- [ ] **Phase 5: Deployment & Reboot Survival** - The bot runs supervised, survives reboot, and self-checks on startup

## Phase Details

### Phase 1: First Briefing End-to-End

**Goal**: A single correct, correctly-located weather briefing is fetched, persisted to a long-term SQLite store, rendered imperial-primary, and delivered to Discord on demand — the complete pipeline proven in one vertical slice, with weather history accruing from the very first fetch.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: FCST-01, FCST-02, FCST-03, FCST-04, DATA-01, DATA-02, DATA-03, DELV-01, DELV-02, DELV-03, CONF-02, CONF-04
**Success Criteria** (what must be TRUE):

  1. Running `--send-now <location>` posts a weather briefing to the configured Discord channel for that location
  2. The briefing shows current temperature, today's high/low, sky conditions, rain chance, wind, and humidity, with values imperial-primary and metric in parentheses (e.g. `72°F (22°C)`)
  3. Today's high/low and rain chance are derived by aggregating the free 2.5 forecast's 3-hour buckets for the location's local date (not the current-moment min/max), and a clear-sky day with no `rain` field renders without error
  4. The OpenWeather API key and Discord webhook URL are read from `.env`/environment and are absent from the committed config and from git
  5. The message is plain-text-first and is sent through a `Channel.send(text)` interface with Discord as the one concrete implementation
  6. After a send, the fetch is recorded as a row in a local SQLite store — capturing the location, fetch time (UTC + local), the raw OpenWeather payload, and the normalized briefing fields — and that row is written from the same fetch the briefing used (no extra OpenWeather call solely to persist)
  7. The SQLite schema is designed up front as a queryable per-location time series so the deferred v2 weather-pattern analysis can read it without a data migration

**Plans**: 4 of 4 complete — 01-01 (config/secrets), 01-02 (weather data layer), 01-03 (SQLite store + renderer/templates), 01-04 (Channel/Discord + `--send-now` composition; live-send human-verified)

> **Schema-up-front note:** DATA-02 is a foundational design concern on par with IANA timezone and secrets-from-env. Getting the persistence schema right in Phase 1 — a per-location, time-indexed table that retains raw payload plus normalized fields — avoids a v2 migration when analysis (ANLY-V2-01/02) reads this store. The data layer (`weather/`) owns the write; persistence is wired in at or immediately after the fetch so every fetch (manual now, scheduled from Phase 3) is captured from day one.

### Phase 2: Real Config — Locations, Content & Templates

**Goal**: The user can configure two or more independent locations — each with its own name, lat/lon, IANA timezone, and units — receive a fully-featured briefing (with actionable hints and any active severe-weather line), and control the wording through a safe editable template.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: LOC-01, LOC-02, LOC-03, FCST-05, FCST-06, TMPL-01, TMPL-02, CONF-01, CONF-03, CONF-05
**Success Criteria** (what must be TRUE):

  1. The user can define at least two independent locations in the config file (no code changes), each with name, lat/lon, IANA timezone, and an optional per-location units override, and `--send-now` produces the correct briefing for each
  2. City-name → lat/lon resolution happens once at config/setup time, so scheduled sends never spend an API call geocoding
  3. The briefing includes "feels like" plus simple threshold-driven hints (e.g. rain chance > 40% → bring an umbrella) and surfaces any active severe-weather alert for the location, with no separate monitoring loop
  4. The user can edit the message template with named placeholders (`{temp}`, `{high}`, `{low}`, `{rain}`, `{wind}`, `{humidity}`, `{conditions}`, `{hint}`); substitution runs no arbitrary logic and a missing field fails loudly at validation rather than rendering blank
  5. Running `--check` validates the config and reports malformed input loudly without sending anything**Plans**: 5 of TBD planned — vertical slices (One Call 3.0 migration ordered first as the foundation):

**Wave 1**

- [x] 02-01-PLAN.md — Wave 0: One Call 3.0 + geocoding test fixtures, scaffold tests/test_cli.py, retire 2.5 aggregate.py

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md — One Call 3.0 data-source migration: client + Forecast mapping (feels_like/hint/alert) + weather_onecall store; 2-call send_now

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03-PLAN.md — Config (timezone/units validators + ≥2 locations) + template placeholder validation wired at every load

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 02-04-PLAN.md — --check and --geocode CLI subcommands

**Wave 5** *(gap closure — blocked on Wave 4 completion)*

- [x] 02-05-PLAN.md — Gap closure: honor per-location units override end-to-end (metric→metric-primary) + WR-01 null-feels_like hint guard

### Phase 3: Always-On Scheduler

**Goal**: The manual pipeline becomes an always-on daemon that fires each location's briefings at the right local wall-clock time, honoring day-of-week selection, surviving DST, recovering missed sends, and never sending a slot twice.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: SCHD-01, SCHD-02, SCHD-03, SCHD-04, SCHD-05, SCHD-06, SCHD-07
**Success Criteria** (what must be TRUE):

  1. Each location can carry multiple send-times per day, each individually toggleable on/off without being deleted, and each with a day-of-week selection (e.g. home Mon–Fri, travel city Sat–Sun)
  2. A send fires at the location's local wall-clock time computed per-location IANA timezone, and a location in a different timezone fires at its own local time
  3. Across a simulated DST transition, a morning send fires exactly once (no skipped spring-forward miss, no doubled fall-back send)
  4. After downtime that spanned a send-time, the bot sends the missed briefing once on recovery (within the defined grace window) rather than silently skipping it
  5. Restarting the process mid-morning produces exactly one briefing per `(location, schedule-slot, local-date)` — the idempotency key prevents restart replay and DST double-fire

**Plans**: 3 plans + 2 gap-closure (03-04, 03-05)
Plans:
**Wave 1**

- [x] 03-01-PLAN.md — Wave 1: Schedule config model + Location.schedule, days parser, sent_log idempotency table + was_sent/record_sent, test scaffold (SCHD-01/02/03/07-store)
- [x] 03-02-PLAN.md — Wave 1: ScheduleContext + schedule_placeholders, {sent_at}/{checked_at}/{schedule_note} canonical extension, send_now threading, template footers (SCHD-04 display)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-03-PLAN.md — Wave 2: daemon spine — plan_catchup 90-min recovery, run_daemon foreground lifecycle + fire_slot, per-location-tz CronTrigger firing, weatherbot --run (SCHD-05/06, SCHD-03 DST exactly-once)

**Gap closure** *(from 03-VERIFICATION.md — run via `/gsd-execute-phase 03 --gaps-only`)*

- [x] 03-04-PLAN.md — DST transition-band fix: plan_catchup builds the scheduled instant via datetime(...).replace(tzinfo=tz), round-trip-detects+skips the spring-forward gap, compares aware instants; transition-band tests (02:30 gap / 01:30 fold) (SCHD-04 DST half / SC#3)
- [x] 03-05-PLAN.md — Exactly-once delivery: atomic claim_slot (INSERT OR IGNORE + rowcount==1) gating delivery before the network send + release_claim on failure; fire_slot rewired; concurrent-double-fire test asserts one POST (SCHD-07 / SC#5)

### Phase 4: Retry-then-Alert Reliability

**Goal**: Transient fetch and send failures recover automatically without burning quota, a genuinely-failed briefing produces a visible out-of-band alert, the daemon distinguishes liveness from silence, and one bad run can never kill the loop.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: RELY-01, RELY-02, RELY-03, RELY-04, RELY-05, RELY-06
**Success Criteria** (what must be TRUE):

  1. A transient fetch or send failure is retried with bounded exponential backoff that honors `Retry-After`, while an auth failure (401/403) is never retried
  2. With Discord deliberately broken, the user still receives a "briefing missed" alert via a path independent of the failing primary channel, and the alert does not loop
  3. An injected exception in one scheduled job is logged with a traceback and the scheduler keeps running — other jobs still fire
  4. The bot emits a heartbeat/liveness signal (per successful run or daily) so a prolonged silence is distinguishable from a crash

**Plans**: 4 plans in 2 waves

**Wave 1** *(foundation — parallel, no file overlap)*

- [ ] 04-01-PLAN.md — Retry engine foundation: gated `tenacity` add (legitimacy checkpoint) + `weatherbot/reliability/` two-burst Retrying builder, transient/auth classifier, capped Retry-After parser, reason taxonomy + `tests/test_reliability.py` Wave-0 scaffold (RELY-01/02, D-07/08)
- [ ] 04-02-PLAN.md — Durable state + config: `alerts` + `heartbeat` tables/helpers (record/resolve/stamp, INSERT-OR-IGNORE dedup) + `Reliability` load-validated retry-config model + documented `[reliability]` TOML (RELY-03/04/05, D-03/05/09/11/13)

**Wave 2** *(wiring — parallel, daemon vs cli)*

- [ ] 04-03-PLAN.md — Daemon patient path: wrap `fire_slot` in the two-burst retry (interruptible via stop_event), reason-taxonomy alerts + CRITICAL log + resolve-on-success, hardened exception isolation (internal_error + traceback), periodic heartbeat IntervalTrigger tick (RELY-01..06, D-04/05/06/08/10/11/12/13)
- [ ] 04-04-PLAN.md — Manual tight path: `--send-now` short bounded retry (terminal-only, NO alerts/heartbeat rows) + `--check` surfaces the resolved retry budget (RELY-01, D-09/10)

### Phase 5: Deployment & Reboot Survival

**Goal**: The bot runs as a supervised long-running process that comes back automatically after a crash or host reboot and announces itself online only after confirming its config and API key are good.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: OPS-01, OPS-02
**Success Criteria** (what must be TRUE):

  1. After a host reboot, the bot restarts automatically under a supervisor (systemd `Restart=always` / container `restart: always`) without manual intervention
  2. On startup the bot self-checks that config is valid and the OpenWeather key is reachable, failing loudly and distinguishably (e.g. key-not-yet-active vs. genuine auth error) when it is not
  3. On a healthy start the bot emits an "online" signal, so a silent death after deploy or reboot is detectable

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. First Briefing End-to-End | 4/4 | ✅ Complete (verified) | 2026-06-09 |
| 2. Real Config — Locations, Content & Templates | 5/5 | ✅ Complete (verified) | 2026-06-10 |
| 3. Always-On Scheduler | 5/5 | ✅ Complete (verified) | 2026-06-11 |
| 4. Retry-then-Alert Reliability | 0/4 | Planned | - |
| 5. Deployment & Reboot Survival | 0/TBD | Not started | - |
