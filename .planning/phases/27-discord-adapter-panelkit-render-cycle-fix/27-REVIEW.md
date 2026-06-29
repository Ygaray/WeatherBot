---
phase: 27-discord-adapter-panelkit-render-cycle-fix
reviewed: 2026-06-29T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - yahir_reusable_bot/discord/selection.py
  - yahir_reusable_bot/discord/panelkit.py
  - yahir_reusable_bot/discord/gateway.py
  - yahir_reusable_bot/discord/__init__.py
  - weatherbot/interactive/bot.py
  - weatherbot/interactive/panel.py
  - weatherbot/interactive/__init__.py
  - weatherbot/scheduler/wiring.py
  - weatherbot/scheduler/daemon.py
  - tests/test_import_hygiene.py
  - tests/test_injection_registry.py
  - tests/test_panelkit_marker.py
  - tests/test_panel.py
  - tests/test_bot.py
  - tests/test_scheduler.py
findings:
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 27: Code Review Report

**Reviewed:** 2026-06-29
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 27 is a byte-identical brownfield extraction of the Discord adapter (`BotThread` +
`PanelKit` + generic `SelectedContext[I]`) from `weatherbot/interactive/{bot.py,panel.py}`
into `yahir_reusable_bot/discord/`, resolving the `render_embed`↔`PanelView` cycle by
ownership and injecting `render_embed` via a `_render_bridge(reply, ctx)` closure at the
`wiring.build_inbound_bot` composition root.

I focused on latent correctness/security issues a green byte-identical suite would NOT
catch: behavior paths with no golden, cross-thread/cross-tap races, secret handling, and
injection vectors.

The headline finding is **WR-01**: the relocation introduced a new shared-mutable
`render_location[0]` cell to bridge the signature mismatch between the module's
`render(reply, ctx)` contract and the app's `render_embed(reply, *, location=)`. This cell
is written *before* an `await` (the off-loop `dispatch_spec` fetch) and read *after* the
await resolves — a genuine interleaving window that did NOT exist in the pre-relocation
code, where `location` was a callback-local variable. The single-writer contract that
`selection.py` documents holds for the *selection holder* but does NOT hold for this new
cell, because the off-loop `run_in_executor` fetch genuinely yields the loop mid-tap and
discord.py does not serialize component interactions per-view.

The security posture is sound: the operator gate is preserved verbatim (bot reject +
identity-free ephemeral with zero interpolation), the marker is unforgeable and
app-supplied, no secret (token/appid) is threaded into views or logs, and the module tree
imports zero app code (gated three ways). The remaining findings are robustness/quality
items.

## Warnings

### WR-01: New shared `render_location[0]` cell races across concurrent taps (📍 may render on wrong/argless reply)

**File:** `weatherbot/scheduler/wiring.py:393-452` (and the mirrored harness at `tests/test_panel.py:196-241`)
**Issue:**
The relocation replaced the v1 direct call `render_embed(reply, location=arg)` (where `arg`
was a callback-local variable) with a one-slot module-level cell:

```python
render_location: list[str | None] = [None]
def _render_bridge(reply, ctx):
    return render_embed(reply, location=render_location[0])
async def _dispatch(name, selection) -> DispatchOutcome:
    ...
    render_location[0] = arg            # write
    reply = await dispatch_spec(...)    # ← yields the loop (off-loop run_in_executor fetch)
    ...
```

`PanelKit.on_command` calls `outcome = await self._dispatch(...)` and *then*
`self._render(outcome.reply, self._selection)` which reads `render_location[0]`. The write
happens before an `await` that genuinely suspends (the fetch runs in a thread-pool
executor). The docstring asserts "every tap runs `dispatch` then `render` serially on the
same loop, so the cell is set immediately before it is read with no interleaving" — but
that is only true if discord.py serializes interactions for one view. It does not:
discord.py dispatches each component interaction as its own `asyncio` task
(`_scheduled_task`), so two near-simultaneous operator taps interleave at the
`await dispatch_spec` boundary. Sequence:

1. Tap A (`status`, argless): `render_location[0] = None`, awaits dispatch, suspends.
2. Tap B (`weather travel`): `render_location[0] = "travel"`, awaits dispatch, suspends.
3. Tap A resumes; `on_command` renders → reads `render_location[0] == "travel"` → the
   `status` embed now carries a `📍 travel` line that v1 would have suppressed.

This is the exact 📍-argless-suppression contract (D-01) the phase calls load-bearing, and
it has **no golden** because every golden test drives a single tap to completion. The blast
radius is cosmetic (a wrong/extra location indicator line), not data loss — hence WARNING,
not BLOCKER — but it is real behavior drift introduced by the relocation, and a single
operator double-tapping fast enough during a slow OpenWeather fetch can hit it.

Note the `operator_id != self._operator_id` gate means only the single operator can drive
the panel, which *reduces* but does not eliminate the window: one human can tap two buttons
within one slow-fetch interval, and discord delivers both interactions concurrently.

**Fix:** Bind the render location to the tap, not a shared cell. The cleanest fix keeps
`render_embed` untouched and carries the location on the `DispatchOutcome` the module
already threads back:

```python
# panelkit.py — add a neutral, opaque field the module forwards but never inspects:
@dataclass(frozen=True)
class DispatchOutcome:
    reply: Any = None
    error_message: str | None = None
    render_arg: Any = None      # opaque: app's per-tap render context

# on_command: pass the per-tap value straight through (no shared state)
embed=self._render(outcome.reply, outcome.render_arg)

# wiring._dispatch: return the location WITH the outcome
return DispatchOutcome(reply=reply, render_arg=arg)        # location path
return DispatchOutcome(reply=reply, render_arg=selection.value)  # forecast path
# and _render_bridge reads its 2nd positional arg instead of the cell:
def _render_bridge(reply, render_arg):
    return render_embed(reply, location=render_arg)
```

This makes the bridge stateless and per-tap, eliminating the interleaving window while
preserving the module's "render is opaque" contract.

---

### WR-02: `on_command` error-message path does not record/restore the per-tap render arg (latent coupling to WR-01)

**File:** `yahir_reusable_bot/discord/panelkit.py:350-357`; `weatherbot/scheduler/wiring.py:449-451`
**Issue:**
On the `UnknownLocationError` branch, `_dispatch` returns `DispatchOutcome(error_message=...)`
*after* having set `render_location[0] = arg` for this tap (the write at wiring.py:440/426
precedes the `try` that catches the error). The error branch in `on_command` edits content
with `embed=None`, so the stale `render_location[0]` is not consumed *this* tap — but the
cell is left holding this tap's location, and the next tap's render (if it is an argless
command whose own write is somehow skipped by an early raise) could read it. This is the
same root cause as WR-01 (shared mutable cell) surfacing on the error path; fixing WR-01 as
described (per-tap `render_arg` on the outcome) closes this too. Calling it out separately
because the error path is itself golden-free.
**Fix:** Subsumed by WR-01's per-tap `render_arg` fix — no cell to leave stale.

---

### WR-03: `summon_panel` deletes ALL matched owned panels including the (possibly still-live) prior one — relies on create-before-delete but does not verify the fresh pin survived

**File:** `yahir_reusable_bot/discord/gateway.py:148-165`
**Issue:**
The create-before-delete ordering is correct (send+pin fresh, then delete priors), and the
per-write `discord.Forbidden` is caught. But the delete loop `for old in matches: await
old.delete()` runs *after* the fresh `msg.pin()` with no guard that the fresh pin actually
succeeded as a pin (only that `send` + `pin` did not raise `Forbidden`). If `msg.pin()`
raises a non-`Forbidden` error (e.g. `HTTPException` because the channel already holds 50
pins — Discord's hard cap, which is plausible precisely when strays have accumulated), the
exception propagates out of the `try` (only `discord.Forbidden` is caught), the prior owned
panels are NOT deleted, and the whole `summon_panel` raises up into
`build_panel_summon`/`on_message`'s envelope → generic error reply. The net effect is a
zero-*new*-pin outcome with strays intact — recoverable, but the operator gets the generic
"something went wrong" rather than an actionable message, during exactly the cleanup moment
the command exists for.
This is a pre-existing edge (the 50-pin cap) that the relocation carried along, so it is a
WARNING and arguably out of strict byte-identical scope — flagging because the relocation is
the natural point to harden it and the pin-cap interacts with the stray-cleanup path.
**Fix:** Catch `discord.HTTPException` (superclass of `Forbidden`) around the pin/cleanup
and, on a pin-cap failure, delete the oldest stray first then retry the pin; or at minimum
log a CRITICAL naming the pin cap so the operator can manually unpin. At a minimum, widen
the existing `except discord.Forbidden` documentation to note that a non-403 pin failure
still bubbles to the generic reply.

---

### WR-04: `LocationSelect.callback` and harness reach into module-private `_build_clone_view` / `_safe_error_edit` — fragile cross-package coupling

**File:** `weatherbot/interactive/panel.py:252,255`
**Issue:**
The app component calls `panel._build_clone_view()` and `panel._safe_error_edit(interaction)`
— two underscore-prefixed module-internal methods of `PanelKit` — from across the
package/repo boundary. The whole point of the extraction is a clean reusable module with a
stable public surface; reaching into `_`-private methods means any future refactor of
`PanelKit`'s internals (e.g. renaming the clone path, as the litmus already forced once:
the harness comment at test_panel.py:317-320 notes the method was renamed to avoid a
`render`/`location` name) silently breaks the app component with no type/test guard at the
seam. The module exposes no public "re-render this panel in place" / "best-effort error
edit" verb for contributors to use.
**Fix:** Promote the two operations contributors legitimately need to a public contract —
e.g. `PanelKit.rerender_clone()` and `PanelKit.safe_error_edit(interaction)` (or pass a
small injected "panel ops" facade into contributors). Keep the litmus-safe generic names.
This converts an implicit private-method dependency into an explicit supported seam.

## Info

### IN-01: `_render_bridge` and `_dispatch` ignore the `ctx`/`selection` they are handed — dead parameter signals confusion at the seam

**File:** `weatherbot/scheduler/wiring.py:401-402`
**Issue:**
`def _render_bridge(reply, ctx): return render_embed(reply, location=render_location[0])` —
the `ctx` (the `SelectedContext` the module passes per the `render(reply, ctx)` contract) is
accepted and discarded; the actual render location is pulled from the shared cell instead.
This is the structural smell that produces WR-01: the module hands the bridge exactly the
live selection it needs, but the bridge cannot use it directly because the selection always
holds a location (it cannot express argless suppression). Fixing WR-01 (per-tap `render_arg`)
removes the dead `ctx` param and makes the data flow honest.
**Fix:** After adopting WR-01's `render_arg`, the bridge becomes `def _render_bridge(reply,
render_arg): return render_embed(reply, location=render_arg)` — every parameter is used.

### IN-02: `is_owned_panel` walk reads `msg.components` without a defensive `getattr`, unlike the rest of the walk

**File:** `yahir_reusable_bot/discord/panelkit.py:468`
**Issue:**
The ownership predicate is documented as "defensive `getattr` throughout — an unexpected
component shape is skipped, never raised on," and the inner walk does use
`getattr(row, "children", [])` / `getattr(child, "custom_id", None)`. But the outer
`for row in msg.components:` assumes `msg.components` is iterable; a `Message` stand-in (or
a future discord.py shape) where `.components` is `None` would raise `TypeError` here,
defeating the stated "can't crash the bot thread" guarantee. The summon path's per-write
`Forbidden` catch would not cover this (it is a `TypeError`, raised during the pin *scan*
which is inside the `try` — so it would actually be swallowed by `on_message`'s envelope,
but as a generic error, not the intended skip). Low severity since real discord.py always
sets `.components` to a list.
**Fix:** `for row in getattr(msg, "components", []) or []:` to match the documented
defensive posture.

### IN-03: `CmdButton.__init__` / `PanelKit.__init__` have no guard that `labels[name]` / `command_rows[name]` exist for every curated name

**File:** `yahir_reusable_bot/discord/panelkit.py:206-213`
**Issue:**
`_build_command_buttons` asserts `name in by_name` (good — fails loud) but then does
`self._labels[name]` and `self._command_rows[name]` with a bare `[]` subscript. If an app
supplies `command_names` that includes a name missing from `labels` or `command_rows`, this
raises a bare `KeyError` at construction rather than the curated, actionable `AssertionError`
the `by_name` check models. For WeatherBot the maps are kept in lockstep app-side (panel.py
builds them from the same `_LOCATION_CMDS`/`_ARGLESS_CMDS` tuples, so today it is safe), but
a future reusing bot gets a cryptic `KeyError` instead of "panel curated command X has no
label." Quality/ergonomics for the reusable-module goal, not a WeatherBot bug.
**Fix:** Mirror the `by_name` assert: `assert name in self._labels, f"panel command {name!r}
has no label"` (and same for `command_rows`) before constructing the button.

---

_Reviewed: 2026-06-29_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
