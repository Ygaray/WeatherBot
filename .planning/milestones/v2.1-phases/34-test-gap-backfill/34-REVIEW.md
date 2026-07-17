---
phase: 34-test-gap-backfill
reviewed: 2026-07-13T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - tests/test_cache.py
  - tests/test_models.py
  - tests/test_multiday.py
  - tests/test_reliability.py
  - tests/test_reload_engine.py
  - tests/test_scheduler.py
  - tests/test_store.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 34: Code Review Report

**Reviewed:** 2026-07-13
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Phase 34 "Test-Gap Backfill" adds/hardens tests that exist to kill false-green coverage. I reviewed only the new/changed test code (diff base `71198d5`) and cross-checked the load-bearing claims against production code (`weatherbot/reliability/retry.py`, `weatherbot/weather/store.py`, `weatherbot/interactive/cache.py`, `weatherbot/weather/multiday.py`).

The weighted anti-patterns this phase targets hold up under scrutiny:

- **F112 derived bounds** (`test_two_burst_wait_shape`): verified against the real constants — `step = BURST_SPREAD_S/(BURST_SIZE-1)` = 85.71, ceiling 128.57. The test derives both from imported constants and no longer uses the loose `< 150.0` literal or a magic `128.57`. Genuine.
- **F106 real concurrency** (`test_concurrent_double_fire_delivers_once` + `_metaguard`): two barrier-synced `threading.Thread`s race `fire_slot` against the shared **file-backed** `tmp_db` (WAL + `busy_timeout`, each thread opening its own `_connect`). The production `claim_slot` is a single `INSERT OR IGNORE` against a `UNIQUE` key (atomic). The meta-guard swaps in a weakened SELECT-then-INSERT shim over BOTH `store.claim_slot` and `daemon.claim_slot` and deterministically observes 2 POSTs — so the test flips red when atomicity is removed. Not decoration.
- **F108/F115 id≠name** (`test_fire_and_catchup_use_location_id_not_name`, `test_cache_key_collapses_on_id_not_name`): both use a DISTINCT `id != name` (`"loc-7"`/`"Beach House"`, `"loc-42"`/`"Cabin"`) and assert on the persisted/queried identity key, so the rename-safe claim is genuinely proven (red against any `.name`-reading regression).
- **F109 date-anchored daily select** (`test_daily0_today_not_at_index_zero_selects_today`): places TODAY at index 2 behind two earlier-dated decoys with distinctive wrong values (111/99, 222/200) and asserts the 76/58 today values — a positional `daily[0]` grab is caught by construction. Genuine positive twin.
- **F37/F63 atomic persist** (`test_persist_onecall_atomic_rollback`): injects a mid-transaction failure on the second INSERT and reads back zero rows from a fresh connection — proves both-or-neither, not a happy path.

No BLOCKER-tier defects (no test that proves nothing / re-creates a false-green). The findings below are robustness/fragility (WARNING) and style (INFO) issues in the new test code.

## Warnings

### WR-01: F106 meta-guard barrier timeout can collide with the store's 5s busy_timeout

**File:** `tests/test_scheduler.py:922-931` (`_weak_claim_slot` in `test_concurrent_double_fire_metaguard`)
**Issue:** The weakened shim synchronizes the two racers with `read_barrier.wait(timeout=5)`. The production store connection sets `PRAGMA busy_timeout=5000` (5s), confirmed in `weatherbot/weather/store.py:190`. Both timeouts are 5s. If the loser thread's `_connect`/`INSERT OR IGNORE` ever contends for the write lock long enough (heavily loaded CI), the barrier's 5s and the DB's 5s are in the same order of magnitude — a `BrokenBarrierError` is silently `pass`-ed, which defeats the synchronization the meta-guard depends on. The test would then no longer deterministically exercise the TOCTOU window it claims to. This is a fragility (flaky-under-load), not a false-green, because the final `assert len(channel.sent_text) == 2` still holds when the shim behaves — but the guarantee that the barrier actually paired the two stale reads is weakened.
**Fix:** Decouple the two timescales — give the barrier a generous timeout well above the DB busy_timeout, and make a broken barrier a hard failure instead of a silent pass:
```python
try:
    read_barrier.wait(timeout=30)  # >> the 5s store busy_timeout
except threading.BrokenBarrierError:
    raise AssertionError("meta-guard barrier broke — racers did not pair on the stale read")
```

### WR-02: Global monkeypatch of `daemon_mod.threading.Event` replaces the module's threading.Event for the whole test

**File:** `tests/test_scheduler.py:1263`, `1374`, `1429`, `1512`, `1559`, `1628`, `1711`, `1779`, `1841`, `1926` (every `monkeypatch.setattr(daemon_mod.threading, "Event", ...)`)
**Issue:** These tests patch the `Event` attribute on the `threading` module object that `daemon_mod` imported (`daemon_mod.threading` is the real `threading` module, not a daemon-local alias). `monkeypatch.setattr(daemon_mod.threading, "Event", ...)` therefore mutates the global `threading.Event` symbol for the duration of the test, not just the daemon's view of it. Any other code that runs during that test and constructs a `threading.Event` (a background thread, a library, a fixture) gets the fake. monkeypatch restores it on teardown so there is no cross-test leak, but within the test the blast radius is the entire interpreter, not the daemon — an over-broad patch that could mask the real code path if the daemon ever constructed an Event indirectly through another module.
**Fix:** Prefer patching a daemon-local seam. If `run_daemon` referenced `Event` via a module-level indirection (e.g., `from threading import Event as _Event` and `daemon._Event`), the patch would target only the daemon's construction site. Absent that, narrow intent by asserting the fake was actually the one constructed, or document that the whole-interpreter patch is acceptable because nothing else in the no-slot path builds an Event.

### WR-03: Inclusive vs strict ceiling on the jittered within-burst wait is inconsistent across `test_reliability.py`

**File:** `tests/test_reliability.py:109` (`step <= wait <= ceiling`) vs `tests/test_reliability.py:303` (`step <= no_ra_wait < step * 1.5`)
**Issue:** The within-burst wait is `step + uniform(0, step*0.5)`. `random.uniform(a, b)` CAN return the endpoint `b` (inclusive per CPython docs), so `wait == step*1.5` is a legal outcome. `test_two_burst_wait_shape` correctly uses `<=` on the ceiling; but `test_retry_after_capped:303` asserts the identical quantity with a strict `< step * 1.5`. If `uniform` ever returns exactly the boundary, one test passes and the other fails — the suite's contract on whether the ceiling is inclusive is self-contradictory.
**Fix:** Standardize on inclusive `<=` for the ceiling everywhere (change `< step * 1.5` at `:303` to `<= step * 1.5`), matching `uniform`'s reachable upper endpoint.

## Info

### IN-01: `test_post_send_success_log_raise_keeps_claim` custom `__getattr__` forwarder risks confusing failures

**File:** `tests/test_scheduler.py:728-737` (`_RaisingOnSlotFired`)
**Issue:** The fake logger forwards every non-`info` attribute via `__getattr__` to `real_log`. This is fine functionally, but `__getattr__` also intercepts dunder/internal lookups; if structlog ever probes an attribute `real_log` lacks, the `getattr(real_log, name)` raises `AttributeError` from deep inside the logging path, which would surface as an opaque failure unrelated to the branch under test.
**Fix:** Constrain the proxy to the methods the daemon actually calls (`info`, `warning`, `error`, `exception`, `critical`, `bind`) with explicit delegation, or subclass the real logger type.

### IN-02: Magic epoch literal `dt=1718377200` asserted only in a comment

**File:** `tests/test_models.py:704` (`# the real 2024-06-14 entry (dt=1718377200)`)
**Issue:** `_place_today_at_index_two` relies on `daily[0]` already being the 2024-06-14 entry; the epoch is documented in a comment but never asserted, so a fixture change that reorders `daily[]` would let the decoy logic silently operate on the wrong base entry while the comment still claims 06-14. The 76/58 assertions in the test would then fail with a misleading message rather than pointing at the moved base entry.
**Fix:** Add a one-line guard before building decoys: `assert datetime.fromtimestamp(today["dt"], ZoneInfo("America/New_York")).date().isoformat() == "2024-06-14"`, so the premise is checked, not assumed.

### IN-03: `test_null_dt_entry_skipped_in_date_index` requests the `imp` fixture but never uses it

**File:** `tests/test_multiday.py:179` (signature `def test_null_dt_entry_skipped_in_date_index(imp):`)
**Issue:** The test constructs its own synthetic `daily` list and never touches the injected `imp` fixture — the parameter is dead. It forces the 8-day fixture to load for no reason and misleads a reader into thinking the fixture is under test.
**Fix:** Drop the `imp` parameter from the signature (the test is self-contained).

### IN-04: `test_persist_onecall_atomic_rollback` string-matches SQL text to select the failing INSERT

**File:** `tests/test_store.py:128-134` (`if "INSERT INTO weather_onecall" in sql`)
**Issue:** The fault-injection wrapper decides which INSERT to fail by substring-matching the raw SQL string. If `persist` ever reformats its SQL (`INSERT  INTO`, a comment, or a parameterized table name), the match silently stops firing and the "metric INSERT fails mid-transaction" scenario never triggers. This is currently SAFE because the `else` branch (`raise AssertionError("expected the injected metric INSERT to raise")`) fails the test if `persist` did not raise — so a missed injection is caught, not passed vacuously. Flagged only as brittleness.
**Fix:** No correctness action required. Optionally assert `wrapper._onecall_inserts == 2` was reached after `persist` runs, to prove the injection point was actually exercised (rather than the first INSERT having failed for an unrelated reason).

---

_Reviewed: 2026-07-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
