---
phase: 19-forecast-two-tier-sub-options
verified: 2026-06-26T00:00:00Z
status: human_needed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "On the live yahir-mint host: deploy + `sudo systemctl restart weatherbot`, summon `!panel`, tap Forecast (reveal), tap a variant (e.g. Weekday Compact)."
    expected: "The 2×2 sub-grid reveals on the first Forecast tap; a variant tap renders the correct in-place forecast embed for the currently selected location, then collapses the sub-grid."
    why_human: "Requires a real Discord gateway interaction on a live always-on host (editable install needs deploy + restart); cannot be driven from the test harness. Mechanism is fully unit-verified in source + tests; only the physical live tap is deferred (Gate-2 milestone-close obligation)."
  - test: "After the reveal above, `sudo systemctl restart weatherbot` while the panel message still shows the revealed sub-grid, then tap a forecast variant on the still-displayed grid."
    expected: "The post-restart tap still routes (the persistent view re-registers all 13 custom_ids via add_view) and renders the correct forecast — display state is independent of routing (D-05)."
    why_human: "Post-restart component routing across a process restart on a live host cannot be exercised in-process. add_view registration of all 5 forecast custom_ids is unit-verified (test_forecast_custom_ids_registered); the live restart round-trip is the deferred Gate-2 obligation."
---

# Phase 19: Forecast Two-Tier Sub-Options Verification Report

**Phase Goal:** The panel gains a Forecast button that reveals the Weekday/Weekend × Detailed/Compact sub-options (a static four-button sub-row / 2×2 grid), each building a `ForecastFlags(variant=…, location=selected)` directly and routing through the same Phase-16 `dispatch_spec` — so the panel mirrors the text command's forecast variants exactly. The one layout-pressure flow, with a build-time assertion that the component layout fits Discord's hard limits (≤5 rows / ≤5 per row / ids ≤100 / labels ≤80).
**Verified:** 2026-06-26
**Status:** human_needed (all automated must-haves VERIFIED; live Discord tap + post-restart routing are deferred Gate-2 obligations per project Verification Policy and the verification notes)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | `dispatch_spec` accepts additive keyword-only `flags=None`; non-None skips `parse_forecast_flags` and uses `flags.location` + `forecast_cache_suffix(spec.name, flags)` (D-01) | ✓ VERIFIED | `dispatch.py:113` signature; `dispatch.py:156-161` `if flags is None:` guard then `lookup_name = flags.location` / `suffix = forecast_cache_suffix(...)`. `test_dispatch_spec_flags_passthrough_skips_parse` passes. |
| 2 | `flags=None` path is byte-identical (only diff inside `is_forecast` block is the guard); `dispatch_reply` untouched (D-02) | ✓ VERIFIED (behavior-dependent) | `dispatch.py:157-161` — only the `if flags is None:` guard wraps the unchanged parse; `dispatch_reply` (60-102) unchanged. Named test `test_dispatch_spec_flags_none_is_byte_identical` passes; full anti-drift suite (test_dispatch/bot/command/command_views/registry) green. |
| 3 | Tapping the Forecast toggle reveals the 2×2 sub-grid (rows 3–4); re-tap collapses — single `edit_message(view=)` swap (D-03/D-07) | ✓ VERIFIED (behavior-dependent) | `panel.py:614-632` `on_forecast_toggle` flips `_expanded`, one `response.edit_message`. `test_forecast_toggle_reveal` asserts reveal-then-collapse on the captured view. |
| 4 | A forecast variant tap builds `ForecastFlags(variant, location=_selected_location)` (add/drop empty) and routes `dispatch_spec(spec, None, …, flags=)` via `registry.BY_NAME[…-forecast]` — same shared seam, no parallel logic (D-01, criterion 2) | ✓ VERIFIED | `panel.py:567-592`; spec is `registry.BY_NAME[command_name]`, `arg=None`, `flags=flags`. `test_on_forecast_dispatch` + `test_forecast_matches_registry` assert spec identity, flags fields, arg=None, and reply equals the shared-seam reply. |
| 5 | Every non-toggle action (variant tap, other command, dropdown change) renders the COLLAPSED base; a variant renders result AND collapses in the terminal edit (D-03/D-04) | ✓ VERIFIED (behavior-dependent) | `on_forecast` (602-606), `on_command` (526-538), `on_select` (472-476) all attach `_render_view(expanded=False)` + reset `_expanded`. Named test `test_collapse_on_action` (all three paths) + `test_transient_ack_and_error_views_honor_collapsed_state` (WR-01/WR-02 transient surfaces) pass. |
| 6 | All four `wb:fc:*` + `wb:forecast:toggle` custom_ids build in `__init__` so add_view registers them; a revealed sub-button still routes post-restart (D-05, criterion 1) | ✓ VERIFIED | `panel.py:335-362` build all 13 children in `__init__`; `_render_view` (676) builds a fresh view and never mutates `self`. `test_forecast_custom_ids_registered` asserts all 5 ids among registered children. (Live post-restart round-trip → human_verification.) |
| 7 | `_assert_layout` validates the full revealed panel: ≤5 rows, ≤5 per row, ≤25 children, id≤100, label≤80; a test asserts both fit and an over-cap trip (D-08, criterion 3) | ✓ VERIFIED | `panel.py:376-416` `_assert_layout_children` enforces all 5 caps via `Counter`. `test_layout_full_panel_fits` (13 children/5 rows, no raise) + `test_layout_overflow_trips_assert` (5 over-cap cases each raise `AssertionError`). |

(Truth #6's "operator gate / single-ack / envelope inherited unchanged" sub-clause is also VERIFIED: `interaction_check` (418-459), the single-ack pattern, and `on_error`/`_safe_error_edit` backstop (634-744) are present and cover the new toggle + 4 sub-buttons; code review confirmed the inherited gate/envelope is not regressed.)

**Score:** 7/7 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `weatherbot/interactive/dispatch.py` | additive `flags=None` param skipping parse on panel path | ✓ VERIFIED | `flags: ForecastFlags | None = None` (113); guard at 157; wired by `panel.py` + 2 tests. |
| `weatherbot/interactive/panel.py` | ForecastButton + ForecastToggleButton + on_forecast + on_forecast_toggle + _render_view + extended _assert_layout + collapse wiring | ✓ VERIFIED | All present (188-251 classes, 543-632 callbacks, 654-701 `_render_view`, 376-416 `_assert_layout_children`); 744 lines; imported nowhere-broken (`import weatherbot.interactive.panel` exits 0). |
| `tests/test_dispatch.py` | flags= passthrough + flags=None byte-identical nodes | ✓ VERIFIED | Both nodes present (319, 367), passing. |
| `tests/test_panel.py` | reveal/collapse + dispatch + custom_id + full/overflow + regression nodes | ✓ VERIFIED | 7 plan nodes (644-866) + WR-01/WR-02 regression node (885), all passing. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `panel.py` | `dispatch.py` | `dispatch_spec(spec, None, …, flags=ForecastFlags(...))` | ✓ WIRED | `panel.py:584-592` — exact call shape. |
| `panel.py` | `command.py` | `ForecastFlags(variant=…, location=self._selected_location)` built directly | ✓ WIRED | module-top import (55); built at 570-572. |
| `panel.py` | `registry.py` | `registry.BY_NAME['weekday-forecast'|'weekend-forecast']` | ✓ WIRED | resolved at 568; import-time allow-list assert (97-101); both specs `group="Forecast"` takes_location True (registry.py:67-78). |
| `dispatch.py` | `command.py` | `forecast_cache_suffix(spec.name, flags)` on caller-flags path | ✓ WIRED | `dispatch.py:161`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `on_forecast` embed | `reply` | `dispatch_spec(...)` → off-loop `cache.lookup` + registry forecast handler | ✓ Yes — real registry handler via shared seam | ✓ FLOWING (`test_forecast_matches_registry` proves panel render == shared-seam reply) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| PANEL-07 | 19-01, 19-02 | Operator taps Forecast to reveal Weekday/Weekend × Detailed/Compact sub-options and get the chosen variant for the selected location | ✓ SATISFIED | All 7 truths + artifacts + links verified; `.planning/REQUIREMENTS.md:21,80` marks PANEL-07 Phase 19 Complete. No orphaned IDs for this phase. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Modules import (no cycle) | `python -c "import …dispatch; import …panel"` | `IMPORTS_OK` | ✓ PASS |
| Phase-19 dispatch+panel nodes | `pytest tests/test_panel.py tests/test_dispatch.py -q` | 40 passed | ✓ PASS |
| Full suite (run once) | `pytest -q` | 635 passed | ✓ PASS |
| Behavior-dependent invariants by name | `pytest …transient_ack… …collapse_on_action …forecast_toggle_reveal …flags_none_is_byte_identical` | 4 passed | ✓ PASS |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER in phase source | — | None |

One deferred item logged (`deferred-items.md`): a pre-existing Phase-17 ruff `F841` in `tests/test_panel.py:194`, out of scope for PANEL-07, test passes. Not a Phase-19 gap.

### Human Verification Required

1. **Live Forecast reveal + variant tap** — deploy + `systemctl restart weatherbot`, summon `!panel`, tap Forecast then a variant.
   - Expected: sub-grid reveals on first tap; variant tap renders the correct forecast for the selected location, then collapses.
   - Why human: real Discord gateway interaction on the live always-on host; mechanism fully unit-verified, only the physical tap is deferred (Gate-2 milestone-close obligation per project Verification Policy).
2. **Post-restart routing** — restart with the panel still showing the revealed grid, then tap a variant.
   - Expected: the tap still routes (add_view re-registers all 5 forecast custom_ids) and renders correctly.
   - Why human: cross-process restart routing cannot be exercised in-process; custom_id registration is unit-verified, the live round-trip is the deferred obligation.

### Gaps Summary

No gaps. All three success criteria are achieved in the codebase with substantive, wired implementations and passing behavioral tests:

1. **Reveal → variant for selected location** — toggle + 2×2 grid + `on_forecast` build `ForecastFlags(variant, location=_selected_location)` and dispatch; verified by 4 passing nodes.
2. **Same shared dispatcher/registry, no parallel logic** — panel is the third caller of `dispatch_spec`; `test_forecast_matches_registry` proves the rendered embed equals the shared-seam reply.
3. **Build-time layout assertion** — `_assert_layout_children` enforces all five Discord caps with a fits-and-overflow test.

The two post-execution code-review findings (WR-01 collapsed-ack flicker, WR-02 error-path re-reveal) are fixed in source (`on_command` ack uses `expanded=self._expanded`, `panel.py:508`; `_safe_error_edit` uses `_render_view(expanded=False)`, `panel.py:733`) and pinned by the regression test `test_transient_ack_and_error_views_honor_collapsed_state`. (`_disabled_copy` was removed entirely rather than repointed — a single `_render_view` clone path, fully satisfying D-09's single-path intent.)

Status is `human_needed` solely because the live Discord tap and post-restart routing are physical, host-dependent steps deferred to Gate-2 per the project Verification Policy and the phase verification notes — not because any mechanism is unverified. Phase-20 items (selected-location indicator, emoji labels, "updated" stamp, PANEL-11 isolation re-proof) are correctly out of scope.

---

_Verified: 2026-06-26_
_Verifier: Claude (gsd-verifier)_
