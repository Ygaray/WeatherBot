"""Unit tests for the read-only DaemonState accessor + status handler (Plan 12-02).

Covers CMD-12: ``status`` reports next-scheduled-send per location, alive+uptime,
bot/UV-monitor liveness, and the last-briefing result — all read-only through a
:class:`~weatherbot.interactive.state.DaemonState` accessor (D-02: reports, never
mutates).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.config.holder import ConfigHolder
from weatherbot.config.models import Schedule
from weatherbot.interactive.commands import CommandReply, status as status_cmd
from weatherbot.interactive.state import DaemonState
from weatherbot.weather.store import read_heartbeat, stamp_success


# --------------------------------------------------------------------------- #
# Fake scheduler mirroring the APScheduler introspection status reads.
# --------------------------------------------------------------------------- #


class _FakeTrigger:
    def __init__(self, fire_time: datetime) -> None:
        self._fire_time = fire_time

    def get_next_fire_time(self, previous, now):
        return self._fire_time


class _FakeJob:
    def __init__(self, job_id: str, next_run_time=None, trigger_fire=None) -> None:
        self.id = job_id
        # A running scheduler exposes next_run_time; a pending one does not.
        if next_run_time is not None:
            self.next_run_time = next_run_time
        self.trigger = _FakeTrigger(trigger_fire) if trigger_fire else None


class _FakeScheduler:
    def __init__(self, jobs: list[_FakeJob]) -> None:
        self._jobs = jobs

    def get_jobs(self):
        return list(self._jobs)


def _config(slot_enabled: bool = True) -> Config:
    return Config(
        locations=[
            Location(
                name="Home",
                lat=40.0,
                lon=-74.0,
                timezone="America/New_York",
                schedule=[
                    Schedule(time="09:00", days="weekdays", enabled=slot_enabled)
                ],
            )
        ],
        template="briefing-sectioned.txt",
        webhook=WebhookIdentity(),
    )


def _job_id(location: Location, slot: Schedule) -> str:
    return f"{location.name}|{slot.time}|{slot.days}"


# --------------------------------------------------------------------------- #
# DaemonState: next_fires + uptime (read-only)
# --------------------------------------------------------------------------- #


def test_next_fires_uses_running_next_run_time(tmp_db):
    cfg = _config()
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    fire = datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)
    sched = _FakeScheduler([_FakeJob(_job_id(loc, slot), next_run_time=fire)])

    state = DaemonState(
        scheduler=sched,
        holder=ConfigHolder(cfg),
        db_path=tmp_db,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        bot_alive=lambda: True,
    )

    fires = state.next_fires()
    assert "Home" in fires
    # D-07: humanized local 24-hour HH:MM (raw ISO date/offset dropped).
    assert fires["Home"] == "09:00"


def test_next_fires_falls_back_to_trigger(tmp_db):
    # A pending (no next_run_time) job mirrors _announce_schedule's trigger fallback.
    cfg = _config()
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    fire = datetime(2026, 6, 21, 9, 0, tzinfo=timezone.utc)
    sched = _FakeScheduler([_FakeJob(_job_id(loc, slot), trigger_fire=fire)])

    state = DaemonState(
        scheduler=sched,
        holder=ConfigHolder(cfg),
        db_path=tmp_db,
        started_at=datetime.now(timezone.utc),
        bot_alive=lambda: True,
    )

    fires = state.next_fires()
    # D-07: humanized local 24-hour HH:MM (raw ISO date/offset dropped).
    assert fires["Home"] == "09:00"


def test_uptime_is_positive(tmp_db):
    cfg = _config()
    state = DaemonState(
        scheduler=_FakeScheduler([]),
        holder=ConfigHolder(cfg),
        db_path=tmp_db,
        started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        bot_alive=lambda: True,
    )
    up = state.uptime()
    assert isinstance(up, timedelta)
    assert up.total_seconds() > 0


# --------------------------------------------------------------------------- #
# status handler (CMD-12)
# --------------------------------------------------------------------------- #


def _state(
    tmp_db,
    cfg,
    *,
    bot_alive=True,
    monitor_alive=None,
    started_delta=timedelta(minutes=30),
):
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    fire = datetime(2026, 6, 20, 9, 0, tzinfo=timezone.utc)
    sched = _FakeScheduler([_FakeJob(_job_id(loc, slot), next_run_time=fire)])
    return DaemonState(
        scheduler=sched,
        holder=ConfigHolder(cfg),
        db_path=tmp_db,
        started_at=datetime.now(timezone.utc) - started_delta,
        bot_alive=lambda: bot_alive,
        monitor_alive=(None if monitor_alive is None else (lambda: monitor_alive)),
    )


def test_status_reports_last_briefing_when_stamped(tmp_db):
    stamp_success(tmp_db)
    assert read_heartbeat(tmp_db)["last_success_utc"] is not None

    reply = status_cmd.status(_state(tmp_db, _config()))
    assert isinstance(reply, CommandReply)
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    assert "none yet" not in body.lower()


def test_status_reports_none_yet_when_unstamped(tmp_db):
    # Fresh db: heartbeat row seeded but never stamped (last_success_utc is None).
    reply = status_cmd.status(_state(tmp_db, _config()))
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    assert "none yet" in body.lower()


def test_status_reports_bot_alive_state(tmp_db):
    alive = status_cmd.status(_state(tmp_db, _config(), bot_alive=True))
    dead = status_cmd.status(_state(tmp_db, _config(), bot_alive=False))
    alive_body = "".join(f"{n}{v}" for n, v in alive.lines) + (alive.text or "")
    dead_body = "".join(f"{n}{v}" for n, v in dead.lines) + (dead.text or "")
    assert "alive" in alive_body.lower() or "running" in alive_body.lower()
    assert "down" in dead_body.lower() or "not" in dead_body.lower()


def test_status_reports_uv_monitor_not_running(tmp_db):
    # No monitor_alive callable supplied (bot without a scheduler) → "not running".
    reply = status_cmd.status(_state(tmp_db, _config()))
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    assert "not running" in body.lower()


def test_status_reports_uv_monitor_alive_and_down_from_callable(tmp_db):
    # When the daemon supplies monitor_alive (integration WARNING fix), status
    # reflects the live monitor state instead of permanently "not running".
    alive = status_cmd.status(_state(tmp_db, _config(), monitor_alive=True))
    down = status_cmd.status(_state(tmp_db, _config(), monitor_alive=False))
    alive_body = "".join(f"{n}{v}" for n, v in alive.lines).lower()
    down_body = "".join(f"{n}{v}" for n, v in down.lines).lower()
    assert "uv monitor" in alive_body and "alive" in alive_body
    assert "uv monitor" in down_body and "down" in down_body
    assert "not running" not in alive_body


def test_status_reports_next_send_per_location(tmp_db):
    reply = status_cmd.status(_state(tmp_db, _config()))
    body = (reply.text or "") + "".join(f"{n}{v}" for n, v in reply.lines)
    assert "Home" in body
