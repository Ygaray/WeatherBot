---
phase: 21
slug: characterization-golden-test-harness
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-27
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Detailed SC→signal mapping lives in `21-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (+ syrupy, pytest-cov — installed in Wave 0) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`, new `[tool.coverage.*]`) |
| **Quick run command** | `uv run pytest <new golden test file> -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~30–60 seconds (652 existing + new goldens) |

---

## Sampling Rate

- **After every task commit:** Run the new golden test file (`uv run pytest tests/test_golden_*.py -q`)
- **After every plan wave:** Run the full suite (`uv run pytest -q`)
- **Before `/gsd-verify-work`:** Full suite must be green; `--snapshot-update` must produce an empty diff
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

> Filled by the planner from RESEARCH.md § Validation Architecture (SC→test map). Each golden
> case is verifiable via `uv run pytest <case> -q` and an `assert value == snapshot` comparison;
> the coverage audit via `--cov-branch --cov-report=term-missing`.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 21-01-01 | 01 | 0 | BHV-01 | — | N/A (additive test infra) | unit | `uv run python -c "import syrupy, pytest_cov"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `uv add --dev syrupy pytest-cov` — snapshot + branch-coverage tooling (currently uninstalled)
- [ ] Confirm `time-machine` reaches `discord.utils.utcnow` (open question O1 from RESEARCH.md; monkeypatch fallback documented)
- [ ] `[tool.coverage.run]`/`[tool.coverage.report]` block in `pyproject.toml` (branch=true, source = 6 move-path packages)

*Existing `tests/conftest.py` fixtures + recorded forecast fixtures cover the render/DB/schedule seams.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| — | — | — | — |

*All phase behaviors have automated verification — the golden suite IS the automated oracle.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
