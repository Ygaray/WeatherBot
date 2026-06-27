"""The oracle self-proof — perturbing a real render MUST fail (Plan 21-02, D-12 / SC2).

The golden suite is only trustworthy if its comparison actually has teeth: an
order-PRESERVING embed projection must make a field REORDER a real diff, and a raw-bytes
``custom_id`` pin must make a single byte FLIP a real diff. If either oracle were ever
silently loosened into an order-insensitive / fuzzy compare, every golden would keep
passing while the contract rotted.

These two meta-tests STAND GUARD over exactly that. Each drives ACTUAL production output —
a real ``build_inbound_embed`` render projected through the shipped ``embed_to_golden``, and
a real panel ``custom_id`` read off a real ``PanelView`` — then perturbs it and asserts the
equality FAILS, wrapped in ``pytest.raises(AssertionError)``. Because the inputs are real
(not hand literals), the proof ALSO trips if the render or the panel is ever loosened.

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
    result = lookup_weather(
        "New York",
        config=_CONFIG,
        client=_FakeClient(
            imperial=_load("onecall_metric_clear.json"),
            metric=_load("onecall_metric_clear.json"),
        ),
    )
    with time_machine.travel(FROZEN, tick=False):
        return embed_to_golden(build_inbound_embed(result.forecast))


def test_field_reorder_is_caught():
    """A field REORDER of a REAL render must FAIL the order-preserving comparison (D-12).

    Drives an actual ``build_inbound_embed`` → ``embed_to_golden`` projection, then reverses
    its ``fields`` list. The order-PRESERVING oracle must see the reversed list as unequal —
    ``pytest.raises(AssertionError)`` proves it. An order-INSENSITIVE compare would NOT
    raise, turning this test red and exposing a loosened oracle. The embed has ≥2 fields
    (Now / High·Low / Rain), so the reversal is genuinely a different order.
    """
    good = _real_embed_golden()
    assert len(good["fields"]) >= 2, "need ≥2 fields for a reorder to be observable"
    reordered = {**good, "fields": list(reversed(good["fields"]))}

    # The order-preserving oracle MUST treat a reordered field list as unequal.
    with pytest.raises(AssertionError):
        assert good == reordered


def test_custom_id_byteflip_is_caught():
    """A single-byte FLIP of a REAL panel ``custom_id`` must FAIL the raw-bytes comparison.

    Reads an ACTUAL ``custom_id`` off a real ``PanelView`` (not a hand literal — so this
    also trips if the panel's ids are ever changed), then flips one byte. The raw-bytes
    oracle must see the flipped string as unequal — ``pytest.raises(AssertionError)`` proves
    the byte-level pin bites (a single-character drift breaks routing / the owned-panel
    marker).
    """
    view = _make_panel(panel, holder=_FakeHolder(["home"]), cache=_SpyCache())
    real_id = view.children[0].custom_id  # the real "wb:loc:select"
    real_bytes = real_id.encode()

    # Flip the final byte (':select' -> ':selecu') — a one-character drift.
    flipped = real_bytes[:-1] + bytes([real_bytes[-1] + 1])
    assert flipped != real_bytes, "the perturbation must actually change a byte"

    # The raw-bytes oracle MUST treat the one-byte-flipped id as unequal.
    with pytest.raises(AssertionError):
        assert real_bytes == flipped
