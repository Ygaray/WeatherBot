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

CREATE TABLE IF NOT EXISTS sent_log (
    id            INTEGER PRIMARY KEY,
    location_name TEXT    NOT NULL,
    send_time     TEXT    NOT NULL,   -- "HH:MM" slot identity (D-06)
    local_date    TEXT    NOT NULL,   -- YYYY-MM-DD in the location's tz
    sent_at_utc   INTEGER NOT NULL,
    UNIQUE(location_name, send_time, local_date)
);
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


def was_sent(
    db_path: str | Path,
    location_name: str,
    send_time: str,
    local_date: str,
) -> bool:
    """Has this ``(location, send_time, local_date)`` slot already been sent?

    The primary dedup guard (check-before-fire, D-07). Creates the schema on
    connect (idempotent) so it works against a never-initialized db_path. All
    values are bound as parameters — never f-string'd into SQL (T-03-01 SQLi).
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        row = conn.execute(
            "SELECT 1 FROM sent_log "
            "WHERE location_name=? AND send_time=? AND local_date=?",
            (location_name, send_time, local_date),
        ).fetchone()
    return row is not None


def record_sent(
    db_path: str | Path,
    location_name: str,
    send_time: str,
    local_date: str,
) -> None:
    """Mark a ``(location, send_time, local_date)`` slot as sent (after success).

    Called AFTER a successful delivery (D-07). ``INSERT OR IGNORE`` on the
    ``UNIQUE`` key makes this itself idempotent — a concurrent or replayed
    re-fire (DST fall-back, restart) records exactly one row, never raising
    ``IntegrityError``. Parameterized only (T-03-01 SQLi).
    """
    sent_at_utc = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO sent_log "
            "(location_name, send_time, local_date, sent_at_utc) "
            "VALUES (?, ?, ?, ?)",
            (location_name, send_time, local_date, sent_at_utc),
        )
        conn.commit()


def claim_slot(
    db_path: str | Path,
    location_name: str,
    send_time: str,
    local_date: str,
) -> bool:
    """Atomically claim a ``(location, send_time, local_date)`` slot for delivery.

    Closes the SCHD-07 delivery-level exactly-once gap (03-VERIFICATION.md gap #2 /
    03-REVIEW.md CR-02): ``was_sent`` + ``record_sent`` is a non-atomic
    check-then-act with the side-effecting Discord send INSIDE the window, so two
    overlapping fires both pass the read and both POST. This helper collapses the
    check-and-mark into ONE atomic step taken BEFORE the network send.

    Runs a single parameterized ``INSERT OR IGNORE`` against the ``UNIQUE`` key and
    returns ``cur.rowcount == 1`` — ``True`` ⇒ THIS caller inserted the row and won
    the claim; ``False`` ⇒ the row already existed (already sent, or a concurrent
    fire won first), so this caller must NOT deliver. Exactly one ``True`` across N
    concurrent claims for the same key.

    A won claim writes exactly one ``sent_log`` row, so ``was_sent`` returns ``True``
    immediately. On a delivery FAILURE the caller must :func:`release_claim` to
    re-open the slot (mark-after-success for the failure case, D-07 / SCHD-06).

    Creates the schema on connect (idempotent). Parameterized ``?`` only — never an
    f-string into SQL (T-03-01 SQLi).
    """
    sent_at_utc = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        cur = conn.execute(
            "INSERT OR IGNORE INTO sent_log "
            "(location_name, send_time, local_date, sent_at_utc) "
            "VALUES (?, ?, ?, ?)",
            (location_name, send_time, local_date, sent_at_utc),
        )
        conn.commit()
        return cur.rowcount == 1


def release_claim(
    db_path: str | Path,
    location_name: str,
    send_time: str,
    local_date: str,
) -> None:
    """Release a previously-won claim so the slot can be re-fired.

    Called on a FAILED / non-ok delivery (the claim was taken BEFORE the send),
    so the missed slot stays re-fireable on the next catch-up/retry — preserving
    mark-after-success for the failure case (D-07) and SCHD-06 "send late on
    recovery".

    Binds ALL THREE key columns so the ``DELETE`` can only remove that one slot's
    row — there is no delete-arbitrary-row primitive (T-03-01). Parameterized ``?``
    only — never an f-string into SQL.
    """
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "DELETE FROM sent_log WHERE location_name=? AND send_time=? AND local_date=?",
            (location_name, send_time, local_date),
        )
        conn.commit()
