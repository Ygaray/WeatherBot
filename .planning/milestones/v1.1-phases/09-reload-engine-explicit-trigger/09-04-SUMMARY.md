---
phase: 09-reload-engine-explicit-trigger
plan: 04
subsystem: scheduler
tags: [idempotency, exactly-once, sent-log, sqlite, apscheduler, reload, location-id]

# Dependency graph
requires:
  - phase: 09-02
    provides: "Location.id (optional stable identity, defaults to the RAW name → zero-migration key)"
  - phase: 08-04
    provides: "fire_slot single-read-per-fire holder snapshot; stable APScheduler job id name|time|days"
provides:
  - "The sent-log/alert exactly-once key's first component anchored to the STABLE location.id at all five callsites (daemon claim_slot/release_claim/record_alert/resolve_alert + catchup was_sent) in lockstep"
  - "Structural foundation for the SC#4 / Pitfall #8 exactly-once-across-reload guarantee: a NAME/TZ edit that keeps id + send_time can no longer reset 'already sent today'"
  - "Zero data migration — id defaults to raw name so id-keyed rows are byte-identical to existing sent_log/alerts rows"
affects: [09-05, reload-engine, exactly-once, sent-log]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lockstep idempotency-key migration: all callsites that read/write a shared sent-log key move to the stable id in ONE change (prevents claim/check desync, Pitfall 2)"
    - "Stable-id key with raw-name default → byte-identical rows, no schema/_SCHEMA edit, zero migration (Pitfall 3)"
    - "KEY vs DISPLAY separation: the store key argument moves to location.id; human-readable _log display fields and the APScheduler job-reconcile id stay on location.name"

key-files:
  created: []
  modified:
    - "weatherbot/scheduler/daemon.py — fire_slot's 10 store-key callsites (1 claim, 4 release, 4 record_alert, 1 resolve) keyed on location.id"
    - "weatherbot/scheduler/catchup.py — plan_catchup was_sent read keyed on loc.id"

key-decisions:
  - "All five exactly-once callsites moved to location.id in one lockstep change so the daemon claim and the catchup was_sent check agree on the same key (Pitfall 2)"
  - "weather/store.py left byte-unchanged: the column stays named location_name, only the VALUE the caller passes changes — no _SCHEMA edit, no migration (Pitfall 3)"
  - "_log display fields and the APScheduler job-reconcile id (name|time|days) deliberately stay on location.name — only the sent-log STORE key moved"

patterns-established:
  - "Lockstep key migration with zero-count negative grep + positive migrated-callsite count as the acceptance proof"
  - "Stable-id-with-raw-name-default for byte-identical, migration-free idempotency keys"

requirements-completed: [CFG-05]

# Metrics
duration: ~6min
completed: 2026-06-16
---

# Phase 09 Plan 04: Exactly-once key → location.id Summary

**The sent-log/alert exactly-once key's first component migrated from the mutable display `location.name` to the stable `location.id` at all five callsites (four daemon `fire_slot` store calls + catchup `was_sent`) in lockstep — byte-identical rows, zero migration, store untouched.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-16T14:40Z (approx)
- **Completed:** 2026-06-16
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `daemon.py::fire_slot` now claims/releases/records-alert/resolves under `location.id` at all 10 store-key callsites (1 `claim_slot`, 4 `release_claim`, 4 `record_alert`, 1 `resolve_alert`) — verified by a zero-count name-keyed negative grep (record_alert checked multi-line via `-A1`) and a positive count of 10 id-keyed callsites.
- `catchup.py::plan_catchup` now checks `was_sent(loc.id, ...)` — the fifth exactly-once callsite, moved in the SAME change so the daemon claim and the catchup check can never desync (Pitfall 2).
- Because `location.id` defaults to the RAW name (Plan 02), the id-keyed write/read is byte-identical to every existing `sent_log`/`alerts` row → ZERO data migration; an un-id'd config behaves exactly as today.
- The structural foundation of the SC#4 / Pitfall #8 guarantee is in place: a reload that changes a slot's NAME or TZ (keeping the id AND send_time) can no longer reset "already sent today" — the next fire's `claim_slot` loses on the unchanged id-keyed row.

## Task Commits

Each task was committed atomically:

1. **Task 1: Move fire_slot's four store-key call families to location.id (lockstep)** — `572c3f2` (refactor)
2. **Task 2: Move catchup was_sent to loc.id (the fifth callsite)** — `1d4225a` (refactor)

_Note: Both tasks were `tdd="true"`. The TDD "RED" here is the existing daemon/catchup suites that must stay green (byte-identical for un-id'd configs) plus the SC#4 id-key precondition; no new test file was authored by this plan (the SC#4 / reload tests live in `tests/test_reload.py` and complete end-to-end in Plan 05). No source-change was needed to make a test go from failing→passing because the change is a value-only key repoint that preserves all existing behavior — the guard is the lockstep grep acceptance, not a flipped test._

## Files Created/Modified
- `weatherbot/scheduler/daemon.py` — `fire_slot` store-key arguments moved `location.name` → `location.id` at the claim/release/record_alert/resolve callsites; `_log` display fields and the `name|time|days` job id left on `location.name`.
- `weatherbot/scheduler/catchup.py` — `plan_catchup` `was_sent` read moved `loc.name` → `loc.id`; injected `was_sent` Callable + the `_run_catchup` lambda unchanged (value-agnostic); D-06 docstring bullet updated to `location.id`.

## Decisions Made
- **Lockstep over incremental:** All five callsites moved together in the two task commits (daemon then catchup) — a claim taken under `id` must be released/checked/alerted under the SAME `id`, so splitting would have risked an orphaned-claim / duplicate-alert window (Pitfall 2).
- **Value not schema:** `weather/store.py` left untouched — the column stays `location_name`, only the passed value changes (Pitfall 3); `git diff --stat weatherbot/weather/store.py` is empty.
- **KEY vs DISPLAY:** Only the store KEY argument moved; the human-readable `_log.info/critical(location=location.name)` display fields and the APScheduler job-reconcile id (`name|time|days`) intentionally stay on `location.name`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Two of the `release_claim`/`record_alert` blocks in `fire_slot` are textually identical (the TimeoutException and non-ok DeliveryResult branches), so a single targeted Edit was ambiguous; resolved by using `replace_all` for the identical `release_claim(db_path, location.name, ...)` line and the identical `db_path, location.name, slot.time, local_date,` record_alert arg line, then a targeted Edit for the unique `claim_slot`/`resolve_alert`/auth-block lines. Final grep counts confirmed exactly 6 id-keyed claim/release/resolve + 4 id-keyed record_alert args, 0 name-keyed.

## Known Stubs
None - this plan is a value-only key repoint over existing, fully-wired store functions; no placeholder data, no unwired components.

## Threat Flags
None - no new network endpoint, auth path, file-access pattern, or schema change introduced. The change is an in-process argument-value repoint over existing store functions; logging stays outcome-only with the human display name (no secret).

## Test Status
- `tests/test_scheduler.py tests/test_reliability.py tests/test_send_now.py` — 55 passed (Task 1 verify).
- Catchup + already-sent precondition — catchup tests pass; the SC#4 id-key precondition (`claim_slot` loses on a seeded id row) holds.
- Full suite: **238 passed, 10 failed** — ALL 10 failures are confined to `tests/test_reload.py` and are the Plan-05 reload-engine RED tests (`ImportError: cannot import name '_do_reload'` and its one downstream assertion). These are explicitly OUT OF SCOPE for this plan (they require the daemon reload engine, Plan 05). Zero regressions outside `test_reload.py` — verified by `pytest -q | grep '^FAILED' | grep -vc 'tests/test_reload.py'` = 0.

## Next Phase Readiness
- The id-key half of the SC#4 exactly-once guarantee is structurally in place. Plan 05 (`_do_reload` reload engine) can now prove no re-fire end-to-end: it turns the 10 `tests/test_reload.py` RED tests (including `test_already_sent_slot_not_refired_after_tz_name_change`) green by landing the reload entrypoint that exercises this stable-id claim.
- No blockers introduced; `weather/store.py` and the v1 sent-log schema are untouched, so the live database needs no migration.

## Self-Check: PASSED
- `weatherbot/scheduler/daemon.py` — modified (commit 572c3f2 found)
- `weatherbot/scheduler/catchup.py` — modified (commit 1d4225a found)
- `09-04-SUMMARY.md` — present
- Both task commits present in git history.

---
*Phase: 09-reload-engine-explicit-trigger*
*Completed: 2026-06-16*
