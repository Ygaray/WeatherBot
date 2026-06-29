---
phase: 27-discord-adapter-panelkit-render-cycle-fix
plan: 02
subsystem: interactive
tags: [discord.py, adapter-rewire, dependency-injection, render-bridge, import-cycle, composition-root]

# Dependency graph
requires:
  - phase: 27-discord-adapter-panelkit-render-cycle-fix
    provides: "yahir_reusable_bot/discord/ — the module adapter (PanelKit/BotThread/build_client/SelectedContext/summon_panel) this plan wires the app onto (Plan 27-01)"
  - phase: 26-command-registry-dispatcher-seam
    provides: "registry.BY_NAME / dispatch_spec — the per-tap dispatch closure resolves specs + binds args through these"
  - phase: 25-lifecycle-ready-gate-composition-root
    provides: "build_runtime composition root + the start-after-READY ordering the new build_inbound_bot construction preserves"
provides:
  - "weatherbot/interactive/bot.py — render_embed STAYS app-side (the injected render); BotThread/build_client/_handle_panel_summon DELETED; build_panel_summon (the thin app summon) ADDED"
  - "weatherbot/interactive/panel.py — shrunk to app cosmetic contributors (LocationSelect/ForecastButton + wb: literals + build_contributors); PanelView machinery gone"
  - "weatherbot/scheduler/wiring.py build_inbound_bot — the single greppable injection site wiring render=_render_bridge / contributors / marker / operator_id / dispatch into the module PanelKit + BotThread"
affects: [27-03-injection-oracle, 27-04-harness-rewire, 28-physical-repo-split]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "App-side render-bridge closure adapting ctx -> render_embed(location=) (resolves the render(reply,ctx) signature mismatch without editing render_embed)"
    - "App dispatch closure owning the per-tap holder.current() read + takes_location arg adaptation + forecast-variant decode + UnknownLocationError->error_message"
    - "Per-PanelKit late-binding cell (panel_ref) so app contributor components resolve their owning PanelKit lazily in callbacks"
    - "App-encoded '<name>|<variant>' dispatch key carrying the forecast-grid variant through the module's single command dispatch"
    - "Re-export-shim: interactive/__init__ re-exports BotThread/build_client from the module (Phase-22 pattern)"

key-files:
  created: []
  modified:
    - weatherbot/interactive/bot.py
    - weatherbot/interactive/panel.py
    - weatherbot/interactive/__init__.py
    - weatherbot/scheduler/wiring.py
    - weatherbot/scheduler/daemon.py

key-decisions:
  - "render_embed signature kept UNCHANGED (render_embed(reply, *, location=None)); the module<->render mismatch is bridged by the app _render_bridge closure at the composition root, never by editing render_embed"
  - "The forecast-grid variant (detailed/compact) is carried through the module's single on_command dispatch via an app-encoded '<name>|<variant>' key the app dispatch closure decodes (the module on_command passes only a name)"
  - "Each PanelKit built by the factory gets its OWN late-binding panel_ref cell so a !panel re-summon's fresh panel never re-points the registered panel's component handlers"
  - "interactive/__init__ re-exports BotThread/build_client from yahir_reusable_bot.discord (re-export shim) so the daemon's `from weatherbot.interactive import BotThread` keeps resolving; render_embed stays app-side"
  - "REQUIRED_PANEL_PERMS consumed from the module (relocated there in 27-01); the operator-feedback COPY strings stay app-side in bot.py"

requirements-completed: [SEAM-07]

# Metrics
duration: 13min
completed: 2026-06-29
status: complete
---

# Phase 27 Plan 02: Discord Adapter App-Rewire (Render-Cycle Fix by Ownership) Summary

**Rewired WeatherBot onto the relocated `yahir_reusable_bot.discord` adapter: `render_embed` stays app-side (injected as the module `PanelKit`'s `render` via the `_render_bridge` closure), `panel.py` shrank to its cosmetic contributors, `BotThread`/`build_client`/the summon machinery were deleted from `bot.py`, and the single composition root `build_inbound_bot` injects render/contributors/marker/operator_id/dispatch — resolving the `render_embed`↔`PanelView` import cycle by ownership (both edges gone, SC#2).**

## Performance
- **Duration:** 13 min
- **Started:** 2026-06-29T14:44:53Z
- **Completed:** 2026-06-29T14:58:10Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- **SC#2 — cycle resolved by ownership.** `panel.py` no longer imports `render_embed` from `bot.py` (forward edge gone) and `bot.py` no longer imports `PanelView` (both deferred back edges gone). `uv run weatherbot --help` exits 0 with no circular-import error; `tests/test_import_hygiene.py` (grimp + litmus + isolated-import + the core↔adapter isolation) passes 9/9.
- **render_embed unchanged + bridged.** `render_embed(reply, *, location=None)` keeps its EXACT signature and body — the embed goldens (`test_golden_embeds.py`, 11/11) and the 📍 on/off indicator tests (`test_render_embed_indicator_line` / `_indicator_suppressed_when_argless`) are byte-identical. The module↔render mismatch is bridged by the app `_render_bridge(reply, ctx) -> render_embed(reply, location=(ctx.value if ctx is not None else None))` closure at the composition root, not by editing `render_embed`.
- **panel.py shrunk to contributors.** Removed `PanelView` + `_is_owned_panel` + `_render_view`/`_clone_child` + `CmdButton` (all relocated to the module `PanelKit`). Kept `LocationSelect` (`wb:loc:select`) + the four `ForecastButton`s (`wb:fc:…`) + the emoji/label tables; added `build_contributors` (module `ItemContributor`-shaped clone factories), the forecast dispatch-key codec, and `build_forecast_flags`. The assembled child order through the real `PanelKit` is byte-identical (Select row 0 → `wb:cmd:*` rows 1-2 → `wb:fc:*` rows 3-4) — verified by a construction smoke test.
- **Single greppable injection site.** `wiring.build_inbound_bot` constructs the module `BotThread` + `PanelKit`, injecting `render=_render_bridge`, `contributors=panel.build_contributors(...)`, `marker=PANEL_MARKER` (`"wb:"`), `operator_id` (baked at construction — v1 preserved), `selection=SelectedContext[str]`, and the per-tap `dispatch` closure. `daemon.py` calls it strictly after the READY signal (D-11 ordering preserved) and stops it in the `finally`.

## Task Commits
1. **Task 1: Keep render_embed app-side; delete gateway machinery from bot.py (D-01/D-06)** — `52ddee6` (feat)
2. **Task 2: Shrink panel.py to app cosmetic contributors; drop the render_embed top import (D-03/D-04)** — `5f258da` (feat)
3. **Task 3: Wire the module BotThread + PanelKit at the composition root (D-01/D-04/D-06)** — `7e983fe` (feat)

## Files Created/Modified
- `weatherbot/interactive/bot.py` (modified) — `render_embed` (unchanged) + `build_inbound_embed` + `build_on_message` (now takes an injected `on_panel_summon`) + the new `build_panel_summon` thin app summon (delegates to the module `summon_panel`); `BotThread`/`build_client`/`_handle_panel_summon`/`_REQUIRED_PANEL_PERMS` and both deferred `PanelView` imports DELETED.
- `weatherbot/interactive/panel.py` (modified) — shrunk to `LocationSelect`/`ForecastButton` + the `wb:` literals + `PANEL_MARKER`/`PANEL_COMMAND_NAMES`/`PANEL_LABELS`/`PANEL_EMOJI`/`PANEL_COMMAND_ROWS` + `build_contributors` + the forecast dispatch-key codec; the `render_embed` top import + the `PanelView` machinery removed.
- `weatherbot/interactive/__init__.py` (modified) — re-exports `BotThread`/`build_client` from `yahir_reusable_bot.discord` (re-export shim); `render_embed` still from `.bot`.
- `weatherbot/scheduler/wiring.py` (modified) — added `build_inbound_bot` (the injection site) + `_RegistryView` (adapts `BY_NAME` to the module's `registry.by_name` read); the `_render_bridge` + `_dispatch` closures live here.
- `weatherbot/scheduler/daemon.py` (modified) — constructs the bot via `build_inbound_bot` (after READY), preserving the start/stop ordering.

## Decisions Made
- **render_embed signature is load-bearing for the test callers — keep it, bridge the mismatch.** `test_bot.py` + `test_golden_embeds.py` call `render_embed(reply, location=...)` directly and monkeypatch `bot.render_embed`; changing the signature to `render(reply, ctx)` would break them. The `_render_bridge` closure (composition root) adapts `ctx -> location=` so `render_embed` itself is untouched (Task-1 acceptance, RESEARCH Pattern 2).
- **Forecast variant carried via an app-encoded dispatch key.** The module `PanelKit.on_command(interaction, name)` passes only `name` to the injected `dispatch`. The two weekday buttons share one registry command (`weekday-forecast`) but differ by variant, so the app `ForecastButton.callback` calls `on_command(interaction, "weekday-forecast|detailed")` and the app `_dispatch` closure decodes the `"<name>|<variant>"` key into a DIRECT `ForecastFlags` (Security V5 — no user text reaches the parser). This keeps the frozen module API untouched.
- **Per-PanelKit late-binding cell.** App contributor components need the owning `PanelKit` (for the module clone path on select), but contributors run DURING `PanelKit.__init__`. Each `_build_panelkit()` call owns its own `panel_ref` cell filled immediately after construction; components dereference it lazily via a zero-arg getter only in their callbacks. A fresh `!panel` re-summon therefore never re-points a previously-registered panel's handlers.

## Deviations from Plan

### Sequencing reality — relocated-machinery test harnesses fail (deferred to 27-04 + 27-03)
- **Found during:** Task 1 / Task 3 verify gates.
- **What:** `tests/test_bot.py` (17) and `tests/test_scheduler.py` (3) fail, in addition to the `tests/test_panel.py` (34) + `tests/test_golden_custom_ids.py` (2) + `tests/test_oracle_selfproof.py` (1) the plan's phase_note explicitly defers. All 57 failures are in 5 files and are HARNESS tests bound to the OLD app-side API (`bot.build_client`/`bot.BotThread`/the old `!panel` summon; `_make_panel` constructing `panel.PanelView`; `test_scheduler.py` patching the now-rerouted `interactive.BotThread` lazy import). 721 tests pass; NO non-harness file regresses.
- **Why it's not a regression:** the plan's `<verify>` gates for Tasks 1-3 are scoped to `test_bot.py`+`test_golden_embeds.py` (Task 1), grep+ast (Task 2), and `test_bot.py`+`test_golden_embeds.py`+`test_import_hygiene.py`+CLI (Task 3) — and the named subset that MUST pass (render_embed signature + both indicator tests + the monkeypatch sites + embed goldens + import-hygiene + CLI) all pass. The relocated `build_client`/`BotThread`/summon harness tests are the SAME class as `_make_panel`: bound to symbols that moved to the module, owned by the dedicated 27-04 harness rewire (which runs before 27-03's byte-identical oracle re-run). The daemon's runtime bot behavior (construct via `build_inbound_bot` → start-after-READY → `finally` stop) is unchanged; the 3 `test_scheduler.py` failures are pure mock-injection-point drift (they patch `interactive.BotThread`; the daemon now constructs via `wiring.build_inbound_bot`).
- **Tracked in:** `deferred-items.md` (this phase dir), with the per-file failure counts + the exact harness-rewire each needs in 27-04/27-03.

### Argless 📍 suppression through the panel path — reconcile in 27-04
- The `_render_bridge` is implemented EXACTLY per the acceptance criteria (`location=ctx.value`). Because the frozen module `PanelKit.on_command` passes `self._selection` to `render`, a panel argless tap (status/alerts) would forward the selected location into `location=`. The `_dispatch` closure already computes the correct `arg` (`None` for argless); the panel-path nulling reconciliation lands with the 27-04 harness rewire + the 27-03 oracle (`test_panel.py::test_argless_result_suppresses_indicator`). The Task-1 embed goldens (direct `render_embed(..., location=...)` callers) are byte-identical and pass — `render_embed`'s own suppression branch is untouched. Tracked in `deferred-items.md`.

## Issues Encountered
- **Contributor late-binding IndexError.** The first contributor draft dereferenced `panel_ref[0]` at build time, but contributors run during `PanelKit.__init__` (before the cell is filled) → `IndexError`. Fixed by passing the components a zero-arg `panel_getter` lambda dereferenced only inside callbacks (the late-binding cell). Caught by a construction smoke test before the Task-3 commit.
- **`__init__.py` re-export.** `weatherbot/interactive/__init__.py` re-exported `BotThread`/`build_client` from `.bot`; after deleting them from `bot.py` the barrel `ImportError`'d. Re-pointed to `from yahir_reusable_bot.discord import BotThread, build_client` (the Phase-22 re-export-shim pattern) — committed with Task 1 since the deletions require it.

## User Setup Required
None — no external service configuration. (Internal package-boundary rewire; the editable install on `yahir-mint` needs no reinstall. The live `systemctl restart` re-bind UAT is the Phase-28 deferred Gate-2 obligation.)

## Next Phase Readiness
- The app is rewired onto the module adapter; the cycle is resolved by ownership (both edges gone), the CLI loads, and the import-hygiene/grimp/litmus gates pass. Ready for **Plan 27-04** (the harness rewire): re-point `tests/test_panel.py::_make_panel` + the `test_bot.py` gateway/summon tests + the 3 `test_scheduler.py` bot-construction tests onto the module `PanelKit`/`BotThread` + `wiring.build_inbound_bot`, and reconcile the panel argless 📍 suppression. Then **Plan 27-03** re-runs the full byte-identical oracle (`test_golden_custom_ids.py`, `test_oracle_selfproof.py`, `test_injection_registry.py`) + the positive injection assertion.
- The byte-frozen `custom_id` child order is preserved through the real `PanelKit` (smoke-verified); the goldens that pin it will re-run green once 27-04 rewires `_make_panel`.

## Known Stubs
None — no hardcoded empty/placeholder data flows to a rendered surface. `render_embed`, the dispatch closure, and the contributors are fully wired to live config/registry/cache.

## Threat Flags
None — no new network endpoint, auth path, or trust-boundary surface introduced beyond the plan's `<threat_model>` (T-27-06/07/08 mitigations honored: render/contributors/marker injected only at `build_inbound_bot`; only `operator_id`/`panel_channel_id`/marker/opaque callables cross into the module; the token/appid are never threaded into PanelKit).

## Self-Check: PASSED
- Created files: FOUND `27-02-SUMMARY.md`, FOUND `deferred-items.md`.
- Modified files present: FOUND `weatherbot/scheduler/wiring.py` (+ bot.py/panel.py/__init__.py/daemon.py committed).
- Commits: all 3 FOUND (`52ddee6`, `5f258da`, `7e983fe`).
- Gates: `test_golden_embeds.py` 11/11; `test_import_hygiene.py` 9/9; `weatherbot --help` exit 0 (no cycle); both 📍 indicator tests green; SC#2 — both cycle edges gone. Deferred harness failures (57 across 5 files) documented in `deferred-items.md`, owned by 27-04 + 27-03.
