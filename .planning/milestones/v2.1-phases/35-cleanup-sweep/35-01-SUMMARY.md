---
phase: 35-cleanup-sweep
plan: 01
subsystem: testing
tags: [pytest, negative-grep, dead-code, drift-guard, cleanup]

# Dependency graph
requires:
  - phase: 34-test-gap-backfill
    provides: the token-from-parts negative-grep idiom (test_import_hygiene.py) this gate reuses
provides:
  - Wave-0 negative-grep gate tests/test_dead_code_removed.py pinning F16/F46/F76/F92 as staying gone
  - A drift-back guard that Plans 02/03/08 flip from inert-green to enforcing when they delete the symbols
affects: [35-02, 35-03, 35-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Start-state-green Wave-0 gate: each removal target budgeted at its single known pre-removal site (count <= 1); green at HEAD, green after removal, red only on drift-back to a new site"
    - "Token-from-parts self-proof discipline: forbidden tokens built by concatenation so the gate's own source (and docstrings) carry no literal — a grep over tests/ returns 0"
    - "Source-as-text reads (never import the daemon at module top) so the gate collects green while the dead defs still exist"

key-files:
  created:
    - tests/test_dead_code_removed.py
  modified: []

key-decisions:
  - "Budget-based start-state-green: chose count<=1 per target over a hard-zero so the gate is green at HEAD (removals not yet landed) yet reddens on drift-back after removal — matches the test_import_hygiene.py:104-119 posture the plan mandates"
  - "F46 test-tree check whitelists the ONE sanctioned pre-removal file (test_golden_coverage_fill.py); Plan 02 deletes those cases, auto-flipping the check to enforcing"
  - "F76 assertion region-scoped to the run_weather def signature (lines 327-399) so the unrelated -v/--verbose argparse flag and main() plumbing are not matched"
  - "F92 assertion targets ONLY the standalone discarded-result is_transient(exc) line (stripped-line equality), not the import or the classifier use inside is_auth_failure branches"

patterns-established:
  - "Consolidated per-phase drift-back gate: one test module covers all removal targets in a cleanup phase, each in its own test fn, so a drift-back names the exact finding id"

requirements-completed: [HARD-CLEAN-01]

coverage:
  - id: D1
    description: "Wave-0 negative-grep gate pins the four dead symbols (F16 emit_online/_do_reload, F46 _argv_is_weatherbot, F76 run_weather verbose param, F92 discarded is_transient call) as staying gone and never drifting back"
    requirement: "HARD-CLEAN-01"
    verification:
      - kind: unit
        ref: "tests/test_dead_code_removed.py (4 tests: F46/F76/F92/F16)"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-13
status: complete
---

# Phase 35 Plan 01: Dead-Code Drift-Back Gate Summary

**A start-state-green negative-grep pytest gate (tests/test_dead_code_removed.py) that pins F16/F46/F76/F92 as staying gone — green at HEAD, ready for Plans 02/03/08 to delete the symbols and flip it to enforcing.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-13T18:19:16Z (approx, plan execution start)
- **Completed:** 2026-07-13
- **Tasks:** 1
- **Files modified:** 1 (created)

## Accomplishments
- Authored the consolidated Wave-0 drift-back gate covering exactly the four removal targets (F16, F46, F76, F92) — no accepted/verify-only finding smuggled in as a removal.
- Gate is green at HEAD (removals not yet applied) via the start-state budget rule, and reddens the instant any removed symbol drifts back to a new site after Plans 02/03/08 land.
- Reuses the test_import_hygiene.py token-from-parts idiom so the gate's own source (including docstrings and function names) carries zero literal forbidden tokens — a grep over tests/ for the dead symbols returns 0.
- Reads production source as text only; never imports weatherbot.scheduler.daemon at module top, so it collects green while the F16 defs still exist.

## Task Commits

1. **Task 1: Author consolidated dead-code negative-grep gate** - `ccb2542` (test)

**Plan metadata:** (this commit — docs: complete plan)

_TDD note: This Wave-0 gate is authored green-at-HEAD by design (the "start-state green" rule); the RED→GREEN flip is owned by the downstream removal plans (02/03/08), so a single test commit is the correct atomic unit._

## Files Created/Modified
- `tests/test_dead_code_removed.py` - Consolidated Wave-0 negative-grep gate: 4 tests, one per finding, each budgeting its target at the single known pre-removal site.

## Decisions Made
- **Budget-based start-state-green (count<=1) over hard-zero:** the plan mandates green-at-HEAD with the removals not yet landed, so a hard "token absent" assertion would be RED today. Budgeting each target at its single sanctioned pre-removal occurrence is green now, green after removal, and red on drift-back.
- **F46 test-tree whitelist:** test_golden_coverage_fill.py still references the helper (Plan 02 removes it), so the test-tree check whitelists that one file; any OTHER test referencing it reddens, and after Plan 02 deletes those cases the whitelist becomes empty (enforcing).
- **F76 region-scoping:** scoped the verbose-param assertion to the run_weather signature region so the legitimate `-v/--verbose` CLI flag is not matched.
- **F92 discarded-line targeting:** matched only the bare stripped `is_transient(exc)` statement, sparing the import and the classifier use in the is_auth_failure branch.

## Deviations from Plan

None - plan executed exactly as written. (The gate's start-state-green mechanism was expressed as a per-target occurrence budget rather than a marker-comment, which the plan explicitly permits: "Prefer the simplest form that is green at HEAD and reddens on drift-back after removal.")

## Issues Encountered
- Initial draft's F46 test-tree assertion was a hard-zero and went RED at HEAD (the exclusive test still exists pre-removal); corrected to the whitelist budget form to satisfy the plan's green-at-HEAD requirement.
- Initial docstrings/function name carried literal forbidden tokens (AC2 grep returned 3, then 5); rewrote all prose to name symbols descriptively and renamed the F46 test fn, driving the self-match count to 0.

## Verification

- `uv run pytest tests/test_dead_code_removed.py -q` → **4 passed** (exit 0 at HEAD).
- `grep -c "def emit_online(\|def _do_reload(\|_argv_is_weatherbot" tests/test_dead_code_removed.py` → **0** (no self-invalidating literal).
- No top-level `weatherbot.scheduler.daemon` import in the gate.
- Docstrings/names cite HARD-CLEAN-01 and all four finding ids (F16, F46, F76, F92).
- Full suite: `uv run pytest -q` → **882 passed**, exit 0 (the "2 snapshots failed" line is the known pre-existing syrupy noise; exit code trusted).
- No `yahir_reusable_bot/` or `../Reusable/` file in the diff (hub untouched).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The drift-back gate is in place and green. Plans 02 (F46, F92), 03 (F76), and 08 (F16) can now delete their dead symbols; each removal drops its target's occurrence count to 0, keeping this gate green while making it enforcing against any future re-introduction.

## Self-Check: PASSED

- `tests/test_dead_code_removed.py` — FOUND
- Commit `ccb2542` — FOUND

---
*Phase: 35-cleanup-sweep*
*Completed: 2026-07-13*
