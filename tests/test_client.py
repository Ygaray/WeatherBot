"""Offline tests for the httpx OpenWeather client (FCST-01).

No network is touched: every request is served by an ``httpx.MockTransport``
monkeypatched onto ``httpx.Client``. We assert the correct endpoint paths and
params (lat/lon/appid/units/lang), that a non-2xx surfaces via
``raise_for_status`` (auth failures are NOT retried in Phase 1, Pitfall 7), and
that the secret ``appid`` never appears in a log line (Pitfall 5).
"""

from __future__ import annotations

import logging

import httpx
import pytest

from weatherbot.config.models import Location
from weatherbot.weather import client as client_mod

LOC = Location(name="New York", lat=40.7128, lon=-74.006)
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


def test_fetch_current_builds_request(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"name": "New York", "main": {"temp": 72}})

    _install_mock(monkeypatch, handler)
    data = client_mod.fetch_current(LOC, KEY, units="imperial")

    assert seen["path"] == "/data/2.5/weather"
    assert seen["params"]["lat"] == "40.7128"
    assert seen["params"]["lon"] == "-74.006"
    assert seen["params"]["appid"] == KEY
    assert seen["params"]["units"] == "imperial"
    assert seen["params"]["lang"] == "en"
    assert data["name"] == "New York"


def test_fetch_forecast_builds_request(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"city": {"name": "New York"}, "list": []})

    _install_mock(monkeypatch, handler)
    data = client_mod.fetch_forecast(LOC, KEY, units="metric")

    assert seen["path"] == "/data/2.5/forecast"
    assert seen["params"]["units"] == "metric"
    assert seen["params"]["appid"] == KEY
    assert data["city"]["name"] == "New York"


def test_explicit_timeout_set(monkeypatch):
    cap = {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _install_mock(monkeypatch, handler, capture=cap)
    client_mod.fetch_current(LOC, KEY)
    # The client must be constructed with an explicit (non-None) timeout so the
    # process never hangs forever on a slow OpenWeather response (T-02-03).
    assert cap["init_kwargs"].get("timeout") is not None


def test_401_raises_not_retried(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"cod": 401, "message": "Invalid API key"})

    _install_mock(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        client_mod.fetch_current(LOC, KEY)
    # Surfaced immediately, not retried in Phase 1 (Pitfall 7).
    assert calls["n"] == 1


def test_appid_not_logged(monkeypatch, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    _install_mock(monkeypatch, handler)
    with caplog.at_level(logging.DEBUG):
        client_mod.fetch_current(LOC, KEY)
    # The secret must never leak into any log record (Pitfall 5 / T-02-01).
    for record in caplog.records:
        assert KEY not in record.getMessage()
