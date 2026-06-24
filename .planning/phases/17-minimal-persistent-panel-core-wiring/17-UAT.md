---
status: testing
phase: 17-minimal-persistent-panel-core-wiring
source: [17-VERIFICATION.md]
gate: 2
blocking: milestone
started: 2026-06-24T03:00:00Z
updated: 2026-06-24T03:00:00Z
---

## Current Test

number: 1
name: Tap each command button on the live yahir-mint panel with a cold cache
expected: |
  Each tap is acknowledged within Discord's 3-second window (the ⏳ Fetching… cue
  appears immediately, components disabled), then the panel message edits in-place
  to the command result embed with components reattached — never a second message,
  never an "interaction failed" toast.
awaiting: user response

## Tests

### 1. Live cold-cache tap of every command button (weather / uv / next-cloudy / sun / wind / status / alerts)
expected: Each tap acked within Discord's 3s window (⏳ Fetching… cue appears, components disabled), then the panel edits in-place to the result embed with components reattached; no second message, no "interaction failed" toast.
result: [pending]

### 2. Non-operator tap on the shared pinned panel (second Discord account)
expected: The foreign user sees ONLY an ephemeral "This panel is in use by someone else."; the shared panel is NOT edited/clobbered; no command runs; the operator sees nothing change.
result: [pending]

### 3. Dropdown selection round-trip + hot-reload re-derivation
expected: A location command result reflects the dropdown selection; after a config hot-reload that adds/removes a location, re-opening the panel shows the updated location list.
result: [pending]

### 4. Double-tap during a cold fetch
expected: The disabled-copy ack neutralizes the second tap (components disabled until the result lands); no InteractionResponded error, no duplicate fetch.
result: [pending]

### 5. Live failure isolation
expected: On a forced handler failure (e.g. transient OpenWeather error), the operator gets a generic in-place error ("Sorry — something went wrong."); the bot does not crash; the briefing scheduler thread is unaffected; no traceback reaches the gateway loop.
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps

_None — all mechanisms are source-verified and unit-tested (Gate 1 PASS). These 5 items are deferred Gate-2 (live-Discord) obligations that gate the v1.3 milestone close, not this phase. Run `/gsd-verify-work 17` when the live yahir-mint bot is available to walk through them._
