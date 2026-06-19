"""Read-only command handlers + the surface-agnostic reply type (Plan 12-02).

This package holds the seven read-only command handlers wired into the registry
in Plan 03 (``weather_views`` — alerts/sun/wind/next-cloudy; ``info`` —
help/locations; ``status`` — daemon liveness). Every handler is READ-ONLY
(D-06 / SC#5): it imports nothing from ``weatherbot.weather.store``, takes no
``db_path`` for writing, and writes none of the store functions — proven by the
zero-store-writes spy test.

:class:`CommandReply` is the D-04 "same content both surfaces" seam: a frozen,
immutable reply every handler returns. Plan 03 renders it as a ``discord.Embed``
(Discord) and as plain text (CLI) — the two surfaces share ONE content shape so
they can never drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CommandReply:
    """A surface-agnostic command reply (D-04 — same content on every surface).

    ``title`` is the heading (the Discord embed title / the CLI's first line).
    ``lines`` is an ordered list of ``(name, value)`` field pairs (rendered as
    embed fields on Discord, ``name: value`` lines on the CLI). ``text`` is an
    optional free-form body (used by ``help`` whose content is already a rendered
    block, and as a fallback message line for simple replies). All three are
    immutable so a reply can never be mutated by a downstream renderer.
    """

    title: str
    lines: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    text: str | None = None
