"""Shared pytest fixtures: a tmp SQLite path and a recorded-fixture loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    """Read and parse a recorded OpenWeather JSON fixture by file name."""
    path = FIXTURE_DIR / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def load_fixture():
    """Return the recorded-fixture loader (call it with a fixture file name)."""
    return _load_fixture


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a path to a fresh (not-yet-created) SQLite file under tmp_path.

    The store layer (Plan 02) creates the schema on first connect; tests get an
    isolated database per test with no cross-test state.
    """
    return tmp_path / "weatherbot.db"


# --------------------------------------------------------------------------- #
# Phase 9 reload-engine harness (Plan 09-01 Wave-0).
#
# These two helpers let the exactly-once reload tests seed an already-sent slot
# and stand up a holder + scheduler with no wall-clock waits. They are written
# against the SHIPPED store/holder primitives (claim_slot / ConfigHolder), so
# they work today — only the not-yet-built RELOAD ENTRYPOINT (referenced via a
# per-test lazy import inside test_reload.py) is RED. The seeder writes a real
# ``sent_log`` row through the production ``claim_slot`` path, so the exactly-once
# assertions exercise the real idempotency key, never a mock that always passes
# (T-09-01: no green-but-hollow scaffold).
# --------------------------------------------------------------------------- #


def _seed_sent_row(
    db_path: Path,
    location_id: str,
    send_time: str,
    local_date: str,
) -> None:
    """Mark ``(location_id, send_time, local_date)`` already-sent via ``claim_slot``.

    Uses the SHIPPED atomic ``claim_slot`` (store.py) so the seeded row is
    byte-identical to a row a real fire would have written — the exactly-once
    reload tests then assert that a SECOND claim for the same key LOSES. The
    ``location_id`` is passed into the store's ``location_name`` parameter
    verbatim (D-01: the sent-log key value moves from name → id; with id
    defaulting to the raw name the stored value is unchanged for un-id'd configs).
    """
    from weatherbot.weather.store import claim_slot

    won = claim_slot(db_path, location_id, send_time, local_date)
    assert won is True, (
        f"seed_sent_row expected a fresh win for "
        f"({location_id!r}, {send_time!r}, {local_date!r}) — the slot was already claimed"
    )


@pytest.fixture
def seed_sent_row():
    """Return the sent-log seeder (call it with db_path, id, send_time, local_date)."""
    return _seed_sent_row


@pytest.fixture
def holder_scheduler(tmp_db):
    """Build a (ConfigHolder, BackgroundScheduler, db_path) harness for reload tests.

    Reuses the SHIPPED ``ConfigHolder`` swap seam (Phase 8) and a real, NOT-started
    ``BackgroundScheduler`` (the reload tests assert on ``get_jobs()`` without ever
    starting it, so there are no threads to tear down). The factory takes a
    ``Config`` and returns the harness so each test builds its own first config.
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    from weatherbot.config.holder import ConfigHolder

    created: list[BackgroundScheduler] = []

    def _make(config):
        holder = ConfigHolder(config)
        scheduler = BackgroundScheduler()
        created.append(scheduler)
        return holder, scheduler, tmp_db

    yield _make

    # Defensive teardown: shut down any scheduler a test happened to start.
    for scheduler in created:
        if getattr(scheduler, "running", False):
            scheduler.shutdown(wait=False)
