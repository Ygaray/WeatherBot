"""The persistent operator panel — a tap-to-drive Discord component surface (Phase 17).

This module builds a single :class:`PanelView` (``discord.ui.View``, ``timeout=None``)
with static ``custom_id``s — a location ``Select`` (row 0), the five location-command
buttons (row 1: weather · uv · next-cloudy · sun · wind), and the two argless buttons
(row 2: status · alerts). Each child is derived from a curated name tuple resolved
through :data:`weatherbot.interactive.registry.BY_NAME`, so a registry rename fails LOUD
at construction (the build-time ``assert``) rather than at send time.

The panel is the THIRD caller of the Phase-16 ``dispatch_spec`` seam (after the bot's
``on_message`` and the CLI): a button callback maps ``custom_id → CommandSpec``, the
in-memory selected location → ``arg``, and ``await dispatch_spec(...)`` returns the
``CommandReply`` that ``render_embed`` turns into the in-place embed. No new on-loop
blocking I/O is added — ``dispatch_spec`` already runs the fetch + the whole reply ladder
off-loop via ``run_in_executor``.

Three load-bearing correctness mechanisms (all verified against discord.py 2.7.1,
17-RESEARCH Patterns 1–4):

1. **Single-ack defer-then-edit (D-14/D-15):** exactly ONE ``interaction.response.*``
   call per tap — ``response.edit_message(content="⏳ Fetching…", view=<disabled copy>)``
   (acks <3s, shows the cue, disables to stop double-taps) — then the result lands via
   ``interaction.edit_original_response(...)`` (the followup path, NOT a second
   ``response.*`` call, which would raise ``InteractionResponded``).
2. **Operator gate (D-11/D-12/D-13):** :meth:`PanelView.interaction_check` returns
   ``False`` for any non-operator (and any bot), sending a byte-exact identity-free
   ephemeral reject and emitting an explicit ``structlog`` reject log — because a clean
   ``return False`` does NOT fire ``View.on_error`` (verified), the reject log is the
   sole audit record.
3. **Failure isolation:** a per-callback non-propagating ``try/except`` PLUS a
   ``View.on_error`` backstop, because the ``on_message`` envelope structurally does not
   cover the component callback path. A raising callback can never reach the gateway loop
   / scheduler thread.

Imports follow the ``interactive/`` acyclic discipline (mirroring ``dispatch.py``/
``bot.py``): module-top light imports (``asyncio`` / ``discord`` / ``structlog`` + the
``registry`` / ``render_embed`` / ``dispatch_spec`` / ``UnknownLocationError`` seams),
heavy types under ``TYPE_CHECKING``, no in-handler lazy import.

Out of scope (deferred): persistent ``add_view`` registration (Phase 18), the forecast
button (Phase 19), emoji labels / visual selection indicator (Phase 20).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog

from weatherbot.interactive import registry
from weatherbot.interactive.bot import render_embed
from weatherbot.interactive.dispatch import dispatch_spec
from weatherbot.interactive.lookup import UnknownLocationError

if TYPE_CHECKING:
    from weatherbot.config.holder import ConfigHolder
    from weatherbot.interactive.cache import ForecastCache
    from weatherbot.interactive.state import DaemonState

__all__ = ["PanelView", "CmdButton", "LocationSelect"]

_log = structlog.get_logger(__name__)

# Discord component caps the library does NOT enforce at construction (Pitfall 5) —
# we assert these ourselves at build time so an overlong id/label fails LOUD here
# rather than as a generic HTTPException at send time.
_MAX_CUSTOM_ID = 100
_MAX_LABEL = 80
_MAX_ROWS = 5
_MAX_OPTIONS = 25

# The curated, ORDERED command tuples (the locked UI layout, 17-UI-SPEC). Row 1 is the
# five location-taking commands; row 2 is the two argless commands. Each name is asserted
# present in the registry at import so a registry rename trips here (D-06).
_LOCATION_CMDS: tuple[str, ...] = ("weather", "uv", "next-cloudy", "sun", "wind")
_ARGLESS_CMDS: tuple[str, ...] = ("status", "alerts")

for _name in (*_LOCATION_CMDS, *_ARGLESS_CMDS):
    assert _name in registry.BY_NAME, (  # noqa: S101 — build-time allow-list guard
        f"panel curated command {_name!r} is not in registry.BY_NAME — a registry "
        f"rename broke the panel layout"
    )

# Emoji-free Title-Case labels (17-UI-SPEC Copywriting Contract). Emoji labels are
# Phase 20; these are the plain-text labels.
_LABELS: dict[str, str] = {
    "weather": "Weather",
    "uv": "UV",
    "next-cloudy": "Next Cloudy",
    "sun": "Sun",
    "wind": "Wind",
    "status": "Status",
    "alerts": "Alerts",
}

# The transient cue shown on the single ack while the off-loop fetch runs (D-14).
_FETCHING_CUE = "⏳ Fetching…"
# Generic best-effort error copy for the failure-isolation path (V7 — identity-free).
_ERROR_REPLY = "Sorry — something went wrong."


class CmdButton(discord.ui.Button):
    """A panel command button — a static-``custom_id`` button delegating to ``on_command``.

    The button carries the registry command ``name`` and a back-reference to its owning
    :class:`PanelView`; its ``callback`` simply delegates to ``panel.on_command`` (which
    holds the single-ack contract + per-callback envelope). The ``custom_id`` is the
    deterministic ``wb:cmd:<name>`` so the assembled view is persistent (Phase 18 can
    ``add_view`` it).
    """

    def __init__(self, name: str, panel: "PanelView", *, row: int) -> None:
        super().__init__(
            label=_LABELS[name],
            custom_id=f"wb:cmd:{name}",
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self._name = name
        self._panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_command(interaction, self._name)


class LocationSelect(discord.ui.Select):
    """The location dropdown — a static-``custom_id`` Select delegating to ``on_select``.

    Options are derived per-construction from the passed location names (the live
    ``holder.current().locations`` snapshot), one ``SelectOption(label=n, value=n)`` each,
    so a hot-reload that adds/removes a location is reflected on (re)construction
    (PANEL-02). The callback delegates to ``panel.on_select`` with ``self.values[0]``;
    button callbacks NEVER re-read ``self.values`` (Pitfall 3 — empty outside an active
    select interaction).
    """

    def __init__(self, panel: "PanelView", locations: list[str]) -> None:
        super().__init__(
            custom_id="wb:loc:select",
            placeholder="Location",
            options=[discord.SelectOption(label=n, value=n) for n in locations],
            row=0,
        )
        self._panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_select(interaction, self.values[0])


class PanelView(discord.ui.View):
    """The persistent operator panel root (``timeout=None``, static-id children).

    Built from the four read-only deps it needs to drive the shared ``dispatch_spec``
    seam: ``holder`` (the lock-free ``current()`` config snapshot — read per tap so
    hot-reloads are picked up), ``operator_id`` (the single allowed tapper), ``cache``
    (the per-location TTL ``ForecastCache``), and an optional ``daemon_state`` (read-only
    live-state the ``status`` command reports from). The selected location is held in
    memory as :attr:`_selected_location`, defaulting to ``locations[0].name`` (D-03,
    mirroring ``resolve_location(config, None)``).
    """

    def __init__(
        self,
        *,
        holder: ConfigHolder,
        operator_id: int,
        cache: ForecastCache,
        daemon_state: DaemonState | None = None,
    ) -> None:
        super().__init__(timeout=None)  # REQUIRED for persistence (D-10)
        self._holder = holder
        self._operator_id = operator_id
        self._cache = cache
        self._daemon_state = daemon_state

        config = holder.current()
        locations = [loc.name for loc in config.locations]
        # Fail LOUD at construction with an actionable message: an empty config
        # (no [[locations]]) would otherwise raise a bare IndexError at
        # locations[0] below and build a Select with options=[] that Discord
        # rejects only at send time (HTTPException). This is the "fail at
        # construction" surface, so guard the >= 1 lower bound here (WR-01).
        if not locations:
            raise ValueError(
                "panel requires at least one configured location; "
                "config.locations is empty"
            )
        # D-03 default: the first configured location (mirrors resolve_location(config,
        # None)). Held in memory; the Select callback re-sets it (never re-read from the
        # Select's values inside a button callback — Pitfall 3).
        self._selected_location = locations[0]

        # row 0: the location dropdown.
        self.add_item(LocationSelect(self, locations))
        # row 1: the five location-taking command buttons (curated order).
        for name in _LOCATION_CMDS:
            self.add_item(CmdButton(name, self, row=1))
        # row 2: the two argless command buttons (curated order).
        for name in _ARGLESS_CMDS:
            self.add_item(CmdButton(name, self, row=2))
        # rows 3–4 intentionally empty (Phase 19/20).

        self._assert_layout(locations)

    def _assert_layout(self, locations: list[str]) -> None:
        """Build-time layout guard — assert the caps discord.py does NOT enforce.

        ``add_item`` / ``add_option`` already raise ``ValueError`` for the ≤5-per-row /
        ≤25-children / ≤25-options caps; the ``custom_id`` ≤100 and ``label`` ≤80 caps
        are the ones the library accepts silently and Discord rejects only at SEND time
        (Pitfall 5) — so we assert them here to fail LOUD at construction (D-10).
        """
        rows = {child.row for child in self.children if child.row is not None}
        assert len(rows) <= _MAX_ROWS, (  # noqa: S101
            f"panel uses {len(rows)} rows (>{_MAX_ROWS})"
        )
        assert len(locations) <= _MAX_OPTIONS, (  # noqa: S101
            f"panel has {len(locations)} locations (>{_MAX_OPTIONS} Select options)"
        )
        for child in self.children:
            custom_id = getattr(child, "custom_id", None)
            assert custom_id is not None and len(custom_id) <= _MAX_CUSTOM_ID, (  # noqa: S101
                f"panel child custom_id {custom_id!r} exceeds {_MAX_CUSTOM_ID} chars"
            )
            label = getattr(child, "label", None)
            if label is not None:
                assert len(label) <= _MAX_LABEL, (  # noqa: S101
                    f"panel child label {label!r} exceeds {_MAX_LABEL} chars"
                )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """The single operator gate — runs before EVERY child callback (D-11/D-12/D-13).

        Rejects any bot (defense-in-depth, mirroring the ``author.bot`` rung) and any
        non-operator. The reject is a SINGLE byte-exact identity-free ephemeral
        ``send_message`` (which both suppresses the foreign user's "interaction failed"
        toast and physically cannot edit the shared panel — D-11), plus an explicit
        ``structlog`` reject log. That log is the SOLE audit record: a clean ``return
        False`` does NOT route through ``on_error`` (verified vs discord.py 2.7.1
        ``_scheduled_task``), so the rejection would otherwise be invisible (D-13). The
        reject copy never interpolates the user / custom_id / command / operator (D-12).
        """
        if interaction.user.bot:
            # A clean `return False` does NOT route through on_error, so without
            # this log a bot-triggered reject would leave NO audit record at all
            # — mirror the non-operator branch so the reject log stays the SOLE
            # audit record for EVERY reject path (WR-02).
            _log.info(
                "panel reject (bot)",
                user_id=interaction.user.id,
                custom_id=(interaction.data or {}).get("custom_id"),
            )
            return False
        if interaction.user.id != self._operator_id:
            _log.info(
                "panel reject (non-operator)",
                user_id=interaction.user.id,
                custom_id=(interaction.data or {}).get("custom_id"),
            )
            await interaction.response.send_message(
                "This panel is in use by someone else.",  # D-12: generic, identity-free
                ephemeral=True,
            )
            return False
        return True

    async def on_select(self, interaction: discord.Interaction, value: str) -> None:
        """Persist the operator's location choice in memory (D-01/D-02, Pitfall 3).

        The selected location is held ONLY here (``self._selected_location``); button
        callbacks read this attribute and NEVER re-read ``Select.values`` (which is empty
        outside an active select interaction — #7284). The select interaction is acked
        with a single ``response.edit_message`` (the lightest valid ack that re-renders
        the panel in place) — no new message, no second ``response.*``.
        """
        try:
            self._selected_location = value
            await interaction.response.edit_message(view=self)
        except Exception:  # noqa: BLE001 — non-propagating (Task 3 backstop also covers)
            _log.exception("panel select callback failed", custom_id="wb:loc:select")
            await self._safe_error_edit(interaction)

    async def on_command(self, interaction: discord.Interaction, name: str) -> None:
        """Dispatch a tapped command through the shared seam and render in place (D-14).

        The single-ack contract: exactly ONE ``interaction.response.*`` call — the
        ``edit_message`` cue/ack that disables every component to neutralize double-taps
        — BEFORE the off-loop fetch; the result then lands via
        ``interaction.edit_original_response`` (the followup path, never a second
        ``response.*`` which would raise ``InteractionResponded``). The location arg comes
        from the in-memory ``_selected_location`` for location-taking commands and is
        ``None`` for argless commands (D-04). ``config = holder.current()`` is read here so
        a hot-reload is picked up per tap (PANEL-02). ``UnknownLocationError`` from
        ``dispatch_spec`` is caught at the call site and rendered as a generic in-place
        edit (mirrors ``on_message``'s D-06 call-site catch). The whole body's outer
        non-propagating envelope (Task 3) wraps the whole body so a raising handler can
        never cross into the gateway loop / scheduler thread (CMD-16 analog).
        """
        try:
            spec = registry.BY_NAME[name]  # allow-list (KeyError → caught below)
            arg = self._selected_location if spec.takes_location else None  # D-04
            # ① the SINGLE response.* call — acks (<3s), shows the cue, disables taps.
            await interaction.response.edit_message(
                content=_FETCHING_CUE, view=self._disabled_copy()
            )
            loop = asyncio.get_running_loop()
            config = self._holder.current()  # per-tap snapshot (hot-reload picked up)
            try:
                reply = await dispatch_spec(
                    spec,
                    arg,
                    cache=self._cache,
                    config=config,
                    loop=loop,
                    daemon_state=self._daemon_state,
                )
            except UnknownLocationError as exc:
                # Generic-but-helpful in-place edit (the valid names live in the message).
                await interaction.edit_original_response(
                    content=str(exc), embed=None, view=self
                )
                return
            # ② result lands via the FOLLOWUP path — NOT a second response.* call.
            await interaction.edit_original_response(
                content=None, embed=render_embed(reply), view=self
            )
        except Exception:  # noqa: BLE001 — non-propagating (Pitfall 1; mirrors bot.py:298)
            _log.exception("panel command callback failed", custom_id=f"wb:cmd:{name}")
            await self._safe_error_edit(interaction)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        """The ``View.on_error`` backstop — the LAST line of failure isolation (D-13).

        The per-callback ``try/except`` in ``on_command``/``on_select`` is the primary
        boundary; this override is the backstop for any callback exception that escapes it
        (the dead-button case), because the ``on_message`` envelope structurally does not
        cover the component path (Pitfall 1). It logs in ``structlog`` format and attempts
        a best-effort generic in-place answer, and NEVER re-raises.
        """
        _log.exception(
            "panel view on_error backstop",
            custom_id=getattr(item, "custom_id", None),
        )
        await self._safe_error_edit(interaction)

    def _disabled_copy(self) -> discord.ui.View:
        """Return a disabled clone of the panel for the transient-cue ack (D-14/D-15).

        Rebuilds a fresh ``timeout=None`` view carrying disabled clones of every child
        (same ``custom_id``/``label``/``style``/options), so the ack that shows the cue
        also neutralizes re-taps during the cold fetch. "Disable-only, no transient text"
        is the D-15-blessed fallback; here we pair it with the ``⏳ Fetching…`` content
        for the clearer cue.
        """
        view = discord.ui.View(timeout=None)
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                view.add_item(
                    discord.ui.Button(
                        label=child.label,
                        custom_id=child.custom_id,
                        style=child.style,
                        row=child.row,
                        disabled=True,
                    )
                )
            elif isinstance(child, discord.ui.Select):
                view.add_item(
                    discord.ui.Select(
                        custom_id=child.custom_id,
                        placeholder=child.placeholder,
                        options=list(child.options),
                        row=child.row,
                        disabled=True,
                    )
                )
        return view

    async def _safe_error_edit(self, interaction: discord.Interaction) -> None:
        """Best-effort generic in-place error answer — never re-raises (Pitfall 4).

        By the time a callback's envelope reaches here the single ``edit_message`` ack has
        almost always already fired, so the result/error surface is the followup path:
        ``edit_original_response`` edits the panel message in place (PANEL-06) without a
        second ``response.*`` ack. If the interaction was somehow NOT yet acked
        (``is_done()`` is False AND no original response exists), fall back to
        ``response.send_message`` ephemeral. The WHOLE helper is wrapped in its own
        try/except so a failed error reply (expired token, network) is swallowed — a
        best-effort answer must never re-raise into the gateway loop (mirrors
        ``bot.py:300-303``).
        """
        try:
            # Single path: always attempt the in-place followup edit first (the
            # common case — the ack edit_message already ran in the callback). Only
            # a truly un-acked interaction needs the send_message fallback, gated on
            # `not is_done()` so an already-acked interaction's failed edit logs
            # rather than raising a redundant InteractionResponded (IN-01).
            try:
                await interaction.edit_original_response(
                    content=_ERROR_REPLY, embed=None, view=self
                )
            except Exception:  # noqa: BLE001
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        _ERROR_REPLY, ephemeral=True
                    )
                else:
                    _log.exception("panel error reply failed")
        except Exception:  # noqa: BLE001 — best-effort error reply; never re-raise
            _log.exception("panel error reply failed")
