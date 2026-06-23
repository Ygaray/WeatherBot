# Architecture Research

**Domain:** Discord interactive control panel (persistent View) layered over an existing discord.py gateway bot
**Researched:** 2026-06-23
**Confidence:** HIGH

> Scope note: This is a SUBSEQUENT-milestone (v1.3) integration study, not a greenfield design. The
> briefing spine (APScheduler, sent-log, `lookup.py`, `registry.COMMANDS`, `ConfigHolder`) is built and
> verified and MUST stay untouched. Everything below is about how a button/select panel SLOTS INTO the
> existing `interactive/bot.py` + `BotThread` without redesigning anything beneath it. The existing code
> was read directly (`bot.py`, `registry.py`, `lookup.py`, `cache.py`, `command.py`, `commands/`,
> `daemon.py`); the discord.py 2.x persistence API was verified against current official docs/examples.

---

## Standard Architecture

### System Overview

The panel is a NEW thin presentation surface that reuses the EXISTING dispatch core. It introduces
zero new fetch/render logic — it is a third caller of `registry.COMMANDS` + `CommandReply` +
`render_embed`, alongside the existing `on_message` (Discord) and the CLI.

```
┌──────────────────────────────────────────────────────────────────────┐
│                    BRIEFING SPINE  (UNTOUCHED — main thread)           │
│   APScheduler  →  fire_slot  →  sent-log (exactly-once)  →  webhook    │
│                         ▲ ISOLATION BOUNDARY ▲                         │
└──────────────────────────────────────────────────────────────────────┘
        (no call ever crosses upward from the panel into the spine)
┌──────────────────────────────────────────────────────────────────────┐
│                 BotThread  (own thread + own asyncio loop)             │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  discord.Client  (existing — base Client, NOT commands.Bot)     │  │
│  │   setup_hook()  → add_view(PanelView())   [NEW persistent reg]   │  │
│  │   on_message()  → guard ladder → registry dispatch  [EXISTING]   │  │
│  │   on_interaction (via View item callbacks)          [NEW]        │  │
│  └───────────┬───────────────────────────────────┬────────────────┘  │
│              │                                     │                    │
│   ┌──────────▼─────────┐              ┌────────────▼────────────────┐  │
│   │  panel.py  [NEW]   │              │  on_message handler [EXIST]  │  │
│   │  PanelView (View)  │              │  (text commands, unchanged)  │  │
│   │  • location Select │              └────────────┬─────────────────┘  │
│   │  • command Buttons │                           │                    │
│   │  • Forecast subrow │                           │                    │
│   │  • per-click guard │                           │                    │
│   │  • selected-loc    │                           │                    │
│   │    state           │                           │                    │
│   └──────────┬─────────┘                           │                    │
│              │   both surfaces converge on ONE dispatch path:           │
│              └───────────────────┬───────────────────┘                 │
│                                  ▼                                      │
│   ┌──────────────────────────────────────────────────────────────┐    │
│   │  SHARED DISPATCH CORE  (EXISTING — reused verbatim)            │    │
│   │  registry.COMMANDS (spec.handler)  →  CommandReply             │    │
│   │  ForecastCache.lookup  (off-loop via run_in_executor)         │    │
│   │  lookup_weather / lookup_forecast  (READ-ONLY, zero writes)    │    │
│   │  render_embed(reply) → discord.Embed                           │    │
│   └──────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | New / Existing |
|-----------|----------------|----------------|
| `interactive/panel.py` (`PanelView`) | The persistent `discord.ui.View`: location `Select`, command `Button` grid, Forecast sub-row; per-interaction guard; selected-location state; calls the shared dispatcher and `edit_message` | **NEW** |
| `interactive/panel_dispatch.py` (or a function in `panel.py`) | Maps a button's `custom_id` → a `CommandSpec`, threads the selected location + flags, calls `spec.handler`, returns a `CommandReply` | **NEW** (thin adapter — reuses the EXACT arg-adaptation already in `on_message`) |
| `bot.py` `build_client` / `setup_hook` | Register the persistent View once on startup via `client.add_view(...)`; expose a `!panel` summon command | **MODIFIED** (add `setup_hook`; add one `!panel` branch) |
| `BotThread` | Unchanged — already runs the client off-thread, swallows all failures, started after READY, torn down in `finally` | **Existing — unchanged** |
| `registry.COMMANDS` / `CommandReply` / `render_embed` | The single source of truth the panel drives; buttons are derived FROM the registry | **Existing — reused, not modified** |
| `ForecastCache` / `lookup_*` | Off-loop read-only fetch the panel reuses verbatim | **Existing — reused, not modified** |
| `daemon.py` BotThread wiring | Unchanged: `BotThread(...)` construction stays as-is; the panel needs no new constructor args (operator_id, holder, cache already flow in) | **Existing — unchanged** |

---

## Recommended Project Structure

```
weatherbot/interactive/
├── bot.py            # MODIFIED: add setup_hook (add_view), add !panel summon branch
├── panel.py          # NEW: PanelView(discord.ui.View) — Select + Button grid + Forecast subrow
├── panel_dispatch.py # NEW (optional): custom_id → spec → CommandReply adapter (or fold into panel.py)
├── registry.py       # UNCHANGED — the panel derives its buttons from COMMANDS
├── command.py        # UNCHANGED — reuse parse_forecast_flags / forecast_cache_suffix
├── cache.py          # UNCHANGED — ForecastCache reused for off-loop fetch
├── lookup.py         # UNCHANGED — read-only core
├── commands/         # UNCHANGED — handlers + CommandReply
└── state.py          # UNCHANGED — DaemonState (status command)
```

### Structure Rationale

- **`panel.py` as a NEW sibling module, NOT extending `bot.py`:** keep the View/component classes
  separate from the gateway client wiring. `bot.py` already does one job well (guard ladder + registry
  dispatch + embed render). The View has its own concerns (component layout, `custom_id` scheme,
  selected-state). A new module keeps `bot.py` from ballooning and lets the panel be unit-tested by
  driving callbacks with a fake `Interaction` (the same gateway-free testing discipline `build_on_message`
  already follows). The ONLY edit to `bot.py` is the `setup_hook` registration + a `!panel` summon branch.
- **`panel_dispatch.py` (or a shared helper):** the arg-adaptation ladder in `on_message`
  (lines 276–329 of `bot.py` — `is_forecast` flags, `next-cloudy` threshold, `uv` threshold, `status`
  DaemonState, `locations` config, `help`) is the ONE place that knows each handler's heterogeneous
  signature. The panel must call the SAME ladder, not a copy. Extract that ladder into one shared
  function `dispatch_spec(spec, *, arg, holder, cache, daemon_state, loop) -> CommandReply` that BOTH
  `on_message` and the panel call. This is the single most important anti-drift move in the milestone.

---

## Architectural Patterns

### Pattern 1: Persistent View registered in `setup_hook` (survives restart, no message-id storage)

**What:** A `discord.ui.View` with `timeout=None` and a stable `custom_id` on every component. Registered
once via `client.add_view(PanelView())` inside `Client.setup_hook()`. discord.py then routes any incoming
interaction whose component `custom_id` matches a registered view's item to that item's callback — for ANY
message that view was ever sent on, across process restarts. **No message id is stored or needed.**

**When to use:** Exactly this milestone — a pinned panel whose buttons must keep working after every
deploy/restart.

**Verified facts (discord.py 2.7.1, HIGH — official docs + `examples/views/persistent.py`):**
- `discord.Client` (the base class the existing bot already uses — NOT `commands.Bot`) has BOTH
  `setup_hook()` and `add_view()`. No need to switch the bot to the commands framework.
- Persistence requirements: `super().__init__(timeout=None)` AND every item carries an explicit
  `custom_id`. A View missing either cannot be registered as persistent.
- `setup_hook()` runs after login, before the gateway websocket connects — the correct, documented place
  to call `add_view`. (Do not call `wait_for` there — deadlock.)
- The panel MESSAGE id does not need persisting: a registered persistent view listens by `custom_id`, not
  by message id. The pinned message simply needs to still exist in the channel (it does — it's pinned).

**Example:**
```python
# panel.py (NEW)
import discord

class PanelView(discord.ui.View):
    def __init__(self, *, operator_id, holder, cache, daemon_state):
        super().__init__(timeout=None)          # REQUIRED for persistence
        self._operator_id = operator_id
        self._holder = holder
        self._cache = cache
        self._daemon_state = daemon_state
        # Select + buttons are declared as decorated methods or added in __init__,
        # each with a stable custom_id (see Pattern 5).

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # ONE guard for EVERY component (Pattern 4). Operator-only, polite reject.
        if interaction.user.id != self._operator_id:
            await interaction.response.send_message(
                "This panel is operator-only.", ephemeral=True
            )
            return False
        return True

# bot.py (MODIFIED) — register once, no message id needed
class _Client(discord.Client):
    async def setup_hook(self) -> None:
        self.add_view(PanelView(operator_id=..., holder=..., cache=..., daemon_state=...))
```

**Trade-offs:** A persistent View must be re-registered on EVERY startup (it lives in memory, not on
Discord). That is exactly what `setup_hook` guarantees. Cost: the View's dependencies (operator_id,
holder, cache, daemon_state) must be available at `build_client` time — they already are (all four are
constructor args to `BotThread`/`build_client` today).

### Pattern 2: Reuse the existing registry dispatch — DO NOT duplicate it

**What:** A button callback resolves its `custom_id` to a `CommandSpec` from `registry.BY_NAME`, then runs
the IDENTICAL arg-adaptation + off-loop fetch + `render_embed` path that `on_message` already runs. No
second dispatch table, no second fetch path, no second renderer.

**When to use:** Every command button. This is the milestone's core invariant ("the panel never drifts
from the real command set" — PROJECT.md).

**Trade-offs:** Requires extracting the `on_message` arg ladder into a shared `dispatch_spec(...)` first
(a small refactor of EXISTING code — Phase 1 of the build order). Worth it: it makes drift structurally
impossible and means a future 8th command shows up as a panel button for free if buttons are derived from
`COMMANDS`.

**Example:**
```python
# shared dispatcher (extracted from on_message lines 276–329, called by BOTH surfaces)
async def dispatch_spec(spec, *, arg, holder, cache, daemon_state, loop) -> CommandReply:
    config = holder.current()
    if spec.takes_location:
        is_forecast = spec.group == "Forecast"
        lookup_name, suffix, flags = arg, None, None
        if is_forecast:
            flags = parse_forecast_flags(arg)
            lookup_name = flags.location
            suffix = forecast_cache_suffix(spec.name, flags)
            result = await loop.run_in_executor(None, cache.lookup, lookup_name, config, suffix)
            return spec.handler(result, flags)
        result = await loop.run_in_executor(None, cache.lookup, lookup_name, config)
        if spec.name == "next-cloudy":
            return spec.handler(result, config.cloud_threshold)
        if spec.name == "uv":
            return spec.handler(result, config.uv.threshold)
        return spec.handler(result)
    if spec.name == "status":
        return await loop.run_in_executor(None, spec.handler, daemon_state)
    if spec.name == "locations":
        return spec.handler(config)
    return spec.handler()   # help

# button callback (panel.py)
async def _on_command_button(self, interaction, spec):
    reply = await dispatch_spec(spec, arg=self._selected_location,
                                holder=self._holder, cache=self._cache,
                                daemon_state=self._daemon_state,
                                loop=interaction.client.loop)
    await interaction.response.edit_message(embed=render_embed(reply), view=self)
```

### Pattern 3: In-place rendering via `interaction.response.edit_message`

**What:** A component callback responds with `interaction.response.edit_message(embed=..., view=self)`
instead of `channel.send`. This edits the SAME pinned panel message in place — no new-message spam (the
explicit v1.3 goal). Passing `view=self` re-attaches the panel so the buttons/select remain live after the
edit.

**When to use:** Every button/select callback that updates the panel.

**Trade-offs:** A Discord interaction must be acknowledged within ~3 seconds or it errors. An OpenWeather
fetch on a cache MISS can exceed that. Mitigation (see Pattern 7): on a likely-slow path call
`interaction.response.defer()` first, then `interaction.edit_original_response(...)` after the off-loop
fetch returns. On a cache HIT (the common case for a 10-min TTL) the direct `edit_message` is fast enough.
A simple, robust default: ALWAYS `defer()` then `edit_original_response()` for command buttons; reserve the
synchronous `edit_message` for the pure-UI Select/sub-row toggles that do no fetch.

**Example:**
```python
async def _on_command_button(self, interaction, spec):
    await interaction.response.defer()                      # ack within 3 s
    reply = await dispatch_spec(spec, arg=self._selected_location, ...)
    await interaction.edit_original_response(embed=render_embed(reply), view=self)
```

### Pattern 4: One `interaction_check` guard for the whole View (preserve the operator-only ladder)

**What:** Override `View.interaction_check` once. It runs BEFORE every item callback in that View;
returning `False` blocks the callback. This is the panel-world equivalent of the `on_message` guard ladder
step (2) (`author.id != operator_id`). The pinned panel is publicly visible, so non-operator taps must get
a polite ephemeral reject (PROJECT.md: "non-operator taps on the public pinned panel get a polite
reject"), not silence.

**When to use:** Always — it is the single chokepoint that keeps the panel single-operator.

**Trade-offs:** Unlike `on_message` (which silently drops non-operators to avoid a feedback loop), the panel
should respond with an ephemeral message — there is no feedback-loop risk from an ephemeral reply, and a
visible panel needs to explain the rejection. The `author.bot` guard is unnecessary here (a bot cannot
click a button on behalf of a user; interactions carry a real `interaction.user`).

### Pattern 5: Selected-location state — in-memory on the View instance (single-operator)

**What:** Keep the currently-selected location as an attribute on the `PanelView` instance
(`self._selected_location: str | None`). The location `Select`'s callback sets it; command buttons read it
and pass it as the `arg` to `dispatch_spec`. Because this is a SINGLE-operator tool with ONE pinned panel,
a single in-memory slot is correct and simplest.

**Restart behavior:** After a restart, `setup_hook` registers a FRESH `PanelView` with
`_selected_location = None` (or defaulted to the first configured location). The buttons still work (they
are matched by `custom_id`), but the prior selection is forgotten — the operator re-picks from the Select.
This is acceptable for a personal bot: the default location resolution already handles `arg=None` (bare
default), so even an un-selected panel produces a valid briefing for the default location.

**Alternative considered — encode selection in `custom_id`:** You CAN encode the selected location into
each button's `custom_id` and rebuild the View per interaction so selection survives restart. **Rejected
for v1.3:** it forces a dynamic per-interaction View rebuild, fights the static persistent-View
registration model, bloats `custom_id`s (100-char limit), and breaks if a location is renamed in config.
The in-memory slot + default-on-restart is far simpler and matches the single-operator reality. (Revisit
ONLY if "remember selection across restart" becomes a hard requirement.)

**Trade-offs:** In-memory state means the Select's *visual* "chosen" highlight also resets on restart
(Discord does not persist a Select's chosen option for a `timeout=None` view). Acceptable; the operator
sees the dropdown and re-picks. Populate the Select options from `holder.current()` locations at
build time so it always reflects live config (re-derive on the config-reload hook if you want it to track
renames without a restart — optional polish).

### Pattern 6: Forecast two-tier sub-options — a second row (or a follow-up View), driven by the same flags grammar

**What:** The Forecast button expands to Weekday/Weekend × Detailed/Compact (4 combinations, mirroring the
text command's `+compact`/`+detailed` flags). Model this as additional components on the SAME persistent
View:
- A "Forecast" button that, when clicked, reveals/uses a second action row of buttons:
  `Weekday · Detailed`, `Weekday · Compact`, `Weekend · Detailed`, `Weekend · Compact`
  (4 buttons fit in one 5-slot action row). Each carries a stable `custom_id` encoding its
  (command, variant) pair, e.g. `wbpanel:fc:weekday:detailed`.
- Each sub-button maps to the `weekday-forecast` / `weekend-forecast` spec and constructs a
  `ForecastFlags(variant=..., location=self._selected_location)`, then calls `spec.handler(result, flags)`
  through the SAME `dispatch_spec` path — reusing `parse_forecast_flags` semantics WITHOUT re-parsing text
  (build the `ForecastFlags` directly, or synthesize an arg string and let `dispatch_spec` parse it; the
  former is cleaner).

**Layout reality (HIGH — Discord hard limit):** a message View allows at most **5 action rows of 5
components each (25 total)**; a `Select` occupies a whole row by itself. Budget:
- Row 0: location `Select` (1 full row).
- Rows 1–3: the 7 read-only command buttons (weather/uv/next-cloudy/sun/wind/alerts/status) + the
  Forecast button = 8 buttons across two rows.
- Remaining row(s): the 4 Forecast sub-buttons.
This fits within 5 rows. If it gets tight, the cleanest split is a SECOND persistent View (a "forecast
sub-panel") sent as a follow-up, but a single View with a static forecast sub-row is simpler and is the
recommended default.

**Trade-offs:** A static sub-row (always visible) is simpler than show/hide (which requires editing the
View's component list per interaction and re-sending `view=`). For v1.3, a static layout with the four
forecast buttons always present is the least-moving-parts option; dynamic show/hide is optional polish.

### Pattern 7: Off-loop fetch + 3-second-ack discipline (reuse `run_in_executor` + `ForecastCache`)

**What:** The blocking fetch (`cache.lookup` → `lookup_weather` → httpx) must run OFF the event loop via
`loop.run_in_executor`, EXACTLY as `on_message` does today (lines 302–308). Combined with the
defer-then-edit pattern (Pattern 3), this keeps the gateway heartbeat alive and satisfies Discord's 3s ack
window even on a cache miss.

**When to use:** Every command button that fetches. Pure-UI components (the Select setting state, a sub-row
toggle) do no fetch and can `edit_message` synchronously.

**Trade-offs:** None beyond what the bot already accepts — this is the existing CMD-02/D-10 pattern reused.

---

## Data Flow

### Panel interaction flow (button click)

```
operator taps a command button on the pinned panel
    ↓  (Discord gateway → BotThread's own loop)
View.interaction_check(interaction)         # operator-only guard (Pattern 4)
    ↓ True
button callback (panel.py)
    ↓
interaction.response.defer()                # ack within 3 s (Pattern 3/7)
    ↓
dispatch_spec(spec, arg=self._selected_location, ...)   # SHARED with on_message
    ↓
cache.lookup(...)  via loop.run_in_executor # OFF-loop, read-only (Pattern 7)
    ↓
spec.handler(result[, flags|threshold]) → CommandReply  # EXISTING handler
    ↓
render_embed(reply) → discord.Embed         # EXISTING renderer
    ↓
interaction.edit_original_response(embed=..., view=self) # in-place (Pattern 3)
```

### Location-select flow (no fetch)

```
operator picks a location in the Select
    ↓
interaction_check → True
    ↓
select callback: self._selected_location = chosen value   # in-memory (Pattern 5)
    ↓
interaction.response.edit_message(view=self)  # cheap UI refresh, no fetch
```

### State management

```
PanelView instance (one, registered in setup_hook)
   _selected_location : str | None   ← set by Select callback, read by button callbacks
   (re-created fresh on every restart; default = None / first location)
```

---

## Failure-Isolation Invariant (the non-negotiable)

The briefing spine MUST never be gated, delayed, or stopped by a panel/interaction error. The existing
architecture already enforces this at THREE layers; the panel inherits all three and adds one of its own:

| Layer | Mechanism (existing) | Applies to panel? |
|-------|----------------------|-------------------|
| Thread isolation | The whole bot runs in `BotThread` on its OWN loop; `_run` swallows every exception, sets `_failed`, never re-raises (`bot.py` 458–474). The spine runs on the MAIN thread. | YES — panel callbacks run on the bot loop, structurally unable to reach the scheduler thread. |
| Startup isolation | `BotThread` is started AFTER `scheduler.start()` + `emit_online()` and wrapped in a log-and-proceed try/except in `daemon.py` (1565–1605). A bot that can't start never blocks READY. | YES — `setup_hook`/`add_view` runs inside `client.start`, i.e. inside the already-isolated `BotThread`. A View that fails to register dies in the bot thread. |
| Teardown isolation | `bot.stop()` in the daemon `finally` is itself wrapped so a teardown hiccup never masks shutdown (1674–1678). | YES — unchanged. |
| **Interaction isolation (NEW)** | Wrap each component callback body in a non-propagating try/except mirroring the `on_message` envelope (`bot.py` 332–337): log + ephemeral "something went wrong", NEVER re-raise. discord.py also routes uncaught item errors to `View.on_error`, but rely on the explicit envelope, not just that. | NEW — add per-callback. |

**Concrete rules for v1.3:**
1. Every button/select callback wraps its body in `try/except Exception: log + best-effort ephemeral
   error reply; never re-raise` — copy the `on_message` envelope shape verbatim.
2. Also override `View.on_error(self, interaction, error, item)` as a backstop that logs and never
   re-raises (defense in depth).
3. `add_view` in `setup_hook` is inside the BotThread-isolated `client.start`; if it raises, the bot
   thread dies alone (`_run` swallows) and briefings continue — already guaranteed, do not add spine-side
   handling.
4. The panel calls ONLY read-only paths (`dispatch_spec` → `cache.lookup` → `lookup_weather`, which is
   provably zero store/sent-log/alert/heartbeat writes). It must never touch the scheduler, sent-log,
   `ConfigHolder.replace`, or any write path. (It MAY read `holder.current()` and `daemon_state` — both
   read-only.)

---

## Integration Points

### Where the panel plugs into existing code

| Boundary | Integration | Notes |
|----------|-------------|-------|
| `bot.py build_client` ↔ `panel.py PanelView` | Switch `discord.Client(intents=...)` to a tiny `Client` subclass (or set `client.setup_hook`) that calls `self.add_view(PanelView(...))`. Pass the SAME `operator_id`, `holder`, `cache`, `daemon_state` already available in `build_client`. | The four deps the View needs are ALREADY in `build_client`'s signature — no new wiring through `BotThread`/`daemon.py`. |
| `on_message` ↔ shared `dispatch_spec` | Extract `on_message` lines 276–329 into `dispatch_spec(...)`; `on_message` and panel callbacks both call it. | Refactor of EXISTING code; behavior-preserving; lock it with the existing anti-drift test. |
| `panel.py` ↔ `registry.COMMANDS` | Derive the command buttons by iterating `COMMANDS` (filter `group in {"Weather","Forecast","Info"}` per the panel's 7-command + Forecast layout). Map each button's `custom_id` → `BY_NAME[name]`. | Keeps the panel auto-in-sync with the registry (the milestone's "single source of truth" goal). |
| `panel.py` ↔ `command.py` | Build `ForecastFlags(variant=..., location=...)` directly for sub-buttons; reuse `forecast_cache_suffix` for the cache key. | No text re-parse needed; reuse the grammar types. |
| `daemon.py` BotThread construction | **No change.** `BotThread(token, holder=, operator_id=, cache=, daemon_state=)` already passes everything the View needs down into `build_client`. | Confirmed by reading `daemon.py` 1594–1601 — the panel adds zero new constructor args. |
| `!panel` summon command | Add a branch in `on_message` (or a registry entry) that posts a fresh panel message and pins it. | One new command; the panel is "summonable but meant to live pinned" (PROJECT.md). |

### External services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Discord gateway (interactions) | Already connected via the existing `BotThread` gateway. Button/select clicks arrive as interaction events over the SAME connection — no new inbound infrastructure. | The `message_content` privileged intent is already enabled; component interactions do NOT require an extra intent. The bot must have permission to send/edit/pin in the panel channel. |
| OpenWeather (One Call 3.0) | Reused verbatim through `ForecastCache` → `lookup_weather`. No new endpoint, no extra calls beyond the existing TTL-cached fetch. | The 10-min TTL cache means most panel clicks are cache hits → fast `edit_message`. |

---

## Anti-Patterns

### Anti-Pattern 1: Duplicating dispatch in the button callbacks

**What people do:** Write a fresh `if button == "weather": fetch...; elif button == "uv": ...` ladder in
`panel.py`.
**Why it's wrong:** It re-implements the registry dispatch and the per-handler arg adaptation, guaranteeing
drift the moment a command's signature or the command set changes. Directly violates the milestone's
single-source-of-truth goal.
**Do this instead:** Extract `dispatch_spec(...)` once and call it from both `on_message` and the panel.
Derive buttons from `registry.COMMANDS`.

### Anti-Pattern 2: Storing the panel message id to "rebind" buttons after restart

**What people do:** Persist the pinned message id to disk/SQLite and try to re-attach the View to it on
startup.
**Why it's wrong:** Unnecessary and fragile. discord.py persistent views (`timeout=None` + `custom_id`s +
`add_view` in `setup_hook`) listen by `custom_id` across restarts WITHOUT any message id. Storing the id
adds a write path and a failure mode for zero benefit.
**Do this instead:** Register the persistent View in `setup_hook`; let `custom_id` matching do the work.

### Anti-Pattern 3: Switching the bot from `discord.Client` to `commands.Bot` for the panel

**What people do:** Assume persistent views require the commands framework.
**Why it's wrong:** The base `discord.Client` already exposes `setup_hook` and `add_view` (verified, 2.7.1).
Switching frameworks would churn the verified guard-ladder `on_message` for no gain.
**Do this instead:** Keep `discord.Client`; add `setup_hook`.

### Anti-Pattern 4: Doing the fetch before acking the interaction

**What people do:** Call `cache.lookup` (which can hit the network) and only then `edit_message`.
**Why it's wrong:** A cache-miss fetch can exceed Discord's 3-second ack window → the interaction fails and
the operator sees "interaction failed".
**Do this instead:** `interaction.response.defer()` first, run the fetch off-loop via `run_in_executor`,
then `edit_original_response`.

### Anti-Pattern 5: Letting a callback exception propagate

**What people do:** Rely on discord.py's default error handling for a raising callback.
**Why it's wrong:** Even though the BotThread isolates the spine, an unhandled callback error gives the
operator a silent/ugly failure and risks logging secrets if the exception text carries config.
**Do this instead:** Wrap each callback in the same non-propagating try/except envelope `on_message` uses
(log + ephemeral generic reply, never re-raise), plus a `View.on_error` backstop.

---

## Suggested Build Order

Ordered to respect dependencies and keep the spine-isolation invariant verifiable at each step.

1. **Refactor: extract `dispatch_spec(...)` from `on_message` (behavior-preserving).**
   Move the arg-adaptation ladder (`bot.py` 276–329) into one shared async function; have `on_message`
   call it. Lock with the existing anti-drift / registry tests. *No new behavior — pure groundwork that
   makes no-dispatch-duplication structurally enforced before the panel exists.* (Depends on: nothing.)

2. **New `panel.py`: minimal persistent View — location Select + the 7 command buttons.**
   `timeout=None`, stable `custom_id`s, `interaction_check` operator guard, in-memory `_selected_location`,
   per-callback non-propagating envelope + `on_error` backstop. Buttons call `dispatch_spec` and
   `defer → edit_original_response`. (Depends on: 1.)

3. **Register persistence + summon: `setup_hook` `add_view` in `bot.py`, plus a `!panel` command.**
   Subclass `discord.Client` (or assign `setup_hook`) to register `PanelView`; add the `!panel` branch that
   posts + pins a fresh panel message. Verify buttons survive a `systemctl restart`. (Depends on: 2.)

4. **Forecast two-tier sub-options.**
   Add the Forecast button + the 4 Weekday/Weekend × Detailed/Compact sub-buttons (static sub-row),
   building `ForecastFlags` directly and routing through `dispatch_spec`. (Depends on: 2, ideally 3.)

5. **Polish + isolation hardening.**
   Optional: re-derive Select options on the config-reload hook so renames track without restart; confirm
   the embed-limit clipping in `render_embed` covers the panel path; explicit test that a raising callback
   never reaches the scheduler thread (mirror the BotThread `_run` isolation test). (Depends on: 2–4.)

**Why this order:** Step 1 makes drift impossible BEFORE any panel code can copy a dispatch ladder. Steps
2→3 give a working, restart-surviving panel for the 7 simple commands (the bulk of the value) before the
more layout-fiddly Forecast sub-options in step 4. Step 5 is hardening that depends on everything else
existing. Every step keeps the briefing spine untouched and re-verifies isolation.

---

## Sources

- Existing code read directly (HIGH): `weatherbot/interactive/bot.py` (BotThread isolation, on_message
  guard ladder + dispatch, render_embed), `registry.py` (COMMANDS / CommandSpec / BY_NAME), `lookup.py`
  (read-only core), `cache.py` (off-loop TTL fetch), `command.py` (parse_forecast_flags /
  forecast_cache_suffix), `commands/__init__.py` (CommandReply), `commands/weather_views.py`,
  `scheduler/daemon.py` 1556–1678 (BotThread start-after-READY + finally teardown).
- discord.py persistent View example `Rapptz/discord.py examples/views/persistent.py` — `timeout=None`,
  per-item `custom_id`, `add_view` in `setup_hook`, no message-id storage required. HIGH
- discord.py API reference (stable) — `Client.add_view` ("Registers a View for persistent listening",
  requires no-timeout + explicit custom_ids) and `Client.setup_hook` (runs after login, before websocket;
  correct place for `add_view`); `InteractionResponse.edit_message` (edits the message a component is
  attached to). HIGH
- Installed/pinned versions (HIGH): `pyproject.toml` `discord.py>=2.7.1,<3`; `uv.lock` discord-py 2.7.1
  (verified `discord.__version__ == "2.7.1"`).
- Discord component layout limits (5 action rows × 5 components; a Select fills a row): discord.py docs +
  Discord API — MEDIUM (well-established, not re-quoted line-by-line here).

---
*Architecture research for: Discord interactive control panel integrated into an existing discord.py gateway bot*
*Researched: 2026-06-23*
