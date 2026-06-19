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

from datetime import date

from weatherbot.weather import multiday
from weatherbot.weather.models import ForecastDay

_FIX = Path(__file__).parent / "fixtures"
_TZ = "America/New_York"

# Fixture local dates (America/New_York):
#   idx 0: Fri 2026-06-19   idx 1: Sat 06-20   idx 2: Sun 06-21
#   idx 3: Mon 06-22        idx 4: Tue 06-23   idx 5: Wed 06-24
#   idx 6: Thu 06-25        idx 7: Fri 06-26


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


# --------------------------------------------------------------------------- #
# Task 2: multiday.select_days window / roll-forward / horizon
# --------------------------------------------------------------------------- #


def test_weekday_run_on_monday_returns_five_indices(imp):
    """A weekday forecast run on a fixture Monday → Mon-Fri, no notices (FCAST-01)."""
    daily = imp["daily"]
    indices, notices = multiday.select_days(
        "weekday", date(2026, 6, 22), daily, add=set(), drop=set(), tz=_TZ
    )
    # Mon 6/22(3), Tue 6/23(4), Wed 6/24(5), Thu 6/25(6), Fri 6/26(7)
    assert indices == [3, 4, 5, 6, 7]
    assert notices == []


def test_weekday_mid_block_drops_past_days(imp):
    """Run mid-block (Wednesday) → only the still-upcoming Wed-Fri."""
    daily = imp["daily"]
    indices, notices = multiday.select_days(
        "weekday", date(2026, 6, 24), daily, add=set(), drop=set(), tz=_TZ
    )
    # Wed 6/24(5), Thu 6/25(6), Fri 6/26(7); Mon/Tue already past
    assert indices == [5, 6, 7]
    assert notices == []


def test_weekend_run_returns_fri_sat_sun(imp):
    """A weekend forecast → the Fri-Sat-Sun indices (FCAST-02)."""
    daily = imp["daily"]
    indices, notices = multiday.select_days(
        "weekend", date(2026, 6, 19), daily, add=set(), drop=set(), tz=_TZ
    )
    # Fri 6/19(0), Sat 6/20(1), Sun 6/21(2)
    assert indices == [0, 1, 2]
    assert notices == []


def test_weekday_run_on_saturday_rolls_forward(imp):
    """Weekday run on a Saturday rolls to next week's Mon-Fri, never IndexError."""
    daily = imp["daily"]
    indices, notices = multiday.select_days(
        "weekday", date(2026, 6, 20), daily, add=set(), drop=set(), tz=_TZ
    )
    # Next-week Mon 6/22(3)..Fri 6/26(7) are in window.
    assert indices == [3, 4, 5, 6, 7]
    assert notices == []


def test_add_flag_beyond_horizon_returns_notice(imp):
    """+sat beyond the 7-day horizon → a notice string, never a silent drop (FCAST-04, Pitfall 2)."""
    daily = imp["daily"]
    # On Thu 6/25 a +sat names Sat 6/27 — beyond the fixture's 6/26 horizon.
    indices, notices = multiday.select_days(
        "weekday", date(2026, 6, 25), daily, add={"sat"}, drop=set(), tz=_TZ
    )
    # Thu 6/25(6), Fri 6/26(7) in window; Sat 6/27 out of horizon → notice.
    assert indices == [6, 7]
    assert len(notices) == 1
    assert "horizon" in notices[0].lower()


def test_drop_and_add_deduped_calendar_sorted(imp):
    """-mon +sat yields a deduped, calendar-sorted index list."""
    daily = imp["daily"]
    indices, notices = multiday.select_days(
        "weekday", date(2026, 6, 22), daily, add={"sat"}, drop={"mon"}, tz=_TZ
    )
    # base mon-fri minus mon = tue..fri (next week 6/23..6/26); +sat... but next
    # Saturday from Mon 6/22 is 6/27 (out of horizon). So sat becomes a notice.
    assert indices == [4, 5, 6, 7]
    assert len(notices) == 1


def test_add_existing_day_is_noop(imp):
    """Adding a day already in the base range is a dedup no-op."""
    daily = imp["daily"]
    indices, _ = multiday.select_days(
        "weekday", date(2026, 6, 22), daily, add={"wed"}, drop=set(), tz=_TZ
    )
    assert indices == [3, 4, 5, 6, 7]
    assert indices == sorted(set(indices))


def test_unknown_kind_raises(imp):
    """Unknown kind fails loud with ValueError (T-13-03)."""
    with pytest.raises(ValueError):
        multiday.select_days(
            "monthly", date(2026, 6, 22), imp["daily"], add=set(), drop=set(), tz=_TZ
        )


def test_no_positional_date_today_in_module():
    """multiday must compute today from the passed tz, never date.today()."""
    src = (
        Path(__file__).parent.parent / "weatherbot" / "weather" / "multiday.py"
    ).read_text()
    assert "date.today()" not in src
