"""Tests for the normalized Forecast model (FCST-03/04).

The Forecast normalizes current + forecast payloads (both imperial and metric),
exposes imperial-primary-with-metric display strings, applies the late-day
high/low fallback (Open Question 2), retains the four raw payloads for the store
(DATA-03), and exposes a flat ``placeholders()`` map keyed by the D-01 set.
"""

from __future__ import annotations

from datetime import datetime, timezone

from weatherbot.config.models import Location
from weatherbot.weather.models import Forecast

LOC = Location(name="New York", lat=40.7128, lon=-74.006)
# A UTC instant that lands on 2024-06-14 LOCAL for the NY fixtures (-14400s).
NY_NOW = datetime(2024, 6, 14, 16, 0, tzinfo=timezone.utc)

# The D-01 canonical placeholder set the renderer consumes.
D01_PLACEHOLDERS = {
    "temp",
    "high",
    "low",
    "rain",
    "wind",
    "humidity",
    "conditions",
    "location",
    "date",
}


def _build(load_fixture, now_utc=NY_NOW):
    return Forecast.from_payloads(
        LOC,
        load_fixture("current_imperial_clear.json"),
        load_fixture("current_metric_clear.json"),
        load_fixture("forecast_imperial_clear.json"),
        load_fixture("forecast_metric_clear.json"),
        now_utc=now_utc,
    )


def test_normalizes_core_fields(load_fixture):
    fc = _build(load_fixture)
    assert fc.location == "New York"
    assert fc.lat == 40.7128
    assert fc.lon == -74.006
    assert fc.humidity == 52
    assert fc.conditions == "Clear"
    assert fc.rain_chance == 0


def test_imperial_primary_displays(load_fixture):
    fc = _build(load_fixture)
    # current imperial temp 68.0 / metric 20.0
    assert fc.temp_display == "68°F (20°C)"
    # wind imperial 8.05 -> 8 mph, metric 3.6 -> 3.6 m/s
    assert fc.wind_display == "8 mph (3.6 m/s)"
    # aggregated local-today: imperial high 75 / metric 23.9->24; low 63 / 17.2->17
    assert fc.high_display == "75°F (24°C)"
    assert fc.low_display == "63°F (17°C)"


def test_clear_sky_renders_without_error(load_fixture):
    fc = _build(load_fixture)
    assert fc.rain_chance == 0
    # All display properties render without raising on a clear-sky day.
    assert fc.temp_display
    assert fc.high_display
    assert fc.low_display


def test_late_day_high_low_fallback(load_fixture):
    # Far-future now -> no local-today buckets -> high/low aggregate None ->
    # display falls back to the current temp (Open Question 2 decision).
    far_future = datetime(2024, 6, 20, 16, 0, tzinfo=timezone.utc)
    fc = _build(load_fixture, now_utc=far_future)
    assert fc.high_display == fc.temp_display
    assert fc.low_display == fc.temp_display


def test_retains_raw_payloads(load_fixture):
    fc = _build(load_fixture)
    assert fc.raw_current_imp["name"] == "New York"
    assert fc.raw_current_met["main"]["temp"] == 20.0
    assert fc.raw_forecast_imp["city"]["name"] == "New York"
    assert fc.raw_forecast_met["city"]["name"] == "New York"


def test_null_humidity_renders_zero_percent(load_fixture):
    # WR-01: a present-but-null ``main.humidity`` must coalesce to 0, not render
    # the placeholder as ``"None%"`` (silently-wrong) or crash downstream int code.
    current_imp = load_fixture("current_imperial_clear.json")
    current_met = load_fixture("current_metric_clear.json")
    current_imp["main"]["humidity"] = None
    fc = Forecast.from_payloads(
        LOC,
        current_imp,
        current_met,
        load_fixture("forecast_imperial_clear.json"),
        load_fixture("forecast_metric_clear.json"),
        now_utc=NY_NOW,
    )
    assert fc.humidity == 0
    assert fc.placeholders()["humidity"] == "0%"


def test_placeholders_is_flat_d01_map(load_fixture):
    fc = _build(load_fixture)
    ph = fc.placeholders()
    assert set(ph.keys()) == D01_PLACEHOLDERS
    # Flat str -> str map (renderer-input seam, D-04).
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in ph.items())
    assert ph["location"] == "New York"
    assert ph["temp"] == "68°F (20°C)"
    assert ph["humidity"] == "52%"
    assert ph["rain"] == "0%"
    assert ph["conditions"] == "Clear"
