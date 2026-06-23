# Stack Research

**Domain:** v1.3 — Discord interactive control panel (message components: buttons, string select menus, restart-durable persistent views with in-place message editing) on the EXISTING discord.py gateway bot
**Researched:** 2026-06-23
**Confidence:** HIGH

> Scope note: This file covers ONLY the NEW capability for v1.3 (the tap-to-drive panel).
> The full prior stack (Python 3.12+, uv, httpx/One Call 3.0, APScheduler 3.x, tenacity,
> structlog, SQLite, discord-webhook outbound, **discord.py inbound**, watchfiles, cachetools,
> pydantic/-settings, systemd) is treated as fixed and NOT re-evaluated. Earlier STACK rationale
> for v1.0/v1.1 lives in git history and CLAUDE.md.

## Bottom Line

**No new dependency. No version bump. No migration off prefix commands.**

The already-pinned `discord.py>=2.7.1,<3` covers 100% of v1.3: buttons (`discord.ui.Button`),
string select menus (`discord.ui.Select`), the `discord.ui.View` container, restart-durable
persistent views (`View(timeout=None)` + stable `custom_id` + `Client.add_view()` in
`Client.setup_hook()`), and in-place editing (`interaction.response.edit_message(...)`). All of
these ship in discord.py since **2.0** and are present on the **bare `discord.Client`** the bot
already uses — `commands.Bot` is NOT required. `2.7.1` is the current latest PyPI release
(verified 2026-06-23), so the existing pin is already at HEAD.

v1.3 is a code-only change inside the existing `interactive/bot.py` `BotThread`. The roadmap
should carry **zero stack/dependency tasks**.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **discord.py** | `>=2.7.1,<3` (already pinned — no change) | Buttons, string-select dropdown, `discord.ui.View`, persistent views, interaction handling, in-place embed editing | Already the inbound-gateway dependency since v1.1. The component/UI system (`discord.ui`) is first-party and complete; nothing else implements Discord message components for Python. The current pin (`2.7.1`) is the latest release, so the project is already on the version that ships every needed API. The `<3` cap correctly fences a hypothetical breaking 3.x. |

### Supporting Libraries / stdlib (reused — NO new dependency)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **(none new)** | — | — | The entire component/view/persistence/edit stack is internal to discord.py. v1.3 reuses the v1.2 `registry.COMMANDS` (single source of truth for the button grid), the existing `ForecastCache` (off-loop fetch on a tap), `render_embed(CommandReply)` (so panel output cannot drift from text output), and `operator_id` from pydantic-settings config (the per-tap guard). |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest (already `>=9.0.3`) | Gateway-free tests of views + callbacks | `ui.View`/`Button`/`Select` are plain objects — assert on `label`, `custom_id`, `options`, `disabled` without a live gateway. Callbacks take a `discord.Interaction`; drive them with a fake interaction whose `response.edit_message`/`response.defer` are `AsyncMock`s, mirroring the existing `build_on_message` gateway-free test style. |
| ruff (already `>=0.15.16`) | Lint/format | Callbacks are `async def` decorated methods — same as existing event handlers; no config change. |

## Required APIs (all present in the pinned version — what the roadmap wires into)

| Capability | discord.py API | Added | On bare `discord.Client`? |
|------------|----------------|-------|---------------------------|
| Button | `discord.ui.Button` / `@discord.ui.button(..., custom_id=...)` | 2.0 | Yes (View item) |
| String dropdown | `discord.ui.Select` / `@discord.ui.select(..., custom_id=..., options=[...])` | 2.0 | Yes (View item) |
| Component container | `discord.ui.View` | 2.0 | Yes |
| Attach components to a message | `Messageable.send(..., view=...)` and `Message.edit(..., view=...)` | 2.0 | Yes — works on the **normal `on_message` reply path** (`message.channel.send(view=...)`); no slash command needed |
| Restart-durable view | `discord.ui.View(timeout=None)` + every item a stable `custom_id` | 2.0 | Yes |
| Re-register after restart | `Client.add_view(view)` inside `Client.setup_hook()` | 2.0 | **Yes — `add_view` and `setup_hook` are defined on `discord.Client`, not just `commands.Bot`** (verified against the stable API reference) |
| In-place result rendering | `interaction.response.edit_message(embed=..., view=...)` | 2.0 | Yes (on the `Interaction`) |
| Ack a slow tap within 3s | `interaction.response.defer()` then `interaction.edit_original_response(...)` | 2.0 | Yes |
| Operator gate on a tap | `interaction.user.id` (+ optional `View.interaction_check`) | 2.0 | Yes |

## Installation

```bash
# Nothing to install. The capability already ships in the pinned dependency:
#   discord.py>=2.7.1,<3   (already in pyproject.toml [project].dependencies)
#
# Sanity-check the resolved version on the host before building:
uv run python -c "import discord; print(discord.__version__)"   # expect 2.7.x
```

## Integration Notes (into the existing `BotThread` / `build_client`)

Confirmed against `weatherbot/interactive/bot.py`. All additive, all inside the already-isolated
bot thread:

1. **Register persistent views in `setup_hook`, not `on_ready`.** Today `build_client` wires only
   `on_ready`/`on_message` on a bare `discord.Client`. Override `setup_hook` on the client (or a
   `Client` subclass) and call `self.add_view(PanelView(...))` so the pinned panel's buttons are
   live immediately after login and survive every `BotThread` restart. `setup_hook` runs once after
   login, before the gateway connects — the documented place for this.
2. **The panel is sent over the existing reply path.** A `!panel`-style prefix command in the
   registry-driven `on_message` does `await message.channel.send(embed=..., view=PanelView(...))`.
   No new inbound infrastructure — PROJECT.md already notes button clicks ride the existing gateway.
3. **Button/select callbacks reuse v1.2 registry + `ForecastCache`.** Each command button maps to a
   `registry.COMMANDS` spec; the callback runs the same off-loop fetch
   (`loop.run_in_executor(None, cache.lookup, ...)`) the text path uses, then
   `interaction.response.edit_message(embed=render_embed(reply), view=self)` for in-place rendering.
   `render_embed(CommandReply)` is reused unchanged, so panel output can't drift from text output.
4. **Operator gate carries over.** An early `if interaction.user.id != operator_id` check (or
   `View.interaction_check` returning `False`) makes non-operator taps on the public pinned panel
   get a polite reject — same single-operator stance as the text guard ladder. `operator_id` is
   already injected into the client builder.
5. **The one new timing constraint: 3-second interaction ack.** Because the fetch runs off-loop,
   either rely on a fast cache hit or `await interaction.response.defer()` first, then
   `interaction.edit_original_response(...)`. Keep a non-propagating try/except around each callback
   (mirroring the existing `on_message` envelope) so a raising callback never reaches the bot
   thread / scheduler (failure isolation, D-11).

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Keep bare `discord.Client` + `add_view`/`setup_hook` | Migrate to `commands.Bot` | Only if you later want the `ext.commands` framework (cogs) or app-command trees. Persistent views work identically on `discord.Client` (both inherit `add_view`/`setup_hook` from the same base since 2.0), so migrating buys **nothing** for v1.3 and would churn the validated `build_client`/`BotThread`. Do NOT migrate. |
| Persistent `View(timeout=None)` + `custom_id` | Ephemeral timed views (default `timeout=180`) | Use a timed view only for transient throwaway prompts. The milestone requires a **pinned panel that survives restarts**, which mandates `timeout=None` + stable `custom_id` + `add_view`. A timed view goes dead after the timeout and after every restart — wrong for a pinned panel. |
| Embed + classic `View` (button grid + select) | `discord.ui.LayoutView` / Components V2 (`Container`, `Section`, `TextDisplay`, `ActionRow`) | LayoutView (in 2.6+/2.7.x) is a richer layout system but a bigger surface and replaces the embed body. For a location dropdown + a grid of command buttons rendering into an embed, classic `View` + `Embed` is simpler, well-trodden, and matches the existing `render_embed` house style. Reach for LayoutView only if the panel later wants in-message galleries/sections. Not needed for v1.3. |
| discord.py UI | A separate UI/component micro-library | None worth using exists; Discord message components are protocol-level and discord.py is the canonical Python implementation. Anything else would duplicate an existing dependency. |

## What NOT to Use / NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Adding ANY new package for v1.3 | The whole component/view/persistence/edit stack is internal to the already-pinned discord.py. A new dependency would be dead weight. | Reuse `discord.py>=2.7.1,<3` as-is. |
| Bumping or unpinning discord.py | `2.7.1` is already the latest PyPI release (verified 2026-06-23) and ships every required API; `<3` correctly caps a breaking 3.x. | Leave the pin exactly as it is. |
| Migrating prefix `on_message` → slash / app commands (`app_commands`, `CommandTree`, `tree.sync()`) | **Message components are NOT app commands.** A button/select click arrives as a `discord.Interaction` over the EXISTING gateway and is dispatched straight into the `View`'s item callbacks — zero command registration, zero `tree.sync()`, no `applications.commands` scope. Components attach fine to an ordinary `message.channel.send(view=...)`, which is exactly the panel-summon path. Slash commands would add sync complexity, propagation delay, and a scope change for no benefit. | Keep the prefix `!`-command surface unchanged; have it `send(view=panel)`. Drive everything else via component interactions. |
| Switching to `commands.Bot` "to get `add_view`/`setup_hook`" | Both are inherited by the bare `discord.Client` (since 2.0). The premise is false. | Override `setup_hook` on the existing `discord.Client` and call `self.add_view(...)` there. |
| Enabling new gateway intents for the panel | Interactions (button/select clicks) are delivered **regardless of intents** — they do not need `message_content`. That intent is only for reading the `!weather` text and stays as-is. | No intent change. Keep the current `Intents.none()` + `guilds`/`guild_messages`/`message_content`. |
| A DB/store to "remember" the panel across restarts | Component persistence is handled by `add_view()` re-registering the `custom_id` handlers on startup; Discord keeps the message. You only need the pinned message's ID to edit it (a config/known value or a one-time lookup), not a new persistence layer. | `timeout=None` view + stable `custom_id`s + `add_view()` in `setup_hook`. |
| Hand-managing an HTTP interaction webhook / ack server | discord.py handles the interaction ACK/response lifecycle over the gateway; responding (or `defer()`) within 3s is the whole contract. | `interaction.response.*` (and `defer()` for slow taps). |

## Stack Patterns by Variant

**Recommended default (matches the milestone exactly):**
- Classic `discord.ui.View(timeout=None)` holding one `Select` (location dropdown) + a grid of
  `Button`s (one per read-only command), each with a stable `custom_id`.
- Register it via `Client.add_view(...)` in a `setup_hook` override on the existing bare
  `discord.Client`; summon/pin it from a registry prefix command.
- Results render in place with `interaction.response.edit_message(embed=render_embed(reply))`.
- Per-callback operator gate via `interaction.user.id` (or `View.interaction_check`).

**If the panel later wants in-message galleries/sections:**
- Opt into `discord.ui.LayoutView` (Components V2, available in 2.7.x) — still no new dependency.
- Out of scope for v1.3.

## Version Compatibility

| Package@version | Compatible With | Notes |
|-----------------|-----------------|-------|
| discord.py@2.7.1 | Python `>=3.12` (project floor) | discord.py 2.7.x supports Python 3.9+; the 3.12 floor is well within range. |
| discord.py@2.7.1 | discord-webhook `>=1.4.1` (outbound) | Independent libraries; coexist today (webhook = outbound briefing, discord.py = inbound gateway + now components). v1.3 changes nothing here. |
| `View(timeout=None)` + `Client.add_view` / `Client.setup_hook` | discord.py 2.0+ | Persistent-view API + both methods on `Client` present since 2.0. **Effective version floor for this milestone: discord.py 2.0** — already far exceeded by the `2.7.1` pin. |
| `discord.ui.LayoutView` (Components V2) | discord.py 2.6+ | Only relevant if you opt into LayoutView (not recommended for v1.3). Classic `View`+`Embed` needs nothing beyond 2.0. |

## Sources

- `/rapptz/discord.py` (Context7) — persistent `View(timeout=None)`, `@discord.ui.button(custom_id=...)`, `@discord.ui.select(... options=...)`, `interaction.response.edit_message(view=...)`, `add_view` in `setup_hook`, `send(..., view=...)` signature. HIGH
- https://discordpy.readthedocs.io/en/stable/api.html — confirmed `Client.add_view` ("Registers a View for persistent listening", *New in 2.0*) and `Client.setup_hook` (*New in 2.0*) exist on the bare `discord.Client`, not just `commands.Bot`. HIGH
- https://raw.githubusercontent.com/Rapptz/discord.py/master/examples/views/persistent.py — canonical persistent-view example: `View(timeout=None)`, `custom_id='persistent_view:green'`, `self.add_view(PersistentView())` in `setup_hook`. (Example happens to subclass `commands.Bot`, but the methods it calls are inherited from `Client`.) HIGH
- https://pypi.org/pypi/discord.py/json (checked 2026-06-23) — latest release `2.7.1`; recent line 2.5.2 → 2.7.1. Confirms the existing pin is at HEAD. HIGH
- `weatherbot/interactive/bot.py` + `pyproject.toml` (repo) — existing bare `discord.Client`, `build_client`/`BotThread` wiring, intents set, registry-driven `on_message`, `discord.py>=2.7.1,<3` pin. HIGH

---
*Stack research for: WeatherBot v1.3 Discord interactive control panel (message components on the existing discord.py gateway bot)*
*Researched: 2026-06-23*
