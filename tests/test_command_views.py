"""Unit tests for the read-only weather-view + info command handlers (Plan 12-02).

Covers CMD-10 (alerts), CMD-13 (sun), CMD-14 (wind), CMD-15 (next-cloudy) and
CMD-09-render/CMD-11 (help/locations). Every handler reads ONLY the already-fetched
One Call payload retained on ``Forecast`` (no second fetch) and writes NOTHING to
the store (D-06 / SC#5 — proven by the zero-store-writes spy).
"""

from __future__ import annotations

import pytest

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.interactive.commands import CommandReply
from weatherbot.interactive.commands import info, weather_views
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
