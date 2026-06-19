---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Forecasts, Commands & UV
status: executing
stopped_at: 15-02 complete (UV monitor tick + decision branches) — ready for Phase 15 Plan 03
last_updated: "2026-06-19T19:35:00.000Z"
last_activity: 2026-06-19 -- Phase 15 Plan 02 executed
progress:
  total_phases: 4
  completed_phases: 3
  total_plans: 15
  completed_plans: 14
  percent: 87
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-19 after v1.1 milestone)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Phase 15 — proactive-uv-sunscreen-monitor

## Current Position

Phase: 15 (proactive-uv-sunscreen-monitor) — EXECUTING
Plan: 3 of 3 (15-01, 15-02 complete)
Status: Executing Phase 15
Last activity: 2026-06-19 -- Phase 15 Plan 02 executed (UV monitor tick + 3 decision branches)

## v1.2 Roadmap at a Glance

| Phase | Goal (short) | Requirements |
|-------|--------------|--------------|
| 12 | Command registry + read-only command surface (`help`/`alerts`/`locations`/`status`/`sun`/`wind`/`next-cloudy`) on CLI + Discord behind the guard ladder | CMD-09..16 |
| 13 | Multi-day forecast templates (weekday + weekend, detailed/compact, additive day flags) on demand + per-location scheduled, reusing One Call `daily` | FCAST-01..07 |
| 14 | UV index — `uv <loc>` command + current/max UV + threshold-crossing time in daily briefing; configurable threshold + lead | UV-01, UV-02, UV-03 |
| 15 | Proactive UV sunscreen monitor — daylight-only intraday poll loop, pre-warn + crossing alerts once/day/location, failure-isolated | UV-04, UV-05, UV-06 |

**Dependency notes:** Phase 12's command registry underpins the on-demand forecast (Phase 13) and `uv` (Phase 14) commands. Phase 15 (UV monitor) builds on Phase 14's UV render/threshold/lead config and reuses the v1.1 failure-isolated background-thread pattern (BotThread discipline). Phase 15 is the highest-risk phase (new intraday loop, daylight-only gating, once/day/location dedup, isolation) — consider `/gsd-plan-phase --research-phase 15`.

**Reuse anchors (brownfield):** shared read-only `interactive/lookup.py` core, argparse CLI subcommands, `interactive/bot.py` BotThread + operator guard ladder + ForecastCache, APScheduler briefing spine + per-location schedule slots, lock-guarded ConfigHolder + `_do_reload` hot-reload, editable fail-loud templates, `alerts` table + Discord outcome posting. New work reuses the already-fetched One Call 3.0 `daily[]`/`hourly[]`/`current` (incl. `uvi`, `clouds`, `sunrise`/`sunset`) — no new endpoints.

## Performance Metrics

**Velocity (v1.0 — shipped):**

- Total plans completed: 33 (across Phases 1–5)
- v1.0 timeline: 11 days (2026-06-04 → 2026-06-15), ~7.9k LOC, 186 tests green

**Velocity (v1.1 — shipped):**

- Total plans completed: 22 (across Phases 6–11), 29 tasks
- v1.1 timeline: ~4 days (2026-06-15 → 2026-06-18), ~13.5k LOC, 291 tests green

**Velocity (v1.2 — in progress):**

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 13 | 04 | ~35 min | 2 | 13 |

*Updated after each plan completion*
| Phase 13 P05 | ~18 min | 2 tasks | 5 files |
| Phase 14 P01 | ~9 min | 2 tasks | 7 files |
| Phase 14 P02 | ~12 min | 1 task | 2 files |
| Phase 14 P03 | ~18 min | 2 tasks | 8 files |
| Phase 14 P04 | ~22 min | 2 tasks | 8 files |
| Phase 15 P01 | ~30 min | 3 tasks | 7 files |
| Phase 15 P02 | ~40 min | 3 tasks | 2 files, 559 green |

## Accumulated Context

### Decisions

All v1.0/v1.1 phase-level decisions are archived in PROJECT.md Key Decisions and the milestone ROADMAPs. STATE.md keeps only decisions affecting *upcoming* work:

- **Command registry first (Phase 12):** `help` (CMD-09) must auto-generate from a registry, and all new commands route through one guard ladder (CMD-16) — so a shared command-registry foundation lands before the per-command views and before the on-demand forecast/`uv` commands depend on it.
- **UV render/config before the monitor:** UV threshold + lead config and UV field rendering (Phase 14) are a prerequisite for the Phase 15 monitor's threshold-crossing detection and pre-warn lead.
- **Monitor reuses the v1.1 isolation pattern:** the new intraday UV loop must be failure-isolated like BotThread (UV-06) — never gate/delay/stop a briefing.
- [Phase ?]: Read-only command handlers (Plan 12-02) return a frozen surface-agnostic CommandReply (title/lines/text) — the D-04 seam Plan 03 renders to Discord embed vs CLI plain text
- [Phase ?]: DaemonState takes the live ConfigHolder (read via current()) not a frozen snapshot, so status always reports the reloaded config; monitor_alive=None is the clean Phase-15 UV-monitor slot
- [Phase 12]: Registry handlers wired via a single _wire_handlers(replace(...)) pass with LAZY handler imports (not per-spec handler= literals) so registry.py stays importable by command.py with no import cycle
- [Phase 12]: render_embed (Discord) + render_text (CLI) render the SAME frozen CommandReply (D-04 same-content seam); both surfaces' dispatch derive from registry.COMMANDS (CMD-09 anti-drift, now load-bearing on the CLI too)
- [Phase 12]: CLI status scope is intentionally narrower than live-daemon !status (one-shot has no live scheduler/bot — only the heartbeat read is live)
- [Phase ?]: [Phase 13]: ForecastDay.from_daily takes label as a parameter (caller computes Today/Tomorrow in Plan 04/05); feels-like hi/lo derived from max/min of dayparts (no feels_like.max)
- [Phase ?]: [Phase 13]: multiday.select_days is a pure dep-free module reusing days._DAYS; resolves desired dates to daily[] index by matching local date (never positional), out-of-horizon -> notices not IndexError
- [Phase ?]: Scheduled forecasts (13-05): one _forecast_job_id with |fc| namespace feeds both register+desired loops (no drift/collision); fire_forecast_slot reuses the on-demand render path inside fire_slot's isolation envelope MINUS all store writes (read-only, FCAST-05)
- [Phase 14]: UvConfig is a frozen [uv] table (threshold 6.0 + pre_warn_lead_minutes 30) wired via Config.uv = Field(default_factory=UvConfig) — absent table = defaults (zero migration), hot-reloaded by the whole-Config re-read; threshold default 6.0 preserves the hardcoded sunscreen-hint behavior verbatim (A5)
- [Phase 14]: pre_warn_lead_minutes is STORED+VALIDATED in Phase 14 but has NO behavior yet — Phase 15's monitor gives it meaning (Open Q1/A4)
- [Phase 14]: Three deterministic hourly[].uvi fixtures (uvcross/uvbelow/highuv) anchored to 2024-06-14 NY (sunrise 04:40 / sunset 19:40) so Plan 14-02 can pin now= and assert exact interpolated minutes; client.py is VERIFY-ONLY (hourly[]-carries-uvi regression canary guards the Phase-12 exclude widening)
- [Phase 14]: compute_uv (14-02) is a pure, interactive-layer-free helper (stdlib+dataclasses only) returning a frozen UvSummary — current=current.uvi, max=daily[0].uvi verbatim (Pitfall 6), hourly[] ONLY for linearly-interpolated up-cross/down-cross/peak; onecall_met accepted-but-ignored (A1, UV is unitless); round-then-band WHO category (A2); malformed/empty hourly -> stays_below, never raises (T-14-04 briefing-spine isolation). 14-03/14-04/Phase-15 reuse it verbatim.
- [Phase 14]: (14-04) The `uv <loc>` command (CLI `uv <loc>` / Discord `!uv <loc>`, UV-01) is a read-only `weather_views.uv(result, threshold, *, now=None)` handler: reads `result.forecast.raw_onecall_imp` (no second fetch, store-free), calls `compute_uv`, and returns a `CommandReply` with the full summary (Now/Today's max + WHO category/Peak/Crosses/Protect, or "stays below {threshold} today") PLUS a command-only compact daytime `HH:UV` hourly line (D-04 — briefing carries summary fields only). Registered as ONE Weather `CommandSpec` + `_wire_handlers` entry → auto-appears in the generated CLI subparser, Discord dispatch, and `help` (CMD-09 derive-from-one-list, no parser edit). Both dispatch sites thread `config.uv.threshold` via a sibling `elif spec.name == "uv":` branch mirroring next-cloudy's `cloud_threshold` (single literal each). A raising uv handler stays inside the existing non-propagating Discord envelope / clean CLI envelope and never gates the briefing spine (CMD-16 / T-14-10, asserted). Handler `now` is keyword-only + injectable for the anchored fixtures (forecast-handler idiom); live dispatch passes nothing → `datetime.now(tz)`.
- [Phase 15]: (15-01) UV monitor FOUNDATION (no monitor logic yet). UvConfig extended with monitor_enabled (True) / interval_seconds (900, RESTART-DEFERRED per DP-2 — baked into IntervalTrigger at registration, not live-reloaded) / value_margin (1.0), each fail-loud-validated (interval 60..86400 = T-15-02 DoS floor, margin 0..20). A DEDICATED uv_alerts table (DP-1, keyed UNIQUE(location_id, local_date, alert_kind)) + claim_uv_alert (INSERT OR IGNORE first-wins, restart-durable) + claimed_uv_kinds (durable prior-set reader) — structurally isolated from briefing sent_log/alerts so a UV dedup bug can NEVER block a briefing (UV-06 safety). Keyed on location.id (rename-safe), not name. _fires_on promoted to public catchup.fires_on (single source-of-truth active-today; the monitor reuses it, never forks weekday logic). tests/test_uv_monitor.py is the Wave-0 scaffold: a build-time dependency canary pins compute_uv's (onecall_imp, onecall_met, threshold, *, tz, now) signature + UvSummary fields + non-empty hourly[].uvi + daily[0].sunrise/sunset — fails loudly if Phase-14/Phase-12 regresses. 15-02 (tick + 3 decision branches) and 15-03 (daemon job wiring) consume these. UV-04/05/06 stay Pending until 15-03.
- [Phase 15]: (15-02) The UV monitor TICK lands as a pure, APScheduler-free `weatherbot/scheduler/uvmonitor.py` (mirrors catchup.py). `_uv_monitor_tick(holder, db_path, settings, client, channel, *, now_utc=None)` reads `holder.current()` ONCE (snapshot-once), then per location: `_active_today` (reuses `catchup.fires_on`, no forked weekday logic) → read-only `client.fetch_onecall(loc, "imperial")` (single fetch, UV unitless A1; NEVER `store.persist` — Pattern 4) → `_is_daylight` (configured-tz `daily[0].sunrise/sunset` epoch conversion, never the API offset, Pitfall 3) → `compute_uv` verbatim → `_decide`. `_decide` implements RESEARCH Pattern 3 IN ORDER: (1) already-high/crossing (`current>=T`): a first-poll already-high (no prior rows) ALSO claims `prewarn` WITHOUT posting (suppress the moot pre-warn) + posts "already ≥T"; a genuine crossing posts "now ≥T"; (2) pre-warn (`current<T`, neither prewarn nor crossing claimed): fires on time-proximity (within `lead` min of `crossing_time`) OR value-proximity (`T-current<=value_margin`), whichever first; (3) independent all-clear (`current<T` after a crossing claimed). Every post is gated by durable `claim_uv_alert` (rowcount==1) → at most once/day/location, restart-durable (Pitfall 2). Posts are best-effort plain `channel.send` (never send_briefing). Failure isolation is TWO-layer (UV-06): per-location try/except + an OUTERMOST envelope that logs critical + returns None (even a holder.current()/client-build raise never propagates to APScheduler — "die alone"). The module references NONE of the briefing exactly-once namespace (grep-asserted) — a UV bug can't gate a briefing. 24 tests green (full suite 559). 15-03 registers `_uv_monitor_tick` as an IntervalTrigger job (max_instances=1, gated on `monitor_enabled`, `interval_seconds`); UV-04/05/06 complete then.
- [Phase 14]: (14-03) The daily briefing renders six UV tokens (uv_now/uv_max/uv_cross/uv_window/uv_peak/uv_category) formatted in CODE (_format_uv) from compute_uv, emitted by Forecast.placeholders() in lockstep with renderer.CANONICAL (Pitfall 3, asserted by a test). Display strings collapse to "" when non-applicable (empty-collapse precedent of {hint}/{alert}); uv_cross says "stays below {threshold} today" on stays_below. The sunscreen hint + the briefing UV line BOTH derive from config.uv.threshold threaded via from_payloads(uv_threshold=...) (D-01 single source of truth, T-14-08 closed); lookup_weather passes config.uv.threshold. Missing/empty hourly[] degrades the UV line without raising the render (T-14-07). Peak display value = uv_max (daily[0].uvi), clock = hourly argmax. UV line shipped in all three starter templates (compact stays SMS-safe / no emoji).

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

**DEFERRED — non-halting (Phase 12 Plan 03, Task 4):** Live operator verification on host `yahir-mint` was explicitly deferred by the operator during autonomous execution (2026-06-19) so the milestone chain could continue. Phase 12 is marked complete because all must-haves are verified in code (5/5), the full suite is green (358 tests), and the code passed review + fix. Outstanding live UAT (tracked in 12-UAT.md, run via `/gsd-verify-work 12`): deploy + `sudo systemctl restart weatherbot` (new modules + widened `exclude` only load on the NEXT process start — hot-reload covers config/templates, not modules), then verify `help`/`locations`/`status`/`sun`/`wind`/`alerts`/`next-cloudy` answer on BOTH Discord and the CLI, and that the briefing path is unaffected.

Carry-forward tech debt from v1.1 is tracked in milestones/v1.1-MILESTONE-AUDIT.md (non-blocking): Phase 9 advisory hardening; `[bot] operator_id` / `[reload] watch` restart-deferred.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260615-fac | Resolve milestone-audit tech debt: drop dead `record_sent` + migrate idempotency test to `claim_slot`; backfill `requirements-completed` frontmatter on 11 plan SUMMARYs | 2026-06-15 | 7842e9e | [260615-fac-resolve-two-milestone-audit-tech-debt-it](./quick/260615-fac-resolve-two-milestone-audit-tech-debt-it/) |
| 260617-fua | Wire `ForecastCache.invalidate()` into the daemon reload path (closes Phase 11 code-review CR-01; reverses the Q2/D-12 cache-invalidation deferral) + daemon-level integration test | 2026-06-17 | 7ba1ff4 | [260617-fua-wire-forecastcache-invalidate-into-the-d](./quick/260617-fua-wire-forecastcache-invalidate-into-the-d/) |
| 260617-idm | Fix daemon startup crash-loop (Phase 11 UAT blocker): non-root service couldn't write PID file to root-owned `/run` — repoint `PID_FILE` to `/run/weatherbot/weatherbot.pid` + add `RuntimeDirectory=weatherbot` to the unit (requires manual root re-install of installed unit) | 2026-06-17 | 5dcec80 | [260617-idm-fix-daemon-startup-crash-loop-pid-file-w](./quick/260617-idm-fix-daemon-startup-crash-loop-pid-file-w/) |
| Phase 12 P02 | ~12 min | 3 tasks | 10 files |
| Phase 12 P03 | ~30 min | 3 tasks (of 4; Task 4 = live checkpoint) | 10 files, +14 tests, 358 green |
| Phase 13 P01 | ~25 min | 2 tasks | 5 files |
| Phase 13 P02 | ~12 min | 2 tasks | 10 files |
| Phase 13 P03 | ~12 min | 2 tasks | 5 files |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Host UAT | OPS-01 SC#1 live `sudo reboot` power-cycle on host `yahir-mint`. | ✅ CONFIRMED 2026-06-15 | 05-02 (2026-06-11) |
| Data semantics | DATA-03 delivered-only persistence — confirm when v2 analysis (ANLY-V2-01) reads the store. | Open (v2) | v1.0 close |

## Session Continuity

Last session: 2026-06-19T19:35:00Z
Stopped at: 15-02 complete (UV monitor tick + 3 decision branches) — ready for Phase 15 Plan 03
Resume file: None

## Operator Next Steps

- **Phase 12 live checkpoint (BLOCKING):** deploy to `yahir-mint`, `sudo systemctl restart weatherbot`, then verify every command (`help`/`locations`/`status`/`sun`/`wind`/`alerts`/`next-cloudy`) on BOTH Discord and the CLI per 12-03-PLAN.md Task 4. Reply "approved" (or describe what's wrong) to close Plan 12-03 and Phase 12.
- After approval: advance to Phase 13 (multi-day forecast templates) via the execution chain.
- Consider `/gsd-plan-phase --research-phase 15` for the new intraday UV monitor loop (highest-risk phase)
