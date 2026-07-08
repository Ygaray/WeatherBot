---
phase: 27-discord-adapter-panelkit-render-cycle-fix
plan: 04
subsystem: tests
tags: [test-harness, panelkit, byte-identical-oracle, discord-adapter, dependency-injection, render-bridge]

# Dependency graph
requires:
  - phase: 27-discord-adapter-panelkit-render-cycle-fix
    provides: "yahir_reusable_bot/discord/ — the module PanelKit/BotThread/build_client/SelectedContext/summon_panel the harness drives (Plan 27-01)"
  - phase: 27-discord-adapter-panelkit-render-cycle-fix
    provides: "weatherbot/interactive/{bot,panel}.py shrunk to contributors + render_embed; wiring.build_inbound_bot composition root (Plan 27-02)"
provides:
  - "tests/test_panel.py — _make_panel rewired to assemble the module PanelKit via app contributors + injected render/marker/selection/dispatch; _HarnessPanel adapter subclass re-exposing the pre-relocation API"
  - "tests/test_bot.py — gateway (build_client/setup_hook/BotThread) + !panel summon tests rewired onto the module adapter"
  - "tests/test_scheduler.py — daemon bot-construction + panel-wedge patch targets repointed to wiring.build_inbound_bot / the module PanelKit"
  - "wiring.build_inbound_bot — per-tap render-location cell fixing argless panel 📍 suppression (the relocation-regressed v1 contract)"
affects: [27-03-injection-oracle]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Harness adapter subclass (_HarnessPanel) re-exposing a relocated module API's old method/attribute names as thin pass-throughs — keeps node IDs byte-identical across a constructor relocation"
    - "Harness-only module attribute seeding (panel.dispatch_spec) so existing raising=True monkeypatches keep biting after the production symbol moved"
    - "Per-tap render-location cell shared between the dispatch closure and the render bridge (single-writer on the gateway loop) to thread argless-ness the frozen module API cannot express"

key-files:
  created: []
  modified:
    - tests/test_panel.py
    - tests/test_bot.py
    - tests/test_scheduler.py
    - weatherbot/scheduler/wiring.py

key-decisions:
  - "_make_panel assembles the REAL module PanelKit (mirrors wiring.build_inbound_bot) and wraps it in a _HarnessPanel subclass that adapts the old PanelView API names — every existing assertion byte-identical, signature unchanged so the ~14 call sites + 2 downstream importers need no edit"
  - "Argless 📍 suppression fixed in production (wiring.build_inbound_bot) via a per-tap render-location cell, NOT a test-only patch — the relocation regressed the v1 contract (the module passes the live selection to render unconditionally)"
  - "test_bot.py gateway/BotThread tests construct the module API directly (build_client(on_message=, view=) / BotThread(token, *, client=)); the 10 !panel summon tests inject the real app summon closure via bot.build_panel_summon threaded into build_on_message(on_panel_summon=)"
  - "test_scheduler daemon-lifecycle patches repointed from interactive_mod.BotThread to wiring_mod.build_inbound_bot (daemon now constructs via the composition root); the fakes' ctors already match build_inbound_bot's signature"
  - "Forbidden-backstop CRITICAL patch moved to the module gateway logger (the log relocated into summon_panel)"

requirements-completed: [SEAM-07]

# Metrics
duration: 38min
completed: 2026-06-29
status: complete
---

# Phase 27 Plan 04: Byte-Identical Panel Oracle Harness Rewire Summary

**Rewired the full relocated-API test harness onto the `yahir_reusable_bot.discord` adapter — `tests/test_panel.py::_make_panel` now assembles the module `PanelKit` (via the app contributors + injected render/marker/selection/dispatch) wrapped in a `_HarnessPanel` adapter subclass that re-exposes the pre-relocation API byte-identically; the relocated `build_client`/`BotThread`/`!panel`-summon tests in `test_bot.py` and the bot-construction/panel-wedge patch targets in `test_scheduler.py` were repointed to the module/composition-root; and the relocation-regressed argless panel 📍 suppression was fixed in production. Full suite: 778 passed (exit 0), zero `.ambr`/custom_id-byte re-baseline.**

## Performance
- **Duration:** ~38 min
- **Started:** 2026-06-29 (post 27-02)
- **Tasks:** 1 planned (Task 1) + the expanded harness realignment (test_bot.py + test_scheduler.py), per the phase_note
- **Files modified:** 4

## Accomplishments
- **`tests/test_panel.py` (34 node IDs) green byte-identically.** `_make_panel` assembles the real module `PanelKit` exactly as `wiring.build_inbound_bot` does (app contributors, `_render_bridge`, the per-tap dispatch closure decoding the forecast key + routing through the shared `dispatch_spec` seam, `marker=PANEL_MARKER`, the curated command set, the generic `SelectedContext`). A `_HarnessPanel(PanelKit)` subclass re-exposes the old `PanelView` API names (`on_select` / `on_forecast` / `_selected_location` / `_render_view` / the 2-arg `_assert_layout_children` / `_LABELS`) as thin adapters over the relocated module shape — adding no behavior, so every assertion stays byte-identical. The signature is unchanged.
- **The 2 downstream importers collect + pass byte-identically.** `tests/test_golden_custom_ids.py` + `tests/test_oracle_selfproof.py` (`from tests.test_panel import _FakeHolder, _SpyCache, _make_panel`) needed NO edit — `_make_panel(...).children[0].custom_id == "wb:loc:select"` still holds and the full ordered `custom_id` byte golden is zero-diff (no `.ambr` re-baseline).
- **`tests/test_bot.py` (17 relocated) green.** `build_client`/`setup_hook`/`on_ready` drive the module `build_client(on_message=, view=)` with a real module `PanelKit`; the `BotThread` failure-isolation/lifecycle tests construct `BotThread(token, *, client=)` directly with the gateway-free fake (no `build_client` patch — the client is injected); the 10 `!panel` summon tests inject the real `bot.build_panel_summon(...)` closure via `build_on_message(on_panel_summon=)`; the Forbidden-backstop CRITICAL patch moved to the module gateway logger.
- **`tests/test_scheduler.py` (3 relocated) green.** The 4 daemon-lifecycle bot tests repoint from `interactive_mod.BotThread` to `wiring_mod.build_inbound_bot` (daemon now constructs via the composition root); the hanging-callback wedge builds the module `PanelKit` via the shared `_make_panel` harness and hangs the `on_command` fetch by monkeypatching `panel.dispatch_spec`.
- **Argless 📍 suppression fixed in production (Rule 1 bug).** `wiring.build_inbound_bot` now records a per-tap render-location (`None` for argless) in a one-slot cell the render bridge reads — restoring the v1 contract the relocation regressed (`test_argless_result_suppresses_indicator`).
- **Verify gate met.** `uv run pytest -q` → **778 passed, exit 0**, zero golden/`.ambr`/custom_id-byte file changes (the printed "2 snapshots failed" is the documented syrupy oracle-self-proof perturbation quirk — exit 0 + no `.ambr` diff confirm it). `test_import_hygiene.py` 9/9.

## Task Commits
1. **Rewire _make_panel harness onto module PanelKit; fix argless panel 📍 suppression** — `84228c4` (test)
2. **Rewire test_bot.py gateway + !panel summon tests onto the module adapter** — `6ad484c` (test)
3. **Repoint test_scheduler bot/panel patch targets to the relocated module** — `6aa5a26` (test)

## Files Created/Modified
- `tests/test_panel.py` (modified) — `_panel()` seeds the harness-only `panel.dispatch_spec`; `_make_panel` → `_HarnessPanel` factory + `_make_panel_kit` (the module `PanelKit` assembly) + `_harness_panel_class` (the adapter subclass) + `_RegistryView`; the marker/ownership tests rewired onto `panel.PANEL_MARKER` + the module `is_owned_panel(marker=)` predicate; the L212 hot-reload re-construct routes through `_make_panel`; `_LABELS` → `PANEL_LABELS`.
- `tests/test_bot.py` (modified) — `_noop_on_message` / `_SpyForecastCache` / `_module_panel_view` / `_panel_summon_on_message` helpers; the gateway/BotThread/summon tests rewired onto the module adapter.
- `tests/test_scheduler.py` (modified) — daemon bot-construction patches repointed to `wiring_mod.build_inbound_bot`; the panel wedge built via `_make_panel`.
- `weatherbot/scheduler/wiring.py` (modified) — per-tap `render_location` cell in `build_inbound_bot`; `_dispatch` records it (`None` argless / `selection.value` location-bearing+forecast); `_render_bridge` reads it back.

## Deviations from Plan

### Expanded scope — owned the COMPLETE harness realignment (tracked, per phase_note)
- **Found during:** plan execution (the phase_note pre-authorized this expansion).
- **What:** the plan's `files_modified` named ONLY `tests/test_panel.py`, but Wave 2 (27-02) relocated more app-side API than that one file covers. I added `tests/test_bot.py` (17 relocated gateway/summon tests) and `tests/test_scheduler.py` (3 relocated bot-construction/wedge tests) to the realignment so the full suite reaches 0 failures (the verify gate).
- **Why:** the named-scope `_make_panel` rewire alone leaves 23 failures in 2 other files bound to the SAME relocated symbols (`build_client`/`BotThread`/the `!panel` summon/`panel.PanelView`); the phase_note explicitly directs owning all five files. Every added edit keeps assertions byte-identical (rewires constructors/patch-targets to the new module locations, never weakens an assertion).
- **Files added beyond the plan:** `tests/test_bot.py`, `tests/test_scheduler.py`.

### Auto-fixed Issues

**1. [Rule 1 - Bug] Argless panel result no longer suppresses the 📍 indicator**
- **Found during:** Task 1 (`test_argless_result_suppresses_indicator`).
- **Issue:** the Phase-27 relocation moved the panel render-cycle into the module `PanelKit.on_command`, which passes `self._selection` to the injected `render` UNCONDITIONALLY. The v1 contract suppressed the 📍 indicator on argless replies (status/alerts) via `arg = _selected_location if spec.takes_location else None`; the relocated `_render_bridge` forwarded `ctx.value` (always a location), so a panel `status`/`alerts` tap would show a spurious 📍. This was the deferred reconciliation flagged in 27-02-SUMMARY / `deferred-items.md`.
- **Fix:** added a per-tap `render_location` cell to `wiring.build_inbound_bot` (single-writer on the gateway loop, the `SelectedContext` concurrency contract). `_dispatch` records the location that should render (`None` for argless, the selected location for location-bearing + forecast); `_render_bridge` reads it back into `render_embed(location=)`. Mirrored in the harness dispatch closure. `render_embed` itself is untouched.
- **Files modified:** `weatherbot/scheduler/wiring.py`, `tests/test_panel.py`.
- **Commit:** `84228c4`.

## Issues Encountered
- **`raising=True` dispatch-spy monkeypatches need a real attribute.** Three node IDs + the scheduler wedge do `monkeypatch.setattr(panel, "dispatch_spec", …, raising=True)`, but the relocation removed `panel.py`'s dispatch coupling. Resolved by seeding a harness-only `panel.dispatch_spec` attribute in `_panel()` (defaulting to the real shared seam, never committed to source) that the harness dispatch closure reads off the module object at call time — so the spies bite without re-adding production coupling.
- **`_assert_layout_children` signature drift.** The v1 guard took `(children, locations)`; the relocated module guard takes only `(children)`. The harness adapter drops the now-unused `locations` arg so the existing 2-arg call sites (`test_layout_overflow_trips_assert`) stay byte-identical.

## Known Stubs
None — the harness assembles the real module `PanelKit` with live contributors/render/dispatch; no hardcoded empty/placeholder data flows to an assertion.

## Threat Flags
None — test-harness + a single composition-root render-suppression fix; no new network endpoint, auth path, or trust boundary. T-27-12 (silent golden re-baseline) and T-27-13 (importer collection failure) are both held: zero `.ambr`/custom_id-byte diff, and the two downstream importers collect + pass with `_make_panel`'s signature unchanged.

## Self-Check: PASSED
- Modified files present: FOUND `tests/test_panel.py`, `tests/test_bot.py`, `tests/test_scheduler.py`, `weatherbot/scheduler/wiring.py`.
- Commits: all 3 FOUND (`84228c4`, `6ad484c`, `6aa5a26`).
- Gates: full suite `uv run pytest -q` → 778 passed, exit 0; zero `.ambr`/snapshot/fixture file changes (`git status` clean of snapshot diffs); `test_import_hygiene.py` 9/9; `grep -nE 'panel\.PanelView|\.PanelView\(' tests/test_panel.py` → none; `grep -c 'PanelKit' tests/test_panel.py` ≥ 1.

---
*Phase: 27-discord-adapter-panelkit-render-cycle-fix*
*Completed: 2026-06-29*
