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

from weatherbot.branding import BRIEFING_COLOR_INT
from weatherbot.interactive.command import parse_command
from weatherbot.interactive.lookup import UnknownLocationError

if TYPE_CHECKING:
    from weatherbot.config.holder import ConfigHolder
    from weatherbot.interactive.cache import ForecastCache
    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive.state import DaemonState
    from weatherbot.weather.models import Forecast

__all__ = [
    "build_client",
    "build_inbound_embed",
    "build_on_message",
    "render_embed",
    "BotThread",
]

_log = structlog.get_logger(__name__)

_ERROR_REPLY = "Sorry — something went wrong fetching that."

# Discord embed hard limits (WR-06). A send that violates any of these raises
# HTTPException on the gateway, which the on_message envelope would turn into the
# generic error reply — leaving the operator with nothing useful during exactly
# the high-alert moment the alerts command exists for. Bound them at render time.
_MAX_FIELDS = 25  # Discord rejects an embed with >25 fields.
_MAX_FIELD_NAME = 256  # field name limit.
_MAX_FIELD_VALUE = 1024  # field value limit.
# Embed TITLE limit (WR-03). Coincidentally 256 today, but it is a SEPARATE
# Discord cap from the field-NAME limit — kept as its own named constant so a
# future change to _MAX_FIELD_NAME cannot silently re-cap the title.
_MAX_TITLE = 256


def _clip(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` chars with an ellipsis when it overflows."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _split_body(text: str, limit: int) -> list[str]:
    """Pack ``text`` into a list of chunks each ``<= limit`` chars (WR-02).

    A detailed multi-day forecast body is the WHOLE deliverable — clipping it into
    a single 1024-char field silently drops the last day(s). Instead, split on LINE
    boundaries so each chunk holds as many whole lines as fit under ``limit``, and
    the caller emits each chunk as its OWN embed field. No data is lost as long as
    the field budget holds (the caller bounds the number of chunks).

    A single line longer than ``limit`` (pathological) is hard-split mid-line so the
    chunk still fits Discord's per-field cap rather than being rejected.
    """
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        # A single line that alone exceeds the limit: flush what we have, then
        # hard-split the oversized line into limit-sized pieces.
        if len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
            continue
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def render_embed(reply: CommandReply) -> discord.Embed:
    """Render a surface-agnostic :class:`CommandReply` into a Discord embed (D-04).

    Reuses the :func:`build_inbound_embed` house style: the reply ``title`` is the
    embed title, each ``(name, value)`` line becomes an inline ``add_field``, an
    optional free-form ``text`` body is added as a single non-inline field, and a UTC
    timestamp is stamped. The SAME ``CommandReply`` the CLI prints as plain text is
    rendered here as an embed, so the two surfaces can never drift.

    Field count and name/value lengths are bounded to Discord's limits (WR-06):
    provider-controlled text (e.g. an alert ``event`` as a field name) is clipped,
    and at most 24 fields render plus a "+N more" summary, so a many-alert reply
    still sends instead of being rejected by the gateway.

    A long free-form ``text`` body (a detailed multi-day forecast — the WHOLE
    deliverable) is SPLIT across as many ``<=1024``-char non-inline fields as the
    field budget allows (WR-02), so a five-day forecast is delivered IN FULL rather
    than silently truncated at the 1024-char single-field cap. Only if the body
    needs MORE fields than the budget leaves is a trailing "+N more" marker used as
    a genuine last resort.
    """
    embed = discord.Embed(
        title=_clip(reply.title, _MAX_TITLE), color=BRIEFING_COLOR_INT
    )

    # WR-02: a free-form ``text`` body is split into 1024-char chunks, each its own
    # non-inline field, so a long forecast is not clipped into a single field.
    text_chunks = _split_body(reply.text, _MAX_FIELD_VALUE) if reply.text else []

    # Reserve field slots for the body chunks (>=1 when present) and one for the
    # "+N more" overflow marker so the total never exceeds Discord's hard cap. At
    # least one body slot is always reserved when text is present; the body itself
    # is overflow-trimmed below if it would alone exhaust the budget.
    text_budget = 1 if reply.text else 0
    field_budget = _MAX_FIELDS - text_budget
    lines = list(reply.lines)
    overflow = 0
    if len(lines) > field_budget:
        # Keep room for the "+N more" marker field.
        keep = field_budget - 1
        overflow = len(lines) - keep
        lines = lines[:keep]

    for name, value in lines:
        embed.add_field(
            name=_clip(name, _MAX_FIELD_NAME),
            value=_clip(value, _MAX_FIELD_VALUE),
            inline=True,
        )
    if overflow:
        embed.add_field(name="…", value=f"+{overflow} more", inline=True)
    if text_chunks:
        # Spend whatever field slots remain on the body chunks. A zero-width-space
        # field name keeps each chunk left-aligned without a visible label. If the
        # body needs more fields than remain, drop the tail and append a "+N more"
        # marker (last resort — only a pathologically long body hits this).
        remaining = _MAX_FIELDS - len(embed.fields)
        body_overflow = 0
        if len(text_chunks) > remaining:
            keep = max(remaining - 1, 0)
            body_overflow = len(text_chunks) - keep
            text_chunks = text_chunks[:keep]
        for chunk in text_chunks:
            embed.add_field(name="​", value=chunk, inline=False)
        if body_overflow:
            embed.add_field(name="…", value=f"+{body_overflow} more", inline=False)
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_inbound_embed(forecast: Forecast) -> discord.Embed:
    """Build the inbound reply embed, mirroring ``send_briefing`` field-for-field (D-07).

    Uses the GATEWAY lib's :class:`discord.Embed` (color int — NOT the webhook lib's
    hex *string*). Both forms derive from the single ``BRIEFING_COLOR_HEX`` constant
    in :mod:`weatherbot.branding` so the brand color cannot drift (IN-03). Fields
    match the webhook briefing exactly: ``Now`` = ``temp_display``,
    ``High / Low`` = ``"{high} / {low}"``, ``Rain`` = ``"{pct}%"``, plus a UTC timestamp.
    """
    embed = discord.Embed(
        title=f"Weather — {forecast.location}", color=BRIEFING_COLOR_INT
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
    daemon_state: DaemonState | None = None,
) -> Callable[[discord.Message], Awaitable[None]]:
    """Build the ``on_message`` coroutine handler (the guard ladder + registry dispatch).

    Returned as a standalone coroutine (rather than only registered on a client) so
    the gateway-free tests can drive it directly with a fake message. ``holder`` gives
    a lock-free ``current()`` config snapshot; ``cache`` is the per-location TTL cache;
    ``operator_id`` is the single allowed author; ``daemon_state`` is the read-only
    live-state accessor ``status`` reports from (``None`` in the gateway-free tests and
    when the daemon has no scheduler to expose).

    The guard ladder steps (1)-(3) and the non-propagating try/except envelope are
    UNCHANGED from the ``!weather`` design (CMD-16, Pitfall 5); only step (4) is now
    registry-driven (:func:`parse_command`), and the WHOLE registry dispatch lives
    INSIDE the EXISTING try/except — no second envelope. A command handler that raises
    surfaces as the generic error reply and NEVER propagates out of ``on_message`` /
    into the scheduler thread (CMD-16 failure isolation).

    DEFERRED (v1): ``operator_id`` is BAKED at construction, not re-read from
    ``holder.current()`` per message. A config reload that changes ``[bot] operator_id``
    is therefore NOT picked up by an already-running bot — changing the operator
    requires a process restart (see deploy/README "Reload behavior"). Live re-read is
    intentionally out of scope for v1.
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
        # (4) Parse against the command REGISTRY (CMD-09; strip the leading ``!``).
        #     A non-command (spec is None) is dropped exactly as before.
        parsed = parse_command(content[1:])
        if parsed.spec is None:
            return
        spec = parsed.spec
        arg = parsed.arg  # raw location (None → default) for location-taking commands

        # --- Reply path — wrapped so NOTHING propagates out of on_message (D-11). #
        #     The WHOLE registry dispatch stays INSIDE this one envelope (Pitfall 5):
        #     a handler that raises is caught here → generic reply, logged, never
        #     re-raised, never touching the scheduler thread (CMD-16).
        try:
            loop = asyncio.get_running_loop()
            config = holder.current()
            # Compute the reply payload inside the typing block, then perform a
            # SINGLE send after it so every send sits at the same level (WR-06).
            async with message.channel.typing():  # D-08 typing indicator
                if spec.takes_location:
                    # Forecast commands thread +day/-day/+compact flags through the
                    # SHARED grammar (identical to the CLI). The location for the
                    # lookup is the flag-stripped substring; the cache key is widened
                    # with a per-command/variant/flags suffix so a forecast result
                    # never collides with a plain !weather result (A5).
                    is_forecast = spec.group == "Forecast"
                    lookup_name = arg
                    flags = None
                    suffix = None
                    if is_forecast:
                        from weatherbot.interactive.command import (
                            forecast_cache_suffix,
                            parse_forecast_flags,
                        )

                        flags = parse_forecast_flags(arg)
                        lookup_name = flags.location
                        suffix = forecast_cache_suffix(spec.name, flags)
                    try:
                        # All blocking work OFF the loop (D-10, Pitfall 1): the cache
                        # lookup (resolve + fetch + render) gives the LookupResult the
                        # handler reads off the retained payload. Only forecast commands
                        # pass the widened-key ``suffix`` so a plain weather lookup keeps
                        # the original 2-arg cache call (back-compat).
                        if is_forecast:
                            result = await loop.run_in_executor(
                                None, cache.lookup, lookup_name, config, suffix
                            )
                        else:
                            result = await loop.run_in_executor(
                                None, cache.lookup, lookup_name, config
                            )
                    except UnknownLocationError as exc:
                        # CMD-02 error path: reply with the valid names, no embed.
                        await message.channel.send(str(exc))
                        return
                    if is_forecast:
                        reply = spec.handler(result, flags)
                    elif spec.name == "next-cloudy":
                        reply = spec.handler(result, config.cloud_threshold)
                    elif spec.name == "uv":
                        reply = spec.handler(result, config.uv.threshold)
                    else:
                        reply = spec.handler(result)
                elif spec.name == "status":
                    # status reads the injected read-only DaemonState (next-send /
                    # uptime / liveness / heartbeat). Run off-loop — read_heartbeat
                    # touches SQLite.
                    reply = await loop.run_in_executor(None, spec.handler, daemon_state)
                elif spec.name == "locations":
                    reply = spec.handler(config)
                else:  # help — no fetch, no config
                    reply = spec.handler()
                payload = render_embed(reply)
            await message.channel.send(embed=payload)
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
    daemon_state: DaemonState | None = None,
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
        holder=holder, operator_id=operator_id, cache=cache, daemon_state=daemon_state
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
        daemon_state: DaemonState | None = None,
    ) -> None:
        self._token = token
        self._client = build_client(
            holder=holder,
            operator_id=operator_id,
            cache=cache,
            daemon_state=daemon_state,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        # ``_loop_started`` signals only that the thread reached ``_amain`` and the
        # event loop is up (WR-03) — it does NOT imply a successful gateway login.
        # An invalid token raises ``LoginFailure`` AFTER this is set; that failure
        # surfaces later as a CRITICAL log in ``_run`` and flips ``_failed``.
        self._loop_started = threading.Event()
        # Set in the ``_run`` except handlers when the thread dies (WR-04). Lets the
        # daemon make a dead-start teardown explicit instead of inferring it from
        # ``loop.is_running()``. Failure isolation is preserved: ``_run`` never raises.
        self._failed = False
        self._thread = threading.Thread(
            target=self._run, name="weatherbot-discord", daemon=True
        )

    def start(self) -> None:
        """Start the bot thread and wait (up to 5s) for its event LOOP to come up.

        NOTE (WR-03): a returned ``start()`` means only that the bot loop started —
        NOT that the gateway authenticated/connected. An invalid token logs CRITICAL
        and flips ``is_alive()`` to False asynchronously; callers must consult
        ``is_alive()`` (not the mere return of ``start()``) to know the bot is live.
        """
        self._thread.start()
        if not self._loop_started.wait(timeout=5.0):
            _log.warning("bot thread did not signal loop-started within 5s")

    def is_alive(self) -> bool:
        """True unless the bot thread has died in ``_run`` (WR-04).

        Returns False once a ``LoginFailure`` / unexpected crash has been caught in
        ``_run`` (``_failed`` set) OR the underlying thread has exited. The daemon can
        use this to null out a confirmed-dead bot and skip a no-op ``stop()``.
        """
        return not self._failed and self._thread.is_alive()

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
        """Thread target: run the bot loop; isolate ALL failures here (D-11).

        On ANY failure the ``_failed`` flag is set (WR-04) so ``is_alive()`` reports
        a dead start, then the failure is SWALLOWED — it never propagates into the
        daemon thread (failure isolation, D-11).
        """
        try:
            asyncio.run(self._amain())
        except discord.LoginFailure:
            self._failed = True
            _log.critical(
                "invalid Discord token; inbound bot disabled, briefings unaffected"
            )
        except Exception:  # noqa: BLE001 — die alone; never crash the process (D-11)
            self._failed = True
            _log.critical("inbound bot thread crashed; briefings unaffected")

    async def _amain(self) -> None:
        """Bot loop entrypoint: record the loop, signal loop-started, then start the client."""
        self._loop = asyncio.get_running_loop()
        self._loop_started.set()
        async with self._client:
            await self._client.start(self._token)  # NOT the blocking Client.run helper
