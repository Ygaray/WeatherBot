# Phase 27: Discord Adapter + PanelKit + Render-Cycle Fix - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-29
**Phase:** 27-discord-adapter-panelkit-render-cycle-fix
**Mode:** `--auto` — fully autonomous, single-pass. No AskUserQuestion; the recommended option was
auto-selected per question on the **reusable-module + lowest-byte-identical-risk** axis (matching the
user's standing guidance to decide for the reusable-module goal on deep-technical phases). ADVISOR_MODE
was active but `--auto` overrides the interactive table-first flow.
**Areas discussed:** Render-cycle resolution, SelectedContext[I] shape, Generic-vs-app UI split,
custom_id marker ownership, discord.py pin location, BotThread relocation scope

---

## Render-cycle resolution (the crux, SC#2)

| Option | Description | Selected |
|--------|-------------|----------|
| Move `render_embed` app-side + inject opaque `render` callable; kill the deferred import | The whole weather/house-style embed builder goes app-side and is injected; no deferred/in-function import survives | ✓ |
| Keep the deferred `PanelView` import | Leave the cycle broken by a deferred import | |
| Thin generic `render` in module + app passes style data | A module render shell taking app colors/style | |

**Auto-selected:** Move `render_embed` app-side + inject. **Notes:** ROADMAP **mandates** "by
ownership, not a deferred import"; `render_embed` is irreducibly weather house-style (📍,
`BRIEFING_COLOR_INT`, `Updated <t:…>`, forecast field budgeting). Mirrors the Phase-26 `bind` /
Phase-23/24 opaque-callable precedent. SC#2's core↔adapter import-isolation check is the proof.

---

## SelectedContext[I] shape (SC#4)

| Option | Description | Selected |
|--------|-------------|----------|
| Module-owned generic `SelectedContext[I]`; WeatherBot uses `SelectedContext[str]` | Typed generic holder for the selected item; replaces hardcoded `_selected_location: str` | ✓ |
| Bare `Any`/untyped slot | Untyped selected-item field | |

**Auto-selected:** Generic `SelectedContext[I]`. **Notes:** ROADMAP-locked headline (generic, no
hardcoded "location", carries WeatherBot's selected location). `spec.takes_location` (the one Phase-26
survivor) generalizes to an app-supplied datum read by the app's binding, not the module.

---

## Generic-vs-app UI split (SC#1, APP-02) — most intricate seam, primary research target

| Option | Description | Selected |
|--------|-------------|----------|
| PanelKit owns registry-derived buttons + persistent-view invariants; app contributes its cosmetic UI (location Select, forecast grid, emoji) + injected render | Litmus-clean split; module names no weather UI; mechanism (callables vs subclass hook vs extra-rows param) is planner's discretion | ✓ |
| Relocate the location dropdown + forecast grid into the module too | Bake WeatherBot UI into the adapter | |

**Auto-selected:** App-contributed cosmetics + module-owned generic surface. **Notes:** The location
dropdown + 2×2 forecast grid + 📍/emoji are irreducibly WeatherBot UI (a reminder/Slack bot has
neither) — baking them in trips the litmus and defeats adapter reuse. Exact contributor mechanism left
to research/planner.

---

## custom_id marker ownership + freeze (SC#3)

| Option | Description | Selected |
|--------|-------------|----------|
| App-supplied marker prefix (required, no weather default); frozen custom_id byte strings asserted by a byte-string test | Module contains no `wb:` literal; WeatherBot keeps `wb:` byte-for-byte | ✓ |
| Module-default `wb:` the app can override | A weather-flavored default literal still in module source | |

**Auto-selected:** App-supplied marker. **Notes:** `wb:` is a WeatherBot identifier; a module default
trips the litmus and blocks a reminder bot from owning its own panels. The live already-pinned panel
keeps routing because WeatherBot's `wb:…` strings are frozen byte-identically.

---

## discord.py pin location + freeze (SC#3)

| Option | Description | Selected |
|--------|-------------|----------|
| Exact `discord.py==2.7.1` in the module adapter package deps | The adapter owns the Discord coupling, so it owns the pinned version; tightens today's `>=2.7.1,<3` | ✓ |
| Keep the range / pin only app-side | Leave `>=2.7.1,<3` or pin app-side only | |

**Auto-selected:** Exact pin in module deps. **Notes:** The component owning the persistent-view +
`custom_id` contract owns the version that contract is valid against. Belt-and-suspenders app-side pin
+ `uv.lock` shape left to planner discretion (one wheel today; matters at the Phase-28 split).

---

## BotThread relocation scope (SC#1)

| Option | Description | Selected |
|--------|-------------|----------|
| Relocate gateway/persistent-view plumbing wholesale into module; keep channel-config read + render + cosmetics app-injected | BotThread, operator gate, failure-isolation envelope, summon orchestration → module; render/cosmetics/marker/ids injected | ✓ |
| Leave BotThread app-side, relocate only PanelKit | Keep the gateway host app-side | |

**Auto-selected:** Relocate wholesale. **Notes:** `BotThread`'s gateway lifecycle / operator gate /
failure-isolation envelope are exactly the reusable adapter payoff SEAM-07 names; leaving it app-side
under-delivers the phase. How `summon_panel` splits (module orchestration vs app channel-read/render)
is planner's discretion.

## Claude's Discretion

- Module adapter sub-layout + naming (`yahir_reusable_bot/discord/` vs `adapters/discord/` vs flatter).
- The exact app-component-contributor mechanism (D-03) — **primary research target**.
- The injected `render` signature + how `SelectedContext[I]` threads to it and the app cosmetics.
- How `summon_panel` splits between module orchestration and app-supplied channel-read/render/cosmetics;
  operator_id / panel_channel_id injection (preserving the v1 "operator_id baked at construction"
  behavior).
- Where the exact `discord.py==2.7.1` pin sits (module-only vs also app-side) + `uv.lock` shape.
- The form of the positive injection assertion + the litmus/grimp/isolated-import/core↔adapter-isolation
  extensions.
- Whether the byte-string custom_id freeze lives app-side, module-side, or both.

## Deferred Ideas

- Physical repo split + uv git dep + EXTENSION-GUIDE + live `yahir-mint` restart UAT → **Phase 28**.
- Uniform/declarative panel-layout DSL beyond the minimal contributor seam → revisit if a 3rd bot needs it.
- Re-reading `operator_id` per message from `holder.current()` → v1 deferral preserved, not fixed here.
- Slash-command / non-text adapter surface → separate future capability.
- Broadening the litmus term set → rejected; stays weather-specific.
