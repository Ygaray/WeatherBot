# Roadmap: WeatherBot

## Milestones

- ✅ **v1.0 WeatherBot MVP** — Phases 1–5 (shipped 2026-06-15) — full details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Interactive & Live-Config** — Phases 6–11 (shipped 2026-06-19) — full details: [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- 📋 **v2.0** — channels (Telegram/SMS), arbitrary/geocoded lookup, weather-pattern analysis + history export, extra template fields, real-time severe-weather push (planned — define via `/gsd-new-milestone`)

## Phases

**Phase Numbering:**

- Integer phases (6, 7, 8…): Planned milestone work
- Decimal phases (e.g. 9.1): Urgent insertions (marked INSERTED)
- Numbering never restarts across milestones — the next milestone continues from Phase 12

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

### 📋 v2.0 (Planned)

To be defined via `/gsd-new-milestone`. Candidate goals (see PROJECT.md → Requirements → Future candidates):
Telegram + SMS channels (CHAN-V2-01/02), arbitrary/geocoded `weather <any city>` lookup (CMD-V2-02), weather-pattern analysis + history/CSV export over the v1 SQLite store (ANLY-V2-01/02), extra template fields (ENH-V2-02), real-time severe-weather push alerts (ENH-V2-03).

## Progress

**Execution Order:** Phases execute in numeric order. v1.0: 1 → 5. v1.1: 6 → 11. v2.0 continues from 12.

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
