"""End-to-end happy-path test for --send-now (CONF-04).

This is the anchor for the whole phase: it exercises the full
fetch -> persist -> render -> deliver composition via ``weatherbot.cli.send_now``.
Plan 04 wires that composition, so the test (which was a strict xfail through
Plans 01-03) now PASSES with the marker removed.

Everything is mocked — no network, no real Discord webhook. A fake client returns
the recorded fixtures, a fake channel captures the rendered text + the Forecast it
received, and the test asserts the load-bearing DATA-03 contract: a SINGLE fetch
round feeds BOTH the SQLite persist AND the renderer (no second fetch exists just
to persist).
"""

from __future__ import annotations

import sqlite3

from weatherbot.cli import send_now
from weatherbot.config import Config, Location, WebhookIdentity


class _FakeClient:
    """Returns recorded fixtures and counts fetch calls (DATA-03 assertion)."""

    def __init__(self, current_imp, current_met, forecast_imp, forecast_met):
        self._current = {"imperial": current_imp, "metric": current_met}
        self._forecast = {"imperial": forecast_imp, "metric": forecast_met}
        self.current_calls: list[str] = []
        self.forecast_calls: list[str] = []

    def fetch_current(self, location, units):
        self.current_calls.append(units)
        return self._current[units]

    def fetch_forecast(self, location, units):
        self.forecast_calls.append(units)
        return self._forecast[units]


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
    current = load_fixture("current_imperial_clear.json")
    current_metric = load_fixture("current_metric_clear.json")
    forecast = load_fixture("forecast_imperial_clear.json")
    forecast_metric = load_fixture("forecast_metric_clear.json")

    client = _FakeClient(current, current_metric, forecast, forecast_metric)
    channel = _FakeChannel()

    config = Config(
        locations=[Location(name="New York", lat=40.7128, lon=-74.006)],
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

    # --- persistence: rows written to BOTH tables ----------------------------
    con = sqlite3.connect(tmp_db)
    try:
        n_current = con.execute("SELECT COUNT(*) FROM weather_current").fetchone()[0]
        n_forecast = con.execute("SELECT COUNT(*) FROM weather_forecast").fetchone()[0]
    finally:
        con.close()
    assert n_current >= 1
    assert n_forecast >= 1

    # --- DATA-03: exactly ONE fetch round fed both persist AND render ---------
    # current+forecast each fetched once per units variant (imperial+metric) =
    # 2 current + 2 forecast calls total; no extra fetch happened to persist.
    assert client.current_calls == ["imperial", "metric"]
    assert client.forecast_calls == ["imperial", "metric"]

    # The SAME Forecast object that was rendered/delivered is the one persisted:
    # send_briefing received a Forecast whose location matches the rendered body.
    assert channel.briefing_forecasts
    delivered_forecast = channel.briefing_forecasts[0]
    assert delivered_forecast.location == "New York"
