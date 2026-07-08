# Phase 26: Command Registry + Dispatcher Seam - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Relocate the **self-describing command registry + the shared `dispatch_spec` dispatcher** (already
un-braided in Phase 16) into the module `yahir_reusable_bot` as **generic plumbing**: commands are
*registered by the app* at the single composition root, and CLI + Discord + auto-`help` all derive
from that ONE registry with command-set drift **structurally impossible**. The module owns the
registry/dispatch plumbing + the help-derivation; **WeatherBot owns the actual command set**
(weather / uv / next-cloudy / sun / wind / status / alerts / locations / weekday-forecast /
weekend-forecast / help) and their content + handlers. **No weather command name or handler lives in
the module** — a reminder bot registers its own commands into the same mechanism.

**HOW is what we clarified here. The WHAT — and the headline shape — is LOCKED** by ROADMAP (Phase-26
detail block) + REQUIREMENTS (SEAM-06), and **behavior must stay byte-identical** (the Phase-21 CLI +
`help` goldens + the anti-drift tests + the ~649-test suite are the oracle). Research flag is **No** —
the dispatcher was already extracted in Phase 16; this is a **relocation behind the established
boundary**, so every decision below anchors on **move-not-redesign + lowest byte-identical risk**.

**Governing acceptance lens (every seam):** *"could a hypothetical reminder bot reuse this with zero
weather assumptions?"* The module's registry/dispatch must name no weather noun; the APP-02 litmus grep
over `yahir_reusable_bot/**` (term set `weather|forecast|location|openweather|\buv\b|briefing`,
D-13-locked, **do not broaden**) must stay clean, and the planner adds the positive
injection-registry assertion that the command set is *supplied by the app, not baked* (the Phase-25
D-05 pattern extended to commands).

**The crux this phase resolves:** today's `dispatch_reply` (dispatch.py:88-102) branches on weather
command **names** (`next-cloudy`, `uv`, `status`, `locations`) + the group string `"Forecast"`, and
reads weather config (`config.cloud_threshold`, `config.uv.threshold`); **`dispatch_spec`'s fetch path
(dispatch.py:152-161) is a SECOND coupling site** keying on `spec.group == "Forecast"` to choose the
flags-parse + cache-suffix branch. **Both** must lose their weather knowledge for the dispatcher to
move into the module.

**Stays entirely app-side (never enters the module):** the actual command names/summaries/groups +
their handlers (`weatherbot/interactive/commands/**`), the weather config reads (`cloud_threshold`,
`uv.threshold`), and the forecast grammar — `parse_forecast_flags` / `forecast_cache_suffix` /
`ForecastFlags` (litmus-tripping `forecast`/`\buv\b`/day-token).

**Cross-cutting gates re-run this phase:** PKG-01 (module imports zero app code; `grimp`-in-pytest +
isolated-import smoke), APP-02 litmus grep over the registry/dispatch seam **plus** the positive
injection-registry assertion, BHV-01/BHV-02 (suite + goldens green).

New capabilities (the Discord adapter / PanelKit relocation, the physical repo split) stay deferred to
their named later phases (27 / 28).

</domain>

<decisions>
## Implementation Decisions

The roadmap Phase-26 detail block pre-locks the headline (registry + shared dispatcher into the module
as a generic registration mechanism; app registers commands; CLI/Discord/`help` derive from the one
registry; drift impossible; no weather command name/handler in the module). Four parallel advisor
research agents (read the live code) surfaced the genuinely-open sub-decisions below. **The user
selected every recommended option** — all four anchor on the reusable-module goal and minimize
byte-identical risk. **The four decisions interlock into one coherent design:** the **`bind` closure
(D-01)** subsumes `takes_location`, so the **generic spec shrinks to 4 fields (D-02)**; the
**module-owns-type + app-side re-export (D-03)** keeps the oracle byte-identical while the mechanism
lives in the module; the **standalone matcher (D-04)** rides along opt-in.

### Handler arg-binding — the dispatcher genericization crux (SEAM-06)
- **D-01 [chosen: app-owned `bind(ctx)` closure on each `CommandSpec`]:** each app-supplied spec
  carries an **opaque `bind`/arg-provider callable** that receives a generic dispatch context
  (`result` / `config` / `flags` / `daemon_state`) and returns the handler's `CommandReply`. The
  module dispatcher collapses to a one-liner (`return spec.bind(ctx)` inside the existing off-loop
  `run_in_executor` shell). Each `bind` closure is a **verbatim lift of one existing `dispatch_reply`
  ladder arm** into WeatherBot's composition root (`wiring.py`) — where the weather names + threshold
  reads are *allowed* to live — so the module's litmus stays clean by construction and the
  contractual byte-identical reply suite keeps passing.
  - **Directly mirrors** the module's established "engines drive opaque app callables" precedent
    (`SchedulerEngine.callback`, `ReloadEngine.validate`/`register_jobs` — opaque, never inspected).
  - **MANDATORY follow-through (the second coupling site):** `dispatch_spec`'s fetch path keys on
    `spec.group == "Forecast"` (dispatch.py:153) to choose the flags-parse + cache-suffix branch. That
    pre-dispatch concern needs its **own generic signal** distinct from `bind` — an app-supplied
    `prepare`/`fetch` hook on the spec, **or** a neutral field (e.g. `needs_flags` / `fetch_kind`) the
    module reads without naming "Forecast". Planner's discretion which, as long as the module's async
    wrapper stops naming a weather group.
  - **Why not uniform single-context handler signature (Option b — rejected):** rewrites all 11
    handler signatures + their entire test surface — a redesign against the "No" research flag; every
    handler body changes → highest byte-identical risk.
  - **Why not `needs=(...)` descriptor + app providers (Option c — rejected):** right shape, but
    layers a net-new need-resolution engine into the module for behavior one opaque closure already
    delivers. Reach for it only if a future bot needs introspectable per-command capability metadata.
  - **Why not pre-bound closures curried at registration (Option d — rejected):** **regresses
    hot-reload.** `config`/thresholds are read **per-tap** via `holder.current()` (panel.py:520,
    bot.py:501); currying a threshold at build time freezes it stale after a SIGHUP reload. `result`/
    `flags` are fetched per-call and can't be curried anyway.

### Registration API + generic spec shape (SEAM-06, APP-01)
- **D-02 [chosen: a module `CommandRegistry` class + `build_registry(specs)`]:** the module ships a
  **`CommandRegistry` type** (constructed from the app's specs) that computes the immutable views every
  surface reads — `by_name`, the **longest-keyword-first** ordering (`COMMANDS_BY_KEYWORD_LEN_DESC`),
  and `render_help` — once, frozen. Same **constructor-injection idiom** the module already ships 3×
  (`SchedulerEngine(scheduler)`, `ReloadEngine(holder, …)`, `ConfigHolder(None)`). The generic
  **`CommandSpec` shrinks to `name, group, summary, handler`** — `group` is a generic help-header
  string the app fills with "Weather"/"Forecast"/"Info"; **`takes_location` does NOT survive in the
  module** (it is subsumed by D-01's `bind` closure, which already knows each handler's arg shape).
  - **Why not functional `build_registry → FrozenRegistry` struct (Option b):** equivalent, but breaks
    the class idiom the rest of the module chose, for no structural gain.
  - **Why not decorator registration (Option c — rejected):** scatters registration across handler
    modules → violates the single-composition-root rule (APP-01 / Phase-25 D-04) + the
    frozen-immutability goal; re-opens the drift this phase exists to make impossible.
  - **Why not thin helper fns + app keeps the tuple (Option d — fallback floor):** lowest diff, but
    leaves the BY_NAME/keyword-ordering *assembly* app-side — under-delivers "module owns the
    mechanism." Sanctioned only if the registry class somehow perturbs a golden.

### Registry threading — where the assembled registry lives (SEAM-06, BHV-01)
- **D-03 [chosen: module owns the TYPE; app keeps a thin re-exporting `registry.py` singleton]:** the
  module owns the `CommandRegistry` type + `build_registry`; **WeatherBot keeps a thin
  `weatherbot/interactive/registry.py`** that builds its singleton instance (`build_registry(_SPECS)`)
  and **re-exports `COMMANDS` / `BY_NAME` / `COMMANDS_BY_KEYWORD_LEN_DESC` / `render_help`
  byte-for-byte**. Every existing read site keeps its exact `registry.X` access — **all 6 consumers +
  the oracle tests pass by construction**, not by re-baselining.
  - **The decisive constraint (live-code finding):** `tests/test_registry.py` and
    `tests/test_command_views.py` `import COMMANDS, BY_NAME, COMMANDS_BY_KEYWORD_LEN_DESC, render_help`
    **directly from `weatherbot.interactive.registry`**. Any option that *removes/renames* those
    app-side globals **rewrites the oracle itself** — converting a relocation into a behavioral-surface
    change. That is why pure DI (Option a) and the lazy accessor (Option d) are rejected.
  - **Documented divergence (accepted):** the "single composition root" for the registry is therefore
    **import-time** (the app's `registry.py` module load) rather than **call-time** (`build_runtime`).
    This is a conscious, lowest-risk exception to Phase-25's constructor-injection-from-root rule,
    justified by the import-time-global reality of two consumers (`parse_command`'s call-time read +
    the **panel's import-time `registry.BY_NAME` assert**, panel.py:98) and the phase's byte-identical
    mandate. **Reusability is still real:** a reminder bot calls the same module
    `build_registry(its_own_specs)` with its own handler closures.
  - **Why not pure DI / thread the instance everywhere (Option a — rejected):** cleanest single-root
    story, but touches all 6 read sites AND rewrites the registry oracle; the panel's import-time assert
    has no instance to read at import. Highest risk; revisit only if a genuine multi-registry-in-one-
    process need appears in a later milestone.
  - **Why not hybrid / lazy accessor (Options c/d — rejected):** (c) creates two ways to reach the
    registry = the exact drift this phase kills; (d) hits a panel import-order hazard (assert fires
    before the root populates the holder).

### Parser-seam scope (SEAM-06)
- **D-04 [chosen: standalone module free function `match_command(text, specs)`]:** relocate the
  **generic longest-keyword-first + word-boundary matcher** (today `parse_command`, command.py:91-118)
  into the module as an **opt-in free function** that takes the keyword-ordered specs; the registry
  stays pure data. The **forecast grammar stays app-side** — `parse_forecast_flags` /
  `forecast_cache_suffix` / `ForecastFlags` trip the `forecast`/`\buv\b`/day-token litmus and must not
  move. The module should **re-export the len-descending ordering** beside the matcher so the
  "longest-first" invariant (Pitfall 4 — `next-cloudy` before any shorter prefix) + the word-boundary
  guard ("sunny" ≠ "sun", T-06-02) live together as captured reuse payoff.
  - **Decisive code fact:** the matcher has **exactly one consumer** — the Discord text path
    (`bot.py:489`). The CLI (`cli.py:958`, argparse already split the name) and the panel
    (`custom_id → BY_NAME[name]`) resolve commands **without** it. So the matcher is genuinely-generic
    text-command plumbing a *second text bot* would re-hand-write, while a button/slash bot pulls the
    registry without dragging it.
  - **Why not a method on the registry type (Option c — rejected):** couples the registry type to a
    text grammar the panel/CLI never use — WeatherBot's own button-only panel is the living counter-
    example.
  - **Why not leave all parsing app-side (Option b — rejected):** smallest diff, but forfeits the one
    genuinely-generic reuse payoff and defers the litmus-clean split from forecast grammar.

### Claude's Discretion
- The module sub-layout for the registry seam (a `registry/` package inside `yahir_reusable_bot/`
  holding `CommandSpec` + `CommandRegistry` + `match_command`, vs a flatter shape) and file naming —
  guided by the existing `channels/` / `config/` / `scheduler/` / `lifecycle/` / `ports/` shapes.
- Exact `CommandRegistry` / `CommandSpec` / `build_registry` / `match_command` names and param shapes,
  and the generic dispatch-context type the `bind` closure receives — shaped by what keeps the call
  sites byte-identical.
- **Which neutral signal de-weathers `dispatch_spec`'s fetch branch** (D-01 follow-through): an
  app-supplied `prepare`/`fetch` hook on the spec, or a neutral `needs_flags`/`fetch_kind` field the
  module reads — either keeps the module from naming "Forecast".
- Where the `bind` closures are authored (inline at `wiring.py build_runtime`, or a small app-side
  factory beside the specs) and how `result`/`config`/`flags`/`daemon_state` are bundled into the
  context the module hands them.
- The precise form of the positive injection-registry assertion (extending the Phase-25 D-05 pattern
  to commands) and the litmus-grep target set for the registry/dispatch seam; the `grimp`-graph +
  isolated-import smoke extension for the new module edges.
- Whether the app's `CommandSpec` re-adds `takes_location` (or equivalent arg-shape datum) via an
  app-side subclass / `meta` field for any app code that still reads it, or whether the `bind`
  closures fully absorb it.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & milestone contract
- `.planning/ROADMAP.md` § "Phase 26: Command Registry + Dispatcher Seam" — the **pre-locked design**
  (registry + shared `dispatch_spec` into the module as a generic registration mechanism; app
  registers commands at the composition root; CLI/Discord/`help` derive from the one registry; drift
  structurally impossible; no weather command name/handler in the module) + the **3 locked success
  criteria**.
- `.planning/ROADMAP.md` § "v2.0 Bot Module Extraction" milestone header + phase spine (leaf-seams-
  first, split-last) — why the registry/dispatch is this seam and why the Discord adapter / PanelKit
  relocation defers to Phase 27 and the physical split to Phase 28.
- `.planning/REQUIREMENTS.md` § **SEAM-06** (self-describing registry + shared dispatcher in the
  module; commands registered by the app; CLI/Discord/`help` derive from one registry; drift
  structurally impossible) + the **Cross-cutting acceptances** (PKG-01 on 23–27; APP-02 standing
  litmus grep; BHV-01/BHV-02 re-run every phase). Traceability: SEAM-06 → Phase 26.

### Prior-phase contracts this phase must honor
- `.planning/phases/25-lifecycle-ready-gate-composition-root/25-CONTEXT.md` — the **explicit hand-off**
  deferring the Command Registry relocation to THIS phase; **D-04** the single app-side `wiring.py`
  `build_runtime(...)` composition root where commands are registered; **D-05** the positive
  injection-registry assertion pattern (extend here to commands); the **deferred `BotApp.compose()`**
  note ("defer to after Phase 26, when the registry gives the assembly object something real to
  compose") — Phase 26's registry is exactly that something.
- `.planning/phases/24-config-hot-reload-engine/24-CONTEXT.md` — the constructor-injection +
  opaque-passthrough engine precedent (`ReloadEngine`, basis for the `CommandRegistry` shape) and the
  per-tap `holder.current()` reload contract (why D-01 rejects build-time threshold currying).
- `.planning/phases/23-scheduler-engine-occurrencestore-jobstore-seam/23-CONTEXT.md` — the
  `SchedulerEngine(scheduler)` constructor-injection precedent the `CommandRegistry` mirrors.
- `.planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-CONTEXT.md` — the Ports &
  Adapters / DI template, the **flat-sibling `yahir_reusable_bot/` layout**, the `grimp`-in-pytest
  import gate + isolated-import smoke + signatures-only litmus (basis for the seam gates), and "adapt
  the orchestrator, don't rewrite it."
- `.planning/phases/21-characterization-golden-test-harness/21-CONTEXT.md` + `21-PATTERNS.md` — the
  golden oracle (the **CLI + `help` goldens + the anti-drift tests**) and the move-path package
  pattern map; the discipline rule (any non-empty snapshot diff during extraction is a failure to
  investigate, never rubber-stamped).
- Phase 16 (shared `dispatch_spec` extraction) — the original un-braiding this phase relocates; the
  single arg-adaptation ladder lifted out of the two old call sites (`bot.build_on_message` + the CLI
  `_run_registry_command`).

### Source surfaces this phase moves / touches
- `weatherbot/interactive/registry.py` — `CommandSpec` (frozen `name, group, summary, takes_location,
  handler`), `_SPECS` / `_wire_handlers` / `COMMANDS`, `BY_NAME`, `COMMANDS_BY_KEYWORD_LEN_DESC`,
  `render_help` (registry.py:133-155, groups by `.group` first-appearance order). **The registry
  TYPE + assembly + `render_help` + the keyword ordering move into the module; the app keeps a thin
  re-exporting `registry.py` (D-03); the spec shrinks to 4 generic fields (D-02).**
- `weatherbot/interactive/dispatch.py` — `dispatch_reply` (L88-102, the if/elif arm ladder → app
  `bind` closures, D-01) + `dispatch_spec` (L105-186, the off-loop `run_in_executor` wrapper → module
  control-flow shell; its `group=="Forecast"` fetch branch L152-161 → a neutral signal, D-01
  follow-through). **Dispatcher relocates; the weather branching rides app-supplied closures/hooks.**
- `weatherbot/interactive/command.py` — `parse_command` (L91-118, the generic longest-first +
  word-boundary matcher → module `match_command`, D-04) vs `parse_forecast_flags` /
  `forecast_cache_suffix` / `ForecastFlags` (**stay app-side** — litmus-tripping forecast grammar).
- `weatherbot/interactive/commands/` — `weather_views.py` / `forecast.py` / `info.py` / `status.py`
  (the heterogeneous handler signatures the `bind` closures wrap; **stay app-side**, unchanged).
- `weatherbot/scheduler/wiring.py` — `build_runtime(...)` the single composition root (Phase-25 D-04):
  builds the registry singleton from the app specs + authors the `bind` closures (the weather names +
  `cloud_threshold`/`uv.threshold` reads live here).
- `weatherbot/cli.py` — `_run_registry_command` (~L557-630, calls `dispatch_reply` — no event loop,
  own sync fetch), the registry subparser build (~L806-833), the dispatch read (~L953-960 via
  `registry.BY_NAME`). **Reads the re-exported globals (D-03) — must stay byte-identical (CLI
  goldens).**
- `weatherbot/interactive/bot.py` — `build_on_message` (~L489 `parse_command`, ~L500-520 `dispatch_spec`
  call inside the failure-isolation envelope). The **sole `parse_command` consumer**.
- `weatherbot/interactive/panel.py` — the import-time `registry.BY_NAME` allow-list assert (~L89-99)
  + the callback `registry.BY_NAME[name]` lookups + the third `dispatch_spec` call (~L505-525). The
  **import-time global read** that forces D-03's re-export approach.
- `tests/test_registry.py` + `tests/test_command_views.py` — **import the module globals directly**
  (`COMMANDS, BY_NAME, COMMANDS_BY_KEYWORD_LEN_DESC, render_help`) — the oracle that pins D-03.
- `tests/test_import_hygiene.py` — the mature 3-gate APP-02 litmus (grimp + isolated-import + AST noun
  scan, D-13-locked term set `weather|forecast|location|openweather|\buv\b|briefing`) to **re-run +
  extend** with the new registry/dispatch module edges + the positive injection-registry assertion.
- `tests/test_dispatch.py` / `tests/test_bot.py` / `tests/test_panel.py` — the contractual reply suite
  proving `dispatch_spec`/`dispatch_reply` stay byte-identical through the relocation.
- `pyproject.toml` — `[tool.hatch...packages]` (two-package wheel), the `grimp` import-gate config,
  `[tool.coverage]` (must keep covering moved code).
- `yahir_reusable_bot/scheduler/engine.py` (`SchedulerEngine`) + `yahir_reusable_bot/config/reload.py`
  (`ReloadEngine`) + `yahir_reusable_bot/config/holder.py` (`ConfigHolder`) — the constructor-
  injection + opaque-callable precedents the `CommandRegistry` + `bind` closures clone.

### Tooling docs (for the planner)
- `typing` — `Callable` / `Protocol` / `dataclass(frozen=True)` / `replace` (the generic `CommandSpec`
  + `bind` callable + the immutable registry views) — https://docs.python.org/3/library/typing.html
- `grimp` (the import-graph gate over the growing module) — https://pypi.org/project/grimp/

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weatherbot/interactive/registry.py` (`CommandSpec` + `_wire_handlers` + `render_help` +
  `COMMANDS_BY_KEYWORD_LEN_DESC`): the registry mechanism to relocate; the `replace(spec, handler=…)`
  lazy-handler-wiring (registry.py:85-117) keeps imports acyclic and must survive the move.
- `weatherbot/interactive/dispatch.py` (`dispatch_spec` off-loop `run_in_executor` shell): the
  generic control flow moves to the module verbatim; only the weather-specific binding (`dispatch_reply`
  arms + the `group=="Forecast"` fetch branch) lifts behind app closures/hooks.
- `weatherbot/interactive/command.py` (`parse_command`): the pitfall-dense longest-first +
  word-boundary matcher — pure plumbing reading only `spec.name`, ready to relocate as `match_command`.
- `yahir_reusable_bot/scheduler/engine.py` + `config/reload.py` + `config/holder.py`: the
  constructor-injection + opaque-callable recipe to clone for `CommandRegistry` + `bind`.
- `tests/test_import_hygiene.py`: the mature, self-proven 3-gate APP-02 litmus to re-run + extend.
- The Phase-21 CLI/`help` goldens + anti-drift tests + ~649 tests: the standing byte-identical oracle.

### Established Patterns
- **Engines take collaborators by constructor injection + drive opaque app callables/hooks**
  (`SchedulerEngine` / `ReloadEngine` / `ConfigHolder` precedent) — the `CommandRegistry` follows this
  (D-02); the `bind` closure is the opaque per-command callable (D-01).
- **App injects WeatherBot specifics into generic module mechanisms; the module never assembles the
  app** — the weather names + threshold reads live in the app's `wiring.py`/`bind` closures, never in
  the module.
- **Litmus is a negative grep over `yahir_reusable_bot/**`; the locked term set stays weather-specific**
  — generic seam names (`CommandRegistry`/`CommandSpec`/`match_command`/`group`) are allowed; the
  *positive* injection-registry test proves the command set is app-supplied (D-03/Phase-25 D-05).
- **Module-mechanism + app-side thin singleton re-export** keeps import-time-global consumers
  (`parse_command`, the panel's import-time assert) + the oracle byte-identical (D-03) — the lowest-
  risk relocation shape.
- **Lazy handler imports inside the wiring function** (registry.py `_wire_handlers`) keep `command.py`
  / `panel.py` registry imports acyclic — preserve this through the relocation.

### Integration Points
- The app's thin `weatherbot/interactive/registry.py` builds the singleton via the module
  `build_registry(_SPECS)` and re-exports `COMMANDS`/`BY_NAME`/`COMMANDS_BY_KEYWORD_LEN_DESC`/
  `render_help` — all 6 consumers (cli subparser build + dispatch, `parse_command`, panel import-time
  assert + callbacks, bot `on_message`) keep their exact `registry.X` access.
- The `bind` closures are authored at the composition root (`wiring.py build_runtime`) and carried on
  each app `CommandSpec`; the module dispatcher invokes `spec.bind(ctx)` inside the unchanged off-loop
  `run_in_executor` tail.
- `dispatch_spec`'s fetch path stops reading `spec.group == "Forecast"` — it reads a neutral
  signal/hook so a forecast lookup still widens the cache key while the module names no weather group.
- The import-hygiene + litmus gates gain new registry/dispatch module-edge coverage + the positive
  injection-registry assertion — additive test/config, no production behavior change beyond the
  relocation.

</code_context>

<specifics>
## Specific Ideas

- **Two coupling sites, not one.** The genericization must de-weather BOTH `dispatch_reply` (the arm
  ladder → `bind` closures) AND `dispatch_spec`'s fetch branch (`group=="Forecast"` → a neutral
  signal). Missing the second leaves a weather noun in the module and trips the litmus.
- **The oracle imports the module globals.** `test_registry.py` / `test_command_views.py` do
  `from weatherbot.interactive.registry import COMMANDS, BY_NAME, …`. This single fact pins D-03:
  the app keeps a thin re-exporting `registry.py`; the registry TYPE relocates, the globals do not.
- **The matcher has exactly one consumer.** Only the Discord text path (`bot.py:489`) calls
  `parse_command`; CLI + panel resolve via `BY_NAME` directly. So the matcher is opt-in module
  plumbing a text reminder bot reuses, while a button/slash bot ignores it — hence the standalone
  free function (D-04), not a registry method.
- **Hot-reload forbids registration-time config capture.** Thresholds are read per-tap via
  `holder.current()`; the `bind` closure must read live config from the context, not a value curried
  when the spec was built (D-01 rejects Option d for this reason).

</specifics>

<deferred>
## Deferred Ideas

- **`BotApp.compose()` explicit assembly object** (Phase-25 D-04 Option b) — the registry this phase
  builds is what it was waiting for, but the explicit-assembly relocation itself stays deferred past
  Phase 26; the single root remains the procedural app-side `wiring.py build_runtime`.
- **Uniform single-context handler signatures** (D-01 Option b) — the principled end-state (handlers
  self-describe their arg needs) but a multi-file redesign; defer past the relocation if ever wanted.
- **`needs=(...)` capability descriptor + a module need-resolution engine** (D-01 Option c) — revisit
  only if a future bot needs introspectable per-command capability metadata.
- **Pure-DI registry instance threaded through all consumers** (D-03 Option a) — revisit only if a
  genuine multi-registry-in-one-process need appears in a later milestone; would also rewrite the
  registry oracle.
- **PanelKit / Discord adapter physical relocation + the generic `SelectedContext[I]`** — **Phase 27**
  (PanelKit builds the control surface *from this registry*, injects `render`).
- **Physical repo split + uv git dependency + EXTENSION-GUIDE** — **Phase 28** (the registry/command
  registration becomes one of the documented plug points).
- **Broadening the litmus term set** — rejected; the D-13-locked term set stays weather-specific.
  Generic seam names (`CommandRegistry`/`match_command`/`group`) are exactly what the module exposes.

None of these are scope creep — they are alternatives/extensions within the extraction domain,
consciously placed in their correct later phase.

</deferred>

---

*Phase: 26-command-registry-dispatcher-seam*
*Context gathered: 2026-06-28*
