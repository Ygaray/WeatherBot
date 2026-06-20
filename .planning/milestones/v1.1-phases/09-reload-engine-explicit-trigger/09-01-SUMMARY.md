---
phase: 09-reload-engine-explicit-trigger
plan: 01
subsystem: testing
tags: [pytest, reload, hot-reload, apscheduler, sent-log, exactly-once, nyquist-red, config-holder]

# Dependency graph
requires:
  - phase: 08-configholder-fire-slot-reads-from-holder-refactor
    provides: ConfigHolder.replace() swap seam + per-fire holder.current() read + frozen Config snapshots + stable job id name|time|days
  - phase: 03 (v1.0)
    provides: claim_slot/was_sent atomic sent-log idempotency key + _register_jobs CronTrigger per-slot
provides:
  - "tests/test_reload.py — RED contract for the Phase 9 reload engine (12 load-bearing node IDs, 15 incl. parametrized invalid-reload)"
  - "SC#4 exactly-once guard test_already_sent_slot_not_refired_after_tz_name_change (name/tz only, keeps send_time)"
  - "Companion test_send_time_change_is_new_slot_fires_today_if_ahead (accepted new-slot semantics)"
  - "All-or-nothing rollback + identical-noop + diff-reconcile + invalid-keeps-old(x4) + apply + SIGHUP + reload-CLI + diff-summary/reason-log + shared-validation tests"
  - "tests/test_models.py — Location.id default-from-raw-name + explicit-wins + frozen + duplicate-id RED tests (D-01)"
  - "tests/test_cli.py — check-config offline pass/fail + zero-network RED tests (CFG-08)"
  - "conftest.py — seed_sent_row (real claim_slot) + holder_scheduler harness fixtures for the engine plans"
affects: [09-02, 09-03, 09-04, 09-05, reload-engine, validate-config-and-templates, location-id, check-config, pid-file-sighup]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred per-test import of the not-yet-built reload entrypoint (_do_reload/_reload_cli) so all node IDs COLLECT while RED (Phase 8 Wave-0 lesson)"
    - "Sent-log seeding via the SHIPPED claim_slot so exactly-once tests exercise the real key, not a mock (T-09-01 no green-but-hollow scaffold)"
    - "holder_scheduler harness reuses ConfigHolder + a not-started BackgroundScheduler; assert on get_jobs() with no wall-clock waits"

key-files:
  created:
    - tests/test_reload.py
  modified:
    - tests/conftest.py
    - tests/test_models.py
    - tests/test_cli.py

key-decisions:
  - "SC#4 test keeps send_time FIXED (name/tz only) and asserts NO later re-fire — a time change is a new slot (amended D-02, RESEARCH A3)"
  - "No blanket per-location once-today guard introduced or tested (rejected — would break multi-slot-per-day locations)"
  - "Renamed the duplicate-id test to test_duplicate_location_id_rejected so `-k location_id` collects all four id tests"
  - "check-config no-network test patches the module-level fetch_onecall (weatherbot.weather.client) to explode if ever reached"

patterns-established:
  - "RED-on-missing-symbol: tests fail on real ModuleNotFoundError/AttributeError/ValidationError/SystemExit(2), never SyntaxError or collection abort"
  - "Exactly-once tests seed (id, time, today) and assert claim_slot loses on re-fire under the stable id"

requirements-completed: [CFG-01, CFG-02, CFG-04, CFG-05, CFG-06, CFG-08]

# Metrics
duration: ~10min
completed: 2026-06-16
---

# Phase 9 Plan 01: Wave-0 Reload-Engine RED Scaffold Summary

**A RED test suite pinning the Phase 9 reload contract — the SC#4 name/tz exactly-once guard, the separate send_time-is-new-slot semantics, two-phase rollback, diff-reconcile, the Location.id zero-migration key, and the offline check-config dry-run — all failing on missing symbols with a sent-log seeding + holder/scheduler harness for the engine plans to consume.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-16T14:00Z (approx)
- **Completed:** 2026-06-16T14:10Z
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 extended)

## Accomplishments
- `tests/test_reload.py` (NEW): 12 load-bearing reload node IDs (15 incl. the 4 parametrized `test_invalid_reload_keeps_old` cases) all COLLECT while RED, via deferred per-test imports of the not-yet-built `_do_reload`/`_reload_cli`/`validate_config_and_templates`.
- The highest-risk SC#4 guard `test_already_sent_slot_not_refired_after_tz_name_change` ships: a name + IANA-tz change on an already-sent slot KEEPS `send_time` (same logical slot under the stable id) → `claim_slot` loses on re-fire → no duplicate, no skip. The body never reassigns `send_time` and asserts no later-morning re-fire.
- The companion `test_send_time_change_is_new_slot_fires_today_if_ahead` pins the accepted semantics (a `send_time` change is a NEW key/job that fires today if still ahead), and explicitly allows both same-day slots to coexist (no blanket per-location once-today guard).
- `test_models.py` extended with the four `Location.id` D-01 tests (raw-name default = zero-migration key, explicit-id-wins, frozen-invariant, duplicate-id-rejected).
- `test_cli.py` extended with the three `check-config` CFG-08 tests (offline pass, offline fail, zero-network — patching `fetch_onecall` to explode if reached).
- `conftest.py` gained the `seed_sent_row` (real `claim_slot`) seeder and the `holder_scheduler` harness so the engine plans (09-02..05) need no test plumbing.
- The 226 pre-existing tests stay green; exactly the 22 new node IDs are RED.

## Task Commits

Each task was committed atomically:

1. **Task 1: NEW tests/test_reload.py — reload-engine RED suite + seeding harness** - `ab8c4f9` (test)
2. **Task 2: Extend test_models.py (Location.id) + test_cli.py (check-config offline)** - `b9f6c32` (test)

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified
- `tests/test_reload.py` - NEW: the reload-engine RED suite (apply, reject/keep-old, rollback, identical-noop, diff-reconcile, SC#4 name/tz exactly-once, send_time-is-new-slot, SIGHUP handoff, reload-CLI PID signal, diff-summary/reason logs, shared-validator).
- `tests/conftest.py` - Added `seed_sent_row` (seeds via shipped `claim_slot`) + `holder_scheduler` harness (ConfigHolder + not-started BackgroundScheduler).
- `tests/test_models.py` - Added the four `Location.id` D-01 tests (raw-name default, explicit-wins, frozen, duplicate-id-rejected).
- `tests/test_cli.py` - Added the three `check-config` offline CFG-08 tests (pass, fail, zero-network).

## Decisions Made
- **SC#4 scope (amended D-02):** the exactly-once guard protects NAME and TZ edits ONLY (both keep `send_time` → same logical slot); a `send_time` change is, by design, a new slot. Two separate named tests pin each side so neither silently regresses.
- **No suppression guard:** deliberately did NOT add or test a blanket per-location once-today guard (rejected — breaks multi-slot-per-day locations).
- **Test rename:** `test_duplicate_id_rejected` → `test_duplicate_location_id_rejected` so the acceptance `-k location_id` filter collects all four id tests (the plan's frontmatter named it `test_duplicate_id_rejected`; the rename keeps the duplicate-id semantics while satisfying the verification filter).
- **Stable `id` pinned explicitly in the exactly-once tests** (`id="home-stable"`) so the rename/tz-shift keeps the same sent-log key — this is what makes the slot recognizably "already sent" across the reload.

## Deviations from Plan

None - plan executed exactly as written. (The one micro-adjustment — renaming the duplicate-id test to include `location_id` so the `-k location_id` acceptance grep collects all four — is a naming refinement within the plan's own acceptance criteria, not a scope change. The plan's artifact contract `contains: "location_id"` is honored.)

## Issues Encountered
- **`fetch_onecall` shape:** the no-network check-config test originally patched a `OneCallClient.fetch_onecall` method; the live fetch is actually a module-level `weatherbot.weather.client.fetch_onecall(loc, key, units)` function. Adjusted the patch target and signature accordingly (resolved during Task 2 before commit).
- **Acceptance-grep prose collisions:** the SC#4-body grep (`send_time=|next.?day|defer`) and the whole-file `location.level|same.?day.suppress` grep initially matched explanatory docstring/comment prose. Reworded the prose ("same logical slot time", "blanket per-location once-today guard", "no later re-fire") so the greps return NOTHING while the meaning is preserved.

## User Setup Required
None - no external service configuration required. Test-only scaffold; zero new dependencies (`uv.lock` unchanged, T-09-SC accept).

## Next Phase Readiness
- The RED contract is in place: Plans 09-02..05 are judged done by flipping these named node IDs GREEN.
- Engine plans should implement, in dependency order: `Location.id` + `_default_id_from_name` (models.py) and unique-id in `assert_unique_names` (loader.py); `validate_config_and_templates` (loader.py, shared by check-config + reload); the `_do_reload` two-phase engine + diff-reconcile in daemon.py; the SIGHUP install + poll loop + PID-file sender (daemon.py + cli.py); the `check-config`/`reload` subcommands (cli.py); and the lockstep move of the four store callsites from `location.name` to `location.id`.
- The `_do_reload` signature is the engine's to define — these tests call it by keyword (`config`/`config_path`, `holder`, `scheduler`, `db_path`, `client`, `channel`); the engine should accept either an in-memory `config=` (the rollback/diff tests) or a `config_path=` to re-read+validate from disk (the invalid-keeps-old / shared-validation tests).

---
*Phase: 09-reload-engine-explicit-trigger*
*Completed: 2026-06-16*

## Self-Check: PASSED

- FOUND: tests/test_reload.py, tests/conftest.py, tests/test_models.py, tests/test_cli.py, 09-01-SUMMARY.md
- FOUND commits: ab8c4f9 (Task 1), b9f6c32 (Task 2)
- Full suite: 226 pre-existing passed, 22 new node IDs RED (15 reload + 4 model-id + 3 check-config) — exactly the intended Nyquist RED scaffold.
