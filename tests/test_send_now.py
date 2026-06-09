"""End-to-end happy-path test for --send-now (CONF-04).

This is the RED anchor for the whole phase: it exercises the full
fetch -> persist -> render -> dispatch composition via ``weatherbot.cli.send_now``,
which does NOT exist yet (it is wired in Plan 04). The test is therefore a
DECLARED xfail (strict) — it must fail until the pipeline lands, then later
plans drive it green. Marked strict so an accidental early pass is flagged.

The composition import lives INSIDE the test body so collection succeeds (the
module is absent today); when Plan 04 adds ``weatherbot.cli.send_now`` and the
store/channel/renderer, this test flips to xpass and the marker is removed.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest


@pytest.mark.xfail(reason="pipeline wired in Plan 04", strict=True)
def test_send_now_posts_briefing(tmp_db, load_fixture, monkeypatch):
    # Imported here (not at module top) so collection works before Plan 04.
    from weatherbot.cli import send_now  # noqa: F401  (absent until Plan 04)
    from weatherbot.config import Config, Location, WebhookIdentity

    current = load_fixture("current_imperial_clear.json")
    current_metric = load_fixture("current_metric_clear.json")
    forecast = load_fixture("forecast_imperial_clear.json")
    forecast_metric = load_fixture("forecast_metric_clear.json")

    # Stub the network: weather client returns the recorded fixtures.
    fake_client = MagicMock()
    fake_client.fetch_current.side_effect = [current, current_metric]
    fake_client.fetch_forecast.side_effect = [forecast, forecast_metric]
    monkeypatch.setattr("weatherbot.cli.build_client", lambda *a, **k: fake_client, raising=False)

    # Capture the channel dispatch (no real Discord call).
    sent: list[str] = []
    fake_channel = MagicMock()
    fake_channel.send.side_effect = lambda text: sent.append(text)
    monkeypatch.setattr("weatherbot.cli.build_channel", lambda *a, **k: fake_channel, raising=False)

    config = Config(
        locations=[Location(name="New York", lat=40.7128, lon=-74.006)],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )

    # Run the composition for the default (first) location.
    send_now(config=config, db_path=tmp_db, location_name=None)

    # It persisted at least one current row and the forecast buckets.
    con = sqlite3.connect(tmp_db)
    try:
        n_current = con.execute("SELECT COUNT(*) FROM weather_current").fetchone()[0]
        n_forecast = con.execute("SELECT COUNT(*) FROM weather_forecast").fetchone()[0]
    finally:
        con.close()
    assert n_current >= 1
    assert n_forecast >= 1

    # And it dispatched the rendered briefing to the channel.
    assert fake_channel.send.called
    assert sent and isinstance(sent[0], str)
