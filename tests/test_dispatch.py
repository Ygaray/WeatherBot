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

import asyncio
from dataclasses import dataclass
from typing import Callable

import pytest

from weatherbot.interactive.command import ForecastFlags
from weatherbot.interactive.commands import CommandReply
from weatherbot.interactive.dispatch import dispatch_reply, dispatch_spec
from weatherbot.interactive.lookup import UnknownLocationError


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


# ---------------------------------------------------------------------------
# dispatch_spec — the async off-loop-fetch wrapper (WR-01).
#
# dispatch_reply (above) is the sync ladder; dispatch_spec owns the three
# responsibilities lifted out of on_message that the ladder tests do NOT touch:
#   1. the forecast-flags parse + cache-key ``suffix`` widening (A5 collision guard),
#   2. the 2-arg (plain weather) vs 3-arg (forecast) ``cache.lookup`` dispatch,
#   3. letting ``UnknownLocationError`` BUBBLE (D-06).
# These drive a spy cache through a real event loop and assert the exact lookup
# call shape, so a regression in the drift-prone wrapper is caught at the unit
# level rather than only transitively via test_bot.py.
# ---------------------------------------------------------------------------


class _SpyCache:
    """Records every ``lookup`` call; ``rest`` captures the optional suffix arg."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list = []
        self._raises = raises

    def lookup(self, name, config, *rest):
        self.calls.append((name, config, rest))
        if self._raises is not None:
            raise self._raises
        return object()


def test_dispatch_spec_forecast_widens_cache_key_with_3arg_lookup() -> None:
    """Forecast → flags.location as the lookup name + a non-None suffix (3-arg)."""
    cache = _SpyCache()
    calls: list = []
    spec = _FakeSpec(
        name="weekday-forecast",
        group="Forecast",
        takes_location=True,
        handler=_recording_handler(calls),
    )
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(
            dispatch_spec(
                spec,
                "home +sat",
                cache=cache,
                config=_FakeConfig(),
                loop=loop,
                daemon_state=None,
            )
        )
    finally:
        loop.close()
    assert reply is _SENTINEL
    # One 3-arg lookup: location parsed out of the arg, suffix present (A5).
    (name, _config, rest), = cache.calls
    assert name == "home"
    assert len(rest) == 1 and rest[0] is not None
    # The fetched result + parsed flags are threaded into the handler.
    (handler_args, _kwargs), = calls
    fetched_result, flags = handler_args
    assert fetched_result is not None
    assert flags is not None and flags.location == "home"


def test_dispatch_spec_plain_weather_uses_2arg_lookup() -> None:
    """Plain weather → raw arg as the lookup name + the back-compat 2-arg form."""
    cache = _SpyCache()
    calls: list = []
    spec = _FakeSpec(
        name="weather",
        group="Weather",
        takes_location=True,
        handler=_recording_handler(calls),
    )
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(
            dispatch_spec(
                spec,
                "home",
                cache=cache,
                config=_FakeConfig(),
                loop=loop,
                daemon_state=None,
            )
        )
    finally:
        loop.close()
    assert reply is _SENTINEL
    (name, _config, rest), = cache.calls
    assert name == "home"
    assert rest == ()  # 2-arg form — no suffix for a plain weather lookup


def test_dispatch_spec_unknown_location_bubbles() -> None:
    """``UnknownLocationError`` from the fetch is NOT caught here — it bubbles (D-06)."""
    cache = _SpyCache(raises=UnknownLocationError("nope", ["home"]))
    spec = _FakeSpec(
        name="weather",
        group="Weather",
        takes_location=True,
        handler=lambda result: _SENTINEL,
    )
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(UnknownLocationError):
            loop.run_until_complete(
                dispatch_spec(
                    spec,
                    "nope",
                    cache=cache,
                    config=_FakeConfig(),
                    loop=loop,
                    daemon_state=None,
                )
            )
    finally:
        loop.close()


def test_dispatch_spec_flags_passthrough_skips_parse() -> None:
    """Caller-provided ``flags`` SKIPS ``parse_forecast_flags`` (D-01).

    A pre-built ``ForecastFlags`` drives the lookup name (``flags.location``) and
    the cache suffix directly; the ``arg`` string is deliberately different from the
    flags' location, so a recorded lookup of ``"travel"`` (not ``"ignored-arg"``)
    proves the parse was bypassed. The same flags object is threaded to the handler.
    """
    cache = _SpyCache()
    calls: list = []
    spec = _FakeSpec(
        name="weekday-forecast",
        group="Forecast",
        takes_location=True,
        handler=_recording_handler(calls),
    )
    flags = ForecastFlags(variant="compact", location="travel")
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(
            dispatch_spec(
                spec,
                "ignored-arg",
                cache=cache,
                config=_FakeConfig(),
                loop=loop,
                daemon_state=None,
                flags=flags,
            )
        )
    finally:
        loop.close()
    assert reply is _SENTINEL
    # Lookup name comes from flags.location, NOT the arg (parse skipped).
    (name, _config, rest), = cache.calls
    assert name == "travel"
    assert len(rest) == 1 and rest[0] is not None  # 3-arg suffix form, still applied
    # The SAME pre-built flags object reaches the handler (not a re-parsed one).
    (handler_args, _kwargs), = calls
    fetched_result, handler_flags = handler_args
    assert fetched_result is not None
    assert handler_flags is flags
    assert handler_flags.variant == "compact"
    assert handler_flags.location == "travel"
    assert handler_flags.add == frozenset()
    assert handler_flags.drop == frozenset()


def test_dispatch_spec_flags_none_is_byte_identical() -> None:
    """Explicit ``flags=None`` is byte-identical to omitting the kwarg (D-02).

    Drives the SAME arg through ``dispatch_spec(..., flags=None)`` and the existing
    no-``flags``-kwarg call; the recorded lookup name, the 3-arg suffix, and the
    handler args (result + parsed flags) must match — proving the additive seam is
    behavior-preserving on the every-existing-caller path.
    """
    arg = "home +sat"

    def _drive(**extra) -> tuple:
        cache = _SpyCache()
        calls: list = []
        spec = _FakeSpec(
            name="weekday-forecast",
            group="Forecast",
            takes_location=True,
            handler=_recording_handler(calls),
        )
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                dispatch_spec(
                    spec,
                    arg,
                    cache=cache,
                    config=_FakeConfig(),
                    loop=loop,
                    daemon_state=None,
                    **extra,
                )
            )
        finally:
            loop.close()
        (name, _config, rest), = cache.calls
        (handler_args, _kwargs), = calls
        _result, handler_flags = handler_args
        return name, rest, handler_flags

    name_none, rest_none, flags_none = _drive(flags=None)
    name_omitted, rest_omitted, flags_omitted = _drive()

    assert name_none == name_omitted == "home"
    # The 3-arg suffix is present and identical on both paths.
    assert len(rest_none) == 1 and rest_none[0] is not None
    assert rest_none == rest_omitted
    # Both paths parse the arg into an equal ForecastFlags handed to the handler.
    assert flags_none == flags_omitted
    assert flags_none.location == "home"


def test_dispatch_spec_argless_spec_never_fetches() -> None:
    """A non-``takes_location`` spec (help) must never touch the cache."""
    cache = _SpyCache()
    calls: list = []
    spec = _FakeSpec(
        name="help",
        group="Info",
        takes_location=False,
        handler=_recording_handler(calls),
    )
    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(
            dispatch_spec(
                spec,
                None,
                cache=cache,
                config=_FakeConfig(),
                loop=loop,
                daemon_state=None,
            )
        )
    finally:
        loop.close()
    assert reply is _SENTINEL
    assert cache.calls == []  # no fetch for an argless command
    assert calls == [((), {})]  # help handler invoked with no args
