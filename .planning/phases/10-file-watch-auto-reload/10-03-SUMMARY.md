---
phase: 10-file-watch-auto-reload
plan: 03
subsystem: infra
tags: [watchfiles, inotify, file-watch, hot-reload, debounce, threading, daemon]

# Dependency graph
requires:
  - phase: 09-reload-engine
    provides: "_do_reload validate/swap/reconcile/keep-old engine + reload_requested Event + main poll loop"
  - phase: 10-file-watch-auto-reload (10-01)
    provides: "tests/test_filewatch.py Wave-0 RED scaffold (8 nodes)"
  - phase: 10-file-watch-auto-reload (10-02)
    provides: "watchfiles>=1.2.0 runtime dep; ReloadConfig.watch toggle + Config.reload field"
provides:
  - "Single long-lived watchfiles observer thread (weatherbot-filewatch) wired into run_daemon"
  - "_run_watch_observer flag-set-only loop, _derive_watch_dirs, _make_watch_filter helpers"
  - "WATCH_QUIET_MS/WATCH_DEBOUNCE_MS/WATCH_RUST_TIMEOUT_MS module constants"
  - "D-04 watch-set re-derive on _do_reload success path (no second observer; A4)"
  - "CFG-03 closed: config/template saves auto-reload with debounce; .env never watched"
affects: [phase-11-discord-gateway, reload, daemon-lifecycle]

# Tech tracking
tech-stack:
  added: []  # watchfiles added in 10-02; this plan only wires it
  patterns:
    - "Flag-set-only observer thread funneling into the existing reload_requested Event (D-02)"
    - "Directory-watch + basename filter (inode-swap safe; secrets boundary)"
    - "Shared one-element box (watch_dirs_ref) re-read by the observer loop; mutated on reload"

key-files:
  created: []
  modified:
    - "weatherbot/scheduler/daemon.py"
    - "tests/test_filewatch.py"

key-decisions:
  - "Observer is FLAG-SET ONLY (request_reload -> reload_requested.set()); _do_reload always runs on the main poll-loop thread (D-02, Pitfall #6/#9)."
  - "watch() params: step=400 (quiet window), debounce=1600, rust_timeout=500 (sub-second SIGTERM teardown), yield_on_timeout=True, stop_event=stop (D-05, Pitfall #2)."
  - "Watch DIRECTORIES (config dir + TEMPLATES_DIR), never files; basename allow-list filter excludes .env (Pitfall #11c / #12)."
  - "D-04 re-derive mutates only watch_dirs_ref[0]; the single watch() generator re-enters with new dirs on the next rust_timeout tick, releasing old fds on exhaustion (A4 — no fd leak, no second observer)."
  - "[reload] watch toggle is read ONCE at startup (Open Question Q2); flipping it applies on next restart, the explicit SIGHUP/CLI trigger always works."

patterns-established:
  - "Flag-set-then-service-on-main-thread extended from SIGHUP to file-watch (single Event, one reload path)."
  - "Watch-arm settle in tests: bounded pre-save settle so reload/no-reload assertions are valid before the inotify watch arms."

requirements-completed: [CFG-03]

# Metrics
duration: ~10min
completed: 2026-06-16
---

# Phase 10 Plan 03: File-Watch Observer Wiring Summary

**Single long-lived watchfiles observer wired into run_daemon — config/template saves debounce (step=400) and funnel through the existing reload_requested Event into Phase 9's untouched _do_reload; .env is never watched, the watch set re-derives on each successful reload (A4), and the observer tears down sub-second on SIGTERM. CFG-03 closed.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-16T22:18:17Z
- **Completed:** 2026-06-16T22:28:11Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added the three WATCH_* module constants + `_derive_watch_dirs`, `_make_watch_filter`, `_run_watch_observer` (flag-set-only blocking `watch()` loop).
- Wired a single `weatherbot-filewatch` daemon thread into `run_daemon` (gated on `config.reload.watch and config_path is not None`), stopped + joined in the existing `finally`.
- Threaded an optional `watch_dirs_ref` into `_do_reload`; the success path re-derives the watch set (D-04) by mutating only the shared cell — no second observer, no `watch()` call (A4 structural guarantee).
- Turned all 8 `tests/test_filewatch.py` nodes green; `tests/test_reload.py` (Phase-9 regression guard) stays green; full suite green (261 passed), verified stable across 4 consecutive full-load runs.

## Task Commits

Each task was committed atomically:

1. **Task 1: WATCH_* constants, _derive_watch_dirs, _make_watch_filter, _run_watch_observer** - `5a0c1d0` (feat)
2. **Task 2: Wire observer start/stop into run_daemon + watch-set re-derive in _do_reload** - `e6bd6da` (feat)

_Plan metadata commit follows this summary._

## Files Created/Modified
- `weatherbot/scheduler/daemon.py` - WATCH_* constants; `_derive_watch_dirs`/`_make_watch_filter`/`_run_watch_observer` helpers; observer start in `run_daemon` + stop/join in the existing `finally`; optional `watch_dirs_ref` kwarg on `_do_reload` with the D-04 re-derive on the success path; `watch_dirs_ref` threaded into the poll-loop `_do_reload(...)` call.
- `tests/test_filewatch.py` - Added a bounded `_await_watch_armed()` settle before the decisive save in the arm-race-sensitive tests so the inotify watch is established before the reload/no-reload assertion (test-harness fix; no assertion weakened).

## Decisions Made
- Implemented `_make_watch_filter` as a plain `(change, path) -> bool` closure over a basename allow-list (`{config.toml} ∪ {referenced template names}`) rather than subclassing `watchfiles.DefaultFilter` — explicit, minimal, and the hard `.env` exclusion is obvious by construction (Pitfall #12).
- `request_reload` logs at debug then `.set()`s — kept flag-set-only, mirroring `_handle_hup`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed a watchfiles inotify arm-race in the filewatch tests**
- **Found during:** Task 2 (full-suite verification)
- **Issue:** The Wave-0 tests write the decisive save IMMEDIATELY after `thread.start()`. watchfiles' Rust inotify backend establishes its directory watch a short moment after the thread starts; a save landing before the watch is armed is genuinely never reported (inotify only delivers events for watches already in place). Under full-suite CPU contention this arm window widens, so `test_save_triggers_reload` (and, more insidiously, `test_env_save_never_reloads` — whose NO-reload assertion could pass spuriously on a missed event) intermittently failed/were-invalid. Empirically reproduced: 1/12 misses without a settle, 0/12 with a 0.3s settle.
- **Fix:** Added a named `_WATCH_ARM_SETTLE_S = 0.3` constant + `_await_watch_armed()` helper and call it before the decisive save in the six arm-race-sensitive tests. No assertion was changed — every reload/no-reload claim still holds, now evaluated AFTER the watch is armed. The production observer is a long-lived loop that arms once and stays armed; the race was purely a test-harness timing concern.
- **Files modified:** tests/test_filewatch.py
- **Verification:** Full suite (`uv run pytest`) green 4/4 consecutive runs under full load (261 passed); `tests/test_filewatch.py` 8/8 green.
- **Committed in:** e6bd6da (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — test reliability)
**Impact on plan:** The fix only stabilizes the test harness against an inherent inotify arm latency; it strengthens the `.env` negative assertion (which is now evaluated against an armed watch) and weakens nothing. No production-code scope creep.

## Issues Encountered
- The flake was initially non-deterministic (passing in isolation, failing under full-suite load), which required empirical root-causing (a 12x arm-race micro-benchmark) before fixing — see Deviation 1.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CFG-03 is closed: file-watch auto-reload is live, debounced, secrets-safe, and re-derives its watch set on reload. Phase 10 is complete.
- Phase 11 (Discord inbound gateway bot + reload confirm) can build on the now-complete reload surface: the observer/SIGHUP/CLI triggers all funnel through the same `reload_requested` Event and `_do_reload`, so a Discord-posted reload outcome (CFG-07) hooks the existing success/reject logs without touching the trigger layer.

## Self-Check: PASSED

- weatherbot/scheduler/daemon.py — FOUND
- tests/test_filewatch.py — FOUND
- 10-03-SUMMARY.md — FOUND
- commit 5a0c1d0 — FOUND
- commit e6bd6da — FOUND

---
*Phase: 10-file-watch-auto-reload*
*Completed: 2026-06-16*
