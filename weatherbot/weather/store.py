"""Analysis-ready SQLite persistence (DATA-01/02/03).

The store writes the briefing's *existing* fetch — no extra OpenWeather call
(DATA-03). Each ``persist`` call inserts one ``weather_onecall`` row per units
variant (imperial + metric), reusing the ``Forecast``'s two retained One Call
payloads. The full One Call response is stored as ``raw_json`` TEXT and exposed
through GENERATED VIRTUAL columns via ``json_extract`` — so v2 analysis columns
are added with no back-fill (DATA-02). Each row carries ``target_local_date``
(computed from the CONFIGURED IANA tz, D-03) so a deferred v2 forecast-vs-actual
accuracy join needs no migration.

The old 2.5 ``weather_current`` / ``weather_forecast`` tables are RETAINED in the
schema (idempotent ``CREATE TABLE IF NOT EXISTS``) as historical data but are no
longer written — new writes go to ``weather_onecall`` (A3: new table, no
destructive backfill).

Secret hygiene (T-02-03): only OpenWeather *response* payloads are stored; the
request URL (which carries the ``appid``) is never persisted. All inserts are
parameterized ``?`` (SQLi-safe).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

CREATE TABLE IF NOT EXISTS weather_onecall (
    id                INTEGER PRIMARY KEY,
    location_name     TEXT    NOT NULL,
    lat               REAL    NOT NULL,
    lon               REAL    NOT NULL,
    fetched_at_utc    INTEGER NOT NULL,
    target_local_date TEXT    NOT NULL,
    units             TEXT    NOT NULL,
    raw_json          TEXT    NOT NULL,
    temp       REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.current.temp')) VIRTUAL,
    feels_like REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.current.feels_like')) VIRTUAL,
    humidity   REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.current.humidity')) VIRTUAL,
    wind_speed REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.current.wind_speed')) VIRTUAL,
    uvi        REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.current.uvi')) VIRTUAL,
    day_high   REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.daily[0].temp.max')) VIRTUAL,
    day_low    REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.daily[0].temp.min')) VIRTUAL,
    pop        REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.daily[0].pop')) VIRTUAL,
    day_uvi    REAL GENERATED ALWAYS AS (json_extract(raw_json,'$.daily[0].uvi')) VIRTUAL
);
CREATE INDEX IF NOT EXISTS ix_onecall_loc_time
    ON weather_onecall(location_name, fetched_at_utc);
CREATE INDEX IF NOT EXISTS ix_onecall_loc_date
    ON weather_onecall(location_name, target_local_date);
"""


def init_db(db_path: str | Path) -> None:
    """Create the schema (tables, generated columns, indexes) if absent.

    Idempotent: every statement uses ``IF NOT EXISTS`` so re-running is safe.
    Kept as a public function for callers/tests that want to create the schema
    standalone; ``persist`` creates the schema inline on its own connection.
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def _local_date_iso(location: Location, now_utc: datetime) -> str:
    """The location's local ``YYYY-MM-DD`` today, from the CONFIGURED IANA tz.

    The configured ``Location.timezone`` is authoritative (D-03), NOT the API
    ``timezone`` offset (Pitfall 3). Falls back to UTC when absent/invalid.
    """
    tz_name = getattr(location, "timezone", None)
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
    else:
        tz = timezone.utc
    return now_utc.astimezone(tz).date().isoformat()


def persist(db_path: str | Path, location: Location, forecast: Forecast) -> None:
    """Write one One Call fetch (both units) to the ``weather_onecall`` table.

    Reuses the ``Forecast``'s two retained One Call payloads — performs NO network
    call (DATA-03). ``target_local_date`` is computed from the configured IANA tz
    (D-03), NOT the payload's ``timezone_offset``. All inserts are parameterized.
    """
    now_utc = datetime.now(timezone.utc)
    fetched_at = int(now_utc.timestamp())
    target_local_date = _local_date_iso(location, now_utc)

    onecall_variants = (
        ("imperial", forecast.raw_onecall_imp),
        ("metric", forecast.raw_onecall_met),
    )

    with sqlite3.connect(db_path) as conn:
        # Create the schema in the SAME connection/transaction as the inserts
        # (idempotent; all ``IF NOT EXISTS``) instead of opening a second
        # connection per write. Keeps schema + data atomic and halves the
        # connection count per send (WR-03).
        conn.executescript(_SCHEMA)

        for units, payload in onecall_variants:
            conn.execute(
                "INSERT INTO weather_onecall ("
                "location_name, lat, lon, fetched_at_utc, "
                "target_local_date, units, raw_json"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    location.name,
                    location.lat,
                    location.lon,
                    fetched_at,
                    target_local_date,
                    units,
                    json.dumps(payload),
                ),
            )

        conn.commit()
