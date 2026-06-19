---
phase: 15-proactive-uv-sunscreen-monitor
plan: 02
subsystem: scheduler
tags: [apscheduler, uv, dedup, sqlite, timezone, failure-isolation, tdd]

# Dependency graph
requires:
  - phase: 15-proactive-uv-sunscreen-monitor
    provides: "UvConfig monitor knobs (monitor_enabled/interval_seconds/value_margin) + claim_uv_alert/claimed_uv_kinds dedup + public catchup.fires_on"
  - phase: 14-uv-index-on-demand-daily-briefing
    provides: "compute_uv/UvSummary (current/crossing_time/window_start/window_end/stays_below) — reused verbatim, no re-derived UV math"
  - phase: 12-onecall-migration
    provides: 'fetch_onecall exclude="minutely" keeps hourly[].uvi + daily[0].sunrise/sunset'
provides:
  - "weatherbot/scheduler/uvmonitor.py — _uv_monitor_tick (APScheduler-free pure decision module) + _active_today + _is_daylight + the three decision branches"
  - "Read-only per-tick fetch (never store.persist) reusing compute_uv verbatim"
  - "Three once/day/location alert kinds (prewarn/crossing/allclear) with durable claim_uv_alert dedup"
  - "Two-layer failure isolation (per-location + outermost envelope); briefing namespace structurally untouched"
affects: [15-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure decision module beside the daemon (mirrors catchup.py) — APScheduler-free, clock-injected, unit-testable"
    - "Snapshot-once holder.current() threaded through the per-location loop (fire_slot idiom)"
    - "Two-layer failure isolation: per-iteration try/except + outermost envelope ('die alone')"
    - "Configured-tz epoch conversion for daylight bounding (never the API offset, Pitfall 3)"

key-files:
  created:
    - weatherbot/scheduler/uvmonitor.py
  modified:
    - tests/test_uv_monitor.py

key-decisions:
  - "Single imperial fetch per location — UV is unitless (A1), so no metric fetch needed"
  - "First-poll already-high also claims prewarn (without posting) to suppress the now-moot pre-warn"
  - "crossing kind reused for already-high with distinct 'already ≥T' vs 'now ≥T' wording (Open Q3)"
  - "Outermost envelope logs critical + returns None — never self-recovers, never propagates (UV-06)"

patterns-established:
  - "A monitor tick that re-reads live config, fetches read-only, and can never raise to APScheduler"
  - "Decision branches gated entirely by durable SQLite claims (restart-durable once-per-day-per-location)"

requirements-completed: []  # UV-04/05/06 complete after 15-03 wires the job into run_daemon

# Metrics
duration: ~40 min
completed: 2026-06-19
---

# Phase 15 Plan 02: UV Monitor Tick + Decision Branches Summary

**A pure, APScheduler-free `_uv_monitor_tick` that polls only active-today locations during daylight, fetches read-only (never persisting), reuses Phase-14's `compute_uv` verbatim, and fires three once/day/location alerts (pre-warn / crossing-or-already-high / all-clear) gated by durable dedup — and that can never raise to its scheduler caller.**

## Performance
- **Duration:** ~40 min
- **Completed:** 2026-06-19
- **Tasks:** 3 (all TDD: RED → GREEN in a single commit per task)
- **Files:** 2 (1 created, 1 modified)

## Accomplishments
- **Task 1 — gates + read-only fetch:** Created `weatherbot/scheduler/uvmonitor.py`. `_uv_monitor_tick` reads `holder.current()` exactly once (snapshot-once) and threads it through the per-location loop; `_active_today` reuses `catchup.fires_on` (no forked weekday logic); `_is_daylight` converts the `daily[0].sunrise/sunset` epochs in the **configured** `Location.timezone` (never the API offset). Each location fetches `client.fetch_onecall(loc, "imperial")` once and **never** calls `store.persist`. Per-location `try/except` isolation from the start.
- **Task 2 — the three decision branches:** `_decide` implements RESEARCH Pattern 3 exactly and in order — (1) already-high/crossing (a first-poll already-high also claims `prewarn` without posting to suppress the moot pre-warn, then posts the "already ≥T" wording; a genuine crossing posts "now ≥T"), (2) pre-warn (time- OR value-proximity, whichever first), (3) independent all-clear after a crossing. Every post is gated by `claim_uv_alert` (`rowcount==1`) so each kind fires at most once per day per location, durable across a restart.
- **Task 3 — outermost failure isolation:** Wrapped the whole tick body in an outermost `try/except` that logs `critical` and returns `None`, so even a `holder.current()`/client-build failure can never propagate to the APScheduler caller. Confirmed the per-location envelope and the best-effort post helper swallow fetch/compute/send raises. A structural test asserts the module references **none** of the briefing exactly-once namespace.

## Task Commits
1. **Task 1: tick + active-today/daylight gates + read-only fetch** — `ad67f54` (feat)
2. **Task 2: three decision branches + once/day/location dedup** — `88349fa` (feat)
3. **Task 3: outermost failure-isolation envelope** — `2621ddf` (feat)

## Files Created/Modified
- `weatherbot/scheduler/uvmonitor.py` (NEW, 328 lines) — `_uv_monitor_tick`, `_active_today`, `_is_daylight`, `_evaluate_location`, `_decide` + wording/window helpers + best-effort `_post`.
- `tests/test_uv_monitor.py` — filled the Wave-0 scaffold with 21 new behavior tests (gates, daylight, zero-fetch, no-persist, snapshot-once, all three decision branches, restart-dedup, ordering, stays-below, and the five isolation cases) against the Phase-14 anchored fixtures.

## Decisions Made
- Single imperial fetch per location (UV is unitless, A1) — no second metric fetch.
- First-poll already-high claims `prewarn` (without posting) so the now-pointless pre-warn never fires later; reuses the `crossing` dedup kind for already-high with distinct wording (Open Q3 / D-04).
- The outermost envelope logs `critical` and returns `None` — it never self-recovers, mirroring `fire_slot` / `BotThread._run` "die alone" discipline.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test builder used an invalid `days` preset**
- **Found during:** Task 1 (running the gate tests)
- **Issue:** The first draft of the test location builder passed `days="everyday"`, which `Schedule._days_valid` rejects (valid presets are `daily`/`mon-fri`/`weekdays`/`weekends`).
- **Fix:** Switched the builder to `days="daily"`.
- **Files modified:** `tests/test_uv_monitor.py`
- **Committed in:** `ad67f54`

**2. [Rule 1 - Bug] Initial tz-isolation test asserted the wrong daylight answer**
- **Found during:** Task 1 (`test_is_daylight_uses_configured_tz_not_api_offset`)
- **Issue:** The test's reasoning about LA-converted sun epochs was inverted (it expected `False` for an instant that is actually in-window).
- **Fix:** Re-derived the LA-converted window (01:40–16:40 LA) and asserted `18:00 LA → False`, `12:00 LA → True`, which genuinely exercises configured-tz conversion (a fixed-offset bug would flip both).
- **Files modified:** `tests/test_uv_monitor.py`
- **Committed in:** `ad67f54`

**3. [Rule 3 - Blocking] Docstring tokens tripped the grep-based acceptance asserts**
- **Found during:** Task 1 + Task 3 (acceptance greps for `persist(`, `timezone_offset`/`["timezone"]`, and `claim_slot`/`sent_log`/`record_sent`/`release_claim` all required `== 0`)
- **Issue:** The module docstrings/comments mentioned those exact tokens (e.g. "never `store.persist`", "the API `timezone_offset`", and the briefing-namespace helper names), which the literal grep counts treat as violations even though they are prose, not code.
- **Fix:** Reworded the docstrings/comments to describe the same invariants without the literal tokens (e.g. "never writes the weather time series", "the API payload offset", "the slot-claim / sent-log / record-sent / release-claim helpers"). No behavior change; the actual code already had zero such calls.
- **Files modified:** `weatherbot/scheduler/uvmonitor.py`
- **Committed in:** `ad67f54`, `2621ddf`

---

**Total deviations:** 3 auto-fixed (2 test bugs, 1 blocking grep-token rewording)
**Impact on plan:** None on scope — all were test/prose fixes; the production decision logic matches RESEARCH Pattern 3 exactly.

## Issues Encountered
None beyond the auto-fixed items above. Per-task TDD RED was confirmed before each GREEN.

## Known Stubs
None. The Task-1 commit intentionally left `_decide` a documented no-op stub (so the gate/fetch/no-persist behavior was testable first); Task 2 filled it completely. The shipped module has no remaining stubs.

## Requirements Status
UV-04/UV-05/UV-06 are **NOT** marked complete by this plan — the tick exists and is fully tested, but it is not yet registered as a daemon job. **Plan 15-03** wires `_uv_monitor_tick` into `run_daemon` as an `IntervalTrigger` job (gated by `monitor_enabled`, `max_instances=1`), after which UV-04/05/06 complete. Requirements remain `Pending`.

## Verification
- `uv run pytest tests/test_uv_monitor.py` → 24 passed (canary + gates + decisions + dedup + isolation + no-persist).
- `uv run pytest` → 559 passed (full suite green, no regression).
- `uv run ruff check weatherbot/scheduler/uvmonitor.py tests/test_uv_monitor.py` → clean.
- Acceptance greps: `_uv_monitor_tick`/`_active_today`/`_is_daylight` each ==1; `store.persist|persist(`==0; `fires_on`>=1, `_weekday_set|weekday()`==0; `timezone_offset|["timezone"]`==0; `claim_uv_alert`>=3; `send_briefing`==0; briefing-namespace tokens==0.

## Next Phase Readiness
- 15-03 consumes `weatherbot.scheduler.uvmonitor._uv_monitor_tick(holder, db_path, settings, client, channel)` — a top-level callback ready to register on an `IntervalTrigger` (set `max_instances=1`, gate on `snapshot.uv.monitor_enabled`, use `snapshot.uv.interval_seconds`).
- The tick is failure-isolated (can never crash the scheduler) and namespace-isolated (can never gate a briefing), so wiring it in carries no risk to the briefing spine.

## Self-Check: PASSED
- `weatherbot/scheduler/uvmonitor.py` present on disk.
- Commits `ad67f54`, `88349fa`, `2621ddf` exist in history.

---
*Phase: 15-proactive-uv-sunscreen-monitor*
*Completed: 2026-06-19*
