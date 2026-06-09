"""Fixture-driven tests for the PURE today_aggregate bucket aggregation (FCST-02).

The aggregation must select today's 3-hour buckets by the LOCATION's local date
(derived from ``city.timezone``), NOT the host/UTC date, and must survive a
clear-sky day where ``rain`` is absent and ``pop`` is 0. ``now_utc`` is injected
so these assertions are deterministic against the recorded fixtures (whose unix
``dt`` values fall on 2024-06-14 local).
"""

from __future__ import annotations

from datetime import datetime, timezone

from weatherbot.weather.aggregate import today_aggregate

# A UTC instant that lands on 2024-06-14 LOCAL for the New York fixtures
# (offset -14400s): 16:00Z -> 12:00 local on 2024-06-14.
NY_NOW = datetime(2024, 6, 14, 16, 0, tzinfo=timezone.utc)


def test_rainy_base(load_fixture):
    """Rainy fixture: high/low over local-today buckets; rain == round(max pop * 100)."""
    payload = load_fixture("forecast_imperial_rainy.json")
    result = today_aggregate(payload, now_utc=NY_NOW)
    # Local-today (2024-06-14) buckets are temps 60, 62, 61, 57 (the 5th is 06-15).
    assert result["high"] == 62.0
    assert result["low"] == 57.0
    # max pop over today's buckets is 0.85 -> 85.
    assert result["rain_chance"] == 85


def test_clear_sky(load_fixture):
    """Clear-sky fixture: no ``rain`` key, pop all 0 -> rain_chance 0, no KeyError."""
    payload = load_fixture("forecast_imperial_clear.json")
    result = today_aggregate(payload, now_utc=NY_NOW)
    # Local-today buckets: temps 66, 72, 75, 63.
    assert result["high"] == 75.0
    assert result["low"] == 63.0
    assert result["rain_chance"] == 0


def test_tz_boundary_plus(load_fixture):
    """+offset (Sydney +14h): local-today selection differs from naive UTC-today."""
    payload = load_fixture("forecast_imperial_offset_plus.json")
    # Pick a UTC instant where Sydney local date is 2024-06-14.
    # 1718323200 = 2024-06-14 00:00 UTC -> +14h = 14:00 local on 2024-06-14.
    sydney_now = datetime.fromtimestamp(1718323200, tz=timezone.utc)
    result = today_aggregate(payload, now_utc=sydney_now)
    # Local-today buckets are the first three (temps 80, 83, 79); the 4th bucket
    # (dt=1718388000) is local 2024-06-15 though its UTC date is 2024-06-14 --
    # a naive UTC-date selection would WRONGLY include it (temp 76).
    assert result["high"] == 83.0
    assert result["low"] == 79.0


def test_tz_boundary_minus(load_fixture):
    """-offset (Honolulu -10h): local-today selection differs from naive UTC-today."""
    payload = load_fixture("forecast_imperial_offset_minus.json")
    # 1718366400 = 2024-06-14 12:00 UTC -> -10h = 02:00 local on 2024-06-14.
    honolulu_now = datetime.fromtimestamp(1718366400, tz=timezone.utc)
    result = today_aggregate(payload, now_utc=honolulu_now)
    # Local-today buckets are indices 1,2,3 (temps 82, 85, 81); index 0
    # (dt=1718323200) is local 2024-06-13 though its UTC date is 2024-06-14 --
    # a naive UTC-date selection would WRONGLY include it (temp 78).
    assert result["high"] == 85.0
    assert result["low"] == 81.0


def test_late_day_no_buckets(load_fixture):
    """Zero remaining local-today buckets -> high/low None (fallback handled in models)."""
    payload = load_fixture("forecast_imperial_clear.json")
    # All fixture buckets are 2024-06-14/15 local; pick a far-future "now".
    far_future = datetime(2024, 6, 20, 16, 0, tzinfo=timezone.utc)
    result = today_aggregate(payload, now_utc=far_future)
    assert result["high"] is None
    assert result["low"] is None
    assert result["rain_chance"] == 0


def test_unit_agnostic(load_fixture):
    """Metric fixture: same selection behaviour, numbers differ, algorithm identical."""
    payload = load_fixture("forecast_metric_clear.json")
    result = today_aggregate(payload, now_utc=NY_NOW)
    # Local-today metric temps: 18.9, 22.2, 23.9, 17.2.
    assert result["high"] == 23.9
    assert result["low"] == 17.2
    assert result["rain_chance"] == 0
