# Roadmap: WeatherBot

## Milestones

- ✅ **v1.0 WeatherBot MVP** — Phases 1–5 (shipped 2026-06-15) — full details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Interactive & Live-Config** — Phases 6–11 (shipped 2026-06-19) — full details: [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- 🚧 **v1.2 Forecasts, Commands & UV** — Phases 12–15 (in progress)
- 📋 **v2.0** — channels (Telegram/SMS), arbitrary/geocoded lookup, weather-pattern analysis + history export, real-time severe-weather push (planned — define via `/gsd-new-milestone`)

## Phases

**Phase Numbering:**

- Integer phases (6, 7, 8…): Planned milestone work
- Decimal phases (e.g. 9.1): Urgent insertions (marked INSERTED)
- Numbering never restarts across milestones — v1.2 continues from Phase 12

<details>
<summary>✅ v1.0 WeatherBot MVP (Phases 1–5) — SHIPPED 2026-06-15</summary>

- [x] Phase 1: First Briefing End-to-End (4/4 plans) — completed 2026-06-09
- [x] Phase 2: Real Config — Locations, Content & Templates (5/5 plans) — completed 2026-06-10
- [x] Phase 3: Always-On Scheduler (5/5 plans) — completed 2026-06-11
- [x] Phase 4: Retry-then-Alert Reliability (4/4 plans) — completed 2026-06-11
- [x] Phase 5: Deployment & Reboot Survival (3/3 plans) — completed 2026-06-15

Full phase goals, plans, and details archived in [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md).

</details>

<details>
<summary>✅ v1.1 Interactive & Live-Config (Phases 6–11) — SHIPPED 2026-06-19</summary>

**Milestone Goal:** Make the running daemon responsive without a restart — answer on-demand `weather <location>` requests (CLI + Discord bot) and pick up config edits live (file-watch + explicit trigger), all without ever regressing v1.0's "the morning briefing always goes out, exactly once" guarantee.

- [x] Phase 6: Shared Lookup Core & Command Parser (3/3 plans) — completed 2026-06-15
- [x] Phase 7: CLI `weather [location]` One-Shot (3/3 plans) — completed 2026-06-15
- [x] Phase 8: ConfigHolder & `fire_slot` Reads-From-Holder Refactor (4/4 plans) — completed 2026-06-16
- [x] Phase 9: Reload Engine & Explicit Trigger (5/5 plans) — completed 2026-06-16
- [x] Phase 10: File-Watch Auto-Reload (3/3 plans) — completed 2026-06-16
- [x] Phase 11: Discord Inbound Gateway Bot (4/4 plans) — completed 2026-06-19

Full phase goals, plans, success criteria, and details archived in [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md).
Requirements (16/16 satisfied) archived in [milestones/v1.1-REQUIREMENTS.md](./milestones/v1.1-REQUIREMENTS.md).
Audit (passed) in [milestones/v1.1-MILESTONE-AUDIT.md](./milestones/v1.1-MILESTONE-AUDIT.md).

</details>

### 🚧 v1.2 Forecasts, Commands & UV (In Progress)

**Milestone Goal:** Turn WeatherBot from a daily-briefing daemon into a multi-forecast, command-driven assistant with proactive UV/sunscreen guidance — every new output reachable both on a schedule and on demand, reusing the already-fetched One Call 3.0 data and the existing lookup core / guard ladder / scheduler / config-reload spine, never regressing the "morning briefing always goes out, exactly once" guarantee.

- [x] **Phase 12: Command Registry & Read-Only Command Surface** — a self-describing command registry plus `help`/`alerts`/`locations`/`status`/`sun`/`wind`/`next-cloudy` on CLI + Discord, all behind the existing operator guard ladder (completed 2026-06-19)
- [x] **Phase 13: Multi-Day Forecast Templates** — weekday & weekend forecasts (detailed + compact, additive day flags), on demand and per-location scheduled, reusing One Call `daily` (completed 2026-06-19)
- [x] **Phase 14: UV Index — On-Demand & Daily Briefing** — `uv <loc>` command plus current/max UV + threshold-crossing time in the daily briefing, with configurable sunscreen threshold and lead (completed 2026-06-19)
- [x] **Phase 15: Proactive UV Sunscreen Monitor** — a daylight-only intraday poll loop that pre-warns and alerts once/day/location on UV threshold crossing, failure-isolated from briefings (completed 2026-06-19)

## Phase Details

### Phase 12: Command Registry & Read-Only Command Surface

**Goal**: A single self-describing command registry feeds both the CLI and Discord bot, expanding the on-demand command surface to a full set of read-only views over already-available One Call 3.0 data — all routed through the shared lookup core and the existing operator-id / command-only guard ladder, fully isolated from the briefing path.
**Depends on**: Phase 11 (existing bot command surface, lookup core, guard ladder)
**Requirements**: CMD-09, CMD-10, CMD-11, CMD-12, CMD-13, CMD-14, CMD-15, CMD-16
**Success Criteria** (what must be TRUE):

  1. User can run `help` (CLI + Discord) and see an auto-generated, accurate list of every available command with a short explanation that updates when commands are added.
  2. User can run `alerts <loc>`, `locations`, `status`, `sun <loc>`, `wind <loc>`, and `next-cloudy <loc>` (configurable cloud-cover threshold) from both the CLI and the Discord bot and get correct answers for configured locations.
  3. `status` confirms the daemon is alive and reports the next scheduled send time(s).
  4. Every new command is subject to the same operator-id / command-only guard ladder as `!weather`, and any command failure stays isolated from the scheduled briefing path.
  5. New commands read only already-fetched/available data and never write to the persisted SQLite time series.

**Plans**: 3 plans
Plans:

- [x] 12-01-PLAN.md — Command registry + registry-driven parser + One Call/store/config seams (CMD-09/15/16) — completed 2026-06-19
- [x] 12-02-PLAN.md — Read-only command handlers (alerts/sun/wind/next-cloudy/help/locations) + status DaemonState (CMD-10..15)
- [~] 12-03-PLAN.md — Registry-wired Discord dispatch + CLI subparsers + daemon threading (CMD-09..16) — code complete (358 tests green); AWAITING the Task 4 live operator verification on yahir-mint

**UI hint**: no

### Phase 13: Multi-Day Forecast Templates

**Goal**: The user can get a multi-day weekday (Mon–Fri) and weekend (Fri–Sat–Sun) forecast — in a detailed (default) or compact variant, with additive day flags — on demand from the CLI and Discord bot and on a per-location schedule, all rendered from editable templates reusing the One Call 3.0 `daily` array with no extra API call.
**Depends on**: Phase 12 (command registry + guard ladder for the on-demand forecast commands)
**Requirements**: FCAST-01, FCAST-02, FCAST-03, FCAST-04, FCAST-05, FCAST-06, FCAST-07
**Success Criteria** (what must be TRUE):

  1. User receives a weekday forecast (Mon–Fri) and a weekend forecast (Fri–Sat–Sun), each with per-day high/low, sky condition, and rain chance, from its own editable template.
  2. User can select a detailed (default) or compact variant on demand via a `--compact` / `+compact` flag and per scheduled slot in config.
  3. User can append extra named days to a forecast on demand via additive day flags (e.g. `weekday-forecast +sat`).
  4. User can request either forecast on demand from both the CLI and the Discord bot, and these on-demand reads never write to the persisted SQLite time series.
  5. Each forecast type can be scheduled per-location with its own toggleable send-time slots and chosen variant, fully configurable in `config.toml` with no code changes, reusing the already-fetched `daily` data (no additional OpenWeather call).

**Plans**: 5 plans
Plans:

- [x] 13-01-PLAN.md — ForecastDay per-day extraction model + multiday.select_days window/roll-forward selector + 8-day fixture (D-01/D-03)
- [x] 13-02-PLAN.md — Forecast token sets + render_forecast helper + 4 editable detailed/compact templates with sibling line-formats (D-02/D-06)
- [x] 13-03-PLAN.md — Shared +day/-day/+compact flag grammar + ForecastSchedule config model (D-02/D-03/D-05)
- [x] 13-04-PLAN.md — On-demand forecast surface: read-only handler + lookup path + registry specs + widened cache key + CLI/Discord dispatch (FCAST-01..05/07)
- [x] 13-05-PLAN.md — Scheduled per-location forecast slots: namespaced job id + fire_forecast_slot (no-store, isolated) + template validate/watch (FCAST-06)

**UI hint**: no

### Phase 14: UV Index — On-Demand & Daily Briefing

**Goal**: The user gets UV/sunscreen awareness on demand and in the daily briefing — an on-demand `uv <loc>` command plus current UV, today's max forecasted UV, and the predicted local time UV first crosses a configurable sunscreen threshold in the daily briefing — with the threshold and pre-warning lead editable in config without code changes.
**Depends on**: Phase 12 (command registry for `uv <loc>`); informs Phase 15
**Requirements**: UV-01, UV-02, UV-03
**Success Criteria** (what must be TRUE):

  1. User can request the current and maximum-forecasted UV index for a location on demand via `uv <loc>` on both the CLI and the Discord bot.
  2. The daily briefing includes current UV, today's max forecasted UV, and the predicted local time UV first crosses the configured sunscreen threshold (or a clear "stays below threshold" line).
  3. User can set a UV sunscreen threshold and a pre-warning lead in `config.toml`, editable without code changes and picked up by the existing reload path.
  4. UV values reuse the already-fetched One Call 3.0 data with no additional OpenWeather call.

**Plans**: 4 plans
Plans:

- [x] 14-01-PLAN.md — [uv] config table (threshold + lead) + Wave-0 hourly[] fixtures + client hourly[] regression canary (UV-03)
- [x] 14-02-PLAN.md — Pure compute_uv/UvSummary helper: interpolated crossing/window/peak + WHO category, interactive-layer-free for Phase-15 reuse (UV-02)
- [x] 14-03-PLAN.md — Briefing UV line: UV placeholder fields + CANONICAL tokens + threshold-driven sunscreen hint + three editable templates (UV-01/UV-02)
- [x] 14-04-PLAN.md — uv <loc> command: read-only handler (summary + compact hourly line) + registry spec + CLI/Discord dispatch threading config.uv.threshold (UV-01)

**UI hint**: no

### Phase 15: Proactive UV Sunscreen Monitor

**Goal**: A new background intraday monitor watches today's active location(s) during daylight and proactively warns the user before and when UV crosses the sunscreen threshold — at most once per day per location — running failure-isolated from the briefing spine in the same discipline as the v1.1 inbound bot thread.
**Depends on**: Phase 14 (UV render + threshold/lead config) and Phase 11 (failure-isolated background-thread pattern)
**Requirements**: UV-04, UV-05, UV-06
**Success Criteria** (what must be TRUE):

  1. A background monitor polls forecast data on a configurable interval (default ~15 min, bounded well under API limits) for today's active location(s) — those with a briefing scheduled today — during daylight only.
  2. User receives a pre-warning alert when UV is approaching the threshold (within the configured lead) and a threshold-reached alert when UV crosses it, each posted to Discord.
  3. Each alert fires at most once per day per location (no spam across poll cycles).
  4. The monitor's errors never gate, delay, or stop a scheduled briefing — verifiably isolated like the v1.1 bot thread.

**Plans**: 3 plans
Plans:

- [x] 15-01-PLAN.md — Extend UvConfig (monitor knobs) + uv_alerts dedup table/helpers + promote fires_on + Wave-0 dependency canary (UV-04/05/06) ✅ 2026-06-19 (3 tasks, 7 files)
- [x] 15-02-PLAN.md — uvmonitor.py tick: active-today/daylight gates + read-only fetch (no persist) + three once/day/location decision branches + failure isolation (UV-04/05/06) ✅ 2026-06-19 (3 tasks, 2 files, 559 green)
- [x] 15-03-PLAN.md — Daemon wiring: register __uvmonitor__ IntervalTrigger job (gated, max_instances=1) + reconcile exclusion (like __heartbeat__) + scheduler-level UV-06 isolation proof (UV-04/06) ✅ 2026-06-19 (2 auto tasks, 3 files, 565 green) — live daylight-crossing UAT on host yahir-mint pending operator (UV-05 end-to-end; deferrable non-halting)

**UI hint**: no

### 📋 v2.0 (Planned)

To be defined via `/gsd-new-milestone`. Candidate goals (see PROJECT.md → Requirements → Future candidates):
Telegram + SMS channels (CHAN-V2-01/02), arbitrary/geocoded `weather <any city>` lookup (CMD-V2-02), weather-pattern analysis + history/CSV export over the v1 SQLite store (ANLY-V2-01/02), real-time severe-weather push alerts (ENH-V2-03 — extends the v1.2 UV intraday-loop pattern).

## Progress

**Execution Order:** Phases execute in numeric order. v1.0: 1 → 5. v1.1: 6 → 11. v1.2: 12 → 15. v2.0 continues from 16.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. First Briefing End-to-End | v1.0 | 4/4 | ✅ Complete | 2026-06-09 |
| 2. Real Config — Locations, Content & Templates | v1.0 | 5/5 | ✅ Complete | 2026-06-10 |
| 3. Always-On Scheduler | v1.0 | 5/5 | ✅ Complete | 2026-06-11 |
| 4. Retry-then-Alert Reliability | v1.0 | 4/4 | ✅ Complete | 2026-06-11 |
| 5. Deployment & Reboot Survival | v1.0 | 3/3 | ✅ Complete | 2026-06-15 |
| 6. Shared Lookup Core & Command Parser | v1.1 | 3/3 | ✅ Complete | 2026-06-15 |
| 7. CLI `weather [location]` One-Shot | v1.1 | 3/3 | ✅ Complete | 2026-06-15 |
| 8. ConfigHolder & `fire_slot` Refactor | v1.1 | 4/4 | ✅ Complete | 2026-06-16 |
| 9. Reload Engine & Explicit Trigger | v1.1 | 5/5 | ✅ Complete | 2026-06-16 |
| 10. File-Watch Auto-Reload | v1.1 | 3/3 | ✅ Complete | 2026-06-16 |
| 11. Discord Inbound Gateway Bot | v1.1 | 4/4 | ✅ Complete | 2026-06-19 |
| 12. Command Registry & Read-Only Command Surface | v1.2 | 3/3 | Complete    | 2026-06-19 |
| 13. Multi-Day Forecast Templates | v1.2 | 5/5 | Complete    | 2026-06-19 |
| 14. UV Index — On-Demand & Daily Briefing | v1.2 | 4/4 | Complete    | 2026-06-19 |
| 15. Proactive UV Sunscreen Monitor | v1.2 | 3/3 | Complete    | 2026-06-19 |
