"""Shared read-only lookup core + command parser for the CLI (P7) and Discord bot (P11)."""

from .command import Command, CommandKind, parse_weather_command
from .lookup import LookupResult, UnknownLocationError, lookup_weather

__all__ = [
    "Command",
    "CommandKind",
    "LookupResult",
    "UnknownLocationError",
    "lookup_weather",
    "parse_weather_command",
]
