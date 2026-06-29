---
phase: 28
slug: physical-repo-split-uv-git-dependency-extension-guide
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-29
---

# Phase 28 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (uv-managed) |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest -q` |
| **Full suite command** | `uv run pytest` (the standing 649-suite + Phase-21 goldens) |
| **Estimated runtime** | ~30–60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q`
- **After every plan wave:** Run `uv run pytest` (full suite + goldens byte-identical)
- **Before `/gsd-verify-work`:** Full suite + Phase-21 goldens green; `uv build --no-sources` clean; clean-venv `uv sync --frozen` install gate passes
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

> Filled by the planner / Nyquist auditor from PLAN.md tasks. Anchors: the byte-identical golden oracle (Phase-21 embeds/CLI/schedule/DB-rows/custom_id/exception-identity) re-run from the consuming app against the pinned module; the `grimp`/litmus import-hygiene gate re-scoped across the repo boundary; the `uv build --no-sources` leak gate; the clean-venv `uv sync --frozen` installed-artifact gate.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 28-01-01 | 01 | 0 | PKG-02 | — | N/A | integration | `uv build --no-sources` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> Confirmed by research (28-RESEARCH.md Open Questions / Wave-0 gap list):

- [ ] Spike: install the module from a throwaway git tag into a scratch venv and `cat` its `direct_url.json` to confirm a uv **git** install (not editable) populates `vcs_info.commit_id` before wiring the startup-version-log.
- [ ] Re-scope/retarget `tests/test_import_hygiene.py` self-proofs that import `weatherbot` by name (Pitfall 6) — these break once `weatherbot` is no longer in the module's tree.
- [ ] Remove the now-external `yahir_reusable_bot` entry from the app's `[tool.coverage.run] source` (Pitfall 5, pyproject.toml line ~57).

*Existing pytest infrastructure otherwise covers all phase requirements (no new framework).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live `yahir-mint` `sudo systemctl restart weatherbot` against the pinned module sha; every panel button/dropdown still routes; correct default location | PKG-02 (SC#3) | Secure host action + live Discord gateway interaction the tooling cannot synthesize — deferred to Gate-2 (Two-Gate UAT policy). The *mechanism* (startup-version-log line, persistent-view re-bind, custom_id contract) and *data-level* checks (clean-venv `uv sync --frozen`, suite/goldens byte-identical, `direct_url.json` sha) ARE automated in Gate-1. | After repin: push module tag → host pull → `uv sync --frozen` → `sudo systemctl restart weatherbot` → confirm the startup-version-log line announces the deployed sha → tap each panel button/dropdown → confirm no "interaction failed" and correct default location. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
