"""Analysis-ready SQLite persistence (DATA-01/02/03).

The store writes the briefing's *existing* fetch — no extra OpenWeather call
(DATA-03). Each ``persist`` call inserts:

* one ``weather_current`` row per units variant (imperial + metric), and
* one ``weather_forecast`` row per 3-hour bucket per units variant,

all from the ``Forecast``'s four retained raw payloads. The schema follows the
RESEARCH §SQLite Schema Design: the full response (current) or single bucket
(forecast) is stored as ``raw_json`` TEXT and exposed through GENERATED VIRTUAL
columns via ``json_extract`` — so v2 analysis columns are added with no
back-fill (DATA-02). Forecast rows carry ``target_ts_utc`` (the bucket's valid
time) so a deferred v2 forecast-vs-actual accuracy join needs no migration.

Secret hygiene (T-03-01): only OpenWeather *response* payloads are stored; the
request URL (which carries the ``appid``) is never persisted.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weatherbot.config.models import Location
    from weatherbot.weather.models import Forecast


_SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_current (
    id              INTEGER PRIMARY KEY,
    location_name   TEXT    NOT NULL,
    lat             REAL    NOT NULL,
    lon             REAL    NOT NULL,
    fetched_at_utc  INTEGER NOT NULL,
    observed_at_utc INTEGER NOT NULL,
    tz_offset_sec   INTEGER NOT NULL,
    local_date      TEXT    NOT NULL,
    units           TEXT    NOT NULL,
    raw_json        TEXT    NOT NULL,
    temp       REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp')) VIRTUAL,
    humidity   REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.humidity')) VIRTUAL,
    wind_speed REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.wind.speed')) VIRTUAL,
    conditions TEXT GENERATED ALWAYS AS (json_extract(raw_json,'$.weather[0].main')) VIRTUAL
);
CREATE INDEX IF NOT EXISTS ix_current_loc_time
    ON weather_current(location_name, observed_at_utc);
CREATE INDEX IF NOT EXISTS ix_current_loc_date
    ON weather_current(location_name, local_date);

CREATE TABLE IF NOT EXISTS weather_forecast (
    id                INTEGER PRIMARY KEY,
    location_name     TEXT    NOT NULL,
    lat               REAL    NOT NULL,
    lon               REAL    NOT NULL,
    fetched_at_utc    INTEGER NOT NULL,
    target_ts_utc     INTEGER NOT NULL,
    target_local_date TEXT    NOT NULL,
    tz_offset_sec     INTEGER NOT NULL,
    units             TEXT    NOT NULL,
    raw_json          TEXT    NOT NULL,
    temp       REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp')) VIRTUAL,
    temp_min   REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp_min')) VIRTUAL,
    temp_max   REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.temp_max')) VIRTUAL,
    pop        REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.pop')) VIRTUAL,
    humidity   REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.main.humidity')) VIRTUAL,
    wind_speed REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.wind.speed')) VIRTUAL,
    conditions TEXT GENERATED ALWAYS AS (json_extract(raw_json,'$.weather[0].main')) VIRTUAL
);
CREATE INDEX IF NOT EXISTS ix_forecast_loc_target
    ON weather_forecast(location_name, target_ts_utc);
CREATE INDEX IF NOT EXISTS ix_forecast_loc_targetdate
    ON weather_forecast(location_name, target_local_date);
CREATE INDEX IF NOT EXISTS ix_forecast_fetched
    ON weather_forecast(location_name, fetched_at_utc);
"""


def init_db(db_path: str | Path) -> None:
    """Create the schema (tables, generated columns, indexes) if absent.

    Idempotent: every statement uses ``IF NOT EXISTS`` so re-running is safe.
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def _local_date_iso(unix_ts: int, tz_offset_sec: int) -> str:
    """The local ``YYYY-MM-DD`` for a unix instant under a UTC offset."""
    local = datetime.fromtimestamp(unix_ts, tz=timezone.utc) + timedelta(
        seconds=tz_offset_sec
    )
    return local.date().isoformat()


def persist(db_path: str | Path, location: Location, forecast: Forecast) -> None:
    """Write one fetch (current + forecast, both units) to SQLite.

    Reuses the ``Forecast``'s four retained raw payloads — performs NO network
    call (DATA-03). Computes ``local_date``/``target_local_date`` at write time
    from each payload's unix timestamp + its ``timezone`` offset.
    """
    init_db(db_path)

    fetched_at = int(datetime.now(timezone.utc).timestamp())

    current_variants = (
        ("imperial", forecast.raw_current_imp),
        ("metric", forecast.raw_current_met),
    )
    forecast_variants = (
        ("imperial", forecast.raw_forecast_imp),
        ("metric", forecast.raw_forecast_met),
    )

    with sqlite3.connect(db_path) as conn:
        for units, payload in current_variants:
            # ``or`` fallbacks: a present-but-null field returns None from ``.get``.
            observed_at = payload.get("dt") or fetched_at
            tz_offset = payload.get("timezone") or 0
            conn.execute(
                "INSERT INTO weather_current ("
                "location_name, lat, lon, fetched_at_utc, observed_at_utc, "
                "tz_offset_sec, local_date, units, raw_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    location.name,
                    location.lat,
                    location.lon,
                    fetched_at,
                    observed_at,
                    tz_offset,
                    _local_date_iso(observed_at, tz_offset),
                    units,
                    json.dumps(payload),
                ),
            )

        for units, payload in forecast_variants:
            city = payload.get("city") or {}
            tz_offset = city.get("timezone") or 0
            for bucket in payload.get("list", []):
                # Skip a bucket with no usable target time rather than KeyError;
                # ``target_ts_utc`` is NOT NULL, so a null/absent dt can't persist.
                target_ts = bucket.get("dt")
                if target_ts is None:
                    continue
                conn.execute(
                    "INSERT INTO weather_forecast ("
                    "location_name, lat, lon, fetched_at_utc, target_ts_utc, "
                    "target_local_date, tz_offset_sec, units, raw_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        location.name,
                        location.lat,
                        location.lon,
                        fetched_at,
                        target_ts,
                        _local_date_iso(target_ts, tz_offset),
                        tz_offset,
                        units,
                        json.dumps(bucket),
                    ),
                )

        conn.commit()
