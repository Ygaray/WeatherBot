---
phase: 09-reload-engine-explicit-trigger
plan: 03
subsystem: cli-ops
tags: [cli, ops, pid-file, sighup, reload, check-config, stdlib-only, proc-guard]

# Dependency graph
requires:
  - phase: 09-01
    provides: Wave-0 RED tests (test_reload_cli_signals_pid in test_reload.py; the three check_config tests in test_cli.py)
  - phase: 09-02
    provides: validate_config_and_templates(path, templates_dir=None) — the ONE shared offline validator check-config calls
provides:
  - "weatherbot/ops/pidfile.py: write_pid_atomic (temp + os.replace, POSIX-atomic, re-raises), read_pid (FileNotFoundError/ValueError), is_weatherbot_pid (/proc/<pid>/cmdline D-03 guard with injectable cmdline_reader + non-Linux degrade), PID_FILE constant (default /run/weatherbot.pid)"
  - "weatherbot/cli.py do_reload(pid_file=PID_FILE, *, _cmdline_reader=None) -> int — the SIGHUP sender (read PID -> /proc guard -> os.kill, 0/1)"
  - "weatherbot check-config subcommand — OFFLINE validate via the shared validator (0/1, zero network, no Settings/do_check)"
  - "weatherbot reload subcommand (--pid-file override) -> do_reload"
affects: [09-05 daemon-side SIGHUP receiver + write_pid_atomic on startup + PID unlink in finally, 10 watchfiles auto-reload, 11 reload-confirm]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "stdlib-only never-raise ops helper (mirrors sdnotify.py) — EXCEPT the writer deliberately re-raises so a startup PID-write failure is visible"
    - "Atomic file write via tempfile.mkstemp + os.replace (POSIX-atomic) — no python-pidfile dependency"
    - "/proc/<pid>/cmdline PID-recycling guard with an injectable cmdline_reader seam for offline testing + documented non-Linux degrade-to-signal"
    - "check-config dispatch as a strict offline subset of check (calls the shared validator, never do_check/run_self_check/load_settings — Pitfall 8)"

key-files:
  created:
    - weatherbot/ops/pidfile.py
  modified:
    - weatherbot/ops/__init__.py
    - weatherbot/cli.py

key-decisions:
  - "is_weatherbot_pid takes an injectable cmdline_reader (pid -> bytes); test_reload_cli_signals_pid stubs it via do_reload's _cmdline_reader kwarg so the /proc guard is exercised offline without a real /proc entry"
  - "The PID writer RE-RAISES on failure (unlike sdnotify's swallow-OSError) because it runs in run_daemon startup where a PID-write failure must be loud, not silent"
  - "do_reload returns 1 (without ever signaling) on no-PID / stale-PID / not-a-weatherbot-process — the signal is never delivered to a recycled PID (T-09-06)"
  - "check-config dispatch is an early-return offline branch: validate_config_and_templates inside the established catch set (FileNotFoundError, tomllib.TOMLDecodeError, ValidationError, ValueError); it loads NO Settings and never probes the network (Pitfall 8)"
  - "reload subparser omits config_parent (it loads no config) and carries only an optional --pid-file override defaulting to PID_FILE"

patterns-established:
  - "Pattern: atomic PID-file write (temp + os.replace) + /proc cmdline staleness guard, stdlib-only, cycle-free ops helper"
  - "Pattern: CLI control-path sender (do_reload) following do_check's return-int + outcome-only-log contract"

requirements-completed: [CFG-02, CFG-08]

# Metrics
duration: ~5min
completed: 2026-06-16
---

# Phase 09 Plan 03: check-config + reload CLI surfaces & ops/pidfile helper Summary

Added the two operator-facing CLI surfaces — `weatherbot check-config` (CFG-08 offline
dry-run over the Plan-02 shared validator, zero network) and `weatherbot reload` (CFG-02
explicit-trigger sender half) — plus a new stdlib-only `weatherbot/ops/pidfile.py`
(atomic PID write + read + the `/proc/<pid>/cmdline` PID-recycling guard, D-03).

## What Was Built

### Task 1 — `weatherbot/ops/pidfile.py` (NEW) + ops exports
- `write_pid_atomic(pid_file=PID_FILE)`: `mkdir(parents)` → `tempfile.mkstemp` → write
  `os.getpid()` → `os.replace(tmp, pid_file)` (atomic on POSIX, T-09-07). On any error it
  unlinks the temp and **re-raises** (startup-visible, not swallowed).
- `read_pid(pid_file=PID_FILE) -> int`: raises `FileNotFoundError`/`ValueError` for the
  sender to report "no valid PID file".
- `is_weatherbot_pid(pid, cmdline_reader=None) -> bool`: reads `/proc/<pid>/cmdline`,
  returns `b"weatherbot" in cmdline`; `False` on a missing PID (FileNotFoundError); degrades
  to `True` if `/proc` is entirely absent (non-Linux). `cmdline_reader` is an injectable
  seam for offline tests.
- `PID_FILE = Path("/run/weatherbot.pid")` module constant + override at every callsite.
- Exported the three helpers + `PID_FILE` from `weatherbot/ops/__init__.py`. Cycle-free
  (no `cli`/`scheduler` import).
- Commit: `4dd847a`

### Task 2 — `cli.py` check-config + reload subparsers, `do_reload`, dispatch
- `do_reload(pid_file=PID_FILE, *, _cmdline_reader=None) -> int`: `read_pid` → on
  `(FileNotFoundError, ValueError)` log + return 1; `is_weatherbot_pid` guard → on stale/
  recycled log + return 1 (signal NEVER sent); else `os.kill(pid, signal.SIGHUP)` + return 0.
  Mirrors `do_check`'s return-int + outcome-only-log contract.
- `check-config` subparser (`parents=[config_parent]`) + offline dispatch branch:
  `validate_config_and_templates(args.config)` inside the established catch set → 1 on
  failure, 0 on pass. Loads **no** Settings, **never** calls `do_check`/`run_self_check`
  (Pitfall 8 — strict subset of `check`).
- `reload` subparser (`--pid-file` override, no config_parent) + dispatch → `do_reload`.
- Imported `os`, `signal`, the pidfile helpers, and the shared validator at module top.
- Commit: `ff47d9f`

## Verification

| Check | Result |
|-------|--------|
| `test_reload_cli_signals_pid` (test_reload.py) | PASS — reads PID file, passes the stubbed `/proc` guard, `os.kill(4242, SIGHUP)` |
| `test_check_config_offline_pass` | PASS — good config → 0 |
| `test_check_config_offline_fail` | PASS — bad template token → 1 |
| `test_check_config_no_network` | PASS — `fetch_onecall` boundary never reached (zero network) |
| check-config branch offline (grep do_check/run_self_check/load_settings) | 0 matches |
| `os.replace` in pidfile.py | present (atomic write) |
| pidfile cycle-free (grep weatherbot.cli/scheduler) | 0 matches |
| ruff check + format | clean |
| Full suite | 238 passed, 10 failed |

The 10 remaining failures are **all** in `test_reload.py` and **all** depend on the
not-yet-built daemon-side engine — `_do_reload` / `_install_reload_signal` from
`weatherbot.scheduler.daemon` (Plan 09-05, later wave). This is expected and out of scope
for this plan, exactly as called out in the execution brief ("Phase-9 tests for the reload
engine (Plan 09-05) will remain RED").

## Deviations from Plan

None — plan executed exactly as written. The one nuance worth noting (not a deviation): the
`test_reload_cli_signals_pid` test lives in `tests/test_reload.py` (the plan's `<verify>`
referenced `tests/test_cli.py -k reload_cli_signals_pid`); the test exists and is green, and
the three `check_config` tests are in `tests/test_cli.py` as the plan describes. The test
exercises the `/proc` guard through `do_reload`'s `_cmdline_reader` injection seam — which is
why `is_weatherbot_pid` and `do_reload` both expose that kwarg.

## TDD Gate Compliance

Both tasks are `tdd="true"`. The Wave-0 RED tests (`test_reload_cli_signals_pid` + the three
`check_config` tests) were confirmed failing before implementation and are now GREEN. Per the
sequential single-feature convention these were committed as `feat(...)` commits (the RED
tests were authored in Plan 09-01 Wave 0, so no new `test(...)` commit was authored here —
the RED gate predates this plan). No regression introduced.

## Self-Check: PASSED
- FOUND: weatherbot/ops/pidfile.py
- FOUND: weatherbot/ops/__init__.py (pidfile exports)
- FOUND: weatherbot/cli.py (do_reload + check-config/reload subparsers + dispatch)
- FOUND commit: 4dd847a (pidfile helper)
- FOUND commit: ff47d9f (check-config + reload CLI)
