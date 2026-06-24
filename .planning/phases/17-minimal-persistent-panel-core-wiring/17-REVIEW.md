---
phase: 17-minimal-persistent-panel-core-wiring
reviewed: 2026-06-24T02:50:38Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - weatherbot/interactive/panel.py
  - weatherbot/interactive/registry.py
  - weatherbot/interactive/commands/weather_views.py
  - weatherbot/cli.py
  - tests/test_panel.py
  - tests/test_registry.py
  - tests/test_command_views.py
  - tests/conftest.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 17: Code Review Report

**Reviewed:** 2026-06-24T02:50:38Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 17 wires a `discord.ui.View` operator panel (`PanelView`) onto the Phase-16
`dispatch_spec` seam and promotes `weather` to a first-class registry command (W2).
The load-bearing interaction-correctness invariants the prompt flagged are all upheld
in the implementation and pinned by tests:

- **Single-ack defer-then-edit (D-14):** `on_command` spends exactly ONE
  `interaction.response.edit_message` ack (cue + disabled copy) before the off-loop
  fetch; the result and every error surface land via `edit_original_response`
  (followup path), never a second `response.*`. No `InteractionResponded` path exists.
- **Operator gate (D-11/D-12/D-13):** `interaction_check`'s non-operator reject is a
  single identity-free `"This panel is in use by someone else."` ephemeral, logs
  explicitly via structlog, runs no handler, and `return False` does not route through
  `on_error` (test `test_reject_does_not_call_on_error` proves it).
- **Failure isolation:** per-callback non-propagating `try/except` in
  `on_command`/`on_select` PLUS a `View.on_error` backstop; `test_callback_raise_isolated`
  proves a raising handler returns cleanly and still answers in place.
- **In-memory selection:** `_selected_location` is held as an attribute, defaulted to
  `locations[0]`, re-set by `on_select`, and never re-read from `Select.values` in a
  button callback (Pitfall 3).
- **W2 byte-identity, CLI skip-guard, registry anti-drift:** the `weather` reply renders
  to the same Now/High·Low/Rain fields as `build_inbound_embed`; the CLI `_HANDWRITTEN`
  skip-guard keeps the registry loop from re-`add_parser("weather")` (verified `--help`
  builds cleanly, `weather` appears once); the registry anti-drift suite passes.

Off-loop discipline holds (all fetch + the whole `dispatch_reply` ladder run via
`run_in_executor`), no new deps/intents are introduced, and structlog is used throughout.
All 49 Phase-17 tests pass. The findings below are robustness/consistency gaps, not
breaks in the core invariants.

## Warnings

### WR-01: Empty `config.locations` crashes `PanelView.__init__` and builds an invalid Select

**File:** `weatherbot/interactive/panel.py:178-186` (and `weatherbot/config/models.py:481`)
**Issue:** The constructor does
`locations = [loc.name for loc in config.locations]` then
`self._selected_location = locations[0]`. `Config.locations` is typed
`list[Location]` with NO `min_length=1` validator (models.py:481 — confirmed no
non-empty guard), so an empty `[[locations]]` config loads successfully. With zero
locations the constructor raises a bare `IndexError` at `locations[0]`, and
`LocationSelect` is built with `options=[]` — which `discord.py` accepts at
construction but Discord rejects at send time (`HTTPException`). The module docstring
positions the panel as the "fail LOUD at construction" surface (the `_assert_layout`
guard), yet the empty-locations case neither fails with an actionable message nor is
caught by `_assert_layout` (which only checks the `<= 25` upper bound, not `>= 1`).
**Fix:** Add a build-time guard with an actionable message, e.g. in `__init__` before
`locations[0]`:
```python
if not locations:
    raise ValueError(
        "panel requires at least one configured location; "
        "config.locations is empty"
    )
```
(or extend `_assert_layout` to assert `1 <= len(locations) <= _MAX_OPTIONS`).
Ideally also add `min_length=1` to the `Config.locations` field so every surface
benefits, but the panel-local guard is the minimum fix for this phase.

### WR-02: Bot-reject branch in `interaction_check` is silent — no log, no audit record

**File:** `weatherbot/interactive/panel.py:235-236`
**Issue:** The gate's first rung is
`if interaction.user.bot: return False` with no structlog line and no reply. The method
docstring (lines 228-233) asserts the reject log "is the SOLE audit record" because a
clean `return False` does NOT route through `on_error` — but that guarantee only holds
for the non-operator branch (235-247), which DOES log. A bot-triggered reject is
therefore completely invisible: it leaves no record at all, contradicting the stated
audit invariant. This is the same class of "a clean `return False` is invisible" gap
the non-operator branch was explicitly built to close.
**Fix:** Log the bot reject before returning, mirroring the non-operator branch:
```python
if interaction.user.bot:
    _log.info(
        "panel reject (bot)",
        user_id=interaction.user.id,
        custom_id=(interaction.data or {}).get("custom_id"),
    )
    return False
```

## Info

### IN-01: `_safe_error_edit` if/else branches are redundant

**File:** `weatherbot/interactive/panel.py:380-397`
**Issue:** Both the `is_done()`-True branch (382-385) and the `else` branch (390-393)
call `edit_original_response(...)` first. The only behavioral difference is that the
`else` branch wraps it in an inner `try/except` that falls back to
`response.send_message` for a truly un-acked interaction. As written the `is_done()`
check buys almost nothing — the True branch could simply share the else-branch logic
(an already-acked interaction's inner `send_message` fallback would just be unreachable,
harmlessly). The duplicated `edit_original_response` call obscures the one meaningful
distinction (the un-acked `send_message` fallback).
**Fix:** Collapse to a single path that always attempts `edit_original_response` and
falls back to `send_message` only when `not interaction.response.is_done()`:
```python
try:
    await interaction.edit_original_response(
        content=_ERROR_REPLY, embed=None, view=self
    )
except Exception:  # noqa: BLE001
    if not interaction.response.is_done():
        await interaction.response.send_message(_ERROR_REPLY, ephemeral=True)
    else:
        _log.exception("panel error reply failed")
```

### IN-02: "byte-identical render" claim is narrower than stated

**File:** `weatherbot/interactive/commands/weather_views.py:94-115` and
`weatherbot/interactive/bot.py:124-191`
**Issue:** The `weather` handler docstring claims the reply renders "byte-identically"
to `build_inbound_embed`. Two render-path differences mean true byte-identity holds only
for normal-length values: (1) `render_embed` clips title and field name/value to
Discord's caps via `_clip` (bot.py:146,169-170), whereas `build_inbound_embed` writes
them raw — they diverge only for a pathologically long location name (>256 chars),
which is degenerate; (2) both stamp an independent `discord.utils.utcnow()`
(bot.py:190 vs bot.py:213), so the `timestamp` field differs by the microseconds
between the two calls. The test (`test_weather_spec_byte_identical`) correctly compares
only title + fields, not the timestamp, so the contract that matters (Now/High·Low/Rain
+ title) is genuinely pinned. The wording "byte-identical" just overstates the timestamp
and clipping edge.
**Fix:** Tighten the docstring to "renders to identical title + Now/High·Low/Rain
fields" (excluding the independently-stamped timestamp), so the invariant the test
actually enforces is the one documented.

### IN-03: `PanelView` is not yet instantiated in the runtime (intentional, noted for traceability)

**File:** `weatherbot/interactive/panel.py` (whole module)
**Issue:** A grep of `weatherbot/` finds no runtime caller of `PanelView`/`add_view`
outside the module itself — its only consumer this phase is the test suite. This is
explicitly by design: the module docstring (lines 40-41) defers persistent `add_view`
registration to Phase 18. Flagged only so the reviewer/orchestrator records that the
panel ships dark this phase (no live operator can reach it yet), and that the Phase-18
follow-up is the one that must add the `add_view` registration + the on-ready re-attach.
**Fix:** None required for Phase 17. Ensure Phase 18 wires `bot.py`'s client setup to
construct and `add_view` a `PanelView`, and confirm the persistent re-attach path (a
fresh process re-binds the static `custom_id`s) is tested before the panel is considered
live.

---

_Reviewed: 2026-06-24T02:50:38Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
