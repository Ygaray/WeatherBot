---
status: resolved
phase: 17-minimal-persistent-panel-core-wiring
source: [17-VERIFICATION.md]
gate: 2
blocking: milestone
started: 2026-06-24T03:00:00Z
updated: 2026-06-27T22:25:00Z
resolved: 2026-06-27T22:25:00Z   # Gate-2 live UAT driven on host yahir-mint at v1.3 milestone close
---

## Current Test

_None — Gate-2 batch driven live on yahir-mint at v1.3 milestone close (all 5 scenarios PASS)._

## Tests

### 1. Live cold-cache tap of every command button (weather / uv / next-cloudy / sun / wind / status / alerts)
expected: Each tap acked within Discord's 3s window (⏳ Fetching… cue appears, components disabled), then the panel edits in-place to the result embed with components reattached; no second message, no "interaction failed" toast.
result: [pass]

### 2. Non-operator tap on the shared pinned panel (second Discord account)
expected: The foreign user sees ONLY an ephemeral "This panel is in use by someone else."; the shared panel is NOT edited/clobbered; no command runs; the operator sees nothing change.
result: [pass]

### 3. Dropdown selection round-trip + hot-reload re-derivation
expected: A location command result reflects the dropdown selection; after a config hot-reload that adds/removes a location, re-opening the panel shows the updated location list.
result: [pass]

### 4. Double-tap during a cold fetch
expected: The disabled-copy ack neutralizes the second tap (components disabled until the result lands); no InteractionResponded error, no duplicate fetch.
result: [pass]

### 5. Live failure isolation
expected: On a forced handler failure (e.g. transient OpenWeather error), the operator gets a generic in-place error ("Sorry — something went wrong."); the bot does not crash; the briefing scheduler thread is unaffected; no traceback reaches the gateway loop.
result: [pass]

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

_None — all mechanisms were source-verified and unit-tested (Gate 1 PASS), then all 5 live-Discord scenarios were driven on host yahir-mint during the v1.3 milestone-close Gate-2 batch (2026-06-27). All PASS._
