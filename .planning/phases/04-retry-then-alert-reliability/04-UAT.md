---
status: complete
phase: 04-retry-then-alert-reliability
source: [04-VERIFICATION.md]
started: 2026-06-11T00:00:00Z
updated: 2026-06-11T00:00:00Z
---

## Current Test

[testing complete — all 3 passed; both gaps fixed inline and re-verified]

## Tests

### 1. Out-of-band alert during a live Discord outage (SC2)
expected: After the two-burst retry exhausts (or immediately on 401/403), a CRITICAL `briefing_missed` log event appears on stderr/journald AND exactly one deduped row lands in the `alerts` table for (location, slot, local_date); a re-fire adds no second alert.
result: pass
resolution: "FIXED + re-verified live. SC2 behavior held throughout; the reason-misclassification gap below was fixed (commit 375b081) and a live re-run now shows reason=transient_exhausted. Regression test test_nonok_delivery_exhaustion_alerts_transient added."
reported: "Tested live with a real broken Discord webhook (404 Unknown Webhook). The stated SC2 behavior all held — CRITICAL `briefing_missed` fired, exactly one `alerts` row, re-fire added no second row (dedup works), Discord-down not swallowed. BUT the alert `reason` was `internal_error`, not `transient_exhausted` (now fixed)."
severity: major
diagnosis: "`build_retrying` sets reraise=True with NO retry_error_callback. When every delivery attempt returns a non-ok DeliveryResult (no exception raised — the Discord-down case), tenacity raises `RetryError` on exhaustion (it can only reraise actual exceptions; a non-ok RESULT has none). `fire_slot`'s `except httpx.*` handlers don't catch RetryError, so it hits the broad `except Exception` → REASON_INTERNAL_ERROR. The `if not result.ok:` branch (daemon.py ~239) that records REASON_TRANSIENT_EXHAUSTED is therefore DEAD CODE for the all-attempts-fail case. The manual path (04-04 run_send_now) avoided this with its own `retry_error_callback=lambda rs: rs.outcome.result()`; the daemon's shared build_retrying did not."
proposed_fix: "Add `retry_error_callback=lambda rs: rs.outcome.result()` to build_retrying. On non-ok-result exhaustion it returns the last non-ok DeliveryResult (→ daemon's `if not result.ok` fires → transient_exhausted); on exception exhaustion `.result()` re-raises the httpx error (→ daemon's `except httpx.*` → transient/auth). build_retrying is daemon-only (run_send_now uses its own Retrying), so the change is isolated. Add a daemon test: all-attempts-fail delivery records reason=transient_exhausted, not internal_error."

### 2. Heartbeat liveness cadence over real wall-clock (SC4)
expected: Start the daemon and leave it running >10 minutes with no sends due. The single `heartbeat` row's `last_tick_utc` advances on the ~600s IntervalTrigger cadence (and is stamped once at startup), independent of any send. After a successful send, `last_success_utc` is also stamped — so a monitor can distinguish a crashed process (stale last_tick) from one alive-but-failing-to-send (fresh last_tick, stale last_success).
result: pass
note: "Verified the mechanism deterministically (the ~600s IntervalTrigger calls the same `_heartbeat_tick`/`stamp_tick` exercised here, so real wall-clock waiting was not required): init → last_tick NULL; startup `stamp_tick` sets last_tick immediately (IN-02 fix); a periodic `_heartbeat_tick` advances it; a successful `fire_slot` stamps last_success. Crashed / alive-but-failing / alive-and-delivering are all distinguishable."

### 3. Fail-loud over-budget config + `--check` budget surface (D-09)
expected: A `[reliability]` section with an over-budget value makes `weatherbot --check` fail loudly at load with the budget-exceeds-90-min-grace error and NOT proceed. With a valid budget, `--check` prints the resolved retry budget line and exits 0 without sending.
result: pass
note: "Over-budget (mid_pause_seconds=4000) → `--check` exited 1 with the corrected-formula error ('14 within-burst waits up to 129s + 4000s mid-pause = 5800s must stay under 5400s'). This config passes the OLD 2*spread+mid_pause guard (5200s) — so it directly proves the WR-01/02 fix. Valid config → `--check` printed 'retry budget: attempts_per_burst=8 burst_spread_seconds=600 mid_pause_seconds=2700 (approx total ~65 min)', real .env key probe passed, exit 0, nothing sent. MINOR follow-up: the `--check` echo's 'approx total' (cli.py:383) still uses the old `(2*spread+mid_pause)/60` ≈65 min formula while the validator now enforces ~75 min — cosmetic inconsistency."

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "A daemon briefing that fails delivery on every attempt (Discord down) is alerted with reason=transient_exhausted (RELY-03 taxonomy)"
  status: resolved
  reason: "Live test showed reason=internal_error. Root cause: build_retrying lacked retry_error_callback, so non-ok-result exhaustion raised RetryError → broad except → internal_error; the transient_exhausted branch was dead for the all-fail case."
  resolution: "Added retry_error_callback=lambda rs: rs.outcome.result() to build_retrying (commit 375b081) + regression test test_nonok_delivery_exhaustion_alerts_transient. Live re-run confirms reason=transient_exhausted."
  severity: major
  test: 1
  artifacts: ["weatherbot/reliability/retry.py::build_retrying", "weatherbot/scheduler/daemon.py::fire_slot"]

- truth: "`--check` 'approx total' reflects the true worst-case retry budget"
  status: resolved
  reason: "Echo at cli.py:383 used old (2*spread+mid_pause)/60 ≈65 min; validator enforces ~75 min worst case."
  resolution: "Extracted Reliability.worst_case_seconds() as the single source of truth for both the validator and the --check echo (commit a7b29ff)."
  severity: cosmetic
  test: 3
  artifacts: ["weatherbot/cli.py::do_check", "weatherbot/config/models.py::Reliability.worst_case_seconds"]
