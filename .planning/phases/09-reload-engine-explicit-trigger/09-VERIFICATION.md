---
phase: 09-reload-engine-explicit-trigger
verified: 2026-06-16T08:50:00Z
status: gaps_found
score: 5/5 truths functionally verified; 2 must-have claims (PID-recycling guard + safe-fail contract) falsified
overrides_applied: 0
gaps:
  - truth: "`weatherbot reload` (do_reload) returns 0 on success / 1 on no-PID/stale-PID/not-our-process — outcome-only logging, all safe-fail branches return 1 (never a traceback)."
    status: partial
    reason: >
      CR-01 confirmed in code. weatherbot/cli.py:500 calls
      `os.kill(pid, signal.SIGHUP)` with NO try/except. Between the `/proc`
      guard read (line 493) and the `os.kill` (line 500) the daemon can exit
      (ProcessLookupError) or the PID can be recycled to a process the sender
      cannot signal (PermissionError). Neither is caught, so a routine
      `weatherbot reload` crashes with a raw Python traceback instead of the
      documented "return 1, outcome-only-log" contract that the rest of the
      module (`_load_config_reporting`, `run_send_now`, `run_weather`,
      `_load_config_reporting`) is written to honor. The Plan 03 must-have
      explicitly claims "returns 1 on no-PID/stale-PID/not-our-process"; the
      os.kill failure path violates it. The HAPPY path is tested and works
      (test_reload_cli_signals_pid passes; SIGHUP is sent), so the goal is met
      in the normal case — this is a failure-mode robustness gap on the
      explicitly-claimed safe-fail contract.
    artifacts:
      - path: "weatherbot/cli.py"
        issue: "Line 500 `os.kill(pid, signal.SIGHUP)` is unguarded — ProcessLookupError/PermissionError escape and crash the reload sender with a traceback, breaking the documented all-safe-fail-branches-return-1 contract."
    missing:
      - "Wrap os.kill in try/except (ProcessLookupError, PermissionError) -> _log.error(...) + return 1, per the fix in 09-REVIEW.md CR-01."
      - "Optionally broaden read_pid catch in do_reload to OSError (WR-01) so a non-readable PID file also safe-fails to 1 instead of an uncaught PermissionError/IsADirectoryError."
  - truth: "The /proc/<pid>/cmdline staleness guard confirms the PID is a weatherbot process before signaling, so a SIGHUP can NEVER be delivered to a recycled/unrelated PID (T-09-06 PID-recycling defense)."
    status: partial
    reason: >
      CR-02 confirmed in code. weatherbot/ops/pidfile.py:97 implements the guard
      as `return b"weatherbot" in cmdline` — a raw substring test against the
      whole NUL-separated argv. After the real daemon exits and the OS recycles
      its PID, ANY unrelated process whose argv merely contains the token passes
      the guard: `vim /home/me/weatherbot/config.toml`, `tail -f
      /var/log/weatherbot.log`, `grep weatherbot ...`, `python -m pytest
      tests/.../weatherbot`. Since most programs install no SIGHUP handler, the
      default disposition of SIGHUP is to TERMINATE — so a routine `weatherbot
      reload` can kill an operator's editor/log-tail that recycled the daemon's
      PID. This directly falsifies the must-have's "can NEVER be delivered to a
      recycled/unrelated PID" claim — the substring match defeats the very
      PID-recycling defense it bills itself as. Compounded by WR-04: on a
      non-Linux host (no /proc) `_read_proc_cmdline` returns the sentinel
      `b"weatherbot"`, making the guard a no-op that fails OPEN (signal any PID)
      rather than fail closed.
    artifacts:
      - path: "weatherbot/ops/pidfile.py"
        issue: "Line 97 `b\"weatherbot\" in cmdline` substring guard is too permissive — matches unrelated processes after PID recycling; line 110 `/proc`-absent sentinel fails open."
    missing:
      - "Match argv0 (or the `-m weatherbot` target) for the program identity rather than scanning the whole buffer, per the fix in 09-REVIEW.md CR-02."
      - "Make the /proc-absent degrade fail CLOSED (return a non-matching sentinel so the guard rejects) rather than fail open (WR-04)."
deferred: []
---

# Phase 9: Reload Engine + Explicit Trigger Verification Report

**Phase Goal:** The running daemon applies edits to config.toml and template files (schedules, locations, units, templates) via an explicit trigger (SIGHUP / `weatherbot reload`) — validate → atomic all-or-nothing swap → diff-and-re-register jobs — keeping the old config on any failure and preserving v1.0's exactly-once delivery across the reload. Also ships `--check-config` dry-run.
**Verified:** 2026-06-16T08:50:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | After editing config.toml/template and triggering reload via SIGHUP or `weatherbot reload`, the daemon applies the change without restart; a new send-time fires on its new schedule (CFG-01, CFG-02). | ✓ VERIFIED | `run_daemon` poll loop (daemon.py:961-988) services `reload_requested`, calls `_do_reload(config_path=...)` on the main thread; `_install_reload_signal` (793-814) installs SIGHUP flag-set-only handler before `scheduler.start()`. `_do_reload` PHASE 2 re-reads config and diff-reconciles jobs (584-627). `test_reload_applies_new_schedule`, `test_sighup_triggers_reload`, `test_reconcile_diff` pass. CLI `reload` subparser registered + dispatched (cli.py:617-628, 711-712). |
| 2 | An invalid edit (bad TOML, dup names, unknown token) is rejected: daemon logs reason and keeps running on the previous valid config — never half-applied, even if job re-registration fails midway (CFG-04, CFG-06). | ✓ VERIFIED | `_do_reload` PHASE 1 (daemon.py:565-580) validates via shared `validate_config_and_templates`; on the catch set (FileNotFoundError/TOMLDecodeError/ValidationError/ValueError) logs `reload rejected` and re-raises with holder+jobs untouched. PHASE 2 wraps reconcile in try/except, `holder.replace(old_cfg)` + `_restore_jobs` on throw (595-616). Poll loop swallows so a bad edit never crashes the daemon (983-988). `test_invalid_reload_keeps_old`, `test_reconcile_failure_rolls_back`, `test_rejected_reload_logs_reason` pass. |
| 3 | Reload reconciles jobs by stable (location, send_time, days) id — adds new, removes deleted/disabled, leaves unchanged; identical config → zero job changes, no duplicate fires (CFG-05). | ✓ VERIFIED | `_reconcile_jobs` (daemon.py:440-498) diffs `_desired_job_ids` vs live (excluding `__heartbeat__`), `add_job(replace_existing=True)` for desired + `remove_job` for dropped; NO `remove_all_jobs` anywhere (grep confirmed). Job id `f"{location.name}|{slot.time}|{slot.days}"`. `test_identical_reload_zero_changes`, `test_reconcile_diff` pass. |
| 4 | Exactly-once preserved across reload: changing a slot's name or IANA tz for an already-delivered-today slot does NOT cause duplicate/skipped briefing (CFG-05, HIGHEST RISK). send_time change is by design a NEW slot. | ✓ VERIFIED | Sent-log/alert key moved name→`location.id` at all four store callsites (daemon.py:183, 239/245, 261/263, 284/286, 305, 322/324) + catchup `was_sent(loc.id,...)` (catchup.py:170) in lockstep. `Location.id` defaults to RAW name (models.py:109-118) → byte-identical key, zero migration. `test_already_sent_slot_not_refired_after_tz_name_change` asserts `claim_slot` LOSES after rename+tz-shift through the REAL claim path; `test_send_time_change_is_new_slot_fires_today_if_ahead` asserts the new-time slot WINS its first claim. Both substantive (not trivial), both pass. |
| 5 | `weatherbot check-config` loads and fully validates a config edit (parse + unique names + template tokens), reports pass/fail without applying or sending (CFG-08). | ✓ VERIFIED | `check-config` subparser (cli.py:611-615) dispatches to `validate_config_and_templates` OFFLINE (695-707): no Settings/secrets, no `run_self_check`. Validator does TOML parse + pydantic + unique name+id + regex template-token check (loader.py:99-139). Behavioral: valid config→rc 0, bad TOML→rc 1, dup name→rc 1 (all confirmed live). `test_check_config_offline_pass/_offline_fail/_no_network` pass (no_network monkeypatches the fetch to fail loud and still exits 0). |

**Score:** 5/5 success criteria functionally verified. Two underlying Plan-03 must-have CLAIMS about the cross-process `reload` sender are falsified (see Gaps).

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `weatherbot/ops/pidfile.py` | atomic PID write + read + /proc staleness guard | ⚠️ ORPHANED-FREE but DEFECTIVE | write_pid_atomic (temp+os.replace), read_pid, is_weatherbot_pid all present and wired into daemon startup + cli sender. Guard substring defect (CR-02) + /proc-absent fail-open (WR-04). |
| `weatherbot/config/loader.py` | validate_config_and_templates shared offline validator + unique-id | ✓ VERIFIED | Present (99-139); called by both check-config and `_do_reload` PHASE 1; assert_unique_names extended for id (67-96). |
| `weatherbot/config/models.py` | Location.id optional + raw-name after-validator default | ✓ VERIFIED | `id: str | None = None` (102) + `_default_id_from_name` model_validator using object.__setattr__ (109-118); frozen intact. |
| `weatherbot/scheduler/daemon.py` | _do_reload + _reconcile_jobs + _restore_jobs + SIGHUP handler + poll loop + PID write/unlink + run_daemon config_path; id-keyed store callsites | ✓ VERIFIED | All present and wired (see truths). PID written at startup (922), unlinked in finally (1002). |
| `weatherbot/scheduler/catchup.py` | plan_catchup was_sent keyed on loc.id | ✓ VERIFIED | `was_sent(loc.id, slot.time, local_date)` (catchup.py:170). |
| `weatherbot/cli.py` | check-config + reload subparsers + dispatch; do_reload sender; run threads config_path | ✓ VERIFIED (subparsers/dispatch) / ⚠️ DEFECTIVE (do_reload os.kill) | Subparsers + dispatch + config_path threading all correct; do_reload os.kill unguarded (CR-01). |
| `tests/test_reload.py` | RED scaffold turned green: apply/reject/rollback/noop/exactly-once/new-slot/SIGHUP/shared-validator | ✓ VERIFIED | 12 tests, all pass; load-bearing exactly-once + rollback + noop named and substantive. |
| `tests/test_models.py` | Location.id default + explicit-wins + frozen + duplicate-id | ✓ VERIFIED | Tests present; full suite green. |
| `tests/test_cli.py` | check-config offline pass/fail + no-network | ✓ VERIFIED | test_check_config_offline_pass/_offline_fail/_no_network present + pass. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| cli.py run dispatch | run_daemon | `config_path=args.config` | ✓ WIRED | cli.py:728-730. |
| run_daemon poll loop | _do_reload | `if reload_requested.is_set(): clear(); _do_reload(config_path=...)` | ✓ WIRED | daemon.py:961-982. |
| _do_reload PHASE 1 | validate_config_and_templates | `new_cfg = validate_config_and_templates(config_path)` | ✓ WIRED | daemon.py:567. |
| _reconcile_jobs | APScheduler add_job/remove_job | stable name|time|days id, replace_existing=True | ✓ WIRED | daemon.py:480-496. |
| cli.py do_reload | pidfile guard + os.kill | read_pid → is_weatherbot_pid → os.kill(SIGHUP) | ⚠️ PARTIAL | Wired but os.kill unguarded (CR-01) and guard substring-permissive (CR-02). |
| cli.py check-config | validate_config_and_templates | try validate except catch-set | ✓ WIRED | cli.py:695-707. |
| daemon fire_slot/catchup | store claim/release/record/resolve + was_sent | pass location.id (not name) | ✓ WIRED | All four daemon callsites + catchup use `.id`; display fields keep `.name`. |
| Location | self.id default | object.__setattr__ in model_validator(after) | ✓ WIRED | models.py:117. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Subcommands registered | `weatherbot --help` | check-config + reload listed | ✓ PASS |
| check-config valid config | `weatherbot check-config --config config.toml` | rc=0, "check-config passed" | ✓ PASS |
| check-config bad TOML | `weatherbot check-config --config /tmp/bad.toml` | rc=1, parse error logged | ✓ PASS |
| check-config duplicate name | `weatherbot check-config --config /tmp/dup.toml` | rc=1 | ✓ PASS |
| reload missing PID safe-fail | `weatherbot reload --pid-file /tmp/nonexistent` | rc=1, "no valid PID file" | ✓ PASS |
| reload happy path | `test_reload_cli_signals_pid` | rc=0, SIGHUP recorded | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist; phase uses pytest as the runnable check.

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Full suite | `uv run pytest -q` | 248 passed in 5.98s | ✓ PASS |
| Phase-9 targeted | `uv run pytest tests/test_reload.py tests/test_cli.py::test_check_config_* -q` | 18 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| CFG-01 | 09-01, 09-05 | Edit config/templates, apply without restart | ✓ SATISFIED | SC#1; poll loop + _do_reload re-read. |
| CFG-02 | 09-01, 09-03, 09-05 | Trigger via SIGHUP and/or `weatherbot reload` | ✓ SATISFIED (functionally) / ⚠️ sender robustness gaps | SC#1; CR-01/CR-02 affect sender failure modes. |
| CFG-04 | 09-01, 09-02, 09-05 | Invalid edit rejected, keep-old, all-or-nothing | ✓ SATISFIED | SC#2; PHASE 1 reject + PHASE 2 rollback. |
| CFG-05 | 09-01, 09-04, 09-05 | Re-register jobs, exactly-once preserved | ✓ SATISFIED | SC#3 + SC#4; stable-id reconcile + id-keyed sent-log. |
| CFG-06 | 09-01, 09-05 | Each outcome (applied/rejected) logged | ✓ SATISFIED | `reload applied`/`reload rejected` (daemon.py:574, 619). |
| CFG-08 | 09-01, 09-02, 09-03 | `check-config` dry-run validate without apply/send | ✓ SATISFIED | SC#5; offline validator, zero network. |

All six requirement IDs accounted for and present in REQUIREMENTS.md mapped to Phase 9. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| weatherbot/cli.py | 500 | Unguarded `os.kill` after a TOCTOU guard | 🛑 Blocker | Routine `weatherbot reload` crashes with a traceback on a benign daemon-exit race / permission error; violates the documented safe-fail-returns-1 contract (CR-01). |
| weatherbot/ops/pidfile.py | 97 | Substring `b"weatherbot" in cmdline` PID-recycling guard | 🛑 Blocker | After PID recycling, SIGHUP can be sent to an unrelated process (vim/tail/grep), terminating it; falsifies the must-have's "never to a recycled/unrelated PID" claim (CR-02). |
| weatherbot/ops/pidfile.py | 109-110 | `/proc`-absent sentinel fails OPEN | ⚠️ Warning | On non-Linux the guard becomes a no-op signaling any PID; should fail closed (WR-04). |
| weatherbot/scheduler/daemon.py | 602-613 | Rollback `_restore_jobs` re-invokes the same `_register_jobs` that failed; swallowed with `_log.exception` | ⚠️ Warning | A persistent `_register_jobs` failure can leave the live job table half-rebuilt while announcing "rolled back"; config holder IS correctly restored (WR-02). |
| tests/test_reload.py | 261-296 | `test_reconcile_failure_rolls_back` patches `_register_jobs` for the whole reload | ⚠️ Warning | Live job set is never mutated, so the restore path isn't genuinely exercised — false confidence in rollback job-restoration (IN-04). |
| weatherbot/config/models.py | 59 | bare `except Exception` in `_hhmm` | ℹ️ Info | Misclassifies an internal type bug as a malformed-time user error (WR-05); pydantic coerces to str first, low risk. |

No TBD/FIXME/XXX debt markers found in phase-modified files.

### Human Verification Required

None strictly required for status determination — all five success criteria are programmatically verified (or behaviorally spot-checked). The cross-process `reload` failure-mode defects (CR-01/CR-02) are codebase-observable and resolved as gaps, not human checks.

### Gaps Summary

The phase GOAL is functionally achieved: all five success criteria are demonstrably true in the codebase — hot-reload via SIGHUP/`weatherbot reload` applies edits without restart, invalid edits are rejected keep-old with all-or-nothing rollback, jobs reconcile by stable id with identical-config-noop, exactly-once survives a name/tz change (the highest-risk SC#4, proven by a substantive test through the real claim path), and `check-config` validates offline with zero network. 248 tests pass.

Two gaps remain, both confined to the **cross-process control path** of the `weatherbot reload` SENDER (not the daemon reload engine, which is sound):

1. **CR-01 — unguarded `os.kill` (cli.py:500).** The happy path works and is tested, but the documented "all safe-fail branches return 1, never a traceback" contract is broken: a daemon that exits in the TOCTOU window (ProcessLookupError) or a PID the sender cannot signal (PermissionError) crashes the sender. This falsifies the Plan-03 must-have "returns 1 on stale-PID/not-our-process."

2. **CR-02 — substring PID-recycling guard (pidfile.py:97).** `b"weatherbot" in cmdline` is too permissive; after PID recycling it can deliver SIGHUP to an unrelated process and (since SIGHUP's default disposition is terminate) kill an operator's editor or log-tail. This directly falsifies the must-have's "can NEVER be delivered to a recycled/unrelated PID" — the substring match defeats the very recycling defense it claims to provide.

Both are real correctness/safety defects in claimed behavior, each with a precise fix already specified in 09-REVIEW.md. They do not block the day-one happy-path functionality but must be closed before the reload sender can be trusted on the always-on host the project targets — exactly the unattended, multi-day, PID-recycling-prone environment where these failure modes occur. Recommended: close via `/gsd-plan-phase --gaps` (small, surgical: a try/except around os.kill + an argv0 match in the guard + fail-closed /proc degrade). The WR-02 rollback-restore and IN-04 test-coverage warnings are advisable companion hardening but are not standalone blockers.

---

_Verified: 2026-06-16T08:50:00Z_
_Verifier: Claude (gsd-verifier)_
