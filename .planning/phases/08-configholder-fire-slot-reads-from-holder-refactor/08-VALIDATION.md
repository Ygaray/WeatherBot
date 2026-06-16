---
phase: 8
slug: configholder-fire-slot-reads-from-holder-refactor
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-15
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pinned in `pyproject.toml` `[tool.pytest.ini_options]`) |
| **Config file** | `pyproject.toml` — `testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"` |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_config_holder.py tests/test_models.py -x` |
| **Full suite command** | `.venv/bin/python -m pytest -q` |
| **Estimated runtime** | ~5 seconds (baseline `215 passed in 4.52s`) |

**Baseline correction:** the "186 tests" figure in CONTEXT/ROADMAP is the v1.0 close count; Phases 6–7 added 29 more. The real constraint (ROADMAP SC#3 generalized) is **all 215 existing tests stay green**.

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/test_config_holder.py tests/test_models.py -x`
- **After every plan wave:** Run `.venv/bin/python -m pytest -q` (all 215 + new)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 08-W0 | — | 0 | SC#1/SC#2/D-01/D-04 | — | N/A | unit/integration | `pytest tests/test_config_holder.py` (stubs RED) | ❌ W0 | ⬜ pending |
| 08-W0 | — | 0 | D-02 | — | mutation rejected | unit | `pytest tests/test_models.py::test_frozen_rejects_mutation` (stub RED) | ❌ W0 | ⬜ pending |
| SC#1a | TBD | — | SC#1 | — | `current()` returns held config | unit | `pytest tests/test_config_holder.py::test_current_returns_held -x` | ❌ W0 | ⬜ pending |
| SC#1b | TBD | — | SC#1 | — | `replace()` rebinds | unit | `pytest tests/test_config_holder.py::test_replace_rebinds -x` | ❌ W0 | ⬜ pending |
| SC#1c | TBD | — | SC#1 | — | concurrent read/swap never tears | concurrency | `pytest tests/test_config_holder.py::test_concurrent_read_swap_safe -x` | ❌ W0 | ⬜ pending |
| SC#2a | TBD | — | SC#2 | — | in-flight job keeps original snapshot | integration | `pytest tests/test_config_holder.py::test_inflight_job_keeps_snapshot -x` | ❌ W0 | ⬜ pending |
| SC#2b | TBD | — | SC#2 / D-04 | — | unchanged job renders NEW config after replace | integration | `pytest tests/test_config_holder.py::test_unchanged_job_renders_after_replace -x` | ❌ W0 | ⬜ pending |
| D-01 | TBD | — | D-01 | — | explicit `config=` override wins over holder | unit | `pytest tests/test_config_holder.py::test_config_override_wins -x` | ❌ W0 | ⬜ pending |
| D-02 | TBD | — | D-02 | — | all 5 models reject mutation (`pydantic.ValidationError`) | unit | `pytest tests/test_models.py::test_frozen_rejects_mutation -x` | extend | ⬜ pending |
| SC#3 | TBD | — | SC#3 | — | daemon behaves identically; no hashing regression | full suite | `.venv/bin/python -m pytest -q` | existing 215 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Concurrency-test guidance (SC#1c):** spawn ~8 reader threads (matching the `max_workers=10` context) looping `assert holder.current() is config_a or holder.current() is config_b`, plus one writer alternating `replace(config_a)/replace(config_b)` for a few thousand iterations. Use `is`-identity checks (the holder hands out the shared reference, no copy). A torn read is impossible by construction (atomic store), so this test documents/guards the invariant — keep it short and deterministic (bounded iterations, `join()` all threads, fail on any exception via a shared error list).

**Mid-job snapshot test (SC#2a):** inject a fake `send_now` (suite already does this — `tests/test_reliability.py` `_patch_send_now`) that on first call records the `config` it received, signals the test, and blocks on an event; the test then calls `holder.replace(config_b)`, releases the block, and asserts the recorded config `is config_a`. Proves single-read-per-fire without real sleeps.

---

## Wave 0 Requirements

- [ ] `tests/test_config_holder.py` — NEW file: holder unit tests (current / replace / override), concurrency safety, mid-job snapshot retention, unchanged-job-renders-after-replace (covers SC#1 / SC#2 / D-01 / D-04)
- [ ] `tests/test_models.py` — EXTEND: add `frozen=True` mutation-guard test asserting `pydantic.ValidationError` (type `frozen_instance`) on each of the 5 models (covers D-02)
- [ ] No new fixtures — reuse `tmp_db` / `load_fixture` (conftest) and the existing `_FakeClient` / `_FakeChannel` / `_patch_send_now` helpers in `test_scheduler.py` / `test_reliability.py`
- [ ] No framework install — pytest already configured

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | All phase behaviors have automated verification. |

*All phase behaviors have automated verification — this is a pure backend refactor with deterministic, threadable tests.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`tests/test_config_holder.py`, `tests/test_models.py` extension)
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
