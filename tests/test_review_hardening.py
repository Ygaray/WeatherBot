"""Regression tests for the two critical findings in 01-REVIEW.md.

CR-01 — the renderer must NOT expose attribute/index/positional access through
``str.format`` field parsing, and must never crash on a malformed template
(threat mitigations T-03-02 / T-03-03).

CR-02 — a present-but-``null`` field in an OpenWeather payload must not crash the
briefing pipeline. ``dict.get(key, default)`` returns ``None`` when the key is
present with a null value, so every consumer must coerce null, not rely on the
default. This protects the project's core reliability constraint (retry/alert,
never silently miss a briefing).
"""

from __future__ import annotations

from datetime import datetime, timezone

from weatherbot.config.models import Location
from weatherbot.weather.aggregate import today_aggregate
from weatherbot.weather.models import Forecast
from weatherbot.weather.store import persist

from templates.renderer import render

NOW = datetime(2024, 6, 14, 12, 0, tzinfo=timezone.utc)
DT = int(NOW.timestamp())
LOC = Location(name="X", lat=0.0, lon=0.0)


# --- CR-01: renderer hardening -------------------------------------------------


def test_attribute_access_is_not_evaluated():
    # str.format would resolve {conditions.__class__}; the guarded renderer must
    # leave it literal (no attribute traversal — T-03-02).
    out = render("{conditions.__class__}", {"conditions": "Rain"})
    assert out == "{conditions.__class__}"


def test_index_access_is_not_evaluated():
    out = render("{a[0]}", {"a": "hello"})
    assert out == "{a[0]}"


def test_positional_field_does_not_crash():
    # {0} would raise IndexError under vformat with no positional args.
    out = render("{0}", {"a": "1"})
    assert out == "{0}"


def test_unbalanced_brace_does_not_crash():
    # A lone '{' makes str.format raise ValueError; the renderer must not crash.
    out = render("now 100% {temp", {"temp": "72"})
    assert "{temp" in out


def test_known_placeholder_still_substitutes():
    assert render("hi {name}", {"name": "Bob"}) == "hi Bob"


# --- CR-02: present-but-null field tolerance -----------------------------------


def test_aggregate_tolerates_null_pop():
    payload = {
        "city": {"timezone": 0},
        "list": [{"dt": DT, "main": {"temp": 70.0}, "pop": None}],
    }
    result = today_aggregate(payload, now_utc=NOW)
    assert result["rain_chance"] == 0
    assert result["high"] == 70.0


def test_aggregate_tolerates_null_main():
    payload = {
        "city": {"timezone": 0},
        "list": [{"dt": DT, "main": None, "pop": 0.1}],
    }
    result = today_aggregate(payload, now_utc=NOW)
    # No usable temp -> high/low None; rain still derived from pop.
    assert result["high"] is None
    assert result["low"] is None
    assert result["rain_chance"] == 10


def test_aggregate_tolerates_null_city():
    payload = {"city": None, "list": []}
    result = today_aggregate(payload, now_utc=NOW)
    assert result == {"high": None, "low": None, "rain_chance": 0}


def test_forecast_from_payloads_tolerates_null_current_fields():
    current = {"main": None, "wind": None, "weather": None, "dt": DT}
    forecast = {"city": None, "list": []}
    fc = Forecast.from_payloads(LOC, current, current, forecast, forecast, now_utc=NOW)
    # Must not raise; display fields are safe to read.
    assert fc.temp_display
    assert fc.conditions == ""


def test_persist_skips_forecast_bucket_without_dt(tmp_db):
    forecast = {"city": {"timezone": 0}, "list": [{"main": {"temp": 1.0}, "pop": 0.0}]}
    current = {"main": {"temp": 1.0}, "dt": DT}
    fc = Forecast.from_payloads(LOC, current, current, forecast, forecast, now_utc=NOW)
    # A bucket with no "dt" must be skipped, not raise KeyError.
    persist(tmp_db, LOC, fc)
