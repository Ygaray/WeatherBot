---
phase: 04-retry-then-alert-reliability
plan: 04
subsystem: cli (manual attended retry path)
tags: [retry, manual-path, terminal-only, check-budget, D-10, D-09, RELY-01]
dependency_graph:
  requires:
    - "weatherbot.reliability.is_transient (Plan 04-01)"
    - "weatherbot.config.models.Config.reliability (Plan 04-02)"
    - "weatherbot.cli.send_now (single-attempt composition root, Phase 1-3)"
    - "tenacity.Retrying / stop_after_attempt / wait_exponential / retry_if_result / retry_if_exception"
  provides:
    - "weatherbot.cli.run_send_now — the manual tight-retry wrapper (terminal-only, NO liveness rows)"
    - "main --send-now branch delegates to run_send_now (send_now stays single-attempt)"
    - "do_check retry-budget echo (attempts/spread/pause + approx total minutes, D-09)"
  affects:
    - "Phase 4 is complete after this plan — the daemon-vs-manual split (D-10) is now wired on BOTH halves"
tech_stack:
  added: []
  patterns:
    - "manual-path retry locus in run_send_now (send_now stays single-attempt, Open Question 1)"
    - "SHORT bounded Retrying (stop_after_attempt(3), wait_exponential cap 10s) — NOT the daemon two-burst"
    - "reraise=True (exception exhaustion) + retry_error_callback=last-result (non-ok DeliveryResult exhaustion)"
    - "patchable sleep=time.sleep seam so the bound runs in ms under test"
    - "do_check additive budget echo via print() (deterministic terminal output, numeric-only)"
key_files:
  created: []
  modified:
    - "weatherbot/cli.py"
    - "tests/test_cli.py"
decisions:
  - "Manual tight bound = stop_after_attempt(3) + wait_exponential(multiplier=1, max=10) — at most 3 attempts (D-10), deliberately NOT the ~65-min two-burst"
  - "reraise=True handles the exhausted/permanent EXCEPTION path (reported via the except blocks); retry_error_callback returns the last DeliveryResult so an exhausted NON-OK result reports its detail (not a wrapped RetryError)"
  - "Manual failure reports OUTCOME-ONLY to the terminal: result.detail, or exc status code / exception type name — never the key/URL (T-04-01)"
  - "--check budget echo uses print() (not _log.info) so the budget is deterministic user-facing terminal output regardless of structlog config"
metrics:
  duration_min: 4
  completed: 2026-06-11
  tasks: 1
  files: 2
requirements-completed: [RELY-01]
---

# Phase 4 Plan 04: Manual Tight-Retry Path Summary

Wired the ATTENDED half of the daemon-vs-manual reliability split (D-10): a new `run_send_now` wraps the single-attempt `send_now` composition root in a SHORT bounded `Retrying` so a transient `--send-now` blip recovers in seconds, reports any final failure straight to the terminal (exit 1), and writes NO `alerts`/`heartbeat` rows — those liveness concerns belong only to the unattended daemon. `--check` now surfaces the resolved retry budget (D-09) so a mis-tuned `[reliability]` section is visible without sending. This completes Phase 4.

## What Was Built

### Task 1 — manual `run_send_now` tight retry + `do_check` budget surface (TDD)
- **`run_send_now(location_name, *, config, db_path, settings, client, channel, templates_dir)` → int** — the manual tight-retry wrapper. Builds a tight `Retrying(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10), retry=(retry_if_result(lambda r: not r.ok) | retry_if_exception(is_transient)), reraise=True, retry_error_callback=lambda rs: rs.outcome.result(), sleep=time.sleep)` and runs `send_now` through it.
  - `reraise=True` → an exhausted/permanent **exception** (a `transient_exhausted` fetch/network error, or a permanent auth/4xx, which `is_transient` rejects so it is reraised at once) propagates to the `except httpx.HTTPStatusError` / `except (TimeoutException|ConnectError|ReadError)` blocks, which log the **outcome only** (status code / exception type name — never the key/URL) and return exit 1.
  - `retry_error_callback=lambda rs: rs.outcome.result()` → an exhausted **non-ok `DeliveryResult`** (a persistent delivery failure that never raised, e.g. Discord non-2xx) is returned as the last result rather than wrapped in a `RetryError`, so the existing terminal report path (`_log.error("briefing delivery failed", detail=result.detail)`, exit 1) fires.
  - On (eventual) success → `_log.info("briefing delivered")`, exit 0.
  - `sleep=time.sleep` is an explicit patchable seam — tests `monkeypatch` `weatherbot.cli.time.sleep` so the bound runs in milliseconds.
- **`main`'s `--send-now` branch** now delegates to `return run_send_now(args.send_now, config=config, db_path=db_path, settings=settings)` instead of calling `send_now` inline. `send_now`'s body is unchanged — it stays the single-attempt shared composition root (Open Question 1 / D-10); the retry locus lives in `run_send_now`, mirroring the daemon's `fire_slot` locus.
- **No liveness writes (D-10 / Pitfall 4):** `run_send_now` never calls `record_alert`, `stamp_tick`, or `stamp_success` — `grep -nE "record_alert|stamp_tick|stamp_success" weatherbot/cli.py` returns nothing. `send_now` already only `persist`s weather data; the wrapper adds no liveness write. A failed manual send leaves zero `alerts` rows and a heartbeat row whose `last_tick_utc`/`last_success_utc` are both still NULL.
- **`do_check` budget echo (D-09):** after the four existing ordered validation steps and the "nothing delivered" guard, `do_check` now prints the resolved budget from `config.reliability` (the only `config.reliability` reference in `cli.py`, inside `do_check`). The 401/403 subscription-not-active message is unchanged; the echo is additive and sends nothing.

## Output-Spec Answers (per plan `<output>`)
- **Manual tight-retry bound chosen:** `stop_after_attempt(3)` (module constant `_MANUAL_MAX_ATTEMPTS = 3`) + `wait_exponential(multiplier=1, max=10)` — at most 3 attempts with a brief capped backoff. Deliberately NOT the daemon's `2 * attempts_per_burst` two-burst schedule.
- **Confirmation no liveness write exists on the manual path:** confirmed — `grep -nE "record_alert|stamp_tick|stamp_success" weatherbot/cli.py` returns nothing; `test_send_now_no_liveness_rows` asserts zero `alerts` rows and both heartbeat stamps still NULL after a failed manual send.
- **Exact `--check` budget output format** (a single line to stdout):
  ```
  retry budget: attempts_per_burst=8 burst_spread_seconds=600 mid_pause_seconds=2700 (approx total ~65 min)
  ```
  (approx total = `(2*burst_spread_seconds + mid_pause_seconds)/60`, rounded to whole minutes.)

## Verification
- `uv run pytest tests/test_cli.py -q` → 19 passed (15 prior + 4 new).
- `uv run pytest -q` → 160 passed, 1 failed — the single failure is the documented pre-existing `tests/test_reliability.py::test_retry_after_capped` timing flake (Plan 04-01 engine; logged in deferred-items.md). It passes in isolation (confirmed: `1 passed in 0.25s`) and touches none of this plan's files. All of this plan's tests pass deterministically.
- `uv run ruff check weatherbot/cli.py tests/test_cli.py` → All checks passed.
- Acceptance greps: `record_alert|stamp_tick|stamp_success` in `cli.py` → NONE (D-10 negative guarantee); `config.reliability` → matches only inside `do_check` (D-09); no `Retrying`/`build_retrying` inside the `send_now` function body (retry locus stays in `run_send_now`).

## Behavior Coverage (RELY-01 manual half + D-10 + D-09)
- `test_send_now_no_liveness_rows` — D-10 / Pitfall 4: a manual send failing after the tight retry writes ZERO `alerts` and ZERO heartbeat stamps and returns exit 1 with the terminal detail report.
- `test_send_now_transient_then_success` — RELY-01 manual half: a 429 blip on attempt 1 then success returns exit 0 via the tight retry, still no liveness rows.
- `test_send_now_tight_retry_is_short_bound` — T-04-DoS: an always-transient send attempts at most 3 times (the SHORT bound, not the 16-attempt two-burst).
- `test_check_surfaces_retry_budget` — D-09: `do_check` returns 0 and its stdout includes the resolved budget values (8 / 600 / 2700).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `reraise=True` alone wrapped an exhausted non-ok DeliveryResult in a `RetryError`**
- **Found during:** Task 1 (GREEN run)
- **Issue:** With only `reraise=True`, tenacity reraises the *exception* on exception-exhaustion, but a result-based retry that exhausts on a non-ok `DeliveryResult` (no exception ever raised) is wrapped in a `tenacity.RetryError` instead of returning the result — so the terminal `detail` report path never ran and the call raised.
- **Fix:** Added `retry_error_callback=lambda rs: rs.outcome.result()` so an exhausted non-ok result is returned as the last `DeliveryResult`; the `if result.ok` branch then reports its `detail` and returns exit 1. Exception-exhaustion still reraises (handled by the `except` blocks). No behavior change to the success/transient paths.
- **Files modified:** weatherbot/cli.py
- **Commit:** af1f03a

**2. [Rule 1 - Bug] Test helper indexed a sqlite3 tuple row by column name**
- **Found during:** Task 1 (GREEN run)
- **Issue:** `_heartbeat_row` used `hb["last_tick_utc"]`, but the test's `sqlite3.connect` has no `row_factory`, so rows are plain tuples → `TypeError: tuple indices must be integers or slices, not str`. Test-only defect; production code was already correct (the failed send wrote no liveness rows).
- **Fix:** Replaced with `_heartbeat_stamps` selecting `(last_tick_utc, last_success_utc)` explicitly and unpacking the tuple; assert both are NULL.
- **Files modified:** tests/test_cli.py
- **Commit:** af1f03a

## Deferred Issues (out of scope — pre-existing)
- `tests/test_reliability.py::test_retry_after_capped` — the documented Plan 04-01 engine timing flake (HTTP-date Retry-After parse can record ~123-127s against the 120s cap under heavy full-suite load). Already logged in `deferred-items.md` by Plan 04-03. Passes in isolation; touches none of this plan's files; out of scope per the scope boundary.

## Threat Surface
No new trust boundaries beyond the plan's `<threat_model>`.
- **T-04-01 (Information Disclosure)** mitigated: the `--check` budget echo prints only numeric `[reliability]` fields; the manual failure report logs `detail` / a status code / an exception type name only — no key/URL/`appid`.
- **T-04-NOISE (Tampering)** mitigated: grep gate confirms no `record_alert`/`stamp_*` in `cli.py`; `test_send_now_no_liveness_rows` asserts zero `alerts` rows and both heartbeat stamps NULL after a manual failure.
- **T-04-DoS (Denial of Service)** mitigated: `stop_after_attempt(3)` bounds the manual retry — it never runs the daemon's long patient schedule (`test_send_now_tight_retry_is_short_bound`).

## Commits
- 5b9f607 — test(04-04): add failing manual tight-retry + --check budget tests (RED)
- af1f03a — feat(04-04): manual --send-now tight retry + --check budget surface (GREEN)

## TDD Gate Compliance
RED → GREEN followed: the failing tests were authored and committed first (`5b9f607`, RED — `ImportError: cannot import name 'run_send_now'`), then the implementation made them pass (`af1f03a`, GREEN — 19 passed in test_cli.py). No test passed unexpectedly during RED. The single behavior task carries both new functions (manual retry + budget echo), so its implementation is one cohesive GREEN commit. No REFACTOR commit needed.

## Self-Check: PASSED
