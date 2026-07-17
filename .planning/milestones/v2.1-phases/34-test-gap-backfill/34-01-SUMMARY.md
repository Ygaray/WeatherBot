---
phase: 34-test-gap-backfill
plan: 01
subsystem: scheduler-tests
tags: [testing, concurrency, F106, HARD-TEST-01, meta-guard]
requires:
  - "tests/conftest.py file-backed tmp_db fixture"
  - "weatherbot/weather/store.py claim_slot INSERT OR IGNORE atomicity (unchanged)"
provides:
  - "F106 genuinely-concurrent double-fire test (barrier threads)"
  - "F106 meta-guard proving claim_slot atomicity is exercised"
affects:
  - "tests/test_scheduler.py"
tech-stack:
  added: []
  patterns:
    - "canonical real-thread harness (threading.Barrier + shared errors list, no sleeps)"
    - "monkeypatched weakened-shim meta-guard (SELECT-then-INSERT) proving red-by-construction"
key-files:
  created: []
  modified:
    - "tests/test_scheduler.py"
decisions:
  - "D-06 red->green spot-check performed against the REAL store.claim_slot (not only the shim): weakening store.claim_slot turns the concurrent test red (2 deliveries); restoring it turns it green."
  - "Meta-guard read-barrier deterministically forces both racers past the stale was_sent read before either commits, so the TOCTOU hole is exercised without real sleeps."
metrics:
  duration: "~3 min"
  completed: 2026-07-13
status: complete
---

# Phase 34 Plan 01: F106 Concurrent Double-Fire Correction Summary

Corrected the F106 false-green `test_concurrent_double_fire_delivers_once` to a genuinely concurrent two-thread barrier race on the shared file-backed `tmp_db`, and added a co-located meta-guard that proves the test breaks if `claim_slot`'s `INSERT OR IGNORE`/`UNIQUE` atomicity is removed.

## What Was Built

- **Task 1 — real concurrency (F106):** Replaced the sequential double `fire_slot(...)` call (the false-green: a SELECT-then-INSERT `claim_slot` would also pass it) with two `threading.Barrier(2)`-synchronized worker threads racing the SAME slot key against the file-backed `tmp_db`. Exceptions are collected in a shared `errors` list (never swallowed); there are no real sleeps. Exactly-once is asserted by construction: `len(channel.sent_text) == 1`, exactly one non-None `fire_slot` return + one None, one `sent_log` row (`was_sent(...) is True`), and `errors == []`. Tagged `# F106 / HARD-TEST-01`. The pre-existing claim-arbitration prelude (unit-level `claim_slot`/`release_claim`/`was_sent` assertions) was retained.
- **Task 2 — meta-guard (D-04):** Added co-located `test_concurrent_double_fire_metaguard` that monkeypatches a weakened SELECT-then-INSERT `claim_slot` shim over both `weatherbot.weather.store.claim_slot` and the daemon-imported symbol `daemon_mod.claim_slot`. A read-barrier forces both racers past the stale `was_sent` read before either commits, deterministically exercising the TOCTOU window; the claim decision comes from the stale read (`return not already`), so both threads win and both deliver. Asserts `len(channel.sent_text) == 2` and `errors == []`. `store.py` is untouched; monkeypatch teardown restores the real `claim_slot`.

## Verification

| Check | Command | Result |
|---|---|---|
| Task 1 | `uv run pytest tests/test_scheduler.py -k concurrent -x -q` | 1 passed, exit 0 |
| Task 2 | `uv run pytest tests/test_scheduler.py -k "concurrent or metaguard" -x -q` | 2 passed, exit 0 |
| Full module | `uv run pytest tests/test_scheduler.py -q` | 64 passed, exit 0 |
| Meta-guard sanity | mutate meta-guard assert to `== 1` | fails `assert 2 == 1` (genuinely observes 2 deliveries) |
| D-06 red→green (real store) | weaken `store.claim_slot` to SELECT-then-INSERT | concurrent test RED (`len(sent_text)` == 2); restore → GREEN |

The D-06 spot-check confirms the corrected test is provably atomicity-sensitive against the **real** production `claim_slot`, not just the monkeypatched shim. `weatherbot/weather/store.py` verified byte-identical (`git diff --quiet`) after the spot-check — no production code changed.

## Deviations from Plan

None — plan executed exactly as written. Tests-only; no production code modified (per CLAUDE.md ecosystem rule and the plan's tests-only scope).

## Gate-1 Self-UAT Note (D-06)

The documented red→green mutation spot-check was performed as an in-repo temporary mutation (weaken `store.claim_slot` → run concurrent test → observe 2 deliveries / red → restore → green). No mutation-testing dependency was added. Behavioral Gate-1 verification (autonomous tester) remains owned downstream of execution.

## Self-Check: PASSED

- FOUND: tests/test_scheduler.py (modified — both tests present, tagged F106 / HARD-TEST-01)
- FOUND: commit b4ac468 (Task 1)
- FOUND: commit 17c7a79 (Task 2)
- CONFIRMED: weatherbot/weather/store.py unchanged (git diff --quiet clean)
