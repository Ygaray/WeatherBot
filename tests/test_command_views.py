"""Unit tests for the read-only weather-view + info command handlers (Plan 12-02).

Covers CMD-10 (alerts), CMD-13 (sun), CMD-14 (wind), CMD-15 (next-cloudy) and
CMD-09-render/CMD-11 (help/locations). Every handler reads ONLY the already-fetched
One Call payload retained on ``Forecast`` (no second fetch) and writes NOTHING to
the store (D-06 / SC#5 — proven by the zero-store-writes spy).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.interactive.commands import CommandReply
from weatherbot.interactive.commands import info, status as status_cmd, weather_views
from weatherbot.interactive.lookup import LookupResult
from weatherbot.weather.models import Forecast

# The seven store write functions a read-only handler must never touch (D-06).
_STORE_WRITES = (
    "persist",
    "claim_slot",
    "record_alert",
    "resolve_alert",
    "stamp_tick",
    "stamp_success",
    "stamp_health",
)


def _ny_location() -> Location:
    return Location(
        name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York"
    )


def _result_from(
    load_fixture, imp_name: str, met_name: str | None = None
) -> LookupResult:
    """Build a LookupResult from a fixture (metric defaults to the clear fixture)."""
    loc = _ny_location()
    onecall_imp = load_fixture(imp_name)
    onecall_met = load_fixture(met_name or "onecall_metric_clear.json")
    forecast = Forecast.from_payloads(loc, onecall_imp, onecall_met)
    return LookupResult(text="", forecast=forecast, location=loc)


# --------------------------------------------------------------------------- #
# weather (W2 / D-07/D-08 — byte-identical to build_inbound_embed)
# --------------------------------------------------------------------------- #


def test_weather_reply_is_byte_identical_to_build_inbound_embed(load_fixture):
    """The new `weather` handler reproduces build_inbound_embed field-for-field.

    W2 (D-07/D-08): the panel weather button now routes through the dispatch ladder
    → render_embed, so the `!weather` reply MUST stay byte-identical to the legacy
    build_inbound_embed (Now / High·Low / Rain), using ``forecast.location`` (the
    str) — NOT ``result.location.name`` like sibling handlers.
    """
    from weatherbot.interactive.bot import build_inbound_embed

    result = _result_from(load_fixture, "onecall_imperial_clouds_clear.json")
    f = result.forecast
    reply = weather_views.weather(result)
    embed = build_inbound_embed(f)

    assert isinstance(reply, CommandReply)
    # Title matches the embed title (uses forecast.location, the str).
    assert reply.title == embed.title == f"Weather — {f.location}"
    # Field name/value pairs match the embed's three fields in order.
    assert reply.lines == (
        ("Now", f.temp_display),
        ("High / Low", f"{f.high_display} / {f.low_display}"),
        ("Rain", f"{f.rain_chance}%"),
    )
    assert [(fld.name, fld.value) for fld in embed.fields] == list(reply.lines)


# --------------------------------------------------------------------------- #
# alerts (CMD-10)
# --------------------------------------------------------------------------- #


def test_alerts_present_surfaces_event(load_fixture):
    result = _result_from(load_fixture, "onecall_imperial_alert.json")
    reply = weather_views.alerts(result)
    assert isinstance(reply, CommandReply)
    body = reply.text or "\n".join(v for _, v in reply.lines)
    assert "Heat Advisory" in body


def test_alerts_clear_reports_no_active_alerts(load_fixture):
    # The clear clouds fixture has no alerts[] key at all (defensive `or []`).
    result = _result_from(load_fixture, "onecall_imperial_clouds_clear.json")
    reply = weather_views.alerts(result)
    body = (reply.text or "") + "".join(v for _, v in reply.lines)
    assert "no active" in body.lower()


# --------------------------------------------------------------------------- #
# sun (CMD-13)
# --------------------------------------------------------------------------- #


def test_sun_reports_local_wallclock(load_fixture):
    # sunrise 1718354400 = 04:40 EDT, sunset 1718408400 = 19:40 EDT.
    result = _result_from(load_fixture, "onecall_imperial_alert.json")
    reply = weather_views.sun(result)
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    assert "04:40" in body
    assert "19:40" in body


# --------------------------------------------------------------------------- #
# wind (CMD-14) + compass helper
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "deg,label",
    [(0, "N"), (90, "E"), (180, "S"), (270, "W"), (45, "NE"), (360, "N")],
)
def test_compass_cardinals(deg, label):
    assert weather_views.compass(deg) == label


def test_wind_reports_speed_and_compass(load_fixture):
    # alert fixture current.wind_deg=200 -> SSW; wind_speed 10 mph.
    result = _result_from(load_fixture, "onecall_imperial_alert.json")
    reply = weather_views.wind(result)
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    assert "mph" in body
    assert "SSW" in body


# --------------------------------------------------------------------------- #
# next-cloudy (CMD-15)
# --------------------------------------------------------------------------- #


def test_next_cloudy_hourly_hit(load_fixture):
    # hourly bucket at index 4 (12:00 EDT, daytime) has clouds=80 >= 60.
    result = _result_from(load_fixture, "onecall_imperial_cloudy_hourly.json")
    reply = weather_views.next_cloudy(result, threshold=60)
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    # Reports a same-day cloudy time around midday local.
    assert "12:" in body or "12:00" in body


def test_next_cloudy_daily_fallback(load_fixture):
    # hourly all clear; daily index 3 has clouds=85 >= 60 (days 3-8 slice).
    result = _result_from(load_fixture, "onecall_imperial_cloudy_daily.json")
    reply = weather_views.next_cloudy(result, threshold=60)
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    assert body  # a cloudy day was found and reported
    assert "no cloudy" not in body.lower()


def test_next_cloudy_none_in_range(load_fixture):
    result = _result_from(load_fixture, "onecall_imperial_clouds_clear.json")
    reply = weather_views.next_cloudy(result, threshold=60)
    body = (reply.text or "") + "".join(v for _, v in reply.lines)
    assert "no cloudy" in body.lower()


# --------------------------------------------------------------------------- #
# uv (UV-01) — full summary + compact daytime hourly line (D-04)
# --------------------------------------------------------------------------- #

# Pinned "now": noon local on the UV fixtures' anchor day (2024-06-14 NY), so the
# anchored hourly[] buckets resolve as "today" deterministically (mirrors test_uv.py).
_UV_NOW = datetime(2024, 6, 14, 12, 0, tzinfo=ZoneInfo("America/New_York"))


def test_uv_crossing_reports_summary_and_hourly_line(load_fixture):
    # uvcross fixture: current 4.x, max 9.6 (Very High), peak 13:00, crosses 6 up at
    # ~10:20 and back down ~15:20. Threshold 6 => a crossing + protect window.
    result = _result_from(load_fixture, "onecall_imperial_uvcross.json")
    reply = weather_views.uv(result, 6.0, now=_UV_NOW)
    assert isinstance(reply, CommandReply)
    body = (reply.text or "") + "\n".join(f"{n}: {v}" for n, v in reply.lines)
    # WHO category for the day's max (9.6 -> Very High).
    assert "Very High" in body
    # The interpolated crossing clock (10:20) appears somewhere in the reply.
    assert "10:20" in body
    # A compact daytime hourly UV line (HH:UV pairs) is present — the midday peak
    # bucket (13:00 -> 10) and a representative morning bucket both show up.
    assert "13:10" in body
    assert "12:8" in body
    # Does not claim it stays below threshold (a crossing was found).
    assert "stays below" not in body.lower()


def test_uv_now_line_uses_current_value_band_not_day_max(load_fixture):
    # WR-01: the "Now" line must be labeled with the band of the CURRENT value,
    # not the day-max band. uvcross fixture: current.uvi 7.0 (High) vs day-max
    # 9.6 (Very High). The Now line must read "High", the max line "Very High".
    result = _result_from(load_fixture, "onecall_imperial_uvcross.json")
    reply = weather_views.uv(result, 6.0, now=_UV_NOW)
    by_label = {n: v for n, v in reply.lines}
    assert by_label["Now"] == "7 (High)"
    assert by_label["Today's max"] == "10 (Very High)"


def test_uv_stays_below_reports_no_crossing_but_keeps_hourly_line(load_fixture):
    # uvbelow fixture: UV never reaches 6 -> "stays below threshold today", still
    # lists current/max/category + the compact hourly line.
    result = _result_from(load_fixture, "onecall_imperial_uvbelow.json")
    reply = weather_views.uv(result, 6.0, now=_UV_NOW)
    body = (reply.text or "") + "\n".join(f"{n}: {v}" for n, v in reply.lines)
    assert "stays below" in body.lower()
    # Current/max still reported (read verbatim from current.uvi / daily[0].uvi).
    assert "4" in body  # current 4.2 / max 4.5 round into the reply
    # The compact daytime hourly line is still present even with no crossing.
    assert ":" in body  # at least one HH:UV pair rendered


def test_uv_threshold_is_threaded(load_fixture):
    # A LOWER threshold (4) crosses EARLIER than the default 6 on the same fixture —
    # proving the handler uses the passed threshold, not a hardcoded 6.
    result = _result_from(load_fixture, "onecall_imperial_uvcross.json")
    reply_low = weather_views.uv(result, 4.0, now=_UV_NOW)
    reply_high = weather_views.uv(result, 6.0, now=_UV_NOW)
    body_low = (reply_low.text or "") + "\n".join(
        f"{n}: {v}" for n, v in reply_low.lines
    )
    body_high = (reply_high.text or "") + "\n".join(
        f"{n}: {v}" for n, v in reply_high.lines
    )
    # Both find a crossing, but the clocks differ (lower threshold crosses earlier).
    assert body_low != body_high


def test_uv_handler_reads_only_retained_payload(load_fixture, monkeypatch):
    # The handler must NOT trigger a second fetch: it reads result.forecast.raw_onecall_imp.
    # Guard the lookup core so any re-fetch attempt would explode.
    import weatherbot.interactive.lookup as lookup

    def _boom(*args, **kwargs):  # pragma: no cover - only fires on a violation
        raise AssertionError("uv handler triggered a second fetch")

    monkeypatch.setattr(lookup, "lookup_weather", _boom, raising=False)
    result = _result_from(load_fixture, "onecall_imperial_uvcross.json")
    reply = weather_views.uv(result, 6.0, now=_UV_NOW)
    assert isinstance(reply, CommandReply)


# --------------------------------------------------------------------------- #
# Zero-store-writes spy (SC#5 / D-06)
# --------------------------------------------------------------------------- #


def test_handlers_never_touch_the_store(monkeypatch, load_fixture):
    import weatherbot.weather.store as store

    def _boom(*args, **kwargs):
        raise AssertionError("a read-only handler touched the store")

    for fn in _STORE_WRITES:
        monkeypatch.setattr(store, fn, _boom)

    result = _result_from(load_fixture, "onecall_imperial_cloudy_hourly.json")
    cfg = Config(
        locations=[_ny_location()],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )

    # Every handler must complete without tripping a store-write spy.
    weather_views.alerts(result)
    weather_views.sun(result)
    weather_views.wind(result)
    weather_views.next_cloudy(result, threshold=60)
    weather_views.uv(result, 6.0, now=_UV_NOW)
    info.help_cmd()
    info.locations(cfg)


# --------------------------------------------------------------------------- #
# info: help (CMD-09 render) + locations (CMD-11)
# --------------------------------------------------------------------------- #


def test_help_cmd_includes_every_command_summary():
    from weatherbot.interactive import registry

    reply = info.help_cmd()
    body = reply.text or ""
    for spec in registry.COMMANDS:
        assert spec.summary in body


def test_locations_lists_all_configured_names():
    cfg = Config(
        locations=[
            Location(name="Home", lat=40.0, lon=-74.0, timezone="America/New_York"),
            Location(name="Travel", lat=52.52, lon=13.405, timezone="Europe/Berlin"),
        ],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )
    reply = info.locations(cfg)
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    assert "Home" in body
    assert "Travel" in body


def test_locations_does_not_fetch_or_store(monkeypatch):
    # locations must read config only — no ForecastCache, no network, no store.
    import weatherbot.weather.store as store

    def _boom(*args, **kwargs):
        raise AssertionError("locations touched the store")

    for fn in _STORE_WRITES:
        monkeypatch.setattr(store, fn, _boom)

    cfg = Config(
        locations=[Location(name="Home", lat=40.0, lon=-74.0, timezone="UTC")],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )
    reply = info.locations(cfg)
    assert isinstance(reply, CommandReply)


# --------------------------------------------------------------------------- #
# D-07 — humanized timestamps: local 24-hour HH:MM (no raw ISO / "... UTC")
# --------------------------------------------------------------------------- #

_HHMM = re.compile(r"^\d{2}:\d{2}$")


def test_humanized_timestamp():
    """status._fmt_epoch renders local 24h ``09:00``, not raw ISO / ``... UTC``.

    D-07: the template/CLI text path drops the raw ISO / ``%Y-%m-%d %H:%M UTC``
    form for a bare, already-localized 24-hour ``HH:MM`` clock. ``None`` stays
    the friendly ``none yet`` sentinel.
    """
    assert status_cmd._fmt_epoch(None) == "none yet"
    # 2026-06-20 09:00:00 UTC.
    epoch = int(datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc).timestamp())
    out = status_cmd._fmt_epoch(epoch)
    assert _HHMM.match(out), f"expected HH:MM, got {out!r}"
    assert "UTC" not in out, f"raw UTC suffix leaked: {out!r}"
    assert "2026" not in out, f"raw ISO date leaked: {out!r}"
    assert out == "09:00"
