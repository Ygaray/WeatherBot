"""Shared read-only lookup core + command parser/registry for the CLI (P7) and Discord bot (P11)."""

from .bot import BotThread, build_client, render_embed
from .cache import ForecastCache
from .command import (
    Command,
    CommandKind,
    ParsedCommand,
    parse_command,
    parse_weather_command,
)
from .lookup import LookupResult, UnknownLocationError, lookup_weather
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
    "LookupResult",
    "ParsedCommand",
    "UnknownLocationError",
    "build_client",
    "lookup_weather",
    "parse_command",
    "parse_weather_command",
    "render_embed",
    "render_help",
]
