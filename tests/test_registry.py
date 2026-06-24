"""Tests for the single self-describing command registry (CMD-09, D-04).

The registry is the ONE source of truth for the read-only command surface. These
tests assert the immutable-spec shape, the derived indexes (BY_NAME, longest-first),
and — crucially — the derive-from-one-list invariant: a command added to the source
list appears in ``render_help`` with no other edit (CMD-09). Pure and I/O-free: no
fixture, no network, no config import.
"""

from __future__ import annotations

from weatherbot.interactive.registry import (
    BY_NAME,
    COMMANDS,
    COMMANDS_BY_KEYWORD_LEN_DESC,
    CommandSpec,
    render_help,
)


def test_commands_is_immutable_tuple() -> None:
    assert isinstance(COMMANDS, tuple)
    assert all(isinstance(c, CommandSpec) for c in COMMANDS)


def test_command_spec_is_frozen() -> None:
    spec = COMMANDS[0]
    import dataclasses

    try:
        spec.name = "mutated"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover - guards against a non-frozen regression
        raise AssertionError("CommandSpec must be frozen")


def test_every_command_name_is_unique() -> None:
    names = [c.name for c in COMMANDS]
    assert len(names) == len(set(names))


def test_by_name_has_one_entry_per_spec() -> None:
    assert len(BY_NAME) == len(COMMANDS)
    for spec in COMMANDS:
        assert BY_NAME[spec.name] is spec


def test_longest_keyword_first_ordering() -> None:
    lengths = [len(c.name) for c in COMMANDS_BY_KEYWORD_LEN_DESC]
    assert lengths == sorted(lengths, reverse=True)
    # The forecast commands ("weekday-forecast"/"weekend-forecast", 16 chars) are the
    # longest names → one must sort ahead of every shorter command (so the parser
    # matches the full forecast keyword before any prefix, Pitfall 4).
    assert COMMANDS_BY_KEYWORD_LEN_DESC[0].name in (
        "weekday-forecast",
        "weekend-forecast",
    )


def test_handlers_are_wired() -> None:
    # Plan 03 wires the real callables onto every spec (the Plan 01 None placeholders
    # are now filled in by registry._wire_handlers — CMD-09..16). Both surfaces
    # (CLI + Discord) derive their dispatch from these.
    assert all(callable(c.handler) for c in COMMANDS)


def test_groups_are_weather_info_and_forecast() -> None:
    groups = {c.group for c in COMMANDS}
    assert groups == {"Weather", "Info", "Forecast"}
    weather = {c.name for c in COMMANDS if c.group == "Weather"}
    info = {c.name for c in COMMANDS if c.group == "Info"}
    forecast = {c.name for c in COMMANDS if c.group == "Forecast"}
    assert weather == {"weather", "alerts", "sun", "wind", "next-cloudy", "uv"}
    assert info == {"help", "locations", "status"}
    assert forecast == {"weekday-forecast", "weekend-forecast"}


def test_location_taking_flags() -> None:
    by_name = {c.name: c for c in COMMANDS}
    for name in ("alerts", "sun", "wind", "next-cloudy", "uv"):
        assert by_name[name].takes_location is True
    for name in ("help", "locations", "status"):
        assert by_name[name].takes_location is False
    # Forecast commands take a location too (D-01 default when omitted).
    for name in ("weekday-forecast", "weekend-forecast"):
        assert by_name[name].takes_location is True


def test_forecast_commands_wired() -> None:
    """The forecast specs are registered and wired to the real handlers (Task 2)."""
    from weatherbot.interactive.commands import forecast as forecast_cmd

    assert BY_NAME["weekday-forecast"].handler is forecast_cmd.weekday_forecast
    assert BY_NAME["weekend-forecast"].handler is forecast_cmd.weekend_forecast


def test_weather_command_registered_and_wired() -> None:
    """The `weather` spec is in the registry, wired to the real handler, and Weather-grouped.

    W2 (D-07/D-08): `weather` is now a real first-class registry command so the panel
    weather button routes uniformly through `dispatch_spec` → `render_embed` with no
    panel-side special case. Derive-from-one-list (CMD-09): registering the spec makes
    `weather` appear in `COMMANDS`, `BY_NAME`, and `render_help` with no other edit.
    """
    from weatherbot.interactive.commands import weather_views

    assert "weather" in {c.name for c in COMMANDS}
    spec = BY_NAME["weather"]
    assert spec.handler is weather_views.weather
    assert spec.takes_location is True
    assert spec.group == "Weather"


def test_uv_command_registered_and_wired() -> None:
    """The `uv` spec is in the registry, wired to the real handler, and Weather-grouped.

    Derive-from-one-list (CMD-09): registering the spec here makes `uv` appear in
    `COMMANDS`, `BY_NAME`, and `render_help` with no other registry edit.
    """
    from weatherbot.interactive.commands import weather_views

    assert "uv" in {c.name for c in COMMANDS}
    spec = BY_NAME["uv"]
    assert spec.handler is weather_views.uv
    assert spec.takes_location is True
    assert spec.group == "Weather"


def test_help_lists_uv_under_weather() -> None:
    """The `uv` command surfaces in help under the Weather group (CMD-09 parity)."""
    text = render_help()
    assert "uv" in text
    assert BY_NAME["uv"].summary in text


def test_help_lists_forecast_commands() -> None:
    """Derive-from-one-list: both forecast commands appear in help (CMD-09 parity)."""
    text = render_help()
    assert "weekday-forecast" in text
    assert "weekend-forecast" in text
    assert "Forecast" in text  # the group header


def test_render_help_groups_and_lists_every_command() -> None:
    out = render_help()
    # Every command's summary appears (one line per command).
    for spec in COMMANDS:
        assert spec.summary in out
        assert spec.name in out
    # Group headers appear.
    assert "Weather" in out
    assert "Info" in out


def test_render_help_auto_generates_from_one_list() -> None:
    # The derive-from-one-list invariant (CMD-09): adding a CommandSpec to the
    # source list makes it appear in help with no other edit.
    extra = CommandSpec("throwaway", "Info", "A throwaway probe command.", False)
    out = render_help(COMMANDS + (extra,))
    assert "throwaway" in out
    assert "A throwaway probe command." in out
