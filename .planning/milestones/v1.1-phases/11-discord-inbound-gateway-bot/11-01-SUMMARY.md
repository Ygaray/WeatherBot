---
phase: 11-discord-inbound-gateway-bot
plan: 01
subsystem: testing
tags: [pytest, discord, asyncio, ttl-cache, red-scaffold, nyquist, asyncmock]

# Dependency graph
requires:
  - phase: 06-shared-lookup-core
    provides: "lookup_weather read-only core + UnknownLocationError(.requested/.valid_names) + parse_weather_command"
  - phase: 09-reload-engine
    provides: "_do_reload two-phase build-then-commit engine (already takes channel=) + +a -r ~c =u diff summary"
provides:
  - "RED contract for weatherbot.interactive.bot (on_message guard ladder, build_inbound_embed, run_in_executor dispatch)"
  - "RED contract for weatherbot.interactive.cache.ForecastCache (TTL hit/miss/expiry/invalidate)"
  - "fake_discord_message gateway-free message factory (AsyncMock channel.send, async-cm typing) in conftest"
  - "CFG-07 reload-outcome posting contract (success summary post, rejection reason post, send-failure isolation)"
affects: [11-02-deps-gate, 11-03-bot-cache-impl, 11-04-reload-post-impl]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred per-test import idiom (node IDs COLLECT while failing RED on the unbuilt module)"
    - "Gateway-free discord.py handler testing via MagicMock + AsyncMock channel.send + async-cm typing"
    - "run_in_executor dispatch assertion (spy the bound loop method to prove blocking work runs off-loop)"

key-files:
  created:
    - tests/test_bot.py
    - tests/test_cache.py
  modified:
    - tests/conftest.py
    - tests/test_reload.py

key-decisions:
  - "fake_discord_message is a pure MagicMock stand-in (no discord import) so it stays collectable before discord.py is installed"
  - "build_on_message(holder, operator_id, cache) is the handler-factory seam the bot tests pin (handler built per-call, driven directly)"
  - "CFG-07 posts go through the agnostic channel.send seam (plain text, distinct from the briefing embed, D-13)"
  - "cache.lookup keys on resolve_location(config, name).id so home/Home/bare-default collapse to one TTL entry"

patterns-established:
  - "Wave-0 RED scaffold: deferred import + counting spies on lookup_weather (real key path, never a green-but-hollow mock)"
  - "TTL expiry tested via injected timer= seam (controllable clock, no wall-clock sleep)"

requirements-completed: [CMD-02, CMD-06, CMD-07, CMD-08, CFG-07]

# Metrics
duration: 8min
completed: 2026-06-16
---

# Phase 11 Plan 01: Inbound Bot RED Scaffold Summary

**Wave-0 Nyquist RED scaffold pinning all CMD-02/06/07/08 + CFG-07 behavior node IDs (10 bot/cache + 3 cfg07) that COLLECT under pytest while failing RED on the not-yet-built weatherbot.interactive.bot/.cache symbols, plus a gateway-free fake_discord_message factory.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-16T20:40:00Z
- **Completed:** 2026-06-16T20:48:00Z
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `fake_discord_message` factory in conftest: a pure MagicMock-shaped discord.py Message with an `AsyncMock` `channel.send` and an async-context-manager `channel.typing()` — no discord import, no network, no live gateway.
- `tests/test_bot.py`: 6 RED node IDs covering the guard ladder (webhook-author CMD-07, non-operator CMD-07), located embed reply (CMD-02), unknown-location valid-names reply (CMD-02 error path), off-loop dispatch (Pitfall 1), and non-propagating handler (CMD-08) — all via the deferred-import idiom.
- `tests/test_cache.py`: 4 RED node IDs for `ForecastCache` TTL hit, post-TTL refetch (controllable timer), distinct-location entries, and invalidate-clears (CMD-06).
- `tests/test_reload.py`: 3 `cfg07` RED node IDs for success-posts-summary, rejection-posts-reason (still raises, keep-old), and channel-send-failure-does-not-abort-reload (best-effort isolation).

## Task Commits

Each task was committed atomically:

1. **Task 1: fake_discord_message factory + RED test_bot.py / test_cache.py** - `2c71421` (test)
2. **Task 2: CFG-07 reload-outcome posting tests in test_reload.py** - `f56eba5` (test)

**Plan metadata:** (final docs commit — this SUMMARY + STATE + ROADMAP)

## Files Created/Modified
- `tests/test_bot.py` - 6 RED bot-handler node IDs (deferred `weatherbot.interactive.bot` import)
- `tests/test_cache.py` - 4 RED `ForecastCache` TTL node IDs (deferred `.cache` import)
- `tests/conftest.py` - `fake_discord_message` gateway-free message factory fixture
- `tests/test_reload.py` - 3 `cfg07` reload-outcome posting tests appended (reuses `holder_scheduler`)

## Decisions Made
- `build_on_message(holder, operator_id, cache)` chosen as the handler-factory seam the tests drive directly (handler is a coroutine; tests call it on a fresh `asyncio.run` loop with the fake message).
- The off-loop assertion spies the **bound** `loop.run_in_executor` for the duration of the call and asserts the blocking `cache.lookup` was dispatched through it — proving Pitfall-1 compliance without a real thread pool race.
- The CFG-07 send-failure test pins BOTH branches: a raising post on success must not block the swap, and a raising post on rejection must surface the ORIGINAL validation error (not the send `RuntimeError`).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. All 10 bot/cache node IDs and 3 cfg07 node IDs collect cleanly; the full project suite collects 276 tests with zero collection errors.

## User Setup Required
None - no external service configuration required (the package-legitimacy gate for discord.py/cachetools is Plan 11-02; this plan installs nothing).

## Next Phase Readiness
- The RED contract is fixed and visible: Plan 11-02 gates the `discord.py>=2.7.1,<3` + `cachetools>=6,<8` installs; Plan 11-03 turns the 10 bot/cache node IDs GREEN; Plan 11-04 adds the two `_do_reload` `channel.send` post sites to turn the 3 cfg07 node IDs GREEN.
- No blockers. Pre-existing reload suite unaffected at collection (20 → 23 in test_reload.py).

## Self-Check: PASSED

- FOUND: tests/test_bot.py, tests/test_cache.py, 11-01-SUMMARY.md
- FOUND: commits 2c71421 (Task 1), f56eba5 (Task 2)
- FOUND: fake_discord_message fixture in conftest.py

---
*Phase: 11-discord-inbound-gateway-bot*
*Completed: 2026-06-16*
