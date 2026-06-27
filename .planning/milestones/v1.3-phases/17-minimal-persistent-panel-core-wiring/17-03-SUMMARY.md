---
phase: 17-minimal-persistent-panel-core-wiring
plan: 03
subsystem: ui
tags: [discord.py, ui-components, persistent-view, interaction-check, dispatch-spec, structlog]

# Dependency graph
requires:
  - phase: 16-extract-shared-dispatch-spec
    provides: dispatch_spec async off-loop-fetch seam + render_embed renderer (the panel is its third caller)
  - phase: 17-01
    provides: tests/test_panel.py executable contract + conftest fake_interaction factory
  - phase: 17-02
    provides: weather CommandSpec + weather_view handler + CLI skip-guard (test_weather_spec_byte_identical already green)
provides:
  - "weatherbot/interactive/panel.py — PanelView(discord.ui.View, timeout=None) with CmdButton/LocationSelect children"
  - "Single-ack defer-then-edit contract (one response.edit_message cue + edit_original_response result)"
  - "interaction_check operator gate with byte-exact identity-free ephemeral reject + explicit structlog reject log"
  - "Per-callback non-propagating envelope + View.on_error backstop (component-path failure isolation)"
affects: [18-persistent-view-add_view, 19-forecast-button-layout, 20-panel-isolation-reproof]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "discord.py subclass-and-override (Button/Select.callback) for registry-derived dynamic children"
    - "Single response.* ack per component tap; result via edit_original_response (never a second response.*)"
    - "Operator gate in View.interaction_check with explicit reject log (clean False skips on_error)"
    - "Per-callback try/except + View.on_error backstop (the on_message envelope does not cover components)"

key-files:
  created:
    - weatherbot/interactive/panel.py
  modified: []

key-decisions:
  - "Selection held in-memory as _selected_location (default locations[0]); never re-read Select.values in a button callback (Pitfall 3), never encoded in custom_id"
  - "_disabled_copy rebuilds a disabled clone view to neutralize double-taps during the cold fetch (D-14, D-15-blessed disable path) paired with the ⏳ Fetching… cue"
  - "_safe_error_edit prefers edit_original_response in-place (post-ack) with send_message fallback, wrapped in its own best-effort try/except so an error reply never re-raises"

patterns-established:
  - "Persistent registry-derived View: timeout=None + static wb:cmd:<name>/wb:loc:select ids + build-time _assert_layout for the custom_id<=100/label<=80 caps discord.py does NOT enforce (Pitfall 5)"
  - "Curated ordered command tuples (_LOCATION_CMDS/_ARGLESS_CMDS) asserted against registry.BY_NAME at import so a registry rename fails loud at construction (D-06)"

requirements-completed: [PANEL-02, PANEL-03, PANEL-04, PANEL-05, PANEL-06, PANEL-08]

# Metrics
duration: ~18min
completed: 2026-06-24
---

# Phase 17 Plan 03: Minimal Persistent Panel (Core Wiring) Summary

**A persistent operator panel (`PanelView`) wiring tap-to-drive Discord components onto the Phase-16 `dispatch_spec` seam — single-ack defer-then-edit, operator-gated interaction_check, and per-callback failure isolation, all 11 `test_panel.py` nodes GREEN.**

## Performance

- **Duration:** ~18 min
- **Completed:** 2026-06-24
- **Tasks:** 3
- **Files modified:** 1 (created)

## Accomplishments
- `PanelView(discord.ui.View, timeout=None)` with a row-0 location `Select`, row-1 five location-command buttons (weather · uv · next-cloudy · sun · wind), and row-2 two argless buttons (status · alerts) — every child a static-`custom_id` registry-derived component (`view.is_persistent()` is True, ready for Phase 18 `add_view`).
- The load-bearing single-ack contract: exactly one `response.edit_message(content="⏳ Fetching…", view=<disabled copy>)` per tap before the off-loop `dispatch_spec` fetch, with the result landing in place via `edit_original_response` — never a second `response.*` (no `InteractionResponded`).
- The operator gate in `interaction_check`: bots + non-operators rejected with the byte-exact identity-free `"This panel is in use by someone else."` ephemeral reply plus an explicit `structlog` reject log (the sole audit, since a clean `return False` does not fire `View.on_error`).
- Component-path failure isolation: a per-callback non-propagating `try/except` on `on_command`/`on_select` plus a `View.on_error` backstop, so a raising callback can never reach the gateway loop / scheduler thread (the CMD-16 analog).

## Task Commits

Each task was committed atomically (TDD GREEN — the RED tests shipped in Plan 17-01):

1. **Task 1: PanelView construction (registry-derived children, layout assert, persistence, default selection)** - `9246df7` (feat)
2. **Task 2: Operator gate + single-ack defer-then-edit + dispatch_spec routing + in-place render** - `96aeb03` (feat)
3. **Task 3: Per-callback non-propagating envelope + View.on_error backstop** - `52223fd` (feat)

_Note: tests were already RED (shipped Plan 17-01), so each task is a single GREEN feat commit rather than a test→feat pair._

## Files Created/Modified
- `weatherbot/interactive/panel.py` - The persistent operator panel: `PanelView` + `CmdButton` + `LocationSelect`, the three correctness mechanisms (single-ack, operator gate, failure isolation), the curated registry-derived layout, and the in-memory selection state.

## Decisions Made
- **In-memory selection (D-01/D-02/D-03):** `_selected_location` is set from `select.values[0]` inside the Select's own callback and defaults to `locations[0]`; button callbacks read the attribute, never `Select.values` (empty outside an active select interaction — Pitfall 3), and the selection is never encoded in `custom_id`.
- **Disabled-copy ack (D-14/D-15):** `_disabled_copy()` rebuilds a fresh `timeout=None` view with disabled clones of every child so the cue ack also neutralizes double-taps during the cold fetch.
- **Error-reply surface (Pitfall 4 / A2):** `_safe_error_edit` prefers `edit_original_response` (the in-place followup path, correct after the ack) with a `send_message` fallback, wrapped in its own best-effort `try/except` so a failed error reply never re-raises (mirrors `bot.py:300-303`).

## Deviations from Plan

None - plan executed exactly as written. The three tasks mapped 1:1 to the three correctness mechanisms; all 11 `test_panel.py` node IDs and the full 600-test suite are green, imports are acyclic (`import weatherbot.interactive.panel` exits 0), and `ruff check` is clean.

## Issues Encountered
- The `weather`-spec contract test (`test_weather_spec_byte_identical`) was already green on entry — it was satisfied by Plan 17-02 (the `weather` `CommandSpec` + `weather_view` handler + CLI skip-guard). This plan correctly scoped to `panel.py` only and did not re-touch the registry/CLI.

## User Setup Required
None - no external service configuration required. (Deploy note: the live `yahir-mint` editable install must be restarted to load the new `panel.py` module — standard deploy loop — but Phase 17 does not yet `add_view` the panel; live registration is Phase 18.)

## Next Phase Readiness
- `view.is_persistent()` is True with every child carrying a static `custom_id`, so **Phase 18** can `add_view(PanelView(...))` in `setup_hook` without a `ValueError`.
- The panel touches only read-only surfaces (`registry`, `ForecastCache`, `holder.current()`, read-only `daemon_state`) — never the scheduler / sent-log / `holder.replace` — so **Phase 20**'s whole-panel isolation re-proof against a live scheduler has a clean seam.
- Out of scope and deferred as designed: persistent `add_view`/`message_id` durability (Phase 18), the forecast button (Phase 19), emoji labels / visual selection indicator (Phase 20).
- **Gate-2 (deferred, milestone-close):** live `yahir-mint` tap-each-button + in-place-edit + non-operator ephemeral-reject UAT under a real cold-cache fetch (per the global Verification Policy; non-blocking for this phase).

---
*Phase: 17-minimal-persistent-panel-core-wiring*
*Completed: 2026-06-24*

## Self-Check: PASSED
- FOUND: weatherbot/interactive/panel.py
- FOUND commit 9246df7 (Task 1)
- FOUND commit 96aeb03 (Task 2)
- FOUND commit 52223fd (Task 3)
- All 11 tests/test_panel.py nodes GREEN; full suite 600 passed; acyclic import OK; ruff clean
