"""The pure missed-send planner (D-04/D-06/D-10) — recovery owned by the sent-log.

``plan_catchup`` is a side-effect-free function that, given the validated
:class:`~weatherbot.config.models.Config`, a ``was_sent`` reader, and an injected
``now_utc``, returns the slots whose local scheduled time has already passed TODAY
within the 90-minute grace window (D-04) and are not already in the sent-log
(D-06). It is the SCHD-06 recovery mechanism — APScheduler's misfire/coalesce is
deliberately NOT trusted across a restart (the memory jobstore loses all state on
exit), so this scan re-derives "what should have fired but didn't" at startup.

Purity is the testability backbone: ``now_utc`` and the ``was_sent`` reader are
injected (mirroring ``Forecast.from_payloads``), so the DST exactly-once and
catch-up-window tests need no wall-clock waits or global clock patching.

This module is intentionally APScheduler-free: recovery is the sent-log's job, not
the scheduler's. ``_fires_on`` is driven from the SAME normalized ``day_of_week``
string the live ``CronTrigger`` consumes (via ``Schedule.day_of_week`` →
``parse_days``), so the planner and the trigger can never disagree (Pitfall 3,
Monday-first ``date.weekday()`` Mon=0).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    from weatherbot.config.models import Config, Location, Schedule

# D-04: the catch-up grace window is HARDCODED, never read from config. A slot
# whose local scheduled time passed more than this ago is skipped + logged.
GRACE = timedelta(minutes=90)

# Monday-first weekday tokens → ``date.weekday()`` indices (Mon=0 .. Sun=6).
# Mirrors APScheduler's ``day_of_week`` ordering so the planner agrees with the
# live CronTrigger (Pitfall 3). The normalized strings come from ``parse_days``.
_WEEKDAY_INDEX = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}
# Ordered names for range expansion (``"mon-fri"`` → mon..fri).
_WEEKDAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class MissedSlot:
    """One slot the catch-up scan decided should be (re-)fired now.

    ``scheduled_dt`` is the slot's intended send instant TODAY, tz-aware in the
    location's own IANA zone (so a recovered send can render its intended-vs-actual
    note). ``local_date`` is the ``YYYY-MM-DD`` date component of the D-06
    ``(location, send_time, local_date)`` idempotency key.
    """

    location: Location
    slot: Schedule
    scheduled_dt: datetime
    local_date: str


def _weekday_set(day_of_week: str) -> set[int]:
    """Expand a normalized ``day_of_week`` string to a set of weekday indices.

    Handles the APScheduler grammar produced by ``parse_days``: comma lists
    (``"sat,sun"``) and inclusive ranges (``"mon-fri"``, ``"mon-sun"``), all
    Monday-first (Mon=0 .. Sun=6). Wraps-around ranges are not produced by
    ``parse_days`` so are not handled here.
    """
    indices: set[int] = set()
    for part in day_of_week.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_name, hi_name = (p.strip() for p in part.split("-", 1))
            lo, hi = _WEEKDAY_INDEX[lo_name], _WEEKDAY_INDEX[hi_name]
            indices.update(range(lo, hi + 1))
        else:
            indices.add(_WEEKDAY_INDEX[part])
    return indices


def _fires_on(slot: Schedule, now_local: datetime) -> bool:
    """Does ``slot`` fire on ``now_local``'s weekday?

    Driven from the slot's normalized ``day_of_week`` (the SAME string the
    CronTrigger receives) so the planner and the live trigger always agree
    (Pitfall 3). ``now_local.weekday()`` is Monday-first (Mon=0), matching
    ``_WEEKDAY_INDEX``.
    """
    return now_local.weekday() in _weekday_set(slot.day_of_week)


def plan_catchup(
    config: Config,
    was_sent: Callable[[str, str, str], bool],
    now_utc: datetime | None = None,
) -> list[MissedSlot]:
    """Return the due, within-grace, not-yet-sent slots to fire on startup.

    PURE: ``now_utc`` and the ``was_sent`` reader are injected. ``now_utc``
    defaults to the current UTC instant (mirroring the ``from_payloads``
    clock-injection idiom). For each ENABLED slot of each location, in the
    location's own IANA timezone:

    - skip if the slot does not fire on today's weekday (``_fires_on``);
    - skip if the slot's wall-clock time did NOT exist today (spring-forward gap:
      the naive wall-clock value does not round-trip through the zone, so the
      live CronTrigger skips it — the planner must too);
    - skip if the slot's scheduled instant is still in the future, comparing
      AWARE instants against ``now_utc`` (the live CronTrigger job will fire it);
    - skip if the slot's scheduled instant passed more than :data:`GRACE` ago,
      again comparing aware instants (D-04);
    - skip if ``was_sent(location.name, slot.time, local_date)`` (already
      delivered, D-06);
    - otherwise emit a :class:`MissedSlot`.

    The scheduled instant is built by composing a naive wall-clock datetime for
    today's slot and attaching the location zone via ``.replace(tzinfo=tz)`` so
    the UTC offset/fold re-resolves for the new wall-clock time — never by
    mutating ``now_local``'s hour/minute in place (which would keep its
    already-resolved offset and disagree with the live trigger across DST).

    The returned list is bounded to TODAY's slots within 90 minutes (Pitfall 5),
    so a recovery burst is a rounding error against the OpenWeather quota.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    missed: list[MissedSlot] = []
    for loc in config.locations:
        tz = ZoneInfo(loc.timezone)
        now_local = now_utc.astimezone(tz)
        for slot in loc.schedule:
            if not slot.enabled:  # SCHD-02 toggle: never catch up a paused slot.
                continue
            if not _fires_on(slot, now_local):  # not today's weekday.
                continue
            hh, mm = slot.parsed_time()
            # Compose a NAIVE wall-clock datetime for today's slot, then attach
            # the location zone so the correct UTC offset/fold re-resolves for
            # this wall-clock time (DST-correct; never carry now_local's offset).
            naive = datetime(now_local.year, now_local.month, now_local.day, hh, mm)
            scheduled = naive.replace(tzinfo=tz)
            # Spring-forward gap: if the wall-clock value does not round-trip
            # through the zone, the time never existed today — the live
            # CronTrigger skips it, so the planner must skip it too.
            if scheduled.astimezone(tz).replace(tzinfo=None) != naive:
                continue
            # Compare AWARE instants (never two wall-clock-derived locals):
            if scheduled > now_utc:  # not due yet — the live job will fire it.
                continue
            if now_utc - scheduled > GRACE:  # > 90 min late — skip (D-04).
                continue
            local_date = now_local.date().isoformat()
            if was_sent(loc.name, slot.time, local_date):  # already delivered (D-06).
                continue
            missed.append(MissedSlot(loc, slot, scheduled, local_date))
    return missed
