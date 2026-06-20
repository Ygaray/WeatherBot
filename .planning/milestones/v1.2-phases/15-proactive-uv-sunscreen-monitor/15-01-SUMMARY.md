---
phase: 15-proactive-uv-sunscreen-monitor
plan: 01
subsystem: infra
tags: [pydantic, sqlite, apscheduler, config, dedup, uv, testing]

# Dependency graph
requires:
  - phase: 14-uv-index-on-demand-daily-briefing
    provides: "compute_uv/UvSummary helper (crossing_time/window/stays_below) + the [uv] config table (threshold, pre_warn_lead_minutes)"
  - phase: 12-onecall-migration
    provides: 'fetch_onecall exclude="minutely" — keeps hourly[].uvi + daily[0].sunrise/sunset in the payload'
provides:
  - "UvConfig extended with monitor_enabled / interval_seconds / value_margin (frozen, fail-loud validators)"
  - "uv_alerts dedup table + claim_uv_alert (first-wins) + claimed_uv_kinds (durable prior-set reader)"
  - "public catchup.fires_on (promoted from _fires_on) — single source-of-truth active-today logic"
  - "tests/test_uv_monitor.py Wave-0 scaffold + build-time dependency canary"
affects: [15-02, 15-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dedicated dedup table per namespace (uv_alerts) isolated from briefing sent_log/alerts (DP-1, UV-06 safety)"
    - "Restart-deferred config knob (interval_seconds) documented like [reload] watch (DP-2)"
    - "Build-time dependency canary pinning a cross-phase helper signature + payload contract"

key-files:
  created:
    - tests/test_uv_monitor.py
  modified:
    - weatherbot/config/models.py
    - weatherbot/weather/store.py
    - weatherbot/scheduler/catchup.py
    - tests/test_config_uv.py
    - tests/test_store.py
    - tests/test_scheduler.py

key-decisions:
  - "interval_seconds floored at 60s (T-15-02 DoS) and ceilinged at 86400; restart-deferred (DP-2)"
  - "value_margin bounded 0..20 (mirrors threshold's UVI scale)"
  - "Dedicated uv_alerts table keyed (location_id, local_date, alert_kind) — never reuses the briefing alerts table (DP-1)"
  - "Keyed on location.id (rename-safe), not location.name"
  - "Promoted _fires_on -> public fires_on rather than copy-pasting weekday logic into the monitor"

patterns-established:
  - "Namespace-isolated SQLite dedup: a UV dedup bug can never touch a briefing's exactly-once rows"
  - "Wave-0 canary fails loudly at build time if compute_uv's signature or hourly[].uvi regresses"

requirements-completed: []  # UV-04/05/06 are FOUNDATION-only here; they complete after 15-02 (tick) + 15-03 (daemon wiring)

# Metrics
duration: ~30 min
completed: 2026-06-19
---

# Phase 15 Plan 01: UV Monitor Foundation Summary

**Restart-durable UV-alert dedup table + three frozen monitor config knobs + a public fires_on and a build-time dependency canary — the primitives the 15-02 tick and 15-03 daemon wiring consume.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-06-19T12:40:00Z (approx)
- **Completed:** 2026-06-19T12:48:00Z
- **Tasks:** 3
- **Files modified:** 7 (1 created, 6 modified)

## Accomplishments
- Extended the existing `[uv]` config table with `monitor_enabled` (True), `interval_seconds` (900, restart-deferred), and `value_margin` (1.0), each with a fail-loud `@field_validator` — absent/partial `[uv]` tables still load; reload re-reads edits.
- Added a dedicated `uv_alerts` table + `claim_uv_alert` (atomic first-wins `INSERT OR IGNORE`) + `claimed_uv_kinds` (durable prior-set reader), restart-safe across a fresh connection and structurally isolated from the briefing `sent_log`/`alerts` namespace (UV-06 safety).
- Promoted `catchup._fires_on` to a public `fires_on` so the monitor reuses the single source-of-truth active-today logic instead of forking weekday parsing.
- Stood up `tests/test_uv_monitor.py` with a dependency canary that pins `compute_uv`'s `(onecall_imp, onecall_met, threshold, *, tz, now)` signature, the `UvSummary` fields, and the non-empty `hourly[].uvi` + `daily[0].sunrise/sunset` payload contract — failing loudly at build time if any regress.

## Task Commits

Each task was committed atomically (TDD: tests + impl in one commit per task):

1. **Task 1: Extend UvConfig with monitor knobs** - `37b4785` (feat)
2. **Task 2: uv_alerts dedup table + claim_uv_alert/claimed_uv_kinds** - `381fef0` (feat)
3. **Task 3: Promote _fires_on to fires_on + Wave-0 canary** - `6623597` (feat)

## Files Created/Modified
- `weatherbot/config/models.py` - Three monitor knobs + two validators on the existing `UvConfig`.
- `weatherbot/weather/store.py` - `uv_alerts` table in `_SCHEMA` + `claim_uv_alert` + `claimed_uv_kinds`.
- `weatherbot/scheduler/catchup.py` - `_fires_on` renamed to public `fires_on` (call site + docstrings updated).
- `tests/test_config_uv.py` - Defaults/partial/explicit-load/range-fail/reload cases for the new knobs.
- `tests/test_store.py` - first-wins/repeat-loses, distinct kinds, per-location/date independence, fresh-connection durability, namespace isolation, no-secret rows.
- `tests/test_uv_monitor.py` (NEW) - Wave-0 scaffold + dependency canary.
- `tests/test_scheduler.py` - Updated `_fires_on` callers to the public name.

## Decisions Made
- `interval_seconds` floored at 60s (T-15-02 DoS guard) and ceilinged at 86400; documented as restart-deferred (DP-2).
- `value_margin` bounded 0..20 to match `threshold`'s UVI scale.
- Dedicated `uv_alerts` table (DP-1) keyed on `location.id` (rename-safe), never reusing the briefing `alerts` table.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Plan referenced a non-existent `tests/test_catchup.py`**
- **Found during:** Task 3 (verify step + acceptance criteria)
- **Issue:** The plan's verify (`uv run pytest tests/test_catchup.py -x`) and acceptance criteria named `tests/test_catchup.py`, but the catch-up planner / `_fires_on` tests actually live in `tests/test_scheduler.py` (no `test_catchup.py` exists). Renaming `_fires_on` would also break the existing `_fires_on` callers in `test_scheduler.py`.
- **Fix:** Ran the catchup/`fires_on` verification against `tests/test_scheduler.py` (the real home) and updated its three `_fires_on` import/call sites to the public `fires_on`. No behavior change.
- **Files modified:** `tests/test_scheduler.py`
- **Verification:** `uv run pytest tests/test_scheduler.py -q` → 47 passed; `grep -c 'def _fires_on'` → 0, `grep -c 'def fires_on'` → 1.
- **Committed in:** `6623597` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The deviation was a plan-path mismatch only; the intended verification was performed against the correct test file. No scope change.

## Issues Encountered
None — all three tasks executed cleanly. Per-task TDD RED was confirmed before each GREEN.

## Known Stubs
None — this plan delivers complete, tested primitives. `tests/test_uv_monitor.py` is an intentional Wave-0 scaffold (canary only); its module docstring lists the UV-04/05/06 behavior coverage that **Plan 15-02** fills in. This is documented and expected, not an unintended stub.

## Requirements Status
UV-04/05/06 are **NOT** marked complete by this plan. 15-01 lays the durable foundation (config surface, dedup namespace, public active-today helper, dependency canary); the actual monitor behavior lands in 15-02 (the tick + decision branches) and 15-03 (daemon job registration). Requirements remain `Pending` until 15-03 completes.

## User Setup Required
None - no external service configuration required. (Deferred to phase end: the live host's `config.toml` may add an optional `[uv]` section, but absent/partial tables already load with sane defaults.)

## Next Phase Readiness
- All 15-02 consumables are in place: `UvConfig.monitor_enabled/interval_seconds/value_margin`, `store.claim_uv_alert`/`claimed_uv_kinds`, and `catchup.fires_on`.
- The dependency canary confirms `compute_uv`/`UvSummary` and the `hourly[].uvi` payload are present and correctly shaped — no Phase-14/Phase-12 regression blocks 15-02.
- Full suite green (538 passed); `ruff` clean on all three source files.

## Self-Check: PASSED
- All created/modified files present on disk.
- All three task commits (`37b4785`, `381fef0`, `6623597`) exist in history.

---
*Phase: 15-proactive-uv-sunscreen-monitor*
*Completed: 2026-06-19*
