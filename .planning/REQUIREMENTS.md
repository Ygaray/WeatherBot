# Requirements: WeatherBot — Milestone v1.2 Forecasts, Commands & UV

**Defined:** 2026-06-18
**Core Value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.

> Scope note: v1.0 (37 reqs) and v1.1 (16 reqs) are shipped and validated — see
> `milestones/v1.0-REQUIREMENTS.md` and `milestones/v1.1-REQUIREMENTS.md`. This file
> covers **only** the v1.2 milestone. New categories `FCAST` / `UV` start at 01;
> `CMD` continues from v1.1's last id (CMD-08).

## v1.2 Requirements

Requirements for this milestone. Each maps to exactly one roadmap phase.

### Forecasts (multi-day templates)

- [x] **FCAST-01**: User receives a **weekday forecast** covering Mon–Fri, with per-day high/low, sky condition, and rain chance, rendered from an editable template.
- [x] **FCAST-02**: User receives a **weekend forecast** covering Fri–Sat–Sun, with the same per-day detail, from its own editable template.
- [x] **FCAST-03**: Each forecast type is available in a **detailed variant (default)** and a **compact variant**, selectable on demand via a `--compact` (`+compact`) flag and per scheduled slot in config.
- [x] **FCAST-04**: On-demand forecast commands accept **additive day flags** (e.g. `weekday-forecast +sat`) that append extra named days to the base range.
- [x] **FCAST-05**: User can request any forecast **on demand** from both the CLI and the Discord bot, reusing the shared read-only lookup core so on-demand reads **never write to the persisted SQLite time series**.
- [x] **FCAST-06**: Each forecast type can be **scheduled per-location** with its own toggleable send-time slots (days/times) and chosen variant, fully configurable in `config.toml` with no code changes.
- [x] **FCAST-07**: Forecast rendering reuses the **already-fetched One Call 3.0 `daily` data** — no additional OpenWeather endpoint or extra per-forecast API call.

### UV Index & Proactive Sunscreen Monitor

- [ ] **UV-01**: User can request the **current and maximum-forecasted UV index** for a location on demand (`uv <loc>`, CLI + Discord).
- [ ] **UV-02**: The **daily briefing** includes current UV, today's max forecasted UV, and the **predicted local time UV first crosses the configured sunscreen threshold** (or a clear "stays below threshold" line).
- [x] **UV-03**: User configures a **UV sunscreen threshold** and a **pre-warning lead** in config, editable without code changes.
- [ ] **UV-04**: A **background intraday monitor** polls forecast data on a configurable interval (default ~15 min, bounded well under API limits) for **today's active location(s)** (those with a briefing scheduled today), **during daylight only**.
- [ ] **UV-05**: The monitor delivers a **pre-warning alert** when UV is approaching the threshold (within the configured lead) and a **threshold-reached alert** when UV crosses it — each **at most once per day per location**, posted to Discord.
- [ ] **UV-06**: The UV monitor is **failure-isolated** — its errors never gate, delay, or stop a scheduled briefing (same discipline as the v1.1 inbound bot thread).

### Commands (expanded surface)

All commands below are available on both the CLI and the Discord bot, operate on configured locations, and are subject to the existing operator-id guard ladder.

- [x] **CMD-09**: User can run a **`help` command** that lists and briefly explains all available commands, **auto-generated from the command registry** so it stays current as commands are added.
- [x] **CMD-10**: User can request **active severe-weather alerts** for a location on demand (`alerts <loc>`).
- [x] **CMD-11**: User can **list configured locations** they can query (`locations`).
- [x] **CMD-12**: User can check **bot/daemon status** (`status`) — confirmation the bot is alive plus the next scheduled send time(s).
- [x] **CMD-13**: User can request **sunrise/sunset** times for a location (`sun <loc>`). *(realizes deferred ENH-V2-02)*
- [x] **CMD-14**: User can request **current wind** (speed and direction) for a location (`wind <loc>`).
- [x] **CMD-15**: User can find the **next cloudy day** for a location (`next-cloudy <loc>`) using a **configurable cloud-cover threshold**.
- [x] **CMD-16**: All new commands route through the **same operator-id / command-only guard ladder** as `!weather`, and any command failure stays **isolated from the briefing path**.

## Future Requirements

Deferred to a later milestone. Tracked but not in the v1.2 roadmap.

### Channels

- **CHAN-V2-01**: Telegram delivery channel (validates the channel abstraction with a second free channel)
- **CHAN-V2-02**: SMS delivery via Twilio

### Commands & Analysis

- **CMD-V2-02**: On-demand lookup for *arbitrary / geocoded-anywhere* locations (extends commands beyond configured names)
- **ANLY-V2-01**: Weather-pattern analysis over the v1-persisted SQLite store (trends, history queries)
- **ANLY-V2-02**: History query/export interface (e.g. CSV dump)

### Enhancements

- **ENH-V2-03**: Real-time *severe-weather* push alerts (continuous monitoring loop) — the v1.2 UV monitor establishes the intraday-loop pattern this would extend

## Out of Scope

Explicitly excluded from v1.2. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Geocoded-anywhere lookup for new commands | New commands operate on configured location names only, consistent with v1.1 CMD-01's scope; arbitrary geocoded lookup is deferred (CMD-V2-02) |
| Continuous severe-weather push monitoring | `alerts` is an on-demand pull only; the UV monitor is the sole proactive loop this milestone. Continuous severe-weather push is ENH-V2-03 (deferred) |
| Hourly-granularity forecast output | Multi-day forecasts are daily-granularity (per-day hi/lo/sky/rain/UV), not an hourly breakdown |
| Two-way config editing via commands | `status`/`help` are read-only; the bot reports state, it never mutates config (reaffirms v1.1 project-level decision) |
| New delivery channels | Discord only for v1.2, consistent with v1.0/v1.1; SMS/Telegram remain deferred (CHAN-V2-01/02) |
| Hot-reloading secrets / bot token | Unchanged from v1.1 — secret rotation stays a restart boundary |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CMD-09 | Phase 12 | Complete |
| CMD-10 | Phase 12 | Complete |
| CMD-11 | Phase 12 | Complete |
| CMD-12 | Phase 12 | Complete |
| CMD-13 | Phase 12 | Complete |
| CMD-14 | Phase 12 | Complete |
| CMD-15 | Phase 12 | Complete |
| CMD-16 | Phase 12 | Complete |
| FCAST-01 | Phase 13 | Complete |
| FCAST-02 | Phase 13 | Complete |
| FCAST-03 | Phase 13 | Complete |
| FCAST-04 | Phase 13 | Complete |
| FCAST-05 | Phase 13 | Complete |
| FCAST-06 | Phase 13 | Complete |
| FCAST-07 | Phase 13 | Complete |
| UV-01 | Phase 14 | Pending |
| UV-02 | Phase 14 | In progress (14-02 compute_uv math; briefing render lands in 14-03) |
| UV-03 | Phase 14 | Complete (14-01) |
| UV-04 | Phase 15 | Pending |
| UV-05 | Phase 15 | Pending |
| UV-06 | Phase 15 | Pending |

**Coverage:**

- v1.2 requirements: 21 total
- Mapped to phases: 21 ✓ (Phase 12: 8 · Phase 13: 7 · Phase 14: 3 · Phase 15: 3)
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-18*
*Last updated: 2026-06-19 after v1.2 roadmap creation (phases 12–15 mapped)*
