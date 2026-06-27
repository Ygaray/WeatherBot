---
phase: 17-minimal-persistent-panel-core-wiring
plan: 01
subsystem: tests
tags: [wave-0, nyquist, test-scaffold, discord-panel, RED]
requires:
  - tests/conftest.py (_make_fake_discord_message pattern)
  - tests/test_bot.py (deferred-import + _run driver + handler-stub helpers)
  - weatherbot/interactive/dispatch.py (dispatch_spec seam — referenced by tests)
  - weatherbot/interactive/registry.py (BY_NAME / CommandSpec)
provides:
  - tests/conftest.py::_make_fake_interaction (gateway-free Interaction factory)
  - tests/conftest.py::fake_interaction (fixture)
  - tests/test_panel.py (11 Wave-0 RED node IDs — Plan 17-03 GREEN targets)
affects:
  - Plan 17-03 (panel.py build — these node IDs are its acceptance contract)
tech-stack:
  added: []
  patterns:
    - "Deferred per-test import of a not-yet-built module keeps collection green while bodies stay RED (Wave-0 Nyquist scaffold)"
    - "Gateway-free fake discord.Interaction (MagicMock + AsyncMock seams, no discord import, no network)"
key-files:
  created:
    - tests/test_panel.py
  modified:
    - tests/conftest.py
decisions:
  - "Used a deferred import inside _panel() (NOT xfail) so all 11 node IDs collect; bodies fail RED on a real ImportError/KeyError until panel.py + the weather spec land in Plan 17-03"
  - "Gateway-free _make_fake_interaction mirrors the existing _make_fake_discord_message factory exactly (sibling shape) — no new harness style introduced"
metrics:
  duration: ~9m
  completed: 2026-06-24
---

# Phase 17 Plan 01: Wave-0 Panel Test Scaffold Summary

Gateway-free `fake_interaction` factory + an 11-node-ID RED `test_panel.py` that
collects cleanly (deferred import) and pins every PANEL-02/03/04/05/06/08, D-07/08/10/13
and callback-isolation behavior as a concrete GREEN target for Plan 17-03.

## What Was Built

**Task 1 — `tests/conftest.py` (`_make_fake_interaction` + `fake_interaction`):**
A pure builder (no discord import, no network) returning a `MagicMock` named
`discord.Interaction` exposing exactly the seams every panel callback reads/writes:
`.user.id` / `.user.bot` (operator gate), `.data["custom_id"]` (allow-list dispatch),
`.response.edit_message` (single ack, AsyncMock), `.response.send_message` (reject ack,
AsyncMock), `.response.is_done()` (MagicMock returning the bool param — called, not
awaited), `.edit_original_response` (in-place result/error, AsyncMock), and
`.followup.send` (post-ack fallback, AsyncMock). The existing
`_make_fake_discord_message` factory is untouched.

**Task 2 — `tests/test_panel.py` (new, 11 RED node IDs):**
A `_panel()` deferred-import helper, the `_run(coro)=asyncio.run` driver, `_OPERATOR_ID`,
gateway-free stand-ins (`_FakeHolder` with a swappable `current()` snapshot, `_SpyCache`
recording lookup names, `_FakeForecast`/`_FakeLookupResult`), and a `_stub_handler`
helper mirroring `test_bot.py`'s `_patch_command_in_registry`. The node IDs:

| Node ID | Req | Pins |
|---------|-----|------|
| `test_dropdown_from_config` | PANEL-02 | Select options derived from `holder.current().locations` |
| `test_dropdown_rederives_on_hot_reload` | PANEL-02 | options reflect a changed holder snapshot |
| `test_location_button_uses_selection` | PANEL-03 | location button passes `_selected_location` as `arg` |
| `test_argless_button_ignores_selection` | PANEL-04 | status passes `arg=None`, no location fetch |
| `test_single_ack_before_fetch` | PANEL-05 | exactly one `response.edit_message`; no second `response.*` |
| `test_result_renders_in_place` | PANEL-06 | result via `edit_original_response`; no `followup.send` |
| `test_non_operator_rejected_leak_free` | PANEL-08 | ephemeral byte-exact reject, `return False`, no edit |
| `test_reject_does_not_call_on_error` | D-13 | clean `False` does not route through `on_error` |
| `test_view_persistent_and_layout_bounded` | D-10 | `is_persistent() is True`; custom_id≤100 / label≤80 |
| `test_weather_spec_byte_identical` | D-07/08 | `weather` reply renders same fields as `build_inbound_embed` |
| `test_callback_raise_isolated` | isolation | raising handler swallowed, no propagation, in-place error |

## Verification

- `uv run pytest tests/test_panel.py --collect-only -q` → **11 node IDs collected**.
- `uv run pytest tests/test_panel.py -q` → **11 failed RED** via real
  `ImportError: cannot import name 'panel'` (10) and `KeyError: 'weather'` (1) — a
  genuine RED awaiting Plan 17-03, NOT a collection error and NOT `pass` stubs.
- `uv run pytest tests/test_bot.py -q` → **22 passed** (message factory untouched).
- `uv run pytest -q --ignore=tests/test_panel.py` → **587 passed** (full contractual
  anti-drift suite green).

## Deviations from Plan

None - plan executed exactly as written.

## Notes for Plan 17-03

- The tests reference these not-yet-built symbols, which 17-03 must provide:
  `panel.PanelView(holder=, operator_id=, cache=)` with children carrying static
  `custom_id`s (`wb:loc:select`, `wb:cmd:<name>`), the `on_select(interaction, value)`
  and `on_command(interaction, name)` callbacks, `interaction_check`, `on_error`, and
  the in-memory `_selected_location`. Plus the W2 `weather` registry spec + handler.
- The non-operator reject copy is asserted byte-exact: `This panel is in use by someone else.`
- `_make_panel`/`_stub_handler` centralize the ctor + handler-stub calls so a Plan-03
  signature change is a single edit in the test file.

## Self-Check: PASSED

- FOUND: tests/conftest.py (`_make_fake_interaction`)
- FOUND: tests/test_panel.py
- FOUND commit 0810466 (Task 1)
- FOUND commit f77e0ae (Task 2)
