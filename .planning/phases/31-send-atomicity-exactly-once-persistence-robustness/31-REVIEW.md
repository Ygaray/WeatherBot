---
phase: 31-send-atomicity-exactly-once-persistence-robustness
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - weatherbot/weather/store.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/channels/discord.py
  - weatherbot/cli.py
  - weatherbot/scheduler/wiring.py
  - tests/test_store.py
  - tests/test_scheduler.py
  - tests/test_send_now.py
  - tests/test_channel.py
  - tests/conftest.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: resolved
resolved_at: 2026-07-10
resolution: all 6 findings fixed (CR-01+IN-01, WR-01+IN-02, WR-02, WR-03) — see 31-REVIEW-FIX.md
---

# Phase 31: Code Review Report

**Reviewed:** 2026-07-10
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

This is a v2.1 HARDENING phase whose stated purpose is to close silent-failure
seams around send atomicity, exactly-once delivery, and store robustness. The
adversarial review focused on exactly that: the concurrency/atomicity logic in
`daemon.fire_slot`, the secret-leak surface in the Discord auth carrier, the
`fetch_cache` stale-payload risk, and the new `_connect`/`init_db` store discipline.

The good news, verified empirically:

- The Discord 401/403 auth carrier is **secure**: the synthesized
  `httpx.HTTPStatusError` carries a REDACTED URL, `str(exc)` is status-only, both
  `exc.request.url` and `exc.response.request.url` are the placeholder, and
  `.response.status_code` is a real `int` that the hub `is_auth_failure` classifier
  reads correctly (confirmed by running the exact construction). The never-raise
  contract for non-auth non-2xx is preserved.
- `fetch_cache` is a fresh per-fire `list` created inside `fire_slot` and threaded
  into a single `send_now`; there is **no cross-slot / cross-fire leak** and no
  wrong-location reuse — each fire's cache dies with the call.
- `init_db` idempotency, WAL persistence, per-connection `busy_timeout`, and the
  read-no-write-lock (`mode=ro`) discipline all hold; production read paths are all
  `init_db`-guarded so the new "reads can't create the file" behavior never crashes
  a real path.

The bad news: the **F01 fix is one line short of complete**. The swallow that was
added to protect the committed claim wraps `resolve_alert`/`stamp_success` but NOT
the immediately-following `_log.info("slot fired")` + `return result`, both of which
sit inside the broad `except` that releases the claim when `claimed=True`. A raise
from that log call (a real possibility given the custom `_LiveStderr` stderr sink)
re-opens an already-delivered slot → a duplicate briefing on catch-up/restart. This
is exactly the class of bug the phase set out to eliminate. There is also a latent
URI-metacharacter divergence between the read and write connect paths.

## Critical Issues

### CR-01: F01 swallow doesn't cover the post-success log/return — a `_log.info` raise re-opens a delivered claim [RESOLVED 268f578←5ddec50]

**File:** `weatherbot/scheduler/daemon.py:360-407`
**Issue:**
The F01 fix wraps `resolve_alert` + `stamp_success` in a log-and-swallow
`try/except` (lines 360-368) so a post-delivery DB error cannot fall to the broad
`except Exception` at line 377 and trigger `release_claim`. But the very next
statements — `_log.info("slot fired", ...)` (369-375) and `return result` (376) —
are OUTSIDE that swallow yet still INSIDE the broad `try`. The docstring asserts
"No code path after `result.ok` may reach `release_claim`" (line 359), which is
**false**: if `_log.info` raises, control lands in the broad handler with
`claimed=True` and `local_date` set, so it executes `release_claim(...)` (line 384)
— deleting the `sent_log` row of an already-POSTed briefing — and records a false
`internal_error` alert (386).

This is not purely theoretical. The project configures structlog with a custom
`PrintLoggerFactory(file=_LiveStderr())` (`weatherbot/__init__.py:60`), and
`_LiveStderr.write` forwards to `sys.stderr.write` (`__init__.py:51`), which can
raise `BrokenPipeError` / `ValueError: I/O operation on closed file` / `OSError`
when the stderr sink is closed or the pipe is broken (e.g. journald restart, closed
console). The result is the exact defect F01 was created to prevent: a delivered
slot loses its claim → a duplicate briefing fires on the next catch-up scan or
restart.

The regression test `tests/test_scheduler.py:488` (`test_post_send_db_error_keeps_claim`)
only injects the boom into `stamp_success` — which IS inside the swallow — so it
passes and gives false confidence; nothing exercises a raise from the trailing
`_log.info`.

**Fix:** Move the success log inside the swallow (or hoist the `return` above any
post-commit side effect) so no statement after `result.ok` can reach the broad
`except`:

```python
        try:
            resolve_alert(db_path, location.id, slot.time, local_date)
            stamp_success(db_path)
            _log.info(
                "slot fired",
                location=location.name,
                time=slot.time,
                late=late,
                delivered=result.ok,
            )
        except Exception:  # noqa: BLE001 — best-effort; briefing already delivered
            _log.warning(
                "post-send bookkeeping/log failed; briefing already delivered, claim kept",
                location=location.name,
                time=slot.time,
            )
        return result
```

(If the warning log inside the `except` could itself raise, wrap the whole
post-commit tail in `try/except Exception: pass` — the claim must be inviolable once
`result.ok`.) Add a test that monkeypatches `daemon._log.info` (or the stderr sink)
to raise on the "slot fired" event and asserts `was_sent(...) is True` with no
`internal_error` alert.

## Warnings

### WR-01: read-only `_connect` builds a URI by raw string interpolation — a `?`/`#` in `db_path` opens the WRONG (empty) database on reads only [RESOLVED 268f578]

**File:** `weatherbot/weather/store.py:170-171`
**Issue:**
The read-only branch builds the connection string as
`f"file:{db_path}?mode=ro"` and opens it with `uri=True`. SQLite parses the FIRST
`?` in that string as the URI query delimiter, so any `?` (or `#`) inside the actual
path truncates the filename. Verified empirically: a real DB at
`/tmp/wbq/data?evil.db` opened via `file:/tmp/wbq/data?evil.db?mode=ro` returns
`tables seen: []` — SQLite silently opened a different, empty database rather than
the intended file. The four status readers (`was_sent`, `claimed_uv_kinds`,
`read_heartbeat`, `read_health`) would then return wrong defaults; a `was_sent`
answering `False` for an already-sent slot re-opens the exactly-once guard and can
cause a **duplicate briefing**.

Crucially, the WRITE branch uses `sqlite3.connect(db_path)` (no `uri=True`), so it
is immune — creating a read/write path divergence where reads and writes could
target different files for the same `db_path`. The docstring claims `_connect`
"can't SQL-inject the path" but does not address URI metacharacter handling, which
is the actual risk here.

The production default (`data/weatherbot.db`) has no such character, so this is
latent, not currently exploitable — hence WARNING, not BLOCKER. But `db_path` is
config/host-derived and the divergence is a genuine correctness trap.

**Fix:** Percent-encode the path for the URI form (or resolve to an absolute path
and encode), so reads and writes always resolve to the same file:

```python
from urllib.parse import quote

if read_only:
    conn = sqlite3.connect(
        f"file:{quote(str(Path(db_path).resolve()))}?mode=ro", uri=True
    )
```

Alternatively pass the path via the documented `?mode=ro` on an already-encoded
absolute URI, and add a test with a `?`/`#` in the tmp path asserting the read sees
the same rows the write wrote.

### WR-02: the broad-except recovery path in `fire_slot` is itself unguarded — a `release_claim`/`record_alert` DB error escapes the isolation envelope [RESOLVED 0c396ff]

**File:** `weatherbot/scheduler/daemon.py:383-401`
**Issue:**
The broad `except Exception` (the "one bad slot must not kill the thread"
isolation, line 377) calls `release_claim` (384), `record_alert` (386),
`_log.critical` (394), and `_log.exception` (402) with NO surrounding guard. If any
of these raises — most realistically `release_claim`/`record_alert` throwing
`sqlite3.OperationalError("database is locked")`, the exact contention scenario this
phase is hardening against — the exception propagates OUT of `fire_slot`. On the
live cron path APScheduler's worker absorbs it, but `_run_catchup`
(`daemon.py:1189`) calls `fire_slot` in a bare `for` loop with no try/except, so an
unhandled raise from one recovered slot **aborts every remaining catch-up slot** for
that startup — silently dropping briefings the catch-up scan was meant to recover.
This weakens the "minimal per-job isolation" contract the docstring advertises
(line 173).

**Fix:** Wrap the recovery side effects so the handler can never itself raise:

```python
    except Exception:  # noqa: BLE001 — one bad slot must not kill the thread
        try:
            if claimed and local_date is not None:
                release_claim(db_path, location.id, slot.time, local_date)
            if local_date is not None:
                self_first = record_alert(
                    db_path, location.id, slot.time, local_date, REASON_INTERNAL_ERROR
                )
                if self_first:
                    _log.critical("briefing_missed", ...)
        except Exception:  # noqa: BLE001 — recovery must never re-raise past isolation
            _log.warning("fire_slot recovery bookkeeping failed", location=location.name)
        _log.exception("slot fire failed", location=location.name, time=slot.time)
        return None
```

Additionally, `_run_catchup` should defensively wrap each `fire_slot` call so one
slot's escape can never abort the scan.

### WR-03: `fire_forecast_slot` treats a delivery-auth 401/403 as a mere transient failure, muting the auth signal on the forecast path [RESOLVED d495815]

**File:** `weatherbot/scheduler/daemon.py:576-587, 600-622`
**Issue:**
The F08 fix correctly inspects `fc_result.ok` for a Discord non-2xx. But when the
forecast delivery hits a REVOKED webhook, `channel.send(reply.text)` now RAISES
`httpx.HTTPStatusError` (the DELIV-04 auth carrier added to `discord.py` in this same
phase) rather than returning `ok=False`. That raise skips the `if not fc_result.ok`
arm entirely and lands in the broad `except Exception` (line 600), which logs a
generic "forecast slot fire failed" and bumps the same failure streak as any
transient blip. So a *permanent* auth misconfiguration on the forecast channel is
indistinguishable from a transient network blip and only surfaces after
`_FORECAST_DEAD_AFTER` (3) consecutive fires — three missed forecasts — instead of
immediately. The briefing path deliberately distinguishes `auth_failed` from
`transient_exhausted` (`fire_slot:278-282`); the forecast path silently collapses
the distinction, which is weaker than the project's "retry then alert rather than
silently miss" constraint for the auth case.

This is WARNING (not BLOCKER) because the forecast path is read-only and the
dead-slot escalation does eventually fire — but it delays operator-visible signal on
a permanent fault and is a new seam introduced by pairing the F08 inspection with
the DELIV-04 raise.

**Fix:** In `fire_forecast_slot`, catch `httpx.HTTPStatusError` around the
`channel.send` and, when `is_auth_failure(exc)`, emit the CRITICAL `forecast_slot_dead`
escalation immediately (bypassing the streak) rather than folding it into the generic
transient handler:

```python
        if channel is not None:
            try:
                fc_result = channel.send(reply.text)
            except httpx.HTTPStatusError as exc:
                if is_auth_failure(exc):
                    _log.critical("forecast_slot_dead", location=location.name,
                                  kind=fc.kind, reason="auth_failed", severity="critical")
                    return None
                raise
            if fc_result is not None and not fc_result.ok:
                ...
```

## Info

### IN-01: F01 regression test does not cover the actual gap it guards [RESOLVED 5ddec50]

**File:** `tests/test_scheduler.py:488-558`
**Issue:**
`test_post_send_db_error_keeps_claim` injects the failure into `stamp_success`,
which is INSIDE the F01 swallow, so it exercises the covered branch only. It gives
green-but-hollow confidence for CR-01: the uncovered raise site is the trailing
`_log.info("slot fired")`. Once CR-01 is fixed, add a sibling test that patches the
success-path log (or the stderr sink) to raise and asserts the claim survives and no
`internal_error` alert is written.
**Fix:** Add the missing-branch test alongside the CR-01 fix (snippet in CR-01).

### IN-02: `_connect` docstring overclaims the read-only safety guarantee [RESOLVED 268f578]

**File:** `weatherbot/weather/store.py:157-175`
**Issue:**
The docstring says the read-only branch means "any accidental write raises ...
instead of silently mutating" and centralizes "all store connect discipline" and
that it "can't SQL-inject the path" — but it is silent on URI metacharacter parsing
(WR-01), which is the real path-handling hazard for the `uri=True` branch. A future
reader will trust the docstring and not re-examine the interpolation.
**Fix:** After fixing WR-01, note in the docstring that the read-only path
percent-encodes `db_path` before URI construction so a `?`/`#` in the path cannot
truncate the target file.

---

_Reviewed: 2026-07-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
