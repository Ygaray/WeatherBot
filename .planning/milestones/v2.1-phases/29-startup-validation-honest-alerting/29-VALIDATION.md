---
phase: 29
slug: startup-validation-honest-alerting
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-07
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `29-RESEARCH.md` § Validation Architecture. Per-task IDs are
> assigned by the planner; this file locks the framework, sampling cadence,
> Wave 0 gaps, and the manual/deferred items.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (+ pytest-cov 7.1.0) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`, `testpaths=["tests"]` |
| **Quick run command** | `uv run pytest tests/test_ops_selfcheck.py tests/test_cli.py tests/test_scheduler.py -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~20–40 seconds (full suite) |

> Suite note (project memory `[[pytest-snapshot-report-quirk]]`): the syrupy
> snapshot harness prints "N snapshots failed" but exits 0 on pre-existing
> noise — trust the exit code + any `.ambr` diff, not the printed line.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_ops_selfcheck.py tests/test_cli.py tests/test_scheduler.py -x -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~40 seconds

---

## Per-Task Verification Map

> Task IDs (`29-NN-NN`) are finalized by the planner. Coverage below is keyed by
> requirement so the planner can attach each to the task that implements it. Every
> row must resolve to an `<automated>` verify or a Wave 0 dependency.

| Requirement | Behavior | Test Type | Automated Command | File Status |
|-------------|----------|-----------|-------------------|-------------|
| HARD-STARTUP-01 | `run()` rejects a config with a duplicate id/name at boot (loudly, non-zero) | unit | `uv run pytest tests/test_cli.py -k "run_boot_validate" -x` | ❌ Wave 0 |
| HARD-STARTUP-01 | `run()` rejects a typo'd template token / missing template file at boot | unit | `uv run pytest tests/test_cli.py -k "run_boot_template" -x` | ❌ Wave 0 |
| HARD-STARTUP-01 | Parity: any config `check-config` accepts, `run` accepts; any it rejects, `run` rejects | property/parametrized | `uv run pytest tests/test_cli.py -k "check_run_parity" -x` | ❌ Wave 0 |
| HARD-STARTUP-02 | `run_self_check` classifies config/template/empty-loc error as `CONFIG_INVALID` (not `NETWORK_NOT_READY`) | unit | `uv run pytest tests/test_ops_selfcheck.py -k "config_invalid" -x` | ⚠️ extend existing |
| HARD-STARTUP-02 | `to_health_result` maps `CONFIG_INVALID`→`CRITICAL`; `AUTH_FAILED`→CRITICAL; `NETWORK_NOT_READY`→WARNING | unit | `uv run pytest tests/test_ops_selfcheck.py -k "severity" -x` | ⚠️ extend existing |
| HARD-STARTUP-02 | `AUTH_FAILED` remains NON-fatal (re-probes; marker NOT set) — D-03 regression guard | unit | `uv run pytest tests/test_scheduler.py -k "auth_not_fatal" -x` | ❌ Wave 0 |
| HARD-STARTUP-02 | `on_fail` on `CONFIG_INVALID` sets `fatal`+`stop`, `run_daemon` returns non-zero | unit | `uv run pytest tests/test_scheduler.py -k "fatal_exit_code" -x` | ❌ Wave 0 |
| HARD-STARTUP-02 | Clean SIGTERM (stop set, marker unset) → `run_daemon` returns 0 | unit | `uv run pytest tests/test_scheduler.py -k "clean_shutdown" -x` | ⚠️ near-existing (test_scheduler.py:636-655) |
| HARD-STARTUP-02 | End-to-end: `weatherbot run --config <bad.toml>` process exit code is non-zero + CRITICAL boot log | subprocess/integration | `uv run pytest tests/test_cli.py -k "run_bad_config_exit_code" -x` | ❌ Wave 0 |
| HARD-STARTUP-03 (F90) | `_announce_schedule` logs forecast slots incl. disabled ones with `next_run_time` | unit | `uv run pytest tests/test_scheduler.py -k "announce_forecast" -x` | ❌ Wave 0 |
| HARD-STARTUP-03 (F07) | Online ping fires strictly AFTER `notifier.ready()` (order recorded) | unit | `uv run pytest tests/test_scheduler.py -k "ping_after_ready" -x` | ⚠️ pattern exists (1015-1045) |
| HARD-STARTUP-03 (F89) | A reload removing/renaming a forecast slot prunes its streak entry | unit | `uv run pytest tests/test_reload.py -k "streak_prune" -x` | ❌ Wave 0 |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_cli.py` — boot-validate cases: duplicate id/name, typo'd template, missing template file, the `check-config`↔`run` **parity** property test, and one **subprocess** test asserting a non-zero **process** exit code for `weatherbot run --config <bad>` (the only true end-to-end exit-code proof) — covers HARD-STARTUP-01 + the SC-2 exit-code contract.
- [ ] `tests/test_ops_selfcheck.py` — add `CONFIG_INVALID` classification + severity-map cases (parametrized matrix over config-error / transient / auth); extends existing file.
- [ ] `tests/test_scheduler.py` — fatal-exit-code branch, clean-SIGTERM-returns-0, `AUTH_FAILED`-not-fatal regression (D-03), `announce_forecast` (F90), `ping_after_ready` (F07).
- [ ] `tests/test_reload.py` — streak-prune-on-reload (F89); file exists.
- [ ] A static `deploy/weatherbot.service` directive test — assert `Restart=on-failure`, `StartLimitIntervalSec`/`StartLimitBurst` in `[Unit]`, and STILL `TimeoutStartSec=infinity`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live crash-loop parks the systemd unit in `failed` (not infinite 5s restart + infinite alerts) on a fatal config error | HARD-STARTUP-02 (D-05/D-06) | Requires the real systemd unit on host `yahir-mint` after redeploy + `systemctl daemon-reload`; not reproducible in CI | Deferred **Gate-2** obligation: deploy the unit change, feed a known-bad config, confirm `systemctl status weatherbot` shows `failed` and start-limit hit; confirm exactly one Discord fatal alert. Batched to milestone-close human UAT. |

*Static file assertion (the `.service` directive test above) is automated and gates the phase; only the live restart behavior is deferred.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 40s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
