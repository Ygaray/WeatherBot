---
phase: 11-discord-inbound-gateway-bot
reviewed: 2026-06-17T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - weatherbot/interactive/bot.py
  - weatherbot/interactive/cache.py
  - weatherbot/interactive/__init__.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/config/models.py
  - weatherbot/config/settings.py
  - weatherbot/config/__init__.py
  - tests/conftest.py
  - tests/test_bot.py
  - tests/test_cache.py
  - tests/test_reload.py
  - tests/test_config.py
  - deploy/README.md
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-06-17T00:00:00Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Phase 11 adds an inbound Discord gateway bot (`discord.py`) that coexists with the
sync APScheduler daemon. The thread/loop isolation contract is, on the whole, well
implemented: the bot runs on its own thread + event loop (`asyncio.run`, not
`Client.run`), all bot failures are caught inside `BotThread._run`, and the bot is
started STRICTLY AFTER `emit_online()` / `notifier.ready()` so a bot failure can
never gate the systemd READY signal. The guard ladder order (author.bot →
operator-id → prefix → parser) is correct, blocking work is dispatched off the loop
via `run_in_executor`, and the handler body is wrapped in a non-propagating
try/except. Secret handling is clean: the token lives only on `Settings`, never on
`config.toml`, and never reaches a log or user-facing message.

However, there is one BLOCKER: the entire `ForecastCache.invalidate()` mechanism —
the documented Pattern-4 reload hook whose stated purpose is "a stale forecast is
never served against a freshly reloaded config" — is **never called anywhere in the
daemon**. After a config reload the bot serves stale forecasts for up to the full
TTL. Several WARNING-level reload-consistency and robustness gaps compound this.

## Structural Findings (fallow)

No `<structural_findings>` block was provided with this review; this section is
intentionally empty. All findings below are narrative (direct-read) findings.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: `ForecastCache.invalidate()` is never wired into the reload path — stale forecasts served after reload

**File:** `weatherbot/interactive/cache.py:110-114`, `weatherbot/scheduler/daemon.py:549-679`
**Issue:**
`cache.py` documents `invalidate()` as the load-bearing Pattern-4 reload hook:

> "`invalidate` clears every entry under the lock — the hook a successful config
> reload calls (Pattern 4) so a stale forecast is never served against a freshly
> reloaded config."

But `invalidate()` has **zero callers in production code** (verified:
`grep -rn invalidate weatherbot/` returns only the definition and the cache
docstring; `_do_reload` in `daemon.py` never receives or touches the cache). The
cache is constructed in `run_daemon` (daemon.py:1042-1045) and passed only to the
`BotThread`; the reload engine (`_do_reload`) has no reference to it.

Concrete failure: an operator edits a location's coordinates / units / template
and reloads (SIGHUP, `weatherbot reload`, or file-watch). The schedule reconciles
correctly, but the bot's `ForecastCache` still holds the OLD `LookupResult` keyed
on the resolved `Location.id`. Because the key (`Location.id`) survives an
edit-in-place of lat/lon/units, the next `!weather <loc>` within the TTL (default
~10 min, D-12) replies with a forecast computed against the **pre-reload** config —
exactly the stale-read the cache docstring claims to prevent. The cache's only
public mutator beyond `lookup` is dead in production; the four `test_cache.py`
tests exercise `invalidate()` in isolation, masking the integration gap.

**Fix:** Thread the cache into the reload engine and invalidate it after a
successful swap. Minimal change in `run_daemon` / `_do_reload`:

```python
# run_daemon: pass the cache into the reload call (daemon.py ~1213)
_do_reload(
    config_path=config_path,
    holder=holder,
    scheduler=scheduler,
    db_path=db_path,
    settings=settings,
    client=client,
    channel=channel,
    stop_event=stop,
    watch_dirs_ref=watch_dirs_ref,
    cache=cache,            # NEW
)

# _do_reload: after the success log/post (daemon.py ~668), drop stale entries
def _do_reload(..., cache=None):
    ...
    # PHASE 2 success path, after holder.replace + reconcile committed:
    if cache is not None:
        cache.invalidate()   # Pattern 4: never serve a pre-reload forecast
```

Add a daemon-level integration test that reloads with a changed location and
asserts the next `cache.lookup` refetches (the existing `test_invalidate_clears_cache`
only proves the method works in isolation, not that reload calls it).

## Warnings

### WR-01: Running bot does not pick up `operator_id` / `[bot]` changes on reload

**File:** `weatherbot/interactive/bot.py:88-109`, `weatherbot/scheduler/daemon.py:1179-1190`
**Issue:** `operator_id` is captured as a plain `int` at `BotThread` construction
(daemon.py:1186, `operator_id=config.bot.operator_id`) and closed over in
`build_on_message` (bot.py:108, `if message.author.id != operator_id`). The handler
reads live config via `holder.current()` for the location lookup, but the operator
guard uses the **baked** value. A reload that changes `[bot] operator_id` (or adds
/ removes the `[bot]` section) is silently ignored by the already-running bot: the
old operator keeps command access and the new one is locked out until a full process
restart. Given the cache-invalidate gap (CR-01) this is part of a broader
"reload does not fully reach the bot" pattern. This is an authorization-relevant
staleness (who may command the bot), so it is a strong WARNING bordering on BLOCKER
for a security-sensitive guard.
**Fix:** Read the operator id from the live snapshot inside the guard instead of
baking it:

```python
def build_on_message(*, holder, cache):  # drop operator_id param
    async def on_message(message):
        if message.author.bot:
            return
        config = holder.current()
        bot_cfg = config.bot
        if bot_cfg is None or message.author.id != bot_cfg.operator_id:
            return
        ...
```

If live re-read is intentionally out of scope for v1, document it explicitly in
bot.py and the deploy README ("changing operator_id requires a restart"), since the
current docstring implies the bot tracks `holder.current()`.

### WR-02: `DISCORD_BOT_TOKEN` is required even when the inbound bot is disabled

**File:** `weatherbot/config/settings.py:33`, `weatherbot/scheduler/daemon.py:1179`
**Issue:** `Settings.discord_bot_token: str` has no default, so it is a hard-required
secret at process startup for EVERY deployment — including one that never configures
`[bot]` (the daemon guards the bot start on `config.bot is not None`, daemon.py:1179,
so the token is only ever *used* when a bot is configured). A user who wants only
scheduled briefings and no inbound bot is now forced to invent / paste a bot token
into `.env` or the daemon dies at load with a `ValidationError`. The deploy README
(line 60-65) frames this as intended fail-loud behavior, but it couples a feature
that is optional in `config.toml` (`bot: BotConfig | None = None`) to a mandatory
secret — an inconsistent contract.
**Fix:** Make the token optional and validate its presence only when a bot is
configured:

```python
# settings.py
discord_bot_token: str | None = None
```

```python
# daemon.py, in the bot-start guard
if config.bot is not None and settings is not None:
    if not settings.discord_bot_token:
        _log.critical("[bot] configured but DISCORD_BOT_TOKEN is unset; bot disabled")
    else:
        bot = BotThread(settings.discord_bot_token, ...)
```

If "all three secrets always required" is a deliberate operational decision, keep it
but note that it contradicts the optional `[bot]` model and document the rationale in
settings.py.

### WR-03: `BotThread.start()` reports ready before the gateway login result is known

**File:** `weatherbot/interactive/bot.py:218-253`
**Issue:** `_amain` sets `self._ready` (line 251) BEFORE `client.start(token)` runs
(line 253). `start()` (line 218-222) waits on `_ready` for up to 5s and then logs
nothing on success — but `_ready` only proves the loop thread reached `_amain`, NOT
that the gateway authenticated. An invalid token raises `LoginFailure` *after*
`_ready.set()`, so `start()` returns as if the bot came up; the failure surfaces
only later as a CRITICAL log inside `_run`. This is acceptable for the
failure-isolation contract (a dead bot must not block the daemon), but the `_ready`
event is misleadingly named/used: it signals "loop is up", not "bot is ready",
while the docstring says start "wait[s] ... for its loop to come up" (accurate) yet
callers may reasonably read a returned `start()` as "bot connected". No caller
currently depends on connection state, so impact is low today.
**Fix:** Either rename `_ready` to `_loop_started` and tighten the docstring, or
move `_ready.set()` into an `on_ready` event so it reflects an actual gateway
connection (with the 5s timeout warning then being a true "did not connect"
diagnostic). At minimum, document that a returned `start()` does not imply a
successful login.

### WR-04: `stop()` swallows `KeyboardInterrupt`/`SystemExit` via bare `Exception` is fine, but a never-running loop is silently un-joined-fast

**File:** `weatherbot/interactive/bot.py:224-235`
**Issue:** `stop()` guards the cross-thread close on `loop is not None and
loop.is_running()`. If the bot thread died early (invalid token → `LoginFailure`
caught in `_run`), `self._loop` may be set but `loop.is_running()` is False, so the
close is skipped and the code falls through to `self._thread.join(timeout)`. That is
correct. However, if `_amain` never ran far enough to set `self._loop` (thread
crashed before line 250), `loop is None` and again the join runs — also fine. The
real gap: there is no path that detects an invalid-token bot during `start()` and
clears `bot` so the daemon `finally` skips `stop()`. The `finally` block
(daemon.py:1261-1265) calls `bot.stop()` on a `BotThread` whose thread already
exited; `run_coroutine_threadsafe` is skipped (loop not running) and `join` returns
immediately — harmless, but `bot` is left non-None after a known-dead start. Minor
robustness/clarity issue.
**Fix:** Have `BotThread` expose an `is_alive()` / `failed` flag (set in the `_run`
except handlers) so the daemon can log and null out `bot` on a confirmed dead start,
making the teardown intent explicit rather than relying on `loop.is_running()` being
False.

### WR-05: `getattr(result, "forecast", result)` masks a real type error in production

**File:** `weatherbot/interactive/bot.py:135-138`
**Issue:** `forecast = getattr(result, "forecast", result)` is documented as a
test-tolerance shim ("tolerate a bare result in tests that patch
build_inbound_embed"). In production `cache.lookup` ALWAYS returns a `LookupResult`
with a `.forecast` attribute, so the fallback branch can only fire if the cache
contract is violated — in which case the code would silently pass the WRONG object
(`result` itself) to `build_inbound_embed`, producing a confusing
`AttributeError` deep inside embed construction rather than a clear contract error.
Production code should not bend its types to accommodate a mock; the test should
return a properly shaped fake.
**Fix:** Use a direct attribute access in production and fix the test fakes to
return a `LookupResult`-shaped object:

```python
await message.channel.send(embed=build_inbound_embed(result.forecast))
```

In `test_located_reply_builds_embed` (test_bot.py:115-119) make `_Cache.lookup`
return an object with a `.forecast` attribute (or patch `build_inbound_embed` to
accept the result as-is) so production code keeps a strict contract.

### WR-06: Empty error reply on `UnknownLocationError` shares the typing block but the embed reply does not — split-path send is fragile

**File:** `weatherbot/interactive/bot.py:125-138`
**Issue:** The `UnknownLocationError` reply (`message.channel.send(str(exc))`,
line 133) executes INSIDE the `async with message.channel.typing():` block, while
the success embed reply (line 138) executes OUTSIDE it. Both are correct today, but
the asymmetry is a latent bug magnet: any future edit that moves the success reply
back inside the typing context, or adds an early branch, can easily desync which
sends are wrapped. More importantly, `str(exc)` for `UnknownLocationError` embeds
the full configured-location list into a user-facing message — confirm that is
intended exposure for a single-operator bot (it is acceptable here since only the
operator passes the guard, but the pattern would leak location names if the operator
guard were ever loosened).
**Fix:** Normalize the structure so all reply sends sit at the same level, e.g.
compute the reply payload inside the typing block and perform the single
`channel.send` after it:

```python
async with message.channel.typing():
    try:
        result = await loop.run_in_executor(None, cache.lookup, name, config)
    except UnknownLocationError as exc:
        await message.channel.send(str(exc))
        return
    payload = build_inbound_embed(result.forecast)
await message.channel.send(embed=payload)
```

## Info

### IN-01: `test_guard_webhook_author_fires_nothing` is a weak guard test

**File:** `tests/test_bot.py:59-76`
**Issue:** The test spies `bot.lookup_weather`, but the handler never calls
`bot.lookup_weather` directly (it calls `cache.lookup`, and `lookup_weather` is only
imported as a re-export seam). With `author.bot=True` the guard returns at bot.py:106
before any cache access, so the test passes — but it would ALSO pass if the
author.bot guard were removed entirely and only the operator/cache path were broken,
because `cache=None` would raise inside the swallowing try/except and still never
touch `bot.lookup_weather`. The assertion does not strongly pin "the first guard
short-circuits".
**Fix:** Pass a spying cache (`cache` whose `.lookup` appends to a list) and assert
`cache.lookup` was never called, mirroring the stronger style of
`test_blocking_work_runs_off_loop`.

### IN-02: `lookup_weather` imported only as a "test spy seam" but spy tests don't use it

**File:** `weatherbot/interactive/bot.py:46-49`
**Issue:** `lookup_weather` is imported with `# noqa: F401 — re-exported as a test
spy seam (CMD-07)`, but the bot tests (test_bot.py) monkeypatch
`bot.build_inbound_embed` and inject a fake `cache`, never `bot.lookup_weather`. The
import is effectively dead — it exists only so a test *could* patch it, but no test
does. Carrying an unused import with a justifying comment that the tests do not honor
is misleading.
**Fix:** Remove the import (and the `noqa`) if no test actually patches
`bot.lookup_weather`; the cache already owns the fetch. If the seam is intended for a
future test, add the test now or drop the import until it is needed.

### IN-03: `_ERROR_REPLY` / embed color are magic literals without shared constants

**File:** `weatherbot/interactive/bot.py:63,75,83`
**Issue:** The embed color `0x03B2F8` is duplicated conceptually with the webhook
briefing's `"03b2f8"` string (per the docstring) but the two are independent magic
literals in separate modules — a future brand-color change must be made in two
places and kept in sync by hand. Minor maintainability nit.
**Fix:** Define the color once (e.g. `BRIEFING_COLOR_HEX = "03b2f8"`) in a shared
location and derive both the int (`int(BRIEFING_COLOR_HEX, 16)`) and the string from
it.

### IN-04: Deploy README does not mention the post-reload cache staleness behavior

**File:** `deploy/README.md`
**Issue:** Given CR-01 (and WR-01), the operator-facing deploy doc should state how
config changes interact with the bot's cache and operator guard. Currently it only
covers the token and intent setup. Once CR-01/WR-01 are fixed this becomes a
one-line note; if they are deferred, the doc must warn that `!weather` may return a
stale forecast / honor the old operator_id for up to the TTL after a reload.
**Fix:** Add a short "Reload behavior" subsection once CR-01/WR-01 are resolved (or
documenting the limitation if deferred).

---

_Reviewed: 2026-06-17T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
