---
phase: 11-discord-inbound-gateway-bot
plan: 04
subsystem: infra
tags: [discord, daemon, apscheduler, threading, reload, lifecycle]

# Dependency graph
requires:
  - phase: 11-discord-inbound-gateway-bot
    provides: "BotThread + ForecastCache (11-03); _do_reload two-phase reload engine + emit_online best-effort post idiom (Phase 9/10); cfg07 RED tests + _SpyChannel/_RaisingChannel (11-01)"
provides:
  - "Inbound BotThread is a managed child of run_daemon: started after READY, torn down in the finally"
  - "Bot startup/runtime failure is fully isolated — never delays/gates the systemd READY signal, never stops the scheduler (CMD-08)"
  - "Both reload outcomes post to Discord: success diff summary + rejection reason, best-effort (CFG-07)"
affects: [discord-inbound-gateway-bot, v1.1-interactive-live-config, future-channels]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bot thread started strictly AFTER emit_online so bot health never gates READY (Pitfall 4)"
    - "CFG-07 reload-outcome posts reuse the emit_online best-effort try/except idiom (send failure logged, never propagated)"
    - "Lazy in-function interactive import keeps discord.py off the daemon module import-time graph"

key-files:
  created: []
  modified:
    - "weatherbot/scheduler/daemon.py"
    - "tests/test_reload.py"

key-decisions:
  - "CFG-07 posts capture the summary tuple directly (D-13), never scrape the log line"
  - "ForecastCache constructed only when settings is present; scheduler-read seam left UNWIRED (Q2/D-12) — cache is bot-only for now"
  - "Bot start/stop guarded on config.bot AND settings; bot=None init keeps the finally teardown unconditional"
  - "Used the actual run_daemon coverage in test_scheduler.py for verification (plan's tests/test_daemon.py + -k 'isolation or lifecycle' selector reference tests that do not exist in this repo)"

patterns-established:
  - "Daemon child threads (file-watch observer, inbound bot) are constructed up front as None, started after the gate, and joined in one shared finally"
  - "Best-effort outbound channel.send (online ping, CFG-07 posts) is always wrapped in its own try/except that logs and swallows"

requirements-completed: [CMD-08, CFG-07]

# Metrics
duration: 3min
completed: 2026-06-17
---

# Phase 11 Plan 04: Daemon Bot Lifecycle + Reload-Outcome Posts Summary

**The inbound Discord BotThread is now a managed child of `run_daemon` — started after the systemd READY signal and torn down in the finally, fully isolated so bot failure never stops a briefing or flips READY (CMD-08); both reload outcomes (success diff summary, rejection reason) post to Discord best-effort without ever aborting the reload (CFG-07).**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-06-17T06:20:07Z
- **Completed:** 2026-06-17T06:22:46Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- CFG-07: `_do_reload` posts `✅ config reloaded: {summary}` on a successful swap and `⛔ config reload rejected: {exc}` in the PHASE-1 reject branch — both best-effort, neither aborts the reload or masks the validation error. The three `cfg07` RED tests are now GREEN.
- CMD-08: `run_daemon` constructs a `ForecastCache` and starts a `BotThread` strictly AFTER `scheduler.start()` + `emit_online()`, guarded on `config.bot`/`settings`, wrapped so a startup failure logs and proceeds. The bot is stopped/joined in the same finally that joins the file-watch observer.
- Full suite green: 283 passed. A settings-less / `[bot]`-less config starts no bot thread (the existing `run_daemon` tests confirm).

## Task Commits

Each task was committed atomically:

1. **Task 1: CFG-07 reload-outcome posts (both branches)** - `602b9e8` (feat)
2. **Task 2: BotThread lifecycle in run_daemon** - `24f21a6` (feat)

_Task 1 was a TDD task whose RED tests already shipped in 11-01; this plan implemented the GREEN edit in a single feat commit._

## Files Created/Modified
- `weatherbot/scheduler/daemon.py` - CFG-07 best-effort `channel.send` posts in both `_do_reload` branches; `ForecastCache` construction + guarded `BotThread` start (after `emit_online`) + finally teardown in `run_daemon`
- `tests/test_reload.py` - Relaxed one stale assertion (see Deviations)

## Decisions Made
- Captured the `summary` tuple directly for the CFG-07 success post (D-13) rather than scraping `_stdlog.info("reload applied %s", summary)`.
- `ForecastCache(settings=settings)` is built only when `settings is not None`; the scheduler-read seam stays UNWIRED per Q2/D-12 (the cache serves the bot only for now).
- Verified Task 2 against the real `run_daemon` coverage in `tests/test_scheduler.py` plus the full suite, because the plan's verify command (`tests/test_daemon.py -k "isolation or lifecycle"`) references a test file and selector that do not exist in this repo. The CMD-08 isolation guarantees are enforced structurally (bot wrapped in try/except, started after `emit_online`, BotThread's own `_run` swallows `LoginFailure`/`Exception`) and acceptance-grep-asserted.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Relaxed a stale `sent_text == []` assertion that contradicted the test-pinned CFG-07 post**
- **Found during:** Task 1 (CFG-07 success post)
- **Issue:** `tests/test_reload.py::test_already_sent_slot_not_refired_after_tz_name_change` asserted `channel.sent_text == []` ("the reload itself delivered nothing"). That assertion predates CFG-07 and is mutually exclusive with `test_cfg07_success_posts_summary`, which requires a post on a successful reload. The original intent was "no weather BRIEFING re-fired on a same-day already-sent slot," not "the channel is wholly silent."
- **Fix:** Changed the assertion to filter out the CFG-07 confirmation post (`✅ config reloaded …`) and assert no *briefing* was sent — preserving the test's true intent (no duplicate same-day delivery).
- **Files modified:** `tests/test_reload.py`
- **Verification:** `uv run pytest tests/test_reload.py` → 23 passed; full suite 283 passed.
- **Committed in:** `602b9e8` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The one fix resolved a genuine conflict between a stale pre-CFG-07 assertion and the test-pinned CFG-07 behavior; no scope creep. The verify-command discrepancy (nonexistent `tests/test_daemon.py`) was handled by verifying against the real `run_daemon` suite and acceptance greps.

## Issues Encountered
- The plan's Task 2 verify command pointed at `tests/test_daemon.py` and a `-k "isolation or lifecycle"` selector; neither exists in this repo. Resolved by running the actual `run_daemon` tests in `tests/test_scheduler.py` and the full suite, plus all acceptance greps (BotThread after emit_online, guard present, teardown present, `signal.signal` count unchanged at 2, `add_signal_handler` count 0).

## Threat Model Outcomes
- **T-11-11 (DoS of core value):** mitigated — bot started after `emit_online`, start wrapped in try/except that proceeds; bot lives on its own daemon thread; scheduler/briefing path untouched.
- **T-11-12 (READY-gate tampering):** mitigated — `emit_online`/`notifier.ready()` fires once before the bot starts and is never called from the bot path (source review).
- **T-11-13 (reload-post DoS):** mitigated — both CFG-07 posts wrapped best-effort; a `channel.send` raise is logged, never propagated (`test_cfg07_channel_send_failure_does_not_abort_reload` GREEN).
- **T-11-14 (off-main-thread signal handler):** mitigated — daemon keeps its main-thread `signal.signal` handlers (count 2, unchanged); `add_signal_handler` count is 0; BotThread uses `asyncio.run(client.start())`.

## User Setup Required
None - no external service configuration added by this plan. (The `[bot]` section + `DISCORD_BOT_TOKEN` are required at runtime to actually start the inbound bot, established in earlier Phase 11 plans.)

## Next Phase Readiness
- Phase 11 (discord-inbound-gateway-bot) implementation is complete: the inbound bot is wired into the daemon lifecycle and both reload outcomes post to Discord. CMD-08 and CFG-07 are closed.
- The scheduler-read seam for the shared `ForecastCache` remains intentionally unwired (Q2/D-12) — a future enhancement, not a blocker.

## Self-Check: PASSED
- FOUND: weatherbot/scheduler/daemon.py
- FOUND: tests/test_reload.py
- FOUND commit: 602b9e8 (Task 1, CFG-07)
- FOUND commit: 24f21a6 (Task 2, BotThread lifecycle)

---
*Phase: 11-discord-inbound-gateway-bot*
*Completed: 2026-06-17*
