---
status: partial
phase: 11-discord-inbound-gateway-bot
source: [11-VERIFICATION.md]
started: 2026-06-17T00:00:00Z
updated: 2026-06-17T19:00:00Z
---

## Current Test

[paused — Test 1 surfaced a blocker (daemon crash-loops on restart: PID-file/systemd
RuntimeDirectory regression). Fix being driven via /gsd-quick. Tests 2 & 3 remain pending;
resume with /gsd-verify-work 11 after the daemon starts clean.]

## Tests

### 1. Live `!weather` command in the real Discord channel
expected: An embed briefing reply for a known location (Now / High-Low / Rain fields); the configured-names error text for an unknown location; no "Heartbeat blocked" warning in logs.
result: issue
reported: "No reply (stale daemon), and on restart with current code the daemon crash-loops before it can serve anything."
severity: blocker
diagnosis: |
  Two layers uncovered during setup:
  (1) Initial no-reply: live daemon (PID 585105, started Jun 15 17:35) predated the Phase 11
      inbound bot (landed Jun 17) — the running process had no inbound bot at all.
  (2) On restart with current code (token added to .env, [bot] operator_id added to config.toml,
      both validated — Settings loads, `weatherbot check-config` exit 0), the daemon CRASH-LOOPS
      before startup completes:
        PermissionError: [Errno 13] Permission denied: '/run/.wbpid-...'
        write_pid_atomic(PID_FILE) -> daemon.py:1117 -> pidfile.py:45 (tempfile.mkstemp dir=/run)
      Root cause: pidfile.py:31 hardcodes PID_FILE=/run/weatherbot.pid; /run is root-owned 0755,
      but the systemd unit runs User=yahir (least-privilege, by design) with NO RuntimeDirectory=.
      A non-root user cannot create files in /run. This is a Phase 9 (PID-file/SIGHUP reload) +
      Phase 5 (systemd unit) regression — neither deploy artifact reconciled the runtime dir.
      Crash is at daemon.py:1117, BEFORE scheduler.start/emit_online/bot start (daemon.py:1196),
      so the token/config/bot wiring is intact but untested behind this blocker.
  Fix: (a) add `RuntimeDirectory=weatherbot` to deploy/weatherbot.service (+ installed unit);
       (b) point PID_FILE at /run/weatherbot/weatherbot.pid (inside the systemd-created runtime dir).

### 2. Message Content Intent enabled in the Discord Developer Portal
expected: Message Content Intent (privileged) toggled ON for the bot application; on_ready logs "inbound bot ready" (not the CRITICAL "message_content intent missing" line). With it OFF, the bot reads empty message bodies.
result: [pending]

### 3. Token revocation / gateway failure isolation across a scheduled slot
expected: BotThread logs CRITICAL "invalid Discord token; inbound bot disabled, briefings unaffected" and dies alone; the next scheduled briefing still fires via the webhook; the systemd READY gate is unaffected.
result: [pending]

## Summary

total: 3
passed: 0
issues: 1
pending: 2
skipped: 0
blocked: 0

## Gaps

- truth: "On `systemctl restart`, the daemon (User=yahir, non-root) starts cleanly and writes its PID file."
  status: failed
  reason: "User reported: daemon crash-loops on restart. PermissionError [Errno 13] writing /run/.wbpid-* — pidfile.py:31 hardcodes PID_FILE=/run/weatherbot.pid but the systemd unit runs User=yahir with no RuntimeDirectory=; /run is root-owned. Phase 9 PID-file feature never reconciled with the Phase 5 unit."
  severity: blocker
  test: 1
  artifacts: [weatherbot/ops/pidfile.py:31, weatherbot/ops/pidfile.py:45, weatherbot/scheduler/daemon.py:1117, deploy/weatherbot.service, /etc/systemd/system/weatherbot.service]
  missing: ["RuntimeDirectory=weatherbot in the systemd unit", "PID_FILE pointed at /run/weatherbot/weatherbot.pid (inside the runtime dir)"]
