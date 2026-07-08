# Phase 26: Command Registry + Dispatcher Seam - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-28
**Phase:** 26-command-registry-dispatcher-seam
**Areas discussed:** Handler arg-binding, Registration API + spec shape, Registry threading, Parser-seam scope

> Advisor mode (full_maturity calibration — vendor philosophy: thorough-evaluator). Four parallel
> `gsd-advisor-researcher` agents read the live code and returned 3-5-option comparison tables per
> area. The user selected every recommended option.

---

## Handler arg-binding (the dispatcher genericization crux)

| Option | Description | Selected |
|--------|-------------|----------|
| App `bind(ctx)` closure on each CommandSpec | Module dispatcher collapses to `spec.bind(ctx)`; each closure is a verbatim lift of one `dispatch_reply` arm into `wiring.py`. Lowest byte-identical risk; exact opaque-callable precedent fit. | ✓ |
| Uniform single-context handler signature | Rewrite all 11 handlers to take one DispatchContext. Multi-file redesign against the "No" research flag. | |
| `needs=(...)` descriptor + app providers | Right shape, net-new resolution engine for what one closure delivers. | |
| Pre-bound closures curried at registration | Regresses hot-reload — thresholds read per-tap via `holder.current()`; build-time currying freezes them stale. | |

**User's choice:** App `bind(ctx)` closure (D-01)
**Notes:** Follow-through flagged: `dispatch_spec`'s fetch path keys on `spec.group == "Forecast"`
(dispatch.py:153) — a SECOND coupling site that needs its own neutral signal (app-supplied
`prepare`/`fetch` hook or a neutral `needs_flags`/`fetch_kind` field), distinct from `bind`.

---

## Registration API + generic spec shape

| Option | Description | Selected |
|--------|-------------|----------|
| `CommandRegistry` class + `build_registry(specs)` | Module type computes by_name / keyword-len-desc / render_help once, frozen. Same constructor-injection idiom shipped 3×. Spec shrinks to generic name/group/summary/handler; `takes_location` subsumed by the bind closure. | ✓ |
| Functional `build_registry → FrozenRegistry` struct | Equivalent, breaks the class idiom for no gain. | |
| Thin helper functions, app keeps tuple | Lowest diff but leaves assembly app-side — under-delivers "module owns the mechanism". | |
| Decorator registration | Scatters registration — violates single-composition-root + frozen-immutability; re-opens drift. | |

**User's choice:** `CommandRegistry` class (D-02)
**Notes:** Generic spec = `name, group, summary, handler`. `group` is a generic help-header string the
app fills ("Weather"/"Forecast"/"Info"). `takes_location` does not survive in the module — the bind
closure (D-01) already knows each handler's arg shape.

---

## Registry threading (where the assembled registry lives)

| Option | Description | Selected |
|--------|-------------|----------|
| Module owns TYPE; app-side singleton re-exports globals | Module owns `CommandRegistry` + `build_registry`; app keeps a thin `registry.py` building its singleton + re-exporting COMMANDS/BY_NAME/keyword-order/render_help byte-for-byte. Near-zero churn; all 6 read sites + oracle pass by construction. | ✓ |
| Pure DI — thread instance everywhere | Cleanest single-root, but touches all 6 read sites AND rewrites the registry oracle; panel import-time assert has no instance. Highest risk. | |
| Hybrid (DI dispatch, globals for parser/panel) | Two ways to reach the registry = the exact drift this phase kills. | |
| Lazy `get_registry()` accessor | Panel import-time assert fires before the root populates it — ordering hazard. | |

**User's choice:** Module type + app-side re-export (D-03)
**Notes:** Decisive constraint — `test_registry.py` / `test_command_views.py` import the module
globals directly, so removing/renaming them rewrites the oracle. Accepted documented divergence: the
registry's "single composition root" is import-time (app's `registry.py` load), not call-time
(`build_runtime`) — justified by the import-time-global reality of `parse_command` + the panel assert.

---

## Parser-seam scope

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone `match_command(text, specs)` module free fn | Relocate the generic longest-first + word-boundary matcher opt-in; registry stays pure data; forecast grammar stays app-side. Re-export the len-desc ordering beside it. | ✓ |
| Method on registry type (`registry.match`) | Couples the registry type to a text grammar the panel/CLI never use. | |
| Leave all parsing app-side | Forfeits the one genuinely-generic reuse payoff; defers the litmus-clean split. | |

**User's choice:** Standalone `match_command(text, specs)` (D-04)
**Notes:** The matcher has exactly one consumer — the Discord text path (`bot.py:489`). CLI + panel
resolve via `BY_NAME` directly. `parse_forecast_flags` / `forecast_cache_suffix` / `ForecastFlags`
stay app-side (litmus-tripping forecast grammar).

## Claude's Discretion

- Module sub-layout (`registry/` package vs flatter) + file/symbol naming (`CommandRegistry`,
  `CommandSpec`, `build_registry`, `match_command`) + the generic dispatch-context type shape.
- Which neutral signal de-weathers `dispatch_spec`'s fetch branch (hook vs neutral field).
- Where the `bind` closures are authored + how the context is bundled.
- The precise positive injection-registry assertion form + the litmus/grimp gate extension.
- Whether the app re-adds `takes_location` via subclass/`meta`, or the bind closures fully absorb it.

## Deferred Ideas

- `BotApp.compose()` explicit assembly object — past Phase 26.
- Uniform single-context handler signatures — past the relocation.
- `needs=(...)` capability descriptor + module resolver — only if introspectable metadata is needed.
- Pure-DI registry instance threaded everywhere — only for a future multi-registry-in-one-process need.
- PanelKit / Discord adapter + generic `SelectedContext[I]` — Phase 27.
- Physical repo split + uv git dependency + EXTENSION-GUIDE — Phase 28.
- Broadening the litmus term set — rejected; the D-13 term set stays weather-specific.
