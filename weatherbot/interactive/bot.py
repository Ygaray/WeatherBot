"""The inbound Discord read path — guard ladder, app embed render, off-loop fetch (CMD-02/07/08).

This module is the APP half of the read path ``operator -> guards -> cache -> embed reply``.
After the Phase-27 adapter relocation (SEAM-07, D-01/D-06) the generic gateway plumbing
(``BotThread`` / ``build_client`` / the persistent-view machinery / the create-before-delete
summon orchestration) lives in :mod:`yahir_reusable_bot.discord`; what STAYS here is the
irreducibly weather/house-style surface:

- :func:`render_embed` — the app embed builder (📍 indicator, ``BRIEFING_COLOR_INT``, the
  ``Updated <t:…>`` stamp, the WR-02 field-budget split). The module never owns a render;
  the composition root injects ``render_embed`` (via the ``_render_bridge`` closure) as the
  module ``PanelKit``'s opaque ``render`` (D-01). Its signature is UNCHANGED —
  ``render_embed(reply, *, location=None)`` — so the direct test callers stay byte-identical.
- :func:`build_inbound_embed` — the ``!weather`` inbound reply embed.
- :func:`build_on_message` — the guard ladder (author/operator/``!``-prefix) + the registry
  dispatch, plus the ``!panel`` lifecycle branch that delegates to an INJECTED app summon
  closure (the module owns the create-before-delete ordering; the app owns the channel
  resolution + operator copy + the panel factory).

Design decisions (from 11-RESEARCH / 11-PATTERNS) that ride the relocation unchanged:

- **Guard ladder ORDER (Pattern 2) is load-bearing.** ``on_message`` checks, in this
  exact order: (1) ``message.author.bot`` — drops the bot's OWN webhook briefing AND
  any other bot, the first backstop against a feedback loop (D-04, T-11-05); (2)
  ``author.id != operator_id`` — silently ignores every non-operator (D-05, T-11-06);
  (3) the ``!`` prefix; (4) ``parse_command`` (the shared registry parser, strips
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
"""

from __future__ import annotations

import asyncio
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
    "build_inbound_embed",
    "build_on_message",
    "build_panel_summon",
    "render_embed",
]

_log = structlog.get_logger(__name__)

_ERROR_REPLY = "Sorry — something went wrong fetching that."

# --------------------------------------------------------------------------- #
# !panel summon — the APP-SIDE thin half (PANEL-01, Plan 18-02; D-06 split).
# --------------------------------------------------------------------------- #
# The generic create-before-delete summon ORDERING + the permission-attribute set
# (``REQUIRED_PANEL_PERMS``) live in :mod:`yahir_reusable_bot.discord.gateway` (the
# perm set names Discord permissions, not a weather concept — A4). What stays HERE is
# the app surface: the channel resolution, the operator-feedback COPY (which names the
# ``[bot] panel_channel_id`` config key + the restart), the missing-perm copy, the idle
# embed, and the panel factory — all threaded into the module orchestration at the
# composition root (wiring.py build_runtime).

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
_PANEL_RESUMMONED = "Panel re-summoned — moved to the bottom of the channel."
_PANEL_CREATED = "Panel ready — posted and pinned a new control panel."
# A static idle reply rendered into the panel message's embed on post/re-summon.
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


def _location_label(spec, arg, *, was_bare: bool, config) -> str | None:
    """Compute the 📍 header label for an inbound reply (F27 restore + D-05 marker).

    Returns the location name to thread into ``render_embed(location=…)`` so the inbound
    path shows the 📍 indicator the panel always does (F27 parity — previously the
    inbound render passed no ``location=`` and the header was suppressed). The label:

    - a bare location-taking command (``was_bare``) → the resolved DEFAULT name with a
      literal ``" (default)"`` suffix (``📍 Toronto (default)``, D-05);
    - a named PLAIN location command → the resolved location name (``📍 London``);
    - anything else (argless info commands status/help/locations, or a forecast command
      whose ``arg`` carries flag tokens like ``"home +sat"``) → ``None`` so the 📍 header
      stays suppressed (D-01 — the marker rides only the plain location surface here).

    Resolution reuses ``resolve_location`` (config-derived, never the flag parser). An
    ``UnknownLocationError`` cannot reach here — a bad name already bubbled out of
    ``dispatch_spec`` and was answered upstream (CMD-02), so this only runs for a
    location that resolved cleanly.
    """
    from weatherbot.config import resolve_location

    if not getattr(spec, "takes_location", False):
        return None  # argless info command — keep 📍 suppressed (D-01)
    if getattr(spec, "needs_flags", False):
        return None  # forecast command: ``arg`` carries flags, out of this fix's scope
    # ``dispatch_spec`` already resolved this location successfully (the fetch ran), so
    # this re-resolve is for the DISPLAY NAME only. Guard it: a resolution hiccup must
    # only DROP the 📍 marker (a cosmetic header), never turn a good reply into the
    # generic error — the header is strictly additive to an already-rendered reply.
    try:
        if was_bare:
            return f"{resolve_location(config, None).name} (default)"  # D-05 marker
        return resolve_location(config, arg).name  # F27: named plain-location header
    except Exception:  # noqa: BLE001 — cosmetic marker only; never break the reply
        return None


def render_embed(reply: CommandReply, *, location: str | None = None) -> discord.Embed:
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
    # Description-level polish (PANEL-12/PANEL-13b). The ``<t:>`` markdown does NOT
    # render in an embed title, so both lines live in the description (D-07). Line
    # order (UI-SPEC): 📍 indicator (line 1, suppressed when argless — D-01) then
    # the self-ageing Updated stamp (line 2, always — D-06), then the existing fields.
    unix = int(discord.utils.utcnow().timestamp())
    desc_lines: list[str] = []
    if location is not None:  # suppress on argless replies (status/alerts) — D-01
        desc_lines.append(f"📍 {location}")
    desc_lines.append(f"Updated <t:{unix}:t> (<t:{unix}:R>)")

    embed = discord.Embed(
        title=_clip(reply.title, _MAX_TITLE),
        description="\n".join(desc_lines),
        color=BRIEFING_COLOR_INT,
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


def build_panel_summon(
    *,
    holder: ConfigHolder,
    render: Callable[..., discord.Embed],
    panel_factory: Callable[[], discord.ui.View],
    marker: str,
) -> Callable[[discord.Message], Awaitable[None]]:
    """Build the app-side ``!panel`` summon closure (PANEL-01; D-06 app half).

    The GENERIC create-before-delete ORDERING (pin-scan, post+pin-first, delete-prior,
    the per-write ``discord.Forbidden`` backstop) lives in the module
    :func:`yahir_reusable_bot.discord.gateway.summon_panel`. This builder owns the APP
    surface threaded into it:

    1. Resolve the configured channel (``holder.current().bot.panel_channel_id``). If the
       ``[bot]`` table / id is unset or the channel is inaccessible, send the operator a
       clear, actionable message naming ``[bot] panel_channel_id`` + the restart
       requirement and ABORT — never crash the bot thread (D-04).
    2. Eagerly preflight the exact permission set (incl. ``pin_messages``) imported from
       the module (``REQUIRED_PANEL_PERMS``). On any gap: log a CRITICAL naming the
       missing perm(s), tell the operator the specific gap, and REFUSE before any
       post/pin (no orphan, SC#4).
    3. Build the idle embed (via the injected app ``render``) + the marker-bound owned
       predicate + the operator-feedback callbacks, and hand them to the module
       ``summon_panel`` orchestration (which owns the no-zero-panel-window ordering).

    The returned coroutine runs INSIDE the existing ``on_message`` non-propagating
    envelope (no second envelope, Pitfall 6).
    """
    from weatherbot.interactive.commands import CommandReply
    from yahir_reusable_bot.discord.gateway import (
        REQUIRED_PANEL_PERMS,
        summon_panel,
    )
    from yahir_reusable_bot.discord.panelkit import is_owned_panel

    async def _summon(message: discord.Message) -> None:
        config = holder.current()
        bot_cfg = getattr(config, "bot", None)
        panel_channel_id = getattr(bot_cfg, "panel_channel_id", None)

        # (1) Resolve the configured channel — abort, not crash (D-04). --------- #
        # A VALID-but-wrong id can resolve to a non-text channel (Category/Voice/Forum)
        # that has no .pins()/.send(embed=, view=), and guild.me is None when the bot
        # is not (yet) cached as a member of the guild — permissions_for(None) would
        # raise (WR-03). Treat both as the "inaccessible" case so the operator gets
        # the actionable copy instead of the generic on_message error fallback.
        guild = message.guild
        channel = (
            guild.get_channel(panel_channel_id)
            if guild is not None and panel_channel_id is not None
            else None
        )
        me = getattr(getattr(channel, "guild", None), "me", None)
        if (
            channel is None
            or me is None
            or not hasattr(channel, "pins")
            or not hasattr(channel, "send")
        ):
            _log.error(
                "panel summon: panel channel unset, inaccessible, or not a text channel",
                panel_channel_id=panel_channel_id,  # non-secret id; never token/appid
            )
            await message.channel.send(_PANEL_CHANNEL_UNCONFIGURED)
            return

        # (2) Eager permission preflight — REFUSE before any write (SC#4). ------ #
        perms = channel.permissions_for(me)
        missing = [name for name in REQUIRED_PANEL_PERMS if not getattr(perms, name)]
        if missing:
            _log.critical(
                "panel summon blocked — missing channel permission(s)",
                missing=missing,
                channel_id=channel.id,  # non-secret structured field (Security V7)
            )
            await message.channel.send(_panel_missing_perms_copy(missing))
            return

        # (3) Hand the resolved channel + the app cosmetics to the module
        #     orchestration (the generic no-zero-panel-window ordering, D-06). ---- #
        idle_embed = render(
            CommandReply(title=_PANEL_IDLE_TITLE, text=_PANEL_IDLE_TEXT)
        )

        async def _on_created() -> None:
            await message.channel.send(_PANEL_CREATED)

        async def _on_resummoned() -> None:
            await message.channel.send(_PANEL_RESUMMONED)

        async def _on_strays_cleaned(n: int) -> None:
            await message.channel.send(_panel_strays_cleaned_copy(n))

        await summon_panel(
            channel=channel,
            bot_user=me,
            idle_embed=idle_embed,
            panel_factory=panel_factory,
            is_owned=lambda m: is_owned_panel(m, me, marker=marker),
            on_created=_on_created,
            on_resummoned=_on_resummoned,
            on_strays_cleaned=_on_strays_cleaned,
        )

    return _summon


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
    on_panel_summon: Callable[[discord.Message], Awaitable[None]] | None = None,
) -> Callable[[discord.Message], Awaitable[None]]:
    """Build the ``on_message`` coroutine handler (the guard ladder + registry dispatch).

    Returned as a standalone coroutine (rather than only registered on a client) so
    the gateway-free tests can drive it directly with a fake message. ``holder`` gives
    a lock-free ``current()`` config snapshot; ``cache`` is the per-location TTL cache;
    ``operator_id`` is the single allowed author; ``daemon_state`` is the read-only
    live-state accessor ``status`` reports from (``None`` in the gateway-free tests and
    when the daemon has no scheduler to expose). ``on_panel_summon`` is the INJECTED
    app summon closure (built by :func:`build_panel_summon` at the composition root, D-06)
    that the ``!panel`` lifecycle branch delegates to — ``None`` disables the branch (the
    gateway-free tests that never exercise ``!panel`` omit it).

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
            if on_panel_summon is None:
                return
            try:
                await on_panel_summon(message)
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
        # F02/D-05/F27: capture whether the operator gave NO location BEFORE dispatch
        # resolves the default app-side. A bare location-taking command resolves the
        # default (config.locations[0]) and its 📍 header is marked ``(default)``; a
        # named-arg reply shows ``📍 {name}`` unmarked (and, per F27, the inbound path
        # now passes ``location=`` so the 📍 header is no longer suppressed).
        was_bare = arg is None and spec.takes_location

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
                # F27/D-05: compute the 📍 header label for a location-taking reply so
                # the inbound path shows the same indicator the panel always does (F27
                # parity — previously suppressed by passing no ``location=``). For a
                # PLAIN location command (not forecast: those carry flag tokens in
                # ``arg``) resolve the name from config — the default when the operator
                # gave none (marked ``(default)``, D-05), else the named location. Argless
                # info commands (status/help/locations) keep ``location=None`` so their
                # 📍 stays suppressed (D-01).
                location_label = _location_label(
                    spec, arg, was_bare=was_bare, config=config
                )
                payload = render_embed(reply, location=location_label)
            await message.channel.send(embed=payload)
        except Exception:  # noqa: BLE001 — non-propagating handler (CMD-08, D-11)
            _log.exception("inbound handler failed")
            try:
                await message.channel.send(_ERROR_REPLY)
            except Exception:  # noqa: BLE001 — best-effort reply; never re-raise
                _log.exception("inbound error reply failed")

    return on_message

