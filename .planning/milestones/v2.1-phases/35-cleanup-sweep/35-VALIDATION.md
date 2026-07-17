---
phase: 35
slug: cleanup-sweep
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-13
---

# Phase 35 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `35-RESEARCH.md` §Validation Architecture. Anchor invariant guarded by the full suite:
> "the morning briefing always goes out, exactly once."

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-cov 7.1.0 + syrupy 5.3.4 (`pyproject.toml:40`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths=["tests"]`, `addopts="-ra"` |
| **Quick run command** | `uv run pytest tests/<module>.py -q` (per touched module, < 30s) |
| **Full suite command** | `uv run pytest -q` (878 tests, ~38s) |
| **Estimated runtime** | ~38 seconds (full) |

> **Syrupy quirk:** the report may print "2 snapshots failed" while exiting 0 — trust the exit
> code and the actual `.ambr` diff (project memory). Only intentional render changes (F105/F85)
> should move snapshots.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/<module>.py -q` (the touched module)
- **After every plan wave:** Run `uv run pytest -q` (full suite — the spine invariant is cross-cutting; cheap at ~38s)
- **Before `/gsd-verify-work`:** Full suite must be green (exit 0)
- **Max feedback latency:** ~38 seconds

---

## Per-Task Verification Map

> Plans 35-01 … 35-09 are authored. Each behavior-changing fix maps to a regression test (D-06);
> each dead-code removal maps to a negative-grep assert (35-01 Wave-0 gate); each accepted finding
> maps to an in-code `# ACCEPTED (F##, v2.1)` annotation + Disposition Ledger row (35-09). The
> requirement→proof rows below are the contract the plan tasks satisfy; per-plan task IDs live in
> the PLAN.md `<verify>`/`must_haves` blocks (single source of truth — not duplicated here).

| Req / Criterion | Behavior to prove | Proof type | Automated command / check | Status |
|-----------------|-------------------|------------|---------------------------|--------|
| SC-1 / HARD-CLEAN-01 | Dead `emit_online`/`_do_reload` gone (F16, pending Open-Q1) | grep-assert zero defs | `! grep -qE "def emit_online\|def _do_reload" weatherbot/scheduler/daemon.py` | ⬜ pending |
| SC-1 / HARD-CLEAN-01 | Dead WB `_argv_is_weatherbot` copy gone (F46) | grep-assert + removed test | `! grep -rq "_argv_is_weatherbot" weatherbot/ tests/` | ⬜ pending |
| SC-1 / HARD-CLEAN-01 | Dead discarded `is_transient(exc)` call gone (F92) | read selfcheck except arm | manual read of `ops/selfcheck.py` | ⬜ pending |
| SC-1 / HARD-CLEAN-01 | Dead `verbose` param gone (F76) | grep-assert absent from `run_weather` sig | read `weatherbot/cli.py` `run_weather` | ⬜ pending |
| SC-1 / HARD-CLEAN-01 | No misleading passthrough docstrings (F104/F66) | manual read (F104 already clean) | n/a (doc) | ⬜ pending |
| SC-1 / HARD-CLEAN-01 | No `_local_date_iso` copies (F65/F69, already fixed@32) | negative-grep gate (exists) | `test_import_hygiene.py:104-119` | ✅ green |
| SC-2 / HARD-CLEAN-02 | Every behavior-changing fix has a regression test | per-fix red-against-old test | `uv run pytest tests/<module> -q` | ⬜ pending |
| SC-2 / HARD-CLEAN-02 | Every accepted finding carries `# ACCEPTED (F##, v2.1)` at its site | grep-assert annotation count | `grep -rc "# ACCEPTED (F" weatherbot/` == accepted count | ⬜ pending |
| SC-2 (no silent debt) | Every in-scope WB finding has a disposition | ledger table complete | every WB `F##` appears in Disposition Ledger | ⬜ pending |
| SC-3 | v2.1 ledger reconciles; 17 hub findings confirmed out | Disposition Ledger + handoff confirm | read `WHOLE-PROJECT-REVIEW.md` ledger + `HUB-FINDINGS-HANDOFF.md` | ⬜ pending |
| SC-3 (hub untouched) | No hub-path edits in the sweep | diff-assert | no `yahir_reusable_bot/` or `../Reusable/` files in the phase diff | ⬜ pending |
| Anchor invariant | Briefing spine unchanged | full suite green | `uv run pytest -q` → exit 0 | ✅ 878 baseline |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_dead_code_removed.py` — one consolidated negative-grep gate asserting the removed
      dead symbols stay gone (F16 `emit_online`/`_do_reload`, F46 `_argv_is_weatherbot`, F76
      `verbose`, F92 discarded call). Analog: `test_import_hygiene.py:104-119`.
- [ ] Regression tests for each behavior-CHANGING fix actually chosen (candidates: F60, F70, F74,
      F75, F105, F85, F68; plus F71/F79/F82 only if fixed). Slot into the code's existing test
      module using `34-PATTERNS.md` shapes — no new fixtures needed (`tmp_db`, `load_fixture`,
      `_loc(id=…)` all exist).
- [ ] (optional) Annotation-presence check asserting each accepted `F##` has its `# ACCEPTED
      (F##, v2.1)` marker.
- Framework install: none — pytest/syrupy already present and green.

*No new fixtures or framework work required (per `34-PATTERNS.md` "No Analog Found: None").*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Ledger reconciliation completeness (every WB F## dispositioned) | SC-3 / HARD-CLEAN-02 | Reading a review doc's completeness is a doc-audit, not a runtime behavior | Read `WHOLE-PROJECT-REVIEW.md` §Disposition Ledger; confirm every WB `F##` from §Low/§Cleanup has FIXED@/ACCEPTED/DEFERRED; confirm 17 hub findings marked HUB(out-of-scope) + the 17-vs-18 note |
| Docstring accuracy (F104/F66) | SC-1 / HARD-CLEAN-01 | Prose correctness isn't machine-assertable | Read the specific docstrings; confirm they no longer claim behavior the code doesn't do |

*Behavior-changing code fixes all have automated regression coverage; only doc/ledger completeness is manual.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (dead-code grep gate in 35-01 + per-fix regression tests)
- [x] No watch-mode flags
- [x] Feedback latency < 40s (~38s full suite)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-13
