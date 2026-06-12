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
from weatherbot.weather.store import (
    init_db,
    persist,
    record_alert,
    resolve_alert,
    stamp_health,
    stamp_success,
    stamp_tick,
)

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


# --- 04-02: alerts table + record_alert/resolve_alert (RELY-03/04, D-03/11/13) ---


def test_record_alert_writes_one_row(tmp_db):
    """RELY-03: a missed briefing is durably recorded with reason + created_at."""
    record_alert(tmp_db, "NYC", "09:00", "2026-06-10", "transient_exhausted")

    with _connect(tmp_db) as conn:
        rows = list(conn.execute("SELECT * FROM alerts"))

    assert len(rows) == 1
    row = rows[0]
    assert row["location_name"] == "NYC"
    assert row["slot_time"] == "09:00"
    assert row["local_date"] == "2026-06-10"
    assert row["reason"] == "transient_exhausted"
    assert row["severity"] == "critical"  # default
    assert row["created_at_utc"] is not None
    assert row["resolved_at_utc"] is None  # unresolved (D-13)


def test_record_alert_dedup_no_loop(tmp_db):
    """RELY-04 / D-11: a second alert for the same slot/day is an INSERT-OR-IGNORE
    no-op — exactly one row; the first caller gets True, the second False."""
    first = record_alert(tmp_db, "NYC", "09:00", "2026-06-10", "transient_exhausted")
    second = record_alert(tmp_db, "NYC", "09:00", "2026-06-10", "transient_exhausted")

    assert first is True  # this caller was first
    assert second is False  # already recorded — anti-loop

    with _connect(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 1


def test_resolve_alert_stamps_only_matching_unresolved_row(tmp_db):
    """D-13: resolve_alert sets resolved_at_utc for the matching unresolved row."""
    record_alert(tmp_db, "NYC", "09:00", "2026-06-10", "transient_exhausted")
    resolve_alert(tmp_db, "NYC", "09:00", "2026-06-10")

    with _connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT resolved_at_utc FROM alerts "
            "WHERE location_name='NYC' AND slot_time='09:00' AND local_date='2026-06-10'"
        ).fetchone()
    assert row["resolved_at_utc"] is not None


def test_resolve_alert_is_noop_when_no_row(tmp_db):
    """resolve_alert is a no-op (does not raise, creates nothing) with no match."""
    resolve_alert(tmp_db, "NYC", "09:00", "2026-06-10")  # must not raise

    with _connect(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert count == 0


# --- 04-02: heartbeat single-row upsert (RELY-05, D-05) ---


def test_heartbeat_single_row_upserts_in_place(tmp_db):
    """RELY-05 / D-05: stamp_tick + stamp_success maintain ONE heartbeat row (id=1)
    with both timestamps populated; repeated stamps update in place."""
    stamp_tick(tmp_db)
    stamp_success(tmp_db)

    with _connect(tmp_db) as conn:
        rows = list(conn.execute("SELECT * FROM heartbeat"))
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["last_tick_utc"] is not None
    assert rows[0]["last_success_utc"] is not None

    # Repeated stamps update in place — still exactly one row.
    stamp_tick(tmp_db)
    stamp_tick(tmp_db)
    with _connect(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM heartbeat").fetchone()[0]
    assert count == 1


# --- 04-02: T-04-01 secret hygiene on the new tables ---


def test_no_secret_in_alert_or_heartbeat_rows(tmp_db):
    """T-04-01: stored alert/heartbeat rows carry no OpenWeather key or host."""
    record_alert(tmp_db, "NYC", "09:00", "2026-06-10", "transient_exhausted")
    stamp_tick(tmp_db)
    stamp_success(tmp_db)

    with _connect(tmp_db) as conn:
        alert_blob = " ".join(
            str(v) for r in conn.execute("SELECT * FROM alerts") for v in tuple(r)
        )
        hb_blob = " ".join(
            str(v) for r in conn.execute("SELECT * FROM heartbeat") for v in tuple(r)
        )

    for blob in (alert_blob, hb_blob):
        assert "appid" not in blob
        assert "api.openweathermap.org" not in blob


# --- 05-01: health single-row upsert (OPS-02, D-08) ---


def test_health_single_row_upserts_in_place(tmp_db):
    """D-08: stamp_health maintains ONE health row (id=1); repeated stamps update
    in place and reflect the LATEST reason/detail."""
    stamp_health(tmp_db, reason="online")

    with _connect(tmp_db) as conn:
        rows = list(conn.execute("SELECT * FROM health"))
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["reason"] == "online"
    assert rows[0]["updated_at_utc"] is not None

    # A second stamp UPDATES in place — still exactly one row, latest values win.
    stamp_health(tmp_db, reason="auth_failed", detail="401")
    with _connect(tmp_db) as conn:
        rows = list(conn.execute("SELECT * FROM health"))
    assert len(rows) == 1
    assert rows[0]["reason"] == "auth_failed"
    assert rows[0]["detail"] == "401"
    assert rows[0]["updated_at_utc"] is not None


def test_no_secret_in_health_row(tmp_db):
    """T-04-01: the health row carries reason/detail/timestamp only — no key/URL."""
    stamp_health(tmp_db, reason="auth_failed", detail="401")
    stamp_health(tmp_db, reason="network_not_ready", detail="ConnectError")

    with _connect(tmp_db) as conn:
        health_blob = " ".join(
            str(v) for r in conn.execute("SELECT * FROM health") for v in tuple(r)
        )

    assert "appid" not in health_blob
    assert "api.openweathermap.org" not in health_blob
