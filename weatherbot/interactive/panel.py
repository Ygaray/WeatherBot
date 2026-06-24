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

from typing import TYPE_CHECKING

import discord
import structlog

from weatherbot.interactive import registry

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
        """Stub filled in Task 2 (operator gate)."""
        return True

    async def on_select(self, interaction: discord.Interaction, value: str) -> None:
        """Stub filled in Task 2 (selection state)."""

    async def on_command(self, interaction: discord.Interaction, name: str) -> None:
        """Stub filled in Task 2 (single-ack dispatch)."""

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        """Stub filled in Task 3 (failure-isolation backstop)."""

    def _disabled_copy(self) -> discord.ui.View:
        """Stub filled in Task 2 (disabled view for the transient cue)."""
        return self

    async def _safe_error_edit(self, interaction: discord.Interaction) -> None:
        """Stub filled in Task 3 (best-effort error reply)."""
