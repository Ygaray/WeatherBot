---
slug: panel-dead-after-first-tap
status: resolved
trigger: "Panel dead after one interaction — every tap after the first fails with 'This interaction failed' (no server log). Live Gate-2 UAT of v1.3 Discord control panel on host yahir-mint."
created: 2026-06-27
updated: 2026-06-27
---

# Debug Session: panel-dead-after-first-tap

## Symptoms

- **Expected behavior:** Every panel tap — dropdown location change, command button (weather/uv/…), Forecast toggle + variant — is acked within Discord's 3s window and renders in-place; the panel stays interactive across many consecutive taps (and after a restart, PANEL-09).
- **Actual behavior:** The panel works for EXACTLY ONE interaction after a fresh real-view attach (the `!panel` summon, or a process restart). Every subsequent tap fails with the client-side toast **"This interaction failed."** Observed live: `!panel` → switch dropdown to location 2 (worked) → switch back to location 1 (failed). Equivalent to: first tap works, second+ tap dies until the panel is re-summoned/restarted.
- **Error messages:** Client-side "This interaction failed" only. **Zero** server-side output — no structlog line, no traceback in `journalctl -u weatherbot` (the panel's `on_select`/`on_command` try/except and the `View.on_error` backstop never fire).
- **Timeline:** Never worked in live use. 2026-06-27 was the first-ever deploy of the entire v1.3 panel (the production daemon had run pre-panel code since 2026-06-20). Not caught by the 649-test suite.
- **Reproduction:** On host `yahir-mint`, `!panel` in the configured panel channel as operator → tap any component twice. The first tap renders; the second shows "This interaction failed."

## Confirmed Root Cause (high confidence — verified against installed discord.py 2.7.1)

The defect is in `weatherbot/interactive/panel.py::PanelView._render_view` (line ~706-770).

1. **Every render path** re-attaches the message's components via `self._render_view(...)`:
   `on_select` (panel.py:520), `on_command` ack + final render (552, 587), `on_forecast` (627, 657),
   the forecast-toggle, and the `UnknownLocationError` branches (575, 648).
2. `_render_view` rebuilds each child as a **plain `discord.ui.Button` / `discord.ui.Select`**
   (panel.py:733-770) — these carry the right `custom_id`/emoji/`default` BUT **no callback**.
   In discord.py 2.7.1, a plain `Item.callback` is a no-op (`discord/ui/item.py:215` — body is `pass`).
3. discord.py routes component interactions by **message_id FIRST** (`discord/ui/view.py:1068`,
   `dispatch_view`: `item = self._views.get(message_id, {}).get(key)`). Calling
   `interaction.response.edit_message(view=clone)` registers the clone against that message_id
   (`add_view(view, message_id)` → `_synced_message_views[message_id] = view`, view.py:965-968),
   so the message-bound clone **shadows** the persistent `add_view` (setup_hook) registration,
   which is only the `message_id=None` fallback (view.py:1071-1072).
4. Therefore, after the first edit, every tap routes to the clone's **dead (`pass`) callbacks** →
   no ack within 3s → Discord shows "This interaction failed", and because `pass` raises nothing
   there is no exception for the try/except or `View.on_error` to log. **Explains the no-log symptom.**

**Asymmetry explained:** the `!panel` summon (and post-restart `add_view` fallback) attaches the
REAL `PanelView` with working callbacks → first tap works; the very first render then swaps in a
dead clone → all subsequent taps die.

**Why 649 tests missed it:** `tests/test_panel.py` invokes `panel.on_select(...)` / `on_command(...)`
DIRECTLY — it never routes a second interaction THROUGH the rendered clone, so the clone's dead
callbacks are invisible to the suite. The "_render_view clone is cosmetic; the persistent view
handles routing" assumption (panel.py:720-723 docstring) is false in-process.

## Fix Direction

`_render_view` must produce components that actually route to the panel's callbacks. Preferred:
rebuild the clone's children from the REAL callback-bearing item subclasses (`CmdButton`,
`LocationSelect`, `ForecastButton`, `ForecastToggleButton`) bound to this panel (`self`), preserving
the existing knobs (collapsed drops rows 3-4; `disabled` for the ack cue; emoji + dropdown `default`
re-derived from `_selected_location`; min/max_values; option label). Alternative: re-attach the
persistent `self` and represent collapse without a plain-component clone. Either way the message-bound
view must carry live callbacks.

**Regression test (must fail before the fix):** drive an interaction THROUGH the rendered clone —
build the panel, call a render path (e.g. `on_select`) to produce the attached clone view, then locate
the cloned child by `custom_id` and invoke ITS `callback(fake_interaction)` (simulating discord.py's
message-bound dispatch). Assert the tap acks / dispatches (i.e. the cloned child's callback is the
panel's real handler, not the no-op base). Cover both a command button and the dropdown on the clone.
Keep the full suite green and zero production-behavior regressions elsewhere.

## Current Focus

reasoning_checkpoint:
  hypothesis: "`_render_view` rebuilds children as plain `discord.ui.Button`/`discord.ui.Select`
    (no callback). discord.py 2.7.1 routes component interactions by message_id first, and
    `edit_message(view=clone)` binds the clone to the message, so every tap after the first
    render dispatches to the clone's no-op (`pass`) callbacks → no ack → 'This interaction failed',
    no log."
  confirming_evidence:
    - "Empirically confirmed: plain `discord.ui.Button.callback` body is `pass`; awaiting it awaits
      NOTHING on the interaction (await_count 0 on edit_message)."
    - "Regression test routing the SECOND tap through the rendered clone's own callback fails RED
      with `response.edit_message Awaited 0 times` — for BOTH the command button and the dropdown."
    - "discord.py 2.7.1 source: dispatch_view resolves by message_id first (view.py:1068);
      edit_message binds clone to message_id (view.py:965-968)."
  falsification_test: "If invoking the cloned child's callback DID ack/dispatch with the plain-clone
    code, the hypothesis would be wrong. It does not — confirmed RED."
  fix_rationale: "Rebuild the clone's children from the REAL callback-bearing item subclasses
    (CmdButton/LocationSelect/ForecastButton/ForecastToggleButton) bound to `self`, so the
    message-bound clone carries live callbacks that route to the panel handlers. This addresses
    the root cause (dead callbacks on the routed view), not a symptom."
  blind_spots: "No live-gateway test possible here; the regression test simulates discord.py's
    message-bound dispatch by invoking the cloned child's callback directly. Select.values is
    seeded via `_values` (the documented fallback path) rather than the contextvar."

- next_action: Apply the _render_view fix (rebuild from real item subclasses bound to self,
  preserving collapse/disabled/emoji/default/min-max/label knobs); verify regression GREEN,
  full suite at 650+, lint/format clean.

## Evidence

- timestamp 2026-06-27: discord.py 2.7.1 `Item.callback` default body is `pass` (`discord/ui/item.py:215`).
- timestamp 2026-06-27: `dispatch_view` resolves by `message_id` first (`discord/ui/view.py:1068`); `edit_message(view=)` binds the clone to the message (`view.py:965-968`).
- timestamp 2026-06-27: live UAT on yahir-mint — first dropdown switch rendered, second failed with "This interaction failed", zero journald output.

## Eliminated

(none — the orchestrator's source-verified root cause was confirmed RED-then-GREEN on the first
hypothesis; no competing hypotheses required elimination)

## Resolution

root_cause: |
  `PanelView._render_view` rebuilt every child as a PLAIN `discord.ui.Button` /
  `discord.ui.Select`, whose base `callback` is a no-op (`pass`) in discord.py 2.7.1. Because
  discord.py routes component interactions by `message_id` FIRST (`View.dispatch_view`) and
  `interaction.response.edit_message(view=clone)` binds the clone to the panel message, every tap
  AFTER the first render dispatched to the clone's dead callbacks — not to the persistent
  `add_view`-registered `PanelView`. A dead callback acks nothing within Discord's 3s window
  (client toast "This interaction failed") and, since `pass` raises nothing, leaves no server log.
  The `!panel` summon / post-restart `add_view` attaches the REAL view (first tap works); the first
  render then swaps in a dead clone (all subsequent taps die) — exactly the observed asymmetry.

fix: |
  Rewrote `_render_view` to rebuild each child from its REAL callback-bearing subclass bound to
  `self` via a new `_clone_child` helper: `LocationSelect(self, locations)`,
  `CmdButton(child._name, self, row=...)`, `ForecastButton(self, command_name, variant, ...)`,
  `ForecastToggleButton(self, row=...)`. The message-bound clone now delegates to the panel's live
  handlers. All knobs preserved: collapsed still drops rows 3–4; `disabled` applied
  post-construction (the subclass ctors take no `disabled` param); emoji + dropdown `default`
  re-derived from `_selected_location` by the subclass ctors (LocationSelect rebuilt from the live
  `holder.current().locations`); min/max_values, option label, custom_id all carried. The
  briefing/scheduler spine and the `dispatch_spec` seam are untouched.

verification: |
  - REQUIRED regression tests added to tests/test_panel.py that route the SECOND tap THROUGH the
    rendered clone's own callback (simulating discord.py's message-bound dispatch):
    `test_rendered_clone_command_button_routes_to_handler` (command button) and
    `test_rendered_clone_dropdown_routes_to_handler` (location dropdown). BOTH failed RED before
    the fix ("response.edit_message Awaited 0 times") and pass GREEN after.
  - Empirically confirmed the no-op: plain `discord.ui.Button.callback` body is `pass`; awaiting it
    awaits nothing on the interaction.
  - Full suite: 652 passed (650 baseline + 2 new), zero regressions. All prior structural tests
    (emoji-survives-clone, dropdown-default-survives-clone, collapse-on-action, disabled-ack,
    layout fits/overflow, persistence/custom_id registration, transient-view collapse) still green.
  - `ruff check` clean; `ruff format --check` clean.
  - NOTE (Gate-2 deferred obligation): live verification on host yahir-mint — `!panel` then tap a
    component twice+ — remains a human-UAT item per the Two-Gate policy; the in-process clone-routing
    repro is now covered by automated regression.

files_changed:
  - weatherbot/interactive/panel.py: rewrote _render_view to rebuild callback-bearing item
    subclasses (added _clone_child helper); message-bound clone now routes to live handlers.
  - tests/test_panel.py: added two clone-routing regression tests (command button + dropdown).
