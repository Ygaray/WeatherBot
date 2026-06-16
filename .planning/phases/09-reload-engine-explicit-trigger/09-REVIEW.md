---
phase: 09-reload-engine-explicit-trigger
reviewed: 2026-06-16T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - tests/conftest.py
  - tests/test_cli.py
  - tests/test_models.py
  - tests/test_reload.py
  - tests/test_scheduler.py
  - weatherbot/cli.py
  - weatherbot/config/loader.py
  - weatherbot/config/models.py
  - weatherbot/ops/__init__.py
  - weatherbot/ops/pidfile.py
  - weatherbot/scheduler/catchup.py
  - weatherbot/scheduler/daemon.py
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 9: Code Review Report

**Reviewed:** 2026-06-16T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

This phase ships the explicit hot-reload path: a `weatherbot reload` CLI sender (PID
file + `/proc` guard + `os.kill`), a SIGHUP handler + poll-loop in the daemon, and a
two-phase build-then-commit reload engine (`_do_reload`) with diff-reconcile and
all-or-nothing rollback. The reload engine itself is carefully structured (validate-
or-keep-old, atomic holder swap, rollback on reconcile throw) and the exactly-once
sent-log story is sound.

The serious defects are in the **cross-process control path** — the part that crosses
a process boundary and therefore cannot be fully covered by the in-process tests.
`do_reload` and the `/proc` staleness guard have two real correctness/robustness gaps
that the existing tests do not exercise: an unhandled `os.kill` TOCTOU race that turns
a routine "process just exited" into an uncaught traceback, and a substring-only
`b"weatherbot" in cmdline` guard that defeats the very PID-recycling defense it claims
to provide. A handful of warnings concern incomplete exception catch-sets and a
rollback path that can leave the live scheduler half-rebuilt.

## Critical Issues

### CR-01: `os.kill` TOCTOU race in `do_reload` propagates an uncaught traceback

**File:** `weatherbot/cli.py:493-502`
**Issue:** `do_reload` checks `is_weatherbot_pid(pid, ...)` and then calls
`os.kill(pid, signal.SIGHUP)`. Between the `/proc` guard read and the `os.kill`, the
target process can exit (the daemon is on a separate process and could be shutting
down — exactly the window this guard exists to narrow). When that happens `os.kill`
raises `ProcessLookupError`; if the caller lacks permission to signal the (now
recycled) PID it raises `PermissionError`. Neither is caught. The function's docstring
promises a "return-int + outcome-only-log contract (never a secret)" with every
safe-fail branch returning `1`, but this path instead crashes with a raw Python
traceback — the precise failure mode the rest of the module (`_load_config_reporting`,
`run_send_now`, `run_weather`) is written to avoid. This is the canonical TOCTOU bug:
the guard reduces but does not eliminate the race, so the signal call must itself be
defended.
**Fix:**
```python
    try:
        os.kill(pid, signal.SIGHUP)
    except ProcessLookupError:
        _log.error("reload: PID exited before signal (stale or recycled)", pid=pid)
        return 1
    except PermissionError:
        _log.error("reload: not permitted to signal PID", pid=pid)
        return 1
    _log.info("reload signal sent", pid=pid)
    return 0
```

### CR-02: `/proc` PID-recycling guard accepts any process whose cmdline merely contains `b"weatherbot"`

**File:** `weatherbot/ops/pidfile.py:90-97`
**Issue:** `is_weatherbot_pid` returns `b"weatherbot" in cmdline`, a raw substring
test against the entire NUL-separated argv. The module bills this as "the PID-recycling
defense" so a SIGHUP "can never be delivered to a recycled/unrelated PID (T-09-06)."
But the substring match makes the guard far too permissive: after the real daemon
exits and the OS recycles its PID, an unrelated process passes the guard if `weatherbot`
appears anywhere in its argv — e.g. `vim /home/me/weatherbot/config.toml`,
`tail -f /var/log/weatherbot.log`, `grep weatherbot ...`, or `python -m pytest
tests/.../weatherbot`. The reload sender would then deliver SIGHUP to that innocent
process. Since most programs do not install a SIGHUP handler, the default disposition
of SIGHUP is to **terminate** the process — so a routine `weatherbot reload` can kill
an operator's editor or log tail that happened to recycle the daemon's PID. The guard
must match the executable/argv0 identity, not "the string appears somewhere."
**Fix:** Check argv0 (the first NUL-delimited field) for the expected program name
rather than scanning the whole buffer:
```python
def is_weatherbot_pid(pid, cmdline_reader=None) -> bool:
    if cmdline_reader is None:
        cmdline_reader = _read_proc_cmdline
    try:
        cmdline = cmdline_reader(pid)
    except FileNotFoundError:
        return False
    argv = cmdline.split(b"\x00")
    # argv0 (or argv1 for `python -m weatherbot`) must name the program, not just
    # contain the token anywhere in an unrelated path/argument.
    prog = Path(argv[0].decode("utf-8", "replace")).name if argv and argv[0] else ""
    rest = b"\x00".join(argv[1:3])  # `python -m weatherbot` / `... weatherbot run`
    return prog == "weatherbot" or b"weatherbot" in rest
```
(Exact predicate is a judgment call, but matching argv0/`-m` target rather than the
whole buffer is mandatory to make the recycling defense real.)

## Warnings

### WR-01: `read_pid` / `do_reload` do not handle `PermissionError` (or other `OSError`) on the PID-file read

**File:** `weatherbot/ops/pidfile.py:62-71`, `weatherbot/cli.py:487-491`
**Issue:** `read_pid` does `Path(pid_file).read_text(...)` and `do_reload` catches only
`(FileNotFoundError, ValueError)`. A PID file that exists but is not readable by the
reload sender (e.g. written by the daemon under a different umask, or an `IsADirectory`/
`PermissionError` on `/run`) raises `PermissionError`/`OSError`, which escapes the catch
set and crashes with a traceback — contradicting the documented "all safe-fail branches
return 1" contract. The `read_pid` docstring even enumerates the catch set the caller
relies on, but omits the realistic permission case.
**Fix:** Broaden the catch in `do_reload` to include `OSError` (which covers
`PermissionError`, `IsADirectoryError`, etc.) alongside `ValueError`:
```python
    try:
        pid = read_pid(pid_file)
    except (FileNotFoundError, ValueError, OSError):
        _log.error("reload: no valid PID file", path=str(pid_file))
        return 1
```
(`FileNotFoundError` is itself an `OSError`, so the explicit listing is just for the
distinct log message if you want one; the key fix is catching `OSError`.)

### WR-02: Rollback `_restore_jobs` can leave the live scheduler partially rebuilt and only logs the failure

**File:** `weatherbot/scheduler/daemon.py:595-616`
**Issue:** On a reconcile throw, `_do_reload` restores via `_restore_jobs` →
`_reconcile_jobs` → `_register_jobs`. If the original failure was a transient/persistent
problem inside `_register_jobs` (the canonical reconcile failure — see
`test_reconcile_failure_rolls_back`, which monkeypatches exactly `_register_jobs` to
raise), the SAME `_register_jobs` is re-invoked during restore and will raise again. The
inner `except Exception` swallows it with `_log.exception(...)`, so the holder is
correctly rolled back (`holder.replace(old_cfg)` ran first) but the **live job table may
be left in whatever half-applied state the failed reconcile produced** — the old jobs are
not guaranteed to be re-added. The code comment claims "Because the reconcile ADDs
(replace_existing) BEFORE it REMOVEs, a throw in the add phase leaves the old jobs
untouched," which is true only when the throw happens after the old ids were already
re-added; an injected/early `_register_jobs` failure re-throws before re-adding anything.
The unit test passes only because it asserts on `holder.current()` (the config), not on a
correctly-restored job set after this double-failure. In production this means the daemon
can come out of a failed reload announcing "rolled back" while actually running a degraded
schedule.
**Fix:** Make the restore not depend on the same primitive that just failed, or at minimum
re-raise / escalate (not silently `_log.exception`) when restore itself fails so the
operator knows the schedule is degraded:
```python
        try:
            _restore_jobs(...)
        except Exception:
            _log.critical("reload rollback FAILED to restore old jobs; "
                          "schedule may be degraded — restart advised")
            # keep re-raising the ORIGINAL error below, but the operator is now warned
```
and consider snapshotting/rebuilding the live job set from the known-good `old_cfg`
through a path that cannot share the failure.

### WR-03: `record_alert(...)` return value assigned to `self_first` but only used for logging — three near-identical blocks invite drift

**File:** `weatherbot/scheduler/daemon.py:245-299, 322-336`
**Issue:** Four structurally-identical alert blocks (`release_claim` → set
`claimed=False` → `record_alert` → `if self_first: _log.critical(...)`) are copy-pasted
across the HTTPStatusError arm, the network-error arm, the non-ok-result arm, and the
unexpected-exception arm. They differ only in the `reason` value and (in the last) the
`claimed and local_date is not None` guard. This is high-duplication code on the most
safety-critical path (alert-on-miss), where a future edit to one block (e.g. adding a
severity field or changing the log key) can silently miss the others. Not a present-tense
bug, but a maintainability defect on a path that must stay consistent.
**Fix:** Extract a helper, e.g.
`_alert_missed(db_path, location, slot, local_date, reason)` that does the
`record_alert` + conditional `_log.critical` and call it from all four sites; keep the
`release_claim`/`claimed=False` at the call sites where they differ.

### WR-04: `_read_proc_cmdline` silently degrades to "is a weatherbot process" when `/proc` is absent

**File:** `weatherbot/ops/pidfile.py:100-111`
**Issue:** When `/proc` does not exist (non-Linux), `_read_proc_cmdline` returns the
sentinel `b"weatherbot"`, which makes `is_weatherbot_pid` return `True` unconditionally —
i.e. the staleness/recycling guard is fully disabled and `do_reload` will signal **any**
PID found in the file. The docstring calls this "documented degraded guard; host is
Linux," but combined with CR-02 this means on any non-Linux dev/CI box the guard is a
no-op and a stale PID file signals an arbitrary process. At minimum this should fail
closed (return a value that makes the guard *reject*), since "signal an unknown PID" is
the more dangerous default than "refuse to reload."
**Fix:** Degrade to reject, not accept — return a sentinel that does NOT contain the
token (so `is_weatherbot_pid` returns `False` and the reload safe-fails with "not a
weatherbot process") when `/proc` is unavailable, or raise a clear "guard unsupported on
this platform" error that `do_reload` maps to exit 1.

### WR-05: `Schedule._hhmm` swallows `ValueError` from non-numeric time components into a misleading message via a bare `except Exception`

**File:** `weatherbot/config/models.py:54-60`
**Issue:** `_hhmm` wraps the parse in `try/except Exception` and re-raises a single
`"time must be 'HH:MM' 24-hour"` message. This is broadly correct for validation, but the
bare `except Exception` also catches programming errors unrelated to the input (e.g. if
`v` were ever not a `str`, `v.split` raises `AttributeError`, which is then reported to
the user as a malformed-time error). For a fail-loud-at-load validator this misclassifies
an internal type bug as user input error. Low severity because pydantic coerces `time` to
`str` first, but the catch is wider than the intent.
**Fix:** Narrow to the expected parse errors: `except (ValueError, AttributeError)` — or
better, validate structure explicitly without relying on exception flow for the
`len()==2`/range checks (which currently raise a bare `ValueError` with no message inside
the `try`, only to be re-wrapped).

### WR-06: `_announce_schedule` / `_run_catchup` re-enumerate `holder.current()` independently of `_register_jobs`, risking drift if one enumeration changes

**File:** `weatherbot/scheduler/daemon.py:645-650, 689-693` vs `391-420`, `431-437`
**Issue:** The job id `f"{location.name}|{slot.time}|{slot.days}"` and the enabled-slot
filter are spelled out independently in `_register_jobs`, `_desired_job_ids`, and
`_announce_schedule` (and the enable filter again in catchup planning). The codebase
comments explicitly note these "must mirror EXACTLY," which is an acknowledgment that the
identity is duplicated across four sites with no single source of truth. A future change
to the id scheme (e.g. incorporating `location.id` instead of `name`, which D-01 work
suggests is coming) must be made in all sites or the reconcile diff silently mis-keys
(orphaned old jobs, or a reload that never removes a renamed slot). This is the latent
coupling that a structural pre-pass would flag.
**Fix:** Centralize the job-id derivation in one helper, e.g.
`def _job_id(location, slot) -> str`, and the enabled-slot enumeration in one generator,
and have all call sites consume them.

## Info

### IN-01: `do_reload` and `_do_reload` share a name across modules

**File:** `weatherbot/cli.py:464` (`do_reload`) and `weatherbot/scheduler/daemon.py:531`
(`_do_reload`)
**Issue:** The CLI sender is `do_reload` and the daemon engine is `_do_reload`; the
near-identical names (differing only by a leading underscore and module) are easy to
confuse when reading stack traces or grepping. Naming-only.
**Fix:** Consider `send_reload_signal` for the CLI sender vs `apply_reload` for the
engine to make the cross-process roles obvious.

### IN-02: `_heartbeat_tick` and `emit_online` import `datetime`/`timezone` inside the function body

**File:** `weatherbot/scheduler/daemon.py:355`, and in-body `from datetime import datetime`
at lines 174, 355, 640
**Issue:** Several functions do in-body `from datetime import ...`. Module-top already
needs datetime in multiple places; the in-body imports are cheap but inconsistent with the
module's other top-level stdlib imports and add noise. (The lazy `send_now`/`build_channel`
imports are justified cycle-breakers; the `datetime` ones are not.)
**Fix:** Hoist `from datetime import datetime, timezone` to module top.

### IN-03: Magic literal `"__heartbeat__"` repeated across reconcile/announce sites

**File:** `weatherbot/scheduler/daemon.py:429, 471, 887`
**Issue:** The internal heartbeat job id `"__heartbeat__"` is a string literal duplicated
in `_desired_job_ids`'s comment, `_reconcile_jobs`'s live-set filter, and the `add_job`
registration. A typo in one (e.g. the reconcile filter) would cause the heartbeat job to
be treated as a stale slot and removed on the first reload.
**Fix:** Promote to a module constant `HEARTBEAT_JOB_ID = "__heartbeat__"` and reference
it at all three sites.

### IN-04: Test `test_reconcile_failure_rolls_back` asserts only `holder.current() is old`, not a correctly-restored job set after a re-throwing restore

**File:** `tests/test_reload.py:261-296`
**Issue:** This test monkeypatches `_register_jobs` to raise for the WHOLE reload,
including the rollback's `_restore_jobs` path. It then asserts `_job_ids(scheduler) ==
jobs_before` — but because `_register_jobs` is patched to a no-op-raise, the live job
table was never mutated in the first place, so the assertion passes trivially without
proving the restore actually rebuilds anything (see WR-02). The test gives false
confidence that rollback restores the job set. Consider a variant where the reconcile
fails AFTER partially mutating jobs (e.g. patch `remove_job` to raise) so the restore path
is genuinely exercised.
**Fix:** Add a rollback test that mutates the live job set before throwing, then asserts
the old job set is fully restored (not just the config reference).

---

_Reviewed: 2026-06-16T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
