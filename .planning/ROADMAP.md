# Roadmap: WeatherBot

## Milestones

- ✅ **v1.0 WeatherBot MVP** — Phases 1–5 (shipped 2026-06-15) — full details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Interactive & Live-Config** — Phases 6–11 (shipped 2026-06-19) — full details: [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Forecasts, Commands & UV** — Phases 12–15 (shipped 2026-06-20) — full details: [milestones/v1.2-ROADMAP.md](./milestones/v1.2-ROADMAP.md)
- 🚧 **v1.3 Discord Control Panel** — Phases 16–20 (in progress)
- 📋 **v2.0** — channels (Telegram/SMS), arbitrary/geocoded lookup, weather-pattern analysis + history export, real-time severe-weather push (planned — define via `/gsd-new-milestone`)

## Phases

**Phase Numbering:**

- Integer phases (6, 7, 8…): Planned milestone work
- Decimal phases (e.g. 9.1): Urgent insertions (marked INSERTED)
- Numbering never restarts across milestones — v1.3 continues from Phase 16

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

### 🚧 v1.3 Discord Control Panel (In Progress)

**Milestone Goal:** Make the bot tap-to-drive — a pinned, always-live Discord control panel (location dropdown + command-button grid, results rendering in-place) becomes the operator's primary, typing-free way to access every existing read-only command. A pure UI layer inside the existing discord.py `BotThread`: no new weather data, no new dependencies, no new gateway intent. The panel is a third caller of the same registry dispatch core that `on_message` and the CLI already use; the briefing spine stays untouched and its failure-isolation is re-proven for the new interaction path.

**Build order (research-driven):** refactor-first → core-before-durability-before-layout → isolation-reproof-last.

- [x] **Phase 16: Extract Shared `dispatch_spec`** — Lift the `on_message` arg-adaptation ladder into one shared dispatcher so the panel can never drift from the real command set (completed 2026-06-23)
- [x] **Phase 17: Minimal Persistent Panel (Core Wiring)** — Location dropdown + read-only command buttons, defer-then-edit fast ack, in-place render, operator guard (completed 2026-06-24)
- [x] **Phase 18: Persistence + Summon/Lifecycle** — Persistent views survive restart; idempotent `!panel` summon + pin; exactly one panel (completed 2026-06-26)
- [x] **Phase 19: Forecast Two-Tier Sub-Options** — Forecast button revealing Weekday/Weekend × Detailed/Compact variants (completed 2026-06-26)
- [ ] **Phase 20: Isolation Hardening + Polish** — Re-prove briefing isolation for the interaction path; selected-location indicator + emoji labels + "updated" stamp

## Phase Details

<details>
<summary>✅ v1.0 / v1.1 / v1.2 Phase Details (Phases 1–15) — archived per-milestone</summary>

Full per-phase goals, success criteria, and plans for Phases 1–15 are archived in:

- [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- [milestones/v1.2-ROADMAP.md](./milestones/v1.2-ROADMAP.md)

</details>

### Phase 16: Extract Shared `dispatch_spec`

**Goal**: The heterogeneous arg-adaptation ladder currently living inside `on_message` is lifted into one shared `dispatch_spec(...)` function that resolves a `CommandSpec` from the registry, threads the location/flags/threshold each handler needs, runs the off-loop fetch, and returns a `CommandReply` — so `on_message` (and, in later phases, the panel) call the same code with no duplicated dispatch table. This makes command-set drift structurally impossible before any panel callback exists. Pure groundwork, behavior-preserving.
**Depends on**: Phase 15 (existing `on_message` dispatch, `registry.COMMANDS`, `ForecastCache`, `command.py` flag helpers)
**Requirements**: PANEL-10
**Success Criteria** (what must be TRUE):

  1. A single shared dispatcher resolves every registry command (weather / uv / next-cloudy / sun / wind / status / alerts / locations / help / forecasts) and returns the same `CommandReply` the command produces today.
  2. `on_message` produces byte-identical replies to before the refactor (text `!weather`, `!uv`, `!status`, etc. unchanged), proven by the existing anti-drift / registry tests staying green.
  3. There is exactly one dispatch path in the codebase — no second hardcoded command list or parallel arg-adaptation ladder — and adding a registry command surfaces through the shared dispatcher with no per-callsite edit.
  4. The shared dispatcher only ever drives read-only paths (registry handler + `ForecastCache` + read-only `DaemonState` / `holder.current()`) and writes nothing to the store, sent-log, or scheduler.

**Plans**: 1 plan

- [x] 16-01-PLAN.md — Extract the if/elif arg-adaptation ladder into a shared dispatch.py (dispatch_reply + dispatch_spec); route bot.py and cli.py through it; behavior-preserving (PANEL-10)

**UI hint**: no

### Phase 17: Minimal Persistent Panel (Core Wiring)

**Goal**: A `PanelView` (`discord.ui.View`, `timeout=None`, static `custom_id`s) carries a location dropdown populated from configured locations plus the read-only command buttons (weather / uv / next-cloudy / sun / wind / status / alerts), each derived from the registry. A tap is acknowledged within Discord's 3-second window (defer-then-edit), runs the off-loop fetch through the Phase-16 `dispatch_spec`, and renders the result in-place by editing the panel message with components reattached. One `interaction_check` operator guard gates every interaction; a per-callback non-propagating envelope plus a `View.on_error` backstop keep any failure contained. This phase carries the load-bearing interaction correctness.
**Depends on**: Phase 16 (shared `dispatch_spec`)
**Requirements**: PANEL-02, PANEL-03, PANEL-04, PANEL-05, PANEL-06, PANEL-08
**Success Criteria** (what must be TRUE):

  1. Operator can pick a location from the panel's dropdown (populated from configured locations, re-derived when config is hot-reloaded) and tap a command button (weather / uv / next-cloudy / sun / wind) to get that command's result for the selected location.
  2. Argless command buttons (status / alerts) work from the panel and ignore the selected location.
  3. Every tap is acknowledged within Discord's 3-second window (defer-then-edit), so a slow cold-cache fetch never shows "interaction failed".
  4. Command results render in-place — the panel message edits with its components reattached; no new messages are posted.
  5. A non-operator tap gets an ephemeral, leak-free reject that never echoes the user/command or clobbers the shared panel, and no command handler runs for it.

**Plans**: 3 plans
**Wave 1**

- [x] 17-01-PLAN.md — Wave-0 test scaffold: `fake_interaction` factory + `tests/test_panel.py` RED node IDs for PANEL-02/03/04/05/06/08
- [x] 17-02-PLAN.md — W2 behavior-preserving refactor: real `weather` registry spec + handler (byte-identical to `build_inbound_embed`) + CLI subparser skip-guard + registry anti-drift test update (PANEL-03)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 17-03-PLAN.md — `PanelView` core wiring: registry-derived dropdown + button grid, single-ack defer-then-edit, in-place render, operator guard + leak-free reject, per-callback envelope + `View.on_error` (PANEL-02/03/04/05/06/08)

**UI hint**: yes

### Phase 18: Persistence + Summon/Lifecycle (Restart Durability)

**Goal**: The pinned panel keeps working after a bot restart/deploy — the `PanelView` is registered as a persistent view (`timeout=None` + static `custom_id`s + `add_view` in `setup_hook`, not `on_ready`) so component clicks route to their callbacks across process restarts. An idempotent `!panel` summon finds-or-creates exactly one panel, pins it, and cleans up strays; required channel permissions (pin / embed) are checked with a CRITICAL log if missing. This phase resolves the one genuinely open design decision — whether/where to persist the pinned `message_id` and the selected location vs. recreate-on-restart — and is verified by a live `systemctl restart` UAT on host `yahir-mint`.
**Depends on**: Phase 17 (the `PanelView` to register and summon)
**Requirements**: PANEL-01, PANEL-09
**Success Criteria** (what must be TRUE):

  1. After a `systemctl restart weatherbot`, every button and the dropdown on the already-pinned panel still work (taps route to callbacks, not "interaction failed").
  2. Operator can summon a pinned control-panel message; the summon is idempotent — it leaves exactly one panel and removes/cleans up any stray panels it owns.
  3. After a restart the panel resolves to a sensible selected-location default (the documented default-on-restart behavior), so the next tap hits a valid location rather than erroring.
  4. If the bot lacks the channel permissions needed to post/pin/edit the panel, it logs a clear CRITICAL rather than failing silently mid-operation.

**Plans**: 2/2 plans complete
**Wave 1**

- [x] 18-01-PLAN.md — Config field `panel_channel_id` + thread through daemon/BotThread/build_client + `setup_hook` `add_view` persistent-view registration + `_is_owned_panel` marker + Wave-0 test fakes (PANEL-09)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 18-02-PLAN.md — Idempotent `!panel` summon: channel resolve/abort + permission preflight (`pin_messages`) + `Forbidden` backstop + find-or-create-one scan + reuse-in-place + delete-extras (PANEL-01)

**Research flag**: This phase has the milestone's one open design decision (persist `message_id` / selected-location durably vs. recreate-on-restart) and a MEDIUM-confidence exact pin/embed permission set — benefits from `/gsd-plan-phase --research-phase 18`.

**UI hint**: yes

### Phase 19: Forecast Two-Tier Sub-Options

**Goal**: The panel gains a Forecast button that reveals the Weekday/Weekend × Detailed/Compact sub-options (a static four-button sub-row), each building a `ForecastFlags(variant=..., location=selected)` directly and routing through the same Phase-16 `dispatch_spec` — so the panel mirrors the text command's forecast variants exactly. The one layout-pressure flow, deliberately isolated after the simple grid is proven, with a build-time assertion that the component layout fits Discord's hard limits (≤5 rows / ≤5 per row / ids ≤100 / labels ≤80).
**Depends on**: Phase 17 (core panel); ideally Phase 18 (persistence in place)
**Requirements**: PANEL-07
**Success Criteria** (what must be TRUE):

  1. Operator can tap the Forecast button to reveal Weekday/Weekend × Detailed/Compact sub-options and get the chosen variant for the currently selected location.
  2. The forecast results come through the same shared dispatcher and registry forecast specs as the text command — same content, no parallel forecast logic.
  3. The full panel (dropdown + command grid + forecast sub-options) fits within Discord's component limits, asserted at build time so a future addition can't silently overflow.

**Plans**: 2/2 plans complete
**Wave 1**

- [x] 19-01-PLAN.md — Additive `flags=None` seam on `dispatch_spec` (D-01/D-02, byte-identical when None) + `test_dispatch.py` nodes [Wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 19-02-PLAN.md — Forecast toggle + 2×2 sub-grid + `on_forecast`/`on_forecast_toggle` + merged `_render_view` + completed `_assert_layout` + collapse-on-action + `test_panel.py` nodes [Wave 2]

**UI hint**: yes

### Phase 20: Isolation Hardening + Polish

**Goal**: The milestone's load-bearing failure-isolation guarantee is re-proven for the new interaction-callback path — a panel callback that raises or hangs never delays, drops, or stops a concurrently-scheduled briefing (mirroring the Phase-15 raising-tick proof against a live scheduler). On top of that, the panel polish lands: a visible selected-location indicator with a sensible startup default, emoji-coded command-button labels for at-a-glance scanning, and an "updated <time>" stamp on rendered results so an in-place edit is visibly distinct from the prior one.
**Depends on**: Phases 17–19 (the whole assembled panel)
**Requirements**: PANEL-11, PANEL-12, PANEL-13
**Success Criteria** (what must be TRUE):

  1. A panel/interaction error (a raising or hanging callback) never delays, drops, or stops a scheduled briefing — re-proven by a test/UAT that fires a briefing while a callback raises, asserting the briefing still goes out on time.
  2. The panel shows a visible "selected location" indicator with a sensible startup default (home/first), so the operator always knows which location the next tap will hit.
  3. Command buttons use emoji-coded labels for at-a-glance scanning.
  4. Rendered results carry an "updated <time>" stamp so an in-place edit is visibly distinct from the prior one.

**Plans**: 2/3 plans executed
**Wave 1**

- [x] 20-01-PLAN.md — PANEL-11 isolation re-proof: live-`BackgroundScheduler` hanging-callback test (`await asyncio.Event().wait()`, D-08/D-08a) + D-08b executor-sharing audit; test-only, zero production change (PANEL-11)
- [x] 20-02-PLAN.md — `render_embed` polish: `location=` kwarg + `📍` indicator line (argless-suppressed) + `Updated <t:…>` self-ageing stamp in the embed description, native timestamp kept (D-01/D-06/D-07) (PANEL-12/13)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 20-03-PLAN.md — panel-component polish: `_EMOJI` + `emoji=` on every button + dropdown `default=True` re-mark + the `_render_view` clone-survival fix + thread `location=` into the two panel result renders; Gate-1 self-UAT (D-02/D-04/D-05) (PANEL-12/13)

**UI hint**: yes

### 📋 v2.0 (Planned)

To be defined via `/gsd-new-milestone`. Candidate goals (see PROJECT.md → Requirements → Future candidates):
Telegram + SMS channels (CHAN-V2-01/02), arbitrary/geocoded `weather <any city>` lookup (CMD-V2-02 — would extend the panel with a modal text-input flow), weather-pattern analysis + history/CSV export over the v1 SQLite store (ANLY-V2-01/02), real-time severe-weather push alerts (ENH-V2-03 — a panel auto-refresh/live-update would build on this), panel polish PANEL-V2-01 (grey out command buttons until a location is selected).

## Progress

**Execution Order:** Phases execute in numeric order. v1.0: 1 → 5. v1.1: 6 → 11. v1.2: 12 → 15. v1.3: 16 → 20. v2.0 continues from 21.

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
| 16. Extract Shared `dispatch_spec` | v1.3 | 1/1 | Complete    | 2026-06-23 |
| 17. Minimal Persistent Panel (Core Wiring) | v1.3 | 3/3 | Complete    | 2026-06-24 |
| 18. Persistence + Summon/Lifecycle | v1.3 | 2/2 | Complete    | 2026-06-26 |
| 19. Forecast Two-Tier Sub-Options | v1.3 | 2/2 | Complete    | 2026-06-26 |
| 20. Isolation Hardening + Polish | v1.3 | 2/3 | In Progress|  |
