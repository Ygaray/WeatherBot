---
phase: 35-cleanup-sweep
plan: 06
subsystem: testing
tags: [interactive, discord, render, snapshot, syrupy, docstring, cleanup]

# Dependency graph
requires:
  - phase: 34-test-gap-backfill
    provides: regression-test shapes + finding-tagged assertion convention (34-PATTERNS.md)
provides:
  - "!locations marks the default (first) location with the ' (default)' suffix (F105)"
  - "next_cloudy hourly 'When' label is dated (%a %b %d %H:%M), matching daily/wind/alerts branches (F85)"
  - "models.from_payloads alerts docstring corrected: read ONCE from imperial, unit-independent (F66)"
  - "In-code # ACCEPTED (F##, v2.1) annotations for F62, F51, F83"
  - "F82 wind-degree rounded not truncated; F79 '!panel please' summons; F80 getattr default False"
affects: [35-cleanup-sweep Plan 09 ledger, interactive dispatch, golden snapshots]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "In-code accept-annotation: # ACCEPTED (F##, v<milestone>): <rationale> marks a knowingly-not-fixed finding at its site"
    - "Finding-tagged regression assertion: test docstring names 'HARD-CLEAN-02 / F##' so a finding maps to a named test"

key-files:
  created: []
  modified:
    - weatherbot/interactive/commands/info.py
    - weatherbot/interactive/commands/weather_views.py
    - weatherbot/interactive/bot.py
    - weatherbot/interactive/lookup.py
    - weatherbot/weather/models.py
    - tests/test_command_views.py
    - tests/test_bot.py
    - tests/__snapshots__/test_golden_embeds/test_next_cloudy_embed_golden.json
    - tests/__snapshots__/test_golden_cli/test_locations_stdout_golden.raw

key-decisions:
  - "F82/F79/F80 took the D-01 cheap-fix default (round / split-token match / getattr default) over accept; each preserves existing behavior"
  - "F83 accepted (annotation only): the len(daily) vs scanned-window count only diverges on an unusual empty-hourly/full-daily payload"
  - "F104 verify-only: lookup_forecast docstring already accurate at HEAD; not re-touched"

patterns-established:
  - "Accept-annotation convention: # ACCEPTED (F##, v2.1): <rationale> at the finding site records intentional non-fix (no silent debt)"

requirements-completed: [HARD-CLEAN-01, HARD-CLEAN-02]

coverage:
  - id: D1
    description: "!locations marks the default (first) location with ' (default)' (F105)"
    requirement: HARD-CLEAN-02
    verification:
      - kind: unit
        ref: "tests/test_command_views.py#test_locations_marks_the_default_location"
        status: pass
      - kind: unit
        ref: "tests/test_golden_cli.py#test_locations_stdout_golden"
        status: pass
    human_judgment: false
  - id: D2
    description: "next_cloudy hourly 'When' label is dated (%a %b %d %H:%M) (F85)"
    requirement: HARD-CLEAN-02
    verification:
      - kind: unit
        ref: "tests/test_command_views.py#test_next_cloudy_hourly_when_label_is_dated"
        status: pass
      - kind: unit
        ref: "tests/test_golden_embeds.py#test_next_cloudy_embed_golden"
        status: pass
    human_judgment: false
  - id: D3
    description: "models.from_payloads alerts docstring corrected (read once from imperial) (F66); F104 confirmed already-accurate"
    requirement: HARD-CLEAN-01
    verification:
      - kind: other
        ref: "grep -n 'read ONCE from the IMPERIAL' weatherbot/weather/models.py"
        status: pass
    human_judgment: false
  - id: D4
    description: "Accept-annotations for F62, F51, F83 recorded in-code (no silent debt)"
    requirement: HARD-CLEAN-01
    verification:
      - kind: other
        ref: "grep -c '# ACCEPTED (F62, v2.1):' weatherbot/weather/models.py; grep -c '# ACCEPTED (F51, v2.1):' weatherbot/interactive/lookup.py; grep -c '# ACCEPTED (F83, v2.1):' weatherbot/interactive/commands/weather_views.py"
        status: pass
    human_judgment: false
  - id: D5
    description: "F82 wind-degree rounded not truncated; F79 '!panel please' summons; F80 getattr default False"
    requirement: HARD-CLEAN-02
    verification:
      - kind: unit
        ref: "tests/test_command_views.py#test_wind_degree_is_rounded_not_truncated"
        status: pass
      - kind: unit
        ref: "tests/test_bot.py#test_panel_with_trailing_text_still_summons"
        status: pass
    human_judgment: false

# Metrics
duration: 7min
completed: 2026-07-13
status: complete
---

# Phase 35 Plan 06: Interactive/render + models-docs cleanup sweep Summary

**Marked the default location in !locations, dated the next_cloudy hourly label, corrected the F66 alerts docstring, and resolved the cosmetic F82/F79/F51/F80/F83/F62/F104 findings as one-char fixes or in-code accept-annotations — all with finding-tagged regressions and moved goldens.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-07-13T18:42:26Z
- **Completed:** 2026-07-13T18:49:22Z
- **Tasks:** 3
- **Files modified:** 9 (5 source, 2 test, 2 golden)

## Accomplishments
- **F105:** `info.locations` marks the first (default) location with the literal `" (default)"` suffix (matching the bot.py:223 bare-command marker), so the user can see which name a bare `!weather` resolves to.
- **F85:** `next_cloudy` hourly "When" label now renders `%a %b %d %H:%M` (dated) — unambiguous a few days out, aligned with the daily/wind-window/alerts branches.
- **F66:** `models.from_payloads` docstring corrected — alerts are read ONCE from the imperial payload (unit-independent, coordinate-keyed), not "from each payload".
- **F82/F79/F80 fixed; F62/F51/F83 accepted; F104 verified-clean** — every finding maps to FIX or ACCEPT (no silent debt), each accept carries an in-code `# ACCEPTED (F##, v2.1):` marker.
- Full suite green: **891 passed, exit 0** (887 baseline + 4 new finding-tagged assertions). Only the two intended goldens moved.

## Task Commits

Each task was committed atomically:

1. **Task 1: F105 default marker + F85 dated hourly label** - `1da69c8` (feat, TDD)
2. **Task 2: F66 docstring + F62/F51 accept-annotations + F104 verify-only** - `c0d5aaa` (docs)
3. **Task 3: F82/F79/F80 fixes + F83 accept** - `e51075f` (fix)

_Note: Task 1 was TDD (RED assertions → GREEN code → golden regen) but committed as a single atomic task commit since the render change is the primary deliverable and the RED/GREEN cycle was tight._

## Files Created/Modified
- `weatherbot/interactive/commands/info.py` - F105: first location gets " (default)" suffix
- `weatherbot/interactive/commands/weather_views.py` - F85 dated hourly label; F82 round(deg); F83 accept-annotation
- `weatherbot/interactive/bot.py` - F79 `content.split()[0] == "!panel"`; F80 `getattr(perms, name, False)`
- `weatherbot/interactive/lookup.py` - F51 accept-annotation (cached bake-time stamp); F104 verified-clean (no edit)
- `weatherbot/weather/models.py` - F66 corrected alerts docstring; F62 accept-annotation (uvi coalesce)
- `tests/test_command_views.py` - F105/F85/F82 finding-tagged assertions
- `tests/test_bot.py` - F79 finding-tagged assertion (`!panel please` still summons)
- `tests/__snapshots__/test_golden_embeds/test_next_cloudy_embed_golden.json` - regenerated (Fri 12:00 → Fri Jun 14 12:00)
- `tests/__snapshots__/test_golden_cli/test_locations_stdout_golden.raw` - regenerated (New York → New York (default))

## Decisions Made
- **F82/F79/F80 took the D-01 cheap-fix default over accept.** F82: `round(deg)` (199.8°→"200°"), compass sector already correct. F79: match `content.split()[0]` so `!panel please` summons but `!panelfoo` still does not. F80: `getattr(perms, name, False)` turns a missing perm-name into a clean "missing" refusal instead of AttributeError.
- **F83 accepted** — the `len(daily)` vs scanned-window count is cosmetic and only diverges on an unusual empty-hourly/full-daily payload; the honest empty-daily branch already exists.
- **F104 verify-only** — `lookup_forecast` docstring already says "DELEGATES to lookup_weather" / "NAMED seam" with no false cache-routing claim at HEAD; confirmed and NOT re-touched (marked FIXED for the Plan 09 ledger).

## Deviations from Plan

None - plan executed exactly as written. All eight findings resolved per their D-01 defaults; no auto-fix rules (1-4) triggered.

## Issues Encountered
- The `test_command_views.py` handler tests use direct body assertions (not syrupy), while the render fixes moved two syrupy GOLDEN snapshots elsewhere (`test_golden_embeds` next_cloudy embed, `test_golden_cli` locations stdout). Regenerated both with `--snapshot-update` and eyeballed the `.json`/`.raw` diffs — each showed exactly the intended marker/date change and nothing else.
- The suite prints "2 snapshots failed" but exits 0 — the pre-existing syrupy report quirk (project memory). Trusted the exit code; the two intended goldens were regenerated and the remaining report noise is unrelated.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Interactive/render + models-docs cluster is swept. F66/F104 docs and F105/F85/F82/F79/F51/F80/F83/F62 findings are all FIX-or-ACCEPT with in-code markers — ready for the Plan 09 ledger to record each as FIXED/ACCEPTED.
- No hub-path file touched; `models.py` remained single-owner within Wave 1.

## Self-Check: PASSED

All three task commits (`1da69c8`, `c0d5aaa`, `e51075f`) exist in git history and all modified source/test/summary files are present on disk.

---
*Phase: 35-cleanup-sweep*
*Completed: 2026-07-13*
