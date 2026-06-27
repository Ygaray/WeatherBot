---
phase: 20
slug: isolation-hardening-polish
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-26
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `20-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (existing) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/test_panel.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~tens of seconds (includes a live-scheduler timing test) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_panel.py -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 20-01-01 | 01 | 1 | PANEL-11 | — | A hanging panel callback never delays/drops/stops a concurrently scheduled briefing | integration (live scheduler) | `uv run pytest tests/test_panel.py -k hanging -q` | ❌ W0 | ⬜ pending |
| 20-02-01 | 02 | 2 | PANEL-12/13 | — | Indicator line, emoji, and Updated stamp survive every render incl. clone path | unit/snapshot | `uv run pytest tests/test_panel.py tests/test_bot.py -q` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_panel.py` — hanging-callback live-scheduler isolation test (new) for PANEL-11
- [ ] `tests/test_panel.py` — D-08b executor-sharing audit assertion

*Existing infrastructure (pytest + the Phase-15 live-scheduler pattern) covers all remaining phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Emoji glyphs render legibly on the operator's Discord client (A1) | PANEL-13a | Pixel rendering is client-specific; not assertable in code | Open the live panel; confirm each command/forecast button shows its locked emoji + text |
| `<t:…:R>` stamp self-ages and snaps to "now" on in-place edit (A2) | PANEL-13b | Discord client re-renders relative time; not observable in unit tests | Trigger a render, wait ~2 min, observe stamp age; tap again, confirm it snaps back |
| Selected-location indicator visibly tracks dropdown changes | PANEL-12 | Visual confirmation on live panel | Change dropdown; confirm `📍` line + dropdown highlight follow |

*Mechanism for all three is verifiable in automated tests; only the on-device visual confirmation is deferred to Gate-2 human UAT.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
