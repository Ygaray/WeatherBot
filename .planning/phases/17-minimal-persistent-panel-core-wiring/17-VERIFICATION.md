---
phase: 17-minimal-persistent-panel-core-wiring
verified: 2026-06-24T02:55:50Z
status: human_needed
score: 9/9 must-haves verified (mechanism); 5 live-Discord checks deferred to Gate-2
overrides_applied: 0
human_verification:
  - test: "On the live yahir-mint bot, tap each command button (weather / uv / next-cloudy / sun / wind / status / alerts) with a cold ForecastCache."
    expected: "Each tap is acknowledged within Discord's 3-second window (the ⏳ Fetching… cue appears immediately, components disabled), then the panel message edits in-place to the command result embed with components reattached — never a second message, never an 'interaction failed' toast."
    why_human: "Requires a live Discord gateway + real OpenWeather cold-cache latency to exercise the real 3-second ack budget; unit tests prove the call sequence (single response.edit_message before dispatch_spec, result via edit_original_response) but cannot measure the real ack window or render the embed in a real client."
  - test: "From a second (non-operator) Discord account, tap any panel button on the shared pinned panel."
    expected: "The foreign user sees ONLY an ephemeral message 'This panel is in use by someone else.' (visible to them alone); the shared panel message is NOT edited/clobbered; no command runs; the operator sees nothing change."
    why_human: "Ephemeral-message visibility to a foreign user and the no-clobber guarantee on the shared message can only be observed in a real two-account Discord session. The mechanism (interaction_check returns False + ephemeral send_message + structlog reject log, no handler runs) is unit-verified."
  - test: "Pick a location in the dropdown, then tap a location command button; then change config (hot-reload) to add/remove a location and re-open the panel."
    expected: "The command result is for the selected location; after hot-reload the dropdown shows the updated location list."
    why_human: "Full hot-reload-to-dropdown loop on the live holder + real selection round-trip is best confirmed in a live client; the per-construction re-derivation and in-memory _selected_location → arg routing are unit-verified."
  - test: "Tap a button, then immediately double-tap during the cold fetch."
    expected: "The disabled-copy ack neutralizes the second tap (components disabled until the result lands); no InteractionResponded error, no duplicate fetch."
    why_human: "Double-tap timing during a real cold fetch requires the live latency window; the single-ack + _disabled_copy mechanism is source-verified."
  - test: "Force a handler failure on the live panel (e.g. transient OpenWeather error) and tap the affected button."
    expected: "The operator gets a generic in-place error answer ('Sorry — something went wrong.'); the bot does not crash; the briefing scheduler thread is unaffected; no traceback reaches the gateway loop."
    why_human: "Real failure-isolation under a live scheduler is a Gate-2 / Phase-20 re-proof; the per-callback envelope + View.on_error backstop are unit-verified (test_callback_raise_isolated) and source-confirmed."
---

# Phase 17: Minimal Persistent Panel (Core Wiring) Verification Report

**Phase Goal:** A `PanelView` (`discord.ui.View`, `timeout=None`, static `custom_id`s) carries a location dropdown populated from configured locations plus the read-only command buttons, each derived from the registry. A tap is acknowledged within Discord's 3-second window (defer-then-edit), runs the off-loop fetch through the Phase-16 `dispatch_spec`, and renders the result in-place by editing the panel message with components reattached. One `interaction_check` operator guard gates every interaction; a per-callback non-propagating envelope plus a `View.on_error` backstop keep any failure contained.

**Verified:** 2026-06-24T02:55:50Z
**Status:** human_needed (all mechanisms VERIFIED; 5 live-Discord checks deferred as Gate-2 obligations per project Two-Gate UAT policy)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | Operator picks a location from the dropdown (re-derived from `holder.current().locations`) and taps a command button to get that command's result for the selection | ✓ VERIFIED | `LocationSelect.options` built per-construction from `[loc.name for loc in config.locations]` (panel.py:179, :143); `on_command` resolves `spec = registry.BY_NAME[name]` and routes `arg=self._selected_location` (panel.py:283-284). Tests `test_dropdown_from_config`, `test_location_button_uses_selection` PASS. |
| 2   | Selected location held as in-memory `_selected_location` from `select.values[0]`, default `locations[0]`, never re-read from `Select.values` in a button callback, never in `custom_id` | ✓ VERIFIED | `_selected_location = locations[0]` default (panel.py:183); set in `on_select` from `value` arg (panel.py:260); button callback reads the attribute, not `Select.values` (panel.py:284). custom_id is static `wb:cmd:<name>` (panel.py:117). |
| 3   | Buttons are a curated ordered tuple of the seven names, each resolved via `registry.BY_NAME` with a build-time assert (registry rename fails loud) | ✓ VERIFIED | `_LOCATION_CMDS`/`_ARGLESS_CMDS` (panel.py:77-78); module-level `assert _name in registry.BY_NAME` loop (panel.py:80-84); `BY_NAME` confirmed to contain all 7 names (registry.py:51-52, 105-110). |
| 4   | Argless buttons (status / alerts) work and ignore the selected location (`arg=None`) | ✓ VERIFIED | `arg = self._selected_location if spec.takes_location else None` (panel.py:284). Test `test_argless_button_ignores_selection` asserts `cache.calls == []` for status — PASS. |
| 5   | Every tap acked within 3s by a single `response.edit_message` before the off-loop fetch | ✓ VERIFIED (mechanism) | One `interaction.response.edit_message(content=_FETCHING_CUE, view=self._disabled_copy())` BEFORE `dispatch_spec` (panel.py:286-292); result lands via `edit_original_response`, never a 2nd `response.*`. Test `test_single_ack_before_fetch` asserts `edit_message.assert_awaited_once()` + `send_message.assert_not_awaited()` — PASS. Real 3s budget → Gate-2. |
| 6   | Results render in-place via `edit_original_response` with components reattached — no new message | ✓ VERIFIED | `await interaction.edit_original_response(content=None, embed=render_embed(reply), view=self)` (panel.py:307-309). Test `test_result_renders_in_place`: `edit_original_response.assert_awaited()` + `followup.send.assert_not_awaited()` — PASS. |
| 7   | A non-operator tap gets an ephemeral leak-free reject, no handler runs, reject logged | ✓ VERIFIED (mechanism) | `interaction_check` returns False for `user.bot` and `user.id != operator_id`; emits `_log.info("panel reject (non-operator)", ...)` + ephemeral byte-exact `"This panel is in use by someone else."` (panel.py:235-248). Tests `test_non_operator_rejected_leak_free`, `test_reject_does_not_call_on_error` PASS. Live foreign-user visibility → Gate-2. |
| 8   | `view.is_persistent()` is True so Phase 18 can `add_view` it | ✓ VERIFIED | `super().__init__(timeout=None)` (panel.py:172) + every child static `custom_id`. Test `test_view_persistent_and_layout_bounded`: `view.is_persistent() is True` — PASS. |
| 9   | A raising callback never propagates (per-callback envelope + `View.on_error` backstop) | ✓ VERIFIED | Per-callback `except Exception:` non-propagating envelope on `on_command` (panel.py:310-312) and `on_select` (panel.py:262-264); `View.on_error` override logs + `_safe_error_edit`, never re-raises (panel.py:314-332). Test `test_callback_raise_isolated`: `on_command` returns without raising, operator gets in-place answer — PASS. |

**Score:** 9/9 truths verified at the mechanism level (the contract under the verifier's reach). 5 live-Discord behaviors deferred as Gate-2 milestone-close obligations.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `weatherbot/interactive/panel.py` | `PanelView` + `CmdButton` + `LocationSelect` + callbacks + guard + envelope (min 120 lines) | ✓ VERIFIED | 400 lines. All 3 classes present; `interaction_check`, `on_command`, `on_select`, `on_error`, `_disabled_copy`, `_safe_error_edit`, `_assert_layout` all implemented (not stubs). Acyclic import OK (`import weatherbot.interactive.panel` exits 0). |
| `weatherbot/interactive/registry.py` | `CommandSpec("weather", "Weather", ..., True)` + `_wire_handlers` entry | ✓ VERIFIED | Spec at registry.py:51 (first Weather-group row); wired `"weather": weather_views.weather` at registry.py:105. |
| `weatherbot/interactive/commands/weather_views.py` | `weather(result) -> CommandReply` (Now / High·Low / Rain) | ✓ VERIFIED | `def weather` at :94 returns `CommandReply` titled off `f.location` with Now/High·Low/Rain lines (:107-114). Test `test_weather_spec_byte_identical` PASS. |
| `weatherbot/cli.py` | Registry-loop skip-guard for hand-written subparser names | ✓ VERIFIED | `_HANDWRITTEN` set (:823-831) + `if _spec.name in _HANDWRITTEN: continue` (:834-835). `weatherbot --help` exits 0; `weatherbot weather --help` shows `-v/--verbose` (standalone subparser preserved, no collision). |
| `tests/conftest.py` | `_make_fake_interaction` factory + `fake_interaction` fixture | ✓ VERIFIED | Used by all 11 panel tests; gateway-free MagicMock. |
| `tests/test_panel.py` | 11 panel node IDs | ✓ VERIFIED | All 11 nodes present and GREEN (`11 passed`). |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| panel.py | dispatch.py | `await dispatch_spec(spec, arg, cache, config, loop, daemon_state)` | ✓ WIRED | panel.py:292-299; `dispatch_spec` is a real off-loop fetch via `run_in_executor` (dispatch.py:105+). |
| panel.py | bot.py | `render_embed(reply)` | ✓ WIRED | panel.py:308; `render_embed` real renderer (bot.py:124). |
| panel.py | registry.py | `registry.BY_NAME[name]` (allow-list) | ✓ WIRED | panel.py:283 + build-time assert loop panel.py:80-84. |
| registry.py | weather_views.py | `_wire_handlers` maps `"weather" → weather_views.weather` | ✓ WIRED | registry.py:105. |
| cli.py | registry.COMMANDS loop | `_HANDWRITTEN` skip-guard | ✓ WIRED | cli.py:823-835; no argparse collision (verified `--help` exit 0). |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| PanelView dropdown | `locations` | `holder.current().locations` per construction | Yes (live config snapshot, re-derived not cached) | ✓ FLOWING |
| on_command result | `reply` | `await dispatch_spec(...)` → real off-loop `cache.lookup` → handler | Yes (real fetch ladder, not static) | ✓ FLOWING |
| weather button embed | `render_embed(reply)` | `weather_views.weather(result)` reading `result.forecast` | Yes (byte-identical to `build_inbound_embed`) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Panel module imports acyclically | `python -c "import weatherbot.interactive.panel"` | `IMPORT_OK` | ✓ PASS |
| CLI builds without subparser collision | `weatherbot --help` | exit 0 | ✓ PASS |
| Standalone weather subparser preserved | `weatherbot weather --help` | shows `-v/--verbose` | ✓ PASS |
| All 11 panel tests green | `pytest tests/test_panel.py -q` | `11 passed` | ✓ PASS |
| Full suite green (no regressions) | `pytest -q` | `600 passed` | ✓ PASS |

### Probe Execution

No probes apply. Phase 17 is a Discord-UI-component phase, not a migration/CLI-probe phase; `find scripts -path '*/tests/probe-*.sh'` returns nothing and no PLAN/SUMMARY declares a probe. Verification used the unit suite + behavioral spot-checks instead.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| PANEL-02 | 17-01, 17-03 | Dropdown populated from configured locations + re-derives on hot-reload | ✓ SATISFIED | Truth 1; tests `test_dropdown_from_config`, `test_dropdown_rederives_on_hot_reload`. REQUIREMENTS.md:16 marked complete. |
| PANEL-03 | 17-01, 17-02, 17-03 | Tap a command button → result for selected location | ✓ SATISFIED | Truths 1, 3; weather is a first-class registry command (17-02); `test_location_button_uses_selection`. |
| PANEL-04 | 17-01, 17-03 | Argless buttons work and ignore selection | ✓ SATISFIED | Truth 4; `test_argless_button_ignores_selection`. |
| PANEL-05 | 17-01, 17-03 | Tap acked within 3s (defer-then-edit) | ✓ SATISFIED (mechanism) | Truth 5; `test_single_ack_before_fetch`. Real 3s window → Gate-2. |
| PANEL-06 | 17-01, 17-03 | Results render in-place, components reattached, no new message | ✓ SATISFIED | Truth 6; `test_result_renders_in_place`. |
| PANEL-08 | 17-01, 17-03 | Only operator drives; non-operator ephemeral leak-free reject | ✓ SATISFIED (mechanism) | Truth 7; `test_non_operator_rejected_leak_free`, `test_reject_does_not_call_on_error`. Foreign-user visibility → Gate-2. |

All 6 declared requirement IDs (PANEL-02/03/04/05/06/08) are present in `.planning/REQUIREMENTS.md`, mapped to Phase 17, and marked Complete. No orphaned requirements. PANEL-09 (persistent re-registration after restart) is explicitly mapped to Phase 18 in REQUIREMENTS.md:82,98 — correctly out of scope here.

### Anti-Patterns Found

None. Grep for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER|not yet implemented|coming soon` across `panel.py` and `weather_views.py` returned nothing. The `return False`/`return None`-style matches in `interaction_check` and the `except Exception` envelopes are intentional, documented correctness mechanisms (operator gate + non-propagating failure isolation), each carrying a `noqa` with a rationale — not stubs. No debt markers.

### Human Verification Required

Per the project's Two-Gate UAT policy, the following are Gate-2 (milestone-close, deferred) obligations. They do NOT block Phase 17 — every mechanism is source-verified and unit-tested. They are recorded so the human verifies the live behavior before the v1.2 milestone closes.

1. **Tap each button under a cold cache** — confirm the 3-second ack + in-place edit on the live bot.
2. **Non-operator reject** — confirm the ephemeral, no-clobber reject from a second Discord account.
3. **Hot-reload dropdown loop** — confirm dropdown re-derivation + selection round-trip on the live holder.
4. **Double-tap during cold fetch** — confirm the disabled-copy ack neutralizes the re-tap.
5. **Live failure isolation** — confirm a handler failure yields a generic in-place answer without crashing the scheduler.

(Detailed test/expected/why-human for each is in the frontmatter `human_verification` block.)

### Gaps Summary

No gaps. Every must-have is mechanically VERIFIED in the codebase:
- The `PanelView` exists with all three classes, `timeout=None`, static `custom_id`s, registry-derived curated children, and a build-time layout assert.
- All three load-bearing correctness mechanisms are present in source and unit-proven: single-ack defer-then-edit (one `response.edit_message` before `dispatch_spec`, result via `edit_original_response`), the `interaction_check` operator gate (return False + ephemeral byte-exact reject + structlog log, no handler runs), and per-callback non-propagating envelope + `View.on_error` backstop.
- `weather` is a real first-class registry command routing through the shared `dispatch_spec → render_embed` ladder, byte-identical to `build_inbound_embed`, with the CLI skip-guard preventing an argparse collision.
- All 11 `test_panel.py` nodes pass; the full 600-test suite is green; imports are acyclic.

Status is `human_needed` (not `passed`) solely because the live-Discord behaviors listed above require a real gateway/client to fully exercise and are non-empty Gate-2 items — consistent with the project Two-Gate UAT policy where these are deferred, non-phase-blocking obligations.

---

_Verified: 2026-06-24T02:55:50Z_
_Verifier: Claude (gsd-verifier)_
