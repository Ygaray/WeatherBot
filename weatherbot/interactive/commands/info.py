"""Read-only info handlers: help / locations (Plan 12-02, CMD-09 render / CMD-11).

``help_cmd`` returns the registry-rendered help content — it delegates to
:func:`weatherbot.interactive.registry.render_help` so the grouping lives in ONE
place; adding a command to ``COMMANDS`` changes help with no edit here (CMD-09
anti-drift). ``locations`` lists the configured location names straight off the
``Config`` — NO fetch, NO ``ForecastCache``, NO network, NO store (CMD-11).

Both handlers are store-free and fetch-free (D-06 / SC#5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from weatherbot.interactive import registry
from weatherbot.interactive.commands import CommandReply

if TYPE_CHECKING:
    from weatherbot.config.models import Config


def help_cmd() -> CommandReply:
    """All available commands, grouped by area (CMD-09 / D-04).

    Delegates to :func:`registry.render_help` — the registry owns the grouping, so
    this never duplicates it and can never drift. The same rendered block is shown
    on Discord (embed body) and the CLI (plain text).
    """
    return CommandReply(title="Commands", text=registry.render_help())


def locations(config: Config) -> CommandReply:
    """List the configured location names (CMD-11).

    Reads ``config.locations`` only — no fetch, no cache, no store. The first
    configured location is the default for bare location-taking commands (D-01),
    so it is listed first as it already is in config order.
    """
    lines = tuple((loc.name, loc.timezone) for loc in config.locations)
    if not lines:
        return CommandReply(title="Locations", text="No locations configured.")
    return CommandReply(title="Locations", lines=lines)
