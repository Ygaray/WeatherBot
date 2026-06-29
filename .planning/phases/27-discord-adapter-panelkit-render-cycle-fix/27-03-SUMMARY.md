---
phase: 27-discord-adapter-panelkit-render-cycle-fix
plan: 03
subsystem: tests
tags: [import-hygiene, injection-oracle, marker-parameterization, byte-identical-oracle, gate-1-self-uat, render-cycle]

# Dependency graph
requires:
  - phase: 27-discord-adapter-panelkit-render-cycle-fix
    provides: "yahir_reusable_bot/discord/ — the module adapter (PanelKit/CmdButton/SelectedContext) the new gates introspect (Plan 27-01)"
  - phase: 27-discord-adapter-panelkit-render-cycle-fix
    provides: "weatherbot/scheduler/wiring.build_inbound_bot composition root (_render_bridge / marker / contributors injection site) the positive-injection assertion greps (Plan 27-02)"
  - phase: 27-discord-adapter-panelkit-render-cycle-fix
    provides: "the green relocated harness (test_panel.py/_make_panel + the byte-identical oracle) this plan re-runs (Plan 27-04)"
provides:
  - "tests/test_import_hygiene.py — discord/ tree-coverage guard + explicit core↔adapter grimp isolation + no-deferred-cycle-import (SC#2) gates"
  - "tests/test_injection_registry.py — PanelKit positive injection assertion (render/contributors/marker required, wired at build_inbound_bot); realigned leak-point-1/4 stubs (SelectedContext seam; render via _render_bridge); stale render_embed-in-panel assertion removed"
  - "tests/test_panelkit_marker.py — generic PanelKit(marker='X:') → X:cmd:<name> parameterization proof; module bakes no wb:"
  - ".planning/phases/27-.../27-SELF-UAT.md — the Gate-1 self-UAT log (PASS per SC#1-4 + PKG-01/APP-02/BHV-01/BHV-02; live restart PARTIAL/deferred)"
affects: [28-physical-repo-split]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Negative-grep guard that builds its forbidden token from parts (\"import\" + symbol) so the guard's own source never self-invalidates a future grep over tests/"
    - "Parametrized wiring-function AST keyword-arg scanner (_function_keyword_args) generalizing the build_runtime scanner to any composition-root function (build_inbound_bot)"
    - "Generic adapter construction smoke (fake registry + empty contributors + trivial render/dispatch) proving a marker parameter flows to the custom_id wire string with zero app code"

key-files:
  created:
    - tests/test_panelkit_marker.py
    - .planning/phases/27-discord-adapter-panelkit-render-cycle-fix/27-SELF-UAT.md
  modified:
    - tests/test_import_hygiene.py
    - tests/test_injection_registry.py

key-decisions:
  - "SC#2 grep nuance: the cycle oracle is the bot.py/panel.py endpoints (proven clean) — the one broad-grep hit is the app barrel re-export of app-owned render_embed (no PanelView to cycle back to), a benign same-package re-export, not a cycle edge"
  - "Realigned test_selected_location_context_originates_app_side off the now-docstring-only _selected_location to the robust relocated SelectedContext seam (panel.py + wiring.py consume it)"
  - "Removed the stale 'render_embed in panel_src' assertion (panel.py no longer imports render_embed post-relocation) — re-pointed the app-side-ownership proof to the composition-root _render_bridge in wiring.py"
  - "Marker test imports zero app code (fake registry + empty contributors) so the marker-parameterization proof stays a genuine generic-module test"

requirements-completed: [SEAM-07]

# Metrics
duration: 14min
completed: 2026-06-29
status: complete
---

# Phase 27 Plan 03: Boundary Gates + Byte-Identical Oracle + Gate-1 Self-UAT Summary

**Extended the standing test gates to the relocated Discord adapter — import-hygiene now requires the `discord/` tree in litmus coverage and proves the `render_embed`↔`PanelView` cycle is dead (SC#2); the injection oracle adds the positive PanelKit render/contributors/marker assertion and realigns the leak-point stubs to the relocated `SelectedContext`/`_render_bridge` shape; a new generic marker test proves `PanelKit(marker="X:")` yields `X:cmd:<name>` ids with no baked `wb:`; the full byte-identical oracle re-ran green (783 passed, exit 0, zero `.ambr` re-baseline); and the Gate-1 self-UAT log records the evidence with the live restart deferred to Phase 28.**

## Performance
- **Duration:** ~14 min
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- **SC#1 — litmus tree-coverage.** `test_litmus_clean` now asserts `{panelkit.py, gateway.py, selection.py}` are in the scanned `yahir_reusable_bot/discord/` tree (mirrors the lifecycle/registry coverage-gap guards), so a future relocation can't silently drop the adapter from litmus coverage. The D-13 term set is UNCHANGED.
- **SC#2 — cycle dead, proven two ways.** `test_no_deferred_cycle_import_survives_in_app_interactive` reads `bot.py`/`panel.py` source and reddens if either carries an `import PanelView`/`import render_embed` edge (forbidden tokens built from parts so the guard's own source stays grep-clean); `test_discord_adapter_imports_zero_app_code` is the explicit grimp gate naming the adapter package. Both green. `PanelView` no longer exists app-side at all.
- **APP-02 — positive injection.** `test_panel_cosmetics_and_render_and_marker_are_app_supplied`: `render`/`contributors`/`marker` are REQUIRED no-default `PanelKit.__init__` params (each with a biting baked-default self-proof); `panelkit.py` bakes no `wb:`; all three are wired at the single composition root `wiring.build_inbound_bot` (via the new parametrized `_build_inbound_bot_keyword_args` AST scanner).
- **Leak-point stubs realigned.** `test_selected_location_context_originates_app_side` now proves the relocated `SelectedContext` seam (panel.py + wiring.py) instead of the gone `_selected_location` attribute; `test_render_embed_is_app_side_module_owns_no_render` dropped the stale `render_embed in panel_src` assertion (panel.py no longer imports it) and re-points the app-side-ownership proof to the composition-root `_render_bridge`.
- **SC#3 — marker parameterized.** New `tests/test_panelkit_marker.py` constructs a fully-generic `PanelKit(marker="X:")` (zero app code) → `X:cmd:<name>` ids; a second `marker="reminder:"` panel yields `reminder:cmd:<name>`; module source bakes no `wb:`.
- **SC#4 / BHV-01 / BHV-02 — byte-identical oracle.** `uv run pytest -q` → **783 passed, exit 0** (was 778; +5 new gate tests); explicit goldens 88 passed, 12 snapshots passed; `git status` shows zero `.ambr`/golden/fixture file change (no re-baseline). The printed "2 snapshots failed" is the documented syrupy quirk (exit 0 + empty `.ambr` diff confirm it).
- **Gate-1 self-UAT log written** with per-criterion PASS + exact commands/evidence; the live `yahir-mint` restart re-bind is the single deferred Gate-2 PARTIAL (mechanism verified via the frozen custom_id snapshot + persistent-view registration; physical run = Phase 28).

## Task Commits
1. **Extend import-hygiene — discord/ tree coverage + core↔adapter isolation + no-deferred-import SC#2** — `63419cc` (test)
2. **PanelKit positive injection + marker-parameterization; realign leak-point stubs** — `450a30a` (test)
3. **Full byte-identical oracle re-run + Gate-1 self-UAT log** — `d1da496` (test)

## Files Created/Modified
- `tests/test_import_hygiene.py` (modified) — discord/ tree-coverage guard in `test_litmus_clean`; `test_discord_adapter_imports_zero_app_code` (grimp, adapter-scoped); `test_no_deferred_cycle_import_survives_in_app_interactive` (SC#2, tokens built from parts) + the `_REPO_ROOT_INTERACTIVE` constant.
- `tests/test_injection_registry.py` (modified) — `_function_keyword_args`/`_build_inbound_bot_keyword_args` helpers; `test_panel_cosmetics_and_render_and_marker_are_app_supplied`; realigned `test_selected_location_context_originates_app_side` (SelectedContext seam) and `test_render_embed_is_app_side_module_owns_no_render` (composition-root `_render_bridge`, stale assertion removed); `PanelKit` import.
- `tests/test_panelkit_marker.py` (created) — `test_panelkit_marker_parameterized` + `test_panelkit_marker_selfproof_detector_bites`; generic fake-registry construction harness.
- `.planning/phases/27-discord-adapter-panelkit-render-cycle-fix/27-SELF-UAT.md` (created) — the Gate-1 self-UAT log.

## Decisions Made
- **SC#2 grep nuance — the cycle is dead; the one broad-grep hit is benign.** The plan's literal verify grep `'import render_embed\|import PanelView' weatherbot/` returns ONE hit: `weatherbot/interactive/__init__.py: from .bot import render_embed`. This is the package **barrel** re-exporting its OWN app-owned `render_embed` from its sibling `bot.py` (present since before Phase 27). It cannot form the `render_embed↔PanelView` cycle (there is no `PanelView` to point back to). SC#2 is about the cycle *endpoints* — `bot.py`/`panel.py` — which are proven clean by grep + the grimp gate + the no-deferred-import gate. Scoped the SC#2 verify to those endpoints and documented the nuance in the self-UAT.
- **Realigned the docstring-fragile stubs to robust source assertions.** Both `_selected_location` (panel.py) and `render_embed` (panel.py) now appear ONLY in docstring prose post-relocation, so the v1 substring assertions were passing for the wrong reason. Re-pointed to the relocated seams: `SelectedContext` (consumed in panel.py + injected in wiring.py) and `_render_bridge` → app embed builder (wiring.py).

## Deviations from Plan
None — plan executed as written. The SC#2 verify-grep scoping (cycle endpoints vs. the broad pattern that also matches the benign barrel re-export) is a documented interpretation of the SC#2 intent, not a deviation: the cycle the criterion targets is genuinely dead, proven by the bot.py/panel.py endpoint grep + the grimp + no-deferred-import gates.

## Known Stubs
None — all new tests assemble/introspect the real module `PanelKit` + the real wiring source; no hardcoded empty/placeholder data flows to an assertion.

## Threat Flags
None — test-only plan + a self-UAT doc; no new network endpoint, auth path, or trust boundary. T-27-09 (silent golden re-baseline) HELD (zero `.ambr` diff); T-27-10 (reintroduced cycle) HELD (the no-deferred-import + grimp gates redden on any new edge); T-27-11 (unverified claim) HELD (self-UAT records exact commands + evidence); T-27-SC ACCEPT (no install).

## Self-Check: PASSED
- Created files: FOUND `tests/test_panelkit_marker.py`, FOUND `.planning/phases/27-discord-adapter-panelkit-render-cycle-fix/27-SELF-UAT.md`.
- Commits: all 3 FOUND (`63419cc`, `450a30a`, `d1da496`).
- Gates: `test_import_hygiene.py` 11/11; `test_injection_registry.py` 10/10; `test_panelkit_marker.py` 2/2; full suite `uv run pytest -q` → 783 passed, exit 0; goldens 88 passed byte-identical (zero `.ambr` re-baseline); SC#2 cycle endpoints (bot.py/panel.py) clean; `grep '"render_embed" in panel_src' tests/test_injection_registry.py` → nothing (stale assertion removed); D-13 litmus term set unchanged.

---
*Phase: 27-discord-adapter-panelkit-render-cycle-fix*
*Completed: 2026-06-29*
