"""Tests for the guarded plain-text renderer + three starter templates (D-01/02/03).

The renderer substitutes a flat ``Forecast.placeholders()`` map into the editable
``.txt`` templates. It is guarded: a missing/typo'd placeholder stays VISIBLE as
``{key}`` and never crashes (T-03-03), and substitution never uses
``str.format(**obj)`` or ``eval`` (T-03-02). The ``compact`` template is the plain
SMS-safe seam — no emoji.
"""

from __future__ import annotations

import re

from weatherbot.config.models import Location
from weatherbot.weather.models import Forecast

from templates.renderer import load_template, render

LOC = Location(name="New York", lat=40.7128, lon=-74.006)

TEMPLATES = (
    "briefing-sectioned.txt",
    "briefing-multiline.txt",
    "briefing-compact.txt",
)

# Light-emoji range used by the sectioned/multiline templates; compact must avoid it.
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")


def _forecast(load_fixture) -> Forecast:
    return Forecast.from_payloads(
        LOC,
        load_fixture("current_imperial_clear.json"),
        load_fixture("current_metric_clear.json"),
        load_fixture("forecast_imperial_clear.json"),
        load_fixture("forecast_metric_clear.json"),
    )


def test_renders_each_template_imperial_primary(load_fixture):
    values = _forecast(load_fixture).placeholders()
    for name in TEMPLATES:
        body = render(load_template(name), values)
        # No unsubstituted known placeholder remains; imperial-primary present.
        assert "New York" in body
        assert "°F" in body  # imperial-primary display
        assert "{location}" not in body
        assert "{temp}" not in body


def test_default_template_contains_location_and_high(load_fixture):
    values = _forecast(load_fixture).placeholders()
    raw = load_template("briefing-sectioned.txt")
    assert "{location}" in raw
    assert "{high}" in raw
    body = render(raw, values)
    assert "New York" in body


def test_missing_placeholder_stays_visible_and_does_not_raise():
    # A template referencing a key not in the values map must NOT crash and must
    # render the literal {missingkey} (T-03-03 guarded substitution).
    out = render("hello {missingkey} world", {"present": "x"})
    assert "{missingkey}" in out


def test_extra_values_are_ignored():
    out = render("only {a}", {"a": "1", "b": "2", "c": "3"})
    assert out == "only 1"


def test_compact_template_has_no_emoji():
    raw = load_template("briefing-compact.txt")
    assert _EMOJI.search(raw) is None


def test_renderer_uses_no_dangerous_substitution():
    """Guard against str.format(**obj) / eval (T-03-02) in the renderer source."""
    src = load_template("renderer.py")
    assert "eval(" not in src
    assert ".format(**" not in src
