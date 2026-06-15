# Project Research Summary

**Project:** WeatherBot — milestone v1.1 "Interactive & Live-Config"
**Domain:** Adding an inbound Discord command bot + full-config hot-reload to an already-shipped always-on Python scheduler daemon
**Researched:** 2026-06-15
**Confidence:** HIGH

## Executive Summary

WeatherBot v1.1 bolts two new surfaces onto a *shipped, hardened* v1.0 daemon (thread-based APScheduler `BackgroundScheduler`, sync OpenWeather/httpx fetch, regex template renderer, SQLite sent-log with an exactly-once `(location, send_time, local_date)` key, outbound `DiscordWebhookChannel`, systemd `Type=notify` `Restart=always` with a startup health gate, 186 green tests). The two features are **CMD-V2-01** (on-demand `weather [location]` lookup over *configured* locations only, exposed both as a standalone CLI one-shot and as an in-channel Discord reply) and **ENH-V2-01** (full-config hot-reload of locations/schedules/units/templates via file-watch plus an explicit trigger, with validate-and-keep-old-config-on-failure). This is fundamentally an *integration* milestone, not a greenfield one — the dominant risk is regressing v1.0's "the morning briefing always goes out" guarantee, not building new capability.

The research converges cleanly (all four files HIGH confidence, architecture read directly from v1.0 source) on a low-blast-radius approach: **add only two third-party dependencies** — `discord.py 2.7.1` for the inbound gateway and `watchfiles 1.2.0` for file-watch — and reuse everything else (APScheduler runtime job mutation, stdlib `signal` for SIGHUP, the existing pydantic/tomllib validation path, the existing client/renderer/store). The concurrency topology is the keystone decision: **leave the sync `BackgroundScheduler` untouched and run the asyncio discord.py bot in its own dedicated thread with its own event loop**, never migrating the scheduler to `AsyncIOScheduler`. Two further architectural keystones: a `lookup_weather()` shared read-only core that both the CLI and the bot call (and that deliberately writes no sent-log/alert/heartbeat rows), and a lock-guarded `ConfigHolder` that hands out immutable config snapshots so reload is an atomic reference swap, never an in-place mutation.

The risks are well-understood and almost entirely about the seam between new and old. The headline hazards: (1) blocking the gateway event loop with sync fetch/SQLite work inside `on_message` (causes heartbeat drops → gateway churn) — mitigated with `asyncio.to_thread`/`run_in_executor`; (2) a bot crash or gateway failure killing the briefing daemon — mitigated by failure isolation and decoupling bot health from the systemd ready gate; (3) the most subtle one, hot-reload breaking the exactly-once idempotency key when a location's name/tz/send_time changes mid-day → duplicate or skipped briefing — mitigated by keying off a stable location identifier and a "don't re-fire already-sent-today" guard. The single most important refactor flagged across files: v1.0 captures `config` as a frozen APScheduler job kwarg, so `fire_slot` must be changed to read `holder.current()` *before* any reload logic lands, or unchanged jobs will render with stale config after a reload.

## Key Findings

### Recommended Stack

Only two new runtime dependencies are needed; the rest of v1.1 reuses the existing v1.0 stack verbatim (APScheduler 3.11.2 runtime job mutation, stdlib `signal`, `tomllib`, pydantic/pydantic-settings, the existing CLI layer). See [STACK.md](STACK.md) for full rationale and alternatives.

**Core technologies (new for v1.1):**
- **discord.py 2.7.1** — inbound gateway command bot — the canonical, best-documented Python gateway lib; the threading-coexistence-with-a-sync-host pattern is well-trodden. Use `client.start()` in a child thread/loop, **not** `client.run()` (which seizes the main thread + signal handlers). This does NOT contradict CLAUDE.md's "no discord.py for webhooks" — that rule was about *outbound* fire-and-forget; the outbound briefing path stays on `discord-webhook`.
- **watchfiles 1.2.0** — config file-watch hot-reload — Rust/notify-backed, ~0% idle CPU, built-in debounce that natively absorbs editor save-storms. Lighter than watchdog for "watch ~2 paths, debounce, call reload()". Polling stdlib mtime is a legitimate zero-dependency fallback if minimizing deps.
- **APScheduler 3.11.2 (reused, no new dep)** — runtime job mutation for reload via `add_job`/`remove_job`/`get_jobs`/`reschedule_job` on the running `BackgroundScheduler`. **Stay on 3.x — do NOT adopt 4.0.0aX** (alpha, not for production).

**Key secret/integration note:** the bot token is a *new* secret (`DISCORD_BOT_TOKEN`) that must live in git-ignored `.env` (same handling as the v1 webhook URL), never in `config.toml`. The `message_content` privileged intent must be toggled in BOTH code and the Discord Developer Portal (no approval needed for a small private bot); slash commands avoid that intent entirely.

### Expected Features

Scope is deliberately narrow: one read-only command + a config-only reload. See [FEATURES.md](FEATURES.md) for the full landscape and anti-feature rationale.

**Must have (table stakes):**
- On-demand lookup of a *configured* location by name, available as BOTH a CLI one-shot (no daemon required) and a Discord in-channel reply, via one shared fetch+render function
- Default location on bare `weather`; clear "unknown location — valid names: …" error (configured-only, no geocode fallback)
- Reuse the existing briefing template for the on-demand reply (no second format)
- Full-config reload: re-read → validate → atomic swap → re-register scheduler jobs
- Validate-and-keep-old-config on any failure (never crash the live daemon); atomic all-or-nothing apply
- At least the explicit reload trigger (SIGHUP / CLI / Discord) + a reload-outcome log line
- Short-TTL response cache that doubles as the quota guard (One Call 3.0 is metered/card-on-file)

**Should have (competitive):**
- File-watch auto-reload with debounce (the "no friction" path on top of the explicit trigger)
- Discord in-channel reload confirmation (success summary / rejection reason without tailing logs)
- `--check-config` dry-run validate-only subcommand (like `nginx -t`)

**Defer (v2+, already deferred in PROJECT.md):**
- Arbitrary/geocoded "weather in <any city>" (CMD-V2-02) — out of configured-only scope
- Telegram/SMS inbound surfaces; history/trend query commands over SQLite
- Hot-reloading secrets — **decline**; secret/token rotation = restart (documented boundary)
- Anti-features to actively skip: per-user cooldown tables (single user), persisting on-demand fetches into the scheduled `weather_onecall` series (pollutes the clean analysis time series), two-way config editing via chat

### Architecture Approach

One process, three independent threads under systemd: the UNCHANGED main-thread `BackgroundScheduler`, a dedicated discord.py bot thread owning its own asyncio loop, and a watchfiles watcher thread (plus the main-thread SIGHUP/SIGTERM handlers). They communicate only through a thread-safe shared core (pure functions + SQLite with a fresh connection per call). The CLI `weather <loc>` is a separate one-shot process that reuses the same shared core with zero daemon coupling. See [ARCHITECTURE.md](ARCHITECTURE.md) for the topology diagram, sketches, and the dependency-ordered build sequence.

**Major components:**
1. **`interactive/lookup.py` (NEW, the keystone)** — shared read-only fetch→render core; both the CLI one-shot and the Discord bot call it; deliberately writes no sent-log/alert/heartbeat rows.
2. **`interactive/command.py` + `discord_bot.py` (NEW)** — one `weather <loc>` parser (tested for both surfaces) + the isolated gateway `Client`; heavy asyncio import kept out of the cheap CLI path.
3. **`scheduler/reload.py` (NEW)** — `ConfigHolder` (lock-guarded atomic-swap box) + `reload_config` (re-validate → swap → diff-and-re-register jobs), separated from `daemon.py` so it's unit-testable without a full daemon.
4. **`fire_slot` refactor (MODIFY, prerequisite)** — read `holder.current()` instead of a captured `config` kwarg, so unchanged jobs render with live config after a reload.

### Critical Pitfalls

Top hazards from [PITFALLS.md](PITFALLS.md) (13 total, fully phase-mapped there). All are about the seam where the new features meet the shipped daemon.

1. **Blocking the gateway loop with sync work** (#1) — calling v1's sync fetch/SQLite directly in `on_message` drops the heartbeat → gateway churn. Avoid: bot loop on its own thread; `await asyncio.to_thread(lookup_weather, ...)` for all blocking work.
2. **A bot crash kills the briefing daemon** (#4) — the fragile long-lived gateway connection must not take down the reliable scheduler. Avoid: try/except around the whole handler; treat the bot as non-critical/self-contained; do NOT let bot health flip the systemd `gate_until_healthy` READY=1 signal. Verify by revoking the token and confirming a scheduled briefing still fires.
3. **Reload breaks the exactly-once idempotency key** (#8, HIGHEST RISK) — a name/tz/send_time change recomputes a different `(location, send_time, local_date)` key for the same morning → duplicate or skipped briefing. Avoid: key off a stable location id/slug; "don't re-fire already-sent-today" guard; explicit test of a tz/name change for an already-sent slot.
4. **Reload double-fires or drops a briefing** (#7) + **half-applied torn state** (#6) — Avoid: stable job IDs `(location, send_time)`, `replace_existing=True`, diff/reconcile only the delta (never `remove_all_jobs()`); two-phase build-then-atomic-swap so a failure mid-apply leaves the old config fully intact.
5. **Bot replies to its own / the webhook's messages** (#2) + **intent/token misconfig** (#3) — the v1 outbound briefing posts into the same channel. Avoid: `if message.author.bot: return` (covers self AND webhook), explicit command form (never substring-match), optional operator-user-ID allowlist; token in `.env`; intent enabled in both code and portal (or use slash commands).

Supporting hazards also covered: command spam burning quota (#10 → short-TTL cache), reload reading a half-written file (#5 → debounce + directory-watch), in-flight send during reload (#9 → per-job config snapshot), file-watch fd leaks/loops (#11), secrets-reload semantics (#12 → config-only, documented), systemd `RELOADING=1`/`READY=1` lifecycle (#13).

## Implications for Roadmap

The architecture research provides an explicit, dependency-ordered build sequence; the suggested phase structure follows it directly. Dependencies flow strictly upward, the highest-risk async/threading work lands last on proven foundations, and each phase is independently shippable and testable. A natural two-phase grouping also exists (Phases 1–3 = the command/CLI surface + the reload prerequisite; Phases 4–6 = reload mechanics + the gateway bot), but the finer breakdown below keeps blast radius small and pitfalls isolated.

### Phase 1: Shared lookup core + command parser
**Rationale:** Foundation with no concurrency; everything else depends on it. Refactor the read-only fetch/render path out of `send_now` into `lookup_weather()` and add the `weather <loc>` parser.
**Delivers:** `interactive/lookup.py` + `command.py`, independently unit-testable.
**Addresses:** the shared-core half of CMD-V2-01 (shared fetch+render function; configured-only resolution).
**Avoids:** the "two divergent formats / two code paths" trap by establishing one core both surfaces call; deliberately writes no liveness rows (avoids polluting the scheduled series — anti-feature).

### Phase 2: CLI `weather [location]` one-shot
**Rationale:** Lowest risk, no daemon coupling; validates `lookup_weather` end-to-end first. Ship before any threading work.
**Delivers:** standalone `weatherbot weather <loc>` subcommand (load config → lookup → print → exit).
**Addresses:** the CLI half of CMD-V2-01 (must work with no daemon running); default-location + unknown-name error UX.
**Uses:** existing CLI/argparse layer, existing client/renderer.

### Phase 3: ConfigHolder + `fire_slot` reads-from-holder refactor
**Rationale:** Prerequisite correctness fix that MUST land before reload logic — v1.0 passes `config` as a frozen job kwarg, so unchanged jobs would render stale after a reload (the single most important hot-reload refactor flagged in research).
**Delivers:** lock-guarded `ConfigHolder` (atomic-swap box) + `fire_slot` reading `holder.current()`.
**Implements:** ARCHITECTURE Pattern 2.
**Avoids:** Pitfall #9 (in-flight send reads torn config — per-job snapshot) and the stale-kwarg bug; preserves v1's per-job snapshot semantics.

### Phase 4: `reload_config` (re-validate → swap → job diff) + explicit trigger (SIGHUP / CLI)
**Rationale:** The explicit-trigger half of ENH-V2-01 — testable without a file watcher. The deterministic "apply now" path and the safest reload surface.
**Delivers:** `scheduler/reload.py` with two-phase build-then-swap + stable-job-ID diff/reconcile; SIGHUP handler (sets a flag, reload runs off-handler) + `weatherbot reload` CLI; reload-outcome log line.
**Addresses:** ENH-V2-01 core (validate → atomic swap → re-register jobs; keep-old-on-failure; reload feedback).
**Avoids:** Pitfalls #6 (all-or-nothing apply), #7 (stable IDs + diff, never `remove_all_jobs()`), #8 (exactly-once key preservation — HIGH RISK), #12 (config-only, secrets need restart), #13 (systemd reload lifecycle alignment).

### Phase 5: watchfiles file-watch auto-reload
**Rationale:** The "edit + save → applied" convenience layer; a thin wrapper that funnels into the Phase 4 reload function, so it's low-risk once the explicit trigger is trusted.
**Delivers:** watchfiles watcher thread (directory-watch + debounce) calling `reload_config`; clean teardown on SIGTERM.
**Addresses:** the file-watch differentiator of ENH-V2-01.
**Avoids:** Pitfall #5 (debounce + validate-then-swap, ignore partial files) and #11 (single long-lived observer, directory-watch to survive inode swaps, no write-back near the watched file, fd-stability soak test).

### Phase 6: Discord inbound gateway bot
**Rationale:** Highest-risk async/threading work, built LAST on proven foundations — depends on the shared lookup (Phase 1) and benefits from the holder (Phase 3) so the bot reads live config.
**Delivers:** `interactive/discord_bot.py` — gateway `Client` in its own thread/loop, `on_message` → parse → `asyncio.to_thread(lookup_weather)` → in-channel reply; short-TTL cache; optional Discord reload-confirmation.
**Addresses:** the Discord half of CMD-V2-01 (in-channel access); the reload-confirmation differentiator.
**Avoids:** Pitfalls #1 (loop hygiene via `to_thread`), #2 (`author.bot` guard + explicit command form), #3 (token in `.env`, intent in code+portal), #4 (failure isolation; bot health ≠ briefing health), #10 (cache + cooldown protect quota).

### Phase Ordering Rationale

- **Dependencies flow strictly upward** (1 → {2,3}; 3 → 4 → 5; {1,3} → 6), exactly as ARCHITECTURE's build order specifies. Nothing depends on a later phase.
- **The riskiest work lands last on a verified base** — the async gateway bot (Phase 6) sits on the already-shipped shared lookup and config holder, so threading bugs can't be confused with core-logic bugs.
- **The mandatory correctness refactor (Phase 3) precedes all reload logic** — without `fire_slot` reading the holder, hot-reload would silently render stale config.
- **Explicit-trigger reload (Phase 4) precedes file-watch (Phase 5)** — the deterministic path is the safe, fully-testable foundation; file-watch is a convenience wrapper layered on top, and PROJECT.md wants both.
- **CLI (Phase 2) ships before the bot (Phase 6)** because PROJECT.md requires the CLI to run with no daemon, and it validates the shared core with zero concurrency risk.

### Research Flags

Phases likely needing deeper research during planning (`/gsd-plan-phase --research-phase <N>`):
- **Phase 4 (reload):** the exactly-once idempotency-key interaction (Pitfall #8) is explicitly flagged HIGH RISK by the pitfalls research — it is the failure most likely to silently break a shipped guarantee. The reload policy for tz/name/send_time changes on an already-sent slot, the stable-location-id key change, and the two-phase apply/rollback warrant a deeper plan-phase pass.
- **Phase 6 (Discord bot):** the asyncio-loop-in-a-thread coexistence with `BackgroundScheduler` and the `client.start()` lifecycle/shutdown wiring are the trickiest mechanics; the pattern is well-documented (MEDIUM-confidence community consensus, corroborated) but is the highest-blast-radius integration. A focused plan-phase pass on thread lifecycle + failure isolation is worthwhile.

Phases with standard patterns (skip research-phase):
- **Phase 1, 2 (lookup core + CLI):** pure refactor/reuse of existing verified code paths; no new integration surface.
- **Phase 3 (ConfigHolder):** small, well-understood lock-guarded holder pattern.
- **Phase 5 (watchfiles):** thin wrapper over Phase 4; the watcher gotchas (debounce, directory-watch, teardown) are already enumerated in PITFALLS.md.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI JSON 2026-06-15; only 2 new deps; rest reuses the validated v1.0 stack. APScheduler runtime-mutation + intents facts from official docs. |
| Features | HIGH | Narrow single-user scope; patterns converge across Discord-bot guides + daemon-reload conventions; v1 components are known from source, not assumed. PROJECT.md is authoritative for scope/Out-of-Scope. |
| Architecture | HIGH | v1.0 architecture read directly from source (`daemon.py`, `cli.py`, `store.py`, config loaders/models); integration points and the idempotency-key/sent-log interaction confirmed against the actual code. External libs verified against docs. |
| Pitfalls | HIGH | asyncio/thread + discord.py intents + APScheduler facts verified against current official docs; idempotency/secrets/systemd specifics derived from this codebase's documented v1 patterns. Fully phase-mapped with verifications. |

**Overall confidence:** HIGH

### Gaps to Address

- **Exactly-once key under reload (Pitfall #8):** the research prescribes the fix (stable location id + already-sent-today guard) but the *exact* policy for tz/send_time changes mid-day needs a decision + dedicated test during Phase 4 planning. Highest-value gap to nail down.
- **Stable location identifier introduction:** v1's sent-log key embeds the mutable location *name*; introducing an immutable id/slug may touch the schema/key and existing rows. Validate the migration/back-compat story during Phase 4 planning (the v1.0 store is the integration target).
- **systemd reload trigger surface:** whether to expose `systemctl reload` (requires `RELOADING=1`→`READY=1` handshake) or keep reload purely file-watch + app trigger. Research recommends "reload never touches ready state" as the simplest correct choice; confirm the unit-file decision in Phase 4.
- **Discord command type (prefix vs slash):** prefix needs the `message_content` privileged intent + portal toggle; slash avoids it and can't be tripped by briefing text. Research leans slash as the cleaner default for safety (Pitfalls #2/#3); pick explicitly in Phase 6 planning.
- **Cache vs hard-cooldown for quota:** short-TTL cache is recommended (instant repeats + cheap spam); confirm TTL value and whether scheduled briefings should share the cache during Phase 6.

## Sources

### Primary (HIGH confidence)
- WeatherBot v1.0 source — `scheduler/daemon.py`, `scheduler/context.py`, `cli.py`, `channels/base.py`, `channels/factory.py`, `config/loader.py`, `config/models.py`, `weather/store.py` (the authoritative integration target)
- WeatherBot `.planning/PROJECT.md` + `CLAUDE.md` — v1.1 milestone scope/Out-of-Scope, v1 key decisions (per-job isolation, exactly-once `(location, send_time, local_date)` key + atomic claim, validate-on-load fail-loud, secrets-in-`.env`, systemd `Type=notify` `gate_until_healthy`)
- PyPI JSON (2026-06-15) — discord.py 2.7.1, watchfiles 1.2.0, watchdog 6.0.0, interactions.py 5.16.0, hikari 2.5.0, APScheduler 3.11.2 (4.0.0a6 is pre-release)
- APScheduler 3.x user guide + base scheduler API — runtime `add_job`/`remove_job`/`get_jobs`/`reschedule_job` thread-safe on a running `BackgroundScheduler`; `AsyncIOScheduler` vs thread-based
- discord.py docs — `Client.run()` vs `Client.start()` for custom loop/thread; FAQ "Heartbeat blocked"/`run_in_executor`; `Intents`/gateway lifecycle
- Discord message-content privileged intent — portal + code toggle; `author.bot` self/webhook guard (pythondiscord.com, discord-api-docs discussion)

### Secondary (MEDIUM confidence)
- discord.py-in-a-background-thread pattern — `new_event_loop`/`run_until_complete`, `run_coroutine_threadsafe`/`call_soon_threadsafe` (community consensus, corroborated across sources + verified against asyncio stdlib semantics)
- watchfiles vs watchdog 2025 recommendation — Rust/notify backend, low idle CPU, built-in debounce (watchfiles.helpmanual.io, adamj.eu)
- SIGHUP reload convention + config hot-reload patterns — validate-then-apply, atomic swap, keep-old-on-failure, debounce, watch-dir-not-file (linuxvox, oneuptime)
- systemd `Type=notify` reload protocol — `RELOADING=1`→`READY=1`, `ExecReload` (sd_notify standard docs)
- discord.py cooldown/anti-spam guidance — per-user cooldown decorators (informs the single-user anti-feature call)

### Tertiary (LOW confidence)
- None — all findings are backed by official docs, direct source reading, or corroborated multi-source community consensus.

---
*Research completed: 2026-06-15*
*Ready for roadmap: yes*
