---
status: complete
phase: 11-discord-inbound-gateway-bot
source: [11-VERIFICATION.md]
started: 2026-06-17T00:00:00Z
updated: 2026-06-18T19:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live `!weather` command in the real Discord channel
expected: An embed briefing reply for a known location (Now / High-Low / Rain fields); the configured-names error text for an unknown location; no "Heartbeat blocked" warning in logs.
result: pass
verified: |
  After resolving the startup blocker (see history below), retested live on the daemon
  running current code (PID 3838953, boot 2026-06-18 18:49):
  - Known location: embed reply rendered correctly with Now / High-Low / Rain fields.
    Logs: `lookup complete location=Carlsbad`, `lookup complete location='El Paso'`.
  - Unknown location: replied "No location named 'los Angeles'; configured locations:
    Carlsbad, El Paso" — the configured-names error text, exactly as specified.
  - No "Heartbeat blocked" / heartbeat-interference warnings in the journal; off-loop
    fetch via run_in_executor kept the scheduler thread free.
observations:
  - "Cosmetic (minor): embeds could use weather icons/emoji. Enhancement idea, not a defect — captured for backlog."
history: |
  Originally failed as a BLOCKER, since fixed:
  (1) Initial no-reply: live daemon (PID 585105, started Jun 15 17:35) predated the Phase 11
      inbound bot (landed Jun 17) — the running process had no inbound bot at all.
  (2) On restart with current code the daemon CRASH-LOOPED before startup completed:
        PermissionError: [Errno 13] Permission denied: '/run/.wbpid-...'
        write_pid_atomic(PID_FILE) -> daemon.py:1117 -> pidfile.py:45 (tempfile.mkstemp dir=/run)
      Root cause: PID_FILE hardcoded to /run/weatherbot.pid; /run root-owned, but the unit
      runs User=yahir with no RuntimeDirectory=. Phase 9 (PID-file) + Phase 5 (unit) regression.
  Fixed by quick task 260617-idm: PID_FILE -> /run/weatherbot/weatherbot.pid + RuntimeDirectory=
  weatherbot added to the unit. Installed unit re-copied (host-substituted) + daemon-reload +
  restart by the operator; daemon now starts clean and /run/weatherbot/weatherbot.pid is written.

### 2. Message Content Intent enabled in the Discord Developer Portal
expected: Message Content Intent (privileged) toggled ON for the bot application; on_ready logs "inbound bot ready" (not the CRITICAL "message_content intent missing" line). With it OFF, the bot reads empty message bodies.
result: pass
verified: |
  Journal at boot 2026-06-18 18:49 shows `inbound bot thread started` -> gateway connected ->
  `inbound bot ready user=WeatherBot#4860`, with NO CRITICAL "message_content intent missing"
  line. Reaching `ready` without that abort + successfully reading message bodies in Test 1
  (the bot parsed `!weather <loc>` content) confirms the privileged Message Content Intent is ON.

### 3. Token revocation / gateway failure isolation across a scheduled slot
expected: BotThread logs CRITICAL "invalid Discord token; inbound bot disabled, briefings unaffected" and dies alone; the next scheduled briefing still fires via the webhook; the systemd READY gate is unaffected.
result: skipped
reason: "Operator chose to skip the disruptive live test. Bot-failure isolation is already covered by the Phase 11 automated tests (CMD-08 / T-11-11 / T-11-12): BotThread is a managed child of run_daemon started after the READY signal and torn down in finally, isolated so bot failure never stops a briefing or flips READY. Live retest would mean re-breaking a healthy daemon for marginal added confidence."

## Summary

total: 3
passed: 2
issues: 0
pending: 0
skipped: 1
blocked: 0

## Gaps

- truth: "On `systemctl restart`, the daemon (User=yahir, non-root) starts cleanly and writes its PID file."
  status: resolved
  reason: "Daemon crash-looped on restart. PermissionError [Errno 13] writing /run/.wbpid-* — PID_FILE was /run/weatherbot.pid but the unit runs User=yahir with no RuntimeDirectory=; /run is root-owned. Phase 9 PID-file feature never reconciled with the Phase 5 unit."
  severity: blocker
  test: 1
  artifacts: [weatherbot/ops/pidfile.py, weatherbot/scheduler/daemon.py:1117, deploy/weatherbot.service, /etc/systemd/system/weatherbot.service]
  missing: []
  resolution: "Fixed by quick task 260617-idm (commits c1f6ad7, 5dcec80): PID_FILE -> /run/weatherbot/weatherbot.pid; RuntimeDirectory=weatherbot added to the unit. Operator re-installed the host-substituted unit + daemon-reload + restart. Verified live 2026-06-18: daemon active, /run/weatherbot/weatherbot.pid written, full UAT happy path green. 291 tests pass."
