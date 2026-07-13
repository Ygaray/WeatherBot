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
from urllib.parse import quote

from weatherbot.weather.dates import local_date_for

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

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY,
    location_name   TEXT    NOT NULL,
    slot_time       TEXT    NOT NULL,   -- "HH:MM" slot identity (D-03)
    local_date      TEXT    NOT NULL,   -- YYYY-MM-DD in the location's tz
    reason          TEXT    NOT NULL,   -- reason taxonomy (transient_exhausted, ...)
    severity        TEXT    NOT NULL,   -- "critical" by default
    created_at_utc  INTEGER NOT NULL,
    resolved_at_utc INTEGER,            -- NULL = unresolved (D-13)
    UNIQUE(location_name, slot_time, local_date)  -- at-most-one alert/slot/day (D-11)
);

CREATE TABLE IF NOT EXISTS uv_alerts (
    id             INTEGER PRIMARY KEY,
    location_id    TEXT    NOT NULL,   -- Location.id (rename-safe identity, DP-1)
    local_date     TEXT    NOT NULL,   -- YYYY-MM-DD in the location's configured tz
    alert_kind     TEXT    NOT NULL,   -- 'prewarn' | 'crossing' | 'allclear'
    created_at_utc INTEGER NOT NULL,
    UNIQUE(location_id, local_date, alert_kind)  -- at-most-once/location/day/kind (UV-05)
);

CREATE TABLE IF NOT EXISTS heartbeat (
    id               INTEGER PRIMARY KEY CHECK (id = 1),  -- single liveness row (D-05)
    last_tick_utc    INTEGER,
    last_success_utc INTEGER
);
INSERT OR IGNORE INTO heartbeat (id, last_tick_utc, last_success_utc)
    VALUES (1, NULL, NULL);

CREATE TABLE IF NOT EXISTS health (
    id             INTEGER PRIMARY KEY CHECK (id = 1),  -- single status row (D-08)
    reason         TEXT,                                 -- online | network_not_ready | auth_failed
    detail         TEXT,                                 -- outcome-only, NEVER a secret (T-04-01)
    updated_at_utc INTEGER
);
INSERT OR IGNORE INTO health (id, reason, detail, updated_at_utc)
    VALUES (1, NULL, NULL, NULL);
"""


def _connect(db_path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a store connection with a per-connection ``busy_timeout`` (D-06).

    Centralizes all store connect discipline (HARD-STORE-02). When ``read_only``
    is True the db is opened via a ``file:...?mode=ro`` URI (``uri=True``) so any
    accidental write raises ``attempt to write a readonly database`` instead of
    silently mutating — the four status readers use this branch and take NO write
    lock under WAL (D-07, F10 fix).

    WR-01/IN-02: the read-only path resolves ``db_path`` to an absolute path and
    **percent-encodes** it (``urllib.parse.quote``) before building the URI, so a
    ``?`` or ``#`` inside the path cannot be parsed as the URI query/fragment
    delimiter and silently truncate the filename (which would open a DIFFERENT,
    empty database — diverging reads from the plain ``sqlite3.connect(db_path)``
    write path and, e.g., making ``was_sent`` answer ``False`` for an already-sent
    slot ⇒ a duplicate briefing). Reads and writes therefore always resolve to the
    same file. Parameterized ``?`` inserts already keep the path out of SQL; this
    additionally closes the URI-metacharacter hole for the ``uri=True`` branch.

    ``PRAGMA busy_timeout`` is per-connection (must be set on every connect), so it
    is set here on every returned connection. WAL journal mode is *persistent* and
    is therefore NOT set here — :func:`init_db` establishes it once (D-05).
    """
    if read_only:
        # Percent-encode the resolved absolute path so a ``?``/``#`` in db_path
        # cannot truncate the URI target (WR-01). The plain write branch below is
        # already immune (no ``uri=True``), so both branches now hit the same file.
        uri = f"file:{quote(str(Path(db_path).resolve()))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=5000")  # D-06: per-connection ~5s default
    return conn


def init_db(db_path: str | Path) -> None:
    """Establish WAL and own the one-time schema + seed-row bootstrap (D-05/D-07).

    Sets ``PRAGMA journal_mode=WAL`` ONCE (WAL is persistent — it survives reopen,
    so a later fresh connect reports ``journal_mode=wal``), then executes the
    schema script (the ``CREATE ... IF NOT EXISTS`` tables/indexes plus the
    ``INSERT OR IGNORE`` heartbeat/health seed rows). This function is the SOLE
    owner of the schema bootstrap: no read or per-write connection re-runs the DDL,
    so a status read takes no write lock (F10). Idempotent — every DDL statement is
    ``IF NOT EXISTS`` and the seeds are ``INSERT OR IGNORE``, so re-running is safe.
    """
    # ACCEPTED (F64, v2.1): the audit flagged per-op full ``_SCHEMA`` re-exec on every
    # store connect (a latent perf/contention nit on the hot delivery path). That is the
    # SOLE remaining schema-bootstrap site — ``init_db`` owns the one-time DDL and every
    # per-write connect (persist/was_sent/mark_sent/heartbeat/health) executes NO DDL (see
    # their docstrings: "Schema is owned by init_db … no per-write DDL", D-05/D-07/F10). So
    # the init-once guard the finding asked for already exists structurally: the DDL runs
    # once here at startup, not per operation. No further code change is warranted — the
    # perf concern is already closed by the F10 store-connect discipline.
    with _connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # D-05: persistent, set once
        conn.executescript(_SCHEMA)
        conn.commit()


def persist(db_path: str | Path, location: Location, forecast: Forecast) -> None:
    """Write one One Call fetch (both units) to the ``weather_onecall`` table.

    Reuses the ``Forecast``'s two retained One Call payloads — performs NO network
    call (DATA-03). ``target_local_date`` is computed from the configured IANA tz
    (D-03), NOT the payload's ``timezone_offset``. All inserts are parameterized.
    """
    now_utc = datetime.now(timezone.utc)
    fetched_at = int(now_utc.timestamp())
    target_local_date = local_date_for(location, now_utc)

    onecall_variants = (
        ("imperial", forecast.raw_onecall_imp),
        ("metric", forecast.raw_onecall_met),
    )

    with _connect(db_path) as conn:
        # init_db owns the schema (D-05/D-07); this write no longer re-runs the
        # DDL. The two INSERTs + single commit remain ONE atomic transaction —
        # both unit variants land or neither (D-08, HARD-STORE-01).
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

    The primary dedup guard (check-before-fire, D-07). READ-ONLY: opens the db
    read-only (``mode=ro``) and writes nothing — no schema DDL — so a status read
    takes NO write lock and never contends with a concurrent daemon write (F10).
    Startup (:func:`init_db`) owns schema creation. All values are bound as
    parameters — never f-string'd into SQL (T-03-01 SQLi).
    """
    with _connect(db_path, read_only=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM sent_log "
            "WHERE location_name=? AND send_time=? AND local_date=?",
            (location_name, send_time, local_date),
        ).fetchone()
    return row is not None


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

    Parameterized ``?`` only — never an f-string into SQL (T-03-01 SQLi). Schema
    is owned by :func:`init_db` at startup; this write no longer re-runs the DDL.
    """
    sent_at_utc = int(datetime.now(timezone.utc).timestamp())
    with _connect(db_path) as conn:
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
    only — never an f-string into SQL. Schema is owned by :func:`init_db`.
    """
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM sent_log WHERE location_name=? AND send_time=? AND local_date=?",
            (location_name, send_time, local_date),
        )
        conn.commit()


def record_alert(
    db_path: str | Path,
    location_name: str,
    slot_time: str,
    local_date: str,
    reason: str,
    severity: str = "critical",
) -> bool:
    """Durably record a missed-briefing alert, at most once per slot/day (RELY-03/04).

    Structural copy of :func:`claim_slot`: a single parameterized
    ``INSERT OR IGNORE`` against the ``UNIQUE(location_name, slot_time, local_date)``
    key (D-11 anti-loop) — never a SELECT-then-INSERT. Returns ``cur.rowcount == 1``:
    ``True`` ⇒ THIS caller wrote the row (the FIRST alert for this slot/day, so the
    caller may ALSO emit the CRITICAL log); ``False`` ⇒ an alert already existed, so
    a re-fire/retry does not re-alert (the dedup that prevents an alert loop, D-11).

    Rows carry ONLY location/slot/date/reason/severity/timestamp — never a key or URL
    (T-04-01). Parameterized ``?`` only — never an f-string into SQL (T-03-01 SQLi).
    Schema is owned by :func:`init_db` at startup; this write no longer re-runs DDL.
    """
    created_at_utc = int(datetime.now(timezone.utc).timestamp())
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO alerts "
            "(location_name, slot_time, local_date, reason, severity, created_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (location_name, slot_time, local_date, reason, severity, created_at_utc),
        )
        conn.commit()
        return cur.rowcount == 1


def claim_uv_alert(
    db_path: str | Path,
    location_id: str,
    local_date: str,
    alert_kind: str,
) -> bool:
    """Atomically claim ONE UV alert (kind) for a location/day (UV-05, DP-1).

    Structural copy of :func:`record_alert`: a single parameterized
    ``INSERT OR IGNORE`` against the dedicated ``uv_alerts`` table's
    ``UNIQUE(location_id, local_date, alert_kind)`` key — never a
    SELECT-then-INSERT. Returns ``cur.rowcount == 1``: ``True`` ⇒ THIS caller
    wrote the row (the FIRST claim of this kind today, so the caller may post the
    alert); ``False`` ⇒ a row already existed (a repeat tick / a mid-day restart
    must NOT re-post — the durability that defeats Pitfall 2 re-spam).

    Keyed on ``location.id`` (the rename-safe identity), NOT ``location.name``.
    The ``uv_alerts`` namespace is fully separate from the briefing
    ``sent_log``/``alerts`` namespace — a UV dedup bug can never touch a briefing
    (UV-06 safety property, T-15-03).

    Rows carry ONLY location_id/date/kind/timestamp — never a key or URL
    (T-15-04). Parameterized ``?`` only — never an f-string into SQL (T-15-01
    SQLi). Schema is owned by :func:`init_db` at startup; no per-write DDL.
    """
    created_at_utc = int(datetime.now(timezone.utc).timestamp())
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO uv_alerts "
            "(location_id, local_date, alert_kind, created_at_utc) "
            "VALUES (?, ?, ?, ?)",
            (location_id, local_date, alert_kind, created_at_utc),
        )
        conn.commit()
        return cur.rowcount == 1


def claimed_uv_kinds(
    db_path: str | Path,
    location_id: str,
    local_date: str,
) -> set[str]:
    """Return the durable set of UV alert kinds already claimed today (UV-05).

    The restart-safe "prior" set that drives the monitor's three decision
    branches: ``{kind, ...}`` for every row already in ``uv_alerts`` for this
    ``(location_id, local_date)``. An untouched location/day yields an empty set.
    Reads its own connection (so the set survives a process restart — it is NOT
    an in-memory cache). READ-ONLY: opens the db read-only (``mode=ro``) and writes
    nothing — no schema DDL — so the read takes NO write lock (F10). Parameterized
    ``?`` only (T-15-01).
    """
    with _connect(db_path, read_only=True) as conn:
        rows = conn.execute(
            "SELECT alert_kind FROM uv_alerts WHERE location_id=? AND local_date=?",
            (location_id, local_date),
        ).fetchall()
    return {r[0] for r in rows}


def resolve_alert(
    db_path: str | Path,
    location_name: str,
    slot_time: str,
    local_date: str,
) -> None:
    """Stamp an alert resolved when the slot later succeeds (D-13).

    Copy of :func:`release_claim`'s parameterized shape: an ``UPDATE ... WHERE`` bound
    on all three key columns plus ``resolved_at_utc IS NULL`` so it only touches the
    matching UNRESOLVED row and is a no-op when no such alert exists. Parameterized
    ``?`` only — never an f-string into SQL (T-03-01 SQLi). Schema owned by
    :func:`init_db`.
    """
    resolved_at_utc = int(datetime.now(timezone.utc).timestamp())
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE alerts SET resolved_at_utc=? "
            "WHERE location_name=? AND slot_time=? AND local_date=? "
            "AND resolved_at_utc IS NULL",
            (resolved_at_utc, location_name, slot_time, local_date),
        )
        conn.commit()


def stamp_tick(db_path: str | Path) -> None:
    """Record a liveness tick on the single heartbeat row (RELY-05, D-05).

    Updates the seeded ``id=1`` row in place (the schema seeds it via
    ``INSERT OR IGNORE``), so there is always exactly one heartbeat row for a future
    monitor to read. Parameterized ``?`` only (T-03-01 SQLi). Schema owned by
    :func:`init_db`.
    """
    last_tick_utc = int(datetime.now(timezone.utc).timestamp())
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE heartbeat SET last_tick_utc=? WHERE id=1",
            (last_tick_utc,),
        )
        conn.commit()


def stamp_success(db_path: str | Path) -> None:
    """Record the last successful delivery on the single heartbeat row (RELY-05, D-05).

    Updates the seeded ``id=1`` row in place. Parameterized ``?`` only (T-03-01
    SQLi). Schema owned by :func:`init_db`.
    """
    last_success_utc = int(datetime.now(timezone.utc).timestamp())
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE heartbeat SET last_success_utc=? WHERE id=1",
            (last_success_utc,),
        )
        conn.commit()


def stamp_health(db_path: str | Path, reason: str, detail: str = "") -> None:
    """Upsert the single health row with the latest self-check outcome (OPS-02, D-08).

    Updates the seeded ``id=1`` row in place (the schema seeds it via
    ``INSERT OR IGNORE``), so there is always exactly one health row for the future
    inbound-``status`` reader (deferred, D-08) to query. ``reason`` is one of
    ``online`` / ``network_not_ready`` / ``auth_failed``; ``detail`` is outcome-only
    (a status code or exception class name) — NEVER the key or webhook URL
    (T-04-01). Parameterized ``?`` only — never an f-string into SQL (T-03-01
    SQLi). Schema owned by :func:`init_db` at startup; no per-write DDL.
    """
    now = int(datetime.now(timezone.utc).timestamp())
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE health SET reason=?, detail=?, updated_at_utc=? WHERE id=1",
            (reason, detail, now),
        )
        conn.commit()


def read_heartbeat(db_path: str | Path) -> dict:
    """Read the single liveness row for ``status`` (CMD-12 reader, D-05).

    READ-ONLY: opens the db read-only (``mode=ro``) and writes nothing — no schema
    DDL — so the read takes NO write lock and never contends with a concurrent
    daemon write (F10). Startup (:func:`init_db`) seeds the ``id=1`` row via
    ``INSERT OR IGNORE``, so the row always exists (values ``None`` until first
    stamped). Parameterized ``?`` only — never an f-string into SQL (T-03-01 SQLi).
    Returns ``{"last_tick_utc": ..., "last_success_utc": ...}``.
    """
    with _connect(db_path, read_only=True) as conn:
        row = conn.execute(
            "SELECT last_tick_utc, last_success_utc FROM heartbeat WHERE id=?",
            (1,),
        ).fetchone()
    return {"last_tick_utc": row[0], "last_success_utc": row[1]}


def read_health(db_path: str | Path) -> dict:
    """Read the single health row for ``status`` (CMD-12 reader, D-08).

    READ-ONLY: opens the db read-only (``mode=ro``) and writes nothing — no schema
    DDL — so the read takes NO write lock and never contends with a concurrent
    daemon write (F10). Startup (:func:`init_db`) seeds the ``id=1`` row via
    ``INSERT OR IGNORE``, so the row always exists (values ``None`` until first
    stamped). Parameterized ``?`` only — never an f-string into SQL (T-03-01 SQLi).
    Returns ``{"reason": ..., "detail": ..., "updated_at_utc": ...}``.
    """
    with _connect(db_path, read_only=True) as conn:
        row = conn.execute(
            "SELECT reason, detail, updated_at_utc FROM health WHERE id=?",
            (1,),
        ).fetchone()
    return {"reason": row[0], "detail": row[1], "updated_at_utc": row[2]}
