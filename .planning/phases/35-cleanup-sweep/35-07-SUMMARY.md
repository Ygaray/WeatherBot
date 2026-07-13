---
phase: 35-cleanup-sweep
plan: 07
subsystem: weather/multiday
tags: [cleanup, hardening, multiday, day-selection, F70, F71]
requires: []
provides:
  - "multiday.select_days: drop-beats-add for contradictory same-day tokens (deterministic)"
  - "F71 accepted-with-rationale annotation (latent-vs-live boundary documented)"
affects:
  - weatherbot/weather/multiday.py
  - tests/test_multiday.py
tech-stack:
  added: []
  patterns:
    - "In-code # ACCEPTED (F##, v2.1) annotation for accepted-with-rationale low findings"
    - "TDD RED→GREEN regression for a behavior-changing fix"
key-files:
  created: []
  modified:
    - weatherbot/weather/multiday.py
    - tests/test_multiday.py
decisions:
  - "F71 (Friday-as-weekend) ACCEPTED-with-rationale, not changed: on the current single-slot deployment no location configures overlapping weekday+weekend slots, so there is no live Friday double-send (A1). Annotation documents it becomes a live bug to fix+test if overlapping slots are ever configured (D-01 accept, D-06 no behavior change, Open-Q2 conservative --auto choice). Flagged for the user via user_setup."
  - "F70 (drop cannot override same-day add) FIXED: dropped days' next-occurrence dates are subtracted AFTER the additive build so a contradictory +X -X resolves to dropped (drop wins). Non-contradictory add-only/drop-only/disjoint inputs preserved (D-06)."
metrics:
  duration: 4min
  completed: 2026-07-13
status: complete
---

# Phase 35 Plan 07: Multiday Cleanup Sweep (F71 accept + F70 fix) Summary

Accept-annotated F71 (Friday-as-weekend, conservative Open-Q2 default) and fixed F70 (drop now beats a contradictory same-day add) in `weatherbot/weather/multiday.py`, with a finding-tagged TDD regression test pinning drop-beats-add while preserving all non-contradictory day-selection behavior.

## What Was Built

**Task 1 — F71 accept-annotation (`docs`).** Added an in-code `# ACCEPTED (F71, v2.1): ...` comment at the `_WEEKEND_DAYS = ("fri", "sat", "sun")` tuple documenting that Friday is intentionally counted as weekend for the home/travel split, that there is no live double-send on the current single-slot deployment (A1), and that this becomes a live Friday double-send bug to FIX (drop `'fri'`) + regression-test if overlapping weekday+weekend slots are ever configured. `_WEEKEND_DAYS` is UNCHANGED — no behavior change (D-06). The domain-intent decision is flagged for the user via the plan's `user_setup`.

**Task 2 — F70 drop-beats-add fix (TDD `test` + `fix`).** Pre-fix, the additive `add` loop ran AFTER the base-block `drop` was applied, so a same-day `+X -X` re-added the dropped day (drop could not override an explicit add). The fix adds a second loop that subtracts each dropped day's next-occurrence date AFTER the additive build, so a contradictory `+X -X` deterministically resolves to dropped. A finding-tagged regression test (`test_drop_beats_contradictory_same_day_add`, `# HARD-CLEAN-02 / F70`) asserts the contradictory case excludes Saturday, and that add-only / drop-only / disjoint add+drop cases behave exactly as before.

## Task-by-Task

| Task | Type | Commit | Result |
|------|------|--------|--------|
| 1. Accept-annotate F71 | docs | `099d67d` | `# ACCEPTED (F71, v2.1)` at `_WEEKEND_DAYS`; tuple unchanged; suite green |
| 2. F70 RED test | test | `4ffc46b` | Failing regression: `+sat -sat` re-added Saturday (`[1,3,4,5,6,7]`) |
| 2. F70 GREEN fix | fix | `b710bfa` | Drop subtracted after add; contradictory case excludes Saturday; suite green |

## Verification

- `grep -q "# ACCEPTED (F71, v2.1):" weatherbot/weather/multiday.py` → exit 0 (annotation at `_WEEKEND_DAYS`).
- `_WEEKEND_DAYS` still `("fri", "sat", "sun")` — no behavior change (F71).
- F70 regression proven RED (`4ffc46b`, `assert 1 not in [1,3,4,5,6,7]`) then GREEN after fix (`b710bfa`).
- `uv run pytest tests/test_multiday.py -q` → 20 passed (19 baseline + 1 new).
- `uv run pytest -q` → 892 passed, **exit 0** (the "2 snapshots failed" line is the known pre-existing syrupy report quirk; exit code trusted per project convention).
- No hub-path file in the diff (`git diff --name-only` = `tests/test_multiday.py`, `weatherbot/weather/multiday.py` only).

## TDD Gate Compliance

Task 2 followed RED→GREEN: `test(35-07)` RED commit `4ffc46b` (proven failing against pre-fix behavior) precedes `fix(35-07)` GREEN commit `b710bfa`. No REFACTOR needed — the fix is a minimal, self-documenting second loop.

## Deviations from Plan

None — plan executed exactly as written. Both tasks landed with the planned dispositions (F71 accept-with-rationale, F70 behavior-changing fix + regression test).

## Requirements Satisfied

- **HARD-CLEAN-02** — remaining low-severity latent multiday findings resolved-or-accepted with no silent debt: F71 accepted-with-rationale (annotated + user-flagged), F70 fixed with a finding-tagged regression test.

## Self-Check: PASSED

- `weatherbot/weather/multiday.py` — FOUND (annotation + fix present)
- `tests/test_multiday.py` — FOUND (F70 regression test present, green)
- Commit `099d67d` — FOUND
- Commit `4ffc46b` — FOUND
- Commit `b710bfa` — FOUND
