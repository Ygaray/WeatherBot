"""Wave-0 Nyquist RED scaffold for Phase 17 — the persistent interaction panel.

These tests are the EXECUTABLE CONTRACT that Plan 17-03 turns green. They are
written BEFORE ``weatherbot.interactive.panel`` exists: the not-yet-built module
(``PanelView`` + the ``CmdButton`` / ``LocationSelect`` children, ``_selected_location``)
is referenced through a PER-TEST lazy import (``_panel`` below), NOT at module top.
A hard top-level ``from weatherbot.interactive import panel`` would raise at
COLLECTION and HIDE every node ID — the exact Phase 8/9/10/11 Wave-0 lesson. The
deferred import lets all eleven node IDs COLLECT while each still fails RED on a real
``ModuleNotFoundError``/``AttributeError`` until ``panel.py`` lands (T-17-01).

No live gateway, no network: every test drives a panel callback / ``interaction_check``
directly with the ``fake_interaction`` factory (conftest) — a MagicMock shaped like a
discord.py ``Interaction`` with ``AsyncMock`` ``response.edit_message`` /
``response.send_message`` / ``edit_original_response`` / ``followup.send`` and a
``response.is_done()`` MagicMock. Handlers are stubbed via
``monkeypatch.setitem(registry.BY_NAME, …)`` mirroring ``test_bot.py``'s
``_patch_command_in_registry``.

The load-bearing contracts these node IDs pin (each maps to a Plan-03 GREEN target):
PANEL-02 dropdown from config + hot-reload re-derive, PANEL-03 location button uses
the in-memory selection, PANEL-04 argless button ignores it, PANEL-05 single-ack
before fetch, PANEL-06 in-place render, PANEL-08 leak-free non-operator reject,
D-13 reject does not fire ``on_error``, D-10 persistence + bounded layout,
D-07/D-08 ``weather`` spec renders byte-identical to ``build_inbound_embed``, and the
per-callback failure-isolation envelope (the analog of CMD-16).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace


# --------------------------------------------------------------------------- #
# Deferred reference to the NOT-YET-BUILT panel module (Wave-0 lesson). Resolved
# INSIDE each test body so every node ID collects while the symbol is absent; each
# call fails RED with a real ModuleNotFoundError/AttributeError until Plan 17-03.
# --------------------------------------------------------------------------- #


def _panel():
    """Import the not-yet-built panel module — RED until Plan 17-03 lands it.

    Deferred import (NOT module-top) so the node IDs collect. The module will expose
    ``PanelView(discord.ui.View)`` (built from ``holder`` / ``operator_id`` / ``cache``
    / ``daemon_state``) with the ``CmdButton`` / ``LocationSelect`` children, the
    in-memory ``_selected_location`` selection state, ``interaction_check``, the
    ``on_command`` / ``on_select`` callbacks, and ``on_error`` backstop.
    """
    from weatherbot.interactive import panel

    return panel


def _run(coro):
    """Drive a coroutine to completion on a fresh event loop (no live gateway)."""
    return asyncio.run(coro)


_OPERATOR_ID = 12345


# --------------------------------------------------------------------------- #
# Gateway-free harness stand-ins (no discord import, no network). A holder whose
# ``current()`` returns a snapshot with ``.locations`` (each ``.name``) and a cache
# whose ``lookup`` returns a fake LookupResult — mirroring test_bot.py's _FakeHolder
# / _Cache. These exercise the panel's read-only reuse of holder.current() +
# dispatch_spec without standing up a real ConfigHolder/ForecastCache.
# --------------------------------------------------------------------------- #


class _FakeLocation:
    """A config location stand-in exposing only ``.name`` (what the Select reads)."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeConfig:
    """A Config snapshot stand-in exposing ``.locations`` (the dropdown source)."""

    def __init__(self, names) -> None:
        self.locations = [_FakeLocation(n) for n in names]


class _FakeHolder:
    """A ConfigHolder stand-in whose ``current()`` returns a swappable snapshot.

    Mutating ``self.config`` between calls models a hot-reload: the panel re-reads
    ``holder.current()`` so the new snapshot's locations are reflected (PANEL-02).
    """

    def __init__(self, names) -> None:
        self.config = _FakeConfig(names)

    def current(self):
        return self.config


class _FakeForecast:
    """A Forecast stand-in exposing the display fields ``build_inbound_embed`` reads."""

    location = "home"
    temp_display = "20°C"
    high_display = "24°C"
    low_display = "15°C"
    rain_chance = 30


class _FakeLookupResult:
    """A LookupResult stand-in carrying a ``.forecast`` (what the handlers read)."""

    forecast = _FakeForecast()


class _SpyCache:
    """A ForecastCache stand-in whose ``lookup`` records calls and returns a result.

    The panel routes its fetch through ``dispatch_spec`` → ``loop.run_in_executor(
    None, cache.lookup, name, config[, suffix])``; recording the lookup name lets the
    location-button test prove the in-memory selection (not a re-read of an empty
    ``Select.values``) reached the fetch (PANEL-03, Pitfall 3).
    """

    def __init__(self) -> None:
        self.calls: list = []

    def lookup(self, name, config, *suffix):
        self.calls.append((name, suffix))
        return _FakeLookupResult()


def _make_panel(panel, *, holder, cache, operator_id=_OPERATOR_ID):
    """Construct a PanelView from the gateway-free stand-ins (Plan-03 ctor shape).

    Centralizes the constructor call so a ctor-signature change in Plan 03 is a single
    edit here. RED until ``panel.PanelView`` exists.
    """
    return panel.PanelView(holder=holder, operator_id=operator_id, cache=cache)


def _stub_handler(monkeypatch, name, handler):
    """Swap the named registry spec's handler (frozen CommandSpec → ``replace``).

    Mirrors test_bot.py's ``_spec_with_handler`` + ``_patch_command_in_registry``: the
    panel resolves ``registry.BY_NAME[custom_id-name]``, so stubbing ``BY_NAME`` (and
    the iterated tuples for parity) makes the dispatched spec carry the stub.
    """
    from weatherbot.interactive import registry

    spec = registry.BY_NAME[name]
    stubbed = replace(spec, handler=handler)
    monkeypatch.setitem(registry.BY_NAME, name, stubbed)
    new_commands = tuple(stubbed if s.name == name else s for s in registry.COMMANDS)
    monkeypatch.setattr(registry, "COMMANDS", new_commands, raising=True)
    monkeypatch.setattr(
        registry,
        "COMMANDS_BY_KEYWORD_LEN_DESC",
        tuple(sorted(new_commands, key=lambda c: len(c.name), reverse=True)),
        raising=True,
    )
    return stubbed


# --------------------------------------------------------------------------- #
# PANEL-02 — dropdown options derived from holder.current().locations.
# --------------------------------------------------------------------------- #


def test_dropdown_from_config(fake_interaction):
    """PANEL-02: the location Select's options are derived from the live config
    snapshot (``holder.current().locations``), one option per configured location —
    NOT a hardcoded list. The panel is the single source of truth for the grid."""
    panel = _panel()

    holder = _FakeHolder(["home", "travel"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    select = next(c for c in view.children if getattr(c, "custom_id", None) == "wb:loc:select")
    option_values = [opt.value for opt in select.options]
    assert option_values == ["home", "travel"], (
        "Select options must derive from holder.current().locations, in order"
    )


def test_dropdown_rederives_on_hot_reload(fake_interaction):
    """PANEL-02: a hot-reload that changes the holder snapshot is reflected — the
    dropdown re-derives its options from ``holder.current()`` on (re)render rather
    than caching the startup list (a config edit adds/removes a location live)."""
    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    # Simulate a hot-reload swapping in a new snapshot with an added location.
    holder.config = _FakeConfig(["home", "travel", "beach"])
    rebuilt = panel.PanelView(holder=holder, operator_id=_OPERATOR_ID, cache=_SpyCache())

    select = next(c for c in rebuilt.children if getattr(c, "custom_id", None) == "wb:loc:select")
    assert [opt.value for opt in select.options] == ["home", "travel", "beach"], (
        "the dropdown must reflect the post-reload holder snapshot"
    )


# --------------------------------------------------------------------------- #
# PANEL-03 — a location button uses the in-memory _selected_location as the arg.
# --------------------------------------------------------------------------- #


def test_location_button_uses_selection(fake_interaction, monkeypatch):
    """PANEL-03: a location-taking button passes ``_selected_location`` as the ``arg``
    to ``dispatch_spec`` (read from the in-memory attribute set by the Select callback,
    NOT a re-read of the empty ``Select.values`` — Pitfall 3). After the operator
    picks "travel", a ``sun`` tap must fetch for "travel"."""
    panel = _panel()

    cache = _SpyCache()
    holder = _FakeHolder(["home", "travel"])
    view = _make_panel(panel, holder=holder, cache=cache)

    captured = {}

    def _spy_handler(result):
        from weatherbot.interactive.commands import CommandReply

        captured["forecast"] = result.forecast
        return CommandReply(title="Sun", lines=())

    _stub_handler(monkeypatch, "sun", _spy_handler)

    # Operator selects "travel" via the Select callback, then taps the sun button.
    select_interaction = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:loc:select")
    _run(view.on_select(select_interaction, "travel"))

    sun_interaction = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:cmd:sun")
    _run(view.on_command(sun_interaction, "sun"))

    # The fetch must have used the selected location, not the default/empty values.
    assert cache.calls, "the location button must drive a fetch"
    assert cache.calls[-1][0] == "travel", "the fetch must use _selected_location"


# --------------------------------------------------------------------------- #
# PANEL-04 — an argless button (status/alerts info-group) passes arg=None.
# --------------------------------------------------------------------------- #


def test_argless_button_ignores_selection(fake_interaction, monkeypatch):
    """PANEL-04: an argless command (``status``) ignores ``_selected_location`` and is
    dispatched with ``arg=None`` — the in-memory selection never leaks into a command
    that takes no location. Picking "travel" then tapping status must NOT fetch a
    location (status reads daemon_state, not a forecast)."""
    panel = _panel()

    cache = _SpyCache()
    holder = _FakeHolder(["home", "travel"])
    view = _make_panel(panel, holder=holder, cache=cache)

    def _status_handler(daemon_state):
        from weatherbot.interactive.commands import CommandReply

        return CommandReply(title="Status", lines=())

    _stub_handler(monkeypatch, "status", _status_handler)

    _run(view.on_select(fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:loc:select"), "travel"))
    _run(view.on_command(fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:cmd:status"), "status"))

    # status takes no location → dispatch_spec performs no location fetch.
    assert cache.calls == [], "an argless button must pass arg=None (no location fetch)"


# --------------------------------------------------------------------------- #
# PANEL-05 — exactly one response.edit_message ack before the fetch (no second
# response.* call).
# --------------------------------------------------------------------------- #


def test_single_ack_before_fetch(fake_interaction, monkeypatch):
    """PANEL-05 (D-14): a button tap spends EXACTLY one ``interaction.response.*`` call
    — ``response.edit_message`` (the cue/ack, <3s) — before the fetch, and NEVER a
    second ``response.*`` (a double-ack ``InteractionResponded``). The result lands via
    the followup path, not a second ack."""
    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    def _sun_handler(result):
        from weatherbot.interactive.commands import CommandReply

        return CommandReply(title="Sun", lines=())

    _stub_handler(monkeypatch, "sun", _sun_handler)

    interaction = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:cmd:sun")
    _run(view.on_command(interaction, "sun"))

    # Exactly one ack — the transient cue — and no second response.* (no double-ack).
    interaction.response.edit_message.assert_awaited_once()
    interaction.response.send_message.assert_not_awaited()


# --------------------------------------------------------------------------- #
# PANEL-06 — the result lands in-place via edit_original_response (no new message).
# --------------------------------------------------------------------------- #


def test_result_renders_in_place(fake_interaction, monkeypatch):
    """PANEL-06: the command result renders IN PLACE on the panel message via
    ``interaction.edit_original_response`` (an embed edit) — never a new ``followup.send``
    /``channel.send`` message. The pinned panel is edited, not spammed with replies."""
    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    def _sun_handler(result):
        from weatherbot.interactive.commands import CommandReply

        return CommandReply(title="Sun", lines=(("Sunrise", "06:00"),))

    _stub_handler(monkeypatch, "sun", _sun_handler)

    interaction = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:cmd:sun")
    _run(view.on_command(interaction, "sun"))

    # Result lands in-place; no new message is sent for the happy path.
    interaction.edit_original_response.assert_awaited()
    interaction.followup.send.assert_not_awaited()


# --------------------------------------------------------------------------- #
# PANEL-08 — non-operator: ephemeral generic reject, return False, no handler runs.
# --------------------------------------------------------------------------- #


def test_non_operator_rejected_leak_free(fake_interaction):
    """PANEL-08 (D-11/D-12): a non-operator tap is rejected by ``interaction_check`` —
    it returns ``False``, sends a SINGLE ephemeral generic message with the byte-exact
    identity-free copy, and no command handler runs (the shared panel cannot be driven
    by anyone but the operator)."""
    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    interaction = fake_interaction(user_id=99999, custom_id="wb:cmd:sun")
    allowed = _run(view.interaction_check(interaction))

    assert allowed is False, "a non-operator must be rejected (return False)"
    interaction.response.send_message.assert_awaited_once()
    args, kwargs = interaction.response.send_message.await_args
    assert args and args[0] == "This panel is in use by someone else.", (
        "the reject copy must be byte-exact and identity-free (D-12)"
    )
    assert kwargs.get("ephemeral") is True, "the reject must be ephemeral (leak-free)"
    # No panel edit happened — the shared message is untouched by a foreigner (D-11).
    interaction.response.edit_message.assert_not_awaited()


# --------------------------------------------------------------------------- #
# D-13 — a clean interaction_check `return False` does NOT invoke View.on_error.
# --------------------------------------------------------------------------- #


def test_reject_does_not_call_on_error(fake_interaction, monkeypatch):
    """D-13: a clean ``interaction_check`` ``return False`` early-returns WITHOUT
    invoking ``View.on_error`` (verified against discord.py 2.7.1 ``_scheduled_task``).
    The explicit reject log is therefore the SOLE audit record — so ``on_error`` must
    not be the rejection path. We assert the reject is a clean ``False`` and that
    driving it does not raise into ``on_error``."""
    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    on_error_calls = []

    async def _spy_on_error(interaction, error, item):
        on_error_calls.append((error, item))

    monkeypatch.setattr(view, "on_error", _spy_on_error, raising=False)

    interaction = fake_interaction(user_id=99999, custom_id="wb:cmd:sun")
    allowed = _run(view.interaction_check(interaction))

    assert allowed is False
    assert on_error_calls == [], "a clean reject must NOT route through on_error (D-13)"


# --------------------------------------------------------------------------- #
# D-10 — view.is_persistent() is True; every child's custom_id/label is bounded.
# --------------------------------------------------------------------------- #


def test_view_persistent_and_layout_bounded(fake_interaction):
    """D-10 (PANEL-10 seam): the assembled view satisfies ``view.is_persistent() is
    True`` (timeout None + every child carries a static ``custom_id`` — required so
    Phase 18 can ``add_view`` without a ``ValueError``), and the build-time layout
    assert holds: every child ``custom_id`` ≤ 100 chars and every ``label`` ≤ 80 (the
    library does NOT enforce these — Pitfall 5)."""
    panel = _panel()

    holder = _FakeHolder(["home", "travel"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    assert view.is_persistent() is True, "the panel must be a persistent view (D-10)"
    for child in view.children:
        custom_id = getattr(child, "custom_id", None)
        assert custom_id is not None and len(custom_id) <= 100, (
            "every child needs a static custom_id ≤100 chars"
        )
        label = getattr(child, "label", None)
        if label is not None:
            assert len(label) <= 80, "every label must be ≤80 chars (Pitfall 5)"


def test_freshly_built_view_is_persistent_and_defaults_location(fake_interaction):
    """Phase 18 (D-08/D-13): a freshly-built PanelView — the exact object setup_hook
    constructs at add_view time on every process start — is persistent
    (``is_persistent() is True``, so add_view re-binds its callbacks by custom_id
    after a restart) AND defaults its in-memory selection to ``locations[0]`` (the
    documented default-on-restart; this phase confirms, adds nothing)."""
    panel = _panel()

    holder = _FakeHolder(["home", "travel"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    assert view.is_persistent() is True
    assert view._selected_location == "home", (
        "a freshly-built view must default to locations[0] (D-08 default-on-restart)"
    )


# --------------------------------------------------------------------------- #
# D-07/D-08 — the `weather` spec renders to the same fields as build_inbound_embed.
# --------------------------------------------------------------------------- #


def test_weather_spec_byte_identical(fake_interaction):
    """D-07/D-08: the NEW ``weather`` command reply renders to the SAME embed fields as
    the existing ``build_inbound_embed`` (Now / High·Low / Rain). The panel's ``weather``
    button and the briefing webhook must produce the byte-identical Now/High·Low/Rain
    shape — this pins the W2 ``weather_view`` handler against the briefing reference."""
    from weatherbot.interactive import registry
    from weatherbot.interactive.bot import build_inbound_embed, render_embed

    forecast = _FakeForecast()

    # The W2 weather spec must exist in the registry (D-08 — re-enables !weather).
    weather_spec = registry.BY_NAME["weather"]
    reply = weather_spec.handler(_FakeLookupResult())

    panel_embed = render_embed(reply)
    reference_embed = build_inbound_embed(forecast)

    panel_fields = [(f.name, f.value) for f in panel_embed.fields]
    reference_fields = [(f.name, f.value) for f in reference_embed.fields]
    assert panel_fields == reference_fields, (
        "the weather reply must render byte-identical Now/High·Low/Rain fields"
    )
    assert panel_embed.title == reference_embed.title, "titles must match (D-07)"


# --------------------------------------------------------------------------- #
# isolation — a raising panel callback never propagates (the CMD-16 analog).
# --------------------------------------------------------------------------- #


def test_callback_raise_isolated(fake_interaction, monkeypatch):
    """Failure isolation (CMD-16 analog): a command handler that raises is swallowed by
    the per-callback non-propagating envelope — ``on_command`` returns WITHOUT raising
    (so a panel bug can never cross into the gateway / scheduler thread) and the
    operator still gets a generic in-place answer (the error edit). This is the direct
    analog of ``test_raising_command_handler_is_isolated`` for the interaction path."""
    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    def _boom(result):
        raise RuntimeError("panel handler blew up after a clean fetch")

    _stub_handler(monkeypatch, "sun", _boom)

    interaction = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:cmd:sun")

    # MUST return without raising (the raising handler is isolated) ...
    _run(view.on_command(interaction, "sun"))

    # ... and the operator gets a best-effort in-place answer (never a dead button).
    interaction.edit_original_response.assert_awaited()


# --------------------------------------------------------------------------- #
# Phase 18 (D-05) — _PANEL_MARKER + _is_owned_panel marker matcher.
#
# The summon (Plan 02) scans channel.pins() and must touch ONLY panels the bot
# owns: identity = author == bot.user AND a child component custom_id starting with
# the unforgeable wb: marker. Author-alone was rejected (would risk deleting an
# unrelated bot pin — e.g. a future alert post). The walk is defensive (getattr) so
# a component row without .children / .custom_id can never raise.
# --------------------------------------------------------------------------- #


class _FakeBotUser:
    """A bot-user stand-in compared by snowflake ``.id`` (IN-04 — explicit id check).

    ``_is_owned_panel`` now compares ``msg.author.id`` to ``bot_user.id`` rather than
    relying on object ``__eq__``, so the stand-in carries an ``.id``. A default unique
    id per instance preserves the old "distinct objects are not owned" semantics, while
    passing an explicit ``id=`` lets a test build two DISTINCT objects that share an id
    (the Member-vs-User cache-state case)."""

    _next_id = 1000

    def __init__(self, *, id=None):  # noqa: A002 — mirrors discord's `.id` attr name
        if id is None:
            type(self)._next_id += 1
            id = type(self)._next_id
        self.id = id


def test_panel_marker_constant_is_wb():
    """D-05: the marker constant the scan keys on is the wb: custom_id prefix."""
    panel = _panel()
    assert panel._PANEL_MARKER == "wb:"


def test_is_owned_panel_matches_bot_authored_wb_message(fake_pinned_message):
    """D-05 positive: a message authored by the bot AND carrying a wb:-prefixed child
    custom_id is owned (the survivor the summon reuses-in-place)."""
    panel = _panel()
    bot_user = _FakeBotUser()
    msg = fake_pinned_message(author=bot_user, custom_ids=("wb:cmd:weather",))

    assert panel._is_owned_panel(msg, bot_user) is True


def test_is_owned_panel_rejects_other_author(fake_pinned_message):
    """D-05 negative: a wb:-bearing message authored by SOMEONE ELSE is not owned —
    the author check gates first."""
    panel = _panel()
    bot_user = _FakeBotUser()
    other = _FakeBotUser()
    msg = fake_pinned_message(author=other, custom_ids=("wb:cmd:weather",))

    assert panel._is_owned_panel(msg, bot_user) is False


def test_is_owned_panel_matches_distinct_objects_with_same_id(fake_pinned_message):
    """IN-04: the author check compares snowflake ``.id``, not object identity. A pinned
    bot message whose author is a DISTINCT object from ``bot_user`` (the Member-vs-User
    cache-state case) but shares the same ``.id`` is still owned."""
    panel = _panel()
    bot_user = _FakeBotUser(id=4242)  # guild.me (a Member)
    author = _FakeBotUser(id=4242)  # msg.author (a User) — distinct object, same id
    assert author is not bot_user
    msg = fake_pinned_message(author=author, custom_ids=("wb:cmd:weather",))

    assert panel._is_owned_panel(msg, bot_user) is True


def test_is_owned_panel_rejects_bot_message_without_wb_child(fake_pinned_message):
    """D-05 negative: a bot-authored pin with NO wb: child (an unrelated bot post,
    e.g. a future alert) must NOT match — it must never be deleted as a stray."""
    panel = _panel()
    bot_user = _FakeBotUser()
    msg = fake_pinned_message(author=bot_user, custom_ids=())

    assert panel._is_owned_panel(msg, bot_user) is False


def test_is_owned_panel_does_not_raise_on_childless_row():
    """D-05 robustness: a component row lacking .children must not raise — the walk is
    defensive (getattr(row, "children", []))."""
    from unittest.mock import MagicMock

    panel = _panel()
    bot_user = _FakeBotUser()

    msg = MagicMock(name="discord.Message")
    msg.author = bot_user
    # A row object with NO .children attribute at all.
    bare_row = object()
    msg.components = [bare_row]

    assert panel._is_owned_panel(msg, bot_user) is False


# --------------------------------------------------------------------------- #
# Phase 19 (PANEL-07) — Forecast two-tier reveal/collapse sub-grid.
#
# These seven nodes are the EXECUTABLE CONTRACT for Plan 19-02. They are a
# Wave-0 RED scaffold: written before the new ForecastButton /
# ForecastToggleButton classes, the on_forecast / on_forecast_toggle callbacks,
# the merged _render_view, and the completed _assert_layout exist. They reuse the
# existing _FakeHolder / _SpyCache / _make_panel / _stub_handler stand-ins and the
# fake_interaction fixture verbatim — NO new conftest fixtures.
#
# The contracts they pin (each → a Plan-02 GREEN target):
#   D-03 reveal-then-collapse, D-04 collapse-on-any-non-toggle-action,
#   D-01 ForecastFlags built directly + routed through dispatch_spec(flags=),
#   D-05 all forecast custom_ids registered on the persistent view (post-restart
#   routing), D-08 the load-bearing _assert_layout (≤5 rows / ≤5 per row /
#   ≤25 children / id≤100 / label≤80) fits-and-overflow guard, criterion 2 the
#   panel is the third caller of the shared seam (no parallel forecast logic).
# --------------------------------------------------------------------------- #


# The forecast custom_ids the reveal sub-grid carries (byte-exact, UI-SPEC
# Copywriting Contract). rows 3-4 hold the 2x2 grid; the toggle sits in row 2.
_FC_SUBGRID_IDS = (
    "wb:fc:weekday:detailed",
    "wb:fc:weekday:compact",
    "wb:fc:weekend:detailed",
    "wb:fc:weekend:compact",
)
_FC_TOGGLE_ID = "wb:forecast:toggle"


def _captured_view(mock_call):
    """Return the ``view=`` kwarg captured on an AsyncMock edit_* call (or None)."""
    if mock_call.await_args is None:
        return None
    return mock_call.await_args.kwargs.get("view")


def _rows_of(view):
    """The set of ``row`` indices present among a rendered view's children."""
    return {getattr(c, "row", None) for c in view.children}


def _has_subgrid(view):
    """True iff the rendered view includes any row-3/row-4 (forecast sub-grid) child."""
    return any(getattr(c, "row", None) in (3, 4) for c in view.children)


def test_forecast_toggle_reveal(fake_interaction):
    """D-03/D-07: tapping the Forecast toggle reveals the 2x2 sub-grid (rows 3-4 appear
    in the rendered view); re-tapping it collapses back to the base (rows 3-4 gone) —
    a plain toggle via a single response.edit_message(view=<render view>) swap."""
    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    # First tap → reveal: the edited view INCLUDES rows 3-4.
    reveal_i = fake_interaction(user_id=_OPERATOR_ID, custom_id=_FC_TOGGLE_ID)
    _run(view.on_forecast_toggle(reveal_i))
    revealed = _captured_view(reveal_i.response.edit_message)
    assert revealed is not None, "the toggle must render via response.edit_message(view=)"
    assert _has_subgrid(revealed), "the first Forecast tap must reveal rows 3-4"

    # Second tap → collapse: the edited view EXCLUDES rows 3-4 (plain toggle).
    collapse_i = fake_interaction(user_id=_OPERATOR_ID, custom_id=_FC_TOGGLE_ID)
    _run(view.on_forecast_toggle(collapse_i))
    collapsed = _captured_view(collapse_i.response.edit_message)
    assert collapsed is not None
    assert not _has_subgrid(collapsed), "re-tapping Forecast must collapse rows 3-4"


def test_on_forecast_dispatch(fake_interaction, monkeypatch):
    """D-01 / criterion 2: a forecast variant tap builds ForecastFlags directly and
    routes through the SAME shared dispatch_spec seam the text command uses — no
    parallel forecast logic. After selecting "travel", a Weekday Compact tap dispatches
    registry.BY_NAME["weekday-forecast"] with flags=ForecastFlags(variant="compact",
    location="travel", add=frozenset(), drop=frozenset())."""
    panel = _panel()
    from weatherbot.interactive import registry
    from weatherbot.interactive.commands import CommandReply

    holder = _FakeHolder(["home", "travel"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    recorded = {}

    async def _spy_dispatch(spec, arg, **kwargs):
        recorded["spec"] = spec
        recorded["arg"] = arg
        recorded["flags"] = kwargs.get("flags")
        return CommandReply(title="Weekday forecast", lines=())

    # Spy the shared seam as the panel module sees it (criterion 2 — same seam).
    monkeypatch.setattr(panel, "dispatch_spec", _spy_dispatch, raising=True)

    # Operator selects "travel", then taps Weekday Compact.
    _run(view.on_select(fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:loc:select"), "travel"))
    fc_i = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:fc:weekday:compact")
    _run(view.on_forecast(fc_i, command_name="weekday-forecast", variant="compact"))

    flags = recorded.get("flags")
    assert flags is not None, "on_forecast must pass a pre-built ForecastFlags via flags="
    assert flags.variant == "compact", "variant must come from the tapped button"
    assert flags.location == "travel", "location must be the in-memory _selected_location"
    assert flags.add == frozenset() and flags.drop == frozenset(), (
        "the panel adds no day deltas — add/drop stay at frozenset() defaults (D-01)"
    )
    assert recorded["spec"] is registry.BY_NAME["weekday-forecast"], (
        "the panel must resolve the registry forecast spec (no parallel logic)"
    )
    assert recorded["arg"] is None, "the flags= path passes arg=None (D-01)"


def test_collapse_on_action(fake_interaction, monkeypatch):
    """D-04: every non-toggle action collapses. After on_forecast, after a non-forecast
    on_command, and after on_select, the terminal edited view EXCLUDES rows 3-4."""
    panel = _panel()
    from weatherbot.interactive.commands import CommandReply

    holder = _FakeHolder(["home", "travel"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    async def _spy_dispatch(spec, arg, **kwargs):
        return CommandReply(title="Reply", lines=())

    monkeypatch.setattr(panel, "dispatch_spec", _spy_dispatch, raising=True)

    # (a) a forecast variant tap renders its result AND collapses (result-then-collapse).
    fc_i = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:fc:weekday:detailed")
    _run(view.on_forecast(fc_i, command_name="weekday-forecast", variant="detailed"))
    fc_view = _captured_view(fc_i.edit_original_response)
    assert fc_view is not None and not _has_subgrid(fc_view), (
        "a forecast variant tap must collapse on its result render (D-03/D-04)"
    )

    # (b) a non-forecast command tap collapses too.
    def _sun_handler(result):
        return CommandReply(title="Sun", lines=())

    _stub_handler(monkeypatch, "sun", _sun_handler)
    sun_i = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:cmd:sun")
    _run(view.on_command(sun_i, "sun"))
    sun_view = _captured_view(sun_i.edit_original_response)
    assert sun_view is not None and not _has_subgrid(sun_view), (
        "a non-forecast command tap must render the collapsed base (D-04)"
    )

    # (c) a dropdown change collapses too (on_select acks via response.edit_message).
    sel_i = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:loc:select")
    _run(view.on_select(sel_i, "travel"))
    sel_view = _captured_view(sel_i.response.edit_message)
    assert sel_view is not None and not _has_subgrid(sel_view), (
        "a dropdown change must render the collapsed base (D-04)"
    )


def test_forecast_custom_ids_registered(fake_interaction):
    """D-05: all four wb:fc:* sub-button custom_ids + wb:forecast:toggle are built in
    __init__ so add_view registers them — a revealed sub-button tapped after a restart
    still routes (post-restart routing is display-independent)."""
    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    registered = {getattr(c, "custom_id", None) for c in view.children}
    for cid in (*_FC_SUBGRID_IDS, _FC_TOGGLE_ID):
        assert cid in registered, (
            f"{cid!r} must be a registered child custom_id (add_view post-restart routing)"
        )


def test_forecast_matches_registry(fake_interaction, monkeypatch):
    """criterion 2 / PANEL-10: the panel forecast path renders the SAME reply as the
    registry weekday-forecast spec — the reply the shared dispatch produces flows
    straight to the in-place render, with no parallel forecast logic in the panel."""
    panel = _panel()
    from weatherbot.interactive import registry
    from weatherbot.interactive.bot import render_embed
    from weatherbot.interactive.commands import CommandReply

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    # The reply the registry spec's dispatch yields (a real CommandReply shape).
    canonical = CommandReply(title="Weekday forecast", lines=(("Today", "Sunny"),))

    captured = {}

    async def _spy_dispatch(spec, arg, **kwargs):
        # Prove the panel resolved the registry forecast spec, then return the
        # canonical reply the shared seam would produce.
        captured["spec"] = spec
        return canonical

    monkeypatch.setattr(panel, "dispatch_spec", _spy_dispatch, raising=True)

    fc_i = fake_interaction(user_id=_OPERATOR_ID, custom_id="wb:fc:weekday:detailed")
    _run(view.on_forecast(fc_i, command_name="weekday-forecast", variant="detailed"))

    assert captured["spec"] is registry.BY_NAME["weekday-forecast"], (
        "the panel must dispatch the registry forecast spec (no parallel logic)"
    )
    # The in-place render is exactly render_embed(<that shared reply>).
    rendered = _captured_view  # noqa: F841 — keep helper referenced for clarity
    embed_kwargs = fc_i.edit_original_response.await_args.kwargs
    assert embed_kwargs.get("embed") is not None, "the result renders an embed in place"
    expected = render_embed(canonical)
    got = embed_kwargs["embed"]
    assert [(f.name, f.value) for f in got.fields] == [
        (f.name, f.value) for f in expected.fields
    ], "the panel forecast reply must render the shared-seam reply (no drift)"
    assert got.title == expected.title


def test_layout_full_panel_fits(fake_interaction):
    """D-08: constructing the full PanelView (the __init__ _assert_layout runs) does NOT
    raise at 13 children / 5 rows / ≤5 per row / ids≤100 / labels≤80."""
    panel = _panel()

    holder = _FakeHolder(["home", "travel"])
    # The __init__ assert runs here; a raise would fail the test.
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    assert len(view.children) == 13, "the revealed panel is exactly 13 children (D-06)"
    assert _rows_of(view) == {0, 1, 2, 3, 4}, "the full panel spans 5/5 rows (D-06)"
    assert view.is_persistent() is True, "the full view must stay persistent"


def test_layout_overflow_trips_assert(fake_interaction):
    """D-08 / criterion 3: an over-cap layout (6th row / 26th child / 6-per-row /
    101-char custom_id / 81-char label) trips _assert_layout — so a future addition
    can't silently overflow Discord's caps."""
    import pytest

    panel = _panel()

    holder = _FakeHolder(["home"])
    view = _make_panel(panel, holder=holder, cache=_SpyCache())

    class _FakeChild:
        def __init__(self, *, row, custom_id, label=None):
            self.row = row
            self.custom_id = custom_id
            self.label = label

    # (a) too many rows (a 6th row).
    over_rows = [_FakeChild(row=r, custom_id=f"wb:x:{r}") for r in range(6)]
    with pytest.raises(AssertionError):
        view._assert_layout_children(over_rows, ["home"])

    # (b) too many children total (26).
    over_total = [_FakeChild(row=(i % 5), custom_id=f"wb:x:{i}") for i in range(26)]
    with pytest.raises(AssertionError):
        view._assert_layout_children(over_total, ["home"])

    # (c) too many per row (6 in one row).
    over_per_row = [_FakeChild(row=1, custom_id=f"wb:x:{i}") for i in range(6)]
    with pytest.raises(AssertionError):
        view._assert_layout_children(over_per_row, ["home"])

    # (d) an over-length custom_id (101 chars).
    over_id = [_FakeChild(row=0, custom_id="wb:" + ("x" * 99))]
    with pytest.raises(AssertionError):
        view._assert_layout_children(over_id, ["home"])

    # (e) an over-length label (81 chars).
    over_label = [_FakeChild(row=0, custom_id="wb:ok", label="L" * 81)]
    with pytest.raises(AssertionError):
        view._assert_layout_children(over_label, ["home"])
