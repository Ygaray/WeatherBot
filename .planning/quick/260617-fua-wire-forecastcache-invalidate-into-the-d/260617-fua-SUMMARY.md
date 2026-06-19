---
phase: quick-260617-fua
plan: 01
status: complete
subsystem: scheduler/reload + interactive/cache
tags: [reload, cache, discord-bot, CR-01]
requires:
  - weatherbot/scheduler/daemon.py::_do_reload
  - weatherbot/interactive/cache.py::ForecastCache.invalidate
provides:
  - "ForecastCache.invalidate() wired into the daemon reload success path (CR-01 closed)"
affects:
  - weatherbot/scheduler/daemon.py
  - tests/test_reload.py
  - deploy/README.md
  - .planning/phases/11-discord-inbound-gateway-bot/11-CONTEXT.md
tech-stack:
  added: []
  patterns: ["best-effort post-commit hook (mirrors emit_online / CFG-07 idiom)"]
key-files:
  created: []
  modified:
    - weatherbot/scheduler/daemon.py
    - tests/test_reload.py
    - deploy/README.md
    - .planning/phases/11-discord-inbound-gateway-bot/11-CONTEXT.md
decisions:
  - "Invalidate cache ONLY in the committed-success branch of _do_reload (after holder.replace + _reconcile_jobs), never on reject/rollback paths."
  - "Best-effort: a cache.invalidate() error is logged and swallowed; it never aborts an already-committed reload."
  - "cache=None keyword-only param keeps every existing _do_reload caller/test valid (additive)."
metrics:
  duration: ~6 min
  completed: 2026-06-17
requirements: [CR-01]
---

# Quick Task 260617-fua: Wire ForecastCache.invalidate into the daemon reload path Summary

Wired `ForecastCache.invalidate()` into `_do_reload`'s committed-success branch and threaded
`cache=cache` from `run_daemon`'s poll loop, closing code-review finding CR-01 (stale forecast
served for up to the TTL after a config reload) and reversing the Phase 11 Q2/D-12 deferral.

## What was done

- **Task 1 (feat, c6064e4):** Added a `cache=None` keyword-only parameter to `_do_reload`. In the
  committed-success branch only (after `holder.replace` + `_reconcile_jobs`, after the CFG-07 post,
  before the watch-dir re-derive) added a best-effort `if cache is not None: try: cache.invalidate()
  except Exception: _log.warning(...)`. Threaded `cache=cache` into `run_daemon`'s poll-loop
  `_do_reload(...)` call. Cache construction, BotThread wiring, and all reload semantics untouched.
- **Task 2 (test, 80ee140):** Added `test_reload_invalidates_forecast_cache_so_next_lookup_refetches`
  to `tests/test_reload.py` — a daemon-level integration test that primes a real
  `ForecastCache(settings=None)` (spy count 1), drives the real `_do_reload(..., cache=cache)` with a
  changed lat/lon on the SAME stable id (cache key survives the edit — the exact CR-01 stale-key
  scenario), then asserts the next `cache.lookup` refetches (spy count 2). Distinct from the isolated
  `test_invalidate_clears_cache`.
- **Task 3 (docs, 7ba1ff4):** Rewrote the deploy/README.md "Reload behavior" first bullet to state the
  forecast cache is now invalidated on reload (no stale-forecast window); kept the separate
  `operator_id`-requires-restart limitation intact and adjusted the closing restart line to apply only
  to it. Updated 11-CONTEXT.md D-12 and the Deferred-section bullet to mark bot-cache invalidation as
  wired (CR-01 closed), keeping the scheduler-READ seam as still-deferred. Corrected the stale
  "scheduler-read seam stays UNWIRED" in-code comment in daemon.py.

## Deviations from Plan

None - plan executed exactly as written.

## Verification

- `grep -n "cache=cache" weatherbot/scheduler/daemon.py` → present in both run_daemon poll-loop calls.
- `grep -n "cache.invalidate" weatherbot/scheduler/daemon.py` → present in `_do_reload` success branch.
- `uv run python -c "import weatherbot.scheduler.daemon"` → imports cleanly.
- `uv run pytest tests/test_reload.py tests/test_cache.py -q` → 28 passed.
- `uv run pytest -q` (full suite) → 284 passed, 1 warning (pre-existing audioop DeprecationWarning).
- deploy/README.md and 11-CONTEXT.md no longer frame forecast-cache-on-reload as a deferral.

## Self-Check: PASSED

- FOUND: weatherbot/scheduler/daemon.py (cache=cache + cache.invalidate present)
- FOUND: tests/test_reload.py (new integration test, passes)
- FOUND: deploy/README.md (invalidat wording present)
- FOUND: .planning/phases/11-discord-inbound-gateway-bot/11-CONTEXT.md (CR-01 + invalidat present)
- FOUND commit c6064e4 (Task 1)
- FOUND commit 80ee140 (Task 2)
- FOUND commit 7ba1ff4 (Task 3)
