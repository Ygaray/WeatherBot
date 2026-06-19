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
    # next-cloudy is the longest name → must sort ahead of every shorter command.
    assert COMMANDS_BY_KEYWORD_LEN_DESC[0].name == "next-cloudy"


def test_handlers_are_placeholders_this_plan() -> None:
    # Plans 02/03 wire the real callables; in this plan every handler is None.
    assert all(c.handler is None for c in COMMANDS)


def test_groups_are_weather_and_info() -> None:
    groups = {c.group for c in COMMANDS}
    assert groups == {"Weather", "Info"}
    weather = {c.name for c in COMMANDS if c.group == "Weather"}
    info = {c.name for c in COMMANDS if c.group == "Info"}
    assert weather == {"alerts", "sun", "wind", "next-cloudy"}
    assert info == {"help", "locations", "status"}


def test_location_taking_flags() -> None:
    by_name = {c.name: c for c in COMMANDS}
    for name in ("alerts", "sun", "wind", "next-cloudy"):
        assert by_name[name].takes_location is True
    for name in ("help", "locations", "status"):
        assert by_name[name].takes_location is False


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
