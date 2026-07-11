---
phase: 32-timezone-date-boundary-correctness
reviewed: 2026-07-11T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - weatherbot/weather/dates.py
  - weatherbot/weather/models.py
  - weatherbot/weather/uv.py
  - weatherbot/weather/store.py
  - weatherbot/scheduler/catchup.py
  - weatherbot/scheduler/uvmonitor.py
findings:
  critical: 1
  warning: 3
  info: 3
  total: 7
status: resolved
resolved: 2026-07-11
resolution_note: >-
  CR-01, WR-01, WR-02, WR-03 fixed in a review-remediation pass (commits
  4d9a088, 44edb5c, 6208155). INFO items IN-01 (store $.daily[0] generated
  columns → F36/F37 deferred data-model) and IN-03 (from_payloads double tz
  resolution) intentionally left as-is; IN-02 (compute_uv naive-now contract)
  is now documented on the parameter as part of the CR-01 fix.
resolutions:
  CR-01: fixed  # naive now→UTC in compute_uv + _today_daytime_points (commit 4d9a088)
  WR-01: fixed  # uvmonitor daylight gate uses select_today_daily (commit 44edb5c)
  WR-02: fixed  # _daily0_matches_today removed; single source of truth (commit 44edb5c)
  WR-03: fixed  # select_today_daily explicit dt-None check (commit 6208155)
  IN-01: deferred  # F36/F37 data-model, out of phase scope
  IN-02: fixed  # naive-now contract now documented on compute_uv (with CR-01)
  IN-03: wont_fix  # trivial-only-if-editing; models.py untouched this pass
---

# Phase 32: Code Review Report

**Reviewed:** 2026-07-11
**Resolved:** 2026-07-11 (review-remediation pass)
**Depth:** standard
**Files Reviewed:** 6
**Status:** resolved (CR-01 / WR-01 / WR-02 / WR-03 fixed; IN-02 documented)

## Summary

This phase collapses three verbatim `_local_date_iso` copies into one shared
`weatherbot/weather/dates.py` leaf and replaces positional `daily[0]` date/window
math with own-local-date selection (`select_today_daily`) across the UV and
briefing paths. The core primitive `local_date_iso` correctly treats a naive
`now_utc` as UTC (F33), `select_today_daily` is robustly defensive (skips
malformed epochs, matches by the entry's own local date, degrades to `None`),
the catch-up prior-day candidate loop is keyed on the candidate day with a
per-slot dedup set and preserves the spring-forward gap skip and fold=0 grace,
and the UV all-clear uses a proper `below AND past_peak AND window_over`
hysteresis gate that a momentary sub-threshold dip cannot latch. `store.py` is
clean for this phase's scope (parameterized SQL, read-only URI hardening, tz
authority preserved).

However, the phase's central invariant — "one authoritative naive→UTC 'today'
that the briefing, the store key, and the UV math all agree on" — has a hole:
`compute_uv`/`_today_daytime_points` never normalize a naive `now`, yet
`Forecast.from_payloads` forwards its (documented-as-possibly-naive) `now_utc`
straight into `compute_uv`. On a non-UTC host near midnight the UV "today" can
diverge by a day from the briefing "today" that was computed correctly via
`local_date_for`. There is also a residual positional `daily[0]` read in the UV
monitor's daylight gate that was not migrated to `select_today_daily` the way
`uv.py` was.

## Critical Issues

### CR-01: `compute_uv` does not treat a naive `now` as UTC — UV "today" can host-shift a day, diverging from the briefing/store date

> **RESOLVED (2026-07-11, commit 4d9a088).** `compute_uv` now normalizes a naive
> `now` to UTC (`now.replace(tzinfo=timezone.utc)`) at the top, and
> `_today_daytime_points` re-applies the same guard defensively (it is module-level
> and callable directly). Regression test
> `test_uv.py::test_naive_now_treated_as_utc_not_host_local` forces `TZ=Asia/Tokyo`
> and asserts a naive `now` yields the SAME `UvSummary` selection as the UTC-aware
> equivalent (RED before the fix, GREEN after). IN-02's naive-now contract is now
> documented on the `compute_uv` docstring/`now` parameter.

**File:** `weatherbot/weather/uv.py:239` (also `:114`), fed by `weatherbot/weather/models.py:336`

**Issue:** `compute_uv` computes its day anchor with
`today_iso = now.astimezone(tz).date().isoformat()` (line 239) and
`_today_daytime_points` does `today = now.astimezone(tz).date()` (line 114).
Neither normalizes a naive `now` to UTC. `datetime.astimezone()` on a **naive**
datetime interprets it in the **host local timezone**, not UTC — the exact F33
class of bug this phase fixes everywhere else.

`Forecast.from_payloads` documents that `now_utc` may be naive and is "treated as
UTC" (docstring lines 289–291), and it correctly computes the briefing/store
`local_date` via `local_date_for` (which normalizes naive→UTC). But it then
forwards the **same, still-naive** `now_utc` into `compute_uv` at line 336:

```python
uv_summary = compute_uv(
    onecall_imp, onecall_met, uv_threshold, tz=uv_tz, now=now_utc
)
```

Inside `compute_uv`, a naive `now_utc` near midnight is reinterpreted in the host
tz. On any host not in UTC this makes the UV "today" (`today_iso`,
`_today_daytime_points`'s `today`, and thus `select_today_daily` matching,
`max_uvi`, crossing/window/peak) a potentially **different calendar day** than
the briefing's `{date}` and the store's `target_local_date`. The whole point of
Phase 32 is that these can never disagree; here they can, precisely at the
midnight/tz boundary the phase targets. It is masked only because the default
`now` is aware — but the documented naive contract makes it a real, reachable
correctness bug (and any test injecting a naive clock on a non-UTC host will
expose it).

**Fix:** Normalize `now` to UTC at the top of `compute_uv`, mirroring
`local_date_iso`, so every downstream `.astimezone(tz)` is anchored to UTC:

```python
from datetime import timezone
...
raw = onecall_imp or {}
if now is None:
    now = datetime.now(tz)
elif now.tzinfo is None:
    now = now.replace(tzinfo=timezone.utc)  # F33: naive is UTC, never host-local
```

(This one guard covers both line 239 and the `now` passed into
`_today_daytime_points`.) Preferably also have `_today_daytime_points` reuse the
same normalized `now`. Alternatively, normalize at the single call site in
`from_payloads` — but fixing it inside `compute_uv` protects the `uv` command
and the monitor call paths too.

## Warnings

### WR-01: UV monitor daylight gate still reads `daily[0]` positionally instead of `select_today_daily` — degrades (skips the tick) when today's entry is `daily[1]`

> **RESOLVED (2026-07-11, commit 44edb5c).** `_evaluate_location` now computes
> `local_date` first, then sources the daylight gate's `sunrise`/`sunset` from
> `select_today_daily(onecall_imp.get("daily"), tz, local_date)` (today by its own
> local date), consistent with the `uv.py` window-bound fix. The `sunrise is None or
> sunset is None → return True` safe skip is preserved (covers the selector-`None`
> no-today-entry case). Regression test
> `test_uv_monitor.py::test_today_is_daily1_still_decides` (daily[0]=yesterday,
> daily[1]=today) asserts the tick is no longer dropped (RED before, GREEN after).

**File:** `weatherbot/scheduler/uvmonitor.py:143`

**Issue:** This phase migrated `uv.py`'s window bound off positional `daily[0]`
to `select_today_daily`, but `_evaluate_location` still does:

```python
daily0 = (onecall_imp.get("daily") or [{}])[0] or {}
sunrise = daily0.get("sunrise")
sunset = daily0.get("sunset")
```

It then guards with `_daily0_matches_today(sunrise, tz, local_date)` (line 161),
returning `True` (fetched, no decision) when `daily[0]` is not today. So near a
tz/midnight boundary where the payload's `daily[0]` is yesterday but `daily[1]`
is today, the monitor **skips the whole decision for that tick** even though the
correct today entry is present in the payload — while `compute_uv`, called just
below at line 181, independently locates the correct today entry via
`select_today_daily`. The monitor's daylight baseline and `compute_uv`'s day
baseline are therefore sourced differently, and the monitor stops functioning
for the boundary tick rather than using the available correct data. This is a
functional gap (missed/late UV alerting at the boundary) and an inconsistency
with the fix applied to `uv.py`, not a wrong-data hazard.

**Fix:** Source the sunrise/sunset window bound from the same today entry, so the
gate and `compute_uv` agree and no tick is dropped when today is `daily[1..]`:

```python
from weatherbot.weather.dates import select_today_daily
...
local_date = local_date_iso(now_utc, tz)
today_entry = select_today_daily(onecall_imp.get("daily"), tz, local_date) or {}
sunrise = today_entry.get("sunrise")
sunset = today_entry.get("sunset")
if sunrise is None or sunset is None:
    return True  # no sun data for today → skip safely
```

Then `_daily0_matches_today` becomes unnecessary (the selection already
guarantees the entry's own local date == today).

### WR-02: `_daily0_matches_today` derives the day from `sunrise` only, ignoring `dt` — inconsistent with `select_today_daily`'s `dt`-first rule

> **RESOLVED by deletion (2026-07-11, commit 44edb5c).** `_daily0_matches_today` is
> removed entirely (the WR-01 `select_today_daily` routing makes it dead), so there
> is now one source of truth for a daily entry's local date. Its non-numeric-stamp →
> skip-safely coverage migrated into
> `test_golden_coverage_fill.py::test_select_today_daily_stamp_edges`.

**File:** `weatherbot/scheduler/uvmonitor.py:85-102`

**Issue:** `select_today_daily` (dates.py:93) derives an entry's own date from
`entry.get("dt") or entry.get("sunrise")` (dt-first), while
`_daily0_matches_today` derives it from `sunrise` only. For a normal One Call
`daily` entry both land on the same calendar date, so this is not currently a
wrong-answer bug — but it is a second, divergent implementation of "what day is
this daily entry," which is exactly the duplication this phase set out to
eliminate (three `_local_date_iso` copies → one helper). If `select_today_daily`
replaces the positional read per WR-01, this helper and its bespoke date-derive
logic can be deleted entirely, removing the divergence risk.

**Fix:** Remove `_daily0_matches_today` and route the monitor through
`select_today_daily` (see WR-01), so there is one source of truth for a daily
entry's local date.

### WR-03: `select_today_daily` `dt`-vs-`sunrise` fallthrough treats a `dt` of `0` as absent

> **RESOLVED (2026-07-11, commit 6208155).** `dates.select_today_daily` now uses an
> explicit `stamp = entry.get("dt"); if stamp is None: stamp = entry.get("sunrise")`
> None-check instead of truthiness, so a legitimate `dt == 0` is used verbatim and
> never falls through to `sunrise`. A `dt == 0` assertion was added to
> `test_select_today_daily_stamp_edges`.

**File:** `weatherbot/weather/dates.py:93`

**Issue:** `stamp = entry.get("dt") or entry.get("sunrise")` uses truthiness, so
a literal `dt == 0` (Unix epoch 1970-01-01, a valid-if-nonsensical timestamp)
falls through to `sunrise`. This is defensively harmless for real OpenWeather
payloads (daily `dt` is always a large positive epoch) and generally safer
(0 is never a real forecast day), but it is a latent truthiness footgun that
would also swallow any future legitimately-falsy sentinel. Worth an explicit
`None` check to match the deliberate care taken elsewhere in this module.

**Fix:**

```python
stamp = entry.get("dt")
if stamp is None:
    stamp = entry.get("sunrise")
if stamp is None:
    continue
```

## Info

### IN-01: `store.py` generated virtual columns still hardcode `$.daily[0]` positionally

**File:** `weatherbot/weather/store.py:100-103`

**Issue:** The `weather_onecall` GENERATED columns (`day_high`, `day_low`, `pop`,
`day_uvi`) extract `$.daily[0].*` positionally from the raw payload. This phase's
thesis is that `daily[0]` is not reliably "today" near a tz/midnight boundary, so
these analysis columns can, in the same boundary case, index yesterday's day.
`target_local_date` (the join key) is computed correctly via `local_date_for`, so
a v2 forecast-vs-actual join keyed on the date is unaffected — but the
convenience columns themselves can be a day off. Out of this phase's stated
scope (persistence of the raw payload is retained deliberately), noted so it is
not mistaken for correct. Fixing would require a `json_extract` that filters
`daily[]` by date, which SQLite generated columns cannot express cleanly; a v2
analysis view is the natural home.

### IN-02: `_epoch_local` / naive-`now` contract is undocumented at the `compute_uv` boundary

**File:** `weatherbot/weather/uv.py:214`

**Issue:** `compute_uv`'s signature comment says `now` "defaults to
`datetime.now(tz)`" but does not state whether an injected `now` must be aware.
Given CR-01, the intended contract (naive == UTC) should be documented on the
parameter so future callers do not reintroduce a host-shift. Pairs with the CR-01
fix.

### IN-03: `from_payloads` resolves the location tz twice

**File:** `weatherbot/weather/models.py:284-291`

**Issue:** `from_payloads` resolves `loc_tz` inline (lines 284–288) AND calls
`local_date_for(loc, now_utc)` (line 291), which resolves the same tz again via
`_resolve_tz`. Two independent resolutions of the same `location.timezone`
(inline `ZoneInfo(...)` vs `dates._resolve_tz`) are behaviorally identical today
but are two code paths that could drift. Minor: derive `local_date` from the
already-resolved `loc_tz` via `local_date_iso(now_utc, loc_tz)` to keep a single
resolution, or drop the inline resolution and reuse the helper's.

---

_Reviewed: 2026-07-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
