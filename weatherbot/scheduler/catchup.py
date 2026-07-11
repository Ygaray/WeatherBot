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
the scheduler's. ``fires_on`` is driven from the SAME normalized ``day_of_week``
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


def fires_on(slot: Schedule, now_local: datetime) -> bool:
    """Does ``slot`` fire on ``now_local``'s weekday?

    Driven from the slot's normalized ``day_of_week`` (the SAME string the
    CronTrigger receives) so the planner and the live trigger always agree
    (Pitfall 3). ``now_local.weekday()`` is Monday-first (Mon=0), matching
    ``_WEEKDAY_INDEX``.

    Public (promoted from ``_fires_on``) so the Phase-15 UV monitor can reuse the
    single source-of-truth active-today logic instead of forking the weekday
    parsing (Anti-Pattern: two divergent day-of-week implementations). The
    catch-up planner is the other caller.
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

    - skip if the slot does not fire on today's weekday (``fires_on``);
    - skip if the slot's wall-clock time did NOT exist today (spring-forward gap:
      the naive wall-clock value does not round-trip through the zone, so the
      live CronTrigger skips it — the planner must too);
    - skip if the slot's scheduled instant is still in the future, comparing
      AWARE instants against ``now_utc`` (the live CronTrigger job will fire it);
    - skip if the slot's scheduled instant passed more than :data:`GRACE` ago,
      again comparing aware instants (D-04);
    - skip if ``was_sent(location.id, slot.time, local_date)`` (already
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
            hh, mm = slot.parsed_time()
            # D-01 / F14: evaluate BOTH today's and yesterday's local date as
            # candidate scheduled days. A slot due at 23:45 and only recovered at
            # 00:15 the NEXT local day has its real scheduled instant on YESTERDAY;
            # composing only today's date builds a ~23.5h-future instant that the
            # bare `scheduled > now_utc` gate wrongly skips as "not due yet". The
            # per-slot `emitted_dates` set guarantees a single slot never emits
            # twice even if both candidates fall within GRACE.
            emitted_dates: set[str] = set()
            for cand_date in (now_local.date(), now_local.date() - timedelta(days=1)):
                # fires_on is evaluated on the CANDIDATE day (not now_local) so a
                # weekend-only slot is never recovered on a weekday it does not run.
                cand_local = datetime(cand_date.year, cand_date.month, cand_date.day)
                if not fires_on(slot, cand_local):  # not the candidate day's weekday.
                    continue
                # Compose a NAIVE wall-clock datetime for the CANDIDATE day's slot,
                # then attach the location zone so the correct UTC offset/fold
                # re-resolves for this wall-clock time (DST-correct; never carry
                # now_local's offset).
                naive = datetime(cand_date.year, cand_date.month, cand_date.day, hh, mm)
                # Spring-forward GAP: a non-existent wall-clock time has different
                # offsets for its two folds AND its wall clock changes when normalized
                # through UTC and back. (astimezone(tz) alone is a no-op on an aware
                # zoneinfo dt — it must route through UTC to normalize.) Fall-back fold
                # times round-trip unchanged, so they are correctly kept.
                off0 = naive.replace(tzinfo=tz, fold=0).utcoffset()
                off1 = naive.replace(tzinfo=tz, fold=1).utcoffset()
                scheduled = naive.replace(tzinfo=tz)
                roundtrip = (
                    scheduled.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
                )
                if off0 != off1 and roundtrip != naive:
                    continue  # gap time — never existed; the live CronTrigger skips it.
                # Compare AWARE instants (never two wall-clock-derived locals):
                if scheduled > now_utc:  # not due yet — the live job will fire it.
                    continue
                # D-02 / F91: grace lateness is measured against the fold=0 instant
                # ON PURPOSE — a live apscheduler 3.11.2 probe (32-RESEARCH.md) confirms
                # CronTrigger fires the DST fall-back repeated-hour slot at fold=0, and
                # the fold=0 compose above agrees. So fold=0 lateness IS the true
                # lateness; there is no ~60-min inflation to correct. A both-folds min()
                # grace was considered and rejected: it would keep a slot 120 min past
                # fold=0 (measuring 60 min against fold=1) and regress the locked
                # SCHD-04 band test. test_catchup_fold_grace_not_inflated pins this.
                if now_utc - scheduled > GRACE:  # > 90 min late — skip (D-04).
                    continue
                local_date = cand_date.isoformat()  # D-01 / F14: CANDIDATE day, not now_local.date().
                if local_date in emitted_dates:  # per-slot dedup — never emit a slot twice.
                    continue
                if was_sent(loc.id, slot.time, local_date):  # already delivered (D-06).
                    continue
                missed.append(MissedSlot(loc, slot, scheduled, local_date))
                emitted_dates.add(local_date)
    return missed
