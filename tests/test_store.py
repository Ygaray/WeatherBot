"""Tests for the analysis-ready SQLite store (DATA-01/02/03).

The store writes one ``weather_current`` row per units variant and one
``weather_forecast`` row per 3-hour bucket per units variant, all reusing the
Forecast's retained raw payloads from the SAME fetch (DATA-03 — no network call
inside ``persist``). The schema exposes queryable GENERATED columns (DATA-02) and
each forecast row carries ``target_ts_utc`` — the accuracy-join key the deferred
v2 forecast-vs-actual analysis needs with no migration.
"""

from __future__ import annotations

import json
import sqlite3

from weatherbot.config.models import Location
from weatherbot.weather.models import Forecast
from weatherbot.weather.store import init_db, persist

LOC = Location(name="New York", lat=40.7128, lon=-74.006)


def _build(load_fixture) -> Forecast:
    """Build a Forecast from the recorded New York (-14400s) fixtures."""
    return Forecast.from_payloads(
        LOC,
        load_fixture("current_imperial_clear.json"),
        load_fixture("current_metric_clear.json"),
        load_fixture("forecast_imperial_clear.json"),
        load_fixture("forecast_metric_clear.json"),
    )


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_init_db_creates_tables_and_indexes(tmp_db):
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
    assert {"weather_current", "weather_forecast"} <= tables
    assert {
        "ix_current_loc_time",
        "ix_current_loc_date",
        "ix_forecast_loc_target",
        "ix_forecast_loc_targetdate",
        "ix_forecast_fetched",
    } <= indexes


def test_init_db_is_idempotent(tmp_db):
    init_db(tmp_db)
    # Re-running must not raise (CREATE ... IF NOT EXISTS).
    init_db(tmp_db)


def test_persist_writes_current_and_forecast_rows(load_fixture, tmp_db):
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        cur_rows = list(conn.execute("SELECT * FROM weather_current"))
        fc_rows = list(conn.execute("SELECT * FROM weather_forecast"))

    # One current row per units variant (imperial + metric).
    assert len(cur_rows) == 2
    assert {r["units"] for r in cur_rows} == {"imperial", "metric"}

    # One forecast row per bucket per units variant.
    n_buckets = len(forecast.raw_forecast_imp["list"])
    assert n_buckets > 0
    assert len(fc_rows) == 2 * n_buckets
    assert {r["units"] for r in fc_rows} == {"imperial", "metric"}

    # Location is tagged on every row.
    assert all(r["location_name"] == "New York" for r in cur_rows + fc_rows)


def test_persist_makes_no_network_call(load_fixture, tmp_db, monkeypatch):
    """DATA-03: persist reuses retained payloads — never fetches (no httpx use)."""
    import weatherbot.weather.store as store_mod

    # If persist tried any network, importing/using httpx would be the only path;
    # assert the module does not reference httpx at all.
    assert not hasattr(store_mod, "httpx")

    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)  # must complete with no network access


def test_target_ts(load_fixture, tmp_db):
    """DATA-02: every forecast row carries non-null target_ts_utc + local date,
    and the GENERATED temp/pop columns are queryable."""
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        rows = list(
            conn.execute(
                "SELECT target_ts_utc, target_local_date, temp, pop "
                "FROM weather_forecast WHERE units='imperial' "
                "ORDER BY target_ts_utc"
            )
        )

    assert rows, "expected forecast rows"
    for r in rows:
        assert r["target_ts_utc"] is not None
        assert r["target_local_date"] is not None
        # Generated columns return numeric values from the stored raw JSON.
        assert isinstance(r["temp"], (int, float))
        assert isinstance(r["pop"], (int, float))

    # target_ts_utc matches the bucket dt of the retained payload.
    expected = [b["dt"] for b in forecast.raw_forecast_imp["list"]]
    assert [r["target_ts_utc"] for r in rows] == sorted(expected)


def test_generated_columns_match_raw_json(load_fixture, tmp_db):
    """Generated columns always agree with the stored raw_json (no drift)."""
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT raw_json, temp, conditions FROM weather_forecast "
            "WHERE units='imperial' LIMIT 1"
        ).fetchone()

    raw = json.loads(row["raw_json"])
    assert row["temp"] == raw["main"]["temp"]
    assert row["conditions"] == raw["weather"][0]["main"]


def test_current_row_units_and_json_roundtrip(load_fixture, tmp_db):
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT raw_json, units, temp, local_date, observed_at_utc "
            "FROM weather_current WHERE units='imperial'"
        ).fetchone()

    raw = json.loads(row["raw_json"])  # round-trips as valid JSON
    assert raw["main"]["temp"] == row["temp"]
    assert row["units"] == "imperial"
    assert row["local_date"]  # non-empty YYYY-MM-DD
    assert row["observed_at_utc"] == raw["dt"]


def test_no_secret_in_stored_json(load_fixture, tmp_db):
    """T-03-01: no stored raw_json carries the OpenWeather appid or a request URL."""
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        blobs = [
            r[0]
            for r in conn.execute("SELECT raw_json FROM weather_current")
        ] + [
            r[0]
            for r in conn.execute("SELECT raw_json FROM weather_forecast")
        ]

    for blob in blobs:
        assert "appid" not in blob
        assert "api.openweathermap.org" not in blob
