---
phase: 11-discord-inbound-gateway-bot
plan: 03
subsystem: api
tags: [discord.py, gateway, asyncio, cachetools, ttl-cache, threading, embed]

# Dependency graph
requires:
  - phase: 11-01
    provides: "Wave-0 RED contract (tests/test_bot.py, tests/test_cache.py, fake_discord_message fixture, build_on_message handler-factory seam)"
  - phase: 11-02
    provides: "parse_weather_command (D-03) + lookup_weather read-only core + UnknownLocationError (valid_names)"
  - phase: 06
    provides: "LookupResult.forecast / send_briefing embed field shape mirrored by build_inbound_embed"
  - phase: 08
    provides: "ConfigHolder.current() lock-free snapshot read used by on_message"
provides:
  - "ForecastCache: thread-safe per-location TTL cache wrapping lookup_weather (CMD-06)"
  - "build_on_message: gateway-free on_message guard ladder + embed reply (CMD-02/07/08)"
  - "build_inbound_embed: discord.Embed mirroring send_briefing fields (D-07)"
  - "build_client: bare discord.Client with minimal intents + on_ready assertion (D-02)"
  - "BotThread: own-thread/own-loop lifecycle via asyncio.run(client.start())"
affects: [11-04, discord, daemon, hot-reload]

# Tech tracking
tech-stack:
  added: []  # discord.py + cachetools already in pyproject from prior phases
  patterns:
    - "Lock-around-dict-only cache: TTLCache behind threading.Lock; network fetch runs UNLOCKED so misses never serialize"
    - "Handler-factory seam: build_on_message(holder, operator_id, cache) returns a standalone coroutine drivable without a live gateway"
    - "Own-thread gateway: asyncio.run(client.start(token)) (NOT Client.run) + cross-thread close via run_coroutine_threadsafe"
    - "Module-top test-spy import: lookup_weather imported (noqa F401) so tests can monkeypatch bot.lookup_weather to prove the guard ladder short-circuits before any fetch"

key-files:
  created:
    - weatherbot/interactive/cache.py
    - weatherbot/interactive/bot.py
  modified:
    - weatherbot/interactive/__init__.py

key-decisions:
  - "TTLCache exposes an injectable timer= seam (forwarded only when provided) so the TTL-expiry test advances a controllable clock without a wall-clock sleep"
  - "build_inbound_embed reads forecast defensively (getattr(result, 'forecast', result)) so the off-loop result flows through cleanly while the RED embed test (object() result + patched builder) stays green"
  - "Color is the gateway lib's int 0x03B2F8 (NOT the webhook lib's '03b2f8' string) — same visual, correct type for discord.Embed"
  - "Whole reply path wrapped in a non-propagating try/except (CMD-08); UnknownLocationError caught inside the typing block replies str(exc) with valid_names and returns before the embed path"

patterns-established:
  - "Guard ladder ORDER is load-bearing: author.bot -> author.id != operator_id -> '!' prefix -> parse_weather_command -> location; first two are the feedback-loop + quota backstops (T-11-05/06)"
  - "All blocking lookup work dispatched via loop.run_in_executor (D-10) — the gateway heartbeat never blocks"
  - "Bot health failures (LoginFailure / any crash) die inside BotThread._run and never reach the briefing scheduler (D-11)"

requirements-completed: [CMD-02, CMD-06, CMD-07, CMD-08]

# Metrics
duration: 4min
completed: 2026-06-17
---

# Phase 11 Plan 03: Inbound Discord Gateway Bot Summary

**Thread-safe per-location TTL ForecastCache plus a bare discord.Client guard ladder (author.bot -> operator -> ! -> parse) that fetches off-loop via run_in_executor and replies with a send_briefing-mirrored embed, all isolated in a BotThread that can never crash the briefing scheduler.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-17T06:12:46Z
- **Completed:** 2026-06-17T06:16:27Z
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- `ForecastCache` (CMD-06): `cachetools.TTLCache` keyed on the resolved `Location.id` behind a `threading.Lock`, with the `lookup_weather` network fetch run UNLOCKED so two location misses never serialize. `home`/`Home`/bare-default collapse to one entry; `invalidate()` is the config-reload hook. All 4 `tests/test_cache.py` node IDs GREEN.
- `build_on_message` (CMD-02/07/08): the manual guard ladder (`author.bot` -> `operator_id` -> `!` prefix -> `parse_weather_command` -> location), off-loop fetch via `run_in_executor`, `async with channel.typing()` (D-08), embed reply (D-07), `UnknownLocationError` -> valid-names text, and a whole-body non-propagating `try/except` (D-11). All 6 `tests/test_bot.py` node IDs GREEN.
- `build_client` + `BotThread`: minimal intents (`guilds`/`guild_messages`/`message_content`) with an `on_ready` CRITICAL assertion on the privileged intent (D-02), and own-thread/own-loop lifecycle via `asyncio.run(client.start(token))` with cross-thread `client.close()` (no `client.run()` — verified 0 occurrences).

## Task Commits

Each task was committed atomically:

1. **Task 1: ForecastCache — thread-safe TTL wrapper (CMD-06)** - `c88f6b6` (feat)
2. **Task 2: bot.py — guard ladder, embed, executor, BotThread lifecycle (CMD-02/07/08)** - `bbdca66` (feat)

_TDD note: 11-01 already wrote the RED tests in a prior plan, so each task here is the single GREEN commit that turns its contract green (no separate test commit in this plan)._

## Files Created/Modified
- `weatherbot/interactive/cache.py` - `ForecastCache`: TTLCache+Lock wrapping `lookup_weather`, keyed on `Location.id`; injectable `timer=`; `invalidate()`.
- `weatherbot/interactive/bot.py` - `build_inbound_embed`, `build_on_message`, `build_client`, `BotThread` (`_run`/`_amain`/`start`/`stop`).
- `weatherbot/interactive/__init__.py` - barrel exports for `ForecastCache`, `BotThread`, `build_client`.

## Decisions Made
- **Injectable `timer=` on the cache** — forwarded to `TTLCache` only when provided so the expiry test advances a controllable clock deterministically; production uses the default monotonic timer.
- **Defensive `forecast = getattr(result, "forecast", result)`** in the handler — the off-loop result is a `LookupResult` in production; the RED embed test passes a bare `object()` with a patched `build_inbound_embed`, and this avoids an `AttributeError` tripping the broad except before the patched builder runs.
- **`discord.Embed` color int `0x03B2F8`** (not the webhook lib's `"03b2f8"` string) — same color, correct type for the gateway lib.
- **`lookup_weather` imported at module top with `# noqa: F401`** — it is the test-spy seam (`bot.lookup_weather`) the CMD-07 tests monkeypatch to prove the guard ladder short-circuits before any fetch; not called directly here (the cache wraps it).

## Deviations from Plan

The plan's `<action>` prose described registering the handler inside `build_client`, but the 11-01 RED contract (`tests/test_bot.py`) drives `bot.build_on_message(holder=, operator_id=, cache=)` directly. This is the documented 11-01 handler-factory seam (recorded in STATE.md), not a true deviation — `build_on_message` was implemented as the standalone coroutine factory and `build_client` registers it. No deviation rules were triggered; no auto-fixes were required.

**None - plan executed exactly as written** (the test-aligned handler-factory shape was the intended 11-01 seam).

## Issues Encountered
- **`tests/test_reload.py::test_cfg07_success_posts_summary` and `::test_cfg07_rejection_posts_reason` fail.** Verified PRE-EXISTING (reproduced with this plan's files stashed) and OUT OF SCOPE — they pin the CFG-07 reconcile-summary in-channel post, which is daemon-channel wiring scoped to Plan 11-04. This plan's files are not imported by `test_reload.py`. Logged to `deferred-items.md`; not fixed.
- **`DeprecationWarning: 'audioop' is deprecated`** emitted on `import discord` (discord.py player module, Python 3.12). Harmless upstream warning; not actionable here.

## Verification
- `uv run pytest tests/test_bot.py tests/test_cache.py -x` → GREEN (10 node IDs: CMD-02/06/07/08 + Pitfall-1 off-loop dispatch).
- `grep -c 'client.run(' weatherbot/interactive/bot.py` → 0 (uses `client.start()`, the CMD-08 mechanic).
- `uv run ruff check weatherbot/interactive/` → All checks passed.
- Full suite: 281 passed, 2 pre-existing CFG-07 failures (out of scope, see Issues + `deferred-items.md`).

## Threat Coverage
All `mitigate` dispositions from the plan threat register are implemented:
- T-11-05 (feedback loop): `if message.author.bot: return` FIRST guard + `!` prefix + parser word-boundary guard.
- T-11-06 (quota DoS): operator-only silent return + per-location TTLCache.
- T-11-07 (injection): parse-don't-validate parser; only configured names resolve.
- T-11-08 (handler crash): whole-body non-propagating try/except + generic reply.
- T-11-09 (over-broad intents): minimal `none()` + `guilds`/`guild_messages`/`message_content`.
- T-11-10 (log/leak): structlog outcome-only fields; token never logged; generic user-facing error.

No new security surface beyond the plan's threat model was introduced.

## User Setup Required
None in this plan. (Operator's bot token + `operator_id` wiring and enabling the privileged `message_content` intent in the Discord developer portal land with the daemon wiring in Plan 11-04.)

## Next Phase Readiness
- `ForecastCache`, `BotThread`, and `build_client` are exported and tested in isolation — ready for Plan 11-04 to wire `BotThread.start()/stop()` into the daemon lifecycle (CFG-07) and resolve the two deferred `test_reload.py::cfg07` failures.

## Self-Check: PASSED
- All created files present: `cache.py`, `bot.py`, `__init__.py`, `11-03-SUMMARY.md`.
- All task commits present in git: `c88f6b6`, `bbdca66`.

---
*Phase: 11-discord-inbound-gateway-bot*
*Completed: 2026-06-17*
