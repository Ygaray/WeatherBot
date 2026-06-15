"""Input-matrix tests for the pure, surface-agnostic ``weather <loc>`` parser.

``parse_weather_command`` classifies raw command text into one of three states
(``NOT_A_COMMAND`` / ``DEFAULT`` / ``LOCATED``) and extracts the raw location
substring. It is config-free and I/O-free (parse-don't-validate, D-01): no
``weatherbot.config`` import appears here, and there is no fixture — the only
input is a plain string. The keyword is matched case-insensitively (D-04) but the
extracted location keeps its RAW case, and a word-boundary guard (Open Question 2 /
Pitfall 2) keeps "weatherman"/"weather:" from being treated as commands.
"""

from __future__ import annotations

from weatherbot.interactive.command import Command, CommandKind, parse_weather_command


def test_bare_keyword_is_default() -> None:
    result = parse_weather_command("weather")
    assert result.kind is CommandKind.DEFAULT
    assert result.location is None


def test_single_word_location_is_located() -> None:
    result = parse_weather_command("weather home")
    assert result.kind is CommandKind.LOCATED
    assert result.location == "home"


def test_multi_word_location_not_truncated() -> None:
    result = parse_weather_command("weather New York")
    assert result.kind is CommandKind.LOCATED
    assert result.location == "New York"


def test_inner_and_outer_whitespace_trimmed() -> None:
    result = parse_weather_command("weather   home  ")
    assert result.kind is CommandKind.LOCATED
    assert result.location == "home"


def test_keyword_case_insensitive_location_case_preserved() -> None:
    # Keyword matched case-insensitively (D-04); extracted location keeps RAW case.
    result = parse_weather_command("Weather HOME")
    assert result.kind is CommandKind.LOCATED
    assert result.location == "HOME"
    assert result.location != "home"


def test_uppercase_bare_keyword_is_default() -> None:
    result = parse_weather_command("WEATHER")
    assert result.kind is CommandKind.DEFAULT
    assert result.location is None


def test_non_command_word_is_not_a_command() -> None:
    result = parse_weather_command("hello")
    assert result.kind is CommandKind.NOT_A_COMMAND
    assert result.location is None


def test_empty_string_is_not_a_command() -> None:
    result = parse_weather_command("")
    assert result.kind is CommandKind.NOT_A_COMMAND


def test_whitespace_only_is_not_a_command() -> None:
    result = parse_weather_command("  ")
    assert result.kind is CommandKind.NOT_A_COMMAND


def test_weatherman_is_not_a_command() -> None:
    # Word-boundary guard (Open Question 2 / Pitfall 2): no whitespace after the
    # keyword means it is not the "weather" command.
    result = parse_weather_command("weatherman")
    assert result.kind is CommandKind.NOT_A_COMMAND


def test_briefing_shaped_string_is_not_a_command() -> None:
    # "weather:" (briefing-shaped) is guarded so the P11 bot cannot loop on its
    # own briefing text (T-06-02).
    result = parse_weather_command("weather: 72\N{DEGREE SIGN}F today")
    assert result.kind is CommandKind.NOT_A_COMMAND


def test_returns_command_dataclass() -> None:
    assert isinstance(parse_weather_command("weather"), Command)
