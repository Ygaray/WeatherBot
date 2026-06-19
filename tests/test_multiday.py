"""Tests for Phase 13 Wave-0 foundations: ``ForecastDay`` extraction (Task 1) and
the ``multiday.select_days`` window/roll-forward selector (Task 2).

The 8-day fixtures (``onecall_8day_imperial.json`` / ``_metric.json``) carry eight
dated ``daily[]`` entries spanning Fri 2026-06-19 → Fri 2026-06-26 in
``America/New_York`` so window/roll-forward/horizon tests are deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from weatherbot.weather.models import ForecastDay

_FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((_FIX / name).read_text())


@pytest.fixture
def imp() -> dict:
    return _load("onecall_8day_imperial.json")


@pytest.fixture
def met() -> dict:
    return _load("onecall_8day_metric.json")


# --------------------------------------------------------------------------- #
# Task 1: ForecastDay extraction
# --------------------------------------------------------------------------- #


def test_extract_basic_fields(imp, met):
    day = ForecastDay.from_daily(imp["daily"][0], met["daily"][0], label="Today")
    assert day.high_imp == 76.0
    assert day.low_imp == 58.0
    assert day.sky == "Clear"
    assert day.rain_chance == 10  # round(0.1 * 100)
    assert day.uvi == 5.2
    assert day.label == "Today"


def test_forecastday_compact_token_keys(imp, met):
    day = ForecastDay.from_daily(imp["daily"][1], met["daily"][1], label="Tomorrow")
    assert set(day.day_tokens(detailed=False).keys()) == {"label", "high", "low", "sky"}


def test_forecastday_detailed_token_keys(imp, met):
    day = ForecastDay.from_daily(imp["daily"][1], met["daily"][1], label="Sat 6/20")
    tokens = day.day_tokens(detailed=True)
    assert set(tokens.keys()) == {
        "label",
        "high",
        "low",
        "sky",
        "rain",
        "wind",
        "uvi",
        "feels_high",
        "feels_low",
        "sunrise",
        "sunset",
    }
    assert len(tokens) == 11


def test_temp_display_imperial_primary(imp, met):
    """Imperial-primary high display is byte-identical to Forecast._temp_str."""
    day = ForecastDay.from_daily(imp["daily"][0], met["daily"][0], label="Today")
    # high_imp 76.0 / high_met 24.44 → "76°F (24°C)"
    assert day.day_tokens(detailed=False)["high"] == "76°F (24°C)"
    assert day.day_tokens(detailed=False)["low"] == "58°F (14°C)"


def test_temp_display_metric_primary(imp, met):
    day = ForecastDay.from_daily(
        imp["daily"][0], met["daily"][0], label="Today", primary="metric"
    )
    assert day.day_tokens(detailed=False)["high"] == "24°C (76°F)"


def test_feels_high_low_from_dayparts(imp, met):
    """feels_high/low derive from max/min of the four feels_like dayparts (Pitfall 3)."""
    d_imp = imp["daily"][5]  # feels_like day=82, night=65, eve=83, morn=64
    d_met = met["daily"][5]
    day = ForecastDay.from_daily(d_imp, d_met, label="Wed 6/24")
    assert day.feels_high_imp == 83.0
    assert day.feels_low_imp == 64.0


def test_null_fields_coalesce(imp, met):
    """A present-but-null daily field degrades, never raises (T-13-01)."""
    d_imp = {
        "dt": 1781884800,
        "sunrise": None,
        "sunset": None,
        "temp": {"max": None, "min": None},
        "feels_like": {},
        "pop": None,
        "uvi": None,
        "weather": [],
        "wind_speed": None,
    }
    d_met = dict(d_imp)
    day = ForecastDay.from_daily(d_imp, d_met, label="Today")
    assert day.rain_chance == 0
    assert day.uvi == 0.0
    assert day.sky == ""
    # day_tokens must not raise even with missing feels_like dayparts.
    tokens = day.day_tokens(detailed=True)
    assert tokens["label"] == "Today"
