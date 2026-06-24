---
phase: 17
slug: minimal-persistent-panel-core-wiring
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-23
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/test_panel.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_panel.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 0 | PANEL-02..08 | — | N/A | unit | `uv run pytest tests/test_panel.py -q` | ❌ W0 | ⬜ pending |

*The planner fills the full per-task map during planning. Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_panel.py` — stubs for PANEL-02/-03/-04/-05/-06/-08 (panel construction, dropdown re-derivation, selected-location hold, defer/edit ack, in-place render, operator reject)
- [ ] `tests/conftest.py` — reuse existing fixtures; add panel/interaction fakes if needed

*Existing pytest infrastructure covers framework; Wave 0 adds the panel test surface.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Discord 3-second ack under cold-cache fetch | PANEL-05 | Real Discord interaction latency cannot be synthesized in pytest | Operator taps a command button on the live panel during a cold-cache fetch; confirm no "This interaction failed" toast and the "⏳ Fetching…" cue appears in-place |
| Non-operator ephemeral reject visibility | PANEL-08 | Ephemeral message visibility is a Discord client-side rendering behavior | A second (non-operator) user taps the panel; confirm they see a generic ephemeral reject and the shared panel is unchanged |

*Mechanism for both is unit-tested (defer/edit call sequence; interaction_check returns False + logs); only the live Discord-rendered result is deferred to Gate-2 human UAT.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
