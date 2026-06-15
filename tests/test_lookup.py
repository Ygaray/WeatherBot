"""Unit tests for the read-only lookup core (Phase 06-02).

``lookup_weather`` is the shared fetch->render core that two future surfaces
delegate to (P7 CLI prints ``.text``; P11 Discord builds an embed from
``.forecast``). It MUST be read-only: it resolves a configured location, fetches
imperial+metric via the injected One Call client, builds one ``Forecast``,
renders the exact v1 template, and returns a ``LookupResult`` — writing NOTHING
to the SQLite store (D-06). An unknown name raises ``UnknownLocationError``,
which IS-A ``ValueError`` and carries ``.requested`` + ``.valid_names`` (D-07).

This suite pins the keyword signature:
    lookup_weather(name, *, config, settings=None, client=None,
                   templates_dir=None, extra_placeholders=None)
"""

from __future__ import annotations

import sqlite3

import pytest

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.interactive.lookup import (
    LookupResult,
    UnknownLocationError,
    lookup_weather,
)

# The seven store write functions a read-only lookup must never touch (D-06).
_STORE_WRITES = (
    "persist",
    "claim_slot",
    "record_alert",
    "resolve_alert",
    "stamp_tick",
    "stamp_success",
    "stamp_health",
)


class _FakeClient:
    """Returns recorded One Call fixtures and counts fetch calls (DATA-03).

    Copied verbatim from tests/test_send_now.py — records ``onecall_calls`` so
    the dual-fetch order (imperial first) can be asserted. No channel fake: a
    lookup never delivers.
    """

    def __init__(self, onecall_imp, onecall_met):
        self._onecall = {"imperial": onecall_imp, "metric": onecall_met}
        self.onecall_calls: list[str] = []

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._onecall[units]


def _ny_config() -> Config:
    """New York config mirroring test_send_now.py's happy-path config."""
    return Config(
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


def _berlin_metric_config() -> Config:
    """Berlin units='metric' config mirroring test_send_now.py (metric-primary)."""
    return Config(
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


def test_lookup_imperial_happy_path(load_fixture):
    # Criterion #1 (imperial): resolve -> dual-fetch -> render -> LookupResult.
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    cfg = _ny_config()

    result = lookup_weather("New York", config=cfg, client=client)

    assert isinstance(result, LookupResult)
    # Rendered briefing carries the location and an imperial-primary value.
    assert "New York" in result.text
    assert "°F" in result.text
    # Structured forecast + resolved location are exposed for the embed surface.
    assert result.forecast.location == "New York"
    assert result.location.name == "New York"
    # DATA-03 dual-fetch contract: imperial first, then metric.
    assert client.onecall_calls == ["imperial", "metric"]


def test_lookup_metric_primary(load_fixture):
    # Criterion #1 (metric-primary): a units="metric" location leads with °C.
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    cfg = _berlin_metric_config()

    result = lookup_weather("Berlin", config=cfg, client=client)

    assert result.forecast.temp_display == "20°C (68°F)"
    assert "°C" in result.text


def test_lookup_writes_nothing_to_store(monkeypatch, tmp_db, load_fixture):
    # Criterion #2 (zero store writes): monkeypatch all 7 store write functions
    # to raise; lookup_weather must complete without tripping any of them.
    import weatherbot.weather.store as store

    def _boom(*args, **kwargs):
        raise AssertionError("lookup_weather touched the store")

    for fn in _STORE_WRITES:
        monkeypatch.setattr(store, fn, _boom)

    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    cfg = _ny_config()

    # Completes without raising — no store write function was called.
    result = lookup_weather("New York", config=cfg, client=client)
    assert isinstance(result, LookupResult)

    # Belt-and-suspenders: nothing was written to a real (fresh) database. The
    # store creates the schema on first connect; a lookup never connects, so the
    # file does not even exist. If it somehow did, the row counts must be 0.
    if tmp_db.exists():
        con = sqlite3.connect(tmp_db)
        try:
            for table in ("weather_onecall", "sent_log", "alerts"):
                n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert n == 0, f"{table} had {n} rows after a read-only lookup"
        finally:
            con.close()


def test_lookup_unknown_location_raises_typed_error(load_fixture):
    # D-07: an unknown name raises UnknownLocationError, an IS-A ValueError that
    # carries the requested name + the configured display names.
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    cfg = _ny_config()

    with pytest.raises(UnknownLocationError) as exc_info:
        lookup_weather("Nowhere", config=cfg, client=client)

    err = exc_info.value
    assert isinstance(err, ValueError)
    assert err.requested == "Nowhere"
    assert err.valid_names == ["New York"]


def test_lookup_unknown_location_caught_by_value_error(load_fixture):
    # D-07 / Pitfall 5: an `except ValueError` block still catches the typed error
    # so every existing v1.0 caller stays green.
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    cfg = _ny_config()

    caught = False
    try:
        lookup_weather("Nowhere", config=cfg, client=client)
    except ValueError:
        caught = True
    assert caught
