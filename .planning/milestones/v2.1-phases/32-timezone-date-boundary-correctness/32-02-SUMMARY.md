---
phase: 32-timezone-date-boundary-correctness
plan: 02
subsystem: weather
tags: [timezone, date-boundary, D-08, D-06, D-05, refactor, tdd-green]
status: complete
requires:
  - "32-01 RED tests (import-hygiene same-output/naive + store round-trip)"
provides:
  - "weatherbot.weather.dates — the ONE tz-correct local-date helper module (D-08)"
  - "local_date_iso(now_utc, tz) — core primitive with naive→UTC hardening (D-06)"
  - "local_date_for(location, now_utc) — Location-resolving wrapper (models/store contract)"
  - "select_today_daily(daily, tz, local_date) — match-by-own-local-date selector, None on no-match (D-05)"
affects:
  - "32-03 (catch-up) may import dates helpers"
  - "32-04 (models/uv) imports local_date_for/local_date_iso/select_today_daily; consumes the None degrade contract"
  - "32-05 (uvmonitor) imports local_date_iso and drops its own _local_date_iso/_daily0_matches_today"
tech-stack:
  added: []
  patterns:
    - "Pure acyclic leaf module (stdlib + TYPE_CHECKING-only Location) mirroring scheduler/days.py + weather/multiday.py — no import cycle"
    - "Naive datetime hardened to UTC before astimezone() (D-06/F33)"
    - "Match daily[] by each entry's OWN local date, never positional daily[0] (Pitfall 1); skip-never-raise on malformed dt/sunrise (ASVS V5)"
key-files:
  created:
    - "weatherbot/weather/dates.py — new pure helper module. Public contract (consumed by 32-04/32-05):
        def local_date_iso(now_utc: datetime, tz: timezone | ZoneInfo) -> str;
        def local_date_for(location: Location, now_utc: datetime) -> str;
        def select_today_daily(daily: list[dict] | None, tz: timezone | ZoneInfo, local_date: str) -> dict | None.
        Internal: def _resolve_tz(tz_name: str | None) -> timezone | ZoneInfo (mirrors multiday._resolve_tz).
        __all__ = ['local_date_iso', 'local_date_for', 'select_today_daily']."
  modified:
    - "weatherbot/weather/store.py — deleted local _local_date_iso (:210-224); imports local_date_for from weatherbot.weather.dates; persist target_local_date swapped to local_date_for(location, now_utc); removed now-unused zoneinfo import; WAL/_connect/init_db (Phase-31) untouched"
    - "tests/test_store.py — repointed test_onecall_write_atomic round-trip check at the shared local_date_for (the D-08 swap removed store._local_date_iso the test imported)"
decisions:
  - "D-08: exactly ONE tz-correct local-date helper (weather.dates); store.py is the first caller migrated"
  - "D-06: naive now_utc treated as UTC in the single helper — fixed once for all callers"
  - "D-05: select_today_daily returns None (→ caller degrades) when no daily[] entry matches today's configured-tz local date"
metrics:
  duration_minutes: 4
  completed: 2026-07-11
  tasks_completed: 2
  files_created: 1
  files_modified: 2
---

# Phase 32 Plan 02: Unified tz-correct dates helper + store migration Summary

One-liner: New pure, acyclic `weatherbot/weather/dates.py` (`local_date_iso`/`local_date_for`/`select_today_daily` with the D-06 naive→UTC guard baked into the primitive) becomes the single source of truth for "which local day is today," and `store.py` is migrated onto it byte-identically — closing the render/store date-divergence (F69) at its source.

## What was built

- **`weatherbot/weather/dates.py`** (new): a dependency-free leaf module mirroring `scheduler/days.py` + `weather/multiday.py` (`from __future__ import annotations`, stdlib-only, `TYPE_CHECKING`-only `Location`). Exposes:
  - `local_date_iso(now_utc, tz)` — core primitive. Attaches `timezone.utc` when `now_utc` is naive (D-06/F33), then `astimezone(tz).date().isoformat()`.
  - `local_date_for(location, now_utc)` — thin wrapper resolving `location.timezone` via `_resolve_tz`, delegating to the primitive (byte-identical output for the same resolved `(now, tz)`).
  - `select_today_daily(daily, tz, local_date)` — returns the `daily[]` entry whose OWN local date (from `dt` or `sunrise` in `tz`) equals `local_date`; `None` on no-match/empty; skips malformed entries without raising (D-05, ASVS V5).
  - `_resolve_tz(tz_name)` — internal belt-and-suspenders UTC fallback mirroring `multiday._resolve_tz`.
- **`store.py`** migrated: local `_local_date_iso` deleted, `local_date_for` imported, `persist:236` call swapped, unused `zoneinfo` import removed. Phase-31 WAL/`_connect`/`init_db` code untouched. No data migration (byte-identical output for aware `now_utc` + valid tz).

## Verification (plan-level acceptance)

- `uv run python -c "from weatherbot.weather import store, dates, models"` → all import, no cycle (leaf module).
- `grep -c "def _local_date_iso" weatherbot/weather/store.py` → 0.
- dates.py has no top-level import from `weatherbot.config`/`store`/`scheduler`/`apscheduler` (grep-clean); ruff clean.
- `test_dates_helper_same_output_and_deterministic` (the test this plan owns) → GREEN, including the naive→UTC (D-06) assertion.
- `tests/test_store.py` → 31 passed (store behavior + local_date round-trip unregressed).

## Suite state (regression evidence)

| | pre-32-02 (1b3781b) | after 32-02 |
|---|---|---|
| passed | 833 | **834** (+1: dates same-output test turned GREEN) |
| failed | 10 | **9** |
| snapshots failed | 2 | 2 (unchanged, pre-existing syrupy quirk — no snapshot references dates/store) |

Zero pre-existing regressions. The remaining 9 failures are 32-01 RED tests owned by later plans:
- `test_dates_single_helper_no_local_copies` → now reports only `models.py` + `uvmonitor.py` still carry `_local_date_iso` (store.py cleared). Turns GREEN when 32-04 (models) and 32-05 (uvmonitor) migrate.
- `test_models.py` (daily0/naive), `test_uv.py` (daily0 guard/hourly sort) → 32-04.
- `test_scheduler.py` (catch-up ×2) → 32-03.
- `test_uv_monitor.py` (×2) → 32-05.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Repointed pre-existing store test off deleted `store._local_date_iso`**
- **Found during:** Task 2
- **Issue:** `tests/test_store.py::test_onecall_write_atomic` imported `from weatherbot.weather.store import _local_date_iso` — the D-08 unification (this plan's explicit goal) deletes that symbol, so the pre-existing (non-RED) test raised `ImportError`.
- **Fix:** Repointed the round-trip assertion at the shared helper it now validates against: `from weatherbot.weather.dates import local_date_for`. The assertion (byte-identical `target_local_date` round-trip) is preserved and strengthened (it now checks against the exact helper `persist` uses). No test weakened.
- **Files modified:** `tests/test_store.py`
- **Commit:** 698de96

**2. [Rule 3 - Blocking] Removed now-unused `zoneinfo` import from store.py**
- **Found during:** Task 2
- **Issue:** After deleting `_local_date_iso`, `ZoneInfo`/`ZoneInfoNotFoundError` were only referenced inside that function → dead import (ruff F401).
- **Fix:** Dropped `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError`. `timezone` (still used widely) retained.
- **Files modified:** `weatherbot/weather/store.py`
- **Commit:** 698de96

## Known Stubs

None. No placeholder/stub values introduced; every symbol is fully wired.

## Threat surface

No new security-relevant surface beyond the plan's `<threat_model>`. `dates.py` logs nothing, touches no URL/secret; `select_today_daily` skip-never-raise mitigation (T-32-03) is implemented; store `local_date` keying single-source mitigation (T-32-04) is implemented. No package installs (stdlib only).

## Commits

- 5767d23: feat(32-02): add unified tz-correct dates helper + selector (D-08/D-06/D-05)
- 698de96: feat(32-02): migrate store.py onto shared local_date_for helper (D-08)

## Self-Check: PASSED

- FOUND: weatherbot/weather/dates.py
- FOUND: .planning/phases/32-timezone-date-boundary-correctness/32-02-SUMMARY.md
- FOUND commit: 5767d23
- FOUND commit: 698de96
