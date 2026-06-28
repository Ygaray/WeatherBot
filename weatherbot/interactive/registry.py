"""The single self-describing command registry (CMD-09, D-04; SEAM-06 app half).

This module is the ONE source of truth for the read-only command surface. The
Discord dispatch, the CLI subparser builder, and ``help`` all derive from the same
:data:`COMMANDS` tuple, so adding a command here makes it appear in every surface
with no other edit — the "derive-from-one-list" invariant that keeps ``help`` from
ever drifting (CMD-09 / D-04).

**SEAM-06 (Phase 26 D-03) — thin re-exporting singleton.** The registry *mechanism*
(the :class:`~yahir_reusable_bot.registry.CommandRegistry` type, ``build_registry``,
the three frozen views, ``render_help``) lives in the generic, weather-noun-free
``yahir_reusable_bot.registry`` package. This module keeps a THIN singleton: it owns
the app's command SET (``_SPECS``), builds its singleton via the module
``build_registry(_SPECS)``, and re-exports ``COMMANDS`` / ``BY_NAME`` /
``COMMANDS_BY_KEYWORD_LEN_DESC`` / ``render_help`` byte-for-byte. Every existing read
site (the parser, the CLI subparser build + dispatch, the panel's import-time
``BY_NAME`` assert + callbacks, the bot's ``on_message``) keeps its exact
``registry.X`` access, and the oracle (``tests/test_registry.py`` /
``tests/test_command_views.py``) imports the globals directly — all pass by
construction, not by re-baselining.

Each command is a frozen :class:`CommandSpec` (name, group, summary, takes-location
flag, handler) — the APP's richer spec, which structurally satisfies the module's
generic 4+bind spec. Two app-side fields were added for the relocation (D-01):
``bind`` (the per-command arg-binding closure the module dispatcher invokes opaquely)
and ``needs_flags`` (the neutral pre-dispatch signal the module reads instead of the
old ``spec.group == "Forecast"`` branch). Both the handler AND the bind closure are
wired LAZILY in :func:`_wire_handlers` (imports inside the function) so the import
direction stays acyclic: ``command.py`` imports this module for the parser, and the
handler modules import ``lookup``/``models`` — keeping handler imports out of the
module-top graph (Pitfall 5 / import-cycle guard).

The ``bind`` closures are authored HERE (not at ``wiring.py build_runtime``) because
the CLI (``cli.py`` resolves ``registry.BY_NAME[name]`` and calls ``dispatch_reply``
WITHOUT going through ``build_runtime``) and the panel/bot resolve their specs from
this import-time global — ``build_runtime`` never threads the spec set to those
surfaces, so a ``build_runtime``-authored ``bind`` would be invisible to them. The
weather names + threshold reads in the closures are app-side (this module is the
app, never the module) and read LIVE from the dispatch context per-tap (NOT curried
at build time — the hot-reload contract, D-01: a SIGHUP reload must not serve a
frozen-stale threshold).

``render_help`` is surface-agnostic plain text (grouped by ``.group``); the Discord
embed and the CLI both render the same content (D-04). It is re-exported with the
optional ``commands`` arg defaulting to :data:`COMMANDS` so BOTH ``render_help()``
and the parameterized ``render_help(COMMANDS + (extra,))`` return the byte-identical
string today's code returns.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable

from yahir_reusable_bot.registry import build_registry

if TYPE_CHECKING:
    from yahir_reusable_bot.registry import DispatchContext


@dataclass(frozen=True)
class CommandSpec:
    """One command in the registry — the immutable spec every surface reads.

    ``name`` is the keyword the parser matches (D-01 short names). ``group`` is the
    help section header (D-04: Weather / Info / Forecast). ``summary`` is the one-line
    help description. ``takes_location`` marks the location-taking commands (None arg →
    default location downstream, D-01). ``handler`` is the raw app callable each
    surface's dispatch adapts.

    Two fields were added for the Phase-26 relocation (D-01): ``bind`` is the opaque
    per-command arg-binding closure the generic module dispatcher invokes (it receives
    a :class:`~yahir_reusable_bot.registry.DispatchContext` and returns the handler's
    reply — the verbatim lift of one old ``dispatch_reply`` ladder arm). ``needs_flags``
    is the neutral pre-dispatch signal the module's ``dispatch_spec`` reads (set ``True``
    only on the two forecast specs) instead of the old ``spec.group == "Forecast"``
    branch, so the module names no weather group. Both default to ``None`` / ``False``
    and are filled by :func:`_wire_handlers`; ``handler``/``bind`` stay generic enough
    that the module's structural typing is satisfied.
    """

    name: str
    group: str
    summary: str
    takes_location: bool
    handler: Callable | None = None
    bind: Callable[["DispatchContext"], Any] | None = None
    needs_flags: bool = False


# The immutable source-of-truth command list (D-04 grouping; D-01 short names).
# Specs start handler-less + bind-less; :func:`_wire_handlers` (run once below) replaces
# each with the same spec carrying its real handler AND its bind closure. Keeping the
# literal list handler-free keeps this declaration import-cycle-free; the wiring imports
# the handler modules lazily. ``needs_flags`` is set ``True`` only on the two forecast
# specs (the neutral pre-dispatch signal, D-01 follow-through).
_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("weather", "Weather", "Current conditions for a location.", True),
    CommandSpec("alerts", "Weather", "Active weather alerts for a location.", True),
    CommandSpec("sun", "Weather", "Sunrise and sunset times for a location.", True),
    CommandSpec("wind", "Weather", "Current wind speed and direction.", True),
    CommandSpec(
        "next-cloudy",
        "Weather",
        "The next cloudy day in the forecast window.",
        True,
    ),
    CommandSpec(
        "uv",
        "Weather",
        "Current + max UV and sunscreen window for a location.",
        True,
    ),
    CommandSpec(
        "weekday-forecast",
        "Forecast",
        "Multi-day weekday (Mon-Fri) forecast.",
        True,
        needs_flags=True,
    ),
    CommandSpec(
        "weekend-forecast",
        "Forecast",
        "Multi-day weekend (Fri-Sat-Sun) forecast.",
        True,
        needs_flags=True,
    ),
    CommandSpec("help", "Info", "List all available commands.", False),
    CommandSpec("locations", "Info", "List the configured locations.", False),
    CommandSpec("status", "Info", "Daemon liveness and next scheduled sends.", False),
)


def _wire_handlers(specs: tuple[CommandSpec, ...]) -> tuple[CommandSpec, ...]:
    """Return ``specs`` with each command's real handler AND ``bind`` closure wired on.

    Imports the handler modules LAZILY (here, not at module top) so the registry stays
    importable by ``command.py`` without dragging the handler modules' deeper imports
    (``lookup``/``models``) into the module-top graph — the acyclic-import discipline
    (Pitfall 5). The handlers have heterogeneous signatures (location-taking handlers
    take a ``LookupResult`` (+ ``threshold`` for ``next-cloudy``/``uv``, ``flags`` for
    forecast); ``help`` takes none, ``locations`` a ``Config``, ``status`` a
    ``DaemonState``).

    Each ``bind`` closure is a VERBATIM lift of one old ``dispatch_reply`` arm
    (dispatch.py's if/elif ladder), authored as ``lambda ctx: handler(...)`` reading
    the needed values LIVE from the :class:`~yahir_reusable_bot.registry.DispatchContext`
    per-tap (NOT curried at build time — the hot-reload contract, D-01: thresholds are
    read from ``ctx.config`` so a SIGHUP reload is never served stale). The module
    dispatcher invokes ``spec.bind(ctx)`` opaquely and learns nothing about weather.
    """
    from weatherbot.interactive.commands import (
        forecast,
        info,
        status,
        weather_views,
    )

    handlers: dict[str, Callable] = {
        "weather": weather_views.weather,
        "alerts": weather_views.alerts,
        "sun": weather_views.sun,
        "wind": weather_views.wind,
        "next-cloudy": weather_views.next_cloudy,
        "uv": weather_views.uv,
        "weekday-forecast": forecast.weekday_forecast,
        "weekend-forecast": forecast.weekend_forecast,
        "help": info.help_cmd,
        "locations": info.locations,
        "status": status.status,
    }

    # Each bind closure = one verbatim ``dispatch_reply`` arm. The closure encodes only
    # the per-command ARG-SHAPE (which values the handler takes), reading them LIVE from
    # the dispatch context per-tap (D-01 anti-currying: ctx.config.cloud_threshold /
    # ctx.config.uv.threshold are read per-tap, never captured at build time — a SIGHUP
    # reload is never served stale). The HANDLER itself is resolved live from
    # ``BY_NAME[name].handler`` at call time (not captured) so a test that swaps a spec's
    # handler via ``replace(spec, handler=stub)`` is honored uniformly — the arg-shape is
    # structural, the handler identity is patchable. The weather names + threshold reads
    # are app-side (this is the app's registry module, never the reusable module).
    def _h(name: str) -> Callable:
        # Live handler lookup: the patched spec in BY_NAME wins over the wired default.
        spec = BY_NAME.get(name)
        return spec.handler if spec is not None else handlers[name]

    binds: dict[str, Callable[["DispatchContext"], Any]] = {
        # plain location-taking arms (catch-all #4): handler(result)
        "weather": lambda ctx: _h("weather")(ctx.result),
        "alerts": lambda ctx: _h("alerts")(ctx.result),
        "sun": lambda ctx: _h("sun")(ctx.result),
        "wind": lambda ctx: _h("wind")(ctx.result),
        # next-cloudy arm: handler(result, config.cloud_threshold) — live per-tap
        "next-cloudy": lambda ctx: _h("next-cloudy")(
            ctx.result, ctx.config.cloud_threshold
        ),
        # uv arm: handler(result, config.uv.threshold) — live per-tap
        "uv": lambda ctx: _h("uv")(ctx.result, ctx.config.uv.threshold),
        # forecast arms: handler(result, flags)
        "weekday-forecast": lambda ctx: _h("weekday-forecast")(ctx.result, ctx.flags),
        "weekend-forecast": lambda ctx: _h("weekend-forecast")(ctx.result, ctx.flags),
        # argless arms: help() / locations(config) / status(daemon_state)
        "help": lambda ctx: _h("help")(),
        "locations": lambda ctx: _h("locations")(ctx.config),
        "status": lambda ctx: _h("status")(ctx.daemon_state),
    }
    return tuple(
        replace(spec, handler=handlers[spec.name], bind=binds[spec.name])
        for spec in specs
    )


# Build the singleton via the generic module mechanism (D-02/D-03): the app passes its
# handler+bind-wired specs in; the module computes the three frozen views once. The app
# re-exports them byte-for-byte under the EXACT names every consumer + the oracle read.
_registry = build_registry(_wire_handlers(_SPECS))

# The immutable, handler-wired source-of-truth command list every surface derives from.
COMMANDS: tuple[CommandSpec, ...] = _registry.commands

# name -> spec index (every name is unique; one entry per spec).
BY_NAME: dict[str, CommandSpec] = _registry.by_name

# Longest-keyword-first ordering for the parser so a longer command (e.g.
# "next-cloudy") is matched before any shorter command that prefixes it (Pitfall 4).
COMMANDS_BY_KEYWORD_LEN_DESC: tuple[CommandSpec, ...] = _registry.by_keyword_len_desc


def render_help(commands: tuple[CommandSpec, ...] = COMMANDS) -> str:
    """Render surface-agnostic plain-text help, grouped by ``.group`` (D-04, CMD-09).

    A thin re-export of the module registry's ``render_help`` preserving today's
    default-arg public signature EXACTLY (D-03): with no argument it renders the app's
    :data:`COMMANDS`; passed an explicit spec list it renders that list (the
    parameterized form the oracle drives at ``tests/test_registry.py:160`` with a
    throwaway extra spec). Both forms return the byte-identical string today's
    ``def render_help(commands=COMMANDS)`` returned — the parameterized call does NOT
    raise ``TypeError``. Production callers use the default.

    Groups appear in order of first appearance in ``commands``; each command emits a
    ``  {name} — {summary}`` line under its group header (the EM DASH + two-space indent
    are golden-sensitive — owned now by the module ``render_help``).
    """
    return _registry.render_help(commands)
