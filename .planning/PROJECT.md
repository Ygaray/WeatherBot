# WeatherBot

## What This Is

WeatherBot is a personal, always-on morning weather briefing bot. It pulls forecast
data from the OpenWeather API and delivers a templated daily briefing to the user
across messaging channels (Discord first; SMS and Telegram designed to slot in later).
It is built for one person who splits time between a home city on weekdays and a travel
city on weekends, so each location is configured independently with its own send
schedule. As of v1.1 it is also interactive and live-editable — the user can ask for a
location's briefing on demand (standalone CLI or an in-channel Discord `!weather` command)
and edit config/templates while the daemon picks them up live, with no restart.

## Core Value

Every morning, the user reliably receives a clear, correctly-located weather briefing
for the place they'll actually be that day — without lifting a finger.

## Current Milestone: v1.3 Discord Control Panel

**Goal:** Make the bot tap-to-drive — a pinned, always-live Discord panel replaces typing as
the primary way the operator accesses every command.

**Target features:**
- **Smart panel** — one message with a location dropdown at top + a grid of command buttons;
  results render in-place (the message edits, no new-message spam).
- **Pinned & persistent** — a single pinned panel whose buttons survive bot restarts/deploys
  (persistent views with stable `custom_id`s, re-registered on startup); summonable but
  meant to live pinned so the operator never has to type to bring it up.
- **Drives the existing read-only commands** — weather / uv / next-cloudy / sun / wind /
  alerts / status, each 1-tap once a location is selected (argless commands ignore the
  location).
- **Forecast button + sub-options** — expands to Weekday/Weekend × Detailed/Compact, mirroring
  the text command's variants.
- **Pure UI layer** — no new weather data/features; reuses the v1.2 command registry as the
  single source of truth so the panel never drifts from the real command set.

**Builds on:** v1.1's discord.py gateway bot (`interactive/bot.py` / `BotThread`) — button
clicks arrive as interaction events over the existing gateway connection, so no new inbound
infrastructure is needed. Stays operator-only (the guard ladder checks `interaction.user.id`,
so non-operator taps on the public pinned panel get a polite reject). Text commands stay
unchanged; the panel is additive.

**Deferred candidates** (Telegram/SMS channels, geocoded-anywhere lookup, SQLite
weather-pattern analysis/export, real-time severe-weather push) stay deferred for a later
milestone.

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

### Active

**v1.3 Discord Control Panel** — tap-to-drive interaction layer over the existing commands:

- [ ] Pinned, persistent smart panel (location dropdown + command-button grid) that survives bot restarts
- [ ] In-place result rendering (the panel message edits rather than posting new messages)
- [ ] 1-tap access to the read-only commands (weather / uv / next-cloudy / sun / wind / alerts / status) for the selected location
- [ ] Forecast button with Weekday/Weekend × Detailed/Compact sub-options
- [ ] Operator-only enforcement on every interaction; text commands remain unchanged

(Final REQ-IDs scoped in REQUIREMENTS.md and mapped to phases in ROADMAP.md.)

**Future candidates (deferred — to be defined in a later milestone):**

- [ ] Telegram delivery channel (validates the channel abstraction with a second free channel) — CHAN-V2-01
- [ ] SMS delivery via Twilio — CHAN-V2-02
- [ ] On-demand lookup for *arbitrary / geocoded-anywhere* locations (extends CMD-V2-01 beyond configured names) — CMD-V2-02
- [ ] Weather-pattern analysis over the v1-persisted SQLite store (trends, history queries) — ANLY-V2-01
- [ ] History query/export interface (e.g. CSV dump) — ANLY-V2-02
- [ ] Real-time severe-weather push alerts (continuous monitoring loop) — ENH-V2-03 (the v1.2 UV monitor establishes the intraday-loop pattern this would extend)

### Out of Scope

- Web/GUI configuration — config is file-based for a single personal user; a UI adds disproportionate complexity
- Multi-user / accounts — this is a personal single-user tool
- Full multi-user interactive Discord gateway bot — config file is the interface; the v1.1 bot is a single-operator command→reply surface only (operator-id guarded), not a multi-user bot
- Full templating engine (logic/loops/conditionals) — named placeholders + code-computed derived fields instead
- Hot-reloading secrets / the bot token — secret rotation is a restart boundary; `DISCORD_BOT_TOKEN` lives in git-ignored `.env` like the v1 webhook URL (v1.1 decision)
- Two-way config editing via Discord chat — config stays file-based; the bot reads weather and reports reload outcomes, it does not edit config (v1.1 decision)
- Migrating the briefing scheduler to `AsyncIOScheduler` — the verified sync scheduler spine stays; the inbound bot runs in its own thread instead (v1.1 decision)

## Current State

**v1.3 Discord Control Panel — all phases complete (2026-06-27); ready for milestone close.** Phase 20 complete (2026-06-27): isolation hardening + polish (PANEL-11/12/13). PANEL-11 re-proves the milestone's load-bearing failure-isolation guarantee for the new interaction-callback path with **zero production change** (D-08): `tests/test_scheduler.py::test_hanging_callback_never_stops_live_briefing` fires a real briefing on a live `BackgroundScheduler` while a panel callback is wedged on an `await asyncio.Event().wait()` (await-shaped, not a CPU spin — D-08a) and asserts the briefing still fires on time, plus a D-08b executor-sharing audit (`tests/test_dispatch.py`) confirming the briefing spine never borrows the panel's asyncio default executor. Polish landed in the one shared `render_embed` builder + the panel: a `📍 {location}` selected-location indicator (suppressed on argless replies, default `locations[0]` — D-01/D-03), emoji on every button via discord.py `emoji=` with text labels kept (locked D-05 set — D-04), and an `Updated <t:{unix}:t> (<t:{unix}:R>)` relative-timestamp stamp in the embed description (never title; native `embed.timestamp` retained — D-06/D-07). The load-bearing fix: `_render_view`'s clone path now carries `emoji=` onto the plain Button clones and re-derives `SelectOption(default=)` from `_selected_location` (never `Select.values`) so the polish survives every ack/collapse render — proven by clone-path tests, not just first construction. **649 tests green**; code review found 0 blockers, 3 warnings — WR-01 (`label=o.label`) and WR-02 (`min_values`/`max_values`) clone-completeness gaps were FIXED, WR-03 (a test-only daemon-thread leak) noted as an accepted hygiene trade. Gate-1 verification passed (4/4 must-haves); on-device emoji pixel rendering, `<t:R>` self-aging, and live `📍`/dropdown visual confirmation are deferred Gate-2 (milestone-close) obligations. **Next: `/gsd-complete-milestone` to close v1.3.**

Phase 19 complete (2026-06-26): the forecast two-tier sub-options (PANEL-07). A `Forecast` toggle in row 2 (alongside `Status`/`Alerts`) reveals a 2×2 variant sub-grid in rows 3–4 (`Weekday/Weekend` × `Detailed/Compact`); each variant builds `ForecastFlags(variant=…, location=<selected>)` directly and routes through the shared `dispatch_spec` via a new **additive `flags=` param** (byte-identical when `flags=None`, D-02) — the panel is the third caller of the forecast core, no parallel logic. One canonical persistent view holds all 13 children; reveal/collapse is a cosmetic `edit_message(view=…)` swap that **never mutates the registered view** (D-05 post-restart routing), via a merged `_render_view(expanded, disabled)` that replaced the old `_disabled_copy` two-path clone. `_assert_layout` is now complete and load-bearing (≤5 rows / ≤5 per row / ≤25 children / id≤100 / label≤80) — the revealed panel sits at exactly 5/5 rows, with both a fits-test and an overflow-trips-assert test (D-08, SC#3). **635 tests green**; code review found 0 blockers, 3 warnings — two D-04 collapse-on-action regressions (WR-01 collapsed-ack flicker, WR-02 error-path re-reveal) were FIXED with a regression test pinning the transient ack/error view shape. Gate-1 verification passed at the mechanism level (7/7 must-haves); 2 live-Discord behaviors (live reveal + variant tap, post-restart routing on a still-revealed panel) are deferred Gate-2 (milestone-close) obligations tracked in 19-UAT.md. Next: Phase 20 (isolation hardening + polish).

Phase 18 complete (2026-06-26): restart durability for the pinned panel (PANEL-01/PANEL-09). `PanelView` is now registered as a persistent view via `client.add_view(...)` inside `setup_hook` (not `on_ready`, so reconnects can't duplicate), so component clicks re-bind by `custom_id` across process restarts. A new required `[bot] panel_channel_id` config field (D-04) is read live by the summon handler from the config holder (`holder.current().bot.panel_channel_id`; the build_client/BotThread param threading was removed in the post-review cleanup as dead weight). An operator-gated, idempotent `!panel` summon (`_handle_panel_summon`) resolves-or-aborts the channel, runs an eager permission preflight using `pin_messages` (the 2026-01-12 Discord split, **not** `manage_messages`) + `embed_links` with a CRITICAL log on miss, scans pins via `async for channel.pins()` with a marker-strict `_is_owned_panel` (`wb:` custom_id) ownership check, reuses the first owned panel in place and deletes strays (exactly one), and wraps each write against `discord.Forbidden`. The open design decision resolved to **recreate/scan-on-restart, no persisted `message_id`/selection** (D-01/D-02). **622 tests green**; 0 blockers in code review (3 non-blocking warnings in 18-REVIEW.md — notably `panel_channel_id` threaded but read live rather than from the param). Gate-1 verification passed at the mechanism level (11/11 must-haves); 3 live-restart behaviors (SC#1 re-bind, SC#3 default-on-restart, SC#2 live reconcile) are deferred Gate-2 (milestone-close) obligations tracked in 18-UAT.md. Next: Phase 19 (forecast two-tier sub-options).

Phase 17 complete (2026-06-24): the minimal persistent panel core wiring — `weatherbot/interactive/panel.py` (`PanelView(discord.ui.View, timeout=None)` + `CmdButton` + `LocationSelect`) — wires a tap-to-drive operator panel onto the Phase-16 `dispatch_spec` seam. The three load-bearing correctness mechanisms are in place and unit-pinned: single-ack defer-then-edit (one `response.edit_message("⏳ Fetching…")` before the off-loop fetch, result via `edit_original_response` — never a 2nd `response.*`), the `interaction_check` operator gate with an identity-free ephemeral reject + structlog audit log, and a per-callback non-propagating envelope + `View.on_error` backstop. W2 also made `weather` a first-class registry command (byte-identical to `build_inbound_embed`) with a CLI subparser skip-guard so every button routes uniformly through `dispatch_spec → render_embed` (PANEL-02/03/04/05/06/08). **600 tests green**; 0 blockers in code review (2 non-blocking warnings tracked in 17-REVIEW.md). Gate-1 verification passed at the mechanism level (9/9 must-haves); 5 live-Discord behaviors are deferred Gate-2 (milestone-close) obligations tracked in 17-UAT.md. Persistence across restart + summon/lifecycle remain Phase 18. Next: Phase 18 (persistence + summon/lifecycle — restart durability).

Phase 16 complete (2026-06-23): the duplicated arg-adaptation dispatch ladder in `on_message` + the CLI is lifted into one shared `weatherbot/interactive/dispatch.py` (`dispatch_reply` sync ladder + `dispatch_spec` async fetch wrapper), so command-set drift is structurally impossible before any panel callback exists (PANEL-10). Behavior-preserving — replies byte-identical.

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
*Last updated: 2026-06-27 — after completing Phase 20 (isolation hardening + polish); v1.3 all phases complete, ready for milestone close*
