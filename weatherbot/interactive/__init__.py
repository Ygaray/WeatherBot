"""Shared read-only lookup core + command parser/registry for the CLI (P7) and Discord bot (P11).

After the Phase-27 adapter relocation (SEAM-07, D-06) the generic gateway plumbing
(``BotThread`` / ``build_client``) lives in :mod:`yahir_reusable_bot.discord`; this barrel
re-exports them from the module so the daemon's
``from weatherbot.interactive import BotThread`` keeps resolving (the Phase-22 re-export-shim
pattern). ``render_embed`` STAYS app-side in :mod:`weatherbot.interactive.bot` (D-01).
"""

from yahir_reusable_bot.discord import BotThread, build_client

from .bot import render_embed
from .cache import ForecastCache
from .command import (
    Command,
    CommandKind,
    ForecastFlags,
    ParsedCommand,
    forecast_cache_suffix,
    parse_command,
    parse_forecast_flags,
    parse_weather_command,
)
from .lookup import (
    LookupResult,
    UnknownLocationError,
    lookup_forecast,
    lookup_weather,
)
from .registry import COMMANDS, CommandSpec, render_help
from .state import DaemonState

__all__ = [
    "BotThread",
    "COMMANDS",
    "Command",
    "CommandKind",
    "CommandSpec",
    "DaemonState",
    "ForecastCache",
    "ForecastFlags",
    "LookupResult",
    "ParsedCommand",
    "UnknownLocationError",
    "build_client",
    "forecast_cache_suffix",
    "lookup_forecast",
    "lookup_weather",
    "parse_command",
    "parse_forecast_flags",
    "parse_weather_command",
    "render_embed",
    "render_help",
]
