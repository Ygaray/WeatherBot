---
status: diagnosed
phase: 05-deployment-reboot-survival
source: [05-VERIFICATION.md]
started: 2026-06-11
updated: 2026-06-14T22:49:40-0600
---

## Current Test

[testing complete]

## Tests

### 1. Live host-reboot power-cycle survival (OPS-01 SC#1)
expected: |
  On host `yahir-mint`, run `sudo reboot`. After the host returns, without touching anything:
    systemctl is-active weatherbot        # -> active
    journalctl -u weatherbot -b | tail    # -> post-boot "weatherbot online" log + Discord online ping
  The service is installed, `enabled` (symlinked into multi-user.target.wants), and was confirmed
  `active (running)` pre-reboot — so this UAT is the live confirmation that auto-start survives a
  power cycle. Code + systemd config for reboot survival are complete; only the live observation
  is outstanding (operator deferred the reboot to avoid power-cycling their primary workstation).
result: issue
reported: "After live `sudo reboot` on yahir-mint: `systemctl is-active` = active and the post-boot `weatherbot online` log line (jobs=3, PID 1485, 21:51:04) fired this boot, but the one-time Discord 'online' ping never arrived in the channel. Auto-start + log + READY=1 survived the reboot; the Discord half of the startup online signal is missing."
severity: major

## Summary

total: 1
passed: 0
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "After reboot, a one-time Discord 'online' ping is posted to the channel once the startup self-check passes (same atomic online signal as the `weatherbot online` log line and READY=1)"
  status: failed
  reason: "User reported: post-reboot, `weatherbot online` log line + READY=1 + heartbeats all fired (service active this boot), but no Discord 'online' message arrived in the channel"
  severity: major
  test: 1
  root_cause: "The `--run` CLI path calls `daemon.run_daemon(config, settings, db_path)` WITHOUT a `channel=` argument (weatherbot/cli.py:480), so `run_daemon`'s `channel` defaults to None and is passed as None into `emit_online` (daemon.py:622-627). `emit_online` guards the Discord ping with `if channel is not None:` (daemon.py:527) and has NO build-from-settings fallback, so the ping is silently skipped in production. Regular briefings are unaffected because `fire_slot -> send_now` builds its own channel from config+settings when channel is None (cli.py:119-122). Daemon tests pass only because they inject a channel directly, so they never exercise the None path."
  artifacts:
    - path: "weatherbot/cli.py"
      issue: "line ~480: --run path invokes run_daemon without channel=, so the daemon never gets a delivery channel for the online ping"
    - path: "weatherbot/scheduler/daemon.py"
      issue: "run_daemon (~536) and emit_online (503-533) have no build_channel fallback when channel is None — unlike send_now (cli.py:119-122); emit_online's `if channel is not None` guard then drops the ping"
  missing:
    - "Build the channel from config+settings when channel is None — either in run_daemon (mirroring send_now's fallback, then thread the built channel into both emit_online and the registered jobs) or via build_channel() inside emit_online"
    - "A regression test that drives run_daemon with channel=None + a stubbed build_channel and asserts the online ping is sent (closes the test blind spot that let this ship)"
  debug_session: ""
