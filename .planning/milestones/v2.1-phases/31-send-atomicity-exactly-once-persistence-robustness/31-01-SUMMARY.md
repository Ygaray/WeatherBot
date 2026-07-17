---
phase: 31-send-atomicity-exactly-once-persistence-robustness
plan: 01
subsystem: database
tags: [sqlite, wal, busy_timeout, concurrency, atomicity, store]

# Dependency graph
requires:
  - phase: 04-alerts-heartbeat
    provides: the store schema (alerts/heartbeat) + record_alert/stamp_* write fns hardened here
  - phase: 12-status-readers
    provides: read_heartbeat/read_health readers now opened read-only
provides:
  - "_connect(db_path, *, read_only=False) helper — centralized per-connection busy_timeout + read-only mode=ro URI"
  - "init_db repurposed as SOLE schema owner: sets persistent PRAGMA journal_mode=WAL once + owns executescript(_SCHEMA)"
  - "4 status reads (was_sent/claimed_uv_kinds/read_heartbeat/read_health) open read-only and take no write lock (F10 fix)"
  - "all 9 store write fns routed through _connect() with per-connect schema DDL removed"
  - "init_db wired into build_runtime (daemon startup) + CLI send-now/status paths as the one-time bootstrap"
  - "store regression tests locking WAL/busy_timeout, read-no-write-lock, and atomic onecall write"
affects: [31-02, 31-03, send-atomicity, exactly-once]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SQLite WAL set once persistently at init; busy_timeout set per-connection in a shared _connect() helper"
    - "read/write connect split: reads open file:{path}?mode=ro (uri=True) so a stray write raises instead of corrupting"
    - "schema ownership centralized: executescript(_SCHEMA) lives in exactly one place (init_db), invoked once at startup"

key-files:
  created: []
  modified:
    - weatherbot/weather/store.py
    - tests/test_store.py
    - tests/conftest.py
    - weatherbot/scheduler/wiring.py
    - weatherbot/cli.py

key-decisions:
  - "HARD-STORE-01 is confirm-only: persist was already a single-with atomic dual-INSERT; no truncate-then-write bug existed, so persist was NOT restructured (D-08, RESEARCH Pattern 6)."
  - "init_db must run once at startup — since reads/writes no longer self-create the schema, wired init_db into build_runtime (composition root) + the CLI send/status entrypoints (Rule 3 blocking fix)."
  - "tmp_db test fixture now bootstraps the schema via init_db, mirroring the new production startup contract (D-07)."
  - "busy_timeout=5000ms per D-06 (SQLite historical default; conservative under the ~10-worker + heartbeat + UV contention profile)."

patterns-established:
  - "Pattern: shared _connect() as the single store connect seam (busy_timeout + read/write split)"
  - "Pattern: WAL persistent-at-init, busy_timeout per-connection"
  - "Pattern: schema bootstrap owned once at the composition root, not on every connect"

requirements-completed: [HARD-STORE-01, HARD-STORE-02]

coverage:
  - id: D1
    description: "SQLite opened in WAL journal mode set once persistently at init (a fresh connect reports journal_mode=wal) and every store connection carries a non-zero busy_timeout."
    requirement: "HARD-STORE-02"
    verification:
      - kind: unit
        ref: "tests/test_store.py#test_wal_and_busy_timeout_are_set"
        status: pass
    human_judgment: false
  - id: D2
    description: "A status read (was_sent/read_heartbeat/read_health/claimed_uv_kinds) takes NO write lock: opens read-only, runs no seeding DDL, and does not raise database is locked when a write lock is held concurrently (F10)."
    requirement: "HARD-STORE-02"
    verification:
      - kind: unit
        ref: "tests/test_store.py#test_reads_take_no_write_lock"
        status: pass
    human_judgment: false
  - id: D3
    description: "The weather_onecall multi-step write commits both unit variants as one atomic transaction, and target_local_date round-trips byte-identical."
    requirement: "HARD-STORE-01"
    verification:
      - kind: unit
        ref: "tests/test_store.py#test_onecall_write_atomic"
        status: pass
    human_judgment: false
  - id: D4
    description: "executescript(_SCHEMA) appears in exactly one place (init_db); all writes route through _connect() and the 4 reads open read-only; full store suite + full project suite green."
    requirement: "HARD-STORE-01"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_store.py -q (30 passed); grep -c 'executescript(_SCHEMA)' weatherbot/weather/store.py == 1"
        status: pass
      - kind: integration
        ref: "uv run pytest -q (815 passed, exit 0)"
        status: pass
    human_judgment: false
  - id: D5
    description: "On the live systemd DB (host yahir-mint), after restart PRAGMA journal_mode returns 'wal' and -wal/-shm sidecars appear."
    verification: []
    human_judgment: true
    rationale: "Deferred Gate-2 milestone-close obligation — the WAL switch on the production DB requires a clean daemon restart on the live host, which is not an autonomous step."

# Metrics
duration: ~20min
completed: 2026-07-10
status: complete
---

# Phase 31 Plan 01: Store Hardening (WAL + busy_timeout + read/write split) Summary

**Shared `_connect()` helper with persistent WAL + per-connection busy_timeout, `init_db` made the sole schema owner, and the four status reads opened `mode=ro` so a read concurrent with a daemon write no longer raises `database is locked` (F10) — de-risking the F01 duplicate-briefing critical.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-10
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Added `_connect(db_path, *, read_only=False)` centralizing the store's connect discipline: `PRAGMA busy_timeout=5000` on every connection, and a `file:{db_path}?mode=ro` (uri=True) read-only branch.
- Repurposed `init_db` as the SOLE owner of the schema: it now sets persistent `PRAGMA journal_mode=WAL` once and is the only site running `executescript(_SCHEMA)` (grep count == 1).
- Opened the four status reads (`was_sent`, `claimed_uv_kinds`, `read_heartbeat`, `read_health`) read-only with no seeding DDL — they no longer take a write lock (F10 fix), so a read concurrent with a held write does not raise `database is locked`.
- Routed all nine write fns through `_connect()` and removed their per-connect `executescript(_SCHEMA)`; `persist` kept its two INSERTs + single commit as one atomic transaction (no restructure — confirm-only per RESEARCH).
- Wired `init_db` into the daemon composition root (`build_runtime`) and the CLI send-now/status entrypoints so the one-time schema+WAL bootstrap runs at startup (necessary because reads/writes no longer self-create the schema).

## Task Commits

Each task was committed atomically:

1. **Task 1: Wave-0 store regression tests (RED)** — `c04493f` (test)
2. **Task 2: _connect() helper + WAL/schema ownership in init_db** — `9f25988` (feat)
3. **Task 3: route writes through _connect(); open 4 reads read-only; drop per-connect schema** — `93227f3` (feat)

**Plan metadata:** (see final docs commit)

## RED evidence (TDD gate, Task 1)

Against the pre-fix `store.py` (before Tasks 2-3), the three tests ran RED as required:
- `test_wal_and_busy_timeout_are_set` — FAILED with `ImportError` (no `_connect` yet).
- `test_reads_take_no_write_lock` — FAILED with `sqlite3.OperationalError: database is locked` at `store.py:242` (`was_sent`'s per-connect `executescript(_SCHEMA)` taking a write lock) — the exact F10 defect.
- `test_onecall_write_atomic` — PASSED even at RED, confirming RESEARCH's finding that `persist` was ALREADY atomic (HARD-STORE-01 is confirm-only, no truncate-then-write bug). The plan required "at least the WAL and read-lock assertions" to fail at RED — satisfied.

## Files Created/Modified
- `weatherbot/weather/store.py` — added `_connect()`; repurposed `init_db` (WAL + sole schema owner); 9 writes → `_connect()`; 4 reads → `_connect(read_only=True)`; deleted all per-connect `executescript(_SCHEMA)`.
- `tests/test_store.py` — 3 new regression tests (WAL/busy_timeout, read-no-write-lock, atomic onecall write).
- `tests/conftest.py` — `tmp_db` fixture now bootstraps schema via `init_db` (new startup contract).
- `weatherbot/scheduler/wiring.py` — `build_runtime` calls `init_db(db_path)` once before jobs/heartbeat/gate touch the store.
- `weatherbot/cli.py` — CLI send-now + status paths call `init_db` after mkdir (fresh-install bootstrap).

## Decisions Made
- **`persist` untouched (D-08 confirm-only):** RESEARCH verified `persist` is already a single-`with` atomic dual-INSERT; no truncate bug exists, so it was not restructured — only its per-connect schema DDL was dropped.
- **busy_timeout=5000ms (D-06):** matches SQLite's historical default; conservative under the ~10-worker + heartbeat + UV contention profile (WAL makes contention effectively disappear; the timeout is belt-and-suspenders).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Wired `init_db` into startup (daemon composition root + CLI entrypoints)**
- **Found during:** Task 3 (dropping per-connect `executescript`)
- **Issue:** `init_db` was not called anywhere in production code — the old design relied on every store fn creating the schema on connect. Removing per-connect schema DDL (as the plan requires) without wiring `init_db` at startup would break production: on a fresh DB the writes would hit non-existent tables (`no such table: weather_onecall`) and the `mode=ro` reads would fail (`unable to open database file`).
- **Fix:** Added `init_db(db_path)` at the daemon composition root (`build_runtime` in `weatherbot/scheduler/wiring.py`, before any job/heartbeat/gate) and at the two CLI entrypoints that touch the store on a fresh install (send-now path and the `status` read path in `cli.py`). Also updated the shared `tmp_db` test fixture to bootstrap the schema, mirroring the new contract.
- **Files modified:** weatherbot/scheduler/wiring.py, weatherbot/cli.py, tests/conftest.py
- **Verification:** Full suite green (815 passed, exit 0); store suite 30/30 green.
- **Committed in:** `93227f3` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** The startup-wiring fix is a correctness requirement implied by the plan's own schema-ownership refactor (RESEARCH §Pattern 5 D-07: "startup guarantees the schema exists"). No scope creep — it completes the refactor rather than extending it.

## Issues Encountered
- The contract change surfaced 25 pre-existing store tests (and the shared `tmp_db` fixture) that relied on create-on-connect. Resolved by bootstrapping the schema in the `tmp_db` fixture, which matches the new production startup guarantee.

## Deferred Issues
- Pre-existing ruff findings in out-of-scope files (`tests/test_golden_cli.py:33`, `tests/test_reload.py:626`, `weatherbot/scheduler/daemon.py:69,71,1418` — unused `notifier`) logged to `deferred-items.md`. Not fixed (SCOPE BOUNDARY: unrelated to this task's changes). Full pytest suite is green; these are lint-only.

## User Setup Required

**Deferred Gate-2 (milestone-close) obligation on the live systemd host.** The WAL journal-mode switch applies to the live `data/weatherbot.db` on host `yahir-mint`. A clean daemon restart is required to apply it (the daemon reconnects → `init_db` runs `PRAGMA journal_mode=WAL` persistently). This is NOT an autonomous step:
- After deploy: `sudo systemctl restart weatherbot`
- Confirm `PRAGMA journal_mode` returns `'wal'` on the live DB
- Confirm `-wal` / `-shm` sidecars appear next to the DB

## Next Phase Readiness
- The store is de-risked: WAL + non-blocking reads remove the post-delivery lock contention that makes F01 reachable. Plan 02's atomicity/bookkeeping fix (F01) now lands on a hardened store.
- No blockers for 31-02.

## Self-Check: PASSED

All modified files exist on disk; all three task commits (`c04493f`, `9f25988`, `93227f3`) are present in git history.

---
*Phase: 31-send-atomicity-exactly-once-persistence-robustness*
*Completed: 2026-07-10*
