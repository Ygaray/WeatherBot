"""Shared pytest fixtures: a tmp SQLite path and a recorded-fixture loader."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture(autouse=True)
def _redirect_pid_file(tmp_path: Path, monkeypatch):
    """Redirect the daemon's PID file off the host ``/run`` for every test.

    Phase 9 (Plan 05) makes ``run_daemon`` write a PID file atomically at startup via
    ``weatherbot.ops.pidfile.PID_FILE`` (default ``/run/weatherbot.pid``), which is not
    writable in the test/CI sandbox. This autouse fixture points the module-level
    ``daemon.PID_FILE`` at a per-test tmp path so the startup write + the finally
    unlink both succeed without touching the real host runtime dir. Tests that assert
    on the PID file read this same redirected path.
    """
    pid_file = tmp_path / "weatherbot.pid"
    # Patch where run_daemon resolves the name (the daemon module's module-level
    # binding); pidfile.PID_FILE itself stays the production default.
    import weatherbot.scheduler.daemon as _daemon_mod

    monkeypatch.setattr(_daemon_mod, "PID_FILE", pid_file, raising=False)
    return pid_file


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


# --------------------------------------------------------------------------- #
# Phase 11 inbound-bot harness (Plan 11-01 Wave-0).
#
# ``fake_discord_message`` is the gateway-free message factory the bot tests feed
# straight into ``on_message`` (RESEARCH "How to test a discord.py handler WITHOUT
# a live gateway"). It is a pure builder: NO discord import, NO network, NO gateway
# — just a MagicMock shaped like a discord.py Message so each test can drive the
# guard ladder (author.bot / author.id / content) and assert on an AsyncMock
# ``channel.send``. ``channel.typing()`` returns an async-context-manager mock so
# the ``async with message.channel.typing():`` indicator (D-08) works under await.
# --------------------------------------------------------------------------- #


def _make_fake_discord_message(
    *,
    author_bot: bool = False,
    author_id: int = 12345,
    content: str = "!weather home",
):
    """Build a gateway-free stand-in for a discord.py ``Message`` (Plan 11-01).

    Returns a ``MagicMock`` exposing exactly the attributes the bot's ``on_message``
    guard ladder + reply path read: ``author.bot`` (webhook/self guard, CMD-07),
    ``author.id`` (operator guard, CMD-07), ``content`` (the raw command text), and
    ``channel`` whose ``.send`` is an ``AsyncMock`` (the awaited reply, CMD-02) and
    whose ``.typing()`` returns an async-context-manager mock (the D-08 typing
    indicator). The factory is PURE — no discord import, no network — so the tests
    stay collectable even before discord.py is installed (T-11-01 deferred-import
    discipline applies to the production module, not this stand-in).
    """
    message = MagicMock(name="discord.Message")
    message.author.bot = author_bot
    message.author.id = author_id
    message.content = content

    # channel.send is the awaited reply seam (CMD-02): an AsyncMock so the test can
    # assert it was/was-not awaited and inspect the embed=/text it received.
    message.channel.send = AsyncMock(name="channel.send")

    # channel.typing() is used as `async with channel.typing():` (D-08). Build an
    # object whose __aenter__/__aexit__ are AsyncMocks; channel.typing() returns it.
    typing_cm = MagicMock(name="typing-context-manager")
    typing_cm.__aenter__ = AsyncMock(return_value=None)
    typing_cm.__aexit__ = AsyncMock(return_value=False)
    message.channel.typing = MagicMock(return_value=typing_cm)

    return message


@pytest.fixture
def fake_discord_message():
    """Return the gateway-free message factory (call it with author_bot/id/content)."""
    return _make_fake_discord_message


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
