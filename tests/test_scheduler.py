"""Scheduler foundation tests (Plan 03-01, Wave 0 scaffold).

Covers the pure, isolately-testable pieces the daemon (Plan 03) consumes:
- the ``days`` vocabulary parser/normalizer (Pattern 2, SCHD-03),
- the ``Schedule`` config model HH:MM/days validation (SCHD-01/02),
- the ``sent_log`` idempotency store (Pattern 4, SCHD-07 store half).
No daemon wiring is exercised here.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from weatherbot.scheduler.days import parse_days
from weatherbot.scheduler.context import ScheduleContext, schedule_placeholders
from weatherbot.config import Config, Location
from weatherbot.config.models import Schedule


# --- SCHD-03: days vocabulary parses + normalizes to day_of_week ------------


def test_days_parsing_matrix():
    # presets normalize to APScheduler day_of_week strings
    assert parse_days("mon-fri") == "mon-fri"
    assert parse_days("weekdays") == "mon-fri"
    assert parse_days("weekends") == "sat,sun"
    assert parse_days("daily") == "mon-sun"
    # comma lists pass through (normalized: lower, trimmed)
    assert parse_days("sat,sun") == "sat,sun"
    assert parse_days("mon,wed,fri") == "mon,wed,fri"
    # case / whitespace insensitive
    assert parse_days("  MON-FRI ") == "mon-fri"
    assert parse_days("Sat, Sun") == "sat,sun"
    assert parse_days("WEEKENDS") == "sat,sun"


def test_bad_days_token_raises():
    with pytest.raises(ValueError):
        parse_days("funday")
    with pytest.raises(ValueError):
        parse_days("")
    with pytest.raises(ValueError):
        parse_days("mon,funday")


def test_bad_days_message_lists_vocabulary():
    with pytest.raises(ValueError) as exc:
        parse_days("funday")
    msg = str(exc.value)
    # the error surfaces both the allowed presets and the day tokens
    assert "weekends" in msg
    assert "mon" in msg


# --- SCHD-04 display half: ScheduleContext + schedule_placeholders ----------

_TZ = ZoneInfo("America/New_York")


def test_schedule_placeholders_manual_no_context():
    # No context (manual --send-now): sent_at/checked_at render from the passed
    # datetimes; schedule_note is empty (D-15 collapse rule).
    sent = datetime(2026, 6, 10, 7, 30, tzinfo=_TZ)
    checked = datetime(2026, 6, 10, 7, 30, tzinfo=_TZ)
    out = schedule_placeholders(None, sent, checked)
    assert out["sent_at"]  # non-empty
    assert out["checked_at"]  # non-empty
    assert "7:30 AM" in out["sent_at"]
    assert out["schedule_note"] == ""


def test_schedule_placeholders_context_no_scheduled_time():
    # A context whose scheduled_dt is None (manual path that still carries a tz)
    # must keep schedule_note empty — no None crash (Pitfall 4).
    ctx = ScheduleContext(scheduled_dt=None, tz=_TZ)
    sent = datetime(2026, 6, 10, 7, 30, tzinfo=_TZ)
    out = schedule_placeholders(ctx, sent, sent)
    assert out["schedule_note"] == ""
    assert out["sent_at"]


def test_schedule_placeholders_late_populates_note():
    # A within-grace late send renders an intended-vs-actual local-time note.
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_TZ)
    sent = datetime(2026, 6, 10, 7, 30, tzinfo=_TZ)
    ctx = ScheduleContext(scheduled_dt=scheduled, tz=_TZ, late=True)
    out = schedule_placeholders(ctx, sent, sent)
    assert "intended for 7:00 AM" in out["schedule_note"]
    assert "sent 7:30 AM" in out["schedule_note"]


def test_schedule_placeholders_on_time_not_late_empty_note():
    # late=False (on-time scheduled send) keeps the note empty even with a
    # scheduled_dt present.
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_TZ)
    ctx = ScheduleContext(scheduled_dt=scheduled, tz=_TZ, late=False)
    sent = datetime(2026, 6, 10, 7, 0, tzinfo=_TZ)
    out = schedule_placeholders(ctx, sent, sent)
    assert out["schedule_note"] == ""


def test_schedule_placeholders_render_location_local():
    # Times are rendered in the context tz: a UTC instant displays as the local
    # wall-clock time (D-14).
    ctx = ScheduleContext(scheduled_dt=None, tz=_TZ)
    sent_utc = datetime(2026, 6, 10, 11, 30, tzinfo=ZoneInfo("UTC"))  # 07:30 EDT
    out = schedule_placeholders(ctx, sent_utc, sent_utc)
    assert "7:30 AM" in out["sent_at"]


# --- SCHD-07 store half: sent_log idempotency -------------------------------


def test_sent_log_idempotent(tmp_db):
    from weatherbot.weather.store import record_sent, was_sent

    # fresh db: nothing sent yet (helpers self-create the schema)
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is False

    record_sent(tmp_db, "Home", "07:00", "2026-06-10")
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is True

    # double record on the same key inserts exactly one row (INSERT OR IGNORE)
    record_sent(tmp_db, "Home", "07:00", "2026-06-10")
    import sqlite3

    with sqlite3.connect(tmp_db) as conn:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM sent_log "
            "WHERE location_name=? AND send_time=? AND local_date=?",
            ("Home", "07:00", "2026-06-10"),
        ).fetchone()
    assert count == 1

    # distinct date / distinct send_time are separate slots
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-11") is False
    assert was_sent(tmp_db, "Home", "08:30", "2026-06-10") is False


# --- SCHD-06/D-04: pure catch-up planner (plan_catchup + _fires_on) ---------

_NY = ZoneInfo("America/New_York")


def _home_config(days: str = "mon-fri", time: str = "07:00", enabled: bool = True):
    """Build a single-location Config with one schedule slot for planner tests."""
    return Config(
        locations=[
            Location(
                name="Home",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
                schedule=[Schedule(time=time, days=days, enabled=enabled)],
            )
        ],
    )


def _utc_for_local(y, mo, d, hh, mm, tz=_NY):
    """A UTC datetime that lands at the given local wall-clock time in ``tz``."""
    return datetime(y, mo, d, hh, mm, tzinfo=tz).astimezone(ZoneInfo("UTC"))


def _never_sent(*_a):
    return False


def test_catchup_window():
    from weatherbot.scheduler.catchup import plan_catchup

    # 2026-06-10 is a Wednesday (mon-fri slot is due).
    cfg = _home_config(days="mon-fri", time="07:00")

    # 07:30 local: 30 min late (< 90) → exactly one MissedSlot.
    now = _utc_for_local(2026, 6, 10, 7, 30)
    missed = plan_catchup(cfg, _never_sent, now_utc=now)
    assert len(missed) == 1
    ms = missed[0]
    assert ms.local_date == "2026-06-10"
    assert ms.scheduled_dt.astimezone(_NY).hour == 7
    assert ms.scheduled_dt.astimezone(_NY).minute == 0

    # 08:31 local: > 90 min late → skipped (empty).
    now_late = _utc_for_local(2026, 6, 10, 8, 31)
    assert plan_catchup(cfg, _never_sent, now_utc=now_late) == []

    # 06:45 local: before 07:00 → not due yet (empty; live job will fire it).
    now_early = _utc_for_local(2026, 6, 10, 6, 45)
    assert plan_catchup(cfg, _never_sent, now_utc=now_early) == []

    # already sent → empty (D-06).
    def _sent(name, time, date):
        return name == "Home" and time == "07:00" and date == "2026-06-10"

    assert plan_catchup(cfg, _sent, now_utc=now) == []


def test_disabled_slot_not_fired():
    from weatherbot.scheduler.catchup import plan_catchup

    cfg = _home_config(days="mon-fri", time="07:00", enabled=False)
    now = _utc_for_local(2026, 6, 10, 7, 30)
    assert plan_catchup(cfg, _never_sent, now_utc=now) == []


def test_days_match_agrees_across_week():
    from weatherbot.scheduler.catchup import _fires_on

    # Build a tiny stand-in slot with the normalized day_of_week the trigger gets.
    class _Slot:
        def __init__(self, days):
            self._dow = parse_days(days)

        @property
        def day_of_week(self):
            return self._dow

    # 2026-06-08 (Mon) .. 2026-06-14 (Sun): one full week.
    week = [datetime(2026, 6, 8 + i, 7, 0, tzinfo=_NY) for i in range(7)]
    weekday_index = {i: dt for i, dt in enumerate(week)}  # 0=Mon .. 6=Sun

    # mon-fri fires Mon..Fri (0..4), not Sat/Sun.
    mf = _Slot("mon-fri")
    for i in range(7):
        assert _fires_on(mf, weekday_index[i]) is (i <= 4)

    # weekends (sat,sun) fires only Sat(5)/Sun(6).
    we = _Slot("weekends")
    for i in range(7):
        assert _fires_on(we, weekday_index[i]) is (i >= 5)

    # daily (mon-sun) fires every day.
    dl = _Slot("daily")
    for i in range(7):
        assert _fires_on(dl, weekday_index[i]) is True

    # explicit comma list mon,wed,fri.
    mwf = _Slot("mon,wed,fri")
    for i in range(7):
        assert _fires_on(mwf, weekday_index[i]) is (i in (0, 2, 4))


def test_dst_exactly_once():
    from weatherbot.scheduler.catchup import plan_catchup

    # Spring-forward: 2026-03-08 (Sun). A 07:00 send is outside the 01:00-02:59
    # skipped band → exactly one MissedSlot when scanned at 07:30 local.
    spring_cfg = _home_config(days="daily", time="07:00")
    spring_now = _utc_for_local(2026, 3, 8, 7, 30)
    spring = plan_catchup(spring_cfg, _never_sent, now_utc=spring_now)
    assert len(spring) == 1
    assert spring[0].local_date == "2026-03-08"

    # Fall-back: 2026-11-01 (Sun). A 07:00 send is outside the repeated 01:00 hour
    # → exactly one MissedSlot.
    fall_now = _utc_for_local(2026, 11, 1, 7, 30)
    fall = plan_catchup(spring_cfg, _never_sent, now_utc=fall_now)
    assert len(fall) == 1
    assert fall[0].local_date == "2026-11-01"
