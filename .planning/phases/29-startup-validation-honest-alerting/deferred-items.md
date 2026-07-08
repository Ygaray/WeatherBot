# Deferred Items — Phase 29

Out-of-scope discoveries logged during execution (not fixed — pre-existing, unrelated
to the current task's changes).

## Pre-existing lint findings in weatherbot/scheduler/daemon.py (discovered 29-03)

These `ruff` errors exist on `HEAD` before plan 29-03 touched the file (verified via
`git show HEAD:weatherbot/scheduler/daemon.py`). Not caused by the CONFIG_INVALID import.

- `F401` — `yahir_reusable_bot.config.ReloadEngine` imported but unused
- `F401` — `weatherbot.ops.pidfile.PID_FILE` imported but unused
- `F841` — local variable `notifier` (daemon.py:1406) assigned but never used

Note: `notifier`/`ReloadEngine`/`PID_FILE` may be consumed by later Phase-29 plans
(29-05 wires the fatal path through `parts.notifier` etc.). Revisit at phase close;
do not blind-fix.

## 29-05 update

`notifier`/`ReloadEngine`/`PID_FILE` confirmed STILL unused after 29-05 (29-05 reads
`parts.fatal`, not `parts.notifier`, at the gate-return branch). They remain
pre-existing out-of-scope findings — candidates for the phase-close cleanup sweep.
`AUTH_FAILED` / `run_self_check` became unused via the `gate_until_healthy` removal
and were fixed IN-SCOPE with `# noqa: F401` re-export markers (consumed by wiring.py
via `daemon.AUTH_FAILED` / `daemon.run_self_check`).
