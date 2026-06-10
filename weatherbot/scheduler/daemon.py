"""The daemon spine: the always-on foreground lifecycle + the per-fire callback.

This is Phase 3's defining new capability — the first long-running process. It
turns the validated building blocks (the ``Schedule`` model + ``sent_log`` from
Plan 01, the ``ScheduleContext`` from Plan 02, the ``plan_catchup`` planner from
this plan) into a working scheduler:

- ``run_daemon`` registers one APScheduler ``CronTrigger`` job per ENABLED
  ``(location, schedule entry)`` at the LOCATION's own IANA timezone (so a Home
  weekday slot and a Weekend slot in another zone each fire at their own local
  wall-clock time, SCHD-04/SCHD-05), announces the schedule (D-10), runs the
  90-minute startup catch-up scan (Pattern 3 / SCHD-06), starts the scheduler,
  then blocks in the foreground until SIGTERM / Ctrl-C and shuts down cleanly
  (D-09). It does NOT self-daemonize — systemd keeps the process alive (Phase 5).

- ``fire_slot`` is the SAME callback used by both the live cron job and the
  catch-up scan: it checks ``was_sent`` BEFORE delivering (idempotency, D-07),
  threads a ``ScheduleContext`` through ``send_now`` (so a recovered late send
  renders its intended-vs-actual note), and calls ``record_sent`` ONLY after the
  channel confirms ``result.ok`` (mark-after-success — a failed send leaves the
  slot unsent for re-fire; retry-then-alert is Phase 4). Its whole body is wrapped
  in a try/except so one bad slot cannot crash the scheduler thread (minimal
  isolation now; Phase 4 hardens it, Anti-Pattern: per-job isolation).

Recovery across a restart is OWNED by the sent-log + catch-up scan, NOT by
APScheduler misfire/coalesce (the memory jobstore loses all state on exit), so
every job is registered with ``misfire_grace_time=None``.

Logging is OUTCOME-ONLY (T-04-01): ``location``/``time``/``days``/
``next_run_time``/``delivered`` — never the API key or the webhook URL, which
stay inside the injected client/channel.
"""

from __future__ import annotations

import signal
import threading
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from weatherbot.scheduler.catchup import plan_catchup
from weatherbot.scheduler.context import ScheduleContext
from weatherbot.weather.store import record_sent, was_sent

if TYPE_CHECKING:
    from weatherbot.channels.base import Channel, DeliveryResult
    from weatherbot.config.models import Config, Location, Schedule
    from weatherbot.config.settings import Settings

_log = structlog.get_logger(__name__)


def fire_slot(
    location: Location,
    slot: Schedule,
    *,
    config: Config,
    db_path,
    settings: Settings | None = None,
    client=None,
    channel: Channel | None = None,
    scheduled_dt=None,
    late: bool = False,
) -> DeliveryResult | None:
    """Deliver one briefing for ``(location, slot)`` — check-before-fire, mark-after-success.

    The single callback for BOTH the live cron job and the catch-up scan. It:

    1. computes the ``local_date`` dedup-key component (from ``scheduled_dt`` when
       present, else "now" in the location's tz);
    2. returns ``None`` early if ``was_sent`` already recorded this slot (D-06 —
       restart-replay / DST fall-back safety);
    3. builds a :class:`ScheduleContext` and calls ``send_now`` (which fetches live
       weather, so a recovered late send carries CURRENT data, D-05);
    4. calls ``record_sent`` ONLY when ``result.ok`` (mark-after-success, D-07 — a
       failed send stays unsent for re-fire; retry-then-alert is Phase 4).

    The whole body is wrapped in ``try/except`` that logs and returns ``None`` so
    one bad slot cannot crash the scheduler thread (minimal isolation, T-03-07).
    Returns the :class:`DeliveryResult` on a fire, or ``None`` on skip/failure.
    """
    try:
        tz = ZoneInfo(location.timezone)
        if scheduled_dt is not None:
            local_date = scheduled_dt.astimezone(tz).date().isoformat()
        else:
            from datetime import datetime

            local_date = datetime.now(tz).date().isoformat()

        # Check-before-fire: never re-deliver an already-recorded slot (D-07).
        if was_sent(db_path, location.name, slot.time, local_date):
            _log.info(
                "slot skipped (already sent)",
                location=location.name,
                time=slot.time,
                local_date=local_date,
            )
            return None

        # Import send_now lazily: this module is dragged in (via the scheduler
        # package barrel) while ``weatherbot.cli`` is still initializing, so a
        # top-level ``from weatherbot.cli import send_now`` would be a cycle.
        from weatherbot.cli import send_now

        ctx = ScheduleContext(scheduled_dt=scheduled_dt, tz=tz, late=late)
        result = send_now(
            location.name,
            config=config,
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            schedule_ctx=ctx,
        )

        # Mark-after-success ONLY (D-07): a failed send leaves the slot unsent.
        if result.ok:
            record_sent(db_path, location.name, slot.time, local_date)

        _log.info(
            "slot fired",
            location=location.name,
            time=slot.time,
            late=late,
            delivered=result.ok,
        )
        return result
    except Exception as exc:  # noqa: BLE001 — one bad slot must not kill the thread
        _log.error(
            "slot fire failed",
            location=location.name,
            time=slot.time,
            error=str(exc),
        )
        return None


def _register_jobs(
    scheduler: BackgroundScheduler,
    config: Config,
    *,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
) -> None:
    """Register one CronTrigger job per ENABLED slot at the location's own tz (Pattern 1).

    Disabled slots produce NO job (SCHD-02 toggle). Each trigger is pinned to the
    LOCATION's IANA ``timezone`` so it fires at that place's local wall-clock time
    (SCHD-04). ``misfire_grace_time=None`` because cross-restart recovery is owned
    by the sent-log + catch-up scan, not APScheduler (Anti-Pattern); ``coalesce``
    is a harmless backstop. The job ``id`` keys on ``name|time|days`` (D-06: editing
    a time = a new slot).
    """
    for location in config.locations:
        for slot in location.schedule:
            if not slot.enabled:
                continue
            hh, mm = slot.parsed_time()
            scheduler.add_job(
                fire_slot,
                trigger=CronTrigger(
                    hour=hh,
                    minute=mm,
                    day_of_week=slot.day_of_week,
                    timezone=location.timezone,
                ),
                kwargs={
                    "config": config,
                    "db_path": db_path,
                    "settings": settings,
                    "client": client,
                    "channel": channel,
                },
                args=[location, slot],
                id=f"{location.name}|{slot.time}|{slot.days}",
                misfire_grace_time=None,
                coalesce=True,
            )


def _announce_schedule(scheduler: BackgroundScheduler, config: Config) -> None:
    """Log every registered slot + its computed next_run_time (D-10).

    Outcome-only logging: ``location``/``time``/``days``/``next_run_time`` — never
    a secret. Announce runs BEFORE ``scheduler.start()`` (so the log reads cleanly),
    and a not-yet-started APScheduler job has no ``next_run_time`` attribute yet —
    so the next fire is computed straight from the job's CronTrigger, which is
    tz-aware in the location's own zone (the proof the per-location wall-clock
    firing works).
    """
    from datetime import datetime

    jobs = scheduler.get_jobs()
    by_id = {job.id: job for job in jobs}
    for location in config.locations:
        tz = ZoneInfo(location.timezone)
        for slot in location.schedule:
            if not slot.enabled:
                continue
            job = by_id.get(f"{location.name}|{slot.time}|{slot.days}")
            next_run = None
            if job is not None:
                # Prefer a running scheduler's computed value; else derive it from
                # the trigger (pending jobs have no next_run_time attribute yet).
                next_run = getattr(job, "next_run_time", None)
                if next_run is None:
                    next_run = job.trigger.get_next_fire_time(None, datetime.now(tz))
            _log.info(
                "scheduled slot",
                location=location.name,
                time=slot.time,
                days=slot.days,
                next_run_time=str(next_run),
            )


def _run_catchup(
    config: Config,
    *,
    db_path,
    settings: Settings | None,
    client=None,
    channel: Channel | None = None,
) -> None:
    """Run the 90-minute startup catch-up scan, firing each missed slot once (Pattern 3).

    Re-derives what should have fired TODAY within the grace window and isn't in
    the sent-log (SCHD-06), then fires each via the SAME ``fire_slot`` callback
    with ``late=True`` so the recovered send renders its intended-vs-actual note.
    """
    missed = plan_catchup(
        config,
        lambda name, time, date: was_sent(db_path, name, time, date),
    )
    for ms in missed:
        fire_slot(
            ms.location,
            ms.slot,
            config=config,
            db_path=db_path,
            settings=settings,
            client=client,
            channel=channel,
            scheduled_dt=ms.scheduled_dt,
            late=True,
        )


def run_daemon(
    config: Config,
    settings: Settings | None,
    db_path,
    *,
    client=None,
    channel: Channel | None = None,
) -> int:
    """Run the always-on scheduler in the FOREGROUND until SIGTERM / Ctrl-C (D-09).

    Order (so the log reads cleanly): register jobs → announce the schedule →
    run the catch-up scan → ``scheduler.start()``. Then block on a
    ``threading.Event`` with a SIGTERM handler + a ``KeyboardInterrupt`` catch,
    and ``scheduler.shutdown(wait=False)`` on exit. Returns 0 on a clean shutdown.
    Does NOT self-daemonize (systemd owns process liveness, Phase 5).
    """
    scheduler = BackgroundScheduler()
    _register_jobs(
        scheduler,
        config,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
    )
    _announce_schedule(scheduler, config)
    _run_catchup(
        config,
        db_path=db_path,
        settings=settings,
        client=client,
        channel=channel,
    )
    scheduler.start()
    _log.info("daemon started", jobs=len(scheduler.get_jobs()))

    stop = threading.Event()

    def _handle(signum, frame):  # noqa: ANN001 — signal handler signature
        stop.set()

    signal.signal(signal.SIGTERM, _handle)
    try:
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.shutdown(wait=False)
        _log.info("daemon stopped")
    return 0
