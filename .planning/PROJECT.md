# WeatherBot

## What This Is

WeatherBot is a personal, always-on morning weather briefing bot. It pulls forecast
data from the OpenWeather API and delivers a templated daily briefing to the user
across messaging channels (Discord first; SMS and Telegram designed to slot in later).
It is built for one person who splits time between a home city on weekdays and a travel
city on weekends, so each location is configured independently with its own send
schedule. As of v1.1 it is also interactive and live-editable — the user can ask for a
location's briefing on demand (standalone CLI or an in-channel Discord `!weather` command)
and edit config/templates while the daemon picks them up live, with no restart. As of v1.3
it is also tap-to-drive — a pinned, restart-durable Discord control panel (location dropdown
+ command-button grid, results rendering in-place) is the operator's primary, typing-free
way to reach every read-only command.

## Core Value

Every morning, the user reliably receives a clear, correctly-located weather briefing
for the place they'll actually be that day — without lifting a finger.

## Current Milestone: v2.1 Hardening

**Goal:** Fix the correctness defects surfaced by the whole-project audit so the briefing spine stops failing silently — no boot-green misconfig that drops briefings forever, no leaked OpenWeather key, no duplicate/mis-alerted sends, and correct timezone/date boundaries — then backfill the test gaps that let those bugs hide and sweep the latent/cleanup debt.

**Target features:**
- **Startup validation + honest alerting** — the daemon `run` path validates config/templates like `check-config`, and permanent config/template errors alert instead of being misclassified as transient network faults (F05, F06).
- **Send atomicity & exactly-once hardening** — post-send bookkeeping can't release a delivered claim (no duplicate briefing), forecast-slot delivery failures are detected, retry doesn't re-fetch on delivery-only failure, HTTP send status is checked (F01, F08, F13).
- **Secret hygiene** — `appid` never rides in an exception/traceback that reaches logs; inbound Discord error paths don't dump the key (F12).
- **Timezone / date-boundary correctness** — catch-up survives local-midnight, UV all-clear has hysteresis, `daily[0]` is anchored to the configured IANA tz, the `_local_date_iso` helpers are de-duplicated (F14, F15, F31, F35, F91, F109).
- **Interactive/panel robustness** — bare location commands don't crash, cache/interaction races closed, rendering bugs fixed (F02, panel + render findings).
- **Persistence robustness** — store writes atomic, SQLite `WAL`/`busy_timeout`, cache eviction bounded.
- **Test-gap backfill** — kill the false-greens and add coverage on the exact paths the above bugs live in.
- **Cleanup sweep** — remaining low/dead-code/latent findings fixed behind the correctness work (in the same files, once already open).

**Scope:** 99 WeatherBot findings (88 WB + 11 shared). The **17 hub findings route upstream** — captured in `.planning/HUB-FINDINGS-HANDOFF.md` for a separate `YahirReusableBot` milestone (human-gated tag cut). Full detail: `.planning/WHOLE-PROJECT-REVIEW.md` + `.planning/audit-raw.json`.

## Last Shipped Milestone: v2.0 Bot Module Extraction ("The Great Decoupling")

**Shipped 2026-07-07.**

**Goal (delivered):** Extract WeatherBot's reusable bot infrastructure into a standalone, channel-agnostic
bot module (its own repo) that WeatherBot imports and adapts — with byte-identical behavior
(the test suite + golden oracle were the acceptance contract), establishing clean seams future bots (e.g. a
reminder bot) can reuse without inheriting a single weather assumption.

**Target deliverables:**
- In-place seam first — un-braid *mechanism from content* into a clean internal package
  boundary, tests proving zero behavior change; *then* physically split to its own repo.
- Generic scheduler engine — `register(job_id, trigger, callback)`, arbitrary triggers,
  exactly-once on generic `(job_id, occurrence)`, DST + catch-up; a `JobStore` seam *designed*
  for durable/dynamic jobs (in-memory impl only — durable jobstore = documented deferred
  extension point).
- Config hot-reload engine — generic holder + validate→swap→reconcile + file-watch + SIGHUP;
  app extends the schema (the high-effort seam).
- Delivery reliability + `Channel` abstraction — retry/backoff/Retry-After/alert/heartbeat.
- Process lifecycle — systemd `Type=notify` READY-gate / supervised restart with an
  app-provided health-check callback.
- Discord adapter with reusable panel — gateway bot + persistent-view plumbing + ack/operator
  gate/isolation + registry→panel builder + selected-*context* abstraction; WeatherBot supplies
  the location dropdown, forecast 2×2 grid, 📍/emoji polish.
- Physical repo split + uv git dependency.
- Extension-guide / documented-seams doc — the plug points and implemented-vs-extension-point
  status; module becomes its own GSD project with the durable-jobstore gap recorded as deferred.

**Guardrails:** Pure extraction (behavior byte-identical, no new user-facing feature). Litmus
test for every seam: *"could a reminder bot use this with zero weather assumptions?"* The module
is layered — channel-agnostic core + per-channel adapters (the panel lives in the Discord
adapter; SMS/Slack have no buttons). Promotion discipline for future bots:
build-in-consumer-then-promote, rule of three. **Explicitly deferred:** durable/dynamic jobstore
*impl*, Telegram/SMS/Slack channels, weather-pattern analysis.

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

All v1.2 requirements shipped and code-verified (18/18 — see milestones/v1.2-REQUIREMENTS.md; live-daemon UATs deferred at close, tracked in STATE.md):

- ✓ Self-describing command registry feeding CLI + Discord + auto-`help`, plus `alerts`/`locations`/`status`/`sun`/`wind`/`next-cloudy` read-only commands behind the operator guard ladder — v1.2 (Phase 12; CMD-09..16)
- ✓ Multi-day weekday & weekend forecast templates (detailed/compact, additive day flags), on demand and per-location scheduled, reusing One Call `daily` with no extra fetch — v1.2 (Phase 13; FCAST-01..07)
- ✓ `uv <loc>` command + current/max UV and predicted threshold-crossing time in the daily briefing, with a configurable `[uv]` sunscreen threshold + pre-warn lead — v1.2 (Phase 14; UV-01/02/03)
- ✓ Proactive daylight-only intraday UV monitor — pre-warn / crossing / all-clear alerts once/day/location, durable across restart, failure-isolated from the briefing spine — v1.2 (Phase 15; UV-04/05/06). Realizes deferred ENH-V2-02.

All v1.3 requirements shipped and verified (13/13 — see milestones/v1.3-REQUIREMENTS.md; Gate-2 live UAT driven on host `yahir-mint` at milestone close):

- ✓ Pinned, restart-durable smart panel — idempotent `!panel` summon re-summons to channel bottom, exactly one panel, strays cleaned up; persistent views (`timeout=None`, stable `custom_id`s, `add_view` in `setup_hook`) survive restart — v1.3 (Phases 17/18; PANEL-01/09)
- ✓ Tap-to-drive read-only commands (weather / uv / next-cloudy / sun / wind, + argless status / alerts) for the selected location, results rendering in-place with components reattached, every tap acked within Discord's 3s window — v1.3 (Phase 17; PANEL-02..06)
- ✓ Always-visible 2×2 forecast grid (Weekday/Weekend × Detailed/Compact) routing through the same shared dispatcher — v1.3 (Phase 19; PANEL-07)
- ✓ Operator-only enforcement on every interaction (ephemeral leak-free reject, no shared-panel clobber); text commands unchanged — v1.3 (Phase 17; PANEL-08)
- ✓ Panel command set derived from the v1.2 registry via one shared `dispatch_spec` (single source of truth — no parallel command list, drift structurally impossible) — v1.3 (Phase 16; PANEL-10)
- ✓ Interaction failure never delays/drops/stops a scheduled briefing (failure-isolation re-proven against a live scheduler for the callback path) — v1.3 (Phase 20; PANEL-11)
- ✓ Visible `📍` selected-location indicator with sensible startup default, emoji-coded button labels, self-ageing "Updated &lt;time&gt;" stamp on rendered results — v1.3 (Phase 20; PANEL-12/13)

All v2.0 requirements shipped and verified (15/15 — see milestones/v2.0-REQUIREMENTS.md; milestone audit passed, live `yahir-mint` Gate-2 driven at close):

- ✓ Byte-identical extraction proven by a golden/characterization oracle re-run after every seam + physical split — v2.0 (Phase 21; BHV-01/02)
- ✓ Channel abstraction + delivery-reliability wrapper extracted weather-free into a clean in-place package boundary + import-hygiene/litmus gate — v2.0 (Phase 22; SEAM-01, PKG-01)
- ✓ Generic scheduler engine (`register`/exactly-once) + serialization-clean `JobStore` Protocol (in-memory impl; durable impl deferred) — v2.0 (Phase 23; SEAM-02/03)
- ✓ Config hot-reload engine over an app-defined schema via injected `validate`/`desired_jobs` hooks — v2.0 (Phase 24; SEAM-04)
- ✓ Lifecycle READY-gate on an app health-check + single composition root; four leak-points injected (litmus-clean) — v2.0 (Phase 25; SEAM-05, APP-01/02)
- ✓ Self-describing command registry + shared dispatcher; CLI/Discord/help all derive from one registry — v2.0 (Phase 26; SEAM-06)
- ✓ Discord adapter (`BotThread` + `PanelKit` + `SelectedContext`) with injected `render` resolving the `render_embed`↔`PanelView` cycle; frozen `custom_id`s + `discord.py==2.7.1` — v2.0 (Phase 27; SEAM-07)
- ✓ Physical repo split to `YahirReusableBot` + uv git tag pin (`v0.1.1`) + `EXTENSION-GUIDE`; clean-venv install + live `yahir-mint` restart UAT — v2.0 (Phase 28; PKG-02, DOCS-01)

### Active

**v2.1 Hardening is active (started 2026-07-07)** — an audit-driven correctness/hardening milestone. Requirements are enumerated in `.planning/REQUIREMENTS.md` (grouped: startup-validation, send-atomicity, secret-hygiene, timezone-boundaries, interactive-robustness, persistence, test-backfill, cleanup) and traced to the 99 WeatherBot findings in `.planning/WHOLE-PROJECT-REVIEW.md`. The 17 hub findings are handed off in `.planning/HUB-FINDINGS-HANDOFF.md`.

**Future candidates (deferred — to be defined in a later milestone):**

- [ ] Telegram delivery channel (validates the channel abstraction with a second free channel) — CHAN-V2-01
- [ ] SMS delivery via Twilio — CHAN-V2-02
- [ ] On-demand lookup for *arbitrary / geocoded-anywhere* locations (extends CMD-V2-01 beyond configured names) — CMD-V2-02
- [ ] Weather-pattern analysis over the v1-persisted SQLite store (trends, history queries) — ANLY-V2-01
- [ ] History query/export interface (e.g. CSV dump) — ANLY-V2-02
- [ ] Real-time severe-weather push alerts (continuous monitoring loop) — ENH-V2-03 (the v1.2 UV monitor establishes the intraday-loop pattern this would extend)
- [ ] Grey out / disable command buttons until a location is selected — PANEL-V2-01 (likely unnecessary given a sensible startup default; revisit only if a no-location state proves reachable)

### Out of Scope

- Web/GUI configuration — config is file-based for a single personal user; a UI adds disproportionate complexity
- Multi-user / accounts — this is a personal single-user tool
- Full multi-user interactive Discord gateway bot — config file is the interface; the v1.1 bot is a single-operator command→reply surface only (operator-id guarded), not a multi-user bot
- Full templating engine (logic/loops/conditionals) — named placeholders + code-computed derived fields instead
- Hot-reloading secrets / the bot token — secret rotation is a restart boundary; `DISCORD_BOT_TOKEN` lives in git-ignored `.env` like the v1 webhook URL (v1.1 decision)
- Two-way config editing via Discord chat — config stays file-based; the bot reads weather and reports reload outcomes, it does not edit config (v1.1 decision)
- Migrating the briefing scheduler to `AsyncIOScheduler` — the verified sync scheduler spine stays; the inbound bot runs in its own thread instead (v1.1 decision)

## Current State

**v2.0 Bot Module Extraction — SHIPPED 2026-07-07 (all 8 phases complete + verified; milestone audit passed 15/15).** The reusable bot core is physically extracted into its own PUBLIC repo `YahirReusableBot` (import root `yahir_reusable_bot`, `github.com/Ygaray/YahirReusableBot`, no console script); WeatherBot consumes it via a uv git **tag pin** (`[tool.uv.sources]` → `v0.1.1` @ `7f3cc00`, reproducible `uv.lock`) with an uncommitted venv editable overlay for local co-dev. Phase 28 closed the split: in-tree module removed, wheel collapsed to `["weatherbot"]`, `discord.py==2.7.1` pin moved into the module (inherited transitively), a startup provenance line announces the deployed sha (PEP 610 `direct_url.json` via `importlib.metadata`), and the `EXTENSION-GUIDE` + module GSD project + repin-ritual + promotion-ledger are stood up. **Gate-2 live UAT PASSED on host `yahir-mint`** (2026-07-07): restart against the pinned module + panel/reload/briefing/CLI all verified — and a live-only `on_message` recursion bug (broke `!panel`) was found and fixed *during* the UAT, shipped as module **v0.1.1** (`7f3cc00`), which the deploy is repinned to. Integration audit confirmed 6/6 module seams wired at the single composition root; retroactive security gate clean across phases 23–28 (`threats_open: 0`). All 15 requirements validated. **Next:** define the next milestone via `/gsd-new-milestone`.

**Shipped v1.3 Discord Control Panel** (2026-06-27) — the bot is now tap-to-drive. A pinned, restart-durable Discord control panel (location dropdown + emoji-coded command grid + always-visible 2×2 forecast grid) renders every read-only command result in-place, operator-gated, as a third caller of the one shared `dispatch_spec` core (no command-set drift). All 13/13 requirements verified; **649 tests green** on `main`; Gate-2 live UAT driven on host `yahir-mint` at close (found+fixed 1 production bug, +2 UX refinements: `!panel` re-summons to channel bottom — 260626-uqp; forecast grid made always-visible — 260626-u8y). **No new runtime dependencies** — components ride the existing discord.py 2.7.1 gateway. ~10k LOC `weatherbot/` + ~16.4k LOC `tests/` Python. Next: define v2.0 via `/gsd-new-milestone`.

<details>
<summary>v1.3 per-phase narrative (Phases 16–20)</summary>

Phase 20 complete (2026-06-27): isolation hardening + polish (PANEL-11/12/13). PANEL-11 re-proves the milestone's load-bearing failure-isolation guarantee for the new interaction-callback path with **zero production change** (D-08): `tests/test_scheduler.py::test_hanging_callback_never_stops_live_briefing` fires a real briefing on a live `BackgroundScheduler` while a panel callback is wedged on an `await asyncio.Event().wait()` (await-shaped, not a CPU spin — D-08a) and asserts the briefing still fires on time, plus a D-08b executor-sharing audit (`tests/test_dispatch.py`) confirming the briefing spine never borrows the panel's asyncio default executor. Polish landed in the one shared `render_embed` builder + the panel: a `📍 {location}` selected-location indicator (suppressed on argless replies, default `locations[0]` — D-01/D-03), emoji on every button via discord.py `emoji=` with text labels kept (locked D-05 set — D-04), and an `Updated <t:{unix}:t> (<t:{unix}:R>)` relative-timestamp stamp in the embed description (never title; native `embed.timestamp` retained — D-06/D-07). The load-bearing fix: `_render_view`'s clone path now carries `emoji=` onto the plain Button clones and re-derives `SelectOption(default=)` from `_selected_location` (never `Select.values`) so the polish survives every ack/collapse render — proven by clone-path tests, not just first construction. **649 tests green**; code review found 0 blockers, 3 warnings — WR-01 (`label=o.label`) and WR-02 (`min_values`/`max_values`) clone-completeness gaps were FIXED, WR-03 (a test-only daemon-thread leak) noted as an accepted hygiene trade. Gate-1 verification passed (4/4 must-haves); on-device emoji pixel rendering, `<t:R>` self-aging, and live `📍`/dropdown visual confirmation are deferred Gate-2 (milestone-close) obligations. **Next: `/gsd-complete-milestone` to close v1.3.**

Phase 19 complete (2026-06-26): the forecast two-tier sub-options (PANEL-07). A `Forecast` toggle in row 2 (alongside `Status`/`Alerts`) reveals a 2×2 variant sub-grid in rows 3–4 (`Weekday/Weekend` × `Detailed/Compact`); each variant builds `ForecastFlags(variant=…, location=<selected>)` directly and routes through the shared `dispatch_spec` via a new **additive `flags=` param** (byte-identical when `flags=None`, D-02) — the panel is the third caller of the forecast core, no parallel logic. One canonical persistent view holds all 13 children; reveal/collapse is a cosmetic `edit_message(view=…)` swap that **never mutates the registered view** (D-05 post-restart routing), via a merged `_render_view(expanded, disabled)` that replaced the old `_disabled_copy` two-path clone. `_assert_layout` is now complete and load-bearing (≤5 rows / ≤5 per row / ≤25 children / id≤100 / label≤80) — the revealed panel sits at exactly 5/5 rows, with both a fits-test and an overflow-trips-assert test (D-08, SC#3). **635 tests green**; code review found 0 blockers, 3 warnings — two D-04 collapse-on-action regressions (WR-01 collapsed-ack flicker, WR-02 error-path re-reveal) were FIXED with a regression test pinning the transient ack/error view shape. Gate-1 verification passed at the mechanism level (7/7 must-haves); 2 live-Discord behaviors (live reveal + variant tap, post-restart routing on a still-revealed panel) are deferred Gate-2 (milestone-close) obligations tracked in 19-UAT.md. Next: Phase 20 (isolation hardening + polish).

Phase 18 complete (2026-06-26): restart durability for the pinned panel (PANEL-01/PANEL-09). `PanelView` is now registered as a persistent view via `client.add_view(...)` inside `setup_hook` (not `on_ready`, so reconnects can't duplicate), so component clicks re-bind by `custom_id` across process restarts. A new required `[bot] panel_channel_id` config field (D-04) is read live by the summon handler from the config holder (`holder.current().bot.panel_channel_id`; the build_client/BotThread param threading was removed in the post-review cleanup as dead weight). An operator-gated, idempotent `!panel` summon (`_handle_panel_summon`) resolves-or-aborts the channel, runs an eager permission preflight using `pin_messages` (the 2026-01-12 Discord split, **not** `manage_messages`) + `embed_links` with a CRITICAL log on miss, scans pins via `async for channel.pins()` with a marker-strict `_is_owned_panel` (`wb:` custom_id) ownership check, reuses the first owned panel in place and deletes strays (exactly one), and wraps each write against `discord.Forbidden`. The open design decision resolved to **recreate/scan-on-restart, no persisted `message_id`/selection** (D-01/D-02). **622 tests green**; 0 blockers in code review (3 non-blocking warnings in 18-REVIEW.md — notably `panel_channel_id` threaded but read live rather than from the param). Gate-1 verification passed at the mechanism level (11/11 must-haves); 3 live-restart behaviors (SC#1 re-bind, SC#3 default-on-restart, SC#2 live reconcile) are deferred Gate-2 (milestone-close) obligations tracked in 18-UAT.md. Next: Phase 19 (forecast two-tier sub-options).

Phase 17 complete (2026-06-24): the minimal persistent panel core wiring — `weatherbot/interactive/panel.py` (`PanelView(discord.ui.View, timeout=None)` + `CmdButton` + `LocationSelect`) — wires a tap-to-drive operator panel onto the Phase-16 `dispatch_spec` seam. The three load-bearing correctness mechanisms are in place and unit-pinned: single-ack defer-then-edit (one `response.edit_message("⏳ Fetching…")` before the off-loop fetch, result via `edit_original_response` — never a 2nd `response.*`), the `interaction_check` operator gate with an identity-free ephemeral reject + structlog audit log, and a per-callback non-propagating envelope + `View.on_error` backstop. W2 also made `weather` a first-class registry command (byte-identical to `build_inbound_embed`) with a CLI subparser skip-guard so every button routes uniformly through `dispatch_spec → render_embed` (PANEL-02/03/04/05/06/08). **600 tests green**; 0 blockers in code review (2 non-blocking warnings tracked in 17-REVIEW.md). Gate-1 verification passed at the mechanism level (9/9 must-haves); 5 live-Discord behaviors are deferred Gate-2 (milestone-close) obligations tracked in 17-UAT.md. Persistence across restart + summon/lifecycle remain Phase 18. Next: Phase 18 (persistence + summon/lifecycle — restart durability).

Phase 16 complete (2026-06-23): the duplicated arg-adaptation dispatch ladder in `on_message` + the CLI is lifted into one shared `weatherbot/interactive/dispatch.py` (`dispatch_reply` sync ladder + `dispatch_spec` async fetch wrapper), so command-set drift is structurally impossible before any panel callback exists (PANEL-10). Behavior-preserving — replies byte-identical.

</details>

**Shipped v1.2** (2026-06-20) — command-driven, multi-forecast, UV-aware. **575 tests green** on `main`; all 18 v1.2 requirements code-verified; all cross-phase integration seams wired. **Deferred at close:** 4 live-daemon UATs on host `yahir-mint` (each requires one deploy + `systemctl restart weatherbot`; tracked in STATE.md Deferred Items / `<N>-UAT.md`, run via `/gsd-verify-work <N>`). No new runtime dependencies were added in v1.2 — all work reused the existing One Call 3.0 payload, APScheduler spine, registry, and config-reload machinery.

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
| One self-describing command registry as the single source of truth for CLI + Discord + `help` | Adding a command must not require editing three places; `help` must never drift from the real command set | ✓ Phase 12 — `registry.COMMANDS` auto-derives CLI subparsers, Discord dispatch, and `render_help`; anti-drift test-locked; commands wired via lazy `_wire_handlers` (no import cycle) |
| Widen the One Call `exclude` to keep `hourly[]` (shared seam, owned by Phase 12) | `next-cloudy`, UV crossing, and the UV monitor all need `hourly[]`; re-fetching or per-phase trimming would burn API calls and hide gaps behind empty fixtures | ✓ Phase 12 — `exclude="minutely"` + regression canary; one fetch feeds forecast/UV/monitor; fixtures carry real `hourly[]` |
| `compute_uv()` as a pure, interactive-layer-free helper reused by briefing + command + monitor | Three consumers must not each re-derive UV crossing math; the monitor (Phase 15) needs it without dragging in the interactive layer | ✓ Phase 14 — `weather/uv.py` `compute_uv`/`UvSummary` (stdlib + dataclasses only); 3 call sites, no duplicated math; degrades-not-raises on malformed payload (briefing-spine isolation) |
| One extensible `[uv]` config table (threshold + lead in Phase 14, monitor knobs in Phase 15) | A second UV table would fragment config and risk drift; absent-table-loads-as-defaults keeps existing configs valid | ✓ Phase 14/15 — single frozen `UvConfig` extended in place; `Field(default_factory=UvConfig)` zero-migration; hot-reloaded by the whole-Config re-read |
| Proactive UV monitor as a failure-isolated APScheduler `IntervalTrigger` job, not a new thread | UV-06 demands the monitor never gate/delay/drop a briefing; reusing the scheduler's per-job isolation + a two-layer envelope is simpler and safer than a hand-rolled thread | ✓ Phase 15 — `__uvmonitor__` (`max_instances=1`/`misfire_grace_time=None`/`coalesce=True`), two-layer try/except, dedicated `uv_alerts` dedup namespace; raising-tick-doesn't-stop-scheduler proven on a live BackgroundScheduler |
| One shared `dispatch_spec` core for every command surface (panel = third caller) before any panel callback exists | The panel must never drift from the real command set; extracting the dispatcher first makes a parallel hardcoded list structurally impossible | ✓ Phase 16 — `interactive/dispatch.py` (`dispatch_reply` + `dispatch_spec`); `on_message`, CLI, and panel all route through it; `grep spec.handler(` returns only `dispatch.py`; behavior-preserving (PANEL-10) |
| Single-ack defer-then-edit + per-callback non-propagating envelope for panel interactions | Discord's 3s ack window + a slow cold fetch must never show "interaction failed", and a raising/hanging callback must never escape to the gateway loop | ✓ Phase 17 — one `response.edit_message("⏳ Fetching…")` then `edit_original_response`; `interaction_check` operator gate with identity-free ephemeral reject; `View.on_error` backstop (PANEL-05/06/08) |
| Recreate/scan-on-restart, no persisted `message_id`/selection (persistent views by `custom_id`) | Discord won't persist select state and a new datastore for a cosmetic nicety isn't worth it; `add_view` in `setup_hook` re-binds clicks by `custom_id` across restarts | ✓ Phase 18 — required `[bot] panel_channel_id`; idempotent `!panel` find-or-create-one + delete-strays via `pin_messages` (the 2026-01-12 Discord split, not `manage_messages`); default-on-restart `locations[0]` (PANEL-01/09) |
| Forecast variants ride an additive `flags=` seam on `dispatch_spec` (byte-identical when `flags=None`) | The panel forecast must reuse the exact text-command variant logic, not a parallel path; one canonical persistent view holds all children, reveal/collapse is cosmetic only | ✓ Phase 19 — `ForecastFlags(variant=, location=)` through the shared dispatcher; `_render_view` clone never mutates the registered view; `_assert_layout` (≤5/5 rows) load-bearing. Later made always-visible at Gate-2 (260626-u8y) (PANEL-07) |
| Re-prove briefing failure-isolation for the interaction path with zero production change | The milestone's load-bearing guarantee (briefing always fires) must hold for the new callback path, mirroring the Phase-15 raising-tick proof | ✓ Phase 20 — live-`BackgroundScheduler` test: sentinel briefing keeps firing while a panel callback is wedged on `await asyncio.Event().wait()`; executor-sharing audit confirms the spine never borrows the panel's default executor (PANEL-11) |
| `!panel` re-summons a fresh panel to the channel bottom (not reuse-in-place) | Gate-2 live UX: a panel buried up-channel is hard to reach; re-summoning to the bottom keeps the cockpit where the operator is looking, still exactly one panel | ✓ Gate-2 quick task 260626-uqp — supersedes the Phase-18 reuse-in-place summon (PANEL-01) |
| Extract reusable core in-place first, `git mv` to its own repo last (v2.0) | A rename-in-place with the suite green de-risks the physical split to a pure move; the boundary subpackage is named what the extracted package becomes | ✓ v2.0 — clean `yahir_reusable_bot` boundary (Phases 22–27) then physical split (Phase 28); byte-identical oracle green throughout |
| Consume the extracted module via a uv git **tag pin** + frozen `uv.lock`, editable overlay for co-dev (v2.0) | Deploy needs a reproducible, immutable pin; local cross-repo work needs live edits — uv has no committed path-override, so the overlay stays uncommitted and `uv build --no-sources` is the leak backstop | ✓ v2.0 — `[tool.uv.sources]` `tag=v0.1.1`, sha frozen; startup provenance line + `direct_url.json` sha cross-check prove the deployed sha; REPIN-RITUAL + PROMOTION-LEDGER |
| Every app-specific coupling injected at ONE composition root; litmus-gate the module weather-free (v2.0) | A reminder bot must reuse the core with zero weather assumptions; the four leak-points (SelectedContext/id-deriver/health-check/panel cosmetics) injected app-side keep the module domain-free, enforced by a standing litmus grep + grimp one-way-dependency gate | ✓ v2.0 (Phase 25) — `build_runtime` wires all seams; integration audit confirmed 6/6 wired, litmus + grimp gates green |
| Resolve the `render_embed`↔`PanelView` cycle by ownership, not a deferred import (v2.0) | Porting an in-function import across the boundary re-couples the module to the app; owning `render_embed` app-side and injecting it into `PanelKit` kills both edges | ✓ v2.0 (Phase 27) — `_render_bridge` closure injects `render`; both cycle edges dead, proven by import-hygiene test |

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
*Last updated: 2026-07-11 — v2.1 Hardening in progress (4/7 phases). Phase 32 (Timezone & Date-Boundary Correctness) complete + verified (4/4 must-haves): HARD-TZ-01..04. Catch-up now recovers a slot missed across local midnight — `plan_catchup` evaluates {today, yesterday-local} candidates and keys `MissedSlot`/`was_sent` on the CANDIDATE day (F14). The UV all-clear gained hysteresis — it fires only on `below AND past_peak AND window_over` from `UvSummary` (a momentary solar-noon dip can no longer latch "protect window over"; empty-hourly degrades to don't-post, no new store table), and the pre-warn↔crossing↔all-clear lifecycle was audited for no never-fire gap (F15). "Today" is now anchored to the configured IANA tz everywhere via ONE shared `select_today_daily` — `models.from_payloads`, `uv.compute_uv`, `uv._today_daytime_points`'s sunrise/sunset **window bound** (the real F31 defect site, caught by the plan-checker), and the `uvmonitor` daylight gate all pick the entry whose own local date is today (never positional `daily[0]`), with hourly points sorted before interpolation (F32) and naive `now_utc` treated as UTC in BOTH the briefing and UV paths (F33). The three duplicated `_local_date_iso` helpers (models/store/uvmonitor) are unified into one new pure leaf module `weatherbot/weather/dates.py` (`local_date_iso`/`local_date_for` + `select_today_daily`), so the rendered `{date}` and persisted `local_date` can never diverge (F69). **F91 was determined a non-bug** and pinned rather than "fixed": a live apscheduler probe proved `CronTrigger` fires DST fall-back at fold=0 and catch-up already composes fold=0 (they agree) — the mandated both-folds-`min()` would have regressed the locked SCHD-04 band test, so `test_catchup_fold_grace_not_inflated` was rewritten to pin the fold=0/CronTrigger agreement instead. Executed test-first: 845 tests green (10 failing-first RED→GREEN + 2 code-review regressions). The post-execution code review found 1 blocker + 3 warnings — CR-01 was the phase's own F33 goal leaking through the UV path (`compute_uv` didn't normalize a naive `now`), WR-01 the `uvmonitor` daylight gate still reading positional `daily[0]` — all fixed test-first and re-verified (32-REVIEW.md status: resolved). Deferred Gate-2: `systemctl restart weatherbot` on host `yahir-mint` to confirm the new `dates.py` loads + catch-up runs clean at boot, and a true wall-clock local-midnight/DST recovery observation. Builds on Phase 31 (send atomicity/store) and Phase 29 (validated boot).*

<details>
<summary>Phase 31 narrative</summary>

*Phase 31 (Send Atomicity, Exactly-Once & Persistence Robustness) complete + verified (16/16 must-haves): HARD-DELIV-01..04 + HARD-STORE-01/02. The F01 duplicate-briefing critical is closed — post-send bookkeeping (`resolve_alert`/`stamp_success`) **and** the success `_log.info` now sit inside a log-and-swallow in `fire_slot`, so no path after `result.ok` can reach `release_claim` (a code-review round caught that the first fix was one line short — the trailing log/return was still exposed to a `_LiveStderr` `BrokenPipeError`; fixed as CR-01). F08: `fire_forecast_slot` inspects `DeliveryResult.ok` and escalates a delivery-auth 401/403 immediately (WR-03). DELIV-03: a per-fire `fetch_cache` reuses the single fetched payload on a delivery-only retry (no re-fetch) while keeping fetch-429 Retry-After honoring. DELIV-04: `discord._post` raises a redacted-URL `httpx.HTTPStatusError` on 401/403 only, landing in the existing `daemon.py` auth arm → `auth_failed` (zero hub change — cross-repo jurisdiction respected). Store: shared `_connect()` with `busy_timeout=5000`, persistent `WAL` set once in `init_db` (now wired at the composition root), 4 status reads open `mode=ro` (F10 read-write-lock gone; read-only URI percent-encoded per WR-01), `persist` confirmed single-transaction atomic. 833 tests green (14 new regressions incl. reproduce-first F01 RED evidence); code review found 1 critical + 3 warnings, all fixed and re-verified in source (31-REVIEW-FIX.md). Deferred Gate-2: confirm `PRAGMA journal_mode=wal` on the live `data/weatherbot.db` (host `yahir-mint`) after a `systemctl restart`. Builds on Phase 30 (secret hygiene) and Phase 29 (startup validation).*

</details>
