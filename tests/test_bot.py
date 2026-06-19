"""Wave-0 Nyquist RED scaffold for Phase 11 — the inbound Discord gateway bot.

These tests are the EXECUTABLE CONTRACT that Plans 11-03/11-04 turn green. They are
written BEFORE ``weatherbot.interactive.bot`` exists: the not-yet-built module
(``build_client`` / ``on_message`` handler / ``build_inbound_embed``) is referenced
through PER-TEST lazy-import helpers (``_bot`` below), NOT at module top. A hard
top-level ``import weatherbot.interactive.bot`` would raise at COLLECTION and HIDE
every node ID — the exact Phase 8/9/10 Wave-0 lesson. Deferring the import lets all
six node IDs COLLECT while each still fails RED on a real
``ModuleNotFoundError``/``AttributeError`` until the bot module lands (T-11-01).

No live gateway, no network: every test drives ``on_message`` directly with the
``fake_discord_message`` factory (conftest) — a MagicMock shaped like a discord.py
Message with an ``AsyncMock`` ``channel.send`` and an async-context-manager
``channel.typing()``. The guard-ladder ORDER (Pattern 2: author.bot → operator-id →
parser → executor) and the non-propagating handler (CMD-08) are the load-bearing
contract these node IDs pin.
"""

from __future__ import annotations

import asyncio


# --------------------------------------------------------------------------- #
# Deferred reference to the NOT-YET-BUILT bot module (Phase 8/9/10 Wave-0 lesson).
# Resolved INSIDE each test body so every node ID collects while the symbol is
# absent; each call fails RED with a real ModuleNotFoundError/AttributeError.
# --------------------------------------------------------------------------- #


def _bot():
    """Import the not-yet-built bot module — RED until Plan 11-03 lands it.

    Deferred import (NOT module-top) so the node IDs collect. The module exposes the
    gateway client builder ``build_client(*, holder, operator_id, cache)``, the
    ``on_message`` coroutine handler it registers, and ``build_inbound_embed(forecast)``.
    """
    from weatherbot.interactive import bot

    return bot


def _run(coro):
    """Drive a coroutine to completion on a fresh event loop (no live gateway)."""
    return asyncio.run(coro)


_OPERATOR_ID = 12345


# --------------------------------------------------------------------------- #
# (1) Webhook/self guard — author.bot=True fires nothing (CMD-07, Pattern 2 D-04).
# --------------------------------------------------------------------------- #


def test_guard_webhook_author_fires_nothing(fake_discord_message, monkeypatch):
    """CMD-07: a message whose ``author.bot`` is True (the bot's own webhook briefing
    or any other bot) must short-circuit the FIRST guard — no lookup, no reply — so
    the always-on briefing webhook can never trip a feedback loop (T-11-01)."""
    bot = _bot()  # RED until the module exists

    # Spy the cache the handler dispatches to; ``lookup`` must NOT be touched because
    # the author.bot guard fires FIRST (IN-01: strongly pins the short-circuit).
    lookup_calls: list = []

    class _SpyCache:
        def lookup(self, name, config):
            lookup_calls.append((name, config))
            return object()

    msg = fake_discord_message(author_bot=True, content="!sun home")
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_SpyCache()
    )
    _run(handler(msg))

    assert lookup_calls == []  # the bot-author guard fired before any cache.lookup
    msg.channel.send.assert_not_awaited()  # and before any reply


# --------------------------------------------------------------------------- #
# (2) Operator guard — a non-operator human is silently ignored (CMD-07, D-05).
# --------------------------------------------------------------------------- #


def test_guard_non_operator_silently_ignored(fake_discord_message, monkeypatch):
    """CMD-07: a real human whose ``author.id`` is not the configured ``operator_id``
    is silently ignored — no lookup, no reply (single-user tool; A3). The bot must
    not even acknowledge unrelated channel chatter."""
    bot = _bot()

    lookup_calls: list = []
    monkeypatch.setattr(
        bot,
        "lookup_weather",
        lambda *a, **k: lookup_calls.append((a, k)),
        raising=False,
    )

    msg = fake_discord_message(author_bot=False, author_id=999, content="!sun home")
    handler = bot.build_on_message(holder=None, operator_id=_OPERATOR_ID, cache=None)
    _run(handler(msg))

    assert lookup_calls == []  # non-operator never reaches the executor
    msg.channel.send.assert_not_awaited()  # and gets no reply


# --------------------------------------------------------------------------- #
# (3) A registry weather-view dispatches its handler → embed reply (CMD-13/D-04).
# --------------------------------------------------------------------------- #


def test_registry_weather_view_builds_embed(fake_discord_message, monkeypatch):
    """CMD-13: an operator ``!sun home`` resolves the location via the cache, runs the
    registry ``sun`` handler off-loop, renders its CommandReply via ``render_embed``,
    and AWAITS ``channel.send(embed=...)``. The reply carries the structured embed,
    not plain text — and it is built from the SAME LookupResult the cache returned."""
    bot = _bot()

    # A LookupResult-shaped fake whose .forecast is the object the sun handler reads.
    fake_result = object()
    fake_embed = object()

    class _Cache:
        def lookup(self, name, config):
            return fake_result

    # Stub the registry ``sun`` handler so the test does not depend on a real payload
    # shape; assert it receives the LookupResult the cache returned, then render_embed
    # turns its reply into the embed the operator sees.
    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive import registry

    sentinel_reply = CommandReply(title="Sun — home", lines=(("Sunrise", "06:00"),))
    sun_spec = registry.BY_NAME["sun"]
    monkeypatch.setitem(
        registry.BY_NAME,
        "sun",
        _spec_with_handler(
            sun_spec,
            lambda result: sentinel_reply if result is fake_result else None,
        ),
    )
    # parse_command iterates registry.COMMANDS, not BY_NAME — patch that too so the
    # dispatched spec carries the stub handler.
    _patch_command_in_registry(monkeypatch, registry, "sun", registry.BY_NAME["sun"])

    monkeypatch.setattr(
        bot,
        "render_embed",
        lambda reply: fake_embed if reply is sentinel_reply else None,
        raising=True,
    )

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!sun home"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache()
    )
    _run(handler(msg))

    msg.channel.send.assert_awaited()
    _, kwargs = msg.channel.send.await_args
    assert "embed" in kwargs
    assert kwargs["embed"] is fake_embed


# --------------------------------------------------------------------------- #
# (3b) Info commands dispatch WITHOUT a fetch — help / locations (CMD-09/CMD-11).
# --------------------------------------------------------------------------- #


def test_help_command_replies_without_fetch(fake_discord_message, monkeypatch):
    """CMD-09: ``!help`` runs the registry ``help`` handler with NO cache lookup and
    replies with an embed. The cache.lookup must never be touched (info commands do
    not fetch)."""
    bot = _bot()

    lookup_calls: list = []

    class _SpyCache:
        def lookup(self, name, config):
            lookup_calls.append((name, config))
            return object()

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!help"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_SpyCache()
    )
    _run(handler(msg))

    assert lookup_calls == []  # help never fetches
    msg.channel.send.assert_awaited()
    _, kwargs = msg.channel.send.await_args
    assert "embed" in kwargs  # rendered as an embed (D-04)


def test_locations_command_replies_from_config(fake_discord_message, monkeypatch):
    """CMD-11: ``!locations`` runs the registry ``locations`` handler with the live
    config (no fetch, no cache) and replies with an embed listing the names."""
    bot = _bot()

    from weatherbot.config import Config, Location, WebhookIdentity

    config = Config(
        locations=[
            Location(name="Home", lat=40.0, lon=-74.0, timezone="America/New_York")
        ],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )

    class _NoFetchCache:
        def lookup(self, name, cfg):  # pragma: no cover — must not be called
            raise AssertionError("locations must not fetch")

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!locations"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(config), operator_id=_OPERATOR_ID, cache=_NoFetchCache()
    )
    _run(handler(msg))

    msg.channel.send.assert_awaited()


# --------------------------------------------------------------------------- #
# (3c) status dispatch reaches the injected read-only DaemonState (CMD-12).
# --------------------------------------------------------------------------- #


def test_status_command_reads_daemon_state(fake_discord_message, monkeypatch):
    """CMD-12: ``!status`` runs the registry ``status`` handler against the injected
    ``daemon_state`` and replies with an embed (next-send / uptime / liveness)."""
    bot = _bot()

    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive import registry

    sentinel = CommandReply(title="Status", lines=(("Daemon", "alive, up 1m"),))

    class _FakeDaemonState:
        pass

    fake_state = _FakeDaemonState()

    status_spec = registry.BY_NAME["status"]
    monkeypatch.setitem(
        registry.BY_NAME,
        "status",
        _spec_with_handler(
            status_spec,
            lambda ds: sentinel if ds is fake_state else None,
        ),
    )
    _patch_command_in_registry(
        monkeypatch, registry, "status", registry.BY_NAME["status"]
    )

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!status"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(),
        operator_id=_OPERATOR_ID,
        cache=object(),
        daemon_state=fake_state,
    )
    _run(handler(msg))

    msg.channel.send.assert_awaited()
    _, kwargs = msg.channel.send.await_args
    assert "embed" in kwargs


# --------------------------------------------------------------------------- #
# (4) A non-command is silently dropped (registry parse, CMD-16).
# --------------------------------------------------------------------------- #


def test_non_command_silently_dropped(fake_discord_message, monkeypatch):
    """A ``!`` message that matches NO registry command (``!nonsense``) is dropped at
    step (4) — no lookup, no reply (the parse-don't-validate boundary)."""
    bot = _bot()

    lookup_calls: list = []

    class _SpyCache:
        def lookup(self, name, config):
            lookup_calls.append((name, config))
            return object()

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!nonsense"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_SpyCache()
    )
    _run(handler(msg))

    assert lookup_calls == []
    msg.channel.send.assert_not_awaited()


# --------------------------------------------------------------------------- #
# (4b) Unknown location replies with the valid names (CMD-02 error path, D-07).
# --------------------------------------------------------------------------- #


def test_unknown_location_replies_valid_names(fake_discord_message, monkeypatch):
    """CMD-02 error path: when a location-taking command's lookup raises
    ``UnknownLocationError(requested, valid_names)``, the bot replies with a corrective
    hint text that NAMES the valid locations (no embed) so the operator can fix the
    typo without re-reading config."""
    bot = _bot()
    from weatherbot.interactive.lookup import UnknownLocationError

    class _Cache:
        def lookup(self, name, config):
            raise UnknownLocationError("nowhere", ["home", "away"])

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!sun nowhere"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache()
    )
    _run(handler(msg))

    msg.channel.send.assert_awaited()
    # The reply text mentions the valid names so the operator can correct the typo.
    sent = _sent_text(msg)
    assert "home" in sent and "away" in sent


# --------------------------------------------------------------------------- #
# (5) Blocking work runs OFF the event loop (Pitfall 1) — via run_in_executor.
# --------------------------------------------------------------------------- #


def test_blocking_work_runs_off_loop(fake_discord_message, monkeypatch):
    """Pitfall 1 (D-10): the SYNC ``cache.lookup`` (httpx fetch + render) must be
    dispatched through ``loop.run_in_executor`` so it never blocks the gateway
    heartbeat — it must NOT be awaited/called inline on the coroutine. Assert the
    handler routes the blocking call through ``run_in_executor`` and never calls
    ``cache.lookup`` directly on the event-loop thread."""
    bot = _bot()

    executor_dispatched: list = []
    inline_calls: list = []

    fake_embed = object()
    monkeypatch.setattr(bot, "render_embed", lambda reply: fake_embed, raising=True)

    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive import registry

    sun_spec = registry.BY_NAME["sun"]
    monkeypatch.setitem(
        registry.BY_NAME,
        "sun",
        _spec_with_handler(sun_spec, lambda result: CommandReply(title="Sun")),
    )
    _patch_command_in_registry(monkeypatch, registry, "sun", registry.BY_NAME["sun"])

    class _Cache:
        def lookup(self, name, config):
            # If this ever runs on the loop thread directly the handler is wrong.
            inline_calls.append((name, config))
            return object()

    async def _amain():
        loop = asyncio.get_running_loop()
        real_run_in_executor = loop.run_in_executor

        def _spy(executor, func, *args):
            executor_dispatched.append(func)
            return real_run_in_executor(executor, func, *args)

        # Patch the bound method on this loop instance for the duration of the call.
        loop.run_in_executor = _spy  # type: ignore[method-assign]
        try:
            msg = fake_discord_message(
                author_bot=False, author_id=_OPERATOR_ID, content="!sun home"
            )
            handler = bot.build_on_message(
                holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache()
            )
            await handler(msg)
        finally:
            loop.run_in_executor = real_run_in_executor  # type: ignore[method-assign]

    asyncio.run(_amain())

    # The blocking lookup was dispatched through run_in_executor at least once ...
    assert executor_dispatched, "cache.lookup was not dispatched via run_in_executor"


# --------------------------------------------------------------------------- #
# (6) Handler exceptions never propagate (CMD-16) — an error reply is sent instead.
# --------------------------------------------------------------------------- #


def test_handler_exception_does_not_propagate(fake_discord_message, monkeypatch):
    """CMD-16 (D-11): an UNEXPECTED failure inside the executor (not an
    UnknownLocationError) must NOT propagate out of ``on_message`` — the always-on
    process must survive. The handler swallows + logs the error and sends a generic
    error reply rather than crashing the gateway / reaching the scheduler thread."""
    bot = _bot()

    class _Cache:
        def lookup(self, name, config):
            raise RuntimeError("boom — upstream fetch exploded")

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!sun home"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache()
    )

    # The handler must return WITHOUT raising (non-propagating, CMD-16) ...
    _run(handler(msg))

    # ... and an error reply was sent so the operator is not left hanging.
    msg.channel.send.assert_awaited()


def test_raising_command_handler_is_isolated(fake_discord_message, monkeypatch):
    """CMD-16 failure isolation: a registry HANDLER (not the fetch) that raises is
    caught by the EXISTING non-propagating envelope — on_message does NOT raise and a
    generic error reply is sent. This proves a per-command bug never crosses into the
    gateway / scheduler thread."""
    bot = _bot()

    from weatherbot.interactive import registry

    class _LookupResultLike:
        forecast = object()

    class _Cache:
        def lookup(self, name, config):
            return _LookupResultLike()

    def _boom(result):
        raise RuntimeError("handler blew up after a clean fetch")

    sun_spec = registry.BY_NAME["sun"]
    monkeypatch.setitem(registry.BY_NAME, "sun", _spec_with_handler(sun_spec, _boom))
    _patch_command_in_registry(monkeypatch, registry, "sun", registry.BY_NAME["sun"])

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!sun home"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache()
    )

    # MUST return without raising (the raising handler is isolated, CMD-16) ...
    _run(handler(msg))

    # ... and the operator gets the generic error reply.
    msg.channel.send.assert_awaited()


# --------------------------------------------------------------------------- #
# uv command on Discord (Plan 14-04, UV-01): embed + threshold + isolation.
# --------------------------------------------------------------------------- #


def _config_with_uv_threshold(threshold):
    """A minimal config stand-in exposing ``.uv.threshold`` for the uv dispatch."""

    class _Uv:
        pass

    class _Cfg:
        pass

    uv = _Uv()
    uv.threshold = threshold
    cfg = _Cfg()
    cfg.uv = uv
    return cfg


def test_uv_command_builds_embed(fake_discord_message, monkeypatch):
    """UV-01: ``!uv home`` resolves via the cache, runs the registry ``uv`` handler with
    ``(result, config.uv.threshold)`` off-loop, and replies with an embed built from the
    SAME LookupResult the cache returned."""
    bot = _bot()

    fake_result = object()
    fake_embed = object()

    class _Cache:
        def lookup(self, name, config):
            return fake_result

    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive import registry

    sentinel_reply = CommandReply(title="UV — home", lines=(("Now", "5 (Moderate)"),))
    uv_spec = registry.BY_NAME["uv"]
    monkeypatch.setitem(
        registry.BY_NAME,
        "uv",
        _spec_with_handler(
            uv_spec,
            lambda result, threshold: (
                sentinel_reply if result is fake_result else None
            ),
        ),
    )
    _patch_command_in_registry(monkeypatch, registry, "uv", registry.BY_NAME["uv"])

    monkeypatch.setattr(
        bot,
        "render_embed",
        lambda reply: fake_embed if reply is sentinel_reply else None,
        raising=True,
    )

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!uv home"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(_config_with_uv_threshold(6.0)),
        operator_id=_OPERATOR_ID,
        cache=_Cache(),
    )
    _run(handler(msg))

    msg.channel.send.assert_awaited()
    _, kwargs = msg.channel.send.await_args
    assert "embed" in kwargs
    assert kwargs["embed"] is fake_embed


def test_uv_command_threads_config_threshold(fake_discord_message, monkeypatch):
    """The Discord dispatch passes ``config.uv.threshold`` (NOT a literal) to the uv
    handler — a ``[uv] threshold`` change reaches the command."""
    bot = _bot()

    fake_result = object()
    captured: dict = {}

    class _Cache:
        def lookup(self, name, config):
            return fake_result

    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive import registry

    def _handler(result, threshold):
        captured["threshold"] = threshold
        return CommandReply(title="UV — home")

    uv_spec = registry.BY_NAME["uv"]
    monkeypatch.setitem(
        registry.BY_NAME, "uv", _spec_with_handler(uv_spec, _handler)
    )
    _patch_command_in_registry(monkeypatch, registry, "uv", registry.BY_NAME["uv"])
    monkeypatch.setattr(bot, "render_embed", lambda reply: object(), raising=True)

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!uv home"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(_config_with_uv_threshold(4.0)),
        operator_id=_OPERATOR_ID,
        cache=_Cache(),
    )
    _run(handler(msg))

    assert captured["threshold"] == 4.0


def test_raising_uv_handler_is_isolated(fake_discord_message, monkeypatch):
    """CMD-16 / T-14-10: a raising ``uv`` handler is caught by the existing
    non-propagating envelope — on_message does NOT raise and never gates the briefing
    spine; the operator still gets the generic error reply."""
    bot = _bot()

    from weatherbot.interactive import registry

    class _LookupResultLike:
        forecast = object()

    class _Cache:
        def lookup(self, name, config):
            return _LookupResultLike()

    def _boom(result, threshold):
        raise RuntimeError("uv handler blew up after a clean fetch")

    uv_spec = registry.BY_NAME["uv"]
    monkeypatch.setitem(registry.BY_NAME, "uv", _spec_with_handler(uv_spec, _boom))
    _patch_command_in_registry(monkeypatch, registry, "uv", registry.BY_NAME["uv"])

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!uv home"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(_config_with_uv_threshold(6.0)),
        operator_id=_OPERATOR_ID,
        cache=_Cache(),
    )

    # MUST return without raising (the raising handler is isolated, CMD-16) ...
    _run(handler(msg))
    # ... and the operator gets the generic error reply.
    msg.channel.send.assert_awaited()


# --------------------------------------------------------------------------- #
# Forecast commands on Discord (Plan 13-04): flags threaded + widened cache key.
# --------------------------------------------------------------------------- #


def test_weekend_forecast_dispatch_builds_embed(fake_discord_message, monkeypatch):
    """FCAST-02/04: ``!weekend-forecast home +sat`` parses the flags, looks up via the
    widened cache key, runs the forecast handler with ``(result, flags)`` and replies
    with an embed built from the SAME LookupResult the cache returned."""
    bot = _bot()

    fake_result = object()
    fake_embed = object()
    captured: dict = {}

    class _Cache:
        # Widened signature: forecast dispatch passes the key suffix positionally.
        def lookup(self, name, config, suffix=None):
            captured["name"] = name
            captured["suffix"] = suffix
            return fake_result

    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive import registry

    sentinel = CommandReply(title="Weekend forecast — home", text="…")

    def _handler(result, flags):
        captured["flags"] = flags
        return sentinel if result is fake_result else None

    spec = registry.BY_NAME["weekend-forecast"]
    monkeypatch.setitem(
        registry.BY_NAME, "weekend-forecast", _spec_with_handler(spec, _handler)
    )
    _patch_command_in_registry(
        monkeypatch, registry, "weekend-forecast", registry.BY_NAME["weekend-forecast"]
    )
    monkeypatch.setattr(
        bot,
        "render_embed",
        lambda reply: fake_embed if reply is sentinel else None,
        raising=True,
    )

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!weekend-forecast home +sat"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache()
    )
    _run(handler(msg))

    msg.channel.send.assert_awaited()
    _, kwargs = msg.channel.send.await_args
    assert kwargs.get("embed") is fake_embed
    # The flag-stripped location was used for the lookup, the add flag parsed, and the
    # cache key suffix encodes the command/variant/flags (A5 collision guard).
    assert captured["name"] == "home"
    assert "sat" in captured["flags"].add
    assert captured["suffix"] is not None
    assert "weekend-forecast" in captured["suffix"]


def test_raising_forecast_handler_is_isolated(fake_discord_message, monkeypatch):
    """CMD-16: a forecast handler that raises does NOT propagate out of on_message —
    the existing non-propagating envelope catches it and sends the generic reply."""
    bot = _bot()

    from weatherbot.interactive import registry

    class _Cache:
        def lookup(self, name, config, suffix=None):
            return object()

    def _boom(result, flags):
        raise RuntimeError("forecast handler blew up after a clean fetch")

    spec = registry.BY_NAME["weekday-forecast"]
    monkeypatch.setitem(
        registry.BY_NAME, "weekday-forecast", _spec_with_handler(spec, _boom)
    )
    _patch_command_in_registry(
        monkeypatch, registry, "weekday-forecast", registry.BY_NAME["weekday-forecast"]
    )

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!weekday-forecast home"
    )
    handler = bot.build_on_message(
        holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache()
    )
    _run(handler(msg))  # MUST NOT raise

    msg.channel.send.assert_awaited()  # generic error reply sent


# --------------------------------------------------------------------------- #
# render_embed field/title bounding (WR-02 / WR-03).
# --------------------------------------------------------------------------- #


def test_long_forecast_body_split_across_fields_not_truncated():
    """WR-02: a >1024-char forecast body is split across multiple <=1024 fields,
    delivering EVERY day rather than clipping the tail into one field."""
    bot = _bot()
    from weatherbot.interactive.commands import CommandReply

    # Five distinctly-tagged "day" lines, each long enough that the whole body
    # comfortably exceeds the 1024-char single-field cap.
    day_lines = [f"DAY{i} " + ("x" * 250) for i in range(5)]
    body = "\n".join(day_lines)
    assert len(body) > bot._MAX_FIELD_VALUE  # would be truncated by the old path

    embed = bot.render_embed(CommandReply(title="Weekday forecast — home", text=body))

    # Every field value is within Discord's per-field cap...
    assert all(len(f.value) <= bot._MAX_FIELD_VALUE for f in embed.fields)
    # ...and no day was lost: every DAYn tag survives somewhere in the fields.
    joined = "\n".join(f.value for f in embed.fields)
    for i in range(5):
        assert f"DAY{i}" in joined
    # The old single-field path would have dropped the last day(s) with an ellipsis.
    assert "…" not in joined or all(f"DAY{i}" in joined for i in range(5))


def test_body_split_respects_field_count_cap():
    """WR-02 last-resort: a body needing more than the field budget is trimmed with a
    trailing "+N more" marker rather than exceeding Discord's 25-field cap."""
    bot = _bot()
    from weatherbot.interactive.commands import CommandReply

    # Each line is a full 1024-char chunk → one field each. Far more than 25.
    lines = [("y" * bot._MAX_FIELD_VALUE) for _ in range(40)]
    body = "\n".join(lines)
    embed = bot.render_embed(CommandReply(title="t", text=body))

    assert len(embed.fields) <= bot._MAX_FIELDS
    assert any(f.value.startswith("+") and "more" in f.value for f in embed.fields)


def test_embed_title_clipped_to_title_cap():
    """WR-03: the title is clipped against the dedicated _MAX_TITLE constant."""
    bot = _bot()
    from weatherbot.interactive.commands import CommandReply

    assert bot._MAX_TITLE == 256
    long_title = "T" * 500
    embed = bot.render_embed(CommandReply(title=long_title))
    assert len(embed.title) <= bot._MAX_TITLE


# --------------------------------------------------------------------------- #
# Local helpers (no production import — pure test scaffolding).
# --------------------------------------------------------------------------- #


class _FakeHolder:
    """Minimal ConfigHolder stand-in — ``current()`` returns a sentinel config."""

    def __init__(self, config=None):
        self._config = config if config is not None else object()

    def current(self):
        return self._config


def _spec_with_handler(spec, handler):
    """Return a copy of ``spec`` carrying ``handler`` (frozen CommandSpec → replace)."""
    from dataclasses import replace

    return replace(spec, handler=handler)


def _patch_command_in_registry(monkeypatch, registry, name, new_spec):
    """Swap the named spec inside ``registry.COMMANDS`` (what parse_command iterates).

    ``parse_command`` matches against ``COMMANDS`` / ``COMMANDS_BY_KEYWORD_LEN_DESC``,
    not ``BY_NAME``, so a test that stubs a handler must replace the spec in BOTH the
    name index and the iterated tuples for the dispatched spec to carry the stub.
    """
    new_commands = tuple(new_spec if s.name == name else s for s in registry.COMMANDS)
    monkeypatch.setattr(registry, "COMMANDS", new_commands, raising=True)
    monkeypatch.setattr(
        registry,
        "COMMANDS_BY_KEYWORD_LEN_DESC",
        tuple(sorted(new_commands, key=lambda c: len(c.name), reverse=True)),
        raising=True,
    )


def _sent_text(msg) -> str:
    """Return the text content of the (single) awaited channel.send call.

    Reads either the first positional arg or the ``content=`` kwarg so the test does
    not over-constrain the bot's reply-call shape (it may send positionally or by
    keyword), only that the text was delivered.
    """
    args, kwargs = msg.channel.send.await_args
    if args:
        return str(args[0])
    return str(kwargs.get("content", ""))


# --------------------------------------------------------------------------- #
# BotThread failure isolation (T-11-11 / T-11-14 "dies alone", CMD-08).
#
# These tests stand up a REAL BotThread on its own thread + event loop, but
# substitute the gateway client with a gateway-free fake (no token, no network,
# no real ``discord.Client``). The fake's ``start()`` is what raises, exercising
# the exact ``_run`` -> ``asyncio.run(_amain())`` -> ``client.start()`` path the
# production daemon relies on for failure isolation. ``build_client`` is patched
# at the bot module so ``BotThread.__init__`` wires the fake in (it calls
# ``build_client`` internally).
# --------------------------------------------------------------------------- #


class _FakeGatewayClient:
    """A gateway-free stand-in for ``discord.Client`` used by BotThread tests.

    Supports exactly what ``BotThread._amain`` touches: ``async with self._client``
    (async context manager) and ``await self._client.start(token)``. ``start`` runs
    a caller-supplied async behavior so a test can make it raise ``LoginFailure``,
    raise an arbitrary error, or block until ``close()`` for the clean-stop path.
    """

    def __init__(self, *, on_start):
        self._on_start = on_start
        self.closed = False
        self._close_event = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def start(self, token):  # noqa: D401 — mirrors discord.Client.start
        await self._on_start(self)

    async def close(self):
        self.closed = True
        if self._close_event is not None:
            self._close_event.set()


def _join_until_dead(thread_obj, timeout=5.0):
    """Wait up to ``timeout`` for a BotThread's underlying thread to exit."""
    thread_obj._thread.join(timeout=timeout)


def test_bot_thread_dies_alone_on_login_failure(monkeypatch):
    """T-11-11/T-11-14: a ``discord.LoginFailure`` raised inside the gateway client's
    ``start()`` is caught in ``BotThread._run`` — the bot thread TERMINATES, the
    failure NEVER propagates out of the thread, and ``is_alive()`` flips to False so
    the daemon can observe the dead start. This is the unit-level proof the inbound
    bot "dies alone" without taking the process down (CMD-08 / D-11)."""
    import discord

    bot = _bot()

    async def _raise_login_failure(_client):
        raise discord.LoginFailure("invalid token")

    # Patch build_client so the REAL BotThread wires in a gateway-free fake client
    # whose start() raises LoginFailure (no token, no network).
    monkeypatch.setattr(
        bot,
        "build_client",
        lambda **kwargs: _FakeGatewayClient(on_start=_raise_login_failure),
        raising=True,
    )

    thread = bot.BotThread(
        "fake-token",
        holder=_FakeHolder(),
        operator_id=_OPERATOR_ID,
        cache=object(),
    )

    # start() must return normally — the failure is asynchronous, inside the thread.
    thread.start()
    _join_until_dead(thread)

    # The failure was SWALLOWED inside _run: the thread is dead, nothing escaped.
    assert thread._thread.is_alive() is False  # the bot thread terminated
    # ``_failed`` is set ONLY by _run's except arms — proves the LoginFailure was
    # actively CAUGHT (not merely that the thread happened to exit).
    assert thread._failed is True
    assert thread.is_alive() is False  # _failed flipped -> daemon sees a dead start


def test_bot_thread_dies_alone_on_unexpected_crash(monkeypatch):
    """T-11-11 (broader catch): an UNEXPECTED (non-LoginFailure) exception inside the
    gateway client's ``start()`` is ALSO isolated by ``BotThread._run`` — the thread
    terminates, ``is_alive()`` reports a dead start, and nothing propagates out of the
    thread. Proves the generic ``except Exception`` arm (D-11), not just the
    LoginFailure path."""
    bot = _bot()

    async def _raise_runtime(_client):
        raise RuntimeError("gateway exploded mid-connect")

    monkeypatch.setattr(
        bot,
        "build_client",
        lambda **kwargs: _FakeGatewayClient(on_start=_raise_runtime),
        raising=True,
    )

    thread = bot.BotThread(
        "fake-token",
        holder=_FakeHolder(),
        operator_id=_OPERATOR_ID,
        cache=object(),
    )

    thread.start()
    _join_until_dead(thread)

    assert thread._thread.is_alive() is False
    assert thread._failed is True  # generic except arm actively caught the crash
    assert thread.is_alive() is False  # generic crash isolated, daemon sees dead start


def test_bot_thread_clean_start_and_stop(monkeypatch):
    """Lifecycle happy path: a client whose ``start()`` blocks until ``close()`` lets
    ``BotThread.start()`` bring the loop up (``is_alive()`` True), and ``stop()``
    cross-thread-schedules ``client.close()`` and joins the thread to completion —
    proving the start/stop teardown the daemon's finally relies on actually works,
    gateway-free."""
    import asyncio as _asyncio

    bot = _bot()

    captured = {}

    async def _block_until_close(client):
        # Hold the bot loop open until close() sets this event (the real gateway
        # blocks here until the connection is torn down).
        ev = _asyncio.Event()
        client._close_event = ev
        captured["client"] = client
        await ev.wait()

    monkeypatch.setattr(
        bot,
        "build_client",
        lambda **kwargs: _FakeGatewayClient(on_start=_block_until_close),
        raising=True,
    )

    thread = bot.BotThread(
        "fake-token",
        holder=_FakeHolder(),
        operator_id=_OPERATOR_ID,
        cache=object(),
    )

    thread.start()
    assert thread.is_alive() is True  # loop came up; no failure flagged

    thread.stop(timeout=5.0)

    assert thread._thread.is_alive() is False  # joined to completion
    assert captured["client"].closed is True  # close() was scheduled cross-thread
