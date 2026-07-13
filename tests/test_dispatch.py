"""Shared-dispatcher resolution tests (Phase 16-01, PANEL-10, D-01/D-07; SEAM-06).

These tests assert the SINGLE arg-adaptation binding the app dispatcher resolves —
:func:`weatherbot.interactive.dispatch.dispatch_reply` binds each command shape to the
right handler-call signature, the one place both surfaces (bot + CLI) resolve through,
so the registry command set can never drift across surfaces.

Phase 26 relocated the generic dispatcher into ``yahir_reusable_bot.registry``: the app
``dispatch_reply``/``dispatch_spec`` are now thin shims, and the per-command arg-binding
lives in each spec's opaque ``bind`` closure (D-01) — the module invokes ``spec.bind(ctx)``
and reads the neutral ``spec.needs_flags`` signal instead of ``spec.group == "Forecast"``.
The :class:`_FakeSpec` below therefore carries a ``bind`` closure + a ``needs_flags`` flag
(auto-derived in ``__post_init__`` from the same ``name``/``group`` the old ladder branched
on, so every test call site stays byte-identical) — the behavioral assertions (which args
each command shape receives, the cache-call shape, the bubble) are unchanged. The tests
still prove the read-only discipline: ``dispatch_reply`` performs NO fetch and NO render —
it only invokes the handler and returns its reply unchanged (D-05).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from weatherbot.interactive.command import ForecastFlags
from weatherbot.interactive.commands import CommandReply
from weatherbot.interactive.dispatch import dispatch_reply, dispatch_spec
from weatherbot.interactive.lookup import UnknownLocationError


def _ladder_bind(name: str, group: str, takes_location: bool, handler: Callable):
    """Build the ``bind`` closure for a fake spec — the verbatim old dispatch_reply arm.

    Mirrors the seven-arm ladder the app dispatcher used to inline (now relocated into
    each app ``bind`` closure, D-01): forecast → ``handler(result, flags)``; next-cloudy →
    ``handler(result, config.cloud_threshold)``; uv → ``handler(result, config.uv.threshold)``;
    other location-taking → ``handler(result)``; status → ``handler(daemon_state)``;
    locations → ``handler(config)``; help → ``handler()``. Reads LIVE from ``ctx`` (D-01).
    """
    if takes_location:
        if group == "Forecast":
            return lambda ctx: handler(ctx.result, ctx.flags)
        if name == "next-cloudy":
            return lambda ctx: handler(ctx.result, ctx.config.cloud_threshold)
        if name == "uv":
            return lambda ctx: handler(ctx.result, ctx.config.uv.threshold)
        return lambda ctx: handler(ctx.result)
    if name == "status":
        return lambda ctx: handler(ctx.daemon_state)
    if name == "locations":
        return lambda ctx: handler(ctx.config)
    return lambda ctx: handler()  # help — no fetch, no config


@dataclass
class _FakeSpec:
    """A CommandSpec-shaped stand-in (the fields the relocated dispatcher reads).

    ``bind`` + ``needs_flags`` are auto-derived from ``name``/``group`` in
    ``__post_init__`` so every test constructs a fake exactly as before
    (``_FakeSpec(name=, group=, takes_location=, handler=)``) while the relocated module
    dispatcher (which invokes ``spec.bind(ctx)`` and reads ``spec.needs_flags``) gets what
    it needs — the behavioral assertions are unchanged.
    """

    name: str
    group: str
    takes_location: bool
    handler: Callable
    bind: Callable[[Any], Any] = field(default=None)  # type: ignore[assignment]
    needs_flags: bool = field(default=False)

    def __post_init__(self) -> None:
        if self.bind is None:
            self.bind = _ladder_bind(
                self.name, self.group, self.takes_location, self.handler
            )
        # The neutral pre-dispatch signal the module reads instead of group=="Forecast".
        self.needs_flags = self.group == "Forecast"


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
    ((name, _config, rest),) = cache.calls
    assert name == "home"
    assert len(rest) == 1 and rest[0] is not None
    # The fetched result + parsed flags are threaded into the handler.
    ((handler_args, _kwargs),) = calls
    fetched_result, flags = handler_args
    assert fetched_result is not None
    assert flags is not None and flags.location == "home"


def test_dispatch_spec_text_forecast_parses_flags_and_widens_suffix() -> None:
    """WR-01: the text-command (``flags=None``) forecast path parses the arg itself.

    This pins the drift-prone HALF the audit calls out: with NO ``flags=`` kwarg,
    ``dispatch_spec`` must run ``parse_forecast_flags`` on the raw arg, derive the
    lookup name from the PARSED ``flags.location`` (not the raw arg verbatim), and
    widen the cache key via ``forecast_cache_suffix`` (3-arg ``cache.lookup``). A
    distinct location+token (``"travel +sun"`` ≠ the other tests' ``"home +sat"``)
    proves the name comes from the parse, and the parsed ``ForecastFlags`` reaches
    the handler. Currently this lookup-name + suffix derivation is only covered
    transitively via test_bot.py — this asserts it at the unit level.
    """
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
                "travel +sun",
                cache=cache,
                config=_FakeConfig(),
                loop=loop,
                daemon_state=None,
            )  # NO flags= kwarg → the text parse path runs
        )
    finally:
        loop.close()
    assert reply is _SENTINEL
    # (1) exactly one recorded lookup, in the 3-arg widened form;
    # (2) its name is the location PARSED out of the arg (not "travel +sun");
    # (3) its rest is a 1-tuple with a non-None suffix (the A5 widening).
    ((name, _config, rest),) = cache.calls
    assert name == "travel"
    assert len(rest) == 1 and rest[0] is not None
    # (4) the handler received the fetched result + a parsed ForecastFlags whose
    # .location matches and whose +sun token was parsed (proving a real parse ran).
    ((handler_args, _kwargs),) = calls
    fetched_result, flags = handler_args
    assert fetched_result is not None
    assert flags is not None
    assert flags.location == "travel"
    assert flags.add == frozenset({"sun"})


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
    ((name, _config, rest),) = cache.calls
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
    ((name, _config, rest),) = cache.calls
    assert name == "travel"
    assert len(rest) == 1 and rest[0] is not None  # 3-arg suffix form, still applied
    # The SAME pre-built flags object reaches the handler (not a re-parsed one).
    ((handler_args, _kwargs),) = calls
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
        ((name, _config, rest),) = cache.calls
        ((handler_args, _kwargs),) = calls
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


# ---------------------------------------------------------------------------
# Phase 33 HARD-UI-01 (F02) — bare location commands resolve the default (D-01/D-02).
#
# The app ``dispatch_spec`` shim pre-resolves the default location app-side when
# ``arg is None`` for a location-taking, non-flags spec — so the hub guard
# ``if arg is not None or spec.needs_flags:`` fires and the existing fetch path runs
# with the resolved default NAME (``resolve_location(config, None).name``), matching
# the CLI's ``resolve_location(None)`` behavior on Discord. This is the app-side-only
# fix (D-01): the hub dispatcher stays weather-domain-free. These tests drive the REAL
# app ``dispatch_spec`` (not the _FakeSpec harness) with the real registry specs, a
# real Config, and ``arg=None`` — asserting the fetch runs with the default name for
# all six ``takes_location=True`` non-flags commands.
# ---------------------------------------------------------------------------


class _DefaultResolvingCache:
    """Records ``lookup(name, config, *rest)`` and returns an opaque result sentinel.

    Post-fix the app resolves the default name before the hub guard, so this records a
    non-None ``name`` (the default) rather than never being called. The returned object
    is opaque — the command handler is stubbed in the test so the assertion pins the
    FETCH NAME (the F02 contract), not each handler's payload shape.
    """

    def __init__(self) -> None:
        self.calls: list = []

    def lookup(self, name, config, *rest):
        self.calls.append((name, config, rest))
        return object()


def _real_config_with_default(name="Toronto"):
    """A real Config whose ``locations[0]`` is the default the F02 fix resolves."""
    from weatherbot.config.models import Config, Location, WebhookIdentity

    return Config(
        locations=[
            Location(name=name, lat=43.65, lon=-79.38, timezone="America/Toronto"),
            Location(name="London", lat=51.5, lon=-0.12, timezone="Europe/London"),
        ],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )


@pytest.mark.parametrize(
    "command",
    ["weather", "alerts", "sun", "wind", "next-cloudy", "uv"],
)
def test_takes_location_default_resolves(command, monkeypatch) -> None:
    """HARD-UI-01/F02 (D-01): each of the six ``takes_location=True`` non-flags commands
    with ``arg=None`` resolves the default location app-side so the fetch runs with the
    default NAME — instead of the hub skipping the fetch (leaving ``result=None`` and
    crashing the handler on ``None.forecast``).

    Drives the REAL app ``dispatch_spec`` with the real registry spec + a real Config;
    asserts the recorded ``cache.lookup`` was called with the resolved default name
    (``config.locations[0].name`` = ``Toronto``), proving the default reaches the fetch.
    The command handler is stubbed (a lenient ``*args`` handler) so the assertion pins
    the FETCH NAME (the F02 contract), decoupled from each handler's payload shape.
    """
    from dataclasses import replace

    from weatherbot.interactive import registry

    spec = registry.BY_NAME[command]
    assert spec.takes_location and not spec.needs_flags  # the F02 bucket

    # Stub the handler so the (result → reply) step never touches a rich forecast shape;
    # the real ``bind`` closure reads it live from BY_NAME, so patching BY_NAME suffices.
    reply = CommandReply(title=f"{command} — default")
    stub = replace(spec, handler=lambda *args, **kwargs: reply)
    monkeypatch.setitem(registry.BY_NAME, command, stub)

    cache = _DefaultResolvingCache()
    config = _real_config_with_default()
    loop = asyncio.new_event_loop()
    try:
        got = loop.run_until_complete(
            dispatch_spec(
                stub,
                None,  # bare command — no location arg (the F02 case)
                cache=cache,
                config=config,
                loop=loop,
                daemon_state=None,
            )
        )
    finally:
        loop.close()

    assert got is reply  # the fetch → handler → reply path completed (no crash)
    # The fetch ran with the resolved default name (not skipped, not None).
    assert cache.calls, f"bare !{command} must resolve the default and fetch"
    ((name, _config, _rest),) = cache.calls
    assert name == "Toronto", (
        f"bare !{command} must fetch the default location name, got {name!r}"
    )


def test_briefing_path_not_on_default_executor() -> None:
    """PANEL-11/T-20-02/D-08b: the briefing/scheduler path never borrows the asyncio
    default executor that the panel's read-only fetch uses.

    Audit target: ``weatherbot/interactive/dispatch.py:166-188`` — the ONLY caller of
    ``loop.run_in_executor(None, …)`` (the asyncio DEFAULT ``ThreadPoolExecutor``). That
    default pool is panel-only: it backs the read-only OpenWeather fetch + the off-loop
    reply ladder. The briefing instead runs under APScheduler ``BackgroundScheduler``'s
    OWN pool on a separate OS thread (see ``tests/test_scheduler.py``), so the two pools
    are distinct objects and the briefing spine never reaches ``dispatch.py``.

    This is a confirming audit, EXPECTED to come back clean (Pitfall 4: a concrete
    assertion is cheap regression insurance over a documented code-path note). It does NOT
    introduce a dedicated bounded executor (Option C — out of scope unless real sharing
    were found). Two structural facts are pinned:

    (a) ``loop.run_in_executor(None, …)`` appears ONLY in the relocated generic
        dispatcher (``yahir_reusable_bot/registry/dispatch.py``) and NOWHERE in the
        ``weatherbot/`` tree — i.e. the asyncio default executor is reached from exactly
        one module (the shared dispatcher the panel's read-only fetch delegates to),
        never duplicated into a scheduler path. (Phase 26 relocated the off-loop fetch +
        reply shell into the module behind the byte-identical app shim; the app's
        ``weatherbot/interactive/dispatch.py`` is now a thin delegate that no longer
        names the default executor itself.)
    (b) The ``weatherbot/scheduler/`` package (the briefing spine) contains ZERO
        ``run_in_executor`` calls — the scheduler job never touches the default pool.
    """
    import re
    from pathlib import Path

    import weatherbot
    import yahir_reusable_bot

    pkg_root = Path(weatherbot.__file__).parent
    module_root = Path(yahir_reusable_bot.__file__).parent

    # (a) After the Phase-26 relocation, the asyncio default executor call lives in the
    # ONE shared module dispatcher and NOWHERE under weatherbot/ (the app shim delegates).
    default_executor_pat = re.compile(r"run_in_executor\(\s*None")
    app_callers = sorted(
        path.relative_to(pkg_root).as_posix()
        for path in pkg_root.rglob("*.py")
        # Only count real call sites: a `run_in_executor(None` followed by an arg list,
        # not a docstring mention of the method name.
        if default_executor_pat.search(path.read_text(encoding="utf-8"))
    )
    assert app_callers == [], (
        "no weatherbot/ module may borrow the asyncio default executor directly after "
        "the Phase-26 relocation (the app dispatch shim delegates to the module); "
        f"found callers: {app_callers}"
    )
    module_callers = sorted(
        path.relative_to(module_root).as_posix()
        for path in module_root.rglob("*.py")
        if default_executor_pat.search(path.read_text(encoding="utf-8"))
    )
    assert module_callers == ["registry/dispatch.py"], (
        "the asyncio default executor (run_in_executor(None, …)) must be reached ONLY "
        "from the relocated shared dispatcher (registry/dispatch.py), never the briefing "
        f"path; found module callers: {module_callers}"
    )

    # (b) The scheduler package (the briefing spine) never calls run_in_executor at all.
    scheduler_root = pkg_root / "scheduler"
    scheduler_executor_callers = sorted(
        path.relative_to(scheduler_root).as_posix()
        for path in scheduler_root.rglob("*.py")
        if "run_in_executor" in path.read_text(encoding="utf-8")
    )
    assert scheduler_executor_callers == [], (
        "no scheduler/briefing code path may borrow an executor via run_in_executor; "
        f"found: {scheduler_executor_callers}"
    )
