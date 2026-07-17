---
phase: 29-startup-validation-honest-alerting
plan: 04
subsystem: cli-daemon-boot
tags: [startup-validation, fatal-alert, secret-hygiene, tdd]
requires: [29-01, 29-03]
provides:
  - "run() offline boot-validate gate (HARD-STARTUP-01)"
  - "_fatal_config_exit single fatal path (HARD-STARTUP-02, D-08)"
affects: [weatherbot/cli.py]
tech-stack:
  added: []
  patterns:
    - "check-config↔run validator parity (identical 4-exception catch tuple, F05 guard)"
    - "best-effort operator alert that never masks the non-zero exit (T-29-11 DoS)"
    - "outcome-only detail (type(exc).__name__), never str(exc) (T-29-10 secret hygiene)"
key-files:
  created: []
  modified:
    - weatherbot/cli.py
    - tests/test_cli.py
decisions:
  - "run() replaces the thin _load_config_reporting load with the full validate_config_and_templates gate, matching check-config's validation depth exactly"
  - "_fatal_config_exit builds the channel from settings alone (no valid Config required) so it works when the config itself failed to load"
  - "fatal path loads settings best-effort; a missing secret still stamps health + returns 1"
metrics:
  duration: ~14min
  completed: 2026-07-07
  tasks: 2
  files: 2
status: complete
---

# Phase 29 Plan 04: run() Boot-Validate Fatal Gate Summary

Landed the PRIMARY offline fatal gate: `run()` now validates config + templates with the
same depth and the same exact 4-exception catch set as `check-config` before the scheduler
starts, and routes any failure through a single `_fatal_config_exit` helper that best-effort
alerts once, stamps the durable health row `CONFIG_INVALID`, and returns non-zero — a
misconfigured daemon can no longer green-boot and silently drop every briefing.

## What Was Built

- **`_fatal_config_exit(settings, reason, detail) -> int`** (weatherbot/cli.py) — the D-08 single
  fatal path. Best-effort builds a Discord channel from `settings` alone (no validated `Config`
  needed, since the fatal path may have no valid config), fires ONE operator alert wrapped in a
  swallow-all try/except, preps the DB dir, stamps `stamp_health(DEFAULT_DB_PATH, reason, detail)`
  so a later `!status` after a systemd restart reads the fatal reason from the DB (D-02), logs one
  outcome-only CRITICAL line, and returns `1`. The non-zero return is computed independently of
  alert success so a hung/failed send never masks or delays the exit (T-29-11).
- **`run` boot-validate gate** (weatherbot/cli.py) — replaced the thin
  `_load_config_reporting`→`load_config` load with `validate_config_and_templates(args.config)`
  wrapped in the EXACT same `(FileNotFoundError, tomllib.TOMLDecodeError, ValidationError,
  ValueError)` tuple `check-config` uses. On catch: best-effort `load_settings()` (a missing
  secret is tolerated → `settings=None`), then `return _fatal_config_exit(settings,
  reason=CONFIG_INVALID, detail=type(exc).__name__)`. On success, the branch proceeds unchanged to
  the module-provenance log / db-dir prep / `daemon.run_daemon(...)`.
- **Imports:** `CONFIG_INVALID` from `weatherbot.ops`; `stamp_health` from `weatherbot.weather.store`.

## RED→GREEN Transition (TDD)

- Added 4 new RED tests for `_fatal_config_exit` (returns-nonzero+stamps-once,
  swallows-send-failure, tolerates-None-settings, no-`str(exc)`-in-executable-body), committed as
  a failing `test(...)` gate, then made them green with the helper.
- **De-xfailed the 4 Wave-0 (29-01) boot-validate tests** now that the gate exists — removed the
  `xfail(strict=False)` markers from `test_run_boot_validate_rejects_duplicate_id`,
  `test_run_boot_template_rejects_missing_template`, the parametrized `test_check_run_parity`
  (valid/duplicate_id/bad_template), and `test_run_bad_config_exit_code` — so they are now strict
  green guards. The subprocess test shells out to `weatherbot run --config <bad>` and asserts a
  non-zero PROCESS exit code (systemd sees a failed boot, not a green one).

## Verification

- `uv run pytest tests/test_cli.py -k "fatal_config_exit"` → 4 passed.
- `uv run pytest tests/test_cli.py -k "run_boot_validate or run_boot_template or check_run_parity or run_bad_config_exit_code"` → 6 passed.
- `uv run pytest tests/test_cli.py` → 56 passed.
- **Full suite:** `uv run pytest` → 797 passed, 5 xfailed (all 29-05/29-06 items, out of scope), exit 0. The "2 snapshots failed" line is the known pre-existing syrupy noise (project memory) — exit code is 0, no golden diff.
- `uv run ruff check weatherbot/cli.py tests/test_cli.py` → all checks passed.
- Acceptance greps: `validate_config_and_templates` present in the `run` branch (cli.py:1031); `str(exc)` appears only in the `_fatal_config_exit` docstring, never in executable code; the `run` catch tuple is byte-identical to `check-config`'s.

## Threat Mitigations Applied

- **T-29-10 (Info Disclosure):** fatal alert/log `detail` is `type(exc).__name__`, never `str(exc)` — a config error's embedded filesystem path cannot leak. Enforced by an AST-based source test.
- **T-29-11 (DoS):** the best-effort `channel.send` is fully wrapped; the non-zero return is computed independent of send success, so a hung alert never blocks the exit.
- **T-29-12 (Elevation/lifecycle):** the full-validator gate + the parity test guarantee `run` rejects exactly what `check-config` rejects, closing F05 (no silent green boot).

## Deviations from Plan

None — plan executed as written. (Two of the new RED test assertions were tightened during the
GREEN step: `db.exists()`→`db.parent.exists()` since the stamp is monkeypatched to a no-op, and the
`str(exc)` source check was made AST-aware so the docstring's legitimate mention of the contract
doesn't trip it. Both are test-quality corrections, not behavior changes.)

## Constraints Honored

- No hub source touched (only `weatherbot/cli.py` + `tests/test_cli.py`).
- No live `systemctl`/daemon restart performed.

## Known Stubs

None.

## Self-Check: PASSED
- weatherbot/cli.py — FOUND (modified, `_fatal_config_exit` + run gate present)
- tests/test_cli.py — FOUND (4 new tests + 4 de-xfailed)
- Commits 585d67a, 3813d01, bcd65f6 — FOUND in git log
