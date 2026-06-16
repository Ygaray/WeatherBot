---
phase: 9
slug: reload-engine-explicit-trigger
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-15
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
| (TBD) | — | 0 | CFG-05 | — | **HIGHEST RISK** — reload a tz/name/send_time change on an ALREADY-SENT slot → no duplicate, no skip (Pitfall #8) | integration | `pytest tests/test_reload.py::test_reload_changed_slot_already_sent_no_refire -x` | ❌ W0 | ⬜ pending |
| (TBD) | — | 0 | CFG-04, CFG-06 | — | Injected job-registration failure mid-reload → OLD schedule fully intact, keep-old, reason logged (Pitfall #6) | integration | `pytest tests/test_reload.py::test_reload_rollback_on_job_failure -x` | ❌ W0 | ⬜ pending |
| (TBD) | — | 0 | CFG-05 | — | Identical-config reload → zero job changes, no duplicate fires (Pitfall #7) | integration | `pytest tests/test_reload.py::test_reload_identical_config_noop -x` | ❌ W0 | ⬜ pending |
| (TBD) | — | 0 | CFG-01, CFG-02 | — | Edit + SIGHUP/`reload` → applied without restart; new send-time fires on new schedule | integration | `pytest tests/test_reload.py -x` | ❌ W0 | ⬜ pending |
| (TBD) | — | 0 | CFG-08 | — | `check-config` offline-validates (parse + unique id/name + template tokens), applies/sends nothing, no network | unit | `pytest tests/test_cli.py -k check_config -x` | ❌ W0 | ⬜ pending |
| (TBD) | — | 0 | CFG-01 | — | Optional `Location.id` defaults to raw `name`; sent-log key byte-identical for un-`id`'d configs (zero migration) | unit | `pytest tests/test_models.py -k location_id -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_reload.py` — NEW: reload engine integration tests (apply, reject/keep-old, rollback, identical-noop, exactly-once-on-change). Reuse existing daemon/store test fixtures (`tmp_db`, `monkeypatch`, fake client/channel).
- [ ] Extend `tests/test_models.py` — optional `Location.id` default-from-name + unique-id validation.
- [ ] Extend `tests/test_cli.py` — `check-config` offline subcommand exit matrix.
- [ ] No framework install — pytest already configured. No new dependencies (RESEARCH: stdlib `signal`/`os`/`tomllib`, APScheduler 3.11.2 already pinned).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `systemctl reload` parity | — | Out of scope (D-04: no ExecReload); reload stays always-ready | N/A — reload via `weatherbot reload` (PID file + SIGHUP) is automatable; systemd integration deliberately not wired |

*Most behaviors have automated verification — this is a backend daemon/CLI phase with deterministic, threadable tests. The one out-of-band item (systemd) is explicitly out of scope per D-04.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`tests/test_reload.py`, model/CLI extensions)
- [ ] No watch-mode flags
- [ ] Feedback latency < 6s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
