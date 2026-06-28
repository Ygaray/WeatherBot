---
phase: 26-command-registry-dispatcher-seam
plan: 02
subsystem: interactive
tags: [command-registry, dispatcher, re-export-singleton, opaque-bind, neutral-signal, byte-identical-oracle, app-rewire]

# Dependency graph
requires:
  - phase: 26-command-registry-dispatcher-seam
    plan: 01
    provides: the generic yahir_reusable_bot/registry package (CommandSpec 5-field generic, build_registry/CommandRegistry, match_command, the dispatcher shell with spec.bind + needs_flags + injected parse_flags/cache_suffix hooks, render_help dual signature)
  - phase: 25-lifecycle-ready-gate-composition-root
    provides: the D-05 positive injection-registry assertion pattern this plan extends to commands
provides:
  - "weatherbot/interactive/registry.py rewired as a THIN re-exporting singleton — builds via module build_registry(_wire_handlers(_SPECS)), re-exports COMMANDS/BY_NAME/COMMANDS_BY_KEYWORD_LEN_DESC/render_help + CommandSpec byte-for-byte (D-03)"
  - "weatherbot/interactive/dispatch.py rewired as thin shims over the module dispatcher (forecast hooks injected; module reads neutral needs_flags, not group==Forecast)"
  - "weatherbot/interactive/command.py parse_command delegates to module match_command (D-04); forecast grammar stays app-side"
  - "Positive command-injection assertion (build_registry REQUIRES specs + module bakes no weather command name) with a biting self-proof"
  - "Litmus coverage-gap assertion now names the registry package files (spec/registry/match/dispatch)"
affects: [27-panelkit-discord-adapter, 28-physical-repo-split]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-mechanism + app-side thin re-export keeps the byte-identical oracle untouched (D-03 realized): the app owns the command SET, the module owns the registry/dispatch mechanism"
    - "Per-command bind closure encodes the ARG-SHAPE; the handler identity is resolved LIVE from BY_NAME[name].handler at call time so replace(spec, handler=stub) test patches are honored uniformly"
    - "Thin app dispatch shim delegates to the module dispatcher with app forecast hooks (parse_flags/cache_suffix) injected — the module names no weather group"

key-files:
  created: []
  modified:
    - weatherbot/interactive/registry.py
    - weatherbot/interactive/dispatch.py
    - weatherbot/interactive/command.py
    - tests/test_dispatch.py
    - tests/test_import_hygiene.py
    - tests/test_injection_registry.py

key-decisions:
  - "bind closures authored in registry._wire_handlers (import-time), NOT wiring.py build_runtime — the CLI/panel/bot resolve specs from the import-time global registry (cli.py reads registry.BY_NAME[name] and never calls build_runtime), so a build_runtime-authored bind would be invisible to those surfaces. D-01's substance (verbatim arm lift, live per-tap ctx config reads) is preserved; only the authoring SITE diverged. wiring.py needed no change."
  - "bind closures resolve the handler LIVE via BY_NAME[name].handler (not captured) so the established test-patch idiom (replace(spec, handler=stub) + setitem(BY_NAME)) keeps working without touching the bot/panel/cli consumer tests — lowest-risk byte-identical path."
  - "app dispatch.py became a thin shim over the module dispatcher; test_dispatch.py's _FakeSpec gained auto-derived bind+needs_flags in __post_init__ so every test call site stays byte-identical while the relocated module dispatcher (spec.bind(ctx) + needs_flags) gets what it reads."
  - "positive injection-registry noun set narrowed to the DISTINCTIVELY-weather command nouns (weather/forecast/uv/cloudy) — the generic ops nouns (alert/status/sun/wind) legitimately name the module's own surface (AlertSink/record_alert), so including them would false-positive, not bite."

requirements-completed: [SEAM-06]

# Metrics
duration: 8min
completed: 2026-06-28
status: complete
---

# Phase 26 Plan 02: Command Registry + Dispatcher Seam (app rewire) Summary

**Rewired WeatherBot onto the Plan-01 module registry/dispatcher while holding the byte-identical oracle green: the app keeps a THIN re-exporting registry.py (builds via module `build_registry`, re-exports the four globals + `CommandSpec` byte-for-byte), `parse_command` delegates to the module `match_command`, and `dispatch.py` is a thin shim over the module dispatcher with the forecast hooks injected — both dispatcher coupling sites de-weathered (arm ladder → per-command `bind` closures, `group=="Forecast"` → neutral `needs_flags`), with the full ~778-test oracle byte-identical and zero golden re-baselined.**

## Performance

- **Duration:** ~8 min
- **Tasks:** 3
- **Files modified:** 6 (0 created)

## Accomplishments
- `weatherbot/interactive/registry.py` is now a thin singleton (D-03): `_registry = build_registry(_wire_handlers(_SPECS))` then re-exports `COMMANDS`/`BY_NAME`/`COMMANDS_BY_KEYWORD_LEN_DESC`/`render_help` under the EXACT names; the app `CommandSpec` keeps `takes_location`+`handler` (the oracle asserts them) and gains `bind`+`needs_flags`. `render_help` re-exported with the optional `commands` arg defaulting to `COMMANDS` so both `render_help()` and `render_help(COMMANDS + (extra,))` stay byte-identical (no TypeError on the parameterized oracle call at test_registry.py:160).
- The per-command `bind` closures (verbatim lifts of the seven `dispatch_reply` arms) read thresholds LIVE per-tap from `ctx.config` (D-01 anti-currying — a SIGHUP reload is never served stale) and resolve the handler live from `BY_NAME[name].handler` so handler-stub test patches are honored uniformly. `needs_flags=True` is set only on the two forecast specs.
- `parse_command` delegates to the module `match_command(text, registry.COMMANDS_BY_KEYWORD_LEN_DESC)` (D-04), re-wrapping into the app `ParsedCommand` so `bot.py` reads `parsed.spec`/`parsed.arg` byte-identically; the forecast grammar (`parse_forecast_flags`/`forecast_cache_suffix`/`ForecastFlags`/`_day_token`) stayed app-side.
- `dispatch.py` is a thin shim: `dispatch_reply` bundles a module `DispatchContext` and calls `spec.bind(ctx)`; `dispatch_spec` keeps its exact signature and delegates to the module dispatcher injecting `parse_flags=parse_forecast_flags` + `cache_suffix=forecast_cache_suffix`. The three call sites (bot.py, panel.py ×2, cli.py) are byte-identical; the module names no Forecast group; the off-loop `run_in_executor` + `UnknownLocationError` bubble (D-06) discipline is preserved.
- Gates extended: the `test_import_hygiene.py` litmus coverage-gap assertion now names the registry package files (`spec/registry/match/dispatch.py`, scoped to the registry subtree); `test_injection_registry.py` gained the positive command-injection assertion (build_registry + CommandRegistry require specs; the module bakes no distinctively-weather command name) paired with a biting `_BakedRegistry` + `weekday_forecast` self-proof.
- Full oracle green: **778 passed, exit 0** (baseline 777 + 1 new positive assertion). The CLI + `help` goldens + the anti-drift tests are byte-identical — the snapshot summary line (2 failed / 27 passed) is byte-for-byte the pre-existing baseline (consistent with 26-01-SUMMARY), so ZERO new snapshot diff was introduced.

## Task Commits

1. **Task 1: Thin app registry re-export + bind/needs_flags + match_command delegation** — `6ceb8cc` (feat)
2. **Task 2: Thin app dispatch shim over the module dispatcher (de-weather both coupling sites)** — `455f280` (feat)
3. **Task 3: Extend gates — litmus coverage-gap + positive injection-registry assertion** — `8e0711c` (feat)

## Files Modified
- `weatherbot/interactive/registry.py` — thin re-exporting singleton; app `CommandSpec` keeps takes_location+handler and gains bind+needs_flags; `_wire_handlers` wires handler+bind (lazy import; bind reads handler live via BY_NAME); render_help re-export with default-arg signature.
- `weatherbot/interactive/dispatch.py` — `dispatch_reply`/`dispatch_spec` reduced to thin shims over `yahir_reusable_bot.registry`; forecast hooks injected.
- `weatherbot/interactive/command.py` — `parse_command` delegates to module `match_command`; imports `match_command`; forecast grammar unchanged.
- `tests/test_dispatch.py` — `_FakeSpec` gained auto-derived bind+needs_flags (`__post_init__`); `test_briefing_path_not_on_default_executor` updated for the relocated `run_in_executor(None)` call site (now in the module dispatcher; weatherbot/ has zero, scheduler still zero).
- `tests/test_import_hygiene.py` — litmus coverage-gap now names the registry package files.
- `tests/test_injection_registry.py` — positive command-injection assertion + self-proof.

## Decisions Made
- **bind authored in `_wire_handlers`, not `build_runtime` (divergence from the plan's stated authoring site):** the CLI resolves `registry.BY_NAME[name]` and calls `dispatch_reply` WITHOUT going through `build_runtime`, and the panel/bot resolve specs from the import-time global — `build_runtime` never threads the spec set to those surfaces. Authoring `bind` only at `build_runtime` would leave the CLI/panel/bot specs with `bind=None`. So the closures live at the import-time registry site. D-01's substance is fully preserved (verbatim arm lift; live per-tap `ctx.config` reads). `wiring.py` therefore needed NO change.
- **bind resolves the handler live via `BY_NAME[name].handler`:** the established test-patch idiom (`replace(spec, handler=stub)` + `setitem(BY_NAME, name, stub)`, used across test_bot/test_panel/test_cli) swaps the handler but keeps the original `bind`. Capturing the handler in the closure would make those patches stale. Reading the handler live at call time honors every patch with zero consumer-test edits — the lowest-risk byte-identical path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] `weatherbot/scheduler/wiring.py` left unchanged (bind authored at the registry import-time site instead)**
- **Found during:** Task 1/Task 2 design.
- **Issue:** the plan + must_haves direct `build_runtime` to author the `bind` closures and list wiring.py in `files_modified`. But the CLI/panel/bot resolve their specs from the import-time global `registry.BY_NAME`/`COMMANDS`, and `cli.py` never calls `build_runtime` at all — a `build_runtime`-authored `bind` would be invisible to those three surfaces (their dispatched specs would carry `bind=None` and crash).
- **Fix:** authored each `bind` closure in `registry._wire_handlers` (the import-time site that populates `COMMANDS`), preserving D-01's substance exactly (verbatim arm lift; live per-tap `ctx.config.cloud_threshold`/`ctx.config.uv.threshold` reads — no build-time currying). The plan grants this discretion ("decide … whether bind is wired in `_wire_handlers` … or threaded from build_runtime"). `wiring.py` needed no change.
- **Files modified:** weatherbot/interactive/registry.py (no wiring.py edit).
- **Verification:** test_cli + test_bot + test_panel (which exercise the import-time-global dispatch) pass; the existing `test_injection_registry.py` AST-walk of `build_runtime` is unaffected.
- **Committed in:** 6ceb8cc / 455f280.

**2. [Rule 1 — Bug] `test_briefing_path_not_on_default_executor` reddened on the relocated executor call site**
- **Found during:** Task 2 (verify run).
- **Issue:** the test asserted `run_in_executor(None, …)` appears ONLY in `weatherbot/interactive/dispatch.py`. The relocation moved that call into `yahir_reusable_bot/registry/dispatch.py`, so the `weatherbot/` scan found `[]` and the `== ["interactive/dispatch.py"]` assertion failed. This is a structural consequence of the legitimate relocation, NOT a behavioral re-baseline (no golden output changed).
- **Fix:** updated part (a) to assert (i) the `weatherbot/` tree now has ZERO direct default-executor callers (the app shim delegates) and (ii) the call lives in exactly `registry/dispatch.py` under the module tree — preserving the test's true intent (the default executor is reached from the one shared dispatcher, never duplicated into a scheduler path). Part (b) — the scheduler package has ZERO `run_in_executor` — is unchanged and stays green.
- **Files modified:** tests/test_dispatch.py.
- **Verification:** test_dispatch passes (137 passed in the Task-2 verify); the scheduler-package invariant is byte-identical.
- **Committed in:** 455f280.

**3. [Rule 1 — Bug] positive injection-registry noun set false-positived on `AlertSink`**
- **Found during:** Task 3 (verify run).
- **Issue:** my first command-noun set included generic nouns (`alerts`/`status`/`sun`/`wind`); `alert` matched the module's legitimate generic `AlertSink`/`record_alert`/`resolve_alert` ops symbols (alert-throttle ports, not weather commands), reddening the assertion.
- **Fix:** narrowed the noun set to the DISTINCTIVELY-weather command nouns (`weather`/`forecast`/`uv`/`cloudy`) — aligned with the D-13-locked litmus's distinctive terms — which produce zero collisions with the module's generic surface while still biting (the self-proof flags `weekday_forecast`). Documented the exclusion rationale in the test.
- **Files modified:** tests/test_injection_registry.py.
- **Verification:** test_injection_registry passes (18 passed with test_import_hygiene); the self-proof still flags a baked `weekday_forecast`.
- **Committed in:** 8e0711c.

---

**Total deviations:** 3 auto-fixed (1 blocking, 2 bugs). No architectural decision required; no scope creep. All three are byte-identical-preserving (no behavioral golden re-baselined).

## Issues Encountered
None beyond the deviations above. The held-byte-identical oracle (`test_registry.py`, `test_command_views.py`, bot.py/panel.py/cli.py call sites, the CLI + help goldens, the anti-drift tests) passed by construction with zero re-baselining.

## TDD Gate Compliance
Tasks did not carry `tdd="true"` (the plan is `type: execute`). Each task is a verbatim-lift relocation of an already-tested app surface; the RED/GREEN proof is the per-task `<verify>` one-liner plus the full byte-identical oracle (778 passed, exit 0). No new behavior was introduced beyond the relocation, so no test(...) RED commit precedes each feat(...).

## Known Stubs
None. No placeholder values, empty data sources, or TODO/FIXME markers introduced. All four app surfaces are fully rewired onto the live module.

## Threat Flags
None. The rewire keeps every call site byte-identical and adds only additive test assertions. The `bind` closures read live config per-tap (T-26-04 mitigated — no registration-time capture); the thin dispatch shim adds no logging/I/O/secret handling (T-26-05 accepted); the panel operator gate + failure-isolation envelope are untouched (T-26-06 accepted); no package installs (T-26-SC mitigated). The `match_command` security contract (strip/casefold/slice-only) is the module's verbatim lift. No new network endpoint, auth path, file-access pattern, or trust-boundary schema.

## Next Phase Readiness
- SEAM-06 is fully delivered: CLI / Discord / `help` all derive from the one module-owned registry/dispatch; drift is structurally impossible (single dispatch path, asserted by the positive injection-registry test + the derive-from-one-list oracle); the module registry/dispatch carries no weather command name (litmus clean + the positive assertion); both coupling sites de-weathered with the hot-reload contract preserved.
- Phase 27 (PanelKit / Discord adapter) builds the control surface FROM this registry and injects `render`; Phase 28 (physical repo split) makes the command registration one of the documented plug points. No blockers.

## Self-Check: PASSED

All 6 modified files exist on disk; all 3 task commits (`6ceb8cc`, `455f280`, `8e0711c`) are in git history; the full suite is green (778 passed, exit 0) with the snapshot summary byte-identical to the pre-work baseline.

---
*Phase: 26-command-registry-dispatcher-seam*
*Completed: 2026-06-28*
