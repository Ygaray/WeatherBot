---
phase: 04-retry-then-alert-reliability
plan: 03
subsystem: scheduler (daemon patient path)
tags: [retry, alerts, heartbeat, reason-taxonomy, interruptible, daemon, RELY-01..06]
dependency_graph:
  requires:
    - "weatherbot.reliability.build_retrying / is_auth_failure / REASON_* (Plan 04-01)"
    - "weatherbot.weather.store.record_alert / resolve_alert / stamp_tick / stamp_success (Plan 04-02)"
    - "weatherbot.config.models.Config.reliability (Plan 04-02)"
    - "weatherbot.cli.send_now (single-attempt composition root, Phase 1-3)"
  provides:
    - "fire_slot daemon patient path: two-burst retry + reason-taxonomy alerts + resolve/stamp_success"
    - "fire_slot stop_event keyword (interruptible mid-pause, D-07)"
    - "daemon._heartbeat_tick + HEARTBEAT_INTERVAL_S=600 on an __heartbeat__ IntervalTrigger job"
    - "tests/test_reliability.py — 8 implemented daemon behavior tests (was 7 skip stubs)"
  affects:
    - "Plan 04-04 (manual tight path) reuses build_retrying with a different profile; send_now stays single-attempt"
tech_stack:
  added: []
  patterns:
    - "daemon-path retry locus in fire_slot (send_now stays single-attempt, Open Question 1)"
    - "retried callable lets the fetch httpx.HTTPStatusError propagate so the wait callable honors Retry-After"
    - "tenacity reraise=True → classify reraised exc (auth vs transient-exhausted) vs exhausted non-ok result"
    - "IntervalTrigger heartbeat job on the shared default threadpool (Pitfall 3)"
    - "stop_event created up front in run_daemon, threaded into live + catch-up fires"
key_files:
  created: []
  modified:
    - "weatherbot/scheduler/daemon.py"
    - "tests/test_reliability.py"
decisions:
  - "HEARTBEAT_INTERVAL_S=600 (~10 min, D-06 Claude's discretion) — well under any staleness alarm; same threadpool, never starves slots"
  - "stop_event threaded via the fire_slot kwargs dict (not a positional) + a stop_event param on _register_jobs/_run_catchup; created up front in run_daemon so the SAME instance reaches every fire"
  - "send_now stayed SINGLE-ATTEMPT — the retry locus is fire_slot's _attempt wrapper (Open Question 1 resolution, D-10)"
  - "Exhausted transient classified two ways: a reraised httpx transient/timeout exc OR a returned non-ok DeliveryResult both → reason=transient_exhausted"
metrics:
  duration_min: 9
  completed: 2026-06-11
  tasks: 2
  files: 2
requirements-completed: [RELY-01, RELY-02, RELY-03, RELY-04, RELY-05, RELY-06]
---

# Phase 4 Plan 03: Daemon Patient Path Summary

Wired the daemon's unattended reliability path end-to-end: `fire_slot` now runs `send_now` through Plan 01's two-burst retry (config-driven, SIGTERM-interruptible), classifies every outcome into the `REASON_*` taxonomy with a deduped durable alert + CRITICAL `briefing_missed` log, resolves the alert and stamps heartbeat success on eventual delivery, survives unexpected exceptions with a full traceback + `internal_error` alert, and emits a periodic heartbeat tick on its own `IntervalTrigger` job.

## What Was Built

### Task 1 — `fire_slot` patient retry + reason-taxonomy alerts + resolve/stamp + hardened isolation
- Imported `build_retrying`, `is_auth_failure`, `REASON_TRANSIENT_EXHAUSTED/AUTH_FAILED/INTERNAL_ERROR` from `weatherbot.reliability` and `record_alert`/`resolve_alert`/`stamp_success`/`stamp_tick` from `weatherbot.weather.store`.
- Added a `stop_event=None` keyword to `fire_slot`. Built the retry from `config.reliability` (D-09): `build_retrying(stop, attempts_per_burst=…, burst_spread_s=…, mid_pause_s=…)`. When `stop_event` is `None` (a standalone/test fire), a fresh never-set `threading.Event()` is used so the schedule still runs.
- The existing single-attempt `send_now(...)` call is wrapped in an inner `_attempt()` callable and run THROUGH `retrying(_attempt)` — the daemon patient path. `send_now` is unchanged (stays the retry-agnostic shared composition root, Open Question 1 / D-10).
- **Retry-After propagation:** `_attempt` lets the fetch `httpx.HTTPStatusError` (carrying `.response` with the `Retry-After` header) propagate untouched, so Plan 01's `two_burst_wait` reads it from `retry_state.outcome` and honors the capped value on the daemon path (RELY-02).
- Outcome classification:
  - **Success** (`result.ok`): keep the claim, `resolve_alert(...)` (D-13), `stamp_success(...)` (D-04/D-05), `_log.info("slot fired", …)`.
  - **Reraised `httpx.HTTPStatusError`**: `release_claim`, then `reason = auth_failed` when `is_auth_failure(exc)` else `transient_exhausted`; `record_alert(...)` + (if first this slot/day) a CRITICAL `briefing_missed` log.
  - **Reraised transient network error** (`TimeoutException/ConnectError/ReadError`, exhausted): `release_claim` + `record_alert(reason=transient_exhausted)` + CRITICAL log.
  - **Exhausted non-ok `DeliveryResult`** (a persistent delivery failure that never raised, e.g. a Discord non-2xx): `release_claim` + `record_alert(reason=transient_exhausted)` + CRITICAL log. No second Discord retry (channel owns its own within-attempt 429 wait, D-02 / Pitfall 2).
  - **Hardened `except Exception`** (D-12 / RELY-06): release a won claim, `record_alert(reason=internal_error)` + CRITICAL log, `_log.exception(...)` for the FULL traceback, return `None` so the APScheduler worker thread survives.
- Every `briefing_missed` event carries flat outcome-only fields (`location`, `slot`, `local_date`, `reason`, `severity`) — never a secret (T-04-01).

### Task 2 — periodic heartbeat tick + stop_event threading
- `HEARTBEAT_INTERVAL_S = 600` module constant. `def _heartbeat_tick(db_path)` calls `stamp_tick(db_path)` and emits `_log.info("heartbeat", last_tick=<epoch>)` (stable key, flat field, secret-free).
- `run_daemon` creates the `stop` Event UP FRONT, then registers the heartbeat on its own job: `scheduler.add_job(_heartbeat_tick, trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S), kwargs={"db_path": db_path}, id="__heartbeat__", misfire_grace_time=None, coalesce=True)`. It runs on the same default threadpool (`max_workers=10`) and never starves slot jobs at a personal-bot slot count (Pitfall 3, noted in a comment).
- The SAME `stop` Event is threaded into every fire: a `stop_event` param added to `_register_jobs` (placed in the `fire_slot` kwargs dict) and to `_run_catchup` (catch-up fires are also daemon-path). So a SIGTERM during the 45-min mid-pause aborts the in-progress retry cleanly (D-07 / Pitfall 1). The existing SIGTERM handler + `scheduler.shutdown(wait=False)` finally block are unchanged.

## Output-Spec Answers (per plan `<output>`)
- **HEARTBEAT_INTERVAL_S:** 600 seconds (~10 min).
- **How stop_event is threaded:** created up front in `run_daemon`; passed as a `stop_event` keyword param to `_register_jobs` (which puts it in the per-job `kwargs` dict) and to `_run_catchup` (which forwards it to each catch-up `fire_slot`). It is the SAME instance whose `.wait` is Plan 01's `sleep=` source.
- **send_now stayed single-attempt:** confirmed — the retry locus is `fire_slot`'s `_attempt` wrapper run through `retrying(...)`; `weatherbot/cli.py:send_now` was not modified.
- **Fetch HTTPStatusError reaches the wait callable:** confirmed by `test_daemon_retry_after_honored` — a 429 with `Retry-After: 9999` then success records exactly one wait that honors the capped value (`>= RETRY_AFTER_CAP_S`), proving the header-carrying exception is not swallowed inside `_attempt`.

## Verification
- `uv run pytest tests/test_reliability.py -q` → 20 passed (12 engine + 8 daemon behavior tests; the 7 prior skip stubs are now implemented + 1 registration test).
- `uv run pytest -q` → 157 passed, 0 skipped (no Phase 1-3 regression; claim/release/catch-up intact).
- `uv run ruff check weatherbot/scheduler/daemon.py tests/test_reliability.py` → All checks passed.
- Acceptance greps all match: `build_retrying(`, three `record_alert(` reason paths, `resolve_alert(`, `stamp_success(`, `_log.exception`, `IntervalTrigger`, `stamp_tick`, `__heartbeat__`/`HEARTBEAT_INTERVAL_S`/`def _heartbeat_tick`, `stop_event` (10 occurrences).
- Secret hygiene: `grep -nE "appid|api.openweathermap.org|webhook|api_key" weatherbot/scheduler/daemon.py` matches only the pre-existing module docstring stating it never logs the key/URL — no secret in any new event; the `briefing_missed`/`heartbeat` tests grep captured output for `appid`/host and assert absent.

## Behavior Coverage (RELY-01..06 + D-07/D-13)
- `test_transient_retries_then_succeeds` — RELY-01 (transient retries, succeeds, no alert, stamps success)
- `test_auth_no_retry` — RELY-02 (401 single attempt, reason=auth_failed)
- `test_exhaustion_alerts` — RELY-03 (always-transient → exactly one transient_exhausted alert + CRITICAL log, slot released)
- `test_daemon_retry_after_honored` — RELY-02 (daemon-path Retry-After honored, header propagates to the wait callable)
- `test_alert_dedup_no_loop` — RELY-04 (two exhausted fires → one alert; zero Discord calls)
- `test_heartbeat_upsert` + `test_heartbeat_job_registered_with_slots` — RELY-05 (tick stamps last_tick + event; `__heartbeat__` job coexists with slot jobs)
- `test_exception_isolation` — RELY-06 (ValueError → internal_error alert + full traceback + returns None; a second slot still fires)
- `test_resolve_on_eventual_success` — D-13 (a later success resolves the prior alert + stamps success)
- `test_pause_interruptible` — D-07 (set stop_event → mid-pause abandons in < 1s)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Behavior-test log assertions used `caplog`, but structlog renders to stdout (not stdlib logging)**
- **Found during:** Task 1 (GREEN run)
- **Issue:** The project never configures structlog, so `structlog.get_logger` uses the lazy default `PrintLoggerFactory` that writes to stdout — it does NOT route through stdlib `logging`. `caplog.records` was therefore empty, so the `briefing_missed`/`heartbeat`/traceback assertions failed (`assert False`).
- **Fix:** Switched those three tests (`test_exhaustion_alerts`, `test_heartbeat_upsert`, `test_exception_isolation`) from `caplog` to `capsys`, asserting the event key / `transient_exhausted` / `Traceback` + raised-message text appear in captured stdout+stderr and that no secret token is present. No production-code change; the events are emitted exactly as specified.
- **Files modified:** tests/test_reliability.py
- **Commit:** 8debaaa

**2. [Rule 1 - Bug] `test_daemon_retry_after_honored` asserted `== RETRY_AFTER_CAP_S`, which flakes under jitter**
- **Found during:** Task 2 (full-file run)
- **Issue:** `two_burst_wait` returns `max(base, capped_retry_after)`; the within-burst `base` (`step ≈ 85.7s` + up to ~42.8s jitter) can exceed the 120s cap, so an exact equality to the cap intermittently failed (same latent shape as Plan 01's `test_retry_after_capped`).
- **Fix:** Asserted the single recorded wait HONORS the cap (`len == 1` and `>= RETRY_AFTER_CAP_S`) — the honoring guarantee is "wait at least the capped value", which holds deterministically. Verified stable across 5 isolated runs.
- **Files modified:** tests/test_reliability.py
- **Commit:** 8debaaa

## Deferred Issues (out of scope — pre-existing)
- `tests/test_reliability.py::test_retry_after_capped` (Plan 04-01's engine test) is the documented timing-flaky test: under heavy full-suite load its HTTP-date Retry-After parse can record ~123s against the 120s cap. It passes in isolation (confirmed) and touches none of this plan's files. Not fixed (scope boundary — belongs to Plan 04-01's engine; suggested fix logged in 04-02's deferred items: inject a frozen clock into the HTTP-date parse path). It passed in this plan's final full-suite run.

## Threat Surface
No new trust boundaries beyond the plan's `<threat_model>`. T-04-01 mitigated (flat outcome-only `briefing_missed`/`heartbeat` fields; secret-leak greps in the behavior tests). T-03-07 / RELY-06 mitigated (hardened `except Exception` returns None + alerts; thread survives). T-04-DoS mitigated (config-driven bounded two-burst budget; capped Retry-After from Plan 01; `sleep=stop_event.wait` interruptible). T-04-LOOP mitigated (`record_alert` INSERT-OR-IGNORE dedup; alert path never touches Discord — `test_alert_dedup_no_loop` asserts zero channel calls). T-04-LOG mitigated (reason strings are fixed Plan-01 constants; structlog renders flat kwargs).

## Commits
- 7c45e85 — test(04-03): add failing daemon patient-path + heartbeat tests (RED)
- 8debaaa — feat(04-03): wire daemon patient retry, reason-taxonomy alerts, heartbeat (GREEN)

## TDD Gate Compliance
RED → GREEN followed: the failing tests were authored and committed first (`7c45e85`, RED — `TypeError: fire_slot() got an unexpected keyword argument 'stop_event'`), then the daemon implementation made them pass (`8debaaa`, GREEN — 20 passed). Tasks 1 and 2 share `weatherbot/scheduler/daemon.py`, so their implementations were committed together as the single cohesive GREEN change; both tasks' behaviors are covered by the green suite. No REFACTOR commit needed. No test passed unexpectedly during RED.

## Self-Check: PASSED
