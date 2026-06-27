---
phase: quick-260626-uqp
plan: 01
subsystem: ui
tags: [discord, panel, bot, interactive, pins, webhook]

requires:
  - phase: 18-persistence-summon-lifecycle
    provides: _handle_panel_summon (channel resolve/abort, perm preflight, Forbidden backstop, marker-strict ownership)
provides:
  - "!panel re-summon-to-bottom behavior (fresh panel posted+pinned at channel bottom, all prior owned panels deleted)"
  - _PANEL_RESUMMONED copy constant
affects: [panel, control-panel, PANEL-01]

tech-stack:
  added: []
  patterns:
    - "Create-before-delete ordering: post+pin fresh before deleting old (no zero-panel window)"

key-files:
  created: []
  modified:
    - weatherbot/interactive/bot.py
    - tests/test_bot.py
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md

key-decisions:
  - "Used create-before-delete ordering so there is never a zero-panel window (SC#4 no-orphan), preserved inside the existing Forbidden try/except backstop"
  - "Stray-count copy reports len(matches)-1 (one prior is logically replaced by the fresh panel, the rest are strays)"

patterns-established:
  - "Re-summon-to-bottom: !panel always posts a fresh newest-message panel then deletes all prior owned panels"

requirements-completed: [PANEL-01]

duration: 12min
completed: 2026-06-26
status: complete
---

# Phase quick-260626-uqp Plan 01: Panel Re-summon-to-Bottom Summary

**`!panel` now posts a fresh PanelView as the newest channel message, pins it, then deletes all prior bot-owned panels — repositioning the single pinned panel to the channel bottom on every summon (mobile reachability) while keeping the exactly-one-panel invariant.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-26
- **Completed:** 2026-06-26
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Rewrote `_handle_panel_summon` step-3 from reuse-in-place (`matches[0].edit(...)`) to create-before-delete recreate-at-bottom: post+pin a fresh panel first, then delete every prior owned panel (the previously-pinned one + strays).
- Added `_PANEL_RESUMMONED` copy constant; removed the now-unused `_PANEL_REUSED`. Kept `_PANEL_CREATED` (no-prior case) and `_panel_strays_cleaned_copy(n)` (>1-prior case).
- Updated panel-summon tests to assert fresh post+pin + old delete (never edit-in-place), added a create-before-delete ordering test, and rewrote the strays test for all-priors-deleted.
- Annotated REQUIREMENTS.md (PANEL-01 reworded) and ROADMAP.md (Phase 18 + 18-02 plan) with 260626-uqp supersession notes; PANEL-01 stays Complete / Phase 18.

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite `_handle_panel_summon` step-3 + copy constants** - `d83aa27` (feat)
2. **Task 2: Update panel-summon tests to re-summon-to-bottom** - `42fb027` (test)
3. **Task 3: REQUIREMENTS.md + ROADMAP.md supersession notes** - `19f49b2` (docs)

_Plan-doc metadata commit (SUMMARY.md / STATE.md) is handled by the orchestrator._

## Files Created/Modified
- `weatherbot/interactive/bot.py` - New step-3 always-recreate-at-bottom logic (create-before-delete inside the existing Forbidden try/except), `_PANEL_RESUMMONED` constant, docstring + comment updates; `_PANEL_REUSED` removed.
- `tests/test_bot.py` - `test_panel_resummon_posts_fresh_and_deletes_old` (renamed from reuse test), `test_panel_resummon_creates_before_deleting_old` (new ordering test), rewritten strays test; header comment updated; all `_PANEL_REUSED` references dropped.
- `.planning/REQUIREMENTS.md` - PANEL-01 reworded to re-summon-to-bottom with 260626-uqp supersession note (stays Complete / Phase 18).
- `.planning/ROADMAP.md` - Phase 18 entry + 18-02 plan line annotated as superseded by 260626-uqp.

## Decisions Made
- **Create-before-delete ordering** (post+pin fresh BEFORE any delete) so there is never a zero-panel window, even if a later delete write fails — kept entirely inside the existing `except discord.Forbidden` TOCTOU backstop so all new writes stay guarded.
- **Stray-count copy** reports `len(matches) - 1`: one prior panel is logically replaced by the fresh one, the remainder are strays. For the single-prior case the copy is `_PANEL_RESUMMONED`; for zero priors it stays `_PANEL_CREATED`.
- **Ordering test** uses explicit ordered `side_effect` markers (`["send", "pin", "delete"]`) rather than the weaker structural-guarantee fallback, since the existing Wave-0 fakes supported wiring it cleanly.

## Phase-18 Prohibitions Preserved (verified)
- D-04 channel resolve/abort (`_PANEL_CHANNEL_UNCONFIGURED`) — untouched (step 1).
- D-09/D-10 eager `permissions_for` preflight incl. `pin_messages`, refuse-before-write — untouched (step 2).
- D-09 per-write `except discord.Forbidden` TOCTOU backstop — still wraps ALL new create→pin→delete writes (the new step-3 body is inside the SAME `try:`).
- D-05 marker-strict `_is_owned_panel` ownership — unchanged.
- D-03 async-for `channel.pins()` (never `await channel.pins()`) — preserved.
- D-06 DELETE strays/old, never unpin-only — preserved; deleting the old pinned message also clears its pin → net exactly one pin.
- D-07 `!panel` stays operator-gated and NOT routed through `dispatch_spec` — unchanged.
- Untouched: PanelView, `_render_view`, clone-routing fix, `dispatch_spec`, registry, scheduler/briefing spine, `add_view` registration. Fresh panel uses `_build_view()` (the real PanelView) so static custom_ids keep add_view coverage post-restart.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## Known Stubs
None - no stub/placeholder patterns introduced. All new writes are wired to real Discord seams (`channel.send` / `msg.pin` / `old.delete`) and the fresh panel attaches the real `PanelView`.

## Final Gates
- `uv run pytest -q` → **652 passed** (baseline 651; +1 from the new create-before-delete ordering test, no regression).
- `uv run ruff check weatherbot tests` → **All checks passed!**
- `uv run ruff format --check weatherbot tests` → **79 files already formatted**.

## User Setup Required
None - no external service configuration required. (Behavior is live on the systemd `weatherbot` service on host `yahir-mint`; an editable-install restart picks up the change. Gate-2 human UAT of the on-device re-summon-to-bottom is a deferred milestone-close obligation per the Two-Gate UAT policy.)

## Next Phase Readiness
- PANEL-01 re-summon-to-bottom behavior shipped, fully covered by gateway-free tests, all gates green.
- Deferred: live device Gate-2 confirmation that the panel visibly moves to the channel bottom on mobile after `!panel`.

## Self-Check: PASSED

All modified files exist on disk; all three task commits (`d83aa27`, `42fb027`, `19f49b2`) present in git history.

---
*Phase: quick-260626-uqp*
*Completed: 2026-06-26*
