# Phase 27: Discord Adapter + PanelKit + Render-Cycle Fix - Pattern Map

**Mapped:** 2026-06-29
**Files analyzed:** 13 (4 new module files, 4 modified app sources, 5 extended/added test gates, pyproject)
**Analogs found:** 13 / 13 (every file anchors on a shipped Phase 22-26 module idiom or the in-place source being cut)

> This is a **byte-identical EXTRACTION/relocation** phase, not a redesign. Every mechanism that
> moves already exists and was read in full. The planner's job is to *cut along the generic/app
> seam* and re-anchor each new module file on the established constructor-injection + opaque-callable
> idiom — never to invent. The Phase-21 goldens are the byte-identical oracle for every cut.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `yahir_reusable_bot/discord/gateway.py` (NEW — `BotThread` + `build_client` + summon orchestration) | adapter/provider | event-driven | `weatherbot/interactive/bot.py` (`BotThread`, `build_client`, `_handle_panel_summon`) | exact (verbatim relocation) |
| `yahir_reusable_bot/discord/panelkit.py` (NEW — `PanelKit` view machinery + ownership test + clone path) | adapter/component | event-driven | `weatherbot/interactive/panel.py` (`PanelView`, `CmdButton`, `_is_owned_panel`, `_render_view`, `_clone_child`) | exact (verbatim, marker/UI parameterized out) |
| `yahir_reusable_bot/discord/selection.py` (NEW — generic `SelectedContext[I]`) | model/holder | transform | `yahir_reusable_bot/config/holder.py` (`ConfigHolder(Generic[T])`) | exact (verbatim `Generic`/unbound-`TypeVar`/no-base-class precedent) |
| `yahir_reusable_bot/discord/__init__.py` (NEW — public re-exports) | config/barrel | — | `yahir_reusable_bot/registry/__init__.py` | exact |
| `weatherbot/interactive/bot.py` (MODIFIED — `render_embed` STAYS, gateway machinery REMOVED) | utility (app render) | request-response | itself (shrinks to `render_embed` + `build_inbound_embed`) | self |
| `weatherbot/interactive/panel.py` (MODIFIED — shrinks to app cosmetic contributors + marker literals) | component (app UI) | event-driven | itself (keeps `LocationSelect`/`ForecastButton`/`wb:` literals; `PanelView` machinery moves) | self |
| `weatherbot/scheduler/wiring.py` / `daemon.py` (MODIFIED — composition root injects render/cosmetics/marker) | config (composition root) | — | `daemon.py:1508` `BotThread(...)` construction site | exact (re-wire the existing call) |
| `pyproject.toml` (MODIFIED — `discord.py==2.7.1` exact pin, D-05) | config | — | `pyproject.toml:10` + `:26-27` two-package wheel | self |
| `tests/test_import_hygiene.py` (EXTEND — `discord/` tree coverage + core↔adapter isolation) | test | — | `test_litmus_clean` lifecycle/registry coverage-gap guards (L379-395) | exact |
| `tests/test_injection_registry.py` (EXTEND — PanelKit render/contributors/marker injection assertion) | test | — | leak-point-1/4 stubs (L225-304) | exact (stubs ALREADY present) |
| `tests/test_golden_custom_ids.py` (RE-RUN unchanged + add generic module marker test) | test | — | `test_all_custom_ids_byte_golden` (L43-53) | self |
| `tests/test_golden_embeds.py` / `test_bot.py` / `test_panel.py` (RE-RUN unchanged — byte oracle) | test | — | `test_render_embed_indicator_suppressed_when_argless` (test_bot.py:789) | self |

## Pattern Assignments

### `yahir_reusable_bot/discord/selection.py` — generic `SelectedContext[I]` (model, D-02)

**Analog:** `yahir_reusable_bot/config/holder.py` (`ConfigHolder(Generic[T])`) — the research flags this as the *verbatim* precedent.

**The idiom to clone — unbound `TypeVar`, NO base class** (`holder.py:37-43`):
```python
# UNBOUND (D-02) — no module base class. Any bot passes its own frozen config type, so the
# module imposes zero inheritance. The bound is deliberately omitted...
T = TypeVar("T")


class ConfigHolder(Generic[T]):
    def __init__(self, config: T) -> None:
        self._config = config
        self._lock = threading.Lock()
```

**The lock-free read / mutate shape to mirror** (`holder.py:56-72`) — `SelectedContext` replaces today's hardcoded `_selected_location: str` (panel.py:323). Map `current()`→`value` (property) and `replace()`→`set()`. Drop the threading lock unless a golden depends on swap-atomicity (selection is mutated only inside an `on_select` callback on the gateway loop — single-writer; see RESEARCH Open Question 2: recommend a simple mutable holder, no lock).

```python
# Recommended (selection.py), cloned from the holder precedent:
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
WeatherBot instantiates `SelectedContext[str]`; the app's `LocationSelect.callback` calls `ctx.set(self.values[0])` (replacing `self._panel._selected_location = value`, panel.py:488). **Preserve Pitfall-3:** button callbacks read `ctx.value`, NEVER re-read `Select.values` (panel.py:279, 570).

---

### `yahir_reusable_bot/discord/panelkit.py` — `PanelKit` view machinery (adapter/component, D-03/D-04)

**Analog (primary, the code being cut):** `weatherbot/interactive/panel.py` `PanelView` + `_is_owned_panel` + `_render_view`/`_clone_child`.
**Analog (the injection idiom to anchor the new constructor on):** `CommandRegistry.__init__` (registry.py:39 — required `specs` arg, no baked default) + `SchedulerEngine.__init__` (engine.py:41 — opaque collaborator) + `ReloadEngine` (reload.py — injected `validate`/`desired_jobs`/`register_jobs` callables).

**Constructor — injected collaborators, required no-default params** (mirror registry.py:39 / engine.py:41):
```python
ItemContributor = Callable[["SelectedContext"], list[discord.ui.Item]]

class PanelKit(discord.ui.View):
    def __init__(
        self,
        *,
        registry,                       # Phase-26 CommandRegistry — command buttons built FROM it
        command_names: tuple[str, ...], # curated ordered button names (app-supplied)
        marker: str,                    # D-04 — REQUIRED, no weather default ("wb:")
        operator_id: int,               # D-06 — baked at construction (preserve v1, bot.py:448)
        selection: "SelectedContext",   # D-02 — the generic selected-item holder
        contributors: list[ItemContributor],  # D-03 — app builds Select/grid here
        render: Callable,               # D-01 — opaque app embed builder (was render_embed)
    ) -> None:
        super().__init__(timeout=None)  # REQUIRED for persistence (Phase-18 D-10) — panel.py:302
```
**`marker`/`render`/`contributors` MUST be required (no default)** — this is what the positive injection assertion (below) checks. Mirrors how `CommandRegistry(specs)` makes `specs` required so "the module holds no baked default" (registry.py:39, 84-89).

**Operator gate — relocate VERBATIM** (`panel.py:435-476`), `operator_id` injected. Preserve the WR-03 intentional asymmetry (bot reject sends NO ephemeral, panel.py:447-464) and the D-12 identity-free reject copy. The reject log is the SOLE audit record.

**Ownership test — marker parameterized** (`panel.py:144-177`): replace `_PANEL_MARKER = "wb:"` (panel.py:141) with `self._marker` (the injected param); `cid.startswith(self._marker)` at panel.py:175. The module source contains NO `wb:` literal (D-04).

**Build-children order is load-bearing** (`panel.py:325-381`): row 0 Select → rows 1-2 command buttons → rows 3-4 forecast grid. The `custom_id` byte-snapshot (`test_golden_custom_ids.py:52`) pins the ordered set — the contributor interleaving must reproduce: Select row 0, module command buttons rows 1-2, app contributors rows 3-4. Build a row/position contract (RESEARCH Pattern 4 / Open Question 1).

**The clone path — the highest-risk mechanism** (`panel.py:644-724`): the `_render_view`/`_clone_child` live-routing trap. The module's clone path CANNOT `isinstance`-check `LocationSelect`/`ForecastButton` (app classes the module must not name, panel.py:710-723). **Generalize via contributor re-invocation (RESEARCH Pattern 1a):** `_render_view` rebuilds the registry-derived `CmdButton`s AND re-invokes each app contributor, never plain items. **Apply `disabled` post-construction** (panel.py:688-690 — the ctors take no `disabled` param). Anchor the clone-doc on panel.py:659-674 verbatim (the v1.3 Gate-2 trap explanation).

**Per-callback envelope + `View.on_error` + `_safe_error_edit` — relocate VERBATIM** (`panel.py:490-492`, `624-642`, `726-764`). Names no weather; rides the move unchanged.

**`_assert_layout` / caps — relocate VERBATIM** (`panel.py:385-433`) — the child-cap build-time guards (`_MAX_CUSTOM_ID=100` etc.) are generic Discord caps.

**Per-tap `holder.current()` reload reads survive** (panel.py:520, 590, 680): the relocated callbacks read live config through the injected holder/accessor, never a construction-time capture (Phase-24 contract).

---

### `yahir_reusable_bot/discord/gateway.py` — `BotThread` + `build_client` + summon (adapter, D-06)

**Analog (the code being cut, verbatim):** `weatherbot/interactive/bot.py` `BotThread` (L612-709), `build_client` (L536-609), `_handle_panel_summon` (L276-399).

**`BotThread` — relocate VERBATIM** (`bot.py:612-709`): own thread+loop via `asyncio.run(client.start(token))` (NOT `Client.run`), `start()` waits on `_loop_started` (bot.py:652-662), `stop()` schedules `client.close()` cross-thread + joins (bot.py:673-684), `_run` swallows `LoginFailure`/any crash and sets `_failed` (bot.py:686-702 — failure isolation D-11). None of it names weather.

**`setup_hook` persistent-view registration — relocate, eliminating the deferred import** (`bot.py:576-593`):
```python
# BEFORE (the deferred back-edge to kill, bot.py:583):
@client.event
async def setup_hook() -> None:
    from weatherbot.interactive.panel import PanelView   # <-- DEFERRED IMPORT, D-01 eliminates
    client.add_view(PanelView(holder=..., operator_id=..., cache=..., daemon_state=...))
```
After D-01 the app constructs the `PanelKit` (with `render` + contributors + marker injected) at `wiring.py`/`daemon.py` and hands it (or a factory) to `build_client`, so `setup_hook` calls `client.add_view(panelkit)` with NO `weatherbot` import. Keep the D-13 reason verbatim (setup_hook runs once pre-connect, NOT on_ready, bot.py:578-579).

**Summon orchestration split (D-06, RESEARCH Pattern 3):**
- **Module-side (generic):** the pin-scan + create-before-delete ordering (`bot.py:368-390` — `channel.send` + `msg.pin()` FIRST, then delete prior owned, no zero-panel window), the `_is_owned_panel` predicate (marker-bound), the per-write `discord.Forbidden` backstop (bot.py:391-399), the permission preflight loop. `_REQUIRED_PANEL_PERMS` (bot.py:78-84) may relocate (names Discord perms, not weather — A4).
- **App-side (injected):** the `holder.current().bot.panel_channel_id` read + channel resolution (bot.py:309-341, incl. the `hasattr(channel, "pins")` duck-type), ALL operator-feedback copy strings (bot.py:105-136 — name `[bot] panel_channel_id`, weather config concern), the idle embed (`render(CommandReply(title=_PANEL_IDLE_TITLE,...))`, bot.py:364-366), the panel-factory `_build_view` (bot.py:356-362).

**`build_client` intents + on_ready — relocate VERBATIM** (`bot.py:566-607`): the `Intents.none()` + 3-intent setup and the `message_content` startup assertion name no weather.

---

### `yahir_reusable_bot/discord/__init__.py` — public re-exports (barrel)

**Analog:** `yahir_reusable_bot/registry/__init__.py` (verbatim shape):
```python
from yahir_reusable_bot.discord.gateway import BotThread, build_client
from yahir_reusable_bot.discord.panelkit import PanelKit
from yahir_reusable_bot.discord.selection import SelectedContext

__all__ = ["BotThread", "build_client", "PanelKit", "SelectedContext"]
```
Re-export ONLY generic adapter names (`PanelKit`/`SelectedContext`/`BotThread`/`build_client`) — the litmus permits these; it forbids `weather|forecast|location|openweather|\buv\b|briefing`.

---

### `weatherbot/interactive/bot.py` (MODIFIED — `render_embed` STAYS, D-01)

`render_embed` (bot.py:194-273) is irreducibly weather/house-style (📍 line bot.py:221-222, `BRIEFING_COLOR_INT` bot.py:228, `Updated <t:…>` stamp bot.py:223, WR-02 field-budget split bot.py:233-271) — **stays defined here**, becomes the injected `render`. The argless-suppression (`if location is not None`, bot.py:221) is load-bearing for the embed golden; thread it via `SelectedContext` per RESEARCH Pattern 2 (module passes `.value` set, or `None` when the app's per-spec `takes_location` datum is false). `BotThread`/`build_client`/`_handle_panel_summon` are DELETED from this file (moved to the module). The deferred `from weatherbot.interactive.panel import PanelView` at bot.py:307 and bot.py:583 both vanish (SC#2 proof).

### `weatherbot/interactive/panel.py` (MODIFIED — shrinks to app contributors, D-03)

KEEPS: `LocationSelect` (`wb:loc:select`, panel.py:250-279), `ForecastButton` (`wb:fc:…`, panel.py:205-247), `CmdButton` labels/emoji (panel.py:105-129), the `wb:` literals, and the new contributor functions handed to `PanelKit`. The module-top `from weatherbot.interactive.bot import render_embed` (panel.py:54) is removed — `render` is injected at the composition root, not imported here. `PanelView` machinery + `_is_owned_panel` + `_render_view`/`_clone_child` move to the module.

### `weatherbot/scheduler/wiring.py` + `daemon.py:1508` (MODIFIED — composition root)

**Analog:** the existing `BotThread(...)` construction at `daemon.py:1508-1514`:
```python
bot = BotThread(
    settings.discord_bot_token,
    holder=holder,
    operator_id=config.bot.operator_id,
    cache=cache,
    daemon_state=daemon_state,
)
```
Re-wire this single site (or move it into `wiring.py build_runtime` per Phase-25 D-04) to construct the *module* `BotThread`, injecting `render=render_embed`, the app cosmetic-contributor list, `marker="wb:"`, and a `PanelKit` factory. This is the ONE greppable injection site (APP-01/APP-02). The positive injection assertion verifies `render`/`contributors`/`marker` are wired here.

---

## Shared Patterns

### Constructor injection of opaque callables (the module's locked idiom)
**Source:** `registry/registry.py:39` (`CommandRegistry(specs)` — required arg), `scheduler/engine.py:41` (`SchedulerEngine(scheduler)` — opaque collaborator), `config/reload.py:47-51` (`ReloadEngine(holder, validate=, desired_jobs=, register_jobs=)` — injected callables).
**Apply to:** `PanelKit.__init__` (`render`/`contributors`/`marker` required, no default), `gateway.py` summon (channel-read/idle-embed/factory injected).
**Why:** zero inheritance, zero baked app default — `test_injection_registry.py` enforces "required param = no baked default."

### Generic `Generic[T]` holder, unbound `TypeVar`, no base class
**Source:** `config/holder.py:37-43`.
**Apply to:** `selection.py` `SelectedContext[I]`.

### Litmus + positive-injection assertion (negative grep + positive proof)
**Source:** `test_import_hygiene.py:361-402` (`test_litmus_clean` — negative grep over `yahir_reusable_bot/**`, D-13 term set LOCKED) + `test_injection_registry.py:225-304` (leak-point-1/4 stubs — ALREADY present, naming Phase-27 as the relocation that lands them).
**Apply to:** the new `discord/` package. Generic adapter names (`PanelKit`/`SelectedContext`/`BotThread`/`render`/`marker`) are ALLOWED; the positive assertion proves cosmetics + `render` + marker are app-supplied, not baked.

```python
# Extend test_injection_registry.py (the stubs at L225-304 anticipate this):
def test_panel_cosmetics_and_render_and_marker_are_app_supplied():
    required = _required_params_without_default(PanelKit.__init__)
    assert {"render", "contributors", "marker"} <= required
    panelkit_src = (_MODULE_ROOT / "discord" / "panelkit.py").read_text()
    assert "wb:" not in panelkit_src
```

### Tree-coverage guard against silent litmus-drop
**Source:** `test_import_hygiene.py:379-395` (lifecycle + registry coverage-gap guards).
**Apply to:** add `discord/` files (`panelkit.py`, `gateway.py`, `selection.py`) to the scanned-tree assertion so a future relocation can't silently drop the adapter from litmus coverage.

```python
# Mirror the lifecycle/registry guards (L382, L392):
discord_scanned = {p.name for p in (_MODULE_ROOT / "discord").rglob("*.py")}
assert {"panelkit.py", "gateway.py", "selection.py"} <= discord_scanned
```

### Byte-identical golden oracle (the strongest sampling rate)
**Source:** `test_golden_custom_ids.py:43-53` (ordered `custom_id` byte-snapshot), `test_golden_embeds.py`, `test_bot.py:789` (`test_render_embed_indicator_suppressed_when_argless`), the Phase-21 panel/clone-render goldens.
**Apply to:** EVERY cut. Any non-empty diff is a regression to investigate, NEVER re-baseline (Phase-21 discipline / CONTEXT D-06). Add ONE generic module test: `PanelKit(marker="X:")` produces `X:cmd:<name>` ids (D-04 marker parameterization).

### Two-package wheel + exact pin (D-05)
**Source:** `pyproject.toml:10` (`discord.py>=2.7.1,<3` → tighten to `==2.7.1`) + `pyproject.toml:26-27` (`packages = ["weatherbot", "yahir_reusable_bot"]` — the new `discord/` subpackage rides the already-listed top-level package, hatchling recurses, no new entry).
**Apply to:** tighten the constraint now (documented as "owned by the adapter; moves to the module's own pyproject in Phase 28"); regenerate + commit `uv.lock`.

## No Analog Found

> None. Every new module file maps onto a shipped Phase 22-26 module idiom (constructor injection,
> `Generic[T]` holder, the `__init__` barrel) or onto the exact in-place source being relocated
> (`bot.py`/`panel.py`). This phase introduces no novel mechanism — it is a pure relocation along
> the generic/app seam, oracle'd by the Phase-21 goldens.

## Metadata

**Analog search scope:** `yahir_reusable_bot/{config,scheduler,registry,lifecycle}/`, `weatherbot/interactive/{bot,panel}.py`, `weatherbot/scheduler/{wiring,daemon}.py`, `tests/test_{import_hygiene,injection_registry,golden_custom_ids}.py`, `pyproject.toml`.
**Files scanned:** 14 (read in full or targeted: bot.py 709L, panel.py 764L, holder.py, engine.py, registry.py, reload.py header, two test gates, wiring/daemon construction sites, pyproject).
**Pattern extraction date:** 2026-06-29
