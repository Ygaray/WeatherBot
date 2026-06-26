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
    """A bot-user stand-in compared by identity (msg.author == bot_user)."""


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
