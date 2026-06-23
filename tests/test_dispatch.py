"""Shared-dispatcher resolution tests (Phase 16-01, PANEL-10, D-01/D-07).

These tests assert the SINGLE arg-adaptation ladder in
:func:`weatherbot.interactive.dispatch.dispatch_reply` binds each command shape to
the right handler-call signature — the one place both surfaces (bot + CLI) now
resolve through, so the registry command set can never drift across surfaces.

The dispatcher is exercised with fake ``CommandSpec``-like objects and fake
handlers returning a sentinel :class:`CommandReply`, so the tests prove the
BINDING (who-gets-what args) without coupling to real handler bodies. They also
prove the read-only discipline: ``dispatch_reply`` performs NO fetch and NO render
— it only invokes the handler and returns its reply unchanged (D-05).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from weatherbot.interactive.commands import CommandReply
from weatherbot.interactive.dispatch import dispatch_reply


@dataclass
class _FakeSpec:
    """A CommandSpec-shaped stand-in (only the fields the ladder reads)."""

    name: str
    group: str
    takes_location: bool
    handler: Callable


class _UV:
    threshold = 7


class _FakeConfig:
    cloud_threshold = 42
    uv = _UV()


_SENTINEL = CommandReply(title="sentinel", lines=(("k", "v"),), text="body")


def _recording_handler(calls: list) -> Callable:
    def handler(*args, **kwargs):
        calls.append((args, kwargs))
        return _SENTINEL

    return handler


def test_forecast_spec_calls_handler_with_result_and_flags() -> None:
    calls: list = []
    spec = _FakeSpec(
        name="weekday-forecast",
        group="Forecast",
        takes_location=True,
        handler=_recording_handler(calls),
    )
    flags = object()
    result = object()
    reply = dispatch_reply(
        spec,
        result=result,
        config=_FakeConfig(),
        flags=flags,
        daemon_state=None,
    )
    assert reply is _SENTINEL
    assert calls == [((result, flags), {})]


def test_next_cloudy_calls_handler_with_result_and_cloud_threshold() -> None:
    calls: list = []
    spec = _FakeSpec(
        name="next-cloudy",
        group="Weather",
        takes_location=True,
        handler=_recording_handler(calls),
    )
    result = object()
    config = _FakeConfig()
    reply = dispatch_reply(
        spec, result=result, config=config, flags=None, daemon_state=None
    )
    assert reply is _SENTINEL
    assert calls == [((result, config.cloud_threshold), {})]


def test_uv_calls_handler_with_result_and_uv_threshold() -> None:
    calls: list = []
    spec = _FakeSpec(
        name="uv",
        group="Weather",
        takes_location=True,
        handler=_recording_handler(calls),
    )
    result = object()
    config = _FakeConfig()
    reply = dispatch_reply(
        spec, result=result, config=config, flags=None, daemon_state=None
    )
    assert reply is _SENTINEL
    assert calls == [((result, config.uv.threshold), {})]


def test_plain_location_spec_calls_handler_with_result_only() -> None:
    calls: list = []
    spec = _FakeSpec(
        name="weather",
        group="Weather",
        takes_location=True,
        handler=_recording_handler(calls),
    )
    result = object()
    reply = dispatch_reply(
        spec, result=result, config=_FakeConfig(), flags=None, daemon_state=None
    )
    assert reply is _SENTINEL
    assert calls == [((result,), {})]


def test_status_calls_handler_with_daemon_state() -> None:
    calls: list = []
    spec = _FakeSpec(
        name="status",
        group="Info",
        takes_location=False,
        handler=_recording_handler(calls),
    )
    daemon_state = object()
    reply = dispatch_reply(
        spec,
        result=None,
        config=_FakeConfig(),
        flags=None,
        daemon_state=daemon_state,
    )
    assert reply is _SENTINEL
    assert calls == [((daemon_state,), {})]


def test_locations_calls_handler_with_config() -> None:
    calls: list = []
    spec = _FakeSpec(
        name="locations",
        group="Info",
        takes_location=False,
        handler=_recording_handler(calls),
    )
    config = _FakeConfig()
    reply = dispatch_reply(
        spec, result=None, config=config, flags=None, daemon_state=None
    )
    assert reply is _SENTINEL
    assert calls == [((config,), {})]


def test_help_calls_handler_with_no_args() -> None:
    calls: list = []
    spec = _FakeSpec(
        name="help",
        group="Info",
        takes_location=False,
        handler=_recording_handler(calls),
    )
    reply = dispatch_reply(
        spec, result=None, config=_FakeConfig(), flags=None, daemon_state=None
    )
    assert reply is _SENTINEL
    assert calls == [((), {})]


def test_dispatch_reply_does_no_fetch_or_render() -> None:
    """The ladder only invokes the handler and returns its reply unchanged (D-05).

    A handler returning a sentinel CommandReply must come back byte-identical — no
    rendering, no re-wrapping, no fetch interposed.
    """
    spec = _FakeSpec(
        name="weather",
        group="Weather",
        takes_location=True,
        handler=lambda result: _SENTINEL,
    )
    reply = dispatch_reply(
        spec, result=object(), config=_FakeConfig(), flags=None, daemon_state=None
    )
    assert reply is _SENTINEL
