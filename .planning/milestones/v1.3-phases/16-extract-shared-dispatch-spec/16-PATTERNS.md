# Phase 16: Extract Shared `dispatch_spec` - Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 3 (1 new, 2 modified)
**Analogs found:** 3 / 3

This is a behavior-preserving refactor. The "patterns to copy" are unusually
literal: the NEW module's *style* is copied from its sibling `interactive/`
modules, and its *body* is the verbatim if/elif ladder lifted out of the two
call sites. The two MODIFIED files have their ladders DELETED and replaced with
a call. The excerpts below are load-bearing — they must move byte-for-byte (same
branch order, same `spec.handler(...)` arg shapes) so the existing tests stay
green.

## File Classification

| File | New/Mod | Role | Data Flow | Closest Analog | Match Quality |
|------|---------|------|-----------|----------------|---------------|
| `weatherbot/interactive/dispatch.py` | NEW | service (dispatcher) | request-response (sync ladder) + async off-loop fetch | `weatherbot/interactive/cache.py` (style) + `command.py` (style) | role + style match (no existing dispatcher) |
| `weatherbot/interactive/bot.py` | MOD | controller (gateway handler) | event-driven (async on_message) | itself (in-place ladder removal) | exact (self) |
| `weatherbot/cli.py` | MOD | controller (CLI command) | request-response (sync) | itself (in-place ladder removal) | exact (self) |

---

## Pattern Assignments

### `weatherbot/interactive/dispatch.py` (NEW — service / dispatcher)

No dispatcher exists yet, so style is copied from the leanest sibling modules in
`weatherbot/interactive/` that the CONTEXT.md flagged (D-09): `cache.py`,
`command.py`, `state.py`. The function BODY is the ladder lifted from the two
call sites (see the two MODIFIED files below — those excerpts ARE the body).

**Module-top + TYPE_CHECKING style** — copy from `cache.py:30-46` and
`state.py:15-24`. Every `interactive/` module opens with `from __future__ import
annotations`, imports only light siblings at module top, and pushes heavy types
under `TYPE_CHECKING`:

```python
# cache.py:30-46 — the exact shape dispatch.py should mirror
from __future__ import annotations

import threading                       # (dispatch.py needs asyncio instead)
from typing import TYPE_CHECKING, Callable

import structlog

from weatherbot.config import resolve_location
from weatherbot.interactive.lookup import lookup_weather

if TYPE_CHECKING:
    from weatherbot.config.models import Config
    from weatherbot.config.settings import Settings
    from weatherbot.interactive.lookup import LookupResult

_log = structlog.get_logger(__name__)
```

For `dispatch.py` (per D-09): import `command` and/or `registry` at module top
(acyclic — nothing imports `dispatch`). The forecast-flag helpers
`parse_forecast_flags` / `forecast_cache_suffix` live in `command.py` — D-09 says
`dispatch.py` MAY import `command` at module top (it is recommended that
`dispatch_spec` owns the forecast-flags parse so bot + panel stay DRY, per
CONTEXT lines 98-100). Heavy types go under `TYPE_CHECKING`:

```python
if TYPE_CHECKING:
    from weatherbot.config.models import Config
    from weatherbot.interactive.cache import ForecastCache
    from weatherbot.interactive.command import ForecastFlags
    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive.lookup import LookupResult
    from weatherbot.interactive.state import DaemonState
    from weatherbot.interactive.registry import CommandSpec
```

> NOTE on lazy imports: `bot.py:287-290` currently lazy-imports
> `parse_forecast_flags` / `forecast_cache_suffix` *inside* `on_message`. That
> lazy import was a cycle dodge from the CALL SITE. In `dispatch.py` these can be
> a normal module-top import (`from weatherbot.interactive.command import
> parse_forecast_flags, forecast_cache_suffix`) because `command.py` does not
> import `dispatch` — D-09 confirms this is acyclic. Mirror the
> `command.py → registry` direction, not the in-handler lazy form.

**Function signature conventions** — `interactive/` uses keyword-only params with
`*,` and explicit return-type annotations (see `cache.py:57-64`,
`build_on_message` `bot.py:216-222`). D-01 already fixes the inner signature:

```python
def dispatch_reply(
    spec: CommandSpec,
    *,
    result: LookupResult | None,
    config: Config,
    flags: ForecastFlags | None,
    daemon_state: DaemonState | None,
) -> CommandReply:
    ...
```

The async wrapper mirrors `cache.lookup`'s off-loop contract (see cache.py
docstring lines 13-21 "ALWAYS called via loop.run_in_executor"). Exact param
shape for `dispatch_spec` is Claude's Discretion (CONTEXT lines 94-100) — the
constraint is only D-01/D-02 layering: outer does the off-loop fetch then calls
the inner ladder.

**Return shape — `CommandReply`** — from `commands/__init__.py:21-35`. The ladder
returns whatever `spec.handler(...)` produces, which is always a `CommandReply`
(frozen: `title: str`, `lines: tuple[tuple[str,str],...]`, `text: str | None`).
The dispatcher returns it unrendered — rendering stays at the call site (D-05).

**Docstring + structlog conventions** — every `interactive/` module has a rich
module docstring citing the decision IDs and a `_log = structlog.get_logger(__name__)`.
Match that house style (cite D-01/D-02/D-07/D-09).

---

### `weatherbot/interactive/bot.py` (MODIFIED — controller / async gateway)

**Analog:** itself. The async ladder is DELETED; the dispatch becomes one
`await dispatch_spec(...)` call kept INSIDE the existing typing block and the
existing non-propagating try/except envelope (D-06, code_context lines 171-174).

**Current code to REPLACE** — `bot.py:276-329` (the whole inside-`typing()`
fetch + ladder). This is the exact behavior `dispatch_spec` must reproduce:

```python
# bot.py:276-329 — forecast-flag parse + off-loop fetch + the if/elif ladder
if spec.takes_location:
    is_forecast = spec.group == "Forecast"
    lookup_name = arg
    flags = None
    suffix = None
    if is_forecast:
        from weatherbot.interactive.command import (
            forecast_cache_suffix,
            parse_forecast_flags,
        )
        flags = parse_forecast_flags(arg)
        lookup_name = flags.location
        suffix = forecast_cache_suffix(spec.name, flags)
    try:
        if is_forecast:
            result = await loop.run_in_executor(
                None, cache.lookup, lookup_name, config, suffix
            )
        else:
            result = await loop.run_in_executor(
                None, cache.lookup, lookup_name, config
            )
    except UnknownLocationError as exc:
        await message.channel.send(str(exc))   # STAYS at call site (D-06)
        return
    if is_forecast:
        reply = spec.handler(result, flags)
    elif spec.name == "next-cloudy":
        reply = spec.handler(result, config.cloud_threshold)
    elif spec.name == "uv":
        reply = spec.handler(result, config.uv.threshold)
    else:
        reply = spec.handler(result)
elif spec.name == "status":
    reply = await loop.run_in_executor(None, spec.handler, daemon_state)
elif spec.name == "locations":
    reply = spec.handler(config)
else:  # help — no fetch, no config
    reply = spec.handler()
payload = render_embed(reply)
```

**What MUST stay at the call site** (do NOT move into the shared module):
- The guard ladder `bot.py:247-264` (author/bot/operator/prefix/`parse_command`) — untouched.
- The `async with message.channel.typing():` block `bot.py:275` — the `dispatch_spec` call goes inside it.
- `UnknownLocationError → await message.channel.send(str(exc)); return` (D-06). The shared code MUST let this exception bubble; the bot catches it at the call site. (Currently caught at `bot.py:309-312` around only the fetch — preserve that semantics: the bot's send-the-message-and-return on unknown location.)
- The outer non-propagating try/except `bot.py:270-337` (`_log.exception` + `_ERROR_REPLY`) — the WHOLE `dispatch_spec` call stays inside it; no second envelope (code_context line 174, criterion #4 / CMD-16).
- `payload = render_embed(reply)` and `await message.channel.send(embed=payload)` `bot.py:330-331` — rendering + send stay (D-05).

**Behavioral subtlety to preserve (status off-loop):** the bot runs the `status`
handler off-loop too (`bot.py:325` — `read_heartbeat` touches SQLite). The sync
`dispatch_reply` calls `spec.handler(daemon_state)` directly; in the async path
`dispatch_spec` should still run the whole `dispatch_reply` (or at least the
status handler) via `run_in_executor` so the loop never blocks on SQLite. Easiest
behavior-preserving approach: have `dispatch_spec` off-load the entire
`dispatch_reply` call to the executor after computing `result`. Confirm against
`tests/test_bot.py` either way.

---

### `weatherbot/cli.py` (MODIFIED — controller / sync CLI command)

**Analog:** itself. Per D-02 the CLI is unified by replacing ONLY its if/elif
block with a `dispatch_reply(...)` call. The CLI MUST NOT call the async
`dispatch_spec` (different fetch path, no event loop).

**Current code to REPLACE** — `cli.py:618-632` (the if/elif ladder, identical
twin of the bot's). This is what the `dispatch_reply(...)` call replaces:

```python
# cli.py:618-632 — the identical sync ladder (replace with dispatch_reply call)
if spec.takes_location:
    if is_forecast:
        reply = spec.handler(result, flags)
    elif spec.name == "next-cloudy":
        reply = spec.handler(result, config.cloud_threshold)
    elif spec.name == "uv":
        reply = spec.handler(result, config.uv.threshold)
    else:
        reply = spec.handler(result)
elif spec.name == "status":
    reply = spec.handler(_cli_daemon_state(config))
elif spec.name == "locations":
    reply = spec.handler(config)
else:  # help
    reply = spec.handler()
rendered = render_text(reply)
```

The replacement is a single call, e.g.:
```python
reply = dispatch_reply(
    spec,
    result=result if spec.takes_location else None,
    config=config,
    flags=flags,
    daemon_state=_cli_daemon_state(config) if spec.name == "status" else None,
)
rendered = render_text(reply)
```

**What MUST stay at the call site** (do NOT move into the shared module):
- The forecast-flag parse `cli.py:578-589` (`is_forecast`, `parse_forecast_flags(raw_args)`, the `ValueError → stderr / exit 1`). NOTE: the CLI's flag source is `args.args` (subparser `nargs="*"`), DIFFERENT from the bot's `arg` string — so the *parse-source* stays at the CLI call site even though both produce a `ForecastFlags` that feeds the same ladder. (CONTEXT discretion lines 98-100 lets `dispatch_spec` own the parse for the ASYNC surfaces; the CLI keeps its own.)
- `lookup_weather(...)` + the tenacity/exit-code wrapper `cli.py:591-608` (`UnknownLocationError → stderr/exit 1`, `httpx.* → exit 3`) — D-02/D-06.
- `_cli_daemon_state(config)` `cli.py:643-675` — the CLI builds its own scoped `DaemonState` and passes it as the `daemon_state` arg (code_context lines 179-181: the shared ladder takes `daemon_state` as a param, no special-casing inside it).
- The handler-failure envelope `cli.py:617,634-637` (`try/except → _log.error + exit 3`) — keep the `dispatch_reply(...)` call INSIDE this try so a handler raise still becomes the clean exit-3 message, not a traceback (D-06).
- `render_text(reply)` + `print(rendered)` `cli.py:633,639` — rendering stays (D-05).

---

## Shared Patterns

### The if/elif binding ladder (the one thing being centralized — D-07)
**Source (identical in both):** `bot.py:313-329` and `cli.py:618-632`
**Lands in:** `dispatch_reply` (single copy)
**Branch order is load-bearing** — preserve verbatim (matches D-07 lines 70-78):
1. `spec.takes_location` + `spec.group == "Forecast"` → `handler(result, flags)`
2. `spec.takes_location` + `spec.name == "next-cloudy"` → `handler(result, config.cloud_threshold)`
3. `spec.takes_location` + `spec.name == "uv"` → `handler(result, config.uv.threshold)`
4. `spec.takes_location` (catch-all) → `handler(result)`
5. `spec.name == "status"` → `handler(daemon_state)`
6. `spec.name == "locations"` → `handler(config)`
7. else (`help`) → `handler()`

A new command of an existing shape needs zero ladder edits (catch-all at #4); a
genuinely new arg-shape is a one-line edit in this single place (D-07).

### Off-loop fetch contract (async wrapper only — D-01)
**Source:** `cache.py:82-120` (`ForecastCache.lookup`) + `bot.py:301-308` (the `run_in_executor` call).
**Apply to:** `dispatch_spec` only. `cache.lookup(name, config, suffix)` is ALWAYS
called via `loop.run_in_executor` (cache.py docstring lines 13-21). Plain weather
passes the 2-arg form (`cache.lookup, name, config`); forecast passes the widened
key (`cache.lookup, name, config, suffix`). The CLI does NOT use the cache — it
calls `lookup_weather` directly (cli.py:598), so this contract is async-surface-only.

### Acyclic lazy / module-top imports (Pitfall 5 — D-09)
**Source:** `command.py:22-24` (module-top `from weatherbot.interactive import
registry`), `registry.py:84-115` (lazy handler wiring), `lookup.py:105-113` (lazy
`build_client` inside a branch).
**Apply to:** `dispatch.py` — import `command`/`registry` at module top (acyclic,
nothing imports `dispatch`); heavy types under `TYPE_CHECKING`. Do NOT replicate
the call-site's in-handler lazy import of `parse_forecast_flags` (that was a
call-site cycle dodge; unnecessary in `dispatch.py`).

### Surface-agnostic reply seam (D-05 — unchanged)
**Source:** `commands/__init__.py:21-35` (`CommandReply`), `bot.py:123-190`
(`render_embed`), `cli.py:540-553` (`render_text`).
**Apply to:** Both call sites keep their renderer. `dispatch_*` returns the raw
`CommandReply`; it never renders. This is the existing anti-drift seam — leave it.

---

## No Analog Found

None. Every needed pattern exists in `weatherbot/interactive/` (style) or in the
two call sites themselves (the ladder body). `dispatch_spec` is named in
`.planning/research/ARCHITECTURE.md` §Pattern 2 but has no existing
implementation — its body is the lifted ladder above, not a fresh design.

## Metadata

**Analog search scope:** `weatherbot/interactive/` (bot, registry, command,
cache, lookup, state, commands), `weatherbot/cli.py`.
**Files scanned:** 8
**Pattern extraction date:** 2026-06-23
