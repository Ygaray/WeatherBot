---
phase: 07-cli-weather-location-one-shot
reviewed: 2026-06-15T22:51:20Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - weatherbot/cli.py
  - weatherbot/__init__.py
  - pyproject.toml
  - tests/test_cli.py
  - tests/test_scheduler.py
  - deploy/weatherbot.service
  - deploy/README.md
findings:
  critical: 1
  warning: 4
  info: 4
  total: 9
status: issues_found
---

# Phase 7: Code Review Report

**Reviewed:** 2026-06-15T22:51:20Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the Phase 7 CLI surface (subparser restructure: `weather`/`run`/`check`/`send-now`/`geocode`), the package-level structlog/STDERR baseline, the `pyproject.toml` build-system + console-script entry point, and the two affected test modules plus the systemd deploy artifacts. The existing test suite (57 tests across `test_cli.py` + `test_scheduler.py`) passes.

The retry/exit-code machinery in `run_weather` and `run_send_now` is carefully built and well-covered. However, the review surfaced one BLOCKER: the `geocode` subcommand — a real network call — has incomplete exception handling and will emit a raw Python traceback on a transient network failure, contradicting both its own docstring ("returns non-zero on failure") and the project's explicit "report malformed input loudly but cleanly, never a raw traceback" requirement (CONF-05 / SC-05). Several WARNINGs concern a dead `verbose` parameter, inconsistent exit-code contracts vs. docstrings, and missing transient-error handling on the `check` probe path.

Cross-referenced the called collaborators (`lookup_weather`, `run_self_check`, `geocode`, `is_transient`) to confirm the findings rather than relying on the CLI module in isolation.

## Critical Issues

### CR-01: `geocode` subcommand crashes with a raw traceback on transient network errors

**File:** `weatherbot/cli.py:365-370` (and dispatch at `weatherbot/cli.py:613-615`)
**Issue:** `do_geocode` wraps the live network call in a `try` that catches ONLY `httpx.HTTPStatusError`:

```python
try:
    matches = client.geocode(query)
except httpx.HTTPStatusError as exc:
    _log.error("geocode failed", status=exc.response.status_code)
    return 1
```

`weatherbot/weather/client.py::geocode` makes a real `httpx.Client.get(...)` with a finite timeout and `raise_for_status()`. A timeout, DNS failure, or connection reset therefore raises `httpx.TimeoutException` / `httpx.ConnectError` / `httpx.ReadError` — none of which are caught here. The `main` `geocode` branch (`do_geocode(args.query, settings=settings)`) has no retry wrapper and no outer guard, so the exception propagates out of `main()` as an uncaught traceback to the terminal.

This violates two contracts at once:
1. The function docstring's promise: *"Returns 0 on success, non-zero on failure. The `appid` never appears in output or logs."* A traceback bypasses the outcome-only logging entirely.
2. The project requirement (CONF-05 / SC-05, enforced for `check`/`send-now`/`weather` everywhere else in this file): a failure must be reported loudly but cleanly, never as a raw Python traceback.

Every OTHER network path in this module catches the full transient triple (`run_weather` at `cli.py:317`, `run_send_now` at `cli.py:242`). `geocode` was missed.

**Fix:** Catch the transient-network exceptions alongside `HTTPStatusError`, mirroring the other paths:
```python
try:
    matches = client.geocode(query)
except httpx.HTTPStatusError as exc:
    _log.error("geocode failed", status=exc.response.status_code)
    return 1
except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
    _log.error("geocode failed", error=type(exc).__name__)
    return 1
```

## Warnings

### WR-01: `do_check` reachability probe leaves transient network errors unhandled

**File:** `weatherbot/cli.py:416` (call to `run_self_check`)
**Issue:** `do_check` delegates the One Call reachability probe to `run_self_check`. Inspecting `weatherbot/ops/selfcheck.py`, `run_self_check` classifies `HTTPStatusError` (401/403 → `AUTH_FAILED`, 429/5xx → `NETWORK_NOT_READY`) and connect/timeout/read errors into a `CheckResult` — so `check` is safe IF the probe always classifies. Confirm that `run_self_check` catches the same transient triple `do_geocode` misses; if any `httpx` transient type escapes `run_self_check`'s `except`, `do_check` (which has no `try` around the call at `cli.py:416`) will crash with a raw traceback exactly like CR-01. This is a latent coupling: the safety of `check` depends entirely on `run_self_check`'s catch breadth, with no defense-in-depth at the `do_check` boundary.
**Fix:** Either (a) confirm and document that `run_self_check` catches `httpx.TimeoutException`/`ConnectError`/`ReadError` (the test `test_check_reachability_subscription_message` only exercises `HTTPStatusError(401)` — add a connect/timeout case), or (b) add a defensive `except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)` guard in `do_check` returning 1.

### WR-02: `run_weather` accepts a `verbose` parameter it never uses

**File:** `weatherbot/cli.py:260` (param), `weatherbot/cli.py:341` (passed by `_cmd_weather`)
**Issue:** `run_weather(..., verbose: bool = False)` declares `verbose` but the function body never references it — the actual quiet/INFO level decision is made in `main` (`cli.py:597-599`) via `_configure_logging`, BEFORE `run_weather` is reached. The parameter is dead: `_cmd_weather` reads `args.verbose` and forwards it to a function that ignores it. A future maintainer will reasonably assume passing `verbose=True` to `run_weather` changes logging — it does nothing. This is a misleading contract, not just an unused local.
**Fix:** Remove the `verbose` parameter from `run_weather` and drop `verbose=args.verbose` from the `_cmd_weather` call (`cli.py:341`). The verbosity decision correctly lives in `main`; `run_weather` should not advertise control it does not have.

### WR-03: `do_geocode` docstring contradicts its "no matches" return code

**File:** `weatherbot/cli.py:357-358` (docstring) vs `weatherbot/cli.py:372-374` (behavior)
**Issue:** The docstring states *"Returns 0 on success, non-zero on failure."* But a successful API call that simply returns zero matches (a typo'd place name — not a failure) returns `1`:
```python
if not matches:
    print(f"# No matches for {query!r}.")
    return 1
```
A geocode that successfully reached the API and got an empty list is arguably "success with no result," yet it shares the exit code with a genuine API failure. Callers/scripts cannot distinguish "API down" from "no such place." This may be intentional (treat no-match as a usage failure), but the docstring's "0 on success" framing is then wrong.
**Fix:** Reconcile docstring and behavior. Either document that an empty match-set is treated as a non-zero "nothing to do" outcome, or return a distinct code. At minimum update the docstring so the contract is truthful.

### WR-04: `send_now` computes `sent_dt`/`checked_dt` unconditionally then discards them when `tz is None`

**File:** `weatherbot/cli.py:134-140`
**Issue:**
```python
tz = schedule_ctx.tz if schedule_ctx is not None else None
sent_dt = datetime.now(tz) if tz is not None else None
checked_dt = datetime.now(tz) if tz is not None else None
if tz is not None:
    extra_placeholders = schedule_placeholders(schedule_ctx, sent_dt, checked_dt)
else:
    extra_placeholders = None
```
`sent_dt` and `checked_dt` are only ever consumed inside the `if tz is not None` branch, so the two `datetime.now(tz) if tz is not None else None` assignments are redundant guards (the `else None` arms are computed only to be ignored). More importantly, two SEPARATE `datetime.now(tz)` calls are made for `sent_dt` and `checked_dt` even though the docstring (lines 130-131) asserts they are "within seconds of the single fetch" and effectively the same instant — they will differ by microseconds-to-milliseconds for no reason, and the duplication invites future drift. This is a clarity/correctness-adjacent smell rather than a hard bug.
**Fix:** Compute the instant once inside the guarded branch:
```python
tz = schedule_ctx.tz if schedule_ctx is not None else None
if tz is not None:
    now = datetime.now(tz)
    extra_placeholders = schedule_placeholders(schedule_ctx, now, now)
else:
    extra_placeholders = None
```

## Info

### IN-01: `_LiveStderr.write` return value is the underlying write count but the type contract is unchecked

**File:** `weatherbot/__init__.py:33-34`
**Issue:** `def write(self, data: str) -> int: return sys.stderr.write(data)` forwards correctly, but `_LiveStderr` is a minimal duck-typed file proxy — it implements only `write`/`flush`. If structlog's `PrintLoggerFactory` (or any handler) ever calls another file method (`isatty`, `closed`, `fileno`), this proxy raises `AttributeError`. For the current structlog version this is fine; it is a latent fragility worth a comment noting the proxy is intentionally minimal.
**Fix:** Add a brief note that only `write`/`flush` are required by `PrintLoggerFactory`, or subclass/delegate `__getattr__` to `sys.stderr` for robustness.

### IN-02: `structlog.configure` runs twice (package import + `_configure_logging`)

**File:** `weatherbot/__init__.py:40-44` and `weatherbot/cli.py:496-500`
**Issue:** The package `__init__` configures structlog at import time with `make_filtering_bound_logger(logging.INFO)`; `main` then re-configures it via `_configure_logging` after parsing args with the per-command level. The first configuration is effectively a throwaway for the CLI path (immediately overridden). It does serve non-CLI entry points (daemon/tests), per the docstring, so this is intentional — but the double-configure with `cache_logger_on_first_use=False` means every `get_logger` re-resolves. Confirm no logger is bound between the two `configure` calls in a way that captures the stale INFO wrapper.
**Fix:** No change required if intentional; consider a one-line comment in `_configure_logging` noting it deliberately re-runs `configure` over the package baseline.

### IN-03: `db_path.parent.mkdir` duplicated across `run` and `send-now` branches

**File:** `weatherbot/cli.py:635-636` and `weatherbot/cli.py:651-652`
**Issue:** The `run` and `send-now` branches each repeat `db_path = DEFAULT_DB_PATH; db_path.parent.mkdir(parents=True, exist_ok=True)`. Minor duplication of the DB-dir prep logic.
**Fix:** Extract a tiny `_ensure_db_dir() -> Path` helper returning the prepared `DEFAULT_DB_PATH`.

### IN-04: `templates_dir` type annotation mismatch across the call chain

**File:** `weatherbot/cli.py:96, 258` (`templates_dir: str | Path | None`) vs `weatherbot/interactive/lookup.py:84` (`templates_dir: str | None`)
**Issue:** `send_now` and `run_weather` annotate `templates_dir` as `str | Path | None` and forward it into `lookup_weather`, whose signature declares `str | None`. Passing a `Path` (as `test_send_now_bad_template_aborts` does via `templates_dir=tmp_path`) works at runtime because `load_template` accepts `str | Path`, but the `lookup_weather` annotation is too narrow and a strict type-checker would flag the call. Cosmetic type-contract drift.
**Fix:** Widen `lookup_weather`'s `templates_dir` annotation to `str | Path | None` to match callers and `load_template`.

---

_Reviewed: 2026-06-15T22:51:20Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
