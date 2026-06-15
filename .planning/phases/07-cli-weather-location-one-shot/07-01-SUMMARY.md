---
phase: 07-cli-weather-location-one-shot
plan: 01
subsystem: infra
tags: [packaging, hatchling, uv, console-scripts, entry-point, cli]

# Dependency graph
requires:
  - phase: 06-shared-lookup-core
    provides: weatherbot.cli:main module-level callable (entry-point target)
provides:
  - "[build-system] (hatchling) so uv treats the project as an installable package"
  - "[project.scripts] weatherbot = \"weatherbot.cli:main\" console entry point"
  - "Materialized .venv/bin/weatherbot console script via uv sync"
affects: [07-02, "weather command handler", "verbatim `weatherbot weather <loc>` invocation"]

# Tech tracking
tech-stack:
  added: [hatchling (build backend)]
  patterns: ["PyPA console_scripts entry point materialized by uv sync", "single CLI entry point — no broadening of packaged surface"]

key-files:
  created: []
  modified: [pyproject.toml, uv.lock]

key-decisions:
  - "Used hatchling (PyPA-canonical) as the build backend rather than [tool.uv] package = true — portable, not uv-specific (D-03, RESEARCH Pitfall 1)"
  - "Added exactly ONE [project.scripts] entry; no broadening of packaged surface (T-07-PKG)"
  - "No new runtime dependency — argparse stdlib + existing tenacity/structlog/httpx cover the phase"

patterns-established:
  - "Console entry point: weatherbot = \"weatherbot.cli:main\" resolved via uv sync into .venv/bin/"

requirements-completed: [CMD-01]

# Metrics
duration: 4min
completed: 2026-06-15
---

# Phase 7 Plan 1: CLI Console-Script Entry Point Summary

**Made `weatherbot` a real installed console command by adding a hatchling `[build-system]` and a `[project.scripts]` entry point so `uv sync` materializes `.venv/bin/weatherbot`.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-15T22:34Z
- **Completed:** 2026-06-15T22:38Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Added `[build-system]` (`requires = ["hatchling"]`, `build-backend = "hatchling.build"`) so uv no longer treats the project as a non-package — the single most likely silent failure of this phase (RESEARCH Pitfall 1) is now eliminated.
- Added `[project.scripts]` with `weatherbot = "weatherbot.cli:main"`; `uv sync` built and installed the package, materializing `.venv/bin/weatherbot`.
- `uv run weatherbot --help` resolves and exits 0 (old flag surface is expected; the `weather <loc>` restructure is Plan 02).
- Full test suite stays green (206 passed) — packaging change introduced no regressions.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add build-system + console-script entry point and sync** - `ee4cd02` (feat)

**Plan metadata:** committed separately (docs: complete plan)

## Files Created/Modified
- `pyproject.toml` - Added `[build-system]` (hatchling) and `[project.scripts]` (weatherbot entry point)
- `uv.lock` - Updated by `uv sync` to record the project now builds as a package

## Decisions Made
- Chose hatchling (PyPA-canonical, HIGH-trust per RESEARCH Package Legitimacy Audit) over the `[tool.uv] package = true` uv-specific alternative — portable, no checkpoint required (T-07-SC accepted).
- Added exactly one entry point to avoid broadening the packaged/exposed surface (T-07-PKG mitigation).
- No new runtime dependency added — all libraries the phase needs are already declared.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The `weatherbot` console command now resolves as a real installed script (D-03), unblocking the verbatim `weatherbot weather home` acceptance in Plan 02 (CMD-01 / ROADMAP SC#1).
- No blockers or concerns.

## Self-Check: PASSED
- FOUND: pyproject.toml contains `[build-system]` and `[project.scripts]`
- FOUND: commit ee4cd02
- FOUND: .venv/bin/weatherbot (materialized console script)

---
*Phase: 07-cli-weather-location-one-shot*
*Completed: 2026-06-15*
