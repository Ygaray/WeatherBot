# Phase 32: Timezone & Date-Boundary Correctness - Pattern Map

**Mapped:** 2026-07-11
**Files analyzed:** 12 (6 source: 1 new + 5 modified; 5 test files + 1 import-hygiene)
**Analogs found:** 12 / 12 (all in-repo — this is a consolidation/correctness phase, no new mechanism)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/weather/dates.py` (CREATE) | utility (pure helper) | transform | `weatherbot/scheduler/days.py` + `weatherbot/weather/multiday.py` | exact (pure acyclic precedent) |
| `weatherbot/scheduler/catchup.py` (MODIFY) | service (pure planner) | batch/transform | its OWN gap/fold roundtrip `:161-168` | exact (same function) |
| `weatherbot/scheduler/uvmonitor.py` (MODIFY) | service (event-driven tick) | event-driven | its OWN `_daily0_matches_today` `:93-110` + `_decide` `:256-323` | exact (same module) |
| `weatherbot/weather/models.py` (MODIFY) | model (payload → Forecast) | transform | `multiday._date_index_map` `:49-58` | role+flow match |
| `weatherbot/weather/uv.py` (MODIFY) | service (UV compute) | transform | `uvmonitor._daily0_matches_today` (guard) + `days.py` (sort site local) | role+flow match |
| `weatherbot/weather/store.py` (MODIFY) | store (persistence) | file-I/O (SQLite) | new `dates.py` helper (import swap only) | exact (verbatim twin) |
| `tests/test_scheduler.py` (EXTEND) | test | request-response | existing `test_catchup_*` / `test_dst_transition_band_exactly_once` | exact |
| `tests/test_uv_monitor.py` (EXTEND) | test | event-driven | existing `_run` helper + injected `now_utc` | exact |
| `tests/test_models.py` (EXTEND) | test | transform | existing `load_fixture`-driven `from_payloads` tests | exact |
| `tests/test_uv.py` (EXTEND) | test | transform | existing `compute_uv` tests | exact |
| `tests/test_import_hygiene.py` (EXTEND) | test | — | existing source-reading substring gate | role match |

**Confirmed filenames:** `tests/test_uv_monitor.py` exists (not `test_uvmonitor.py`). `tests/conftest.py` provides `load_fixture` and `tmp_db` fixtures; `tests/test_uv_monitor.py` has a local `_run(payload, *, tmp_db, now_utc, uv, channel)` helper (`:342`) and `_at(hh, mm)` time builders.

---

## Pattern Assignments

### `weatherbot/weather/dates.py` (CREATE — utility, transform) — D-08/D-06

**Primary analog:** `weatherbot/scheduler/days.py` (module shape) + `weatherbot/weather/multiday.py` (`_resolve_tz` + `from __future__`/`TYPE_CHECKING` usage). **Source of the three copies to collapse:** `models.py:69`, `store.py:210`, `uvmonitor.py:84`.

**Module-shape / import pattern to copy** — from `multiday.py:24-46` (the acyclic pure-helper precedent, stdlib + `TYPE_CHECKING`-only domain import):
```python
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
# multiday.py declares NO config/apscheduler/store import — dates.py must match.
```
`multiday._resolve_tz` (`:39-46`) is the exact tz-resolution body to reuse for the wrapper:
```python
def _resolve_tz(tz: str | None) -> timezone | ZoneInfo:
    if tz:
        try:
            return ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            return timezone.utc
    return timezone.utc
```

**The three copies to unify (verbatim, so byte-identical output is provable):**

`uvmonitor.py:84-90` — the `(now_utc, tz)` core primitive (already resolved-tz signature):
```python
def _local_date_iso(now_utc: datetime, tz: ZoneInfo) -> str:
    return now_utc.astimezone(tz).date().isoformat()
```

`store.py:210-224` and `models.py:69-84` — verbatim twins, the `(Location, now_utc)` wrapper signature:
```python
def _local_date_iso(location: Location, now_utc: datetime) -> str:
    tz_name = getattr(location, "timezone", None)
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
    else:
        tz = timezone.utc
    return now_utc.astimezone(tz).date().isoformat()
```

**D-06 hardening to fold into the core primitive** (new — attach UTC when naive so `astimezone()` never reinterprets in HOST tz):
```python
if now_utc.tzinfo is None:
    now_utc = now_utc.replace(tzinfo=timezone.utc)
```

**Recommended target shape** (RESEARCH §Code Examples): core `local_date_iso(now_utc, tz)` (uvmonitor signature + D-06 guard) + thin `local_date_for(location, now_utc)` wrapper (models/store signature) that calls `local_date_iso(now_utc, _resolve_tz(getattr(location,"timezone",None)))`. Public names (no leading underscore) since three modules import it — mirror `days.parse_days` / `multiday.select_days` which are public.

**Import-cycle check (verified in RESEARCH):** `dates.py` is a leaf — `models`/`store`/`uvmonitor` import from `weather.uv`/`weather.store`/`scheduler.catchup` but none import `weather.dates` today. `Location` referenced under `TYPE_CHECKING` only (mirrors `catchup.py:29-30`).

**Call-site swaps:**
- `models.py`: `_local_date_iso(loc, now_utc)` → `local_date_for(loc, now_utc)` (used at `:388` local_date write).
- `store.py`: `_local_date_iso(location, now_utc)` → `local_date_for(location, now_utc)` (used at `persist:236` `target_local_date`).
- `uvmonitor.py`: `_local_date_iso(now_utc, tz)` → `local_date_iso(now_utc, tz)`.

---

### `weatherbot/scheduler/catchup.py` (MODIFY — service, batch) — D-01/D-02

**Analog:** its OWN existing compose/gates, `plan_catchup` `:146-177`.

**Existing single-`now_local.date()` compose to wrap in a candidate loop** (`:151-177`):
```python
hh, mm = slot.parsed_time()
naive = datetime(now_local.year, now_local.month, now_local.day, hh, mm)
off0 = naive.replace(tzinfo=tz, fold=0).utcoffset()
off1 = naive.replace(tzinfo=tz, fold=1).utcoffset()
scheduled = naive.replace(tzinfo=tz)
roundtrip = (
    scheduled.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
)
if off0 != off1 and roundtrip != naive:
    continue  # gap time — never existed (spring-forward). PRESERVE UNCHANGED (D-02).
if scheduled > now_utc:
    continue
if now_utc - scheduled > GRACE:  # <-- D-02 inflation risk lives here
    continue
local_date = now_local.date().isoformat()   # <-- D-01: must become CANDIDATE date
if was_sent(loc.id, slot.time, local_date):
    continue
missed.append(MissedSlot(loc, slot, scheduled, local_date))
```

**D-01 change:** wrap the above in `for cand_date in (now_local.date(), now_local.date() - timedelta(days=1)):`, composing `naive = datetime(cand_date.year, cand_date.month, cand_date.day, hh, mm)`, and set `local_date = cand_date.isoformat()` INSIDE the loop (Pitfall 1: never key yesterday's recovery on `now_local.date()`). Add an `emitted_dates: set[str]` dedup so a slot never emits twice. `timedelta` already imported (`:25`).

**D-02 fold grace (keep `fold=0` compose — verified to match live CronTrigger 3.11.2):** replace the bare `now_utc - scheduled > GRACE` with a both-folds `min()` lateness so a slot minutes-late inside a fall-back repeated hour is not dropped by 60-min inflation:
```python
due_within = min(
    now_utc - naive.replace(tzinfo=tz, fold=0).astimezone(timezone.utc),
    now_utc - naive.replace(tzinfo=tz, fold=1).astimezone(timezone.utc),
)
if due_within > GRACE:
    continue
```
(For all non-fall-back times `off0 == off1`, so both folds resolve identically and `due_within` is exact.) The `scheduled` composed for `MissedSlot`/`> now_utc` stays `fold=0` (CronTrigger agreement — do NOT switch to `fold=1`).

**MissedSlot dataclass** (`:52-60`) — `local_date` field docstring says "date component of the D-06 idempotency key"; keep the field, just feed it the candidate date.

---

### `weatherbot/scheduler/uvmonitor.py` (MODIFY — service, event-driven) — D-03/D-04 + D-08 swap

**Reusable guard (already present, extend/share for D-05):** `_daily0_matches_today` `:93-110` — derives `daily[0]`'s own local date from its `sunrise` in the configured tz and requires it to equal `local_date`. This IS the pattern `models`/`compute_uv` must gain:
```python
def _daily0_matches_today(sunrise_epoch: int, tz: ZoneInfo, local_date: str) -> bool:
    try:
        daily0_date = _dt.fromtimestamp(int(sunrise_epoch), tz=tz).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    return daily0_date == local_date
```

**D-03 all-clear hysteresis** — replace `_decide` branch 3 (`:317-323`), the CONFIRMED F15 latch:
```python
# CURRENT (bug): latches on one instantaneous dip
if summary.current < threshold and "crossing" in prior and "allclear" not in prior:
    if claim_uv_alert(db_path, location.id, local_date, "allclear"):
        _post(channel, f"✅ UV back below {t} in {name} — protect window over.")
```
`UvSummary` already carries the facts to gate on (`weather/uv.py:34-53`: `peak_time`, `window_end`, `crossing_time`, `hourly_points`). Recommended stateless primary gate (RESEARCH Pattern 3): require `below AND past_peak AND window_over` where `past_peak = summary.peak_time and now_local >= summary.peak_time` and `window_over = summary.window_end and now_local >= summary.window_end`. When `window_end`/`peak_time` are `None` (empty hourly), degrade to "don't post all-clear yet" rather than latch or add a persistence table (A2/Open-Q1: keeps store data-model out of scope, F36/F37 deferred).

**D-04 lifecycle no-never-fire-gap** — audit branches `:256-323`: already-high/crossing (`:257`, daylight-gated), pre-warn (`:286-315`, daylight-gated), all-clear (`:318`, NOT daylight-gated per WR-01 comment `:243-245`). Preserve the WR-02 claim-crossing-before-moot-prewarn ordering (`:267-272`) — the D-04 audit must not orphan a state or block a later crossing/all-clear.

**D-08 swap:** delete local `_local_date_iso` (`:84`), import `local_date_iso` from `weatherbot.weather.dates`.

---

### `weatherbot/weather/models.py` (MODIFY — model, transform) — D-05/D-06

**Analog:** `multiday._date_index_map` `:49-58` (no-positional-math) + `uvmonitor._daily0_matches_today`.

**Positional `daily[0]` hard-index to replace** (`from_payloads`, `:302-303`, the F35 defect):
```python
day_i = (onecall_imp.get("daily") or [{}])[0] or {}
day_m = (onecall_met.get("daily") or [{}])[0] or {}
```
**Selector pattern to introduce** (RESEARCH Pattern 2 — synthesis of `_daily0_matches_today` + `_date_index_map`): match by the entry's OWN local date via `dt`/`sunrise` in the configured tz; return `None` if no entry matches today. On `None`, take the EXISTING degrade path (`high_imp=None`, rain from `{}`, UV → `stays_below` via `compute_uv`'s empty path) — the fail-safe posture already in the file (`:294` "degrades ... WITHOUT raising"). NEVER ship a non-today entry as today.

**Reference `_date_index_map` body to adapt** (`multiday.py:49-58`):
```python
for i, day in enumerate(daily or []):
    dt = (day or {}).get("dt")
    if dt is None:
        continue
    local = datetime.fromtimestamp(dt, tz).date()
    out.setdefault(local, i)
```

**D-06:** route the `local_date` write (`:388`) through the shared `local_date_for` helper (naive-`now_utc` hardening baked in). `now_utc` default at `:296-297` (`datetime.now(timezone.utc)`) is fine; the F33 risk is an INJECTED naive `now_utc` (the new `test_naive_now_utc_treated_as_utc` test).

---

### `weatherbot/weather/uv.py` (MODIFY — service, transform) — D-05/D-07

**F31 daily0-today guard (D-05):** `compute_uv` (`:193-224`) reads `daily0 = (raw.get("daily") or [{}])[0] or {}` at `:219` and trusts its `uvi`/sunrise unconditionally. Add the same `_daily0_matches_today`-style guard the monitor already has: if the chosen entry's own local date != today's configured-tz date, degrade to the empty-points / `stays_below=True` path (`:241`) rather than compute against a stale sunset. Reuse the shared selector from D-05 (lean: one selector in `dates.py` or `uv.py`, per Open-Q2).

**F32 sort (D-07):** `_today_daytime_points` (`:98-146`) appends buckets in raw payload order (`:145 points.append(...)`); the interpolators `_first_up_cross` (`:159`) and `_first_down_cross_after` (`:177`) `zip(points, points[1:])` assume time-order. Add ONE line before `return tuple(points)` (`:146`):
```python
points.sort(key=lambda p: p[0])   # D-07/F32: time-sorted before interpolation
return tuple(points)
```

---

### `weatherbot/weather/store.py` (MODIFY — store, file-I/O) — D-08 swap only

Delete local `_local_date_iso` (`:210-224`), import `local_date_for` from `weatherbot.weather.dates`. Call site: `persist:236` `target_local_date = local_date_for(location, now_utc)`. **Constraint:** must NOT regress the Phase-31 WAL/`_connect` refactor (`init_db:204-207`, `_connect` context manager). No schema/data migration — helper output is byte-identical for correct rows (A3).

---

### Tests (EXTEND) — Wave 0 failing-first regression hooks

**Analog conventions to copy:**
- `tests/test_scheduler.py:149-175` — `_home_config(days, time, enabled)`, `_utc_for_local(y,mo,d,hh,mm,tz)`, `_never_sent`, `_NY = ZoneInfo("America/New_York")`, injected `now_utc` into `plan_catchup`. Extend `test_dst_transition_band_exactly_once` neighbor for `test_catchup_fold_grace_not_inflated`; add `test_catchup_prior_local_day` (23:45→00:15).
- `tests/test_uv_monitor.py:342` `_run(payload, *, tmp_db, now_utc, uv, channel)` + `_at(hh,mm)` + `_clone(...)` + `load_fixture("onecall_imperial_highuv.json")`. Model `test_allclear_not_latched_on_momentary_dip` and `test_lifecycle_full_day_no_never_fire_gap` on existing `test_daily0_prior_day_skips_decision` (`:251`).
- `tests/test_models.py` / `tests/test_uv.py` — `load_fixture`-driven `from_payloads`/`compute_uv` with injected `now_utc`/`now`; new `test_daily0_not_today_degrades`, `test_naive_now_utc_treated_as_utc`, `test_compute_uv_daily0_today_guard`, `test_hourly_points_sorted_before_interpolation`.
- `tests/test_import_hygiene.py` — the source-reading substring-gate style (`APP = "weatherbot"`, `Path(__file__).resolve().parent.parent / APP`); add a `dates` same-output test + assert all three callers import the ONE helper.

**Fixtures:** `load_fixture` + `tmp_db` in `tests/conftest.py:26-` — no new framework install.

---

## Shared Patterns

### Pure acyclic helper module shape (D-08)
**Source:** `weatherbot/scheduler/days.py` (docstring `:1-12` states "intentionally dependency-free ... so ... can import ... without an import cycle") and `weatherbot/weather/multiday.py:1-46`.
**Apply to:** new `weather/dates.py` — stdlib-only imports, `from __future__ import annotations`, domain types under `TYPE_CHECKING`, public function names.

### "No positional math — match by own local date" (D-05)
**Source:** `multiday._date_index_map` `:49-58` + `uvmonitor._daily0_matches_today` `:93-110`.
**Apply to:** `models.from_payloads` (`:302`), `uv.compute_uv` (`:219`). Derive each `daily[i]`'s date from `dt`/`sunrise` in the CONFIGURED tz; never trust index `[0]`.

### Fail-safe degrade (never raise on malformed/missing/mismatched)
**Source:** `uv.py:120-145` (skip malformed bucket), `uv.py:241` (`stays_below=True` on empty), `models.py:294`/`:299` (`or {}`/`or []` coalesce). ASVS V5.
**Apply to:** the new selector (no-today-entry → degrade path), the hourly sort, the all-clear gate (empty hourly → don't post) — reuse the existing empty/`stays_below`/`None` collapse; invent NO new user-facing string (D-05 discretion).

### CronTrigger fold agreement (D-02)
**Source:** `catchup.py:17-19` + `:154-168` docstring/roundtrip; verified live `apscheduler 3.11.2` fires fall-back at `fold=0`.
**Apply to:** keep the composed `scheduled` at `fold=0`; both-folds `min()` only for the grace comparison.

### Configured IANA tz is authoritative (D-03 convention)
**Source:** `uvmonitor.py:26-28`, `models._local_date_iso` docstring (Pitfall 3 — never the API `timezone` field).
**Apply to:** every date decision this phase — all resolve through `Location.timezone`, never the payload offset.

### Injected `now_utc` purity (testability)
**Source:** `catchup.py:11-13` / `plan_catchup(now_utc=None)`; `compute_uv(now=None)`; `_uv_monitor_tick(now_utc=None)`.
**Apply to:** every fix + every Wave-0 test — inject the clock, no wall-clock waits.

## No Analog Found

None. Every file has a strong in-repo analog (this is a consolidation/correctness phase, not new mechanism — RESEARCH "Key insight").

## Metadata

**Analog search scope:** `weatherbot/scheduler/` (`catchup.py`, `days.py`, `uvmonitor.py`), `weatherbot/weather/` (`models.py`, `uv.py`, `store.py`, `multiday.py`), `tests/` (`test_scheduler.py`, `test_uv_monitor.py`, `test_import_hygiene.py`, `conftest.py`).
**Files scanned:** 11 source/test files read (targeted ranges), all confirmed against RESEARCH line refs.
**Pattern extraction date:** 2026-07-11
