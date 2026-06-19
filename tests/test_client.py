"""Offline tests for the httpx OpenWeather client (FCST-01, LOC-03).

No network is touched: every request is served by an ``httpx.MockTransport``
monkeypatched onto ``httpx.Client``. We assert the correct endpoint paths and
params for One Call 3.0 (``/data/3.0/onecall``) and Geocoding
(``/geo/1.0/direct``), that a non-2xx surfaces via ``raise_for_status`` (auth /
subscription failures are NOT retried in this phase, Pitfall 1), and that the
secret ``appid`` never appears in a log line (Pitfall 6).
"""

from __future__ import annotations

import logging

import httpx
import pytest

from weatherbot.config.models import Location
from weatherbot.weather import client as client_mod

LOC = Location(name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York")
KEY = "secret-api-key-123"


def _install_mock(monkeypatch, handler, capture: dict | None = None):
    """Patch httpx.Client so every request is served by ``handler`` (offline)."""
    real_init = httpx.Client.__init__

    def fake_init(self, *args, **kwargs):
        if capture is not None:
            capture["init_kwargs"] = kwargs
        kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", fake_init)


def test_fetch_onecall_builds_request(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"timezone": "America/New_York", "current": {}})

    _install_mock(monkeypatch, handler)
    data = client_mod.fetch_onecall(LOC, KEY, units="imperial")

    assert seen["path"] == "/data/3.0/onecall"
    assert seen["params"]["lat"] == "40.7128"
    assert seen["params"]["lon"] == "-74.006"
    assert seen["params"]["appid"] == KEY
    assert seen["params"]["units"] == "imperial"
    assert seen["params"]["lang"] == "en"
    # Drops only minutely; KEEPS hourly (next-cloudy + Phases 14/15, D-06).
    assert seen["params"]["exclude"] == "minutely"
    assert data["timezone"] == "America/New_York"


def test_fetch_onecall_keeps_hourly_regression_canary(monkeypatch):
    # Regression canary (D-06): the One Call exclude must drop ONLY minutely and
    # KEEP hourly. If a future bandwidth trim re-adds hourly to exclude, this fails
    # — protecting next-cloudy (Phase 12) and the UV features (Phases 14/15).
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={"current": {}, "hourly": [{"dt": 1, "clouds": 80}], "daily": [{}]},
        )

    _install_mock(monkeypatch, handler)
    data = client_mod.fetch_onecall(LOC, KEY)

    # The client must NOT ask the API to exclude hourly.
    assert "hourly" not in seen["params"]["exclude"].split(",")
    assert seen["params"]["exclude"] == "minutely"
    # The parsed payload retains a non-empty hourly[] block.
    assert data["hourly"]
    assert len(data["hourly"]) >= 1


def test_fetch_onecall_metric_units(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"current": {"temp": 20.0}})

    _install_mock(monkeypatch, handler)
    data = client_mod.fetch_onecall(LOC, KEY, units="metric")

    assert seen["path"] == "/data/3.0/onecall"
    assert seen["params"]["units"] == "metric"
    assert seen["params"]["appid"] == KEY
    assert data["current"]["temp"] == 20.0


def test_geocode_builds_request(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json=[{"name": "Austin", "lat": 30.2672, "lon": -97.7431, "country": "US"}],
        )

    _install_mock(monkeypatch, handler)
    matches = client_mod.geocode("Austin, TX", KEY, limit=5)

    assert seen["path"] == "/geo/1.0/direct"
    assert seen["params"]["q"] == "Austin, TX"
    assert seen["params"]["limit"] == "5"
    assert seen["params"]["appid"] == KEY
    assert isinstance(matches, list)
    assert matches[0]["name"] == "Austin"


def test_explicit_timeout_set(monkeypatch):
    cap = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _install_mock(monkeypatch, handler, capture=cap)
    client_mod.fetch_onecall(LOC, KEY)
    # The client must be constructed with an explicit (non-None) timeout so the
    # process never hangs forever on a slow OpenWeather response (T-02-04).
    assert cap["init_kwargs"].get("timeout") is not None


def test_401_raises_not_retried(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"cod": 401, "message": "Invalid API key"})

    _install_mock(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        client_mod.fetch_onecall(LOC, KEY)
    # Surfaced immediately, not retried in this phase (Pitfall 1).
    assert calls["n"] == 1


def test_appid_not_logged(monkeypatch, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _install_mock(monkeypatch, handler)
    with caplog.at_level(logging.DEBUG):
        client_mod.fetch_onecall(LOC, KEY)
        client_mod.geocode("Austin", KEY)
    # The secret must never leak into any log record (Pitfall 6 / T-02-01) — for
    # the One Call fetch AND the geocode call.
    for record in caplog.records:
        assert KEY not in record.getMessage()
