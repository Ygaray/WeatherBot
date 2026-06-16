---
phase: 10-file-watch-auto-reload
plan: 01
subsystem: testing
tags: [nyquist, wave-0, red-scaffold, file-watch, watchfiles, reload]
requirements-completed: [CFG-03]
requires:
  - "weatherbot.scheduler.daemon._install_reload_signal (Phase 9 — referenced for the toggle-independence assertion)"
  - "weatherbot.scheduler.daemon._do_reload / _register_jobs (Phase 9 — real keep-old path for SC#4 + idempotence)"
  - "weatherbot.config.holder.ConfigHolder (Phase 8 — current()/replace())"
  - "tests/conftest.py::holder_scheduler (existing reload-test harness)"
provides:
  - "tests/test_filewatch.py — executable RED contract for the file-watch observer (8 nodes)"
  - "Local editor-save helpers truncate_write / temp_then_rename / multi_event_burst"
  - "Per-test deferred-import wrappers _run_watch_observer / _derive_watch_dirs / _make_watch_filter"
affects:
  - "Plans 10-02 / 10-03 — must implement the referenced observer symbols + Config.reload.watch to turn this file green"
tech-stack:
  added: []
  patterns:
    - "Wave-0 deferred-import RED scaffold (per-test lazy imports so all node IDs COLLECT while RED)"
    - "Dependency-free /proc/<pid>/fd fd-stability soak (no psutil)"
key-files:
  created:
    - tests/test_filewatch.py
  modified: []
decisions:
  - "SC#2 is ONE node iterating the three editor-save patterns internally (not parametrized) to hit the plan's exactly-8-node-IDs contract"
  - "Removed the mirrored ConfigHolder import from test_reload.py — genuinely unused here, ruff-clean over verbatim mirroring"
metrics:
  duration: "~9 min"
  completed: "2026-06-16"
  tasks: 1
  files: 1
---

# Phase 10 Plan 01: File-Watch RED Scaffold Summary

Wave-0 Nyquist RED scaffold `tests/test_filewatch.py` — eight executable, currently-RED file-watch contract nodes (SC#1-4 + idempotence + toggle + `.env`-filter + watch-set re-derive) that Plans 10-02/10-03 turn green, referencing the not-yet-built observer symbols through per-test deferred imports so all node IDs COLLECT.

## What Was Built

`tests/test_filewatch.py` (527 lines) with eight node IDs, each mapped to a Test-Map behavior:

| Node | SC / driver |
|------|-------------|
| `test_save_triggers_reload` | SC#1 — save → `request_reload` fires |
| `test_editor_save_patterns_one_reload` | SC#2 — truncate-write / temp-then-rename / multi-event burst each → exactly ONE reload |
| `test_fd_stable_and_clean_teardown` | SC#3 — fd delta within `FD_SLACK` across ≥50 inode-swapping saves incl. a watch-set-changing reload (A4); clean SIGTERM join |
| `test_invalid_save_keeps_old_config` | SC#4 — keep-old THROUGH the file-watch trigger, real `_do_reload`/`holder` |
| `test_identical_save_zero_job_changes` | idempotence — `+0 -0 ~0 =N` via real `_register_jobs`/`_do_reload` |
| `test_watch_toggle_off_no_observer` | D-03 — `Config.reload.watch` field + SIGHUP independence |
| `test_env_save_never_reloads` | Pitfall #12 — `.env` edit → ZERO reloads |
| `test_watch_set_rederived_on_reload` | D-04 — config dir + `TEMPLATES_DIR` derived from live config |

Supporting helpers in-file: deferred-import wrappers `_run_watch_observer` / `_derive_watch_dirs` / `_make_watch_filter`; editor-save helpers `truncate_write` / `temp_then_rename` / `multi_event_burst`; the `_fd_count()` `/proc/<pid>/fd` probe; the `FD_SLACK = 4` named tolerance; and the local `_loc`/`_cfg`/`_slot` builders mirrored from `test_reload.py`.

## How It Works

- Every reference to a Plan-10-02/03 symbol lives INSIDE a per-test deferred-import wrapper body (no module-top `from weatherbot.scheduler.daemon import _run_watch_observer`), so collection never crashes and all eight node IDs surface RED individually.
- SC#1/SC#2/idempotence/.env use a `Mock`/counter `request_reload` seam so they assert the trigger fires WITHOUT standing up `_do_reload`. SC#4 and idempotence wire the REAL `_do_reload`/`holder` keep-old path (T-09-01: no green-but-hollow mock).
- SC#3 counts fds via the dependency-free, Linux-only `len(os.listdir(f"/proc/{os.getpid()}/fd"))` (psutil is NOT imported), asserts the delta is within `FD_SLACK` (NOT `== 0`) sampled after a `stop`-bounded settle window, and includes a watch-set swap mid-soak (A4). All bounded waits use `Event.wait(timeout=...)` over `sleep`.

## Verification

- `uv run pytest tests/test_filewatch.py --collect-only -q` → exactly **8 node IDs**, no collection error.
- `uv run pytest tests/test_filewatch.py -x` → RED with a real `ImportError` (`_make_watch_filter` absent); full file run = **8 failed** on genuine `ImportError`/`AttributeError` (the toggle node RED-fails on the absent `Config.reload` field).
- Full suite: `uv run pytest` → **253 passed, 8 failed** (only the new RED file fails; Phase 9 `test_reload.py` engine stays green).
- `uv run ruff check tests/test_filewatch.py` → clean.
- Guard greps: no `import psutil`/`psutil.` anywhere; `/proc/<pid>/fd` listdir present; no top-level observer import; all three editor-save helpers + three deferred wrappers present.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] SC#2 collapsed from a 3-way parametrize to one internal loop**
- **Found during:** Task 1 (first collect-only run returned 10 node IDs, not 8)
- **Issue:** Parametrizing `test_editor_save_patterns_one_reload` over the three savers expanded it into 3 node IDs, breaking the plan's `must_haves` truth "All eight Phase-10 node IDs COLLECT" and the acceptance criterion "lists exactly 8 node IDs".
- **Fix:** Made it a single node that iterates `(truncate_write, temp_then_rename, multi_event_burst)` internally (each against its own fresh observer), so the file collects exactly 8 node IDs while still exercising all three editor-save sequences.
- **Files modified:** tests/test_filewatch.py
- **Commit:** b412e3e

**2. [Rule 3 - Blocking] Dropped the mirrored `ConfigHolder` import**
- **Found during:** Task 1 (ruff F401)
- **Issue:** The plan says to mirror `test_reload.py`'s imports "where applicable"; the verbatim `from weatherbot.config.holder import ConfigHolder` is genuinely unused in this file (the SC#4 node receives the holder via the `holder_scheduler` fixture), and the project gates on ruff.
- **Fix:** Removed the unused import to keep ruff clean. `Config`/`Location`/`Schedule` imports are retained (used by the local builders).
- **Files modified:** tests/test_filewatch.py
- **Commit:** b412e3e

## Self-Check: PASSED
- FOUND: tests/test_filewatch.py
- FOUND: commit b412e3e
