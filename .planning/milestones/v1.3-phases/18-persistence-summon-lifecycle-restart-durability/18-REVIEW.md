---
phase: 18-persistence-summon-lifecycle-restart-durability
reviewed: 2026-06-26T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - weatherbot/config/models.py
  - weatherbot/interactive/bot.py
  - weatherbot/interactive/panel.py
  - weatherbot/scheduler/daemon.py
  - tests/conftest.py
  - tests/test_bot.py
  - tests/test_config.py
  - tests/test_models.py
  - tests/test_panel.py
  - tests/test_scheduler.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 18: Code Review Report

**Reviewed:** 2026-06-26
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Reviewed the Phase 18 diff against `f3448bd` (persistent-view registration in
`setup_hook`, the idempotent `!panel` operator summon, the channel permission
preflight, and the new required `panel_channel_id` config field). The
implementation is correct and well-isolated: the `!panel` branch rides the existing
non-propagating `on_message` envelope, the permission preflight runs before any
write, the marker-strict `_is_owned_panel` scan avoids touching unrelated bot pins,
and `setup_hook` (not `on_ready`) registers the persistent view exactly once. I
verified against the installed `discord.py 2.7.1` that `Permissions.pin_messages`
exists and `channel.pins()` is an async iterator — both assumptions the code rests
on hold. The full phase test suite (187 tests) passes.

No BLOCKER-class correctness or security defects were found. The findings below are
quality and robustness issues — chief among them a **required `panel_channel_id`
parameter on `build_client`/`BotThread` that is never used** (the summon re-reads it
from the holder), which is misleading and a maintenance trap. There are also a
couple of unguarded Discord-object assumptions that currently only survive because
the broad outer `except Exception` swallows them.

## Warnings

### WR-01: `panel_channel_id` is a required parameter of `build_client` / `BotThread` but is never read

**File:** `weatherbot/interactive/bot.py:489`, `weatherbot/interactive/bot.py:574-583`
**Issue:** `build_client(..., panel_channel_id: int, ...)` and
`BotThread.__init__(..., panel_channel_id: int, ...)` both add `panel_channel_id` as
a *required* keyword-only parameter, and `BotThread` forwards it into `build_client`
— but **neither function body ever reads it**. The docstring at `bot.py:500-502`
claims it "threads in here so the Plan-02 `!panel` summon can re-find the panel...
It is read once at startup," which is inaccurate: `_handle_panel_summon`
(`bot.py:272-274`) re-reads `holder.current().bot.panel_channel_id` at `!panel`
time, not from this parameter. The threaded value is dead weight. This is a
maintenance trap — a future reader will assume the bot is pinned to the
construction-time channel id, when in fact it follows the live holder. It also
forces every caller (and every test double) to supply a value that has no effect.
**Fix:** Either remove the unused parameter from both signatures (and the daemon
call site at `daemon.py:1598`), or actually consume it — e.g. pass it down to
`build_on_message`/`_handle_panel_summon` and use it instead of the holder re-read
if "read once at startup" is the intended semantic. Pick one; today the signature
and the docstring contradict the behavior.

```python
# Option A — drop the no-op parameter (simplest; matches actual behavior):
def build_client(*, holder, operator_id, cache, daemon_state=None) -> discord.Client:
    ...
# and in BotThread.__init__ / daemon.py drop panel_channel_id= entirely.
```

### WR-02: `BotThread` test doubles default `panel_channel_id=None`, masking the now-required parameter

**File:** `tests/test_scheduler.py:1050-1058`, `1123-1131`, `1193-1201`
**Issue:** The three `_RecordingBotThread` / `_CapturingBotThread` /
`_ExplodingBotThread` stand-ins declare `panel_channel_id=None` with a default,
while the real `BotThread.__init__` makes it required (no default). The stubs
therefore would not catch a daemon call site that *forgot* to pass
`panel_channel_id` — the contract the real constructor enforces is silently
loosened in the doubles. (Combined with WR-01 this is doubly unfortunate: the param
is both unused in production and under-pinned in tests.) No test actually asserts
that the daemon forwards the real `config.bot.panel_channel_id` into `BotThread`.
**Fix:** Make the test doubles mirror the real signature (drop the `=None` default
so a missing kwarg is a `TypeError`), and add an assertion in
`test_run_daemon_threads_read_only_daemon_state_into_bot` (or a sibling) that
`captured["panel_channel_id"] == config.bot.panel_channel_id`. If WR-01 is fixed by
removing the parameter, delete it from the doubles instead.

### WR-03: `_handle_panel_summon` assumes the resolved channel is a Messageable text channel and `guild.me` is non-None

**File:** `weatherbot/interactive/bot.py:278-293`, `320-323`
**Issue:** `channel = guild.get_channel(panel_channel_id)` can return any channel
type for a valid-but-wrong id — a `CategoryChannel`, `VoiceChannel`, or
`ForumChannel` — none of which support `.pins()` / `.send(embed=..., view=...)`. The
code only checks `channel is None`, then calls `me = channel.guild.me` and
`channel.permissions_for(me)` and later `channel.pins()` / `channel.send(...)`.
Separately, `channel.guild.me` is `None` if the bot is not (yet) cached as a member
of that guild, and `permissions_for(None)` would raise. Both paths currently survive
only because the outer `on_message` envelope (`bot.py:428`) swallows the resulting
`AttributeError`/`TypeError` and replies with the generic "something went wrong"
message — so the operator gets the *wrong* (generic) feedback instead of the
actionable "panel channel is not configured or is inaccessible" message that step
(1) was designed to give for exactly this misconfiguration. **Fix:** Tighten the
resolve check to treat a non-text-channel and a `None` `guild.me` as the
"inaccessible" case so the operator gets the actionable copy, not the generic
fallback:

```python
me = getattr(channel.guild, "me", None)
if me is None or not isinstance(channel, discord.abc.Messageable) or not hasattr(channel, "pins"):
    _log.error("panel summon: panel channel inaccessible or not a text channel",
               panel_channel_id=panel_channel_id)
    await message.channel.send(_PANEL_CHANNEL_UNCONFIGURED)
    return
```

## Info

### IN-01: Unconfigured-channel copy names `panel_channel_id` as "not configured", but the field is now required

**File:** `weatherbot/interactive/bot.py:89-92`
**Issue:** `_PANEL_CHANNEL_UNCONFIGURED` reads "Panel channel is not configured or
is inaccessible — set [bot] panel_channel_id and restart." Since `BotConfig` now
makes `panel_channel_id` a required field (config fails to load without it), the
`!panel` branch can only ever reach this copy via the *inaccessible* case (stale id,
bot not in guild, wrong channel type) — never the literal "not configured" case. The
"set [bot] panel_channel_id" half of the copy points the operator at a key that is,
by construction, already set. Minor operator-facing accuracy nit. **Fix:** Lead with
the inaccessible framing (e.g. "Panel channel id is set but I can't reach that
channel — check it exists, that I'm in the server, and that it's a text channel.").

### IN-02: `_panel_missing_perms_copy` / preflight emit raw discord attribute names to the operator

**File:** `weatherbot/interactive/bot.py:102-107`, `294`, `301`
**Issue:** The missing-permission reply interpolates the raw
`_REQUIRED_PANEL_PERMS` attribute names — e.g. `pin_messages`,
`read_message_history`, `embed_links` — straight into operator copy ("I'm missing
the pin_messages permission(s)"). These are Python/discord.py identifiers, not the
labels the operator sees in the Discord permission UI ("Pin Messages", "Read Message
History", "Embed Links"). The 18-UI-SPEC Copywriting Contract calls for naming the
specific fix so the operator can act; the underscore identifiers are slightly
harder to map to the UI toggle. **Fix:** Map the internal names to their Discord UI
labels for the operator message (keep the raw names in the structured log).

### IN-03: Empty `_disabled_copy` Select for a single-option panel is unreachable but the rebuild duplicates option state

**File:** `weatherbot/interactive/panel.py:406-415`
**Issue:** `_disabled_copy()` rebuilds the Select with
`options=list(child.options)`. discord.py rejects a `Select` with zero options at
send time; the live panel always has ≥1 location (guarded at construction), so this
is currently safe. Noting it as a latent coupling: the disabled-copy path
re-derives component state by hand rather than cloning, so any future child kind
(e.g. the Phase-19 forecast button) silently won't be carried into the disabled ack
view. Not a bug today. **Fix (optional):** Add a brief comment that
`_disabled_copy` must be extended whenever a new child type is added to `PanelView`,
or derive the disabled view from `self.children` generically.

### IN-04: `_is_owned_panel` relies on `Member`/`User` `__eq__` identity for `msg.author != bot_user`

**File:** `weatherbot/interactive/panel.py:126`
**Issue:** The ownership check is `if msg.author != bot_user: return False`, where
`bot_user` is `channel.guild.me` (a `Member`) and `msg.author` for a pinned bot
message may be a `Member` or a `User` depending on cache state. discord.py compares
these by snowflake `id`, so this is correct in practice — but the correctness hinges
on an implicit library `__eq__` contract rather than an explicit id comparison, and
the tests exercise it only with bare identity stand-ins (`_FakeBotUser`) that
compare by Python object identity, not by `.id`. The defensive intent (don't touch
foreign pins) would be more robustly expressed as an id comparison. **Fix
(optional):** Compare ids explicitly — `if getattr(msg.author, "id", None) !=
getattr(bot_user, "id", None): return False` — and add a test where author and
bot_user are distinct objects sharing the same `.id`.

---

_Reviewed: 2026-06-26T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
