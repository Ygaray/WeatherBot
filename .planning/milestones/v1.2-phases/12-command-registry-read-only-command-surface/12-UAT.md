---
status: complete
phase: 12-command-registry-read-only-command-surface
source: [12-VERIFICATION.md]
started: 2026-06-19T16:05:00Z
updated: 2026-06-23T00:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Discord live surface — all read-only commands as operator on yahir-mint
expected: After `sudo systemctl restart weatherbot`, each command (!help, !locations, !status, !sun, !sun <other loc>, !wind <loc>, !alerts <loc>, !next-cloudy <loc>, !sun bogusplace) answers correctly per VERIFICATION.md human_verification[0].
result: pass

### 2. CLI live surface — same commands as subcommands against live config/API
expected: `weatherbot locations|status|sun <loc>|wind <loc>|alerts <loc>|next-cloudy <loc>` each prints plain-text content matching the Discord embed content (D-04) and exits 0; unknown location prints the hint and exits non-zero.
result: pass

### 3. Briefing isolation on the live daemon after restart
expected: A scheduled briefing is still delivered on time after the restart; the command surface never gates, delays, or drops it (CMD-16 isolation on the live daemon). Confirm via journal / !status last-briefing after the next scheduled send.
result: pass

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
