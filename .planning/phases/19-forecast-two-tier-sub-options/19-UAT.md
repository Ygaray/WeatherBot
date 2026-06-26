---
status: testing
phase: 19-forecast-two-tier-sub-options
source: [19-VERIFICATION.md]
started: 2026-06-26T00:00:00Z
updated: 2026-06-26T00:00:00Z
---

## Current Test

number: 1
name: Live reveal + variant tap for selected location
expected: |
  The 2×2 sub-grid reveals on the first Forecast tap; a variant tap renders the
  correct in-place forecast embed for the currently selected location, then
  collapses the sub-grid.
awaiting: user response

## Tests

### 1. Live reveal + variant tap for selected location
expected: On the live yahir-mint host (deploy + `sudo systemctl restart weatherbot`, summon `!panel`): tapping Forecast reveals the 2×2 sub-grid; tapping a variant (e.g. Weekday Compact) renders the correct in-place forecast embed for the currently selected location, then collapses the sub-grid.
result: [pending]

### 2. Post-restart routing on a still-revealed panel
expected: After revealing the sub-grid, `sudo systemctl restart weatherbot` while the panel message still shows the revealed grid, then tap a forecast variant on the still-displayed grid — the tap still routes (persistent view re-registers all 13 custom_ids via add_view) and renders the correct forecast; display state is independent of routing (D-05).
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
