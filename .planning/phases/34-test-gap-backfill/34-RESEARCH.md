# Phase 34: Test-Gap Backfill - Research

**Researched:** 2026-07-13
**Domain:** Python test hardening (pytest 9.x + real-thread concurrency) — correcting false-green tests and backfilling regression coverage for the v2.1 audit fixes (Phases 29–33). Tests-only.
**Confidence:** HIGH — every finding is grounded in the actual current source/test code (quoted with file:line), verified against a green baseline run (`869 passed`, exit 0).

## Summary

This is a **tests-only** phase with two jobs, both already methodology-locked in CONTEXT.md (D-01..D-08): (1) correct five false-green tests that pass against broken/weak behavior, and (2) add regression tests on the exact high-risk paths the fixed bugs lived in. The production fixes already shipped in Phases 29–33 — this phase adds/repairs the tests around merged code. Every correction is `[VERIFIED: codebase grep]` against the real source; no library research is needed (no packages installed).

The single most important grounding result: **all of the "id==name" and "loose bound" hiding conditions are real and reproducible in the current tree.** `Location.id` defaults to `name` (`weatherbot/config/models.py:199-207`), so every existing test using `Location(name="Home")` has `id == name == "Home"` — which is exactly why F108/F115 can't tell whether the code reads `.id` or `.name`. The F106 "concurrent" test (`tests/test_scheduler.py:817`) calls `fire_slot(...)` **twice sequentially** (lines 858-859), never concurrently. The F112 bound is a literal `< 150.0` (`tests/test_reliability.py:100`) where the real jittered ceiling is `128.57s`. The F114 heartbeat test (`tests/test_reliability.py:606`) asserts `last_tick_utc is not None` but **never** asserts `last_success_utc` stays `None` after a bare tick.

**Primary recommendation:** Extend the six named per-module test files (D-01) with assertion-by-construction tests (D-05) that pin the exact observable each fix produces — a `sent_log` row count / one channel POST (F106), `last_success_utc is None` (F114), `< 128.57` (F112), a distinct `id != name` cache key (F115), a register-before-remove order log (F116), `location.id` threaded through `fire_slot`/`plan_catchup`/`record_alert` (F108), dt-paired daily buckets (F107), a today-anchored `daily[0]` selector (F109), weekend whole-block roll-forward (F111), a `dt=None` skip in `_date_index_map` (F113), a `Retry-After`-on-`attempt==BURST_SIZE` collapse (F110), midnight catch-up via `emitted_dates` (F14), and a transactional both-or-neither `persist` (F37/F63). Reuse the `test_config_holder.py:89` real-thread/error-list/no-sleep pattern for F106 (D-03), adding a `threading.Barrier`.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Test Organization & Traceability**
- **D-01:** Extend the **existing per-module test files** — `tests/test_scheduler.py`, `tests/test_reliability.py`, `tests/test_models.py`, `tests/test_multiday.py`, `tests/test_cache.py`, `tests/test_reload_engine.py`. Do **not** create a new consolidated module. Matches the repo's one-file-per-module convention.
- **D-02:** Each new/corrected test **names its audit finding id and requirement** in the test name or docstring (e.g. `# F106 / HARD-TEST-01`) so the fix↔test↔finding chain is auditable from the test source alone.

**Concurrency Proof Mechanism (F106)**
- **D-03:** Make `test_concurrent_double_fire_delivers_once` (`tests/test_scheduler.py:817`) **actually concurrent** by reusing the repo's real-thread pattern from `tests/test_config_holder.py:89`: two worker threads both call `fire_slot(...)` on the **same slot key**, synchronized with a `threading.Barrier` so both hit `claim_slot` simultaneously against the **shared file-backed `tmp_db`**; collect exceptions in a shared list (never swallow); assert **exactly one delivery** (one POST / one `sent_log` row) and no error. Deterministic *outcome* assertion — **no real `sleep`s**.
- **D-04:** Include a co-located **meta-guard** showing a weakened `SELECT-then-INSERT` `claim_slot` variant (local monkeypatched shim) makes the concurrent test **fail**. The real atomicity lives in `store.py` `INSERT OR IGNORE` + `UNIQUE` — the test must break if that guarantee is removed.

**"Fails-Pre-Fix" Demonstration (SC-3)**
- **D-05:** Default to **assertion-by-construction** — write the exact assertion the bug violated, so the test is red against pre-fix behavior by design.
- **D-06:** For the **highest-risk corrections** (F106 concurrency, F114 heartbeat tick/success separation, F112 loose-bound tightening), additionally record a **documented mutation spot-check in the Gate-1 self-UAT log**: temporarily revert/weaken the fix (`git stash` or a local shim), show the new test goes **red**, then restore and show **green**. Do **not** add a mutation-testing dependency.

**Latent-Bug Escape Handling**
- **D-07:** If a backfill test goes **red against current (post-fix) code**, treat it as a **real escape**, not a test bug. Correctness-first: fold the **minimal** fix into this phase and keep the pinning test. Escalate to the user only if the required fix is large or clearly out of scope.

**Coverage Ledger (D-08):** F106–F116 are the explicit cluster, but SC-3 requires **every** Phase 29–33 correctness fix to have ≥1 pinning test. Two roadmap-named id-less paths must be covered:
- **Catch-up across local midnight** → the **F14** fix (Phase 32).
- **Store atomicity / data-loss path** → **F37** (no `UNIQUE` on `weather_onecall`) / **F63** (`executescript` force-commit) / **F01** (post-send bookkeeping re-fire) fixes (Phase 31).

### Claude's Discretion
- Exact test function names, whether to extract a shared threading/barrier helper into `conftest.py`, and the precise per-finding assertion wording.

### Deferred Ideas (OUT OF SCOPE)
- **Mutation-testing tooling** (mutmut / cosmic-ray) as a permanent dependency — rejected (D-06 uses a manual documented spot-check).
- **Cleanup-sweep findings** — belong to Phase 35.
- **Hub findings** (17 routed to `YahirReusableBot`) — out of this milestone.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HARD-TEST-01 | Correct the false-green tests (F106, F114, F112, F115, F116) | Each false-green located + weak assertion quoted below (§Finding Map); real behavior confirmed in source so the strengthened assertion is correct, not guessed. |
| HARD-TEST-02 | Add missing high-risk coverage (F110, F108, F107, F109, F111, F113, + F14 midnight catch-up, + F37/F63/F01 store atomicity) | Each production symbol located + signature + fix line confirmed; observable signal for each new test named (§Finding Map, §Validation Architecture). |

## Architectural Responsibility Map

All capabilities in this phase are **test-tier** (pytest suite). The production symbols under test map as follows:

| Capability under test | Production Tier | Symbol (file:line) | Rationale |
|------------------------|-----------------|--------------------|-----------|
| Delivery exactly-once (F106) | Scheduler + Store | `fire_slot` (`daemon.py:140`) → `claim_slot` (`store.py:274`) | Atomicity is a store `INSERT OR IGNORE`/`UNIQUE` property; the scheduler orchestrates it. |
| Rename-safe identity (F108) | Scheduler | `fire_slot`/`plan_catchup` use `location.id` | Identity key belongs to config→scheduler wiring, not the store. |
| Retry budget shape (F112, F110) | Reliability (hub) | `two_burst_wait` (`yahir_reusable_bot/reliability/retry.py:146`) | Retry engine is hub code; app re-exports via `weatherbot/reliability/retry.py` shim. Test drives via app import. |
| Heartbeat tick/success (F114) | Store | `stamp_tick`/`stamp_success` (`store.py:456/473`) | Two separate columns on one liveness row. |
| Cache key identity (F115) | Interactive | `ForecastCache.lookup` (`cache.py:129`) keys on `resolve_location(...).id` | Cache is app-side interactive tier. |
| Reload job ordering (F116) | Config/Reload (hub) | `ReloadEngine.reconcile` (`yahir_reusable_bot/config/reload.py:184-190`) | Engine is hub; test drives it via injected stubs (in-scope, app-side test). |
| Daily pairing/anchoring (F107, F109) | Weather models | `Forecast.from_payloads` (`models.py:250`) | Payload→briefing transform. |
| Multi-day window (F111, F113) | Weather multiday | `select_days` (`multiday.py:61`), `_date_index_map` (`multiday.py:49`) | Pure day selector. |
| Midnight catch-up (F14) | Scheduler | `plan_catchup` (`catchup.py:106`), `emitted_dates` loop (lines 157-201) | Pure missed-send planner. |
| Store atomicity (F37/F63) | Store | `persist` (`store.py:211`), `_SCHEMA` (`store.py:38`), `init_db` (`store.py:194`) | Two-INSERT single-commit transaction. |

## Finding Map — Exact Current Test, Production Symbol, and Required Assertion

> This is the load-bearing section for the planner. For each finding: (1) the false-green/missing test, (2) the production symbol it pins, (3) the concrete assertion/mechanism the corrected/new test needs.

### HARD-TEST-01 — Correct the false-green tests

#### F106 — sequential "concurrent" double-fire → make it real `[VERIFIED: codebase grep]`
- **Current test:** `tests/test_scheduler.py:817` `test_concurrent_double_fire_delivers_once`. The "concurrency" is faked — two **sequential** calls:
  ```python
  # tests/test_scheduler.py:858-861
  fire_slot(loc, slot, **kwargs)
  fire_slot(loc, slot, **kwargs)
  assert len(channel.sent_text) == 1
  ```
  A SELECT-then-INSERT `claim_slot` would ALSO pass this (the first call commits its row before the second reads), so it proves nothing about a real race.
- **Production symbol:** `claim_slot` (`weatherbot/weather/store.py:274-310`). Atomicity mechanism (quote for the meta-guard, D-04):
  ```python
  # store.py:303-310
  cur = conn.execute(
      "INSERT OR IGNORE INTO sent_log "
      "(location_name, send_time, local_date, sent_at_utc) "
      "VALUES (?, ?, ?, ?)", ...)
  conn.commit()
  return cur.rowcount == 1
  ```
  The `UNIQUE(location_name, send_time, local_date)` constraint lives at `store.py:116`. Exactly one concurrent claim returns `True` because SQLite's `INSERT OR IGNORE` is atomic against the unique index.
- **Observable seam to assert:** `fire_slot` returns a `DeliveryResult | None` (None on lost claim, `daemon.py:217`); the winner POSTs exactly once via the shared `_FakeChannel` (`channel.sent_text` length == 1), and exactly one `sent_log` row exists (`was_sent(...) is True`, `store.py:251`). Assert **both**: `len(channel.sent_text) == 1` AND exactly one non-None `fire_slot` return.
- **Harness to reuse (D-03):** `tests/test_config_holder.py:89-133` — shared `errors: list[BaseException]`, `threading.Event`/threads, `except BaseException: errors.append(exc)` (never swallow), bounded, no real sleeps, final `assert not errors`. **Add** a `threading.Barrier(2)` so both `fire_slot` racers block until both are inside `_attempt`'s claim window. `tmp_db` is a **real file** (`conftest.py:67`) so both threads share one sqlite file and genuinely race `INSERT OR IGNORE`.
- **Can `fire_slot` be driven from two threads against one `tmp_db`?** YES. `fire_slot` accepts `config=`, `db_path=`, `client=`, `channel=`, `scheduled_dt=` (no holder needed) — see kwargs at `daemon.py:847-854`. Two threads call it with the same kwargs and a shared `_FakeChannel`.
- **Barrier placement:** Put the barrier BEFORE the `fire_slot` call inside each worker so both threads enter near-simultaneously; the internal `claim_slot` INSERT is the race point. (A tighter barrier inside `claim_slot` is not needed — SQLite's page lock serializes the two INSERTs and the `UNIQUE` index arbitrates; the barrier just guarantees genuine overlap of the two `fire_slot` invocations.)
- **Meta-guard (D-04):** Monkeypatch a SELECT-then-INSERT shim over `weatherbot.weather.store.claim_slot` (read `was_sent` then unconditionally INSERT), run the SAME barrier-threaded body, and assert it produces **2** deliveries (test fails ⇒ proves the real test exercises atomicity, not decoration). Keep this as a co-located `test_..._metaguard` in the same file.

#### F114 — heartbeat tick/success separation unpinned `[VERIFIED: codebase grep]`
- **Current test:** `tests/test_reliability.py:606` `test_heartbeat_upsert`:
  ```python
  daemon_mod._heartbeat_tick(tmp_db)
  row = _heartbeat(tmp_db)
  assert row["last_tick_utc"] is not None   # only checks tick
  ```
  It **never** asserts `last_success_utc` stays `None` after a bare tick — so a bug that stamped success on every tick would pass.
- **Production symbols:** `stamp_tick` (`store.py:456-470`) writes ONLY `last_tick_utc`; `stamp_success` (`store.py:473-485`) writes ONLY `last_success_utc`. Schema seeds both `NULL` (`store.py:140-146`). `_heartbeat_tick` (`daemon.py:705-718`) calls `stamp_tick(db_path)` only.
- **Required assertion:** After `init_db(tmp_db)` + `_heartbeat_tick(tmp_db)`:
  ```python
  row = read_heartbeat(tmp_db)  # store.py:508
  assert row["last_tick_utc"] is not None
  assert row["last_success_utc"] is None   # NEW — the tick/success separation
  ```
  Then separately call `stamp_success(tmp_db)` and assert `last_success_utc is not None`, `last_tick_utc` unchanged. `read_heartbeat` (`store.py:508`) returns `{"last_tick_utc", "last_success_utc"}`.
- **Fails-pre-fix (D-06):** weaken `_heartbeat_tick` to also call `stamp_success` (local shim), show the new `assert last_success_utc is None` goes red, restore, green.

#### F112 — loose within-burst wait bound `[VERIFIED: codebase grep]`
- **Current test:** `tests/test_reliability.py:95-102` `test_two_burst_wait_shape`, assertion `assert 0.0 <= wait < 150.0` (line 100).
- **Production symbol:** `_within_burst_wait` (`yahir_reusable_bot/reliability/retry.py:133-143`):
  ```python
  step = burst_spread_s / (burst_size - 1)
  jitter = random.uniform(0, step * 0.5)
  return step + jitter
  ```
- **Exact real ceiling (compute, do not guess):** with the hub/app defaults `BURST_SIZE = 8` (`retry.py:57`), `BURST_SPREAD_S = 600` (`retry.py:58`) — which are ALSO the app `Reliability` defaults `attempts_per_burst=8, burst_spread_seconds=600` (`config/models.py:280-281`):
  - `step = 600 / (8 - 1) = 85.714…s`
  - `max jitter = step * 0.5 = 42.857…s`
  - **within-burst ceiling = step * 1.5 = 128.571…s** (the strict `< 128.572` upper bound; a safe literal bound is `< 128.58` or, matching `Reliability.worst_case_seconds`, `step * 1.5`).
  - This is exactly the "128.6" the config docstring cites (`models.py:274`, `models.py:317` `within_max = (burst_spread_seconds/(n-1)) * 1.5`).
- **Required assertion:** replace `< 150.0` with a bound derived from the constants (not a magic number), e.g.:
  ```python
  step = BURST_SPREAD_S / (BURST_SIZE - 1)
  ceiling = step * 1.5              # 128.571…
  assert step <= wait <= ceiling    # tightened from < 150.0
  ```
  Note the existing lower-bound precedent at `test_reliability.py:285` (`step = BURST_SPREAD_S / (BURST_SIZE - 1)`) and `:294` (`assert step <= no_ra_wait < step * 1.5`) — this exact bound is already used elsewhere in the file, so the correction aligns with established convention.
- **Fails-pre-fix (D-06):** temporarily widen the jitter multiplier in the hub shim / or assert a value like `149.0` would have passed the old bound but fails the new — document red→green.

#### F115 — cache id==name shortcut unproven `[VERIFIED: codebase grep]`
- **Current test:** `tests/test_cache.py` uses `_loc("home")` (helper at `:53-59`) where `id` defaults to `name="home"`, so a name-keyed cache would pass identically. The `_loc` helper ALREADY supports `_loc(name, id=...)` (lines 57-58) — it is simply never exercised with `id != name` for the collapse claim.
- **Production symbol:** `ForecastCache.lookup` (`cache.py:129-184`) keys on:
  ```python
  # cache.py:151-152
  loc_id = resolve_location(config, name).id
  key = loc_id if suffix is None else (loc_id, suffix)
  ```
- **Required test (F115):** build a location with a **distinct** id, e.g. `_loc("Cabin", id="loc-42")`; look up by the **name** `"Cabin"` (or a case variant `"cabin"`), and prove the cache collapses on the **id**: two lookups of `"Cabin"` → one fetch; and (the discriminating assertion) a location whose *name* differs but whose *id* matches must hit the same entry, while a location whose id differs must NOT. A name-keyed shortcut would fail this because it would key on `"Cabin"` vs `"cabin"` differently. Assert the resolved cache key is the id, not the name.

#### F116 — reconcile register-before-remove ordering unpinned `[VERIFIED: codebase grep]`
- **Current test:** `tests/test_reload_engine.py:155` `test_reload_committed_success_diff_removes_excluded_and_summary` asserts `calls["register"] == [new_cfg]` (line 174) AND `fake.removed == ["gone"]` (line 175) — but **not that register happened before remove**. A remove-then-register engine (which would momentarily leave a job gap) passes.
- **Production symbol:** `ReloadEngine.reconcile` in the hub (`yahir_reusable_bot/config/reload.py:184-190`):
  ```python
  self._register_jobs(self._holder.current())   # line 184 — ADD first
  removed = 0
  for job_id in (live_ids - desired_ids):
      self._scheduler_engine.remove(job_id)     # line 189 — REMOVE after
      removed += 1
  ```
  (The app-side twin is `_reconcile_jobs` in `daemon.py:906`, which likewise ADDs via `_register_jobs` at :958 before the REMOVE loop at :972.)
- **Required assertion (F116):** thread a shared **order log** through the injected stubs — `register_jobs` appends `"register"`, the fake scheduler engine's `remove` appends `f"remove:{job_id}"` — then assert `order.index("register") < order.index("remove:gone")` (register strictly before every remove). The `_FakeSchedulerEngine.remove` (`test_reload_engine.py:51-52`) already records into `self.removed`; extend it (or the injected `register_jobs`) to write into a shared ordered list. This is the "no-gap-in-jobs" invariant.
- **Scope note:** the engine is a hub symbol but the TEST lives in WeatherBot and drives the engine through injected app-side stubs — pinning the ordering is in-scope (tests-only). No hub change.

### HARD-TEST-02 — Add missing high-risk coverage

#### F108 — rename-safe `Location.id != name` through fire_slot/plan_catchup/alert-dedup `[VERIFIED: codebase grep]`
- **Root condition:** `Location.id` defaults to `name` (`config/models.py:199-207`), so EVERY existing test has `id == name`. No test proves the code reads `.id` (a regression to `.name` is invisible).
- **Production symbols confirmed to use `.id` (must be pinned):**
  - `fire_slot` claim/release/alert: `claim_slot(db_path, location.id, ...)` (`daemon.py:210`), `release_claim(db_path, location.id, ...)` (`daemon.py:276,299,325`), `record_alert(db_path, location.id, ...)` (`daemon.py:283,301,327`). Logging uses `location.name` (`daemon.py:213`) — correct.
  - `plan_catchup`: `was_sent(loc.id, slot.time, local_date)` (`catchup.py:198`).
  - UV dedup: `claim_uv_alert(db_path, location_id, ...)` keyed on `location.id` (`store.py:371`).
- **Required test (F108):** build `Location(name="Beach House", id="loc-7")` (name ≠ id). Drive `fire_slot` and assert the `sent_log`/`alerts` rows carry `location_name == "loc-7"` (the id), NOT `"Beach House"`. Drive `plan_catchup` with a `was_sent` spy and assert it was queried with `"loc-7"`. This is red against any `.name`-using regression.

#### F110 — Retry-After 429 landing on the mid-pause attempt (attempt == BURST_SIZE) `[VERIFIED: codebase grep]`
- **Current coverage gap:** the existing honoring test (`test_reliability.py:259-267`) fires 429 on attempt **1** (base ≈ step, small). The untested case is 429 on `attempt == BURST_SIZE`, where the base is `MID_PAUSE_S` (2700s) and the cap collapses it.
- **Production symbol:** `two_burst_wait` (`retry.py:146-181`). The collapse line:
  ```python
  # retry.py:180
  return min(max(base, ra), RETRY_AFTER_CAP_S)
  ```
  At `attempt_number == burst_size`, `_within_burst_wait` returns `mid_pause_s` (`retry.py:137-139`), so `base = 2700`, `ra ≤ 120` (`RETRY_AFTER_CAP_S = 120`, `retry.py:67`), and `min(max(2700, 120), 120) = 120`. The 45-min mid-pause **collapses** to the 120s cap on a 429 mid-pause attempt.
- **How a test injects it:** use the file's `_State`/`_Outcome` stand-ins (`test_reliability.py:82-87`) — build `_State(BURST_SIZE, _Outcome(_status_error(429, headers={"Retry-After": "9999"})))` and assert `two_burst_wait(state) == RETRY_AFTER_CAP_S` (120.0), NOT `MID_PAUSE_S` (2700). Contrast with the no-header mid-pause case which must return `MID_PAUSE_S`. This pins the "a capped Retry-After never *extends* but *can shorten* the mid-pause" contract.

#### F107 — dt-based imperial/metric daily pairing `[VERIFIED: codebase grep]`
- **Partial coverage exists:** `tests/test_models.py:141` `test_dt_paired_briefing` + `onecall_imperial_dtskew.json`/`onecall_metric_dtskew.json` fixtures. Verify it asserts the metric side is paired by the imperial day's `dt` (`models.py:310-321`) and degrades to `{}` on no dt-match (never a mispair). If the existing test only checks the happy path, strengthen it to assert the mispairing the independent-selection bug produced does NOT occur (the guard comment is at `test_models.py:162`).
- **Production symbol:** `Forecast.from_payloads` (`models.py:250`), dt-pairing block:
  ```python
  # models.py:310-321
  dt_ts = day_i.get("dt")
  if dt_ts is not None:
      day_m = next((d for d in (onecall_met.get("daily") or [])
                    if (d or {}).get("dt") == dt_ts), {})
  else:
      day_m = select_today_daily(onecall_met.get("daily"), loc_tz, local_date) or {}
  ```
- **Required assertion:** a metric array whose ordering/length is skewed relative to imperial (the rotated `dtskew` fixture) must pair `high_met`/`low_met` to the imperial day's `dt`, or degrade to `None` — never mispair a °F high with the wrong day's °C.

#### F109 — from_payloads daily[0] is location-local TODAY `[VERIFIED: codebase grep]`
- **Negative case covered:** `tests/test_models.py:664` `test_daily0_not_today_degrades` (labeled `# D-05 / F35 / F109`) proves a yesterday-dated `daily[0]` degrades to `None` rather than shipping yesterday as today.
- **Positive/discriminating gap:** add a test where today's entry is NOT at index 0 (e.g. `daily[0]` = yesterday, `daily[1]` = today) and assert `from_payloads` selects the **today** entry (correct high/low), proving the selector is date-anchored, not positional.
- **Production symbol:** `select_today_daily` (`weatherbot/weather/dates.py:77`), called at `models.py:300`. The comment "NEVER positional daily[0]" (`models.py:298-299`) is the contract to pin.
- **Required assertion:** with a payload whose today entry is at `daily[2]`, `fc.high_imp`/`fc.low_imp` == the index-2 values (not index-0), and `fc.local_date` == the configured-tz today.

#### F111 — weekend-block whole-block roll-forward `[VERIFIED: codebase grep]`
- **Gap:** `tests/test_multiday.py:168` `test_weekday_run_on_saturday_rolls_forward` covers the **weekday** block roll-forward. No test covers the **weekend** block (`kind='weekend'`, `_WEEKEND_DAYS = ("fri","sat","sun")`, `multiday.py:33`) rolling forward when the whole Fri-Sat-Sun block is past.
- **Production symbol:** `select_days` (`multiday.py:61-132`), whole-block roll-forward branch:
  ```python
  # multiday.py:104-107
  if base_tokens and not upcoming:
      base_deltas = [delta + 7 for delta in base_deltas]  # roll whole block +1 week
      upcoming = base_deltas
  ```
- **Required assertion:** call `select_days("weekend", today_local=<a Monday>, daily, add=set(), drop=set(), tz=_TZ)` where Fri/Sat/Sun are all in the past relative to Monday → indices resolve to **next** week's Fri-Sat-Sun (matched against a `daily[]` that spans far enough), OR notices for entries beyond the 7-day horizon (`multiday.py:127-128`). Assert no `IndexError` and correct roll-forward.

#### F113 — null `dt` in the date-index map `[VERIFIED: codebase grep]`
- **Gap:** no multiday test injects a `daily[]` entry with `dt=None`. `test_null_fields_coalesce` (`test_multiday.py:107`) is a `from_payloads` test, not the `select_days`/`_date_index_map` path.
- **Production symbol:** `_date_index_map` (`multiday.py:49-58`):
  ```python
  # multiday.py:52-56
  for i, day in enumerate(daily or []):
      dt = (day or {}).get("dt")
      if dt is None:
          continue                # skip null-dt entries (no crash, no mis-index)
      local = datetime.fromtimestamp(dt, tz).date()
      out.setdefault(local, i)
  ```
- **Required assertion:** pass a `daily` list containing an entry with `"dt": None` (and/or a fully-null entry) alongside valid entries; assert `select_days` skips the null-dt entry (it never appears in `by_date`), returns valid indices for the good entries, and produces a notice (not an `IndexError`/`TypeError`) for any desired date whose only candidate had a null dt.

#### F14 — catch-up across local midnight (Phase 32) `[VERIFIED: codebase grep]`
- **Production symbol:** `plan_catchup` (`catchup.py:106-202`), the F14 candidate-date loop:
  ```python
  # catchup.py:157-158
  emitted_dates: set[str] = set()
  for cand_date in (now_local.date(), now_local.date() - timedelta(days=1)):
  ```
  and the per-slot dedup `emitted_dates.add(local_date)` (`catchup.py:196,201`). `local_date = cand_date.isoformat()` (`catchup.py:195`) uses the CANDIDATE day, not `now_local.date()`.
- **Scenario to pin:** a slot due 23:45 local, recovered at 00:15 the NEXT local day. Its real scheduled instant is on YESTERDAY's date; composing only today's date builds a ~23.5h-future instant that `scheduled > now_utc` wrongly skips (`catchup.py:183`). The fix evaluates yesterday as a candidate.
- **Required assertion:** inject `now_utc` such that `now_local` is 00:15 and a 23:45 slot exists; with an injected `was_sent` returning False, assert `plan_catchup` returns one `MissedSlot` whose `local_date` is **yesterday**'s date and whose `scheduled_dt` is yesterday 23:45 local. Purity backbone: `now_utc` + `was_sent` are injected (`catchup.py:106-110`), so NO wall-clock or `time-machine` is needed. Also assert the `emitted_dates` dedup: a slot that qualifies under both candidates emits exactly once.

#### F37/F63/F01 — store atomicity / data-loss path (Phase 31) `[VERIFIED: codebase grep]`
- **Production symbols:**
  - `persist` (`store.py:211-248`): two INSERTs (imperial + metric) + single `conn.commit()` in one `with _connect(...)` transaction — **both land or neither** (`store.py:229-248`, comment at 228-230).
  - `init_db` (`store.py:194-208`): sole schema owner, `PRAGMA journal_mode=WAL` set once, `executescript(_SCHEMA)`. F63 was `executescript` force-commit — the fix makes `init_db` the SOLE DDL owner (no per-write DDL re-run; see `store.py:227-230`).
  - F01: `fire_slot` post-`result.ok` bookkeeping is best-effort and never releases a delivered claim (`daemon.py:350-393`) — already covered by the reliability best-effort tests (`test_reliability.py:428+`), but confirm ≥1 test pins "a raise in resolve_alert/stamp_success after ok keeps the claim."
- **Existing coverage:** `tests/test_store.py:79` `test_persist_onecall_writes_both_unit_rows` asserts both rows exist on success. **Gap:** no test proves the two INSERTs are **transactional** (both-or-neither on a mid-transaction failure).
- **Required assertion (F37/F63):** monkeypatch the second `conn.execute` (metric INSERT) to raise, call `persist`, and assert **zero** `weather_onecall` rows were committed (the imperial INSERT rolled back with the metric failure — both-or-neither). Also assert `init_db` is idempotent and WAL is persistent (a fresh connect reports `journal_mode=wal`) — `test_store.py:73` `test_init_db_is_idempotent` may already cover idempotency; extend for the transactional rollback.

## Coverage Ledger (SC-3 — D-08)

Every Phase 29–33 correctness fix mapped to its pinning test. `[EXISTS]` = already covered; `[ADD/FIX]` = this phase.

| Phase | Fix | Finding | Pinning test disposition |
|-------|-----|---------|--------------------------|
| 31 | Exactly-once claim-before-fire | F106 | `[FIX]` real concurrency (D-03/D-04) |
| 31 | Post-send bookkeeping keeps claim | F01 | `[EXISTS]` `test_reliability.py` best-effort tests; verify ≥1 |
| 31 | `persist` two-INSERT transaction | F37/F63 | `[ADD]` transactional both-or-neither in `test_store.py` |
| 31 | Heartbeat tick/success columns | F114 | `[FIX]` assert `last_success_utc is None` on tick |
| 31 | WAL + busy_timeout | HARD-STORE-02 | `[EXISTS]` `test_store.py` init/idempotency; extend |
| 32 | Midnight catch-up candidate dates | F14 | `[ADD]` `plan_catchup` yesterday-candidate in `test_scheduler.py` (or a catchup test file) |
| 32 | daily[0] today-anchored | F35/F109 | `[EXISTS]` negative case; `[ADD]` positive (today not at index 0) |
| 33 | dt-paired metric daily | F107/F11 | `[EXISTS]` `test_dt_paired_briefing`; strengthen mispair guard |
| — | Rename-safe id identity | F108 | `[ADD]` `id != name` through fire_slot/plan_catchup/alerts |
| — | Cache id-collapse | F115 | `[FIX]` distinct `id != name` |
| — | Retry-After honoring | F110 | `[ADD]` 429 on `attempt==BURST_SIZE` collapse |
| — | Two-burst wait bound | F112 | `[FIX]` `< 128.57` (derived) |
| — | Reconcile no-gap ordering | F116 | `[FIX]` register-before-remove order log |
| — | Weekend roll-forward | F111 | `[ADD]` weekend whole-block roll-forward |
| — | Null-dt date index | F113 | `[ADD]` `dt=None` skip in `_date_index_map` |

**No latent escapes found yet (D-07):** every production symbol matched the CONTEXT.md D-08 mapping. Two ⚠ notes below.

### ⚠ Latent-escape watchpoints (D-07 — the planner must know)
1. **F109 positive case may reveal a real gap.** The negative case (yesterday degrades) is covered, but there is NO test asserting the selector picks today's entry when today is NOT at `daily[0]`. If `select_today_daily` (`dates.py:77`) has an off-by-one or falls back to positional under some input, the F109 positive test could go **red against current code** — treat as a real escape (D-07), not a test bug.
2. **F110 uses hub symbols.** `two_burst_wait` and constants live in `yahir_reusable_bot/reliability/retry.py` (re-exported via `weatherbot/reliability/retry.py` shim). If the F110/F112 tests reveal a *hub* behavior bug (not an app-wiring bug), the fix is **human-gated** (hub tag cut + repin per ECOSYSTEM.md) — surface it, do NOT ship it. But note: the tests themselves live app-side and import via the shim, so pinning the *contract* is fully in-scope.

## Fixtures & Tooling `[VERIFIED: codebase grep]`

| Fixture / tool | Location | Use |
|----------------|----------|-----|
| `tmp_db` | `tests/conftest.py:52-69` | **File-backed** sqlite (`tmp_path / "weatherbot.db"`, `init_db` bootstrapped). Required for F106 (both threads share one file). |
| `load_fixture` | `tests/conftest.py:26-29` | Loads recorded OpenWeather One Call JSON by name. |
| `_seed_sent_row` | `tests/conftest.py:86+` | Seeds a real `sent_log` row via production `claim_slot` (for catch-up/exactly-once). |
| Real-thread pattern | `tests/test_config_holder.py:89-133` | Canonical error-list / `threading.Event` / no-sleep concurrency harness to reuse for F106 (D-03). |
| `_State` / `_Outcome` | `tests/test_reliability.py:82-87` | `RetryCallState` stand-ins for driving `two_burst_wait` directly (F110/F112). |
| `_FakeSchedulerEngine` | `tests/test_reload_engine.py:42-52` | Records `list_live_ids`/`remove`; extend for F116 order log. |
| dtskew fixtures | `tests/fixtures/onecall_imperial_dtskew.json`, `onecall_metric_dtskew.json` | F107 dt-pairing (metric array rotated so its `daily[0]` is a different day). |
| Multi-day fixtures | `onecall_8day_imperial.json`, `onecall_8day_metric.json` | F111/F113 `select_days` (7-day horizon). |

**Run commands:**
- Quick (per task): `uv run pytest tests/test_scheduler.py tests/test_reliability.py -x -q` (target the edited module).
- Full suite (per wave / phase gate): `uv run pytest -q`.
- **Known syrupy quirk (confirmed this session):** the full run prints `2 snapshots failed. 27 snapshots passed.` in the snapshot-report summary but **exits 0** (`869 passed`). This is pre-existing report noise, NOT a golden diff. **Trust the exit code + `.ambr` diff**, never the printed "N snapshots failed" line. (Baseline verified 2026-07-13: `869 passed, 1 warning in 32.47s`, exit 0.)

## Fails-Pre-Fix Proof Strategy (SC-3, D-05/D-06) `[VERIFIED: codebase grep]`

For the three highest-risk corrections, the Gate-1 self-UAT log must record a red→green mutation spot-check (no mutation-testing dep, D-06):

| Finding | Temporary weakening (revert/shim) | Expected red | Restore → green |
|---------|-----------------------------------|--------------|------------------|
| **F106** | Monkeypatch `store.claim_slot` to SELECT-then-INSERT (co-located meta-guard shim, D-04) | Concurrent test sees **2** deliveries | Real `INSERT OR IGNORE` → exactly 1 |
| **F114** | Local shim: `_heartbeat_tick` also calls `stamp_success` | `assert last_success_utc is None` fails | Tick-only → success stays `None` |
| **F112** | Widen the assertion target: show a `149.0` value passes the old `< 150.0` but the new `< 128.58` bound would have caught it (or transiently bump the hub jitter factor via an editable-overlay shim, revert with `uv sync --frozen`) | Old bound green on an out-of-range wait | Tightened bound red on 149, green on real |

For F112, prefer the **assertion-level** demonstration (show a synthetic 149s wait passes old, fails new) over editing hub source — editing the hub is a human-gated cross-repo action (ECOSYSTEM.md). The editable overlay (`uv pip install -e ../Reusable/YahirReusableBot`) is available for a live cross-repo demo but must be reverted (`uv sync --frozen`) and NEVER committed.

## Validation Architecture

> nyquist_validation is enabled (`config.json workflow.nyquist_validation: true`). This section drives VALIDATION.md.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (`pyproject.toml [dependency-groups] dev`) + syrupy 5.3.4, time-machine 2.16 |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| Quick run command | `uv run pytest tests/test_<module>.py -x -q` |
| Full suite command | `uv run pytest -q` |

### Observable signals each new/corrected test asserts on (the Nyquist sampling points)

| Req | Finding | Test type | Observable signal asserted | Automated command |
|-----|---------|-----------|----------------------------|-------------------|
| HARD-TEST-01 | F106 | concurrency (real threads) | `len(channel.sent_text) == 1` AND one `sent_log` row AND `errors == []`; meta-guard: weakened claim → 2 deliveries | `uv run pytest tests/test_scheduler.py -k concurrent -x` |
| HARD-TEST-01 | F114 | unit (store row) | `read_heartbeat` → `last_tick_utc not None`, `last_success_utc is None` after tick | `uv run pytest tests/test_reliability.py -k heartbeat -x` |
| HARD-TEST-01 | F112 | unit (wait value) | `step <= wait <= step*1.5` (= `85.71 <= wait <= 128.57`) for all within-burst attempts | `uv run pytest tests/test_reliability.py -k two_burst_wait -x` |
| HARD-TEST-01 | F115 | unit (cache key) | distinct `id != name`: cache collapses on `.id`; two `"Cabin"` lookups → 1 fetch; id-mismatch → no hit | `uv run pytest tests/test_cache.py -x` |
| HARD-TEST-01 | F116 | unit (order log) | `order.index("register") < order.index("remove:gone")` | `uv run pytest tests/test_reload_engine.py -k committed -x` |
| HARD-TEST-02 | F108 | integration (fire_slot) | `sent_log.location_name == "loc-7"` (the id, not name); `plan_catchup` queries `was_sent("loc-7", ...)` | `uv run pytest tests/test_scheduler.py -k rename -x` |
| HARD-TEST-02 | F110 | unit (wait value) | `two_burst_wait(_State(BURST_SIZE, 429-with-Retry-After)) == RETRY_AFTER_CAP_S` (120, not 2700) | `uv run pytest tests/test_reliability.py -k retry_after -x` |
| HARD-TEST-02 | F107 | unit (model) | dt-skewed metric pairs by imperial `dt` or degrades to None (no mispair) | `uv run pytest tests/test_models.py -k dt_pair -x` |
| HARD-TEST-02 | F109 | unit (model) | today-not-at-index-0 → selector picks today's high/low | `uv run pytest tests/test_models.py -k daily0 -x` |
| HARD-TEST-02 | F111 | unit (multiday) | weekend whole-block-past → next-week Fri/Sat/Sun indices or horizon notices, no IndexError | `uv run pytest tests/test_multiday.py -k weekend -x` |
| HARD-TEST-02 | F113 | unit (multiday) | `dt=None` entry skipped in `_date_index_map`; no TypeError | `uv run pytest tests/test_multiday.py -k null_dt -x` |
| HARD-TEST-02 | F14 | unit (catchup) | `plan_catchup` at 00:15 returns yesterday-dated MissedSlot for a 23:45 slot; `emitted_dates` dedup → exactly one | `uv run pytest tests/test_scheduler.py -k catchup_midnight -x` |
| HARD-TEST-02 | F37/F63 | unit (store) | metric-INSERT raise → 0 committed `weather_onecall` rows (both-or-neither) | `uv run pytest tests/test_store.py -k atomic -x` |

### Minimum test set to prove the requirements
- **HARD-TEST-01 proven** when F106 (real-thread + meta-guard), F114, F112, F115, F116 all pass AND each has a documented pre-fix red (D-06 for F106/F114/F112).
- **HARD-TEST-02 proven** when F110, F108, F107 (strengthened), F109 (positive), F111, F113, F14, F37/F63 all pass and are assertion-by-construction (D-05).

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_<edited_module>.py -x -q`
- **Per wave merge:** `uv run pytest -q` (full suite, trust exit code over snapshot report line)
- **Phase gate:** full suite green (exit 0) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] None — all six target test files exist, `conftest.py` fixtures (`tmp_db` file-backed, `load_fixture`) exist, the real-thread harness exists, all fixtures (dtskew, 8-day) exist. No new framework install, no new fixture module required. (A shared `threading.Barrier` helper in `conftest.py` is optional per Claude's Discretion.)

## Common Pitfalls

### Pitfall 1: Faking concurrency (the exact bug being fixed)
**What goes wrong:** writing "concurrent" tests as sequential calls (the F106 defect itself). **Avoid:** genuine `threading.Barrier(2)` + two threads on a **file-backed** `tmp_db`; assert on an *outcome* (POST count / row count), not timing. Include the D-04 meta-guard so the test provably breaks if atomicity degrades.

### Pitfall 2: id==name masking (F108/F115)
**What goes wrong:** using `Location(name="X")` (id defaults to name) so a `.name`-vs-`.id` regression is invisible. **Avoid:** always use a **distinct** `id != name` in identity-path tests (`Location(name="Beach House", id="loc-7")`; `_loc("Cabin", id="loc-42")`).

### Pitfall 3: Guessing the F112 bound
**What goes wrong:** hard-coding a magic ceiling. **Avoid:** derive it from the constants — `step = BURST_SPREAD_S/(BURST_SIZE-1)`, ceiling `= step*1.5 = 128.571…`. The file already uses this exact form at `test_reliability.py:285,294`.

### Pitfall 4: Trusting the syrupy "N snapshots failed" line
**What goes wrong:** treating the printed snapshot-report failure count as a real failure. **Avoid:** trust the **exit code** (0 = pass) and the `.ambr` diff. Baseline this session: `2 snapshots failed` printed, `869 passed`, exit 0.

### Pitfall 5: Editing hub source to demonstrate F110/F112 red
**What goes wrong:** mutating `yahir_reusable_bot` to force a red is a human-gated cross-repo action. **Avoid:** demonstrate red at the **assertion level** (synthetic wait value / local monkeypatch), or use the editable overlay only transiently (`uv pip install -e ../Reusable/...`, revert with `uv sync --frozen`, never commit).

### Pitfall 6: time-machine where injection suffices (F14)
**What goes wrong:** reaching for `time-machine`/wall-clock for the midnight catch-up test. **Avoid:** `plan_catchup(config, was_sent, now_utc=...)` injects both the clock and the reader (`catchup.py:106-110`) — pass a fixed `now_utc`; no clock patching needed.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Concurrency harness | A new thread-pool helper | `test_config_holder.py:89` pattern (D-03) | Established in-house convention; error-list + no-sleep already proven |
| Seeding a sent slot | Manual SQL INSERT | `conftest.py:_seed_sent_row` (via `claim_slot`) | Byte-identical to a real fire's row |
| RetryCallState mock | Full tenacity state | `test_reliability.py:_State`/`_Outcome` | Minimal stand-in already used for `two_burst_wait` |
| Clock control for catch-up | `time-machine` | `plan_catchup(now_utc=...)` injection | Pure function — no patching |

## State of the Art

Not applicable — this is a tests-only correctness phase against already-shipped fixes. No library/version changes. No new dependencies (D-06 explicitly rejects mutation-testing tooling).

## Package Legitimacy Audit

**Not applicable** — this phase installs **no** packages. All test tooling (pytest 9.0.3, syrupy 5.3.4, time-machine 2.16) is already in `pyproject.toml [dependency-groups] dev` and in the frozen `uv.lock`. Per D-06, no mutation-testing dependency (mutmut/cosmic-ray) is added.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | test runner | ✓ | (project pinned) | — |
| pytest | test suite | ✓ | 9.0.3 | — |
| syrupy | snapshot tests | ✓ | 5.3.4 | — |
| time-machine | (not needed — injection suffices) | ✓ | 2.16 | inject `now_utc` |
| yahir_reusable_bot | retry/reload symbols under test | ✓ | tag v0.1.1 (`.venv/.../yahir_reusable_bot`) | — |

**Baseline verified this session:** `uv run pytest -q` → `869 passed, 1 warning in 32.47s`, exit 0 (with the known syrupy report noise). No blocking dependencies.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The F112 within-burst ceiling `128.571…s` uses the DEFAULT reliability config (n=8, spread=600). A config with different `attempts_per_burst`/`burst_spread_seconds` changes the ceiling. | F112 | LOW — the test builds its bound from `BURST_SIZE`/`BURST_SPREAD_S` constants (or a known config), so it stays correct if derived, not hard-coded. Flagged so the planner derives, never literals `128.57`. |
| A2 | F109's positive case (today not at index 0) is currently uncovered and MAY go red against real code (latent escape, D-07). | ⚠ Watchpoint 1 | MEDIUM — if red, fold a minimal `select_today_daily` fix per D-07, or escalate if large. |
| A3 | F01 already has ≥1 pinning test in `test_reliability.py` (best-effort bookkeeping). Planner must verify; if absent, add one. | Coverage Ledger | LOW — best-effort tests exist around `daemon.py:350-393`; confirm the specific "raise-after-ok keeps claim" assertion. |

## Open Questions

1. **Should the F14 midnight-catch-up test live in `test_scheduler.py` or a dedicated catchup test file?**
   - What we know: D-01 says extend existing per-module files; `plan_catchup` is in `weatherbot/scheduler/catchup.py`.
   - What's unclear: whether the repo already has a `test_catchup.py` (it does not — catchup tests live in `test_scheduler.py`).
   - Recommendation: add to `test_scheduler.py` (matches existing catchup-test placement) unless the planner prefers a `test_catchup.py` — either is D-01-consistent (one file per module; catchup tests currently co-reside with scheduler).

2. **F107 strengthening vs. leaving as-is.**
   - What we know: `test_dt_paired_briefing` exists with a mispair guard comment (`test_models.py:162`).
   - What's unclear: whether the existing assertion already fully pins the mispair (it may). 
   - Recommendation: read the existing assertion; if it already asserts the wrong-day °C never appears, mark F107 `[EXISTS]` and skip; else strengthen.

## Sources

### Primary (HIGH confidence) — codebase (VERIFIED via grep/read this session)
- `weatherbot/weather/store.py:38-542` — schema (`sent_log UNIQUE` :116, `heartbeat` :140), `claim_slot` :274, `persist` :211, `stamp_tick`/`stamp_success` :456/473, `read_heartbeat` :508, `init_db` WAL :194.
- `weatherbot/scheduler/daemon.py:140-399,705-976` — `fire_slot` (`.id` claim/alert), `_heartbeat_tick` :705, `_reconcile_jobs` register-before-remove :958/972.
- `weatherbot/scheduler/catchup.py:106-202` — `plan_catchup`, F14 `emitted_dates` candidate loop :157.
- `weatherbot/weather/models.py:250-406` — `from_payloads`, dt-pairing :310, today-selector :300.
- `weatherbot/weather/multiday.py:49-132` — `_date_index_map` null-dt skip :52, `select_days` weekend roll-forward :104.
- `weatherbot/interactive/cache.py:129-184` — `.id`-keyed cache :151.
- `weatherbot/config/models.py:167-335` — `Location.id` defaults to name :199, `Reliability` defaults + `worst_case_seconds` :280/304.
- `.venv/.../yahir_reusable_bot/reliability/retry.py:57-181` — `BURST_SIZE=8`/`BURST_SPREAD_S=600`, `_within_burst_wait` :133, `two_burst_wait` collapse :180, `RETRY_AFTER_CAP_S=120` :67.
- `.venv/.../yahir_reusable_bot/config/reload.py:184-190` — `ReloadEngine.reconcile` register-before-remove.
- Test files: `test_scheduler.py:817` (F106), `test_reliability.py:95,606,259` (F112/F114/F110), `test_cache.py:53,73` (F115), `test_reload_engine.py:155` (F116), `test_models.py:141,664` (F107/F109), `test_multiday.py:157,168` (F111), `test_config_holder.py:89` (harness), `conftest.py:26,52,86` (fixtures).
- Baseline run: `uv run pytest -q` → 869 passed, exit 0.

### Secondary / Tertiary
- None — no web research needed for a tests-only phase against local source.

## Metadata

**Confidence breakdown:**
- False-green corrections (F106/F114/F112/F115/F116): HIGH — each weak assertion quoted at file:line; real behavior confirmed in source.
- Missing coverage (F108/F110/F107/F109/F111/F113/F14/F37): HIGH — each production symbol + fix line located; observable named.
- F109 positive-case latency (D-07 watchpoint): MEDIUM — may reveal a real escape; flagged.

**Research date:** 2026-07-13
**Valid until:** 2026-08-12 (30 days — stable local codebase; only invalidated by edits to the named source files or a hub repin).
