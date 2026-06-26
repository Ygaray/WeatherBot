---
phase: 18-persistence-summon-lifecycle-restart-durability
fixed_at: 2026-06-26T20:30:34Z
review_path: .planning/phases/18-persistence-summon-lifecycle-restart-durability/18-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 18: Code Review Fix Report

**Fixed at:** 2026-06-26T20:30:34Z
**Source review:** .planning/phases/18-persistence-summon-lifecycle-restart-durability/18-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (3 Warning + 4 Info — fix_scope `all`)
- Fixed: 7
- Skipped: 0

## Verification

Both phase gates were run from the isolated worktree against the edited source (cwd
resolves `weatherbot` to the worktree copy, not the editable install):

- **Full test suite:** `.venv/bin/python -m pytest -q` → **625 passed, 1 warning**
  (baseline 622; net +3 tests added: WR-03 ×2, IN-04 ×1; the WR-01 forwarding test
  was rewritten in place). The lone warning is a pre-existing `audioop`
  DeprecationWarning from `discord/player.py`, unrelated to this work.
- **Lint (required gate):** `.venv/bin/ruff check weatherbot` → **All checks passed!**

Note: `ruff check` on the **test** files surfaces one `F841` (unused `view`) at
`tests/test_panel.py:194`. It is **pre-existing** (predates this fix session — it sits
in code untouched by any finding) and is outside the enforced `ruff check weatherbot`
scope, so it was left as-is rather than expanding scope into unrelated test cleanup.

## Fixed Issues

### WR-01: `panel_channel_id` is a required parameter of `build_client` / `BotThread` but is never read

**Files modified:** `weatherbot/interactive/bot.py`, `weatherbot/scheduler/daemon.py`, `tests/test_bot.py`
**Commit:** 6c61ea6
**Applied fix:** Chose Option A (drop the no-op parameter) — the least-churn fix that
matches actual behavior and keeps locked decision D-04 intact. The `!panel` summon
re-reads `holder.current().bot.panel_channel_id` live, and `[bot]` keys are
read-once-at-startup (restart-boundary), so the live holder read IS the construction-time
value — the bot never needs a cached copy. Removed `panel_channel_id` from
`build_client()` and `BotThread.__init__()` signatures, removed the
`BotThread → build_client` forward, removed the `daemon.py:1594` call-site kwarg
(production wiring stays correct — the summon still reads the real configured channel
via the holder), and rewrote the `build_client` docstring to describe the live-holder
read instead of the inaccurate "read once at startup" parameter claim. Updated the three
`build_client` callers and the three `BotThread` lifecycle-test constructions in
`test_bot.py`; replaced `test_bot_thread_forwards_panel_channel_id` with
`test_bot_thread_does_not_take_panel_channel_id` (asserts passing the param now raises
`TypeError` and that it is never forwarded downstream). The `BotConfig.panel_channel_id`
config field itself (D-04 LOCKED) was NOT touched.

### WR-02: `BotThread` test doubles default `panel_channel_id=None`, masking the now-required parameter

**Files modified:** `tests/test_scheduler.py`
**Commit:** d28e851
**Applied fix:** Per WR-02's stated resolution ("If WR-01 is fixed by removing the
parameter, delete it from the doubles instead"), dropped the `panel_channel_id=None`
stub kwarg from all three daemon test doubles (`_RecordingBotThread`,
`_CapturingBotThread`, `_ExplodingBotThread`) so they mirror the real (now-tighter)
`BotThread.__init__` signature. The assertion WR-02 also requested
(`captured["panel_channel_id"] == config.bot.panel_channel_id`) is moot under the
WR-01 removal — there is no longer a `panel_channel_id` to forward — so it was
intentionally not added.

### WR-03: `_handle_panel_summon` assumes a Messageable text channel and non-None `guild.me`

**Files modified:** `weatherbot/interactive/bot.py`, `tests/test_bot.py`
**Commit:** c3a79b7
**Applied fix:** Tightened the step-(1) resolve check so a valid-but-wrong
`panel_channel_id` resolving to a non-text channel (Category/Voice/Forum) and a
`None` `guild.me` (bot not yet cached as a guild member) are both treated as the
"inaccessible" case — sending the actionable copy and aborting BEFORE the permission
preflight, instead of falling through to `permissions_for(None)` / `channel.pins()` and
the generic `on_message` error-envelope fallback. Used a duck-typed check
(`hasattr(channel, "pins")` and `hasattr(channel, "send")` + `guild.me is not None`)
rather than `isinstance(channel, discord.abc.Messageable)`: the reviewer's literal
`isinstance` suggestion would have broken every gateway-free `MagicMock` panel test
(MagicMock is not a Messageable instance) and is also imprecise (VoiceChannel is
Messageable in discord.py 2.x yet has no usable pin surface) — `.pins`/`.send`
duck-typing is the correct discriminator (TextChannel/Thread have them, CategoryChannel
does not) and is fake-friendly. Added two tests: wrong-channel-type and `None` guild.me,
each asserting the actionable copy (not `_ERROR_REPLY`) and that no preflight ran.

### IN-01: Unconfigured-channel copy names `panel_channel_id` as "not configured", but the field is now required

**Files modified:** `weatherbot/interactive/bot.py`
**Commit:** d791525
**Applied fix:** Reworded `_PANEL_CHANNEL_UNCONFIGURED` to lead with the inaccessible
framing ("Can't reach the configured panel channel — check the channel exists, that I'm
in that server, and that it's a text channel.") since, with `panel_channel_id` now a
required `BotConfig` field, this branch can only be reached via the inaccessible case.
Deliberately kept "[bot] panel_channel_id" + "restart" in the copy (framed as the
repoint action) so the existing D-04 test
(`test_panel_channel_missing_aborts_without_crash`, which asserts both substrings)
stays valid and the operator still learns the key to change.

### IN-02: Preflight emits raw discord attribute names to the operator

**Files modified:** `weatherbot/interactive/bot.py`, `tests/test_bot.py`
**Commit:** 586cf8e
**Applied fix:** Added a `_PANEL_PERM_LABELS` map (`pin_messages → "Pin Messages"`,
`read_message_history → "Read Message History"`, etc.) and translated the
operator-facing `_panel_missing_perms_copy` to the Discord UI labels so the operator can
find the exact toggle. The structured CRITICAL log keeps the raw discord.py attribute
names (`missing=missing`) for diagnosis (Security V7). Updated the perms test to assert
"Pin Messages" appears in operator copy AND that the raw `pin_messages` identifier never
reaches the operator, while still asserting the raw name in the log blob.

### IN-03: `_disabled_copy` rebuild duplicates option state by hand

**Files modified:** `weatherbot/interactive/panel.py`
**Commit:** d8c4147
**Applied fix:** Added a maintenance note to `_disabled_copy`'s docstring pinning the
requirement that any new child KIND added to `PanelView` (e.g. a Phase-19 forecast
button) MUST get a matching branch here or it will silently be dropped from the disabled
ack view. Comment-only; no behavior change (this was the reviewer's "Fix (optional)").

### IN-04: `_is_owned_panel` relies on `Member`/`User` `__eq__` identity

**Files modified:** `weatherbot/interactive/panel.py`, `tests/test_panel.py`
**Commit:** b3041b4
**Applied fix:** Replaced `if msg.author != bot_user` with an explicit snowflake-id
comparison (`getattr(msg.author, "id", None)` vs `getattr(bot_user, "id", None)`;
`None` on either side → not owned, the safe default) so the "don't touch foreign pins"
intent is self-evident and independent of discord.py's `__eq__` contract. Updated the
`_FakeBotUser` stand-in to carry an `.id` (unique-per-instance by default, overridable)
and added `test_is_owned_panel_matches_distinct_objects_with_same_id` covering the
Member-vs-User cache-state case (two distinct objects sharing the same `.id` are owned).

---

_Fixed: 2026-06-26T20:30:34Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
