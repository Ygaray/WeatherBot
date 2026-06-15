"""Smoke tests for the ``weatherbot.interactive`` package barrel (Phase 06-03).

Guards three invariants the two shared surfaces (P7 CLI, P11 Discord bot) depend
on: (1) all six public symbols import from the single barrel, (2) the D-07
``UnknownLocationError`` is-a ``ValueError`` contract holds at the package surface,
and (3) the D-08 cli<->interactive edge has NO import cycle — ``weatherbot.cli``
and ``weatherbot.interactive`` both import in one process (Pitfall 3). Plain
asserts, no fixtures.
"""

from __future__ import annotations


def test_barrel_exports_all_six_public_symbols():
    from weatherbot.interactive import (
        Command,
        CommandKind,
        LookupResult,
        UnknownLocationError,
        lookup_weather,
        parse_weather_command,
    )

    for symbol in (
        Command,
        CommandKind,
        LookupResult,
        UnknownLocationError,
        lookup_weather,
        parse_weather_command,
    ):
        assert symbol is not None


def test_unknown_location_error_is_a_value_error():
    from weatherbot.interactive import UnknownLocationError

    assert issubclass(UnknownLocationError, ValueError)


def test_no_import_cycle_between_cli_and_interactive():
    import weatherbot.cli
    import weatherbot.interactive

    assert callable(weatherbot.cli.send_now)
    assert callable(weatherbot.interactive.lookup_weather)
