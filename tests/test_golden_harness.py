"""Wave-0 golden-harness smoke tests (Plan 21-01).

These standing smokes discharge — and stay as the regression guard for — the three
``[ASSUMED]`` Wave-0 items the rest of the Phase-21 golden harness depends on. The
shared helpers/fixtures themselves live in ``tests/conftest.py`` (FROZEN,
``json_snapshot``/``bytes_snapshot``, ``embed_to_golden`` / ``schedule_plan_golden`` /
``onecall_rows_golden``); this module only proves they rest on confirmed mechanics:

- A3 — ``time_machine.travel(FROZEN)`` freezes ``discord.utils.utcnow()`` (the embed
  ``Updated <t:…>`` epoch). The documented monkeypatch fallback is NOT needed.
- A1 — ``snapshot.use_extension(<ExtensionClass>)`` is the syrupy 5.3.4 call shape, and
  a trivial structured assert round-trips through ``json_snapshot``.
- A7 — ``str(CronTrigger)`` (the schedule golden's byte-exact primary) is deterministic.

This module is purely additive test infrastructure — it touches no ``weatherbot/`` source.
"""

from __future__ import annotations

import time_machine
from apscheduler.triggers.cron import CronTrigger

from tests.conftest import FROZEN, embed_to_golden


def test_frozen_epoch_reaches_render() -> None:
    """Wave-0 smoke (A3): ``time_machine.travel(FROZEN)`` freezes the embed Updated stamp.

    ``render_embed`` stamps ``int(discord.utils.utcnow().timestamp())`` into the
    ``Updated <t:{unix}:t> (<t:{unix}:R>)`` description line (bot.py:219-223). This proves
    the freeze reaches ``discord.utils.utcnow`` (``datetime.now(timezone.utc)`` under the
    hood) so every Wave-1 embed golden gets a deterministic epoch literal. If this ever
    goes red, wire the documented fallback
    ``monkeypatch.setattr("weatherbot.interactive.bot.discord.utils.utcnow", lambda: FROZEN)``
    in the embed goldens and note it in the phase log (Pitfall 4 / D-11).
    """
    from weatherbot.interactive.bot import render_embed
    from weatherbot.interactive.commands import CommandReply

    expected_epoch = int(FROZEN.timestamp())
    with time_machine.travel(FROZEN, tick=False):
        embed = render_embed(CommandReply(title="Weather — home"), location="home")

    # The epoch is frozen to FROZEN; the :t/:R FORMAT string is preserved (not scrubbed).
    assert (
        f"Updated <t:{expected_epoch}:t> (<t:{expected_epoch}:R>)" in embed.description
    )
    # And the 📍 line renders for a location-bearing reply (D-01).
    assert "📍 home" in embed.description


def test_json_snapshot_roundtrips(json_snapshot) -> None:
    """Wave-0 smoke (A1): a structured payload round-trips through ``json_snapshot``.

    Confirms the ``snapshot.use_extension(JSONSnapshotExtension)`` fixture wiring works
    against installed syrupy 5.3.4 and writes an order-preserving ``.json`` golden. The
    payload mirrors an ``embed_to_golden`` projection so the smoke exercises the real
    serializer shape Wave-1 embed goldens use.
    """
    payload = {
        "title": "Weather — home",
        "description": "📍 home\nUpdated <t:1781960400:t> (<t:1781960400:R>)",
        "color": 0x5865F2,
        "fields": [
            {"name": "Now", "value": "20°C", "inline": True},
            {"name": "Rain", "value": "30%", "inline": True},
        ],
    }
    assert payload == json_snapshot


def test_cron_trigger_str_is_stable() -> None:
    """Wave-0 smoke (A7): ``str(CronTrigger)`` is deterministic across constructions.

    The schedule golden snapshots ``str(job.trigger)`` as its byte-exact primary, so its
    stability is load-bearing. Two identically-constructed triggers must render the same
    string (e.g. ``cron[day_of_week='mon-fri', hour='9', minute='0']``).
    """
    a = CronTrigger(
        hour=9, minute=0, day_of_week="mon-fri", timezone="America/New_York"
    )
    b = CronTrigger(
        hour=9, minute=0, day_of_week="mon-fri", timezone="America/New_York"
    )
    assert str(a) == str(b)
    assert str(a) == "cron[day_of_week='mon-fri', hour='9', minute='0']"


def test_embed_to_golden_excludes_timestamp() -> None:
    """``embed_to_golden`` projects the byte-contract surface and excludes embed.timestamp.

    Drives a real ``render_embed`` output (not a hand literal) so the projection contract
    (title / description / color / ordered fields incl. inline; NO timestamp key) is pinned
    against the actual renderer.
    """
    from weatherbot.interactive.bot import render_embed
    from weatherbot.interactive.commands import CommandReply

    with time_machine.travel(FROZEN, tick=False):
        embed = render_embed(
            CommandReply(title="Weather — home", lines=(("Now", "20°C"),)),
            location="home",
        )
    golden = embed_to_golden(embed)

    assert set(golden) == {"title", "description", "color", "fields"}
    assert "timestamp" not in golden
    assert golden["title"] == "Weather — home"
    assert golden["fields"] == [{"name": "Now", "value": "20°C", "inline": True}]
