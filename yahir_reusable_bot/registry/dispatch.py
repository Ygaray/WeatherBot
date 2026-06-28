"""The generic command dispatcher shell — ``spec.bind(ctx)`` off the loop (D-01).

This is the relocated dispatcher (SEAM-06), de-weathered at BOTH coupling sites the
app original carried:

1. **The arm ladder collapses (D-01).** The app's old ``dispatch_reply`` branched on
   weather command names + a group string + threshold reads. That entire ladder LEAVES
   the module: each arm becomes one app-authored ``bind`` closure on its spec, and the
   module's :func:`dispatch_reply` collapses to ``return spec.bind(ctx)``. The module
   shell never sees a command name, a group, or a threshold.

2. **The fetch branch keys on a neutral signal (D-01 follow-through).** The app's old
   ``dispatch_spec`` keyed its flags-parse + cache-suffix branch on
   ``spec.group == "Forecast"``. The module reads the neutral ``spec.needs_flags``
   instead, and reaches the app's flag grammar through INJECTED ``parse_flags`` /
   ``cache_suffix`` hooks (opaque callables — the module never inspects their bodies).
   The flag grammar itself stays app-side; the module names no app-specific group.

The off-loop discipline is preserved byte-identically: ALL blocking work — the fetch
and the WHOLE reply — runs via ``loop.run_in_executor`` so a handler that touches a
blocking resource (e.g. SQLite) never blocks the host's event loop. Exceptions raised
inside the injected hooks or the ``bind`` closure BUBBLE out uncaught — the module
shell never swallows them; the caller catches the app's domain error at the call site.

``parse_flags`` / ``cache_suffix`` are app-supplied opaque callables (the same
constructor-injection / opaque-callable discipline the module already ships on
``SchedulerEngine`` / ``ReloadEngine``); the module forwards to them and learns nothing
about the app's grammar.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from yahir_reusable_bot.registry.spec import CommandSpec, DispatchContext


def dispatch_reply(spec: CommandSpec, ctx: DispatchContext) -> Any:
    """Invoke the spec's opaque ``bind`` closure with ``ctx`` and return its result.

    The entire app arg-adaptation ladder is gone — it lives inside each app ``bind``
    closure now (D-01). The module shell knows nothing about what the closure does.
    """
    return spec.bind(ctx)


async def dispatch_spec(
    spec: CommandSpec,
    arg: str | None,
    *,
    cache: Any,
    config: Any,
    loop: asyncio.AbstractEventLoop,
    daemon_state: Any,
    flags: Any = None,
    parse_flags: Callable[[str | None], Any],
    cache_suffix: Callable[[str, Any], str],
) -> Any:
    """Async off-loop-fetch wrapper around :func:`dispatch_reply` (off-loop discipline).

    For a spec whose ``needs_flags`` signal is set, parse ``arg`` into ``flags`` via the
    injected ``parse_flags`` hook (skipped when the caller already supplied ``flags``),
    look the result up by ``flags.location``, and widen the cache key with the injected
    ``cache_suffix(spec.name, flags)`` hook. For a spec that does not need flags, look up
    the raw ``arg`` with no suffix. For a spec whose ``bind`` needs no fetched result the
    fetch is skipped (``result`` stays ``None``).

    All blocking work runs OFF the loop (the fetch AND the whole reply) via
    ``loop.run_in_executor``. The needs-flags path passes the 3-arg ``suffix`` form to
    the cache; the plain path keeps the 2-arg form (back-compat). Exceptions from the
    injected hooks or the ``bind`` closure BUBBLE — never caught here.
    """
    result: Any = None

    if arg is not None or spec.needs_flags:
        needs = spec.needs_flags
        lookup_name = arg
        suffix = None
        if needs:
            if flags is None:
                flags = parse_flags(arg)
            lookup_name = flags.location
            suffix = cache_suffix(spec.name, flags)
        # All blocking work OFF the loop. Only the needs-flags path passes the
        # widened-key suffix (3-arg); the plain path keeps the original 2-arg cache
        # call (back-compat). Any domain error bubbles.
        if needs:
            result = await loop.run_in_executor(
                None, cache.lookup, lookup_name, config, suffix
            )
        else:
            result = await loop.run_in_executor(None, cache.lookup, lookup_name, config)

    # Run the whole reply off-loop too: a handler may touch a blocking resource, so the
    # host's event loop must never block on it. Replies stay byte-identical.
    ctx = DispatchContext(
        result=result,
        config=config,
        flags=flags,
        daemon_state=daemon_state,
    )
    return await loop.run_in_executor(None, lambda: dispatch_reply(spec, ctx))
