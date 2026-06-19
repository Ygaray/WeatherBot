"""Tests for the normalized Forecast model (FCST-03/04/05/06).

The Forecast normalizes the two One Call 3.0 payloads (imperial + metric),
exposes imperial-primary-with-metric display strings (temp, feels-like, high/low,
wind), derives the five threshold hints (D-06/07) and the passive alert summary
(D-08), computes the local date from the CONFIGURED IANA tz (D-03), retains both
raw payloads for the store (DATA-03), and exposes a flat ``placeholders()`` map
keyed by the canonical set (D-09).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pydantic
import pytest

from weatherbot.config.models import (
    Config,
    Location,
    Reliability,
    Schedule,
    WebhookIdentity,
)
from weatherbot.weather.models import Forecast

LOC = Location(name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York")
# A UTC instant that lands on 2024-06-14 LOCAL for the NY fixtures (-04:00).
NY_NOW = datetime(2024, 6, 14, 16, 0, tzinfo=timezone.utc)
# Noon local on the UV fixtures' anchor day (mirrors tests/test_uv.py NOW), as a
# UTC instant so it threads through ``now_utc``: 12:00 EDT == 16:00 UTC.
UVCROSS_NOW = datetime(2024, 6, 14, 16, 0, tzinfo=timezone.utc)

# The canonical placeholder set the renderer consumes (D-09). Extended in Phase
# 14 Plan 03 with the six UV briefing tokens (UV-02).
CANONICAL_PLACEHOLDERS = {
    "temp",
    "feels_like",
    "high",
    "low",
    "rain",
    "wind",
    "humidity",
    "conditions",
    "location",
    "date",
    "hint",
    "alert",
    "uv_now",
    "uv_max",
    "uv_cross",
    "uv_window",
    "uv_peak",
    "uv_category",
}


def _build(load_fixture, imp="onecall_imperial_clear.json", met="onecall_metric_clear.json",
           now_utc=NY_NOW):
    return Forecast.from_payloads(
        LOC,
        load_fixture(imp),
        load_fixture(met),
        now_utc=now_utc,
    )


# --- from_payloads: One Call mapping ------------------------------------------


def test_from_payloads_normalizes_core_fields(load_fixture):
    fc = _build(load_fixture)
    assert fc.location == "New York"
    assert fc.lat == 40.7128
    assert fc.lon == -74.006
    assert fc.humidity == 52
    assert fc.conditions == "Clear"
    # daily[0].pop 0.1 -> 10%
    assert fc.rain_chance == 10
    # daily[0].uvi (the day's max) carried for the sunscreen hint.
    assert fc.uvi_max == 5.2


def test_from_payloads_imperial_primary_displays(load_fixture):
    fc = _build(load_fixture)
    # current imperial temp 68.0 / metric 20.0
    assert fc.temp_display == "68°F (20°C)"
    # current imperial feels_like 66.2 -> 66 / metric 19.0 -> 19
    assert fc.feels_like_display == "66°F (19°C)"
    # wind imperial 8.05 -> 8 mph, metric 3.6 -> 3.6 m/s
    assert fc.wind_display == "8 mph (3.6 m/s)"
    # daily[0].temp.max imperial 76 / metric 24.4->24; min 58 / 14.4->14
    assert fc.high_display == "76°F (24°C)"
    assert fc.low_display == "58°F (14°C)"


def test_from_payloads_metric_primary_displays(load_fixture):
    # primary="metric" flips the display order: metric value leads, imperial
    # sits in parens (counters the verified imperial-primary spot-check, CR-01).
    fc = Forecast.from_payloads(
        LOC,
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
        now_utc=NY_NOW,
        primary="metric",
    )
    assert fc.temp_display == "20°C (68°F)"
    assert fc.feels_like_display == "19°C (66°F)"
    assert fc.wind_display == "3.6 m/s (8 mph)"
    # daily[0].temp.max metric 24.4->24 / imperial 76; min 14.4->14 / 58
    assert fc.high_display == "24°C (76°F)"
    assert fc.low_display == "14°C (58°F)"
    # placeholders honor primary too — temp leads with °C.
    ph = fc.placeholders()
    assert ph["temp"] == "20°C (68°F)"
    assert set(ph.keys()) == CANONICAL_PLACEHOLDERS


def test_from_payloads_imperial_primary_is_default(load_fixture):
    # Omitting primary keeps imperial-primary, byte-identical to today.
    fc = _build(load_fixture)
    assert fc.temp_display == "68°F (20°C)"
    assert fc.wind_display == "8 mph (3.6 m/s)"


def test_null_feels_like_no_fabricated_cold_hint(load_fixture):
    # WR-01: a present-but-null current.feels_like in BOTH payloads must NOT
    # fabricate a "cold"/"Bundle up" hint from a coalesced 0.0.
    imp = load_fixture("onecall_imperial_clear.json")
    met = load_fixture("onecall_metric_clear.json")
    imp["current"]["feels_like"] = None
    met["current"]["feels_like"] = None
    fc = Forecast.from_payloads(LOC, imp, met, now_utc=NY_NOW)
    assert "cold" not in fc.hint
    assert "Bundle up" not in fc.hint


def test_null_wind_no_fabricated_windy_hint(load_fixture):
    # WR-01: a present-but-null current.wind_speed must NOT fabricate a "Windy"
    # hint (a null wind coalesced to 0.0 cannot exceed the 25 mph threshold,
    # but the guard must hold regardless of coalesce).
    imp = load_fixture("onecall_imperial_clear.json")
    met = load_fixture("onecall_metric_clear.json")
    imp["current"]["wind_speed"] = None
    met["current"]["wind_speed"] = None
    fc = Forecast.from_payloads(LOC, imp, met, now_utc=NY_NOW)
    assert "Windy" not in fc.hint


def test_from_payloads_local_date_uses_configured_tz(load_fixture):
    # 16:00 UTC is 12:00 in America/New_York (-04:00 in June) -> 2024-06-14.
    fc = _build(load_fixture)
    assert fc.local_date == "2024-06-14"


def test_from_payloads_retains_raw_payloads(load_fixture):
    fc = _build(load_fixture)
    assert fc.raw_onecall_imp["current"]["temp"] == 68.0
    assert fc.raw_onecall_met["current"]["temp"] == 20.0
    assert fc.raw_onecall_imp["timezone"] == "America/New_York"


def test_null_humidity_renders_zero_percent(load_fixture):
    # A present-but-null ``current.humidity`` must coalesce to 0, not render
    # ``"None%"`` (silently-wrong) or crash downstream int code (CR-02).
    imp = load_fixture("onecall_imperial_clear.json")
    met = load_fixture("onecall_metric_clear.json")
    imp["current"]["humidity"] = None
    fc = Forecast.from_payloads(LOC, imp, met, now_utc=NY_NOW)
    assert fc.humidity == 0
    assert fc.placeholders()["humidity"] == "0%"


# --- hints (D-06/07): each threshold fires; none -> empty ---------------------


def test_hints_empty_on_clear_day(load_fixture):
    # clear: pop 10% (<=40), feels 66.2 (in [40,90]), wind 8 (<25), uvi 5.2 (<6).
    fc = _build(load_fixture)
    assert fc.hint == ""
    assert fc.placeholders()["hint"] == ""


def test_hints_umbrella_on_rain(load_fixture):
    # rainy: daily pop 0.85 -> 85% (>40) -> umbrella hint.
    fc = _build(load_fixture, imp="onecall_imperial_rainy.json",
                met="onecall_metric_rainy.json")
    assert "umbrella" in fc.hint


def test_hints_sunscreen_on_high_uv(load_fixture):
    # highuv: daily[0].uvi 9.6 (>=6) -> sunscreen hint.
    fc = _build(load_fixture, imp="onecall_imperial_highuv.json",
                met="onecall_imperial_highuv.json")
    assert "sunscreen" in fc.hint


def test_hints_cold_and_wind_on_extreme(load_fixture):
    # extreme: feels_like 14 (<40 -> cold) AND wind_speed 32 (>25 -> wind).
    fc = _build(load_fixture, imp="onecall_imperial_extreme.json",
                met="onecall_imperial_extreme.json")
    assert "cold" in fc.hint
    assert "Windy" in fc.hint
    # Multiple hints render one per line (D-07).
    assert "\n" in fc.hint


def test_hints_heat_above_threshold(load_fixture):
    # alert fixture: current.feels_like 92 (>90) -> heat hint.
    fc = _build(load_fixture, imp="onecall_imperial_alert.json",
                met="onecall_imperial_alert.json")
    assert "hot" in fc.hint


# --- alert (D-08): summary present; absent -> empty ---------------------------


def test_alert_empty_when_absent(load_fixture):
    # clear fixture has no ``alerts`` key (Pitfall 2) -> empty {alert}.
    fc = _build(load_fixture)
    assert fc.alert == ""
    assert fc.placeholders()["alert"] == ""


def test_alert_single_event(load_fixture):
    fc = _build(load_fixture, imp="onecall_imperial_alert.json",
                met="onecall_imperial_alert.json")
    assert "Heat Advisory" in fc.alert
    assert fc.alert.startswith("⚠️")


def test_alert_multi_event_summary(load_fixture):
    fc = _build(load_fixture, imp="onecall_imperial_multialert.json",
                met="onecall_imperial_multialert.json")
    # Distinct event names summarized concisely.
    assert "Severe Thunderstorm Warning" in fc.alert
    assert "Flash Flood Watch" in fc.alert
    assert ";" in fc.alert


# --- placeholders: flat canonical map -----------------------------------------


def test_placeholders_is_flat_canonical_map(load_fixture):
    fc = _build(load_fixture)
    ph = fc.placeholders()
    assert set(ph.keys()) == CANONICAL_PLACEHOLDERS
    # Flat str -> str map (renderer-input seam, D-04).
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in ph.items())
    assert ph["location"] == "New York"
    assert ph["temp"] == "68°F (20°C)"
    assert ph["feels_like"] == "66°F (19°C)"
    assert ph["humidity"] == "52%"
    assert ph["rain"] == "10%"
    assert ph["conditions"] == "Clear"
    assert ph["date"] == "2024-06-14"


# --------------------------------------------------------------------------- #
# Phase 8 D-02 — frozen=True mutation guard across ALL FIVE config models.
#
# Wave-0 RED scaffold: the models are NOT yet ``frozen=True`` (Plan 02 adds it),
# so rebinding a field SUCCEEDS today and ``pytest.raises`` fails ("DID NOT RAISE")
# — the intended RED. Plan 02 turns this GREEN. The guard asserts on pydantic's
# ``ValidationError`` (a frozen pydantic model raises ``ValidationError`` of type
# ``frozen_instance``), NEVER ``dataclasses.FrozenInstanceError`` (Pitfall 2 — these
# are pydantic BaseModels, not stdlib dataclasses).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("instance", "field", "new_value"),
    [
        (Schedule(time="07:00", days="daily"), "time", "08:00"),
        (LOC, "name", "Boston"),
        (WebhookIdentity(), "username", "OtherBot"),
        (Reliability(), "attempts_per_burst", 9),
        (Config(locations=[LOC]), "template", "other.txt"),
    ],
    ids=["Schedule", "Location", "WebhookIdentity", "Reliability", "Config"],
)
def test_frozen_rejects_mutation(instance, field, new_value):
    """D-02: every config model rejects post-construction field mutation.

    Asserts ``pydantic.ValidationError`` (type ``frozen_instance``) — NOT
    ``dataclasses.FrozenInstanceError`` (Pitfall 2). RED until Plan 02 sets
    ``frozen=True`` on each model's ``ConfigDict``.
    """
    with pytest.raises(pydantic.ValidationError):
        setattr(instance, field, new_value)


# --------------------------------------------------------------------------- #
# Phase 9 D-01 — optional stable ``Location.id`` (default = RAW name).
#
# Wave-0 RED scaffold: the ``id`` field does NOT exist yet (Plan 02 adds it on
# ``Location``), and the model is ``extra="forbid"``, so an explicit ``id=`` is
# rejected and ``.id`` is absent today — the intended RED. The exactly-once key
# (sent-log row) moves from the display ``name`` to this stable ``id``; ``id``
# defaults to the RAW ``name`` VERBATIM (NOT casefolded) so the stored key stays
# BYTE-IDENTICAL to existing rows for any config that omits ``id`` (zero
# migration, RESEARCH Pitfall 1 / Option A). Casefolding is used ONLY for the
# uniqueness collision check, never for the stored value.
# --------------------------------------------------------------------------- #


def test_location_id_default():
    """D-01: an un-``id``'d ``Location`` defaults ``.id`` to its RAW ``name``.

    The raw (non-casefolded) default keeps the sent-log key byte-identical to
    existing rows — ``loc.id == loc.name == "Home Base"`` (NOT ``"home base"``).
    RED until Plan 02 adds the field + the default-from-name after-validator.
    """
    loc = Location(
        name="Home Base", lat=40.7128, lon=-74.006, timezone="America/New_York"
    )
    assert loc.id == "Home Base"  # RAW name, not casefolded (zero-migration key)
    assert loc.id == loc.name


def test_location_id_explicit_wins():
    """D-01: an explicit ``id=`` is preserved VERBATIM (the operator's rename-safe
    stable identity), never overwritten by the name default."""
    loc = Location(
        name="Home Base",
        lat=40.7128,
        lon=-74.006,
        timezone="America/New_York",
        id="custom",
    )
    assert loc.id == "custom"  # explicit id kept; name default did not clobber it


def test_location_id_frozen():
    """D-01: ``Location`` is frozen, so rebinding ``.id`` after construction raises
    ``pydantic.ValidationError`` (type ``frozen_instance``) — mirrors the existing
    frozen-mutation guard, never ``dataclasses.FrozenInstanceError`` (Pitfall 2)."""
    loc = Location(
        name="Home Base",
        lat=40.7128,
        lon=-74.006,
        timezone="America/New_York",
        id="custom",
    )
    with pytest.raises(pydantic.ValidationError):
        loc.id = "rebind-not-allowed"


def test_duplicate_location_id_rejected():
    """D-01: two locations whose ids collide CASE-INSENSITIVELY (``Home`` / ``home``)
    fail the unique-id check with a ``ValueError`` — casefold is used for the
    collision test ONLY (the stored value stays raw). Mirrors ``assert_unique_names``.
    """
    from weatherbot.config.loader import assert_unique_names

    config = Config(
        locations=[
            Location(
                name="Alpha", lat=1.0, lon=2.0, timezone="America/New_York", id="Home"
            ),
            Location(
                name="Beta", lat=3.0, lon=4.0, timezone="America/Chicago", id="home"
            ),
        ]
    )
    with pytest.raises(ValueError):
        assert_unique_names(config)


# --------------------------------------------------------------------------- #
# Phase 14 Plan 03 — UV briefing line (UV-02) + threshold-driven sunscreen hint
# (UV-01/03 consumer #1, D-01 "unify three consumers").
#
# ``_hints`` now reads a configured ``uv_threshold`` (default 6.0 keeps existing
# behavior); ``from_payloads`` calls ``compute_uv`` and stashes six formatted UV
# display strings emitted from ``placeholders()`` in lockstep with
# ``renderer.CANONICAL``. Missing/empty ``hourly[]`` degrades gracefully and
# NEVER crashes the briefing render (T-14-07 briefing-spine isolation).
# --------------------------------------------------------------------------- #

from weatherbot.weather.models import _hints  # noqa: E402

# The six UV tokens the briefing line consumes — must be in BOTH
# ``Forecast.placeholders()`` and ``renderer.CANONICAL`` (Pitfall 3 lockstep).
UV_TOKENS = {"uv_now", "uv_max", "uv_cross", "uv_window", "uv_peak", "uv_category"}


# --- threshold-driven sunscreen hint (D-01) -----------------------------------


def test_hints_sunscreen_default_threshold_is_six():
    # Default uv_threshold=6.0 preserves the old hardcoded literal-6 behavior:
    # uvi 9.6 still fires, uvi 5.2 still does not.
    assert "sunscreen" in _hints(0, 70.0, 5.0, 9.6)
    assert "sunscreen" not in _hints(0, 70.0, 5.0, 5.2)


def test_hints_sunscreen_fires_at_configured_lower_threshold():
    # threshold 4.0 + uvi_max 5 → fires (threshold-driven, not literal 6).
    assert "sunscreen" in _hints(0, 70.0, 5.0, 5.0, uv_threshold=4.0)


def test_hints_sunscreen_suppressed_below_configured_higher_threshold():
    # threshold 8.0 + uvi_max 6 → does NOT fire (the old literal-6 would have).
    assert "sunscreen" not in _hints(0, 70.0, 5.0, 6.0, uv_threshold=8.0)


def test_from_payloads_threads_uv_threshold_into_hint(load_fixture):
    # clear fixture daily[0].uvi == 5.2: fires at threshold 4.0, not at 6.0.
    imp = load_fixture("onecall_imperial_clear.json")
    met = load_fixture("onecall_metric_clear.json")
    fc_low = Forecast.from_payloads(LOC, imp, met, now_utc=NY_NOW, uv_threshold=4.0)
    fc_def = Forecast.from_payloads(LOC, imp, met, now_utc=NY_NOW)
    assert "sunscreen" in fc_low.hint
    assert "sunscreen" not in fc_def.hint


# --- UV placeholder presence + lockstep ---------------------------------------


def test_placeholders_carries_uv_tokens(load_fixture):
    fc = _build(load_fixture, imp="onecall_imperial_uvcross.json",
                met="onecall_imperial_uvcross.json", now_utc=UVCROSS_NOW)
    ph = fc.placeholders()
    # Lockstep: every UV token is present and str-valued.
    assert UV_TOKENS <= set(ph.keys())
    assert all(isinstance(ph[k], str) for k in UV_TOKENS)


def test_canonical_placeholders_superset_includes_uv(load_fixture):
    # placeholders() must be a SUPERSET of the (now extended) canonical core +
    # the six UV tokens — the renderer's CANONICAL gains them in Task 2.
    raw = load_fixture("onecall_imperial_uvcross.json")
    fc = Forecast.from_payloads(LOC, raw, raw, now_utc=UVCROSS_NOW)
    assert UV_TOKENS <= set(fc.placeholders().keys())


# --- crossing vs stays-below vs missing-hourly rendering ----------------------


def test_uv_crossing_fixture_renders_nonempty_tokens(load_fixture):
    fc = _build(load_fixture, imp="onecall_imperial_uvcross.json",
                met="onecall_imperial_uvcross.json", now_utc=UVCROSS_NOW)
    ph = fc.placeholders()
    # current.uvi 7.0 → "7"; daily[0].uvi 9.6 → "10"; category of 9.6 → "Very High".
    assert "7" in ph["uv_now"]
    assert "10" in ph["uv_max"]
    assert ph["uv_category"] == "Very High"
    # crossing line carries the interpolated local crossing clock (10:20).
    assert ph["uv_cross"] != ""
    assert "10:20" in ph["uv_cross"]
    # protect window range present (10:20–3:20 PM crossing/down-cross).
    assert ph["uv_window"] != ""
    assert "10:20" in ph["uv_window"]
    # peak clock from hourly argmax (1:00 PM); never None.
    assert ph["uv_peak"] != ""


def test_uv_peak_value_matches_hourly_argmax_not_day_max(load_fixture):
    # WR-02: the briefing peak VALUE must agree with the peak CLOCK (both from the
    # hourly argmax) and with the uv command. Construct a payload where the day-max
    # (daily[0].uvi) EXCEEDS the hourly argmax, then assert the briefing prints the
    # hourly-argmax value, not the day-max, so value and clock never disagree.
    from weatherbot.weather.uv import compute_uv

    imp = load_fixture("onecall_imperial_uvcross.json")
    # daily[0].uvi inflated well above the hourly buckets (argmax stays 9.6 @ 13:00).
    imp = {**imp, "daily": [{**imp["daily"][0], "uvi": 11.0}, *imp["daily"][1:]]}

    fc = Forecast.from_payloads(LOC, imp, imp, now_utc=UVCROSS_NOW)
    ph = fc.placeholders()
    summary = compute_uv(
        imp, None, 6.0, tz=ZoneInfo("America/New_York"), now=UVCROSS_NOW
    )
    # uv_max shows the inflated day-max (11), but the PEAK line shows the
    # hourly-argmax value (round(9.6) == 10) that the clock actually refers to.
    assert ph["uv_max"] == "11"
    assert ph["uv_peak"] == f"peak {round(summary.peak_uvi)} at 1:00 PM"
    assert "peak 11" not in ph["uv_peak"]


def test_uv_stays_below_renders_clear_line_not_none(load_fixture):
    fc = _build(load_fixture, imp="onecall_imperial_uvbelow.json",
                met="onecall_imperial_uvbelow.json", now_utc=UVCROSS_NOW)
    ph = fc.placeholders()
    # No literal "None" anywhere; the crossing/window collapse per empty-collapse.
    for k in UV_TOKENS:
        assert "None" not in ph[k]
    # A clear "stays below"-style line OR an empty collapse — never a crash/None.
    assert ph["uv_cross"] == "" or "below" in ph["uv_cross"].lower()
    # current/max still render (read verbatim, independent of hourly[]).
    assert ph["uv_now"] != ""
    assert ph["uv_max"] != ""


def test_uv_missing_hourly_degrades_without_raising(load_fixture):
    # T-14-07 briefing-spine isolation: an empty/missing hourly[] must NOT raise;
    # crossing/window/peak collapse, current/max still render.
    imp = load_fixture("onecall_imperial_uvcross.json")
    imp.pop("hourly", None)
    fc = Forecast.from_payloads(LOC, imp, imp, now_utc=UVCROSS_NOW)
    ph = fc.placeholders()
    assert UV_TOKENS <= set(ph.keys())
    for k in UV_TOKENS:
        assert "None" not in ph[k]
    assert ph["uv_now"] != ""
    assert ph["uv_max"] != ""


def test_uv_malformed_hourly_does_not_crash_briefing(load_fixture):
    # CR-01: a PRESENT-but-non-numeric hourly[] (provider schema drift — "NA"
    # uvi, non-int dt) must NOT abort the Forecast build. The briefing spine must
    # still render current/max; the crossing/window/peak collapse to "".
    imp = load_fixture("onecall_imperial_uvcross.json")
    imp["hourly"] = [
        {"dt": "not-an-epoch", "uvi": "NA"},
        {"dt": None, "uvi": [1, 2]},
        {"dt": {"x": 1}, "uvi": 9.9},
    ]
    # The assertion that matters: from_payloads does NOT raise.
    fc = Forecast.from_payloads(LOC, imp, imp, now_utc=UVCROSS_NOW)
    ph = fc.placeholders()
    for k in UV_TOKENS:
        assert "None" not in ph[k]
    # current/max are read verbatim (independent of hourly[]) and still render.
    assert ph["uv_now"] != ""
    assert ph["uv_max"] != ""
    # The rest of the briefing renders normally (UV failure is isolated).
    assert ph["temp"] != ""
    assert ph["high"] != ""
