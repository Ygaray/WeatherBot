# Roadmap: WeatherBot

## Milestones

- ✅ **v1.0 WeatherBot MVP** — Phases 1–5 (shipped 2026-06-15) — full details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Interactive & Live-Config** — Phases 6–11 (shipped 2026-06-19) — full details: [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Forecasts, Commands & UV** — Phases 12–15 (shipped 2026-06-20) — full details: [milestones/v1.2-ROADMAP.md](./milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Discord Control Panel** — Phases 16–20 (shipped 2026-06-27) — full details: [milestones/v1.3-ROADMAP.md](./milestones/v1.3-ROADMAP.md)
- ✅ **v2.0 Bot Module Extraction ("The Great Decoupling")** — Phases 21–28 (shipped 2026-07-07) — full details: [milestones/v2.0-ROADMAP.md](./milestones/v2.0-ROADMAP.md)
- ✅ **v2.1 Hardening** — Phases 29–35 (shipped 2026-07-17) — full details: [milestones/v2.1-ROADMAP.md](./milestones/v2.1-ROADMAP.md)

## Phases

**Phase Numbering:**

- Integer phases (29, 30, 31…): Planned milestone work
- Decimal phases (e.g. 31.1): Urgent insertions (marked INSERTED)
- Numbering never restarts across milestones — v2.1 continues from Phase 28

<details>
<summary>✅ v2.1 Hardening (Phases 29–35) — SHIPPED 2026-07-17</summary>

**Milestone Goal:** Fix the correctness defects the whole-project audit surfaced so the briefing spine stops failing silently — no boot-green misconfig that drops briefings forever, no leaked OpenWeather key, no duplicate/mis-alerted sends, correct timezone/date boundaries — then backfill the test gaps that let the bugs hide and sweep the latent/cleanup debt. **Audit-driven, no new user features.** Sequenced correctness-first, cleanup last.

- [x] Phase 29: Startup Validation & Honest Alerting — daemon `run` boot validates config/templates like `check-config`; permanent config/template errors alert instead of warn-looping forever as fake network faults (completed 2026-07-08)
- [x] Phase 30: Secret Hygiene — the OpenWeather `appid` never rides in an exception/traceback/log line; the Discord inbound error path stops dumping the key (completed 2026-07-09)
- [x] Phase 31: Send Atomicity, Exactly-Once & Persistence Robustness — post-send bookkeeping can't release a delivered claim (no duplicate briefing), send failures detected and correctly classified, retry doesn't re-fetch, store atomic under `WAL`/`busy_timeout` (completed 2026-07-10)
- [x] Phase 32: Timezone & Date-Boundary Correctness — catch-up survives local-midnight, UV all-clear has hysteresis, `daily[0]` anchored to the configured IANA tz, duplicated `_local_date_iso` helper unified (completed 2026-07-11)
- [x] Phase 33: Interactive & Panel Robustness — bare location commands resolve the default instead of crashing, panel cache/interaction races closed, rendering defects fixed (completed 2026-07-13)
- [x] Phase 34: Test-Gap Backfill — false-green tests corrected; highest-risk uncovered paths (retry-exhaustion, midnight catch-up, rename-safe id, store atomicity) get real regression tests (completed 2026-07-13)
- [x] Phase 35: Cleanup Sweep — dead/divergent code and inaccurate docs removed; remaining low-severity latent findings resolved or explicitly annotated as accepted — no silent debt left behind (completed 2026-07-13)

Full phase goals, plans, and details archived in [milestones/v2.1-ROADMAP.md](./milestones/v2.1-ROADMAP.md). Requirements (21/21) in [milestones/v2.1-REQUIREMENTS.md](./milestones/v2.1-REQUIREMENTS.md). Audit (passed) in [milestones/v2.1-MILESTONE-AUDIT.md](./milestones/v2.1-MILESTONE-AUDIT.md).

</details>

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

<details>
<summary>✅ v1.2 Forecasts, Commands & UV (Phases 12–15) — SHIPPED 2026-06-20</summary>

**Milestone Goal:** Turn WeatherBot from a daily-briefing daemon into a multi-forecast, command-driven assistant with proactive UV/sunscreen guidance — every new output reachable both on a schedule and on demand, reusing the already-fetched One Call 3.0 data and the existing lookup core / guard ladder / scheduler / config-reload spine, never regressing the "morning briefing always goes out, exactly once" guarantee.

- [x] Phase 12: Command Registry & Read-Only Command Surface (3/3 plans) — completed 2026-06-19
- [x] Phase 13: Multi-Day Forecast Templates (5/5 plans) — completed 2026-06-19
- [x] Phase 14: UV Index — On-Demand & Daily Briefing (4/4 plans) — completed 2026-06-19
- [x] Phase 15: Proactive UV Sunscreen Monitor (3/3 plans) — completed 2026-06-19

_Live-daemon UATs on host `yahir-mint` deferred at close (see milestones/v1.2-ROADMAP.md + STATE.md Deferred Items)._

</details>

<details>
<summary>✅ v1.3 Discord Control Panel (Phases 16–20) — SHIPPED 2026-06-27</summary>

**Milestone Goal:** Make the bot tap-to-drive — a pinned, always-live Discord control panel (location dropdown + command-button grid, results rendering in-place) becomes the operator's primary, typing-free way to access every existing read-only command. A pure UI layer inside the existing discord.py `BotThread`: no new weather data, no new dependencies, no new gateway intent. The panel is a third caller of the same registry dispatch core that `on_message` and the CLI already use; the briefing spine stays untouched and its failure-isolation is re-proven for the new interaction path.

- [x] Phase 16: Extract Shared `dispatch_spec` (1/1 plans) — completed 2026-06-23
- [x] Phase 17: Minimal Persistent Panel (Core Wiring) (3/3 plans) — completed 2026-06-24
- [x] Phase 18: Persistence + Summon/Lifecycle (2/2 plans) — completed 2026-06-26 _(superseded: re-summon-to-bottom, 260626-uqp)_
- [x] Phase 19: Forecast Two-Tier Sub-Options (2/2 plans) — completed 2026-06-26 _(superseded: always-visible forecast grid at Gate-2, 260626-u8y)_
- [x] Phase 20: Isolation Hardening + Polish (3/3 plans) — completed 2026-06-27

Full phase goals, plans, success criteria, and details archived in [milestones/v1.3-ROADMAP.md](./milestones/v1.3-ROADMAP.md).
Requirements (13/13 satisfied) archived in [milestones/v1.3-REQUIREMENTS.md](./milestones/v1.3-REQUIREMENTS.md).
Audit (passed) in [milestones/v1.3-MILESTONE-AUDIT.md](./milestones/v1.3-MILESTONE-AUDIT.md).

</details>

<details>
<summary>✅ v2.0 Bot Module Extraction (Phases 21–28) — SHIPPED 2026-07-07</summary>

**Milestone Goal:** Carve WeatherBot's reusable, channel-agnostic bot infrastructure out of the weather app into a standalone module (`YahirReusableBot`, import root `yahir_reusable_bot`) consumed back via a uv git dependency — **pure extraction, behavior byte-identical**. In-place seam boundary first (tests green), then physical split last.

- [x] Phase 21: Characterization / Golden-Test Harness (5/5 plans) — completed 2026-06-27
- [x] Phase 22: Channel + Delivery-Reliability Seam (3/3 plans) — completed 2026-06-27
- [x] Phase 23: Scheduler Engine + OccurrenceStore + JobStore Seam (2/2 plans) — completed 2026-06-28
- [x] Phase 24: Config Hot-Reload Engine (3/3 plans) — completed 2026-06-28
- [x] Phase 25: Lifecycle READY-Gate + Composition Root (3/3 plans) — completed 2026-06-28
- [x] Phase 26: Command Registry + Dispatcher Seam (2/2 plans) — completed 2026-06-28
- [x] Phase 27: Discord Adapter + PanelKit + Render-Cycle Fix (4/4 plans) — completed 2026-06-29
- [x] Phase 28: Physical Repo Split + uv Git Dependency + EXTENSION-GUIDE (4/4 plans) — completed 2026-06-29

Full phase goals, plans, and details archived in [milestones/v2.0-ROADMAP.md](./milestones/v2.0-ROADMAP.md).

</details>

## Phase Details

<details>
<summary>✅ v1.0 / v1.1 / v1.2 / v1.3 / v2.0 / v2.1 Phase Details (Phases 1–35) — archived per-milestone</summary>

Full per-phase goals, success criteria, and plans for Phases 1–35 are archived in:

- [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- [milestones/v1.2-ROADMAP.md](./milestones/v1.2-ROADMAP.md)
- [milestones/v1.3-ROADMAP.md](./milestones/v1.3-ROADMAP.md)
- [milestones/v2.0-ROADMAP.md](./milestones/v2.0-ROADMAP.md)
- [milestones/v2.1-ROADMAP.md](./milestones/v2.1-ROADMAP.md)

</details>

## Progress

**Execution Order:** Phases execute in numeric order. v1.0: 1 → 5. v1.1: 6 → 11. v1.2: 12 → 15. v1.3: 16 → 20. v2.0: 21 → 28. v2.1 continues from 29.

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
| 12. Command Registry & Read-Only Command Surface | v1.2 | 3/3 | ✅ Complete | 2026-06-19 |
| 13. Multi-Day Forecast Templates | v1.2 | 5/5 | ✅ Complete | 2026-06-19 |
| 14. UV Index — On-Demand & Daily Briefing | v1.2 | 4/4 | ✅ Complete | 2026-06-19 |
| 15. Proactive UV Sunscreen Monitor | v1.2 | 3/3 | ✅ Complete | 2026-06-19 |
| 16. Extract Shared `dispatch_spec` | v1.3 | 1/1 | ✅ Complete | 2026-06-23 |
| 17. Minimal Persistent Panel (Core Wiring) | v1.3 | 3/3 | ✅ Complete | 2026-06-24 |
| 18. Persistence + Summon/Lifecycle | v1.3 | 2/2 | ✅ Complete | 2026-06-26 |
| 19. Forecast Two-Tier Sub-Options | v1.3 | 2/2 | ✅ Complete | 2026-06-26 |
| 20. Isolation Hardening + Polish | v1.3 | 3/3 | ✅ Complete | 2026-06-27 |
| 21. Characterization / Golden-Test Harness | v2.0 | 5/5 | ✅ Complete | 2026-06-27 |
| 22. Channel + Delivery-Reliability Seam | v2.0 | 3/3 | ✅ Complete | 2026-06-27 |
| 23. Scheduler Engine + OccurrenceStore + JobStore Seam | v2.0 | 2/2 | ✅ Complete | 2026-06-28 |
| 24. Config Hot-Reload Engine | v2.0 | 3/3 | ✅ Complete | 2026-06-28 |
| 25. Lifecycle READY-Gate + Composition Root | v2.0 | 3/3 | ✅ Complete | 2026-06-28 |
| 26. Command Registry + Dispatcher Seam | v2.0 | 2/2 | ✅ Complete | 2026-06-28 |
| 27. Discord Adapter + PanelKit + Render-Cycle Fix | v2.0 | 4/4 | ✅ Complete | 2026-06-29 |
| 28. Physical Repo Split + uv Git Dep + EXTENSION-GUIDE | v2.0 | 4/4 | ✅ Complete | 2026-06-29 |
| 29. Startup Validation & Honest Alerting | v2.1 | 6/6 | ✅ Complete | 2026-07-08 |
| 30. Secret Hygiene | v2.1 | 1/1 | ✅ Complete | 2026-07-09 |
| 31. Send Atomicity, Exactly-Once & Persistence Robustness | v2.1 | 3/3 | ✅ Complete | 2026-07-10 |
| 32. Timezone & Date-Boundary Correctness | v2.1 | 5/5 | ✅ Complete | 2026-07-11 |
| 33. Interactive & Panel Robustness | v2.1 | 7/6 | ✅ Complete | 2026-07-13 |
| 34. Test-Gap Backfill | v2.1 | 7/7 | ✅ Complete | 2026-07-13 |
| 35. Cleanup Sweep | v2.1 | 10/9 | ✅ Complete | 2026-07-13 |
