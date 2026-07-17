---
phase: 33-interactive-panel-robustness
plan: 04
subsystem: ui
tags: [discord, panel, discord.py, interaction, selectedcontext, resilience]

# Dependency graph
requires:
  - phase: 33-interactive-panel-robustness (plans 02, 03)
    provides: F13 cache epoch-guard/bounding (02) and F17/F22 invalidate-before-send + selection reconcile (03) — the earlier HARD-UI-02 slices this plan closes on top of
provides:
  - Non-raising empty-locations degrade in the panel select contributor (F23) — zero-locations config renders a disabled placeholder Select instead of freezing the panel
  - Ack-before-mutate roll-back in LocationSelect.callback (F24) — a failed/expired interaction ack rolls the shared selection back instead of silently advancing it
  - HARD-UI-02 fully closed (final slice after 02 and 03)
affects: [phase-34-testing, phase-35-cleanup-sweep, panel, interactive]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Non-raising contributor degrade: an app panel contributor re-invoked by the frozen hub clone/error path must NEVER raise — degrade to a disabled, self-documenting placeholder component so neither clone path (success or _safe_error_edit) can recurse into the same exception and freeze the panel."
    - "Ack-before-mutate with roll-back: set shared interaction state first (so the re-render reflects it), ack, and on a genuine ack failure (discord.NotFound/HTTPException) roll the state back and re-raise into the existing View.on_error backstop — reversible mutation, not another blanket swallow."

key-files:
  created: []
  modified:
    - weatherbot/interactive/panel.py
    - tests/test_panel.py

key-decisions:
  - "F23 cured app-side (hub frozen): the recursion originates in the hub's _safe_error_edit → _build_clone_view, but the pinned wheel can't be edited, so the cure makes the APP contributor non-raising."
  - "Placeholder Select carries a single dummy option (value=__none__), disabled=True, and keeps the wb:loc:select custom_id — satisfies Discord's non-empty-options rule while making the empty-config state a visible recoverable cue."
  - "F24 sets the NEW selection before building the clone (so default= reflects it), then rolls back to the captured previous value only on ack failure, and re-raises rather than swallowing to a log."

patterns-established:
  - "Panel contributor non-raising invariant (F23): any contributor the hub clone/error path re-invokes degrades instead of raising."
  - "Reversible interaction mutation (F24): capture-previous → set-new → ack → roll-back-on-ack-failure + re-raise into the backstop."

requirements-completed: [HARD-UI-02]

coverage:
  - id: D1
    description: "Zero-locations config degrades to a disabled placeholder Select (no ValueError), so _build_clone_view() always succeeds and the hub error path cannot recurse into the same ValueError and freeze the panel; restoring locations re-renders a normal enabled LocationSelect (F23)."
    requirement: "HARD-UI-02"
    verification:
      - kind: unit
        ref: "tests/test_panel.py#test_empty_locations_recover"
        status: pass
    human_judgment: false
  - id: D2
    description: "A failed/expired ack (discord.NotFound) rolls the shared SelectedContext back to the previous value instead of leaving it silently advanced, and re-raises into the View.on_error backstop (F24)."
    requirement: "HARD-UI-02"
    verification:
      - kind: unit
        ref: "tests/test_panel.py#test_ack_failure_rollback"
        status: pass
    human_judgment: false

# Metrics
duration: 10min
completed: 2026-07-13
status: complete
---

# Phase 33 Plan 04: Empty-Locations Degrade (F23) + Ack Roll-back (F24) Summary

**Panel never freezes on an empty config (zero-locations degrades to a disabled placeholder Select instead of recursing into a swallowed ValueError) and never silently advances the selection on a failed/expired interaction ack (roll-back + re-raise) — both cured app-side against the frozen hub.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-07-13T04:04:33Z
- **Completed:** 2026-07-13T04:14:00Z
- **Tasks:** 2 (TDD: RED regressions → GREEN fix)
- **Files modified:** 2

## Accomplishments
- **F23 — empty-locations render recursion cured:** `_select_contributor` no longer `raise ValueError` on zero locations. It returns a disabled, self-documenting placeholder Select (`placeholder="No locations configured — edit config.toml"`, single dummy `__none__` option, `disabled=True`, keeps `wb:loc:select`). Because the frozen hub's `_safe_error_edit` re-invokes this contributor via `_build_clone_view()`, the previous raise recursed into the same ValueError → swallowed → frozen panel. Non-raising means every clone path succeeds; the empty-config state is now a visible recoverable cue, and restoring locations re-renders a normal enabled `LocationSelect`.
- **F24 — ack-before-mutate roll-back:** `LocationSelect.callback` now captures `previous = self._selection.value`, sets the new value first (so the clone's `default=` highlight reflects it), acks via `response.edit_message`, and on `discord.NotFound`/`discord.HTTPException` rolls the selection back to `previous` and re-raises into the module `View.on_error` backstop. A failed/expired ack can no longer leave the shared selection silently advanced past a render that never landed.
- **HARD-UI-02 fully closed** — this is the final slice after plan 02 (F13/bounding) and plan 03 (F17/F22).

## Task Commits

Each task was committed atomically (TDD RED → GREEN):

1. **Task 1: RED regressions (empty-locations recovery + ack-failure rollback)** - `8a67c75` (test)
2. **Task 2: Non-raising empty-locations degrade (F23) + ack-before-mutate roll-back (F24)** - `44ebc98` (fix)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified
- `weatherbot/interactive/panel.py` - `_select_contributor` returns a disabled placeholder Select on empty locations (was `raise ValueError`); `LocationSelect.callback` refactored to ack-before-mutate with roll-back on `discord.NotFound`/`HTTPException` + re-raise.
- `tests/test_panel.py` - added `test_empty_locations_recover` (F23) and `test_ack_failure_rollback` (F24).

## Decisions Made
- **F23/F24 cured app-side; hub untouched.** The recursion originates in the hub's `_safe_error_edit → _build_clone_view`, but the hub runs from the pinned v0.1.1 wheel and is frozen — so the cure makes the app contributor non-raising and the app callback reversible. `git diff` touches only `weatherbot/` + `tests/` (no `.venv/` or `../Reusable/` edit).
- **Placeholder shape:** single dummy option satisfies Discord's non-empty-options requirement; `disabled=True` means the placeholder value can never be chosen; keeping the `wb:loc:select` custom_id preserves persistent-view routing.
- **F24 re-raises rather than swallowing.** The plan's prohibition against "another blanket except that swallows to a log" was honored: the callback rolls back and re-raises into the existing `View.on_error`/`_safe_error_edit` backstop (a `logging.warning` records the rollback, not a swallow). The RED test drives `.callback()` directly (no live dispatcher wrapping), so it asserts the re-raise via `pytest.raises(discord.NotFound)` alongside the roll-back assertion.

## Deviations from Plan
None - plan executed exactly as written. (One test refinement mid-GREEN: `test_ack_failure_rollback` was updated to wrap the direct `.callback()` invocation in `pytest.raises(discord.NotFound)` because the fix re-raises into the backstop by design — the plan explicitly specifies re-raise, so this aligns the RED test's expectation with the specified contract rather than changing the fix.)

## Issues Encountered
None. Both regressions failed RED for the correct reasons (contributor `ValueError`; selection advanced to `travel` with no rollback) and passed GREEN after the fix.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- HARD-UI-02 closed; ROADMAP advanced. Remaining phase-33 plans: 33-05, 33-06 (HARD-UI-03 rendering defects).
- No blockers. Full `tests/test_panel.py` (37 tests) and `tests/test_import_hygiene.py` (3 tests) green; scope confined to `weatherbot/` + `tests/`.

## Self-Check: PASSED

- `33-04-SUMMARY.md` — FOUND
- Commit `8a67c75` (RED tests) — FOUND
- Commit `44ebc98` (fix) — FOUND
- `raise ValueError` statement in `_select_contributor` — REMOVED (only a comment reference remains)
- `test_empty_locations_recover` / `test_ack_failure_rollback` — FOUND
- Full `tests/test_panel.py` (37) + `tests/test_import_hygiene.py` (3) — GREEN
- `git diff` scope — only `weatherbot/` + `tests/` (no `.venv/` / `../Reusable/`)

---
*Phase: 33-interactive-panel-robustness*
*Completed: 2026-07-13*
