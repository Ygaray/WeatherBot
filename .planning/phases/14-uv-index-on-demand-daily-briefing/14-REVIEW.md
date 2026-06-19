---
phase: 14-uv-index-on-demand-daily-briefing
reviewed: 2026-06-19T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - weatherbot/weather/uv.py
  - weatherbot/weather/models.py
  - weatherbot/config/models.py
  - weatherbot/interactive/commands/weather_views.py
  - weatherbot/interactive/lookup.py
  - weatherbot/interactive/registry.py
  - weatherbot/interactive/bot.py
  - weatherbot/cli.py
findings:
  critical: 1
  warning: 4
  info: 4
  total: 9
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-06-19T00:00:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Reviewed the Phase 14 UV-index work at standard depth, with adversarial focus on
the items the prompt flagged: the `compute_uv` crossing/window/peak interpolation
math, the briefing-spine isolation invariant ("UV must never crash/gate a daily
briefing"), threshold threading through every consumer, `UvConfig` fail-loud
validation, the `uv` command's read-only discipline, and `compute_uv`'s freedom
from interactive-layer imports.

Strong points confirmed: the threshold is genuinely threaded (`config.uv.threshold`
reaches both the briefing via `Forecast.from_payloads(uv_threshold=...)` and the
`uv` command via `cli.py:624` / `bot.py:318`); no hardcoded literal `6` survives in
a consumer (only the `6.0` *default* on `_hints`/`from_payloads`, which is the
documented zero-migration default, not a live override). `compute_uv` imports only
stdlib + dataclasses — the Phase-15 reuse seam is clean. The `uv` handler is
read-only (reads `result.forecast.raw_onecall_imp`, no store import, no second
fetch). `UvConfig` is frozen, `extra="forbid"`, and validates threshold range + a
non-negative lead.

The key defects: a **briefing-spine isolation gap** — `compute_uv` is NOT
exception-safe against *malformed* (non-null) hourly data despite its docstring
and the T-14-04 invariant both promising it "never raises"; and a **UV-category
labeling bug** in the `uv` command where the current-UV line is annotated with the
*day-max* WHO band.

## Critical Issues

### CR-01: `compute_uv` raises on malformed (non-null) `hourly[]`/`uvi` — violates briefing-spine isolation

**File:** `weatherbot/weather/uv.py:103-119` (and the unguarded call site `weatherbot/weather/models.py:317-320`)

**Issue:** The module docstring (lines 21-22) and the `compute_uv` docstring
(line 179) both assert the function "Never raises on a malformed/empty
`hourly[]`". The guards only cover the *null/empty* cases — a missing `hourly`
key, an empty list, or a bucket whose `dt`/`uvi` is `None`:

```python
ts = bucket.get("dt")
uvi = bucket.get("uvi")
if ts is None or uvi is None:
    continue
local = _epoch_local(ts, tz)      # raises if ts is a str / float
...
points.append((local, float(uvi)))  # raises ValueError if uvi is "abc" / non-numeric
```

A bucket with a *present-but-non-numeric* `uvi` (e.g. `"NA"`, `None`-in-a-list, a
dict) raises `ValueError`; a non-int `dt` makes `datetime.fromtimestamp` raise
`TypeError`. Neither is caught. Because `Forecast.from_payloads` calls
`compute_uv` **unguarded** (`models.py:317`), that exception propagates out of
`from_payloads`, aborts the entire `Forecast` build, and therefore crashes/gates
the daily briefing render — exactly the T-14-04 "a UV failure must not crash a
briefing" invariant the phase is built around. The same unguarded propagation
exists on the command path (`weather_views.uv` → `compute_uv`), though there the
`bot.py`/`cli.py` envelopes would catch it (degrading to a generic error reply,
which is itself a regression for the `uv` command).

The provider sending a string where a float is expected is a realistic
partial-payload / upstream-schema-drift case — the rest of the codebase
(`models.py`, `weather_views.py`) is defensively coded against exactly this, so
UV is the lone unguarded spot on the briefing spine.

**Fix:** Coerce defensively inside the bucket loop so a non-numeric value is
skipped rather than raising, keeping the promise literal:

```python
ts = bucket.get("dt")
uvi = bucket.get("uvi")
if ts is None or uvi is None:
    continue
try:
    local = _epoch_local(int(ts), tz)
    uvi_f = float(uvi)
except (TypeError, ValueError, OverflowError, OSError):
    continue  # malformed bucket — skip, never raise (T-14-04)
if local.date() != today:
    continue
...
points.append((local, uvi_f))
```

Additionally, belt-and-suspenders the call site so NO `compute_uv` failure can
ever reach the briefing render, regardless of future internal changes:

```python
# models.py from_payloads — UV must degrade, never gate the briefing.
try:
    uv_summary = compute_uv(onecall_imp, onecall_met, uv_threshold, tz=uv_tz, now=now_utc)
    uv_fields = _format_uv(uv_summary, uv_threshold)
except Exception:  # noqa: BLE001 — briefing-spine isolation (T-14-04)
    uv_fields = {k: "" for k in
                 ("uv_now", "uv_max", "uv_cross", "uv_window", "uv_peak", "uv_category")}
```

(Also note `current = float(cur.get("uvi") or 0.0)` and
`max_uvi = float(daily0.get("uvi") or 0.0)` at lines 187-188 have the same
non-numeric-string crash potential, though those fields are far less likely to be
malformed than the hourly buckets.)

## Warnings

### WR-01: `uv` command labels the "Now" line with the day-max WHO category

**File:** `weatherbot/interactive/commands/weather_views.py:294-297`

**Issue:** `UvSummary.category` is computed **only** from the day's max
(`uv.py:189` `category = uv_category(max_uvi)`). The `uv` handler reuses that one
category for BOTH lines:

```python
lines = [
    ("Now", f"{round(summary.current)} ({summary.category})"),       # current value, MAX's band
    ("Today's max", f"{round(summary.max)} ({summary.category})"),
]
```

So at 7am with current UV ≈ 2 (Low) but a day max of 8 (Very High), the reply
reads `Now: 2 (Very High)` — a false, alarming label. The category word must be
derived from the value it annotates.

**Fix:** Compute the current-UV band independently:

```python
from weatherbot.weather.uv import uv_category
...
("Now", f"{round(summary.current)} ({uv_category(summary.current)})"),
("Today's max", f"{round(summary.max)} ({summary.category})"),
```

### WR-02: `_format_uv` peak value can disagree with the actual hourly peak clock

**File:** `weatherbot/weather/models.py:180-183`

**Issue:** The peak DISPLAY string pairs the day-max value (`uv_max`, from
`daily[0].uvi`) with the hourly-argmax CLOCK (`summary.peak_time`):

```python
peak_clock = _uv_hhmm(summary.peak_time)
uv_peak = f"peak {uv_max} at {peak_clock}" if peak_clock else ""
```

`daily[0].uvi` (OpenWeather's own day max) and the max over today's *daytime
hourly buckets* are not guaranteed equal — the daily max can exceed the hourly
sample (different aggregation, sub-hour peak, buckets trimmed to the
sunrise/sunset window). When they differ, the line asserts e.g. "peak 9 at 1:00
PM" while the 1:00 PM bucket was actually 8. The code comment acknowledges the
two sources but ships the mismatch. The command path is internally consistent
(`weather_views.uv:300` uses `summary.peak_uvi` with `summary.peak_time`), so the
briefing and the `uv` command can print *different* peak values for the same day.

**Fix:** Use the hourly-argmax value that actually corresponds to `peak_time` for
the briefing peak line, matching the command path, so value and clock always agree:

```python
peak_clock = _uv_hhmm(summary.peak_time)
uv_peak = f"peak {round(summary.peak_uvi)} at {peak_clock}" if peak_clock else ""
```

If the intent really is to show `daily[0].uvi` as the headline number, then the
clock should not be presented as "the time of THAT value" — reword to avoid the
implied pairing.

### WR-03: `_first_down_cross_after` ignores `start` and can return a down-cross before the protect window opens

**File:** `weatherbot/weather/uv.py:142-157`

**Issue:** The function is documented as "first instant UV falls back below
`threshold` **at/after** `start`", but it only skips pairs where `t1 < start` and
then returns the first downward crossing in the *pair*, never checking that the
interpolated crossing instant is `>= start`. In the normal monotone-ish case this
is fine, but with a non-monotone today profile (UV dips below threshold, climbs
back, then the real up-cross happens later — possible around broken cloud /
provider noise) the up-cross can land late in a pair whose *earlier* portion
already dipped below. `_first_up_cross` and `_first_down_cross_after` then bracket
a window whose `window_end` precedes `window_start`, producing a reversed/negative
"protect 2:00 PM–11:00 AM" range. The window-end is not bounded below by
`window_start`.

**Fix:** Bound the returned down-cross at/after `start`, and have `compute_uv`
defend against an inverted window:

```python
def _first_down_cross_after(points, threshold, start):
    for (t0, u0), (t1, u1) in zip(points, points[1:]):
        if t1 < start:
            continue
        if u0 >= threshold > u1:
            frac = (u0 - threshold) / (u0 - u1)
            cross = t0 + (t1 - t0) * frac
            if cross >= start:
                return cross
    return None
```

And in `compute_uv`, guard the window: `if window_end is not None and
window_end < window_start: window_end = points[-1][0]`.

### WR-04: `UvConfig.pre_warn_lead_minutes` has no upper bound — a too-large lead is silently accepted

**File:** `weatherbot/config/models.py:416-423`

**Issue:** `_lead_non_negative` only rejects negatives. Phase 14 "stores +
validates" this field for Phase 15's pre-warn monitor (per the docstring), but a
nonsensical value like `pre_warn_lead_minutes = 100000` (≈69 days) validates
cleanly and will silently mis-configure the Phase-15 monitor (a pre-warn lead
longer than the daytime/forecast horizon means "warn at a time that never comes"
or "always warn"). The other timing knobs in this file fail loud at both ends
(e.g. `Reliability` enforces an upper budget bound); the UV threshold is bounded
`0..20`. A lead with only a lower bound is inconsistent with the file's
fail-loud-at-both-ends posture and defers a foreseeable Phase-15 footgun.

**Fix:** Add a generous-but-finite ceiling (a pre-warn lead beyond a few hours is
meaningless for an intraday UV monitor):

```python
@field_validator("pre_warn_lead_minutes")
@classmethod
def _lead_in_range(cls, v: int) -> int:
    if not 0 <= v <= 720:  # 0..12h — beyond a daytime span is meaningless
        raise ValueError(
            f"uv.pre_warn_lead_minutes must be between 0 and 720, got {v!r}"
        )
    return v
```

## Info

### IN-01: `onecall_met` parameter is dead weight on `compute_uv`

**File:** `weatherbot/weather/uv.py:160-167` (param `onecall_met`)

**Issue:** `onecall_met` is accepted "for signature parity" and never read — a
genuinely unused parameter. It is documented, so this is intentional, but it
invites a caller to assume metric UV is consulted. Low priority; flagging for the
record. Consider `onecall_met: dict | None = None` (default) so callers that have
no metric payload need not pass `None` explicitly, and the parity intent is
clearer.

### IN-02: `_COMPASS` table and `_compass` helper duplicated across two modules

**File:** `weatherbot/weather/models.py:44-52` vs
`weatherbot/interactive/commands/weather_views.py:31-58`

**Issue:** The 16-point compass tuple and the `int((deg + 11.25) // 22.5) % 16`
helper are copy-pasted in both files (each with a comment acknowledging the
duplication to "stay dependency-free of the interactive layer"). A future fix to
one (e.g. a bearing-rounding tweak) will silently diverge from the other. Not a
Phase-14 regression (pre-existing), but it now sits adjacent to the new UV code.
Consider hoisting `compass`/`_COMPASS` into a tiny stdlib-only helper module
(`weatherbot/weather/bearing.py`) that both layers import, preserving the
no-interactive-import constraint.

### IN-03: `_threshold_display` (weather_views) duplicates the briefing's threshold-format logic

**File:** `weatherbot/interactive/commands/weather_views.py:243-249` vs
`weatherbot/weather/models.py:159-163`

**Issue:** The "render threshold without a trailing `.0`" snippet
(`str(round(t)) if float(t).is_integer() else f"{t:g}"`) is implemented twice. The
comment in `weather_views` explicitly notes it "mirrors the briefing's
`_format_uv`" — a duplication that must be kept in lockstep by hand. Extract one
helper (in `weather.uv`, which both layers may import) so the command and briefing
threshold display can never drift.

### IN-04: `uv_category` band table comment lists "11+ Extreme" but the `_BANDS` table stops at 10

**File:** `weatherbot/weather/uv.py:61-69`

**Issue:** Minor doc/code coherence note: the comment enumerates the full WHO set
including "11+ Extreme", but `_BANDS` only contains entries through `(10, "Very
High")` and relies on the `return "Extreme"` fallthrough. This is correct (the
fallthrough IS the 11+ band) but a reader scanning the table alone may think
Extreme is missing. Optionally add a trailing comment on the `return "Extreme"`
line tying it to the 11+ band. Cosmetic only.

---

_Reviewed: 2026-06-19T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
