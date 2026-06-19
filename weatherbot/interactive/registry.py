"""The single self-describing command registry (CMD-09, D-04).

This module is the ONE source of truth for the read-only command surface. The
Discord dispatch, the CLI subparser builder, and ``help`` all derive from the same
:data:`COMMANDS` tuple, so adding a command here makes it appear in every surface
with no other edit — the "derive-from-one-list" invariant that keeps ``help`` from
ever drifting (CMD-09 / D-04).

Each command is a frozen :class:`CommandSpec` (name, group, summary, takes-location
flag, optional handler). Plan 03 wires the real callables onto each spec (Plan 01
left them ``None``). The handler imports are LAZY (inside :func:`_wire_handlers`,
called once at import time) so the import direction stays acyclic: ``command.py``
imports this module for the parser, and the handler modules import ``lookup``/
``models`` — keeping handler imports out of the module-top graph mirrors the
``lookup.py``/``daemon.py`` lazy-import precedents (Pitfall 5 / import-cycle guard).

``render_help`` is surface-agnostic plain text (grouped by ``.group``); the Discord
embed and the CLI both render the same content (D-04).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable


@dataclass(frozen=True)
class CommandSpec:
    """One command in the registry — the immutable spec every surface reads.

    ``name`` is the keyword the parser matches (D-01 short names). ``group`` is the
    help section header (D-04: Weather / Info). ``summary`` is the one-line help
    description. ``takes_location`` marks the location-taking commands (None arg →
    default location downstream, D-01). ``handler`` is wired in Plans 02/03 and is
    ``None`` in this plan (no handler imports here).
    """

    name: str
    group: str
    summary: str
    takes_location: bool
    handler: Callable | None = None


# The immutable source-of-truth command list (D-04 grouping; D-01 short names).
# Specs start handler-less; :func:`_wire_handlers` (run once below) replaces each with
# the same spec carrying its real handler (Plan 03). Keeping the literal list
# handler-free keeps this declaration import-cycle-free; the wiring imports the
# handler modules lazily.
_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("alerts", "Weather", "Active weather alerts for a location.", True),
    CommandSpec("sun", "Weather", "Sunrise and sunset times for a location.", True),
    CommandSpec("wind", "Weather", "Current wind speed and direction.", True),
    CommandSpec(
        "next-cloudy",
        "Weather",
        "The next cloudy day in the forecast window.",
        True,
    ),
    CommandSpec("help", "Info", "List all available commands.", False),
    CommandSpec("locations", "Info", "List the configured locations.", False),
    CommandSpec("status", "Info", "Daemon liveness and next scheduled sends.", False),
)


def _wire_handlers(specs: tuple[CommandSpec, ...]) -> tuple[CommandSpec, ...]:
    """Return ``specs`` with each command's real handler wired on (Plan 03, CMD-09..16).

    Imports the handler modules LAZILY (here, not at module top) so the registry
    stays importable by ``command.py`` without dragging the handler modules' deeper
    imports (``lookup``/``models``) into the module-top graph — the acyclic-import
    discipline (Pitfall 5). The handlers have heterogeneous signatures (location-
    taking handlers take a ``LookupResult`` (+ ``threshold`` for ``next-cloudy``);
    ``help`` takes none, ``locations`` a ``Config``, ``status`` a ``DaemonState``);
    each surface's dispatch (``bot.py`` / ``cli.py``) adapts the call — the registry
    only carries the raw callable.
    """
    from weatherbot.interactive.commands import info, status, weather_views

    handlers: dict[str, Callable] = {
        "alerts": weather_views.alerts,
        "sun": weather_views.sun,
        "wind": weather_views.wind,
        "next-cloudy": weather_views.next_cloudy,
        "help": info.help_cmd,
        "locations": info.locations,
        "status": status.status,
    }
    return tuple(replace(spec, handler=handlers[spec.name]) for spec in specs)


# The immutable, handler-wired source-of-truth command list every surface derives from.
COMMANDS: tuple[CommandSpec, ...] = _wire_handlers(_SPECS)

# name -> spec index (every name is unique; one entry per spec).
BY_NAME: dict[str, CommandSpec] = {c.name: c for c in COMMANDS}

# Longest-keyword-first ordering for the parser so a longer command (e.g.
# "next-cloudy") is matched before any shorter command that prefixes it (Pitfall 4).
COMMANDS_BY_KEYWORD_LEN_DESC: tuple[CommandSpec, ...] = tuple(
    sorted(COMMANDS, key=lambda c: len(c.name), reverse=True)
)


def render_help(commands: tuple[CommandSpec, ...] = COMMANDS) -> str:
    """Render surface-agnostic plain-text help, grouped by ``.group`` (D-04, CMD-09).

    Groups appear in order of first appearance in ``commands``; each command emits a
    ``  {name} — {summary}`` line under its group header. Adding a :class:`CommandSpec`
    to :data:`COMMANDS` makes it appear here with no other edit (the derive-from-one-
    list invariant). ``commands`` is a parameter only so tests can prove that
    invariant against a throwaway list; production callers use the default.
    """
    groups: list[str] = []
    by_group: dict[str, list[CommandSpec]] = {}
    for spec in commands:
        if spec.group not in by_group:
            by_group[spec.group] = []
            groups.append(spec.group)
        by_group[spec.group].append(spec)

    lines: list[str] = []
    for group in groups:
        lines.append(group)
        for spec in by_group[group]:
            lines.append(f"  {spec.name} \N{EM DASH} {spec.summary}")
    return "\n".join(lines)
