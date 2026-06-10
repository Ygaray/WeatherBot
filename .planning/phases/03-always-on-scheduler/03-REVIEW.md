---
phase: 03-always-on-scheduler
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - weatherbot/scheduler/catchup.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/weather/store.py
  - tests/test_scheduler.py
findings:
  critical: 1
  warning: 4
  info: 2
  total: 7
status: issues_found
---

# Phase 3: Code Review Report (Gap-Closure)

**Reviewed:** 2026-06-10
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Adversarial re-review of the two gap-closure fixes:
- **03-04** — DST-correct scheduled-instant construction in `plan_catchup`.
- **03-05** — atomic `claim_slot`/`release_claim` (delivery-level exactly-once) in `fire_slot` + store.

**03-05 (atomic claim) is correct.** The `INSERT OR IGNORE` + `rowcount == 1`
arbitration was verified against SQLite directly: exactly one `True` per key,
release re-opens the slot, the claim gates the network send, and the
release-on-failure / release-on-exception paths only ever undo a claim THIS
caller won (guarded by `claimed and local_date is not None`). For the actual
in-process threat model (APScheduler `BackgroundScheduler` thread overlapping
the startup catch-up scan) this closes the gap. One durability edge (crash
between claim-commit and send) is a WARNING, not a blocker.

**03-04 (DST spring-forward gap skipping) is BROKEN.** The documented round-trip
gap detector never fires for a spring-forward gap, so a non-existent wall-clock
slot (e.g. `02:30` on 2026-03-08) is emitted as a phantom catch-up fire under
realistic scan timing. The transition-band test passes only because it scans at
an instant where an unrelated "not due yet" branch happens to mask the bug — the
test does not actually exercise gap detection. This is the headline finding.

## Critical Issues

### CR-01: Spring-forward gap detection in `plan_catchup` never triggers — phantom catch-up fire

**File:** `weatherbot/scheduler/catchup.py:150-156`

**Issue:** The gap-skip guard is:

```python
naive = datetime(now_local.year, now_local.month, now_local.day, hh, mm)
scheduled = naive.replace(tzinfo=tz)
if scheduled.astimezone(tz).replace(tzinfo=None) != naive:
    continue
```

`scheduled.astimezone(tz)` is a no-op for an already-`tz`-aware datetime — it
returns the same instant with the same `tzinfo`, so `.replace(tzinfo=None)`
always equals `naive`. The comparison is therefore **always `False`**, and the
spring-forward branch is dead. For a wall-clock time that never existed (the DST
spring-forward gap), `datetime(...).replace(tzinfo=tz)` silently resolves to the
*pre-transition* offset (EST, `-05:00`) instead of detecting that the time is
invalid.

Concretely, for a `02:30` daily slot on 2026-03-08 (`America/New_York`), `02:00 →
03:00` is skipped, so `02:30` never occurs:
- `naive.replace(tzinfo=NY)` → `02:30:00-05:00` → `07:30:00 UTC`.
- Round-trip check returns `True` (no skip).
- The test scans at `03:15` local (`07:15 UTC`), where `scheduled (07:30 UTC) >
  now (07:15 UTC)` is `True`, so the slot is dropped by the **"not due yet"**
  branch at line 158 — masking the broken gap detector.

Move the scan just 15 minutes later — `03:45` local (`07:45 UTC`, still inside
the 90-min grace) — and the slot is **emitted as a phantom `MissedSlot`** for a
time that never existed and that the live `CronTrigger` will never fire. Verified:

```
scan utc      : 2026-03-08 07:45:00+00:00   (03:45 local, within grace)
gap detected? : False        # the broken guard
scheduled > scan (not-due)? : False
now - scheduled > GRACE?     : False (0:15:00)
==> phantom MissedSlot emitted: True
```

This is a correctness defect: a recovery burst would deliver a briefing stamped
with a non-existent intended time, in disagreement with the live trigger — the
exact "planner must agree with `CronTrigger`" invariant the fix claims to
establish.

**Fix:** Detect the gap by comparing the two folds' offsets (a non-existent time
has *different* `utcoffset()` for `fold=0` vs `fold=1` AND round-trips forward
through UTC), not by the no-op `astimezone(tz)` round-trip:

```python
naive = datetime(now_local.year, now_local.month, now_local.day, hh, mm)
# Spring-forward GAP: a non-existent wall-clock time has different offsets for
# the two folds; normalizing through UTC and back changes the wall clock.
off0 = naive.replace(tzinfo=tz, fold=0).utcoffset()
off1 = naive.replace(tzinfo=tz, fold=1).utcoffset()
scheduled = naive.replace(tzinfo=tz)  # fold=0 (first/EDT occurrence on fall-back)
roundtrip = scheduled.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
if off0 != off1 and roundtrip != naive:
    continue  # gap time — never existed; the live CronTrigger skips it.
```

The verified behavior of the corrected detector:
- gap `02:30` (2026-03-08): `off0 != off1` True, UTC round-trip wall-clock
  changes → **skipped** (correct).
- normal `07:00`: offsets equal → kept.
- fold `01:30` (2026-11-01): offsets differ but UTC round-trip wall-clock is
  unchanged → **kept** at the first (EDT) occurrence (correct, matches 03-04
  intent).

## Warnings

### WR-01: `test_dst_transition_band_exactly_once` passes for the wrong reason — it does not exercise gap detection

**File:** `tests/test_scheduler.py:278-280`

**Issue:** The spring-forward leg scans at `03:15` local:

```python
gap_cfg = _home_config(days="daily", time="02:30")
gap_now = _utc_for_local(2026, 3, 8, 3, 15)
assert plan_catchup(gap_cfg, _never_sent, now_utc=gap_now) == []
```

At `03:15` local the EST-misinterpreted `02:30` instant (`07:30 UTC`) is still in
the future relative to the scan (`07:15 UTC`), so the `[]` result comes from the
"not due yet" branch — NOT from gap detection. The test therefore green-lights
the broken CR-01 code. The comment even predicts "the buggy `now_local.replace`
... emits one phantom slot," but the chosen scan time hides exactly that bug.

**Fix:** Scan AFTER the misinterpreted instant but within grace so only true gap
detection can produce `[]`. With the CR-01 fix in place this passes; with the
current code it (correctly) fails:

```python
gap_now = _utc_for_local(2026, 3, 8, 3, 45)  # 07:45 UTC, 15 min past, in grace
assert plan_catchup(gap_cfg, _never_sent, now_utc=gap_now) == []
```

### WR-02: Crash between claim-commit and send leaves a slot permanently un-fireable

**File:** `weatherbot/scheduler/daemon.py:113-137`; `weatherbot/weather/store.py:266-275`

**Issue:** `claim_slot` opens its own connection and `commit()`s the `sent_log`
row before `send_now` runs the network POST. If the process is killed (SIGKILL,
power loss, OOM) AFTER the claim commits but BEFORE/DURING the send, the row
persists with no delivery. On the next startup the catch-up scan calls
`was_sent` → `True` and the slot is skipped forever — a silently missed
briefing, which is the project's primary reliability constraint. `release_claim`
only covers the in-process non-ok / raised-exception paths, not a hard crash.

This is an inherent claim-before-send tradeoff and may be acceptable for a
single-user bot, but it is undocumented as a residual gap and contradicts the
"retry then alert rather than silently miss" requirement.

**Fix:** Either document this as an accepted residual risk in the module
docstring, or record a `claimed_at` and treat a claim with no corresponding
delivery confirmation older than the grace window as re-fireable (a two-state
claim: `claimed` vs `delivered`). Minimum: note the crash window explicitly so
it is a known limitation, not a surprise.

### WR-03: `claim_slot`/`release_claim`/`was_sent`/`record_sent` re-run full `executescript(_SCHEMA)` on every call

**File:** `weatherbot/weather/store.py:267,296,204,228`

**Issue:** Every store entry point runs `conn.executescript(_SCHEMA)` (multiple
`CREATE TABLE`/`CREATE INDEX` DDL statements) before its real query. Inside the
hot exactly-once path, `claim_slot` is now called for every fire and overlapping
fire. `executescript` issues an implicit `COMMIT` before running, which can
interfere with transaction boundaries and adds DDL parsing/locking to each claim.
While each statement is `IF NOT EXISTS` (functionally idempotent), running schema
DDL as a side effect of a read/claim is fragile: under concurrent access the
implicit commit in `executescript` can briefly drop the connection's transaction
context around the very `INSERT OR IGNORE` the atomicity argument depends on.

**Fix:** Initialize the schema ONCE (callers already have `init_db`; `run_daemon`
should call it at startup) and drop the per-call `executescript` from
`claim_slot`/`release_claim`/`was_sent`/`record_sent`, keeping each claim a single
statement on a clean connection. If self-creation must stay for un-initialized
paths, gate it behind a cheap existence check rather than re-running all DDL on
every claim.

### WR-04: APScheduler fall-back fold not verified to match the planner's `fold=0` choice

**File:** `weatherbot/scheduler/catchup.py:151`; `weatherbot/scheduler/daemon.py:195-200`

**Issue:** On a fall-back day the `01:00` hour occurs twice. The planner pins
`scheduled` to `fold=0` (the first/EDT occurrence) via `naive.replace(tzinfo=tz)`.
The fix's invariant is "the planner and the live `CronTrigger` always agree," but
nothing here proves APScheduler 3.x `CronTrigger` fires the repeated hour at
`fold=0` rather than `fold=1` (or fires it twice). If the trigger fires the
second (EST) occurrence, the catch-up `scheduled_dt` (and thus the
intended-vs-actual note and the grace arithmetic) is off by one hour for fall-back
slots inside the repeated hour. The test asserts the planner in isolation but
never cross-checks the trigger's actual fold behavior.

**Fix:** Add a test that computes `CronTrigger(hour=1, minute=30, ...,
timezone="America/New_York").get_next_fire_time(...)` across the 2026-11-01
fall-back boundary and asserts the fired instant's offset matches the planner's
`fold=0` choice — or document that fall-back fold disagreement is accepted and
bounded by the exactly-once claim (which prevents a double-send regardless).

## Info

### IN-01: `record_sent` is now dead code in production

**File:** `weatherbot/weather/store.py:213-235`

**Issue:** Since `fire_slot` switched to `claim_slot`/`release_claim`,
`record_sent` is no longer called anywhere in `weatherbot/` (only by
`test_sent_log_idempotent`). It overlaps almost entirely with `claim_slot`
(same `INSERT OR IGNORE`), inviting future drift if one is changed and not the
other.

**Fix:** Either remove `record_sent` (and re-point the idempotency test at
`claim_slot`), or add a docstring note that it is retained only as a test/utility
helper and is not on the live path.

### IN-02: `was_sent` use in `daemon.py` deserves a clarifying comment

**File:** `weatherbot/scheduler/daemon.py:49,267`

**Issue:** With `claim_slot` now subsuming the per-fire dedup read, the only
remaining `was_sent` use is the planner's pre-filter inside the `_run_catchup`
lambda. Correct and intentional, but a future reader could mistake it for the
(now removed) per-fire guard.

**Fix:** Add a brief comment at line 267 clarifying `was_sent` here is the
planner's cheap pre-filter (the authoritative dedup is the atomic `claim_slot` in
`fire_slot`).

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
