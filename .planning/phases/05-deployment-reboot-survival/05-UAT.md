---
status: testing
phase: 05-deployment-reboot-survival
source: [05-VERIFICATION.md]
started: 2026-06-11
updated: 2026-06-11
---

## Current Test

number: 1
name: Live host-reboot power-cycle survival (OPS-01 SC#1)
expected: |
  On host `yahir-mint`, after `sudo reboot` and WITHOUT manually starting anything:
  - `systemctl is-active weatherbot` returns `active`
  - `journalctl -u weatherbot -b | tail` shows a post-boot `weatherbot online` log line
    and a one-time Discord "online" ping — appearing only after the startup self-check passes.
awaiting: user response

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
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
