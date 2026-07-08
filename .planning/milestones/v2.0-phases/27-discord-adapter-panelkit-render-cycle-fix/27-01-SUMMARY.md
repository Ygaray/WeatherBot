---
phase: 27-discord-adapter-panelkit-render-cycle-fix
plan: 01
subsystem: infra
tags: [discord.py, persistent-view, generic-typevar, dependency-injection, adapter, uv-lock]

# Dependency graph
requires:
  - phase: 26-command-registry-dispatcher-seam
    provides: "CommandRegistry / build_registry / match_command — the registry PanelKit builds its command buttons from"
  - phase: 24-config-hot-reload-engine
    provides: "ConfigHolder(Generic[T]) — the unbound-TypeVar/no-base-class precedent SelectedContext[I] clones"
  - phase: 25-lifecycle-ready-gate-composition-root
    provides: "build_runtime composition root + the positive-injection assertion pattern the adapter wiring extends (Wave 2)"
provides:
  - "yahir_reusable_bot/discord/ — the reusable Discord adapter package (generic, app-domain-free)"
  - "SelectedContext[I] — generic selected-item holder (unbound TypeVar, no base class, no lock)"
  - "PanelKit(discord.ui.View) — persistent-view machinery; marker/render/contributors injected; clone path re-invokes contributors"
  - "BotThread + build_client + summon_panel — gateway thread+loop + persistent-view registration + create-before-delete summon, all generic"
  - "discord.py==2.7.1 exact pin (adapter-owned, D-05); uv.lock regenerated"
affects: [27-02-app-rewire, 28-physical-repo-split]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Constructor-injection of opaque callables for a discord.ui.View (PanelKit clones the CommandRegistry/SchedulerEngine idiom)"
    - "Contributor-callables as clone factories — re-invoked on every render to dodge the live-routing trap without isinstance on app types"
    - "Generic Generic[I] holder cloned from ConfigHolder(Generic[T]) for selection state"
    - "Generic DispatchOutcome (reply | error_message) as the neutral on_command dispatch result"

key-files:
  created:
    - yahir_reusable_bot/discord/__init__.py
    - yahir_reusable_bot/discord/selection.py
    - yahir_reusable_bot/discord/panelkit.py
    - yahir_reusable_bot/discord/gateway.py
  modified:
    - pyproject.toml
    - uv.lock

key-decisions:
  - "render/contributors/marker are REQUIRED no-default PanelKit params (positive injection assertion); module bakes no marker literal"
  - "Clone path re-invokes contributors + rebuilds command buttons (Pattern 1a) — never isinstance-checks an app component class"
  - "on_command dispatches via an injected async dispatch -> generic DispatchOutcome; the UnknownLocation-style error path is the error_message branch"
  - "SelectedContext[I] is a lock-free single-writer holder (no threading.Lock) — selection is mutated only on the gateway loop"
  - "REQUIRED_PANEL_PERMS relocated to the module (names Discord perms, not an app concept — A4); operator copy stays app-side (Wave 2)"
  - "discord.py exact-pinned ==2.7.1 in the single shared pyproject (A5); moves to the module's own pyproject at the Phase-28 split"

patterns-established:
  - "Adapter package layout: yahir_reusable_bot/discord/{selection,panelkit,gateway}.py + barrel __init__ (mirrors registry/)"
  - "Litmus discipline includes substring traps — 'relocation' contains 'location'; reworded to keep the grep clean"

requirements-completed: [SEAM-07]

# Metrics
duration: 9min
completed: 2026-06-29
status: complete
---

# Phase 27 Plan 01: Discord Adapter + PanelKit Module Side Summary

**Created the generic `yahir_reusable_bot/discord/` adapter — `SelectedContext[I]`, `PanelKit` (marker/render/contributors injected, contributor-re-invoking clone path), and `BotThread`/`build_client`/`summon_panel` — all weather-free and importing zero app code, with `discord.py` exact-pinned `==2.7.1`.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-06-29T14:29:35Z
- **Completed:** 2026-06-29T14:39:00Z
- **Tasks:** 3
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments
- New `yahir_reusable_bot/discord/` package: the reusable Discord adapter layer one level up from the channel-agnostic core, litmus-clean across every file (no `weather|forecast|location|openweather|\buv\b|briefing`, zero `wb:` literal).
- `SelectedContext(Generic[I])` clones the `ConfigHolder` unbound-TypeVar/no-base-class precedent (D-02); a lock-free single-writer holder replacing the panel's hardcoded in-memory selection.
- `PanelKit(discord.ui.View)` relocates the persistent-view machinery verbatim in behavior with `marker`/`render`/`contributors` parameterized OUT as REQUIRED no-default constructor params; the clone path (`_build_clone_view`) re-invokes contributors + rebuilds command buttons (no `isinstance` on app classes), applying `disabled` post-construction.
- `gateway.py` relocates `BotThread` (own thread+loop, start-waits-on-loop, cross-thread stop, LoginFailure/crash isolation), `build_client` (intents + on_ready assertion + `setup_hook` `add_view` of the INJECTED view — the deferred `PanelView` import eliminated by construction, SC#2), and the generic `summon_panel` create-before-delete orchestration.
- `discord.py>=2.7.1,<3` tightened to exact `==2.7.1` (D-05) with an adapter-ownership comment; `uv.lock` regenerated, discord-py resolves to 2.7.1.
- Full suite green at the boundary: **778 passed (exit 0)**, zero `.ambr` golden diffs (BHV-01/BHV-02); grimp import gate + litmus + positive-injection stubs all pass (PKG-01/APP-02).

## Task Commits

Each task was committed atomically:

1. **Task 1: Package skeleton + generic SelectedContext[I]** - `286b544` (feat)
2. **Task 2: Relocate PanelKit, marker/render/contributors injected** - `ec3c79a` (feat)
3. **Task 3: Relocate BotThread + build_client + summon; pin discord.py==2.7.1** - `2515d0b` (feat)

## Files Created/Modified
- `yahir_reusable_bot/discord/selection.py` (created) - `SelectedContext(Generic[I])`, unbound module-level `TypeVar I`, lock-free `value`/`set` holder.
- `yahir_reusable_bot/discord/panelkit.py` (created) - `PanelKit`, `CmdButton`, `ItemContributor`, `DispatchOutcome`, module-level `is_owned_panel(marker=...)`; the operator gate, per-callback envelope, `View.on_error`, `_safe_error_edit`, cap guards, and the contributor-re-invoking clone path.
- `yahir_reusable_bot/discord/gateway.py` (created) - `BotThread`, `build_client`, `summon_panel`, `REQUIRED_PANEL_PERMS`.
- `yahir_reusable_bot/discord/__init__.py` (created) - barrel re-exporting `BotThread`, `build_client`, `PanelKit`, `SelectedContext`.
- `pyproject.toml` (modified) - `discord.py` pin tightened `>=2.7.1,<3` → `==2.7.1` (adapter-owned, D-05).
- `uv.lock` (modified) - regenerated; discord-py constrained to exactly 2.7.1.

## Decisions Made
- **PanelKit dispatch seam (planner discretion resolved).** To keep `on_command` generic while the original called `dispatch_spec`/`cache`/`takes_location`/`UnknownLocationError` (all weather/app concerns), `on_command` awaits an injected async `dispatch(name, selection) -> DispatchOutcome`. `DispatchOutcome.reply` (success → fed to the injected `render`) vs `DispatchOutcome.error_message` (the in-place no-embed error edit, mirroring the v1 `UnknownLocationError` branch) is the neutral seam; the app closure (Wave 2) owns the per-tap `holder.current()` read, the off-loop fetch, arg adaptation, and the domain-error catch. This keeps `render` a separate required param as the plan mandates.
- **Method/symbol naming under the symbol-litmus.** `test_injection_registry._module_public_symbols()` scans EVERY `def`/`class` name (incl. private) under the module for `location`/`render` substrings (only `render_help` allowed). The clone-path method is therefore named `_build_clone_view` (not `_render_view`), and no method/class carries a `location`/`render` name.
- **Ownership predicate exposed both as a free function and a method.** `is_owned_panel(msg, bot_user, *, marker)` is the single implementation; `PanelKit.is_owned_panel` binds `self._marker`, and `summon_panel` takes a pre-bound `is_owned` predicate — so the summon scan and the panel share one marker-bound test.

## Deviations from Plan

None - plan executed exactly as written. (The dispatch-seam shape and method names above are planner-discretion details the plan explicitly delegated, not deviations: the plan named `render`/`contributors`/`marker` as required params, the contributor-re-invoking clone path, the per-tap holder reads threaded through an injected accessor, and `REQUIRED_PANEL_PERMS` relocation — all implemented as specified.)

## Issues Encountered
- **Litmus substring traps.** The litmus grep is a plain substring match, so docstring words like "relocation" (contains `location`) and "weather-noun-free" (contains `weather`) tripped it. Reworded to "the reusable-module home of…" / "domain-agnostic" and scrubbed the barrel docstring; the whole `discord/` tree is now litmus-clean. Caught at the per-task verify gate before commit.
- **Incremental barrel import.** The Task-1 `__init__.py` initially re-exported all four names, which `ModuleNotFoundError`'d because `gateway`/`panelkit` didn't exist yet. Fixed by growing the barrel incrementally (per the plan: Task 1 re-exports only `SelectedContext`, the others land in Tasks 2-3).

## User Setup Required
None - no external service configuration required. (This is the module side only; the app does not yet import the adapter — that is Plan 27-02.)

## Next Phase Readiness
- The module adapter surface is complete, generic, litmus-clean, and import-isolated (grimp green, zero `weatherbot.*` edge). Ready for Plan 27-02 (the app rewire): `weatherbot/interactive/panel.py` shrinks to the cosmetic contributors (`LocationSelect`/`ForecastButton`/`wb:` literals/📍), `render_embed` stays app-side and is injected as `render`, and `wiring.py build_runtime` constructs the module `BotThread`/`PanelKit` with `render`/contributors/`marker="wb:"`/`operator_id` injected.
- Wave-2 must wire the injected `dispatch` closure (per-tap `holder.current()` + `dispatch_spec` + cache + `takes_location` arg adaptation + `UnknownLocationError` → `DispatchOutcome.error_message`) and re-thread `SelectedContext[str]` so the byte-frozen `custom_id`/embed goldens stay zero-diff.
- The live `yahir-mint` `systemctl restart` re-bind UAT remains the Phase-28 deferred obligation (Gate 2); this plan's oracle was the green golden byte-snapshot.

## Self-Check: PASSED
- Created files: all 4 FOUND (`selection.py`, `panelkit.py`, `gateway.py`, `__init__.py`).
- Commits: all 3 FOUND (`286b544`, `ec3c79a`, `2515d0b`).
- Gates: full suite 778 passed (exit 0); litmus-clean; zero `wb:` literals; `discord.py==2.7.1` pinned; uv.lock resolves 2.7.1.

---
*Phase: 27-discord-adapter-panelkit-render-cycle-fix*
*Completed: 2026-06-29*
