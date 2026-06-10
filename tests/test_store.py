"""Tests for the analysis-ready SQLite store (DATA-01/02/03).

The store writes one ``weather_onecall`` row per units variant (imperial +
metric), reusing the Forecast's two retained One Call payloads from the SAME fetch
(DATA-03 — no network call inside ``persist``). The schema exposes queryable
GENERATED columns (DATA-02) and each row carries ``target_local_date`` (computed
from the configured IANA tz, D-03) — the per-location analysis axis the deferred
v2 forecast-vs-actual analysis needs with no migration. The old 2.5
``weather_current`` / ``weather_forecast`` tables remain DEFINED (history) but are
no longer written.
"""

from __future__ import annotations

import json
import sqlite3

from weatherbot.config.models import Location
from weatherbot.weather.models import Forecast
from weatherbot.weather.store import init_db, persist

LOC = Location(name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York")


def _build(load_fixture) -> Forecast:
    """Build a Forecast from the recorded New York One Call fixtures."""
    return Forecast.from_payloads(
        LOC,
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_init_db_creates_onecall_table_and_indexes(tmp_db):
    init_db(tmp_db)
    with _connect(tmp_db) as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
    # New One Call table plus the retained 2.5 history tables.
    assert {"weather_onecall", "weather_current", "weather_forecast"} <= tables
    assert {"ix_onecall_loc_time", "ix_onecall_loc_date"} <= indexes


def test_init_db_is_idempotent(tmp_db):
    init_db(tmp_db)
    # Re-running must not raise (CREATE ... IF NOT EXISTS).
    init_db(tmp_db)


def test_persist_onecall_writes_both_unit_rows(load_fixture, tmp_db):
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        rows = list(conn.execute("SELECT * FROM weather_onecall"))

    # One row per units variant (imperial + metric).
    assert len(rows) == 2
    assert {r["units"] for r in rows} == {"imperial", "metric"}
    assert all(r["location_name"] == "New York" for r in rows)


def test_persist_onecall_generated_columns_populate(load_fixture, tmp_db):
    """DATA-02: the json_extract generated columns populate from the raw payload."""
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT temp, feels_like, humidity, wind_speed, uvi, "
            "day_high, day_low, pop, day_uvi, target_local_date "
            "FROM weather_onecall WHERE units='imperial'"
        ).fetchone()

    # current.* generated columns
    assert row["temp"] == 68.0
    assert row["feels_like"] == 66.2
    assert row["humidity"] == 52
    assert row["wind_speed"] == 8.05
    assert row["uvi"] == 3.1
    # daily[0].* generated columns
    assert row["day_high"] == 76.0
    assert row["day_low"] == 58.0
    assert row["pop"] == 0.1
    assert row["day_uvi"] == 5.2
    # target_local_date is a non-empty YYYY-MM-DD from the configured tz.
    assert row["target_local_date"]


def test_persist_onecall_makes_no_network_call(load_fixture, tmp_db):
    """DATA-03: persist reuses retained payloads — never fetches (no httpx use)."""
    import weatherbot.weather.store as store_mod

    # If persist tried any network, importing/using httpx would be the only path;
    # assert the module does not reference httpx at all.
    assert not hasattr(store_mod, "httpx")

    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)  # must complete with no network access


def test_persist_onecall_generated_columns_match_raw_json(load_fixture, tmp_db):
    """Generated columns always agree with the stored raw_json (no drift)."""
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT raw_json, temp, pop FROM weather_onecall "
            "WHERE units='imperial' LIMIT 1"
        ).fetchone()

    raw = json.loads(row["raw_json"])  # round-trips as valid JSON
    assert row["temp"] == raw["current"]["temp"]
    assert row["pop"] == raw["daily"][0]["pop"]


def test_no_secret_in_stored_json(load_fixture, tmp_db):
    """T-02-03: no stored raw_json carries the OpenWeather appid or a request URL."""
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        blobs = [
            r[0] for r in conn.execute("SELECT raw_json FROM weather_onecall")
        ]

    for blob in blobs:
        assert "appid" not in blob
        assert "api.openweathermap.org" not in blob
