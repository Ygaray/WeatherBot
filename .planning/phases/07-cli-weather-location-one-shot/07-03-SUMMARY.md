---
phase: 07-cli-weather-location-one-shot
plan: 03
subsystem: cli
tags: [cli, tests, weather-one-shot, deploy, systemd, structlog, logging, D-09]
requirements-completed: [CMD-01, CMD-03, CMD-04, CMD-05]
dependency-graph:
  requires:
    - "weatherbot.cli.run_weather (Phase 07-02 read-only one-shot handler)"
    - "weatherbot.cli._cmd_weather (Phase 07-02 config-loading dispatcher)"
    - "weatherbot.cli.main add_subparsers surface (Phase 07-02)"
    - "weatherbot console script (Phase 07-01)"
    - "weatherbot.interactive.lookup_weather + UnknownLocationError (Phase 06-02)"
  provides:
    - "Offline weather-subcommand test matrix pinning CMD-01/03/04/05 + D-05/D-08/D-09"
    - "Working D-09 quiet mechanism (structlog routed to STDERR, honors effective level)"
    - "deploy artifacts (service + README) on the run subcommand form"
  affects:
    - "Phase 11 (Discord inbound) reuses the same lookup core + quiet/stderr logging baseline"
    - "Host yahir-mint redeploy (manual UAT step — deployed ExecStart still says --run)"
tech-stack:
  added: []
  patterns:
    - "Project-wide structlog default: make_filtering_bound_logger(level) + PrintLoggerFactory to a live-stderr proxy (logs never pollute pipeable stdout)"
    - "Live-stderr proxy resolves sys.stderr per write so structlog survives pytest capsys stream swaps"
    - "Offline CLI exit-matrix tests via injected _FakeClient (no network), fixed-clock monkeypatch for byte-identical template equality"
key-files:
  created: [weatherbot/__init__.py]
  modified:
    - tests/test_cli.py
    - tests/test_scheduler.py
    - weatherbot/cli.py
    - deploy/weatherbot.service
    - deploy/README.md
decisions:
  - "[07-03] [Rule 1 - Bug] D-09 quiet mode was non-functional: structlog's default config ignored the stdlib level and rendered the 'lookup complete' INFO line to STDOUT, defeating quiet mode AND polluting the weather command's pipeable STDOUT (breaks CMD-01). Fixed by configuring structlog to honor the effective level and render to STDERR."
  - "[07-03] structlog stream bound through a _LiveStderr proxy (resolves sys.stderr lazily) instead of a fixed sys.stderr reference — a fixed reference raised 'I/O operation on closed file' under pytest capsys."
  - "[07-03] CMD-05 byte-equality test uses a fixed-clock monkeypatch on the lookup module's datetime so the two independent renders match across the minute-granularity {sent_at}/{checked_at} tokens."
  - "[07-03] README line-15 pitfall prose ('ExecStart=weatherbot --run will not find the interpreter') left intact — it is explanatory narrative, not a directive (per plan)."
metrics:
  duration: "~10 min"
  completed: "2026-06-15"
  tasks: 3
  files: 6
---

# Phase 7 Plan 03: Suite-green clean break, weather offline tests, deploy migration Summary

Kept the suite green across the D-02 flag→subcommand clean break (rewrote the five removed-flag callsites), pinned the standalone `weather [location]` one-shot with an offline exit-code matrix, and migrated the deploy artifacts to the `run` subcommand form — uncovering and fixing a real D-09 bug where structlog logs leaked onto the briefing's STDOUT.

## What Was Built

**Task 1 — rewrite five removed-flag callsites (commit 80882ba):**
- `tests/test_cli.py`: three `main(["--check", ...])` and one `main(["--send-now", ...])` calls rewritten to `check`/`send-now` subcommand form; `assert rc == 1` assertions unchanged (migrated handlers keep their original 0/1 codes).
- `tests/test_scheduler.py:619`: `cli.main(["--run", ...])` → `cli.main(["run", ...])`.
- Repo-wide grep confirms these were the only five callsites using a removed flag.

**Task 2 — offline weather-subcommand tests + D-09 bug fix (commit c247315):**
- Added 9 offline `weather` tests to `tests/test_cli.py` (inject `_FakeClient`, reuse recorded fixtures, no new fixtures):
  - `test_weather_prints_briefing_exit_0` (CMD-01) — exit 0, briefing on stdout, dual-unit fetch, no log leak on stdout.
  - `test_weather_default_location_exit_0` (CMD-03) — bare `weather` (location=None) → default location, exit 0.
  - `test_weather_unknown_location_exits_1` (CMD-04) — exit 1, verbatim `No location named 'nope'` + valid name on stderr, `onecall_calls` empty (no network on the unknown path).
  - `test_weather_template_matches_v1` (CMD-05) — printed stdout byte-equals `lookup_weather(...).text` under a fixed clock.
  - `test_weather_bad_config_exits_2` + `test_weather_missing_config_exits_2` (D-05) — config-load failure returns 2 (not an argparse SystemExit).
  - `test_weather_fetch_failure_exhausted_transient_exits_3` (D-05/D-08) — persistent 429 exhausts the short bound → exit 3, attempts ≤ 3, no secret in stderr (T-07-05).
  - `test_weather_fetch_failure_auth_401_exits_3_no_retry` (D-08/Pitfall 5) — permanent 401 → exit 3 on the FIRST attempt (no retry), secret-free.
  - `test_weather_quiet_by_default_and_verbose` (D-09) — quiet path has no `lookup complete` on stderr/stdout; `-v` shows it on stderr.
- **[Rule 1 bug fix]** `weatherbot/__init__.py` (new) + `weatherbot/cli._configure_logging`: configure structlog to honor the effective level (`make_filtering_bound_logger`) and render to STDERR via a `_LiveStderr` proxy. See Deviations.

**Task 3 — deploy artifacts on the run subcommand (commit fc6abda):**
- `deploy/weatherbot.service`: `ExecStart` (line 29) + header-comment options (a)/(b) now use `weatherbot run` / `python -m weatherbot run`.
- `deploy/README.md`: the two genuine ExecStart examples (uv + venv) use `run`; line-15 pitfall prose left intact; added a host-redeploy note (`uv sync` + `daemon-reload` + restart) as the ops/UAT step.

## Verification Results

- `uv run pytest` → **215 passed** (was 206; +9 weather tests). Satisfies the ≥206-green clean-break bar.
- `grep -rn 'main(\["--' tests/` → nothing (no removed-flag callsites).
- `uv run weatherbot --help` → exit 0, lists `weather`, `run`, `check`, `send-now`, `geocode`.
- Task 3 verify command passed: service line 29 on `run`, both migrated README forms present, no indented `ExecStart=… --run` example directive survives, line-15 prose untouched.
- Residual `--run` tokens in `deploy/` are all prose (line 15 pitfall + the new redeploy-note narrative) — no genuine directive.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] D-09 quiet mode was non-functional and leaked logs onto the briefing's STDOUT**
- **Found during:** Task 2 (writing the quiet-vs-verbose test, which failed because the `lookup complete` INFO line still appeared).
- **Issue:** The project had no `structlog.configure(...)`, so structlog used its library default, which (a) ignores the stdlib root level set by `logging.basicConfig(level=…)` and (b) renders to STDOUT. Empirically confirmed: `weather` without `-v` still emitted `lookup complete` AND it printed on STDOUT *above the briefing* — defeating D-09 quiet mode and breaking CMD-01's "stdout is just the briefing" pipeable contract.
- **Fix:** Added `weatherbot/__init__.py` with a project-wide `structlog.configure(wrapper_class=make_filtering_bound_logger(INFO), logger_factory=PrintLoggerFactory(file=_LiveStderr()))`, and updated `cli._configure_logging` to re-apply the same with the per-subcommand level (WARNING for quiet `weather`). The `_LiveStderr` proxy resolves `sys.stderr` on each write so the config survives pytest `capsys` stream swaps (a fixed `sys.stderr` reference raised "I/O operation on closed file" across 24 tests).
- **Files modified:** `weatherbot/__init__.py` (created), `weatherbot/cli.py`.
- **Commit:** c247315.
- **Scope note:** `cli.py` is Plan 02's file, but the bug directly blocked Task 2's D-09 deliverable (the quiet-vs-verbose test could not pass) and violated CMD-01 — Rule 1 (auto-fix bug) and Rule 3 (unblock the task) both apply. Existing `test_reliability.py`/`test_scheduler.py` log assertions use `.out + .err`, so routing logs to stderr left all of them green.

**2. [Rule 1 - Test correctness] CMD-05 byte-equality needed a fixed clock**
- **Found during:** Task 2.
- **Issue:** The v1 template renders `{sent_at}`/`{checked_at}` from `datetime.now(tz)`; two independent renders could differ across a minute boundary, flaking the byte-equality assertion.
- **Fix:** Monkeypatch the lookup module's `datetime` to a fixed instant for the duration of the test, making both renders deterministic.
- **Files modified:** `tests/test_cli.py`.
- **Commit:** c247315.

## Known Stubs

None — all weather tests assert real behavior against the read-only core; deploy edits are concrete invocation strings.

## Manual UAT (carried forward — host action, NOT autonomous)

Per the plan's `<uat>`: after this phase merges, redeploy on host `yahir-mint` — `git pull`, `uv sync` (materialize `.venv/bin/weatherbot`), edit the deployed `/etc/systemd/system/weatherbot.service` `ExecStart` to `weatherbot run`, `daemon-reload`, restart, confirm `active (running)`. Claude cannot mutate `/etc/systemd/system/` or restart services on the remote host. The repo `deploy/README.md` now documents this step (§3b).

## Self-Check: PASSED

- FOUND: tests/test_cli.py (9 `test_weather_*` tests)
- FOUND: weatherbot/__init__.py
- FOUND: deploy/weatherbot.service contains `ExecStart=/usr/bin/uv run weatherbot run`
- FOUND commit: 80882ba (Task 1)
- FOUND commit: c247315 (Task 2)
- FOUND commit: fc6abda (Task 3)

---
*Phase: 07-cli-weather-location-one-shot*
*Completed: 2026-06-15*
