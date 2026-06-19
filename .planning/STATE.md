---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Interactive & Live-Config
status: milestone_complete
stopped_at: Phase 11 complete — milestone v1.1 100% (all 6 phases, 22/22 plans); ready to complete milestone
last_updated: "2026-06-19T01:02:00.788Z"
last_activity: 2026-06-19
progress:
  total_phases: 6
  completed_phases: 6
  total_plans: 22
  completed_plans: 22
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-15 after v1.0 milestone)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Milestone v1.1 complete — ready to archive via /gsd-complete-milestone

## Current Position

Phase: 11 — discord-inbound-gateway-bot (COMPLETE)
Plan: 4 of 4 complete
Status: Milestone v1.1 100% complete (all 6 phases). Phase 11 UAT passed (2 pass, 1 skip); startup crash-loop blocker fixed via quick-260617-idm. Ready to complete milestone.
Last activity: 2026-06-19

Progress: [██████████] 100% (v1.1 — 22/22 plans, Phases 6–11 complete)

## v1.1 Roadmap at a Glance

| Phase | Goal (short) | Requirements |
|-------|--------------|--------------|
| 6 | Shared lookup core + `weather <loc>` parser (foundation) | — (underpins CMD-01..05, CMD-02/06/07) |
| 7 | CLI `weather [location]` one-shot (no daemon) | CMD-01, CMD-03, CMD-04, CMD-05 |
| 8 | ConfigHolder + `fire_slot` holder refactor (prerequisite) | — (unblocks CFG-01/05) |
| 9 | Reload engine + explicit trigger + `--check-config` | CFG-01, CFG-02, CFG-04, CFG-05, CFG-06, CFG-08 |
| 10 | watchfiles auto-reload (debounce) | CFG-03 |
| 11 | Discord inbound gateway bot + reload confirm | CMD-02, CMD-06, CMD-07, CMD-08, CFG-07 |

**Research flags:** Phase 9 (exactly-once idempotency key under reload — Pitfall #8, HIGH RISK) and Phase 11 (asyncio-thread coexistence + bot lifecycle — Pitfalls #1/#4) are deeper-research candidates — consider `/gsd-plan-phase --research-phase {9|11}`.

## Performance Metrics

**Velocity (v1.0 — shipped):**

- Total plans completed: 40 (across Phases 1–5)
- v1.0 timeline: 11 days (2026-06-04 → 2026-06-15), ~7.9k LOC, 186 tests green

**v1.1:** no plans executed yet.

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Recent decisions affecting current work:

- [Roadmap v1.1]: Phase numbering CONTINUES from v1.0 — v1.1 is Phases 6–11 (no reset).
- [Roadmap v1.1]: Dependency-ordered build sequence preserved — shared core (6) before its consumers (7, 11); ConfigHolder/`fire_slot` refactor (8) BEFORE reload logic (9); explicit-trigger reload (9) BEFORE file-watch (10); the async Discord bot (11) LAST on proven foundations.
- [Roadmap v1.1]: Only two NEW runtime deps planned — `discord.py 2.7.x` (Phase 11) + `watchfiles 1.2.x` (Phase 10); everything else reuses the v1.0 stack. `BackgroundScheduler` stays sync (no AsyncIOScheduler migration).
- [Roadmap v1.1]: Highest risk = CFG-05 / Pitfall #8 — hot-reload must not break the exactly-once `(location, send_time, local_date)` key on a name/tz/send_time change; Phase 9 carries an explicit exactly-once-across-reload success criterion.
- [Phase ?]: [Phase 6-01]: Command parser is parse-don't-validate (D-01) — config-free, I/O-free; classifies into NOT_A_COMMAND/DEFAULT/LOCATED and extracts raw-case location, validating nothing against config.
- [Phase ?]: [Phase 6-01]: Word-boundary guard on the 'weather' keyword (whitespace required after keyword) prevents briefing-feedback loops (weatherman/weather: -> NOT_A_COMMAND, T-06-02).
- [Phase ?]: [Phase 6-02]: lookup_weather is the read-only fetch->render core (D-06: no db path, no store import) returning a LookupResult value object (D-05); P7 CLI prints .text and P11 Discord builds an embed from .forecast without re-fetching.
- [Phase ?]: [Phase 6-02]: UnknownLocationError subclasses ValueError, carries .requested + .valid_names (D-07), raised from the upgraded resolve_location; every existing except-ValueError caller stays green (Pitfall 5).
- [Phase ?]: 06-03: send_now delegates read-only HEAD to lookup_weather (D-08); deliver+persist TAIL byte-identical, scheduled timing via extra_placeholders
- [Phase ?]: [Phase 7-01]: Used hatchling (PyPA-canonical) build backend + single [project.scripts] entry weatherbot=weatherbot.cli:main; uv sync materializes .venv/bin/weatherbot. No new runtime deps.
- [Phase 07]: [Phase 7-03] Fixed a real D-09 bug: structlog default ignored the stdlib level and rendered to STDOUT, defeating quiet mode AND polluting the weather command's pipeable STDOUT; configured structlog to honor the effective level and render to STDERR via a live-stderr proxy.
- [Phase 08]: [Phase 8-01] Wave-0 RED scaffold deferred the `ConfigHolder` import into a per-test `_holder()` helper (not top-of-module) so all six VALIDATION node IDs COLLECT while each still fails RED on a real `ModuleNotFoundError` — a top-level import would error at collection and hide the node IDs.
- [Phase 08]: [Phase 8-01] frozen-mutation guard asserts `pydantic.ValidationError` (type `frozen_instance`), never `dataclasses.FrozenInstanceError` (Pitfall 2 — pydantic BaseModels); config B built via `model_copy(update=...)`, no Config hashing (Pitfall 1).
- [Phase 08]: [Phase 8-02] frozen=True added to all 5 config models' ConfigDict(extra="forbid") (D-02) — config snapshots are immutable-by-type; field rebind raises pydantic.ValidationError(frozen_instance), the precondition for ConfigHolder lock-free shared reads. No config hashing introduced (Pitfall 1: list-bearing models stay unhashable).
- [Phase ?]: [Phase 8-03] ConfigHolder: lock-free current() (atomic LOAD_ATTR under GIL) + threading.Lock-guarded replace() that does NOT validate (deferred to Phase 9/CFG-04); canonical name replace (D-04); owns Config only, no Settings/secrets (Pitfall #12).
- [Phase ?]: [08-04] fire_slot reads the config snapshot ONCE per fire (override-wins: config= beats holder.current(), both-None raises ValueError) and threads that same object through the reliability budget read AND send_now(config=snapshot) — a mid-fire replace() cannot tear a delivery (Pitfall #9).
- [Phase ?]: [08-04] add_job now carries {holder: holder} not {config: config}, so an UNCHANGED fire_slot job re-reads holder.current() every fire; replace() changes what it renders (the phase core proof). Stable job id and _heartbeat_tick byte-identical; catchup.py unchanged (pure-input, A3).
- [Phase 09]: Wave-0 RED scaffold defers the not-yet-built reload entrypoint into per-test lazy imports so all 12 node IDs COLLECT while RED (Phase 8 Wave-0 lesson).
- [Phase 09]: SC#4 guard protects NAME/TZ edits ONLY (keeps send_time); a send_time change is a NEW slot pinned by a separate test (amended D-02). No blanket per-location once-today guard.
- [Phase 09]: Location.id defaults to the RAW name (zero-migration key); seed_sent_row uses the shipped claim_slot so exactly-once tests hit the real key (T-09-01).
- [Phase ?]: [09-02] Location.id defaults to the RAW name verbatim (Option A); casefold used ONLY for the uniqueness collision check — exactly-once key stays byte-identical (zero migration).
- [Phase ?]: [09-02] validate_config_and_templates is the ONE shared offline validator (load_config + unique name/id + regex validate_template); zero network, no Jinja2, no run_self_check (Pitfall 8) — check-config is a strict subset of check.
- [Phase ?]: [09-03] do_reload reads the PID, passes the /proc cmdline guard (is_weatherbot_pid), then os.kill SIGHUP — returns 1 without ever signaling on no-PID/stale/recycled (T-09-06); guard exposes an injectable cmdline_reader seam for offline tests.
- [Phase ?]: [09-03] check-config dispatch is the OFFLINE strict subset of check: calls the shared validate_config_and_templates, loads NO Settings, never invokes do_check/run_self_check (Pitfall 8 — zero network).
- [Phase ?]: [09-03] write_pid_atomic uses temp + os.replace (POSIX-atomic) and RE-RAISES on failure (unlike sdnotify's swallow) since it runs in run_daemon startup where a PID-write failure must be visible; pidfile.py is stdlib-only and cycle-free.
- [Phase ?]: [09-04] Exactly-once sent-log/alert key moved location.name->location.id at all FIVE callsites in lockstep (daemon claim/release/record_alert/resolve + catchup was_sent); id defaults to raw name (byte-identical rows, zero migration), weather/store.py untouched.
- [Phase ?]: [09-04] KEY vs DISPLAY split: only the store key arg moved to location.id; _log display fields and the APScheduler job id (name|time|days) stay on location.name.
- [Phase ?]: [Phase 10-01] Wave-0 RED scaffold tests/test_filewatch.py defers the not-yet-built observer symbols (_run_watch_observer/_derive_watch_dirs/_make_watch_filter) and Config.reload.watch into per-test wrappers so all 8 node IDs COLLECT while each fails RED; SC#3 fd soak uses /proc/<pid>/fd with FD_SLACK (no psutil), SC#4 uses the real _do_reload keep-old path.
- [Phase ?]: [Phase 10-02] watchfiles>=1.2.0 added as runtime dep (uv add, not pip/dev), alphabetical after tenacity; uv.lock pins 1.2.0 (D-01).
- [Phase ?]: [Phase 10-02] ReloadConfig frozen+extra=forbid, watch: bool = True (ON by default, D-03); Config.reload via default_factory mirrors Reliability — [reload]-less configs load unchanged, unknown key fails loud (T-10-03).
- [Phase ?]: [Phase 10-03] File-watch observer is FLAG-SET ONLY (request_reload -> reload_requested.set()); _do_reload always runs on the main poll-loop thread (D-02). watch() step=400/debounce=1600/rust_timeout=500/yield_on_timeout=True for sub-second SIGTERM teardown (Pitfall #2). CFG-03 closed.
- [Phase ?]: [Phase 10-03] D-04 re-derive mutates ONLY watch_dirs_ref[0]; the single watch() generator re-enters with new dirs on the next rust_timeout tick (A4 — no second observer; old inotify fds released on exhaustion). Basename allow-list filter excludes .env (Pitfall #12).
- [Phase ?]: [Phase 11-01] Wave-0 RED scaffold: fake_discord_message is a pure MagicMock stand-in (no discord import, AsyncMock channel.send, async-cm typing) so the 10 bot/cache node IDs stay collectable before discord.py is installed; deferred per-test import fails RED on the unbuilt weatherbot.interactive.bot/.cache (Phase 8/9/10 lesson).
- [Phase ?]: [Phase 11-01] build_on_message(holder, operator_id, cache) is the handler-factory seam tests drive directly; off-loop dispatch pinned by spying the bound loop.run_in_executor (Pitfall 1); ForecastCache keys on resolve_location(config,name).id (home/Home/bare-default collapse to one TTL entry).
- [Phase ?]: [Phase 11-01] CFG-07 posts go through the agnostic channel.send seam (plain text, distinct from briefing embed, D-13); send-failure isolation pinned both branches — success swap survives a raising post, rejection surfaces the ORIGINAL validation error (not the send RuntimeError).
- [Phase ?]: 11-02: operator_id is a single int (one-operator v1 bot, A3); Config.bot is a plain optional None default so a [bot]-less config means no bot
- [Phase ?]: 11-02: discord_bot_token is a REQUIRED Settings secret (D-14), fails loud at startup; documented in .env.example + deploy/README.md, never config.toml
- [Phase 11]: [11-03] ForecastCache holds TTLCache behind a Lock but runs lookup_weather UNLOCKED so location misses never serialize; injectable timer= for deterministic TTL tests
- [Phase 11]: [11-03] build_on_message is the gateway-free handler-factory; guard ladder author.bot->operator_id->!->parse is the feedback-loop+quota backstop; off-loop fetch via run_in_executor; BotThread isolates bot failures from the scheduler (no client.run)
- [Phase ?]: CFG-07 reload posts reuse emit_online best-effort idiom; inbound bot started after emit_online so bot health never gates READY (11-04)

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- [Phase 9]: Exact policy for tz/send_time changes mid-day on an already-sent slot, plus the stable-location-id key change vs the v1 sent-log schema, needs a decision + dedicated test during Phase 9 planning (Pitfall #8, HIGH RISK).
- [Phase 11]: Prefix vs slash command-type (message_content privileged intent) and the `client.start()`-in-a-thread lifecycle/shutdown wiring to pick during Phase 11 planning (Pitfalls #1/#3/#4).

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260615-fac | Resolve milestone-audit tech debt: drop dead `record_sent` + migrate idempotency test to `claim_slot`; backfill `requirements-completed` frontmatter on 11 plan SUMMARYs | 2026-06-15 | 7842e9e | [260615-fac-resolve-two-milestone-audit-tech-debt-it](./quick/260615-fac-resolve-two-milestone-audit-tech-debt-it/) |
| 260617-fua | Wire `ForecastCache.invalidate()` into the daemon reload path (closes Phase 11 code-review CR-01; reverses the Q2/D-12 cache-invalidation deferral) + daemon-level integration test | 2026-06-17 | 7ba1ff4 | [260617-fua-wire-forecastcache-invalidate-into-the-d](./quick/260617-fua-wire-forecastcache-invalidate-into-the-d/) |
| 260617-idm | Fix daemon startup crash-loop (Phase 11 UAT blocker): non-root service couldn't write PID file to root-owned `/run` — repoint `PID_FILE` to `/run/weatherbot/weatherbot.pid` + add `RuntimeDirectory=weatherbot` to the unit (requires manual root re-install of installed unit) | 2026-06-17 | 5dcec80 | [260617-idm-fix-daemon-startup-crash-loop-pid-file-w](./quick/260617-idm-fix-daemon-startup-crash-loop-pid-file-w/) |
| Phase 06 P01 | 3min | 2 tasks | 2 files |
| Phase 06 P02 | 12m | 3 tasks | 3 files |
| Phase 06 P03 | 2min | 3 tasks | 3 files |
| Phase 07 P01 | 4min | 1 tasks | 2 files |
| Phase 07 P02 | 2 min | 2 tasks | 1 files |
| Phase 07 P03 | ~10 min | 3 tasks | 6 files |
| Phase 08 P01 | ~12 min | 2 tasks | 2 files |
| Phase 08 P02 | ~8min | 1 tasks | 1 files |
| Phase 08 P03 | ~6 min | 1 tasks | 1 files |
| Phase 08 P04 | ~9 min | 2 tasks | 3 files |
| Phase 09 P01 | ~10min | 2 tasks | 4 files |
| Phase 09 P02 | ~6min | 2 tasks | 2 files |
| Phase 09 P03 | ~5min | 2 tasks | 3 files |
| Phase 09 P04 | ~6min | 2 tasks | 2 files |
| Phase 09 P05 | ~14 min | 2 tasks | 4 files |
| Phase 10 P01 | ~9 min | 1 tasks | 1 files |
| Phase 10 P02 | ~1 min | 2 tasks | 3 files |
| Phase 10 P03 | ~10min | 2 tasks | 2 files |
| Phase 11 P01 | 8min | 2 tasks | 4 files |
| Phase 11 P02 | 15min | 2 tasks | 8 files |
| Phase 11 P03 | 4min | 2 tasks | 3 files |
| Phase 11 P04 | 3min | 2 tasks | 2 files |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Host UAT | OPS-01 SC#1 live `sudo reboot` power-cycle on host `yahir-mint`. | ✅ CONFIRMED 2026-06-15 | 05-02 (2026-06-11) |
| Data semantics | DATA-03 delivered-only persistence — confirm when v2 analysis (ANLY-V2-01) reads the store. | Open (v2) | v1.0 close |

## Session Continuity

Last session: 2026-06-19
Stopped at: Phase 11 complete, milestone v1.1 100% — ready to complete milestone
Resume file: None

## Operator Next Steps

- Complete milestone v1.1 with `/gsd-complete-milestone v1.1` (archives ROADMAP, preps next milestone).
- Phase 11 UAT passed (2 pass, 1 skip); the live daemon now runs current code (PID-file/RuntimeDirectory fix applied via quick-260617-idm, installed unit re-deployed).
- Backlog idea from UAT: add weather icons/emoji to the Discord embed replies (cosmetic enhancement).
