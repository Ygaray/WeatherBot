"""The app cosmetic panel contributions — the WeatherBot-specific panel UI (Phase 27, D-03).

After the Phase-27 adapter relocation (SEAM-07) the generic persistent-view machinery
(``timeout=None`` + ``add_view``, the operator gate, the per-callback failure-isolation
envelope + ``View.on_error``, the registry-derived command buttons, the single clone path,
the ownership test) lives in :class:`yahir_reusable_bot.discord.panelkit.PanelKit`. What
STAYS app-side here is irreducibly WeatherBot UI:

- :class:`LocationSelect` — the location dropdown (``custom_id="wb:loc:select"``); its
  callback ``set``s the injected generic :class:`SelectedContext` (D-02) and re-renders the
  panel in place via the module's clone path.
- :class:`ForecastButton` — the 2×2 forecast-grid sub-buttons (``wb:fc:…``) carrying
  ``(command_name, variant)``; their callback routes through the module ``PanelKit``'s single
  command dispatch via an app-encoded ``"<name>|<variant>"`` dispatch key (the app dispatch
  closure decodes it + builds the ``ForecastFlags`` DIRECTLY — no user text reaches the
  parser, Security V5).
- the ``wb:`` custom_id literals + the locked emoji/label tables (these full literals
  legitimately live app-side per D-04 — the module bakes no ``wb:``).
- :func:`build_contributors` — the :data:`PanelKit`-shaped contributor callables (each a
  clone factory returning FRESH callback-bearing items per call, re-invoked by the module's
  clone path to dodge the live-routing trap — Pattern 1a).
- :data:`PANEL_MARKER`, :data:`PANEL_COMMAND_NAMES`, :data:`PANEL_LABELS`,
  :data:`PANEL_EMOJI`, :data:`PANEL_COMMAND_ROWS` — the app-supplied data the composition
  root threads into the module ``PanelKit``.

The module is constructed at the single composition root (``wiring.py build_runtime``); the
``render`` (the app ``render_embed``, via the ``_render_bridge`` closure) is injected there,
NOT imported here — which is what kills the old ``panel→bot`` module-top import edge (SC#2).

Three load-bearing correctness mechanisms (verified against discord.py 2.7.1) now live in the
module ``PanelKit`` and ride the relocation: the single-ack defer-then-edit, the operator gate,
and the per-callback failure isolation + the clone-render live-routing fix. The app components
preserve their part: the Select ``set``s the context (never re-reads ``Select.values`` in a
button callback — Pitfall 3), and the forecast buttons build flags from the in-memory selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import discord
import structlog

from weatherbot.interactive import registry
from weatherbot.interactive.command import ForecastFlags

if TYPE_CHECKING:
    from yahir_reusable_bot.discord.panelkit import PanelKit
    from yahir_reusable_bot.discord.selection import SelectedContext

__all__ = [
    "LocationSelect",
    "ForecastButton",
    "PANEL_MARKER",
    "PANEL_COMMAND_NAMES",
    "PANEL_LABELS",
    "PANEL_EMOJI",
    "PANEL_COMMAND_ROWS",
    "build_contributors",
    "build_forecast_flags",
    "forecast_dispatch_key",
    "parse_forecast_dispatch_key",
]

_log = structlog.get_logger(__name__)

# The curated, ORDERED command tuples (the locked UI layout, 17-UI-SPEC). Row 1 is the
# five location-taking commands; row 2 is the two argless commands. Each name is asserted
# present in the registry at import so a registry rename trips here (D-06).
_LOCATION_CMDS: tuple[str, ...] = ("weather", "uv", "next-cloudy", "sun", "wind")
_ARGLESS_CMDS: tuple[str, ...] = ("status", "alerts")
# The two forecast specs the always-visible 2×2 forecast grid resolves (Phase 19).
# Both rows of the 2×2 grid route through these (variant is the per-button delta,
# not a separate spec).
_FORECAST_CMDS: tuple[str, ...] = ("weekday-forecast", "weekend-forecast")

for _name in (*_LOCATION_CMDS, *_ARGLESS_CMDS, *_FORECAST_CMDS):
    assert _name in registry.BY_NAME, (  # noqa: S101 — build-time allow-list guard
        f"panel curated command {_name!r} is not in registry.BY_NAME — a registry "
        f"rename broke the panel layout"
    )

# Emoji-free Title-Case labels (17-UI-SPEC Copywriting Contract). The module PanelKit
# resolves the command-button label from this app-supplied map.
PANEL_LABELS: dict[str, str] = {
    "weather": "Weather",
    "uv": "UV",
    "next-cloudy": "Next Cloudy",
    "sun": "Sun",
    "wind": "Wind",
    "status": "Status",
    "alerts": "Alerts",
}

# Phase 20 (PANEL-13a / D-04 / D-05): the LOCKED emoji glyph per command, applied via the
# SEPARATE discord.py ``emoji=`` param — NEVER concatenated into the ``PANEL_LABELS`` text
# label (the client renders icon + text with native spacing; the text label is kept for
# screen-reader naming). The forecast buttons carry their glyphs at their own construction
# sites (they are not in ``PANEL_LABELS``). Byte-exact to the 20-UI-SPEC Copywriting Contract.
PANEL_EMOJI: dict[str, str] = {
    "weather": "🌡️",
    "uv": "🧴",
    "next-cloudy": "☁️",
    "sun": "☀️",
    "wind": "💨",
    "status": "🟢",
    "alerts": "⚠️",
}

# The curated ordered command-button names the module PanelKit builds CmdButtons from
# (row 1 = the five location-taking, row 2 = the two argless), and their fixed rows. The
# Select occupies row 0 and the forecast grid rows 3-4 (the app contributors below); the
# command buttons own rows 1-2 — the byte-frozen custom_id golden pins this order.
PANEL_COMMAND_NAMES: tuple[str, ...] = (*_LOCATION_CMDS, *_ARGLESS_CMDS)
PANEL_COMMAND_ROWS: dict[str, int] = {
    **{name: 1 for name in _LOCATION_CMDS},
    **{name: 2 for name in _ARGLESS_CMDS},
}

# The unforgeable bot-owned panel marker (D-04): every panel component carries a static
# ``wb:``-prefixed custom_id (``wb:cmd:<name>`` built module-side from this marker, plus the
# app ``wb:loc:select`` / ``wb:fc:…`` literals below), so a message that has ANY ``wb:`` child
# AND was authored by the bot is OUR panel. The app passes this to the module PanelKit + the
# ownership test; the module bakes no ``wb:`` literal of its own.
PANEL_MARKER = "wb:"

# The forecast dispatch-key separator: the app encodes ``"<command_name>|<variant>"`` so the
# two grid buttons that share one registry command name (``weekday-forecast``) carry their
# distinct ``detailed``/``compact`` variant through the module's single command dispatch
# (which only passes a ``name`` to the injected dispatch closure). The closure decodes it.
_FC_KEY_SEP = "|"


def forecast_dispatch_key(command_name: str, variant: str) -> str:
    """Encode a forecast ``(command_name, variant)`` into the module dispatch key (D-01)."""
    return f"{command_name}{_FC_KEY_SEP}{variant}"


def parse_forecast_dispatch_key(name: str) -> tuple[str, str] | None:
    """Decode a forecast dispatch key → ``(command_name, variant)``, or ``None`` if plain.

    The app dispatch closure calls this first: a ``"<name>|<variant>"`` key is a forecast tap
    (build ``ForecastFlags`` directly); anything without the separator is a plain registry
    command name routed through the normal arg-binding path.
    """
    if _FC_KEY_SEP not in name:
        return None
    command_name, variant = name.split(_FC_KEY_SEP, 1)
    return command_name, variant


class ForecastButton(discord.ui.Button):
    """A forecast variant sub-button — carries ``(command_name, variant)`` (Phase 19).

    The four sub-grid buttons (``Weekday Detailed`` … ``Weekend Compact``) each hold the
    registry forecast command name (``weekday-forecast`` / ``weekend-forecast``) AND a
    variant literal (``"detailed"`` / ``"compact"``). The callback routes through the module
    ``PanelKit.on_command`` using the app-encoded ``"<name>|<variant>"`` dispatch key (the
    app dispatch closure decodes it + builds the ``ForecastFlags`` DIRECTLY from the in-memory
    selection — Security V5: no user-typed string reaches the bypassed parser). The style is
    a uniform ``primary`` — the four variants are equal-weight read-only triggers; meaning is
    carried by the text LABEL alone, never colour (UI-SPEC Color).

    The contributor re-invokes the builder per render so the cloned, message-bound button is a
    REAL callback-bearing ``ForecastButton`` (never a plain no-callback ``discord.ui.Button``;
    the panel-dead-after-first-tap live-routing fix lives in the module clone path).
    """

    def __init__(
        self,
        panel_getter: "Callable[[], PanelKit]",
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
        # A zero-arg getter resolving the owning PanelKit LAZILY (the late-binding cell):
        # the panel is constructed AFTER the contributor first runs (during __init__), so the
        # getter is dereferenced only here in the callback, never at build time.
        self._panel_getter = panel_getter

    async def callback(self, interaction: discord.Interaction) -> None:
        # Route through the module's single command dispatch with the app-encoded key.
        # The app dispatch closure decodes the variant and builds ForecastFlags directly.
        await self._panel_getter().on_command(
            interaction, forecast_dispatch_key(self._command_name, self._variant)
        )


class LocationSelect(discord.ui.Select):
    """The location dropdown — a static-``custom_id`` Select setting the SelectedContext.

    Options are derived per-construction from the live ``holder.current().locations``
    snapshot, one ``SelectOption(label=n, value=n)`` each, so a hot-reload that adds/removes
    a location is reflected on (re)construction (PANEL-02). The callback ``set``s the injected
    generic :class:`SelectedContext` (D-02, replacing the old in-memory ``_selected_location``)
    and re-renders the panel in place via the module's clone path. Button callbacks read
    ``ctx.value`` and NEVER re-read ``self.values`` (Pitfall 3 — empty outside an active
    select interaction).
    """

    def __init__(
        self,
        panel_getter: "Callable[[], PanelKit]",
        selection: "SelectedContext",
        locations: list[str],
    ) -> None:
        super().__init__(
            custom_id="wb:loc:select",
            placeholder="Location",
            # D-02 (PANEL-12): mark the selected option default=True, derived from the
            # generic SelectedContext value — NEVER from Select.values (Pitfall 3 / #7284).
            options=[
                discord.SelectOption(label=n, value=n, default=(n == selection.value))
                for n in locations
            ],
            row=0,
        )
        # A zero-arg getter resolving the owning PanelKit LAZILY (the late-binding cell):
        # see ForecastButton — the panel is constructed after this Select first builds.
        self._panel_getter = panel_getter
        self._selection = selection

    async def callback(self, interaction: discord.Interaction) -> None:
        """Persist the operator's location choice into the SelectedContext (D-01/D-02).

        The selection is held in the generic ``SelectedContext`` (single-writer on the
        gateway loop); the select interaction is acked with a single
        ``response.edit_message`` (the lightest valid ack that re-renders the panel in place
        through the module's clone path) — no new message, no second ``response.*``. The whole
        body rides a non-propagating try/except (the module ``View.on_error`` backstop also
        covers it).
        """
        panel = self._panel_getter()
        try:
            self._selection.set(self.values[0])
            # The module owns the single clone path (the live-routing fix) + the
            # best-effort error edit; the app component reaches them by their module
            # method names (the relocated _render_view / _safe_error_edit).
            await interaction.response.edit_message(view=panel._build_clone_view())
        except Exception:  # noqa: BLE001 — non-propagating (module on_error also covers)
            _log.exception("panel select callback failed", custom_id="wb:loc:select")
            await panel._safe_error_edit(interaction)


def build_contributors(
    panel_ref: "list[PanelKit]",
    holder,
) -> "list[Callable[[SelectedContext], list[discord.ui.Item]]]":
    """Build the module-shaped contributor callables for the app's cosmetic components (D-03).

    Each contributor matches the module's
    ``ItemContributor = Callable[[SelectedContext], list[discord.ui.Item]]`` shape and returns
    FRESH callback-bearing items per call (the module re-invokes them on every clone-render to
    dodge the live-routing trap — Pattern 1a). ``panel_ref`` is a one-element mutable cell the
    composition root fills with the constructed :class:`PanelKit` immediately after building it
    (late binding — the contributors are first invoked DURING ``PanelKit.__init__``, so the
    cell is empty then; the components only dereference it inside their callbacks, well after
    construction). ``holder`` provides the live ``current().locations`` per render so a
    hot-reload is reflected on every (re)build (PANEL-02).

    Returns two contributors in row order:

    - the Select contributor (row 0) → :class:`LocationSelect`;
    - the forecast-grid contributor (rows 3-4) → the four :class:`ForecastButton`s.

    The module slots its registry-derived command buttons at rows 1-2 between them; the
    assembled child order (Select row 0 → cmd rows 1-2 → grid rows 3-4) reproduces today's
    byte-frozen custom_id snapshot.
    """

    # A zero-arg getter the components dereference LAZILY in their callbacks (the late-binding
    # cell): the contributors run DURING PanelKit.__init__ (so panel_ref is empty then); the
    # composition root fills panel_ref[0] immediately after construction.
    def _panel_getter() -> "PanelKit":
        return panel_ref[0]

    def _select_contributor(selection: "SelectedContext") -> list[discord.ui.Item]:
        # Live config locations re-derived per render (PANEL-02 / D-02). The Select stores the
        # lazy getter, so it never touches panel_ref at build time — only in its callback.
        locations = [loc.name for loc in holder.current().locations]
        if not locations:
            # Fail LOUD with an actionable message: an empty config (no [[locations]]) would
            # otherwise build a Select with options=[] that Discord rejects only at send time.
            raise ValueError(
                "panel requires at least one configured location; "
                "config.locations is empty"
            )
        return [LocationSelect(_panel_getter, selection, locations)]

    def _forecast_grid_contributor(
        selection: "SelectedContext",
    ) -> list[discord.ui.Item]:
        # rows 3-4: the 2×2 forecast grid (curated order, UI-SPEC / D-06). row 3 = weekday
        # pair, row 4 = weekend pair. Byte-exact custom_id / label / emoji / row literals.
        return [
            ForecastButton(
                _panel_getter,
                "weekday-forecast",
                "detailed",
                custom_id="wb:fc:weekday:detailed",
                label="Weekday Detailed",
                emoji="📋",
                row=3,
            ),
            ForecastButton(
                _panel_getter,
                "weekday-forecast",
                "compact",
                custom_id="wb:fc:weekday:compact",
                label="Weekday Compact",
                emoji="📝",
                row=3,
            ),
            ForecastButton(
                _panel_getter,
                "weekend-forecast",
                "detailed",
                custom_id="wb:fc:weekend:detailed",
                label="Weekend Detailed",
                emoji="🏖️",
                row=4,
            ),
            ForecastButton(
                _panel_getter,
                "weekend-forecast",
                "compact",
                custom_id="wb:fc:weekend:compact",
                label="Weekend Compact",
                emoji="🌴",
                row=4,
            ),
        ]

    return [_select_contributor, _forecast_grid_contributor]


def build_forecast_flags(variant: str, location: str) -> ForecastFlags:
    """Build the ``ForecastFlags`` for a forecast tap DIRECTLY (Security V5, D-01).

    ``add``/``drop`` stay at their ``frozenset()`` defaults (the command name encodes the
    day set). ``variant`` is a compile-time literal; the location is the already-validated
    in-memory selection, NEVER a re-read of ``Select.values`` (Pitfall 5). No user-typed
    string reaches the bypassed parser.
    """
    return ForecastFlags(variant=variant, location=location)
