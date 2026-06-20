---
phase: 08-configholder-fire-slot-reads-from-holder-refactor
plan: 01
subsystem: testing
tags: [pytest, nyquist, tdd, configholder, fire_slot, frozen, pydantic, concurrency]

# Dependency graph
requires:
  - phase: 04-reliability
    provides: "fire_slot two-burst retry callback + _RecordingStop/_Channel/_config/_slot/_patch_send_now reliability-suite helpers reused by the holder scaffold"
  - phase: 02-config
    provides: "the five pydantic config models (Schedule/Location/WebhookIdentity/Reliability/Config) the frozen-guard parametrizes over"
provides:
  - "NEW tests/test_config_holder.py — six RED node IDs that specify ConfigHolder semantics + fire_slot holder-read behavior (SC#1/SC#2/D-01/D-04)"
  - "tests/test_models.py frozen-mutation guard (test_frozen_rejects_mutation) parametrized over all 5 config models (D-02)"
  - "the falsifiable RED baseline Plans 02/03/04 flip GREEN to prove themselves done"
affects: [08-02, 08-03, 08-04, reload-engine, phase-09]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred-import RED scaffold: a not-yet-built symbol is imported inside a per-test helper (not top-of-module) so the node IDs still COLLECT while each test fails RED at run time"
    - "Concurrency invariant guard: N reader threads + 1 alternating writer, errors collected into a shared list, asserted empty after join() — deterministic, no real sleeps"
    - "model_copy(update=...) to build a distinct 'config B' (never hand-build, never mutate the frozen original)"

key-files:
  created:
    - tests/test_config_holder.py
  modified:
    - tests/test_models.py

key-decisions:
  - "Deferred the ConfigHolder import into a _holder() helper so all six node IDs collect while still landing RED on a real ModuleNotFoundError (a top-level import errors at COLLECTION and hides the node IDs, violating VALIDATION's collect-all-six requirement)"
  - "Frozen guard asserts pydantic.ValidationError (frozen_instance), never dataclasses.FrozenInstanceError (Pitfall 2 — these are BaseModels, not stdlib dataclasses)"
  - "Config B built only via config_a.model_copy(update={'template': 'other.txt'}); no code hashes/sets/dict-keys a Config (Pitfall 1)"

patterns-established:
  - "Deferred-import RED scaffold for Wave-0 Nyquist tests that reference not-yet-built symbols"
  - "Shared-error-list concurrency assertion (fail on any thread exception or torn/None read)"

requirements-completed: []  # plan requirements: none (prerequisite — unblocks CFG-01/CFG-05 in Phase 9)

# Metrics
duration: ~12min
completed: 2026-06-16
---

# Phase 08 Plan 01: ConfigHolder + fire_slot Holder Test Scaffold (RED) Summary

**Wave-0 Nyquist scaffold: a new tests/test_config_holder.py with six RED node IDs specifying ConfigHolder current/replace/concurrency/snapshot/override semantics, plus a frozen-mutation guard over all five config models — all landing RED on purpose while the 215 existing tests stay green.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-16
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 extended)

## Accomplishments

- Created `tests/test_config_holder.py` (238 lines) with the exact six VALIDATION node IDs: `test_current_returns_held`, `test_replace_rebinds`, `test_concurrent_read_swap_safe`, `test_inflight_job_keeps_snapshot`, `test_unchanged_job_renders_after_replace`, `test_config_override_wins`.
- Extended `tests/test_models.py` with a parametrized `test_frozen_rejects_mutation` covering all 5 config models (Schedule/Location/WebhookIdentity/Reliability/Config), asserting `pydantic.ValidationError`.
- Every new test lands RED for the intended reason (ConfigHolder + `fire_slot(holder=)` not built yet; models not yet `frozen=True`) while all 215 pre-existing tests stay green — the falsifiable baseline Plans 02/03/04 flip to prove themselves done.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tests/test_config_holder.py (RED)** - `cf181d9` (test)
2. **Task 2: Extend tests/test_models.py with frozen-mutation guard (RED)** - `b208f75` (test)

_Note: this is a TDD RED-only scaffold plan — the GREEN/feat commits land in Plans 02/03/04._

## Files Created/Modified

- `tests/test_config_holder.py` (created) - Six holder + fire_slot tests: current()/replace() unit semantics, ~8-reader/1-writer concurrency safety, mid-job snapshot retention, the "unchanged job renders new config after replace" core proof, and the explicit `config=` override-wins case. Reuses `_config`/`_slot`/`_RecordingStop`/`_Channel`/`_patch_send_now` from `tests.test_reliability` and `tmp_db` from conftest; config B via `model_copy(update=...)`.
- `tests/test_models.py` (modified) - Added `import pydantic`/`import pytest` and the model imports; appended parametrized `test_frozen_rejects_mutation` (5 cases) asserting `pydantic.ValidationError` on a post-construction field rebind for each model.

## Decisions Made

- **Deferred the `ConfigHolder` import into a `_holder()` helper.** A top-level `from weatherbot.config.holder import ConfigHolder` errors at COLLECTION, which hides the six node IDs and violates VALIDATION's "all six collect, then land RED at run time" requirement. Resolving the symbol inside a per-test helper keeps the file collectable (six node IDs enumerate) while each test still fails RED on a real `ModuleNotFoundError`.
- **Asserted `pydantic.ValidationError` (type `frozen_instance`), never `dataclasses.FrozenInstanceError`** (Pitfall 2 — these are pydantic BaseModels). The two `FrozenInstanceError` mentions in the file are documentation warnings telling future implementers not to use it, not assertions.
- **Built config B only via `model_copy(update={'template': 'other.txt'})`** and added no Config hashing/set/dict-key usage (Pitfall 1 — frozen + list field makes a Config unhashable).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Deferred the `ConfigHolder` import so the six node IDs collect**
- **Found during:** Task 1 (Create tests/test_config_holder.py)
- **Issue:** The plan's acceptance criteria require BOTH "collect-only lists all six node IDs" AND "import error on `weatherbot.config.holder`". A top-level `import ConfigHolder` fails at module import, producing a single collection ERROR — pytest then enumerates ZERO node IDs, so the "list all six" criterion could not be met.
- **Fix:** Moved the `ConfigHolder` import into a `_holder(config)` helper called inside each test body. The module now imports cleanly, all six functions collect, and each one fails RED at run time on the real `ModuleNotFoundError` — satisfying both criteria.
- **Files modified:** tests/test_config_holder.py
- **Verification:** `pytest tests/test_config_holder.py --collect-only -q` lists 6 node IDs; `pytest tests/test_config_holder.py -x` exits non-zero with `ModuleNotFoundError: No module named 'weatherbot.config.holder'`.
- **Committed in:** cf181d9 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The deferral is necessary to satisfy the plan's own dual acceptance contract (collect-all-six AND RED-on-missing-holder). It preserves the exact RED reason and node IDs; no scope creep. Plans 03/04 turn these GREEN unchanged — the helper resolves `ConfigHolder` the moment the module exists.

## Issues Encountered

None — both tasks executed cleanly. ruff passed on both files; the 215-test baseline stayed green throughout.

## Threat Surface Scan

No new runtime surface — test-only change. `test_concurrent_read_swap_safe` directly encodes the T-08-01 integrity invariant (no torn read / lost swap under concurrency) as the falsifiable spec, satisfying the threat register's `mitigate` disposition. No `Settings`/`appid`/webhook-URL construction was placed in the new test file (T-08-02 verified by absence). Zero packages installed (T-08-SC).

## Next Phase Readiness

- The RED baseline is laid down: Plan 02 (frozen models) flips `test_frozen_rejects_mutation` GREEN; Plan 03 (ConfigHolder) flips the holder unit tests; Plan 04 (`fire_slot(holder=)`) flips the integration tests.
- No blockers. The new tests are deterministic (bounded iterations, event-driven, no real sleeps) and reuse only existing fixtures/helpers.

## Self-Check: PASSED

- FOUND: tests/test_config_holder.py
- FOUND: tests/test_models.py
- FOUND: .planning/phases/08-.../08-01-SUMMARY.md
- FOUND commit: cf181d9 (Task 1)
- FOUND commit: b208f75 (Task 2)

---
*Phase: 08-configholder-fire-slot-reads-from-holder-refactor*
*Completed: 2026-06-16*
