---
phase: 04-retry-then-alert-reliability
plan: 02
subsystem: persistence + config
tags: [sqlite, alerts, heartbeat, pydantic, retry-config, reliability]
dependency_graph:
  requires:
    - "weatherbot/weather/store.py (_SCHEMA + claim_slot/release_claim idioms, Phase 1/3)"
    - "weatherbot/config/models.py (Schedule field_validator idiom, Phase 2/3)"
  provides:
    - "store.record_alert / resolve_alert / stamp_tick / stamp_success"
    - "alerts table (durable missed-briefing record, INSERT-OR-IGNORE dedup)"
    - "heartbeat single-row liveness table (seeded id=1)"
    - "config.models.Reliability (load-validated retry-config model)"
    - "Config.reliability (default_factory=Reliability)"
  affects:
    - "Plan 04-03 (daemon patient path consumes record_alert/resolve_alert/stamp_* + Config.reliability)"
    - "Plan 04-04 (manual tight path + --check surfaces Config.reliability budget)"
tech_stack:
  added: []
  patterns:
    - "INSERT OR IGNORE on UNIQUE key = race-free at-most-once dedup (rowcount==1 = first caller)"
    - "single-row table via PRIMARY KEY CHECK (id=1) + INSERT OR IGNORE seed, UPDATE-in-place upsert"
    - "pydantic field_validator (positivity) + model_validator(mode='after') (cross-field budget guard), extra='forbid'"
    - "optional config section via Field(default_factory=...) so existing configs load unchanged"
key_files:
  created: []
  modified:
    - "weatherbot/weather/store.py"
    - "weatherbot/config/models.py"
    - "config.example.toml"
    - "config.toml (gitignored user config — edited on disk, not committed)"
    - "tests/test_store.py"
    - "tests/test_config.py"
decisions:
  - "D-03/D-11: alerts UNIQUE(location_name, slot_time, local_date); record_alert is INSERT OR IGNORE returning rowcount==1"
  - "D-13: resolved_at_utc NULL = unresolved; resolve_alert only stamps the matching unresolved row (no-op otherwise)"
  - "D-05: heartbeat is a single seeded row (id=1), stamp_tick/stamp_success UPDATE in place"
  - "D-09 / Pitfall 5: Reliability fails loud at load on non-positive fields and when 2*burst_spread_seconds + mid_pause_seconds >= 5400s (90-min catch-up grace)"
metrics:
  duration_min: 3
  completed: 2026-06-11
---

# Phase 4 Plan 02: Durable State + Retry Config Summary

Added the persistence + config foundation Phase 4 needs: the `alerts` and `heartbeat` SQLite tables (with `record_alert`/`resolve_alert`/`stamp_tick`/`stamp_success` helpers built verbatim on the existing `claim_slot`/`release_claim` idioms) and the load-validated `Reliability` retry-config pydantic model (with a documented optional `[reliability]` TOML section). All additive, all modeled on Phase 1-3 patterns; no orchestration wiring (that is Plans 03/04).

## What Was Built

### Task 1 — `alerts` + `heartbeat` tables and helpers (store.py)
- Appended two `CREATE TABLE IF NOT EXISTS` tables to the single `_SCHEMA` string (additive; no destructive migration, T-04-DB):
  - **`alerts`**: `id`, `location_name`, `slot_time`, `local_date`, `reason`, `severity`, `created_at_utc`, `resolved_at_utc` (NULL = unresolved), `UNIQUE(location_name, slot_time, local_date)`.
  - **`heartbeat`**: `id INTEGER PRIMARY KEY CHECK (id = 1)`, `last_tick_utc`, `last_success_utc`, seeded with `INSERT OR IGNORE INTO heartbeat (id, ...) VALUES (1, NULL, NULL)` so row 1 always exists.
- Helpers (all schema-on-connect, parameterized `?` only, secret-clean):
  - `record_alert(db_path, location_name, slot_time, local_date, reason, severity="critical") -> bool` — `INSERT OR IGNORE`, returns `rowcount == 1` (this caller was the first → may also emit the CRITICAL log). At most one alert per slot/day (D-11 anti-loop).
  - `resolve_alert(db_path, location_name, slot_time, local_date) -> None` — `UPDATE ... SET resolved_at_utc=? WHERE <key> AND resolved_at_utc IS NULL` (D-13); no-op when no match.
  - `stamp_tick(db_path)` / `stamp_success(db_path)` — `UPDATE heartbeat SET last_tick_utc/last_success_utc=? WHERE id=1` (upsert-in-place, RELY-05).

### Task 2 — `Reliability` retry-config model + documented `[reliability]` TOML
- `class Reliability(BaseModel)` in `config/models.py` with `model_config = ConfigDict(extra="forbid")` and fields:
  - `attempts_per_burst: int = 8`
  - `burst_spread_seconds: int = 600`
  - `mid_pause_seconds: int = 2700`
- `@field_validator` enforcing `> 0` on all three; `@model_validator(mode="after")` enforcing `2*burst_spread_seconds + mid_pause_seconds < 5400` (90-min catch-up grace; Pitfall 5 belt-and-suspenders).
- Attached to `Config` as `reliability: Reliability = Field(default_factory=Reliability)` — existing configs with no `[reliability]` section load unchanged with the D-07 defaults.
- Documented optional `[reliability]` section added to `config.example.toml` and `config.toml` (commented, so `--check` passes on an un-edited file). `config.toml` is gitignored user config — edited on disk but not committed.

## Contract for Plans 03/04 (match these exactly)

**`alerts` columns:** `id, location_name, slot_time, local_date, reason, severity, created_at_utc, resolved_at_utc` — UNIQUE on `(location_name, slot_time, local_date)`.
**`heartbeat` columns:** `id (=1), last_tick_utc, last_success_utc`.
**Helper signatures:**
- `record_alert(db_path, location_name, slot_time, local_date, reason, severity="critical") -> bool`
- `resolve_alert(db_path, location_name, slot_time, local_date) -> None`
- `stamp_tick(db_path) -> None`, `stamp_success(db_path) -> None`
**`Reliability` fields + defaults:** `attempts_per_burst=8`, `burst_spread_seconds=600`, `mid_pause_seconds=2700`; accessed via `config.reliability.*`.

## Verification

- `uv run pytest tests/test_store.py -q -x` → 13 passed
- `uv run pytest tests/test_config.py -q -x` → 24 passed
- `uv run pytest -q` → 147 passed, 7 skipped (skips are Plan 04-03 placeholders in `test_reliability.py`)
- `uv run ruff check` on all four touched source/test files → All checks passed
- `grep -c "INSERT OR IGNORE INTO alerts" weatherbot/weather/store.py` → 1
- `grep -n "default_factory=Reliability" weatherbot/config/models.py` → matches
- No f-string SQL in the new inserts/updates; no `appid`/host bound into any new row (secret-leak test asserts absence)

## Deviations from Plan

**1. [Rule 3 - Blocking] `config.toml` is gitignored — committed `config.example.toml` only**
- **Found during:** Task 2 commit
- **Issue:** `git add config.toml` was rejected (`.gitignore` excludes the user's live config, by design from earlier phases).
- **Fix:** Edited `config.toml` on disk for the user (as the plan intends) but committed only the tracked artifact `config.example.toml`. The documented `[reliability]` section is identical in both.
- **Files modified:** config.toml (uncommitted, gitignored), config.example.toml (committed)
- **Commit:** 14b9343

## Deferred Issues (out of scope)

- `tests/test_reliability.py::test_retry_after_capped` (Plan 04-01's file) is timing-sensitive: it intermittently asserts ~121.96s against the 120s Retry-After cap when the full suite runs under load, but passes in isolation and on re-run. It touches none of this plan's files. Logged to `deferred-items.md`; not fixed (scope boundary — belongs to the `weatherbot/reliability/` retry engine, Plan 04-01). Suggested fix: inject a frozen clock into the HTTP-date Retry-After parse path.

## Threat Surface

No new trust boundaries beyond the plan's `<threat_model>`. The new tables carry only location/slot/date/reason/severity/timestamps (T-04-01 verified by the secret-leak test); all writes are parameterized `?` (T-03-01); schema changes are additive `CREATE TABLE IF NOT EXISTS` only (T-04-DB); the `[reliability]` config crosses the user→pydantic boundary and is fail-loud validated (T-04-CFG).

## Commits

- bf676c7 — test(04-02): add failing tests for alerts/heartbeat store helpers (RED)
- 282c394 — feat(04-02): add alerts + heartbeat tables and helpers to store.py (GREEN)
- 99f473a — test(04-02): add failing test for Reliability retry-config validation (RED)
- 14b9343 — feat(04-02): add Reliability retry-config model + documented [reliability] TOML (GREEN)

## TDD Gate Compliance

Both tasks followed RED → GREEN. Each task has a `test(...)` commit immediately preceding its `feat(...)` commit. No REFACTOR was needed (helpers/model are minimal). No test passed unexpectedly during any RED phase.

## Self-Check: PASSED

All 6 declared files exist on disk; all 4 task commits (bf676c7, 282c394, 99f473a, 14b9343) are present in git history.
