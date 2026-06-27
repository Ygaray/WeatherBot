---
phase: 20-isolation-hardening-polish
reviewed: 2026-06-26T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - weatherbot/interactive/bot.py
  - weatherbot/interactive/panel.py
  - tests/test_bot.py
  - tests/test_panel.py
  - tests/test_scheduler.py
  - tests/test_dispatch.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 20: Code Review Report

**Reviewed:** 2026-06-26
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Adversarial review of the Phase 20 polish slice: `render_embed(location=)` + `📍`/`Updated <t:>`
description lines (bot.py), per-button emoji + dropdown `default=True` re-mark surviving the
`_render_view` clone (panel.py), and two test-only isolation proofs (the live-scheduler
hanging-callback test and the D-08b executor-sharing audit).

The two load-bearing clone-path mechanisms the review focus called out are **correct**:

- `_render_view`'s Button clone copies `emoji=child.emoji` onto the plain `discord.ui.Button`
  clone (panel.py:727), so the glyph survives every ack/collapse render.
- `_render_view`'s Select clone re-derives `default=(o.value == self._selected_location)`
  from `_selected_location`, NOT from `Select.values` (panel.py:743-748), so the highlight
  survives the clone and never reads the empty `Select.values`.
- `render_embed` correctly suppresses the `📍` line when `location is None` (bot.py:223) and
  keeps the `<t:>` markdown in the description, never the title (bot.py:225-229).
- The hanging-callback test wedges via `await asyncio.Event().wait()` (loop-yielding, not a
  CPU spin), confirms entry before judging the briefing, and shuts the live scheduler down in
  a `finally` (test_scheduler.py:2058, 2081, 2105).

No BLOCKER-class defects (incorrect behavior, security, data loss) were found. The findings
below are robustness/maintainability concerns plus one resource-hygiene note on the new tests.

## Warnings

### WR-01: `_render_view` Select clone discards the option's real `label`, silently substituting `value`

**File:** `weatherbot/interactive/panel.py:743-749`
**Issue:** The Select clone rebuilds each option as
`discord.SelectOption(label=o.value, value=o.value, default=...)` — it derives `label` from
`o.value`, **discarding `o.label`**. Today this is invisible because `LocationSelect.__init__`
builds options with `label=n, value=n` (panel.py:294-296), so label == value. But the moment a
location is ever given a display label distinct from its value (a foreseeable evolution — e.g.
`label="Home (NYC)"`, `value="home"`), every ack/collapse re-render would silently relabel the
dropdown to the bare value. The construction-time view would show the friendly label; the very
next clone (the most common path) would revert it. This is the exact class of "survives __init__,
reverts on clone" trap the phase was hardening against, left latent on the label axis.
**Fix:** Copy the label through instead of re-deriving it from value:
```python
options=[
    discord.SelectOption(
        label=o.label,
        value=o.value,
        default=(o.value == self._selected_location),
    )
    for o in child.options
],
```
The `default=` re-derivation from `_selected_location` is correct and must stay; only the
`label=` source should change.

### WR-02: `_render_view` Select clone drops `min_values`/`max_values` (and other Select knobs)

**File:** `weatherbot/interactive/panel.py:736-753`
**Issue:** The clone reconstructs the `discord.ui.Select` from only `custom_id`, `placeholder`,
`options`, `row`, `disabled`. It does NOT carry `min_values`/`max_values` from `child`. This is
benign **only because** `LocationSelect` never overrides those (so both source and clone default
to `min_values=1, max_values=1`). Like WR-01, it is a clone path that re-specifies a subset of the
source's identity rather than mirroring it, so any future single-select → multi-select change (or
a `placeholder`-independent option-count constraint) would apply on the registered view but vanish
on every re-render. Given this clone path is explicitly the "kill the two-path drift" mechanism
(panel.py:695), re-specifying a partial field set reintroduces a drift surface.
**Fix:** Either copy the values explicitly
(`min_values=child.min_values, max_values=child.max_values`) or add a short comment asserting the
clone deliberately assumes the single-select invariant so a future editor knows to update it.

### WR-03: New live-scheduler/wedge tests leak a never-terminating thread + event loop per run

**File:** `tests/test_scheduler.py:2074-2078`
**Issue:** `test_hanging_callback_never_stops_live_briefing` starts a daemon thread that runs
`asyncio.run(view.on_command(...))` where the dispatch seam is monkeypatched to
`await asyncio.Event().wait()` and never resolves. The thread is intentionally `daemon=True` so it
cannot block teardown — that part is sound. But the thread (and its asyncio event loop) is never
joined or cancelled: it stays alive, holding the wedged coroutine and an open loop, for the
remainder of the pytest process. In a single run this is one leaked daemon thread; under
`pytest-repeat`/`-n` parallel/repeated invocation it accumulates one leaked thread + loop per
iteration. It also means the `monkeypatch.setattr(panel_mod, "dispatch_spec", _hang)` target is
still being awaited on that thread after the test body returns and monkeypatch restores the
attribute — a benign-but-surprising lifetime overlap. This is a test-hygiene defect, not a
production one (the production isolation guarantee the test asserts is real and correct).
**Fix:** This may be acceptable as a deliberate trade (a truly wedged callback cannot be cleanly
cancelled without the watchdog the phase intentionally omits per D-09). If kept, add an explicit
comment at the thread start documenting that the daemon thread + loop are knowingly leaked for the
process lifetime and why (mirrors the D-08a/D-09 rationale already in the docstring). If
tightenable, run the wedge on a dedicated loop you can `call_soon_threadsafe(loop.stop)` in the
`finally` so the thread unwinds after the assertions.

## Info

### IN-01: `render_embed` description is never length-bounded against Discord's 4096-char cap

**File:** `weatherbot/interactive/bot.py:221-229`
**Issue:** Field names/values and the title are all clipped to their Discord caps (`_clip`,
`_MAX_*`), but the newly-introduced `description` (`📍 {location}` + `Updated <t:…>`) is assembled
and assigned with no bound. Discord rejects an embed whose description exceeds 4096 chars with an
`HTTPException`, which the `on_message`/panel envelopes would turn into the generic error reply.
`location` is config-controlled and short today, so this is not currently reachable — but it is the
one render axis the phase added that is NOT defensively clipped like every sibling field.
**Fix:** Clip the joined description, e.g. `description=_clip("\n".join(desc_lines), 4096)` (or a
named `_MAX_DESCRIPTION = 4096` constant for parity with the other caps).

### IN-02: `_emoji_str` test helper compares against `emoji.name`, which can mask a wrong-codepoint emoji

**File:** `tests/test_panel.py:972-977`
**Issue:** `_emoji_str` returns `getattr(emoji, "name", None) or str(emoji)`. For a unicode emoji,
discord.py's `PartialEmoji.name` holds the glyph, so this works — but it is comparing a derived
attribute rather than the actual rendered emoji payload. The emoji-survival assertions
(test_panel.py:994, 1019, 1045) therefore pin "the `.name` round-trips" rather than "the exact
emoji the client renders." This is adequate for the current single-codepoint glyphs but would not
catch a variation-selector / ZWJ-sequence mismatch (several Phase 20 glyphs like `🌡️`, `☁️`, `⚠️`
carry a U+FE0F variation selector). Low risk; flagged for completeness.
**Fix:** Optionally also assert the raw `str(child.emoji)` or compare codepoints
(`[hex(ord(c)) for c in ...]`) for the variation-selector glyphs.

### IN-03: Duplicated emoji source-of-truth between production `_EMOJI` and test `_EXPECTED_CMD_EMOJI`

**File:** `weatherbot/interactive/panel.py:121-129` and `tests/test_panel.py:954-969`
**Issue:** The locked glyph mapping is hand-copied into the test as `_EXPECTED_CMD_EMOJI` /
`_EXPECTED_FC_EMOJI` (byte-for-byte). That is a legitimate test pattern (an independent transcription
guards against an accidental production edit), but there is no test asserting the production `_EMOJI`
dict itself matches the UI-SPEC set — the forecast/toggle glyphs in particular are defined at their
construction sites (panel.py:263, 372-393), not in a single dict, so a typo there is only caught
transitively. Acceptable; noted so a future editor knows the test copy is intentional, not stale.
**Fix:** None required. If desired, assert `panel._EMOJI == _EXPECTED_CMD_EMOJI` directly so a
production-dict edit fails loudly with a clear message.

### IN-04: `test_dispatch.py` executor-audit relies on a brittle regex over source text

**File:** `tests/test_dispatch.py:469-501`
**Issue:** `test_briefing_path_not_on_default_executor` proves the D-08b isolation by `rglob`-ing
`weatherbot/` and regex-matching `run_in_executor(\s*None`. This is a structural/"grep test" — it
will silently pass if the call is ever written as `run_in_executor(executor=None, …)`,
`run_in_executor(*(None, fn))`, or split across lines, and will false-FAIL if a docstring/comment
elsewhere ever contains the literal `run_in_executor(None`. The test's own docstring acknowledges
it is a confirming audit (Pitfall 4), so this is low-stakes, but a source-text regex is a fragile
proxy for the actual runtime invariant (two distinct executor objects).
**Fix:** None required for v1. If hardened later, assert the runtime fact instead (e.g. that the
scheduler's `BackgroundScheduler` pool and the panel's default-loop executor are distinct objects),
or constrain the audit to actual AST call sites.

---

_Reviewed: 2026-06-26_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
