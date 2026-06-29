"""``PanelKit`` — the generic persistent operator-panel view machinery (SEAM-07, D-03/D-04).

The reusable-module home of the app's persistent panel view. ``PanelKit`` owns the
generic, domain-agnostic mechanics:

- the persistent-view contract (``timeout=None``, all-static-``custom_id`` children,
  the build-time child-cap asserts, the single clone path),
- the **registry-derived command buttons** built FROM the Phase-26 ``CommandRegistry``
  (one :class:`CmdButton` per curated ``command_names`` entry),
- the **operator gate** (``interaction_check`` — bot reject with no ephemeral, non-operator
  reject with an identity-free ephemeral + the sole audit log),
- the per-callback **non-propagating failure-isolation envelope** + the ``View.on_error``
  backstop + ``_safe_error_edit`` (never re-raises),
- the ownership predicate (author + an **app-supplied marker**, D-04).

Everything app-specific is INJECTED at construction (the module's locked
constructor-injection-of-opaque-callables idiom — ``CommandRegistry(specs)`` /
``SchedulerEngine(scheduler)`` / ``ReloadEngine(validate=…)``):

- ``marker`` (D-04 — REQUIRED, no default; the module bakes no marker literal of its own),
- ``render`` (D-01 — the opaque app embed builder the module invokes but never inspects),
- ``contributors`` (D-03 — the app's item builders for its own cosmetic components; each
  is a clone factory the module re-invokes on every render),
- ``dispatch`` (the app closure that runs the per-tap fetch/dispatch off-loop and returns
  a generic :class:`DispatchOutcome`),
- ``selection`` (D-02 — the generic :class:`SelectedContext` holder),
- ``operator_id`` (D-06 — baked at construction; the v1 deferral is preserved).

THE LIVE-ROUTING TRAP (the highest-risk mechanism — clone-dead-after-first-tap): discord.py
routes component interactions by ``message_id`` FIRST, and ``edit_message(view=clone)`` binds
the clone to the panel message — so every tap AFTER the first render dispatches to the
clone's children, NOT the persistent ``add_view``-registered ``self``. A clone carrying a
plain ``discord.ui.Button``/``Select`` (whose base ``callback`` is a no-op ``pass`` in
discord.py 2.7.1) therefore goes DEAD after the first tap with no log. The cure: the clone
path rebuilds every child as a REAL callback-bearing item bound to ``self`` — the module
rebuilds its own :class:`CmdButton`s and RE-INVOKES each app contributor (never an
``isinstance`` check on an app component class). ``disabled`` is applied post-construction
(the item ctors take no ``disabled`` param).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import discord
import structlog

if TYPE_CHECKING:
    from yahir_reusable_bot.discord.selection import SelectedContext

__all__ = [
    "PanelKit",
    "CmdButton",
    "ItemContributor",
    "DispatchOutcome",
]

_log = structlog.get_logger(__name__)

# Discord component caps the library does NOT enforce at construction — asserted here at
# build time so an overlong id/label fails LOUD here rather than as a generic HTTPException
# at send time. Generic Discord caps; name no app concept.
_MAX_CUSTOM_ID = 100
_MAX_LABEL = 80
_MAX_ROWS = 5
_MAX_OPTIONS = 25
_MAX_PER_ROW = 5
_MAX_CHILDREN = 25

# The transient cue shown on the single ack while the off-loop fetch runs.
_FETCHING_CUE = "⏳ Fetching…"
# Generic best-effort error copy for the failure-isolation path (identity-free).
_ERROR_REPLY = "Sorry — something went wrong."

# A contributor builds the app's items for ONE render. It is called once for the canonical
# (``add_view``'d) view and again on every clone-render, so it MUST return fresh
# callback-bearing items each call (the live-routing trap). It receives the generic
# selection holder so the app can re-derive option defaults from the current selection.
ItemContributor = Callable[["SelectedContext"], "list[discord.ui.Item]"]


@dataclass(frozen=True)
class DispatchOutcome:
    """The generic result of an injected ``dispatch`` call (the on_command fetch path).

    The app's ``dispatch`` closure owns the per-tap config read, the off-loop fetch, the
    arg adaptation, and any domain-error handling — and returns this neutral outcome:

    - ``reply`` — the app's surface-agnostic result the module hands to ``render`` to build
      the in-place embed (the success path).
    - ``error_message`` — when set (NOT ``None``), the app signalled a known, user-presentable
      error (e.g. an unknown selection): the module edits the panel content with this string
      and NO embed, exactly mirroring the v1 in-place error edit. ``reply`` is ignored.
    """

    reply: Any = None
    error_message: str | None = None


# The injected dispatch seam: ``await dispatch(name, selection)`` → a DispatchOutcome.
DispatchCallable = Callable[[str, "SelectedContext"], Awaitable[DispatchOutcome]]


class CmdButton(discord.ui.Button):
    """A panel command button — a static-``custom_id`` button delegating to ``on_command``.

    Carries the registry command ``name``, the owning :class:`PanelKit`, and the bot-owned
    ``custom_id`` ``f"{marker}cmd:{name}"`` (marker injected, D-04). The label + optional
    emoji are passed in by the caller (``PanelKit`` reads them from app-supplied maps), kept
    as SEPARATE params so emoji is never concatenated into the label.
    """

    def __init__(
        self,
        name: str,
        panel: "PanelKit",
        *,
        marker: str,
        label: str,
        emoji: str | None,
        row: int,
    ) -> None:
        super().__init__(
            label=label,
            emoji=emoji,  # SEPARATE param, never concatenated into the label
            custom_id=f"{marker}cmd:{name}",
            style=discord.ButtonStyle.primary,
            row=row,
        )
        self._name = name
        self._panel = panel

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._panel.on_command(interaction, self._name)


class PanelKit(discord.ui.View):
    """The persistent operator-panel root (``timeout=None``, static-id children).

    The generic machinery; all app specifics are injected (see the module docstring). The
    command buttons are built from the injected ``registry`` over the curated
    ``command_names`` (resolving labels/emoji from the app-supplied maps); the app's own
    cosmetic items are built by the injected ``contributors``. The assembled child order is
    a load-bearing contract (the byte-frozen ``custom_id`` golden pins it): contributors
    and command buttons each declare their row, and the children are added contributors-then-
    command-buttons but sorted by row so the rendered order is row-stable.
    """

    def __init__(
        self,
        *,
        registry: Any,
        command_names: tuple[str, ...],
        marker: str,
        operator_id: int,
        selection: "SelectedContext",
        contributors: list[ItemContributor],
        render: Callable[..., discord.Embed],
        dispatch: DispatchCallable,
        labels: dict[str, str],
        emoji: dict[str, str] | None = None,
        command_rows: dict[str, int],
    ) -> None:
        super().__init__(timeout=None)  # REQUIRED for persistence (Phase-18 discipline)
        # Required injected collaborators (no module default — the positive injection
        # assertion checks render/contributors/marker have no default).
        self._registry = registry
        self._command_names = command_names
        self._marker = marker
        self._operator_id = operator_id  # baked at construction (preserve v1 deferral)
        self._selection = selection
        self._contributors = contributors
        self._render = render
        self._dispatch = dispatch
        self._labels = labels
        self._emoji = emoji or {}
        self._command_rows = command_rows

        # Build the canonical children once (every custom_id must be registered at
        # add_view time — never add_item/remove_item post-registration, Phase-18).
        for item in self._build_children():
            self.add_item(item)

        self._assert_layout()

    # -- child assembly -------------------------------------------------------- #

    def _build_command_buttons(self) -> list[discord.ui.Item]:
        """Build the registry-derived command buttons (the module-owned control surface).

        One :class:`CmdButton` per curated ``command_names`` entry, each resolved through the
        injected ``registry`` (a missing name fails LOUD here at construction rather than at
        send time). The button's label/emoji come from the app-supplied maps; its row from
        the app-supplied ``command_rows`` contract.
        """
        by_name = getattr(self._registry, "by_name", {})
        buttons: list[discord.ui.Item] = []
        for name in self._command_names:
            assert name in by_name, (  # noqa: S101 — build-time allow-list guard
                f"panel curated command {name!r} is not in the registry — a rename "
                f"broke the panel layout"
            )
            buttons.append(
                CmdButton(
                    name,
                    self,
                    marker=self._marker,
                    label=self._labels[name],
                    emoji=self._emoji.get(name),
                    row=self._command_rows[name],
                )
            )
        return buttons

    def _build_children(self) -> list[discord.ui.Item]:
        """Assemble the full child set: command buttons + contributor items, row-ordered.

        The module's command buttons and every app contributor's items are gathered, then
        STABLE-sorted by ``row`` so the assembled order reproduces today's snapshot
        byte-for-byte (Select row 0 → command rows 1-2 → grid rows 3-4). Within a row the
        relative order is the order produced here (contributors are invoked in the order the
        app supplied them; command buttons follow the curated ``command_names`` order).
        """
        items: list[discord.ui.Item] = []
        # App contributors first (they own rows 0 and 3-4), then the module command buttons
        # (rows 1-2); the stable row sort below interleaves them into the canonical order.
        for contributor in self._contributors:
            items.extend(contributor(self._selection))
        items.extend(self._build_command_buttons())
        items.sort(key=lambda c: (c.row if c.row is not None else _MAX_ROWS))
        return items

    # -- build-time layout guard ---------------------------------------------- #

    def _assert_layout(self) -> None:
        """Build-time layout guard — assert the FULL panel fits Discord's caps."""
        self._assert_layout_children(self.children)

    def _assert_layout_children(self, children: Any) -> None:
        """Assert an arbitrary child set fits Discord's caps (the load-bearing guard).

        Split out so a dedicated overflow test can drive a hand-built over-cap child set
        WITHOUT going through ``add_item`` (which raises its own ``ValueError`` for the
        per-row / total caps before this guard runs).
        """
        rows = {child.row for child in children if child.row is not None}
        assert len(rows) <= _MAX_ROWS, (  # noqa: S101
            f"panel uses {len(rows)} rows (>{_MAX_ROWS})"
        )
        per_row = Counter(child.row for child in children if child.row is not None)
        for row, count in per_row.items():
            assert count <= _MAX_PER_ROW, (  # noqa: S101
                f"panel row {row} has {count} children (>{_MAX_PER_ROW} per row)"
            )
        assert len(children) <= _MAX_CHILDREN, (  # noqa: S101
            f"panel has {len(children)} children (>{_MAX_CHILDREN} total)"
        )
        for child in children:
            options = getattr(child, "options", None)
            if options is not None:
                assert len(options) <= _MAX_OPTIONS, (  # noqa: S101
                    f"panel Select has {len(options)} options (>{_MAX_OPTIONS})"
                )
            custom_id = getattr(child, "custom_id", None)
            assert custom_id is not None and len(custom_id) <= _MAX_CUSTOM_ID, (  # noqa: S101
                f"panel child custom_id {custom_id!r} exceeds {_MAX_CUSTOM_ID} chars"
            )
            label = getattr(child, "label", None)
            if label is not None:
                assert len(label) <= _MAX_LABEL, (  # noqa: S101
                    f"panel child label {label!r} exceeds {_MAX_LABEL} chars"
                )

    # -- ownership predicate (marker-bound, D-04) ------------------------------ #

    def is_owned_panel(
        self, msg: discord.Message, bot_user: discord.abc.User
    ) -> bool:
        """Return True iff ``msg`` is a panel THIS bot owns (author + injected marker).

        Two conditions, both required (author-alone would risk deleting an unrelated pinned
        bot message): the message was authored by the bot (snowflake ``.id`` match), AND some
        child component carries a ``custom_id`` starting with the injected ``marker`` (the
        unforgeable static marker only the panel's children carry). The walk is defensive
        (``getattr`` everywhere) so an unexpected component shape can't crash the bot thread.
        """
        return is_owned_panel(msg, bot_user, marker=self._marker)

    # -- operator gate (relocated verbatim; operator_id injected) -------------- #

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """The single operator gate — runs before EVERY child callback.

        Rejects any bot (defense-in-depth) and any non-operator. The non-operator reject is a
        SINGLE byte-exact identity-free ephemeral ``send_message`` (which suppresses the
        foreign user's "interaction failed" toast and physically cannot edit the shared
        panel) plus an explicit reject log — that log is the SOLE audit record (a clean
        ``return False`` does NOT route through ``on_error``). The reject copy never
        interpolates the user / custom_id / command / operator.
        """
        if interaction.user.bot:
            # INTENTIONAL asymmetry: a bot actor gets NO ephemeral ack (it needs no
            # human-readable feedback); Discord's "interaction failed" toast fires on the
            # triggering client. The reject log is still emitted so EVERY reject path leaves
            # an audit record. Do NOT "fix" this into a double-ack.
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
                "This panel is in use by someone else.",  # generic, identity-free
                ephemeral=True,
            )
            return False
        return True

    # -- command callback (registry dispatch; render injected) ----------------- #

    async def on_command(self, interaction: discord.Interaction, name: str) -> None:
        """Dispatch a tapped command through the injected ``dispatch`` and render in place.

        The single-ack contract: exactly ONE ``interaction.response.*`` call — the
        ``edit_message`` cue/ack that disables every component to neutralize double-taps —
        BEFORE the off-loop fetch; the result then lands via ``edit_original_response`` (the
        followup path, never a second ``response.*`` which would raise
        ``InteractionResponded``). The injected ``dispatch`` closure owns the per-tap config
        read (``holder.current()``), the off-loop fetch, the arg adaptation, and the domain
        error catch — returning a generic :class:`DispatchOutcome`. The whole body's outer
        non-propagating envelope wraps everything so a raising handler can never cross into
        the gateway loop / scheduler thread.
        """
        try:
            # ① the SINGLE response.* call — acks (<3s), shows the cue, disables every
            # component (double-tap guard) on the always-visible full panel.
            await interaction.response.edit_message(
                content=_FETCHING_CUE,
                view=self._build_clone_view(disabled=True),
            )
            outcome = await self._dispatch(name, self._selection)
            if outcome.error_message is not None:
                # Generic-but-helpful in-place edit (the valid options live in the message).
                await interaction.edit_original_response(
                    content=outcome.error_message,
                    embed=None,
                    view=self._build_clone_view(),
                )
                return
            # ② result lands via the FOLLOWUP path — the injected render builds the embed
            # from the reply + the generic selection (the app draws its own indicator line).
            await interaction.edit_original_response(
                content=None,
                embed=self._render(outcome.reply, self._selection),
                view=self._build_clone_view(),
            )
        except Exception:  # noqa: BLE001 — non-propagating (failure isolation)
            _log.exception(
                "panel command callback failed", custom_id=f"{self._marker}cmd:{name}"
            )
            await self._safe_error_edit(interaction)

    # -- failure-isolation backstop (relocated verbatim) ----------------------- #

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        """The ``View.on_error`` backstop — the LAST line of failure isolation.

        The per-callback ``try/except`` is the primary boundary; this override backstops any
        callback exception that escapes it (the dead-button case). Logs in structlog format,
        attempts a best-effort generic in-place answer, and NEVER re-raises.
        """
        _log.exception(
            "panel view on_error backstop",
            custom_id=getattr(item, "custom_id", None),
        )
        await self._safe_error_edit(interaction)

    # -- the single clone path (re-invokes contributors; no isinstance) -------- #

    def _build_clone_view(self, *, disabled: bool = False) -> discord.ui.View:
        """Build a fresh render-clone — the SINGLE child-cloning path (the live-routing fix).

        The one parameterized clone path the disabled-cue ack and the plain re-render both
        flow through. It rebuilds a fresh ``timeout=None`` view carrying REAL callback-bearing
        clones of EVERY child, with one knob (``disabled``).

        It NEVER mutates the registered persistent view (``self``): the canonical view keeps
        all its children (so ``add_view`` registers every ``custom_id`` and post-restart taps
        route); this only produces a cosmetic clone for ``edit_message``.

        THE LIVE-ROUTING TRAP: the clone MUST carry the REAL callback-bearing items, NOT plain
        ``discord.ui.Button``/``Select`` (whose base ``callback`` is a no-op ``pass``).
        discord.py binds THIS clone to the panel message, so every tap after the first render
        dispatches to the clone's children. The cure: rebuild the module's own command buttons
        AND re-invoke each app contributor (which returns fresh callback-bearing items bound to
        the app's own handlers) — never an ``isinstance`` check against an app component class.
        ``disabled`` is applied post-construction (the item ctors take no ``disabled`` param).
        """
        view = discord.ui.View(timeout=None)
        for clone in self._build_children():
            # Applied post-construction — the callback-bearing items take no ``disabled``
            # ctor param; a disabled child still renders but cannot be tapped.
            clone.disabled = disabled
            view.add_item(clone)
        return view

    async def _safe_error_edit(self, interaction: discord.Interaction) -> None:
        """Best-effort generic in-place error answer — never re-raises.

        By the time a callback's envelope reaches here the single ``edit_message`` ack has
        almost always already fired, so the surface is the followup path:
        ``edit_original_response`` edits the panel message in place without a second
        ``response.*`` ack. If the interaction was somehow NOT yet acked, fall back to
        ``response.send_message`` ephemeral. The WHOLE helper is wrapped so a failed error
        reply (expired token, network) is swallowed — a best-effort answer must never
        re-raise into the gateway loop.
        """
        try:
            try:
                # Attach a fresh clone (NOT the raw persistent ``self``): the clone carries
                # REAL callback-bearing items bound to the panel, so the message-bound error
                # view still routes live. Callback routing on the persistent ``self``
                # (add_view) is unaffected; this only re-renders the message.
                await interaction.edit_original_response(
                    content=_ERROR_REPLY,
                    embed=None,
                    view=self._build_clone_view(),
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


def is_owned_panel(
    msg: discord.Message, bot_user: discord.abc.User, *, marker: str
) -> bool:
    """Module-level ownership predicate (author + app-supplied ``marker``).

    The free function the summon orchestration binds the marker into (so the summon scan and
    ``PanelKit.is_owned_panel`` share one implementation). Both conditions required: the
    message was authored by the bot (snowflake ``.id`` match), AND some child carries a
    ``custom_id`` starting with ``marker``. Defensive ``getattr`` throughout — an unexpected
    component shape is skipped, never raised on.
    """
    author_id = getattr(msg.author, "id", None)
    bot_id = getattr(bot_user, "id", None)
    if author_id is None or bot_id is None or author_id != bot_id:
        return False
    for row in msg.components:
        for child in getattr(row, "children", []):
            cid = getattr(child, "custom_id", None)
            if cid is not None and cid.startswith(marker):
                return True
    return False
