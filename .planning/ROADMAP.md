# Roadmap: WeatherBot

## Milestones

- ✅ **v1.0 WeatherBot MVP** — Phases 1–5 (shipped 2026-06-15) — full details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Interactive & Live-Config** — Phases 6–11 (shipped 2026-06-19) — full details: [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Forecasts, Commands & UV** — Phases 12–15 (shipped 2026-06-20) — full details: [milestones/v1.2-ROADMAP.md](./milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Discord Control Panel** — Phases 16–20 (shipped 2026-06-27) — full details: [milestones/v1.3-ROADMAP.md](./milestones/v1.3-ROADMAP.md)
- ✅ **v2.0 Bot Module Extraction ("The Great Decoupling")** — Phases 21–28 (shipped 2026-07-07) — full details: [milestones/v2.0-ROADMAP.md](./milestones/v2.0-ROADMAP.md)
- 🔨 **v2.1 Hardening** — Phases 29–35 (active, started 2026-07-07) — audit-driven correctness/hardening; requirements in [REQUIREMENTS.md](./REQUIREMENTS.md), findings in [WHOLE-PROJECT-REVIEW.md](./WHOLE-PROJECT-REVIEW.md)

## Phases

**Phase Numbering:**

- Integer phases (29, 30, 31…): Planned milestone work
- Decimal phases (e.g. 31.1): Urgent insertions (marked INSERTED)
- Numbering never restarts across milestones — v2.1 continues from Phase 28

### 🔨 v2.1 Hardening (Phases 29–35) — ACTIVE

**Milestone Goal:** Fix the correctness defects the whole-project audit surfaced so the briefing spine stops failing silently — no boot-green misconfig that drops briefings forever, no leaked OpenWeather key, no duplicate/mis-alerted sends, correct timezone/date boundaries — then backfill the test gaps that let the bugs hide and sweep the latent/cleanup debt. **Audit-driven, no new user features.** Sequenced correctness-first, cleanup last. The 17 hub findings route upstream (`.planning/HUB-FINDINGS-HANDOFF.md`); this milestone is WeatherBot-only. No frontend work — the "panel robustness" phase is Discord-command correctness, not visual design (UI gate: skip).

- [x] **Phase 29: Startup Validation & Honest Alerting** — Daemon `run` boot validates config/templates like `check-config`, and permanent config/template errors alert instead of warn-looping forever as fake network faults (completed 2026-07-08)
- [x] **Phase 30: Secret Hygiene** — The OpenWeather `appid` never rides in an exception/traceback/log line; the Discord inbound error path stops dumping the key (completed 2026-07-09)
- [x] **Phase 31: Send Atomicity, Exactly-Once & Persistence Robustness** — Post-send bookkeeping can't release a delivered claim (no duplicate briefing), send failures are detected and correctly classified, retry doesn't re-fetch, and the store is atomic under `WAL`/`busy_timeout` (completed 2026-07-10)
- [x] **Phase 32: Timezone & Date-Boundary Correctness** — Catch-up survives local-midnight, UV all-clear has hysteresis, `daily[0]` is anchored to the configured IANA tz, and the duplicated `_local_date_iso` helper is unified (completed 2026-07-11)
- [x] **Phase 33: Interactive & Panel Robustness** — Bare location commands resolve the default instead of crashing, panel cache/interaction races are closed, and rendering defects are fixed (completed 2026-07-13)
- [x] **Phase 34: Test-Gap Backfill** — The false-green tests are corrected and the highest-risk uncovered paths (retry-exhaustion, midnight catch-up, rename-safe id, store atomicity) get real regression tests (completed 2026-07-13)
- [ ] **Phase 35: Cleanup Sweep** — Dead/divergent code and inaccurate docs are removed, and remaining low-severity latent findings are resolved or explicitly annotated as accepted — no silent debt left behind

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
<summary>✅ v1.0 / v1.1 / v1.2 / v1.3 / v2.0 Phase Details (Phases 1–28) — archived per-milestone</summary>

Full per-phase goals, success criteria, and plans for Phases 1–28 are archived in:

- [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- [milestones/v1.1-ROADMAP.md](./milestones/v1.1-ROADMAP.md)
- [milestones/v1.2-ROADMAP.md](./milestones/v1.2-ROADMAP.md)
- [milestones/v1.3-ROADMAP.md](./milestones/v1.3-ROADMAP.md)
- [milestones/v2.0-ROADMAP.md](./milestones/v2.0-ROADMAP.md)

</details>

### Phase 29: Startup Validation & Honest Alerting

**Goal**: A misconfigured daemon can no longer boot green and silently drop every briefing — the `run` startup path enforces the same validation `check-config`/reload already run, and permanent config/template errors are surfaced as fatal (alerted) instead of being misclassified as transient network faults the daemon warn-loops on forever. Highest real-world impact class, sequenced first.
**Depends on**: Nothing (first phase of v2.1; builds on the shipped `assert_unique_names` / `validate_config_and_templates` validators and the ReadyGate/selfcheck path)
**Requirements**: HARD-STARTUP-01, HARD-STARTUP-02, HARD-STARTUP-03
**Success Criteria** (what must be TRUE):

  1. A config with a duplicate location id/name, a typo'd template placeholder, or a missing template file fails the daemon `run` loudly at boot (same validation `check-config`/reload enforce) instead of booting green and dropping briefings every morning.
  2. A permanent config/template/empty-locations error at self-check is classified fatal — the daemon surfaces/alerts and stops pretending to be "alive but not ready" rather than warn-looping on `NETWORK_NOT_READY` forever while sending nothing.
  3. Config→runtime startup ordering/logging is corrected so a feature (e.g. a forecast slot) can't be silently disabled or omitted from the startup schedule announcement without a trace.

**Plans**: 6/6 plans complete

Plans:
**Wave 1**

- [x] 29-01-PLAN.md — Wave 0 test scaffolding: boot-validate + parity + subprocess exit-code (test_cli); CONFIG_INVALID classification + severity (test_ops_selfcheck)
- [x] 29-02-PLAN.md — Wave 0 test scaffolding: fatal-exit / clean-shutdown / auth-not-fatal / F90 announce / F07 ping-order (test_scheduler); F89 streak-prune (test_reload); static systemd-directive (test_service_unit)
- [x] 29-03-PLAN.md — CONFIG_INVALID reason + classification split + CRITICAL severity map + ops re-export (HARD-STARTUP-02)
- [x] 29-06-PLAN.md — `deploy/weatherbot.service` restart policy (D-05) + append deferred hub ReadyGate fatal-outcome to HUB-FINDINGS-HANDOFF (D-10)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 29-04-PLAN.md — `run` gated on the full offline validator + `_fatal_config_exit` (best-effort alert → stamp health → non-zero) (HARD-STARTUP-01/02)
- [x] 29-05-PLAN.md — Fatal-marker plumbing + exit code, F07 ping-after-READY, F90 announce forecast slots, F89 streak prune, remove dead `gate_until_healthy` (HARD-STARTUP-02/03)

**UI hint**: no

### Phase 30: Secret Hygiene

**Goal**: The OpenWeather API key never escapes into logs. `raise_for_status()` output (which embeds `appid=<key>` in the failing URL) is sanitized at every call site, and the Discord inbound error path stops dumping the key-bearing traceback to stderr. Cheap, high-value, sequenced second before the deeper correctness work.
**Depends on**: Phase 29 (shares the daemon/selfcheck files already opened; independent otherwise)
**Requirements**: HARD-SEC-01
**Success Criteria** (what must be TRUE):

  1. On a 401/403 (or any HTTP error) from the OpenWeather onecall or geocode call, no log line, exception message, or traceback contains the `appid` value — the key is redacted/omitted from the surfaced error text.
  2. A failing `!weather <loc>` over Discord (the reproduced end-to-end leak path) logs an outcome without dumping the key-bearing traceback; the scheduler/CLI fetch paths remain leak-free.
  3. A regression test asserts the key string never appears in the captured log/exception output for the fetch-failure paths.

**Plans**: 1/1 plans complete

- [x] 30-01-PLAN.md — Redact appid at both client.py raise sites (D-01, `from None` re-raise, type contract intact) + `_LiveStderr.write` backstop (D-02) + three-path regression suite (onecall/geocode/Discord end-to-end, capsys)

**UI hint**: no

### Phase 31: Send Atomicity, Exactly-Once & Persistence Robustness

**Goal**: Close the send-spine edge seams and the persistence-concurrency defect that feeds them. Post-send bookkeeping can no longer release an already-delivered claim (the F01 duplicate-briefing critical), forecast-slot delivery failures are detected and alerted, retry reuses the fetched payload instead of re-fetching on a delivery-only failure, and send failures are classified correctly (auth vs transient). SQLite runs in `WAL` with a `busy_timeout` and store writes are atomic — which directly de-risks the `database is locked`-after-delivery race that makes F01 reachable. DELIV and STORE are paired here because the storage hardening is the root de-risker of the duplicate-send bug. **F01 (`daemon.py:335`) is a `SWEEP-NEW` critical: reproduce/confirm the finding before landing the fix.**
**Depends on**: Phase 29 (validated boot); the exactly-once claim/sent-log spine and the `weather_onecall` store
**Requirements**: HARD-DELIV-01, HARD-DELIV-02, HARD-DELIV-03, HARD-DELIV-04, HARD-STORE-01, HARD-STORE-02
**Success Criteria** (what must be TRUE):

  1. A DB error in post-send bookkeeping (`resolve_alert`/`stamp_success`) after a briefing is delivered never releases the won claim — the slot stays sent, so catch-up/restart does not re-deliver the same briefing and no false `internal_error` alert fires (F01 verified first, then fixed).
  2. A forecast-slot delivery that fails (Discord non-2xx / `DeliveryResult(ok=False)`) is detected — the failure streak and dead-slot CRITICAL/operator alert fire instead of the failure being counted as success and silently swallowed.
  3. A delivery-only failure retries against the already-fetched payload (no fresh OpenWeather re-fetch on retry), and a permanent send auth failure (Discord 401/403) is mapped to the auth reason rather than burning the full retry schedule as transient.
  4. Concurrent status reads and daemon writes no longer raise `database is locked` — SQLite is opened `WAL` + `busy_timeout`, "read-only" reads don't take a write lock, and multi-step writes are transactional (no truncate-then-write or force-commit-before-insert corruption).

**Plans**: 3/3 plans executed

Plans:
**Wave 1**

- [x] 31-01-PLAN.md — Store hardening: WAL + busy_timeout + shared `_connect()`, schema-init split so reads take no write lock (F10), confirm atomic `weather_onecall` write (HARD-STORE-01/02)
- [x] 31-02-PLAN.md — F01 reproduce-first + log-and-swallow post-send bookkeeping (no released delivered claim) + F08 forecast `DeliveryResult` inspection → dead-slot escalation (HARD-DELIV-01/02)

**Wave 2** *(depends on 31-02: shared `daemon.py`)*

- [x] 31-03-PLAN.md — DELIV-03 fetch-once/deliver-retry (checkpoint: fetch-429 disposition) + DELIV-04 app-side 401/403 auth carrier (redacted-URL `httpx.HTTPStatusError`, reuses daemon:263) (HARD-DELIV-03/04)

**UI hint**: no

### Phase 32: Timezone & Date-Boundary Correctness

**Goal**: Clean up the residue of the One Call 3.0 migration — "which day is today" and `daily[0]` relative to the configured IANA timezone. Catch-up composes the correct local date across a local-midnight boundary (so a late-evening slot missed just after midnight is still recovered), the intraday UV monitor's all-clear gets hysteresis (no latching "protect window over" on a momentary dip) and the pre-warn↔crossing branches leave no never-fire gap, `daily[0]`/positional indexing is anchored to the location tz (correct high/low and day-windows across DST and near midnight), and the duplicated `_local_date_iso` helpers are unified into one tz-correct implementation.
**Depends on**: Phase 29 (validated boot); the catch-up, UV-monitor, and models/store date-composition paths
**Requirements**: HARD-TZ-01, HARD-TZ-02, HARD-TZ-03, HARD-TZ-04
**Success Criteria** (what must be TRUE):

  1. A slot missed late in the evening and recovered just after local midnight is still caught up within grace — catch-up composes the prior local day's instant and tests it against `now - grace`, rather than only ever building today's date and skipping it as "not due yet".
  2. The UV monitor does not declare the protect window over on a single momentary sub-threshold dip while UV is still peaking (all-clear has hysteresis/persistence), and no lifecycle gap leaves pre-warn/crossing/all-clear unable to fire for the day.
  3. Today's high/low, rain, UV window, and forecast day-windows are computed against the configured location IANA timezone — `daily[0]` and any positional daily/hourly indexing verify the entry's local date is today rather than trusting position/UTC, so a near-midnight or DST payload doesn't ship yesterday's numbers labelled as today's.
  4. There is exactly one `_local_date_iso` implementation shared by `models.py` and `store.py`, so the rendered briefing's `{date}`/UV-day and the persisted row's local_date can never diverge.

**Plans**: 5/5 plans executed

Plans:
**Wave 1**

- [x] 32-01-PLAN.md — Wave 0 failing-first regression tests (9): catch-up prior-day + fold-grace, UV all-clear no-latch + full-day lifecycle, daily0-degrades + naive-now_utc, compute_uv today-guard + hourly-sort, dates single-helper/same-output (D-01..D-08)

**Wave 2** *(depends on 32-01)*

- [x] 32-02-PLAN.md — New pure `weather/dates.py` (unified tz helper + `select_today_daily` selector + naive-now_utc hardening) and migrate `store.py` onto it (D-08/D-06/D-05, HARD-TZ-03/04)
- [x] 32-03-PLAN.md — `catchup.py` prior-local-day candidate loop keyed on candidate day + both-folds grace math (D-01/D-02, HARD-TZ-01, F14/F91)

**Wave 3** *(depends on 32-02)*

- [x] 32-04-PLAN.md — `models.from_payloads` + `uv.compute_uv` today-entry selector, shared local_date helper, hourly time-sort (D-05/D-06/D-07, HARD-TZ-03, F35/F31/F32/F33)
- [x] 32-05-PLAN.md — `uvmonitor.py` all-clear window-end hysteresis + lifecycle no-gap audit + shared-helper swap (D-03/D-04/D-08, HARD-TZ-02/04, F15)

**UI hint**: no

### Phase 33: Interactive & Panel Robustness

**Goal**: The Discord command/panel surface stops crashing on valid input and stops serving stale/misrendered results. A bare location-taking command (`!weather` with no arg) resolves the default location like the CLI does instead of crashing on `result=None`, panel cache-invalidation and interaction races (stale in-flight re-populate, double-ack/expired-interaction, unbounded/mis-evicting cache) are closed, and the rendering defects (duplicated headers, empty-token trailing blanks, raw ISO timestamps, mispaired metric-on-missing-dt, ambiguous date labels, unmarked default location) are fixed. **F02 (`dispatch.py:119`) is a `SWEEP-NEW` critical: reproduce/confirm that bare `!weather` crashes on the Discord surface before landing the fix.** This is Discord-command correctness, not visual design — UI gate skipped.
**Depends on**: Phase 32 (shares render/tz formatting fixes); the shared `dispatch_spec`, `ForecastCache`, and command view renderers
**Requirements**: HARD-UI-01, HARD-UI-02, HARD-UI-03
**Success Criteria** (what must be TRUE):

  1. A bare `!weather` / `!sun` / `!wind` / `!alerts` / `!uv` / `!next-cloudy` (no location arg) resolves the default location and returns a correct reply over Discord — matching the CLI's default-location behavior — instead of an "AttributeError → something went wrong" (F02 verified first, then fixed).
  2. A config hot-reload that lands while an inbound fetch is in flight no longer leaves a stale pre-reload result cached and served for the TTL, and the panel cache is bounded so heavy forecast/flag use can't evict the plain weather entry it should protect.
  3. Rendered results are clean: no duplicated forecast header line, no trailing blank lines from empty tokens, human-formatted (not raw ISO) timestamps, correctly dt-paired imperial/metric temps, unambiguous dated labels for out-of-today buckets, and the default location marked where the user needs to know which one a bare command resolves to.

**Plans**: 6/6 plans executed

Plans:
**Wave 1** *(all independent; no shared files)*

- [x] 33-01-PLAN.md — F02 verify-crash-first + app-side default resolution (D-01/D-02) + inbound 📍 "(default)" marker (D-05/F27) — HARD-UI-01, HARD-UI-03
- [x] 33-02-PLAN.md — ForecastCache F13 generation guard (D-03) + bounded/pinned eviction protecting the plain-weather entry (D-04) — HARD-UI-02
- [x] 33-03-PLAN.md — `_on_applied` invalidate-before-send reorder (F17) + SelectedContext reconcile-on-reload (F22) (D-04) — HARD-UI-02
- [x] 33-04-PLAN.md — panel F23 non-raising empty-locations degrade + F24 ack-before-mutate roll-back (D-04) — HARD-UI-02
- [x] 33-05-PLAN.md — models F107 dt-paired imperial/metric daily + F11 one-unit-present high/low (D-08) — HARD-UI-03
- [x] 33-06-PLAN.md — F28 dedup header + empty-token blanks + D-06 date labels + D-07 humanized timestamps — HARD-UI-03

**UI hint**: no

### Phase 34: Test-Gap Backfill

**Goal**: Backfill the coverage that let these bugs hide, so every fix from the correctness phases ships with a real regression test and the false-greens can no longer pass a broken implementation. Correct the tests that lie (the "concurrent" test that runs sequentially, weak/never-failing heartbeat and naming assertions), and add tests on the exact paths the fixed bugs lived in: retry-then-alert exhaustion, catch-up across local midnight, rename-safe `id != name` through fire/catch-up/dedup, dt-based metric pairing, weekend roll-forward, and the store atomicity/data-loss path.
**Depends on**: Phases 29–33 (the fixes these tests pin); this phase closes over their paths
**Requirements**: HARD-TEST-01, HARD-TEST-02
**Success Criteria** (what must be TRUE):

  1. The false-green tests are corrected — the "concurrent double-fire" test actually exercises concurrency (a weakened `claim_slot` now fails it), and the heartbeat tick/success separation + naming assertions are strengthened so a regression that made a never-delivering daemon look healthy fails.
  2. New regression tests cover the previously-uncovered high-risk paths: retry-then-alert exhaustion, catch-up across local midnight, the rename-safe `Location.id != name` path through `fire_slot`/`plan_catchup`/alert-dedup, dt-based imperial/metric daily pairing, weekend-block roll-forward, and the store atomicity/data-loss path.
  3. Each correctness fix from Phases 29–33 has at least one test that fails against the pre-fix behavior and passes against the fix (the fix and its regression test ship together).

**Plans**: 7/7 plans executed

Plans:
**Wave 1** *(all independent — six different test modules, no shared state)*

- [x] 34-01-PLAN.md — F106 real-concurrency (barrier threads) + meta-guard in `test_scheduler.py` (HARD-TEST-01)
- [x] 34-02-PLAN.md — F114 heartbeat tick/success + F112 derived within-burst bound + F110 Retry-After mid-pause collapse in `test_reliability.py` (HARD-TEST-01/02)
- [x] 34-03-PLAN.md — F115 distinct id≠name cache-collapse + F116 reconcile register-before-remove order (HARD-TEST-01)
- [x] 34-04-PLAN.md — F107 dt-pairing [EXISTS] confirm + F109 positive today-not-at-index-0 (D-07 watchpoint) in `test_models.py` (HARD-TEST-02)
- [x] 34-05-PLAN.md — F111 weekend whole-block roll-forward + F113 null-dt skip in `test_multiday.py` (HARD-TEST-02)
- [x] 34-06-PLAN.md — F37/F63 transactional both-or-neither `persist` + F01 [EXISTS] confirm in `test_store.py` (HARD-TEST-02)

**Wave 2** *(shares `test_scheduler.py` with 34-01)*

- [x] 34-07-PLAN.md — F108 rename-safe id≠name through fire_slot/plan_catchup/alerts + F14 midnight catch-up [EXISTS] cite (HARD-TEST-02)

**UI hint**: no

### Phase 35: Cleanup Sweep

**Goal**: Sweep the remaining low/dead-code/latent findings behind the correctness work — in the same files, now that they're already open — so the milestone leaves no silent debt. Dead and divergent code (the dead `-m` guard copy, dead `is_transient` selfcheck call, unreachable UTC fallbacks, dead `verbose` param) and inaccurate docstrings are removed or corrected; remaining low-severity latent findings (config defaults, boundary `>=`/`<=` nits, rounding disagreements, observability inconsistencies, resource/state-leak nits) are either resolved or explicitly annotated as accepted-with-rationale. Sequenced last so it rides on top of the already-touched files. **Excludes the 17 hub findings** (routed upstream to `YahirReusableBot`).
**Depends on**: Phases 29–34 (sweeps residue in files those phases already opened)
**Requirements**: HARD-CLEAN-01, HARD-CLEAN-02
**Success Criteria** (what must be TRUE):

  1. The audit's dead/divergent code and inaccurate docs are removed or corrected — no dead second copy of the `-m` guard, no dead result-discarding `is_transient` call, no unreachable UTC-fallback branch masking an invariant, no misleading docstrings on passthrough/routing helpers.
  2. Every remaining low-severity WeatherBot latent/quality finding (config defaults, boundary comparisons, rounding, observability counters, resource/state-leak nits) is either fixed or carries an explicit in-code annotation recording it as accepted with rationale — nothing is silently left open.
  3. The v2.1 finding ledger reconciles: every in-scope WeatherBot finding is fixed, deliberately accepted-with-rationale, or explicitly deferred; the 17 hub findings are confirmed routed to the `HUB-FINDINGS-HANDOFF.md` and out of this milestone.

**Plans**: 8/9 plans executed

Plans:
**Wave 1** *(independent file clusters — no shared files, all parallel)*

- [x] 35-01-PLAN.md — Wave-0 dead-code negative-grep gate (`tests/test_dead_code_removed.py`) pinning F16/F46/F76/F92 removals stay gone (D-05)
- [x] 35-04-PLAN.md — config cluster: F74 HH:MM validator tighten + F75 resolve_location id-then-name, both with D-06 regression tests
- [x] 35-05-PLAN.md — uv/client cluster: F60 rounding fix + F61 counter reconcile + F68 non-JSON-2xx classified error (tests) + F67 vs redaction + F59/F72/F73/F58 accepted
- [x] 35-06-PLAN.md — interactive/render + models-docs: F105/F85 fixes (snapshots) + F66 docstring + F62/F51 accepted + F104 verify + F82/F79/F80/F83 fix-or-accept
- [x] 35-07-PLAN.md — multiday: F71 Friday-as-weekend accepted-with-rationale (flagged) + F70 drop-beats-add fix (regression test)

**Wave 2** *(dead-code removals + daemon cluster; gated on the Wave-0 gate)*

- [x] 35-02-PLAN.md — ops cluster: remove dead `_argv_is_weatherbot` (F46) + its exclusive test + discarded `is_transient` call (F92)
- [x] 35-03-PLAN.md — cli.py: remove dead `verbose` param (F76) + send-now dispatch guard (F78) + F77 exit-code accepted
- [x] 35-08-PLAN.md — daemon cluster (isolated): remove dead `emit_online`/`_do_reload` twins + orphaned tests (F16) + F103-live/F56/F57/F52/F88/F53 accepted

**Wave 3** *(reconciliation — pure docs; captures every disposition last)*

- [ ] 35-09-PLAN.md — Disposition Ledger (v2.1) write-back for all 99 WB/BOTH findings (D-03) + hub-routing confirm + 17-vs-18 note

**UI hint**: no

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
| 29. Startup Validation & Honest Alerting | v2.1 | 6/6 | Complete    | 2026-07-08 |
| 30. Secret Hygiene | v2.1 | 1/1 | Complete    | 2026-07-09 |
| 31. Send Atomicity, Exactly-Once & Persistence Robustness | v2.1 | 3/3 | Complete    | 2026-07-10 |
| 32. Timezone & Date-Boundary Correctness | v2.1 | 5/5 | Complete    | 2026-07-11 |
| 33. Interactive & Panel Robustness | v2.1 | 7/6 | Complete    | 2026-07-13 |
| 34. Test-Gap Backfill | v2.1 | 7/7 | Complete    | 2026-07-13 |
| 35. Cleanup Sweep | v2.1 | 8/9 | In Progress|  |
