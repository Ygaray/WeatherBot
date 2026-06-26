"""The single shared command dispatcher (Phase 16-01, PANEL-10, D-01/D-02/D-07/D-09).

This module holds the ONE arg-adaptation ladder that decides "what does each
registry command's handler need to be handed". Before this module the identical
``if/elif`` ladder lived in BOTH :func:`weatherbot.interactive.bot.build_on_message`
and :func:`weatherbot.cli._run_registry_command`; lifting it here means the command
set can never drift across surfaces — the bot, the CLI, and the future Phase-17
panel are all just callers of the same code (criterion #3 / PANEL-10).

Two layers (D-01):

- **Inner — :func:`dispatch_reply` (SYNC):** the single ``if/elif`` who-needs-what
  ladder and nothing else. It receives an already-fetched ``LookupResult``
  (``result``, ``None`` for argless specs), the parsed ``ForecastFlags`` (``flags``,
  ``None`` for non-forecast specs), the ``Config``, and the read-only
  ``DaemonState``, and returns the ``CommandReply`` the handler produces. It does
  NO fetch, NO render, NO I/O (D-05) — it only invokes the registry handler and
  reads ``DaemonState``. Each surface keeps its own fetch/retry and renderer.

- **Outer — :func:`dispatch_spec` (ASYNC):** the convenience wrapper for the async
  surfaces (``on_message`` now, the panel in Phase 17). It owns the forecast-flags
  parse (so bot + panel stay DRY), runs the off-loop ``ForecastCache.lookup`` fetch
  via ``loop.run_in_executor`` (D-10 / Pitfall 1), then runs the whole
  ``dispatch_reply`` call off-loop too (so the ``status`` handler's SQLite
  ``read_heartbeat`` never blocks the gateway loop), and returns the
  ``CommandReply``. It lets ``UnknownLocationError`` BUBBLE (D-06): the bot catches
  it at the call site and replies with the valid names. The CLI does NOT use this
  wrapper — it has no event loop and its own sync fetch path (D-02).

Imports (D-09 / Pitfall 5): ``parse_forecast_flags`` / ``forecast_cache_suffix``
come in at MODULE TOP (acyclic — nothing imports ``dispatch``; ``command.py`` does
not import this module), NOT via the call-site's in-handler lazy import. Heavy
types are pushed under ``TYPE_CHECKING`` to keep the module-top graph light.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from weatherbot.interactive.command import (
    forecast_cache_suffix,
    parse_forecast_flags,
)

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

    The SINGLE arg-adaptation ladder lifted verbatim from ``on_message`` / the CLI.
    Branch ORDER is load-bearing (D-07) and mirrors the two old call sites exactly:

    1. ``takes_location`` + ``group == "Forecast"`` → ``handler(result, flags)``
    2. ``takes_location`` + ``name == "next-cloudy"`` → ``handler(result, config.cloud_threshold)``
    3. ``takes_location`` + ``name == "uv"`` → ``handler(result, config.uv.threshold)``
    4. ``takes_location`` (catch-all) → ``handler(result)``
    5. ``name == "status"`` → ``handler(daemon_state)``
    6. ``name == "locations"`` → ``handler(config)``
    7. else (``help``) → ``handler()``

    A new command of an existing shape needs zero edits (catch-all #4); a genuinely
    new arg-shape is a one-line edit HERE — the single place the binding lives.

    Read-only (D-05): NO fetch, NO render, NO store/sent-log/scheduler write. The
    function only invokes the registry handler and reads ``DaemonState``; the caller
    fetched ``result`` upstream and renders the returned ``CommandReply`` downstream.
    """
    if spec.takes_location:
        if spec.group == "Forecast":
            return spec.handler(result, flags)
        elif spec.name == "next-cloudy":
            return spec.handler(result, config.cloud_threshold)
        elif spec.name == "uv":
            return spec.handler(result, config.uv.threshold)
        else:
            return spec.handler(result)
    elif spec.name == "status":
        return spec.handler(daemon_state)
    elif spec.name == "locations":
        return spec.handler(config)
    else:  # help — no fetch, no config
        return spec.handler()


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

    Owns the forecast-flags parse for the async surfaces (bot + panel stay DRY):
    for a ``Forecast`` spec it parses ``arg`` into ``flags``, looks the location up
    by ``flags.location``, and widens the cache key with
    ``forecast_cache_suffix(spec.name, flags)`` so a forecast result never collides
    with a plain ``!weather`` result (A5). For a plain location spec ``flags`` is
    ``None``, the lookup name is the raw ``arg``, and no suffix is used.

    All blocking work runs OFF the loop (Pitfall 1): the ``ForecastCache.lookup``
    fetch via ``loop.run_in_executor`` — forecast passes the 3-arg ``suffix`` form,
    plain weather the 2-arg form (back-compat) — and then the WHOLE
    :func:`dispatch_reply` call too, because the ``status`` handler's
    ``read_heartbeat`` touches SQLite and must not block the gateway heartbeat.

    Off-loop scope (deliberate widening — WR-02): the OLD bot ladder ran only the
    ``status`` handler via ``run_in_executor`` while every other handler call ran ON
    the loop. This wrapper now dispatches the ENTIRE ladder — every handler, not just
    ``status`` — to the executor. That is intentional and behavior-preserving: the
    weather-view / ``locations`` / ``help`` handlers are pure in-memory reads of an
    already-fetched payload (no I/O), so moving them off-loop changes nothing
    observable, and one uniform off-loop tail call is simpler than special-casing
    ``status``. Replies stay byte-identical (the contractual suite proves it).

    ``UnknownLocationError`` is NOT caught here — it BUBBLES (D-06); the bot catches
    it at the call site and replies with the valid names. For non-location specs no
    fetch happens and ``result`` is ``None``.

    Additive ``flags=`` seam (Phase 19, D-01/D-02): a caller may pass a pre-built
    ``ForecastFlags`` (the panel does). When ``flags is not None`` the
    ``parse_forecast_flags(arg)`` parse is SKIPPED and the passed flags drive
    ``lookup_name``/``suffix`` directly. When ``flags is None`` (every existing
    caller) the forecast branch runs the parse path byte-for-byte — behavior-
    preserving, not a refactor.
    """
    result: LookupResult | None = None

    if spec.takes_location:
        is_forecast = spec.group == "Forecast"
        lookup_name = arg
        suffix = None
        if is_forecast:
            if flags is None:  # NEW guard (D-02): existing parse path untouched
                flags = parse_forecast_flags(arg)
            # else: caller-provided flags drive lookup_name/suffix directly (D-01)
            lookup_name = flags.location
            suffix = forecast_cache_suffix(spec.name, flags)
        # All blocking work OFF the loop (D-10). Only forecast commands pass the
        # widened-key ``suffix`` so a plain weather lookup keeps the original 2-arg
        # cache call (back-compat). UnknownLocationError bubbles (D-06).
        if is_forecast:
            result = await loop.run_in_executor(
                None, cache.lookup, lookup_name, config, suffix
            )
        else:
            result = await loop.run_in_executor(
                None, cache.lookup, lookup_name, config
            )

    # Run the WHOLE ladder off-loop too (deliberate widening — WR-02). status ->
    # read_heartbeat touches SQLite, so the gateway loop must never block on it; the
    # other handlers are pure in-memory reads, so dispatching them all to the executor
    # is harmless and avoids special-casing status. Old bot ladder ran only status
    # off-loop; replies are byte-identical regardless.
    return await loop.run_in_executor(
        None,
        lambda: dispatch_reply(
            spec,
            result=result,
            config=config,
            flags=flags,
            daemon_state=daemon_state,
        ),
    )
