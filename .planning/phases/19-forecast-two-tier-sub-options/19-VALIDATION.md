---
phase: 19
slug: forecast-two-tier-sub-options
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-26
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/test_panel.py tests/test_dispatch.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_panel.py tests/test_dispatch.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | PANEL-07 | T-19-01 / — | {expected secure behavior or "N/A"} | unit | `{command}` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*(Populated by the planner / Nyquist auditor against the Validation Architecture section of 19-RESEARCH.md — see the 3 success criteria: reveal/collapse routing, shared-dispatch parity, build-time layout assertion.)*

---

## Wave 0 Requirements

- [ ] `tests/test_panel.py` — reveal/collapse + forecast-variant routing + layout-assertion (fits/overflow) stubs for PANEL-07
- [ ] `tests/test_dispatch.py` — `flags=` seam stubs (byte-identical when `flags=None`; pre-built flags path)

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Discord reveal/collapse + post-restart tap routing on a revealed panel | PANEL-07 | Requires a live Discord client + bot restart; Gate-2 milestone-close item | Summon panel, tap Forecast, tap a variant, restart bot, tap a previously-revealed variant button — confirm it still routes and collapses |

*Discord-interaction behaviors are exercised by unit tests against the callbacks/seams; the live end-to-end tap is a deferred Gate-2 milestone obligation.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
