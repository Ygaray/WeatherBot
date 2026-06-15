---
phase: 05-deployment-reboot-survival
plan: 03
subsystem: infra
tags: [daemon, scheduler, discord-webhook, apscheduler, systemd, online-signal, gap-closure]

# Dependency graph
requires:
  - phase: 05-deployment-reboot-survival
    provides: "Type=notify Restart=always systemd unit + run_daemon online signal (emit_online) + self-check gate (05-02)"
  - phase: 03-scheduler-daemon
    provides: "run_daemon spine, fire_slot, emit_online, the channel composition seam"
provides:
  - "Channel-from-settings fallback in run_daemon: when channel is None and settings present, build_channel(config, settings) is called once and shared by both _register_jobs and emit_online"
  - "Restored the human-facing (Discord) third of the startup online signal on the production --run path"
  - "Regression coverage for the channel=None online-ping path (the blind spot that let the gap ship)"
affects: [deployment, daemon, online-signal, monitoring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition-root channel fallback mirrors send_now (cli.py:119-122): build once at the entry point, thread the single instance everywhere (one channel per process, WR-04)"
    - "Fail-loud-at-load: build_channel ValueError is left un-guarded in run_daemon so a bad webhook/type surfaces at startup before scheduler.start(), never as a silently-ringless daemon"

key-files:
  created: []
  modified:
    - "weatherbot/scheduler/daemon.py"
    - "tests/test_scheduler.py"

key-decisions:
  - "Fix at the run_daemon seam (not inside emit_online): build once and share with both jobs and the online ping, mirroring send_now — avoids a second build site and matches WR-04 single-construction"
  - "Lazy in-function import of build_channel (consistent with daemon's existing lazy send_now import), keeping build_channel's transitive imports off the daemon module import-time graph"
  - "build_channel left intentionally un-guarded so a missing/invalid webhook is a loud startup failure, not a daemon that comes online with no delivery path"
  - "Regression test stubs the lazy build SITE (weatherbot.channels.build_channel), not a channel arg, to exercise the exact production None path"

patterns-established:
  - "Pattern: gap-closure plans pin a regression test directly to the missing behavior (assert build_channel was invoked AND the ping was delivered) so the same blind spot cannot reopen"

requirements-completed: [OPS-02]

# Metrics
duration: 9min
completed: 2026-06-14
---

# Phase 5 Plan 03: Daemon Online-Ping Channel Fallback Summary

**run_daemon now builds the Discord channel from config+settings when none is injected (mirroring send_now), restoring the one-time startup online ping on the production `--run` path that the UAT found silently missing.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-14T22:50:00-0600 (approx)
- **Completed:** 2026-06-14
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Closed the diagnosed UAT gap: `--run` (cli.py:480, called without `channel=`) previously left `run_daemon`'s `channel` as `None`, so `emit_online`'s `if channel is not None` guard silently dropped the Discord online ping. The daemon now builds the channel once from `config`+`settings` and threads that single instance into both `_register_jobs` and `emit_online`.
- Preserved the injectable seam: an explicitly-passed `channel=` still wins and skips the build (tests stay deterministic); `channel=None` + `settings=None` stays `None` (channel-less path still tolerated).
- Added two regression tests closing the blind spot — one driving the production `channel=None` + settings-present shape and asserting the ping is delivered via the built channel, one proving an injected channel skips the build entirely.

## Task Commits

Each task was committed atomically:

1. **Task 1: Build the channel from settings in run_daemon when channel is None** - `360d253` (fix)
2. **Task 2: Add the regression test for the channel=None online-ping path** - `36e10b0` (test)

## Files Created/Modified
- `weatherbot/scheduler/daemon.py` - Added the `channel is None and settings is not None` fallback at the top of `run_daemon` (lazy `build_channel` import, un-guarded build, updated docstring). `emit_online`'s guard and warning are unchanged.
- `tests/test_scheduler.py` - Added `_NeverSetImmediateWait` (hoisted to module scope), `test_online_ping_built_from_settings_when_channel_none`, and `test_injected_channel_skips_build`.

## Decisions Made
- Fixed at the `run_daemon` composition root rather than inside `emit_online`, so the single built channel is shared by the online ping AND every briefing job (WR-04 single-construction, matching `send_now`). The UAT's `missing` list offered both placements; the run_daemon seam is the one that keeps construction single-sited.
- Left the `build_channel` call un-guarded: a `ValueError` (unknown type / missing webhook) propagates at startup before the self-check gate and `scheduler.start()`, surfacing a misconfiguration loudly instead of producing a ringless online daemon.
- Used a lazy in-function `from weatherbot.channels import build_channel`, consistent with the module's existing lazy `send_now` import that avoids the cli<->daemon cycle.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None. The `_NeverSetImmediateWait` helper used by the model test was a local class inside `test_online_once_fires_all_signals_then_starts`; rather than modify that existing test (the plan forbids touching existing tests), a module-scope copy was added for the two new tests to reuse. The original local definition was left untouched, so no existing test changed.

## Known Stubs
None.

## Verification
- `uv run pytest tests/test_scheduler.py -k "channel_none or skips_build"` → 2 passed (the new regression tests).
- `uv run pytest` → 186 passed (was 184; +2 new, all pre-existing daemon online/gate tests green and unmodified).
- `uv run ruff check weatherbot tests` → All checks passed.
- The regression test is coupled to the fix: without the Task 1 fallback, `channel` stays `None`, `build_channel` is never called, and the guard drops the ping — so both `build_calls == [1]` and `len(stub_channel.sent_text) == 1` would fail.

Live operator re-verification (not required to be a full reboot — the ping fires on every startup, so a service restart suffices):
```
sudo systemctl restart weatherbot
journalctl -u weatherbot -b | tail   # expect the post-start "weatherbot online" log
# confirm "WeatherBot online — startup self-check passed." arrives in the Discord channel
```

## Next Phase Readiness
- OPS-02's online signal is now complete across all three faces (log + READY=1 + Discord ping) on the production `--run` path.
- The OPS-01 live reboot UAT remains deferred by operator choice; this fix means the next reboot (or a plain `systemctl restart`) will also deliver the Discord half of the online signal.

## Self-Check: PASSED
- `weatherbot/scheduler/daemon.py` — FOUND (fallback at line 568)
- `tests/test_scheduler.py` — FOUND (2 new tests)
- Commit `360d253` — FOUND
- Commit `36e10b0` — FOUND

---
*Phase: 05-deployment-reboot-survival*
*Completed: 2026-06-14*
