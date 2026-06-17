"""Shared read-only lookup core + command parser for the CLI (P7) and Discord bot (P11)."""

from .bot import BotThread, build_client
from .cache import ForecastCache
from .command import Command, CommandKind, parse_weather_command
from .lookup import LookupResult, UnknownLocationError, lookup_weather

__all__ = [
    "BotThread",
    "Command",
    "CommandKind",
    "ForecastCache",
    "LookupResult",
    "UnknownLocationError",
    "build_client",
    "lookup_weather",
    "parse_weather_command",
]
