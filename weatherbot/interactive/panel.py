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
from collections import Counter
from typing import TYPE_CHECKING

import discord
import structlog

from weatherbot.interactive import registry
from weatherbot.interactive.bot import render_embed
from weatherbot.interactive.command import ForecastFlags
from weatherbot.interactive.dispatch import dispatch_spec
from weatherbot.interactive.lookup import UnknownLocationError

if TYPE_CHECKING:
    from weatherbot.config.holder import ConfigHolder
    from weatherbot.interactive.cache import ForecastCache
    from weatherbot.interactive.state import DaemonState

__all__ = [
    "PanelView",
    "CmdButton",
    "LocationSelect",
    "ForecastButton",
    "ForecastToggleButton",
]

_log = structlog.get_logger(__name__)

# Discord component caps the library does NOT enforce at construction (Pitfall 5) —
# we assert these ourselves at build time so an overlong id/label fails LOUD here
# rather than as a generic HTTPException at send time.
_MAX_CUSTOM_ID = 100
_MAX_LABEL = 80
_MAX_ROWS = 5
_MAX_OPTIONS = 25
# The revealed panel is 5/5 rows, 13/25 children — full height, zero spare row
# (D-06/D-08). ``add_item``/``add_option`` already raise for these caps, but a
# hand-built over-cap child set (or a future addition) would slip past silently, so
# the now-load-bearing ``_assert_layout`` asserts them explicitly (D-08).
_MAX_PER_ROW = 5
_MAX_CHILDREN = 25

# The curated, ORDERED command tuples (the locked UI layout, 17-UI-SPEC). Row 1 is the
# five location-taking commands; row 2 is the two argless commands. Each name is asserted
# present in the registry at import so a registry rename trips here (D-06).
_LOCATION_CMDS: tuple[str, ...] = ("weather", "uv", "next-cloudy", "sun", "wind")
_ARGLESS_CMDS: tuple[str, ...] = ("status", "alerts")
# The two forecast specs the reveal sub-grid resolves (Phase 19). Both rows of the
# 2×2 grid route through these (variant is the per-button delta, not a separate spec).
_FORECAST_CMDS: tuple[str, ...] = ("weekday-forecast", "weekend-forecast")

for _name in (*_LOCATION_CMDS, *_ARGLESS_CMDS, *_FORECAST_CMDS):
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

# Phase 20 (PANEL-13a / D-04 / D-05): the LOCKED emoji glyph per command, applied via the
# SEPARATE discord.py ``emoji=`` param — NEVER concatenated into the ``_LABELS`` text label
# (the client renders icon + text with native spacing; the text label is kept for
# screen-reader naming). A parallel dict mirroring ``_LABELS`` (D-04/D-05 executor
# discretion). The forecast/toggle buttons carry their glyphs at their own construction
# sites (they are not in ``_LABELS``). Byte-exact to the 20-UI-SPEC Copywriting Contract.
_EMOJI: dict[str, str] = {
    "weather": "🌡️",
    "uv": "🧴",
    "next-cloudy": "☁️",
    "sun": "☀️",
    "wind": "💨",
    "status": "🟢",
    "alerts": "⚠️",
}

# The transient cue shown on the single ack while the off-loop fetch runs (D-14).
_FETCHING_CUE = "⏳ Fetching…"
# Generic best-effort error copy for the failure-isolation path (V7 — identity-free).
_ERROR_REPLY = "Sorry — something went wrong."

# The unforgeable bot-owned panel marker (D-05): every panel component carries a
# static ``wb:``-prefixed custom_id (``wb:cmd:<name>`` / ``wb:loc:select`` above), so a
# message that has ANY ``wb:`` child AND was authored by the bot is OUR panel. This is
# the identity the Plan-02 ``!panel`` scan keys on to find-or-reuse exactly one panel
# and to delete strays — without it the scan would risk touching an unrelated bot pin.
_PANEL_MARKER = "wb:"


def _is_owned_panel(msg: discord.Message, bot_user: discord.abc.User) -> bool:
    """Return True iff ``msg`` is a panel THIS bot owns (D-05 — author + wb: marker).

    Two conditions, both required (author-alone was rejected — it would risk deleting
    an unrelated pinned bot message such as a future alert post):

    1. ``msg.author`` and ``bot_user`` share the same snowflake ``.id`` — the message
       was authored by the bot itself.
    2. SOME child component carries a ``custom_id`` starting with ``_PANEL_MARKER``
       (``wb:``) — the unforgeable static marker only the panel's children carry.

    The author check compares ``.id`` EXPLICITLY (IN-04) rather than leaning on
    ``Member``/``User`` ``__eq__``: ``bot_user`` is ``guild.me`` (a ``Member``) while
    ``msg.author`` of a pinned bot message may be a ``Member`` OR a ``User`` depending
    on cache state. discord.py's ``__eq__`` already compares by snowflake id, but the
    explicit ``getattr(..., "id", None)`` comparison makes the "don't touch foreign
    pins" intent self-evident and independent of that library contract. A missing id on
    either side yields ``None != None`` → not owned, the safe default.

    The component walk mirrors ``_assert_layout``'s defensive ``getattr`` discipline:
    a row without ``.children`` (``getattr(row, "children", [])``) or a child without
    ``.custom_id`` (``getattr(child, "custom_id", None)``) is skipped, never raised on —
    so an unexpected component shape can't crash the scan inside the bot thread.
    """
    author_id = getattr(msg.author, "id", None)
    bot_id = getattr(bot_user, "id", None)
    if author_id is None or bot_id is None or author_id != bot_id:
        return False
    for row in msg.components:
        for child in getattr(row, "children", []):
            cid = getattr(child, "custom_id", None)
            if cid is not None and cid.startswith(_PANEL_MARKER):
                return True
    return False


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
            emoji=_EMOJI[name],  # D-04: SEPARATE param, never concatenated into label
            custom_id=f"wb:cmd:{name}",
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self._name = name
        self._panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_command(interaction, self._name)


class ForecastButton(discord.ui.Button):
    """A forecast variant sub-button — carries ``(command_name, variant)`` (Phase 19).

    The four sub-grid buttons (``Weekday Detailed`` … ``Weekend Compact``) each hold the
    registry forecast command name (``weekday-forecast`` / ``weekend-forecast``) AND a
    variant literal (``"detailed"`` / ``"compact"``) plus a back-reference to the owning
    :class:`PanelView`. The callback delegates to ``panel.on_forecast`` (which builds the
    ``ForecastFlags`` directly and routes through the shared ``dispatch_spec`` seam). The
    style is a uniform ``primary`` — the four variants are equal-weight read-only
    triggers; meaning is carried by the text LABEL alone, never colour (UI-SPEC Color).

    It is a plain ``discord.ui.Button`` subclass on purpose (D-09): the existing
    ``_render_view`` ``isinstance(child, discord.ui.Button)`` branch already rebuilds it
    for the disabled-ack / reveal-collapse clones with no new branch.
    """

    def __init__(
        self,
        panel: "PanelView",
        command_name: str,
        variant: str,
        *,
        custom_id: str,
        label: str,
        emoji: str,
        row: int,
    ) -> None:
        super().__init__(
            label=label,
            emoji=emoji,  # D-04: SEPARATE param, never concatenated into label
            custom_id=custom_id,
            style=discord.ButtonStyle.primary,  # uniform — no per-variant colour
            row=row,
        )
        self._command_name = command_name
        self._variant = variant
        self._panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_forecast(
            interaction, command_name=self._command_name, variant=self._variant
        )


class ForecastToggleButton(discord.ui.Button):
    """The Forecast disclosure toggle (row 2) — reveals/collapses the sub-grid (D-07).

    A static-``custom_id`` (``wb:forecast:toggle``) button whose ``callback`` delegates to
    ``panel.on_forecast_toggle`` (a plain reveal/collapse swap — no fetch). The ``Forecast``
    label carries the meaning (a textual caret would be a permitted structural affordance,
    NOT an emoji — D-07); the ``secondary`` style marks it as a disclosure affordance, but
    no meaning relies on colour (UI-SPEC Color / accessibility). It is a plain
    ``discord.ui.Button`` subclass for the same D-09 reason as :class:`ForecastButton`.
    """

    def __init__(self, panel: "PanelView", *, row: int) -> None:
        super().__init__(
            label="Forecast",
            emoji="📅",  # D-05 locked toggle glyph (D-04: separate from the label)
            custom_id="wb:forecast:toggle",
            style=discord.ButtonStyle.secondary,
            row=row,
        )
        self._panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_forecast_toggle(interaction)


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
            # D-02 (PANEL-12): mark the selected option default=True, derived from the
            # in-memory ``_selected_location`` (already set before this add_item in
            # PanelView.__init__) — NEVER from Select.values (Pitfall 3 / discord.py #7284).
            options=[
                discord.SelectOption(
                    label=n, value=n, default=(n == panel._selected_location)
                )
                for n in locations
            ],
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
        # In-memory reveal state (D-03/D-04): the sub-grid is hidden by default and
        # after every non-toggle action; only the Forecast toggle flips it. Display-only
        # — it never mutates the registered view (the canonical view holds all 13 children
        # regardless; reveal/collapse is a cosmetic _render_view swap, Pattern 1).
        self._expanded = False

        # row 0: the location dropdown.
        self.add_item(LocationSelect(self, locations))
        # row 1: the five location-taking command buttons (curated order).
        for name in _LOCATION_CMDS:
            self.add_item(CmdButton(name, self, row=1))
        # row 2: the two argless command buttons, then the Forecast toggle LAST
        # (UI-SPEC order: Status · Alerts · Forecast).
        for name in _ARGLESS_CMDS:
            self.add_item(CmdButton(name, self, row=2))
        self.add_item(ForecastToggleButton(self, row=2))
        # rows 3–4: the 2×2 forecast sub-grid (curated order, UI-SPEC / D-06).
        # row 3 = weekday pair, row 4 = weekend pair. ALL build in __init__ so add_view
        # registers every custom_id (Pattern 1 — never add_item/remove_item post-reg).
        self.add_item(
            ForecastButton(
                self, "weekday-forecast", "detailed",
                custom_id="wb:fc:weekday:detailed", label="Weekday Detailed",
                emoji="📋", row=3,
            )
        )
        self.add_item(
            ForecastButton(
                self, "weekday-forecast", "compact",
                custom_id="wb:fc:weekday:compact", label="Weekday Compact",
                emoji="📝", row=3,
            )
        )
        self.add_item(
            ForecastButton(
                self, "weekend-forecast", "detailed",
                custom_id="wb:fc:weekend:detailed", label="Weekend Detailed",
                emoji="🏖️", row=4,
            )
        )
        self.add_item(
            ForecastButton(
                self, "weekend-forecast", "compact",
                custom_id="wb:fc:weekend:compact", label="Weekend Compact",
                emoji="🌴", row=4,
            )
        )

        self._assert_layout(locations)

    def _assert_layout(self, locations: list[str]) -> None:
        """Build-time layout guard — assert the FULL revealed panel fits (D-08).

        Delegates to :meth:`_assert_layout_children` over this view's own children. The
        panel is now at 5/5 rows / 13 children, so this guard is LOAD-BEARING: any future
        component row or extra child trips it at construction rather than at send time
        (Pitfall 5).
        """
        self._assert_layout_children(self.children, locations)

    def _assert_layout_children(self, children, locations: list[str]) -> None:
        """Assert an arbitrary child set fits Discord's caps (D-08 — the load-bearing guard).

        Split out from :meth:`_assert_layout` so the dedicated overflow test can drive a
        hand-built over-cap child set WITHOUT going through ``add_item`` (which would raise
        its own ``ValueError`` for the per-row / total caps before this guard runs). Caps:

        - ``≤ _MAX_ROWS`` distinct rows,
        - ``≤ _MAX_PER_ROW`` children per row [D-08 — was only enforced by ``add_item``],
        - ``≤ _MAX_CHILDREN`` children total [D-08 — was unchecked],
        - ``≤ _MAX_OPTIONS`` Select options,
        - each ``custom_id`` ``≤ _MAX_CUSTOM_ID`` and each ``label`` ``≤ _MAX_LABEL``
          (the two the library accepts silently — Pitfall 5).
        """
        rows = {child.row for child in children if child.row is not None}
        assert len(rows) <= _MAX_ROWS, (  # noqa: S101
            f"panel uses {len(rows)} rows (>{_MAX_ROWS})"
        )
        per_row = Counter(
            child.row for child in children if child.row is not None
        )
        for row, count in per_row.items():
            assert count <= _MAX_PER_ROW, (  # noqa: S101
                f"panel row {row} has {count} children (>{_MAX_PER_ROW} per row)"
            )
        assert len(children) <= _MAX_CHILDREN, (  # noqa: S101
            f"panel has {len(children)} children (>{_MAX_CHILDREN} total)"
        )
        assert len(locations) <= _MAX_OPTIONS, (  # noqa: S101
            f"panel has {len(locations)} locations (>{_MAX_OPTIONS} Select options)"
        )
        for child in children:
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
            #
            # INTENTIONAL asymmetry (WR-03): unlike the non-operator branch below,
            # this branch deliberately sends NO ephemeral ``response.*`` ack. A bot
            # actor needs no human-readable feedback, so we let Discord's "interaction
            # failed" toast fire on the triggering client rather than spend the single
            # ack on a machine. Do NOT "fix" this into a double-ack — the missing
            # ephemeral here is by design, not an oversight.
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
            # A dropdown change is a non-toggle action → render the collapsed base (D-04).
            self._expanded = False
            await interaction.response.edit_message(
                view=self._render_view(expanded=False)
            )
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
            # The ack reflects the LIVE _expanded state (WR-01): a plain command tapped
            # while collapsed must NOT flash the forecast sub-grid open for the duration
            # of the off-loop fetch — disable the *currently displayed* layout, not a
            # force-expanded one. (on_forecast keeps expanded=True since its grid is
            # already revealed at tap time.)
            await interaction.response.edit_message(
                content=_FETCHING_CUE,
                view=self._render_view(expanded=self._expanded, disabled=True),
            )
            loop = asyncio.get_running_loop()
            config = self._holder.current()  # per-tap snapshot (hot-reload picked up)
            # A command tap is a non-toggle action → the result render collapses (D-04).
            self._expanded = False
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
                # Generic-but-helpful in-place edit + collapse (the valid names live in
                # the message). The collapsed base view is attached (D-04).
                await interaction.edit_original_response(
                    content=str(exc),
                    embed=None,
                    view=self._render_view(expanded=False),
                )
                return
            # ② result lands via the FOLLOWUP path — NOT a second response.* call; the
            # collapsed base view is attached so any non-forecast tap collapses (D-04).
            await interaction.edit_original_response(
                content=None,
                # PANEL-12: thread the selected location into the shared render so the 📍
                # indicator line shows — ``arg`` is the _selected_location for
                # location-taking commands and ``None`` for argless (status/alerts), so
                # the indicator auto-suppresses on argless results (D-01).
                embed=render_embed(reply, location=arg),
                view=self._render_view(expanded=False),
            )
        except Exception:  # noqa: BLE001 — non-propagating (Pitfall 1; mirrors bot.py:298)
            _log.exception("panel command callback failed", custom_id=f"wb:cmd:{name}")
            await self._safe_error_edit(interaction)

    async def on_forecast(
        self, interaction: discord.Interaction, *, command_name: str, variant: str
    ) -> None:
        """Dispatch a forecast variant through the SHARED seam and render-then-collapse.

        Mirrors :meth:`on_command`'s single-ack contract + per-callback envelope EXACTLY,
        differing only in (Pattern 3): it builds a ``ForecastFlags`` DIRECTLY and passes
        ``flags=`` (rather than a re-parsed arg string), and BOTH terminal renders attach
        the COLLAPSED base view (D-03 result-then-collapse / D-04).

        - ``spec = registry.BY_NAME[command_name]`` — ``command_name`` is one of two
          compile-time literals (``weekday-forecast`` / ``weekend-forecast``); a typo
          KeyErrors into the envelope.
        - ``flags = ForecastFlags(variant=variant, location=self._selected_location)`` —
          ``add``/``drop`` stay at their ``frozenset()`` defaults (the command name encodes
          the day set — D-01). ``variant`` is a compile-time literal; the location is the
          already-validated in-memory selection, NEVER a re-read of ``Select.values``
          (Pitfall 5). No user-typed string reaches the bypassed parser (Security V5).
        - The SINGLE ``response.edit_message`` ack shows the cue AND disables the
          expanded panel (``_render_view(expanded=True, disabled=True)``) so a double-tap
          on the revealed grid is neutralized during the cold fetch (T-19-02-05).
        - The result / ``UnknownLocationError`` both land via ``edit_original_response``
          with the COLLAPSED base view — never a second ``response.*`` (Pitfall 2).
        """
        try:
            spec = registry.BY_NAME[command_name]  # allow-list (KeyError → caught below)
            # D-01: build the flags DIRECTLY from the in-memory selection (Pitfall 5).
            flags = ForecastFlags(
                variant=variant, location=self._selected_location
            )
            # ① the SINGLE response.* call — acks (<3s), shows the cue, disables the
            # revealed grid so double-taps during the cold fetch are neutralized.
            await interaction.response.edit_message(
                content=_FETCHING_CUE,
                view=self._render_view(expanded=True, disabled=True),
            )
            loop = asyncio.get_running_loop()
            config = self._holder.current()  # per-tap snapshot (hot-reload picked up)
            # A forecast tap is a non-toggle action → the result render collapses (D-04).
            self._expanded = False
            try:
                reply = await dispatch_spec(
                    spec,
                    None,  # the flags= path passes arg=None (D-01)
                    cache=self._cache,
                    config=config,
                    loop=loop,
                    daemon_state=self._daemon_state,
                    flags=flags,
                )
            except UnknownLocationError as exc:
                # Generic-but-helpful in-place edit + collapse (D-03/D-04).
                await interaction.edit_original_response(
                    content=str(exc),
                    embed=None,
                    view=self._render_view(expanded=False),
                )
                return
            # ② result + collapse via the FOLLOWUP path — NOT a second response.* (D-03).
            await interaction.edit_original_response(
                content=None,
                # PANEL-12: forecast is ALWAYS location-bearing → thread the in-memory
                # selection so the 📍 indicator line shows on every forecast result.
                embed=render_embed(reply, location=self._selected_location),
                view=self._render_view(expanded=False),
            )
        except Exception:  # noqa: BLE001 — non-propagating (mirrors on_command)
            _log.exception(
                "panel forecast callback failed",
                custom_id=f"wb:fc:{command_name}:{variant}",
            )
            await self._safe_error_edit(interaction)

    async def on_forecast_toggle(self, interaction: discord.Interaction) -> None:
        """Reveal/collapse the forecast sub-grid — a plain in-memory toggle (D-03/D-07).

        Flips the in-memory ``_expanded`` flag and renders the matching view via EXACTLY
        ONE ``response.edit_message`` (Pattern 2) — no fetch, no second ``response.*``.
        The Forecast toggle is the ONLY control that yields the expanded render; every
        other action collapses (D-04). Wrapped in the same per-callback non-propagating
        envelope as the other callbacks.
        """
        try:
            self._expanded = not self._expanded
            await interaction.response.edit_message(
                view=self._render_view(expanded=self._expanded)
            )
        except Exception:  # noqa: BLE001 — non-propagating (mirrors on_command)
            _log.exception(
                "panel forecast toggle callback failed", custom_id="wb:forecast:toggle"
            )
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

    def _render_view(
        self, *, expanded: bool, disabled: bool = False
    ) -> discord.ui.View:
        """Build a fresh render view — the SINGLE child-cloning path (D-09, Pattern 2).

        The one parameterized clone path that reveal/collapse AND the disabled-cue ack
        both flow through (killing the IN-03 two-path drift). It rebuilds a fresh
        ``timeout=None`` view carrying clones of this panel's children, with two knobs:

        - ``expanded``: when ``False`` the forecast sub-grid (rows 3–4) is OMITTED — the
          collapsed base. When ``True`` every child is cloned — the revealed panel.
        - ``disabled``: when ``True`` every cloned child is disabled (the transient-cue
          ack that neutralizes double-taps during a cold fetch).

        It NEVER mutates the registered persistent view (``self``): the canonical view
        keeps all 13 children (so add_view registers every ``custom_id`` and post-restart
        taps route — Pattern 1); this only produces a cosmetic clone for ``edit_message``.

        D-09: the forecast toggle + 4 sub-buttons are plain ``discord.ui.Button``
        subclasses, so the existing ``isinstance(child, discord.ui.Button)`` branch
        rebuilds them with NO new branch.
        """
        view = discord.ui.View(timeout=None)
        for child in self.children:
            # Collapsed: drop the forecast sub-grid (rows 3–4); keep the base (D-03/D-04).
            if not expanded and getattr(child, "row", None) in (3, 4):
                continue
            if isinstance(child, discord.ui.Button):
                view.add_item(
                    discord.ui.Button(
                        label=child.label,
                        # THE TRAP (Pitfall 1 / D-04): carry the emoji onto the PLAIN
                        # clone — discord.py round-trips ``child.emoji`` as a str/
                        # PartialEmoji. Without this the glyph silently vanishes on every
                        # disabled-ack and collapse render (the most common paths).
                        emoji=child.emoji,
                        custom_id=child.custom_id,
                        style=child.style,
                        row=child.row,
                        disabled=disabled,
                    )
                )
            elif isinstance(child, discord.ui.Select):
                view.add_item(
                    discord.ui.Select(
                        custom_id=child.custom_id,
                        placeholder=child.placeholder,
                        # Carry the selection-cardinality fields so the clone can never
                        # drift from the original on the min/max axis (WR-02).
                        min_values=child.min_values,
                        max_values=child.max_values,
                        # THE TRAP (Pitfall 1 / D-02): re-derive the default mark from
                        # ``_selected_location`` rather than blind-copying ``child.options``
                        # — otherwise the dropdown highlight reverts to bare placeholder on
                        # every ack/collapse render. NEVER read Select.values (Pitfall 3).
                        # Preserve the option's display ``label`` (WR-01): today label==value,
                        # but copying ``o.value`` into ``label`` would silently revert a future
                        # friendly label on the very next clone — the exact drift this guards.
                        options=[
                            discord.SelectOption(
                                label=o.label,
                                value=o.value,
                                default=(o.value == self._selected_location),
                            )
                            for o in child.options
                        ],
                        row=child.row,
                        disabled=disabled,
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
                # Attach a COLLAPSED clone, NOT the raw persistent ``self`` (WR-02): the
                # canonical view carries all 13 children (incl. the rows-3/4 forecast
                # sub-grid), so ``view=self`` would *expand* the panel on any error —
                # contradicting the D-04 "every non-toggle action collapses" invariant
                # and leaking the full expanded layout as the resting state. Callback
                # routing is unaffected: taps route by custom_id on the registered
                # persistent ``self`` (add_view), not on this edited clone.
                await interaction.edit_original_response(
                    content=_ERROR_REPLY,
                    embed=None,
                    view=self._render_view(expanded=False),
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
