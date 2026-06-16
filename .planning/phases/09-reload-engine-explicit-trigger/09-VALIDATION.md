---
phase: 9
slug: reload-engine-explicit-trigger
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-15
validated: 2026-06-16
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pinned in `pyproject.toml` `[tool.pytest.ini_options]`) |
| **Config file** | `pyproject.toml` — `testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"` |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_reload.py tests/test_config_holder.py -x` |
| **Full suite command** | `.venv/bin/python -m pytest -q` |
| **Estimated runtime** | ~6 seconds (baseline `226 passed in 5.92s` at Phase 8 close) |

**Baseline:** all 226 existing tests stay green (ROADMAP SC generalized — no regression in the v1.0 scheduled path or the Phase 6–8 additions).

---

## Sampling Rate

- **After every task commit:** Run the quick command (reload + holder tests)
- **After every plan wave:** Run `.venv/bin/python -m pytest -q` (all 226 + new)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~6 seconds

---

## Per-Task Verification Map

> Populated by the planner / `/gsd-validate-phase` from the RESEARCH "Validation Architecture"
> section. The phase's load-bearing tests (from CONTEXT + RESEARCH):

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| reload-engine | 09-01 (RED) → 09-04 (id key) → 09-05 (engine) | 0 | CFG-05 | — | **HIGHEST RISK** — reload a **tz/name** change on an ALREADY-SENT slot → no duplicate, no skip (Pitfall #8). (A send_time change is a NEW slot — fires today if ahead — covered separately, per D-02.) | integration | `pytest tests/test_reload.py::test_already_sent_slot_not_refired_after_tz_name_change tests/test_reload.py::test_send_time_change_is_new_slot_fires_today_if_ahead -x` | ✅ | ✅ green |
| reload-engine | 09-01 (RED) → 09-05 | 0 | CFG-04, CFG-06 | T-09-06 | Injected job-registration failure mid-reload → OLD schedule fully intact, keep-old, reason logged (Pitfall #6) | integration | `pytest tests/test_reload.py::test_reconcile_failure_rolls_back tests/test_reload.py::test_rejected_reload_logs_reason -x` | ✅ | ✅ green |
| reload-engine | 09-01 (RED) → 09-05 | 0 | CFG-05 | — | Identical-config reload → zero job changes, no duplicate fires (Pitfall #7) | integration | `pytest tests/test_reload.py::test_identical_reload_zero_changes -x` | ✅ | ✅ green |
| reload-engine | 09-01 (RED) → 09-03 (CLI) → 09-05 (engine/SIGHUP) | 0 | CFG-01, CFG-02 | T-09-06, T-09-07 | Edit + SIGHUP/`reload` → applied without restart; new send-time fires on new schedule; PID-file sender safe-fails on stale/recycled PID | integration | `pytest tests/test_reload.py -k "reload_applies_new_schedule or sighup_triggers_reload or reload_cli or reconcile_diff or check_config_and_reload_share_validation" -x` | ✅ | ✅ green |
| check-config | 09-02 (validator) → 09-03 (CLI) | 0 | CFG-08 | — | `check-config` offline-validates (parse + unique id/name + template tokens), applies/sends nothing, no network | unit | `pytest tests/test_cli.py -k check_config -x` | ✅ | ✅ green |
| location-id | 09-02 | 0 | CFG-01 | T-09-05 | Optional `Location.id` defaults to raw `name`; sent-log key byte-identical for un-`id`'d configs (zero migration) | unit | `pytest tests/test_models.py -k location_id -x` | ✅ | ✅ green |
| pid-guard | 09-01 (RED) → 09-09 (gap-close) | 0 | CFG-02 | CR-01/WR-01, CR-02 | PID-file sender guards os.kill TOCTOU + OSError, matches on program identity not substring (no signal to recycled/unrelated PID) | integration | `pytest tests/test_reload.py -k "safe_fails or is_weatherbot_pid" -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Audit result (2026-06-16):** all 6 load-bearing requirement rows COVERED by green automated tests; the security-hardening row (pid-guard) added from the Phase-9 threat verification (commit `84162da`). Full suite **253 passed in 5.21s**, zero gaps, zero manual-only escalations.

---

## Wave 0 Requirements

- [x] `tests/test_reload.py` — NEW: reload engine integration tests (apply, reject/keep-old, rollback, identical-noop, exactly-once-on-change, SIGHUP, reload-CLI, diff-summary/reason logs, PID-guard safe-fail). 17 node IDs, all green.
- [x] Extend `tests/test_models.py` — optional `Location.id` default-from-name + unique-id validation (4 tests, green).
- [x] Extend `tests/test_cli.py` — `check-config` offline subcommand exit matrix (3 tests, green).
- [x] No framework install — pytest already configured. No new dependencies (`uv.lock` unchanged; stdlib `signal`/`os`/`tomllib`, APScheduler 3.11.2 already pinned).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `systemctl reload` parity | — | Out of scope (D-04: no ExecReload); reload stays always-ready | N/A — reload via `weatherbot reload` (PID file + SIGHUP) is automatable; systemd integration deliberately not wired |

*Most behaviors have automated verification — this is a backend daemon/CLI phase with deterministic, threadable tests. The one out-of-band item (systemd) is explicitly out of scope per D-04.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (`tests/test_reload.py`, model/CLI extensions)
- [x] No watch-mode flags
- [x] Feedback latency < 6s (full suite 5.21s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated 2026-06-16 — all requirements have automated verification, zero gaps.

---

## Validation Audit 2026-06-16

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Pre-execution draft reconciled against the shipped phase. All 6 load-bearing requirement
rows mapped to green test node IDs (verified on disk, full suite **253 passed in 5.21s**).
One security-hardening row (`pid-guard`, threat verification commit `84162da`) added.
No tests generated — the executing plans (09-01 RED scaffold → 09-05 engine) already
landed every test the validation plan required. Phase is **Nyquist-compliant**.
