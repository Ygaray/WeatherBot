# Phase 34: Test-Gap Backfill - Pattern Map

**Mapped:** 2026-07-13
**Files analyzed:** 7 target test files (13 tests to add/fix)
**Analogs found:** 13 / 13 (every target has an in-file or cross-file analog)

> This is a **tests-only** phase. "Files to be created/modified" are the existing pytest
> modules; the closest analog for each new/corrected test is almost always an existing test
> **in the same file** (or the cross-file `test_config_holder.py` threading harness for F106).
> Every excerpt below is copy-ready — the planner should lift them into task `<read_first>`
> (analog file:line) and `<action>` (the concrete change) fields. RESEARCH.md already grounds
> every production symbol at file:line; this doc adds the **test-side** analog code to copy.

## File Classification

| Target test file | Test to add/fix | Finding | Role / Data flow | Closest analog (file:line) | Match |
|---|---|---|---|---|---|
| `tests/test_scheduler.py` | fix `test_concurrent_double_fire_delivers_once` → real threads + meta-guard | F106 | concurrency / real-thread race | `test_config_holder.py:89` harness + `test_scheduler.py:817` (current body) | exact (harness) |
| `tests/test_scheduler.py` | add rename-safe `id != name` through `fire_slot`/`plan_catchup`/alert-dedup | F108 | integration / request-response | `test_scheduler.py:817` (fire_slot drive) + `:176` (plan_catchup drive) | role-match |
| `tests/test_scheduler.py` | F14 midnight catch-up | F14 | unit / pure planner | **`test_scheduler.py:312` `test_catchup_prior_local_day` — ALREADY EXISTS** | **[EXISTS]** |
| `tests/test_reliability.py` | fix `test_heartbeat_upsert` tick/success separation | F114 | unit / store row | `test_reliability.py:606` (current body) | exact |
| `tests/test_reliability.py` | fix `test_two_burst_wait_shape` bound `<150.0`→`step*1.5` | F112 | unit / wait value | `test_reliability.py:95` (current) + `:285/:294` (derived-bound precedent) | exact |
| `tests/test_reliability.py` | add Retry-After 429 on `attempt==BURST_SIZE` collapse | F110 | unit / wait value | `test_reliability.py:259-294` (Retry-After honoring + `_State`/`_Outcome`) | role-match |
| `tests/test_models.py` | strengthen/confirm dt-paired imperial/metric | F107 | unit / model transform | `test_models.py:141` `test_dt_paired_briefing` (**likely [EXISTS]**) | exact |
| `tests/test_models.py` | add positive daily[0]==today (today not at index 0) | F109 | unit / model transform | `test_models.py:664` `test_daily0_not_today_degrades` (negative twin) | exact |
| `tests/test_multiday.py` | add weekend whole-block roll-forward | F111 | unit / day selector | `test_multiday.py:168` `test_weekday_run_on_saturday_rolls_forward` | exact |
| `tests/test_multiday.py` | add null-`dt` skip in `_date_index_map` | F113 | unit / day selector | `test_multiday.py:157` `test_weekend_run_returns_fri_sat_sun` (select_days call shape) | role-match |
| `tests/test_cache.py` | fix distinct `id != name` cache-key collapse | F115 | unit / cache key | `test_cache.py:73` `test_second_lookup_within_ttl_hits_cache` + `_loc` helper `:53` | exact |
| `tests/test_reload_engine.py` | fix reconcile register-before-remove order | F116 | unit / order log | `test_reload_engine.py:155` `test_reload_committed_success_diff_...` + `_FakeSchedulerEngine:41` | exact |
| `tests/test_store.py` | add transactional both-or-neither `persist` | F37/F63/F01 | unit / store txn | `test_store.py:79` `test_persist_onecall_writes_both_unit_rows` + `:73` idempotency | exact |

---

## Shared Patterns

### Canonical real-thread harness (F106) — `tests/test_config_holder.py:89-133`
The repo's established concurrency shape: shared `errors: list[BaseException]`, threads,
`except BaseException: errors.append(exc)` (never swallow), bounded, **no real sleeps**, final
`assert not errors`. For F106, swap the reader/writer for two `fire_slot` racers and **add a
`threading.Barrier(2)`** (D-03).
```python
# test_config_holder.py:102-133 — the shape to copy
errors: list[BaseException] = []
stop = threading.Event()
def reader():
    try:
        while not stop.is_set():
            ...  # do work
    except BaseException as exc:  # noqa: BLE001 — record, never swallow
        errors.append(exc)
readers = [threading.Thread(target=reader) for _ in range(8)]
w = threading.Thread(target=writer)
for t in readers: t.start()
w.start(); w.join()
for t in readers: t.join()
assert not errors, f"concurrent ... recorded errors: {errors!r}"
```

### Fixtures — `tests/conftest.py`
```python
# conftest.py:52-69 — FILE-BACKED sqlite (both F106 threads share ONE file → real race)
@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    from weatherbot.weather.store import init_db
    db_path = tmp_path / "weatherbot.db"
    init_db(db_path)
    return db_path

# conftest.py:26-29 — recorded OpenWeather JSON loader (models/multiday tests)
@pytest.fixture
def load_fixture():
    return _load_fixture   # call: load_fixture("onecall_imperial_dtskew.json")

# conftest.py:86-113 — seed a real sent_log row via production claim_slot
def _seed_sent_row(db_path, location_id, send_time, local_date) -> None:
    from weatherbot.weather.store import claim_slot
    won = claim_slot(db_path, location_id, send_time, local_date)
    assert won is True
# fixture name: seed_sent_row
```

### RetryCallState stand-ins (F110/F112) — `tests/test_reliability.py:82-87`
```python
class _State:  # minimal RetryCallState for driving two_burst_wait directly
    def __init__(self, attempt_number, outcome=None):
        self.attempt_number = attempt_number
        self.outcome = outcome
# _Outcome wraps an exception; _status_error(429, headers={"Retry-After": "..."}) builds the 429.
```

### Traceability (D-02) — every new/corrected test names its finding id + requirement
Precedent already in-tree: `test_models.py:664` header `# D-05 / F35 / F109`;
`test_scheduler.py:312` `# D-01 / F14 (CONFIRMED)`. Match this in the test name or docstring.

---

## Pattern Assignments

### `tests/test_scheduler.py` — F106 real concurrency + meta-guard (fix)

**Analog (current false-green):** `test_scheduler.py:817-861`. The defect is the **sequential**
double call:
```python
# test_scheduler.py:858-861 — the SEQUENTIAL fake (replace with barrier threads)
fire_slot(loc, slot, **kwargs)
fire_slot(loc, slot, **kwargs)
assert len(channel.sent_text) == 1
```
**fire_slot drive kwargs (reuse verbatim, no holder):** `test_scheduler.py:840-854`
```python
client = _FakeClient(load_fixture("onecall_imperial_clear.json"),
                     load_fixture("onecall_metric_clear.json"))
channel = _FakeChannel()          # one shared channel counts POSTs across both fires
scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)
kwargs = dict(config=cfg, db_path=tmp_db, client=client, channel=channel,
              scheduled_dt=scheduled, late=True)
```
**What to change:** wrap two `fire_slot(loc, slot, **kwargs)` calls in worker threads gated by a
`threading.Barrier(2)` placed immediately before each `fire_slot` call; collect exceptions into a
shared `errors` list (harness above); assert `len(channel.sent_text) == 1` AND exactly one non-None
`fire_slot` return AND `not errors`. The `tmp_db` fixture is file-backed so both threads race the
real `INSERT OR IGNORE` (RESEARCH store.py:303-310).
**Meta-guard (D-04):** co-located `test_..._metaguard` — monkeypatch
`weatherbot.weather.store.claim_slot` to a SELECT-then-INSERT shim (read `was_sent`, then
unconditional INSERT), run the SAME barrier-threaded body, assert it produces **2** deliveries.

### `tests/test_scheduler.py` — F108 rename-safe `id != name` (add)

**Analog:** the F106 `fire_slot` drive (`:840-854`) for the fire path; `test_catchup_window`
(`:176`) for `plan_catchup(cfg, was_sent_spy, now_utc=...)`. `_home_config` (`:152`) builds the
single-location config but with `name=id`.
**What to change:** build `Location(name="Beach House", id="loc-7")` (name ≠ id — see the
`_home_config` Location kwargs at `:156-162`, add `id="loc-7"`). Drive `fire_slot`, then read
`sent_log`/`alerts` and assert `location_name == "loc-7"` (the id, NOT `"Beach House"`). Drive
`plan_catchup` with a `was_sent` spy (like `_never_sent` at `:172`, but recording its args) and
assert it was queried with `"loc-7"`.

### `tests/test_scheduler.py` — F14 midnight catch-up → **[EXISTS], VERIFY ONLY**

`test_catchup_prior_local_day` (`test_scheduler.py:312-361`) already pins the exact D-08 scenario:
23:45 slot recovered at 00:15 next local day → one MissedSlot keyed on **yesterday** (`2026-06-10`),
with `now_utc` injected via `_utc_for_local(2026, 6, 11, 0, 15)` (no wall-clock, no time-machine),
plus GRACE edges and the already-sent dedup. **Action: confirm it is green and cite it for SC-3;
do not duplicate.** (If any D-08 aspect is missing, extend this test rather than add a new one.)

### `tests/test_reliability.py` — F114 heartbeat tick/success (fix)

**Analog (current):** `test_reliability.py:606-618`
```python
init_db(tmp_db)
daemon_mod._heartbeat_tick(tmp_db)
row = _heartbeat(tmp_db)
assert row["last_tick_utc"] is not None   # <-- only checks tick
```
**What to change:** add `assert row["last_success_utc"] is None` after a bare tick; then call
`stamp_success(tmp_db)`, re-read via `read_heartbeat` (store.py:508 → `{"last_tick_utc",
"last_success_utc"}`), assert `last_success_utc is not None` and `last_tick_utc` unchanged.

### `tests/test_reliability.py` — F112 tighten within-burst bound (fix)

**Analog (current false-green):** `test_reliability.py:95-102`, loose `assert 0.0 <= wait < 150.0`.
**Derived-bound precedent already in this file:** `:285` `step = BURST_SPREAD_S/(BURST_SIZE-1)`
and `:294` `assert step <= no_ra_wait < step * 1.5`.
**What to change:** replace the `< 150.0` bound with a constant-derived ceiling (never a magic
literal, A1):
```python
step = BURST_SPREAD_S / (BURST_SIZE - 1)   # 85.714…
ceiling = step * 1.5                        # 128.571…
for n in list(range(1, BURST_SIZE)) + list(range(BURST_SIZE+1, 2*BURST_SIZE)):
    wait = two_burst_wait(_State(n))
    assert step <= wait <= ceiling
assert two_burst_wait(_State(BURST_SIZE)) == MID_PAUSE_S   # keep (line 102)
```

### `tests/test_reliability.py` — F110 Retry-After on `attempt==BURST_SIZE` (add)

**Analog:** the honoring test `:259-294` (uses `build_retrying` + mocked sleep, and the
`_State`/`_Outcome`/`_status_error` stand-ins). The gap: existing honoring fires 429 on
attempt **1**; the untested case is `attempt == BURST_SIZE` where base = `MID_PAUSE_S` (2700)
and a capped Retry-After **collapses** it to `RETRY_AFTER_CAP_S`.
**What to change (direct `two_burst_wait` drive):**
```python
state = _State(BURST_SIZE, _Outcome(_status_error(429, headers={"Retry-After": "9999"})))
assert two_burst_wait(state) == RETRY_AFTER_CAP_S      # 120, NOT 2700 (MID_PAUSE_S)
# contrast: no header on the mid-pause attempt stays MID_PAUSE_S
assert two_burst_wait(_State(BURST_SIZE)) == MID_PAUSE_S
```

### `tests/test_models.py` — F107 dt-pairing (strengthen / confirm)

**Analog:** `test_dt_paired_briefing` (`test_models.py:141-163`) — **likely already sufficient**:
it uses the `dtskew` fixtures, asserts `high_display == "76°F"` / `"58°F"`, and guards the
mispair with `assert fc.high_display != "76°F (100°C)"` (line 163). **Action:** read the full
assertion; if it already pins that the wrong-day °C never appears, mark F107 `[EXISTS]` (Open
Question 2). Otherwise add the missing "degrades to None, never mispairs" assertion in the same
style.

### `tests/test_models.py` — F109 positive (today not at index 0) (add)

**Analog (negative twin):** `test_daily0_not_today_degrades` (`:664-686`) — uses a
`_shift_daily0_back_one_day` helper and `Forecast.from_payloads(LOC, imp, met, now_utc=NY_NOW)`.
**What to change:** build a payload where today's entry is at `daily[2]` (yesterday at `[0]`,
today at `[2]`) and assert `fc.high_imp`/`fc.low_imp` equal the **index-2** values (not index-0)
and `fc.local_date == <configured-tz today>`. ⚠ **D-07 watchpoint (RESEARCH A2):** if
`select_today_daily` has an off-by-one and this goes red against current code, treat as a real
escape and fold the minimal fix.

### `tests/test_multiday.py` — F111 weekend whole-block roll-forward (add)

**Analog (weekday twin):** `test_weekday_run_on_saturday_rolls_forward` (`:168-176`):
```python
indices, notices = multiday.select_days(
    "weekday", date(2026, 6, 20), daily, add=set(), drop=set(), tz=_TZ)
assert indices == [3, 4, 5, 6, 7]
assert notices == []
```
**What to change:** call `select_days("weekend", <a Monday>, daily, add=set(), drop=set(),
tz=_TZ)` where Fri/Sat/Sun are all past → assert indices resolve to **next-week** Fri-Sat-Sun
(against an 8-day `daily`) or horizon notices, with no `IndexError`. Use the `imp` fixture
(`test_multiday.py:35`) / 8-day fixtures. Weekend-block base is `_WEEKEND_DAYS = ("fri","sat","sun")`.

### `tests/test_multiday.py` — F113 null-`dt` skip (add)

**Analog (call shape):** `test_weekend_run_returns_fri_sat_sun` (`:157-165`).
**What to change:** pass a `daily` list with one entry `{"dt": None, ...}` (and/or a fully-null
entry) alongside valid entries; assert `select_days` **skips** the null-dt entry (never in
`by_date`), returns valid indices for the good entries, and emits a notice (not `IndexError`/
`TypeError`) for a desired date whose only candidate had a null dt.

### `tests/test_cache.py` — F115 distinct `id != name` (fix)

**Analog:** `test_second_lookup_within_ttl_hits_cache` (`:73-88`) — monkeypatches
`cache_mod.lookup_weather` to append into a `fetches` list, then asserts two lookups → one fetch.
The `_loc` helper (`:53-59`) **already accepts** `_loc(name, id=...)` but is never exercised with
`id != name`.
**What to change:** build `_loc("Cabin", id="loc-42")`; look up by the **name** `"Cabin"` (and a
case variant `"cabin"`); assert the cache collapses on the **id** — two `"Cabin"` lookups → one
fetch; a location whose *name* differs but *id* matches hits the same entry; a location whose *id*
differs does NOT hit. Assert the resolved key is the id, not the name.

### `tests/test_reload_engine.py` — F116 register-before-remove order (fix)

**Analog:** `test_reload_committed_success_diff_removes_excluded_and_summary` (`:155-177`) asserts
`calls["register"] == [new_cfg]` and `fake.removed == ["gone"]` but **not ordering**. The
`_FakeSchedulerEngine.remove` (`:51-53`) already records into `self.removed`.
**What to change:** thread a shared **order log** — the injected `register_jobs` appends
`"register"`, and `_FakeSchedulerEngine.remove` appends `f"remove:{job_id}"` (into the same shared
list). After `engine.reload(...)`, assert `order.index("register") < order.index("remove:gone")`
(register strictly before every remove — the no-gap-in-jobs invariant). Hub symbol under test;
test stays app-side via injected stubs (no hub change).

### `tests/test_store.py` — F37/F63/F01 transactional both-or-neither (add)

**Analog:** `test_persist_onecall_writes_both_unit_rows` (`:79-89`) asserts both rows exist on
success; `test_init_db_is_idempotent` (`:73-76`) covers idempotency.
**What to change (F37/F63):** monkeypatch the **second** `conn.execute` (the metric INSERT) inside
`persist` to raise, call `persist`, and assert **zero** committed `weather_onecall` rows (imperial
INSERT rolled back with the metric failure — both-or-neither). Optionally assert WAL is persistent
(`journal_mode=wal` on a fresh connect). **F01:** verify ≥1 existing best-effort test in
`test_reliability.py` (`:428+`) pins "a raise in resolve_alert/stamp_success after `result.ok`
keeps the delivered claim" (RESEARCH A3); add one only if absent.

---

## No Analog Found

None. Every target has an in-file analog or the cross-file threading harness. All fixtures
(`tmp_db` file-backed, `load_fixture`, `seed_sent_row`), the `_State`/`_Outcome` stand-ins, the
`_FakeSchedulerEngine`, the `_loc(id=...)` helper, and the dtskew / 8-day fixtures already exist
(RESEARCH "Wave 0 Gaps: None").

## Already-Covered (verify-only, do NOT duplicate)

- **F14** — `test_scheduler.py:312` `test_catchup_prior_local_day` fully pins the midnight
  catch-up scenario. Cite for SC-3; extend only if a D-08 aspect is missing.
- **F107** — `test_models.py:141` `test_dt_paired_briefing` likely already pins the mispair guard
  (line 163). Read first; strengthen only if the "degrade-not-mispair" assertion is absent.
- **F01** — likely covered by `test_reliability.py:428+` best-effort tests; confirm the specific
  "raise-after-ok keeps claim" assertion exists.

## Metadata

**Analog search scope:** `tests/` (test_scheduler, test_reliability, test_models, test_multiday,
test_cache, test_reload_engine, test_store, test_config_holder, conftest).
**Files scanned:** 9 test modules + conftest.
**Pattern extraction date:** 2026-07-13
