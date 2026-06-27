---
status: resolved
phase: 18-persistence-summon-lifecycle-restart-durability
source: [18-VERIFICATION.md]
gate: 2
host: yahir-mint
started: 2026-06-26T00:00:00Z
updated: 2026-06-27T22:25:00Z
resolved: 2026-06-27T22:25:00Z   # Gate-2 live restart UAT driven on host yahir-mint at v1.3 milestone close
---

## Current Test

_None — Gate-2 live `systemctl restart` batch driven on yahir-mint at v1.3 milestone close (all 3 scenarios PASS)._

## Tests

### 1. Persistent-view re-bind across a real daemon restart (SC#1)
expected: Deploy panel.py/bot.py + add `[bot] panel_channel_id` to config.toml; `sudo systemctl restart weatherbot`; tap every button + the dropdown on the already-pinned panel → every component routes to its callback, no "interaction failed".
why_human: `add_view` re-bind is only observable against a live Discord gateway client after a real daemon restart; the gateway-free unit suite proves `is_persistent()==True` + `setup_hook` registration but cannot exercise the live click route.
result: [pass]

### 2. Default selected-location on restart (SC#3)
expected: Select a non-default location on the panel; `sudo systemctl restart weatherbot`; tap a location-taking button → the tap uses `locations[0]` (documented default-on-restart selection).
why_human: Default-on-restart selected-location state is only observable across a real process restart with live gateway interaction.
result: [pass]

### 3. Idempotent live reconcile (SC#2)
expected: After the restart, run `!panel` again in the panel channel → exactly one pinned panel remains; any stray bot-owned panels are removed.
why_human: Idempotent reconcile against the live pinned state on the production host; unit tests prove the find-or-create-one/delete-extras logic but not the live channel outcome.
result: [pass]

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None — Gate 1 (autonomous self-UAT) passed 11/11 must-haves with 622 unit tests green.
The three deferred Gate-2 obligations (live `systemctl restart` UAT on host `yahir-mint`)
were driven at milestone v1.3 close (2026-06-27). All 3 PASS — live-gateway re-bind,
default-on-restart selection, and idempotent reconcile all confirmed on the device.
