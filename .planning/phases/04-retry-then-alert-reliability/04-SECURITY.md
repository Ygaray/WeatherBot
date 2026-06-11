# Phase 4 — Retry-Then-Alert-Reliability: Security Audit

**Audited:** 2026-06-11
**ASVS Level:** 1
**block_on:** high
**Result:** SECURED — 15/15 threats CLOSED (all `mitigate`)

Every declared mitigation was verified by locating the mitigation pattern in
implementation code (file:line), not by accepting SUMMARY attestations. The
register was authored at plan time (`register_authored_at_plan_time: true`); this
audit verified each listed disposition rather than scanning for new threats.

## Threat Verification

| Threat ID | Category | Disposition | Evidence (file:line) |
|-----------|----------|-------------|----------------------|
| T-04-SC | Tampering (supply chain) | mitigate | `pyproject.toml:13` `tenacity>=9.1.4`; `uv.lock:403-405` resolved tenacity 9.1.4 from pypi.org with sha256, source `github.com/jd/tenacity` (Apache-2.0) — human-verify checkpoint APPROVED per 04-01-SUMMARY (rejection path was the documented zero-dep fallback) |
| T-04-01 (P01) | Information Disclosure | mitigate | `weatherbot/reliability/retry.py` — `before_sleep` hook (`_before_sleep`, lines 212-222) logs only `attempt`/`burst`; secret grep `appid\|api.openweathermap.org\|webhook` returns nothing |
| T-04-DoS (P01) | Denial of Service | mitigate | `retry.py:67` `RETRY_AFTER_CAP_S=120`; `parse_retry_after` caps at line 130; `two_burst_wait` clamps honored value `min(max(base, ra), RETRY_AFTER_CAP_S)` line 174; `stop=stop_after_attempt(2*attempts_per_burst)` line 226 (=16 at defaults) |
| T-04-01 (P02) | Information Disclosure | mitigate | `weatherbot/weather/store.py` — `alerts`/`heartbeat` columns (lines 117-133) carry only location/slot/date/reason/severity/timestamps; `record_alert` binds only those (lines 348-353); test secret-leak greps `tests/test_store.py:256-257` |
| T-03-01 | Tampering (SQLi) | mitigate | `store.py` — all new INSERT/UPDATE parameterized `?`: `record_alert` 349-353, `resolve_alert` 374-379, `stamp_tick` 393-396, `stamp_success` 408-411; no f-string SQL |
| T-04-CFG | Tampering / DoS | mitigate | `weatherbot/config/models.py` `class Reliability` — positivity validator `_must_be_positive` line 160, `_attempts_at_least_two` line 167, under-90-min-grace `_budget_under_grace` (model_validator) lines 197-209; all `ValueError` at load |
| T-04-DB | Tampering (schema) | mitigate | `store.py:117` `CREATE TABLE IF NOT EXISTS alerts`, `store.py:129` `CREATE TABLE IF NOT EXISTS heartbeat` — additive only; existing `sent_log`/`weather_onecall` untouched |
| T-04-01 (P03) | Information Disclosure | mitigate | `weatherbot/scheduler/daemon.py` — `briefing_missed` (lines 205-212, 224-231, 247-254, 285-292) and `heartbeat` (line 314) emit flat outcome-only fields; secret grep matches only the module docstring (line 32), no secret in any new event |
| T-03-07 | Denial of Service | mitigate | `daemon.py:271` hardened `except Exception` → `release_claim` + `record_alert(internal_error)` + `_log.exception` (line 293, full traceback) + `return None` (line 298) so the APScheduler thread survives |
| T-04-DoS (P03) | Denial of Service | mitigate | `daemon.py:168-174` config-driven `build_retrying(stop, attempts_per_burst/burst_spread_s/mid_pause_s from config.reliability)`; `stop_event` threaded into live jobs (`_register_jobs` kwargs line 358) and catch-up (`_run_catchup` line 435); `sleep=stop_event.wait` at `retry.py:231` makes the pause interruptible |
| T-04-LOOP | Denial of Service | mitigate | `store.py:349` `INSERT OR IGNORE INTO alerts` + `return cur.rowcount == 1` (dedup); alert paths in `daemon.py` call only `record_alert`/`_log.critical` — no channel/Discord call (verified by `test_alert_dedup_no_loop`) |
| T-04-LOG | Tampering (log injection) | mitigate | `daemon.py` reasons are fixed constants `REASON_TRANSIENT_EXHAUSTED`/`REASON_AUTH_FAILED`/`REASON_INTERNAL_ERROR` (imported `retry.py:75-77`); location is config-validated; structlog renders flat kwargs (no format string) |
| T-04-01 (P04) | Information Disclosure | mitigate | `weatherbot/cli.py` — `do_check` budget echo prints only numeric `attempts_per_burst`/`burst_spread_seconds`/`mid_pause_seconds`/approx-min (lines 385-391); manual failure reports `status` / `type(exc).__name__` / `result.detail` only (lines 253-262) — no key/URL |
| T-04-NOISE | Tampering | mitigate | `cli.py` grep `record_alert\|stamp_tick\|stamp_success` returns NOTHING (manual path writes no liveness/alert rows, D-10); `test_send_now_no_liveness_rows` asserts zero rows |
| T-04-DoS (P04) | Denial of Service | mitigate | `cli.py:192` `_MANUAL_MAX_ATTEMPTS=3`; `run_send_now` builds `Retrying(stop=stop_after_attempt(_MANUAL_MAX_ATTEMPTS))` line 224 — manual path never runs the long two-burst schedule (`test_send_now_tight_retry_is_short_bound`) |

## Verification Commands Run

- `grep -nE "appid|api.openweathermap.org|webhook" weatherbot/reliability/retry.py` → no match (T-04-01 P01)
- `grep -n "time.sleep" weatherbot/reliability/retry.py` → no match (interruptible, D-07)
- `grep -n "parse_retry_after" weatherbot/reliability/retry.py` → called from `two_burst_wait` (live, not dead code)
- `grep -nE "appid|api.openweathermap.org|webhook|api_key" weatherbot/scheduler/daemon.py` → docstring only (T-04-01 P03)
- `grep -nE "_log.exception|exc_info=True" weatherbot/scheduler/daemon.py` → match line 293 (T-03-07 / D-12)
- `grep -nE "record_alert|stamp_tick|stamp_success" weatherbot/cli.py` → no match (T-04-NOISE)
- `grep -n "config.reliability" weatherbot/cli.py` → only inside `do_check` (T-04-01 P04 budget echo)
- `uv run pytest tests/test_reliability.py tests/test_store.py tests/test_config.py tests/test_cli.py -q` → 82 passed

## Unregistered Flags

None. All four plan SUMMARYs (`## Threat Surface`) attest "No new trust
boundaries beyond the plan's `<threat_model>`." No new attack surface appeared
during implementation that lacks a registered threat mapping.

## Notes (non-blocking)

- A documented timing-sensitive test (`tests/test_reliability.py::test_retry_after_capped`)
  can flake under heavy full-suite load (records ~121-127s against the 120s cap)
  per 04-02/04-03/04-04 deferred items. This is a TEST timing artifact, not a
  mitigation gap: the production cap `min(max(base, ra), RETRY_AFTER_CAP_S)`
  (`retry.py:174`) is a hard ceiling, and the targeted suite above passed
  deterministically (82 passed). It does not affect any T-04-DoS disposition.

## Accepted Risks Log

None declared for this phase. All 15 threats carry the `mitigate` disposition and
are CLOSED above.
