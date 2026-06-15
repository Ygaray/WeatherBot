---
phase: 07-cli-weather-location-one-shot
verified: 2026-06-15T00:00:00Z
status: human_needed
score: 11/11 must-haves verified
overrides_applied: 0
human_verification:
  - test: "On host yahir-mint, run `uv run weatherbot weather home` with the real OpenWeather key and network"
    expected: "Exits 0 and prints the home location's v1 briefing to stdout (no log lines on stdout); `... -v` additionally shows the `lookup complete` INFO line on stderr"
    why_human: "Requires live OpenWeather API key + network; offline matrix uses an injected _FakeClient and cannot exercise the real fetch path"
  - test: "Redeploy the systemd unit on yahir-mint: git pull, `uv sync`, edit /etc/systemd/system/weatherbot.service ExecStart to `weatherbot run`, daemon-reload, restart"
    expected: "`systemctl status weatherbot.service` is active (running) and the next scheduled briefing fires; the deployed ExecStart no longer uses the removed `--run` flag"
    why_human: "Claude cannot mutate /etc/systemd/system/ or restart services on the remote host; the deployed unit still references the removed --run flag until re-synced (documented UAT)"
---

# Phase 7: CLI `weather [location]` One-Shot Verification Report

**Phase Goal:** A user can run `weatherbot weather [location]` as a standalone command — no daemon required — and get the configured location's briefing (or a clear error) printed, reusing the v1 template.
**Verified:** 2026-06-15
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | `weatherbot --help` resolves as a real console command (D-03), exits 0 (SC packaging) | ✓ VERIFIED | `.venv/bin/weatherbot` materialized (329-byte exec); `uv run weatherbot --help` exits 0; pyproject `[project.scripts] weatherbot = "weatherbot.cli:main"` (line 20-21) |
| 2   | `.venv/bin/weatherbot` exists after `uv sync` | ✓ VERIFIED | `ls -la .venv/bin/weatherbot` → present, executable |
| 3   | `weatherbot weather home` resolves configured location, prints briefing, exits 0 — no daemon/send/DB write (CMD-01 / SC#1) | ✓ VERIFIED (offline) | `run_weather` returns 0 after `print(result.text)` (cli.py:322-323); `test_weather_prints_briefing_exit_0` passes; no `persist`/`channel`/`daemon` reachable from `weather` path. Live host run = human item 1 |
| 4   | Bare `weatherbot weather` returns default/primary location's briefing (CMD-03 / SC#2) | ✓ VERIFIED | `weather` positional `location` is `nargs="?", default=None` (cli.py:541-546); `run_weather(None,...)` → `resolve_location(config, None)` resolves first; `test_weather_default_location_exit_0` passes |
| 5   | `weatherbot weather <unknown>` prints UnknownLocationError verbatim message (lists valid names) to stderr, exits 1 — no geocode fallback (CMD-04 / SC#3) | ✓ VERIFIED | `except UnknownLocationError` arm FIRST → `print(str(exc), file=sys.stderr); return 1` (cli.py:307-312); message `"No location named {requested!r}; configured locations: {names}"` (lookup.py:58-62); `test_weather_unknown_location_exits_1` asserts message + valid name on stderr + `onecall_calls` empty (resolve fails before fetch, lookup.py:103 before 117) |
| 6   | Printed briefing is `LookupResult.text` from `lookup_weather` — exact v1 template, no separate format (CMD-05 / SC#4) | ✓ VERIFIED | `print(result.text)` only (cli.py:322); no re-render/re-fetch; `test_weather_template_matches_v1` asserts stdout byte-equals `lookup_weather(...).text` under fixed clock |
| 7   | Bad/missing `--config` exits 2 (no traceback); 401/403 or exhausted-transient fetch failure exits 3 (stderr, never key/URL) | ✓ VERIFIED | `_cmd_weather` returns 2 when `_load_config_reporting` returns None (cli.py:333-335); `_load_config_reporting` catches FileNotFound/TOMLDecode/Validation, logs outcome-only, returns None (cli.py:460-478); HTTPStatusError/timeout arms return 3 with `status=`/`error=type` only (cli.py:313-319); `test_weather_bad_config_exits_2`, `test_weather_missing_config_exits_2`, `test_weather_fetch_failure_exhausted_transient_exits_3`, `test_weather_fetch_failure_auth_401_exits_3_no_retry` pass |
| 8   | `weather` quiet by default (no `lookup complete` INFO on stdout/stderr); `-v` restores INFO (D-09) | ✓ VERIFIED | `_configure_logging` sets WARNING for `weather` without `-v` via `make_filtering_bound_logger` + structlog routed to STDERR (cli.py:481-500, weatherbot/__init__.py); level chosen post-parse_args (cli.py:596-599); `test_weather_quiet_by_default_and_verbose` passes |
| 9   | Migrated `run`/`check`/`send-now`/`geocode` preserve behavior and exit codes | ✓ VERIFIED | Dispatch on `args.command` keeps original 0/1 codes for migrated handlers (cli.py:609-659); `run` retains lazy daemon import (cli.py:637); full suite 215 passed incl. rewritten callsites |
| 10  | Full suite green after clean break (≥206 tests; 5 removed-flag callsites rewritten) | ✓ VERIFIED | `uv run pytest -q` → 215 passed; `grep -rn 'main(\["--' tests/` → NONE; test_scheduler.py:619 uses `cli.main(["run", ...])` |
| 11  | deploy/weatherbot.service + README ExecStart examples use `run` subcommand (no `--run`) | ✓ VERIFIED | service line 29 `ExecStart=/usr/bin/uv run weatherbot run`; header options 8-9 on `run`; README lines 26/31 on `run`; line-15 `--run` is intentional prose (only acceptable residual) |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `pyproject.toml` | `[build-system]` hatchling + `[project.scripts]` weatherbot entry | ✓ VERIFIED | lines 16-21, exact entry `weatherbot = "weatherbot.cli:main"` |
| `weatherbot/cli.py` | subparser `main()`, `run_weather`, `_cmd_weather`, quiet logging | ✓ VERIFIED | `add_subparsers(dest="command")` (line 534); `run_weather` (253), `_cmd_weather` (326), `_configure_logging` (481); imports clean |
| `weatherbot/__init__.py` | project-wide structlog → STDERR baseline | ✓ VERIFIED | created; `_LiveStderr` proxy + `structlog.configure(... PrintLoggerFactory(file=_LiveStderr()))` |
| `tests/test_cli.py` | rewritten callsites + 9 `test_weather_*` | ✓ VERIFIED | 9 weather tests (lines 572-715); all pass; no removed-flag callsites |
| `tests/test_scheduler.py` | line ~619 on `run` subcommand | ✓ VERIFIED | `cli.main(["run", "--config", ...])` |
| `deploy/weatherbot.service` | ExecStart on `run` subcommand | ✓ VERIFIED | line 29 + header comments migrated |
| `deploy/README.md` | ExecStart examples on `run`; line-15 prose intact | ✓ VERIFIED | lines 26/31 migrated; redeploy note added |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `pyproject.toml [project.scripts]` | `weatherbot.cli:main` | console_scripts via uv sync | ✓ WIRED | `.venv/bin/weatherbot` resolves; `--help` exits 0 |
| `cli.run_weather` | `interactive.lookup_weather` | `retrying(lookup_weather, ...)`, is_transient arm only | ✓ WIRED | cli.py:299-306; retry uses `retry_if_exception(is_transient)` only (line 293) |
| `cli.main` | `_cmd_weather` / do_geocode / do_check / run_send_now / daemon.run_daemon | `args.command` dispatch | ✓ WIRED | cli.py:605-659 all branches present |
| `cli.run_weather` | `UnknownLocationError` | except arm BEFORE broad ValueError/httpx | ✓ WIRED | cli.py:307; verified ordering before httpx.HTTPStatusError arm |
| tests | `cli.run_weather` | injected `_FakeClient` (offline) | ✓ WIRED | 9 weather tests inject client; no network |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `run_weather` stdout | `result.text` | `lookup_weather` → `client.fetch_onecall` (real One Call 3.0 fetch) → Forecast → v1 template render | Offline: fixtures via `_FakeClient`; live: real API (human item 1) | ✓ FLOWING (offline) / human-confirm live |

`resolve_location` (lookup.py:103) runs before `fetch_onecall` (lookup.py:117-118), so the unknown-location path never fetches — confirmed by `onecall_calls`-empty assertion. The text rendered is the exact v1 template (CMD-05) with no separate on-demand format.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Console script resolves | `uv run weatherbot --help` | exit 0, lists weather/run/check/send-now/geocode | ✓ PASS |
| Symbols import cleanly | `python -c "from weatherbot.cli import run_weather, _cmd_weather, main"` | import ok | ✓ PASS |
| Full suite green | `uv run pytest -q` | 215 passed | ✓ PASS |
| Weather matrix | `uv run pytest tests/test_cli.py -k weather -q` | 9 passed | ✓ PASS |
| No removed-flag callsites | `grep -rn 'main(\["--' tests/` | NONE | ✓ PASS |
| Live `weather home` over network | (host yahir-mint) | not runnable offline | ? SKIP → human |

### Probe Execution

No `scripts/*/tests/probe-*.sh` exist and no probe declared in PLAN/SUMMARY; phase verification is test-suite + behavioral-check based. Probe execution: not applicable.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| CMD-01 | 07-01, 07-02, 07-03 | Standalone CLI `weather [location]` prints briefing, no daemon | ✓ SATISFIED | console script + `run_weather` exit-0 path + `test_weather_prints_briefing_exit_0`; live host run is human-confirm |
| CMD-03 | 07-02, 07-03 | Bare `weather` returns default/primary location | ✓ SATISFIED | `nargs="?", default=None` → resolve first; `test_weather_default_location_exit_0` |
| CMD-04 | 07-02, 07-03 | Unknown location → clear error listing valid names, no geocode fallback | ✓ SATISFIED | UnknownLocationError verbatim to stderr, exit 1, no fetch; `test_weather_unknown_location_exits_1` |
| CMD-05 | 07-02, 07-03 | Reuses exact v1 template, no separate format | ✓ SATISFIED | prints `result.text` unmodified; `test_weather_template_matches_v1` byte-equality |

No orphaned requirements: REQUIREMENTS.md maps exactly CMD-01/03/04/05 to Phase 7, all claimed by plans. CMD-02/06/07/08 are correctly mapped to Phase 11 (out of scope).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | No TODO/FIXME/XXX/TBD/HACK/PLACEHOLDER in modified files | ℹ️ Info | None |
| weatherbot/cli.py | 28, 62 | strings "appid"/"request.url" present | ℹ️ Info | Documentation only — docstring + a comment explicitly stating these are NEVER logged; actual logging calls use `status=`/`error=type(exc).__name__` (cli.py:315,318). Not a secret leak. |

No blocker anti-patterns. Secret-leak mitigation (T-07-02) confirmed: error logging is outcome-only and a test asserts no secret in stderr.

### Human Verification Required

#### 1. Live `weatherbot weather home` over real network

**Test:** On host yahir-mint, run `uv run weatherbot weather home` with the real OpenWeather key and network; also run `... -v`.
**Expected:** Exits 0 and prints the home location's v1 briefing to stdout with no log lines on stdout; `-v` additionally shows the `lookup complete` INFO line on stderr.
**Why human:** Requires live OpenWeather API key + network. The offline matrix injects `_FakeClient` and cannot exercise the real fetch path; byte-equality and exit codes are pinned offline, but the end-to-end live run is the final goal confirmation.

#### 2. Systemd redeploy on yahir-mint

**Test:** git pull on yahir-mint, `uv sync` (materialize `.venv/bin/weatherbot`), edit `/etc/systemd/system/weatherbot.service` ExecStart to `weatherbot run`, `daemon-reload`, restart.
**Expected:** `systemctl status weatherbot.service` is active (running); next scheduled briefing fires; deployed ExecStart no longer uses the removed `--run`.
**Why human:** Claude cannot mutate `/etc/systemd/system/` or restart remote services. The deployed unit still references the removed `--run` flag until re-synced (documented UAT in deploy/README.md §3b).

### Gaps Summary

No blocking gaps. All 11 must-haves verified in the codebase: the console script materializes (`.venv/bin/weatherbot`), `weatherbot weather [location]` is fully implemented as a daemon-free read-only one-shot reusing the v1 template via `lookup_weather`, the exit-code contract (0/1/2/3) is correct with UnknownLocationError caught first, error logging is outcome-only (no secret leak), quiet-by-default logging works with `-v` override, the four legacy flags are cleanly migrated to subcommands with original exit codes preserved, and the full suite is green (215 passed). Deploy artifacts use the `run` subcommand.

Status is `human_needed` (not `passed`) solely because two items cannot be verified programmatically: the live network end-to-end run and the remote systemd redeploy — both explicitly documented as manual UAT in Plan 03. These are confirmation steps, not unmet goals; the offline evidence already pins the contract.

---

_Verified: 2026-06-15_
_Verifier: Claude (gsd-verifier)_
