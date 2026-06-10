"""End-to-end happy-path test for --send-now (CONF-04).

This is the anchor for the whole phase: it exercises the full
fetch -> persist -> render -> deliver composition via ``weatherbot.cli.send_now``.

Everything is mocked — no network, no real Discord webhook. A fake client returns
the recorded One Call fixtures, a fake channel captures the rendered text + the
Forecast it received, and the test asserts the load-bearing DATA-03 contract: a
SINGLE fetch round (2 One Call calls, imperial + metric) feeds BOTH the SQLite
persist AND the renderer (no second fetch exists just to persist).
"""

from __future__ import annotations

import sqlite3

from weatherbot.cli import send_now
from weatherbot.config import Config, Location, WebhookIdentity


class _FakeClient:
    """Returns recorded One Call fixtures and counts fetch calls (DATA-03)."""

    def __init__(self, onecall_imp, onecall_met):
        self._onecall = {"imperial": onecall_imp, "metric": onecall_met}
        self.onecall_calls: list[str] = []

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._onecall[units]


class _FakeChannel:
    """Captures the rendered body and the Forecast handed to send_briefing."""

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self.briefing_forecasts: list[object] = []
        self._result = DeliveryResult(ok=True)

    def send_briefing(self, text, forecast):
        self.sent_text.append(text)
        self.briefing_forecasts.append(forecast)
        return self._result


def test_send_now_posts_briefing(tmp_db, load_fixture):
    onecall = load_fixture("onecall_imperial_clear.json")
    onecall_metric = load_fixture("onecall_metric_clear.json")

    client = _FakeClient(onecall, onecall_metric)
    channel = _FakeChannel()

    config = Config(
        locations=[
            Location(
                name="New York",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
            )
        ],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )

    # Run the composition for the default (first) location, injecting the fakes.
    result = send_now(
        None,
        config=config,
        db_path=tmp_db,
        client=client,
        channel=channel,
    )

    # --- delivery: the rendered plain-text body reached the channel ----------
    assert result.ok is True
    assert channel.sent_text and isinstance(channel.sent_text[0], str)
    body = channel.sent_text[0]
    # The canonical briefing renders the location + an imperial-primary value.
    assert "New York" in body
    assert "°F" in body

    # --- persistence: rows written to the One Call table ---------------------
    con = sqlite3.connect(tmp_db)
    try:
        n_onecall = con.execute("SELECT COUNT(*) FROM weather_onecall").fetchone()[0]
    finally:
        con.close()
    assert n_onecall == 2  # one row per units variant

    # --- DATA-03: exactly ONE fetch round (2 One Call calls) fed both ---------
    # persist AND render; no extra fetch happened to persist.
    assert client.onecall_calls == ["imperial", "metric"]

    # The SAME Forecast object that was rendered/delivered is the one persisted:
    # send_briefing received a Forecast whose location matches the rendered body.
    assert channel.briefing_forecasts
    delivered_forecast = channel.briefing_forecasts[0]
    assert delivered_forecast.location == "New York"


def test_send_now_metric_location_renders_metric_primary(tmp_db, load_fixture):
    # CR-01: a location with units="metric" must deliver a metric-primary body
    # (°C leads). The suite would FAIL if the per-location override regressed to
    # inert (the bug this gap plan closes).
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()

    config = Config(
        locations=[
            Location(
                name="Berlin",
                lat=52.52,
                lon=13.405,
                timezone="Europe/Berlin",
                units="metric",
            )
        ],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )

    result = send_now(
        None,
        config=config,
        db_path=tmp_db,
        client=client,
        channel=channel,
    )

    assert result.ok is True
    body = channel.sent_text[0]
    # Metric-primary: °C leads the temperature, with °F in parens.
    assert "°C" in body
    fc = channel.briefing_forecasts[0]
    assert fc.temp_display == "20°C (68°F)"
    # The dual fetch is preserved — the override only flips display primary.
    assert client.onecall_calls == ["imperial", "metric"]
