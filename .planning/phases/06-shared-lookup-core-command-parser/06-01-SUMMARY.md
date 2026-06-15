---
phase: 06-shared-lookup-core-command-parser
plan: 01
subsystem: interactive
tags: [parser, command, dataclass, enum, tdd, parse-dont-validate]

# Dependency graph
requires:
  - phase: 03-scheduler
    provides: ScheduleContext frozen value-object house style (dataclass idiom reused)
provides:
  - "weatherbot/interactive/command.py — parse_weather_command + Command (frozen dataclass) + CommandKind enum"
  - "Pure, config-free, I/O-free three-state command parser (NOT_A_COMMAND/DEFAULT/LOCATED)"
  - "tests/test_command.py — full 12-test input matrix for the parser"
affects: [phase-07-cli, phase-11-discord-bot, phase-06-03-package-barrel]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "parse-don't-validate seam (D-01): parser classifies + extracts raw, validates nothing against config"
    - "Word-boundary keyword guard (Open Question 2 / Pitfall 2) to prevent briefing-feedback loops"
    - "Namespace-package submodule import via pytest pythonpath=['.'] without __init__.py (barrel owned by 06-03)"

key-files:
  created:
    - weatherbot/interactive/command.py
    - tests/test_command.py
  modified: []

key-decisions:
  - "Keyword matched case-insensitively (casefold); extracted location keeps RAW case (D-04)"
  - "Word-boundary guard: non-whitespace immediately after 'weather' => NOT_A_COMMAND (weatherman, weather:)"
  - "Security: only str.strip/casefold/slicing — no str.format/eval/exec/shell (T-06-01)"
  - "No weatherbot.config import — parser is config-free and I/O-free (D-01)"

patterns-established:
  - "Three-state command result (CommandKind enum + frozen Command dataclass) as the shared parse contract for both surfaces"
  - "Input-matrix unit test (one assertion per matrix row, plain assert, no fixture) for pure-logic modules"

requirements-completed: []

# Metrics
duration: 3min
completed: 2026-06-15
---

# Phase 6 Plan 01: Shared Command Parser Summary

**Pure, config-free `weather <loc>` parser (`parse_weather_command` + `Command`/`CommandKind`) that classifies raw text into NOT_A_COMMAND/DEFAULT/LOCATED with a word-boundary guard and raw-case location extraction, fully unit-tested via a 12-row input matrix.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-06-15T20:43:18Z
- **Completed:** 2026-06-15T20:46:00Z
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 2 created

## Accomplishments
- `parse_weather_command(text)` returns a stable three-state `Command` (NOT_A_COMMAND / DEFAULT / LOCATED) — one source of truth for both the Phase 7 CLI and Phase 11 Discord bot.
- Parse-don't-validate seam (D-01): parser is config-free (no `weatherbot.config` import) and I/O-free; keeps the "unknown location" signal distinct downstream for CMD-04.
- Case-insensitive keyword with RAW-case location preservation (D-04), plus the word-boundary guard so "weatherman"/"weather:" return NOT_A_COMMAND (T-06-02, anti-feedback-loop).
- Security non-regression (T-06-01): only `str.strip`/`str.casefold`/slicing — no `str.format`/`eval`/`exec`/shell.

## Task Commits

Each task was committed atomically (TDD cycle):

1. **Task 1: Write the failing parser input-matrix test (RED)** - `8a45541` (test)
2. **Task 2: Implement the pure three-state parser (GREEN)** - `3cea614` (feat)

_REFACTOR step skipped — implementation was already minimal and lint-clean._

## Files Created/Modified
- `weatherbot/interactive/command.py` - `parse_weather_command`, `Command` (frozen dataclass: `kind`, `location`), `CommandKind` (Enum: NOT_A_COMMAND/DEFAULT/LOCATED). Config-free, I/O-free, no eval/format.
- `tests/test_command.py` - 12 input-matrix tests covering the full 11-row matrix plus a dataclass-type assertion; direct submodule import, no fixture.

## Decisions Made
None beyond plan — followed the plan's D-01..D-04 + Open Question 2 (word-boundary guard) exactly as specified.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. RED confirmed via expected `ModuleNotFoundError`; GREEN passed all 12 tests on first run; full suite went 186 → 198 passing.

## TDD Gate Compliance
- RED gate present: `8a45541` (test) — failing import/collection error confirmed before implementation.
- GREEN gate present: `3cea614` (feat) — all 12 matrix tests pass.
- REFACTOR: not required (no commit).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The shared parse contract is ready for consumers: Phase 7 CLI (`weather [location]`) and Phase 11 Discord bot can both call `parse_weather_command`.
- Plan 06-02 (lookup core) and 06-03 (package barrel + CLI delegation) can proceed; note 06-03 owns `weatherbot/interactive/__init__.py` (intentionally not created here so 01 and 02 run in parallel without a shared-file conflict). Until 06-03 lands, tests import directly from the submodule.

## Self-Check: PASSED
- FOUND: weatherbot/interactive/command.py
- FOUND: tests/test_command.py
- FOUND commit: 8a45541 (RED test)
- FOUND commit: 3cea614 (GREEN feat)

---
*Phase: 06-shared-lookup-core-command-parser*
*Completed: 2026-06-15*
