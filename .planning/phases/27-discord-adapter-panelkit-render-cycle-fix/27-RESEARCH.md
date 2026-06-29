# Phase 27: Discord Adapter + PanelKit + Render-Cycle Fix - Research

**Researched:** 2026-06-29
**Domain:** Brownfield byte-identical extraction — relocate the Discord gateway adapter (`BotThread`) + persistent-view machinery (`PanelKit`) into the `yahir_reusable_bot` module's new adapter layer, resolve the `render_embed`↔`PanelView` import cycle by ownership, parameterize the `wb:` marker + `SelectedContext[I]`, pin `discord.py==2.7.1` in the module.
**Confidence:** HIGH (this is a relocation of code I read in full; the runtime stack is unchanged; the patterns are already-shipped module precedents)

## Summary

This is a **pure relocation phase, not a redesign**. Every mechanism that moves already exists in `weatherbot/interactive/{bot.py,panel.py}` and was read in full for this research. The intricate work is not *inventing* the seams — it is *cutting* the existing code along the generic/app boundary so the module names no weather concept, while the Phase-21 goldens (`custom_id` byte snapshot, panel/clone-render goldens, operator-gate/isolation tests) stay byte-identical. The six CONTEXT decisions (D-01..D-06) are LOCKED; this research surfaces the implementation-level facts the planner needs to execute them.

The crux (SEAM-07 SC#2) is mechanically simple once the ownership cut is made: `panel.py` has a **module-top** `from weatherbot.interactive.bot import render_embed` (L54), and `bot.py` breaks the back-edge with a **deferred in-function** `from weatherbot.interactive.panel import PanelView` (two sites: L307 inside `_handle_panel_summon`, L583 inside `setup_hook`). Moving `render_embed` app-side and injecting it as an opaque `render` callable removes the panel→bot top import; constructing the module panel at the app's composition root (`wiring.py build_runtime`) with `render` + cosmetics injected removes the need for either deferred import. Neither edge survives — provable by the existing grimp gate plus a new core↔adapter isolation check.

**Primary recommendation:** Create `yahir_reusable_bot/discord/` holding `panelkit.py` (the generic `PanelKit` view machinery + ownership test, marker parameterized), `selection.py` (the generic `SelectedContext[I]`), and `gateway.py` (the relocated `BotThread` + `build_client` + the generic summon *orchestration*). Keep `render_embed`, the `LocationSelect`/`ForecastButton` cosmetic components, the 📍/emoji, the `wb:` marker literal, and the `panel_channel_id`/`operator_id` reads entirely app-side in `weatherbot/interactive/`, injected at `wiring.py build_runtime`. Use the **app-supplied component-builder callables** mechanism for D-03 (not a subclass hook) — it is the closest fit to the module's established constructor-injection + opaque-callable precedent and the only option that keeps `add_view`-in-`setup_hook` persistence intact without the module ever naming a weather component.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 [Render-cycle resolution — the crux, SEAM-07 SC#2]:** Move `render_embed` app-side and inject it as an opaque `render` callable; kill the deferred import. The generic signature drops the weather noun — the callable receives the `CommandReply` + the generic `SelectedContext[I]`, **not** a `location=` kwarg. The current `bot.py:304-307` deferred `from ...panel import PanelView` is eliminated by construction (app-side summon constructs the module panel with app `render` + cosmetics injected). Proven by a core/adapter import-isolation check. *Rejected:* keeping the deferred import (ROADMAP forbids it); a thin generic `render` in the module + app passes only colors/style (re-introduces a weather-shaped contract under a generic name).

- **D-02 [`SelectedContext[I]` — the generic selection, SEAM-07 SC#4]:** Module ships a small **generic** `SelectedContext[I]` (typed holder for the currently selected item of type `I`) replacing today's hardcoded `_selected_location: str` (panel.py:323). The panel holds/threads it opaquely; the app's `render` + components read `.value` (the selected location `str`). WeatherBot uses `SelectedContext[str]`. The one surviving `spec.takes_location` (panel.py:512) generalizes to an **app-supplied datum on the spec/`bind`**, read by the app, not by the module naming "location." *Rejected:* a bare `Any`/untyped slot (forfeits the typed-reuse payoff).

- **D-03 [Generic-vs-app UI split — SEAM-07 SC#1, APP-02 — the PRIMARY research target]:** `PanelKit` owns the registry-derived command buttons + the persistent-view invariants (`timeout=None`, `add_view`, child custom_id length asserts, the clone-render path). The app supplies its cosmetic UI (location `Select`, 2×2 forecast grid, emoji) + the injected `render` through an **app-component-contributor seam**. The module hardcodes no "location Select" and no "forecast grid"; `weatherbot/interactive/panel.py` shrinks to the cosmetic contributions + `render`. **Planner's discretion on the exact contributor mechanism** (callables building `discord.ui.Item`s vs subclass/override hook vs declarative extra-rows). *Rejected:* relocating the dropdown + grid into the module (irreducibly WeatherBot UI — trips the litmus).

- **D-04 [`custom_id` marker ownership + freeze — SEAM-07 SC#3]:** The panel `custom_id` byte strings (`wb:cmd:<name>`, `wb:loc:select`, `wb:fc:weekday:detailed`, …) are frozen and asserted by a byte-string test. The **`wb:` marker is app-supplied** — `PanelKit`/the ownership test (`_is_owned_panel`, author + marker) take the marker/namespace as a parameter (or app-contributed components carry their own custom_ids), so the module contains **no `wb:` literal**. WeatherBot keeps `wb:` byte-for-byte. *Rejected:* a module-default `wb:` the app can override (a weather-flavored default literal still lives in module source).

- **D-05 [`discord.py==2.7.1` pin location + freeze — SEAM-07 SC#3]:** Exact `discord.py==2.7.1` in the **module adapter package's dependencies**, tightening today's `discord.py>=2.7.1,<3` (pyproject.toml:10). The app depends on the module and inherits the pinned Discord. *Rejected:* keep the range / pin only app-side (the component owning the persistent-view + custom_id contract must own the version it is valid against). **Planner's discretion:** whether to also carry a belt-and-suspenders exact pin app-side or rely on the module dep transitively — pick what keeps `uv.lock` + the Phase-28 split clean.

- **D-06 [`BotThread` + view-machinery relocation scope — SEAM-07 SC#1]:** Into the module adapter go the generic, weather-free plumbing — `BotThread` (thread+own-loop, start-after-READY, `finally` teardown), the operator gate (`operator_id`), `timeout=None` + `add_view` in `setup_hook`, the per-callback non-propagating failure-isolation envelope + `View.on_error`, the panel ownership test (author + app-supplied marker), and the create-before-delete summon orchestration. **App-injected / app-side:** the `holder.current().bot.panel_channel_id` read, the injected `render`, the contributed cosmetic components. **Planner's discretion** on how `summon_panel` splits. Preserve the v1 "operator_id baked at construction" deferral (bot.py:448 — do NOT lift it). *Rejected:* leave `BotThread` app-side and relocate only `PanelKit` (under-delivers SEAM-07).

### Claude's Discretion

- The module adapter sub-layout + naming (`yahir_reusable_bot/discord/` vs `adapters/discord/` vs flatter) — guided by existing `channels/` / `config/` / `scheduler/` / `lifecycle/` / `ports/` / `registry/` shapes.
- The exact app-component-contributor mechanism (D-03). **Primary research target.**
- The injected `render` callable's exact signature + how `SelectedContext[I]` is threaded.
- How `summon_panel` splits between module orchestration and app-supplied channel-read/render/cosmetics (D-06); how operator gate / `panel_channel_id` are injected vs baked (preserve the bot.py:448 baked-at-construction `operator_id` behavior).
- Where the `discord.py==2.7.1` exact pin sits relative to the app dep (module-only vs also app-side); the `uv.lock` shape ahead of the Phase-28 split.
- The precise form of the positive injection assertion (panel cosmetics + `render` + marker app-supplied); the litmus-grep + grimp graph + isolated-import + core↔adapter isolation extensions.
- Whether the byte-string `custom_id` freeze test lives app-side **plus** a generic module test that the marker is parameterized — likely both.

### Deferred Ideas (OUT OF SCOPE)

- Physical repo split to `YahirReusableBot` + uv git dependency + EXTENSION-GUIDE + live `yahir-mint` restart UAT → **Phase 28** (strictly last).
- A uniform/declarative app-component contribution framework (a "panel layout DSL") beyond the minimal contributor seam — revisit only if a third bot needs richer composition.
- Re-reading `operator_id` from `holder.current()` per message (lifting the v1 baked-at-construction deferral, bot.py:448) — preserve current behavior, do NOT fix here.
- Slash-command / non-text adapter surface — separate capability, not this phase.
- Broadening the litmus term set — rejected; the D-13-locked term set stays weather-specific.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEAM-07 | The Discord adapter (isolated gateway `BotThread` + `PanelKit`) lives in the module; `PanelKit` builds the control surface from the registry, exposes a generic `SelectedContext`, takes the result `render` as an injected callable — resolving the `render_embed`↔`PanelView` cycle by ownership (not a deferred import). Operator gate, per-callback failure-isolation envelope, frozen `custom_id`s, and `discord.py==2.7.1` pin preserved. | Architectural Responsibility Map (tier ownership); Architecture Patterns 1–4 (contributor seam, render signature, summon split, marker parameterization); Don't Hand-Roll (reuse shipped mechanisms verbatim); Validation Architecture (golden oracle + new isolation/injection assertions); the four cross-cutting acceptances below |

**Cross-cutting acceptances re-run this phase (anchored elsewhere, enforced here):**

| ID | Acceptance | Research Support |
|----|-----------|------------------|
| PKG-01 | Module imports zero app code (grimp-in-pytest + isolated-import smoke), extended to the new adapter edges + the core↔adapter isolation check | Validation Architecture → "New gates"; `tests/test_import_hygiene.py` auto-scales via `startswith(MODULE)` / `walk_packages` |
| APP-02 | Litmus grep (no weather noun in module public surface) + the **positive injection assertion** (cosmetics + render + marker app-supplied, not baked) | `tests/test_injection_registry.py` already stubs Phase-27 leak points (lines 225-304); extend with the marker + contributor + `render`-injection assertions |
| BHV-01 | Full pre-existing suite stays green at the phase boundary (no skips, no weakened assertions) | The ~649-test suite + `tests/test_panel.py` + `tests/test_bot.py` re-run unchanged |
| BHV-02 | Goldens pin observable outputs (embed fields+order, panel `custom_id`s) and are the byte-identical oracle | `tests/test_golden_custom_ids.py`, `tests/test_golden_embeds.py`, the panel/clone-render goldens (Phase-21 harness) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Gateway connection lifecycle (`BotThread`: own thread+loop, start-after-READY, `finally` teardown, `is_alive`/`stop`) | **Module adapter** (`yahir_reusable_bot/discord/gateway.py`) | — | Pure Discord plumbing; names no weather concept. D-06 relocates wholesale. |
| Operator gate (`interaction_check`: bot reject, non-operator reject, identity-free ephemeral, reject log) | **Module adapter** (`PanelKit`) | App injects `operator_id` | `operator_id` is a generic int; the gate logic names no weather. Preserve the WR-03 intentional asymmetry (bot reject sends NO ephemeral). |
| Persistent-view registration (`timeout=None`, `add_view` in `setup_hook`) | **Module adapter** (`gateway.py` + `PanelKit`) | — | Phase-18 discipline; the persistence contract belongs with the version pin (D-05). |
| Registry-derived command buttons (`CmdButton`, `wb:cmd:<name>`) | **Module adapter** (`PanelKit`) | App injects the marker + the Phase-26 registry | `PanelKit` builds the command surface FROM the registry (already in module). The button row is generic; only the `wb:` prefix is app-supplied (D-04). |
| Clone-render path (`_render_view`/`_clone_child`: the single child-cloning path, disabled-cue ack) | **Module adapter** (`PanelKit`) | App-contributed components must be re-cloneable through the same path | The live-routing trap (panel.py:659-674) is generic discord.py mechanics. The module's clone path must re-clone app-contributed items too (see Pattern 1). |
| Per-callback failure-isolation envelope + `View.on_error` backstop + `_safe_error_edit` | **Module adapter** (`PanelKit`) | — | Generic robustness; names no weather. |
| Create-before-delete summon orchestration (pin scan, no-zero-panel-window ordering) | **Module adapter** orchestrator | App injects `panel_channel_id` read + the channel + the idle-embed `render` | The *ordering* is generic; the channel resolution + permission-copy strings + idle embed are app-side (D-06). |
| Panel ownership test (`_is_owned_panel`: author + marker) | **Module adapter** | App injects the marker (`wb:`) | Author check is generic; the marker is app-supplied (D-04). |
| `render_embed` (📍 line, `BRIEFING_COLOR_INT`, `Updated <t:…>` stamp, WR-02 field-budget splitting) | **App** (`weatherbot/interactive/`) | Module invokes it opaquely as `render` | Irreducibly weather/house-style (D-01). Whole builder goes app-side. |
| Location dropdown (`LocationSelect`, `wb:loc:select`), 2×2 forecast grid (`ForecastButton`, `wb:fc:…`), 📍/emoji cosmetics | **App** (contributed components) | Module hosts them via the contributor seam | Irreducibly WeatherBot UI (D-03). A reminder/Slack bot has neither. |
| `panel_channel_id` config read, forecast grammar (`ForecastFlags`) | **App** | — | App config concern; already app-side from Phase 26. |
| Selected-item state | **Module** holds `SelectedContext[I]` opaquely | App's components set `.value`, app's `render` reads `.value` | D-02: generic holder, app-typed `[str]`. |

## Standard Stack

This phase introduces **no new packages**. It relocates existing code and tightens one version constraint. The "stack" is the already-installed, already-pinned set.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | **==2.7.1** (tighten from `>=2.7.1,<3`) | Gateway client + persistent-view component surface | `[VERIFIED: installed]` `python -c "import discord; print(discord.__version__)"` → `2.7.1`; `[VERIFIED: uv.lock]` `discord-py 2.7.1`. The persistent-view `custom_id` routing contract is valid only against the exact version the live panel was registered against — D-05 moves the exact pin into the module adapter deps. |
| grimp | 3.14 | Import-graph gate (dev-only) — extended to the new adapter edges + core↔adapter isolation | `[VERIFIED: uv.lock]` `grimp 3.14`. Already the PKG-01 gate engine in `tests/test_import_hygiene.py`. |
| typing (stdlib) | 3.12+ | `Generic`/`TypeVar` for `SelectedContext[I]`; `Callable`/`Protocol` for the injected `render` + contributor; `dataclass(frozen=True)` | `[VERIFIED: codebase]` The module already ships `ConfigHolder(Generic[T])` with an unbound `TypeVar` (`yahir_reusable_bot/config/holder.py:35-43`) — the exact precedent `SelectedContext[I]` clones. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | 26.x | The reject log + failure-isolation logs in the relocated callbacks | Already used in both `bot.py` and `panel.py`; rides the relocation unchanged. |
| pytest / syrupy | 9.0.3 / 5.3.4 | The golden oracle (`custom_id` byte snapshot, embed goldens, clone-render goldens) + the new isolation/injection asserts | `[VERIFIED: pyproject.toml]` dev group. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| App-supplied component-builder callables (D-03) | App subclass/override hook on a module base `View` | Subclassing re-introduces an inheritance contract across the (eventual) repo boundary; the module's whole established idiom is **constructor injection of opaque callables, zero inheritance** (`ConfigHolder` `TypeVar` unbound "ships NO base class"; `SchedulerEngine`/`ReloadEngine`/`CommandRegistry` take collaborators by arg). A subclass hook also makes `add_view(PanelKit(...))` register the app subclass — blurring the litmus boundary. **Pick the callable seam.** |
| Module-owned exact `==2.7.1` pin (D-05) | Keep `>=2.7.1,<3` range | A range re-opens the "interaction failed on a minor bump" risk the freeze exists to kill (custom_id routing). |

**Installation:** None. Tighten the existing constraint in the new module-adapter dep location (D-05).

**Version verification:** `[VERIFIED: installed]` discord.py 2.7.1 confirmed importable at the pinned version; no install needed.

## Package Legitimacy Audit

> No external packages are installed in this phase. The only dependency change is tightening an **already-present, already-locked** constraint (`discord.py` `>=2.7.1,<3` → `==2.7.1`) and relocating where that constraint is declared (D-05). No new package enters the dependency tree.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| discord.py | PyPI (`discord-py`) | mature (10+ yrs) | millions/wk | github.com/Rapptz/discord.py | OK (already pinned + locked) | Constraint tightened only — no new install |
| grimp | PyPI | mature | — | github.com/seddonym/grimp | OK (already dev dep) | Unchanged |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                         App composition root
                  weatherbot/scheduler/wiring.py :: build_runtime
                  (the ONE greppable injection site, APP-01/APP-02)
                                   │
            injects: render (=render_embed), cosmetic-component builders,
                     marker="wb:", operator_id, panel_channel_id reader
                                   │
                                   ▼
        ┌──────────────────── MODULE ADAPTER ────────────────────────┐
        │           yahir_reusable_bot/discord/                        │
        │                                                              │
        │  gateway.py                                                  │
        │   BotThread ── own thread+loop, start-after-READY, finally   │
        │      │            teardown, LoginFailure isolation           │
        │      ▼                                                       │
        │   build_client ── intents, on_message, setup_hook            │
        │      │  setup_hook: client.add_view(PanelKit(...))  ← persist│
        │      │                                                       │
        │   summon orchestration ── pin-scan, create-before-delete,    │
        │      │   ownership test (author + injected marker)           │
        │      ▼                                                       │
        │  panelkit.py :: PanelKit(discord.ui.View, timeout=None)      │
        │   ├─ registry-derived CmdButtons (from Phase-26 registry)    │
        │   ├─ holds SelectedContext[I]  (selection.py, Generic)       │
        │   ├─ interaction_check (operator gate, identity-free reject) │
        │   ├─ per-callback envelope + View.on_error backstop          │
        │   ├─ _render_view / _clone_child  (the single clone path)    │
        │   └─ hosts APP-CONTRIBUTED items via contributor callables   │
        └────────────────────────────┬─────────────────────────────────┘
                                      │ invokes opaquely
        ┌─────────────────────────────▼─────────────────── APP ──────┐
        │  weatherbot/interactive/                                    │
        │   render(reply, ctx: SelectedContext[str]) -> discord.Embed │  (was render_embed)
        │   LocationSelect (wb:loc:select)  sets ctx.value            │
        │   ForecastButton (wb:fc:…)  reads ctx.value                 │
        │   📍 / emoji / BRIEFING_COLOR_INT / Updated <t:…> stamp     │
        └─────────────────────────────────────────────────────────────┘

  Command interaction routing (unchanged): a tap → registry.BY_NAME[name]
  → dispatch_spec (Phase-26 module seam) → CommandReply → injected render → embed
```

### Recommended Project Structure

Following the existing flat-sibling module shape (`channels/`, `config/`, `scheduler/`, `lifecycle/`, `ports/`, `registry/` — each a package with `__init__.py` re-exporting its public surface), add a new sibling package. **Recommend `yahir_reusable_bot/discord/`** (descriptive of the adapter's technology, parallel to how `channels/` names its concern). The CONTEXT offered `adapters/discord/` as an alternative; the flatter `discord/` matches the existing one-level-deep convention every other seam uses.

```
yahir_reusable_bot/
├── channels/          # SEAM-01 (existing)
├── config/            # SEAM-04 (existing)
├── scheduler/         # SEAM-02 (existing)
├── lifecycle/         # SEAM-05 (existing)
├── ports/             # (existing)
├── registry/          # SEAM-06 (existing — PanelKit builds buttons from here)
├── reliability/       # (existing)
└── discord/           # SEAM-07 (NEW adapter layer)
    ├── __init__.py    # re-export PanelKit, SelectedContext, BotThread, build_client
    ├── gateway.py     # BotThread + build_client + summon orchestration
    ├── panelkit.py    # PanelKit(discord.ui.View) + ownership test + clone path
    └── selection.py   # SelectedContext[I]  (Generic[I], frozen-ish holder)
```

> **Naming caution (litmus):** `discord/` is a generic technology name (allowed). Inside it, NO `def`/`class`/param/annotation may carry `weather|forecast|location|openweather|\buv\b|briefing`. The relocated `BotThread` and operator gate already name no weather (verified by reading `bot.py`); the panel's weather names (`LocationSelect`, `ForecastButton`, `_selected_location`, `render_embed`, `_LOCATION_CMDS`, `_FORECAST_CMDS`, `_EMOJI`, `📍`) all stay app-side.

App side shrinks but stays in `weatherbot/interactive/`:
```
weatherbot/interactive/
├── bot.py             # render_embed STAYS here (D-01); BotThread/build_client/summon REMOVED (moved to module)
├── panel.py           # SHRINKS to: LocationSelect, ForecastButton, the cosmetic builders,
│                      #   the wb: custom_id literals, the contributor functions handed to PanelKit
└── …                  # registry.py (thin singleton), dispatch.py, command.py unchanged
```

### Pattern 1: App-component-contributor via injected builder callables (D-03 — PRIMARY)

**What:** `PanelKit.__init__` takes a list of app-supplied **builder callables**, each of which constructs and returns the `discord.ui.Item`(s) the app wants in the panel (the `LocationSelect`, the four `ForecastButton`s). `PanelKit` builds its own registry-derived `CmdButton`s, then calls each contributor to get the app's items, and `add_item`s them all in `__init__` (before any `add_view`, preserving Phase-18 discipline).

**When to use:** This is the locked mechanism shape for D-03 (callables, not subclassing).

**Why this shape (vs the rejected subclass hook):**
- The module's whole established idiom is constructor-injection of opaque callables with **zero inheritance** (`ConfigHolder` `TypeVar` is unbound: *"the module ships NO base class for apps to subclass"*, holder.py:6-8; `SchedulerEngine(scheduler)`, `ReloadEngine(holder, validate=…, desired_jobs=…)`, `CommandRegistry(specs)` all take collaborators by arg). The contributor seam is the panel-shaped instance of that precedent — exactly what the CONTEXT "Established Patterns" calls out.
- `add_view(PanelKit(...))` registers a **module** class instance, not an app subclass — keeping the litmus boundary clean (the module names `PanelKit`, never a weather subclass).

**The load-bearing constraint — the clone path must re-clone app-contributed items (panel.py:659-724):** This is the highest-risk mechanism in the relocation. discord.py routes component interactions by `message_id` FIRST, and `edit_message(view=clone)` binds the clone to the panel message — so every tap after the first render dispatches to the clone's children, NOT the persistent `add_view`-registered `self`. If a clone carries a plain `discord.ui.Button`/`Select` (whose base `callback` is a no-op `pass` in discord.py 2.7.1), the panel goes DEAD after the first tap with no log. Today's cure (`_clone_child`) rebuilds each child from its REAL subclass bound to `self`. **In the relocated design the module's `_clone_child` cannot `isinstance`-check `LocationSelect`/`ForecastButton` (those are app classes the module must not name).** Two viable approaches:

- **(a) Clone callables travel with the contributed item.** Each contributor returns not just the item but a re-clone callable (e.g. the contributor is itself the clone factory — `PanelKit` calls it once for the canonical view and again per render). The module stores the contributor list and re-invokes them in `_render_view` exactly as it re-invokes the `CmdButton` builders. This generalizes today's `_clone_child` branches into "call the builder again" — no `isinstance` on app types.
- **(b) Items expose a generic `clone()` method (a small module Protocol `ClonableItem`).** The module's `_clone_child` calls `child.clone(disabled=…)`; app items implement it. This adds a module-named Protocol (generic name — allowed) but requires app items to inherit/implement it.

**Recommend (a)** — it is pure callable injection, needs no Protocol, and maps one-to-one onto today's `_render_view` loop (which already rebuilds every child via the subclass ctors). The module's `_render_view` becomes: rebuild the registry-derived `CmdButton`s + re-invoke each app contributor → `add_item` each → apply `disabled` post-construction. **`disabled` must be applied post-construction** (today's ctors take no `disabled` param — panel.py:688-690); preserve that.

**Example (the contributor seam, module side):**
```python
# Source: derived from weatherbot/interactive/panel.py:326-381 (__init__) + 676-692 (_render_view)
# yahir_reusable_bot/discord/panelkit.py
from typing import Callable
import discord

# A contributor builds the app's items for ONE render. Called once for the canonical
# add_view'd view and again per clone-render — exactly how _render_view rebuilds today.
ItemContributor = Callable[["SelectedContext"], list[discord.ui.Item]]

class PanelKit(discord.ui.View):
    def __init__(
        self,
        *,
        registry,                       # the Phase-26 CommandRegistry (command buttons)
        command_names: tuple[str, ...], # the curated ordered button names (app-supplied)
        marker: str,                    # D-04 — REQUIRED, no weather default ("wb:")
        operator_id: int,               # D-06 — baked at construction (preserve v1)
        selection: "SelectedContext",   # D-02 — the generic selected-item holder
        contributors: list[ItemContributor],  # D-03 — app builds Select/grid here
        render: Callable,               # D-01 — opaque app embed builder
    ) -> None:
        super().__init__(timeout=None)  # REQUIRED for persistence (Phase-18 D-10)
        self._marker = marker
        ...
        self._build_children()          # add CmdButtons + invoke contributors, add_item all

    def _render_view(self, *, disabled: bool = False) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        for child in self._rebuild_children():   # registry buttons + contributor outputs
            child.disabled = disabled            # post-construction (ctors take no disabled)
            view.add_item(child)
        return view
```

**Anti-patterns to avoid here:**
- **Do NOT** add/remove items post-`add_view` registration (Phase-18 discipline — every `custom_id` must be registered at `setup_hook` time, or the post-restart tap routing breaks).
- **Do NOT** let the module `isinstance`-check an app component class.
- **Do NOT** concatenate emoji into labels (panel.py:117-120: emoji is a SEPARATE `emoji=` param; the app contributors keep that).

### Pattern 2: The injected `render` signature + `SelectedContext[I]` threading (D-01, D-02)

**What:** `render_embed(reply, *, location=arg)` (panel.py:547,614 callers; defined bot.py:194) becomes the app symbol `render`, invoked by the module with the generic context. The module names no `location=`.

**Recommended signature:**
```python
# Module invokes:  render(reply, ctx)  where ctx: SelectedContext[I]
# App implements (weatherbot/interactive/bot.py — stays here, D-01):
def render(reply: CommandReply, ctx: SelectedContext[str]) -> discord.Embed:
    # the app pulls the selected item to draw its own 📍 line; argless replies pass
    # a ctx whose .value is None (or a sentinel) so the indicator auto-suppresses.
    location = ctx.value
    ...  # the EXACT body of today's render_embed (BRIEFING_COLOR_INT, Updated <t:…>, WR-02 split)
```

**The argless-suppression nuance (load-bearing for the embed golden):** today `render_embed(reply, location=arg)` passes `arg = self._selected_location if spec.takes_location else None` (panel.py:512), and `render_embed` suppresses the 📍 line when `location is None` (bot.py:221). The forecast path always passes `self._selected_location` (panel.py:614). In the relocated design the module passes the same `SelectedContext`, but the **app's `bind`/spec must carry whether the command consumes the context** (D-02's generalization of `spec.takes_location`). Two ways to preserve byte-identical 📍 suppression:
- The module reads an app-supplied `spec` datum (the generalized `takes_location`) to decide whether to pass `ctx` with `.value` set or a context whose `.value` is `None`; OR
- The module always passes the live `ctx`, and the **app's `render`** decides suppression from a per-spec flag it closes over.

**Recommend** the module threads the live `ctx` plus the app-supplied per-spec consumes-context datum (the generalized `takes_location`, re-added app-side per Phase-26 D-02's sanctioned `takes_location`/`meta`), and constructs the `ctx` it passes to `render` with `.value = ctx.value if consumes else None`. This keeps `render` itself free of dispatch logic and reproduces today's exact 📍 on/off behavior. **The embed golden (`tests/test_golden_embeds.py`) + `test_render_embed_indicator_suppressed_when_argless` (test_bot.py:789) are the oracle** — any 📍 change fails them.

**`SelectedContext[I]` (module, `selection.py`):**
```python
# Source: clones yahir_reusable_bot/config/holder.py:35-43 (ConfigHolder Generic[T] precedent)
from typing import Generic, TypeVar
I = TypeVar("I")            # unbound — no module base class (the holder precedent)

class SelectedContext(Generic[I]):
    """A typed holder for the panel's currently selected item of type I (D-02)."""
    def __init__(self, value: I) -> None:
        self._value: I = value
    @property
    def value(self) -> I:
        return self._value
    def set(self, value: I) -> None:
        self._value = value
```
WeatherBot uses `SelectedContext[str]`; the app's `LocationSelect.callback` calls `ctx.set(self.values[0])` (replacing `self._panel._selected_location = value`, panel.py:488). **Keep the Pitfall-3 discipline** (button callbacks read `ctx.value`, NEVER re-read `Select.values` — panel.py:570).

### Pattern 3: The `summon_panel` split (D-06)

**What:** `_handle_panel_summon` (bot.py:276-399) splits into a generic module orchestrator + a thin app summon.

**Generic (module orchestrator):** the pin-scan (`[m async for m in channel.pins() if owned(m)]`), the create-before-delete ordering (`channel.send` + `msg.pin()` FIRST, then delete prior owned, no zero-panel window — bot.py:368-390), the ownership test (`_is_owned_panel`, author + injected marker), the per-write `discord.Forbidden` backstop (bot.py:391-399), and the permission preflight loop over a passed-in required-perm set.

**App-side (injected):** the `holder.current().bot.panel_channel_id` read + channel resolution (bot.py:309-341, including the duck-type `hasattr(channel, "pins")` check), all operator-feedback copy strings (bot.py:105-136 — these name `[bot] panel_channel_id` and are weather-app config concerns), the idle embed (`render(CommandReply(title=_PANEL_IDLE_TITLE, …))`, bot.py:364-366), and the panel-factory (`_build_view`, which constructs the `PanelKit` with app cosmetics injected — bot.py:356-362).

**Recommend** the module exposes the orchestration as a method/function the app's thin summon calls, passing: the resolved channel, the required-perm set, the owned-panel predicate (marker-bound), the panel-factory callable, and the idle embed. The module owns the ordering; the app owns every weather/config string. **`_REQUIRED_PANEL_PERMS` + `_PANEL_PERM_LABELS` (bot.py:78-95)** are arguably generic (they name Discord permissions, not weather) — the planner may relocate the perm-set constant to the module but MUST keep the operator-copy strings app-side.

### Pattern 4: Marker parameterization (D-04)

**What:** `_PANEL_MARKER = "wb:"` (panel.py:141) and the `wb:cmd:`/`wb:loc:`/`wb:fc:` custom_id builders. The module takes the marker as a required `PanelKit` param; the module source contains NO `wb:` literal.

**The cut:**
- **Module:** `CmdButton` builds `custom_id=f"{marker}cmd:{name}"` (marker injected). `_is_owned_panel` uses `cid.startswith(self._marker)`.
- **App:** `LocationSelect` (`custom_id="wb:loc:select"`) and `ForecastButton` (`custom_id="wb:fc:weekday:detailed"` etc.) carry their own full literal custom_ids — they are app-contributed components, so their `wb:` literals legitimately live app-side. The app passes `marker="wb:"` to `PanelKit` for the command buttons + ownership test.
- **Freeze test:** keep `tests/test_golden_custom_ids.py` app-side (it asserts WeatherBot's `wb:…` byte strings via the snapshot, built through the real `PanelKit` + app contributors). **ADD a generic module test** that `PanelKit` with `marker="X:"` produces `X:cmd:<name>` ids and contains no `wb:` literal (grep the module source).

> **Byte-identical custom_id ordering is load-bearing.** `test_golden_custom_ids.py:53` joins `[c.custom_id for c in view.children]` by newline and pins the raw bytes — a reordered child fails. The relocated `PanelKit._build_children` MUST add items in the exact today order: row 0 `wb:loc:select`, row 1 `wb:cmd:{weather,uv,next-cloudy,sun,wind}`, row 2 `wb:cmd:{status,alerts}`, row 3 `wb:fc:weekday:{detailed,compact}`, row 4 `wb:fc:weekend:{detailed,compact}` (panel.py:326-381). With command buttons module-built and Select/grid app-contributed, the **interleaving order** (Select row 0, command rows 1-2, grid rows 3-4) must be reproduced by how `PanelKit` orders "registry buttons vs contributors." Recommend the contributor list + a row/position contract so the canonical view's child order is byte-stable.

### Anti-Patterns to Avoid
- **Re-baselining a golden because it changed.** Any non-empty diff on the `custom_id` byte snapshot, the embed goldens, or the clone-render goldens is a **failure to investigate**, never rubber-stamped (Phase-21 discipline; CONTEXT D-06).
- **A deferred/in-function import surviving** (`from weatherbot…import render_embed` or `from …panel import PanelView`). SC#2 requires BOTH edges gone. The core↔adapter isolation check proves it.
- **The module naming a weather component, marker, or render.** `LocationSelect`, `ForecastButton`, `wb:`, `render_embed`, 📍 all stay app-side.
- **Lifting the `operator_id` baked-at-construction deferral** (bot.py:448) — preserve current behavior (DEFERRED idea).
- **Capturing config at construction.** Per-tap `holder.current()` reads (panel.py:520,590) must survive — the relocated callbacks read live config through the injected holder/accessor, never a construction-time value (Phase-24 contract).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Persistent-view registration | A custom message/component re-bind scanner at boot | discord.py `client.add_view(view)` in `setup_hook` | Relocate the EXISTING mechanism (bot.py:577-593) verbatim. `setup_hook` runs once pre-connect; `on_ready` re-fires on reconnect (bot.py:578-579 — the D-13 reason). |
| The clone-render live-routing | A fresh hand-rolled clone that carries plain Buttons | The existing `_render_view`/`_clone_child` pattern, generalized to re-invoke contributors | Plain clones go DEAD after first tap (panel.py:659-674 — the documented v1.3 Gate-2 trap). |
| Generic typed selection holder | A bespoke `dict`/`Any` slot | `SelectedContext(Generic[I])` cloned from `ConfigHolder(Generic[T])` | The module already ships the exact unbound-`TypeVar`-no-base-class precedent (holder.py). |
| Constructor injection of app specifics | A registry/service-locator/global | Required (no-default) constructor params + the single `build_runtime` root | The module's locked idiom; `test_injection_registry.py` enforces "required param = no baked default." |
| Import-graph enforcement | A custom AST import walker | grimp (already wired) + the isolated-import smoke + the AST litmus | `tests/test_import_hygiene.py` auto-scales to the new `discord/` package via `startswith(MODULE)` / `rglob` / `walk_packages` — no per-module edit. |

**Key insight:** This phase builds almost nothing new. Every mechanism — `BotThread`, the operator gate, the persistent-view registration, the clone path, the failure-isolation envelope, the summon orchestration, the `Generic` holder, the injection-root discipline, the grimp gates — already exists and was read in full. The work is **cutting along the generic/app seam** and **re-invoking contributors instead of `isinstance`-cloning app subclasses**, while the goldens prove byte-identity.

## Runtime State Inventory

> This is a code-relocation + dependency-constraint phase. There is one genuine runtime-state surface: the **live registered Discord panel** on host `yahir-mint`. Its `custom_id` strings are the post-restart routing contract — they are NOT stored by WeatherBot; they live in Discord's component registry, bound at `add_view` time, and re-bound on the next `systemctl restart`.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None in WeatherBot's stores.** The SQLite store (`weatherbot/weather/store.py`) holds forecast/health/sent-log rows keyed on location_name/send_time/local_date — none of these contain panel `custom_id`s or the `wb:` marker. Verified: `custom_id`s appear only in `panel.py` source + the golden snapshot. | None — no data migration. |
| Live service config | **The live Discord panel message on `yahir-mint`** carries `wb:`-prefixed `custom_id`s registered against discord.py 2.7.1. These live in Discord, not in git. | Keep every `custom_id` byte-identical (D-04 freeze) + keep `discord.py==2.7.1` (D-05). On restart, `setup_hook`'s `add_view(PanelKit(...))` re-binds the already-pinned panel purely by `custom_id`. If a byte flips, the live panel shows "interaction failed." **Deferred to Phase 28:** the live `systemctl restart` UAT confirming the deployed bot re-binds. This phase's oracle is the golden byte-snapshot. |
| OS-registered state | **None new.** The systemd unit (`Restart=always`, editable install on yahir-mint per MEMORY) is unaffected by an internal package boundary move — the import root `weatherbot` and console script `weatherbot = weatherbot.cli:main` are unchanged (pyproject.toml:24). | None this phase. (Editable install means an import-path move needs no reinstall; the physical repo split + reinstall is Phase 28.) |
| Secrets / env vars | **None affected.** The Discord token + `panel_channel_id` + `operator_id` are read from app config; the relocation injects them into the module `BotThread`/`PanelKit` rather than the bot reading them directly. No secret key name changes. | None — code re-wire only (inject at `build_runtime`). |
| Build artifacts | **`yahir_reusable_bot` is already a wheel package** (pyproject.toml:26-27 `[tool.hatch.build.targets.wheel] packages = ["weatherbot", "yahir_reusable_bot"]`). Adding `discord/` is a new subpackage under the already-listed top-level package — no new `packages` entry needed (hatchling recurses). No egg-info/compiled artifact carries a stale name. | Verify the new `discord/` subpackage is picked up by the wheel build (it is, transitively); confirm `uv.lock` regenerates cleanly with the tightened `discord.py==2.7.1`. |

**Canonical question — after every file is updated, what runtime systems still hold the old shape?** Only the live Discord panel (its `custom_id`s + the discord.py version it was registered against). Both are frozen by D-04/D-05 and pinned by the golden snapshot; the live-restart confirmation is the Phase-28 deferred UAT.

## Common Pitfalls

### Pitfall 1: The clone goes dead after the first tap (the v1.3 Gate-2 trap)
**What goes wrong:** A relocated clone path that produces plain `discord.ui.Button`/`Select` (base `callback` is a no-op `pass`) makes the panel stop responding after the first render, with NO log (the `pass` raises nothing).
**Why it happens:** discord.py routes by `message_id` first; `edit_message(view=clone)` binds the clone to the message, so all subsequent taps dispatch to the clone's children, not the `add_view`-registered `self` (panel.py:659-674).
**How to avoid:** The module's `_render_view` must produce clones bound to live handlers — re-invoke the registry-button builders AND the app contributors (Pattern 1a), never plain items. App contributors must return real callback-bearing items each call.
**Warning signs:** Clone-render golden diff; a manual second tap on the live panel showing "interaction failed."

### Pitfall 2: 📍 indicator drift across the generic/app cut (WR-01/WR-02 — highest-risk class)
**What goes wrong:** The 📍 line / emoji / `Updated <t:…>` stamp changes on ack/collapse/re-render because the render signature or the argless-suppression logic shifted during the cut.
**Why it happens:** Today's suppression depends on `arg = _selected_location if spec.takes_location else None` (panel.py:512) flowing into `render_embed`'s `if location is not None` (bot.py:221). Re-threading through `SelectedContext` can silently break the suppression boundary.
**How to avoid:** Thread the generalized per-spec consumes-context datum (D-02) and set the `ctx.value` the app's `render` sees to `None` for argless commands — reproducing the exact on/off. Pin with `test_render_embed_indicator_line` / `_indicator_suppressed_when_argless` (test_bot.py:778,789) + the embed goldens.
**Warning signs:** `tests/test_golden_embeds.py` diff; `test_bot.py` indicator tests red.

### Pitfall 3: A surviving import edge (SC#2 not actually satisfied)
**What goes wrong:** The grimp gate stays green but a deferred/in-function import still exists, or the module gains a TYPE_CHECKING edge to the app.
**Why it happens:** grimp counts TYPE_CHECKING edges by default (the gate KEEPS that default — test_import_hygiene.py:32). But a function-local app import only trips the *isolated-import* gate if the function runs.
**How to avoid:** Add an explicit core↔adapter isolation assertion that NO `discord/` module imports `weatherbot.*` at module-top OR function-local — and that `bot.py`/`panel.py` no longer contain `from weatherbot.interactive.panel import PanelView` or `from weatherbot.interactive.bot import render_embed`. The CONTEXT calls this the "core↔adapter import-isolation check (SC#2)."
**Warning signs:** A `grep -rn "import.*PanelView\|import render_embed" weatherbot/` returning a deferred import.

### Pitfall 4: custom_id child-order drift
**What goes wrong:** With command buttons module-built and Select/grid app-contributed, the assembled child order changes, failing the ordered byte-snapshot.
**Why it happens:** The contributor seam introduces a new "registry-buttons vs contributors" ordering decision.
**How to avoid:** Define an explicit row/position contract so the canonical view's child order is byte-stable to today's (Select row 0 → cmd rows 1-2 → grid rows 3-4). Pin with `test_golden_custom_ids.py`.
**Warning signs:** `test_all_custom_ids_byte_golden` diff.

### Pitfall 5: Two-package wheel / dep-location drift (D-05)
**What goes wrong:** The exact `discord.py==2.7.1` pin lands in the wrong place, or `uv.lock` doesn't actually constrain to 2.7.1, or hatchling silently drops the new subpackage.
**Why it happens:** Today both packages share one `pyproject.toml`; D-05 wants the pin in the "module adapter package's deps" but the physical split is Phase 28 — so within this single project the pin lives in the one `[project].dependencies` (tightened to `==2.7.1`), with the planner deciding the belt-and-suspenders question.
**How to avoid:** Tighten `discord.py>=2.7.1,<3` → `discord.py==2.7.1` in `pyproject.toml:10` now (documented as "owned by the adapter; will move to the module's own pyproject in Phase 28"). Regenerate + commit `uv.lock`. The `[tool.hatch...packages]` already lists `yahir_reusable_bot`; the new `discord/` subpackage rides it (verify with a `uv build` dry check if desired).
**Warning signs:** `uv.lock` still allowing a 2.7.x bump; a clean-venv build missing `yahir_reusable_bot/discord/`.

## Code Examples

### The cycle resolution, before → after
```python
# BEFORE (the latent cycle):
# weatherbot/interactive/panel.py:54   — module-top forward edge
from weatherbot.interactive.bot import render_embed
# weatherbot/interactive/bot.py:307    — deferred back edge (inside _handle_panel_summon)
from weatherbot.interactive.panel import PanelView, _is_owned_panel
# weatherbot/interactive/bot.py:583    — deferred back edge (inside setup_hook)
from weatherbot.interactive.panel import PanelView

# AFTER (ownership cut, D-01):
# render_embed STAYS in weatherbot/interactive/bot.py (renamed concept "render", app-side).
# PanelKit lives in yahir_reusable_bot/discord/panelkit.py and takes `render` + contributors
#   as injected args — it imports NOTHING from weatherbot.
# weatherbot/scheduler/wiring.py :: build_runtime constructs:
from yahir_reusable_bot.discord import PanelKit, SelectedContext, BotThread
from weatherbot.interactive.bot import render            # app render (was render_embed)
from weatherbot.interactive.panel import build_contributors, PANEL_MARKER  # app cosmetics
# ... bot = BotThread(token, panelkit_factory=lambda: PanelKit(
#         registry=registry_singleton, command_names=_CURATED, marker=PANEL_MARKER,
#         operator_id=operator_id, selection=SelectedContext(default_location),
#         contributors=build_contributors(holder, selection), render=render))
# No weatherbot import inside yahir_reusable_bot/discord/** — neither edge survives.
```

### The positive injection assertion (extend test_injection_registry.py)
```python
# Source: pattern from tests/test_injection_registry.py:143-304 (already stubs Phase-27 leak points)
def test_panel_cosmetics_and_render_and_marker_are_app_supplied():
    # PanelKit REQUIRES render, contributors, marker (no module default) — the app injects them.
    required = _required_params_without_default(PanelKit.__init__)
    assert {"render", "contributors", "marker"} <= required
    # build_runtime wires them at the single root.
    wired = _build_runtime_keyword_args()
    assert {"render", "contributors", "marker"} <= wired  # (or via a panelkit_factory closure)
    # The module contains NO wb: literal and no weather-cosmetic symbol.
    panelkit_src = (_MODULE_ROOT / "discord" / "panelkit.py").read_text()
    assert "wb:" not in panelkit_src
    # Self-proof: a baked-default PanelKit stub would NOT have these as required params.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `render_embed`↔`PanelView` cycle broken by a deferred in-function import (bot.py:307,583) | Cycle resolved **by ownership**: `render` moved app-side + injected; both edges deleted | This phase (SEAM-07 SC#2) | The module's adapter is import-clean; the core↔adapter isolation check proves no deferred import survives. |
| Hardcoded `_selected_location: str` (panel.py:323) | Generic `SelectedContext[I]`; WeatherBot uses `[str]` | This phase (D-02) | A reminder bot reuses the panel with `SelectedContext[ReminderId]`. |
| `_PANEL_MARKER = "wb:"` baked in panel.py | App-supplied `marker` param; module has no `wb:` literal | This phase (D-04) | Module is litmus-clean; any bot owns its own panels under its own marker. |
| `discord.py>=2.7.1,<3` range | Exact `==2.7.1` in the adapter's deps | This phase (D-05) | The persistent-view custom_id contract is valid against the exact registered version; no "interaction failed on a minor bump." |
| `BotThread`/`build_client`/summon + `PanelView` machinery in `weatherbot/interactive/` | Relocated to `yahir_reusable_bot/discord/` | This phase (D-06) | The reusable Discord adapter "lives in the module" (SEAM-07 headline). |

**Deprecated/outdated:** None introduced. The `Permissions.pin_messages` note (bot.py:75-84, effective 2026-01-12, the split from `manage_messages`) is already correct in the code and rides the relocation unchanged.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | discord.py persistent-view semantics (`timeout=None` required; all children need static `custom_id`; `add_view` in `setup_hook` re-binds by custom_id; `View.on_error` is the callback-exception backstop; base `Button.callback` is a no-op `pass`) hold for 2.7.1 | Architecture Patterns 1-2, Don't Hand-Roll | LOW — these are documented IN the live panel.py/bot.py docstrings as "verified against discord.py 2.7.1," the installed version is confirmed 2.7.1, and the existing passing test suite + live deployed panel exercise them. The relocation does not change the discord.py behavior, only where the code lives. |
| A2 | Recommending `yahir_reusable_bot/discord/` (vs `adapters/discord/`) as the package name | Recommended Project Structure | LOW — explicitly Claude's Discretion; both are litmus-clean generic names. Planner may choose either. |
| A3 | Recommending contributor-callables (Pattern 1a) over a `ClonableItem` Protocol (1b) or subclass hook | Architecture Pattern 1 | MEDIUM — this is the PRIMARY research target and Claude's Discretion. 1a best matches the module's no-inheritance idiom, but the planner should confirm the child-order + clone-re-invocation contract reproduces the byte-identical custom_id order and clone-render goldens before committing. |
| A4 | The `_REQUIRED_PANEL_PERMS`/`_PANEL_PERM_LABELS` constants (bot.py:78-95) are generic enough to relocate to the module (they name Discord permissions, not weather) | Architecture Pattern 3 | LOW — they contain no weather noun; but the operator-COPY strings (bot.py:105-136) MUST stay app-side. Planner decides whether to move the perm-set constant. |
| A5 | The exact `discord.py==2.7.1` pin lives in `pyproject.toml:10` for this phase (the single shared project), moving to the module's own `pyproject.toml` only at the Phase-28 physical split | Pitfall 5, D-05 | LOW — the physical split is explicitly Phase 28; within one project there is one `[project].dependencies`. Planner confirms the belt-and-suspenders question (CONTEXT D-05 discretion). |

## Open Questions

1. **Child-order contract for the contributor seam.**
   - What we know: today's child order is fixed (Select row 0 → cmd rows 1-2 → grid rows 3-4) and pinned by the ordered byte-snapshot.
   - What's unclear: the exact API by which `PanelKit` interleaves its registry-derived buttons with app contributors to reproduce that order.
   - Recommendation: have contributors declare their row/position (or pass an ordered list where `PanelKit` slots its command buttons at fixed indices), and treat `test_golden_custom_ids.py` as the gate. Resolve during planning by writing the contributor contract against the existing snapshot.

2. **`SelectedContext` mutability + the per-tap reload interaction.**
   - What we know: today `_selected_location` is mutated in `on_select` (panel.py:488); config locations are re-read per render from `holder.current()` (panel.py:680).
   - What's unclear: whether `SelectedContext` should be a simple mutable holder (recommended) or frozen-with-replace.
   - Recommendation: mutable holder with `.set()` (mirrors the in-memory selection); the holder.current() reload reads stay separate (they re-derive the dropdown options, not the selection). Confirm no golden depends on selection identity across renders.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | runtime | ✓ | 3.12+ (`requires-python >=3.12`) | — |
| discord.py | the adapter being relocated | ✓ | 2.7.1 (`[VERIFIED: installed]` + `[VERIFIED: uv.lock]`) | — (pinned exact, D-05) |
| grimp | the PKG-01 import gate (dev) | ✓ | 3.14 (`[VERIFIED: uv.lock]`) | — |
| pytest / syrupy | the golden oracle (dev) | ✓ | 9.0.3 / 5.3.4 | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none. This phase introduces no new external dependency.

## Validation Architecture

> `nyquist_validation` is not disabled in config (treated as enabled). This phase's invariants are heavily byte-identical / golden-pinned, which is the strongest possible sampling rate — the goldens ARE the oracle.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + syrupy 5.3.4 (`[VERIFIED: pyproject.toml]`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `pythonpath = ["."]`) |
| Quick run command | `uv run pytest tests/test_panel.py tests/test_bot.py tests/test_golden_custom_ids.py tests/test_import_hygiene.py tests/test_injection_registry.py -x` |
| Full suite command | `uv run pytest` (the ~649-test suite — BHV-01 oracle) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEAM-07 SC#1 | `BotThread` + view machinery relocated; behavior byte-identical | unit/contract | `uv run pytest tests/test_bot.py tests/test_panel.py` | ✅ (re-run unchanged) |
| SEAM-07 SC#2 | render-cycle resolved by ownership; no deferred/in-function import survives | import-isolation | `uv run pytest tests/test_import_hygiene.py` + new core↔adapter check | ✅ extend (add the adapter-edge + no-deferred-import assertion) |
| SEAM-07 SC#3 | `custom_id`s frozen byte-identical; `discord.py==2.7.1` pinned; marker parameterized | golden + dep | `uv run pytest tests/test_golden_custom_ids.py` + new module marker-param test | ✅ extend (add generic module marker test) |
| SEAM-07 SC#4 | generic `SelectedContext[I]`; WeatherBot uses `[str]`; carries selected location | unit + litmus | `uv run pytest tests/test_panel.py tests/test_import_hygiene.py::test_litmus_clean` | ✅ extend (add `selection.py` to litmus tree assertion) |
| PKG-01 | module imports zero app code (grimp + isolated-import), new adapter edges | import gate | `uv run pytest tests/test_import_hygiene.py` | ✅ auto-scales (`startswith(MODULE)` / `walk_packages` / `rglob`) |
| APP-02 | litmus clean + positive injection assertion (cosmetics+render+marker app-supplied) | litmus + injection | `uv run pytest tests/test_import_hygiene.py::test_litmus_clean tests/test_injection_registry.py` | ✅ extend (add PanelKit render/contributors/marker injection asserts) |
| BHV-01 | full suite green at the boundary | full suite | `uv run pytest` | ✅ |
| BHV-02 | embed fields+order + panel custom_ids golden-pinned | golden | `uv run pytest tests/test_golden_embeds.py tests/test_golden_custom_ids.py` | ✅ |

### What is golden-checkable vs property/held-out
- **Golden-checkable (byte-identical oracle — the strongest):** the ordered `custom_id` byte snapshot (`test_golden_custom_ids.py`), the embed fields+order (`test_golden_embeds.py`), the panel/clone-render goldens (Phase-21 harness), the 📍-indicator on/off (`test_bot.py` indicator tests). **Any non-empty diff = a regression to investigate, never re-baseline.**
- **Property/structural-checkable:** the import isolation (grimp graph has no module→app edge — property over the graph), the litmus (no weather noun in the module public name surface — property over AST names), the positive injection (PanelKit required params have no default — property over the signature), the core↔adapter no-deferred-import (grep/AST property).
- **Held-out / not auto-checkable this phase:** the live `yahir-mint` `systemctl restart` re-bind UAT (the live panel re-routing by custom_id) — **deferred to Phase 28** per CONTEXT. The golden byte-snapshot is the stand-in oracle this phase.

### Sampling Rate
- **Per task commit:** the Quick run command (panel + bot + custom_id + import-hygiene + injection).
- **Per wave merge:** `uv run pytest` (full suite) + the goldens.
- **Phase gate:** full suite green + zero golden diff + grimp/isolated-import/litmus/injection all green before `/gsd-verify-work`.

### New gates this phase adds (Wave 0 / extension targets)
- [ ] `tests/test_import_hygiene.py` — extend `test_litmus_clean`'s tree-coverage assertion to require `discord/` files (`panelkit.py`, `gateway.py`, `selection.py`) in the scanned tree (mirroring the existing lifecycle + registry coverage-gap guards at lines 379-395), so a future relocation can't silently drop the adapter from litmus coverage.
- [ ] `tests/test_import_hygiene.py` — add the **core↔adapter import-isolation check**: assert no `yahir_reusable_bot/discord/**` module imports `weatherbot.*` (auto-covered by the existing grimp gate's `startswith(MODULE)` scan + `walk_packages`), PLUS assert `weatherbot/interactive/{bot,panel}.py` contain no `import PanelView` / `import render_embed` deferred edge (the SC#2 proof — grep/AST).
- [ ] `tests/test_injection_registry.py` — add the **PanelKit positive injection assertion**: `render`, `contributors`, and `marker` are required (no-default) `PanelKit.__init__` params, wired at `build_runtime`; the module source contains no `wb:` literal and no weather-cosmetic symbol (extends the existing leak-point-1/4 stubs at lines 225-304).
- [ ] New generic module test: `PanelKit(marker="X:")` produces `X:cmd:<name>` ids (marker parameterization, D-04) — proves the module bakes no `wb:`.
- [ ] (Wave 0 if needed) a clone-render golden for the relocated `_render_view` if the existing Phase-21 clone-render golden doesn't already cover the contributor re-invocation path — verify coverage first; only add if a gap exists.

## Security Domain

> `security_enforcement` not disabled in config (treated as enabled). This is a code-relocation phase with no new attack surface; the existing security controls ride the move unchanged and are pinned by the suite.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface added; the Discord token is read from existing config (`[VERIFIED: codebase]` BotThread takes `token`). |
| V3 Session Management | no | n/a |
| V4 Access Control | **yes** | The **operator gate** (`interaction_check`: non-operator → identity-free ephemeral reject + reject log; bot → reject, no ephemeral by design WR-03) relocates verbatim into `PanelKit`. `operator_id` stays baked-at-construction (preserve — DEFERRED idea). The reject copy never interpolates user/custom_id/command/operator (D-12, panel.py:445). |
| V5 Input Validation | **yes** | Forecast flags are built DIRECTLY from the in-memory selection, never re-parsed from user text (panel.py:570-582 — "no user-typed string reaches the bypassed parser, Security V5"). Preserve through the relocation. |
| V6 Cryptography | no | n/a — no crypto introduced. |
| V7 Error Handling & Logging | **yes** | The per-callback non-propagating envelope + `View.on_error` backstop + `_safe_error_edit` (never re-raises) relocate verbatim; no token/URL ever reaches a log or user message (bot.py:27, panel.py:763). |

### Known Threat Patterns for the Discord adapter
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Foreign user / bot taps the shared panel | Elevation of Privilege | The operator gate (V4) — identity-free ephemeral reject + audit log; relocated verbatim. |
| A raising callback crashes the gateway loop / scheduler thread | Denial of Service | The per-callback failure-isolation envelope + `View.on_error` + `BotThread._run` swallow-and-log (failure isolation, D-11) — relocated verbatim. |
| Token / webhook URL leaks into a log or user reply | Information Disclosure | Secret-free logging (only non-secret ids: `channel_id`, `user_id`, `custom_id`) — relocated verbatim (Security V7). |
| A flipped `custom_id` byte breaks live panel routing | (availability) | The byte-frozen `custom_id` golden (D-04) + the `discord.py==2.7.1` pin (D-05). |
| `pin_messages` permission split (2026-01-12) masks a missing perm | (availability) | The summon preflights `Permissions.pin_messages` (the new bit), not `manage_messages` (bot.py:75-84) — relocated verbatim. |

## Sources

### Primary (HIGH confidence)
- **The live codebase, read in full this session:** `weatherbot/interactive/panel.py` (765 lines), `weatherbot/interactive/bot.py` (710 lines), `weatherbot/scheduler/wiring.py`, `yahir_reusable_bot/registry/{__init__,registry,spec}.py`, `yahir_reusable_bot/scheduler/engine.py`, `yahir_reusable_bot/config/holder.py`, `tests/test_import_hygiene.py`, `tests/test_injection_registry.py`, `tests/test_golden_custom_ids.py`, `tests/test_panel.py`, `pyproject.toml` — the authoritative source for every relocation fact.
- `[VERIFIED: installed]` discord.py version: `python -c "import discord; print(discord.__version__)"` → `2.7.1`.
- `[VERIFIED: uv.lock]` `discord-py 2.7.1`, `grimp 3.14`.
- The CONTEXT (`27-CONTEXT.md`) six locked decisions + canonical refs; REQUIREMENTS SEAM-07 + cross-cutting acceptances.

### Secondary (MEDIUM confidence)
- discord.py 2.7.1 persistent-view semantics — documented in the codebase docstrings as "verified against discord.py 2.7.1, 17-RESEARCH Patterns 1-4" (panel.py:17-18, bot.py:559-564). The official docs page (`discordpy.readthedocs.io`) did not surface the View-lifecycle section on fetch; the codebase + installed version + passing suite are the corroborating evidence.

### Tertiary (LOW confidence)
- None. Every claim is grounded in read source or a verified tool output.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; discord.py 2.7.1 verified installed + locked; the only change is tightening an existing constraint.
- Architecture: HIGH — every mechanism that moves was read in full and maps to an existing shipped module precedent (constructor injection, `Generic[T]` holder, opaque callables, the single composition root, the grimp gates).
- Pitfalls: HIGH — the highest-risk classes (clone-dead-after-first-tap, 📍 drift, custom_id order, surviving import edges) are documented in the live code's own comments and pinned by existing goldens/tests.
- Primary research target (D-03 contributor mechanism): MEDIUM — the recommendation (contributor callables) is well-grounded but the exact child-order/clone-re-invocation API is a planning decision to confirm against the byte-snapshot.

**Research date:** 2026-06-29
**Valid until:** 2026-07-29 (stable — internal relocation of a pinned stack; the only external dependency is exact-pinned).
