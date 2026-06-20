---
status: testing
phase: 15-proactive-uv-sunscreen-monitor
source: [15-VERIFICATION.md]
started: 2026-06-19T19:30:00Z
updated: 2026-06-19T19:30:00Z
---

## Current Test

number: 1
name: Live daylight-crossing UV monitor UAT on yahir-mint
expected: |
  After deploying + `sudo systemctl restart weatherbot`, over a real daylight UV
  crossing for today's active location, Discord receives — each exactly once — a
  pre-warn as UV approaches the threshold, a crossing (or already-high) alert when it
  reaches it, and an all-clear when it drops back below. A mid-day restart after alerts
  fired produces no re-spam (durable uv_alerts rows). The morning briefing still went
  out exactly once, unaffected by the monitor (UV-06).
awaiting: user response

## Tests

### 1. Monitor registers and ticks during daylight on active locations
expected: Daemon log shows `__uvmonitor__` registered and ticking on the configured interval during daylight; skips (no post) outside daylight / for non-active locations.
result: [pending]

### 2. Three once/day/location alerts over a real crossing
expected: Over a real daylight UV crossing, Discord receives a pre-warn, a crossing (or already-high), and an all-clear — each exactly once per day per location.
result: [pending]

### 3. No re-spam after a mid-day restart
expected: `sudo systemctl restart weatherbot` mid-day after alerts fired produces no repeat alerts (durable `uv_alerts` rows suppress repeats).
result: [pending]

### 4. Briefing unaffected by the monitor (UV-06)
expected: The morning briefing still went out exactly once, on time, unaffected by the monitor tick.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
