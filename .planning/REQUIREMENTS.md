# Requirements: WeatherBot — Milestone v1.1 "Interactive & Live-Config"

**Defined:** 2026-06-15
**Core Value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.

> Scope note: v1.0 shipped 37/37 requirements (see `milestones/v1.0-REQUIREMENTS.md`). This file covers **only milestone v1.1**, which adds an on-demand command interface (CMD-V2-01) and full-config hot-reload (ENH-V2-01) to the running daemon. The dominant constraint is **not regressing v1.0's "the morning briefing always goes out, exactly once" guarantee.**

## Milestone v1.1 Requirements

### On-demand Command Interface (umbrella: CMD-V2-01)

- [x] **CMD-01**: User can run `weather [location]` as a standalone CLI command that prints the briefing for a configured location and exits — with **no running daemon required**.
- [ ] **CMD-02**: User can issue a `weather [location]` command in the Discord channel and receive the briefing as an in-channel reply.
- [x] **CMD-03**: A bare `weather` command (no location argument) returns the briefing for a designated default/primary configured location.
- [x] **CMD-04**: Requesting an unknown / unconfigured location returns a clear error that lists the valid configured location names (no geocoding fallback — configured-locations-only).
- [x] **CMD-05**: The on-demand reply reuses the existing v1 briefing template/format (no separate on-demand format to maintain).
- [ ] **CMD-06**: Repeated on-demand requests for the same location within a short TTL reuse a cached fetch instead of calling OpenWeather again (quota/cost guard for the metered One Call 3.0 API).
- [ ] **CMD-07**: The Discord bot responds only to explicit weather commands and never to its own replies or to the outbound briefing webhook's posts (no feedback loop in the shared channel).
- [ ] **CMD-08**: A failure in the command/bot surface (e.g. gateway disconnect, lookup error) never prevents a scheduled briefing from firing — the bot is isolated from the briefing path.

### Config Hot-Reload (umbrella: ENH-V2-01)

- [x] **CFG-01**: User can edit `config.toml` and template files and have the running daemon apply the changes — to schedules, locations, units, and templates — without a restart.
- [x] **CFG-02**: User can trigger a reload explicitly via a signal (e.g. SIGHUP) and/or a `weatherbot reload` command.
- [ ] **CFG-03**: The daemon auto-detects config/template file saves and reloads automatically (file-watch with debounce to absorb editor save-storms and partial writes).
- [x] **CFG-04**: An invalid config edit is rejected and the daemon keeps running on the previous valid config — validate-and-keep-old, all-or-nothing apply (never a half-applied or broken live state).
- [x] **CFG-05**: A reload re-registers scheduler jobs (add new, remove deleted, update changed) without dropping or double-firing an imminent or already-sent briefing — v1.0's exactly-once guarantee is preserved across reloads.
- [x] **CFG-06**: Each reload outcome (applied, or rejected with reason) is reported via a log line.
- [ ] **CFG-07**: Each reload outcome is also posted to Discord (success summary / rejection reason) so the operator doesn't have to tail logs.
- [x] **CFG-08**: User can validate a config edit without applying it via a `weatherbot --check-config` dry-run subcommand (loads + validates, sends/applies nothing).

## Future Requirements

Deferred to a later milestone. Tracked but not in the v1.1 roadmap.

### Command Interface (extensions)

- **CMD-V2-02**: On-demand lookup for **arbitrary / geocoded-anywhere** locations (extends CMD beyond configured names; needs runtime geocoding + a default-units policy for unknown places).

### Channels

- **CHAN-V2-01**: Telegram delivery channel (second free channel; validates the channel abstraction).
- **CHAN-V2-02**: SMS delivery via Twilio.

### Analysis

- **ANLY-V2-01**: Weather-pattern analysis over the v1-persisted SQLite store (trends, history queries).
- **ANLY-V2-02**: History query/export interface (e.g. CSV dump).

### Enhancements

- **ENH-V2-02**: Optional extra template fields (sunrise/sunset, UV index, today's range).
- **ENH-V2-03**: Real-time severe-weather push alerts (continuous monitoring loop).

## Out of Scope

Explicitly excluded for v1.1. Anti-features from research included with warnings.

| Feature | Reason |
|---------|--------|
| Hot-reloading secrets / the bot token | Secret rotation is a restart boundary; reloading `.env` live adds risk for no real benefit. `DISCORD_BOT_TOKEN` lives in git-ignored `.env` like the v1 webhook URL. |
| Persisting on-demand fetches into the scheduled `weather_onecall` series | Ad-hoc/bursty manual lookups would pollute v1's clean per-location daily time series (the future ANLY-V2-01 analysis target). On-demand lookups are read-only w.r.t. the scheduled series. |
| Per-user cooldown tables / multi-user anti-spam | Single-user personal bot; a short-TTL response cache (CMD-06) is the right quota guard. |
| Two-way config editing via Discord chat | Config remains file-based; the bot reads weather and reports reload outcomes, it does not edit config. |
| Geocoded "weather in <any city>" lookups | Deferred to CMD-V2-02; v1.1 is configured-locations-only to stay scoped. |
| Migrating the briefing scheduler to `AsyncIOScheduler` | Forces an async rewrite of the verified v1 scheduler spine for zero user benefit; the bot runs in its own thread instead. |
| `systemctl reload` / sd_notify RELOADING handshake | Reload is via app trigger + file-watch and never touches the systemd READY gate; exposing `systemctl reload` is unnecessary surface for v1.1 (revisit only if wanted). |

## Traceability

Which phases cover which requirements. Phase numbering continues from v1.0 (Phases 1–5); v1.1 occupies Phases 6–11.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CMD-01 | Phase 7 | Complete |
| CMD-02 | Phase 11 | Pending |
| CMD-03 | Phase 7 | Complete |
| CMD-04 | Phase 7 | Complete |
| CMD-05 | Phase 7 | Complete |
| CMD-06 | Phase 11 | Pending |
| CMD-07 | Phase 11 | Pending |
| CMD-08 | Phase 11 | Pending |
| CFG-01 | Phase 9 | Complete |
| CFG-02 | Phase 9 | Complete |
| CFG-03 | Phase 10 | Pending |
| CFG-04 | Phase 9 | Complete |
| CFG-05 | Phase 9 | Complete |
| CFG-06 | Phase 9 | Complete |
| CFG-07 | Phase 11 | Pending |
| CFG-08 | Phase 9 | Complete |

> Foundation/prerequisite phases without a closing requirement: **Phase 6** (shared lookup core + command parser — underpins CMD-01..05 and CMD-02/06/07) and **Phase 8** (ConfigHolder + `fire_slot` holder refactor — mandatory prerequisite for CFG-01/05).

**Coverage:**

- v1.1 requirements: 16 total
- Mapped to phases: 16 ✓ (every requirement → exactly one phase)
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-15*
*Last updated: 2026-06-15 — roadmap created (v1.1 Phases 6–11); traceability populated*
