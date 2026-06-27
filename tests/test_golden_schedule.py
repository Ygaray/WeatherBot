"""Byte-exact schedule-plan golden — (job_id, str(trigger), frozen next_run_time) (Plan 21-03).

The registered-job *plan* is the byte-identical oracle the scheduler-seam extraction (Phase
23) re-runs: every enabled briefing/forecast slot becomes one APScheduler job whose ``id``
(``{name}|{time}|{days}`` / ``{name}|fc|{kind}|{variant}|{time}|{days}``) and whose
``str(CronTrigger)`` ARE the schedule contract. An intent-test asserts "two jobs exist"; THIS
pins the exact id + trigger spec of each, so a drifted cron field, a renamed job id, or a
dropped/added slot surfaces as a real diff.

Primary byte (D-11): ``str(job.trigger)`` — the ``cron[day_of_week=…, hour=…, minute=…]``
spec, deterministic regardless of whether the scheduler is started (A7-confirmed). The plan is
read off a NEVER-started ``BackgroundScheduler`` (Pitfall 3 — no threads, no teardown), via the
shared ``schedule_plan_golden`` serializer (sorts by ``job_id`` → explicit ORDER, not
registration-insertion luck, D-11).

Secondary (D-11 — freeze, don't scrub): a pending scheduler's Job has NO ``next_run_time``, so
``schedule_plan_golden`` reports it ``None``. This test ADDITIONALLY pins a deterministic frozen
``next_run_time`` per job — computed via the SAME ``state._next_fire`` fallback
(``CronTrigger.get_next_fire_time(None, datetime.now(tz))``) the live ``DaemonState.next_fires``
uses — under ``time_machine.travel(FROZEN)`` so it is a stable literal keyed to each job's own
IANA tz.

Purely additive (no ``weatherbot/`` change): drives the shipped ``daemon._register_jobs`` on a
real ``ConfigHolder`` + a tmp db path. No network, no secret.
"""

from __future__ import annotations

import threading
from zoneinfo import ZoneInfo

import time_machine

from tests.conftest import FROZEN, schedule_plan_golden
from weatherbot.config.holder import ConfigHolder
from weatherbot.config.models import Config, ForecastSchedule, Location, Schedule
from weatherbot.interactive.state import _next_fire
from weatherbot.scheduler import daemon as daemon_mod

# A two-location config exercising the full job-enumeration surface: weekday + weekend
# briefing slots, a DISABLED slot (must produce NO job — the SCHD-02 toggle), a forecast
# slot (the namespaced ``|fc|`` id), and a second location in a DIFFERENT tz (so the
# per-place wall-clock trigger + the tz-keyed next-fire are both pinned). Stable IANA tzs
# so every clock-derived value is deterministic under FROZEN.
_CONFIG = Config(
    locations=[
        Location(
            name="Home",
            lat=40.7128,
            lon=-74.006,
            timezone="America/New_York",
            schedule=[
                Schedule(time="09:00", days="weekdays", enabled=True),
                Schedule(time="08:00", days="weekends", enabled=True),
                # A disabled slot must NOT register a job (SCHD-02) — its absence
                # from the golden is the proof the toggle is honored.
                Schedule(time="22:00", days="daily", enabled=False),
            ],
            forecast=[
                ForecastSchedule(
                    kind="weekday",
                    variant="detailed",
                    time="07:00",
                    days="weekdays",
                    enabled=True,
                )
            ],
        ),
        Location(
            name="Travel",
            lat=34.05,
            lon=-118.24,
            timezone="America/Los_Angeles",
            schedule=[Schedule(time="07:30", days="daily", enabled=True)],
        ),
    ],
    template="briefing-sectioned.txt",
)

# Map each job id → the LOCATION tz it was registered against, so the frozen next-fire is
# computed in the same tz ``DaemonState.next_fires`` would use (every job id begins with the
# location name; ``|`` never appears in a location name).
_TZ_BY_LOCATION = {loc.name: loc.timezone for loc in _CONFIG.locations}


def _build_pending_scheduler():
    """Register jobs on a NEVER-started BackgroundScheduler (Pitfall 3 — no teardown)."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    daemon_mod._register_jobs(
        scheduler,
        ConfigHolder(_CONFIG),
        db_path="/tmp/golden-schedule.db",  # never opened — registration only
        settings=None,
        stop_event=threading.Event(),
    )
    return scheduler


def _frozen_plan(scheduler):
    """The shared plan (str(trigger) primary) + a deterministic frozen next_run_time.

    Wraps :func:`schedule_plan_golden` (the byte-exact ``str(trigger)`` primary, sorted by
    job_id) and fills each row's ``next_run_time`` via the ``state._next_fire`` fallback in the
    job's own tz — under the frozen clock so the secondary is a stable literal (D-11).
    """
    base = schedule_plan_golden(scheduler)
    jobs_by_id = {job.id: job for job in scheduler.get_jobs()}
    for row in base:
        location = row["job_id"].split("|", 1)[0]
        tz = ZoneInfo(_TZ_BY_LOCATION[location])
        fire = _next_fire(jobs_by_id[row["job_id"]], tz)
        row["next_run_time"] = fire.isoformat() if fire else None
    return base


def test_schedule_plan_golden(json_snapshot):
    """The full registered-job plan (id + trigger + frozen next-fire) is byte-identical.

    Pins, sorted by job_id (D-11): the two enabled Home briefing slots, the Home forecast
    slot (namespaced ``|fc|`` id), and the Travel daily slot — each with its exact
    ``str(CronTrigger)`` and a frozen ``next_run_time`` in its location tz. The disabled
    Home 22:00 slot is ABSENT (SCHD-02 toggle proof).
    """
    with time_machine.travel(FROZEN, tick=False):
        scheduler = _build_pending_scheduler()
        plan = _frozen_plan(scheduler)
    assert plan == json_snapshot
