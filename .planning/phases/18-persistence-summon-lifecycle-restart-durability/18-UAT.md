---
status: deferred
phase: 18-persistence-summon-lifecycle-restart-durability
source: [18-VERIFICATION.md]
gate: 2
host: yahir-mint
started: 2026-06-26T00:00:00Z
updated: 2026-06-26T00:00:00Z
---

## Current Test

number: 1
name: Persistent-view re-bind across a real daemon restart (SC#1)
expected: |
  After deploying panel.py/bot.py + adding `[bot] panel_channel_id` to config.toml and
  running `sudo systemctl restart weatherbot`, every button and the dropdown on the
  already-pinned panel route to their callbacks — no "interaction failed".
awaiting: deferred to milestone close (Gate 2)

## Tests

### 1. Persistent-view re-bind across a real daemon restart (SC#1)
expected: Deploy panel.py/bot.py + add `[bot] panel_channel_id` to config.toml; `sudo systemctl restart weatherbot`; tap every button + the dropdown on the already-pinned panel → every component routes to its callback, no "interaction failed".
why_human: `add_view` re-bind is only observable against a live Discord gateway client after a real daemon restart; the gateway-free unit suite proves `is_persistent()==True` + `setup_hook` registration but cannot exercise the live click route.
result: [pending — deferred Gate 2]

### 2. Default selected-location on restart (SC#3)
expected: Select a non-default location on the panel; `sudo systemctl restart weatherbot`; tap a location-taking button → the tap uses `locations[0]` (documented default-on-restart selection).
why_human: Default-on-restart selected-location state is only observable across a real process restart with live gateway interaction.
result: [pending — deferred Gate 2]

### 3. Idempotent live reconcile (SC#2)
expected: After the restart, run `!panel` again in the panel channel → exactly one pinned panel remains; any stray bot-owned panels are removed.
why_human: Idempotent reconcile against the live pinned state on the production host; unit tests prove the find-or-create-one/delete-extras logic but not the live channel outcome.
result: [pending — deferred Gate 2]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

None — Gate 1 (autonomous self-UAT) passed 11/11 must-haves with 622 unit tests green.
The three items above are deferred Gate-2 obligations (live `systemctl restart` UAT on
host `yahir-mint`), to be run at milestone v1.3 close. Each mechanism is unit-verified in
source and tests; only the live-gateway outcome remains to be confirmed on the device.
