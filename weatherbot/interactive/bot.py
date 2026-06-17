"""The inbound Discord gateway bot: guard ladder, embed reply, off-loop fetch (CMD-02/07/08).

This module is the read path ``operator -> gateway -> guards -> cache -> embed reply``.
It uses a bare :class:`discord.Client` (NOT a Bot/command framework) with a manually
written ``on_message`` guard ladder, because the only command surface is a single
operator typing ``!weather [loc]`` in one private server.

Design decisions (from 11-RESEARCH / 11-PATTERNS):

- **Guard ladder ORDER (Pattern 2) is load-bearing.** ``on_message`` checks, in this
  exact order: (1) ``message.author.bot`` — drops the bot's OWN webhook briefing AND
  any other bot, the first backstop against a feedback loop (D-04, T-11-05); (2)
  ``author.id != operator_id`` — silently ignores every non-operator (D-05, T-11-06);
  (3) the ``!`` prefix; (4) ``parse_weather_command`` (the shared D-03 parser, strips
  the ``!``); (5) extract the raw location (``None`` for the bare default).
- **All blocking work runs OFF the event loop (D-10, Pitfall 1).** The sync
  ``cache.lookup`` (resolve + httpx fetch + render) is dispatched via
  ``loop.run_in_executor`` so the gateway heartbeat never blocks.
- **A typing indicator (D-08)** is shown via ``async with message.channel.typing():``
  around the fetch.
- **The reply is an embed (D-07)** mirroring ``send_briefing`` field-for-field, built
  with the gateway lib's :class:`discord.Embed` (color int ``0x03b2f8`` — the gateway
  lib takes an int, unlike the webhook lib's ``"03b2f8"`` string).
- **The WHOLE handler body is wrapped in a non-propagating try/except (D-11, CMD-08).**
  An unexpected failure is logged + answered with a generic reply, and NEVER re-raised
  — the always-on process must survive a bad fetch. No token / URL ever reaches a log
  or a user-facing message (T-11-08/T-11-10).

The ``BotThread`` runs the client on its OWN thread + event loop via
``asyncio.run(client.start(token))`` (NOT the blocking ``Client.run`` helper, which
installs signal handlers and only works on the main thread). Bot health failures (invalid token, any
crash) die inside the thread and never take down the briefing scheduler (D-11). Daemon
wiring (start/stop + CFG-07) is Plan 11-04.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Awaitable, Callable

import discord
import structlog

from weatherbot.interactive.command import CommandKind, parse_weather_command
from weatherbot.interactive.lookup import (
    UnknownLocationError,
    lookup_weather,  # noqa: F401 — re-exported as a test spy seam (CMD-07); not called here
)

if TYPE_CHECKING:
    from weatherbot.config.holder import ConfigHolder
    from weatherbot.interactive.cache import ForecastCache
    from weatherbot.weather.models import Forecast

# ``lookup_weather`` is imported at module top (not used directly here — the cache
# wraps it) so the bot tests can spy on ``bot.lookup_weather`` and assert the guard
# ladder short-circuits BEFORE any fetch (CMD-07).
__all__ = ["build_client", "build_inbound_embed", "build_on_message", "BotThread"]

_log = structlog.get_logger(__name__)

_ERROR_REPLY = "Sorry — something went wrong fetching that."


def build_inbound_embed(forecast: Forecast) -> discord.Embed:
    """Build the inbound reply embed, mirroring ``send_briefing`` field-for-field (D-07).

    Uses the GATEWAY lib's :class:`discord.Embed` (color int ``0x03b2f8`` — NOT the
    webhook lib's ``"03b2f8"`` string). Fields match the webhook briefing exactly:
    ``Now`` = ``temp_display``, ``High / Low`` = ``"{high} / {low}"``,
    ``Rain`` = ``"{pct}%"``, plus a UTC timestamp.
    """
    embed = discord.Embed(
        title=f"Weather — {forecast.location}", color=0x03B2F8
    )
    embed.add_field(name="Now", value=forecast.temp_display, inline=True)
    embed.add_field(
        name="High / Low",
        value=f"{forecast.high_display} / {forecast.low_display}",
        inline=True,
    )
    embed.add_field(name="Rain", value=f"{forecast.rain_chance}%", inline=True)
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_on_message(
    *,
    holder: ConfigHolder,
    operator_id: int,
    cache: ForecastCache,
) -> Callable[[discord.Message], Awaitable[None]]:
    """Build the ``on_message`` coroutine handler (the guard ladder + reply, CMD-02/07/08).

    Returned as a standalone coroutine (rather than only registered on a client) so
    the gateway-free tests can drive it directly with a fake message. ``holder`` gives
    a lock-free ``current()`` config snapshot; ``cache`` is the per-location TTL cache;
    ``operator_id`` is the single allowed author.
    """

    async def on_message(message: discord.Message) -> None:
        # --- Guard ladder (Pattern 2 — ORDER is load-bearing) ----------------- #
        # (1) Drop the bot's OWN webhook briefing AND any other bot (D-04, T-11-05).
        if message.author.bot:
            return
        # (2) Silently ignore every non-operator (D-05, T-11-06 — single-user tool).
        if message.author.id != operator_id:
            return
        # (3) Require the ``!`` prefix.
        content = message.content or ""
        if not content.startswith("!"):
            return
        # (4) Parse via the shared D-03 parser (strip the leading ``!``).
        cmd = parse_weather_command(content[1:])
        if cmd.kind is CommandKind.NOT_A_COMMAND:
            return
        # (5) Extract the raw location (``None`` for the bare-default DEFAULT kind).
        name = cmd.location

        # --- Reply path — wrapped so NOTHING propagates out of on_message (D-11) #
        try:
            loop = asyncio.get_running_loop()
            config = holder.current()
            async with message.channel.typing():  # D-08 typing indicator
                try:
                    # All blocking work OFF the loop (D-10, Pitfall 1).
                    result = await loop.run_in_executor(
                        None, cache.lookup, name, config
                    )
                except UnknownLocationError as exc:
                    # CMD-02 error path: reply with the valid names, no embed.
                    await message.channel.send(str(exc))
                    return
            # Forecast lives on LookupResult.forecast; tolerate a bare result in
            # tests that patch build_inbound_embed to ignore its argument.
            forecast = getattr(result, "forecast", result)
            await message.channel.send(embed=build_inbound_embed(forecast))
        except Exception:  # noqa: BLE001 — non-propagating handler (CMD-08, D-11)
            _log.exception("inbound handler failed")
            try:
                await message.channel.send(_ERROR_REPLY)
            except Exception:  # noqa: BLE001 — best-effort reply; never re-raise
                _log.exception("inbound error reply failed")

    return on_message


def build_client(
    *,
    holder: ConfigHolder,
    operator_id: int,
    cache: ForecastCache,
) -> discord.Client:
    """Construct the gateway :class:`discord.Client` with minimal intents + handlers.

    Intents (T-11-09): start from ``none()`` then enable only ``guilds``,
    ``guild_messages``, and ``message_content`` (the last is a privileged intent that
    must also be toggled on in the Discord developer portal, D-02). An ``on_ready``
    startup assertion logs CRITICAL if ``message_content`` did not actually arrive
    (so a missing portal toggle is loud, not a silently dead bot, D-02).
    """
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.message_content = True  # privileged (D-02)

    client = discord.Client(intents=intents)
    handler = build_on_message(
        holder=holder, operator_id=operator_id, cache=cache
    )

    @client.event
    async def on_ready() -> None:
        if not client.intents.message_content:
            _log.critical(
                "message_content intent missing — enable it in the Discord "
                "developer portal; the bot cannot read commands"
            )
        else:
            _log.info("inbound bot ready", user=str(client.user))

    @client.event
    async def on_message(message: discord.Message) -> None:
        await handler(message)

    return client


class BotThread:
    """Run the gateway client on its OWN thread + event loop (RESEARCH Pattern 1).

    Uses ``asyncio.run(client.start(token))`` (NOT the blocking ``Client.run`` helper,
    which only works on the main thread). Bot health failures (invalid token, any crash) die inside
    this thread and NEVER take down the briefing scheduler (D-11). ``stop`` schedules
    ``client.close()`` cross-thread onto the bot loop via
    ``asyncio.run_coroutine_threadsafe`` and then joins the thread.
    """

    def __init__(
        self,
        token: str,
        *,
        holder: ConfigHolder,
        operator_id: int,
        cache: ForecastCache,
    ) -> None:
        self._token = token
        self._client = build_client(
            holder=holder, operator_id=operator_id, cache=cache
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="weatherbot-discord", daemon=True
        )

    def start(self) -> None:
        """Start the bot thread and wait (up to 5s) for its loop to come up."""
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            _log.warning("bot thread did not signal ready within 5s")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the bot: schedule ``client.close()`` cross-thread, then join."""
        loop = self._loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._client.close(), loop)
            try:
                future.result(timeout=timeout)
            except Exception:  # noqa: BLE001 — close best-effort; still join below
                _log.warning("bot client.close() did not complete cleanly")
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            _log.warning("bot thread did not stop within timeout")

    def _run(self) -> None:
        """Thread target: run the bot loop; isolate ALL failures here (D-11)."""
        try:
            asyncio.run(self._amain())
        except discord.LoginFailure:
            _log.critical(
                "invalid Discord token; inbound bot disabled, briefings unaffected"
            )
        except Exception:  # noqa: BLE001 — die alone; never crash the process (D-11)
            _log.critical("inbound bot thread crashed; briefings unaffected")

    async def _amain(self) -> None:
        """Bot loop entrypoint: record the loop, signal ready, then start the client."""
        self._loop = asyncio.get_running_loop()
        self._ready.set()
        async with self._client:
            await self._client.start(self._token)  # NOT the blocking Client.run helper
