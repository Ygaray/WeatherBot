---
phase: 04-retry-then-alert-reliability
reviewed: 2026-06-11T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - weatherbot/reliability/retry.py
  - weatherbot/reliability/__init__.py
  - weatherbot/weather/store.py
  - weatherbot/config/models.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/cli.py
  - tests/test_reliability.py
  - tests/test_store.py
  - tests/test_config.py
  - tests/test_cli.py
  - config.example.toml
  - pyproject.toml
findings:
  critical: 1
  warning: 5
  info: 4
  total: 10
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-06-11T00:00:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Reviewed the Phase-4 reliability layer: the two-burst retry engine
(`reliability/retry.py`), the SQLite alert/heartbeat/claim store
(`weather/store.py`), the `Reliability` config model, the daemon `fire_slot`
patient path + lifecycle (`scheduler/daemon.py`), and the manual `run_send_now`
tight-retry path (`cli.py`), with their tests.

The core mechanisms are largely sound and well-tested: claim-before-fire is
atomic (`INSERT OR IGNORE` + `rowcount`), the alert dedup is structurally correct
(`UNIQUE(location, slot, date)` + `rowcount==1` gate), the mid-pause is wired to
`stop_event.wait` for SIGTERM interruptibility, `Retry-After` is honored AND
capped, the manual path is verifiably free of alerts/heartbeat writes, and secret
hygiene holds (no `appid`/host/webhook in any persisted row or log field).

However there is a genuine **correctness defect**: the `Reliability` validator
accepts `attempts_per_burst = 1`, but the retry wait callable divides by
`burst_size - 1` and raises `ZeroDivisionError` on the second attempt — a
config-reachable crash that the daemon then mis-classifies as `internal_error`.
Several warnings concern budget-claim divergence between the docstring/config
guard and the actual jittered worst case, a config knob the engine silently
ignores, and a duplicated test-isolation gap. Details below.

## Critical Issues

### CR-01: `attempts_per_burst = 1` is config-valid but crashes the retry wait callable (ZeroDivisionError)

**File:** `weatherbot/reliability/retry.py:125-127` (with `weatherbot/config/models.py:154-159`)
**Issue:**
`Reliability._must_be_positive` only rejects values `<= 0`, so
`attempts_per_burst = 1` loads cleanly. `build_retrying` then passes
`burst_size=1` into the wait closure. `_within_burst_wait` computes
`step = burst_spread_s / (burst_size - 1)` → `600 / 0` → `ZeroDivisionError`.

Trace with `attempts_per_burst = 1`: `stop_after_attempt(2 * 1)` allows attempts
1 and 2. Attempt 1 hits `attempt_number == burst_size (1)` and returns the
mid-pause (no division). On a transient failure, the wait for attempt 2 takes the
`else` branch and divides by `burst_size - 1 == 0`:

```
$ attempts_per_burst=1, transient on attempt 2
1 -> 2700      (mid-pause branch, ok)
2 -> ZeroDivisionError: division by zero
```

In the daemon this is swallowed by `fire_slot`'s broad `except Exception`, so the
thread survives — but the failure is recorded as `reason=internal_error` instead
of `transient_exhausted`, and NO briefing is ever attempted past attempt 1. A
user who tunes `[reliability] attempts_per_burst = 1` (a perfectly reasonable
"try, pause, try once more" intent) silently gets a broken retry path and a
mislabeled alert. This is the exact "fail loud at load, never at 9am" contract the
`Reliability` model exists to enforce — and it leaks through.

**Fix:** Reject `attempts_per_burst < 2` in the validator (the two-burst spread
math is undefined for a single attempt per burst), OR special-case `burst_size == 1`
in `_within_burst_wait` to skip the spread:

```python
# config/models.py
@field_validator("attempts_per_burst")
@classmethod
def _attempts_at_least_two(cls, v: int) -> int:
    if v < 2:
        raise ValueError(
            f"attempts_per_burst must be >= 2 (the burst spread is undefined "
            f"for a single attempt), got {v!r}"
        )
    return v
```

(Keep the existing `> 0` validator for the two seconds fields.) Add a test asserting
`Reliability(attempts_per_burst=1)` raises.

## Warnings

### WR-01: Config budget guard understates the real worst case by ~10 minutes (jitter + within-burst waits are not counted)

**File:** `weatherbot/config/models.py:161-170` (and the docstring claim at `retry.py:62-65`)
**Issue:**
`_budget_under_grace` checks `2 * burst_spread_seconds + mid_pause_seconds < 5400`.
But that sum is NOT the actual schedule duration. The real worst-case wall-clock
budget also includes the 14 within-burst waits, each of which is
`step + uniform(0, step*0.5)` (jittered UP, never down). With the defaults:

```
step              = 600 / 7      = 85.7 s
within-burst max  = step * 1.5   = 128.6 s
14 within-burst waits + mid-pause = 14*128.6 + 2700 = 4500 s = 75 min
guard value (2*600 + 2700)        = 3900 s = 65 min
```

So the guard's "65 min, comfortably under 90 min" claim (docstring `retry.py:60-65`,
`config.example.toml:77`) is ~10 minutes optimistic. With the defaults there is
still headroom, but a user who tunes the budget right up against the guard's 5400s
limit can produce a real schedule that overruns the 90-minute catch-up grace — the
exact failure the guard is supposed to prevent (Pitfall 5). The capped `Retry-After`
waits (`<= 120s` each, up to 14 of them) push it further still.

**Fix:** Make the guard reflect the schedule it bounds — count the max within-burst
contribution and a `Retry-After` allowance:

```python
@model_validator(mode="after")
def _budget_under_grace(self) -> Reliability:
    n = self.attempts_per_burst
    within_step = self.burst_spread_seconds / (n - 1)  # requires CR-01 fix (n>=2)
    within_max = within_step * 1.5                      # jitter ceiling
    worst = (2 * n - 2) * within_max + self.mid_pause_seconds
    if worst >= _CATCHUP_GRACE_SECONDS:
        raise ValueError(...)
    return self
```

### WR-02: `RETRY_AFTER_CAP_S` honoring is excluded from the budget guard entirely

**File:** `weatherbot/reliability/retry.py:65` / `weatherbot/config/models.py:161-170`
**Issue:**
A 429 path can add up to `RETRY_AFTER_CAP_S` (120s) on EACH retry instead of the
within-burst base. Across up to 14 retries that is an extra ~28 min worst case that
the `_budget_under_grace` guard never accounts for. The docstring at `retry.py:62-64`
asserts "Total worst case ... stays comfortably under 90 min" while explicitly
ignoring this term. With defaults the engine can therefore exceed 90 minutes on a
sustained 429 storm with capped `Retry-After`, breaching the very budget the module
documents as load-bearing.

**Fix:** Either fold the `Retry-After` ceiling into the WR-01 guard
(`+ (2*n - 2) * RETRY_AFTER_CAP_S` is too conservative; a tighter model is
`max(within_max, RETRY_AFTER_CAP_S)` per retry), or lower `RETRY_AFTER_CAP_S` and
document the true bound. At minimum, correct the docstring so it does not claim a
guarantee the code does not enforce.

### WR-03: `attempts_per_burst` config value is partly ignored — the `_before_sleep` burst index uses the module constant, not the configured size

**File:** `weatherbot/reliability/retry.py:163-170`
**Issue:**
`build_retrying` correctly threads the configured `attempts_per_burst` into the
wait closure and `stop_after_attempt`, but `_before_sleep` is a module-level
function that hard-codes `burst=1 if attempt <= BURST_SIZE else 2` against the
constant `BURST_SIZE = 8`. If a user sets `attempts_per_burst = 4`, the retry log
will report `burst=1` for attempts 1-8 even though burst 2 actually starts at
attempt 5. This is the diagnostic signal a multi-day unattended operator relies on
to reconstruct "which burst was the 9am send in" — and it lies whenever the config
diverges from the default.

**Fix:** Build `_before_sleep` as a closure over `attempts_per_burst` inside
`build_retrying` (mirroring `_wait`), or pass the size:

```python
def _before_sleep(retry_state) -> None:
    attempt = retry_state.attempt_number
    _log.info("retry_attempt", attempt=attempt,
              burst=1 if attempt <= attempts_per_burst else 2)
```

### WR-04: `send_now` re-runs `persist` (a DB write) on every retry attempt, inflating `weather_onecall` rows for one logical briefing

**File:** `weatherbot/cli.py:127-136` invoked from `weatherbot/scheduler/daemon.py:176-191`
**Issue:**
The daemon wraps the WHOLE of `send_now` in the two-burst retry via `_attempt()`.
`send_now` fetches both units AND calls `persist(db_path, location, forecast)`
before delivery. So a slot that fails delivery 5 times then succeeds writes
`persist` 6 times — i.e. up to `2 * (2*BURST_SIZE)` = 32 `weather_onecall` rows
(2 unit variants × 16 attempts) for ONE briefing, each from a fresh fetch. That is
both extra OpenWeather calls on the retry path (against the documented quota
discipline) and duplicate analysis rows that will skew the deferred
forecast-vs-actual join the store header advertises. The retry is meant to retry
*delivery*; it also blindly re-runs *fetch + persist*.

**Fix:** This is a design seam decision, but at minimum the duplicate persist on a
pure delivery retry should be avoided — e.g. split fetch+persist (idempotent for a
given slot/day) from deliver, and retry only the deliver step; or de-duplicate
`weather_onecall` on `(location, target_local_date, units)` for a given fetch
round. Confirm this is intended before shipping; the store's "v2 accuracy join
needs no migration" claim assumes one row per fetch, not per retry attempt.

### WR-05: `parse_retry_after` can raise `TypeError`/`ValueError` on a malformed HTTP-date `Retry-After`, escaping the wait callable into the broad handler

**File:** `weatherbot/reliability/retry.py:107-115`
**Issue:**
`parse_retry_after` catches only `ValueError` from `float(ra)`, then calls
`parsedate_to_datetime(ra)`. For a malformed date string `parsedate_to_datetime`
can return `None` (→ `None - datetime` raises `TypeError`) or raise `ValueError`
itself depending on input. `Retry-After` is explicitly called out as untrusted
input (V5, `retry.py:104`). An unhandled raise here propagates out of `two_burst_wait`
→ out of tenacity's wait step → in the daemon it is caught by `fire_slot`'s broad
`except Exception` and mislabeled `internal_error` (no further retry); on the manual
path it escapes `run_send_now` uncaught and crashes the CLI.

**Fix:** Treat any parse failure as "no usable header":

```python
try:
    secs = float(ra)
except ValueError:
    try:
        dt = parsedate_to_datetime(ra)
        if dt is None:
            return None
        secs = (dt - datetime.now(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return None
```

## Info

### IN-01: `do_check` 401/403 reachability probe is NOT retried, but a 429 probe IS unhandled

**File:** `weatherbot/cli.py:343-356`
**Issue:**
The reachability probe in `do_check` re-raises any non-401/403 `HTTPStatusError`
(including 429/5xx) up into the broad `except Exception` at line 357, which reports
`config check failed`. That is acceptable for `--check`, but a transient 429 during
a `--check` will read to the user as "your config is broken" rather than "rate
limited, retry." Consider distinguishing transient probe failures from config
failures in the message.

### IN-02: Heartbeat success path never stamps `last_tick`, so a freshly-started daemon that immediately succeeds shows `last_tick=NULL` until the first interval tick

**File:** `weatherbot/scheduler/daemon.py:262, 301-314`
**Issue:**
`fire_slot` success stamps `last_success` only; `last_tick` is stamped solely by
the 10-min `_heartbeat_tick` interval job. For up to the first `HEARTBEAT_INTERVAL_S`
(600s) after startup, a monitor reading `last_tick IS NULL` while `last_success` is
fresh sees a contradictory liveness state. Minor, but the heartbeat semantics
("crashed vs alive-but-failing") lean on `last_tick` freshness. Consider stamping a
tick once at `run_daemon` startup (right after `scheduler.start()`).

### IN-03: Duplicated `_connect` helper and secret-grep convention copied across test modules

**File:** `tests/test_reliability.py:54-58`, `tests/test_store.py:41-44`
**Issue:**
`_connect` and the `appid`/`api.openweathermap.org` grep assertion are copy-pasted
between test files (the reliability file even documents the copy in its module
docstring). Not a defect, but a shared `tests/conftest.py` helper would prevent
drift if the secret-hygiene token set changes.

### IN-04: `test_check_surfaces_retry_budget` calls `capsys.readouterr()` twice, discarding the first capture

**File:** `tests/test_cli.py:459`
**Issue:**
`out = capsys.readouterr().out + capsys.readouterr().err` — the first
`readouterr()` consumes and clears the buffer, so `.err` from the second call is
empty and `.out` from it is empty too. The assertions happen to pass because the
budget values are on stdout (captured by the first call's `.out`), but the `.err`
half is dead. Use a single `captured = capsys.readouterr()` then
`captured.out + captured.err`.

---

_Reviewed: 2026-06-11T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
