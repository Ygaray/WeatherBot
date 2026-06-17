---
phase: 11-discord-inbound-gateway-bot
fixed_at: 2026-06-17T00:00:00Z
review_path: .planning/phases/11-discord-inbound-gateway-bot/11-REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 8
skipped: 3
status: partial
---

# Phase 11: Code Review Fix Report

**Fixed at:** 2026-06-17T00:00:00Z
**Source review:** .planning/phases/11-discord-inbound-gateway-bot/11-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 11
- Fixed: 8
- Skipped: 3

The full test suite (`uv run pytest -q`) passes after the fixes: **283 passed**.

## Fixed Issues

### IN-03: `_ERROR_REPLY` / embed color are magic literals without shared constants

**Files modified:** `weatherbot/branding.py` (new), `weatherbot/channels/discord.py`, `weatherbot/interactive/bot.py`
**Commits:** `b0e6ecc` (constant + webhook consumer), `77005a2` (gateway-embed consumer)
**Applied fix:** Created `weatherbot/branding.py` defining `BRIEFING_COLOR_HEX = "03b2f8"` as the single source of truth, with a derived `BRIEFING_COLOR_INT = int(BRIEFING_COLOR_HEX, 16)`. The webhook channel now passes `BRIEFING_COLOR_HEX` (the discord-webhook hex string) and the gateway embed passes `BRIEFING_COLOR_INT` (the discord.py int), so a brand-color change is a single edit.

### WR-03: `BotThread.start()` reports ready before the gateway login result is known

**Files modified:** `weatherbot/interactive/bot.py`
**Commit:** `77005a2`
**Applied fix:** Renamed `_ready` to `_loop_started` (event + setter in `_amain`) so the name reflects "loop is up", not "gateway connected". Tightened the `start()` docstring to state that a returned `start()` means only that the bot loop started — NOT a successful login — and directs callers to consult `is_alive()` for connection state. The 5s warning text now reads "did not signal loop-started".

### WR-04: dead-start teardown is not explicit

**Files modified:** `weatherbot/interactive/bot.py`
**Commit:** `77005a2`
**Applied fix:** Added a `_failed` flag set in BOTH `_run` except handlers (`LoginFailure` and the generic `Exception`) plus an `is_alive()` method returning `not self._failed and self._thread.is_alive()`. Failure isolation is preserved — `_run` still swallows the exception and never raises into the daemon. The daemon can now null out a confirmed-dead bot explicitly rather than inferring it from `loop.is_running()`.

### WR-05: `getattr(result, "forecast", result)` masks a real type error in production

**Files modified:** `weatherbot/interactive/bot.py`, `tests/test_bot.py`
**Commits:** `77005a2` (production), `01e5a07` (test fake)
**Applied fix:** Replaced the `getattr(result, "forecast", result)` shim with strict `result.forecast` access (payload computed inside the typing block). Fixed `test_located_reply_builds_embed` so `_Cache.lookup` returns a `LookupResult`-shaped object exposing a `.forecast` attribute, and the patched `build_inbound_embed` asserts it received `result.forecast`. Production now keeps a strict cache contract.

### WR-06: split-path send is fragile

**Files modified:** `weatherbot/interactive/bot.py`
**Commit:** `77005a2`
**Applied fix:** Normalized the reply structure: the embed payload is now computed inside the `async with message.channel.typing():` block and a single `channel.send(embed=payload)` runs after it. The `UnknownLocationError` early-return send remains inside the typing block. All success sends now sit at one level; behavior is preserved.

### IN-01: `test_guard_webhook_author_fires_nothing` is a weak guard test

**Files modified:** `tests/test_bot.py`
**Commit:** `01e5a07`
**Applied fix:** Replaced the `bot.lookup_weather` spy (which the handler never calls) with a spying `_SpyCache` whose `.lookup` appends to a list, and asserted `cache.lookup` was never called. This strongly pins that the `author.bot` guard short-circuits BEFORE any cache access, mirroring `test_blocking_work_runs_off_loop`.

### IN-02: `lookup_weather` imported only as a "test spy seam" but spy tests don't use it

**Files modified:** `weatherbot/interactive/bot.py`
**Commit:** `77005a2`
**Applied fix:** Removed the dead `lookup_weather` import and its `# noqa: F401` from `bot.py`, plus the now-stale module comment explaining the seam. The cache owns the fetch; the bot guard tests use `raising=False` monkeypatch / a spying cache, so no test depends on the import. (`lookup_weather` remains re-exported from `weatherbot.interactive.__init__` for the CLI and cache.)

### IN-04: Deploy README does not mention the post-reload cache staleness behavior

**Files modified:** `deploy/README.md`
**Commit:** `8f5c012`
**Applied fix:** Added a "Reload behavior (inbound bot — known v1 limitations)" subsection documenting the two DEFERRED behaviors: `!weather` may return a forecast cached for up to the TTL after a reload, and a changed `[bot] operator_id` requires a process restart. Includes the `systemctl restart` remedy. A matching note was also added to `build_on_message`'s docstring in `bot.py` (committed under `77005a2`) since the prior docstring implied the bot tracked `holder.current()` for the operator guard.

## Skipped Issues

### CR-01: `ForecastCache.invalidate()` is never wired into the reload path

**File:** `weatherbot/interactive/cache.py:110-114`, `weatherbot/scheduler/daemon.py:549-679`
**Reason:** skipped — deferred/locked planning decision; operator opted out. The scheduler→cache invalidation seam is an INTENTIONAL deferral (decision Q2/D-12), confirmed by the plan-checker. `cache.invalidate()` was NOT wired into `_do_reload` and `_do_reload`'s signature was left unchanged. The limitation is instead DOCUMENTED via IN-04 (deploy README + bot.py docstring).
**Original issue:** After a config reload the bot serves stale forecasts for up to the full TTL because `invalidate()` has zero production callers.

### WR-01: Running bot does not pick up `operator_id` / `[bot]` changes on reload

**File:** `weatherbot/interactive/bot.py:88-109`, `weatherbot/scheduler/daemon.py:1179-1190`
**Reason:** skipped (code change) — deferred/locked planning decision; operator opted out. Reading `operator_id` live from `holder.current()` belongs to the same deferred "reload reaches the bot" scope and would change `build_on_message`'s signature; the operator-guard wiring was NOT modified. The deferral is DOCUMENTED (IN-04 deploy-README note + a `build_on_message` docstring note), which was the in-scope portion of this finding.
**Original issue:** `operator_id` is baked at `BotThread` construction, so a reload that changes `[bot] operator_id` is ignored until a process restart.

### WR-02: `DISCORD_BOT_TOKEN` is required even when the inbound bot is disabled

**File:** `weatherbot/config/settings.py:33`, `weatherbot/scheduler/daemon.py:1179`
**Reason:** skipped — deferred/locked planning decision; operator opted out. The required, fail-loud token is locked decision D-14/Q1, affirmed by the operator. `Settings.discord_bot_token` was NOT made optional and the daemon bot-start guard was left unchanged.
**Original issue:** `Settings.discord_bot_token: str` has no default, making it a hard-required secret for every deployment even when no `[bot]` is configured.

---

_Fixed: 2026-06-17T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
