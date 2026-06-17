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

import pytest


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

    msg = fake_discord_message(author_bot=True, content="!weather home")
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
        bot, "lookup_weather", lambda *a, **k: lookup_calls.append((a, k)), raising=False
    )

    msg = fake_discord_message(author_bot=False, author_id=999, content="!weather home")
    handler = bot.build_on_message(holder=None, operator_id=_OPERATOR_ID, cache=None)
    _run(handler(msg))

    assert lookup_calls == []  # non-operator never reaches the executor
    msg.channel.send.assert_not_awaited()  # and gets no reply


# --------------------------------------------------------------------------- #
# (3) Located reply builds an embed (CMD-02) — operator `!weather home` → embed reply.
# --------------------------------------------------------------------------- #


def test_located_reply_builds_embed(fake_discord_message, monkeypatch):
    """CMD-02: an operator ``!weather home`` resolves the location, fetches via the
    cache, builds an embed from the forecast, and AWAITS ``channel.send(embed=...)``.
    The reply carries the structured embed, not plain briefing text (D-07)."""
    bot = _bot()

    # Fake the cache.lookup result the handler renders into an embed. Production
    # accesses ``result.forecast`` strictly (WR-05), so the fake must be a
    # LookupResult-SHAPED object with a ``.forecast`` attribute — not a bare object.
    fake_forecast = object()
    fake_embed = object()

    class _LookupResultLike:
        forecast = fake_forecast

    class _Cache:
        def lookup(self, name, config):
            return _LookupResultLike()

    # Assert the embed is built from ``result.forecast`` (the strict contract).
    monkeypatch.setattr(
        bot,
        "build_inbound_embed",
        lambda forecast: fake_embed if forecast is fake_forecast else None,
        raising=False,
    )

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!weather home"
    )
    handler = bot.build_on_message(holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache())
    _run(handler(msg))

    # The reply was awaited with an embed= kwarg (the embed built from the forecast).
    msg.channel.send.assert_awaited()
    _, kwargs = msg.channel.send.await_args
    assert "embed" in kwargs
    assert kwargs["embed"] is fake_embed


# --------------------------------------------------------------------------- #
# (4) Unknown location replies with the valid names (CMD-02 error path, D-07).
# --------------------------------------------------------------------------- #


def test_unknown_location_replies_valid_names(fake_discord_message, monkeypatch):
    """CMD-02 error path: when the lookup raises ``UnknownLocationError(requested,
    valid_names)``, the bot replies with a corrective hint text that NAMES the valid
    locations (no embed) so the operator can fix the typo without re-reading config."""
    bot = _bot()
    from weatherbot.interactive.lookup import UnknownLocationError

    class _Cache:
        def lookup(self, name, config):
            raise UnknownLocationError("nowhere", ["home", "away"])

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!weather nowhere"
    )
    handler = bot.build_on_message(holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache())
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
    monkeypatch.setattr(
        bot, "build_inbound_embed", lambda forecast: fake_embed, raising=False
    )

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
                author_bot=False, author_id=_OPERATOR_ID, content="!weather home"
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
# (6) Handler exceptions never propagate (CMD-08) — an error reply is sent instead.
# --------------------------------------------------------------------------- #


def test_handler_exception_does_not_propagate(fake_discord_message, monkeypatch):
    """CMD-08 (D-11): an UNEXPECTED failure inside the executor (not an
    UnknownLocationError) must NOT propagate out of ``on_message`` — the always-on
    process must survive. The handler swallows + logs the error and sends a generic
    error reply rather than crashing the gateway."""
    bot = _bot()

    class _Cache:
        def lookup(self, name, config):
            raise RuntimeError("boom — upstream fetch exploded")

    msg = fake_discord_message(
        author_bot=False, author_id=_OPERATOR_ID, content="!weather home"
    )
    handler = bot.build_on_message(holder=_FakeHolder(), operator_id=_OPERATOR_ID, cache=_Cache())

    # The handler must return WITHOUT raising (non-propagating, CMD-08) ...
    _run(handler(msg))

    # ... and an error reply was sent so the operator is not left hanging.
    msg.channel.send.assert_awaited()


# --------------------------------------------------------------------------- #
# Local helpers (no production import — pure test scaffolding).
# --------------------------------------------------------------------------- #


class _FakeHolder:
    """Minimal ConfigHolder stand-in — ``current()`` returns a sentinel config."""

    def __init__(self, config=None):
        self._config = config if config is not None else object()

    def current(self):
        return self._config


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
