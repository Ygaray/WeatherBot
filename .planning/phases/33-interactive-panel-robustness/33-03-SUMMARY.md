---
phase: 33-interactive-panel-robustness
plan: 03
subsystem: infra
tags: [config-reload, forecast-cache, discord-panel, hot-reload, selectedcontext]

# Dependency graph
requires:
  - phase: 33-interactive-panel-robustness (plan 02)
    provides: "ForecastCache generation-bump invalidate() (F13/D-03) that this plan orders ahead of the slow reload-outcome send"
provides:
  - "F17: _on_applied invalidates the ForecastCache BEFORE the slow Discord reload-outcome post, so a slow post no longer delays invalidation and serves OLD coords to an inbound !weather <loc>"
  - "F22: a renamed/removed selected location is reconciled to config.locations[0].name on hot-reload, so resolve_location(selection.value) can no longer raise UnknownLocationError for a location the user never sees selected"
  - "SelectedContext injected at build_runtime's single composition root and shared (one cell) with the panel dropdown via build_inbound_bot"
affects: [33-04 (panel F23/F24 — shares HARD-UI-02), phase-34 (comprehensive suite), verify-work-agentic]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Ordered best-effort reload side-effects extracted into a module-level, directly-testable seam (_apply_reload_side_effects) that _on_applied delegates to"
    - "Composition-root injection of the leak-point-1 SelectedContext (built in build_runtime, threaded into build_inbound_bot) so reload-reconcile and the panel share one cell"

key-files:
  created: []
  modified:
    - "weatherbot/scheduler/wiring.py — _reconcile_selection + _apply_reload_side_effects module helpers; _on_applied delegates; SelectedContext seeded at the composition root + threaded to build_inbound_bot; RuntimeParts.selection"
    - "weatherbot/scheduler/daemon.py — pass selection=parts.selection into build_inbound_bot"
    - "tests/test_lifecycle_module.py — invalidate-before-send + selection-reconcile regressions"
    - "tests/test_scheduler.py — BotThread fakes accept the new selection= kwarg"

key-decisions:
  - "Extracted the ordered reload side-effects into module-level _apply_reload_side_effects + _reconcile_selection (planner-discretion 'small helper' option) so both F17 ordering and F22 reconcile are unit-testable without standing up the heavyweight build_runtime path"
  - "Seed the SelectedContext at build_runtime's single composition root (not inside build_inbound_bot) and thread it through, so the panel dropdown and the hot-reload reconcile mutate ONE shared cell; build_inbound_bot keeps a self-sufficient fallback (selection=None → builds its own) for call-time construction in fakes"
  - "The 'SAME order + EXACT strings' invariant was re-annotated: it refers to the reload-outcome SEND STRING (kept byte-identical), NOT the invalidate-vs-send order — the F17 reorder is intended"

patterns-established:
  - "Best-effort reload-side-effect ordering: invalidate → send → prune → reconcile, each wrapped try/except … noqa: BLE001 so a hiccup never aborts the already-committed reload"

requirements-completed: []  # HARD-UI-02 is SHARED across plans 02/03/04 — deliberately NOT marked complete here; it flips to Complete when 33-04 lands.

coverage:
  - id: D1
    description: "F17 — _on_applied runs cache.invalidate() BEFORE the slow Discord reload-outcome channel.send, with the send string byte-identical and both side-effects best-effort"
    requirement: "HARD-UI-02"
    verification:
      - kind: unit
        ref: "tests/test_lifecycle_module.py::test_invalidate_before_send"
        status: pass
    human_judgment: false
  - id: D2
    description: "F22 — a renamed/removed selected location is reconciled to config.locations[0].name on hot-reload; a still-present selection is left untouched; resolve_location no longer raises"
    requirement: "HARD-UI-02"
    verification:
      - kind: unit
        ref: "tests/test_lifecycle_module.py::test_selection_reconcile_on_reload"
        status: pass
      - kind: unit
        ref: "tests/test_lifecycle_module.py::test_reconcile_selection_leaves_a_still_present_selection_untouched"
        status: pass
    human_judgment: false
---

# Phase 33 Plan 03: `_on_applied` invalidate-before-send + SelectedContext reconcile Summary

Hot-reload now invalidates the forecast cache before its (slow) Discord outcome post (F17) and reconciles a renamed/removed selected location to the default (F22) — both best-effort, keyed off the now-live config.

## Accomplishments

- **F17 — invalidate before send.** `_on_applied` previously posted the `✅ config reloaded: …` outcome to Discord and only THEN called `cache.invalidate()`. A slow/hung webhook therefore delayed invalidation, so an inbound `!weather <loc>` could be served OLD lat/lon/units until the post finally returned. The reorder moves `cache.invalidate()` (which bumps the Plan-02 generation) ahead of the send, so inbound lookups pick up the new config immediately. The reload-outcome send string is byte-identical; both side-effects stay best-effort.
- **F22 — reconcile stale selection.** The panel's `SelectedContext` was seeded once at wiring and never reconciled on hot-reload. A reload that renamed or removed the selected location left a stale name that a later `resolve_location(selection.value)` would reject with `UnknownLocationError` — for a location the user never sees selected. The new `_reconcile_selection` resets the held value to `config.locations[0].name` (the same default the panel seeds with) only when the current selection is no longer among the reloaded config's names; a still-present selection is left untouched.
- **One shared selection cell.** The `SelectedContext` is now created at `build_runtime`'s single composition root, exposed on `RuntimeParts.selection`, and threaded into `build_inbound_bot` (which keeps a `selection is None` fallback so it stays self-sufficient for fakes). This means the panel dropdown and the reload-reconcile mutate the SAME cell — the reconcile actually affects what the panel resolves.
- **Testable seam.** The ordered trio + reconcile were extracted into module-level `_apply_reload_side_effects` and `_reconcile_selection`, so the F17 ordering (shared order-list spy channel/cache) and F22 reconcile are unit-tested directly, without standing up the heavyweight `build_runtime` init path. `_on_applied` delegates to them, then does the watch-dir re-derive.

## Deviations from Plan

### Auto-fixed Issues

None — no Rule 1/2/3 fixes were required.

### Design note (within planner discretion)

- The plan noted "carrier is planner discretion (inline block or a small `_reconcile_selection` helper)" and "wire the `selection` reference into the `_on_applied` closure if not already captured." The `selection` was NOT previously captured in `_on_applied` (it lived only in `build_inbound_bot`, a separate function called later). Rather than reach across functions, the selection is now created at the composition root in `build_runtime` (where `_on_applied` can capture it) and threaded into `build_inbound_bot`. This required adding an optional `selection=` kwarg to `build_inbound_bot` and updating the three explicit `BotThread` fakes in `tests/test_scheduler.py` to accept it. This is wiring, not a behavior change, and stays app-side.

## Verification

- `uv run pytest tests/test_lifecycle_module.py -x` → 9 passed.
- RED-then-GREEN confirmed: the three new tests failed with `AttributeError` (seams absent) before Task 2 and pass after.
- Full suite: `uv run pytest -q` → **859 passed** (exit 0). The "2 snapshots failed" banner is the known syrupy report quirk (exit 0, no `.ambr` diff) — trusted per the pytest-snapshot-report-quirk convention.
- Manual F17 check: the reload-outcome send string `✅ config reloaded: {summary}` in `wiring.py` is unchanged — only its ORDER relative to `invalidate` moved.
- `git diff` for this plan touches ONLY `weatherbot/` + `tests/` (no hub-source edit) — cross-repo jurisdiction preserved.
- Lint: `weatherbot/scheduler/wiring.py` and the changed test files pass `ruff check` + `ruff format --check`.

## Deferred Issues

- Pre-existing (not introduced by this plan; out of scope per the SCOPE BOUNDARY) ruff findings in `weatherbot/scheduler/daemon.py`: `F401` unused imports (`ReloadEngine`, `PID_FILE`) and `F841` unused local `notifier` at the `parts.notifier` read. Present on HEAD before these edits; this plan only added a `selection=` kwarg to a call there. Logged for a future cleanup sweep (phase-35), not fixed here.

## HARD-UI-02 status

HARD-UI-02 is **shared across plans 33-02 / 33-03 / 33-04** and is intentionally left **In Progress** — it flips to Complete when 33-04 lands the F23/F24 panel fixes. Only this plan's ROADMAP progress line is advanced.

## Self-Check: PASSED
