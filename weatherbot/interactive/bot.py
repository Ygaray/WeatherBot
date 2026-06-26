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
from weatherbot.interactive.dispatch import dispatch_spec
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

# --------------------------------------------------------------------------- #
# !panel summon (PANEL-01, Plan 18-02).
# --------------------------------------------------------------------------- #

# The exact channel permissions the summon preflights BEFORE any write (D-10).
# ⚠️ ``pin_messages``, NOT ``manage_messages`` — Discord split PIN_MESSAGES out of
# MANAGE_MESSAGES (effective 2026-01-12) and discord.py 2.7 exposes the new bit as
# ``Permissions.pin_messages``; checking ``manage_messages`` would falsely pass on a
# server that granted only the new "Pin Messages" permission.
_REQUIRED_PANEL_PERMS: tuple[str, ...] = (
    "view_channel",
    "send_messages",
    "embed_links",
    "read_message_history",
    "pin_messages",
)

# IN-02: map the raw discord.py permission attribute names to the labels the operator
# actually sees in the Discord permission UI, so the missing-permission reply names the
# exact toggle to flip. The raw attribute names stay in the structured log (Security V7).
_PANEL_PERM_LABELS: dict[str, str] = {
    "view_channel": "View Channel",
    "send_messages": "Send Messages",
    "embed_links": "Embed Links",
    "read_message_history": "Read Message History",
    "pin_messages": "Pin Messages",
}

# Operator-feedback copy (18-UI-SPEC Copywriting Contract) — plain-text, emoji-free,
# identity-free, secret-free. The missing-permission / channel-misconfig strings NAME
# the specific fix (which perm / the config key + restart) so the operator can act.
# IN-01: panel_channel_id is now a REQUIRED BotConfig field, so config fails to load
# without it — this branch can only be reached via the *inaccessible* case (stale id,
# bot not in the server, or a non-text channel), never a literal "not set". Lead with
# the inaccessible framing while still naming the config key + restart the operator
# would change to repoint the panel.
_PANEL_CHANNEL_UNCONFIGURED = (
    "Can't reach the configured panel channel — check the channel exists, that I'm "
    "in that server, and that it's a text channel. If you need to repoint it, update "
    "[bot] panel_channel_id and restart."
)
_PANEL_REUSED = "Panel ready — reusing the existing pinned panel."
_PANEL_CREATED = "Panel ready — posted and pinned a new control panel."
# A static idle reply rendered into the panel message's embed on post/reuse.
_PANEL_IDLE_TITLE = "WeatherBot Control Panel"
_PANEL_IDLE_TEXT = (
    "Pick a location, then tap a command. The panel stays here and survives restarts."
)


def _panel_missing_perms_copy(missing: list[str]) -> str:
    """Operator copy naming the specific missing channel permission(s) (D-11).

    IN-02: translates the raw discord.py attribute names (``pin_messages``) to the
    Discord UI labels the operator sees (``Pin Messages``) so the reply names the exact
    toggle to flip. Unknown names fall back to their raw form. The structured log keeps
    the raw attribute names.
    """
    labels = [_PANEL_PERM_LABELS.get(name, name) for name in missing]
    return (
        f"Can't summon the panel — I'm missing the {', '.join(labels)} "
        f"permission(s) in that channel."
    )


def _panel_strays_cleaned_copy(n: int) -> str:
    """Operator copy for the reuse-and-cleanup branch with a non-secret count (D-06)."""
    return f"Panel ready — kept one panel and removed {n} stray panel(s)."


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


async def _handle_panel_summon(
    message: discord.Message,
    *,
    holder: ConfigHolder,
    operator_id: int,
    cache: ForecastCache,
    daemon_state: DaemonState | None,
) -> None:
    """Idempotent ``!panel`` summon: find-or-create exactly one pinned panel (PANEL-01).

    A lifecycle WRITE command (D-07) — NOT routed through ``dispatch_spec``/the registry.
    Runs INSIDE the existing ``on_message`` non-propagating envelope (no second envelope,
    Pitfall 6); each Discord write is additionally guarded by an inner
    ``discord.Forbidden`` catch (the TOCTOU backstop, D-09).

    Sequence:

    1. Resolve the configured channel (``holder.current().bot.panel_channel_id``). If the
       ``[bot]`` table / id is unset or the channel is inaccessible, send the operator a
       clear, actionable message naming ``[bot] panel_channel_id`` + the restart
       requirement and ABORT — never crash the bot thread (D-04).
    2. Eagerly preflight the exact D-10 permission set (incl. ``pin_messages``). On any
       gap: log a CRITICAL naming the missing perm(s), tell the operator the specific
       gap, and REFUSE before any post/pin (no orphan, SC#4).
    3. Scan the channel's pins for bot-owned panels (``_is_owned_panel``, D-03/D-05) and
       reuse the first in place + delete the strays (D-06), or post+pin a fresh panel.
    """
    # Deferred import — panel.py imports render_embed FROM this module, so a module-top
    # PanelView import would create an import cycle (interactive/ acyclicity).
    from weatherbot.interactive.commands import CommandReply
    from weatherbot.interactive.panel import PanelView, _is_owned_panel

    config = holder.current()
    bot_cfg = getattr(config, "bot", None)
    panel_channel_id = getattr(bot_cfg, "panel_channel_id", None)

    # (1) Resolve the configured channel — abort, not crash (D-04). ------------- #
    # A VALID-but-wrong id can resolve to a non-text channel (Category/Voice/Forum)
    # that has no .pins()/.send(embed=, view=), and guild.me is None when the bot is
    # not (yet) cached as a member of the guild — permissions_for(None) would raise
    # (WR-03). Treat both as the "inaccessible" case so the operator gets the
    # actionable copy instead of the generic on_message error-envelope fallback.
    guild = message.guild
    channel = (
        guild.get_channel(panel_channel_id)
        if guild is not None and panel_channel_id is not None
        else None
    )
    # Duck-type the channel rather than isinstance-checking discord.abc.Messageable:
    # a TextChannel/Thread exposes .pins() and .send(); a CategoryChannel (the most
    # likely valid-but-wrong id) exposes neither. hasattr is also fake-friendly for
    # the gateway-free tests. guild.me is None when the bot is not cached as a member.
    me = getattr(getattr(channel, "guild", None), "me", None)
    if (
        channel is None
        or me is None
        or not hasattr(channel, "pins")
        or not hasattr(channel, "send")
    ):
        _log.error(
            "panel summon: panel channel unset, inaccessible, or not a text channel",
            panel_channel_id=panel_channel_id,  # non-secret id; never the token/appid
        )
        await message.channel.send(_PANEL_CHANNEL_UNCONFIGURED)
        return

    # (2) Eager permission preflight (D-09/D-10) — REFUSE before any write (SC#4). #
    perms = channel.permissions_for(me)
    missing = [name for name in _REQUIRED_PANEL_PERMS if not getattr(perms, name)]
    if missing:
        _log.critical(
            "panel summon blocked — missing channel permission(s)",
            missing=missing,
            channel_id=channel.id,  # non-secret structured field (Security V7)
        )
        await message.channel.send(_panel_missing_perms_copy(missing))
        return

    # (3) Find-or-create-one + cleanup, with a per-write Forbidden backstop (D-09). #
    def _build_view() -> PanelView:
        return PanelView(
            holder=holder,
            operator_id=operator_id,
            cache=cache,
            daemon_state=daemon_state,
        )

    idle_embed = render_embed(
        CommandReply(title=_PANEL_IDLE_TITLE, text=_PANEL_IDLE_TEXT)
    )

    try:
        # Async iterator — NOT ``await channel.pins()`` (deprecated awaitable, D-03).
        # Discord caps pins at 50, so no pagination is needed.
        matches = [m async for m in channel.pins() if _is_owned_panel(m, me)]
        if not matches:
            # Recreate: post a fresh panel and pin it (D-06).
            msg = await channel.send(embed=idle_embed, view=_build_view())
            await msg.pin()
            await message.channel.send(_PANEL_CREATED)
            return
        # Reuse the survivor in place (keeps its pin position + history); the view stays
        # live because add_view re-binds by custom_id (D-06).
        await matches[0].edit(embed=idle_embed, view=_build_view())
        strays = matches[1:]
        for extra in strays:
            # DELETE the strays (never unpin-only — an unpinned-but-live View still
            # responds to clicks, D-06).
            await extra.delete()
        if strays:
            await message.channel.send(_panel_strays_cleaned_copy(len(strays)))
        else:
            await message.channel.send(_PANEL_REUSED)
    except discord.Forbidden:
        # TOCTOU backstop: a permission was revoked between the eager preflight and a
        # write. Log CRITICAL and return — never let the 403 bubble out of on_message
        # (D-09). Never leak the token; channel_id is a non-secret structured field.
        _log.critical(
            "panel summon write forbidden (403) despite preflight",
            channel_id=channel.id,
        )
        return


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
        # (3b) !panel is a lifecycle/WRITE command (D-07) handled HERE in the
        #      operator-gated path — it does NOT route through the registry /
        #      dispatch_spec. It rides this SAME non-propagating envelope (Pitfall 6);
        #      its per-write discord.Forbidden catch is the precise inner case (D-09).
        if content.strip() == "!panel":
            try:
                await _handle_panel_summon(
                    message,
                    holder=holder,
                    operator_id=operator_id,
                    cache=cache,
                    daemon_state=daemon_state,
                )
            except Exception:  # noqa: BLE001 — non-propagating (CMD-08, D-11)
                _log.exception("panel summon failed")
                try:
                    await message.channel.send(_ERROR_REPLY)
                except Exception:  # noqa: BLE001 — best-effort reply; never re-raise
                    _log.exception("panel summon error reply failed")
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
                # The arg-adaptation ladder + off-loop fetch live in the SHARED
                # dispatcher (Phase 16, PANEL-10) so the bot, the CLI, and the panel
                # can never drift. dispatch_spec owns the forecast-flags parse + the
                # off-loop cache fetch + the off-loop ladder (status->SQLite stays off
                # the loop); UnknownLocationError still BUBBLES so the surface-specific
                # CMD-02 reply stays HERE at the call site (D-06).
                try:
                    reply = await dispatch_spec(
                        spec,
                        arg,
                        cache=cache,
                        config=config,
                        loop=loop,
                        daemon_state=daemon_state,
                    )
                except UnknownLocationError as exc:
                    # CMD-02 error path: reply with the valid names, no embed.
                    await message.channel.send(str(exc))
                    return
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

    The configured panel channel (D-04, ``[bot] panel_channel_id``) is NOT threaded
    in as a constructor parameter: the ``!panel`` summon re-reads it live from
    ``holder.current().bot.panel_channel_id`` at summon time (see
    :func:`_handle_panel_summon`). Because ``[bot]`` keys are read-once-at-startup
    (restart-boundary tech debt, D-04) the live holder read is the same value as at
    construction — so the summon follows the configured channel without the bot
    caching a separate copy.

    Persistent-view registration (PANEL-09, D-12/D-13): ``setup_hook`` — which
    discord.py invokes ONCE per process, before the first gateway connect (unlike
    ``on_ready``, which re-fires on every reconnect) — registers the
    :class:`~weatherbot.interactive.panel.PanelView` via ``client.add_view``. That
    re-binds the already-pinned panel's button/select callbacks purely by their
    static ``custom_id`` after a ``systemctl restart``, with no boot-time scan.
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
    async def setup_hook() -> None:
        # Runs ONCE per process pre-connect (NOT on_ready — D-13: on_ready re-fires
        # on every gateway reconnect → duplicate persistent-view registrations).
        # PanelView is imported HERE (deferred), never at module top: panel.py imports
        # render_embed FROM this module (panel.py:53), so a module-top import would
        # create an import cycle (the interactive/ acyclicity discipline).
        from weatherbot.interactive.panel import PanelView

        # add_view is a purely-local call (no network/await) → safe before connect.
        client.add_view(
            PanelView(
                holder=holder,
                operator_id=operator_id,
                cache=cache,
                daemon_state=daemon_state,
            )
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
