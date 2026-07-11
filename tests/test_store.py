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
    claim_slot,
    claim_uv_alert,
    claimed_uv_kinds,
    init_db,
    persist,
    read_health,
    read_heartbeat,
    record_alert,
    resolve_alert,
    stamp_health,
    stamp_success,
    stamp_tick,
    was_sent,
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
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
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
        blobs = [r[0] for r in conn.execute("SELECT raw_json FROM weather_onecall")]

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


# --- 12-01: read-only heartbeat/health readers (CMD-12, D-05/D-08) ---


def test_read_heartbeat_fresh_db_defaults_none(tmp_db):
    # Never-stamped db: the seeded id=1 row exists with NULL timestamps.
    hb = read_heartbeat(tmp_db)
    assert hb == {"last_tick_utc": None, "last_success_utc": None}


def test_read_heartbeat_returns_stamped_values(tmp_db):
    stamp_tick(tmp_db)
    stamp_success(tmp_db)
    hb = read_heartbeat(tmp_db)
    assert isinstance(hb["last_tick_utc"], int)
    assert isinstance(hb["last_success_utc"], int)


def test_read_health_fresh_db_defaults_none(tmp_db):
    health = read_health(tmp_db)
    assert health == {"reason": None, "detail": None, "updated_at_utc": None}


def test_read_health_returns_stamped_values(tmp_db):
    stamp_health(tmp_db, reason="online", detail="200")
    health = read_health(tmp_db)
    assert health["reason"] == "online"
    assert health["detail"] == "200"
    assert isinstance(health["updated_at_utc"], int)


# --- 15-01: uv_alerts dedup table (UV-05/UV-06, DP-1) ------------------------


def test_claim_uv_alert_first_wins_repeat_loses(tmp_db):
    # First claim of a (location_id, local_date, alert_kind) triple wins (True);
    # every subsequent claim of the SAME triple loses (False) — the once/day
    # post-once guarantee (UV-05).
    first = claim_uv_alert(tmp_db, "homeA", "2026-06-19", "prewarn")
    assert first is True
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "prewarn") is False
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "prewarn") is False


def test_claim_uv_alert_distinct_kinds_each_win_once(tmp_db):
    # The same (location_id, local_date) accepts the three independent kinds —
    # each wins exactly once.
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "prewarn") is True
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "crossing") is True
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "allclear") is True
    # Re-claiming any of them loses.
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "crossing") is False


def test_claim_uv_alert_independent_per_location_and_date(tmp_db):
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "crossing") is True
    # A DIFFERENT location is an independent claim.
    assert claim_uv_alert(tmp_db, "travelB", "2026-06-19", "crossing") is True
    # A DIFFERENT date is an independent claim.
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-20", "crossing") is True


def test_claimed_uv_kinds_durable_across_fresh_connection(tmp_db):
    # Restart-safety (Pitfall 2): claims survive across a FRESH sqlite connection.
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "prewarn") is True
    assert claim_uv_alert(tmp_db, "homeA", "2026-06-19", "crossing") is True
    # claimed_uv_kinds opens its own connection — proves durability, not in-memory.
    kinds = claimed_uv_kinds(tmp_db, "homeA", "2026-06-19")
    assert kinds == {"prewarn", "crossing"}


def test_claimed_uv_kinds_empty_for_untouched(tmp_db):
    assert claimed_uv_kinds(tmp_db, "nobody", "2026-06-19") == set()


def test_uv_alerts_namespace_isolated_from_sent_log_and_alerts(tmp_db):
    # UV-06 safety: the uv_alerts namespace NEVER touches sent_log/alerts. Claiming
    # a UV row for a name/date does not affect claim_slot/was_sent for the same
    # name/date, and vice versa.
    assert claim_uv_alert(tmp_db, "NYC", "2026-06-19", "crossing") is True
    # The briefing exactly-once slot for the same name/date is still claimable.
    assert claim_slot(tmp_db, "NYC", "09:00", "2026-06-19") is True
    assert was_sent(tmp_db, "NYC", "09:00", "2026-06-19") is True
    # And a briefing-failure alert for the same name/date is independent.
    assert record_alert(tmp_db, "NYC", "09:00", "2026-06-19", "transient_exhausted")
    # The UV claim is unaffected — re-claiming still loses (its row is intact).
    assert claim_uv_alert(tmp_db, "NYC", "2026-06-19", "crossing") is False


def test_uv_alerts_table_created_by_schema(tmp_db):
    init_db(tmp_db)
    with _connect(tmp_db) as conn:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "uv_alerts" in tables


def test_no_secret_in_uv_alert_rows(tmp_db):
    claim_uv_alert(tmp_db, "NYC", "2026-06-19", "crossing")
    with _connect(tmp_db) as conn:
        rows = conn.execute("SELECT * FROM uv_alerts").fetchall()
    blob = " ".join(str(v) for r in rows for v in tuple(r))
    # Rows carry only location_id/date/kind/timestamp — no key/URL/PII (T-15-04).
    assert "appid" not in blob.lower()
    assert "http" not in blob.lower()


# --- 31-01: WAL + busy_timeout + read-no-write-lock + atomic write ------------
# (HARD-STORE-01/02, D-05/D-06/D-07/D-08). Wave-0 RED regression tests: these
# lock the store-hardening contract before the _connect/init_db refactor lands.


def test_wal_and_busy_timeout_are_set(tmp_db):
    """HARD-STORE-02 / D-05/D-06: init_db sets WAL persistently and every store
    connection carries a non-zero busy_timeout.

    WAL is persistent (survives reopen), so a fresh RAW sqlite3 connection — one
    that never runs the store's PRAGMAs — reports journal_mode='wal' after init_db.
    busy_timeout is per-connection, so a store write path must set it: after a
    write, a raw connection's own busy_timeout is 0, but a store-owned connection
    reports the configured non-zero value. We assert the store-owned value via a
    store write followed by inspecting a fresh store connection is not directly
    observable from outside; instead we prove busy_timeout on the store's own
    _connect helper (the seam under test).
    """
    from weatherbot.weather.store import _connect

    init_db(tmp_db)

    # WAL is persistent: a plain raw connection (independent of the helper) sees it.
    with sqlite3.connect(tmp_db) as raw:
        mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"

    # busy_timeout is per-connection: the store's own connection sets a non-zero value.
    with _connect(tmp_db) as conn:
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout > 0


def test_reads_take_no_write_lock(tmp_db):
    """HARD-STORE-02 / F10 / D-07: a status read never contends for the write lock.

    With a second connection holding the write lock (BEGIN IMMEDIATE, uncommitted),
    each of the four read fns (was_sent / read_heartbeat / read_health /
    claimed_uv_kinds) must complete without raising OperationalError. They open
    read-only under WAL and run no seeding DDL, so they proceed concurrently with
    the held writer instead of raising 'database is locked'.
    """
    # Startup owns the schema + seed rows (init_db is the sole schema owner).
    init_db(tmp_db)

    # Hold the write lock on a separate connection and leave it uncommitted.
    holder = sqlite3.connect(tmp_db)
    try:
        holder.execute("BEGIN IMMEDIATE")

        # None of the four read fns may raise while the write lock is held.
        assert was_sent(tmp_db, "NYC", "09:00", "2026-06-19") is False
        assert read_heartbeat(tmp_db) == {
            "last_tick_utc": None,
            "last_success_utc": None,
        }
        assert read_health(tmp_db) == {
            "reason": None,
            "detail": None,
            "updated_at_utc": None,
        }
        assert claimed_uv_kinds(tmp_db, "homeA", "2026-06-19") == set()
    finally:
        holder.rollback()
        holder.close()


def test_onecall_write_atomic(load_fixture, tmp_db):
    """HARD-STORE-01 / D-08: persist writes both unit variants as one atomic pair,
    and target_local_date round-trips byte-identical (encoding/equality backstop)."""
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)

    with _connect(tmp_db) as conn:
        rows = list(conn.execute("SELECT units, target_local_date FROM weather_onecall"))

    # Exactly two rows land from one call — the atomic imperial+metric pair.
    assert len(rows) == 2
    assert {r["units"] for r in rows} == {"imperial", "metric"}

    # target_local_date round-trips byte-identical to the ISO string persist writes.
    from datetime import datetime, timezone

    from weatherbot.weather.dates import local_date_for

    expected = local_date_for(LOC, datetime.now(timezone.utc))
    for r in rows:
        stored = r["target_local_date"]
        assert stored == expected
        assert len(stored) == len(expected)


# --- WR-01: read-only URI must not truncate a db_path containing ?/# ----------


def test_read_only_path_metacharacter_reads_same_file_as_write(tmp_path):
    """WR-01: a ``?`` (or ``#``) in db_path must not make the read-only branch open
    a DIFFERENT (empty) database than the write branch.

    The write path uses plain ``sqlite3.connect(db_path)`` (immune), but the
    read-only branch builds a ``file:...?mode=ro`` URI. Pre-fix it interpolated the
    raw path, so SQLite parsed the FIRST ``?`` in ``data?evil.db`` as the URI query
    delimiter and silently opened a different, empty file — ``was_sent`` then
    answered ``False`` for an already-claimed slot ⇒ a duplicate briefing. After the
    fix the path is percent-encoded, so the ``?`` is escaped (``%3F``) and reads and
    writes resolve to the SAME file.

    This test writes a claim via the write path (``claim_slot``) and asserts the
    read-only path (``was_sent``) sees it, using a db_path that contains a ``?``. It
    FAILS against pre-fix store.py (``was_sent`` reads an empty DB ⇒ False) and
    PASSES once the URI is percent-encoded.
    """
    db_path = str(tmp_path / "data?evil.db")

    init_db(db_path)
    # Write via the plain (immune) write path.
    assert claim_slot(db_path, "NYC", "09:00", "2026-06-19") is True
    # Read via the read-only URI branch — must see the row the write just wrote.
    assert was_sent(db_path, "NYC", "09:00", "2026-06-19") is True

    # And a ``#`` (URI fragment delimiter) is handled the same way.
    db_hash = str(tmp_path / "data#frag.db")
    init_db(db_hash)
    assert claim_slot(db_hash, "NYC", "08:00", "2026-06-20") is True
    assert was_sent(db_hash, "NYC", "08:00", "2026-06-20") is True
