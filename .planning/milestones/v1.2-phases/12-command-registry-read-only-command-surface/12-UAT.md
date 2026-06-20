---
status: testing
phase: 12-command-registry-read-only-command-surface
source: [12-VERIFICATION.md]
started: 2026-06-19T16:05:00Z
updated: 2026-06-19T16:05:00Z
---

## Current Test

number: 1
name: Discord live surface — all read-only commands as operator on yahir-mint
expected: |
  After `sudo systemctl restart weatherbot`, sending !help, !locations, !status, !sun,
  !sun <other loc>, !wind <loc>, !alerts <loc>, !next-cloudy <loc>, and !sun bogusplace
  as the operator each answers correctly: help shows the grouped registry list; locations
  lists configured names; status shows alive+uptime, next send per location, bot active,
  UV monitor 'not running', last briefing; sun gives local sunrise/sunset; wind gives
  speed+compass; alerts gives active alerts or 'no active alerts'; next-cloudy gives the
  next cloudy day at 60% or 'no cloudy day'; bogusplace gives the corrective-hint with valid names.
awaiting: user response

## Tests

### 1. Discord live surface — all read-only commands as operator on yahir-mint
expected: After `sudo systemctl restart weatherbot`, each command (!help, !locations, !status, !sun, !sun <other loc>, !wind <loc>, !alerts <loc>, !next-cloudy <loc>, !sun bogusplace) answers correctly per VERIFICATION.md human_verification[0].
result: [pending]

### 2. CLI live surface — same commands as subcommands against live config/API
expected: `weatherbot locations|status|sun <loc>|wind <loc>|alerts <loc>|next-cloudy <loc>` each prints plain-text content matching the Discord embed content (D-04) and exits 0; unknown location prints the hint and exits non-zero.
result: [pending]

### 3. Briefing isolation on the live daemon after restart
expected: A scheduled briefing is still delivered on time after the restart; the command surface never gates, delays, or drops it (CMD-16 isolation on the live daemon). Confirm via journal / !status last-briefing after the next scheduled send.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
