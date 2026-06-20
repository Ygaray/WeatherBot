---
phase: 15-proactive-uv-sunscreen-monitor
reviewed: 2026-06-19T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - weatherbot/scheduler/uvmonitor.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/scheduler/catchup.py
  - weatherbot/weather/store.py
  - weatherbot/config/models.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 15: Code Review Report

**Reviewed:** 2026-06-19T00:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Reviewed the new intraday proactive UV monitor (`uvmonitor.py`), its daemon
registration (`daemon.py`), the reused catch-up weekday logic (`catchup.py`), the
new `uv_alerts` dedup store functions (`store.py`), and the `UvConfig` model
(`models.py`). The five named risk areas were each traced adversarially.

The phase's headline safety properties largely hold:

- **FAILURE ISOLATION (UV-06):** The two-layer try/except in `_uv_monitor_tick` is
  genuinely robust. The per-location `try/except` (lines 313-323) wraps the entire
  `_active_today` + `_evaluate_location` path, and the outermost envelope (lines
  301-326) wraps `holder.current()`, the lazy `build_client`, and the loop. `_post`
  independently swallows `channel.send` failures. No traced path in the tick can
  raise to the APScheduler worker. `max_instances=1` + `coalesce=True` +
  `misfire_grace_time=None` are all present on the `__uvmonitor__` job, so a slow
  tick cannot stack. **This isolation is sound.**
- **NO TIME-SERIES POLLUTION (UV-04):** Confirmed. `uvmonitor.py` imports only
  `claim_uv_alert` / `claimed_uv_kinds` from the store (line 38) — never `persist`,
  `claim_slot`, `record_alert`, or `was_sent`. It calls `client.fetch_onecall`
  directly. The only durable write is the `uv_alerts` table. **No pollution.**
- **DEDUP / SQL SAFETY (UV-05, SQLi):** `claim_uv_alert` and `claimed_uv_kinds` are
  parameterized `INSERT OR IGNORE` / `SELECT` against the `UNIQUE(location_id,
  local_date, alert_kind)` key, `rowcount==1` race-safe, restart-durable, keyed on
  the rename-safe `location.id`, with the local-date computed in the configured tz.
  **No SQL injection, claim is race-safe and durable.**

However, several correctness gaps were found in the daylight/decision logic and a
claim-vs-send ordering issue that defeats the "claim before send" guarantee for a
specific failure mode. None are crashes (isolation holds), so all are classified
WARNING, but WR-01 and WR-02 cause *missed or lost* alerts — the user-visible
purpose of the feature — and should be fixed before ship.

## Warnings

### WR-01: All-clear alert can never fire — claim is gated behind the daylight check

**File:** `weatherbot/scheduler/uvmonitor.py:136-137, 256-266`

**Issue:** `_evaluate_location` returns early (line 137) whenever `now` is outside
`[sunrise, sunset]`, BEFORE `_decide` is ever called. The all-clear branch (lines
256-266) requires `summary.current < threshold` AND a prior `crossing` claim. On a
typical UV day, UV is highest at solar noon and falls toward sunset — it very often
does NOT drop back below the threshold until at or after sunset. Once `now > sunset`,
`_is_daylight` returns `False` and the decision is skipped entirely, so the all-clear
("protect window over") is never claimed and never posted. The feature's third alert
kind is effectively dead on any day where UV stays above threshold past sunset.

Even when UV does dip below threshold before sunset, the all-clear only fires if a
tick happens to land in that window AND it is still daylight — a narrow combination.

**Fix:** Evaluate the all-clear (and only the all-clear) even when daylight has just
ended, OR widen the gate so the decision still runs for a short grace past sunset
when a `crossing` was claimed today. For example, do not early-return on the daylight
check if `"crossing"` is already in the prior set:

```python
prior = claimed_uv_kinds(db_path, location.id, local_date)
in_daylight = _is_daylight(now_utc, sunrise, sunset, location.timezone)
if not in_daylight and "crossing" not in prior:
    return True  # outside daylight with nothing to close out → skip.
# else fall through to _decide so a post-sunset all-clear can still fire.
```
Note `compute_uv` must still produce a usable `summary.current` post-sunset (it reads
`current.uvi` verbatim, so it does), and branches 1/2 must remain gated on daylight
to avoid a spurious post-sunset crossing — keep that gating inside `_decide` or guard
those branches with `in_daylight`.

### WR-02: `crossing` claimed even when the post is suppressed, but `prewarn` suppression claim is unconditional — a lost first-poll already-high post

**File:** `weatherbot/scheduler/uvmonitor.py:210-228`

**Issue:** In the already-high/crossing branch, on a first poll the code first calls
`claim_uv_alert(..., "prewarn")` (line 214) to suppress the now-moot pre-warn, THEN
calls `claim_uv_alert(..., "crossing")` (line 215). The `crossing` claim is the gate
for the post. This ordering is correct (claim-before-post). BUT: if `claim_uv_alert`
for `prewarn` succeeds and the process crashes/restarts between line 214 and line
215, on the next tick `prior` now contains `prewarn` but NOT `crossing`. Re-entering
`_decide`: branch 1 condition `summary.current >= threshold and "crossing" not in
prior` is still True, but `first_poll = not prior` is now `False` (prewarn row
exists). So the wording silently switches from "UV already ≥T" to "UV now ≥T" for
what is still a first observation. Minor wording drift, not a lost alert — but it is
an observable inconsistency from a non-atomic two-row claim.

More importantly, the two claims are in **separate** `sqlite3.connect` calls
(each `claim_uv_alert` opens/commits its own connection), so they are NOT atomic.
A crash between them leaves a `prewarn` row with no `crossing` row and no post ever
sent for either kind on the original first-poll instant.

**Fix:** Either claim both kinds in one transaction, or reorder so `crossing` (the
posting gate) is claimed/posted FIRST and the moot-`prewarn` suppression claim
happens AFTER a successful claim of `crossing`, so a crash never leaves a suppressing
`prewarn` row without its corresponding `crossing`:

```python
if claim_uv_alert(db_path, location.id, local_date, "crossing"):
    if first_poll:
        claim_uv_alert(db_path, location.id, local_date, "prewarn")  # suppress moot pre-warn
    _post(channel, ...)
```

### WR-03: `monitor_enabled` toggle is silently restart-deferred, contradicting its documented "live" behavior

**File:** `weatherbot/scheduler/daemon.py:710-739, 793-802`; `weatherbot/config/models.py:407-415`

**Issue:** `_register_uvmonitor_job` gates registration on `snapshot.uv.monitor_enabled`
at startup only. `_reconcile_jobs` (lines 798-802) excludes `__uvmonitor__` from the
live-id set, so a config reload NEVER adds a newly-enabled monitor nor removes a
newly-disabled one. The `UvConfig` docstring (models.py:412-414) states only
`interval_seconds` is restart-deferred and that "The other UV knobs
(threshold/lead/margin/enable) ARE live via the per-tick holder read." That is false
for `monitor_enabled`: the *tick* re-reads the holder, but a disabled-via-reload
monitor's job is still registered and still fires (it just keeps polling — there is
no in-tick `if not snapshot.uv.monitor_enabled: return` guard). Conversely, enabling
the monitor via reload does nothing until restart.

So `monitor_enabled=false` set via reload does NOT stop the monitor (it keeps fetching
the One Call payload every interval and may keep posting), which is the opposite of the
operator's intent and wastes API quota.

**Fix:** Add an in-tick gate at the top of `_uv_monitor_tick` after the snapshot read:
```python
snapshot = holder.current()
if not snapshot.uv.monitor_enabled:
    return  # live disable: the job stays registered but does nothing.
```
and correct the docstring to state `monitor_enabled` is honored live (via this gate)
while only `interval_seconds` is restart-deferred.

### WR-04: Pre-warn `mins` can render a misleading value when only `value_close` fires

**File:** `weatherbot/scheduler/uvmonitor.py:236-254`

**Issue:** The pre-warn branch fires when `time_close OR value_close`. The posted
message computes `mins` (line 246-250) as the minutes to `crossing_time` *only if
`crossing_time is not None`*, else falls back to `lead`. Consider a `value_close`
trigger where `crossing_time` IS not None but lies FURTHER out than `lead` (UV is
within `margin` of the threshold now, but the interpolated crossing is, say, 90 min
away while `lead` is 30). The message then reads "UV hits T in ~90 min ... sunscreen
soon" — a "soon" claim with a not-soon number, fired by value-proximity. The number
is technically the crossing time, but the "soon" framing is driven by value-proximity,
producing a contradictory message.

Worse: if `crossing_time` is in the PAST relative to `now_local` (a non-monotone
profile where UV already dipped and `_first_up_cross` returns an earlier straddle —
see `_first_up_cross`, which does not bound by `now`), `mins` is NEGATIVE, rendering
"UV hits T in ~-12 min". The `time_close` guard requires `0 <= delta <= lead`, but the
`value_close` path has no such guard, so a value-triggered post can carry a negative
or stale `mins`.

**Fix:** Clamp/guard the rendered minutes, e.g. only show a "~N min" phrase when
`crossing_time` is in the future, otherwise use value-proximity wording:
```python
delta_min = (
    (summary.crossing_time - now_local).total_seconds() / 60
    if summary.crossing_time is not None else None
)
if delta_min is not None and 0 <= delta_min <= lead:
    text = f"☀️ UV hits {t} in ~{int(delta_min)} min in {name} — sunscreen soon."
else:
    text = f"☀️ UV nearing {t} in {name} — sunscreen soon."
```

### WR-05: Daylight bound and `_today_daytime_points` window can disagree, skewing the crossing time used for pre-warn

**File:** `weatherbot/scheduler/uvmonitor.py:131-144`; `weatherbot/weather/uv.py:109-146`

**Issue:** `_evaluate_location` gates daylight on `daily[0].sunrise`/`sunset`
(lines 131-136) and returns early if either is `None`. But `compute_uv` →
`_today_daytime_points` uses its OWN sunrise/sunset read and falls back to a fixed
`06:00-20:00` window when sun data is absent (uv.py:142-143). Because the monitor
already early-returns when sunrise/sunset is None, the two code paths *normally*
agree — but they read the SAME `daily[0]` independently, and if the payload's
`daily[0]` differs from `daily` ordering assumptions (e.g. the first daily bucket is
yesterday near a tz boundary), the daylight gate and the crossing window are computed
from possibly different day baselines. This is a latent consistency risk rather than
a proven crash: the monitor's daylight check uses `daily[0]` while `compute_uv` also
filters hourly buckets to `now`'s local date. Near a DST or midnight boundary these
can momentarily disagree, producing a crossing_time for "today" while the daylight
gate references a `daily[0]` that may be the prior day.

**Fix:** Have the monitor pass the same authoritative date/window into `compute_uv`
that it uses for the daylight gate, or assert `daily[0]` corresponds to `now`'s local
date before trusting its sunrise/sunset (skip the tick safely if not). At minimum,
add a guard that the `daily[0]` date in the configured tz equals `local_date`,
returning `True` (fetched, no decision) otherwise.

## Info

### IN-01: `_is_daylight` re-imports `datetime` locally and shadows the module-level intent

**File:** `weatherbot/scheduler/uvmonitor.py:75`

**Issue:** `_is_daylight` does `from datetime import datetime as _dt` inside the
function body while `datetime` is also imported under `TYPE_CHECKING` (line 42) and
re-imported again inside `_uv_monitor_tick` (line 296). Three different local import
sites for the same stdlib name is inconsistent and slightly error-prone.

**Fix:** Import `datetime`/`timezone` once at module top (runtime, not just
`TYPE_CHECKING`) and drop the per-function re-imports.

### IN-02: `_evaluate_location` return value `True` overloaded — "fetched" vs "decision taken"

**File:** `weatherbot/scheduler/uvmonitor.py:115-159`

**Issue:** The function returns `True` for "a fetch was performed" but returns `True`
in three different situations (no sun data, outside daylight, and decision taken),
and the caller only uses it to bump a `fetched` counter. The docstring says `False`
when "gated out before any fetch", but every gate that returns is AFTER the fetch, so
`False` is never returned. The counter is therefore always equal to the active-today
count, never reflecting actual decision activity — the log line `fetched=`/`skipped=`
is less informative than it appears.

**Fix:** Either drop the bool return (make it `-> None`) or return a small enum/tuple
distinguishing fetched-no-decision from decision-taken so the outcome log is truthful.

### IN-03: Magic literal daytime fallback window duplicated across modules

**File:** `weatherbot/weather/uv.py:143` (`6 <= local.hour < 20`)

**Issue:** The `06:00-20:00` fallback window is a magic pair duplicated from
`weather_views._is_daytime` (per the comment). The monitor relies on this fallback
indirectly. A drift between the two copies would silently change which hourly buckets
count as daytime.

**Fix:** Hoist the fallback bounds to a single shared module constant
(`_DAYTIME_FALLBACK = (6, 20)`) referenced by both.

### IN-04: `_fmt_threshold` uses `int(threshold)` truncation, not rounding

**File:** `weatherbot/scheduler/uvmonitor.py:162-164`

**Issue:** `_fmt_threshold` returns `str(int(threshold))` only when
`float(threshold).is_integer()`, so the truncation is guarded and currently safe. But
it is a fragile idiom — if the guard is ever loosened, `int(6.9)` would render `6`.
Purely defensive nit.

**Fix:** Use `f"{threshold:g}"` which renders `6.0`→`6` and `6.5`→`6.5` without an
unguarded truncation.

---

_Reviewed: 2026-06-19T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
