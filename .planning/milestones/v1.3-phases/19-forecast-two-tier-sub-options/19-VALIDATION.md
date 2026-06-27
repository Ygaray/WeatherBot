---
phase: 19
slug: forecast-two-tier-sub-options
status: draft
nyquist_compliant: true
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
| 19-01-01 | 01 | 1 | PANEL-07 | T-19-01-01/02/03 | flags= passthrough skips parse; flags=None byte-identical (D-01/D-02) | unit | `uv run pytest "tests/test_dispatch.py::test_dispatch_spec_flags_passthrough_skips_parse" "tests/test_dispatch.py::test_dispatch_spec_flags_none_is_byte_identical" -q` | ❌ W0 | ⬜ pending |
| 19-01-02 | 01 | 1 | PANEL-07 | T-19-01-01/02 | additive seam, parse path byte-identical; anti-drift suite green (D-02) | unit | `uv run pytest tests/test_dispatch.py tests/test_bot.py tests/test_command.py tests/test_command_views.py tests/test_registry.py -q` | ✅ | ⬜ pending |
| 19-02-01 | 02 | 2 | PANEL-07 | T-19-02-01..06 | reveal/collapse + flags-build + custom_id-registration + fits/overflow scaffold | unit | `uv run pytest tests/test_panel.py -k "forecast or layout" -q` | ❌ W0 | ⬜ pending |
| 19-02-02 | 02 | 2 | PANEL-07 | T-19-02-01/06 | full-layout assert + custom_id registration; never mutate registered view (D-05/D-08/D-09) | unit | `uv run pytest "tests/test_panel.py::test_forecast_custom_ids_registered" "tests/test_panel.py::test_layout_full_panel_fits" "tests/test_panel.py::test_layout_overflow_trips_assert" -q` | ❌ W0 | ⬜ pending |
| 19-02-03 | 02 | 2 | PANEL-07 | T-19-02-01..05 | operator gate + single-ack + envelope cover new callbacks; collapse-on-action (D-01/D-03/D-04) | unit | `uv run pytest tests/test_panel.py -q` | ❌ W0 | ⬜ pending |

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
