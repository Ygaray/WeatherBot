"""The read-only ``DaemonState`` accessor for ``status`` (Plan 12-02, CMD-12 / D-02).

``status`` needs four things the bot layer was never given (Pitfall 2): the live
scheduler (next scheduled send per location), the daemon ``db_path`` (last-briefing
heartbeat), the process ``started_at`` (uptime), and a bot-liveness callable.
:class:`DaemonState` bundles them as a frozen, READ-ONLY accessor threaded into the
command layer alongside the cache. It NEVER mutates the scheduler, config, or store
(D-02: "reports, never mutates") — there is no ``add_job``/``remove_job``,
no ``holder.replace``, and no store write anywhere in this module.

Phase 15's UV monitor gets a clean slot: ``monitor_alive`` defaults to ``None`` and
``status`` reports the monitor as "not running" until that callable is supplied (A4).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from weatherbot.config.holder import ConfigHolder


def _next_fire(job, tz: ZoneInfo) -> datetime | None:
    """Next fire time for a job — running value first, trigger fallback (read-only).

    Mirrors ``daemon._announce_schedule`` verbatim: a running scheduler exposes
    ``job.next_run_time``; a pending (not-yet-started) job has none, so the next
    fire is computed straight from the job's tz-aware ``CronTrigger``.
    """
    if job is None:
        return None
    next_run = getattr(job, "next_run_time", None)
    if next_run is None and getattr(job, "trigger", None) is not None:
        next_run = job.trigger.get_next_fire_time(None, datetime.now(tz))
    return next_run


@dataclass(frozen=True)
class DaemonState:
    """Read-only live-state accessor for ``status`` (D-02 — reports, never mutates).

    Holds the live ``scheduler``, the ``holder`` (read via ``current()`` for the
    location/slot list), the daemon ``db_path``, the process ``started_at`` (UTC),
    and a ``bot_alive`` callable. ``monitor_alive`` is the Phase-15 UV-monitor slot
    (``None`` → reported "not running"). Frozen: no setters, no scheduler mutation.
    """

    scheduler: object
    holder: ConfigHolder
    db_path: object
    started_at: datetime
    bot_alive: Callable[[], bool]
    monitor_alive: Callable[[], bool] | None = None

    def next_fires(self) -> dict[str, str]:
        """Per-location next scheduled send as an ISO string (read-only).

        Iterates the held config's enabled slots, looks the job up by the daemon's
        ``f"{name}|{time}|{days}"`` key, and computes the next fire via
        :func:`_next_fire` (the ``_announce_schedule`` logic). The EARLIEST upcoming
        fire across a location's slots is reported for that location.
        """
        config = self.holder.current()
        jobs = self.scheduler.get_jobs()
        by_id = {job.id: job for job in jobs}

        fires: dict[str, str] = {}
        for location in config.locations:
            tz = ZoneInfo(location.timezone)
            earliest: datetime | None = None
            for slot in location.schedule:
                if not slot.enabled:
                    continue
                job = by_id.get(f"{location.name}|{slot.time}|{slot.days}")
                nxt = _next_fire(job, tz)
                if nxt is None:
                    continue
                if earliest is None or nxt < earliest:
                    earliest = nxt
            if earliest is not None:
                fires[location.name] = earliest.isoformat()
        return fires

    def uptime(self) -> timedelta:
        """How long the daemon has been running (now − ``started_at``)."""
        return datetime.now(timezone.utc) - self.started_at
