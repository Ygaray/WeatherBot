---
phase: 07-cli-weather-location-one-shot
plan: 02
subsystem: cli
tags: [cli, argparse, subcommands, weather-one-shot, read-only-lookup]
requirements-completed: [CMD-01, CMD-03, CMD-04, CMD-05]
dependency-graph:
  requires:
    - "weatherbot.interactive.lookup_weather (Phase 06-02 read-only core)"
    - "weatherbot.interactive.UnknownLocationError (Phase 06-02)"
    - "weatherbot.reliability.is_transient (Phase 04)"
  provides:
    - "weatherbot.cli.run_weather (read-only one-shot handler, 0/1/3 exit map)"
    - "weatherbot.cli._cmd_weather (config-loading dispatcher, exit 2 on bad config)"
    - "weatherbot.cli.main restructured to add_subparsers(dest=command)"
    - "CLI subcommand surface: weather/run/check/send-now/geocode"
  affects:
    - "Plan 07-03 (rewrites removed-flag test callsites + adds the weather offline matrix)"
tech-stack:
  added: []
  patterns:
    - "argparse add_subparsers(dest=command) with a shared add_help=False --config parent"
    - "read-only bounded retry: Retrying(stop_after_attempt(3), is_transient arm ONLY)"
    - "quiet-by-default logging: basicConfig AFTER parse_args; WARNING for bare weather"
key-files:
  created: []
  modified:
    - "weatherbot/cli.py"
decisions:
  - "[07-02] weather uses 0/1/2/3 exit scheme (0 ok / 1 unknown-loc / 2 bad-config / 3 fetch-fail); migrated subcommands keep their original 0/1 codes."
  - "[07-02] Clean break: --run/--check/--send-now/--geocode flags removed with NO aliases (D-01/D-02)."
  - "[07-02] run_weather retry has ONLY the is_transient arm (no retry_if_result / no retry_error_callback) — a read-only lookup has no DeliveryResult (D-08)."
  - "[07-02] UnknownLocationError except arm placed BEFORE any broad ValueError/httpx arm (it IS-A ValueError, is_transient False -> reraised attempt 1)."
metrics:
  duration: "~2 min"
  completed: "2026-06-15"
  tasks: 2
  files: 1
---

# Phase 7 Plan 02: CLI weather subcommand + subparser restructure Summary

Shipped the standalone daemon-free `weather [location]` one-shot command (reusing the Phase 6 read-only `lookup_weather` core) and migrated `main()` from flat `--flag` + `hasattr` dispatch to argparse subparsers — all inside `weatherbot/cli.py`.

## What Was Built

**Task 1 — `run_weather` + `_cmd_weather` (commit 7732216):**
- Added `import sys` and `UnknownLocationError` to the cli imports.
- `run_weather(location_name, *, config, settings, client, templates_dir, verbose) -> int`: wraps `lookup_weather` in a short bounded `Retrying` (`stop_after_attempt(3)`, `wait_exponential(max=10)`, `retry=retry_if_exception(is_transient)` as the ONLY arm, `reraise=True`, `sleep=time.sleep`). Except arms ordered exactly: `UnknownLocationError` -> stderr verbatim message, return 1 (CMD-04); `httpx.HTTPStatusError` -> outcome-only `status=` log, return 3; timeout/connect/read -> `error=type(exc).__name__` log, return 3. Success prints `result.text` to stdout (CMD-05) and returns 0 (CMD-01/03).
- `_cmd_weather(args)`: loads config (returns 2 — not 1 — when invalid/missing, D-05), then calls `run_weather` with `args.location` and `verbose=args.verbose`.

**Task 2 — `main()` subparser restructure + quiet logging (commit e2c4b91):**
- Replaced flat-flag parser + `hasattr` dispatch with `add_subparsers(dest="command")`.
- Shared `--config` lives once on an `add_help=False` parent parser, attached via `parents=[config_parent]` to `weather`/`run`/`check`/`send-now`; `geocode` omits it (loads only secrets).
- `weather` subcommand: positional `location` (`nargs="?"`, `default=None` for CMD-03) + `-v`/`--verbose` (`store_true`, D-09).
- Old `--run`/`--check`/`--send-now`/`--geocode` flags REMOVED with no aliases (clean break, D-01/D-02).
- `logging.basicConfig` moved AFTER `parse_args` and called exactly once; level is `WARNING` for `weather` without `-v` (suppresses lookup.py's "lookup complete" INFO line), else `INFO`.
- Dispatch on `args.command`; `None` -> print help, return 0; migrated handlers keep their ORIGINAL exit codes (0/1); `run` branch retains the lazy `from weatherbot.scheduler import daemon` import. D-07 exit-2 overlap documented in a code comment.

## Verification Results

- `uv run python -c "from weatherbot.cli import run_weather, _cmd_weather"` -> import ok.
- `uv run weatherbot --help` -> exit 0, lists `weather`, `run`, `check`, `send-now`, `geocode`.
- `grep` confirms old flags gone and `retry_if_result` is absent from `run_weather` (present only in `run_send_now`).
- Dispatch smoke `main(['weather','x'])` -> printed `No location named 'x'; configured locations: Carlsbad, El Paso` to stderr, returned 1 (CMD-04 path; a local `config.toml` happens to exist).
- Quiet-logging check: after `main(['weather','x'])` the stdlib root level is 30 (WARNING), confirming D-09.

## Deviations from Plan

None — plan executed exactly as written. Task 1 is marked `tdd="true"`, but the plan's own `<verify>` block states the `weather` behavioral tests are authored in Plan 03; this task's authoritative verification is import-cleanliness + suite-collection, which was followed. (Project `config.json` has `tdd_mode: false`, so the MVP+TDD runtime gate was not active.)

## Expected Pre-Existing Test Failures (owned by Plan 03)

`uv run pytest tests/test_cli.py` -> 4 failed, 17 passed. The four failures
(`test_check_malformed_toml_returns_1_no_traceback`, `test_check_schema_error_returns_1_no_traceback`,
`test_check_missing_config_file_returns_1_no_traceback`, `test_send_now_malformed_toml_returns_1_no_traceback`)
are the removed-flag callsites still passing `--check` / `--send-now` / `--config <path>` style args,
which argparse now rejects as invalid subcommand choices. The plan's `<verification>` block explicitly
flags these as EXPECTED and fixed in Plan 03 ("Do not 'fix' tests here"). They were left untouched.

## Self-Check: PASSED

- FOUND: weatherbot/cli.py
- FOUND: .planning/phases/07-cli-weather-location-one-shot/07-02-SUMMARY.md
- FOUND commit: 7732216 (Task 1)
- FOUND commit: e2c4b91 (Task 2)
