---
phase: 05-deployment-reboot-survival
plan: 01
subsystem: infra
tags: [systemd, sd_notify, sqlite, self-check, httpx, structlog, pytest, tdd]

# Dependency graph
requires:
  - phase: 04-reliability
    provides: is_transient / is_auth_failure classifiers + single-row heartbeat (stamp_tick) + INSERT OR IGNORE store idioms
  - phase: 02-config-fetch
    provides: do_check validate+probe (config + template + ONE One Call reachability probe, 401/403 wording)
provides:
  - "weatherbot/ops/ package (sdnotify + selfcheck) — the Phase-5 foundation the daemon gate (05-02) wires together"
  - "SystemdNotifier.ready() — pure-stdlib READY=1 sd_notify (no-op when NOTIFY_SOCKET unset), zero new deps"
  - "run_self_check + CheckResult + reason constants (online / network_not_ready / auth_failed)"
  - "single-row health table + stamp_health upsert in store.py (D-08 durable status row)"
  - "do_check refactored to delegate validate+probe to the shared self-check engine (D-03)"
affects: [05-02, daemon-gate, online-signal, status-reader]

# Tech tracking
tech-stack:
  added: []  # ZERO new dependencies — pure stdlib socket/os + already-audited deps
  patterns:
    - "Classified self-check result (CheckResult dataclass + reason constants) shared by --check and the daemon"
    - "Pure-stdlib sd_notify (best-effort, never-raise OSError) instead of the rejected sdnotify/systemd-python packages"
    - "Cycle-free ops package: imports neither cli nor daemon at module level; build_client imported lazily in-function"

key-files:
  created:
    - weatherbot/ops/__init__.py
    - weatherbot/ops/sdnotify.py
    - weatherbot/ops/selfcheck.py
    - tests/test_sdnotify.py
    - tests/test_ops_selfcheck.py
  modified:
    - weatherbot/weather/store.py
    - weatherbot/cli.py
    - tests/test_store.py

key-decisions:
  - "401/403 folded into a single auth_failed reason (no distinct key_propagating) — one probe cannot tell propagating-vs-bad apart; the daemon re-probe loop recovers a propagating key (D-06)"
  - "build_client imported LAZILY inside run_self_check (only on the no-injected-client path) to keep weatherbot.ops import-cycle-free"
  - "do_check delegates validate+probe to run_self_check but keeps its own surface: 401/403 wording, deliver-nothing guard, retry-budget echo (D-03/D-09)"

patterns-established:
  - "CheckResult(ok, reason, detail) classified outcome; detail is outcome-only (status code / class name), never a secret (T-04-01)"
  - "Single-row health table mirrors heartbeat (CHECK id=1 + INSERT OR IGNORE seed + parameterized UPDATE ... WHERE id=1)"

requirements-completed: [OPS-02]

# Metrics
duration: 4min
completed: 2026-06-12
---

# Phase 5 Plan 01: Self-check foundation + sd_notify + health row Summary

**Classified `run_self_check` engine (online / network_not_ready / auth_failed) extracted from `do_check`, a pure-stdlib `SystemdNotifier.ready()` READY=1 helper with zero new deps, and an additive single-row `health` table — the three Phase-5 foundation pieces the daemon gate (05-02) will wire together.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-12T03:22:16Z
- **Completed:** 2026-06-12T03:25:58Z
- **Tasks:** 3
- **Files modified:** 8 (5 created, 3 modified)

## Accomplishments
- Additive single-row `health` table (`CHECK id=1`) + `stamp_health` upsert in `store.py`, parameterized + no-secret (D-08)
- Pure-stdlib `SystemdNotifier` (READY=1 AF_UNIX datagram, no-op when `NOTIFY_SOCKET` unset, swallows OSError) — no new dependency
- Classified `run_self_check` + `CheckResult` reusing the Phase-4 `is_auth_failure`/`is_transient` classifiers
- `do_check` refactored to delegate the validate+probe to the shared engine while keeping its `--check` surface unchanged (D-03)
- Full suite green: 181 tests pass; ruff clean

## Task Commits

Each task was committed atomically (test + implementation together per TDD cycle):

1. **Task 1: health table + stamp_health** - `0d0ff80` (feat)
2. **Task 2: pure-stdlib sd_notify helper** - `7a81fdb` (feat)
3. **Task 3: classified self-check engine + do_check refactor** - `8d74112` (feat)

## Files Created/Modified
- `weatherbot/ops/__init__.py` - Ops package re-export surface (SystemdNotifier + run_self_check/CheckResult + reason constants)
- `weatherbot/ops/sdnotify.py` - SystemdNotifier: stdlib READY=1/WATCHDOG=1 datagram, no-op when unset, best-effort never-raise
- `weatherbot/ops/selfcheck.py` - run_self_check + CheckResult + PASS/NETWORK_NOT_READY/AUTH_FAILED; cycle-free
- `weatherbot/weather/store.py` - Added health table to `_SCHEMA` + `stamp_health` single-row upsert helper
- `weatherbot/cli.py` - `do_check` now delegates validate+probe to `run_self_check`; dropped unused `assert_unique_names` import
- `tests/test_store.py` - health single-row upsert + no-secret tests
- `tests/test_sdnotify.py` - READY=1 received / no-op-when-unset / no-raise-on-bad-socket
- `tests/test_ops_selfcheck.py` - classified outcomes (online / network_not_ready / auth_failed for 401/403/429/5xx/transient)

## Decisions Made
- Folded 401/403 into a single `auth_failed` reason (no distinct `key_propagating`) — a single probe can't distinguish propagating-vs-bad; the daemon re-probe loop (05-02) recovers a propagating key (D-06).
- `build_client` imported lazily inside `run_self_check` (only when no client is injected) to keep `weatherbot.ops` import-cycle-free — `selfcheck.py` imports neither `cli` nor `daemon` at module level.
- `do_check` keeps its own surface (401/403 subscription-not-active wording, deliver-nothing guard, retry-budget echo) and only delegates the validate+probe (D-03/D-09).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed now-unused `assert_unique_names` import from cli.py**
- **Found during:** Task 3 (do_check refactor)
- **Issue:** After delegating the validate+probe to `run_self_check`, `do_check` no longer calls `assert_unique_names` (it now lives in selfcheck.py), leaving an unused import that ruff flags as F401.
- **Fix:** Dropped `assert_unique_names` from the `weatherbot.config` import block in cli.py (still imported/used inside selfcheck.py).
- **Files modified:** weatherbot/cli.py
- **Verification:** `uv run ruff check weatherbot/cli.py` → All checks passed; full suite green.
- **Committed in:** 8d74112 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking lint/import cleanup)
**Impact on plan:** Trivial import hygiene forced by the planned refactor. No scope creep — the helper moved to selfcheck.py as designed.

## Issues Encountered
None — all three TDD cycles went RED → GREEN cleanly on the first implementation; no REFACTOR commits needed.

## TDD Gate Compliance
This is a `type: execute` plan with three `tdd="true"` tasks (not a plan-level `type: tdd`). Each task followed RED (failing test written first, confirmed failing via ImportError/assertion) → GREEN (minimal implementation, test passes). Tests and implementation were committed together per task per the sequential-executor convention; RED was verified in-session before each implementation.

## User Setup Required
None — no external service configuration required. The systemd unit + `EnvironmentFile=.env` deploy steps land in Plan 05-02 / the deploy notes; this plan is pure in-process foundation with zero new dependencies and no install step.

## Next Phase Readiness
- Plan 05-02 (daemon gate) can now wire `run_self_check` into a SIGTERM-interruptible re-probe loop in `run_daemon`, call `stamp_health` on every probe outcome, and fire the once-only online signal (`stamp_health(reason="online")` + `stamp_tick` + structured log + `SystemdNotifier.ready()` + one-time Discord ping).
- All three foundation pieces are independently tested and import-cycle-free.
- No blockers.

## Self-Check: PASSED
- FOUND: weatherbot/ops/__init__.py
- FOUND: weatherbot/ops/sdnotify.py
- FOUND: weatherbot/ops/selfcheck.py
- FOUND: tests/test_sdnotify.py
- FOUND: tests/test_ops_selfcheck.py
- FOUND commit: 0d0ff80 (Task 1)
- FOUND commit: 7a81fdb (Task 2)
- FOUND commit: 8d74112 (Task 3)

---
*Phase: 05-deployment-reboot-survival*
*Completed: 2026-06-12*
