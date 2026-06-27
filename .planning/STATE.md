---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Discord Control Panel
current_phase: 20
current_phase_name: isolation-hardening-polish
status: executing
stopped_at: Phase 20 UI-SPEC approved
last_updated: "2026-06-27T00:37:22.267Z"
last_activity: 2026-06-27
last_activity_desc: Phase 20 execution started
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 11
  completed_plans: 9
  percent: 80
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-23 after starting v1.3)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Phase 20 — isolation-hardening-polish

## Current Position

Phase: 20 (isolation-hardening-polish) — EXECUTING
Plan: 2 of 3
Status: Ready to execute
Last activity: 2026-06-27 — Phase 20 execution started

## v1.3 Roadmap at a Glance

| Phase | Goal (short) | Requirements |
|-------|--------------|--------------|
| 16 | Extract the `on_message` arg-adaptation ladder into one shared `dispatch_spec` so the panel can never drift from the real command set (refactor-first, behavior-preserving) | PANEL-10 |
| 17 | Minimal persistent panel core: location dropdown + read-only command buttons + argless handling + defer-then-edit fast ack + in-place render + operator guard | PANEL-02, 03, 04, 05, 06, 08 |
| 18 | Persistence + summon/lifecycle: persistent views survive restart, idempotent `!panel` summon + pin, exactly one panel, default-on-restart | PANEL-01, PANEL-09 |
| 19 | Forecast two-tier sub-options: Forecast button → Weekday/Weekend × Detailed/Compact, routed through `dispatch_spec` | PANEL-07 |
| 20 | Isolation hardening + polish: re-prove briefing isolation for the interaction path + selected-location indicator + emoji labels + "updated" stamp | PANEL-11, PANEL-12, PANEL-13 |

**Dependency notes:** Refactor-first → core-before-durability-before-layout → isolation-reproof-last. Phase 16's shared dispatcher is a hard prerequisite for every panel callback (no copied dispatch ladder allowed). Phase 17 carries the load-bearing interaction correctness (3s ack, in-place edit, operator guard, per-callback isolation envelope). Phase 18 is the v1.3 headline (restart durability) and needs a live `systemctl restart` UAT on host `yahir-mint`. Phase 19 is the one layout-pressure flow, isolated after the simple grid is proven. Phase 20 re-proves the whole-panel isolation guarantee against a live scheduler (mirroring the Phase-15 raising-tick proof).

**Research flag:** Phase 18 has the milestone's one genuinely open design decision (persist pinned `message_id` / selected-location durably vs. recreate-on-restart) plus a MEDIUM-confidence exact pin/embed permission set — strongly consider `/gsd-plan-phase --research-phase 18`. Phases 16/17/19/20 have HIGH-confidence, well-documented patterns (skip research-phase).

**Reuse anchors (brownfield — no new deps, no new intent):** the whole milestone is code inside the existing discord.py `BotThread` (failure-isolated, started after systemd READY, torn down in `finally`). Reuse: `registry.COMMANDS` / `BY_NAME` (single source of truth for the button grid), `ForecastCache` (off-loop TTL fetch), `interactive/lookup.py` read-only core, `render_embed` / `CommandReply`, lock-guarded `ConfigHolder` (`holder.current()`), the operator-id guard ladder, `command.py` flag helpers (`parse_forecast_flags` / `forecast_cache_suffix`), read-only `DaemonState`. The four deps a `PanelView` needs (operator_id, holder, cache, daemon_state) already flow into `build_client` — no new `BotThread`/`daemon.py` constructor args. The APScheduler briefing spine stays UNTOUCHED; the panel only ever drives read-only paths.

## Performance Metrics

**Velocity (v1.0 — shipped):**

- Total plans completed: 44 (across Phases 1–5)
- v1.0 timeline: 11 days (2026-06-04 → 2026-06-15), ~7.9k LOC, 186 tests green

**Velocity (v1.1 — shipped):**

- Total plans completed: 22 (across Phases 6–11), 29 tasks
- v1.1 timeline: ~4 days (2026-06-15 → 2026-06-18), ~13.5k LOC, 291 tests green

**Velocity (v1.2 — shipped):**

- Total plans completed: 15 (across Phases 12–15), 34 tasks
- v1.2 timeline: 2026-06-19 → 2026-06-20, 575 tests green

**Velocity (v1.3 — not started):**

*Updated after each plan completion*

## Accumulated Context

### Decisions

All v1.0/v1.1/v1.2 phase-level decisions are archived in PROJECT.md Key Decisions and the milestone ROADMAPs. STATE.md keeps only decisions affecting *upcoming* (v1.3) work:

- **Refactor-first (Phase 16):** extract `dispatch_spec` from `on_message` BEFORE any panel code exists — drift-prevention (PANEL-10) must be structurally enforced before a panel callback could copy a dispatch ladder. The single most important reuse move in the milestone.
- **Pure UI layer, zero new deps / intents (whole milestone):** every "feature" is an interaction behavior whose answer comes from an already-shipped v1.2 registry command + existing `ForecastCache` + `render_embed`. The panel is a third caller of the same dispatch core. Do NOT add a package, bump/unpin discord.py, switch to `commands.Bot`, migrate to slash/app commands, or add a gateway intent "for buttons."
- **Persistent views the documented way (Phase 18):** `super().__init__(timeout=None)` + static centralized `custom_id` constants + `add_view` in `setup_hook` (NOT `on_ready` — it re-fires on reconnect → duplicate registrations). Persistent views listen by `custom_id`, so the panel `message_id` is NOT strictly required to re-bind buttons — but the idempotent-summon / find-or-recreate path may still want it (the open Phase-18 decision).
- **Operator guard moves to the interaction layer (Phase 17):** the `on_message` guard ladder does NOT fire for component clicks. Implement the guard in `View.interaction_check` (`return user.id == operator_id`); on False send a SILENT ephemeral reject that never echoes user/command. Keep an `interaction.user.bot` short-circuit.
- **Defer-then-edit ack discipline (Phase 17):** a cold-cache OpenWeather fetch can exceed Discord's 3s ack window. Rule: cheap/instant change → `response.edit_message`; anything that fetches → `response.defer()` then `edit_original_response`. NEVER `defer()` + `response.edit_message()` (double-ack `InteractionResponded`). All blocking work stays off the bot loop via `run_in_executor`.
- **Interaction isolation envelope is NEW (Phase 17 build, Phase 20 proof):** button/select callbacks bypass the v1.1 `on_message` try/except. Wrap every callback body in the same non-propagating `try/except Exception` (log + best-effort ephemeral, never re-raise) + a `View.on_error` backstop. The panel must touch ONLY read-only registry + `ForecastCache` + read-only `DaemonState` / `holder.current()` — never the scheduler, sent-log, or `holder.replace`.
- **Selected-location state = in-memory + default-on-restart (Phase 18):** hold the selection on the `PanelView` instance (single-operator, one panel); after restart default to home/first. Do NOT pack mutable state into `custom_id` (100-char cap, fights static persistent-view registration, breaks on rename). Persisting selection across restart via a new datastore is Out of Scope.
- [Phase ?]: 16-01: single arg-adaptation ladder now lives once in dispatch_reply; bot + CLI both route through the shared dispatcher (PANEL-10)
- [Phase 17]: weather handler uses forecast.location (str) not result.location.name to stay byte-identical to build_inbound_embed (17-02, D-08)
- [Phase 17]: CLI registry-loop _HANDWRITTEN skip-guard preserves hand-written subparsers and prevents an argparse conflicting-subparser crash (17-02, D-08)
- [Phase ?]: [Phase 17]: 17-03 panel holds selection in-memory (_selected_location, default locations[0]); never re-reads Select.values in a button callback (Pitfall 3), never encodes selection in custom_id
- [Phase ?]: [Phase 17]: 17-03 single-ack defer-then-edit (one response.edit_message cue then edit_original_response result, never a second response.*); per-callback try/except + View.on_error backstop isolates component callbacks
- [Phase ?]: [Phase 18]: 18-01 PanelView registered via add_view in setup_hook (NOT on_ready); deferred PanelView import breaks the panel.py->bot.py render_embed cycle (PANEL-09, D-13)
- [Phase ?]: [Phase 18]: 18-01 panel_channel_id required int on BotConfig (read once at startup); _is_owned_panel matches author==bot AND a wb: child custom_id for Plan 02 scan (D-04/D-05)
- [Phase ?]: [Phase 18]: 18-02 !panel lifecycle WRITE in operator-gated on_message (D-07, NOT dispatch_spec); reads holder.current().bot.panel_channel_id, bot identity from channel.guild.me (gateway-free)
- [Phase ?]: [Phase 18]: 18-02 preflight pin_messages NOT manage_messages (Discord split, D-10); eager permissions_for refuse-before-write (no orphan, SC#4) + per-write discord.Forbidden TOCTOU backstop (D-09); scan via async-for channel.pins(), reuse-in-place + DELETE strays for exactly-one (D-05/D-06)
- [Phase 19]: 19-02 panel Forecast two-tier (toggle row 2 + 2x2 sub-grid rows 3-4) routes ForecastFlags built directly through dispatch_spec(spec, None, flags=) — third caller of the shared seam, no parallel logic (PANEL-07, D-01)
- [Phase 19]: 19-02 reveal/collapse is a cosmetic _render_view(expanded,disabled) edit_message swap; the registered persistent view keeps all 13 children so post-restart taps route (D-05); every non-toggle action collapses + resets _expanded (D-04)
- [Phase 19]: 19-02 _assert_layout completed+load-bearing (≤5 rows/≤5 per row/≤25 children/id≤100/label≤80) via split _assert_layout_children; _disabled_copy delegates to the single _render_view clone path (D-08/D-09)
- [Phase ?]: [Phase 20]: 20-01 hanging-callback isolation proven against a LIVE BackgroundScheduler — panel.dispatch_spec monkeypatched to await asyncio.Event().wait() (D-08a, not a CPU spin), callback driven on a daemon thread; sentinel briefing still fires + scheduler stays running (PANEL-11, D-08 test-only)
- [Phase ?]: [Phase 20]: 20-01 D-08b executor audit is a structural source assertion — run_in_executor(None,…) lives ONLY in interactive/dispatch.py and weatherbot/scheduler/ has zero; no bounded executor introduced (Option C out of scope)

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

- **[Phase 18] Live persistent-view restart UAT on host yahir-mint:** deploy the new `panel.py` + `setup_hook` `add_view`, `sudo systemctl restart weatherbot`, then tap every button + the dropdown on the already-pinned panel to confirm they still route (no "This interaction failed"); select a location → restart → tap → confirm correct location (or documented default); resummon `!panel` → confirm exactly one panel remains. (New module + `setup_hook` only load on next process start — config hot-reload does not load new code.)

### Blockers/Concerns

[Issues that affect future work]

- **Carry-forward `[bot]` read-once-at-startup tech debt:** `[bot] operator_id` is read once at startup (restart boundary, within CFG-01 scope). Confirm the panel's channel/operator binding sits on the right side of that boundary during Phase 17/18 planning (changing them needs a restart — acceptable, document it).

Carry-forward tech debt from v1.1 is tracked in milestones/v1.1-MILESTONE-AUDIT.md (non-blocking): Phase 9 advisory hardening; `[bot] operator_id` / `[reload] watch` restart-deferred.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260615-fac | Resolve milestone-audit tech debt: drop dead `record_sent` + migrate idempotency test to `claim_slot`; backfill `requirements-completed` frontmatter on 11 plan SUMMARYs | 2026-06-15 | 7842e9e | [260615-fac-resolve-two-milestone-audit-tech-debt-it](./quick/260615-fac-resolve-two-milestone-audit-tech-debt-it/) |
| 260617-fua | Wire `ForecastCache.invalidate()` into the daemon reload path (closes Phase 11 code-review CR-01) + daemon-level integration test | 2026-06-17 | 7ba1ff4 | [260617-fua-wire-forecastcache-invalidate-into-the-d](./quick/260617-fua-wire-forecastcache-invalidate-into-the-d/) |
| 260617-idm | Fix daemon startup crash-loop (Phase 11 UAT blocker): repoint `PID_FILE` to `/run/weatherbot/weatherbot.pid` + add `RuntimeDirectory=weatherbot` to the unit | 2026-06-17 | 5dcec80 | [260617-idm-fix-daemon-startup-crash-loop-pid-file-w](./quick/260617-idm-fix-daemon-startup-crash-loop-pid-file-w/) |
| Phase 16 P01 | ~4m | 3 tasks | 4 files |
| Phase 17 P01 | 9m | 2 tasks | 2 files |
| Phase 17 P02 | 18min | 2 tasks | 5 files |
| Phase 17 P03 | 18min | 3 tasks | 1 files |
| Phase 18 P01 | 9min | 3 tasks | 10 files |
| Phase 18 P02 | 6min | 2 tasks | 2 files |
| Phase 19 P01 | ~1 min | 2 tasks | 2 files |
| Phase 19 P02 | ~5 min | 3 tasks | 2 files |
| Phase 20 P01 | 7min | 2 tasks | 2 files |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Host UAT | OPS-01 SC#1 live `sudo reboot` power-cycle on host `yahir-mint`. | ✅ CONFIRMED 2026-06-15 | 05-02 (2026-06-11) |
| Data semantics | DATA-03 delivered-only persistence — confirm when v2 analysis (ANLY-V2-01) reads the store. | Open (v2) | v1.0 close |
| Host UAT | Phase 12 live command surface (12-UAT.md). | ✅ CONFIRMED 2026-06-23 (3/3 UAT passed) | v1.2 close (2026-06-19) |
| Host UAT | Phase 13 live multi-day forecasts (13-UAT.md): weekday/weekend on Discord + CLI, scheduled slot fires, template reload. `/gsd-verify-work 13`. | Open — deploy+restart | v1.2 close (2026-06-19) |
| Host UAT | Phase 14 live UV (14-UAT.md): `uv <loc>` on Discord + CLI, UV line in a live briefing, `[uv]` hot-reload. `/gsd-verify-work 14`. | Open — deploy+restart | v1.2 close (2026-06-19) |
| Host UAT | Phase 15 live proactive UV monitor (15-UAT.md): pre-warn/crossing/all-clear over a real daylight crossing, no re-spam after mid-day restart, briefing unaffected. `/gsd-verify-work 15`. | Open — deploy+restart | v1.2 close (2026-06-19) |

**The three open v1.2 host UATs (13/14/15) require one deploy + `sudo systemctl restart weatherbot` (new Python modules don't hot-reload). Acknowledged as non-blocking tech debt at v1.2 close.**

## Session Continuity

Last session: 2026-06-27T00:37:00.421Z
Stopped at: Phase 20 UI-SPEC approved
Resume file: .planning/phases/20-isolation-hardening-polish/20-UI-SPEC.md

## Operator Next Steps

- Plan the first v1.3 phase with `/gsd-plan-phase 16` (pure local refactor — skip research-phase).
- When you reach Phase 18, strongly consider `/gsd-plan-phase --research-phase 18` (the one open design decision: persist `message_id`/selected-location vs. recreate-on-restart + exact pin/embed perms).
