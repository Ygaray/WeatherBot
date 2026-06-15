---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: Awaiting next milestone
stopped_at: "Quick task 260615-fac complete (2 atomic commits 7a03da3 + 7842e9e); Phase 05 gap-closure done; OPS-01 SC#1 reboot UAT still deferred (host yahir-mint)"
last_updated: "2026-06-15T17:24:10.986Z"
last_activity: 2026-06-15 — Milestone v1.0 completed and archived
progress:
  total_phases: 5
  completed_phases: 5
  total_plans: 21
  completed_plans: 21
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-15 after v1.0 milestone)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Planning next milestone (v2.0) — run `/gsd-new-milestone`

## Current Position

Phase: Milestone v1.0 complete
Plan: —
Status: Awaiting next milestone
Last activity: 2026-06-15 — Milestone v1.0 completed and archived

## Performance Metrics

**Velocity:**

- Total plans completed: 19
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 4 | — | — |
| 02 | 5 | - | - |
| 03 | 5 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 02 P01 | 4 | 2 tasks | 16 files |
| Phase 02 P02 | 9 | 2 tasks | 10 files |
| Phase 02 P03 | 7 | 2 tasks | 16 files |
| Phase 02 P04 | 9 | 2 tasks | 2 files |
| Phase 02 P05 | 9 | 2 tasks | 5 files |
| Phase 03 P01 | 4 | 3 tasks | 8 files |
| Phase 03 P02 | 14min | 3 tasks | 8 files |
| Phase 03 P03 | 5 | 3 tasks | 5 files |
| Phase 03 P04 | 2 | 2 tasks | 2 files |
| Phase 03 P05 | 5 | 2 tasks | 3 files |
| Phase 04 P01 | 4 | 3 tasks | 5 files |
| Phase 04 P02 | 3min | 2 tasks | 6 files |
| Phase 04 P03 | 9 | 2 tasks | 2 files |
| Phase 04 P04 | 4 | 1 tasks | 2 files |
| Phase 05 P01 | 4min | 3 tasks | 8 files |
| Phase 05 P02 | — | 3 tasks | 5 files |
| Phase 05 P03 | 9min | 2 tasks | 2 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: Vertical-MVP structure — Phase 1 ships one complete briefing end-to-end (config + fetch + aggregate + render + Discord + `--send-now`) before any scheduling.
- [Roadmap]: Default data source is free OpenWeather 2.5 (`weather` + `forecast`) with 3-hour-bucket aggregation, NOT One Call 3.0 (which requires a card).
- [Roadmap]: IANA timezone per location and secrets-from-env are baked into the data model from Phase 1 (retrofitting is a migration).
- [Roadmap]: Long-term weather persistence is v1 (DATA-01/02/03), folded into Phase 1 — every OpenWeather fetch is written to a local SQLite store (location, fetch time UTC+local, raw payload, normalized fields) reusing the briefing's existing call, so history accrues from day one and is captured before scheduling lands (Phase 3).
- [Roadmap]: Persistence schema (DATA-02) is designed up front as a queryable per-location time series so v2 weather-pattern analysis (ANLY-V2-01/02) needs no data migration; analysis itself stays v2.
- [Phase ?]: [02-01]: D-01 enacted — 2.5 bucket aggregation retired; high/low/rain become One Call daily[0] in Plan 02-02.
- [Phase ?]: [02-02]: One Call 3.0 is the sole data source; from_payloads emits real daily[0] high/low/pop + feels_like/hint/alert; send_now collapsed to 2 calls; fetches persist to weather_onecall.
- [Phase ?]: [02-03]: Location.timezone promoted to required + IANA-validated; optional imperial/metric units override; validate_template/CANONICAL (12-key) wraps render and fires at the send boundary so --send-now aborts on a typo (D-03/09/10/11).
- [Phase ?]: [02-04]: D-04 + D-12 enacted — --geocode prints paste-ready coords only (never writes config, never on send path, LOC-03); --check validates config+template+unique-names+resolve and makes ONE One Call reachability probe with no delivery (CONF-05), 401/403 reports subscription-not-active/not-propagated (Pitfall 1).
- [Phase ?]: [02-05]: CR-01 closed — Location.units threaded end-to-end via Forecast.primary (default imperial); metric renders metric-primary, dual imperial+metric fetch preserved. WR-01 fixed (null feels_like/wind no longer fabricates a hint).
- [Phase 03]: [03-01]: days stored raw on Schedule, normalized at use via day_of_week; scheduler/days.py dependency-free to break config<->scheduler cycle; sent_log INSERT OR IGNORE on UNIQUE(location,send_time,local_date) for idempotent dedup.
- [Phase 03]: checked_at is a render-time freshness proxy (datetime.now in location tz) within seconds of the single DATA-03 fetch; no fetched_at field added (D-12)
- [Phase 03]: Scheduler timing keys merged at send_now's single render() call; Forecast.placeholders() stays weather-only (merge-at-call-site seam)
- [Phase ?]: [03-03]: weatherbot --run registers one CronTrigger per enabled slot at the location's own IANA tz; recovery owned by the sent-log + 90-min catch-up scan (misfire_grace_time=None), not APScheduler misfire
- [Phase ?]: [03-03]: fire_slot is check-before-fire / mark-after-success / per-job exception-isolated; DST exactly-once via the (location,send_time,local_date) idempotency key
- [Phase ?]: [03-04]: plan_catchup builds the fire instant via datetime(y,mo,d,hh,mm).replace(tzinfo=tz) so DST offset/fold re-resolves; spring-forward-gap slots skipped via zone round-trip and due/grace compares aware instants — closes gap #1 (SCHD-04 DST half)
- [Phase ?]: [03-05]: SCHD-07 exactly-once via atomic claim_slot
- [Phase ?]: [04-01]: tenacity APPROVED at human-verify checkpoint (T-04-SC); two-burst retry engine built — two_burst_wait HONORS a capped Retry-After (max(base, capped), cap=120s) on the fetch 429 path so parse_retry_after is live; sleep=stop_event.wait keeps the 45-min mid-pause interruptible (D-07). Public contract for Plans 03/04: build_retrying + is_transient/is_auth_failure/parse_retry_after + REASON_*.
- [Phase 04]: [04-02]: durable state primitives added — `alerts` table UNIQUE(location_name, slot_time, local_date) with `record_alert` INSERT-OR-IGNORE (rowcount==1 = first caller, at-most-one alert/slot/day, D-11) + `resolve_alert` (D-13) + single-row `heartbeat` (id=1 seed) `stamp_tick`/`stamp_success` (D-05). `Reliability` config model (8/600/2700, D-07) fails loud at load on non-positive fields and when 2*spread+pause >= 5400s (90-min grace, Pitfall 5); attached as Config.reliability via default_factory so existing configs load unchanged (D-09). Note: gsd-tools CLI not installed — STATE/ROADMAP updated manually.
- [Phase 04]: [04-03]: daemon patient path wired — fire_slot runs send_now through the Plan-01 two-burst retry (config.reliability budget, stop_event-interruptible mid-pause); outcomes classified into REASON_* with a deduped briefing_missed alert + CRITICAL log, resolve_alert + stamp_success on eventual delivery, hardened except->internal_error+traceback so the scheduler thread survives; send_now stayed single-attempt (retry locus in fire_slot, D-10); fetch HTTPStatusError propagates so a 429 Retry-After is honored on the daemon path; HEARTBEAT_INTERVAL_S=600 on an __heartbeat__ IntervalTrigger job.
- [Phase 05]: [05-01]: Phase-5 foundation built (no daemon changes). New `weatherbot/ops/` package: pure-stdlib `SystemdNotifier.ready()` (READY=1 AF_UNIX datagram, no-op when `NOTIFY_SOCKET` unset, OSError-swallowed, ZERO new deps — `sdnotify`/`systemd-python` rejected) + classified `run_self_check`/`CheckResult` reusing Phase-4 `is_auth_failure`/`is_transient` (401/403→auth_failed, transient/429/5xx→network_not_ready, clean→online). 401/403 folded into single `auth_failed` (no `key_propagating` — one probe can't disambiguate; 05-02 re-probe loop recovers a propagating key, D-06). selfcheck is import-cycle-free (imports neither cli nor daemon at module level; `build_client` imported lazily in-function). Additive single-row `health` table + `stamp_health` (CHECK id=1, parameterized, no-secret, D-08). `do_check` delegates validate+probe to the shared engine, keeping its 401/403 wording + retry-budget echo (D-03/D-09). 181 tests green; ruff clean. Note: gsd-tools CLI not installed — STATE/ROADMAP updated manually.
- [Phase 05]: [05-02]: daemon supervisor wired — `run_daemon` now runs the classified self-check BEFORE `scheduler.start()` and re-probes on an interruptible `stop.wait(RE_PROBE_INTERVAL_S=120)` (never `time.sleep`/`sys.exit`, D-04); SIGTERM handler MOVED before the gate (load-bearing, Pitfall 2) so a `systemctl stop` mid-loop shuts down cleanly without starting the scheduler. One-time three-part online signal on first pass: `stamp_health(online)` + `stamp_tick` + structured log + `SystemdNotifier.ready()`/READY=1 + a fixed-literal Discord ping (no interpolation, T-05-T-02); once-ness is structural (gate returns immediately on first pass, no later-recovery path). Shipped `deploy/weatherbot.service` (Type=notify, Restart=always, TimeoutStartSec=infinity, EnvironmentFile=-only secrets, non-root User=, After=/Wants=network-online.target, no WatchdogSec) + `deploy/README.md` (systemd-analyze verify clean). 184 tests green; ruff clean. HOST UAT (yahir-mint, 2026-06-11): OPS-02 SC#3 CONFIRMED (journal proves `weatherbot online` precedes `Started weatherbot.service` — READY=1 reaches systemd only after the self-check passes; secrets loaded via EnvironmentFile=). OPS-01 SC#1 (live `sudo reboot`) DEFERRED at operator's request — service installed + enabled + `active (running)`, post-reboot auto-start not yet observed. Post-checkpoint doc fix `e1595bc`: corrected README §4 (an empty `Environment=` from `systemctl show -p Environment` is EXPECTED for EnvironmentFile=-loaded vars; the self-check reaching `active` is the real proof the key loaded). Note: gsd-tools CLI not installed — STATE/ROADMAP/REQUIREMENTS updated manually.
- [Phase 04]: [04-04]: manual (attended) half of D-10 wired — new `run_send_now` wraps single-attempt `send_now` in a SHORT bounded Retrying (stop_after_attempt(3) + wait_exponential(max=10), NOT the daemon two-burst); retries a non-ok DeliveryResult OR a transient fetch/network error (reraise=True for exception-exhaustion + retry_error_callback returning the last result for result-exhaustion); reports outcome-only to the terminal (detail/status/exc-type, exit 1) and writes ZERO alerts/heartbeat rows (D-10 / Pitfall 4). `main`'s --send-now branch delegates to it; send_now stays the single-attempt composition root. `do_check` now echoes the resolved retry budget (attempts/spread/pause + approx total min) so a mis-tune is visible without sending (D-09). Phase 4 complete. Note: gsd-tools state.add-decision was a no-op; this decision logged manually.
- [Phase 05]: [05-03]: UAT gap closed — `run_daemon` now builds the Discord channel from config+settings when `channel is None` and settings present (mirrors `send_now` / cli.py:119-122), sharing the single instance with both `_register_jobs` and `emit_online`, so the `--run` path (cli.py:480, no `channel=`) delivers the one-time online ping. `build_channel` left intentionally un-guarded so a bad webhook/type fails loud at startup; an injected channel still wins and skips the build. Regression tests added for the `channel=None` (asserts build_channel invoked + ping delivered) and injected-skips-build paths — closing the test blind spot where every prior online test injected a channel. 186 tests green; ruff clean.

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- [Phase 2]: The 3-hour-bucket → today's high/low/rain aggregation is the highest-risk unit-testable surface; flagged for a focused spike with recorded JSON fixtures (clear-sky/no-rain, rainy, local-midnight boundary). Note: aggregation itself lands in Phase 1; deeper fixture work may carry into Phase 2.
- [Phase 3]: Backfill-vs-skip grace window (research suggests "send if <90 min late, else skip") is a product decision to confirm during Phase 3 planning.
- [Phase 4]: For a single-channel v1, "out-of-band" alert independence degrades to conspicuous local log + process-health signal; confirm what "independent enough" means.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260615-fac | Resolve milestone-audit tech debt: drop dead `record_sent` + migrate idempotency test to `claim_slot`; backfill `requirements-completed` frontmatter on 11 plan SUMMARYs | 2026-06-15 | 7842e9e | [260615-fac-resolve-two-milestone-audit-tech-debt-it](./quick/260615-fac-resolve-two-milestone-audit-tech-debt-it/) |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Host UAT | OPS-01 SC#1 live `sudo reboot` power-cycle on host `yahir-mint`. | ✅ CONFIRMED 2026-06-15 (post-reboot auto-start observed: `is-active` → active, post-boot `weatherbot online` log present) | 05-02 (2026-06-11) |

## Session Continuity

Last session: 2026-06-15 -- Completed quick task 260615-fac (milestone-audit tech-debt: dead record_sent removed + idempotency test migrated to claim_slot; requirements-completed frontmatter backfilled on 11 SUMMARYs). 186 tests green; ruff clean.
Stopped at: Quick task 260615-fac complete (2 atomic commits 7a03da3 + 7842e9e); Phase 05 gap-closure done; OPS-01 SC#1 reboot UAT still deferred (host yahir-mint)
Resume file: None (Phase 05 complete; pending the deferred OPS-01 reboot UAT before /gsd-complete-milestone)

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
