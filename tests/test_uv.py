"""Unit tests for the pure UV-computation helper (Plan 14-02, UV-02).

Covers ``compute_uv`` (current/max/category/peak/crossing/window/stays_below) +
``uv_category`` against the Plan 14-01 deterministic ``hourly[].uvi`` fixtures
(anchored to 2024-06-14 NY: sunrise 04:40, sunset 19:40). Every crossing/window
assertion pins ``now=`` and passes an explicit ``ZoneInfo`` so the linear
interpolation is asserted to the minute.

The helper is pure (no I/O, no interactive-layer import) so Phase 15's monitor
can reuse it — see ``test_uv_module_is_interactive_layer_free``.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from weatherbot.weather.uv import UvSummary, compute_uv, uv_category

NY = ZoneInfo("America/New_York")
# Pinned "now": noon local on the fixtures' anchor day.
NOW = datetime(2024, 6, 14, 12, 0, tzinfo=NY)


# --------------------------------------------------------------------------- #
# uv_category — WHO bands, round-then-band (A2)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "uvi,expected",
    [
        (0.0, "Low"),
        (2.0, "Low"),
        (2.4, "Low"),  # rounds to 2
        (2.5, "Low"),  # banker's rounding (round half to even) → 2 → Low
        (3.0, "Moderate"),
        (5.0, "Moderate"),
        (5.6, "High"),  # rounds to 6 (the headline A2 case)
        (6.0, "High"),
        (7.0, "High"),
        (8.0, "Very High"),
        (10.0, "Very High"),
        (11.0, "Extreme"),
        (13.5, "Extreme"),
    ],
)
def test_uv_category_bands(uvi: float, expected: str) -> None:
    # round() uses banker's rounding; 2.5→2 (Low), 5.6→6 (High). The headline A2
    # case (5.6 → High) is what matters.
    assert uv_category(uvi) == expected


def test_uv_category_5_6_is_high() -> None:
    assert uv_category(5.6) == "High"


# --------------------------------------------------------------------------- #
# compute_uv — up-cross fixture (interpolated to the minute)
# --------------------------------------------------------------------------- #


def test_uvcross_current_and_max(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    # current == current.uvi verbatim (Pitfall 6); max == daily[0].uvi verbatim.
    assert s.current == 7.0
    assert s.max == 9.6
    assert s.category == "Very High"  # round(9.6) == 10 → Very High
    assert s.stays_below is False


def test_uvcross_crossing_interpolated_to_minute(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    # Up-cross between 10:00 (5.5) and 11:00 (7.0):
    #   frac = (6 - 5.5)/(7 - 5.5) = 1/3 → 10:00 + 20 min = 10:20.
    assert s.crossing_time is not None
    assert s.crossing_time.tzinfo is not None
    assert (s.crossing_time.hour, s.crossing_time.minute) == (10, 20)
    # window_start == crossing_time on an up-cross.
    assert s.window_start == s.crossing_time


def test_uvcross_window_end_down_cross_interpolated(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    # Down-cross between 15:00 (6.5) and 16:00 (5.0):
    #   frac = (6.5 - 6)/(6.5 - 5.0) = 0.5/1.5 = 1/3 → 15:00 + 20 min = 15:20.
    assert s.window_end is not None
    assert (s.window_end.hour, s.window_end.minute) == (15, 20)


def test_uvcross_peak_clock_from_hourly_argmax(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    # Peak hourly point is 13:00 @ 9.6.
    assert s.peak_time is not None
    assert (s.peak_time.hour, s.peak_time.minute) == (13, 0)
    assert s.peak_uvi == 9.6


# --------------------------------------------------------------------------- #
# compute_uv — stays-below fixture
# --------------------------------------------------------------------------- #


def test_uvbelow_stays_below(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvbelow.json")
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    assert s.stays_below is True
    assert s.crossing_time is None
    assert s.window_start is None
    assert s.window_end is None
    # current/max still populated; category from max (4.5 → round 4 → Moderate).
    assert s.current == 4.2
    assert s.max == 4.5
    assert s.category == "Moderate"
    # Peak clock still reflects the day's hourly argmax (first of the two 4.5s @ 12:00).
    assert s.peak_time is not None
    assert (s.peak_time.hour, s.peak_time.minute) == (12, 0)
    assert s.peak_uvi == 4.5


# --------------------------------------------------------------------------- #
# compute_uv — already-above-at-sunrise fixture
# --------------------------------------------------------------------------- #


def test_highuv_already_above_no_interpolation(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_highuv.json")
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    assert s.stays_below is False
    # First daytime point is 05:00 @ 6.2 (>= 6) → crossing == window_start == that point.
    assert s.crossing_time is not None
    assert (s.crossing_time.hour, s.crossing_time.minute) == (5, 0)
    assert s.window_start == s.crossing_time
    # Down-cross between 17:00 (6.4) and 18:00 (5.0):
    #   frac = (6.4-6)/(6.4-5.0) = 0.4/1.4 ≈ 0.2857 → 17:00 + ~17 min = 17:17.
    assert s.window_end is not None
    assert (s.window_end.hour, s.window_end.minute) == (17, 17)


# --------------------------------------------------------------------------- #
# Robustness: missing sunrise/sunset, empty hourly, tz correctness
# --------------------------------------------------------------------------- #


def test_missing_sunrise_falls_back_to_fixed_window(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    # Strip sun data from daily[0] — must NOT raise, fall back to 06:00-20:00 local.
    raw = {**raw, "daily": [{k: v for k, v in raw["daily"][0].items()
                             if k not in ("sunrise", "sunset")}]}
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    # With the 06:00-20:00 fallback the 05:00 bucket is excluded; the up-cross
    # (10:20) still resolves the same way.
    assert s.stays_below is False
    assert s.crossing_time is not None
    assert (s.crossing_time.hour, s.crossing_time.minute) == (10, 20)


def test_empty_hourly_returns_stays_below_no_raise(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    raw = {**raw, "hourly": []}
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    assert s.stays_below is True
    assert s.crossing_time is None
    assert s.window_start is None
    assert s.window_end is None
    assert s.peak_time is None
    # current/max still read from current/daily (independent of hourly).
    assert s.current == 7.0
    assert s.max == 9.6


def test_missing_hourly_key_returns_stays_below_no_raise(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    raw = {k: v for k, v in raw.items() if k != "hourly"}
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    assert s.stays_below is True
    assert s.crossing_time is None
    assert s.peak_time is None


def test_malformed_bucket_with_none_fields_skipped(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    bad = [{"dt": None, "uvi": 9.9}, {"dt": 1718373600, "uvi": None}]
    raw = {**raw, "hourly": bad + list(raw["hourly"])}
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    # Bad buckets are skipped; the real up-cross (10:20) still resolves.
    assert s.crossing_time is not None
    assert (s.crossing_time.hour, s.crossing_time.minute) == (10, 20)


def test_malformed_bucket_with_nonnumeric_fields_skipped(load_fixture) -> None:
    # CR-01: a PRESENT-but-non-numeric uvi/dt (provider schema drift) must be
    # skipped, NOT raise — the null-only guard does not cover "NA"/list/str.
    raw = load_fixture("onecall_imperial_uvcross.json")
    bad = [
        {"dt": 1718373600, "uvi": "NA"},   # non-numeric uvi → ValueError on float()
        {"dt": "not-an-epoch", "uvi": 7.0},  # non-int dt → TypeError on fromtimestamp
        {"dt": 1718373600, "uvi": [1, 2]},   # list uvi → TypeError on float()
        {"dt": {"x": 1}, "uvi": 7.0},        # dict dt → TypeError on int()
    ]
    raw = {**raw, "hourly": bad + list(raw["hourly"])}
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    # The malformed buckets are skipped; the real up-cross (10:20) still resolves.
    assert s.crossing_time is not None
    assert (s.crossing_time.hour, s.crossing_time.minute) == (10, 20)


def test_only_malformed_buckets_returns_stays_below_no_raise(load_fixture) -> None:
    # CR-01: an hourly[] of ENTIRELY malformed buckets must degrade to
    # stays_below (a valid UvSummary), never raise.
    raw = load_fixture("onecall_imperial_uvcross.json")
    raw = {**raw, "hourly": [{"dt": "x", "uvi": "NA"}, {"dt": None, "uvi": "NA"}]}
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    assert isinstance(s, UvSummary)
    assert s.stays_below is True
    assert s.crossing_time is None
    assert s.peak_time is None
    # current/max still read verbatim (independent of hourly[]).
    assert s.current == 7.0
    assert s.max == 9.6


def test_nonnumeric_current_and_max_uvi_no_raise(load_fixture) -> None:
    # CR-01: a present-but-non-numeric current.uvi / daily[0].uvi degrades to 0.0
    # rather than raising out of the briefing spine.
    raw = load_fixture("onecall_imperial_uvcross.json")
    raw = {
        **raw,
        "current": {**raw.get("current", {}), "uvi": "NA"},
        "daily": [{**raw["daily"][0], "uvi": "bad"}, *raw["daily"][1:]],
    }
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    assert s.current == 0.0
    assert s.max == 0.0
    assert s.category == "Low"


def test_completely_empty_payload_no_raise() -> None:
    s = compute_uv({}, None, 6.0, tz=NY, now=NOW)
    assert isinstance(s, UvSummary)
    assert s.stays_below is True
    assert s.current == 0.0
    assert s.max == 0.0
    assert s.crossing_time is None
    assert s.peak_time is None


def test_uses_passed_tz_not_api_timezone(load_fixture) -> None:
    # Even if the payload carried an API "timezone" field, compute_uv must use the
    # passed-in tz for "today"/daytime. Inject a bogus API tz; result must be
    # identical to the NY-tz computation.
    raw = load_fixture("onecall_imperial_uvcross.json")
    raw = {**raw, "timezone": "Asia/Tokyo", "timezone_offset": 32400}
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    assert s.crossing_time is not None
    assert (s.crossing_time.hour, s.crossing_time.minute) == (10, 20)
    assert s.crossing_time.tzinfo is NY


def test_onecall_met_accepted_but_ignored(load_fixture) -> None:
    # A1: only onecall_imp is read; passing a wildly different metric payload must
    # not change the result.
    raw = load_fixture("onecall_imperial_uvcross.json")
    bogus_met = {"current": {"uvi": 999}, "daily": [{"uvi": 999}], "hourly": []}
    s = compute_uv(raw, bogus_met, 6.0, tz=NY, now=NOW)
    assert s.current == 7.0
    assert s.max == 9.6


def test_now_defaults_to_today_when_omitted(load_fixture, monkeypatch) -> None:
    # When now= is omitted, compute_uv uses datetime.now(tz); the helper must not
    # raise. (We can't pin the wall clock, but the call must succeed.)
    raw = load_fixture("onecall_imperial_uvcross.json")
    s = compute_uv(raw, None, 6.0, tz=NY)
    assert isinstance(s, UvSummary)


def test_summary_is_frozen(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    with pytest.raises(Exception):
        s.current = 1.0  # type: ignore[misc]


def test_hourly_points_are_daytime_pairs(load_fixture) -> None:
    raw = load_fixture("onecall_imperial_uvcross.json")
    s = compute_uv(raw, None, 6.0, tz=NY, now=NOW)
    # Tuple of (datetime, float) daytime points for the command's hourly line.
    assert isinstance(s.hourly_points, tuple)
    assert len(s.hourly_points) >= 1
    dt0, uvi0 = s.hourly_points[0]
    assert isinstance(dt0, datetime)
    assert isinstance(uvi0, float)


def test_uv_module_is_interactive_layer_free() -> None:
    # Phase-15 reuse rule: the module must not import the interactive layer.
    import inspect

    import weatherbot.weather.uv as uvmod

    src = inspect.getsource(uvmod)
    assert "weatherbot.interactive" not in src
