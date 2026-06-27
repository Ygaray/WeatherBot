# Phase 17: Minimal Persistent Panel (Core Wiring) - Research

**Researched:** 2026-06-23
**Domain:** discord.py 2.7.1 interactive components (Views / Buttons / Selects) on a bare `discord.Client` gateway bot; off-loop fetch reuse; interaction-callback failure isolation
**Confidence:** HIGH (all discord.py API claims verified against the installed 2.7.1 source in `.venv`; all integration points grounded in the actual repo code)

## Summary

Phase 17 builds a single `PanelView(discord.ui.View, timeout=None)` with static `custom_id`s — a location `Select` (row 0), location-command buttons (row 1), and argless buttons (row 2) — each derived from `registry.BY_NAME`. The load-bearing correctness is in three mechanisms, all verified against discord.py 2.7.1: (1) the **single-ack contract** — exactly one `interaction.response.*` call per tap, spent on `edit_message(content="⏳ Fetching…", view=<disabled copy>)`, with the result landing via `edit_original_response(...)`; (2) the **`interaction_check` operator guard** — `send_message(ephemeral=True)` then `return False`, which (confirmed in the library source) early-returns *without* invoking `on_error`, so the rejection log must be explicit; (3) the **per-callback non-propagating envelope plus `View.on_error` backstop**, because the existing `on_message` envelope structurally does not cover the component path.

The panel is the **third caller** of the Phase-16 `dispatch_spec` seam: a button callback maps `custom_id → CommandSpec`, the in-memory selected location → `arg`, and `await dispatch_spec(...)` returns a `CommandReply` that `render_embed(reply)` turns into the in-place embed. No new on-loop blocking I/O is added — `dispatch_spec` already runs the fetch and the whole `dispatch_reply` ladder off-loop via `run_in_executor`.

The single non-trivial complication is **W2 (D-07/D-08): adding a real `weather` `CommandSpec`**. This is *not* purely additive. It breaks two existing anti-drift artifacts that must be updated in the same change: `tests/test_registry.py:74` (which asserts the Weather group is exactly `{alerts, sun, wind, next-cloudy, uv}`), and — the load-bearing one — `weatherbot/cli.py` registers a standalone `weather` subparser (line 731) **and** loops `registry.COMMANDS` adding a subparser per spec (line 815) with no skip-guard, so a `weather` registry spec causes `argparse.ArgumentError: conflicting subparser` at *every* CLI invocation. Today `!weather` text in the Discord bot is a **silent no-op** (no `weather` spec ⇒ `parse_command` returns `spec=None` ⇒ dropped), so W2 *adds* a working `!weather` reply; the "byte-identical" reference is `build_inbound_embed`'s field shape (Now / High·Low / Rain), which the new handler's `CommandReply` must reproduce through `render_embed`.

**Primary recommendation:** Create `weatherbot/interactive/panel.py` with one `PanelView` subclass plus `CmdButton(discord.ui.Button)` / `LocationSelect(discord.ui.Select)` subclasses (override `callback`); reuse `dispatch_spec` + `render_embed` verbatim; implement the three correctness mechanisms exactly per D-11/D-13/D-14/D-15; and scope W2 as a deliberate behavior-preserving refactor that adds the `weather` spec, adds a `weather_view` handler returning the Now/High·Low/Rain `CommandReply`, **adds a CLI registry-loop skip-guard for already-registered subparser names**, and updates `test_registry.py`'s Weather-group assertion — all proven by keeping the contractual suite green.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Render panel components (Select + Buttons) | Discord gateway (bot thread) | — | Components ride the existing gateway on `BotThread`; no new client/intent |
| Operator gate on every tap | `PanelView.interaction_check` (bot loop) | — | Component interactions never pass through `on_message`; the guard MUST live on the view |
| Map tap → command + location | `PanelView` callbacks (bot loop) | registry (`BY_NAME`) | `custom_id → CommandSpec`; in-memory `_selected_location → arg` |
| Fetch weather data | `dispatch_spec` → `run_in_executor` (executor thread) | `ForecastCache` | Blocking httpx must stay OFF the gateway loop (Pitfall 8) |
| Bind handler to its args | `dispatch_reply` ladder (executor thread) | registry handler | The one shared ladder — panel must not re-implement it |
| Render `CommandReply` → embed | `render_embed` (bot loop) | — | Pure in-memory; shared with `on_message`/CLI so surfaces can't drift |
| In-place result render | `interaction.edit_original_response` (bot loop, REST) | — | Edits the panel message; no new message |
| Failure isolation | per-callback `try/except` + `View.on_error` (bot loop) | `BotThread._run` swallow | The `on_message` envelope does NOT cover callbacks |
| Config snapshot for dropdown | `holder.current()` (lock-free) | — | Hot-reload re-derivation reads the live snapshot; never `holder.replace()` |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | 2.7.1 (pinned `>=2.7.1,<3`) | UI components (`discord.ui.View/Button/Select`), interaction ack/edit | Already the project's gateway lib; components ride the existing gateway — **no new dependency, no new intent** (milestone Out of Scope) `[VERIFIED: uv.lock + .venv import]` |

No new packages. The milestone Out-of-Scope table explicitly forbids "New gateway intent / new dependency / discord.py bump." `[CITED: .planning/REQUIREMENTS.md L66]`

### Supporting
Nothing new. The panel reuses, verbatim:
- `weatherbot.interactive.dispatch.dispatch_spec` (async off-loop fetch + ladder) `[VERIFIED: dispatch.py]`
- `weatherbot.interactive.bot.render_embed` (CommandReply → embed) `[VERIFIED: bot.py]`
- `weatherbot.interactive.registry.BY_NAME` / `CommandSpec` `[VERIFIED: registry.py]`
- `weatherbot.config.holder.ConfigHolder.current()` (lock-free snapshot) `[VERIFIED: holder.py]`
- `weatherbot.config.loader.resolve_location(config, None) → locations[0]` (default semantics D-03) `[VERIFIED: loader.py]`
- `weatherbot.interactive.lookup.UnknownLocationError` (bubbles from `dispatch_spec`) `[VERIFIED: lookup.py]`

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Subclass `Button`/`Select` + override `callback` | `@discord.ui.button`/`@discord.ui.select` decorators | Decorators are static (one method per fixed button); the panel derives buttons *dynamically* from a registry tuple, so subclass-and-override is the correct pattern `[VERIFIED: empirical test, see Code Examples]` |
| `edit_message` for the transient cue | `defer(thinking=True)` | `defer(thinking=True)` forces `deferred_channel_message_with_source` and obligates a *separate* ephemeral followup, splitting result rendering across two surfaces (D-15 rejected) `[VERIFIED: interactions.py defer() docstring]` |
| `edit_message` for the transient cue | plain `defer()` (`deferred_message_update`) | A component `defer()` shows **no** spinner, leaving the panel inert during a cold 1–3s fetch and inviting re-taps (D-15) `[CITED: PITFALLS.md Pitfall 2]` |

**Installation:** None — no packages added.

## Package Legitimacy Audit

> No external packages are installed in this phase. Audit is N/A.

The only library used (`discord.py` 2.7.1) is already pinned in `pyproject.toml`/`uv.lock` and present in `.venv`. No `npm`/`pip`/`cargo` install occurs. slopcheck not run (no new packages to verify).

## Architecture Patterns

### System Architecture Diagram

```
   Operator taps a component in the pinned panel message
                         │
                         ▼  (gateway: INTERACTION_CREATE — no message_content intent needed)
        discord.py dispatches by custom_id to PanelView
                         │
                         ▼
        ┌──────────────────────────────────────────────┐
        │  PanelView.interaction_check(interaction)      │  ← operator gate (EVERY tap)
        │  user.id == operator_id ?                      │
        └───────────────┬───────────────┬───────────────┘
              False      │               │  True
        send_message(    │               │
          ephemeral,     │               ▼
          generic) ;     │   ┌──────────────────────────────────┐
        log reject ;     │   │  item.callback(interaction)        │
        return False ────┘   │  wrapped in per-callback try/except│
        (on_error NOT fired) └──────┬───────────────────┬─────────┘
                                    │                   │
                       Select callback          Button callback
                       sets self._selected_      │
                       location = values[0]      ▼
                       (response.edit_message  ① response.edit_message(
                        re-render or defer)        content="⏳ Fetching…",
                                                   view=<disabled copy>)   ← single ack, <3s
                                                │
                                                ▼  arg = _selected_location (loc btns)
                                                   arg = None (status/alerts)
                                   await dispatch_spec(spec, arg, cache, config, loop, …)
                                                │
                                                ▼  run_in_executor (OFF the gateway loop)
                                   ForecastCache.lookup → httpx → Forecast
                                   dispatch_reply ladder → CommandReply
                                                │
                                                ▼
                                   embed = render_embed(reply)
                                                │
                                   ② await interaction.edit_original_response(
                                        content=None, embed=embed,
                                        view=<re-enabled panel>)          ← in-place, no new msg
                                                │
                       (any exception) ─────────┴──► except: log + generic in-place edit
                                                         (never re-raised → never reaches scheduler)
```

`config = holder.current()` is read per tap (lock-free snapshot) so a hot-reload is picked up on the next interaction. `UnknownLocationError` from `dispatch_spec` is caught at the callback and rendered as a generic-but-helpful in-place edit (mirrors `on_message`'s D-06 call-site catch).

### Recommended Project Structure
```
weatherbot/interactive/
├── panel.py              # NEW — PanelView + CmdButton + LocationSelect (mirrors bot.py/dispatch.py style)
├── bot.py                # render_embed (reused); BotThread (panel lives here, Phase 18 wires add_view)
├── dispatch.py           # dispatch_spec (reused verbatim)
├── registry.py           # MOD — add the `weather` CommandSpec (D-07)
└── commands/
    └── weather_views.py  # MOD — add `weather_view(result) -> CommandReply` (Now/High·Low/Rain) OR a new module (Claude's Discretion)
weatherbot/cli.py         # MOD — add a registry-loop skip-guard so the new `weather` spec doesn't double-register the subparser (D-08, load-bearing)
tests/test_panel.py       # NEW — gateway-free callback tests (mirror test_bot.py's fake-interaction pattern)
tests/test_registry.py    # MOD — update the Weather-group assertion to include `weather` (D-08)
```
Per Claude's Discretion (CONTEXT L131–136): exact attribute names, the disabled-view helper, and whether the weather handler lives in `weather_views.py` or its own module are the planner's call. `panel.py` should follow the `interactive/` import-acyclic discipline (module-top light imports, heavy types under `TYPE_CHECKING`) `[CITED: 16-PATTERNS.md "Acyclic lazy / module-top imports"]`.

### Pattern 1: Persistent `PanelView` with dynamic registry-derived children
**What:** One `View(timeout=None)` whose Select + Buttons all carry static `custom_id`s, built from a curated name tuple resolved through `BY_NAME`.
**When to use:** The panel root. Phase 17 wires callbacks + correctness; **Phase 18** does `add_view` in `setup_hook`. Phase 17 construction MUST already satisfy `view.is_persistent() == True` (verified: requires `timeout is None` AND every child has an explicit `custom_id`) so Phase 18 can register it without a `ValueError`.
**Example:**
```python
# Source: VERIFIED empirically against discord.py 2.7.1 (.venv)
import discord

class CmdButton(discord.ui.Button):
    def __init__(self, name: str, panel: "PanelView", *, row: int):
        super().__init__(
            label=name,                       # plain text label (emoji is Phase 20)
            custom_id=f"wb:cmd:{name}",       # static, deterministic, <100 chars
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self._name = name
        self._panel = panel
    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_command(interaction, self._name)  # per-callback envelope inside

class LocationSelect(discord.ui.Select):
    def __init__(self, panel: "PanelView", locations: list[str]):
        super().__init__(
            custom_id="wb:loc:select",        # static
            placeholder="Location",
            options=[discord.SelectOption(label=n, value=n) for n in locations],
            row=0,
        )
        self._panel = panel
    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_select(interaction, self.values[0])

class PanelView(discord.ui.View):
    def __init__(self, *, holder, operator_id, cache, daemon_state=None):
        super().__init__(timeout=None)        # REQUIRED for persistence
        ...
        self._selected_location = holder.current().locations[0].name  # D-03 default
```
`view.is_persistent()` returns `True` for the assembled view (verified). `Select.values` is `[]` outside an active interaction (the #7284 footgun — see Pitfall 3).

### Pattern 2: Single-ack defer-then-edit (D-14/D-15)
**What:** Exactly one `interaction.response.*` call per tap.
**When to use:** Every fetch-backed button.
**Example:**
```python
# Source: VERIFIED against discord.py 2.7.1 interactions.py (edit_message acks; edit_original_response is a followup)
async def on_command(self, interaction: discord.Interaction, name: str) -> None:
    try:
        spec = registry.BY_NAME[name]
        arg = self._selected_location if spec.takes_location else None  # D-04 argless → None
        # ① the SINGLE response.* call — acks (<3s), shows the cue, disables to stop double-taps
        await interaction.response.edit_message(content="⏳ Fetching…", view=self._disabled_copy())
        loop = asyncio.get_running_loop()
        config = self._holder.current()
        try:
            reply = await dispatch_spec(spec, arg, cache=self._cache, config=config,
                                        loop=loop, daemon_state=self._daemon_state)
        except UnknownLocationError as exc:
            await interaction.edit_original_response(content=str(exc), embed=None, view=self)
            return
        embed = render_embed(reply)
        # ② result lands via the FOLLOWUP path — NOT a second response.* call
        await interaction.edit_original_response(content=None, embed=embed, view=self)
    except Exception:  # noqa: BLE001 — non-propagating (Pitfall 1)
        _log.exception("panel command callback failed", custom_id=f"wb:cmd:{name}")
        await self._safe_error_edit(interaction)
```
**Verified facts:** `response.edit_message(...)` raises `InteractionResponded` if the interaction was already acked, only works for `InteractionType.component`/`modal_submit`, and *is* the ack `[VERIFIED: interactions.py:1120,1198]`. `edit_original_response` exists on `Interaction` (line 512) and goes through the REST/followup path — safe after the `edit_message` ack `[VERIFIED]`. Never call a second `response.*` (double-ack `InteractionResponded`, Pitfall 3 in PITFALLS.md).

### Pattern 3: `interaction_check` operator gate with explicit reject log (D-11/D-12/D-13)
**What:** The single operator gate; runs before any child callback.
**Example:**
```python
# Source: VERIFIED against discord.py 2.7.1 ui/view.py:_scheduled_task L591-593
async def interaction_check(self, interaction: discord.Interaction) -> bool:
    if interaction.user.bot:                       # defense-in-depth (mirrors author.bot rung)
        return False
    if interaction.user.id != self._operator_id:
        # Explicit reject log — on_error does NOT fire on a clean return False (D-13)
        _log.info("panel reject (non-operator)",
                  user_id=interaction.user.id,
                  custom_id=(interaction.data or {}).get("custom_id"))
        await interaction.response.send_message(
            "This panel is in use by someone else.",  # generic, identity-free (D-12)
            ephemeral=True,
        )
        return False
    return True
```
**Verified:** in `_scheduled_task`, `allow = await item._run_checks(...) and await self.interaction_check(...)`; `if not allow: return` — a clean `False` early-returns and **never** reaches `on_error`; `on_error` is only called from the surrounding `except` (so it fires only when the check or a callback *raises*) `[VERIFIED: ui/view.py:587-600]`. Therefore the explicit `_log.info` here is the SOLE audit record of a rejection (D-13). The reject path's `send_message(ephemeral=True)` is the single ack for that interaction — it both prevents the foreign user's "This interaction failed" toast and physically cannot edit the shared panel (D-11).

### Pattern 4: `View.on_error` backstop (D-13)
**What:** Override `on_error` so an escaped callback exception is logged in structlog format and answered generically — never a silent dead button.
```python
# Source: VERIFIED against discord.py 2.7.1 ui/view.py:568 (default just logs to library logger)
async def on_error(self, interaction, error, item) -> None:
    _log.exception("panel view on_error backstop", custom_id=getattr(item, "custom_id", None))
    await self._safe_error_edit(interaction)  # is_done()-guarded (see Pitfall 4)
```
This is a *backstop* — the per-callback `try/except` (Pattern 2) is the primary boundary. Both are required (PITFALLS.md Pitfall 1; the `on_message` envelope does not cover this path).

### Anti-Patterns to Avoid
- **Re-reading `Select.values` inside a button callback** — a button interaction does not carry the dropdown's values; even a `default=True` option reports `[]` until the operator actively changes the selection (#7284). Hold selection in `self._selected_location` (D-01/D-02). `[VERIFIED: empirical — Select.values == [] outside interaction]`
- **Encoding selection in `custom_id`** — breaks the static-id persistence contract (D-02) and risks the 100-char cap.
- **`defer()` + `response.edit_message()`** — double-ack `InteractionResponded` (Pitfall 3).
- **`defer(thinking=True)`** — splits rendering across an ephemeral followup surface (D-15).
- **Blocking I/O on the gateway loop** — always go through `dispatch_spec`'s `run_in_executor` (Pitfall 8).
- **Touching the scheduler / `holder.replace()` from a callback** — panel is read-only (Pitfall 8).
- **Relying on the library to enforce `custom_id ≤100` / `label ≤80`** — it does NOT (see Pitfall 5); add a build-time assert (D-10).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Map tap → command + fetch + bind | A panel-side `if name == "weather": …` ladder | `registry.BY_NAME[name]` + `dispatch_spec(...)` | The whole point of Phase 16 (PANEL-10): one ladder, no drift |
| CommandReply → embed | A second embed builder for the panel | `render_embed(reply)` | Surfaces (bot/CLI/panel) share one renderer so they can't drift |
| Off-loop fetch | A panel `run_in_executor` call | `dispatch_spec` (already off-loops fetch + ladder) | Avoids re-deriving the off-loop + cache-key contract (WR-02) |
| Operator gate | A guard inside each callback | `View.interaction_check` | discord.py's built-in "only this user" mechanism; runs once before all children `[VERIFIED]` |
| "Working" feedback | A separate progress message | `response.edit_message(content="⏳ …")` in-place | One ack, no new message (D-14, PANEL-06) |
| Default location | Re-implementing default-selection | `config.locations[0].name` (mirrors `resolve_location(config, None)`) | D-03 — exact existing precedent |

**Key insight:** Phase 16 already centralized everything risky. The panel's only *new* code is the discord.py wiring (View/Select/Button + ack/edit/guard/envelope). Anything that fetches, binds, or renders must route through the existing seams — building a parallel path is the one thing PANEL-10 exists to prevent.

## Common Pitfalls

> The milestone-level `.planning/research/PITFALLS.md` (12 pitfalls) is the authoritative reference and MUST be read by the planner. The Phase-17-relevant ones are 1, 2, 3, 5, 7, 8, 9, 10. Below are the phase-specific ones, with empirical verification added.

### Pitfall 1: The W2 CLI subparser collision (the load-bearing D-08 consequence)
**What goes wrong:** Adding a `weather` `CommandSpec` to the registry makes `cli.py:815`'s `for _spec in registry.COMMANDS: subparsers.add_parser(_spec.name, …)` call `add_parser("weather", …)` — but `cli.py:731` *already* registers a standalone `weather` subparser. argparse raises `ArgumentError: conflicting subparser: weather` at **every** CLI invocation, breaking the whole CLI (not just `weather`). `[VERIFIED: cli.py:731-747 + 815-817, no skip-guard]`
**Why it happens:** The registry-loop has no "skip names already registered" guard; it assumes registry names are disjoint from the hand-written subparsers.
**How to avoid:** In the registry loop, skip any spec whose name is already a registered subparser (e.g. track the hand-written names in a set and `continue`), so the standalone `weather`/`run`/`check`/… subparsers win and the loop only adds genuinely-new registry commands. The standalone `weather` subparser keeps its `-v/--verbose` flag and quiet-by-default path (`cli.py:745,848,860`), preserving CLI behavior byte-for-byte.
**Warning signs:** `pytest tests/test_cli.py` red with `ArgumentError`; `weatherbot --help` raises.

### Pitfall 2: The `test_registry.py` Weather-group anti-drift assertion
**What goes wrong:** `tests/test_registry.py:74` asserts `weather == {"alerts", "sun", "wind", "next-cloudy", "uv"}` exactly. Adding the `weather` spec to the Weather group makes this assertion fail. `[VERIFIED: test_registry.py:68-75]`
**How to avoid:** Update the assertion to include `"weather"` in the same change that adds the spec. This is an *intended* anti-drift trip — the planner must treat it as part of W2, not a surprise.
**Warning signs:** `test_groups_are_weather_info_and_forecast` red.

### Pitfall 3: `Select.values` is empty outside an active change (#7284)
**What goes wrong:** Reading the Select's `values` in a *button* callback (or before the operator changes the dropdown) returns `[]`. `[VERIFIED: empirical — Select.values == [] with no interaction; ui/select.py:291-293]`
**How to avoid:** Set `self._selected_location = self.values[0]` *inside the Select's own callback*, and read the attribute (never `select.values`) in button callbacks (D-01/D-02). Default it to `locations[0].name` in `__init__` (D-03) so the first button tap before any dropdown use still resolves.
**Warning signs:** Location buttons act on the wrong city / `IndexError` on `values[0]`.

### Pitfall 4: Error reply after an ack — `is_done()` guard
**What goes wrong:** In a callback's `except`, calling `interaction.response.send_message(...)` after `edit_message` already acked raises `InteractionResponded`. `[VERIFIED: interactions.py is_done() L811; PITFALLS.md Pitfall 3]`
**How to avoid:** A `_safe_error_edit(interaction)` helper that checks `interaction.response.is_done()`: if done, use `interaction.edit_original_response(...)` / `interaction.followup.send(..., ephemeral=True)`; if not, `interaction.response.send_message(...)`. Wrap that helper in its own try/except (best-effort; never re-raise) — mirrors `bot.py:300-303`.
**Warning signs:** `InteractionResponded` in logs from the error path.

### Pitfall 5: discord.py does NOT enforce `custom_id ≤100` / `label ≤80` at construction
**What goes wrong:** `discord.ui.Button(custom_id="z"*101)` and `label="x"*81` construct *silently*; Discord rejects them at **send** time with `HTTPException`, surfacing as the generic error with no panel. `[VERIFIED: empirical — 101-char custom_id and 81-char label both accepted at construction]`
**How to avoid:** Add the D-10 minimal build-time `__init__` assertion: rows ≤ 5, ≤ 5 per row, each `custom_id` ≤ 100, each `label` ≤ 80, plus `len(locations) ≤ 25` (Select option cap, which the lib *does* enforce with `ValueError` at `add_option`). `View.add_item` enforces the per-row width ≤5 and ≤25-children caps with `ValueError`, so the panel inherits those; the id/label caps are the ones you must add yourself. `[VERIFIED: ui/view.py:189-193,785-787; ui/select.py:576-577]`
**Warning signs:** `HTTPException` on first panel send; garbled/truncated labels.

## Runtime State Inventory

> N/A for the panel construction itself, but the `weather` spec (W2) touches shared registry/CLI surfaces — captured below as the analog "what else reads this string?" check.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the panel holds selection only in-memory (`_selected_location`); restart amnesia is deferred to Phase 18 (D-05). Verified: no datastore touched. | None |
| Live service config | None — no external service config embeds the new `weather` spec name. The pinned panel *message* (Discord-stored) is Phase 18's concern. | None |
| OS-registered state | None — no systemd unit / task references command names. (The live `yahir-mint` daemon runs an editable install; a restart is the deploy loop per MEMORY.) | None |
| Secrets/env vars | None — no secret key references "weather". | None |
| Build artifacts / installed packages | The editable install on `yahir-mint` must be restarted to pick up `panel.py` + the registry/CLI edits (standard deploy loop). The new `weather` subcommand appears in `weatherbot --help` and as a CLI subcommand (D-08 accepted consequence). | Restart the daemon after deploy (existing ops loop) |

**The W2 derived-surface sweep (the canonical "after the source change, what else carries this?" question):** adding the `weather` registry spec propagates to (1) `render_help` output / `!help` (new line), (2) the CLI registry-loop subparser builder (collision — Pitfall 1), (3) `test_registry.py` Weather-group assertion (Pitfall 2), (4) any test enumerating `COMMANDS`. All four are in-repo and caught by the contractual suite — none are hidden runtime state.

## Code Examples

### Building the disabled-copy view for the transient cue (D-14)
```python
# A fresh PanelView with every item disabled — neutralizes double-taps during the fetch.
def _disabled_copy(self) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for child in self.children:
        # re-add a disabled clone OR set child.disabled=True on a rebuilt view;
        # simplest: iterate self.children, copy custom_id/label/style, disabled=True.
        ...
    return v
# "Disable-only, no transient text" is the acceptable lighter fallback (D-15) if the
# transient-content bookkeeping is troublesome — keeps the anti-double-tap guarantee.
```

### Hot-reload dropdown re-derivation (PANEL-02)
```python
# Source: VERIFIED — holder.current() is a lock-free snapshot (holder.py:50-57)
# Re-derive Select options from the live config on each render so a hot-reload that
# adds/removes a location is reflected. (Phase 17 re-derives on construct/edit; the
# persistent re-registration is Phase 18.)
locations = [loc.name for loc in self._holder.current().locations]
```

### The new `weather` handler must match `build_inbound_embed` (D-07/D-08)
```python
# Source: bot.py:194-214 build_inbound_embed — the byte-identical reference shape
# build_inbound_embed sets: title=f"Weather — {forecast.location}", fields:
#   ("Now", forecast.temp_display), ("High / Low", f"{high_display} / {low_display}"),
#   ("Rain", f"{forecast.rain_chance}%")
# The new weather_view(result) -> CommandReply must produce the SAME fields so
# render_embed yields the identical embed:
def weather_view(result: LookupResult) -> CommandReply:
    f = result.forecast
    return CommandReply(
        title=f"Weather — {f.location}",
        lines=(
            ("Now", f.temp_display),
            ("High / Low", f"{f.high_display} / {f.low_display}"),
            ("Rain", f"{f.rain_chance}%"),
        ),
    )
# Register: CommandSpec("weather", "Weather", "<summary>", True) wired to weather_view;
# ladder catch-all #4 (takes_location) already calls handler(result) — no ladder edit.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `!weather` text → `build_inbound_embed` directly | `!weather` is currently a **no-op** in the bot (no `weather` registry spec ⇒ `parse_command` returns `spec=None` ⇒ dropped) | Phase 12 (registry-driven `on_message`) | W2 *re-enables* `!weather` as a real reply via the registry, not a regression to fix |
| Per-surface dispatch ladders | One shared `dispatch_spec`/`dispatch_reply` | Phase 16 | The panel is the third caller; zero new dispatch code |
| `interaction.response.send_message` returns nothing | returns `InteractionCallbackResponse` (since 2.5) | discord.py 2.5 | Not load-bearing here; just don't assume `None` |

**Deprecated/outdated:**
- Nothing. discord.py 2.7.1 is current and pinned; the `View`/`interaction_check`/`edit_message` API used here is stable across 2.x.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The standalone CLI `weather` subparser must be *kept* (and the registry loop skip-guarded) rather than removed, to preserve `-v/--verbose` + quiet-by-default behavior | Pitfall 1 / D-08 | LOW — both options preserve behavior; if the planner removes `p_weather` instead, it must re-add `-v` and the quiet path to the registry-built subparser or accept a documented behavior change. Either way the byte-identical-reply guard (the embed/text content) is unaffected. |
| A2 | `_safe_error_edit` should prefer `edit_original_response` after an ack and `send_message(ephemeral=True)` before one | Pitfall 4 | LOW — exact error-reply surface is cosmetic; the load-bearing requirement is "never re-raise," which any `is_done()`-guarded form satisfies. |
| A3 | The disabled-copy view (D-14) is worth the bookkeeping over disable-only | Code Examples | NONE — D-15 explicitly blesses "disable-only, no transient text" as an acceptable fallback. |

**All discord.py API claims are VERIFIED (not assumed)** against the installed 2.7.1 source; the assumptions above are implementation-choice judgments, not unverified facts.

## Open Questions

1. **Where does the `weather_view` handler live?** (Claude's Discretion, CONTEXT L134.)
   - What we know: it parallels the existing `weather_views.py` handlers and reads only `result.forecast`.
   - Recommendation: add it to `weather_views.py` (sibling handlers, same import shape) unless the planner prefers a dedicated module. No correctness impact either way.

2. **Disabled-copy vs disable-only for the transient cue.** (D-14 vs D-15 fallback.)
   - Recommendation: start with disable-only (`disabled=True` on a rebuilt view) for simplicity; upgrade to a full disabled copy only if the UX needs it. Both keep the anti-double-tap guarantee.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| discord.py | All panel components | ✓ | 2.7.1 | — (pinned; no bump allowed) |
| Python | runtime | ✓ | 3.12 (.venv) | — |

**Missing dependencies with no fallback:** None.
No live Discord gateway is needed for Phase-17 tests — every callback is driven gateway-free with fake `Interaction` objects (mirrors `test_bot.py`'s fake-message pattern).

## Validation Architecture

> nyquist_validation is enabled (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (configured: `[tool.pytest.ini_options]`, `testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) `[VERIFIED: pyproject.toml:33-36]` |
| Config file | `pyproject.toml` |
| Quick run command | `uv run pytest tests/test_panel.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PANEL-02 | Dropdown options derived from `holder.current().locations`; re-derive on hot-reload | unit | `uv run pytest tests/test_panel.py::test_dropdown_from_config -x` | ❌ Wave 0 |
| PANEL-03 | Location button → `dispatch_spec(spec, selected_location)` → embed | unit | `uv run pytest tests/test_panel.py::test_location_button_uses_selection -x` | ❌ Wave 0 |
| PANEL-04 | Argless button (status/alerts) passes `arg=None`, ignores selection | unit | `uv run pytest tests/test_panel.py::test_argless_button_ignores_selection -x` | ❌ Wave 0 |
| PANEL-05 | Single `response.edit_message` ack before fetch (no second `response.*`) | unit | `uv run pytest tests/test_panel.py::test_single_ack_before_fetch -x` | ❌ Wave 0 |
| PANEL-06 | Result lands via `edit_original_response` (in-place; no `channel.send`) | unit | `uv run pytest tests/test_panel.py::test_result_renders_in_place -x` | ❌ Wave 0 |
| PANEL-08 | Non-operator: ephemeral generic reject, `return False`, no handler runs, reject logged | unit | `uv run pytest tests/test_panel.py::test_non_operator_rejected_leak_free -x` | ❌ Wave 0 |
| D-13 | `interaction_check` clean `False` does NOT trigger `on_error` (reject log is the sole audit) | unit | `uv run pytest tests/test_panel.py::test_reject_does_not_call_on_error -x` | ❌ Wave 0 |
| PANEL-10/D-10 | `view.is_persistent()` True; build-time layout assert (rows/per-row/id≤100/label≤80) | unit | `uv run pytest tests/test_panel.py::test_view_persistent_and_layout_bounded -x` | ❌ Wave 0 |
| D-07/D-08 | New `weather` reply renders to the same embed as `build_inbound_embed` (Now/High·Low/Rain) | unit | `uv run pytest tests/test_panel.py::test_weather_spec_byte_identical -x` | ❌ Wave 0 |
| D-08 | `tests/test_registry.py` Weather group updated; `tests/test_cli.py` green (no subparser collision) | unit (existing, MOD) | `uv run pytest tests/test_registry.py tests/test_cli.py` | ✅ exists (update) |
| isolation | A raising panel callback never propagates / never reaches the scheduler (port CMD-16) | unit | `uv run pytest tests/test_panel.py::test_callback_raise_isolated -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_panel.py -x`
- **Per wave merge:** `uv run pytest` (full suite — the contractual anti-drift suite must stay green: `test_registry.py`, `test_dispatch.py`, `test_bot.py`, `test_command.py`, `test_cli.py`, `test_command_views.py`)
- **Phase gate:** Full suite green before `/gsd-verify-work`; plus the two-gate self-UAT on the live `yahir-mint` daemon (tap each button, verify in-place edit + operator-only reject) per the global Verification Policy.

### Wave 0 Gaps
- [ ] `tests/test_panel.py` — covers PANEL-02/03/04/05/06/08, D-07/08/10/13, isolation. Needs a fake-`Interaction` factory (an `AsyncMock`-shaped object with `.user.id`, `.user.bot`, `.data["custom_id"]`, `.response.edit_message`/`.response.send_message`/`.response.is_done`, `.edit_original_response`, `.followup.send`) — mirror `conftest._make_fake_discord_message` and add a sibling `_make_fake_interaction`.
- [ ] `tests/conftest.py` — add the `fake_interaction` fixture/factory.
- [ ] No framework install needed (pytest present).
- [ ] Existing files to UPDATE (not create): `tests/test_registry.py` (Weather-group assertion), and confirm `tests/test_cli.py` still green after the skip-guard.

## Security Domain

> security_enforcement enabled (config.json `workflow.security_enforcement: true`, ASVS level 1).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth subsystem; the "operator" is a Discord user id baked at construction |
| V3 Session Management | no | No sessions; interaction tokens are Discord-managed (15-min followup window — Pitfall 9) |
| V4 Access Control | **yes** | `View.interaction_check` enforces `user.id == operator_id` on EVERY tap (PANEL-08); the only authz boundary on the component path |
| V5 Input Validation | **yes** | `custom_id` is matched against `registry.BY_NAME` (allow-list); selected location is matched against configured locations via `resolve_location` (rejects spoofed values → `UnknownLocationError`, caught and rendered generically). Never interpolate user input into `str.format`/`eval`/shell (the existing `command.py` T-06-01 contract). |
| V6 Cryptography | no | No crypto; secrets (token/webhook) never enter a callback log or user-facing message (reuse the v1.1 rule) |
| V7 Error Handling & Logging | **yes** | Per-callback envelope + `on_error` backstop log via structlog, never re-raise, never echo the token/webhook/operator identity (D-12); reject log is server-side only (D-13) |

### Known Threat Patterns for discord.py interactive panel
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Non-operator drives the shared pinned panel | Elevation of Privilege | `interaction_check` returns `False` for non-operators; ephemeral leak-free reject (PANEL-08, D-11) `[VERIFIED]` |
| Reject message leaks panel/command/operator identity | Information Disclosure | Generic identity-free copy ("This panel is in use by someone else."); never interpolate `interaction.user`/`custom_id`/command (D-12) |
| Spoofed `custom_id` / select value reaching a handler | Tampering | Allow-list: `BY_NAME[name]` (KeyError → caught) and `resolve_location` (UnknownLocationError → caught); both reject unknown values |
| Token / webhook URL in a callback error reply or log | Information Disclosure | Reuse v1.1 rule — generic reply, no secret in any log/message; `dispatch_spec`/`UnknownLocationError` already never carry the appid/URL `[VERIFIED: lookup.py docstring T-06-05]` |
| Callback exception leaking onto the briefing scheduler thread | Denial of Service | Per-callback non-propagating `try/except` + `View.on_error`; panel touches only read-only registry + `ForecastCache` + `holder.current()`; never the scheduler or `holder.replace()` (Pitfall 8, PANEL-11 seam) |
| Blocking the gateway loop (heartbeat miss → reconnect storm) | Denial of Service | All blocking work off-loop via `dispatch_spec`'s `run_in_executor`; no on-loop httpx/`time.sleep` in a callback |

## Sources

### Primary (HIGH confidence)
- discord.py 2.7.1 installed source (`.venv/.../discord/`): `ui/view.py` (`interaction_check` L533, `on_error` L568, `_scheduled_task` L587-600 — confirms clean `False` skips `on_error`; `is_persistent` L678; `add_item` width/children caps L189,785), `interactions.py` (`edit_message` L1120 + ack/`InteractionResponded`, `defer` L823 + thinking note, `edit_original_response` L512, `is_done` L811, `is_expired` L442), `ui/select.py` (`values` L291/493, 25-option cap L576), `ui/button.py` (custom_id≤100/label≤80 doc-only, NOT enforced at construct), `client.py` (`setup_hook` L623, `add_view` L3166) — all VERIFIED
- Empirical probe (`.venv/bin/python`): persistent `PanelView` assembles to `is_persistent()==True`; `Select.values==[]` outside an interaction (#7284); 101-char custom_id + 81-char label accepted at construction without error — VERIFIED
- Repo source: `weatherbot/interactive/{dispatch,bot,registry,command,lookup}.py`, `weatherbot/config/{holder,loader,models}.py`, `weatherbot/interactive/commands/{__init__,weather_views}.py`, `weatherbot/cli.py` (subparser collision L731+815) — HIGH
- `tests/test_registry.py:74` (Weather-group anti-drift assertion), `tests/test_bot.py` (gateway-free fake-message pattern), `tests/conftest.py` (`_make_fake_discord_message`) — HIGH
- `.planning/research/PITFALLS.md` (12-pitfall milestone reference, authoritative for the panel mechanics) — HIGH
- `.planning/phases/17-.../17-CONTEXT.md` (D-01..D-15 locked), `16-PATTERNS.md` / `16-CONTEXT.md` (dispatch seam + import discipline), `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` — HIGH

### Secondary (MEDIUM confidence)
- None required — every claim was verified against installed source or repo code.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; the one library is pinned/installed/verified.
- Architecture / discord.py mechanics: HIGH — every API claim verified against installed 2.7.1 source + empirical probe.
- Pitfalls: HIGH — milestone PITFALLS.md plus two phase-specific repo-grounded discoveries (CLI subparser collision, registry test assertion) verified in source.
- W2 (D-07/D-08): HIGH — collision and anti-drift trips located at exact line numbers; byte-identical reference shape extracted from `build_inbound_embed`.

**Research date:** 2026-06-23
**Valid until:** ~2026-07-23 (stable; discord.py pinned `<3`, repo seams from Phase 16 are settled). Re-verify only if discord.py is bumped (forbidden this milestone) or the registry/CLI subparser layout changes.
