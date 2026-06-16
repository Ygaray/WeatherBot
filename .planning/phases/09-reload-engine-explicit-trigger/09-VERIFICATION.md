---
phase: 09-reload-engine-explicit-trigger
verified: 2026-06-16T12:30:00Z
status: passed
score: 5/5 must-haves verified (2 prior gaps closed)
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: "5/5 functional; 2 must-have claims falsified (CR-01, CR-02)"
  gaps_closed:
    - "`weatherbot reload` (do_reload) returns 1 on stale-PID/not-our-process/unsignalable-PID — os.kill TOCTOU now defended (CR-01), unreadable PID file safe-fails via OSError catch (WR-01)."
    - "The /proc cmdline guard matches program identity (argv0 basename / `-m weatherbot`) — substring match removed, so SIGHUP can NEVER be delivered to a recycled/unrelated PID (CR-02 / T-09-06)."
  gaps_remaining: []
  regressions: []
gaps: []
deferred: []
---

# Phase 9: Reload Engine + Explicit Trigger Verification Report

**Phase Goal:** The running daemon applies edits to config.toml and template files (schedules, locations, units, templates) via an explicit trigger (SIGHUP / `weatherbot reload`) — validate → atomic all-or-nothing swap → diff-and-re-register jobs — keeping the old config on any failure and preserving v1.0's exactly-once delivery across the reload. Also ships `--check-config` dry-run.
**Verified:** 2026-06-16T12:30:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (CR-01/WR-01 + CR-02). Both prior blockers confirmed closed in code.

## Re-verification Summary

The initial verification (2026-06-16T08:50Z) confirmed all five success criteria functionally true but FALSIFIED two Plan-03 must-have claims about the cross-process `reload` sender, raising two 🛑 blockers:

- **CR-01** — `os.kill(pid, SIGHUP)` in `cli.py do_reload` was unguarded; a TOCTOU daemon-exit (`ProcessLookupError`) or unsignalable recycled PID (`PermissionError`) escaped as a traceback, breaking the "all safe-fail branches return 1" contract.
- **CR-02** — `pidfile.py is_weatherbot_pid` used `b"weatherbot" in cmdline`, a substring test that accepted any recycled-PID process whose argv merely mentioned the token (e.g. `vim .../weatherbot/config.toml`), defeating the PID-recycling defense it billed.

Both are now genuinely closed in the codebase (commit `84162da`, RED tests `e45fcff`):

| Gap | Fix in code | Confirmed |
| --- | --- | --- |
| CR-01 | `cli.py:507-514` wraps `os.kill` in try/except → `ProcessLookupError`→log+`return 1`, `PermissionError`→log+`return 1`. No os.kill path escapes as a traceback. | ✓ |
| WR-01 | `cli.py:489` broadened the PID-read catch from `(FileNotFoundError, ValueError)` to `(ValueError, OSError)`; `FileNotFoundError`/`PermissionError`/`IsADirectoryError` are all `OSError`, so an unreadable PID file safe-fails to 1. | ✓ |
| CR-02 | `pidfile.py:97` delegates to new `_argv_is_weatherbot` (`pidfile.py:100-119`): accepts only when `Path(argv0).name == "weatherbot"` OR `-m` + `weatherbot` appear in early argv fields; the whole-buffer substring scan is gone. | ✓ |

**Decoy trace (CR-02):** `grep\x00weatherbot\x00/etc/hosts` → argv `[grep, weatherbot, /etc/hosts]`, `prog="grep"` ≠ `weatherbot`, and `b"-m" not in argv[1:3]` → returns `False` (REJECTED). `vim .../weatherbot/config.toml`, `tail -f weatherbot.log`, `less weatherbot.log` likewise rejected.
**Real-invocation trace (CR-02):** `/usr/bin/weatherbot\x00run` → `prog="weatherbot"` → `True`. `weatherbot\x00run` → `True`. `/usr/bin/python3\x00-m\x00weatherbot\x00run` → `-m` in argv[1:3] and `weatherbot` in argv[1:4] → `True` (ACCEPTED).

No regressions: full suite **253 passed** (was 248 + 5 new gap-closure tests).

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | After editing config.toml/template and triggering reload via SIGHUP or `weatherbot reload`, the daemon applies the change without restart; a new send-time fires on its new schedule (CFG-01, CFG-02). | ✓ VERIFIED | `run_daemon` poll loop services `reload_requested`, calls `_do_reload(config_path=...)` on the main thread; SIGHUP flag-set-only handler installed before `scheduler.start()`; `_do_reload` PHASE 2 re-reads + diff-reconciles jobs. `reload` subparser registered + dispatched (`cli.py:631-642, 725-726`). `do_reload` sender now safe-fails to 1 on every non-happy branch and sends SIGHUP only after the identity guard (CR-01/CR-02 closed). `test_reload_applies_new_schedule`, `test_sighup_triggers_reload`, `test_reload_cli_signals_pid` + 5 new sender tests pass. |
| 2 | An invalid edit (bad TOML, dup names, unknown token) is rejected: daemon logs reason and keeps running on the previous valid config — never half-applied, even if job re-registration fails midway (CFG-04, CFG-06). | ✓ VERIFIED | `_do_reload` PHASE 1 validates via shared `validate_config_and_templates`; on the catch set logs `reload rejected` and re-raises with holder+jobs untouched. PHASE 2 wraps reconcile in try/except, `holder.replace(old_cfg)` + `_restore_jobs` on throw. Poll loop swallows so a bad edit never crashes the daemon. `test_invalid_reload_keeps_old`, `test_reconcile_failure_rolls_back`, `test_rejected_reload_logs_reason` pass. |
| 3 | Reload reconciles jobs by stable (location, send_time, days) id — adds new, removes deleted/disabled, leaves unchanged; identical config → zero job changes, no duplicate fires (CFG-05). | ✓ VERIFIED | `_reconcile_jobs` diffs `_desired_job_ids` vs live (excluding `__heartbeat__`), `add_job(replace_existing=True)` + `remove_job` for dropped; NO `remove_all_jobs`. Job id `f"{location.name}|{slot.time}|{slot.days}"`. `test_identical_reload_zero_changes`, `test_reconcile_diff` pass. |
| 4 | Exactly-once preserved across reload: changing a slot's name or IANA tz for an already-delivered-today slot does NOT cause duplicate/skipped briefing (CFG-05, HIGHEST RISK). send_time change is by design a NEW slot. | ✓ VERIFIED | Sent-log/alert key moved name→`location.id` at all four store callsites + catchup `was_sent(loc.id,...)` in lockstep. `Location.id` defaults to RAW name → byte-identical key, zero migration. `test_already_sent_slot_not_refired_after_tz_name_change` asserts `claim_slot` LOSES after rename+tz-shift through the REAL claim path; `test_send_time_change_is_new_slot_fires_today_if_ahead` asserts the new-time slot WINS its first claim. Both substantive, both pass. |
| 5 | `weatherbot check-config` loads and fully validates a config edit (parse + unique names + template tokens), reports pass/fail without applying or sending (CFG-08). | ✓ VERIFIED | `check-config` subparser dispatches to `validate_config_and_templates` OFFLINE (`cli.py:709-721`): no Settings/secrets, no `run_self_check`. Validator does TOML parse + pydantic + unique name+id + regex template-token check. `test_check_config_offline_pass/_offline_fail/_no_network` pass. |

**Score:** 5/5 success criteria verified. The two underlying cross-process-sender must-have claims that were falsified at initial verification are now upheld in code.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `weatherbot/ops/pidfile.py` | atomic PID write + read + /proc identity guard | ✓ VERIFIED | `write_pid_atomic` (temp+`os.replace`), `read_pid`, `is_weatherbot_pid` all present and wired. Guard now matches program identity via `_argv_is_weatherbot` (argv0 basename / `-m weatherbot`), substring defect removed (CR-02 closed). |
| `weatherbot/config/loader.py` | validate_config_and_templates shared offline validator + unique-id | ✓ VERIFIED | Called by both check-config and `_do_reload` PHASE 1; `assert_unique_names` extended for id. |
| `weatherbot/config/models.py` | Location.id optional + raw-name after-validator default | ✓ VERIFIED | `id: str | None = None` + `_default_id_from_name` model_validator; frozen intact. |
| `weatherbot/scheduler/daemon.py` | _do_reload + _reconcile_jobs + _restore_jobs + SIGHUP handler + poll loop + PID write/unlink + config_path; id-keyed store callsites | ✓ VERIFIED | All present and wired; PID written at startup, unlinked in finally. |
| `weatherbot/scheduler/catchup.py` | plan_catchup was_sent keyed on loc.id | ✓ VERIFIED | `was_sent(loc.id, slot.time, local_date)`. |
| `weatherbot/cli.py` | check-config + reload subparsers + dispatch; do_reload sender; run threads config_path | ✓ VERIFIED | Subparsers + dispatch + config_path threading correct; `do_reload` os.kill now guarded (`cli.py:507-514`) and PID-read catches `OSError` (`cli.py:489`) — every safe-fail branch returns 1, never a traceback (CR-01/WR-01 closed). |
| `tests/test_reload.py` | apply/reject/rollback/noop/exactly-once/new-slot/SIGHUP/shared-validator + sender safe-fail + guard identity | ✓ VERIFIED | 17 tests, all pass; 5 new tests route through real `do_reload`/`is_weatherbot_pid`. |
| `tests/test_models.py` | Location.id default + explicit-wins + frozen + duplicate-id | ✓ VERIFIED | Full suite green. |
| `tests/test_cli.py` | check-config offline pass/fail + no-network | ✓ VERIFIED | Present + pass. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| cli.py run dispatch | run_daemon | `config_path=args.config` | ✓ WIRED | `cli.py:742-744`. |
| run_daemon poll loop | _do_reload | `if reload_requested.is_set(): clear(); _do_reload(config_path=...)` | ✓ WIRED | daemon poll loop. |
| _do_reload PHASE 1 | validate_config_and_templates | `new_cfg = validate_config_and_templates(config_path)` | ✓ WIRED | shared validator. |
| _reconcile_jobs | APScheduler add_job/remove_job | stable name\|time\|days id, replace_existing=True | ✓ WIRED | diff-reconcile. |
| cli.py do_reload | pidfile guard + os.kill | read_pid → is_weatherbot_pid → guarded os.kill(SIGHUP) | ✓ WIRED | `cli.py:487-516`; os.kill defended, guard matches identity. CR-01/CR-02 closed. |
| cli.py check-config | validate_config_and_templates | try validate except catch-set | ✓ WIRED | `cli.py:709-721`. |
| daemon fire_slot/catchup | store claim/release/record/resolve + was_sent | pass location.id (not name) | ✓ WIRED | All four daemon callsites + catchup use `.id`. |
| Location | self.id default | object.__setattr__ in model_validator(after) | ✓ WIRED | models.py. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Reload sender TOCTOU exit safe-fail | `test_reload_cli_safe_fails_when_target_exits_before_signal` (os.kill→ProcessLookupError) | rc=1, no traceback | ✓ PASS |
| Reload sender unsignalable PID safe-fail | `test_reload_cli_safe_fails_when_not_permitted_to_signal` (os.kill→PermissionError) | rc=1, no traceback | ✓ PASS |
| Reload sender unreadable PID file safe-fail | `test_reload_cli_safe_fails_on_unreadable_pid_file` (IsADirectoryError on read) | rc=1, no traceback | ✓ PASS |
| PID guard rejects substring decoys | `test_is_weatherbot_pid_rejects_unrelated_substring_match` (vim/tail/grep/less) | all False | ✓ PASS |
| PID guard accepts real invocations | `test_is_weatherbot_pid_accepts_real_invocations` (/usr/bin/weatherbot, bare, python -m) | all True | ✓ PASS |
| Reload happy path | `test_reload_cli_signals_pid` | rc=0, SIGHUP recorded | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist; phase uses pytest as the runnable check.

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Full suite | `uv run pytest -q` | 253 passed in 11.08s | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| CFG-01 | 09-01, 09-05 | Edit config/templates, apply without restart | ✓ SATISFIED | SC#1; poll loop + _do_reload re-read. |
| CFG-02 | 09-01, 09-03, 09-05 | Trigger via SIGHUP and/or `weatherbot reload` | ✓ SATISFIED | SC#1; sender failure-mode robustness now upheld (CR-01/CR-02/WR-01 closed). |
| CFG-04 | 09-01, 09-02, 09-05 | Invalid edit rejected, keep-old, all-or-nothing | ✓ SATISFIED | SC#2; PHASE 1 reject + PHASE 2 rollback. |
| CFG-05 | 09-01, 09-04, 09-05 | Re-register jobs, exactly-once preserved | ✓ SATISFIED | SC#3 + SC#4; stable-id reconcile + id-keyed sent-log. |
| CFG-06 | 09-01, 09-05 | Each outcome (applied/rejected) logged | ✓ SATISFIED | `reload applied`/`reload rejected`. |
| CFG-08 | 09-01, 09-02, 09-03 | `check-config` dry-run validate without apply/send | ✓ SATISFIED | SC#5; offline validator, zero network. |

All six requirement IDs (CFG-01/02/04/05/06/08) accounted for and present in REQUIREMENTS.md mapped to Phase 9. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| weatherbot/ops/pidfile.py | 131-132 | `/proc`-absent sentinel returns `b"weatherbot"` (fails OPEN) | ⚠️ Warning (WR-04) | On a non-Linux host (no `/proc`) the guard becomes a no-op signaling any PID. Not in the gap-closure scope (was a Warning, not a Blocker, at initial verification) and the project target host is Linux/systemd (CLAUDE.md). Advisory hardening only. |
| weatherbot/scheduler/daemon.py | rollback `_restore_jobs` | re-invokes the same `_register_jobs` that failed; swallowed with `_log.exception` | ⚠️ Warning (WR-02) | A persistent `_register_jobs` failure can leave the live job table half-rebuilt; config holder IS correctly restored. Advisory. |
| tests/test_reload.py | `test_reconcile_failure_rolls_back` | patches `_register_jobs` for the whole reload | ⚠️ Warning (IN-04) | Restore path not genuinely exercised. Advisory test-quality note. |

No TBD/FIXME/XXX debt markers in phase-modified files (cli.py, pidfile.py, test_reload.py confirmed clean).

### Human Verification Required

None. All five success criteria are programmatically verified, and both prior blockers (CR-01/CR-02) are codebase-observable and confirmed closed via the real code paths exercised by 5 new tests. No visual/real-time/external-service behavior requires human testing for status determination.

### Gaps Summary

No gaps. Phase goal achieved. The reload engine (validate-or-keep-old, atomic holder swap, diff-reconcile, exactly-once across name/tz edits) was already sound at initial verification; the two cross-process-sender blockers are now closed:

1. **CR-01/WR-01 (closed)** — `do_reload`'s `os.kill` is wrapped in try/except for `ProcessLookupError` and `PermissionError` (each logs + returns 1), and the PID-read catch is broadened to `OSError` so an unreadable PID file safe-fails to 1. No os.kill or PID-read path can escape as a traceback; the documented "all safe-fail branches return 1" contract holds.
2. **CR-02 (closed)** — `is_weatherbot_pid` now matches program identity via `_argv_is_weatherbot` (argv0 basename == `weatherbot`, or `python -m weatherbot`), so an unrelated recycled-PID process whose argv merely contains `weatherbot` (vim/tail/grep/less) is REJECTED, while genuine `/usr/bin/weatherbot run`, bare `weatherbot run`, and `python -m weatherbot run` are accepted. SIGHUP can never be delivered to a recycled/unrelated PID.

253 tests pass (248 prior + 5 new gap-closure tests, all routing through production code). Two advisory Warnings remain (WR-04 `/proc`-absent fail-open, WR-02 rollback-restore, IN-04 test-coverage) — these were never blockers and are out of the gap-closure scope; recommended as optional follow-up hardening, not blocking.

---

_Verified: 2026-06-16T12:30:00Z_
_Verifier: Claude (gsd-verifier)_
_Re-verification: gap closure confirmed (CR-01/WR-01 + CR-02)_
