---
phase: 34-test-gap-backfill
plan: 03
subsystem: test-hardening
tags: [tests, cache, reload-engine, false-green, HARD-TEST-01]
requires:
  - weatherbot.interactive.cache.ForecastCache
  - yahir_reusable_bot.config.ReloadEngine
provides:
  - id-collapse cache assertion (F115)
  - register-before-remove ordering assertion (F116)
affects:
  - tests/test_cache.py
  - tests/test_reload_engine.py
tech-stack:
  added: []
  patterns:
    - "fetch-counting monkeypatch spy (reuse of test_second_lookup_within_ttl_hits_cache)"
    - "shared order-log threaded through injected stubs to pin call ordering"
key-files:
  created: []
  modified:
    - tests/test_cache.py
    - tests/test_reload_engine.py
decisions:
  - "F115: use a distinct id != name ('Cabin'/'loc-42') so a name-keyed cache is genuinely red; assert store key is the id via cache._cache membership."
  - "F116: thread an OPTIONAL shared order list through _make_engine + _FakeSchedulerEngine.remove (default None) so only the committed test opts in — every other reload test is byte-unchanged."
metrics:
  duration: ~8m
  completed: 2026-07-13
status: complete
---

# Phase 34 Plan 03: Correct Two False-Green Tests (F115 cache id-collapse, F116 reconcile ordering) Summary

Strengthened two order-blind / id-blind test assertions so each is genuinely RED against the exact bug it claims to guard: F115 proves the forecast cache keys on the resolved location `.id` (not `.name`) using a distinct `id != name`, and F116 pins that `ReloadEngine.reconcile` registers new jobs strictly before removing excluded ones (no momentary job gap). Tests-only — no production or hub source touched.

## What Was Built

### Task 1 — F115: cache collapses on `.id`, not `.name` (`tests/test_cache.py`)
Added `test_cache_key_collapses_on_id_not_name` using `_loc("Cabin", id="loc-42")` — a distinct `id != name`, unlike every existing cache test where `id` defaults to `name` (which is why the id-collapse claim was previously unproven). It reuses the fetch-counting monkeypatch spy and asserts:
- Two lookups of `"Cabin"` and case variant `"cabin"` collapse on id `loc-42` → exactly **one** fetch (a name-keyed cache would key `"Cabin"` ≠ `"cabin"` and fetch twice → RED against the name-keyed bug).
- The resolved store key is the id: `"loc-42" in cache._cache`, `"Cabin" not in cache._cache`.
- A different config whose name differs (`"Lodge"`) but whose id is the same `loc-42` hits the **same** entry (no new fetch) — equality is the `.id`.
- A distinct-id location (`loc-99`) does **not** hit the `Cabin` entry → a new fetch appends.

Commit: `212d421`.

### Task 2 — F116: register-before-remove ordering (`tests/test_reload_engine.py`)
Threaded an **optional** shared `order: list[str]` through `_make_engine` and `_FakeSchedulerEngine.remove` (default `None`, so every other reload test is byte-unchanged). The injected `register_jobs` stub appends `"register"`; `remove` appends `"remove:{job_id}"`. `test_reload_committed_success_diff_removes_excluded_and_summary` now asserts `order.index("register") < order.index("remove:gone")` — register strictly before every remove (the no-job-gap invariant). The prior `calls["register"] == [new_cfg]` and `fake.removed == ["gone"]` assertions are retained; a remove-then-register engine now fails where it previously passed. The hub `ReloadEngine` is driven entirely through injected app-side stubs — no hub edit (ECOSYSTEM.md).

Commit: `b2e55a4`.

## Verification

| Check | Command | Result |
|-------|---------|--------|
| Task 1 acceptance | `uv run pytest tests/test_cache.py -x -q` | 8 passed, exit 0 |
| Task 2 acceptance | `uv run pytest tests/test_reload_engine.py -k committed -x -q` | 1 passed, exit 0 |
| reload_engine full file (plumbing regression) | `uv run pytest tests/test_reload_engine.py -x -q` | 10 passed, exit 0 |
| Per-wave gate (full suite) | `uv run pytest -q` | 872 passed, exit 0 |

The full-suite "2 snapshots failed" report line is the known pre-existing syrupy quirk (exit 0 — not a golden diff); trusted the exit code per the phase note.

## Discriminating power (both red-by-construction, D-05)
- **F115:** a name-keyed cache keys `"Cabin"` and `"cabin"` differently → first assertion `len(fetches) == 1` fails. The id-store assertion (`"loc-42" in cache._cache`) is impossible under a name key.
- **F116:** a remove-then-register engine produces `order == ["remove:gone", "register"]` → `index("register") < index("remove:gone")` fails.

## Deviations from Plan

None — plan executed exactly as written. Both tasks tests-only; `cache.py` and the hub `ReloadEngine` were not modified (verified by staging only the two test files per commit).

## Known Stubs

None.

## Self-Check: PASSED
- FOUND: tests/test_cache.py (test_cache_key_collapses_on_id_not_name)
- FOUND: tests/test_reload_engine.py (order.index assertion in committed test)
- FOUND: commit 212d421 (Task 1)
- FOUND: commit b2e55a4 (Task 2)
