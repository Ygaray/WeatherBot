---
phase: 29-startup-validation-honest-alerting
plan: 05
subsystem: scheduler-composition-root
tags: [startup-validation, fatal-exit, readiness-ordering, observability, dead-code, tdd]
requires: [29-02, 29-03]
provides:
  - "RuntimeParts.fatal marker + non-zero exit on CONFIG_INVALID (HARD-STARTUP-02, D-10)"
  - "F07 online ping strictly after READY (HARD-STARTUP-03, D-12)"
  - "F90 forecast-slot announce incl. disabled (HARD-STARTUP-03, D-11)"
  - "F89 _prune_forecast_streaks on reload (HARD-STARTUP-03, D-13)"
  - "dead gate_until_healthy removed (F16 cleanup)"
affects:
  - weatherbot/scheduler/wiring.py
  - weatherbot/scheduler/daemon.py
tech-stack:
  added: []
  patterns:
    - "dedicated fatal threading.Event kept SEPARATE from stop so fatal-vs-clean-SIGTERM exit-code survives (T-29-13)"
    - "fatal alert reuses outcome-only detail + best-effort send; never masks the non-zero return (T-29-11/T-29-15)"
    - "post-READY best-effort online ping so a hung webhook can't gate systemd readiness (T-29-14)"
    - "reload-time set-diff prune against the authoritative _desired_job_ids (T-29-16)"
    - "daemon-namespace resolution: build_runtime resolved via globals() so the fatal-spy monkeypatch bites"
key-files:
  created: []
  modified:
    - weatherbot/scheduler/wiring.py
    - weatherbot/scheduler/daemon.py
    - tests/test_scheduler.py
    - tests/test_reload.py
decisions:
  - "fatal is a dedicated Event on RuntimeParts, distinct from stop — a clean SIGTERM also sets stop, so reusing it would collapse the fatal-vs-clean exit-code distinction"
  - "the fatal branch fires BEFORE the auth branch in _on_fail so a CONFIG_INVALID/CRITICAL result never falls into the re-probe path; AUTH_FAILED stays non-fatal (D-03)"
  - "online ping relocated out of the on_online hook (hub fires it pre-ready) into run_daemon after the gate returns True (post-READY); scheduler.start()-before-READY invariant preserved in _on_online"
  - "_announce_schedule stops continue-skipping disabled slots (briefing + forecast) so a paused slot is auditable at boot; disabled slot -> no job -> next_run_time=None"
  - "F89 prune keyed by _forecast_job_id (NOT location.name — the stale CONTEXT wording); set-diff vs _desired_job_ids so live slots are kept, removed/renamed pruned"
  - "gate_until_healthy removed (dead twin of hub ReadyGate, zero prod callers); emit_online/_do_reload deliberately LEFT for Phase 35 (F16)"
metrics:
  duration: ~20min
  completed: 2026-07-07
  tasks: 3
  files: 4
status: complete
---

# Phase 29 Plan 05: Composition-Root Corrections (Fatal Plumbing + F07/F90/F89 + Dead-Code) Summary

Landed the defense-in-depth composition-root corrections in `daemon.py` + `wiring.py`, all
riding the hub's EXISTING extension points (`on_fail` hook + `stop` Event) with NO hub source
touched: a dedicated `fatal` marker that makes a config-invalid death exit non-zero (systemd
sees a failure) while a clean SIGTERM still returns 0; the online ping moved strictly after
READY so a hung webhook can't block systemd readiness; every briefing AND forecast slot
(including disabled ones) announced at boot; forecast failure-streaks pruned on reload; and the
dead `gate_until_healthy` twin of the hub ReadyGate removed.

## What Was Built

- **`RuntimeParts.fatal: threading.Event`** (wiring.py) — a DEDICATED marker constructed next to
  `stop` in `build_runtime` (`fatal = daemon.threading.Event()`) and returned on the parts.
  Kept strictly separate from `stop` so the fatal-vs-clean-SIGTERM distinction survives (D-10 /
  T-29-13).
- **`_on_fail` fatal branch** (wiring.py) — a FIRST branch before the auth branch: on
  `reason == daemon.CONFIG_INVALID and severity >= daemon.Severity.CRITICAL` it sets `fatal`,
  fires ONE best-effort outcome-only operator alert via the closed-over `channel`, logs one
  CRITICAL line, and sets `stop` to break the hub re-probe loop. AUTH_FAILED / NETWORK_NOT_READY
  branches are UNCHANGED (D-03 guard — they re-probe, never fatal).
- **`run_daemon` gate-return branch** (daemon.py) — `return 1 if parts.fatal.is_set() else 0`
  after `ready_gate.run(stop)` returns False. Reads `parts.fatal` directly, never `stop`.
- **`build_runtime` daemon-namespace resolution** (daemon.py) — `run_daemon` now resolves
  `build_runtime` via `globals().get("build_runtime")` (fallback to the lazy import) so a
  daemon-suite `daemon.build_runtime` monkeypatch (the fatal-marker spy) bites while still
  dodging the wiring↔daemon import cycle.
- **F07 relocated online ping** (wiring.py + daemon.py) — removed the
  `channel.send("WeatherBot online …")` block from `_on_online` (which the hub fires BEFORE
  `notifier.ready()`); re-added it in `run_daemon` after the gate returns True (post-READY),
  best-effort/try-except, preserving the not-delivered warning. `scheduler.start()` stays in
  `_on_online` so READY still reaches systemd strictly after the scheduler is up.
- **F90 forecast-slot announce** (daemon.py `_announce_schedule`) — stops `continue`-skipping
  disabled slots; logs every briefing slot with `kind="briefing"` and a parallel forecast loop
  keyed by the single-source `_forecast_job_id` with `kind=f"forecast:{fc.kind}"`, `variant`,
  `time`, `days`, `enabled`, and `next_run_time` (disabled → no job → `None`, the visible "off"
  signal).
- **F89 `_prune_forecast_streaks(holder)`** (daemon.py) — computes `_desired_job_ids(holder)`
  and pops `set(_forecast_failure_streaks) - live_ids`; wired best-effort into `_on_applied`
  (wiring.py) in the same try/except style as its siblings.
- **Dead-code removal** (daemon.py) — `gate_until_healthy` (the hand-rolled twin of the hub
  `ReadyGate.run`) removed; replaced by an explanatory NB comment. `emit_online` / `_do_reload`
  deliberately left for Phase 35 (F16).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `daemon.build_runtime` monkeypatch did not bite the local import**
- **Found during:** Task 1 (`test_auth_not_fatal` failed with `KeyError: 'fatal'`).
- **Issue:** `run_daemon` imported `build_runtime` via a function-local `from … import`, so the
  test's `monkeypatch.setattr(daemon_mod, "build_runtime", _spy_build)` never intercepted it and
  the fatal-marker spy never ran.
- **Fix:** resolve `build_runtime` through the daemon module namespace
  (`globals().get("build_runtime")`, fallback to the lazy import), consistent with the module's
  documented daemon-namespace-resolution convention, so the spy monkeypatch bites while the
  import cycle stays dodged.
- **Files modified:** weatherbot/scheduler/daemon.py
- **Commit:** dd3fe6a

**2. [Rule 1 - Lint caused by my change] AUTH_FAILED / run_self_check became unused**
- **Found during:** Task 3 (ruff after `gate_until_healthy` removal).
- **Issue:** removing `gate_until_healthy` deleted the only in-daemon callers of `AUTH_FAILED`
  and `run_self_check`; they are now consumed only via `daemon.AUTH_FAILED` /
  `daemon.run_self_check` by wiring's `_on_fail` / `_health_check` (module-attribute access ruff
  can't see).
- **Fix:** added `# noqa: F401` re-export markers (matching the existing `CONFIG_INVALID`
  pattern) — the symbols must stay importable for wiring's monkeypatch-friendly resolution.
- **Files modified:** weatherbot/scheduler/daemon.py
- **Commit:** 648bcc2

## Deferred Issues (out of scope)

Three PRE-EXISTING ruff findings in `daemon.py` (confirmed present at `HEAD~2`, unrelated to
this plan) were logged to `deferred-items.md` and NOT fixed per the executor scope boundary:
`F401` unused `ReloadEngine`, `F401` unused `PID_FILE`, `F841` unused local `notifier` in
`run_daemon`. Candidates for the phase-close cleanup sweep.

## TDD Red→Green Transition

All five remaining Wave-0 (29-02) phase-29 guarding tests were de-xfailed and now pass strict
green:
- `test_fatal_exit_code`, `test_auth_not_fatal` (D-03 guard) — Task 1
- `test_ping_after_ready` (F07) — Task 2
- `test_announce_forecast` (F90), `test_streak_prune` (F89) — Task 3

`test_clean_shutdown_returns_zero` was never xfail (it guards the pre-existing NETWORK_NOT_READY
re-probe/stop path) and continues to pass. ZERO phase-29 xfails remain.

## Verification

- Target tests: `test_fatal_exit_code`, `test_clean_shutdown_returns_zero`, `test_auth_not_fatal`,
  `test_ping_after_ready`, `test_announce_forecast`, `test_streak_prune` — all pass.
- Full suite: `uv run pytest -q` → **802 passed**, exit 0, ZERO xfails (the "2 snapshots failed"
  line is the known pre-existing syrupy noise; the exit code is 0 — trust the exit code per
  project memory).
- Grep acceptance: `grep 'def gate_until_healthy'` → removed; `grep 'def emit_online\|def _do_reload'`
  → both still present (left for Phase 35).
- No hub source under `../Reusable/YahirReusableBot/yahir_reusable_bot/` modified
  (`git diff --name-only yahir_reusable_bot/` empty).

## Known Stubs

None.

## Threat Flags

None — the changes mitigate the plan's registered threats (T-29-13..16) and introduce no new
trust-boundary surface.

## Self-Check: PASSED

- Files verified on disk: `29-05-SUMMARY.md`, `weatherbot/scheduler/wiring.py`,
  `weatherbot/scheduler/daemon.py`.
- Commits verified in git log: `dd3fe6a` (Task 1), `c3ffb25` (Task 2), `648bcc2` (Task 3).
