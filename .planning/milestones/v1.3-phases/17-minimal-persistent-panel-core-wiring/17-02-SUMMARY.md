---
phase: 17-minimal-persistent-panel-core-wiring
plan: 02
subsystem: api
tags: [registry, dispatch, cli, argparse, discord, weather]

# Dependency graph
requires:
  - phase: 16-extract-shared-dispatch-spec
    provides: dispatch_spec ladder as the single source of truth (PANEL-10); registry CommandSpec model
  - phase: 17-minimal-persistent-panel-core-wiring (plan 01)
    provides: RED panel test scaffold the panel (plan 03) makes green
provides:
  - "weather as a real first-class registry command (CommandSpec + wired handler)"
  - "weather_views.weather(result) handler — byte-identical to build_inbound_embed (Now / High·Low / Rain)"
  - "CLI registry-loop skip-guard (_HANDWRITTEN) preventing an argparse conflicting-subparser crash"
affects: [panel, dispatch, cli, help, registry]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Skip-guard pattern: registry-derived subparser loop skips names already hand-written as standalone subparsers"
    - "Byte-identity refactor: a new dispatch-ladder handler reproduces a legacy embed field-for-field, proven by an equivalence test"

key-files:
  created: []
  modified:
    - weatherbot/interactive/registry.py
    - weatherbot/interactive/commands/weather_views.py
    - weatherbot/cli.py
    - tests/test_registry.py
    - tests/test_command_views.py

key-decisions:
  - "weather handler uses result.forecast.location (str) — NOT result.location.name — to stay byte-identical to build_inbound_embed (D-08, T-17-02-03)"
  - "Preserve the standalone weather subparser (-v/--verbose, D-09 quiet path); skip-guard the registry loop instead of deleting p_weather (RESEARCH A1)"
  - "weather lands in dispatch catch-all #4 (single-arg location handler) — zero dispatch.py ladder edit (W2 is additive to the ladder)"
  - "command.py left untouched (zero-change, as 17-PATTERNS.md predicted — parse_command already iterates the registry)"

patterns-established:
  - "Registry-loop skip-guard: a _HANDWRITTEN name set lets hand-written subparsers win and only genuinely-new registry commands get a loop-built subparser"
  - "Byte-identity equivalence test: assert a new CommandReply's title+lines match a legacy discord.Embed's title+fields field-for-field"

requirements-completed: [PANEL-03]

# Metrics
duration: 18min
completed: 2026-06-23
---

# Phase 17 Plan 02: Weather as a First-Class Registry Command Summary

**`weather` is now a real registry CommandSpec routing through the shared dispatch_spec → render_embed ladder, byte-identical to build_inbound_embed (Now / High·Low / Rain), with a CLI skip-guard that prevents the new spec from crashing the entire CLI via an argparse subparser collision.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-23
- **Completed:** 2026-06-23
- **Tasks:** 2 (Task 1 TDD: RED→GREEN)
- **Files modified:** 5

## Accomplishments
- Added `weather_views.weather(result)` — a behavior-preserving refactor of `bot.build_inbound_embed`; returns a `CommandReply` whose title + Now / High·Low / Rain fields render byte-identically to the legacy embed, using `forecast.location` (the str).
- Registered `CommandSpec("weather", "Weather", ..., True)` as the first Weather-group row and wired it to the handler in `_wire_handlers`, so the panel weather button (plan 03) routes uniformly through the dispatch ladder with NO panel-side special case (W2, D-07/D-08).
- Added the `_HANDWRITTEN` skip-guard to the `cli.py` registry-loop so the new `weather` spec no longer collides with the hand-written `weather` subparser — without the guard, argparse raises a conflicting-subparser error that breaks the ENTIRE CLI (D-08 / Pitfall 1). `weather --help` still shows `-v/--verbose`.
- Updated the `test_registry.py` Weather-group anti-drift assertion to include `weather` and added two positive tests (registration + byte-identity).

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing weather registry + byte-identity tests** - `f81e61f` (test)
2. **Task 1 (GREEN): wire weather as a first-class registry command** - `d974091` (feat)
3. **Task 2: CLI registry-loop skip-guard** - `72f4895` (fix)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified
- `weatherbot/interactive/commands/weather_views.py` - Added `weather(result) -> CommandReply` handler (Now / High·Low / Rain via `f.location`).
- `weatherbot/interactive/registry.py` - Added `CommandSpec("weather", ...)` as the first Weather-group row + `"weather": weather_views.weather` wiring.
- `weatherbot/cli.py` - Added `_HANDWRITTEN` set + `if _spec.name in _HANDWRITTEN: continue` skip-guard in the registry subparser loop.
- `tests/test_registry.py` - Weather-group assertion now includes `weather`; added `test_weather_command_registered_and_wired`.
- `tests/test_command_views.py` - Added `test_weather_reply_is_byte_identical_to_build_inbound_embed`.

## Decisions Made
- **Byte-identity via `forecast.location`:** the new handler titles off `result.forecast.location` (a plain str), matching `build_inbound_embed`, NOT the `result.location.name` that sibling handlers (alerts/sun/wind/next-cloudy/uv) use. This keeps the `!weather` reply byte-identical (T-17-02-03).
- **Preserve `p_weather`, skip-guard the loop:** kept the standalone weather subparser (with its `-v/--verbose` quiet-by-default path, D-09) and skipped it in the registry loop rather than deleting it (RESEARCH A1).
- **No `dispatch.py` edit:** a `takes_location` single-arg handler lands in dispatch catch-all #4, so W2 needed zero ladder change.
- **`command.py` untouched:** confirmed zero-change, exactly as 17-PATTERNS.md predicted (`parse_command` already iterates the registry).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. The TDD RED step correctly failed on the missing handler/spec before implementation; GREEN passed on first run.

## Known Stubs
None.

## Threat Flags
None - no new security surface. The handler reads only `result.forecast` fields (no secret); the skip-guard removes (not adds) a CLI crash vector.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `weather` now routes through the same `dispatch_spec → render_embed` ladder as every other command, so plan 17-03's panel weather button needs NO weather special case — it dispatches `weather` like any other registry command.
- Note: `tests/test_panel.py` remains intentionally RED (panel not built yet) — that is plan 17-03's job; the contractual anti-drift suite (registry/cli/command/dispatch/bot/command_views, 138 tests) is fully green.

## Self-Check: PASSED
- `weatherbot/interactive/commands/weather_views.py` `weather()` — FOUND
- Registry spec `BY_NAME["weather"]` — FOUND (asserted via test)
- `weatherbot/cli.py` `_HANDWRITTEN` skip-guard — FOUND
- Commit `f81e61f` (test RED) — FOUND
- Commit `d974091` (feat GREEN) — FOUND
- Commit `72f4895` (fix skip-guard) — FOUND

---
*Phase: 17-minimal-persistent-panel-core-wiring*
*Completed: 2026-06-23*
