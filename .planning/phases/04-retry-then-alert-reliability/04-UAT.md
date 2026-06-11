---
status: testing
phase: 04-retry-then-alert-reliability
source: [04-VERIFICATION.md]
started: 2026-06-11T00:00:00Z
updated: 2026-06-11T00:00:00Z
---

## Current Test

number: 1
name: Out-of-band alert during a live Discord outage (SC2)
expected: |
  Run the daemon with a deliberately-broken Discord webhook (invalid/unreachable URL)
  and let a scheduled slot fire (or use a near-future slot). After the two-burst retry
  exhausts (or immediately on a 401/403), a CRITICAL `briefing_missed` structured log
  event appears on stderr/journald AND exactly one row is written to the `alerts` table
  for the (location, slot, local_date). A re-fire does not add a second alert row or emit
  a second event (no alert loop). Discord being down does not swallow this signal.
awaiting: user response

## Tests

### 1. Out-of-band alert during a live Discord outage (SC2)
expected: After the two-burst retry exhausts (or immediately on 401/403), a CRITICAL `briefing_missed` log event appears on stderr/journald AND exactly one deduped row lands in the `alerts` table for (location, slot, local_date); a re-fire adds no second alert.
result: [pending]

### 2. Heartbeat liveness cadence over real wall-clock (SC4)
expected: Start the daemon and leave it running >10 minutes with no sends due. The single `heartbeat` row's `last_tick_utc` advances on the ~600s IntervalTrigger cadence (and is stamped once at startup), independent of any send. After a successful send, `last_success_utc` is also stamped — so a monitor can distinguish a crashed process (stale last_tick) from one alive-but-failing-to-send (fresh last_tick, stale last_success).
result: [pending]

### 3. Fail-loud over-budget config + `--check` budget surface (D-09)
expected: A `[reliability]` section with an over-budget value (e.g. `mid_pause_seconds = 5400`) makes `weatherbot --check` fail loudly at load with the budget-exceeds-90-min-grace error and NOT proceed. With a valid budget, `--check` prints the resolved retry budget line (`retry budget: attempts_per_burst=… burst_spread_seconds=… mid_pause_seconds=… (approx total ~NN min)`) and exits 0 without sending.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
