---
phase: 03-always-on-scheduler
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - weatherbot/scheduler/days.py
  - weatherbot/scheduler/context.py
  - weatherbot/scheduler/catchup.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/scheduler/__init__.py
  - weatherbot/config/models.py
  - weatherbot/weather/store.py
  - weatherbot/cli.py
  - templates/renderer.py
  - tests/test_scheduler.py
  - tests/test_send_now.py
  - tests/test_renderer.py
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-10
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Phase 03 adds an APScheduler-based daemon (`weatherbot --run`), a pure catch-up
planner, a `sent_log` dedup table, and a render-boundary timing seam. The SQL is
correctly parameterized throughout (no injection found), and the `INSERT OR
IGNORE`/`UNIQUE` design gives genuine idempotency at the database layer. The
template renderer is properly hardened against format-string injection.

However, the exactly-once-across-DST guarantee — explicitly called out as a goal
of this phase — does **not** hold for slots that fall inside or near a DST
transition, because the catch-up planner builds scheduled instants with
`datetime.replace(hour=, minute=)`, which produces wrong/ambiguous UTC offsets in
the spring-forward gap and the fall-back fold. The DST tests only exercise a
07:00 slot (far outside the 01:00–02:59 transition band), so they assert
"exactly once" without ever testing a transition-band slot — the tests give false
confidence. There is also a check-before-fire / record-after-success race window
that is real (concurrent live-cron + catch-up, or two coalesced misfires) and
only partially mitigated. The remaining findings are robustness and
maintainability issues.

## Critical Issues

### CR-01: Catch-up planner mis-computes scheduled instant across DST transitions (exactly-once breaks)

**File:** `weatherbot/scheduler/catchup.py:137-140`
**Issue:**
`plan_catchup` builds the slot's intended instant with:

```python
now_local = now_utc.astimezone(tz)
...
scheduled = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
if scheduled > now_local:        # not due yet
    continue
if now_local - scheduled > GRACE:  # > 90 min late — skip
    continue
```

`datetime.replace()` keeps `now_local`'s `tzinfo`/`fold` but does **not**
re-resolve the UTC offset for the new wall-clock time. Two failure modes:

1. **Spring-forward gap** — a slot whose `HH:MM` falls in the skipped hour
   (e.g. `02:30` on `America/New_York` 2026-03-08, where 02:00→03:00 is skipped)
   does not exist. `replace()` yields `02:30-05:00` (pre-transition offset) even
   though the scan is running at `03:15-04:00`. The `now_local - scheduled`
   arithmetic is then computed against a phantom instant, so the grace-window and
   "due yet?" comparisons are off by the one-hour DST delta. Verified locally:
   scanning at 03:15 EDT for a 02:30 slot yields `delta = 0:45`, masking the fact
   that the wall-clock slot never occurred.
2. **Fall-back fold** — a slot whose `HH:MM` falls in the repeated hour (e.g.
   `01:30` on 2026-11-01, which occurs twice) is ambiguous. `replace()` does not
   set `fold`, so `scheduled` adopts an arbitrary one of the two offsets.
   Verified locally: scanning at the second 01:15 (`-05:00`) for a 01:30 slot
   produced `delta = -1 day, 23:45:00` (a *negative-day* timedelta), which means
   `scheduled > now_local` evaluates true and the slot is treated as "not due yet"
   — it will never be caught up, and depending on which fold the live CronTrigger
   chose, it may be dropped entirely or fired twice.

This directly defeats the phase's stated "exactly-once delivery (including across
DST transitions)" requirement. The planner and the live trigger can silently
disagree precisely on the days the DST handling was supposed to protect.

**Fix:** Build the scheduled instant by composing a naive wall-clock datetime and
attaching the zone so the offset is resolved correctly, and normalize the gap
case explicitly:

```python
from datetime import datetime

# Compose the intended wall-clock instant, then re-resolve its offset in tz.
naive = datetime(now_local.year, now_local.month, now_local.day, hh, mm)
scheduled = naive.replace(tzinfo=tz)  # tz resolves the correct offset/fold

# Detect a spring-forward gap: a wall-clock time that does not exist round-trips
# to a different wall-clock value.
if scheduled.astimezone(tz).replace(tzinfo=None) != naive:
    # Slot fell in the skipped hour; APScheduler's CronTrigger will also skip it,
    # so the planner must agree and not synthesize a phantom catch-up.
    continue
```

Then compare `scheduled` against `now_utc` (compare the two *aware* instants
directly, never two wall-clock-derived locals). Add explicit tests with a slot
time of `02:30` on 2026-03-08 and `01:30` on 2026-11-01 (not just 07:00) to lock
the behavior.

### CR-02: Check-before-fire / record-after-success is not atomic — duplicate sends under concurrency

**File:** `weatherbot/scheduler/daemon.py:96-123` (with `weatherbot/weather/store.py:191-235`)
**Issue:**
`fire_slot` does a read (`was_sent`) on one SQLite connection, then later a write
(`record_sent`) on a *separate* connection, with a network fetch + delivery in
between. The dedup `UNIQUE` constraint prevents a duplicate *row*, but it does
**not** prevent a duplicate *delivery*: two concurrent firings for the same slot
both pass `was_sent` (neither has recorded yet), both fetch + deliver the
briefing, and both then `INSERT OR IGNORE` (one inserts, one is ignored) — but the
user has received two Discord messages. This is a real window in this phase:

- The catch-up scan in `_run_catchup` runs `fire_slot` for a missed slot at the
  same wall-clock minute the live `CronTrigger` job is scheduled to fire it.
  `_run_catchup` runs *before* `scheduler.start()` (`daemon.py:282-289`), but the
  catch-up delivery does a synchronous network fetch; if it is still in flight
  when `start()` schedules an immediately-due job, both can fire.
- APScheduler `BackgroundScheduler` runs jobs on a thread pool, so two near-
  simultaneous fires of the same job id (e.g. a fall-back-repeated minute) are
  possible.

`record_sent` being idempotent (a good property, store.py:213-235) only protects
the table, not the side-effecting delivery. The class docstring claims
"exactly-once delivery"; this guarantees at-most-once *rows* but allows
duplicate *messages*.

**Fix:** Make the claim/record atomic so the delivery is gated on winning the
insert, not on a prior read. Insert a "claim" row *before* delivering, using the
`UNIQUE` constraint to arbitrate, and only deliver if this process won the claim:

```python
def claim_slot(db_path, location_name, send_time, local_date) -> bool:
    """Atomically claim a slot; returns True iff THIS caller won the insert."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        cur = conn.execute(
            "INSERT OR IGNORE INTO sent_log "
            "(location_name, send_time, local_date, sent_at_utc) VALUES (?,?,?,?)",
            (location_name, send_time, local_date, int(time.time())),
        )
        conn.commit()
        return cur.rowcount == 1
```

Then in `fire_slot`, gate delivery on `claim_slot(...)` and, on a delivery
failure, *delete* the claim so the slot is re-fireable (preserving the
mark-after-success intent for the failure case). Document the trade-off
explicitly if you keep the current read-then-write design — but as written the
exactly-once-delivery claim is incorrect.

## Warnings

### WR-01: DST tests assert "exactly once" but never exercise a transition-band slot

**File:** `tests/test_scheduler.py:248-264`
**Issue:**
`test_dst_exactly_once` uses a `07:00` slot on the spring-forward and fall-back
days. 07:00 is far outside the 01:00–02:59 transition band, so the test passes
trivially and proves nothing about DST. The test name and the catchup module
docstring ("DST exactly-once") both imply coverage that does not exist. This is
how CR-01 shipped undetected.

**Fix:** Add cases with slot times inside the affected hours — `02:30` on
2026-03-08 (gap) and `01:30` on 2026-11-01 (fold) — and assert the planner emits
each missed slot exactly once (and agrees with what the live `CronTrigger` would
fire). These tests should currently *fail* against the code as written, which is
the point.

### WR-02: Job id keyed on raw `days` lets a config rename re-fire an already-sent slot

**File:** `weatherbot/scheduler/daemon.py:182` and `catchup.py:143`
**Issue:**
The APScheduler job id is `f"{location.name}|{slot.time}|{slot.days}"` — the
**raw** `days` string. The `sent_log` dedup key, however, is
`(location_name, send_time, local_date)` — it does **not** include `days`. If a
user edits `days = "weekends"` to `days = "sat,sun"` (semantically identical,
normalizes to the same `day_of_week`), the job id changes but the dedup key does
not — harmless. But the inverse mismatch is the real problem: the job id and the
catch-up planner both treat `time` as the slot identity for dedup, yet the job id
includes `days` while dedup does not. Two slots at the same `time` with different
`days` that both fire on the same date (e.g. `mon-fri` and `sat,sun` can't
overlap, but `mon,wed,fri` and `mon-fri` both fire Monday) collapse to the **same
dedup key** `(loc, time, date)` — so the second slot is silently suppressed as
"already sent" even though it is a distinct configured slot.

**Fix:** Include the slot's normalized `day_of_week` (or a stable slot index) in
the dedup key so two slots sharing a `time` on the same date are not conflated:
`UNIQUE(location_name, send_time, day_of_week, local_date)` — and thread
`day_of_week` through `was_sent`/`record_sent`/`plan_catchup`. At minimum,
document that two enabled slots at the same `time` for one location are
unsupported and validate against it at load.

### WR-03: `was_sent` / `record_sent` run `executescript(_SCHEMA)` on every call

**File:** `weatherbot/weather/store.py:203-209, 227-235`
**Issue:**
Every dedup read and every record re-runs the full multi-table
`executescript(_SCHEMA)` (4 `CREATE TABLE` + 9 `CREATE INDEX` statements). On the
hot `fire_slot` path this executes the schema script twice per fire (once in
`was_sent`, once in `record_sent`) plus once more inside `persist`
(store.py:169). `executescript` also issues an implicit `COMMIT` before running,
which can interfere with surrounding transaction intent. This is defensive but
wasteful and couples every read to DDL.

**Fix:** Call `init_db(db_path)` once at daemon startup (in `run_daemon`, before
`_register_jobs`) and have `was_sent`/`record_sent` assume the schema exists.
Keep a lightweight `CREATE TABLE IF NOT EXISTS sent_log (...)` guard if you want
the helpers to remain standalone, rather than the whole `_SCHEMA`.

### WR-04: SIGTERM handler installed only on the main thread, after a blocking window

**File:** `weatherbot/scheduler/daemon.py:289-301`
**Issue:**
`scheduler.start()` (line 289) and the catch-up scan (line 282, which performs
synchronous network fetches and deliveries) both run *before* the SIGTERM handler
is installed (line 297). A SIGTERM arriving during the catch-up burst — plausible
on a systemd `stop`/restart right after boot — uses the default disposition
(terminate) and the scheduler is never shut down cleanly; in-flight jobs are not
drained and `_log.info("daemon stopped")` never runs. Also, `signal.signal` can
only be called from the main thread; if `run_daemon` were ever invoked off the
main thread (e.g. embedded), this raises `ValueError` and the daemon never
arms its shutdown path.

**Fix:** Install the signal handler *before* the catch-up scan and `start()`
(register `stop` first, then do the work, then `stop.wait()`), and guard the
`signal.signal` call so a non-main-thread invocation degrades gracefully (e.g.
catch `ValueError` and rely on `KeyboardInterrupt`/external shutdown).

### WR-05: Catch-up planner never persists a "skipped (too late)" record despite docstring

**File:** `weatherbot/scheduler/catchup.py:33-34, 140`
**Issue:**
The module docstring and the D-04 comment state: "A slot whose local scheduled
time passed more than this ago is skipped **+ logged**." The implementation at
line 140 just `continue`s — there is no log, no record, no signal that a briefing
was permanently missed. For a reliability-focused bot whose core promise is
"reliably receives ... without lifting a finger," a silently-dropped briefing
(host was off >90 min over the slot) is exactly the failure the user must be
alerted to (CLAUDE.md: "must retry and then alert rather than silently miss a
briefing"). The planner is `structlog`-free by design, but the caller `_run_catchup`
has no visibility into skipped slots either.

**Fix:** Have `plan_catchup` also return (or the daemon compute) the
beyond-grace-but-due-today slots and emit a `_log.warning("briefing missed",
location=..., time=..., scheduled=...)` in `_run_catchup`, so a missed morning is
observable rather than silent. At minimum, fix the docstring to match the code if
silent-skip is genuinely intended.

### WR-06: `fire_slot` recomputes `local_date` from "now" for the live job, risking a midnight off-by-one

**File:** `weatherbot/scheduler/daemon.py:88-93`
**Issue:**
For a live cron fire, `scheduled_dt` is `None` (the daemon's `_register_jobs`
passes no `scheduled_dt` kwarg), so `local_date` is computed from
`datetime.now(tz)` at the moment the job thread actually runs. If the job fires at
`23:59` but the thread is delayed past local midnight (GC pause, thread-pool
contention, a slow preceding job), `local_date` rolls to the next day and the
dedup key no longer matches what a same-night catch-up or a retry would compute —
opening a duplicate-send window around midnight. APScheduler can pass the intended
run time to the job; using "now" discards it.

**Fix:** Pass the trigger's scheduled run time into `fire_slot` for live jobs too.
APScheduler can inject it (e.g. add a `run_time` param and read
`apscheduler.get_job` / use an event listener, or compute `local_date` from the
job's `next_run_time` captured at schedule build). Deriving `local_date` from the
intended instant (as the catch-up path already does) makes the live and recovery
paths consistent.

## Info

### IN-01: `_fmt` parameter typed `ZoneInfo` but called with `None`-narrowed value only

**File:** `weatherbot/scheduler/context.py:45-47, 69-72`
**Issue:**
`_fmt(dt, tz: ZoneInfo)` is only ever called when `tz is not None` (guarded at
the call sites), which is correct, but the duplicated
`_fmt(...) if tz is not None else ....strftime(...)` ternary appears twice
(lines 69 and 70-72) and is mildly error-prone to keep in sync. Minor
readability/DRY issue.

**Fix:** Extract a small `_fmt_in(dt, tz_or_none)` helper that internally branches
on `None`, so the sent/checked formatting is expressed once.

### IN-02: `checked_at` is a fabricated "now", not the real fetch instant

**File:** `weatherbot/cli.py:144-146`
**Issue:**
`checked_dt = datetime.now(tz)` is taken at render time, after fetch + persist, so
`{checked_at}` is a freshness *proxy*, not the actual OpenWeather fetch instant.
The inline comment acknowledges this ("a fetched_at field would be needed for
exact fidelity; out of scope"). For a recovered *late* send (catch-up), the gap
between the real fetch and render is small, so this is low-impact — but a user
reading `{checked_at}` may believe it is the data timestamp. Documented as
out-of-scope, flagged for traceability.

**Fix:** When `Forecast` later exposes its fetch instant, thread it through to
`checked_dt`. No action required this phase.

### IN-03: Broad `except Exception` swallows all errors in `fire_slot` and `do_check`

**File:** `weatherbot/scheduler/daemon.py:133`, `weatherbot/cli.py:269`
**Issue:**
Both sites catch bare `Exception` (annotated `# noqa: BLE001`). In `fire_slot`
this is a deliberate per-job isolation decision (documented, Phase 4 will harden),
and `do_check` intentionally surfaces any failure as exit 1 — both acceptable. The
note is that a `KeyboardInterrupt`/`SystemExit` raised inside a job thread is not
caught (they are not `Exception` subclasses), which is correct, but a
programming bug (e.g. `AttributeError`) inside `fire_slot` is now indistinguishable
in logs from an expected delivery failure — only `error=str(exc)` is logged, no
type, no traceback.

**Fix:** Include `error_type=type(exc).__name__` (and consider
`_log.exception(...)` to capture the traceback) so a genuine code bug in a fired
slot is diagnosable in the multi-day unattended logs the project explicitly wants.

### IN-04: `_announce_schedule` and `_register_jobs`/`_run_catchup` re-walk the same nested loop with duplicated enabled/zone logic

**File:** `weatherbot/scheduler/daemon.py:161-185, 202-221`
**Issue:**
The `for location ... for slot ... if not slot.enabled: continue` walk plus the
`f"{location.name}|{slot.time}|{slot.days}"` id construction is duplicated between
`_register_jobs` (line 161-182) and `_announce_schedule` (line 202-207). A change
to the id format or the enabled rule must be made in two places or they silently
diverge.

**Fix:** Factor the slot id into a single helper (e.g.
`_job_id(location, slot)`) and iterate enabled `(location, slot)` pairs through
one shared generator so registration and announcement cannot drift.

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
