"""Byte-exact persisted-DB-row goldens — weather_onecall / sent_log / alerts (Plan 21-03).

The rows a briefing WRITES are observable bytes that intent-tests miss: an intent-test
asserts "a row was inserted"; THIS pins the exact column values, so a changed write shape, a
dropped column, or a units/ordering drift surfaces as a real diff. These are the byte-identical
oracle the lifecycle/registry extractions (Phases 25-26) re-run against the same recorded
fixtures.

Determinism (D-11 — freeze, don't scrub the meaningful):
  * ORDER: every read path uses an explicit ``ORDER BY`` so query-order nondeterminism is
    killed at the source — never a sort-scrub (an ordering bug stays visible).
  * SCRUB: ONLY the autoincrement rowid ``id`` is dropped (it is meaningless identity, not a
    byte contract) — it is simply never SELECTed.
  * FREEZE: the clock-derived fields (``target_local_date``, ``sent_at_utc``,
    ``created_at_utc``) are pinned by running every write under ``time_machine.travel(FROZEN)``
    so they are STABLE literals (the FROZEN local date / epoch), not blanket-scrubbed.

Secret hygiene (V7): ``store.py`` persists only the OpenWeather *response* payload — the
request URL carrying the ``appid`` is never stored — so no key/URL appears in any ``raw_json``.

Coverage-scope note: ``weatherbot/weather`` is OUT of the branch-coverage move-path scope
(D-07), but its persisted rows ARE snapshotted here — that is intentional (the rows move with
the lifecycle/registry seams even though the store stays app-side).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import time_machine

from tests.conftest import FROZEN, onecall_rows_golden
from weatherbot.config.models import Location
from weatherbot.weather.models import Forecast
from weatherbot.weather.store import claim_slot, record_alert, persist

_FIXTURE_DIR = Path(__file__).parent / "fixtures"

# A stable IANA tz so ``target_local_date`` / the epoch stamps are deterministic under FROZEN.
_LOCATION = Location(
    name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York"
)


def _load(name: str) -> dict:
    """Read a recorded OpenWeather fixture by file name (offline, no network)."""
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _forecast(imperial: str, metric: str) -> Forecast:
    """Build a Forecast from a recorded fixture pair (gateway-free, store-free)."""
    return Forecast.from_payloads(
        _LOCATION, _load(imperial), _load(metric), now_utc=FROZEN
    )


def _sent_log_rows_golden(db_path: Path) -> list[dict]:
    """Read ``sent_log`` deterministically (explicit ORDER BY, rowid scrubbed, clock frozen).

    Selects ONLY the byte-contract columns
    (``location_name, send_time, local_date, sent_at_utc``) with an explicit
    ``ORDER BY location_name, send_time, local_date`` — the autoincrement ``id`` is never
    selected (scrubbed). ``sent_at_utc`` is a frozen-clock epoch (the caller writes under
    ``time_machine.travel(FROZEN)``), so it is the stable FROZEN-epoch literal, not scrubbed.
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT location_name, send_time, local_date, sent_at_utc "
            "FROM sent_log ORDER BY location_name, send_time, local_date"
        ).fetchall()
    return [
        {
            "location_name": r[0],
            "send_time": r[1],
            "local_date": r[2],
            "sent_at_utc": r[3],
        }
        for r in rows
    ]


def _alerts_rows_golden(db_path: Path) -> list[dict]:
    """Read ``alerts`` deterministically (explicit ORDER BY, rowid scrubbed, clock frozen).

    Selects ONLY the byte-contract columns
    (``location_name, slot_time, local_date, reason, severity, created_at_utc,
    resolved_at_utc``) with an explicit ``ORDER BY location_name, slot_time, local_date`` — the
    autoincrement ``id`` is never selected (scrubbed). ``created_at_utc`` is a frozen-clock
    epoch (the caller writes under FROZEN); ``resolved_at_utc`` is NULL for a fresh alert.
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT location_name, slot_time, local_date, reason, severity, "
            "created_at_utc, resolved_at_utc "
            "FROM alerts ORDER BY location_name, slot_time, local_date"
        ).fetchall()
    return [
        {
            "location_name": r[0],
            "slot_time": r[1],
            "local_date": r[2],
            "reason": r[3],
            "severity": r[4],
            "created_at_utc": r[5],
            "resolved_at_utc": r[6],
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# weather_onecall — persist writes TWO rows (imperial + metric) per fetch. The
# conftest onecall_rows_golden reader pins both with ORDER BY units, location_name.
# --------------------------------------------------------------------------- #


def test_weather_onecall_rows_golden(tmp_db, json_snapshot):
    """The two persisted ``weather_onecall`` rows (imperial+metric) are byte-identical.

    Pins ``location_name, lat, lon, target_local_date (frozen), units, raw_json`` for both
    unit variants — ``id``/``fetched_at_utc`` scrubbed, ``raw_json`` parsed back so a payload
    drift diffs structurally. V7: no ``appid``/request-URL is ever in ``raw_json`` (the store
    persists only the response payload).
    """
    forecast = _forecast("onecall_imperial_clear.json", "onecall_metric_clear.json")
    with time_machine.travel(FROZEN, tick=False):
        persist(tmp_db, _LOCATION, forecast)
        rows = onecall_rows_golden(tmp_db)
    assert rows == json_snapshot


def test_sent_log_rows_golden(tmp_db, json_snapshot):
    """A won ``claim_slot`` writes exactly one ``sent_log`` row — pinned byte-exact.

    ``send_time``/``local_date`` are the slot identity; ``sent_at_utc`` is the FROZEN-epoch
    literal (the claim runs under ``time_machine.travel(FROZEN)``). The rowid is scrubbed.
    """
    with time_machine.travel(FROZEN, tick=False):
        won = claim_slot(tmp_db, "New York", "09:00", "2026-06-20")
        rows = _sent_log_rows_golden(tmp_db)
    assert won is True  # the fresh claim wins (inline pin)
    assert rows == json_snapshot


def test_alerts_rows_golden(tmp_db, json_snapshot):
    """A ``record_alert`` writes exactly one ``alerts`` row — pinned byte-exact.

    Pins reason/severity + the slot identity; ``created_at_utc`` is the FROZEN-epoch literal,
    ``resolved_at_utc`` is NULL (a fresh, unresolved alert). The rowid is scrubbed. Rows carry
    NO key/URL (T-04-01).
    """
    with time_machine.travel(FROZEN, tick=False):
        wrote = record_alert(
            tmp_db, "New York", "09:00", "2026-06-20", "transient_exhausted"
        )
        rows = _alerts_rows_golden(tmp_db)
    assert wrote is True  # the first alert for this slot/day wins (inline pin)
    assert rows == json_snapshot
