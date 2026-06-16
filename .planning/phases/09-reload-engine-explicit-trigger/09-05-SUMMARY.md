---
phase: 9
plan: 05
subsystem: scheduler
tags: [reload, sighup, apscheduler, config-holder, exactly-once, daemon]
requires:
  - "weatherbot/config/loader.py::validate_config_and_templates (Plan 02 — shared offline validator)"
  - "weatherbot/config/holder.py::ConfigHolder (Phase 8 — lock-free read / locked swap)"
  - "weatherbot/ops/pidfile.py::write_pid_atomic + PID_FILE (Plan 03)"
  - "weatherbot/weather/store.py::claim_slot keyed on location.id (Plan 04 — stable-id idempotency)"
provides:
  - "weatherbot/scheduler/daemon.py::_do_reload (two-phase build-then-commit reload engine)"
  - "weatherbot/scheduler/daemon.py::_reconcile_jobs (stable-id diff-reconcile)"
  - "weatherbot/scheduler/daemon.py::_restore_jobs (rebuild-from-old_cfg rollback)"
  - "weatherbot/scheduler/daemon.py::_install_reload_signal (flag-set-only SIGHUP handler)"
  - "weatherbot/scheduler/daemon.py::run_daemon poll loop + PID write/unlink + config_path param"
  - "weatherbot/cli.py run dispatch threads config_path=args.config"
affects:
  - "Phase 10 (watchfiles auto-reload) — will trigger _do_reload via file-watch instead of SIGHUP"
  - "Phase 11 (Discord inbound reload confirm) — will surface the +a -r ~c =u summary to the operator"
tech-stack:
  added: []
  patterns:
    - "Two-phase build-then-commit: validate-or-keep-old (PHASE 1), atomic swap + diff-reconcile with all-or-nothing rollback (PHASE 2)"
    - "Signal handler is flag-set-only; reload work runs on the main thread via a poll loop (Pitfall 6)"
    - "Job diff-reconcile on the stable name|time|days id (add_job replace_existing / remove_job); never a wholesale clear"
key-files:
  created: []
  modified:
    - "weatherbot/scheduler/daemon.py"
    - "weatherbot/cli.py"
    - "tests/conftest.py"
    - "tests/test_scheduler.py"
decisions:
  - "[09-05] Poll loop parks on stop.wait(timeout=1.0) (not reload_requested.wait): SIGTERM wins natively (a set stop returns True and exits at once) and each ~1s tick services reload_requested.is_set() on the main thread — cleaner than parking on the reload flag and keeps the existing Event-mocking startup tests green."
  - "[09-05] Reconcile ADD phase delegates to the canonical _register_jobs (replace_existing=True) so the rollback test's monkeypatch of _register_jobs exercises the real commit-phase throw; the REMOVE phase deletes dropped live ids — adds run BEFORE removes so a throw leaves the old job set untouched."
  - "[09-05] Reload outcome lines are mirrored through a stdlib logger (_stdlog) in addition to structlog: the project's structlog default renders to STDERR via PrintLoggerFactory and never routes through stdlib logging, so the operator's journal pipeline (and pytest caplog) can grep the +a -r ~c =u summary / rejection reason."
  - "[09-05] A bad live reload (validation reject or reconcile throw) is caught in the poll loop and logged — it must NOT crash the always-on daemon; _do_reload already kept-old / rolled back, so the live schedule is intact (CFG-04 end-to-end)."
metrics:
  duration: "~14 min"
  completed: "2026-06-16"
  tasks: 2
  files: 4
  tests_added_green: 11
  full_suite: "248 passed"
---

# Phase 9 Plan 05: Reload Engine + Explicit Trigger Summary

Built the daemon hot-reload engine — a two-phase (validate-or-keep-old → atomic swap + diff-reconcile with all-or-nothing rollback) `_do_reload`, a flag-set-only SIGHUP handler serviced by a main-thread poll loop, and the PID-file + `config_path` lifecycle wiring — turning the last 10 RED Phase-9 reload tests green with the full suite at 248 passed.

## What Was Built

### Task 1 — `_reconcile_jobs` + `_restore_jobs` + `_do_reload` (CFG-04/05/06)
- **`_do_reload(config=None, *, config_path=None, holder, scheduler, db_path, settings=None, client=None, channel=None, stop_event=None)`** — two-phase commit:
  - **PHASE 1 (validate-or-keep-old):** when `config_path` is given, re-reads + validates via the shared `validate_config_and_templates`; on any `FileNotFoundError`/`tomllib.TOMLDecodeError`/`ValidationError`/`ValueError` it logs the reason and **re-raises with holder + jobs untouched**. A pre-validated `config` object (in-process/test callers) skips PHASE 1.
  - **PHASE 2 (atomic swap + diff-reconcile):** snapshots `old_cfg`, `holder.replace(new_cfg)`, runs `_reconcile_jobs`; on any reconcile throw rolls back all-or-nothing (`holder.replace(old_cfg)` + `_restore_jobs`) and re-raises.
  - On success logs the `+a -r ~c =u` summary; touches **no Settings and never the systemd READY gate / .env** (D-04 / Pitfall 12).
- **`_reconcile_jobs`** — diffs the desired enabled-slot id set (`_desired_job_ids`) against live ids (excluding `__heartbeat__`); the ADD/replace phase delegates to `_register_jobs(..., replace_existing=True)`, the REMOVE phase deletes dropped live ids. A `send_time`/`days` change is a different id → one add + one remove (fires today if ahead; **not** suppressed). Returns `(added, removed, changed, unchanged)`.
- **`_restore_jobs`** — deterministically rebuilds the old job set by reconciling a transient `ConfigHolder(old_cfg)` (rollback, Pitfall 7).
- `_register_jobs` gained an optional `replace_existing=False` param so the reconcile's idempotent re-register doesn't raise `ConflictingIdError`.

### Task 2 — SIGHUP handler + poll loop + PID lifecycle + `config_path` thread (CFG-01/02; SC#4)
- **`_install_reload_signal()`** — installs a flag-set-only SIGHUP handler (`reload_requested.set()` and nothing else, Pitfall 6) and returns the `threading.Event`; unit-testable standalone.
- **`run_daemon` poll loop** — the single `stop.wait()` park became `while not stop.wait(timeout=1.0):` (SIGTERM wins natively); each ~1s tick services `reload_requested.is_set()`, clears it, re-checks `stop.is_set()` first, then runs `_do_reload(config_path=...)` on the main thread. A bad reload is caught and logged, never crashing the daemon.
- **PID lifecycle** — `write_pid_atomic(PID_FILE)` at startup, `PID_FILE.unlink(missing_ok=True)` in the existing `finally`. `PID_FILE`/`write_pid_atomic` imported at module level so tests can redirect off the host `/run`.
- **`config_path`** — new optional `run_daemon` param; `cli.py` run dispatch passes `config_path=args.config`.

## Verification

- `tests/test_reload.py` — all 11 reload tests green (10 from Task 1's targeted set + the SIGHUP/end-to-end set), including the load-bearing SC#4 `test_already_sent_slot_not_refired_after_tz_name_change` (name/tz exactly-once) and `test_send_time_change_is_new_slot_fires_today_if_ahead`.
- `tests/test_scheduler.py` — all green (dispatch stub + Event-mocking startup tests).
- **Full suite: `248 passed`** (≥ 226 baseline + new Phase 9 tests), zero RED remaining.
- Acceptance greps: three engine functions present; `validate_config_and_templates(config_path` inside the keep-old try; `replace_existing=True` present; `remove_all_jobs` count = 0; `__heartbeat__` excluded in reconcile; no same-day suppression guard; rollback restores old cfg + jobs; READY/.env untouched in the engine body; `config_path=args.config` in cli.
- `ruff check` clean on all modified files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reconcile ADD phase routed through `_register_jobs` (not a standalone add_job loop)**
- **Found during:** Task 1
- **Issue:** `test_reconcile_failure_rolls_back` monkeypatches `daemon_mod._register_jobs` to raise and expects the rollback path to fire. An independent `add_job` loop inside `_reconcile_jobs` would never hit that injection point, so the rollback would not be exercised.
- **Fix:** `_reconcile_jobs` delegates its ADD/replace phase to `_register_jobs(..., replace_existing=True)` (which required adding the `replace_existing` param to `_register_jobs`). Adds run before removes, so a throw in the add phase leaves the old job set intact; `_do_reload`'s rollback wraps `_restore_jobs` defensively so a restore failure never masks the original error.
- **Files modified:** `weatherbot/scheduler/daemon.py`
- **Commit:** dab34dd

**2. [Rule 1 - Bug] Reload outcome logs were invisible to the operator journal / pytest caplog**
- **Found during:** Task 1 (`test_reload_logs_diff_summary`, `test_rejected_reload_logs_reason`)
- **Issue:** The project's structlog default (`weatherbot/__init__.py`) renders to STDERR via `PrintLoggerFactory` and does **not** route through stdlib `logging`, so the `+a -r ~c =u` summary / rejection reason never reached `caplog` (and would not reach a journald/stdlib-logging pipeline either).
- **Fix:** Mirror the three reload outcome lines through a module-level stdlib `logging.getLogger(__name__)` (`_stdlog`) in addition to structlog. Outcome-only (counts + validation reason), never a secret (T-04-01 / T-09-08).
- **Files modified:** `weatherbot/scheduler/daemon.py`
- **Commit:** dab34dd

**3. [Rule 3 - Blocking] PID write to `/run` is not writable in the test sandbox**
- **Found during:** Task 2 (6 real `run_daemon` tests in `test_scheduler.py` failed with `PermissionError`)
- **Issue:** New startup `write_pid_atomic(PID_FILE)` writes `/run/weatherbot.pid`, which the test/CI environment cannot write.
- **Fix:** Imported `PID_FILE`/`write_pid_atomic` at the daemon module level (patchable) and added an **autouse** conftest fixture `_redirect_pid_file` that points `daemon.PID_FILE` at a per-test tmp path. The production default in `pidfile.py` is unchanged. This is a single test-infra change rather than editing six tests.
- **Files modified:** `tests/conftest.py`, `weatherbot/scheduler/daemon.py`
- **Commit:** 52984a6

**4. [Rule 3 - Blocking] Poll-loop redesign + dispatch-stub signature broke existing Event-mocking tests**
- **Found during:** Task 2
- **Issue:** (a) The plan's suggested `reload_requested.wait()` park infinite-looped under the existing `_NeverSetImmediateWait`/`_StopDuringWait` fakes (which lack `.clear()` and whose `wait()` returns True). (b) `test_run_flag_dispatches_to_daemon`'s `_stub_run_daemon` did not accept the new `config_path` kwarg the cli now passes.
- **Fix:** (a) Parked the loop on `stop.wait(timeout=1.0)` (SIGTERM wins natively, the existing fakes exit the loop exactly as the old `stop.wait()` park did) and service `reload_requested.is_set()` per tick. (b) Updated the dispatch stub to accept and assert `config_path == str(cfg_path)`, strengthening the test.
- **Files modified:** `weatherbot/scheduler/daemon.py`, `tests/test_scheduler.py`
- **Commit:** 52984a6

## Threat Surface

No new threat surface beyond the plan's `<threat_model>`. The reload path constructs no `Settings`, never calls the systemd notifier/READY, never deletes `sent_log` rows, and the SIGHUP receiver runs flag-set-only with the reload on the main thread — all per the existing T-09-* register. Outcome logging carries counts + the validation reason only (no secrets).

## Known Stubs

None. `changed` is always 0 in the diff tuple by design (content edits ride the holder swap rather than producing a same-id trigger delta in this codebase) — documented in `_reconcile_jobs`, part of the diff-summary contract, not a stub.

## Self-Check: PASSED

- `weatherbot/scheduler/daemon.py` — FOUND; `_do_reload`/`_reconcile_jobs`/`_restore_jobs`/`_install_reload_signal` all present.
- `weatherbot/cli.py` — FOUND; `config_path=args.config` in run dispatch.
- Commit dab34dd (Task 1) — FOUND in git log.
- Commit 52984a6 (Task 2) — FOUND in git log.
- Full suite: 248 passed, 0 failed.
