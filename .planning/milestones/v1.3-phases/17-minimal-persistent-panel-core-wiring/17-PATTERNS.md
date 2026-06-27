# Phase 17: Minimal Persistent Panel (Core Wiring) - Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 8 (3 new, 5 modified)
**Analogs found:** 8 / 8

Phase 17 has two distinct shapes of work, and the pattern map reflects both:

1. **Greenfield discord.py wiring (`panel.py`, `test_panel.py`)** — no existing
   `discord.ui.View` exists in the repo, so the *module style* is copied from the
   `interactive/` siblings (`bot.py` / `dispatch.py`) and the *correctness
   mechanics* come verbatim from 17-RESEARCH Patterns 1–4 (which were verified
   against the installed discord.py 2.7.1 source — treat those excerpts as the
   canonical copy-from for the discord.py-specific code, since there is no in-repo
   analog for a View). The reusable seams (`dispatch_spec`, `render_embed`,
   `holder.current()`, `resolve_location(...,None)` default) are all in-repo and
   excerpted below.

2. **The W2 behavior-preserving refactor (`registry.py`, `weather_views.py`,
   `command.py`, `cli.py`, `test_registry.py`)** — this is a *textbook
   derive-from-one-list edit*: add one `CommandSpec` + one handler, then fix the
   four derived surfaces it ripples into (help, CLI subparser loop, the
   anti-drift registry test, byte-identical `!weather` reply). Every analog here
   is an existing sibling in the very same file. The excerpts are the exact
   sibling rows to copy and the exact lines to guard.

The panel adds ZERO new fetch/bind/render code — it is the **third caller** of the
Phase-16 `dispatch_spec` seam (`bot.py` is the first, `cli.py` the second). Do not
build a parallel dispatch path; that is the one thing PANEL-10 exists to prevent.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/interactive/panel.py` | controller (component callbacks) | event-driven (interaction callbacks) | `weatherbot/interactive/bot.py` (`build_on_message` guard+envelope+dispatch) + `dispatch.py` (module style) | role + style match (no existing View) |
| `weatherbot/interactive/commands/weather_views.py` | service (view handler) | transform (LookupResult → CommandReply) | the sibling `wind` / `sun` handlers in the SAME file | exact (sibling) |
| `weatherbot/interactive/registry.py` | config (command registry) | declarative table | the existing `uv` / `alerts` `CommandSpec` rows + `_wire_handlers` entries | exact (sibling) |
| `weatherbot/interactive/command.py` | utility (parser) | transform (text → ParsedCommand) | `parse_command` itself (already registry-driven; weather becomes a normal spec) | exact (self — likely zero-change) |
| `weatherbot/cli.py` | controller (CLI subparser builder) | request-response | the existing registry-loop subparser builder (`cli.py:815`) + the hand-written subparser names | exact (self) |
| `tests/test_panel.py` | test | event-driven (fake-interaction) | `tests/test_bot.py` (fake-message driver) + `tests/conftest.py` (`_make_fake_discord_message`) | role + style match |
| `tests/test_registry.py` | test | declarative assertion | the Weather-group assertion at `test_registry.py:74` | exact (self) |

---

## Pattern Assignments

### `weatherbot/interactive/panel.py` (NEW — controller / component callbacks)

No `discord.ui.View` exists in the repo. Copy **module style** from `dispatch.py`
/ `bot.py`, copy the **reusable seams** verbatim from the existing modules, and copy
the **discord.py mechanics** from 17-RESEARCH Patterns 1–4 (verified against the
installed 2.7.1 source — the canonical copy-from for the View/Button/Select code).

**Imports pattern (acyclic, import-discipline)** — mirror `dispatch.py:36-57`.
Every `interactive/` module opens with `from __future__ import annotations`, imports
only light siblings at module top, and pushes heavy types under `TYPE_CHECKING`:

```python
# dispatch.py:36-57 — the exact module-top shape panel.py should mirror
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord            # panel.py needs discord at module top (bot.py:42 does too)
import structlog

from weatherbot.interactive import registry                  # BY_NAME (D-06)
from weatherbot.interactive.bot import render_embed           # reuse the ONE renderer
from weatherbot.interactive.dispatch import dispatch_spec     # the shared seam (3rd caller)
from weatherbot.interactive.lookup import UnknownLocationError

if TYPE_CHECKING:
    from weatherbot.config.holder import ConfigHolder
    from weatherbot.interactive.cache import ForecastCache
    from weatherbot.interactive.state import DaemonState

_log = structlog.get_logger(__name__)
```

> `panel.py` may import `bot`/`dispatch`/`registry` at module top — the edge is
> acyclic (nothing in `interactive/` imports `panel`). This mirrors how `bot.py:46-48`
> imports `command` / `dispatch` / `lookup` at module top. Do NOT replicate any
> in-handler lazy import.

**Constructor deps + default selection (D-03)** — same dependency set as
`build_on_message` (`bot.py:217-223`): `holder`, `operator_id`, `cache`,
`daemon_state`. The D-03 default mirrors `resolve_location(config, None) →
locations[0]` (`loader.py:52-53`):

```python
# 17-RESEARCH Pattern 1 (verified vs discord.py 2.7.1) + loader.py:52-53 default
class PanelView(discord.ui.View):
    def __init__(self, *, holder, operator_id, cache, daemon_state=None):
        super().__init__(timeout=None)               # REQUIRED for is_persistent()==True
        self._holder = holder
        self._operator_id = operator_id
        self._cache = cache
        self._daemon_state = daemon_state
        # D-03 default = locations[0].name (mirrors resolve_location(config, None))
        self._selected_location = holder.current().locations[0].name
```

**Operator gate (D-11/D-12/D-13)** — this is the panel's analog of the `bot.py`
operator guard rung (`bot.py:253-254`), but on the View instead of `on_message`.
Copy from 17-RESEARCH Pattern 3 (verified: a clean `return False` does NOT fire
`on_error`, so the reject log is the SOLE audit record — emit it explicitly):

```python
# 17-RESEARCH Pattern 3 (VERIFIED vs ui/view.py:587-600)
async def interaction_check(self, interaction: discord.Interaction) -> bool:
    if interaction.user.bot:                       # defense-in-depth (mirrors bot.py:250)
        return False
    if interaction.user.id != self._operator_id:   # the operator gate (mirrors bot.py:253)
        _log.info(                                 # D-13: sole audit record of a reject
            "panel reject (non-operator)",
            user_id=interaction.user.id,
            custom_id=(interaction.data or {}).get("custom_id"),
        )
        await interaction.response.send_message(
            "This panel is in use by someone else.",   # D-12 byte-for-byte, identity-free
            ephemeral=True,
        )
        return False
    return True
```

**Single-ack defer-then-edit + the non-propagating envelope (D-14/D-15 + CMD-16)**
— the per-callback `try/except` is the panel's analog of the `on_message`
envelope (`bot.py:271-303`); the `UnknownLocationError` call-site catch mirrors
`bot.py:292-295`. The single `interaction.response.*` call is spent on
`edit_message`; the result lands via `edit_original_response`:

```python
# 17-RESEARCH Pattern 2 (VERIFIED vs interactions.py:1120,512) — mirrors bot.py's envelope
async def on_command(self, interaction: discord.Interaction, name: str) -> None:
    try:
        spec = registry.BY_NAME[name]                      # allow-list (KeyError→caught)
        arg = self._selected_location if spec.takes_location else None  # D-04 argless→None
        await interaction.response.edit_message(           # ① THE single ack (<3s)
            content="⏳ Fetching…", view=self._disabled_copy()
        )
        loop = asyncio.get_running_loop()
        config = self._holder.current()                    # per-tap lock-free snapshot
        try:
            reply = await dispatch_spec(                   # the SHARED seam (3rd caller)
                spec, arg, cache=self._cache, config=config,
                loop=loop, daemon_state=self._daemon_state,
            )
        except UnknownLocationError as exc:                # mirrors bot.py:292-295
            await interaction.edit_original_response(content=str(exc), embed=None, view=self)
            return
        embed = render_embed(reply)                        # the ONE renderer (bot.py:124)
        await interaction.edit_original_response(          # ② result via followup, NOT response.*
            content=None, embed=embed, view=self
        )
    except Exception:  # noqa: BLE001 — non-propagating (mirrors bot.py:298, CMD-16)
        _log.exception("panel command callback failed", custom_id=f"wb:cmd:{name}")
        await self._safe_error_edit(interaction)
```

**`View.on_error` backstop + `_safe_error_edit` is_done() guard** — copy from
17-RESEARCH Patterns 4 + Pitfall 4. The best-effort try/except mirrors
`bot.py:300-303`.

**Build-time layout assert (D-10 / Pitfall 5)** — discord.py does NOT enforce
`custom_id ≤ 100` / `label ≤ 80` at construction (verified). Add the minimal
`__init__` guard: rows ≤ 5, ≤ 5 per row, each `custom_id` ≤ 100, each `label` ≤ 80,
`len(locations) ≤ 25`. Curated ordered name tuple per D-06 with
`assert name in registry.BY_NAME` so a registry rename fails loud at construction.

---

### `weatherbot/interactive/commands/weather_views.py` (MODIFIED — view handler)

**Analog:** the sibling handlers in the SAME file (`wind` `weather_views.py:165-180`,
`sun` `:137-162`). The new `weather` handler is the simplest of all — it reads only
`result.forecast` and builds a `CommandReply` whose three lines reproduce
`build_inbound_embed`'s fields **byte-for-byte** (D-07/D-08).

**Sibling handler shape to copy** (`weather_views.py:165-180`, `wind`):

```python
# weather_views.py:165-180 — the sibling shape: read result.forecast, return CommandReply
def wind(result: LookupResult) -> CommandReply:
    forecast = result.forecast
    ...
    return CommandReply(title=f"Wind — {location_name}", lines=tuple(lines))
```

**The byte-identical reference** — `build_inbound_embed` (`bot.py:194-214`) sets
title `f"Weather — {forecast.location}"` and three inline fields: `("Now",
forecast.temp_display)`, `("High / Low", f"{high} / {low}")`, `("Rain",
f"{rain_chance}%")`. The new handler MUST produce the SAME fields so `render_embed`
yields the identical embed:

```python
# NEW handler — fields mirror build_inbound_embed (bot.py:206-212) exactly (D-07/D-08)
def weather(result: LookupResult) -> CommandReply:
    f = result.forecast
    return CommandReply(
        title=f"Weather — {f.location}",
        lines=(
            ("Now", f.temp_display),
            ("High / Low", f"{f.high_display} / {f.low_display}"),
            ("Rain", f"{f.rain_chance}%"),
        ),
    )
```

> The handler takes ONE arg (`result`) and is `takes_location=True`, so it lands in
> the `dispatch_reply` catch-all branch #4 (`dispatch.py:95-96` — `handler(result)`):
> **no ladder edit is needed.** This is the existing-shape case the dispatcher's
> catch-all was designed for (16-PATTERNS "Shared Patterns").
>
> (Open Question 1 in RESEARCH: this handler may instead live in its own module —
> Claude's Discretion. The sibling-handler shape is identical either way.)

---

### `weatherbot/interactive/registry.py` (MODIFIED — command registry)

**Analog:** the existing `CommandSpec` rows in `_SPECS` (`registry.py:50-81`) and
the `_wire_handlers` map (`registry.py:103-114`). This is a two-line derive-from-
one-list edit.

**Spec row to add** — copy the `alerts`/`sun` row shape (`registry.py:51-53`),
Weather group, `takes_location=True`. Place it FIRST in the Weather group so the
curated panel tuple order (`weather, uv, next-cloudy, sun, wind`) reads naturally:

```python
# registry.py:51 — the sibling row shape to copy for the new spec
CommandSpec("weather", "Weather", "Current conditions for a location.", True),
```

**Handler wiring to add** — one entry in the `_wire_handlers` map
(`registry.py:103-114`), pointing at the new handler (the imports there are the
lazy block at `registry.py:96-101`):

```python
# registry.py:104-113 — add one entry to the handlers dict (sibling shape)
"weather": weather_views.weather,
```

> **Parser ordering note (Pitfall 4 / D-08):** `COMMANDS_BY_KEYWORD_LEN_DESC`
> (`registry.py:126-128`) already sorts longest-first, so `weather` (7) is matched
> after `next-cloudy` (11) and the forecast names (16) but before `sun`/`wind`/`uv`.
> The word-boundary guard in `parse_command` (`command.py:107-110`) already prevents
> `weather` from shadowing those — no parser code change needed. Verify
> `test_command.py` stays green.

---

### `weatherbot/interactive/command.py` (MODIFIED — likely ZERO change)

**Analog:** `parse_command` itself (`command.py:91-114`). It is ALREADY fully
registry-driven — it iterates `registry.COMMANDS_BY_KEYWORD_LEN_DESC` and matches
any registered name. Once `weather` is a real spec (above), `parse_command("weather
home")` automatically returns `ParsedCommand(spec=<weather>, arg="home")` with NO
edit to this file.

```python
# command.py:104-113 — already iterates the registry; weather "just works" once registered
for spec in registry.COMMANDS_BY_KEYWORD_LEN_DESC:
    if not folded.startswith(spec.name):
        continue
    rest = stripped[len(spec.name):]
    if rest and not rest[0].isspace():   # word-boundary guard (so "weatherman" ≠ "weather")
        continue
    arg = rest.strip() or None
    return ParsedCommand(spec=spec, arg=arg)
```

> **D-08 consequence (the load-bearing part):** TODAY `!weather` returns
> `spec=None` (no `weather` spec) and is dropped as a no-op. After W2 it routes
> through `dispatch_spec` → the new `weather` handler → `render_embed`. The
> standalone legacy `build_inbound_embed` path (`bot.py:194`) is NOT reached by
> `!weather` text — it was already unreferenced from `on_message`. The planner must
> still PROVE the new reply is byte-identical to `build_inbound_embed`'s fields
> (the D-07 handler above guarantees the field shape). The note in 17-RESEARCH
> ("`parse_weather_command` legacy parser at `command.py:54-74`") is a SEPARATE
> historical function — leave it untouched; `on_message` uses `parse_command`, not
> `parse_weather_command`.

---

### `weatherbot/cli.py` (MODIFIED — registry-loop subparser skip-guard, load-bearing)

**Analog:** the registry-loop subparser builder itself (`cli.py:813-839`) and the
hand-written subparser names (`weather`/`run`/`check`/`check-config`/`reload`/
`send-now`/`geocode` at `cli.py:731-803`).

**The collision (Pitfall 1):** `cli.py:815` loops `registry.COMMANDS` and calls
`subparsers.add_parser(_spec.name, …)`. `cli.py:731` ALREADY registers a standalone
`weather` subparser. Once `weather` is a registry spec, the loop calls
`add_parser("weather", …)` a SECOND time → `argparse.ArgumentError: conflicting
subparser: weather` at EVERY CLI invocation. `[VERIFIED: cli.py:731 + 815, no skip-guard]`

**Current loop to guard** (`cli.py:813-817`):

```python
# cli.py:813-817 — the registry loop with NO skip-guard (the collision site)
from weatherbot.interactive import registry as _registry

for _spec in _registry.COMMANDS:
    _parents = [] if _spec.name == "help" else [config_parent]
    _sub = subparsers.add_parser(_spec.name, parents=_parents, help=_spec.summary)
```

**The fix** — track the hand-written subparser names and skip any registry spec
whose name collides, so the standalone `weather` subparser (with its `-v/--verbose`
flag + quiet-by-default path at `cli.py:742-747,848`) WINS and stays byte-identical:

```python
# Add a skip-guard: the hand-written subparsers above take precedence.
_HANDWRITTEN = {
    "weather", "run", "check", "check-config", "reload", "send-now", "geocode",
}
for _spec in _registry.COMMANDS:
    if _spec.name in _HANDWRITTEN:          # standalone subparser already registered
        continue
    _parents = [] if _spec.name == "help" else [config_parent]
    _sub = subparsers.add_parser(_spec.name, parents=_parents, help=_spec.summary)
    ...
```

> **Dispatch is already safe (no change needed at the dispatch tail):** `main`
> routes `args.command == "weather"` to `_cmd_weather` at `cli.py:860` — BEFORE the
> registry-command resolution at `cli.py:922` (`_registry.BY_NAME.get(args.command)`
> → `_run_registry_command`). So even with `weather` in `BY_NAME`, the standalone
> `weather` path still wins at dispatch. The collision is PURELY at subparser-build
> time; the skip-guard is the only edit required. `[VERIFIED: cli.py:860 vs 922]`
>
> (Assumption A1 in RESEARCH: keep the standalone `p_weather` and skip-guard the
> loop, rather than deleting `p_weather` — preserves `-v` + the quiet path. The
> alternative would have to re-add those to the registry-built subparser.)

---

### `tests/test_panel.py` (NEW — gateway-free callback tests)

**Analog:** `tests/test_bot.py` (the fake-message driver pattern) + the
`_make_fake_discord_message` factory in `tests/conftest.py:114-153`. The panel needs
a SIBLING `_make_fake_interaction` factory.

**Deferred-import + `_run` pattern** — copy `test_bot.py:32-46`. Reference the
not-yet-built `panel` module via a per-test lazy import so node IDs collect while the
module is RED, and drive callbacks on a fresh loop:

```python
# test_bot.py:32-46 — the deferred-import + asyncio driver to copy for test_panel.py
def _panel():
    from weatherbot.interactive import panel
    return panel

def _run(coro):
    return asyncio.run(coro)

_OPERATOR_ID = 12345
```

**Fake-message factory to mirror** — `conftest.py:114-147` builds a `MagicMock`
shaped like a `Message` with an `AsyncMock` `channel.send` and an
async-context-manager `channel.typing()`. The new `_make_fake_interaction` mirrors
this shape for an `Interaction` (per 17-RESEARCH Wave-0 Gaps):

```python
# Mirror conftest.py:114-147 — a fake Interaction (NO discord import, NO network):
#   .user.id, .user.bot, .data["custom_id"]
#   .response.edit_message  (AsyncMock — the single ack)
#   .response.send_message  (AsyncMock — the reject path)
#   .response.is_done       (MagicMock returning a bool — the _safe_error_edit guard)
#   .edit_original_response (AsyncMock — the in-place result/error)
#   .followup.send          (AsyncMock — the post-ack error fallback)
# Add it to conftest.py as a `fake_interaction` fixture (sibling to fake_discord_message).
```

**Test-body patterns to copy** — `test_bot.py` already demonstrates every
assertion shape the panel tests need: spy-cache to prove a guard short-circuits
(`test_bot.py:67-79`), `monkeypatch.setitem(registry.BY_NAME, …)` +
`_patch_command_in_registry` to stub a handler (`test_bot.py:137-147` and the helpers
at `:788-809`), and the "raising handler is isolated → no propagation + generic
reply" pattern (`test_bot.py:434-468`). The panel's isolation test
(`test_callback_raise_isolated`) is the direct analog of
`test_raising_command_handler_is_isolated`.

The full node-ID list the file must cover is in 17-RESEARCH §"Phase Requirements →
Test Map" (PANEL-02/03/04/05/06/08, D-07/08/10/13, isolation).

---

### `tests/test_registry.py` (MODIFIED — Weather-group anti-drift assertion)

**Analog:** the assertion at `test_registry.py:74` itself (Pitfall 2 — an INTENDED
anti-drift trip). Adding the `weather` spec makes this exact-set assertion fail until
updated in the SAME change:

```python
# test_registry.py:74 — current (RED after W2) → add "weather"
assert weather == {"alerts", "sun", "wind", "next-cloudy", "uv"}
# becomes:
assert weather == {"weather", "alerts", "sun", "wind", "next-cloudy", "uv"}
```

> Optionally add a positive `test_weather_command_registered_and_wired` mirroring
> `test_uv_command_registered_and_wired` (`test_registry.py:98-110`) — same sibling
> shape (assert in `COMMANDS`, handler wired, `takes_location is True`, Weather
> group). The `takes_location` block at `test_registry.py:79-87` and the help
> assertions also enumerate names; confirm they stay green (the loop-based ones at
> `:128-145` are name-agnostic and need no edit).

---

## Shared Patterns

### The shared dispatch seam (the panel is the THIRD caller — PANEL-10)
**Source:** `weatherbot/interactive/dispatch.py:105-179` (`dispatch_spec`) +
`dispatch.py:60-102` (`dispatch_reply`).
**Apply to:** `panel.py` — every button callback is `await dispatch_spec(spec, arg,
cache=…, config=…, loop=…, daemon_state=…)`. `custom_id → spec` (via `BY_NAME`),
`selected location → arg`, argless buttons pass `arg=None`. The off-loop fetch +
the whole bind ladder already run via `run_in_executor` inside `dispatch_spec`
(`dispatch.py:156-179`) — the panel must add NO on-loop I/O. The new `weather`
handler lands in the catch-all branch #4 (`dispatch.py:95-96`), so W2 needs **zero
ladder edits**.

### The single renderer (surfaces can't drift — D-04/D-05)
**Source:** `weatherbot/interactive/bot.py:124-191` (`render_embed`).
**Apply to:** `panel.py` renders results with `render_embed(reply)` — the SAME
function `on_message` uses (`bot.py:296`). Do NOT write a second embed builder. The
byte-identical reference for the `weather` reply is `build_inbound_embed`
(`bot.py:194-214`).

### The operator gate + non-propagating envelope (CMD-16 isolation)
**Source:** `bot.py:250-254` (author/operator guard order), `bot.py:271-303` (the
non-propagating try/except that catches `UnknownLocationError` at the call site and
swallows everything else into a generic reply + `_log.exception`).
**Apply to:** `panel.py` re-implements BOTH per the component model:
`interaction_check` is the operator gate (one place, before all children); a
per-callback `try/except` PLUS `View.on_error` is the envelope (the `on_message`
envelope structurally does NOT cover component callbacks — see PITFALLS.md Pitfall 1
and 17-RESEARCH Pattern 4). The reject log is the SOLE audit of a non-operator tap
(`interaction_check`'s clean `return False` does not fire `on_error`).

### Config snapshot + default location (PANEL-02 / D-03)
**Source:** `holder.py:50-57` (`current()` lock-free snapshot), `loader.py:50-53`
(`resolve_location(config, None) → locations[0]`).
**Apply to:** `panel.py` reads `holder.current()` per tap (hot-reload picked up on
the next interaction) and re-derives Select options from
`holder.current().locations`. The D-03 default `_selected_location` is
`locations[0].name`, the exact precedent `resolve_location(config, None)` encodes.

### Acyclic module-top imports (Pitfall 5 — interactive/ discipline)
**Source:** `dispatch.py:36-57`, `bot.py:36-55`, `command.py:17-24`
(`from __future__ import annotations`; light siblings at module top; heavy types
under `TYPE_CHECKING`).
**Apply to:** `panel.py` imports `discord` + `structlog` + the sibling seams
(`registry`, `bot.render_embed`, `dispatch_spec`, `UnknownLocationError`) at module
top (acyclic — nothing imports `panel`); `ConfigHolder` / `ForecastCache` /
`DaemonState` go under `TYPE_CHECKING`. No in-handler lazy imports.

### The derive-from-one-list edit (W2 ripple checklist)
**Source:** the existing `uv` precedent — added as a spec (`registry.py:60-65`), a
handler (`weather_views.py:263`), a wiring entry (`registry.py:108`), and proven by
`test_registry.py:98-117`. Adding `weather` follows the same four-touch pattern PLUS
the two W2-specific guards: the CLI subparser skip-guard (`cli.py:815`) and the
byte-identical `!weather` reply. The full "what else carries this string?" sweep is
in 17-RESEARCH §"Runtime State Inventory" — all four derived surfaces (help, CLI
loop, `test_registry.py`, `COMMANDS` enumerations) are in-repo and caught by the
contractual suite.

---

## No Analog Found

The **discord.py View/Button/Select mechanics** have no in-repo analog (this is the
first `discord.ui.View` in the project). The planner should use 17-RESEARCH Patterns
1–4 + Code Examples directly as the copy-from for that code — those excerpts were
VERIFIED against the installed discord.py 2.7.1 source (`.venv`) and the empirical
probe, which is a stronger reference than any invented pattern. Specifically:

| Mechanism | Reference (not in-repo) | Why no in-repo analog |
|-----------|-------------------------|------------------------|
| `PanelView` / `CmdButton` / `LocationSelect` subclass+override | 17-RESEARCH Pattern 1 | First `discord.ui.View` in the codebase |
| Single-ack `edit_message` → `edit_original_response` | 17-RESEARCH Pattern 2 | No prior interaction-component code |
| `_disabled_copy()` transient-view helper | 17-RESEARCH §Code Examples | New UX mechanism (D-14) |
| `_safe_error_edit` is_done()-guarded reply | 17-RESEARCH Pattern 4 / Pitfall 4 | New error surface |

Everything that **fetches, binds, renders, gates, or defaults** has a concrete
in-repo analog (excerpted above) — only the raw discord.py wiring is greenfield.

## Metadata

**Analog search scope:** `weatherbot/interactive/` (panel[N/A], bot, dispatch,
registry, command, lookup, cache, state, commands/{__init__, weather_views}),
`weatherbot/config/{holder, loader}.py`, `weatherbot/cli.py`, `tests/{conftest,
test_bot, test_dispatch, test_registry}.py`.
**Files scanned:** 16
**Pattern extraction date:** 2026-06-23
