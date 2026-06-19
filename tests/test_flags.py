"""Tests for the shared +day/-day/+compact forecast flag grammar (FCAST-03/04).

``parse_forecast_flags`` is the single surface-agnostic parser both the CLI and
the Discord bot feed raw forecast argument text into. These tests pin the
grammar (variant selection, additive/subtractive day sets, location substring)
and the T-13-07 security/fail-loud contract (unknown day token raises naming the
allowed tokens; only string ops, never str.format/eval/exec/shell).
"""

from __future__ import annotations

import pytest

from weatherbot.interactive.command import ForecastFlags, parse_forecast_flags
from weatherbot.scheduler.days import _DAYS


# --- variant selection (FCAST-03) -----------------------------------------


def test_plus_compact_selects_compact_variant():
    flags = parse_forecast_flags("home +compact")
    assert flags.variant == "compact"
    assert flags.add == frozenset()
    assert flags.drop == frozenset()
    assert flags.location == "home"


def test_dash_dash_compact_selects_compact_variant():
    # --compact (CLI spelling) and +compact (Discord spelling) are equivalent.
    flags = parse_forecast_flags("home --compact")
    assert flags.variant == "compact"
    assert flags.location == "home"


def test_default_variant_is_detailed():
    flags = parse_forecast_flags("home")
    assert flags.variant == "detailed"
    assert flags.location == "home"


def test_plus_detailed_and_dash_detailed_select_detailed():
    assert parse_forecast_flags("home +detailed").variant == "detailed"
    assert parse_forecast_flags("home --detailed").variant == "detailed"


# --- additive / subtractive day sets (FCAST-04) ---------------------------


def test_add_days_collected_into_add_set():
    flags = parse_forecast_flags("home +sat +sun")
    assert flags.add == frozenset({"sat", "sun"})
    assert flags.variant == "detailed"
    assert flags.drop == frozenset()


def test_drop_day_collected_into_drop_set():
    flags = parse_forecast_flags("home -mon")
    assert flags.drop == frozenset({"mon"})
    assert flags.add == frozenset()


def test_mixed_add_and_drop():
    flags = parse_forecast_flags("home -mon +sat")
    assert flags.drop == frozenset({"mon"})
    assert flags.add == frozenset({"sat"})


# --- None / empty input ---------------------------------------------------


def test_none_arg_returns_defaults():
    flags = parse_forecast_flags(None)
    assert flags == ForecastFlags(
        variant="detailed", add=frozenset(), drop=frozenset(), location=None
    )


def test_empty_string_returns_defaults():
    flags = parse_forecast_flags("   ")
    assert flags.variant == "detailed"
    assert flags.add == frozenset()
    assert flags.drop == frozenset()
    assert flags.location is None


# --- fail-loud unknown token (T-13-07, A4 abbreviations-only) --------------


def test_unknown_add_token_raises_naming_allowed_tokens():
    with pytest.raises(ValueError) as exc:
        parse_forecast_flags("home +xyz")
    msg = str(exc.value)
    # Names the allowed day tokens (sorted) so the user can self-correct.
    for token in sorted(_DAYS):
        assert token in msg


def test_unknown_drop_token_raises():
    with pytest.raises(ValueError):
        parse_forecast_flags("home -funday")


def test_preset_is_not_a_valid_flag_token():
    # A4: only the mon..sun abbreviations are flag tokens; presets like
    # "weekends" are NOT valid +day/-day tokens.
    with pytest.raises(ValueError):
        parse_forecast_flags("home +weekends")


# --- case-insensitivity + raw-case location (mirror parse_command) --------


def test_tokens_case_insensitive_location_keeps_raw_case():
    flags = parse_forecast_flags("New York +SAT --COMPACT")
    assert flags.variant == "compact"
    assert flags.add == frozenset({"sat"})
    # The location substring keeps its raw case.
    assert flags.location == "New York"


def test_location_only_no_flags():
    flags = parse_forecast_flags("San Diego")
    assert flags.location == "San Diego"
    assert flags.variant == "detailed"


# --- frozen result --------------------------------------------------------


def test_result_is_frozen():
    flags = parse_forecast_flags("home +sat")
    with pytest.raises(Exception):
        flags.variant = "compact"  # type: ignore[misc]
