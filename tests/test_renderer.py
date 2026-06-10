"""Tests for the guarded plain-text renderer + three starter templates (D-01/02/03).

The renderer substitutes a flat ``Forecast.placeholders()`` map into the editable
``.txt`` templates. It is guarded: a missing/typo'd placeholder stays VISIBLE as
``{key}`` and never crashes (T-03-03), and substitution never uses
``str.format(**obj)`` or ``eval`` (T-03-02). The ``compact`` template is the plain
SMS-safe seam — no emoji.
"""

from __future__ import annotations

import re

import pytest

from weatherbot.config.models import Location
from weatherbot.weather.models import Forecast

from templates.renderer import CANONICAL, load_template, render, validate_template

LOC = Location(
    name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York"
)

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
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
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


# --- TMPL-02 / D-10: validate_template enforces the canonical set -----------


def test_validate_template_rejects_non_canonical_token():
    # A typo'd placeholder must raise (fail loud, never ship blank — D-11).
    with pytest.raises(ValueError):
        validate_template("Now: {temprature}, {conditions}")


def test_validate_template_passes_clean_canonical_template():
    # A fully-canonical template validates silently (returns None).
    text = "{location} {date}: {temp}/{feels_like}, {hint}\n{alert}"
    assert validate_template(text) is None


def test_validate_template_passes_all_shipped_templates():
    for name in TEMPLATES:
        validate_template(load_template(name))  # must not raise


def test_canonical_matches_forecast_placeholder_keys(load_fixture):
    # CANONICAL must EXACTLY equal the keys Forecast.placeholders() emits (D-09).
    keys = set(_forecast(load_fixture).placeholders().keys())
    assert CANONICAL == keys


def test_templates_substitute_new_placeholders(load_fixture):
    # The new {feels_like}/{hint}/{alert} placeholders are present in the
    # starter templates and substitute (no literal token survives).
    values = _forecast(load_fixture).placeholders()
    for name in TEMPLATES:
        raw = load_template(name)
        assert "{feels_like}" in raw
        assert "{hint}" in raw
        assert "{alert}" in raw
        body = render(raw, values)
        assert "{feels_like}" not in body
        assert "{hint}" not in body
        assert "{alert}" not in body


def test_empty_hint_and_alert_collapse_cleanly():
    # When hint/alert are empty, their own lines collapse to nothing extra
    # (no dangling label, no literal token).
    template = "Now: {temp}\n{hint}\n{alert}"
    out = render(template, {"temp": "70°F", "hint": "", "alert": ""})
    # No leftover tokens; the empty lines render as blank lines only.
    assert "{hint}" not in out
    assert "{alert}" not in out
    assert out.startswith("Now: 70°F")
