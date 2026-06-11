---
phase: 4
slug: retry-then-alert-reliability
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-10
updated: 2026-06-12
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (dev dep) + time-machine 2.16 (clock control) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=["tests"], pythonpath=["."]) |
| **Quick run command** | `uv run pytest tests/test_reliability.py -q -x` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~5–15 seconds (tenacity `sleep=` is mocked; no real bursts/pauses) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_reliability.py -q -x` (plus the touched file's suite — test_store/test_config/test_cli)
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | RELY-01/02 | T-04-SC | tenacity install human-verified before it runs (supply chain) | manual+auto | `uv run python -c "import tenacity"` | ✅ (gate) | ⬜ pending |
| 04-01-02 | 01 | 1 | RELY-01/02 | T-04-01 / T-04-DoS | classifier short-circuits 401/403; Retry-After capped AND HONORED — `test_retry_after_capped` asserts build_retrying WAITS the capped value via recording-mock `sleep=` (parse_retry_after live, not dead); no secret in retry layer | unit | `uv run pytest tests/test_reliability.py -q -x` | ❌ W0 (this task creates it) | ⬜ pending |
| 04-01-03 | 01 | 1 | RELY-01..06 | — | Wave-0 scaffold names every behavior test | unit | `uv run pytest tests/test_reliability.py -q` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | RELY-03/04/05 | T-04-01 / T-03-01 / T-04-DB | dedup INSERT-OR-IGNORE; additive schema; parameterized `?`; no secret in rows | unit | `uv run pytest tests/test_store.py -q -x` | ✅ (extend) | ⬜ pending |
| 04-02-02 | 02 | 1 | RELY-03 (D-09) | T-04-CFG | malformed/over-grace retry config fails loud at load | unit | `uv run pytest tests/test_config.py -q -x` | ✅ (extend) | ⬜ pending |
| 04-03-01 | 03 | 2 | RELY-01/02/03/04/06 | T-04-01 / T-03-07 / T-04-LOOP / T-04-LOG | two-burst retry; reason-taxonomy deduped alert + CRITICAL log; internal_error + traceback, thread survives; no Discord double-retry | unit | `uv run pytest tests/test_reliability.py -q -x` | ❌ W0 (Plan 01 creates) | ⬜ pending |
| 04-03-02 | 03 | 2 | RELY-05 (D-04/05/06) | T-04-01 / T-04-DoS | periodic heartbeat tick (DB+log); stop_event threaded → interruptible 45-min pause | unit | `uv run pytest tests/test_reliability.py -q -x` | ❌ W0 | ⬜ pending |
| 04-04-01 | 04 | 2 | RELY-01 (D-09/10) | T-04-NOISE / T-04-DoS / T-04-01 | manual tight retry, terminal-only, NO alerts/heartbeat rows; --check surfaces budget | unit | `uv run pytest tests/test_cli.py -q -x` | ✅ (extend) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_reliability.py` — NEW file created by Plan 04-01 Task 3: real engine tests (`test_two_burst_wait_shape`, classifier, build_retrying 401/transient, AND `test_retry_after_capped` — asserts the schedule WAITS the capped Retry-After via recording-mock `sleep=`, honoring not just parsing) + skip-marked stubs named for every downstream behavior test (`test_transient_retries_then_succeeds`, `test_auth_no_retry`, `test_exhaustion_alerts`, `test_alert_dedup_no_loop`, `test_heartbeat_upsert`, `test_exception_isolation`, `test_pause_interruptible`). Plans 03/04 un-skip + fill.
- [ ] `uv add tenacity` — Plan 04-01 Task 1, gated behind a `checkpoint:human-verify` (Package Legitimacy Audit; slopcheck unavailable → `[ASSUMED]`). Fallback = hand-rolled `stop_event.wait` loop, zero new deps.
- [ ] Extend `tests/test_store.py` — Plan 04-02 (alerts/heartbeat helpers: record/resolve/dedup + stamp_tick/stamp_success).
- [ ] Extend `tests/test_config.py` — Plan 04-02 (`test_retry_config_validation`, D-09).
- [ ] Extend `tests/test_cli.py` — Plan 04-04 (`test_send_now_no_liveness_rows`, D-10).

> Existing infra (conftest `tmp_db`, `load_fixture`; time-machine) covers most needs. Technique: pass a recording mock as tenacity's `sleep=` so the two-burst shape runs in milliseconds; use `time-machine` for any wall-clock `stop_after_delay` assertion.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| tenacity package legitimacy | RELY-01 (supply chain) | A human must confirm the PyPI package/repo/history before the install runs (slopcheck unavailable) | Plan 04-01 Task 1 checkpoint: verify https://pypi.org/project/tenacity/ name/version/repo/history, then approve `uv add` |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (test_reliability.py is the sole new test file; created in Plan 01 before any consumer)
- [x] No watch-mode flags
- [x] Feedback latency < ~15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-11
