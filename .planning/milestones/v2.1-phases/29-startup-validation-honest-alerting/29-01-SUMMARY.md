---
phase: 29-startup-validation-honest-alerting
plan: 01
subsystem: tests
tags: [tdd-red, wave-0, boot-validate, selfcheck, config-invalid]
status: complete
requires:
  - "weatherbot.ops.run_self_check / to_health_result (existing classifier)"
  - "weatherbot.cli.main run/check-config dispatch (existing)"
provides:
  - "RED test contract for HARD-STARTUP-01 (run boot-validate parity + subprocess exit-code)"
  - "RED test contract for HARD-STARTUP-02 (CONFIG_INVALID classification + CRITICAL severity map)"
affects:
  - "tests/test_cli.py"
  - "tests/test_ops_selfcheck.py"
tech-stack:
  added: []
  patterns:
    - "pytest.mark.xfail(strict=False) for impl-lands-later Wave-0 tests"
    - "guarded try/except import for a symbol added in a downstream plan (CONFIG_INVALID)"
    - "subprocess end-to-end process-exit-code test (first in the CLI suite)"
key-files:
  created: []
  modified:
    - "tests/test_cli.py (+148)"
    - "tests/test_ops_selfcheck.py (+114)"
decisions:
  - "Assert CONFIG_INVALID detail is a bare class identifier (isidentifier() + no '/' + no bad token) rather than guessing the exact exception class — pins the T-29-01 hygiene contract without over-coupling to 29-03's catch-tuple choice."
  - "Parity test asserts accept/reject equivalence ((rc==0)==(rc==0)), not exact-code equality, so it survives run and check-config returning different non-zero codes."
metrics:
  duration: ~10m
  completed: 2026-07-07
  tasks: 2
  files: 2
  lines_added: 262
---

# Phase 29 Plan 01: Wave 0 Test Scaffolding (Boot-Validate + Selfcheck Classification) Summary

RED tests-first scaffolding that locks the observable contract for the offline boot-validate fatal gate (HARD-STARTUP-01) and the CONFIG_INVALID defense-in-depth classifier (HARD-STARTUP-02) before any production code lands in Waves 1-2 (plans 29-03/04). Test files only; every impl-dependent assertion is xfail(strict=False) and fails for the right reason (missing gate / missing symbol), not on a collection or import error.

## What Was Built

### Task 1 — `tests/test_cli.py` (HARD-STARTUP-01)
Four tests + two config-file fixtures (`_dup_id_config_file`, `_bad_template_config_file`) built in the existing `_good_config_file` shape:
- `test_run_boot_validate_rejects_duplicate_id` — `run` must reject a duplicate-name config with a non-zero exit and never reach the daemon (sentinel-monkeypatched `run_daemon` proves the gate fires first).
- `test_run_boot_template_rejects_missing_template` — missing template token rejected at boot.
- `test_check_run_parity` (parametrized: valid / duplicate_id / bad_template) — the strongest F05 guard: `check-config` and `run` boot-validate produce identical accept/reject on the same config.
- `test_run_bad_config_exit_code` — the ONE true end-to-end proof: `python -m weatherbot run --config <bad>` as a real subprocess returns a non-zero PROCESS exit code (asserts `returncode`, never stdout). Genuinely new scaffolding (no prior subprocess CLI test).

All four xfail(strict=False) until the `run` boot-validate gate + `_fatal_config_exit` land in 29-04.

### Task 2 — `tests/test_ops_selfcheck.py` (HARD-STARTUP-02)
A classification matrix + severity-map extending the existing `_config` / `_OkClient` / `_RaisingClient` / `_http_status_error` scaffolding:
- `test_config_invalid_on_bad_template`, `test_config_invalid_on_empty_locations` → `reason == CONFIG_INVALID`; `detail` asserted as a bare class identifier (no `/`, no `__does_not_exist__` token) — the T-29-01 / T-04-01 no-path/no-secret contract. Probe never reached (asserted).
- `test_connect_error_still_network_not_ready`, `test_401_still_auth_failed` → D-03 regression guards; these stay GREEN today, pinning that the new pre-probe split does not shadow the existing network/auth branches.
- `test_severity_map` (parametrized) → CONFIG_INVALID/AUTH_FAILED → CRITICAL, NETWORK_NOT_READY → WARNING.

`CONFIG_INVALID` is imported through a guarded try/except (added to `weatherbot.ops` in 29-03) with a sentinel-string fallback so the file collects pre-impl; the dependent cases carry a conditional xfail marker.

## Verification / Self-UAT (Gate 1)

| Criterion | Command | Evidence | Verdict |
|-----------|---------|----------|---------|
| Task 1 tests collect + run, no collection error | `pytest test_cli.py -k "run_boot..."` | 5 xfailed, 1 xpassed | PASS |
| Task 2 tests collect + run, no ImportError | `pytest test_ops_selfcheck.py -k "config_invalid or severity..."` | 8 passed, 3 xfailed, 2 xpassed | PASS |
| New tests are RED for the right reason (missing impl, not a test typo) | full suite | xfail reasons cite 29-03/29-04 missing gate/symbol | PASS |
| D-03 guards stay green (no regression) | full suite | `connect_error_still_network_not_ready` + `401_still_auth_failed` pass | PASS |
| Pre-existing suite unbroken | `uv run pytest -q` | **778 passed**, 8 xfailed, 3 xpassed, **exit 0** | PASS |

Suite quirk (project memory): the printed "2 snapshots failed" is pre-existing syrupy noise — the process exit code was 0. Trusted the exit code per the pytest snapshot-report quirk memory.

## RED Contract Compliance

This is a tests-first (Wave 0) plan — the RED state IS success. No production `weatherbot/**` file was touched; the impl (the `run` gate, `_fatal_config_exit`, the `CONFIG_INVALID` reason + CRITICAL map) lands in 29-03/04/05. The xfails fail on the intended missing symbol/behavior, verified by their xfail reason strings, not on import/collection errors.

## Deviations from Plan

- **[Rule 1 - test-precision] CONFIG_INVALID `detail` assertion tightened.** The plan said assert `detail == type(exc).__name__`. Because 29-03 chooses the exact caught exception class (`ValueError`/`FileNotFoundError`/template error), pinning a specific class name would over-couple this RED test to an unmade implementation choice. Asserted the observable hygiene contract instead — `detail.isidentifier()` AND no `/` AND no `__does_not_exist__` token — which is exactly what T-29-01 requires (a bare class name, never `str(exc)` with a path). Same guarantee, no premature coupling. Files: `tests/test_ops_selfcheck.py`. Commit: ddea053.

No architectural changes. No auth gates. No package installs.

## Known Stubs

None. These are intentionally-RED contract tests, not stubs; they will turn green when 29-03/04 land.

## Self-Check: PASSED
- FOUND: tests/test_cli.py (Task 1 tests present)
- FOUND: tests/test_ops_selfcheck.py (Task 2 tests present)
- FOUND: .planning/phases/29-startup-validation-honest-alerting/29-01-SUMMARY.md
- FOUND commit 8384cdd (Task 1)
- FOUND commit ddea053 (Task 2)
