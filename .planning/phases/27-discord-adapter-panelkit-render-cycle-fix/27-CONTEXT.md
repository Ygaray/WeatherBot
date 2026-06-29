# Phase 27: Discord Adapter + PanelKit + Render-Cycle Fix - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** `--auto` (single-pass; decisions auto-selected on the reusable-module + byte-identical-lowest-risk axis — see DISCUSSION-LOG for the per-question log)

<domain>
## Phase Boundary

Relocate the **Discord *adapter*** — the isolated gateway `BotThread` (started after READY, torn down
in `finally`), the persistent-view machinery, and **`PanelKit`** — into the module
`yahir_reusable_bot` at a **new adapter layer one level up from the channel-agnostic core** (SMS/Slack
have no buttons, so this is *not* core plumbing). `PanelKit` builds its command-button control surface
**from the Phase-26 registry**, exposes a **generic `SelectedContext[I]`** (WeatherBot's selected
*location* is `SelectedContext[str]`), and takes the result `render` as an **injected callable**.

**The crux this phase resolves (SEAM-07 SC#2):** today there is a latent `render_embed`↔`PanelView`
import cycle — `panel.py` imports `render_embed` from `bot.py` at module top (panel.py:54), and
`bot.py` breaks the back-edge with a **deferred in-function import** of `PanelView` inside
`summon_panel` (bot.py:304-307). This phase resolves the cycle **by ownership, not by deferral**:
`render_embed` is **weather/house-style-specific** (the 📍 location indicator, `BRIEFING_COLOR_INT`,
the self-ageing `Updated <t:…>` stamp, WeatherBot field budgeting) and **moves app-side**; the module's
`PanelKit`/panel view receives it as an **opaque injected `render` callable**. No deferred/in-function
import survives — proven by a core/adapter import-isolation check.

**Every v1.3 persistent-view invariant is preserved byte-identically** (the headline is **LOCKED** by
ROADMAP Phase-27 + REQUIREMENTS SEAM-07; the Phase-21 panel/clone-render goldens + operator-gate /
restart-routing / isolation tests are the oracle): `timeout=None`, `add_view` in `setup_hook`, the
operator gate + identity-free ephemeral reject, the per-callback **non-propagating failure-isolation
envelope** + `View.on_error`, the **WR-01/WR-02 clone-path polish survival** (📍 / emoji / `Updated
<t:…>` across ack/collapse/re-render), the **frozen `custom_id`s** (incl. the `wb:` marker), and the
**`discord.py==2.7.1` pin**.

**Governing acceptance lens (every seam):** *"could a hypothetical reminder/Slack bot reuse this
adapter with zero weather assumptions?"* The module's adapter must name no weather noun and no
WeatherBot-specific UI (no "location" `Select`, no "forecast" grid, no `wb:` literal, no 📍). The
APP-02 litmus grep over `yahir_reusable_bot/**` (D-13-locked term set
`weather|forecast|location|openweather|\buv\b|briefing`, **do not broaden**) must stay clean, and the
planner adds the **positive injection assertion** that the panel's app-specific UI + the `render` are
*supplied by the app, not baked* (the Phase-25 D-05 / Phase-26 D-03 pattern extended to the adapter).

**Stays entirely app-side (never enters the module):** `render_embed` (the weather/house-style embed
builder — moves app-side and is *injected*), the **location dropdown** / **2×2 forecast grid** / **📍
indicator** / **emoji cosmetics**, the `panel_channel_id` config read, and any forecast grammar
(`ForecastFlags` etc., already app-side from Phase 26).

**Generic plumbing that relocates into the module adapter:** the gateway `BotThread`
(thread+own-loop, start-after-READY, `finally` teardown), the operator gate (`operator_id` —
generic), the persistent-view registration (`timeout=None` + `add_view` in `setup_hook`), the
per-callback failure-isolation envelope + `View.on_error`, the panel ownership test (author + marker),
the create-before-delete summon orchestration, and `PanelKit` (registry-derived command buttons +
the `SelectedContext[I]` + the injected `render` seam). Command dispatch already routes through the
Phase-26 `registry` / `dispatch` / `match` module seams.

**Cross-cutting gates re-run this phase:** PKG-01 (module imports zero app code; `grimp`-in-pytest +
isolated-import smoke, extended to the new adapter edges + the core↔adapter isolation check), APP-02
litmus grep over the adapter seam **plus** the positive injection assertion, BHV-01/BHV-02 (suite +
goldens green, panel behavior byte-identical).

The physical repo split + uv git dependency + EXTENSION-GUIDE stay deferred to **Phase 28** (the
adapter's `render` / cosmetic-component / marker injection points become documented plug points).

</domain>

<decisions>
## Implementation Decisions

The ROADMAP Phase-27 detail block + SEAM-07 pre-lock the headline (Discord adapter `BotThread` +
`PanelKit` + generic `SelectedContext[I]` into the module's adapter layer; `PanelKit` builds from the
registry; `render` is an **injected callable** that resolves the cycle by ownership; every v1.3
persistent-view / clone-path / `custom_id` invariant preserved byte-identically; `discord.py==2.7.1`
pinned). This is a **research-flagged phase** — resolving the cycle by ownership while preserving
every invariant byte-identically is intricate. The six decisions below lock the **HOW shape** on the
reusable-module + lowest-byte-identical-risk axis; the **intricate mechanics are explicitly handed to
the researcher/planner** (see Claude's Discretion). The decisions interlock: **moving `render_embed`
app-side + injecting it (D-01)** is what *lets* the panel be generic, which *forces* the generic
**`SelectedContext[I]` (D-02)** and the **app-supplied cosmetic-component seam (D-03)**; the
**app-supplied marker (D-04)** and **module-owned exact pin (D-05)** keep the relocated **`BotThread`
+ view machinery (D-06)** litmus-clean and route-stable.

### Render-cycle resolution — the crux (SEAM-07 SC#2)
- **D-01 [chosen: move `render_embed` app-side + inject it as an opaque `render` callable; kill the
  deferred import]:** `render_embed` is weather/house-style-specific (📍, `BRIEFING_COLOR_INT`,
  `Updated <t:…>`, WeatherBot field budgeting), so it **lives app-side** and is **injected into the
  module panel/`PanelKit` as an opaque `render` callable** the module invokes but never inspects. The
  module names no embed house style. The generic signature drops the weather noun: the callable
  receives the `CommandReply` + the generic `SelectedContext[I]` (D-02) — **not** a `location=` kwarg
  — so the app's `render` pulls the selected item to draw its own 📍 line. The current `bot.py:304-307`
  deferred `from ...panel import PanelView` is **eliminated by construction**: the app-side summon path
  constructs the module's panel with the app's `render` + app cosmetics injected, so neither side
  needs a back-edge import. Proven by a core/adapter import-isolation check (no deferred/in-function
  import survives).
  - **Directly mirrors** the module's established "engines/views take collaborators by constructor
    injection + drive opaque app callables" precedent — Phase-26 `bind`, Phase-24
    `validate`/`register_jobs`, Phase-23 `SchedulerEngine.callback`.
  - **Why not keep the deferred import (Option b — rejected):** the ROADMAP **explicitly forbids** it
    ("not a deferred import"). A deferred import leaves the cycle latent, keeps `render_embed`'s
    weather house-style reachable from the module, and **fails the import-isolation acceptance (SC#2)**.
  - **Why not a thin generic `render` in the module + app passes only colors/style data (Option c —
    rejected):** re-introduces a weather-shaped contract (the 📍 line, field budgeting) into the
    module under a generic name; the cleanest litmus-clean cut is the *whole* embed builder app-side.

### `SelectedContext[I]` — the generic selection (SEAM-07 SC#4)
- **D-02 [chosen: a module-owned generic `SelectedContext[I]`; WeatherBot uses `SelectedContext[str]`]:**
  the module ships a small **generic** `SelectedContext[I]` (a typed holder for the panel's currently
  *selected item* of type `I`) replacing today's hardcoded `_selected_location: str` (panel.py:323).
  The panel holds/threads it opaquely; the app's `render` + app components read `.value` (the selected
  location `str`). The **one place `spec.takes_location` survived Phase 26** (panel.py:512) is
  generalized — whether a command consumes the selected context is an **app-supplied datum on the
  spec/`bind`** (re-added app-side per Phase-26 D-02's sanctioned app-side `takes_location`/`meta`),
  read by the app's binding, not by the module naming "location."
  - **ROADMAP-locked headline** — `SelectedContext` generic, no hardcoded "location", yet carries
    WeatherBot's selected location (SC#4).
  - **Why not a bare `Any`/untyped slot (Option b — rejected):** forfeits the typed reuse payoff the
    `[I]` generic exists to capture (a reminder bot's `SelectedContext[ReminderId]`); costs nothing to
    parameterize.

### Generic-vs-app UI split — how WeatherBot supplies its cosmetics (SEAM-07 SC#1, APP-02)
- **D-03 [chosen: `PanelKit` owns the registry-derived command buttons + the persistent-view
  invariants; the app supplies its cosmetic UI (location `Select`, 2×2 forecast grid, emoji) + the
  injected `render` through an app-component-contributor seam]:** `PanelKit` builds the **generic
  command-button control surface from the Phase-26 registry** and owns the persistent-view contract
  (`timeout=None`, `add_view`, child custom_id length asserts, the clone-render path). **WeatherBot's
  app-specific components** — the location dropdown that *sets* the `SelectedContext`, the
  always-visible forecast grid, the 📍/emoji cosmetics — are **contributed by the app** (app-supplied
  view-item builders / extra rows handed to `PanelKit`, plus the injected `render`), so the module
  hardcodes no "location Select" and no "forecast grid." `weatherbot/interactive/panel.py` shrinks to
  the cosmetic contributions + `render`; the module adapter names no weather UI.
  - **Litmus-clean by construction** — the only weather nouns left (dropdown labels, grid, 📍) are in
    the app's contributed components, never in `yahir_reusable_bot/**`. The positive injection
    assertion proves they are app-supplied.
  - **Planner's discretion on the exact contributor mechanism** — app-supplied callables that build
    extra `discord.ui.Item`s vs an app subclass/override hook vs a declarative "extra rows" parameter
    — as long as `PanelKit` owns the registry-derived buttons + the persistent-view invariants and the
    module names no weather component. This is the **most intricate seam in the phase** and is the
    primary research target.
  - **Why not relocate the location dropdown + forecast grid into the module too (Option b —
    rejected):** they are irreducibly WeatherBot UI (a reminder/Slack bot has neither) — baking them
    in trips the litmus and defeats the adapter-reuse goal.

### `custom_id` marker ownership + freeze (SEAM-07 SC#3)
- **D-04 [chosen: app-supplied marker prefix; the frozen `custom_id` byte strings asserted by a
  byte-string test]:** the panel `custom_id` byte strings (`wb:cmd:<name>`, `wb:loc:select`,
  `wb:fc:weekday:detailed`, …) are **frozen and asserted by a byte-string test** (SC#3). The **`wb:`
  marker is app-supplied** — `PanelKit` / the ownership test (`_is_owned_panel`, author + marker) take
  the marker/namespace **as a parameter** (or the app-contributed components carry their own
  custom_ids), so the module contains **no `wb:` literal**. WeatherBot keeps `wb:` byte-for-byte, so
  the already-pinned live panel keeps routing (no "interaction failed").
  - **`wb:` is a WeatherBot identifier** — baking it into the module would trip the litmus *and*
    prevent a reminder bot from owning its own panels under its own marker.
  - **Why not a module-default `wb:` the app can override (Option b — rejected):** a weather-flavored
    default literal still lives in the module source (litmus risk); make the marker a required
    app-supplied value with no weather default.

### `discord.py==2.7.1` pin location + freeze (SEAM-07 SC#3)
- **D-05 [chosen: exact `discord.py==2.7.1` in the module adapter package's dependencies]:** the
  adapter layer **owns the Discord coupling**, so the **exact pin lives in the module's deps**,
  tightening today's `discord.py>=2.7.1,<3` range (pyproject.toml:10). The app depends on the module
  and inherits the pinned Discord — so the live panel's `custom_id` routing stays on the exact
  version it was registered against (SC#3).
  - **Why not keep the range / pin only app-side (rejected):** the component that owns the persistent-
    view + `custom_id` contract must own the version that contract is valid against; a range re-opens
    the "interaction failed on a minor bump" risk the freeze exists to kill.
  - **Planner's discretion:** whether to *also* carry a belt-and-suspenders exact pin app-side or rely
    on the module dep transitively (within this single two-package wheel) — pick what keeps `uv.lock`
    + the Phase-28 split clean.

### `BotThread` + view-machinery relocation scope (SEAM-07 SC#1)
- **D-06 [chosen: relocate the gateway/persistent-view plumbing wholesale into the module adapter;
  keep the channel-config read + `render` + cosmetics app-injected]:** **into the module adapter** go
  the generic, weather-free plumbing — `BotThread` (thread+own-loop, start-after-READY, `finally`
  teardown), the operator gate (`operator_id`), `timeout=None` + `add_view` in `setup_hook`, the
  per-callback non-propagating failure-isolation envelope + `View.on_error`, the panel ownership test
  (author + app-supplied marker), and the create-before-delete summon orchestration (pin scan,
  no-zero-panel-window ordering). **App-injected / app-side:** the `holder.current().bot.panel_channel_id`
  read, the injected `render`, and the contributed cosmetic components (D-03). Command dispatch already
  routes through the Phase-26 `registry`/`dispatch`/`match` seams.
  - **Planner's discretion** on how `summon_panel` splits — the generic summon *orchestration* is
    module; the channel-config read + render + cosmetic-component construction are app-supplied
    (injected into the module orchestrator, or the module exposes the orchestration as a method the
    app's thin summon calls). The WR-01/WR-02 **clone-path polish survival** is re-guarded by the
    Phase-21 clone-render goldens byte-identically — any non-empty golden diff is a failure to
    investigate, never rubber-stamped.
  - **Why not leave `BotThread` app-side and relocate only `PanelKit` (Option b — rejected):**
    `BotThread`'s gateway lifecycle / operator gate / failure-isolation envelope are exactly the
    reusable adapter payoff SEAM-07 names ("the Discord adapter lives in the module"); leaving it
    app-side under-delivers the phase and re-couples the panel to an app-side host.

### Claude's Discretion
- **The module adapter sub-layout + naming** — a new `yahir_reusable_bot/discord/` (or
  `adapters/discord/`) package holding `BotThread` + `PanelKit` + `SelectedContext`, vs a flatter
  shape — guided by the existing `channels/` / `config/` / `scheduler/` / `lifecycle/` / `ports/` /
  `registry/` shapes and the ROADMAP's "adapter layer one level up from the channel-agnostic core."
- **The exact app-component-contributor mechanism (D-03)** — callables building extra `discord.ui.Item`s
  vs an app subclass/override hook vs a declarative extra-rows parameter. **Primary research target.**
- **The injected `render` callable's exact signature + how `SelectedContext[I]` is threaded** to it
  and to the app's cosmetic components — shaped by what keeps the panel renders byte-identical.
- **How `summon_panel` splits** between module orchestration and app-supplied channel-read/render/
  cosmetics (D-06), and how the operator gate / `panel_channel_id` are injected vs baked (note the
  existing v1 "operator_id baked at construction" deferral, bot.py:448 — preserve that behavior).
- **Where the `discord.py==2.7.1` exact pin sits** relative to the app dep (module-only vs also
  app-side belt-and-suspenders) and the `uv.lock` shape ahead of the Phase-28 split (D-05).
- **The precise form of the positive injection assertion** (extending Phase-25 D-05 / Phase-26 D-03 to
  the adapter: panel cosmetics + `render` are app-supplied, not baked) and the litmus-grep + `grimp`
  graph + isolated-import + core↔adapter isolation extensions for the new adapter edges.
- **Whether the byte-string `custom_id` freeze test lives app-side** (asserting WeatherBot's `wb:…`
  strings) **plus** a generic module test that the marker is parameterized — likely both.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & milestone contract
- `.planning/ROADMAP.md` § "Phase 27: Discord Adapter + PanelKit + Render-Cycle Fix" — the
  **pre-locked design** (relocate the Discord adapter `BotThread` + `PanelKit` + generic
  `SelectedContext[I]` to the module's adapter layer; `PanelKit` builds from the registry; `render`
  **injected** to fix the cycle **by ownership** — move `render_embed` app-side, not a deferred import;
  every v1.3 persistent-view / clone-path / `custom_id` invariant byte-identical; freeze `custom_id`s +
  `discord.py==2.7.1`) + the **4 locked success criteria** + the **Research flag: Yes** note.
- `.planning/ROADMAP.md` § "v2.0 Bot Module Extraction" milestone header + phase spine (leaf-seams-
  first, split-last) — why the Discord adapter is near-last (it consumes the Phase-26 registry *and*
  the Phase-24-relocated renderer's app-side home) and why the physical split defers to Phase 28; the
  **Reuse anchors** entry: `interactive/bot.py render_embed` + `interactive/panel.py PanelView` →
  Discord adapter + PanelKit, **cycle fix by DI**.
- `.planning/REQUIREMENTS.md` § **SEAM-07** (Discord adapter `BotThread` + `PanelKit` in the module;
  `PanelKit` builds from the registry; generic `SelectedContext`; `render` **injected**; cycle resolved
  by ownership not deferred import; operator gate + per-callback failure-isolation envelope + frozen
  `custom_id`s + `discord.py==2.7.1` preserved) + the **Cross-cutting acceptances** (PKG-01 on 23–27;
  APP-02 standing litmus grep; BHV-01/BHV-02 re-run every phase). Traceability: SEAM-07 → Phase 27.

### Prior-phase contracts this phase must honor
- `.planning/phases/26-command-registry-dispatcher-seam/26-CONTEXT.md` — the **registry/dispatch/match
  seam `PanelKit` builds from**: the module `CommandRegistry` + `build_registry` + `match_command`
  (now `yahir_reusable_bot/registry/`), the app's thin re-exporting `weatherbot/interactive/registry.py`
  singleton (the **import-time `registry.BY_NAME` read in the panel**, panel.py:98, that pinned
  Phase-26 D-03), the `bind`-closure dispatch context, and the **sanctioned app-side `takes_location`**
  (Phase-26 D-02) that D-02 here generalizes into `SelectedContext`.
- `.planning/phases/25-lifecycle-ready-gate-composition-root/25-CONTEXT.md` — **D-04** the single
  app-side `wiring.py build_runtime(...)` composition root (where the adapter is now assembled + the
  `render`/cosmetics/marker injected) and **D-05** the positive injection assertion pattern (extend
  here to the adapter's app-supplied UI + `render`); the start-after-READY lifecycle the gateway
  `BotThread` start is gated behind.
- `.planning/phases/24-config-hot-reload-engine/24-CONTEXT.md` — the per-tap `holder.current()` reload
  contract (panel.py:520 / bot.py:501 read config per tap) — the relocated panel must keep reading live
  config through the injected accessor, never a value captured at construction.
- `.planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-CONTEXT.md` — the Ports &
  Adapters / DI template, the **flat-sibling `yahir_reusable_bot/` layout**, the `grimp`-in-pytest
  import gate + isolated-import smoke + signatures-only litmus (basis for the new adapter-edge gates),
  and "adapt the orchestrator, don't rewrite it."
- `.planning/phases/21-characterization-golden-test-harness/21-CONTEXT.md` + `21-PATTERNS.md` — the
  golden oracle: the **panel-render + clone-render goldens + the `custom_id` byte snapshots + the
  exception-identity / restart-routing / operator-gate / isolation tests** that pin every invariant
  byte-identically; the discipline rule (any non-empty snapshot diff during extraction is a failure to
  investigate, never rubber-stamped).

### Source surfaces this phase moves / touches
- `weatherbot/interactive/bot.py` — `render_embed` (L194-~270, **moves app-side**, becomes the injected
  `render` — the 📍 / `BRIEFING_COLOR_INT` / `Updated <t:…>` / field-budget house style); `BotThread`
  (the gateway thread+own-loop, start-after-READY, `finally` teardown — **relocates to the module
  adapter**); the operator gate (`message.author.id != operator_id`, L461) + the failure-isolation
  envelope; `summon_panel` (L278-~390, the create-before-delete pin-scan orchestration + the **deferred
  `PanelView` import at L304-307 to be eliminated**, D-01); the `panel_channel_id` read (app-side).
- `weatherbot/interactive/panel.py` — `PanelView` (L282) + `_CommandButton` / the location `Select`
  (`wb:loc:select`, L251-270) / the forecast-grid buttons (`wb:fc:…`, L337-376) / the `_PANEL_MARKER =
  "wb:"` + `_is_owned_panel` (L137-174) / the clone-render path (L645-704) / the import-time
  `registry.BY_NAME` assert (L98) / the per-callback envelope + `render_embed` calls (L547, L614) /
  `_selected_location` (L323) / `spec.takes_location` (L512). **Splits: `PanelKit` + view machinery +
  `SelectedContext` + ownership test → module (marker parameterized, D-04); location dropdown + grid +
  📍/emoji + the injected `render` → app contributions (D-03).**
- `weatherbot/branding.py` — `BRIEFING_COLOR_INT` (the embed color `render_embed` reads — **app-side**,
  rides with `render_embed`).
- `weatherbot/scheduler/wiring.py` — `build_runtime(...)` the single composition root (Phase-25 D-04):
  now also assembles the adapter — injects `render`, the cosmetic components, the `wb:` marker, and
  `operator_id` / `panel_channel_id` into the module `BotThread` / `PanelKit`.
- `weatherbot/interactive/registry.py` (app thin singleton) + `yahir_reusable_bot/registry/` (module
  `CommandRegistry` / `build_registry` / `match_command`) — the registry `PanelKit` builds its command
  buttons from (Phase-26 seam); the panel's import-time `registry.BY_NAME` read must keep resolving.
- `weatherbot/interactive/dispatch.py` + `yahir_reusable_bot/registry/dispatch.py` — `dispatch_spec`
  (the shared seam the panel callbacks invoke, L547/L614 region) — unchanged contract, called from the
  relocated callbacks.
- `tests/test_panel.py` / `tests/test_bot.py` — the contractual panel + gateway suite (operator gate,
  per-callback isolation, clone-render polish, ownership test) proving behavior byte-identical through
  the relocation.
- `tests/` panel/clone-render goldens + `custom_id` byte snapshots (Phase-21 harness) — the oracle for
  SC#1/SC#3/SC#4; re-run + extend with the marker-parameterization + injection assertions.
- `tests/test_import_hygiene.py` — the mature 3-gate APP-02 litmus (`grimp` + isolated-import + AST
  noun scan, D-13-locked term set `weather|forecast|location|openweather|\buv\b|briefing`) — **re-run +
  extend** with the new adapter module edges, the **core↔adapter import-isolation check** (SC#2 — no
  deferred/in-function `render` import survives), and the **positive injection assertion** (panel
  cosmetics + `render` + marker app-supplied, not baked).
- `pyproject.toml` — L10 `discord.py>=2.7.1,<3` → **exact `==2.7.1` in the module adapter package's
  deps** (D-05); `[tool.hatch...packages]` (two-package wheel — the adapter is a new module subpackage);
  the `grimp` import-gate config + `[tool.coverage]` (must keep covering moved code).
- `yahir_reusable_bot/scheduler/engine.py` + `config/reload.py` + `registry/registry.py` — the
  constructor-injection + opaque-callable precedents `PanelKit`'s injected `render` + app-component
  contributor clone.

### Tooling docs (for the planner)
- `discord.py` 2.7.1 — persistent `View` (`timeout=None`, `add_view` in `setup_hook`), `View.on_error`,
  static `custom_id`, `discord.ui.Item`/`Select`/`Button` — https://discordpy.readthedocs.io/en/stable/
- `typing` — `Generic` / `TypeVar` (the generic `SelectedContext[I]`), `Callable` / `Protocol` (the
  injected `render` + app-component contributor), `dataclass(frozen=True)` —
  https://docs.python.org/3/library/typing.html
- `grimp` (the import-graph gate over the growing module, incl. the core↔adapter edge) —
  https://pypi.org/project/grimp/

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weatherbot/interactive/bot.py` `BotThread` + the operator gate + the per-callback failure-isolation
  envelope + `View.on_error` + start-after-READY/`finally`-teardown: the generic gateway adapter to
  relocate verbatim into the module — none of it names weather.
- `weatherbot/interactive/panel.py` `PanelView` + `_is_owned_panel` (author + marker) + the
  persistent-view registration (`timeout=None`, `add_view`, child custom_id length asserts) + the
  clone-render path: the `PanelKit` mechanism to relocate, with the `wb:` marker parameterized (D-04)
  and the weather UI (dropdown/grid/📍) factored out as app contributions (D-03).
- `weatherbot/interactive/bot.py` `render_embed` + `weatherbot/branding.py BRIEFING_COLOR_INT`: the
  weather/house-style embed builder that moves app-side and becomes the injected `render` (D-01).
- `yahir_reusable_bot/registry/` (`CommandRegistry` / `build_registry` / `match_command`, Phase 26):
  the registry `PanelKit` builds its command buttons from — already in the module.
- `yahir_reusable_bot/scheduler/engine.py` + `config/reload.py` + `registry/registry.py`: the
  constructor-injection + opaque-callable recipe to clone for `PanelKit(render=…, components=…)`.
- The Phase-21 panel/clone-render goldens + `custom_id` byte snapshots + operator-gate/isolation tests
  + the ~649-test suite: the standing byte-identical oracle.
- `tests/test_import_hygiene.py`: the mature 3-gate APP-02 litmus to re-run + extend with the
  core↔adapter isolation check + the positive injection assertion.

### Established Patterns
- **Engines/views take collaborators by constructor injection + drive opaque app callables** — D-01's
  injected `render` and D-03's app-component contributor are the panel-shaped instances of the
  `SchedulerEngine`/`ReloadEngine`/`CommandRegistry`/`bind` precedent.
- **App injects WeatherBot specifics into generic module mechanisms; the module never assembles the
  app** — the 📍/emoji/dropdown/grid + the `wb:` marker + `render` are injected at `wiring.py
  build_runtime`, never baked into `yahir_reusable_bot/**`.
- **Litmus is a negative grep over `yahir_reusable_bot/**`; the D-13-locked term set stays
  weather-specific** — generic adapter names (`PanelKit`/`SelectedContext`/`BotThread`/`render`/
  `marker`) are allowed; the *positive* injection assertion proves the cosmetics + `render` are
  app-supplied (extends Phase-25 D-05 / Phase-26 D-03 to the adapter).
- **Cycle fix by ownership, not deferral** — the module owns no embed house style; `render_embed`
  lives app-side and is injected, so the `panel→bot` top-import and the `bot→panel` deferred import
  both vanish (SC#2).
- **Per-tap `holder.current()` reload reads survive** — the relocated panel callbacks keep reading
  live config through the injected accessor, never a construction-time capture (Phase-24 contract).
- **Persistent-view discipline (Phase 18):** `timeout=None`, `add_view` in `setup_hook`, never
  add_item/remove_item post-registration, static `custom_id`s — preserved byte-identically through the
  relocation.

### Integration Points
- `weatherbot/scheduler/wiring.py build_runtime(...)` assembles the module `BotThread` / `PanelKit`,
  injecting `render` (app `render_embed`), the cosmetic components (location `Select` + forecast grid +
  📍/emoji), the `wb:` marker, and `operator_id` / `panel_channel_id`.
- `PanelKit` builds its command buttons from the Phase-26 module registry; the panel's import-time
  `registry.BY_NAME` read (panel.py:98) must keep resolving against the app's thin singleton.
- The relocated panel callbacks invoke the shared `dispatch_spec` seam and call the **injected**
  `render` (not the app `render_embed` directly), threading the generic `SelectedContext` so the app's
  render draws its 📍 line.
- The app keeps a byte-string `custom_id` freeze test (WeatherBot's `wb:…` strings); the module gains
  a generic test that the marker is parameterized + the injection/core↔adapter-isolation assertions.
- `pyproject.toml`: the new adapter module subpackage joins the two-package wheel; `discord.py` pins to
  exact `==2.7.1` in the module deps; `grimp` config + coverage extend to the adapter edges.

</code_context>

<specifics>
## Specific Ideas

- **Cycle fix is by ownership, NOT deferral.** The ROADMAP forbids a deferred import. `render_embed`
  moves app-side (it's weather house style: 📍, `BRIEFING_COLOR_INT`, `Updated <t:…>`) and is injected;
  the existing `bot.py:304-307` deferred `PanelView` import is eliminated by construction. SC#2's
  core↔adapter import-isolation check is the proof.
- **`wb:` is a WeatherBot identifier, not module vocabulary.** The marker is app-supplied (a required
  `PanelKit` parameter, no weather default); the module's source contains no `wb:` literal. WeatherBot
  keeps `wb:` byte-for-byte so the *already-pinned live panel* keeps routing — the frozen `custom_id`
  byte test guards exactly this (SC#3).
- **`render_embed` is irreducibly weather/house-style.** It draws the 📍 indicator, uses
  `BRIEFING_COLOR_INT`, stamps `Updated <t:…>`, and budgets fields for multi-day forecasts — there is
  no litmus-clean way to keep any of it in the module; the whole builder goes app-side and is injected.
- **The location dropdown + 2×2 forecast grid are irreducibly WeatherBot UI.** A reminder/Slack bot has
  neither — they must be app-contributed components (D-03), never module surface. Only the
  registry-derived command buttons + the persistent-view contract are generic.
- **Hot-reload contract survives the move.** The panel reads config per tap via `holder.current()`
  (panel.py:520) — the relocated callbacks keep reading live config through the injected accessor.
- **The clone-path polish (WR-01/WR-02) is the highest-risk regression class** — 📍 / emoji / `Updated
  <t:…>` must survive every ack/collapse/re-render byte-identically; the Phase-21 clone-render goldens
  re-guard it, and any non-empty diff is investigated, never rubber-stamped.

</specifics>

<deferred>
## Deferred Ideas

- **Physical repo split to `YahirReusableBot` + uv git dependency + EXTENSION-GUIDE + live `yahir-mint`
  restart UAT** — **Phase 28** (strictly last). The adapter's `render` / cosmetic-component / marker /
  `discord.py` pin injection points become documented plug points in the EXTENSION-GUIDE.
- **Uniform/declarative app-component contribution framework** beyond what this phase needs (a full
  "panel layout DSL") — out of scope; D-03 lands the minimal contributor seam that keeps the module
  weather-free. Revisit only if a third bot needs richer panel composition.
- **Re-reading `operator_id` from `holder.current()` per message** (lifting the v1 "baked at
  construction" deferral, bot.py:448) — explicitly deferred in v1; preserve current behavior, do not
  fix here.
- **Slash-command / non-text adapter surface** — SEAM-07 is the *button-panel + gateway text* adapter;
  a future slash/interactions adapter is a separate capability, not this phase.
- **Broadening the litmus term set** — rejected; the D-13-locked term set stays weather-specific.
  Generic adapter names (`PanelKit`/`SelectedContext`/`BotThread`/`render`/`marker`) are exactly what
  the module exposes.

None of these are scope creep — they are alternatives/extensions within the extraction domain,
consciously placed in their correct later phase.

</deferred>

---

*Phase: 27-discord-adapter-panelkit-render-cycle-fix*
*Context gathered: 2026-06-29*
