---
phase: 17
slug: minimal-persistent-panel-core-wiring
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-23
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Audited and reconciled to the executed artifacts (State A) on 2026-06-27 — the planning-time
> draft stub below was never updated post-execution; the panel test surface shipped and is green.

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
| 17-01-01 | 01 | 1 | PANEL-02/03/04/05/06/08 | — | Wave-0 RED scaffold: `fake_interaction` factory + node IDs | unit | `uv run pytest tests/test_panel.py -q` | ✅ | ✅ green |
| 17-02-01 | 02 | 1 | PANEL-03 | — | `weather` registry spec byte-identical to `build_inbound_embed`; CLI subparser skip-guard (no argparse collision) | unit | `uv run pytest tests/test_panel.py::test_weather_spec_byte_identical tests/test_cli.py -q` | ✅ | ✅ green |
| 17-03-01 | 03 | 2 | PANEL-02 | — | Dropdown derived from `holder.current().locations`; re-derives on hot-reload | unit | `uv run pytest tests/test_panel.py::test_dropdown_from_config tests/test_panel.py::test_dropdown_rederives_on_hot_reload -q` | ✅ | ✅ green |
| 17-03-02 | 03 | 2 | PANEL-03 | — | Location button passes in-memory `_selected_location` as arg (never re-read from `Select.values`) | unit | `uv run pytest tests/test_panel.py::test_location_button_uses_selection -q` | ✅ | ✅ green |
| 17-03-03 | 03 | 2 | PANEL-04 | — | Argless button passes `arg=None`, ignores selection | unit | `uv run pytest tests/test_panel.py::test_argless_button_ignores_selection -q` | ✅ | ✅ green |
| 17-03-04 | 03 | 2 | PANEL-05 | — | Exactly one `response.edit_message` ack before the off-loop fetch (mechanism; live 3s window → manual) | unit | `uv run pytest tests/test_panel.py::test_single_ack_before_fetch -q` | ✅ | ✅ green |
| 17-03-05 | 03 | 2 | PANEL-06 | — | Result renders in-place via `edit_original_response`, components reattached, no new message | unit | `uv run pytest tests/test_panel.py::test_result_renders_in_place -q` | ✅ | ✅ green |
| 17-03-06 | 03 | 2 | PANEL-08 | T-17 | Non-operator `interaction_check` returns False + ephemeral leak-free reject + log, no handler runs (mechanism; ephemeral visibility → manual) | unit | `uv run pytest tests/test_panel.py::test_non_operator_rejected_leak_free tests/test_panel.py::test_reject_does_not_call_on_error -q` | ✅ | ✅ green |
| 17-03-07 | 03 | 2 | PANEL-02..08 | — | Per-callback non-propagating envelope + `View.on_error` backstop contain a raising callback | unit | `uv run pytest tests/test_panel.py::test_callback_raise_isolated -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

All Phase-17 requirement IDs have a dedicated, named, green automated test. PANEL-05 and PANEL-08
each have their **mechanism** unit-tested here; only the live-Discord-rendered result (real 3s ack
latency; ephemeral client-side visibility) is deferred to the Manual-Only table below as a Gate-2
human-UAT obligation — not a coverage gap.

---

## Wave 0 Requirements

- [x] `tests/test_panel.py` — RED scaffold landed in Plan 17-01, filled green by 17-02/17-03 (covers PANEL-02/-03/-04/-05/-06/-08: panel construction, dropdown re-derivation, selected-location hold, defer/edit ack, in-place render, operator reject)
- [x] `tests/conftest.py` — `_make_fake_interaction` factory + `fake_interaction` fixture added (gateway-free MagicMock)

*Existing pytest infrastructure covered framework; Wave 0 added the panel test surface — complete and green.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Discord 3-second ack under cold-cache fetch | PANEL-05 | Real Discord interaction latency cannot be synthesized in pytest | Operator taps a command button on the live panel during a cold-cache fetch; confirm no "This interaction failed" toast and the "⏳ Fetching…" cue appears in-place |
| Non-operator ephemeral reject visibility | PANEL-08 | Ephemeral message visibility is a Discord client-side rendering behavior | A second (non-operator) user taps the panel; confirm they see a generic ephemeral reject and the shared panel is unchanged |

*Mechanism for both is unit-tested (defer/edit call sequence; interaction_check returns False + logs); only the live Discord-rendered result is deferred to Gate-2 human UAT.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-27

---

## Validation Audit 2026-06-27

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 (2 pre-existing manual-only Gate-2 items retained) |

State-A audit: the planning-time draft (`nyquist_compliant: false`, placeholder single-row map)
was reconciled to the executed artifacts. All six requirement IDs (PANEL-02/03/04/05/06/08) carry
dedicated, named, green automated tests in `tests/test_panel.py` (`uv run pytest tests/test_panel.py -q`
→ 34 passed, including the Phase 17/19/20 nodes). PANEL-05 (live 3s ack) and PANEL-08 (ephemeral
visibility) remain legitimately manual-only — their mechanisms are unit-tested; only the live
Discord-rendered result is a deferred Gate-2 human-UAT obligation. No automated coverage gaps —
phase is Nyquist-compliant.
