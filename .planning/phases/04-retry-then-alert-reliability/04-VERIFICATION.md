---
phase: 04-retry-then-alert-reliability
verified: 2026-06-11T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification_outcome: "All 3 live UAT items run and passed (see 04-UAT.md). UAT surfaced 1 major bug (delivery-exhaustion mislabeled internal_error) + 1 cosmetic nit (--check echo formula); both fixed inline (commits 375b081, a7b29ff) and re-verified live."
human_verification:
  - test: "Run the daemon with a deliberately-broken Discord webhook (invalid/unreachable URL) and let a scheduled slot fire (or use a near-future slot). Watch stderr/journald and query the alerts DB table."
    expected: "After the two-burst retry exhausts (or immediately on a 401/403), a CRITICAL `briefing_missed` structured log event appears on stderr/journald AND exactly one row is written to the `alerts` table for the (location, slot, local_date) — and a re-fire does not add a second alert row or emit a second event (no alert loop). Discord being down does not swallow this signal."
    why_human: "Success Criterion 2 is an end-to-end live-outage behavior. The codebase implements and unit-tests the out-of-band log+DB alert path (D-01/D-02 — a second webhook/email was deliberately rejected as not independent of a Discord outage), but the actual 'break Discord live → observe the alert out-of-band' flow needs a real run to confirm the journald/DB signal is what the operator will see."
  - test: "Start the daemon and leave it running for >10 minutes with no scheduled sends due. Query the `heartbeat` table (or watch for the periodic `heartbeat` log event)."
    expected: "The single heartbeat row's `last_tick_utc` advances on the ~600s IntervalTrigger cadence (and is stamped once at startup), independent of any send. After a successful send, `last_success_utc` is also stamped — so a monitor can distinguish a crashed process (stale last_tick) from one that is alive but failing to send (fresh last_tick, stale last_success)."
    why_human: "Success Criterion 4 (heartbeat/liveness) is a time-based runtime behavior over real wall-clock minutes. Unit tests stamp the row directly; confirming the periodic IntervalTrigger actually fires on cadence in a live daemon is a real-time observation grep cannot make."
  - test: "Configure a `[reliability]` section with an over-budget value (e.g. mid_pause_seconds = 5400) and run `weatherbot --check`; then set a valid budget and run `--check` again."
    expected: "An over-budget config fails loudly at load with the budget-exceeds-90-min-grace error and `--check` does not proceed to send. A valid config prints the resolved retry budget line (`retry budget: attempts_per_burst=… burst_spread_seconds=… mid_pause_seconds=… (approx total ~NN min)`) and exits 0 without sending."
    why_human: "Confirms the fail-loud config gate and the `--check` budget surface behave for a real operator editing the TOML; the automated tests cover the validator and the echo separately but a live `--check` run confirms the operator-facing message clarity."
---

# Phase 4: Retry-then-Alert Reliability Verification Report

**Phase Goal:** Transient fetch and send failures recover automatically without burning quota, a genuinely-failed briefing produces a visible out-of-band alert, the daemon distinguishes liveness from silence, and one bad run can never kill the loop.
**Verified:** 2026-06-11
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

> Note on mode: the phase is tagged `mode: mvp`, but the ROADMAP Phase-4 goal is an outcome statement, not a User Story (`As a … I want to … so that …`). The User-Story-narrowed MVP verification structure does not apply; this report verifies the four ROADMAP Success Criteria goal-backward against the codebase, which is the correct fallback.

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | A transient fetch/send failure is retried with bounded exponential backoff that honors `Retry-After`, while an auth failure (401/403) is never retried | ✓ VERIFIED | `reliability/retry.py`: `is_transient` (429/5xx/timeout/connect/read) + `is_auth_failure` (401/403); `two_burst_wait` honors a capped `Retry-After` from the failing 429 response (`parse_retry_after`, clamped to `RETRY_AFTER_CAP_S=120`); `build_retrying` uses `retry_if_exception(is_transient) | retry_if_result(not ok)` so 401/403 short-circuit. Tests: `test_is_transient_classification`, `test_is_auth_failure_classification`, `test_build_retrying_auth_not_retried`, `test_retry_after_capped`, `test_daemon_retry_after_honored`, `test_auth_no_retry`. |
| 2 | With Discord deliberately broken, the user still receives a "briefing missed" alert via a path independent of the failing primary channel, and the alert does not loop | ✓ VERIFIED (mechanism); live confirmation requested | `daemon.py` `fire_slot`: on exhausted transient / auth / internal-error it calls `record_alert(...)` (durable DB row) + a CRITICAL `briefing_missed` structlog event to stderr/journald — the documented out-of-band path (D-01/D-02; a second webhook/email was rejected as not independent of a Discord outage). `record_alert` is `INSERT OR IGNORE` on `UNIQUE(location_name, slot_time, local_date)` returning `rowcount==1`, so at most one alert/event per slot/day (anti-loop). Tests: `test_exhaustion_alerts`, `test_alert_dedup_no_loop` (asserts zero Discord calls + one alert across two fires). Live-outage observation routed to human verification. |
| 3 | An injected exception in one scheduled job is logged with a traceback and the scheduler keeps running — other jobs still fire | ✓ VERIFIED | `daemon.py` `fire_slot` broad `except Exception` releases the claim, writes a `reason=internal_error` alert, `_log.exception(...)` (full traceback), returns `None` so the APScheduler worker survives. Test `test_exception_isolation` asserts `first is None`, traceback + raised message in output, one `internal_error` alert, and a second independent slot still fires `ok=True`. |
| 4 | The bot emits a heartbeat/liveness signal (per successful run or daily) so a prolonged silence is distinguishable from a crash | ✓ VERIFIED (mechanism); live cadence confirmation requested | `daemon.py`: `_heartbeat_tick` on an `IntervalTrigger(seconds=600)` `__heartbeat__` job + a startup `stamp_tick` (IN-02 fix), independent of sends; `stamp_success` on eventual delivery. `store.py`: single seeded `heartbeat` row (`id=1`) with `last_tick_utc`/`last_success_utc` upserted in place. Tests: `test_heartbeat_upsert`, `test_heartbeat_job_registered_with_slots`, `test_resolve_on_eventual_success` (stamps last_success). Real-time cadence routed to human verification. |

**Score:** 4/4 truths verified (mechanism present, substantive, wired, and data-flowing). Two carry live runtime confirmations for the human (out-of-band-on-real-outage and heartbeat-on-real-cadence), which is why overall status is `human_needed`, not `passed`.

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `weatherbot/reliability/retry.py` | Two-burst builder, transient/auth classifiers, capped Retry-After parser honored at runtime, reason taxonomy | ✓ VERIFIED | All five functions present (`is_transient`, `is_auth_failure`, `parse_retry_after`, `two_burst_wait`, `build_retrying`); `sleep=stop_event.wait` (interruptible, no `time.sleep`); `parse_retry_after` called from `two_burst_wait`; no secret references. |
| `weatherbot/reliability/__init__.py` | Barrel re-exporting public retry surface | ✓ VERIFIED | Re-exports `build_retrying`, classifiers, `parse_retry_after`, three `REASON_*` constants in `__all__`. |
| `weatherbot/weather/store.py` | `alerts` + `heartbeat` tables; `record_alert`/`resolve_alert`/`stamp_tick`/`stamp_success` | ✓ VERIFIED | Both tables in `_SCHEMA` (alerts UNIQUE key, heartbeat seeded id=1 single row); all four helpers parameterized, schema-on-connect, secret-clean; `record_alert` returns `rowcount==1` dedup gate. |
| `weatherbot/config/models.py` | `Reliability` model attached to `Config`, fail-loud validated | ✓ VERIFIED | `class Reliability` (extra=forbid); `>0` validator + `attempts_per_burst>=2` validator (CR-01) + `_budget_under_grace` modeling the jittered worst case incl. `RETRY_AFTER_CAP_S` (WR-01/WR-02); `Config.reliability = Field(default_factory=Reliability)`. |
| `weatherbot/scheduler/daemon.py` | `fire_slot` two-burst retry + reason-taxonomy alerts + resolve/heartbeat; heartbeat IntervalTrigger; stop_event threaded | ✓ VERIFIED | `build_retrying(stop, …config.reliability…)`; three `record_alert` reason paths + `resolve_alert` + `stamp_success`; `_heartbeat_tick` on `__heartbeat__` IntervalTrigger; startup `stamp_tick`; `stop_event` created up front and threaded into live + catch-up fires. |
| `weatherbot/cli.py` | Manual `run_send_now` tight retry (no liveness rows); `--check` budget echo | ✓ VERIFIED | `run_send_now` uses `stop_after_attempt(3)` + `wait_exponential`; no `record_alert`/`stamp_*` in cli.py; `send_now` persists only on `result.ok` (WR-04 fix); `do_check` prints `config.reliability` budget. |
| `config.example.toml` | Documented `[reliability]` section | ✓ VERIFIED | Commented `[reliability]` block with attempts/spread/pause defaults + corrected ~75-min worst-case note. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `retry.py` | `tenacity.Retrying` | `build_retrying` returns configured `Retrying` | ✓ WIRED | tenacity declared in pyproject (`tenacity>=9.1.4`); imported and used. |
| `retry.py two_burst_wait` | `parse_retry_after` | wait callable reads failing 429 outcome | ✓ WIRED | `parse_retry_after(exc.response)` called inside `two_burst_wait`; `min(max(base, ra), CAP)`. |
| `retry.py` | `stop_event.wait` | `sleep=` interruptible pause | ✓ WIRED | `sleep=stop_event.wait`; no `time.sleep` in the engine. |
| `daemon.py fire_slot` | `reliability.build_retrying` | wraps `send_now` patient path | ✓ WIRED | `retrying(_attempt)`; fetch `HTTPStatusError` propagates untouched to the wait callable. |
| `daemon.py fire_slot` | `store.record_alert`/`resolve_alert`/`stamp_success` | reason-taxonomy alert + resolve/heartbeat | ✓ WIRED | All three reason branches + success-path resolve/stamp present. |
| `daemon.py run_daemon` | `store.stamp_tick` | IntervalTrigger heartbeat job + startup stamp | ✓ WIRED | `_heartbeat_tick` job registered; startup `stamp_tick` after `scheduler.start()`. |
| `config/models.py Config` | `Reliability` | `default_factory=Reliability` | ✓ WIRED | Existing configs with no `[reliability]` load unchanged. |
| `cli.py main (--send-now)` | `run_send_now` | tight `stop_after_attempt(3)` retry | ✓ WIRED | `--send-now` branch delegates; `send_now` stays single-attempt. |
| `cli.py do_check` | `config.reliability` | budget echo | ✓ WIRED | Prints attempts/spread/pause + approx total. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `alerts` table (via `record_alert`) | alert rows | real `INSERT OR IGNORE` from daemon failure paths | Yes (parameterized write, rowcount-gated) | ✓ FLOWING |
| `heartbeat` row (via `stamp_tick`/`stamp_success`) | `last_tick_utc`/`last_success_utc` | real `UPDATE` on seeded id=1 row | Yes | ✓ FLOWING |
| `Retry-After` honoring | wait seconds | parsed from the live failing 429 response header | Yes (capped at 120s) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full test suite passes | `uv run pytest -q` | 167 passed, 0 skipped | ✓ PASS |
| Lint clean | `uv run ruff check` | All checks passed | ✓ PASS |
| tenacity dependency present | `grep tenacity pyproject.toml` | `tenacity>=9.1.4` | ✓ PASS |
| Reliability barrel imports | (collected by suite) | `weatherbot/reliability/__init__.py` exports resolve | ✓ PASS |
| Live daemon out-of-band alert / heartbeat cadence | (requires running daemon + broken Discord over real time) | not run | ? SKIP → human verification |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist and no PLAN/SUMMARY declares probe-based verification; verification is by the pytest suite. Probe execution N/A for this phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| RELY-01 | 04-01, 04-03, 04-04 | Fetch + send retry with bounded exponential backoff on transient failure | ✓ SATISFIED | Two-burst builder (daemon) + tight bounded retry (manual); transient classifier; tests `test_transient_retries_then_succeeds`, `test_send_now_transient_then_success`. |
| RELY-02 | 04-01, 04-03 | Auth (401/403) never retried; honor `Retry-After` on rate limits | ✓ SATISFIED | `is_auth_failure` short-circuit + `parse_retry_after`/`two_burst_wait` honoring; tests `test_build_retrying_auth_not_retried`, `test_retry_after_capped`, `test_daemon_retry_after_honored`. |
| RELY-03 | 04-02, 04-03 | After retries, alert that a briefing was missed | ✓ SATISFIED | `record_alert(reason=transient_exhausted)` + CRITICAL log on exhaustion; test `test_exhaustion_alerts`. |
| RELY-04 | 04-02, 04-03 | Alert delivered out-of-band, independent of the failing channel; no loop | ✓ SATISFIED | Log+DB out-of-band path (D-01/D-02); `INSERT OR IGNORE` dedup; test `test_alert_dedup_no_loop` (zero Discord calls, one alert). Live-outage observation → human verification. |
| RELY-05 | 04-02, 04-03 | Heartbeat/liveness signal so silence ≠ crash | ✓ SATISFIED | `heartbeat` table + `_heartbeat_tick` IntervalTrigger + startup tick + `stamp_success`; tests `test_heartbeat_upsert`, `test_heartbeat_job_registered_with_slots`. |
| RELY-06 | 04-03 | Each job exception-isolated; one bad run can't kill the loop | ✓ SATISFIED | Hardened `except Exception` → release + internal_error alert + traceback + return None; test `test_exception_isolation` (second slot still fires). |

All 6 phase requirement IDs are declared across plan frontmatter and implemented. No orphaned requirements: REQUIREMENTS.md maps exactly RELY-01..06 to Phase 4, and every ID appears in at least one plan's `requirements` field.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| (none) | — | No `TBD`/`FIXME`/`XXX`/`HACK`/stub returns in any modified source file | — | The only "placeholder" grep hits in `cli.py` refer to Jinja template `{token}` placeholders, not code stubs (false positives). |

### Human Verification Required

See the three items in the frontmatter `human_verification` block:
1. **Live out-of-band alert on a broken Discord** — confirm the CRITICAL `briefing_missed` event + single `alerts` row appear when Discord is deliberately unreachable, and a re-fire does not loop (SC2 / RELY-03/04).
2. **Heartbeat cadence over real time** — confirm `last_tick_utc` advances on the ~600s interval (and at startup) independent of sends, and `last_success_utc` stamps on a real success (SC4 / RELY-05).
3. **`--check` fail-loud + budget echo** — confirm an over-budget `[reliability]` config fails loudly and a valid one prints the budget without sending (CONF-05-adjacent operator behavior, D-09).

### Gaps Summary

No gaps. All four Success Criteria are observably true in the codebase: the two-burst-with-honored-Retry-After retry engine, the auth-no-retry short-circuit, the durable + deduped out-of-band log/DB alert path, the exception-isolated `fire_slot`, and the periodic-plus-startup heartbeat are all present, substantive, wired into the daemon and CLI, and exercised by passing tests (167 passed, 0 skipped, ruff clean). The post-execution review's one blocker (CR-01 ZeroDivision on `attempts_per_burst=1`) and five warnings (WR-01..05: budget-guard understatement, Retry-After excluded from guard, before_sleep burst index, duplicate-persist-on-retry, malformed-HTTP-date crash) are all confirmed fixed in the actual code. The previously-flaky `test_retry_after_capped` was resolved by clamping the honored wait to the hard cap.

Status is `human_needed` rather than `passed` solely because two of the criteria (out-of-band alert under a real Discord outage, heartbeat cadence over real wall-clock) are runtime/external behaviors whose final confirmation belongs to a live daemon run — the automated layer for both is fully VERIFIED.

---

_Verified: 2026-06-11_
_Verifier: Claude (gsd-verifier)_
