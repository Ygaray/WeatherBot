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


def test_null_dt_entry_skipped_in_date_index(imp):
    """# F113 / HARD-TEST-02 — a dt=None daily entry is skipped, never crashes.

    Pins the _date_index_map null-dt skip (multiday.py:52-56): an entry with
    "dt": None (and a fully-null entry) must be dropped from the date-index map
    so it never appears in the returned valid indices and never raises a
    TypeError from datetime.fromtimestamp(None, ...). A desired date whose ONLY
    candidate was the null-dt entry degrades to a horizon notice, not a crash.

    Construction: a mixed daily where idx 1 is {"dt": None} (would-be Tue 6/23)
    and idx 3 is a fully-null entry, surrounded by valid Mon/Wed/Thu/Fri entries.
    A weekday run on Mon 6/22 desires Mon-Fri; the good entries resolve to their
    real indices [0, 2, 4, 5] (note the skipped 1 and 3 are absent), while Tue
    6/23 — whose sole candidate was the null-dt slot — becomes a notice.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(_TZ)

    def _ts(y: int, m: int, d: int, h: int = 12) -> int:
        return int(datetime(y, m, d, h, tzinfo=tz).timestamp())

    daily = [
        {"dt": _ts(2026, 6, 22)},  # idx 0  Mon 6/22
        {"dt": None},              # idx 1  null-dt  -> skipped (F113)
        {"dt": _ts(2026, 6, 24)},  # idx 2  Wed 6/24
        None,                       # idx 3  fully-null entry -> skipped
        {"dt": _ts(2026, 6, 25)},  # idx 4  Thu 6/25
        {"dt": _ts(2026, 6, 26)},  # idx 5  Fri 6/26
    ]

    # The null-dt entries must not appear in the date-index map at all.
    by_date = multiday._date_index_map(daily, tz)
    assert set(by_date.values()) == {0, 2, 4, 5}  # idx 1 and 3 skipped

    indices, notices = multiday.select_days(
        "weekday", date(2026, 6, 22), daily, add=set(), drop=set(), tz=_TZ
    )
    # Good entries resolve; the skipped null-dt slots never appear in indices.
    assert indices == [0, 2, 4, 5]
    assert 1 not in indices and 3 not in indices
    # Tue 6/23's only candidate was the null-dt entry -> a notice, not a crash.
    assert len(notices) == 1
    assert "horizon" in notices[0].lower()


def test_weekend_run_on_monday_rolls_forward(imp):
    """# F111 / HARD-TEST-02 — weekend whole-block roll-forward, never IndexError.

    The weekday twin (test_weekday_run_on_saturday_rolls_forward, :168) pins the
    *weekday* block roll-forward; this pins the *weekend* block (kind='weekend',
    _WEEKEND_DAYS = fri/sat/sun) firing the whole-block roll-forward branch
    (multiday.py:104-107): when the remaining weekend token(s) are all past
    relative to `today_local`, the whole block rolls +1 week.

    Geometry note (why a drop is required to reach the branch): _WEEKEND_DAYS's
    latest member is `sun` whose signed delta `6 - today.weekday()` is >= 0 for
    every weekday, so the *full* fri/sat/sun set never has an empty `upcoming` —
    the roll-forward branch is only reachable once the trailing weekend day(s)
    are dropped, leaving a wholly-past remainder. Here `drop={sat,sun}` leaves
    only `fri`; on Sat 2026-06-13 that Friday (6/12) is already past, so the block
    rolls to NEXT week's Friday 2026-06-19 = fixture idx 0. This is the exact
    weekend analog of the weekday twin's roll-forward assertion, deterministic
    against the 8-day fixture, and proves NO IndexError on the rolled index.
    """
    daily = imp["daily"]
    indices, notices = multiday.select_days(
        "weekend", date(2026, 6, 13), daily, add=set(), drop={"sat", "sun"}, tz=_TZ
    )
    # fri/sat/sun with sat+sun dropped -> only fri; Fri 6/12 is past on Sat 6/13,
    # so the whole (remaining) block rolls +7 to next Fri 6/19 = idx 0.
    assert indices == [0]
    assert notices == []


def test_weekend_roll_forward_beyond_horizon_returns_notice(imp):
    """# F111 / HARD-TEST-02 — rolled-forward weekend day past the horizon → notice.

    Same whole-block roll-forward branch (multiday.py:104-107), but the rolled
    target lands beyond the fixture's 7-day horizon (Fri 6/26): dropping fri+sun
    leaves only `sat`; on Sun 2026-06-21 that Saturday (6/20) is past, so it rolls
    to next Sat 2026-06-27 — beyond the 6/26 horizon → a notice, never a silent
    drop or IndexError (multiday.py:127-128).
    """
    daily = imp["daily"]
    indices, notices = multiday.select_days(
        "weekend", date(2026, 6, 21), daily, add=set(), drop={"fri", "sun"}, tz=_TZ
    )
    assert indices == []
    assert len(notices) == 1
    assert "horizon" in notices[0].lower()


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


def test_drop_beats_contradictory_same_day_add(imp):
    """# HARD-CLEAN-02 / F70 — drop wins over a contradictory same-day add.

    Pre-fix, `add` was applied AFTER `drop` (multiday.py add loop), so a same-day
    `+X -X` re-added the dropped day (drop could not override an explicit add). This
    pins the fixed semantics: for the SAME day, drop beats add — Saturday is excluded
    when both add={"sat"} and drop={"sat"} are given. Non-contradictory add-only,
    drop-only, and disjoint add/drop cases must behave exactly as before.

    Base geometry: weekday run on Sat 2026-06-20 rolls the Mon-Fri block to next week
    (Mon 6/22..Fri 6/26 = idx 3..7). Saturday's next occurrence from Sat 6/20 is the
    same day 6/20 = idx 1 when added.
    """
    daily = imp["daily"]
    run_day = date(2026, 6, 20)  # Saturday
    base_kwargs = dict(tz=_TZ)

    # Contradictory same-day +sat -sat → Saturday (idx 1) is NOT in the result.
    indices, notices = multiday.select_days(
        "weekday", run_day, daily, add={"sat"}, drop={"sat"}, **base_kwargs
    )
    assert 1 not in indices, "drop must beat a contradictory same-day add"
    assert indices == [3, 4, 5, 6, 7]  # weekday block only; sat excluded
    assert notices == []

    # Non-contradictory add-only → Saturday IS added (unchanged behavior).
    indices_add, _ = multiday.select_days(
        "weekday", run_day, daily, add={"sat"}, drop=set(), **base_kwargs
    )
    assert 1 in indices_add
    assert indices_add == [1, 3, 4, 5, 6, 7]

    # Non-contradictory drop-only → Saturday excluded (it wasn't in the base anyway;
    # the weekday block is unchanged, no crash).
    indices_drop, _ = multiday.select_days(
        "weekday", run_day, daily, add=set(), drop={"sat"}, **base_kwargs
    )
    assert 1 not in indices_drop
    assert indices_drop == [3, 4, 5, 6, 7]

    # Disjoint add/drop preserved: +sat with -mon (drop a base day, add a different
    # day) resolves independently — sat added, mon dropped, no interaction.
    indices_disjoint, _ = multiday.select_days(
        "weekday", run_day, daily, add={"sat"}, drop={"mon"}, **base_kwargs
    )
    assert 1 in indices_disjoint          # sat added
    assert indices_disjoint == [1, 4, 5, 6, 7]  # mon (idx 3) dropped, sat (idx 1) added


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
