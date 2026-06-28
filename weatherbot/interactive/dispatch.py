"""The shared command dispatcher — a thin app shim over the module dispatcher (SEAM-06).

Before Phase 26 this module held the ONE arg-adaptation ladder + the off-loop fetch
wrapper in-app. Phase 26 (D-01/D-03) relocates the generic dispatcher mechanism into
``yahir_reusable_bot.registry``; this module is now a THIN app shim that delegates to it
so the three call sites (``bot.py`` / ``panel.py`` ×2 / ``cli.py``) stay byte-identical.

Two functions, both thin (mirrors the registry re-export pattern, D-03):

- **:func:`dispatch_reply` (SYNC)** — bundles its four params into a module
  :class:`~yahir_reusable_bot.registry.DispatchContext` and returns the module
  ``dispatch_reply(spec, ctx)`` (which calls ``spec.bind(ctx)``, the per-command arg-
  binding closure authored app-side in ``registry._wire_handlers``). The entire old
  if/elif ladder now lives inside those ``bind`` closures (D-01); this shim names no
  command, group, or threshold. The CLI calls this directly (no event loop, own sync
  fetch — D-02).

- **:func:`dispatch_spec` (ASYNC)** — keeps its EXACT current signature and delegates to
  the module ``dispatch_spec``, INJECTING the app forecast hooks ``parse_flags=
  parse_forecast_flags`` and ``cache_suffix=forecast_cache_suffix`` (both still imported
  app-side from ``command.py`` — they STAY app-side, litmus-tripping forecast grammar).
  The module reads the neutral ``spec.needs_flags`` (set in ``registry._SPECS`` for the
  two forecast specs) instead of ``spec.group == "Forecast"`` — so the module names no
  weather group. The off-loop ``run_in_executor`` fetch + reply discipline and the
  ``UnknownLocationError`` BUBBLE (D-06) are preserved by the module shell; this shim
  adds no catch.

Imports (D-09 / Pitfall 5): ``parse_forecast_flags`` / ``forecast_cache_suffix`` come in
at MODULE TOP (acyclic — nothing imports ``dispatch``; ``command.py`` does not import
this module). Heavy types are pushed under ``TYPE_CHECKING`` to keep the module-top graph
light.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from weatherbot.interactive.command import (
    forecast_cache_suffix,
    parse_forecast_flags,
)
from yahir_reusable_bot.registry import DispatchContext
from yahir_reusable_bot.registry import dispatch_reply as _module_dispatch_reply
from yahir_reusable_bot.registry import dispatch_spec as _module_dispatch_spec

if TYPE_CHECKING:
    from weatherbot.config.models import Config
    from weatherbot.interactive.cache import ForecastCache
    from weatherbot.interactive.command import ForecastFlags
    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive.lookup import LookupResult
    from weatherbot.interactive.registry import CommandSpec
    from weatherbot.interactive.state import DaemonState

_log = structlog.get_logger(__name__)


def dispatch_reply(
    spec: CommandSpec,
    *,
    result: LookupResult | None,
    config: Config,
    flags: ForecastFlags | None,
    daemon_state: DaemonState | None,
) -> CommandReply:
    """Bind ``spec``'s handler to its args and return the ``CommandReply`` (D-01/D-07).

    A thin shim (D-03): bundles the four params into a module
    :class:`~yahir_reusable_bot.registry.DispatchContext` and returns the module
    ``dispatch_reply(spec, ctx)`` — which invokes the per-command ``spec.bind(ctx)``
    closure (the verbatim lift of one old arg-adaptation arm, authored app-side in
    ``registry._wire_handlers``). The old in/elif ladder is gone from here; the binding
    lives in each app ``bind`` closure (a new command of an existing shape needs zero
    edits here, a genuinely new arg-shape is a one-line edit in ``_wire_handlers``).

    Read-only (D-05): NO fetch, NO render, NO store/sent-log/scheduler write — the
    ``bind`` closures only invoke the registry handler (and read ``DaemonState``); the
    caller fetched ``result`` upstream and renders the returned ``CommandReply``
    downstream.
    """
    ctx = DispatchContext(
        result=result,
        config=config,
        flags=flags,
        daemon_state=daemon_state,
    )
    return _module_dispatch_reply(spec, ctx)


async def dispatch_spec(
    spec: CommandSpec,
    arg: str | None,
    *,
    cache: ForecastCache,
    config: Config,
    loop: asyncio.AbstractEventLoop,
    daemon_state: DaemonState | None,
    flags: ForecastFlags | None = None,
) -> CommandReply:
    """Async off-loop-fetch wrapper for the async surfaces (D-01, off-loop D-10).

    A thin shim (D-03): keeps the EXACT current signature (the three call sites — bot.py,
    panel.py ×2 — stay byte-identical) and delegates to the module ``dispatch_spec``,
    INJECTING the app forecast hooks ``parse_flags=parse_forecast_flags`` and
    ``cache_suffix=forecast_cache_suffix``. The module gates its flags-parse + cache-key
    widening on the neutral ``spec.needs_flags`` signal (set on the two forecast specs)
    rather than naming a weather group; the forecast grammar itself stays app-side.

    The module shell owns the rest of the contract byte-identically: the off-loop
    ``ForecastCache.lookup`` fetch (3-arg widened form for needs-flags specs, 2-arg
    back-compat for plain weather), the off-loop whole-reply call (so the ``status``
    handler's SQLite ``read_heartbeat`` never blocks the gateway loop), the additive
    caller-provided ``flags=`` passthrough (skips the parse), and the
    ``UnknownLocationError`` BUBBLE (D-06) — this shim adds no catch.
    """
    return await _module_dispatch_spec(
        spec,
        arg,
        cache=cache,
        config=config,
        loop=loop,
        daemon_state=daemon_state,
        flags=flags,
        parse_flags=parse_forecast_flags,
        cache_suffix=forecast_cache_suffix,
    )
