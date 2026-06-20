---
phase: 8
slug: configholder-fire-slot-reads-from-holder-refactor
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-15
validated: 2026-06-15
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
| SC#1a | 08-03 | 0/1 | SC#1 | T-08-05 | `current()` returns held config | unit | `pytest tests/test_config_holder.py::test_current_returns_held -x` | ✓ | ✅ green |
| SC#1b | 08-03 | 1 | SC#1 | T-08-06 | `replace()` rebinds | unit | `pytest tests/test_config_holder.py::test_replace_rebinds -x` | ✓ | ✅ green |
| SC#1c | 08-03 | 0/1 | SC#1 | T-08-05/06 | concurrent read/swap never tears | concurrency | `pytest tests/test_config_holder.py::test_concurrent_read_swap_safe -x` | ✓ | ✅ green |
| SC#2a | 08-04 | 1 | SC#2 | T-08-08 | in-flight job keeps original snapshot | integration | `pytest tests/test_config_holder.py::test_inflight_job_keeps_snapshot -x` | ✓ | ✅ green |
| SC#2b | 08-04 | 1 | SC#2 / D-04 | T-08-09 | unchanged job renders NEW config after replace | integration | `pytest tests/test_config_holder.py::test_unchanged_job_renders_after_replace -x` | ✓ | ✅ green |
| D-01 | 08-04 | 1 | D-01 | — | explicit `config=` override wins over holder | unit | `pytest tests/test_config_holder.py::test_config_override_wins -x` | ✓ | ✅ green |
| D-02 | 08-02 | 0/1 | D-02 | T-08-03 | all 5 models reject mutation (`pydantic.ValidationError`) | unit | `pytest tests/test_models.py::test_frozen_rejects_mutation -x` (5 params: Schedule/Location/WebhookIdentity/Reliability/Config) | ✓ | ✅ green |
| SC#3 | 08-04 | 1 | SC#3 | T-08-04 | daemon behaves identically; no hashing regression | full suite | `.venv/bin/python -m pytest -q` | 226 | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Concurrency-test guidance (SC#1c):** spawn ~8 reader threads (matching the `max_workers=10` context) looping `assert holder.current() is config_a or holder.current() is config_b`, plus one writer alternating `replace(config_a)/replace(config_b)` for a few thousand iterations. Use `is`-identity checks (the holder hands out the shared reference, no copy). A torn read is impossible by construction (atomic store), so this test documents/guards the invariant — keep it short and deterministic (bounded iterations, `join()` all threads, fail on any exception via a shared error list).

**Mid-job snapshot test (SC#2a):** inject a fake `send_now` (suite already does this — `tests/test_reliability.py` `_patch_send_now`) that on first call records the `config` it received, signals the test, and blocks on an event; the test then calls `holder.replace(config_b)`, releases the block, and asserts the recorded config `is config_a`. Proves single-read-per-fire without real sleeps.

---

## Wave 0 Requirements

- [x] `tests/test_config_holder.py` — NEW file: holder unit tests (current / replace / override), concurrency safety, mid-job snapshot retention, unchanged-job-renders-after-replace (covers SC#1 / SC#2 / D-01 / D-04) — 6 tests present, all green
- [x] `tests/test_models.py` — EXTEND: `frozen=True` mutation-guard test asserting `pydantic.ValidationError` on each of the 5 models (covers D-02) — `test_frozen_rejects_mutation` parametrized ×5, all green
- [x] No new fixtures — reuses `tmp_db` (conftest) and `monkeypatch`
- [x] No framework install — pytest already configured

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | All phase behaviors have automated verification. |

*All phase behaviors have automated verification — this is a pure backend refactor with deterministic, threadable tests.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (`tests/test_config_holder.py`, `tests/test_models.py` extension)
- [x] No watch-mode flags
- [x] Feedback latency < 5s (targeted run `11 passed in 2.34s`)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ✅ validated 2026-06-15 — all 8 requirements automated and green.

---

## Validation Audit 2026-06-15

| Metric | Count |
|--------|-------|
| Requirements audited | 8 |
| COVERED (automated, green) | 8 |
| PARTIAL | 0 |
| MISSING | 0 |
| Gaps found | 0 |
| Resolved | 0 (no gaps to fill) |
| Escalated | 0 |

**Evidence:** Targeted run `tests/test_config_holder.py` + `test_frozen_rejects_mutation` → `11 passed in 2.34s`. Full suite → `226 passed in 5.92s`. `test_frozen_rejects_mutation` confirmed parametrized over all 5 models (Schedule/Location/WebhookIdentity/Reliability/Config). No auditor spawn required — zero gaps. State A audit reconciled the plan-time draft (all-pending) against the executed, fully-green implementation.
