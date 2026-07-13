---
phase: 34-test-gap-backfill
plan: 07
subsystem: scheduler-tests
tags: [testing, identity, rename-safe, midnight-catchup, F108, F14, HARD-TEST-02]
requires:
  - "tests/conftest.py file-backed tmp_db + load_fixture fixtures"
  - "weatherbot/scheduler/daemon.py fire_slot keying on location.id (unchanged)"
  - "weatherbot/scheduler/catchup.py plan_catchup was_sent(loc.id, ...) (unchanged)"
  - "weatherbot/config/models.py Location.id defaults to name (unchanged)"
provides:
  - "F108 rename-safe id != name test: fire_slot sent_log row + plan_catchup was_sent query both key on location.id, not display name"
  - "F14 [EXISTS] citation for the SC-3 midnight-catch-up ledger (test_catchup_prior_local_day)"
affects:
  - "tests/test_scheduler.py"
tech-stack:
  added: []
  patterns:
    - "distinct id != name Location (name='Beach House', id='loc-7') to expose the identity seam every id==name test masks"
    - "raw sqlite3 SELECT of sent_log.location_name to prove the persisted key by construction (not inferred from source)"
    - "recording was_sent spy capturing (name, time, date) to prove plan_catchup queries the id"
key-files:
  created: []
  modified:
    - "tests/test_scheduler.py"
decisions:
  - "D-08: F14 midnight catch-up cited [EXISTS] against test_catchup_prior_local_day (:313) — NOT duplicated and NOT extended; it already pins the full scenario (one yesterday-keyed MissedSlot, GRACE edges, already-sent dedup)."
  - "emitted_dates cross-candidate dedup is unreachable-by-construction (the two candidate dates are always distinct, 24h apart), so exactly-once under both candidates is already pinned by the existing 23:45 `len(missed) == 1` — no new assertion needed."
metrics:
  duration: "~4 min"
  completed: 2026-07-13
status: complete
---

# Phase 34 Plan 07: Rename-Safe Identity (F108) + Midnight Catch-up Citation (F14) Summary

Added a rename-safe `id != name` test that pins the scheduler's identity key to `location.id` (not the display `.name`) across `fire_slot` and `plan_catchup`, and confirmed + cited the already-existing F14 midnight-catch-up test [EXISTS] for the SC-3 ledger — no duplicate written.

## What Was Built

- **Task 1 — F108 rename-safe identity (HARD-TEST-02):** Added `test_fire_and_catchup_use_location_id_not_name` to `tests/test_scheduler.py`. Because `Location.id` defaults to `name` (`config/models.py:199-207`), every other scheduler test builds `id == name` and cannot tell the two apart — a regression from `location.id` to `location.name` in the claim/alert/catch-up path would be invisible. This test builds `Location(name="Beach House", id="loc-7")` (id != name), drives `fire_slot` on the clear fixture, then reads the raw `sent_log` via `sqlite3` and asserts `location_name == ["loc-7"]` (the id), never `"Beach House"`. It then drives `plan_catchup` with a recording `was_sent` spy and asserts the query is issued for `"loc-7"`, never `"Beach House"`. The `alerts` table is asserted empty of the display name too (the clear path fires no alert; if it ever did, it also keys on id). Tagged `# F108 / HARD-TEST-02`. No production code changed.
- **Task 2 — F14 midnight catch-up [EXISTS] (D-08):** Confirmed `test_catchup_prior_local_day` (`tests/test_scheduler.py:313`, already tagged `# D-01 / F14 (CONFIRMED)`) is GREEN. It fully pins the D-08 scenario: a 23:45 slot scanned at 00:15 the next local day → exactly ONE MissedSlot keyed on YESTERDAY's local_date (`2026-06-10`); the composed 23:45 instant; within-GRACE; the GRACE boundary edges (scheduled==now, exactly-GRACE, one-sec-past); and the already-sent dedup (`_sent_yesterday` → `[]`). Cited [EXISTS] for SC-3 — NOT duplicated and NOT extended (verified no D-08 aspect is missing; see Deviations for the emitted_dates analysis).

## Verification

| Check | Command | Result |
|---|---|---|
| Task 1 (F108) | `uv run pytest tests/test_scheduler.py -k "rename or location_id" -x -q` | 1 passed, exit 0 |
| Task 1 red→green spot-check | mutate daemon `claim_slot(db_path, location.id, ...)` → `location.name` | test RED (persists "Beach House"); restore → GREEN; `git diff --quiet` daemon.py clean |
| Task 2 (F14 [EXISTS]) | `uv run pytest tests/test_scheduler.py -k catchup_prior_local_day -x -q` | 1 passed, exit 0 |
| Combined | `uv run pytest tests/test_scheduler.py -k "rename or location_id or catchup_prior_local_day" -x -q` | 2 passed, exit 0 |
| Full module (no 34-01 collision) | `uv run pytest tests/test_scheduler.py -q` | 65 passed, exit 0 |

The F108 red→green spot-check proves the test is genuinely `.id`-sensitive against the **real** production `daemon.py`, not merely decorative: temporarily swapping `location.id` → `location.name` in `claim_slot` turns it red (the `sent_log` row then persists "Beach House"), and restoring it turns it green. `weatherbot/scheduler/daemon.py` verified byte-identical (`git diff --quiet` clean) after the spot-check — no production code changed. The full module is 65 passed (64 pre-existing incl. 34-01's F106 concurrent + metaguard tests, plus the 1 new F108 test) — the new test appends cleanly with no collision.

## Deviations from Plan

None — plan executed exactly as written. Tests-only; no production code modified (per CLAUDE.md ecosystem rule and the plan's tests-only scope). No app-side escape (D-07) surfaced: the current `daemon.py`/`catchup.py` already key correctly on `location.id`, so F108 is GREEN against current code and only RED against a hypothetical `.name` regression.

### emitted_dates dedup analysis (why Task 2 was NOT extended)

The plan permitted extending `test_catchup_prior_local_day` ONLY if a specific D-08 aspect (e.g. the `emitted_dates` cross-candidate exactly-once dedup) were genuinely unasserted. It is not missing in any testable sense: `plan_catchup`'s candidate loop (`catchup.py:158`) iterates two ALWAYS-DISTINCT dates (today and yesterday, 24h apart), and `emitted_dates` is keyed on `cand_date.isoformat()` — so the `if local_date in emitted_dates` guard (`:196`) can never fire from two distinct candidate dates. The only way a single slot would qualify under BOTH candidates is if both composed instants were ≤ now AND within the 90-min GRACE — impossible for two instants 24h apart inside a 90-min window. The existing 23:45 case already asserts `len(missed) == 1` (only yesterday qualifies; today's 23:45 is future → skipped), which is the exactly-once observable. Adding a duplicate assertion would test unreachable code. So the existing test was cited [EXISTS], not extended.

## Self-Check: PASSED

- FOUND: tests/test_scheduler.py (modified — test_fire_and_catchup_use_location_id_not_name present, tagged F108 / HARD-TEST-02)
- FOUND: commit dde4af2 (Task 1)
- CONFIRMED: test_catchup_prior_local_day green + tagged # D-01 / F14 (CONFIRMED) at tests/test_scheduler.py:313 (Task 2 [EXISTS] citation)
- CONFIRMED: weatherbot/scheduler/daemon.py unchanged (git diff --quiet clean after spot-check)
