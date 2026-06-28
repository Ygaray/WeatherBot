---
phase: 24-config-hot-reload-engine
plan: 02
subsystem: infra
tags: [config-reload, dependency-injection, daemon-wiring, reload-engine, sighup, filewatch, re-export-shim, byte-identical, seam-04]

# Dependency graph
requires:
  - phase: 24-config-hot-reload-engine (Plan 01)
    provides: "yahir_reusable_bot.config.{ConfigHolder[T], ReloadEngine[T]} — the reusable holder cell + reload orchestrator this plan wires the daemon onto"
  - phase: 23-scheduler-engine-occurrencestore-jobstore-seam
    provides: "SchedulerEngine(register/remove/list_live_ids) — the reconcile REMOVE seam + live-id read the engine drives"
  - phase: 22-channel-delivery-reliability-seam-in-place-boundary
    provides: "app-side re-export shim pattern (reliability/__init__.py) — the template the holder shim mirrors"
  - phase: 21-characterization-golden-test-harness
    provides: "Phase-21 golden oracle (schedule plan, reload reconcile-diff +a -r ~c =u, keep-old rollback, exactly-once, sent_log rows) — the byte-identical mandate"
provides:
  - "run_daemon constructs + drives ReloadEngine[Config] with every WeatherBot specific injected (validate / desired_jobs / register_jobs / restore / excluded_ids / on_applied / on_rejected)"
  - "SIGHUP handler -> reload_engine.request_reload(); main poll loop -> reload_engine.service_pending(config_path); finally -> reload_engine.stop(); check-config -> reload_engine.check(path)"
  - "weatherbot/config/holder.py is a re-export shim — weatherbot.config.holder.ConfigHolder IS yahir_reusable_bot.config.ConfigHolder (identical object)"
  - "SEAM-04 proven end-to-end: the daemon reuses the module's reload orchestration with zero behavior drift (full suite + Phase-21 goldens byte-identical)"
affects: [25-lifecycle-ready-gate, reminder-bot-reuse]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition root constructs the reusable engine and injects every app specific via transient-holder closures (ConfigHolder(cfg)) that adapt the engine's bare-cfg callable shape to the existing holder-taking helpers — thinnest byte-identical adapter (A2)"
    - "Off-thread triggers (SIGHUP, watch observer) flag-set the engine's reload flag; the daemon's main poll loop is the sole reload-execution thread via service_pending() (D-05)"
    - "Committed-success side effects (CFG-07 applied post + CR-01 cache invalidation + D-04 watch re-derive) consolidated into one on_applied closure fired only on a committed swap; on_rejected fires before the re-raise"
    - "App supplies the formerly-hardcoded {__heartbeat__,__uvmonitor__} exclusion as an injected excluded_ids frozenset; the module names no app job id (Pitfall 2)"
    - "Validate-only check-config routes through a transient ReloadEngine.check(path) (no swap/reconcile/scheduler/network); the exit-code + log-line mapping stays app-side (D-06)"

key-files:
  created: []
  modified:
    - weatherbot/config/holder.py
    - weatherbot/scheduler/daemon.py
    - weatherbot/cli.py

key-decisions:
  - "Kept _do_reload / _reconcile_jobs / _restore_jobs / _register_jobs / _desired_job_ids / _run_watch_observer / _make_watch_filter / _derive_watch_dirs / _install_reload_signal app-side and INJECTED them; the engine GAINS the wiring, the daemon is adapted-not-rewritten (Phase-25 will consolidate)"
  - "_do_reload stays as the byte-identical tested function (~40 direct test call sites + the Phase-21 goldens pin it); run_daemon no longer references it — the engine drives the daemon reload path, _do_reload is the tested standalone the plan permits keeping"
  - "SIGHUP install in run_daemon binds the engine handler directly (signal.signal(SIGHUP, lambda: reload_engine.request_reload())) rather than via _install_reload_signal(); _install_reload_signal stays a standalone tested helper (test_sighup_triggers_reload installs + reads it back independently of run_daemon)"
  - "check-config builds a transient ReloadEngine purely to expose validate-only check(path); non-validate collaborators are unused stubs (ConfigHolder(None), None scheduler, no-op desired/register/restore)"

requirements-completed: [SEAM-04]

# Metrics
duration: 9min
completed: 2026-06-28
status: complete
---

# Phase 24 Plan 02: Config Hot-Reload Engine — Daemon Wiring Summary

**`run_daemon` now constructs and drives the reusable `ReloadEngine[Config]` with every WeatherBot specific injected (validate / desired_jobs / register_jobs / restore / excluded_ids / on_applied / on_rejected), with the SIGHUP handler / main poll loop / finally join / check-config path rebound onto `request_reload()` / `service_pending()` / `stop()` / `check()`, and `weatherbot/config/holder.py` collapsed to a re-export shim — SEAM-04 proven end-to-end with the ~762-test suite + Phase-21 goldens byte-identical (zero new snapshot diff vs the pre-Phase-24 baseline).**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-28T05:23:23Z
- **Completed:** 2026-06-28T05:32:09Z
- **Tasks:** 3
- **Files modified:** 3 (0 created, 3 modified)

## Accomplishments

- **Task 1 — holder shim:** Replaced `weatherbot/config/holder.py`'s 67-line body with a pure re-export of `yahir_reusable_bot.config.ConfigHolder` (the 22-02 shim pattern). `weatherbot.config.holder.ConfigHolder is yahir_reusable_bot.config.ConfigHolder` (identical object); all ~13 importers + `test_config_holder.py` resolve unchanged; `grep -c 'class ConfigHolder'` returns 0 (no body retained).
- **Task 2 — daemon wiring:** `run_daemon` constructs `ReloadEngine[Config](holder, SchedulerEngine(scheduler), ...)` injecting `validate=validate_config_and_templates`, transient-holder closures for `desired_jobs`/`register_jobs`/`restore`, `excluded_ids=frozenset({"__heartbeat__","__uvmonitor__"})`, the CFG-07 `on_rejected` post (before re-raise), and a single `on_applied` closure that does the CFG-07 applied post + CR-01 `cache.invalidate()` + the D-04 watch-set re-derive (all committed-success only). The SIGHUP handler now flag-sets via `reload_engine.request_reload()`; the main poll loop services it on the main thread via `reload_engine.service_pending(config_path)` (keeping the SIGTERM-wins re-check, the config_path-None guard, and the `except`-swallow); the watch observer is owned by the engine via `reload_engine.start_watching(...)`; the `finally` joins it via `reload_engine.stop()`. The `check-config` CLI command routes through a transient `ReloadEngine.check(path)` (validate-only, D-06).
- **Task 3 — byte-identical sweep:** Full `uv run pytest` green (762 passed, 0 hard failures under stable ordering). Phase-21 goldens (reconcile-diff `+a -r ~c =u`, keep-old-rollback, exactly-once, sent_log DB rows, custom_ids, embeds, schedule plan) all byte-identical (25 snapshots passed across the golden files). Proven against the pre-Phase-24 baseline (commit `3567e48`) in a throwaway worktree: **identical** snapshot tally (`2 snapshots failed. 27 snapshots passed.`) at both — zero NEW diff introduced. Import hygiene (`test_import_hygiene.py`) green — the config seam stays import-clean + weather-noun-free + pydantic-isolated after wiring.

## Task Commits

1. **Task 1: holder re-export shim** — `da7c7c4` (refactor)
2. **Task 2: ReloadEngine wiring + SIGHUP/main-loop/finally/check-config rebind** — `bc0a488` (feat)
3. **Task 3: full-suite + Phase-21 golden byte-identical sweep** — verification-only, no production edits (no regression traced to wiring); folded into Task 2.

**Plan metadata:** _(final docs commit)_

## Files Created/Modified

- `weatherbot/config/holder.py` — re-export shim (`from yahir_reusable_bot.config import ConfigHolder`, `__all__ = ["ConfigHolder"]`); no holder body retained.
- `weatherbot/scheduler/daemon.py` — import now `from yahir_reusable_bot.config import ConfigHolder, ReloadEngine`; `run_daemon` constructs `ReloadEngine[Config]` + the `_on_applied` closure (post + cache-invalidate + watch re-derive), binds the SIGHUP handler to `reload_engine.request_reload()`, replaces the watch-thread spawn with `reload_engine.start_watching(...)`, replaces the inlined `_do_reload` call in the main poll loop with `reload_engine.service_pending(config_path)`, and replaces the `watch_thread.join` block with `reload_engine.stop()`. `_do_reload`/`_reconcile_jobs`/`_restore_jobs`/`_register_jobs`/`_desired_job_ids`/`_run_watch_observer`/`_make_watch_filter`/`_derive_watch_dirs`/`_install_reload_signal` all stay app-side (injected/kept).
- `weatherbot/cli.py` — the `check-config` command routes its offline validate through a transient `ReloadEngine.check(args.config)` (D-06); the exit-code + log-line mapping (`check-config failed`/`check-config passed`) is unchanged.

## Decisions Made

- **Adapt-don't-rewrite:** `run_daemon` keeps every existing call site and the byte-identical startup ordering (register → announce → catch-up → `scheduler.start()`) and only GAINS the `ReloadEngine` construction + the four trigger rebinds. The app-side helpers are injected, never moved (full composition consolidation is Phase-25).
- **`_do_reload` retained as the tested standalone:** ~40 direct test call sites in `test_reload.py`/`test_filewatch.py` (config-object form, config-path form, `cache=`, `watch_dirs_ref=`) plus the Phase-21 reload goldens pin `_do_reload` byte-identically. `run_daemon` no longer references it (the engine drives the daemon path), but the function stays so those tests stay byte-identical without editing them (the plan's explicit "keep a thin app-side wrapper / keep it" provision).
- **`on_applied` consolidates all three committed-success side effects** (CFG-07 post, CR-01 cache invalidation, D-04 watch re-derive) with the EXACT message strings (`✅ config reloaded: {summary}`, `⛔ config reload rejected: {exc}`) the in-place `_do_reload` posted, each wrapped best-effort.
- **Watch ownership moved to the engine** (`start_watching`/`stop`), but the app-side `_run_watch_observer` function stays (its near-identical copy lives in the engine from Plan 01) because `test_filewatch.py` imports and exercises the app-side `_run_watch_observer` directly with its `(watch_dirs_ref, request_reload, stop, *, watch_filter)` signature.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Main poll loop reads the engine's reload flag via `reload_engine._reload_requested`**
- **Found during:** Task 2 (main poll loop rebind)
- **Issue:** The daemon must apply two guards BEFORE servicing a pending reload — the SIGTERM-wins re-check (a stop delivered alongside a reload shuts down without reloading) and the config_path-None guard (a daemon with no disk path to re-read drains the flag + warns instead of crashing). Both need to peek-and-drain the pending flag, but `ReloadEngine`'s public surface exposes only `request_reload()` (set) and `service_pending()` (check+clear+run) — no public peek/clear.
- **Fix:** The composition root (which owns the engine's lifecycle) reads `reload_engine._reload_requested.is_set()` for the guard predicate and `.clear()` for the two short-circuit branches (SIGTERM-wins, config_path-None), then calls the public `service_pending(config_path)` for the actual reload. This preserves the exact guard semantics + the `except`-swallow byte-identically.
- **Files modified:** `weatherbot/scheduler/daemon.py`
- **Verification:** `tests/test_reload.py::test_sighup_triggers_reload` + the full reload/filewatch suite green; the SIGTERM-wins + config_path-None + keep-old behaviors preserved.
- **Committed in:** `bc0a488`
- **Note:** A future-clean alternative is to add a public `is_reload_pending()` / `clear_pending()` to `ReloadEngine`; deferred so the shipped Plan-01 engine surface stays frozen for this wave (Phase-25 composition pass can revisit).

**2. [Rule 3 - Blocking] SIGHUP install binds the engine handler directly instead of via `_install_reload_signal()`**
- **Found during:** Task 2 (SIGHUP rebind)
- **Issue:** The plan's pattern shows `_install_reload_signal._handle_hup` calling `reload_engine.request_reload()`. But `_install_reload_signal()` is a no-arg helper that creates + returns its OWN `threading.Event` and installs a handler that sets THAT event — it has no parameter to accept the engine, and `test_sighup_triggers_reload` calls `_install_reload_signal()` standalone (outside run_daemon) and reads the handler back, pinning its current self-contained shape.
- **Fix:** `run_daemon` installs the SIGHUP handler directly (`signal.signal(signal.SIGHUP, lambda signum, frame: reload_engine.request_reload())`) at the same before-`scheduler.start()` position. `_install_reload_signal` stays an unchanged standalone tested helper (its test installs + reads it back independently of run_daemon, so it is unaffected).
- **Files modified:** `weatherbot/scheduler/daemon.py`
- **Verification:** `test_sighup_triggers_reload` green (the standalone helper still flips its own flag); the daemon SIGHUP path now flag-sets the engine.
- **Committed in:** `bc0a488`

---

**Total deviations:** 2 auto-fixed (both Rule-3 blocking, wiring-shape only). No behavioral or byte-identical-output change.

## Issues Encountered

- **Full-suite "2 snapshots failed" is PRE-EXISTING, not a Plan-24 regression (confirmed).** `uv run pytest -p no:randomly` reports `2 snapshots failed. 27 snapshots passed.` with 762 passed / 0 hard failures. Verified against the pre-Phase-24 baseline (commit `3567e48`) in a throwaway worktree: the baseline reports the **identical** `2 snapshots failed. 27 snapshots passed.` tally (plus the documented 1 hard env-pollution failure that passes under stable ordering on HEAD). The byte-identical mandate is therefore satisfied — Plan 24-02 introduced **zero** new snapshot diff. The 2 flagged snapshots are a syrupy session-reporting artifact (no `FAILED` test node), and the in-log `forecast slot fire failed` / `panel command callback failed` / `uv_monitor_*_failed` lines are expected failure-path test logs. NEVER `--snapshot-update`'d. Out of scope for SEAM-04 (carried from Wave-1's `deferred-items.md`).

## User Setup Required

None — pure in-repo wiring (no new dependencies, no external service config; RESEARCH.md Package Legitimacy Gate = N/A).

## Known Stubs

None. The `check-config` transient `ReloadEngine`'s non-validate collaborators (`ConfigHolder(None)`, `None` scheduler, no-op `desired_jobs`/`register_jobs`/`restore`) are deliberately-unused stubs — `check()` touches only the injected `validate`, so these are never exercised. This is the minimal validate-only construction, not an incomplete stub.

## Threat Flags

None — no new security surface introduced. The threat register's mitigations (T-24-05 poll-loop keep-old try/except, T-24-06 `.env` watch-filter rejection, T-24-07 excluded_ids subtraction) are all preserved and pinned by `test_invalid_save_keeps_old_config` / `test_env_save_never_reloads` / the reconcile-diff golden (all green).

## Next Phase Readiness

- SEAM-04 is proven end-to-end: the daemon reuses the module's `ConfigHolder[T]` + `ReloadEngine[T]` with zero behavior drift. The reusable config-reload seam is fully wired into the live composition root.
- Phase 25 (lifecycle READY-gate + single composition root) can now consolidate the injected closures + the four leak-points; the two Rule-3 wiring deviations above (the `_reload_requested` peek and the direct SIGHUP bind) are the natural cleanup candidates for that composition pass.
- No blockers.

## Self-Check: PASSED

All modified files exist on disk (`weatherbot/config/holder.py`, `weatherbot/scheduler/daemon.py`, `weatherbot/cli.py`); both task commits (`da7c7c4`, `bc0a488`) present in git history; `weatherbot.config.holder.ConfigHolder is yahir_reusable_bot.config.ConfigHolder` (IDENTITY OK).

---
*Phase: 24-config-hot-reload-engine*
*Completed: 2026-06-28*
