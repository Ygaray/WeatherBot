---
phase: 35-cleanup-sweep
plan: 08
subsystem: scheduler
tags: [dead-code-removal, daemon, reload-engine, latent-findings, accept-with-rationale]

# Dependency graph
requires:
  - phase: 35-01
    provides: "Wave-0 dead-code drift-back gate (test_dead_code_removed.py) pinning F16 absence"
provides:
  - "F16 dead code removed: emit_online + _do_reload twins gone from scheduler/daemon.py"
  - "Orphaned _do_reload/emit_online tests removed; SC#4 exactly-once + idempotence tests migrated onto the LIVE _reconcile_jobs seam"
  - "Daemon-cluster latent findings accepted-annotated: F103-live, F56, F57 (daemon.py); F52, F53 (wiring.py); F88 cheap-fixed (context.py)"
affects: [35-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dead-twin removal gated on a green full suite (a red suite after removal = the symbol was live = revert)"
    - "Test migration off a removed twin onto the live seam it delegated to (rather than blanket deletion) when the assertion survives"
    - "# ACCEPTED (F##, v2.1): <rationale> in-code marker for accept-with-rationale latent findings"

key-files:
  created: []
  modified:
    - "weatherbot/scheduler/daemon.py (removed emit_online + _do_reload defs + orphaned imports; F103/F56/F57 annotations; stale comment cleanup)"
    - "weatherbot/scheduler/wiring.py (F52 + F53 annotations)"
    - "weatherbot/scheduler/context.py (F88 cheap PRESERVE fix — assert dt.tzinfo)"
    - "weatherbot/scheduler/uvmonitor.py (stale _do_reload docstring ref cleaned)"
    - "tests/test_reload.py (removed _do_reload-exclusive reload-engine tests; migrated SC#4 tests onto _reconcile_jobs)"
    - "tests/test_filewatch.py (migrated the two _do_reload tests onto the live validator/_reconcile_jobs seam)"
    - "tests/test_scheduler.py (cleaned stale emit_online comment refs — live tests, not removed)"

key-decisions:
  - "F16 confirmed dead (Open-Q1): live online-ping is inlined in run_daemon; live reload is hub reload_engine.service_pending() — both twins had ZERO runtime callers."
  - "Migrated (not deleted) the two SC#4 exactly-once tests + the two filewatch reload tests onto the LIVE _reconcile_jobs / validate_config_and_templates seams — their assertions survive without the dead twin (D-05 keep-if-survives)."
  - "F88 took the cheap PRESERVE fix (assert dt.tzinfo is not None) over accept-annotate — no test perturbed, and it makes a future naive-dt regression fail LOUD instead of mis-rendering."
  - "F53 verified STILL in the hub's best-effort-swallowed on_online hook (ready_gate.py:96 best_effort then ready()) — annotated accept (unreachable single-drive; ordering preserved), ledger disposition lands in 35-09."

patterns-established:
  - "Re-export F401 discipline: symbols kept only for daemon.* attr access from wiring carry a # noqa: F401 re-export marker (SystemdNotifier, stamp_health)."
---

# Phase 35 Plan 08: Daemon-Cluster Cleanup Sweep Summary

Removed the dead `emit_online`/`_do_reload` twins from `scheduler/daemon.py` (F16 — Open-Q1 traced-and-confirmed-dead), pruned/migrated their orphaned tests, and accept-annotated every surviving daemon/wiring/context latent finding (F103-live, F56, F57, F52, F53, F88) — full suite green at 876, F16 revert-gate honored.

## What Was Built

**Task 1 — F16 dead-code removal + orphaned-test handling (commit 6b45e55):**
- Deleted the `_do_reload` (two-phase reload) and `emit_online` (online-signal) function defs from `daemon.py`. Confirmed dead via `grep`: only the two defs + stale comments, zero runtime callers. The live online ping is inlined in `run_daemon` (post-READY); the live reload routes through the hub `reload_engine.service_pending()`.
- Removed the now-orphaned imports the twins exclusively used: `import tomllib`, `from pydantic import ValidationError`, `from weatherbot.config.loader import validate_config_and_templates`.
- Kept `SystemdNotifier` and `stamp_health` (live via `daemon.*` attribute access from `wiring.py`) with `# noqa: F401` re-export markers.
- Cleaned/corrected every stale comment/docstring reference to the removed symbols in `daemon.py` and `uvmonitor.py` (no reference to a removed symbol remains in `daemon.py`).
- Test handling per D-05:
  - Removed the `_do_reload`-exclusive reload-engine tests in `test_reload.py` (rollback / diff / keep-old / CFG-07 posts / cache-invalidate) — all independently covered by `test_reload_engine.py`.
  - **Migrated** the two load-bearing SC#4 exactly-once tests (`test_already_sent_slot_not_refired_after_tz_name_change`, `test_send_time_change_is_new_slot_fires_today_if_ahead`) onto the LIVE `_reconcile_jobs` commit-half (`_apply_reload` helper: `holder.replace` + `_reconcile_jobs`) — their claim/sent-log assertions survive without the twin.
  - **Migrated** the two `test_filewatch.py` reload tests: `test_invalid_save_keeps_old_config` now drives the live `validate_config_and_templates` gate; `test_identical_save_zero_job_changes` now drives `holder.replace` + `_reconcile_jobs`.
  - Kept all SIGHUP-flag / CLI-reload / pidfile-guard / streak-prune / observer tests.
  - Cleaned stale `emit_online` comment refs in `test_scheduler.py` (its two mentions were docstring-only; the tests exercise the live `run_daemon` path and stay).

**Task 2 — accept-annotate daemon-cluster latent findings (commit ade8add):**
- **F103** (`daemon.py` inlined online-ping `getattr(send_result,"ok",True)`): `# ACCEPTED` — over-guard masks a None-on-failure channel; a single missed WARNING on a best-effort ping.
- **F56** (`daemon.py` `fire_slot` pre-`local_date` arm): `# ACCEPTED` — a raise before `local_date` is computed (invalid tz → ValueError) is unreachable given config-validated tz; the guard exists to avoid an unbound-name delete, not to alert.
- **F57** (`daemon.py` heartbeat cadence vs retry-pause): `# ACCEPTED` — not reachable at 2-slot scale; `misfire_grace_time=None` delays (not skips) the tick, preserving `last_tick` freshness.
- **F52** (`wiring.py` transient `ConfigHolder` in reload closures): `# ACCEPTED` — identity-divergence smell only; read-once, never escapes the closure (downgraded from medium).
- **F53** (`wiring.py` `scheduler.start()` in best-effort `on_online` hook): verified STILL inside the hub's swallowed hook (`ready_gate.py:96` `_best_effort_hook(on_online)` then `notifier.ready()`); `# ACCEPTED` — unreachable on the single-drive path, READY-after-start ordering preserved.
- **F88** (`context.py` `_fmt` naive-dt `astimezone`): cheap PRESERVE fix — `assert dt.tzinfo is not None` — no test perturbed; makes a future naive-dt regression fail loud instead of silently mis-rendering a briefing time.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Re-export markers for SystemdNotifier / stamp_health**
- **Found during:** Task 1 (ruff check after removing the twins)
- **Issue:** After deleting `emit_online`, `SystemdNotifier` and `stamp_health` became locally-unused imports (ruff F401), but they are LIVE re-exports accessed as `daemon.SystemdNotifier` / `daemon.stamp_health` from `wiring.py`. Removing them would break the runtime.
- **Fix:** Added `# noqa: F401` re-export markers (matching the existing `AUTH_FAILED`/`run_self_check` pattern on the same imports) rather than deleting them.
- **Files modified:** weatherbot/scheduler/daemon.py
- **Commit:** 6b45e55

**2. [D-05 refinement] Migrated rather than deleted 4 tests**
- **Found during:** Task 1
- **Issue:** The two SC#4 exactly-once tests and the two filewatch reload tests assert behavior that survives without the dead twin (the exactly-once claim/sent-log path + the live validator), so blanket deletion would drop live coverage.
- **Fix:** Migrated them onto the live `_reconcile_jobs` / `validate_config_and_templates` seams (the exact seams the hub reload engine delegates to). Deleted only the tests whose assertion was exclusively about the removed engine (covered by `test_reload_engine.py`).
- **Files modified:** tests/test_reload.py, tests/test_filewatch.py
- **Commit:** 6b45e55

## Out-of-Scope Findings (NOT fixed — pre-existing)

- `daemon.py` ruff F401 (`ReloadEngine`, `PID_FILE`) and F841 (`notifier`): all three exist on HEAD before this plan (verified against `git show HEAD:...`) — pre-existing, left untouched (scope boundary).
- `test_reload.py` E731 (`reader = lambda ...`) in `test_is_weatherbot_pid_delegates_byte_identically...`: pre-existing in a kept test — left untouched.

## Known Stubs

None — this plan removes dead code and annotates findings; no stubs introduced.

## Verification

- `uv run pytest -q` → **876 passed**, exit 0 (the "2 snapshots failed" line is the known syrupy quirk per project memory — exit code trusted).
- `tests/test_reload_engine.py` → 10 passed (live reload behavior intact).
- `tests/test_dead_code_removed.py` → 4 passed (F16 absence enforced by the Wave-0 gate).
- `grep -cE 'def emit_online\(|def _do_reload\(' weatherbot/scheduler/daemon.py` → 0.
- `! grep -qE 'emit_online|_do_reload' weatherbot/scheduler/daemon.py` → PASS (no stale reference).
- Every surviving latent finding carries its `# ACCEPTED (F##, v2.1)` marker (F88 the cheap-fix assert).
- `git diff --name-only` → no `yahir_reusable_bot/` or `../Reusable/` file (hub untouched).

## Commits

- 6b45e55 — refactor(35-08): remove dead emit_online/_do_reload twins + orphaned tests (F16)
- ade8add — docs(35-08): accept-annotate daemon/wiring/context latent findings (F103,F56,F57,F52,F53,F88)

## Self-Check: PASSED

- FOUND: .planning/phases/35-cleanup-sweep/35-08-SUMMARY.md
- FOUND: commit 6b45e55
- FOUND: commit ade8add
