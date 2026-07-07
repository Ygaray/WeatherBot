# Roadmap: WeatherBot

## Milestones

- ✅ **v1.0 WeatherBot MVP** — Phases 1–5 (shipped 2026-06-15) — full details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Interactive & Live-Config** — Phases 6–11 (shipped 2026-06-19) — full details: [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Forecasts, Commands & UV** — Phases 12–15 (shipped 2026-06-20) — full details: [milestones/v1.2-ROADMAP.md](./milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Discord Control Panel** — Phases 16–20 (shipped 2026-06-27) — full details: [milestones/v1.3-ROADMAP.md](./milestones/v1.3-ROADMAP.md)
- 🚧 **v2.0 Bot Module Extraction ("The Great Decoupling")** — Phases 21–28 (in progress) — pure extraction: carve WeatherBot's reusable, channel-agnostic bot infrastructure into a standalone module (`YahirReusableBot`), byte-identical behavior, in-place seam first → physical split last
- 📋 **v2.1+** — deferred behind the extraction: durable `JobStore` impl (JOBSTORE-V2-01), channels (Telegram/SMS/Slack), arbitrary/geocoded lookup, weather-pattern analysis + history export, real-time severe-weather push (see PROJECT.md → Future candidates)

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

## Phase Details

<details>
<summary>✅ v1.0 / v1.1 / v1.2 / v1.3 Phase Details (Phases 1–20) — archived per-milestone</summary>

Full per-phase goals, success criteria, and plans for Phases 1–20 are archived in:

- [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- [milestones/v1.2-ROADMAP.md](./milestones/v1.2-ROADMAP.md)
- [milestones/v1.3-ROADMAP.md](./milestones/v1.3-ROADMAP.md)

</details>

<details>
<summary>v1.3 per-phase detail (retained inline until next milestone) — Phases 16–20</summary>

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

- [x] 18-02-PLAN.md — Idempotent `!panel` summon: channel resolve/abort + permission preflight (`pin_messages`) + `Forbidden` backstop + find-or-create-one scan + reuse-in-place + delete-extras (PANEL-01) _(superseded: re-summon-to-bottom, 260626-uqp)_

**Research flag**: This phase has the milestone's one open design decision (persist `message_id` / selected-location durably vs. recreate-on-restart) and a MEDIUM-confidence exact pin/embed permission set — benefits from `/gsd-plan-phase --research-phase 18`.

**UI hint**: yes

### Phase 19: Forecast Two-Tier Sub-Options

**Goal**: The panel gains a Forecast button that reveals the Weekday/Weekend × Detailed/Compact sub-options (a static four-button sub-row), each building a `ForecastFlags(variant=..., location=selected)` directly and routing through the same Phase-16 `dispatch_spec` — so the panel mirrors the text command's forecast variants exactly. The one layout-pressure flow, deliberately isolated after the simple grid is proven, with a build-time assertion that the component layout fits Discord's hard limits (≤5 rows / ≤5 per row / ids ≤100 / labels ≤80). (superseded: the forecast grid was made always-visible at Gate-2, dropping the toggle/reveal — quick task 260626-u8y.)
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

**Plans**: 3/3 plans complete
**Wave 1**

- [x] 20-01-PLAN.md — PANEL-11 isolation re-proof: live-`BackgroundScheduler` hanging-callback test (`await asyncio.Event().wait()`, D-08/D-08a) + D-08b executor-sharing audit; test-only, zero production change (PANEL-11)
- [x] 20-02-PLAN.md — `render_embed` polish: `location=` kwarg + `📍` indicator line (argless-suppressed) + `Updated <t:…>` self-ageing stamp in the embed description, native timestamp kept (D-01/D-06/D-07) (PANEL-12/13)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 20-03-PLAN.md — panel-component polish: `_EMOJI` + `emoji=` on every button + dropdown `default=True` re-mark + the `_render_view` clone-survival fix + thread `location=` into the two panel result renders; Gate-1 self-UAT (D-02/D-04/D-05) (PANEL-12/13)

**UI hint**: yes

</details>

### 🚧 v2.0 Bot Module Extraction ("The Great Decoupling") (In Progress)

**Milestone Goal:** Carve WeatherBot's reusable, channel-agnostic bot infrastructure out of the weather app into a standalone module (`YahirReusableBot`, import root `yahir_reusable_bot`) that lives in its own repo and is consumed back via a uv git dependency — **pure extraction, behavior byte-identical** (the 649-test suite plus new golden tests are the acceptance contract). Un-braid *mechanism* (scheduler / config-reload / delivery / lifecycle / registry / Discord adapter) from *content* (locations / forecast / uv / templates) into a clean internal package boundary **in place first** (tests green), **then** physically split. The governing acceptance lens for every seam: *"could a hypothetical reminder bot reuse this with zero weather assumptions?"* No new user-facing feature; durable `JobStore` impl, new channels, and weather analysis are explicitly deferred.

**Phase spine (leaf-seams-first, split-last):** goldens → Channel → scheduler/occurrence/jobstore → config-reload → lifecycle + composition root → registry/dispatch → Discord adapter/PanelKit → physical split. The byte-identical golden harness (Phase 21) is the standing oracle re-run after every later phase. PKG-01 (clean in-place boundary, module imports zero app code, import-lint/grep gate) and BHV-01 (suite stays green) are cross-cutting acceptances enforced on every seam phase, anchored where they are first established. The physical split (Phase 28) is strictly last.

- [x] **Phase 21: Characterization / Golden-Test Harness** — Lay byte-identical golden snapshots (embeds, CLI, schedule plan, DB rows, custom_ids, exception identity) as the oracle every later phase re-runs (completed 2026-06-27)
- [x] **Phase 22: Channel + Delivery-Reliability Seam (+ in-place boundary)** — Extract the channel-agnostic `Channel` abstraction + reliability wrapper into the clean in-place module boundary; stand up the import-lint/litmus-grep gate (completed 2026-06-27)
- [x] **Phase 23: Scheduler Engine + OccurrenceStore + JobStore Seam** — Generic `register(job_id, trigger, callback)` + exactly-once on `(job_id, occurrence)` + serialization-clean `JobStore` Protocol (in-memory impl); no weather concept in the engine (completed 2026-06-28)
- [x] **Phase 24: Config Hot-Reload Engine** — Generic `ConfigHolder[T]` + `ReloadEngine` (validate→swap→reconcile + watch + SIGHUP) over an app-defined schema via injected `validate` / `desired_jobs` hooks (completed 2026-06-28)
- [x] **Phase 25: Lifecycle READY-Gate + Composition Root** — READY-gate over an app-provided health-check; consolidate WeatherBot's wiring at a single composition root; prove the four leak-points are injected (litmus-grep clean) (completed 2026-06-28)
- [x] **Phase 26: Command Registry + Dispatcher Seam** — Move the self-describing registry + shared dispatcher into the module; app registers commands; CLI + Discord + `help` derive from the one registry, drift impossible (completed 2026-06-28)
- [x] **Phase 27: Discord Adapter + PanelKit + Render-Cycle Fix** — Relocate the gateway `BotThread` + `PanelKit` + generic `SelectedContext`; inject `render` to resolve the `render_embed`↔`PanelView` cycle by ownership; freeze `custom_id`s + `discord.py==2.7.1` (completed 2026-06-29)
- [x] **Phase 28: Physical Repo Split + uv Git Dependency + EXTENSION-GUIDE** — `git mv` the clean boundary to `YahirReusableBot`; re-point WeatherBot via a uv git pin (+ dev path override); EXTENSION-GUIDE; live `yahir-mint` restart UAT (completed 2026-06-29)

#### Phase 21: Characterization / Golden-Test Harness

**Goal**: Pin every observable byte of WeatherBot's current behavior as golden/characterization snapshots *before any code moves*, so "byte-identical" is provable (not merely "649 tests green"). The harness captures full rendered Discord embeds (per command × `📍`/`Updated` states, frozen forecast + frozen clock), CLI stdout/exit-code per subcommand and forecast variant, the registered-job schedule plan `(job_id, trigger spec, next_run_time)`, the `weather_onecall`/`alerts`/sent-log DB rows a briefing writes, the exact panel `custom_id` byte strings (incl. the `wb:` marker), and an exception-identity pin; a coverage audit fills any uncovered branch on the move paths. This golden suite is the standing oracle re-run after every later seam extraction and again after the physical split.
**Depends on**: Nothing (first phase of v2.0; builds on the existing Phase 1–20 codebase + test suite)
**Requirements**: BHV-02, BHV-01
**Success Criteria** (what must be TRUE):

  1. Running the full suite (existing 649 + new goldens) is green on `main`, and the golden snapshots capture the rendered embeds, CLI stdout/exit, the registered-job schedule plan, the briefing's DB rows, and the panel `custom_id`s as byte-exact artifacts.
  2. A deliberate trial perturbation of a rendered embed field order / a `custom_id` string makes a golden test FAIL (the oracle actually detects byte drift, not just intent).
  3. An exception-identity test asserts the move-path error types via the import path other code catches them through, so a later re-home that changes a fully-qualified name fails loud.
  4. A coverage audit over the modules slated to move shows no uncovered branch on a move path (any gap is filled with a characterization test first).

**Plans**: 4/5 plans executed

**Wave 0**

- [x] 21-01-PLAN.md — Tooling + harness: `uv add --dev syrupy pytest-cov`, `[tool.coverage.*]` branch-mode block (6 move-path pkgs), shared conftest helpers (FROZEN, json/bytes snapshot fixtures, embed/row/schedule serializers) + Wave-0 smoke confirms (BHV-01)

**Wave 1** *(blocked on Wave 0)*

- [x] 21-02-PLAN.md — Embed goldens per command × 📍/Updated states (D-10/D-11) + custom_id byte pins (D-02/D-03) + oracle self-proof meta-test (D-12 / SC2) (BHV-02)
- [x] 21-03-PLAN.md — CLI stdout/exit goldens + schedule-plan golden + briefing DB-row goldens (D-11 freeze/scrub/ORDER BY) (BHV-02)
- [x] 21-04-PLAN.md — Move-path exception-identity pins: `is`-identity + frozen `(__module__,__qualname__)` (D-13 / SC3) (BHV-02)

**Wave 2** *(blocked on Wave 1)*

- [x] 21-05-PLAN.md — One-time branch-coverage audit over the 6 move-path packages, fill uncovered branches, full-suite zero-flake gate (D-05..D-09 / SC4 / BHV-01)

**Research flag**: No — established characterization-test technique; the suite already uses frozen forecast fixtures + clock seams.
**UI hint**: no

#### Phase 22: Channel + Delivery-Reliability Seam (+ in-place boundary)

**Goal**: Establish the clean in-place package boundary (the subpackage already named what the extracted module will be, so the split is a later `git mv` not a rename) and extract the lowest-risk seam first: the channel-agnostic `Channel` abstraction + the delivery-reliability wrapper (retry/backoff honoring `Retry-After`, never retrying 401/403, out-of-band alert, heartbeat) into that boundary, with zero weather coupling. This phase also stands up the cross-cutting import-hygiene gate — a one-way dependency rule (module subpackage imports zero app code) enforced by an import-lint contract + a litmus grep (`weather|forecast|location|openweather|\buv\b|briefing` returns only incidental hits) — that every subsequent seam phase re-runs.
**Depends on**: Phase 21 (golden harness as the byte-identical oracle)
**Requirements**: SEAM-01, PKG-01
**Success Criteria** (what must be TRUE):

  1. The `Channel` abstraction + reliability wrapper live in the in-place module boundary, and the existing channel/reliability suites plus the Phase-21 goldens stay green (delivery behavior byte-identical: same retry bursts, same `Retry-After` honoring, same no-retry-on-401/403, same alert/heartbeat).
  2. The module subpackage imports zero app code — proven by an import-lint contract (one-way dependency) and a core-in-isolation import test that pulls in no weather module.
  3. The litmus grep over the module boundary returns only incidental hits — no `Channel`/reliability signature names a weather noun (a reminder bot could deliver through it with zero weather assumptions).
  4. The import-hygiene + litmus-grep gate is wired as a test/check so a later leak fails loud, and is documented as a standing success criterion for every following seam phase.

**Plans**: 3/3 plans complete
**Wave 1**

- [x] 22-01-PLAN.md — Package skeleton + pyproject build/coverage/dev-dep + the three import-hygiene gates (red-then-green infra)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 22-02-PLAN.md — Channel seam: move text-only `Channel`/`DeliveryResult` into the module; re-home `send_briefing` app-side

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 22-03-PLAN.md — Reliability seam: move the retry engine verbatim + define the `AlertSink` port; adapt (not rewrite) `fire_slot`

**Cross-cutting constraints:**

- Full 732-test suite green with zero golden snapshot diff

**Research flag**: No — already a clean ABC + `retry.py`; lowest-risk warm-up.
**UI hint**: no

#### Phase 23: Scheduler Engine + OccurrenceStore + JobStore Seam

**Goal**: Un-braid the scheduler's *mechanism* from weather *content*. First extract exactly-once out of `fire_slot` into a generic `OccurrenceStore.claim(job_id, occurrence)` + an app-supplied `occurrence_of` callable (WeatherBot's per-tz `local_date`), then wrap APScheduler behind a single `SchedulerEngine.register(job_id, trigger, callback)` surface accepting arbitrary triggers (cron / interval / one-shot date), keeping the proven defaults (`misfire_grace_time=None`, `coalesce=True`, `max_instances=1`, per-tz). Every job type (briefing / forecast / uvmonitor / heartbeat) re-registers through it. Ship a serialization-clean `JobStore` Protocol with the in-memory impl only — shaped so a future durable store is a drop-in, not a redesign (importable callable + picklable identity-style args, live collaborators looked up at fire time). The engine contains no `Location` / `send_time` / `local_date` / `forecast` in its signatures.
**Depends on**: Phase 22 (in-place boundary + import-hygiene gate; Channel seam)
**Requirements**: SEAM-02, SEAM-03
**Success Criteria** (what must be TRUE):

  1. Every WeatherBot job (briefing / forecast / uvmonitor / heartbeat) is registered through `SchedulerEngine.register(job_id, trigger, callback)`, and the Phase-21 schedule-plan golden + exactly-once / DST / restart-catch-up / exactly-once-across-reload tests stay green (byte-identical timing and dedup).
  2. Exactly-once is keyed on a generic `(job_id, occurrence)` via the injected `OccurrenceStore`; the engine's signatures name no weather concept (litmus grep clean — a reminder bot could schedule with its own occurrence semantics).
  3. A guard test asserts every registered callback is an importable module-level function and its args are picklable *even for the in-memory impl*, so the deferred durable `JobStore` is a drop-in (the serialization constraint is recorded for the extension-guide).
  4. The durable `JobStore` *implementation* is absent and documented-deferred — the Protocol ships with only the in-memory / config-rederive impl, with no speculative backend built.

**Plans**: 2/2 plans complete
**Wave 1**

- [x] 23-01-PLAN.md — Module artifacts: SchedulerEngine + OccurrenceStore/JobStore Protocols + MemoryJobStore + barrels + Wave-0 read-back/structural tests

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 23-02-PLAN.md — Adapt daemon.py: route all 4 job types through engine.register, rebind reconcile read-throughs, byte-identical self-UAT

**Research flag**: Yes — the APScheduler serialization-clean seam shape (importable callable + picklable args + fire-time lookup) is a subtle *design-now-build-later* contract; consider `/gsd-plan-phase --research-phase 23`.
**UI hint**: no

#### Phase 24: Config Hot-Reload Engine

**Goal**: Generalize the config hot-reload machinery into the module without it knowing a single app field name — the high-effort, highest-coupling seam. Extract `ConfigHolder` into a generic `ConfigHolder[T]` (lock-free `current()` / locked `replace()`) holding an app-defined frozen `BaseConfig`, and the reload flow into a `ReloadEngine` running validate→atomic-swap→job-reconcile with file-watch + SIGHUP triggers, `check-config` dry-run, and keep-old-on-failure all-or-nothing rollback — driven by **injected** `validate(path)→BaseConfig` and `desired_jobs(cfg)→set[JobSpec]` hooks. Validation routes through the app's concrete validator callable (never an unparametrized pydantic generic, which silently drops subclass fields). WeatherBot's `Config` / `Location` / `UvConfig` / templates stay app-side; `[uv]` never enters the module; restart-boundary *policy* (which keys are restart-only) stays app-side.
**Depends on**: Phase 23 (the `SchedulerEngine` — reload reconciles *jobs* through it)
**Requirements**: SEAM-04
**Success Criteria** (what must be TRUE):

  1. The reload engine drives validate→swap→reconcile + watch + SIGHUP + `check-config` over WeatherBot's schema purely through injected `validate` / `desired_jobs` callables, and the Phase-21 goldens + reload-reconcile-diff / keep-old-rollback / exactly-once-across-reload tests stay green (byte-identical reload behavior).
  2. The module's config seam knows no app field names — validation goes through the app validator callable (subclass fields like `locations`/`[uv]` are never dropped), and the litmus grep over the config seam is clean (a reminder bot supplies its own schema + `desired_jobs`).
  3. A bad config edit still half-applies nothing — validate-raises keeps the old config untouched, and a reconcile failure rolls back to the old job set (all-or-nothing), proven against the existing rollback tests.
  4. `[uv]` / `Location` / templates and the "which keys are restart-only" policy remain entirely app-side — no weather schema or restart-policy list lives in the module holder.

**Plans**: 3/3 plans complete

Plans:

- [x] 24-01-PLAN.md — Module config seam: ConfigHolder[T] + ReloadEngine + barrel + Wave-0 gates (pydantic-isolation, direct-engine, generic-holder)
- [x] 24-02-PLAN.md — Adapt daemon.py: wire ReloadEngine in run_daemon, holder→shim, rebind SIGHUP/main-loop/finally/check-config; byte-identical regression sweep
- [x] 24-03-PLAN.md — Autonomous Gate-1 self-UAT: drive all five reload paths with byte-level golden + DB-row evidence

**Wave 1**

- [x] 24-01-PLAN.md — Module config seam: ConfigHolder[T] + ReloadEngine + barrel + Wave-0 gates

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 24-02-PLAN.md — Adapt daemon.py: wire + drive ReloadEngine; holder shim; byte-identical sweep

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 24-03-PLAN.md — Autonomous Gate-1 self-UAT with byte-level evidence

**Research flag**: Yes — the pydantic-v2 generic-validation pitfall + the `validate` / `desired_jobs` / rollback hook shapes are the highest-effort, highest-coupling seam; consider `/gsd-plan-phase --research-phase 24`.
**UI hint**: no

#### Phase 25: Lifecycle READY-Gate + Composition Root

**Goal**: Extract the process-lifecycle layer (systemd `Type=notify` READY-gate, supervised-restart contract, heartbeat) into the module so it gates `READY=1` on an **app-provided** health-check callback — the weather/API probe (`run_self_check`) stays app-side, and PID path / runtime dir / unit name / console name are parameterized (no `weatherbot` literal in the module; the `.service` ships as a template). With every core+adapter seam now extracted, consolidate WeatherBot's wiring at a **single composition root** that registers its weather commands, its config schema, its health probe, its `render_embed`, and its selected-*location* context — keeping zero duplicated copy of any module mechanism. This is the anchor for proving the four "secretly app-coupled" leak points (`SelectedContext`=location, the config id-deriver/exactly-once key, the health-check, panel cosmetics) are *injected, not baked* — verified by the litmus check that no weather term appears in the module package.
**Depends on**: Phase 24 (config holder — lifecycle depends on it; and the seams the composition root wires together)
**Requirements**: SEAM-05, APP-01, APP-02
**Success Criteria** (what must be TRUE):

  1. The lifecycle layer gates `READY=1` on an app-provided health-check callable — the live reboot/READY-gate behavior on the existing unit is byte-identical (READY reaches systemd only after the app probe passes), with no weather/OpenWeather code and no `weatherbot` literal in the module's lifecycle.
  2. WeatherBot wires the module at a single composition root that registers its commands, config schema, health probe, `render_embed`, and selected-location context, with no duplicated copy of any module mechanism (one wiring site, verified by inspection + green suite).
  3. The four leak points (`SelectedContext`, the exactly-once id-deriver, the health-check, panel cosmetics) are injected at that root, not baked into the module — proven by a litmus check that the module package contains no weather term (`location`/`forecast`/`uv`/`openweather`/`briefing` returns only incidental hits).
  4. The shipped systemd unit is a parameterized template (identity supplied by the app), so a reminder bot could supply its own filesystem identity and health predicate with zero weather assumptions.

**Plans**: 3/3 plans complete
**Wave 1**

- [x] 25-01-PLAN.md — Build the reusable `lifecycle/` module (SystemdNotifier move, HealthResult+neutral severity, LifecycleIdentity+generic proc guard, ReadyGate engine)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 25-02-PLAN.md — Wire app-side: `build_runtime()` composition root + run_daemon drives the ReadyGate (byte-identical ordering), pidfile/sdnotify/selfcheck boundary, `.service` template

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 25-03-PLAN.md — Positive injection-registry test + 3-gate litmus re-run; autonomous Gate-1 self-UAT (READY=1 ordering capture + zero golden diff)

**Research flag**: No — lifecycle is a small, well-understood seam (gate + injected callback + parameterized identity); the composition-root wiring is mechanical once the seams exist.
**UI hint**: no

#### Phase 26: Command Registry + Dispatcher Seam

**Goal**: Move the self-describing command registry + the shared `dispatch_spec` dispatcher (already un-braided in Phase 16) into the module as a generic registration mechanism: commands are *registered by the app*, and CLI + Discord + auto-`help` all derive from that single registry with command-set drift structurally impossible. The module owns the registry/dispatch plumbing and the help-derivation; WeatherBot owns the actual command set (weather / uv / next-cloudy / sun / wind / status / alerts / locations / forecasts) and their content. No weather command name or handler lives in the module — a reminder bot registers its own commands into the same mechanism.
**Depends on**: Phase 25 (composition root — commands are registered there); builds on the Phase 16 shared dispatcher
**Requirements**: SEAM-06
**Success Criteria** (what must be TRUE):

  1. The registry + shared dispatcher live in the module, WeatherBot registers its command set into them at the composition root, and CLI / Discord / `help` all derive from that one registry — the Phase-21 CLI + `help` goldens and the anti-drift tests stay green (byte-identical command surface).
  2. Adding or removing a registered command surfaces uniformly across CLI, Discord, and `help` with no parallel hardcoded list — drift is structurally impossible (a single dispatch path, asserted).
  3. The module's registry/dispatch carries no weather command name or handler — the litmus grep over the registry seam is clean (a reminder bot registers its own commands into the same mechanism).

**Plans**: 2/2 plans complete
**Wave 1**

- [x] 26-01-PLAN.md — Stand up the generic `yahir_reusable_bot/registry/` package (spec + CommandRegistry/build_registry + match_command + dispatch shell), de-weathered at both coupling sites (bind + needs_flags)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 26-02-PLAN.md — Rewire the app onto it (thin re-exporting registry.py, bind closures at build_runtime, match_command delegation), extend the litmus + positive injection-registry gates, re-run the byte-identical oracle

**Research flag**: No — the dispatcher was already extracted in Phase 16; this is a relocation behind the established boundary.
**UI hint**: no

#### Phase 27: Discord Adapter + PanelKit + Render-Cycle Fix

**Goal**: Relocate the Discord *adapter* (the isolated gateway `BotThread` started after READY/torn down in `finally`, persistent-view plumbing, and `PanelKit`) into the module's adapter layer — one level up from the channel-agnostic core, since SMS/Slack have no buttons. `PanelKit` builds the control surface from the registry, exposes a generic `SelectedContext[I]` (WeatherBot's selected *location* is `SelectedContext[str]`), and takes the result `render` as an **injected** callable — resolving the latent `render_embed`↔`PanelView` import cycle *by ownership* (move `render_embed` app-side, inject it; not a deferred import). Every v1.3 persistent-view invariant is preserved byte-identically: `timeout=None`, `add_view` in `setup_hook`, the operator gate + identity-free ephemeral reject, the per-callback non-propagating failure-isolation envelope + `View.on_error`, the clone-path polish survival (the WR-01/WR-02 class), the frozen `custom_id`s (incl. the `wb:` marker), and the `discord.py==2.7.1` pin.
**Depends on**: Phase 26 (registry/dispatcher — PanelKit builds from it) and Phase 24 (the relocated renderer's app-side home)
**Requirements**: SEAM-07
**Success Criteria** (what must be TRUE):

  1. The Discord adapter (`BotThread` + `PanelKit` + `SelectedContext`) lives in the module, WeatherBot supplies the location dropdown / forecast grid / 📍 / emoji cosmetics + the injected `render`, and the Phase-21 panel/clone-render goldens + operator-gate / restart-routing / isolation tests stay green (panel behavior byte-identical).
  2. The `render_embed`↔`PanelView` cycle is resolved by ownership — `render` is an injected callable, with no deferred/in-function import surviving — proven by a core/adapter import-isolation check.
  3. The panel `custom_id` byte strings (incl. the `wb:` marker) are frozen and asserted by a byte-string test, and the module pins `discord.py==2.7.1` — so the already-pinned live panel keeps routing (no "interaction failed").
  4. The operator gate, per-callback isolation envelope, and clone-path polish survival (📍 / emoji / `Updated <t:…>` across ack/collapse renders) are preserved byte-identically — the WR-01/WR-02 clone-path regression class is re-guarded by clone-render goldens; `SelectedContext` is generic (no hardcoded "location") yet carries WeatherBot's selected location.

**Plans**: 4/4 plans complete

Plans:
**Wave 1**

- [x] 27-01-PLAN.md — Create the `yahir_reusable_bot/discord/` adapter package (SelectedContext[I], PanelKit, BotThread/build_client/summon) with marker/render/contributors parameterized out; pin `discord.py==2.7.1` (Wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 27-02-PLAN.md — App-side rewire: keep `render_embed` app-side (signature unchanged) + bridge it via a composition-root `_render_bridge` closure, shrink `panel.py` to cosmetic contributors, delete the gateway machinery, wire the module adapter at the composition root (kills both cycle imports) (Wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 27-04-PLAN.md — Rewire the `tests/test_panel.py` oracle harness (`_make_panel` + the `_render_view`/`_selected_location` tests) onto the module `PanelKit` via app contributors, byte-identically; keep `test_golden_custom_ids.py`/`test_oracle_selfproof.py` collecting (Wave 3)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 27-03-PLAN.md — Extend the import-hygiene + injection gates (core↔adapter isolation, positive injection, marker-parameterization), re-run the byte-identical golden oracle, write the Gate-1 self-UAT log (Wave 4)

**Research flag**: Yes — resolving the cycle by ownership while preserving every v1.3 persistent-view / clone-path / `custom_id` invariant byte-identically is intricate; consider `/gsd-plan-phase --research-phase 27`.
**UI hint**: yes

#### Phase 28: Physical Repo Split + uv Git Dependency + EXTENSION-GUIDE

**Goal**: With the in-place boundary clean and the full suite + goldens green, physically split the module to its own repo `YahirReusableBot` (import root `yahir_reusable_bot`, shipping **no** console script) via a `git mv` of the clean boundary, and re-point WeatherBot at it through a uv **git dependency** (`tool.uv.sources` git pin, tag-pinned for deploy) with an editable path override for local co-development, a reproducible `uv.lock`, and a `uv build --no-sources` leak gate. The `weatherbot` console entry point stays in the app, crossing into the module only through stable public names. Ship the `EXTENSION-GUIDE` documenting every plug point (`JobStore`, command registration, config-schema extension, `Channel`, panel `SelectedContext`, health-check) with implemented-vs-deferred status (incl. the durable-`JobStore` serialization contract), initialize the module as its own GSD project recording the durable-`JobStore` impl + a second `Channel` adapter as deferred extension points, and stand up the commit→push→repin→deploy ritual + startup-version-log + promotion ledger. A clean-venv install + a live `yahir-mint` `systemctl restart` UAT confirm the deployed bot runs against the pinned module with the live pinned panel still routing.
**Depends on**: Phases 22–27 (all seams extracted, in-place boundary clean, suite + goldens green)
**Requirements**: PKG-02, DOCS-01
**Success Criteria** (what must be TRUE):

  1. The module lives in its own repo `YahirReusableBot` (import root `yahir_reusable_bot`, no console script), WeatherBot depends on it via a tag-pinned uv git dependency with a reproducible `uv.lock`, and the full 649-suite + Phase-21 goldens pass byte-identical from the consuming app against the pinned module.
  2. A clean-venv `uv sync --frozen` from the git pin + `weatherbot check` / `--help` + the full suite pass (the installed-artifact gate that turns "works locally" into "works on host"), and `uv build --no-sources` raises no leak; the `weatherbot` console script still resolves through stable public module names.
  3. The live `yahir-mint` UAT passes — deploy → `sudo systemctl restart weatherbot` → the bot runs against the pinned module sha (announced by a startup-version-log line) and every button/dropdown on the already-pinned panel still routes (custom_id contract + persistent-view re-bind intact), with the correct default location.
  4. The `EXTENSION-GUIDE` documents each plug point with implemented-vs-deferred status (durable `JobStore` + 2nd `Channel` recorded as deferred extension points, incl. the serialization contract), the module is initialized as its own GSD project, and the repin ritual + promotion ledger are stood up as durable process artifacts.

**Plans**: 4/4 plans complete
**Wave 1**

- [x] 28-01-PLAN.md — Spike `direct_url.json` + create the `YahirReusableBot` repo (fresh git init, scrub docstrings, module pyproject, re-scope import-hygiene, EXTENSION-GUIDE, module GSD init), tag v0.1.0

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 28-02-PLAN.md — Re-point WeatherBot pyproject (git pin + collapse wheel + drop discord.py + fix coverage) + lock + clean-venv install gate + `uv build --no-sources` leak gate

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 28-03-PLAN.md — startup-version-log (`_module_provenance()` reads PEP 610 `direct_url.json`) + provenance unit test

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 28-04-PLAN.md — repin ritual + promotion ledger + Gate-1 self-UAT (autonomous) + deferred Gate-2 live `yahir-mint` restart obligation

**Research flag**: Yes — packaging / namespace / entry-point / dev-vs-deploy mechanics + the live-host UAT have the most "works locally, breaks on host" surface; consider `/gsd-plan-phase --research-phase 28`.
**UI hint**: no

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
| 16. Extract Shared `dispatch_spec` | v1.3 | 1/1 | ✅ Complete | 2026-06-23 |
| 17. Minimal Persistent Panel (Core Wiring) | v1.3 | 3/3 | ✅ Complete | 2026-06-24 |
| 18. Persistence + Summon/Lifecycle | v1.3 | 2/2 | ✅ Complete | 2026-06-26 |
| 19. Forecast Two-Tier Sub-Options | v1.3 | 2/2 | ✅ Complete | 2026-06-26 |
| 20. Isolation Hardening + Polish | v1.3 | 3/3 | ✅ Complete | 2026-06-27 |
| 21. Characterization / Golden-Test Harness | v2.0 | 5/5 | Complete    | 2026-06-27 |
| 22. Channel + Delivery-Reliability Seam | v2.0 | 3/3 | Complete    | 2026-06-27 |
| 23. Scheduler Engine + OccurrenceStore + JobStore Seam | v2.0 | 2/2 | Complete    | 2026-06-28 |
| 24. Config Hot-Reload Engine | v2.0 | 3/3 | Complete    | 2026-06-28 |
| 25. Lifecycle READY-Gate + Composition Root | v2.0 | 3/3 | Complete    | 2026-06-28 |
| 26. Command Registry + Dispatcher Seam | v2.0 | 2/2 | Complete    | 2026-06-28 |
| 27. Discord Adapter + PanelKit + Render-Cycle Fix | v2.0 | 4/4 | Complete    | 2026-06-29 |
| 28. Physical Repo Split + uv Git Dep + EXTENSION-GUIDE | v2.0 | 4/4 | Complete    | 2026-06-29 |
