"""The oracle self-proof — perturbing a real render MUST fail (Plan 21-02, D-12 / SC2).

The golden suite is only trustworthy if its comparison actually has teeth: an
order-PRESERVING embed projection must make a field REORDER a real diff, and a raw-bytes
``custom_id`` pin must make a single byte FLIP a real diff. If either oracle were ever
silently loosened into an order-insensitive / fuzzy compare (or syrupy removed), every
golden would keep passing while the contract rotted.

These two meta-tests STAND GUARD over exactly that — and they do it through the SAME
configured syrupy extension the real goldens use, NOT through plain Python ``==`` (which is
trivially order-/byte-sensitive and proves nothing about the oracle). Each drives ACTUAL
production output — a real ``build_inbound_embed`` render projected through the shipped
``embed_to_golden``, and a real panel ``custom_id`` read off a real ``PanelView`` — and
pins it as a committed canonical snapshot via the ``json_snapshot`` / ``bytes_snapshot``
fixtures (``JSONSnapshotExtension`` / ``SingleFileSnapshotExtension``). The proof then has
two halves, both routed through that extension against the SAME named slot:

1. The UNPERTURBED real value MUST MATCH its canonical snapshot — proving the snapshot is
   the real golden, not a vacuous placeholder, and that the inputs are real production output.
2. The PERTURBED value (reversed ``fields`` list / one-byte-flipped ``custom_id``) compared
   through the SAME extension against the SAME snapshot MUST NOT match — wrapped in
   ``pytest.raises(AssertionError)``.

Net effect: the test goes RED if the embed/``custom_id`` extension is ever loosened to an
order-insensitive / fuzzy compare OR removed — exactly what D-12 / SC2 demand. Because the
inputs are real (not hand literals), the proof ALSO trips if the render or the panel ids
are ever changed (the canonical snapshot stops matching).

Both halves use a NAMED snapshot (``json_snapshot(name=...)`` / ``bytes_snapshot(name=...)``)
so the canonical assertion and the perturbed comparison target the SAME stored slot —
syrupy's default positional auto-index would otherwise record the perturbed value as its own
second snapshot and defeat the proof.

Deliberately NOT an expected-failure marker (that reads inverted — a "passing" expected
failure is itself a failing assertion — and was D-12-rejected). These ship as ordinary
standing tests that are GREEN precisely because the perturbation raises ``AssertionError``
— the comparison bites.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import time_machine

from tests.conftest import FROZEN, embed_to_golden
from tests.test_panel import _FakeHolder, _SpyCache, _make_panel
from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.interactive import lookup_weather, panel
from weatherbot.interactive.bot import build_inbound_embed

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _redate_daily_to_frozen(payload: dict) -> dict:
    """Shift each ``daily[]`` entry onto FROZEN's day (Phase 32 D-05/F35).

    ``Forecast.from_payloads`` now selects today's ``daily[]`` entry by its OWN local
    date (not positional ``daily[0]``), so the 2024-06-14 ``clear`` fixture must be
    re-dated onto FROZEN's (2026-06-20) day — else the today-selector correctly
    degrades High/Low/Rain and the oracle's real render loses its recorded values.
    Whole-day (24h) shift so DST offsets stay intact.
    """
    daily = payload.get("daily") or []
    if not daily or daily[0].get("dt") is None:
        return payload
    one_day = 24 * 3600
    day_delta = (
        int(FROZEN.timestamp()) // one_day - int(daily[0]["dt"]) // one_day
    ) * one_day
    for entry in daily:
        for key in ("dt", "sunrise", "sunset"):
            if entry.get(key) is not None:
                entry[key] += day_delta
    return payload


class _FakeClient:
    """Returns recorded imperial/metric One Call fixtures — NO network."""

    def __init__(self, *, imperial: dict, metric: dict) -> None:
        self._onecall = {"imperial": imperial, "metric": metric}

    def fetch_onecall(self, location, units):  # noqa: ANN001
        return self._onecall[units]


_CONFIG = Config(
    locations=[
        Location(name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York")
    ],
    template="briefing-sectioned.txt",
    webhook=WebhookIdentity(),
)


def _real_embed_golden() -> dict:
    """A REAL ``build_inbound_embed`` render projected via ``embed_to_golden`` (frozen)."""
    # Phase 32 (D-05/F35): re-date the fixture onto FROZEN's day and freeze the
    # ``from_payloads`` build clock so the today-selector matches the fixture's entry
    # and the real render keeps its recorded High/Low/Rain (the oracle proves ORDER,
    # not the F35 date guard).
    client = _FakeClient(
        imperial=_redate_daily_to_frozen(_load("onecall_imperial_clear.json")),
        metric=_redate_daily_to_frozen(_load("onecall_metric_clear.json")),
    )
    with time_machine.travel(FROZEN, tick=False):
        result = lookup_weather("New York", config=_CONFIG, client=client)
        return embed_to_golden(build_inbound_embed(result.forecast))


def test_field_reorder_is_caught(json_snapshot):
    """A field REORDER of a REAL render must FAIL the configured JSON oracle (D-12 / SC2).

    Drives an actual ``build_inbound_embed`` → ``embed_to_golden`` projection, then pins it
    as a canonical ``JSONSnapshotExtension`` golden via the ``json_snapshot`` fixture — the
    SAME order-preserving extension every real embed golden uses. Two halves, both routed
    through that extension against the SAME named slot:

    1. The unperturbed render MUST MATCH its committed snapshot — proving the golden is the
       real render (not vacuous) and the inputs are real production output.
    2. The reversed ``fields`` list compared through the SAME extension MUST NOT match —
       ``pytest.raises(AssertionError)`` proves the order-preserving oracle bites.

    If ``JSONSnapshotExtension`` were ever swapped for an order-INSENSITIVE compare (the
    Amber default normalizes key order) or removed, the reversed list would MATCH and the
    ``pytest.raises`` would go unsatisfied → this test goes RED, exposing the loosened
    oracle. The embed has ≥2 fields (Now / High·Low / Rain), so the reversal is genuinely a
    different order.
    """
    good = _real_embed_golden()
    assert len(good["fields"]) >= 2, "need ≥2 fields for a reorder to be observable"

    # Half 1 (canonical): the REAL render must MATCH its committed golden (the snapshot is
    # the real render, not vacuous) — routed through the actual JSONSnapshotExtension.
    #
    # REGENERATION NOTE: both halves target the SAME named slot, so a naive
    # ``--snapshot-update`` lets the perturbed (Half 2) comparison overwrite the slot with the
    # reversed value. To regenerate the canonical snapshot, temporarily disable Half 2 below,
    # run ``uv run pytest tests/test_oracle_selfproof.py --snapshot-update``, then restore it.
    assert good == json_snapshot(name="real_embed")

    # Half 2 (perturbation): a field REORDER, compared through the SAME extension against the
    # SAME slot, MUST NOT match. An order-insensitive / removed oracle would MATCH here,
    # leaving the pytest.raises unsatisfied → this test goes RED, exposing the loosened
    # oracle.
    reordered = {**good, "fields": list(reversed(good["fields"]))}
    with pytest.raises(AssertionError):
        assert reordered == json_snapshot(name="real_embed")


def test_custom_id_byteflip_is_caught(bytes_snapshot):
    """A single-byte FLIP of a REAL panel ``custom_id`` must FAIL the raw-bytes oracle.

    Reads an ACTUAL ``custom_id`` off a real ``PanelView`` (not a hand literal — so this
    also trips if the panel's ids are ever changed), pins it as a canonical
    ``SingleFileSnapshotExtension`` golden via the ``bytes_snapshot`` fixture (the SAME
    raw-bytes extension the real ``custom_id`` golden uses), then flips one byte. Two halves,
    both routed through that extension against the SAME named slot:

    1. The unperturbed id bytes MUST MATCH the committed snapshot — proving the golden is
       the real id (not vacuous).
    2. The one-byte-flipped bytes compared through the SAME extension MUST NOT match —
       ``pytest.raises(AssertionError)`` proves the byte-level pin bites (a single-character
       drift breaks routing / the owned-panel marker).

    If the raw-bytes oracle were ever loosened (fuzzy compare) or removed, the flipped bytes
    would match and the ``pytest.raises`` would go unsatisfied → this test goes RED.
    """
    view = _make_panel(panel, holder=_FakeHolder(["home"]), cache=_SpyCache())
    real_id = view.children[0].custom_id  # the real "wb:loc:select"
    real_bytes = real_id.encode()

    # Half 1 (canonical): the REAL id bytes must MATCH the committed golden (the snapshot is
    # the real id, not vacuous) — through the actual SingleFileSnapshotExtension.
    #
    # REGENERATION NOTE: both halves target the SAME named slot, so to regenerate the
    # canonical snapshot, temporarily disable Half 2 below, run with ``--snapshot-update``,
    # then restore it (otherwise the perturbed value overwrites the slot).
    assert real_bytes == bytes_snapshot(name="real_custom_id")

    # Flip the final byte (':select' -> ':selecu') — a one-character drift.
    flipped = real_bytes[:-1] + bytes([real_bytes[-1] + 1])
    assert flipped != real_bytes, "the perturbation must actually change a byte"

    # Half 2 (perturbation): the one-byte-flipped id, compared through the SAME extension
    # against the SAME slot, MUST NOT match. A fuzzy / removed oracle would MATCH here,
    # leaving the pytest.raises unsatisfied → this test goes RED.
    with pytest.raises(AssertionError):
        assert flipped == bytes_snapshot(name="real_custom_id")
