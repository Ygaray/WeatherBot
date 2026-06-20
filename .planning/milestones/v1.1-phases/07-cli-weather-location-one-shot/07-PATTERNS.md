# Phase 7: CLI `weather [location]` One-Shot - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 5 (1 new handler in an existing file, 4 modifications)
**Analogs found:** 5 / 5 (all in-repo; no external pattern needed)

> **Key framing:** This phase is ~40 lines of glue plus a *restructure*. Almost every
> pattern the new `weather` command needs already exists verbatim in `weatherbot/cli.py`
> (`run_send_now`, `do_check`, `do_geocode`, `_load_config_reporting`, `main`). The
> closest analogs are NOT in some other module — they are the sibling functions in the
> very file being edited. Copy them, do not invent.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/cli.py` → new `run_weather`/`_cmd_weather` handler | controller (CLI handler) | request-response (read-only fetch→print) | `weatherbot/cli.py` `run_send_now` (lines 181-249) | exact (same file, same retry shape, minus DeliveryResult arm) |
| `weatherbot/cli.py` → restructured `main()` | controller (CLI dispatch) | request-response | `weatherbot/cli.py` `main` (lines 388-490) | exact (the function being refactored) |
| `pyproject.toml` | config (packaging) | n/a | existing `[project]` table (lines 1-26) | role-match (adding `[build-system]` + `[project.scripts]`) |
| `deploy/weatherbot.service` | config (systemd unit) | n/a | existing `ExecStart` line (line 29) | exact (string swap `--run` → `run`) |
| `deploy/README.md` | docs | n/a | existing invocation block (lines 15-31) | exact (string swap) |
| `tests/test_cli.py` | test | request-response | existing `main([...])` tests (lines 286-323) + `do_*` injected-client tests (lines 75-245) | exact (rewrite removed-flag calls; mirror fake-client offline seam) |

> **Discretion locked by RESEARCH §Recommended Project Structure:** keep the new
> `weather` handler in `weatherbot/cli.py` (alongside `run_send_now`/`do_check`/`do_geocode`)
> rather than a new `interactive/cli.py` — avoids a new import edge and the cli↔interactive
> cycle that `lookup_weather` and `resolve_location` already lazily guard against.

## Pattern Assignments

### `weatherbot/cli.py` — new `run_weather` handler (controller, request-response)

**Analog:** `run_send_now` (lines 181-249) — the ATTENDED tight-retry wrapper. Copy its
`Retrying` block and its two `except httpx.*` arms; DROP the `retry_if_result` arm and the
`retry_error_callback` (both exist only because `send_now` returns a `DeliveryResult` —
`lookup_weather` returns a `LookupResult` and never an `ok=False` result).

**Imports already present at top of `cli.py`** (lines 27-46) — reuse, add nothing new:
```python
import httpx
import structlog
from tenacity import (
    Retrying, retry_if_exception, retry_if_result,   # retry_if_result no longer needed by weather
    stop_after_attempt, wait_exponential,
)
from weatherbot.interactive import lookup_weather     # line 43 — already imported
from weatherbot.reliability import is_transient        # line 45 — already imported
# add: import sys  (for print(..., file=sys.stderr))  — not currently imported, ADD IT
# add to the interactive import: UnknownLocationError  (see lookup.py public surface)
```
> NOTE: `cli.py` imports `lookup_weather` from `weatherbot.interactive` but NOT
> `UnknownLocationError`. Confirm `UnknownLocationError` is exported from
> `weatherbot/interactive/__init__.py`; if not, import it from `weatherbot.interactive.lookup`.
> `sys` is NOT imported in `cli.py` today — add `import sys` for the stderr writes (D-06).

**Retry template — copy `run_send_now` lines 209-243, adapted (D-08):**
```python
# Reuse the SAME bound (line 178): _MANUAL_MAX_ATTEMPTS = 3
retrying = Retrying(
    stop=stop_after_attempt(_MANUAL_MAX_ATTEMPTS),       # =3, line 210
    wait=wait_exponential(multiplier=1, max=10),         # identical to line 211
    retry=retry_if_exception(is_transient),              # ONLY this arm (DROP retry_if_result)
    reraise=True,                                        # line 217
    sleep=time.sleep,                                    # line 222 — patchable test seam
    # NO retry_error_callback — that line (221) only mattered for a non-ok DeliveryResult
)
try:
    result = retrying(
        lookup_weather, location_name,
        config=config, settings=settings, client=client, templates_dir=templates_dir,
    )
except UnknownLocationError as exc:          # MUST be caught BEFORE any broad ValueError
    print(str(exc), file=sys.stderr)         # reuse message verbatim (D-06 / CMD-04)
    return 1
except httpx.HTTPStatusError as exc:         # copy run_send_now lines 236-240
    _log.error("weather lookup failed", status=exc.response.status_code)  # outcome only, T-04-01
    return 3
except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:  # lines 241-243
    _log.error("weather lookup failed", error=type(exc).__name__)
    return 3
print(result.text)                           # briefing → stdout (D-06 / CMD-05)
return 0
```

**CRITICAL ordering (NOT in `run_send_now`):** `UnknownLocationError` IS-A `ValueError`
(see `lookup.py` line 44: `class UnknownLocationError(ValueError)`), and `is_transient`
returns `False` for it (`reliability/retry.py` lines 80-91 — it only matches httpx
transient errors). So it is re-raised on attempt 1, never retried, and its `except` arm
must come FIRST. `resolve_location` runs inside `lookup_weather` BEFORE any fetch
(`lookup.py` line 103), so the unknown-location path never touches the network.

**Auth-failure handling is FREE:** a 401/403 is in `PERMANENT = frozenset({400,401,403,404})`
(`reliability/retry.py` line 71), so `is_transient` returns `False` → `reraise=True`
re-raises it on attempt 1 → caught by the `except httpx.HTTPStatusError` arm → exit 3
immediately, NOT after 3 attempts (D-08 / RESEARCH Pitfall 5).

**Exit-code dispatcher — copy `_load_config_reporting` usage from `main()` lines 444-450:**
```python
def _cmd_weather(args) -> int:
    config = _load_config_reporting(args.config)   # lines 367-385 — clean no-traceback load
    if config is None:
        return 2                                    # config invalid/missing (D-05) — was 1 for old flags
    settings = load_settings()                      # line 449 pattern
    return run_weather(args.location, config=config, settings=settings,
                       verbose=args.verbose)
```
> **Migration note (RESEARCH §Code Examples):** the *migrated* `check`/`run`/`send-now`/`geocode`
> handlers keep their EXISTING return codes (0/1). Only the new `weather` command uses the
> richer 0/1/2/3 scheme. In `main()`, the old `--check`/`--run`/`--send-now` branches return
> `1` on `config is None` (lines 448/455/473) — leave those as-is; only `weather` returns 2.

---

### `weatherbot/cli.py` — restructured `main()` (controller, request-response)

**Analog:** the existing `main()` (lines 388-490) being refactored from flat flags +
`hasattr` dispatch to `add_subparsers(dest="command")`.

**What is being replaced** (lines 396-437 flag definitions; lines 440-468 `hasattr` dispatch):
```python
# OLD (flat flags, lines 396-431):  --send-now / --geocode / --check / --run  with argparse.SUPPRESS
# OLD (dispatch, lines 440-468):     if hasattr(args, "geocode"): ... if hasattr(args, "check"): ...
```

**New structure** (RESEARCH Pattern 1 — parent parser carrying `--config` via `parents=[...]`):
```python
parent = argparse.ArgumentParser(add_help=False)
parent.add_argument("--config", default="config.toml",
                    help="Path to the non-secret TOML config (default: config.toml).")  # copies line 433-435
parser = argparse.ArgumentParser(prog="weatherbot", description="...")
sub = parser.add_subparsers(dest="command")     # dest → clean args.command dispatch
p_weather = sub.add_parser("weather", parents=[parent], help="Print a configured location's briefing and exit.")
p_weather.add_argument("location", nargs="?", default=None)   # CMD-03: bare → default location
p_weather.add_argument("-v", "--verbose", action="store_true")  # D-09
p_run     = sub.add_parser("run",      parents=[parent], help="Run the always-on scheduler.")
p_check   = sub.add_parser("check",    parents=[parent], help="Validate config + one probe.")
p_send    = sub.add_parser("send-now", parents=[parent], help="Send a briefing now.")
p_send.add_argument("location", nargs="?", default=None)        # mirrors old --send-now nargs="?" (line 398)
p_geo     = sub.add_parser("geocode")    # geocode needs NO --config (old branch only loads settings, line 441)
p_geo.add_argument("query")
args = parser.parse_args(argv)
if args.command is None:           # bare `weatherbot` — preserve lines 468-470 behavior
    parser.print_help(); return 0
```

**Quiet-logging pattern (D-09) — REPLACES the unconditional `basicConfig` at line 390:**
```python
# MOVE basicConfig to AFTER parse_args (RESEARCH Anti-Pattern: basicConfig is a no-op on 2nd call).
# Today line 390 calls logging.basicConfig(level=logging.INFO) unconditionally — that defeats D-09.
level = logging.INFO
if args.command == "weather" and not getattr(args, "verbose", False):
    level = logging.WARNING        # suppress lookup.py line 146: _log.info("lookup complete", ...)
logging.basicConfig(level=level)
```
> **Open Question 1 / Assumption A1 (MUST verify in Wave 0):** D-09's mechanism assumes
> structlog defers to the stdlib root level. Grep for `structlog.configure` /
> `make_filtering_bound_logger` before locking this. The INFO line to suppress is
> `lookup.py:146` `_log.info("lookup complete", location=location.name)`. If structlog
> pins its own level, quiet via structlog instead. A test asserting "no INFO on `weather`,
> INFO appears with `-v`" pins it either way.

**Dispatch the migrated handlers** — the bodies are UNCHANGED, only the trigger moves from
`hasattr(args, X)` to `args.command == "X"`:
- `weather`  → `_cmd_weather(args)` (NEW)
- `geocode`  → `do_geocode(args.query, settings=load_settings())` (copy lines 440-442)
- `check`    → `_load_config_reporting` → `do_check(...)` (copy lines 445-450)
- `run`      → `_load_config_reporting` → lazy `from weatherbot.scheduler import daemon` → `daemon.run_daemon(...)` (copy lines 453-466, **keep the lazy import** — line 464 comment: a top-level import creates a cli↔daemon cycle)
- `send-now` → `run_send_now(args.location, config=..., db_path=..., settings=...)` (copy lines 472-490)

**D-07 documented mapping (argparse-2 overlap):** argparse raises `SystemExit(2)` for bad
usage *inside* `parse_args`; a bad config returns `2` from `_cmd_weather`. They are
distinguishable in tests: `pytest.raises(SystemExit)` for bad usage vs `main([...]) == 2`
for a bad config file. Keep the overlap (both mean "bad input"); write config-invalid tests
that drive a VALID subcommand with a BAD config file.

---

### `pyproject.toml` (config, packaging)

**Analog:** existing `[project]` table (lines 1-26). NO new runtime dependencies — every
needed library (argparse stdlib, tenacity, structlog, httpx) is already in `dependencies`
(lines 6-14).

**Add (D-03 — RESEARCH Pitfall 1, the most likely silent failure):**
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project.scripts]
weatherbot = "weatherbot.cli:main"
```
> Without a `[build-system]` (the file has NONE today, verified lines 1-26), uv treats the
> project as a non-package and `[project.scripts]` produces NO console script — `uv run
> weatherbot` and the deployed `ExecStart` then fail. Alternative: `[tool.uv] package = true`
> (uv-specific). Hatchling is the portable PyPA choice and approved in RESEARCH §Legitimacy Audit.
> **Verification task:** after editing, `uv sync` then `uv run weatherbot --help` exits 0.

---

### `deploy/weatherbot.service` (config, systemd unit)

**Analog:** line 29 `ExecStart=/usr/bin/uv run weatherbot --run`.

**Change (D-02):** `--run` → `run` subcommand form:
```
ExecStart=/usr/bin/uv run weatherbot run
```
Also update the header comment options (lines 8-9) that show both invocation forms with `--run`.

> **Ops/UAT (NOT a code change, D-02):** the DEPLOYED unit on host `yahir-mint` lives in
> `/etc/systemd/system/` and still says `--run`. After redeploy: edit it to `run`,
> `systemctl daemon-reload`, restart, confirm `active (running)`. Also `uv sync` on the
> host so the `weatherbot` console script materializes in `.venv/bin/` (RESEARCH §Runtime
> State Inventory). The venv form (option b) `… python -m weatherbot run` also needs the
> `--run` → `run` swap.

---

### `deploy/README.md` (docs)

**Analog:** lines 15, 26, 31 — three `weatherbot --run` / `python -m weatherbot --run`
invocation examples.

**Change (D-02):** swap each to `run` subcommand form:
- line 15: `ExecStart=weatherbot run`
- line 26: `ExecStart=/usr/bin/uv run weatherbot run`
- line 31: `ExecStart=<REPO>/.venv/bin/python -m weatherbot run`

---

### `tests/test_cli.py` (test, request-response)

**Analog A — offline injected-client seam** (lines 25-69): `_FakeClient` (records
`onecall_calls`, returns fixtures), `_FakeChannel`, and `_config(...)` helper. Reuse these
verbatim for the new `weather` tests — inject `client=` so the lazy `build_client` import
(`lookup.py` lines 105-113) never runs and no network is touched.

**Analog B — `main([...])` exit-code tests** (lines 286-323): the FOUR calls that MUST be
rewritten (RESEARCH Pitfall 2):
```python
# lines 295, 308, 314 — REWRITE  main(["--check", ...])  →  main(["check", ...])
# line 322          — REWRITE  main(["--send-now", ...])  →  main(["send-now", ...])
```
After the clean break these flags no longer parse → argparse raises `SystemExit(2)` instead
of returning 1, so the tests ERROR rather than fail. Rewriting them is mandatory for "206
green" and is part of the migration, not scope creep.

> **A FIFTH removed-flag call exists OUTSIDE this file** (verified by repo-wide grep —
> RESEARCH Assumption A3 was at risk and IS triggered):
> **`tests/test_scheduler.py:619`** `rc = cli.main(["--run", "--config", str(cfg_path)])`.
> This MUST be rewritten to `cli.main(["run", "--config", str(cfg_path)])` or
> `test_run_daemon` errors with `SystemExit(2)`. Audit closed: those are the only five
> `main([...])` callsites using a removed flag.

**New `weather` tests to add** (RESEARCH §Test Map; reuse `_FakeClient`/`load_fixture`/`capsys`):
```python
def test_weather_unknown_location_exits_1(capsys):
    rc = run_weather("nope", config=_config(), client=_FakeClient())  # never reaches network
    assert rc == 1
    err = capsys.readouterr().err
    assert "No location named 'nope'" in err   # CMD-04 message verbatim
    assert "New York" in err                    # valid names listed (from _config default)

def test_weather_prints_briefing_exit_0(capsys, load_fixture):
    client = _FakeClient(onecall_imp=load_fixture("onecall_imperial_clear.json"),
                         onecall_met=load_fixture("onecall_metric_clear.json"))
    rc = run_weather(None, config=_config(), client=client)   # CMD-03 bare → default
    assert rc == 0
    assert capsys.readouterr().out.strip()       # briefing on stdout
```
For exit-3 / bounded-retry: patch the `sleep` seam (`_no_sleep` helper, lines 335-337 already
exists — `monkeypatch.setattr("weatherbot.cli.time.sleep", lambda _d: None)`) and have the
fake client raise `httpx.HTTPStatusError(429)` (the `_http_429()` helper, lines 355-358) every
call; assert `rc == 3` and attempts ≤ 3. Available fixtures: `onecall_imperial_clear.json`,
`onecall_metric_clear.json`, `onecall_imperial_rainy.json`, `onecall_metric_rainy.json`,
plus alert/extreme/highuv variants (in `tests/fixtures/`).

---

## Shared Patterns

### Outcome-only error logging (T-04-01)
**Source:** `cli.py` `run_send_now` lines 236-243, `do_geocode` lines 274-276, `do_check`
lines 328-338.
**Apply to:** the new `weather` handler's `except` arms.
```python
_log.error("weather lookup failed", status=exc.response.status_code)   # status code only
_log.error("weather lookup failed", error=type(exc).__name__)          # exception TYPE only
```
NEVER log the `appid`/webhook URL or `exc.request.url` (which carries the key). The
`UnknownLocationError` message carries only names, never secrets (`lookup.py` lines 44-60).

### Clean config-error reporting → exit (CONF-05)
**Source:** `cli.py` `_load_config_reporting` (lines 367-385) — catches `FileNotFoundError`,
`tomllib.TOMLDecodeError`, `pydantic.ValidationError`, logs outcome-only, returns `None`.
**Apply to:** `_cmd_weather` (`None` → exit 2). Reuse the function as-is — do NOT add a new
config loader. (The migrated `check`/`run`/`send-now` branches keep mapping `None` → 1.)

### Bounded transient retry (D-08)
**Source:** `cli.py` `run_send_now` lines 209-223 + `_MANUAL_MAX_ATTEMPTS = 3` (line 178);
classifier `reliability/retry.py` `is_transient` (lines 80-91) with `PERMANENT`/`TRANSIENT`
sets (lines 71-72).
**Apply to:** the `weather` handler — copy the `Retrying` block, drop the `retry_if_result`
arm and `retry_error_callback`. `sleep=time.sleep` is the patchable test seam (line 222).

### Injectable client seam for offline tests
**Source:** `lookup_weather` `client=None` branch (`lookup.py` lines 105-113) + `_FakeClient`
(`tests/test_cli.py` lines 25-41).
**Apply to:** `run_weather` — accept `client=`, `settings=`, `templates_dir=` kwargs and pass
them straight to `lookup_weather`, so tests inject `_FakeClient` and never hit the network.

## No Analog Found

None. Every pattern this phase needs already exists in-repo. The new `weather` command is a
near-copy of `run_send_now` minus the delivery half; the subparser restructure refactors the
existing `main()`; the packaging/deploy edits are string/section additions.

## Metadata

**Analog search scope:** `weatherbot/cli.py`, `weatherbot/interactive/lookup.py`,
`weatherbot/reliability/retry.py`, `weatherbot/config/loader.py`, `weatherbot/__main__.py`,
`tests/test_cli.py`, `tests/test_scheduler.py`, `pyproject.toml`, `deploy/weatherbot.service`,
`deploy/README.md`, `tests/fixtures/`.
**Files scanned:** 11 + fixtures dir.
**Pattern extraction date:** 2026-06-15
</content>
</invoke>
