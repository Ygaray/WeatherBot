"""Scheduler foundation tests (Plan 03-01, Wave 0 scaffold).

Covers the pure, isolately-testable pieces the daemon (Plan 03) consumes:
- the ``days`` vocabulary parser/normalizer (Pattern 2, SCHD-03),
- the ``Schedule`` config model HH:MM/days validation (SCHD-01/02),
- the ``sent_log`` idempotency store (Pattern 4, SCHD-07 store half).
No daemon wiring is exercised here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from weatherbot.scheduler.days import parse_days
from weatherbot.scheduler.context import ScheduleContext, schedule_placeholders
from weatherbot.config import Config, Location
from weatherbot.config.holder import ConfigHolder
from weatherbot.config.models import BotConfig, Schedule


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
    from weatherbot.weather.store import claim_slot, was_sent

    # fresh db: nothing sent yet (helpers self-create the schema)
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is False

    # first claim wins (THIS caller inserted the row) and marks the slot sent
    assert claim_slot(tmp_db, "Home", "07:00", "2026-06-10") is True
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is True

    # second claim on the same key loses (row already exists) — idempotency
    # guarantee that the old double-record_sent asserted, now on the live path
    assert claim_slot(tmp_db, "Home", "07:00", "2026-06-10") is False
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


# --- SCHD-06/D-04: pure catch-up planner (plan_catchup + fires_on) ----------

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
    from weatherbot.scheduler.catchup import fires_on

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
        assert fires_on(mf, weekday_index[i]) is (i <= 4)

    # weekends (sat,sun) fires only Sat(5)/Sun(6).
    we = _Slot("weekends")
    for i in range(7):
        assert fires_on(we, weekday_index[i]) is (i >= 5)

    # daily (mon-sun) fires every day.
    dl = _Slot("daily")
    for i in range(7):
        assert fires_on(dl, weekday_index[i]) is True

    # explicit comma list mon,wed,fri.
    mwf = _Slot("mon,wed,fri")
    for i in range(7):
        assert fires_on(mwf, weekday_index[i]) is (i in (0, 2, 4))


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


def test_dst_transition_band_exactly_once():
    """SCHD-04 DST half: slots INSIDE the transition band (02:30 gap / 01:30
    fold) must agree with the live CronTrigger — no phantom spring-forward fire,
    no dropped fall-back fold via a negative-day delta (success criterion #3)."""
    from weatherbot.scheduler.catchup import plan_catchup

    # --- Spring-forward GAP: 2026-03-08, 02:00 -> 03:00 is skipped. ----------
    # A 02:30 daily slot is a wall-clock time that NEVER occurs that day, so the
    # live CronTrigger skips it. Scanned at 03:45 local — PAST-DUE within the
    # 90-min grace — the planner must agree → ZERO MissedSlots ONLY because the
    # gap is detected (the buggy no-op astimezone guard emits one phantom slot).
    gap_cfg = _home_config(days="daily", time="02:30")
    gap_now = _utc_for_local(2026, 3, 8, 3, 45)  # 07:45 UTC, 15 min past, within grace
    assert plan_catchup(gap_cfg, _never_sent, now_utc=gap_now) == []

    # --- Fall-back FOLD: 2026-11-01, the 01:00 hour occurs twice. ------------
    # A 01:30 daily slot. The FIRST 01:30 occurrence is at 01:30 EDT (UTC-4).
    fold_cfg = _home_config(days="daily", time="01:30")
    first_0130_edt = datetime(2026, 11, 1, 1, 30, tzinfo=_NY, fold=0).astimezone(
        ZoneInfo("UTC")
    )

    # Scanned 60 min after the first 01:30 (within the 90-min grace), not yet
    # sent → exactly ONE MissedSlot for 2026-11-01. The buggy code yields a
    # negative-day delta (scheduled > now_local) and drops it.
    within_grace = first_0130_edt + timedelta(minutes=60)
    fold_missed = plan_catchup(fold_cfg, _never_sent, now_utc=within_grace)
    assert len(fold_missed) == 1
    assert fold_missed[0].local_date == "2026-11-01"

    # Scanned 120 min after the first 01:30 (beyond the 90-min grace) → ZERO
    # (must be skipped as too-late, not misread as "not due yet").
    beyond_grace = first_0130_edt + timedelta(minutes=120)
    assert plan_catchup(fold_cfg, _never_sent, now_utc=beyond_grace) == []


# --- SCHD-05/D-07: daemon spine (fire_slot + run_daemon) --------------------


class _FakeClient:
    """Returns recorded One Call fixtures (copied from test_send_now.py)."""

    def __init__(self, onecall_imp, onecall_met):
        self._onecall = {"imperial": onecall_imp, "metric": onecall_met}
        self.onecall_calls: list[str] = []

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._onecall[units]


class _FakeChannel:
    """Captures the rendered body and the Forecast (copied from test_send_now.py)."""

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self.briefing_forecasts: list[object] = []
        self._result = DeliveryResult(ok=True)

    def send_briefing(self, text, forecast):
        self.sent_text.append(text)
        self.briefing_forecasts.append(forecast)
        return self._result


class _RaisingChannel:
    """A channel whose send raises — proves fire_slot isolates the exception."""

    def __init__(self):
        self.sent_text: list[str] = []

    def send_briefing(self, text, forecast):
        raise RuntimeError("delivery boom")


def _two_tz_config():
    """Home (America/New_York) + Weekend (America/Chicago), each with one slot."""
    return Config(
        locations=[
            Location(
                name="Home",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
                schedule=[
                    Schedule(time="07:00", days="mon-fri"),
                    Schedule(time="08:00", days="sat,sun", enabled=False),
                ],
            ),
            Location(
                name="Weekend",
                lat=41.8781,
                lon=-87.6298,
                timezone="America/Chicago",
                schedule=[Schedule(time="08:30", days="sat,sun")],
            ),
        ],
    )


def test_fire_slot_records_after_success(tmp_db, load_fixture):
    from weatherbot.scheduler.daemon import fire_slot
    from weatherbot.weather.store import was_sent

    cfg = _home_config(days="mon-fri", time="07:00")
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)

    result = fire_slot(
        loc,
        slot,
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=channel,
        scheduled_dt=scheduled,
        late=True,
    )

    assert result is not None and result.ok
    assert len(channel.sent_text) == 1
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is True


def test_fire_slot_idempotent_double_fire(tmp_db, load_fixture):
    from weatherbot.scheduler.daemon import fire_slot

    cfg = _home_config(days="mon-fri", time="07:00")
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)

    kwargs = dict(
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=channel,
        scheduled_dt=scheduled,
        late=True,
    )
    fire_slot(loc, slot, **kwargs)
    # Second fire for the same (location, slot, local_date) must SKIP.
    fire_slot(loc, slot, **kwargs)

    assert len(channel.sent_text) == 1  # only the first fire delivered


def test_late_send_note(tmp_db, load_fixture):
    from weatherbot.scheduler.daemon import fire_slot

    cfg = _home_config(days="mon-fri", time="07:00")
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)

    fire_slot(
        loc,
        slot,
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=channel,
        scheduled_dt=scheduled,
        late=True,
    )

    body = channel.sent_text[0]
    # A within-grace recovered send renders the intended-vs-actual note.
    assert "intended for 7:00 AM" in body


def test_fire_slot_isolates_exception(tmp_db, load_fixture):
    from weatherbot.scheduler.daemon import fire_slot
    from weatherbot.weather.store import was_sent

    cfg = _home_config(days="mon-fri", time="07:00")
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)

    # A raising channel must NOT propagate out of fire_slot and must NOT record.
    result = fire_slot(
        loc,
        slot,
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=_RaisingChannel(),
        scheduled_dt=scheduled,
        late=True,
    )

    assert result is None
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is False


def test_post_send_db_error_keeps_claim(tmp_db, load_fixture, monkeypatch):
    """F01 (HARD-DELIV-01, D-01a reproduce-first): a post-DELIVERY bookkeeping DB
    error must NOT release the won claim.

    After ``result.ok`` (the briefing is delivered), ``fire_slot`` runs its
    bookkeeping tail (``resolve_alert`` + ``stamp_success``). If that tail raises a
    realistic ``database is locked`` ``OperationalError``, the current code falls to
    the broad ``except`` which — because ``claimed=True`` — releases the claim
    (deleting the ``sent_log`` row so the slot re-fires on catch-up/restart ⇒
    DUPLICATE) and records a false ``internal_error`` alert.

    The exactly-once claim is the source of truth once delivery succeeds: this test
    asserts the slot STAYS sent (``was_sent`` True — no re-fire) and NO
    ``internal_error`` alert is recorded. It FAILS against pre-fix daemon.py and
    PASSES once the bookkeeping tail is a log-and-swallow (D-01).
    """
    import sqlite3

    from weatherbot.reliability import REASON_INTERNAL_ERROR
    from weatherbot.scheduler import daemon as daemon_mod
    from weatherbot.scheduler.daemon import fire_slot
    from weatherbot.weather.store import was_sent

    cfg = _home_config(days="mon-fri", time="07:00")
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()  # delivers ok=True
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)

    # Inject a store error into the POST-SEND bookkeeping (mirrors a
    # ``database is locked`` on ``stamp_success`` AFTER a successful delivery). The
    # daemon module holds its own imported ``stamp_success`` symbol.
    def _boom_stamp(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(daemon_mod, "stamp_success", _boom_stamp)

    fire_slot(
        loc,
        slot,
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=channel,
        scheduled_dt=scheduled,
        late=True,
    )

    # The briefing WAS delivered exactly once.
    assert len(channel.sent_text) == 1
    # The claim must STAY committed — a post-delivery bookkeeping error can never
    # re-open a delivered slot (no duplicate on catch-up/restart).
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is True
    # And no false internal_error alert may be recorded for this slot/day.
    conn = sqlite3.connect(tmp_db)
    try:
        reasons = [
            r[0]
            for r in conn.execute(
                "SELECT reason FROM alerts "
                "WHERE slot_time=? AND local_date=?",
                ("07:00", "2026-06-10"),
            ).fetchall()
        ]
    finally:
        conn.close()
    assert REASON_INTERNAL_ERROR not in reasons


def test_post_send_success_log_raise_keeps_claim(tmp_db, load_fixture, monkeypatch):
    """CR-01 (IN-01 missing-branch): a raise from the trailing ``_log.info("slot
    fired")`` must NOT re-open a delivered claim.

    The F01 swallow originally covered ``resolve_alert``/``stamp_success`` but NOT
    the following ``_log.info("slot fired")`` + ``return result``. The project logs
    through a custom ``PrintLoggerFactory(file=_LiveStderr())`` sink that forwards to
    ``sys.stderr.write`` — which can raise ``BrokenPipeError`` / ``OSError`` (journald
    restart, closed console). Pre-fix, that raise fell to the broad ``except`` with
    ``claimed=True`` and released the claim (deleting the ``sent_log`` row ⇒ a
    duplicate on catch-up/restart) plus recorded a false ``internal_error`` alert.

    This test patches the daemon logger so the "slot fired" event raises ``OSError``
    and asserts the slot STAYS sent (``was_sent`` True — no re-fire) and NO
    ``internal_error`` alert is recorded. It FAILS against pre-fix daemon.py (the
    success log lived outside the swallow) and PASSES once the log is inside it.
    """
    import sqlite3

    from weatherbot.reliability import REASON_INTERNAL_ERROR
    from weatherbot.scheduler import daemon as daemon_mod
    from weatherbot.scheduler.daemon import fire_slot
    from weatherbot.weather.store import was_sent

    cfg = _home_config(days="mon-fri", time="07:00")
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()  # delivers ok=True
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)

    # Wrap the daemon logger so ONLY the post-success "slot fired" event raises a
    # realistic stderr-sink error (BrokenPipeError is an OSError subclass). Every
    # other event (including the recovery warning) passes through untouched so the
    # test proves the SUCCESS log site is what's guarded.
    real_log = daemon_mod._log

    class _RaisingOnSlotFired:
        def info(self, event, *args, **kwargs):
            if event == "slot fired":
                raise BrokenPipeError("stderr sink closed")
            return real_log.info(event, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(real_log, name)

    monkeypatch.setattr(daemon_mod, "_log", _RaisingOnSlotFired())

    fire_slot(
        loc,
        slot,
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=channel,
        scheduled_dt=scheduled,
        late=True,
    )

    # The briefing WAS delivered exactly once.
    assert len(channel.sent_text) == 1
    # A raise from the success log can never re-open a delivered slot.
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is True
    # And no false internal_error alert may be recorded for this slot/day.
    conn = sqlite3.connect(tmp_db)
    try:
        reasons = [
            r[0]
            for r in conn.execute(
                "SELECT reason FROM alerts WHERE slot_time=? AND local_date=?",
                ("07:00", "2026-06-10"),
            ).fetchall()
        ]
    finally:
        conn.close()
    assert REASON_INTERNAL_ERROR not in reasons


# --- SCHD-07 delivery-level exactly-once: atomic claim_slot (gap #2 / CR-02) -


def test_concurrent_double_fire_delivers_once(tmp_db, load_fixture):
    from weatherbot.scheduler.daemon import fire_slot
    from weatherbot.weather.store import claim_slot, release_claim, was_sent

    # --- Claim arbitration (Task 1): exactly one True per key ----------------
    # First caller wins the fresh claim; any subsequent caller loses it.
    assert claim_slot(tmp_db, "Home", "07:00", "2026-06-10") is True
    assert claim_slot(tmp_db, "Home", "07:00", "2026-06-10") is False
    # A won claim writes the row immediately (so was_sent sees it).
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is True
    # Releasing the claim re-opens the slot so a re-claim can win again.
    release_claim(tmp_db, "Home", "07:00", "2026-06-10")
    assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is False
    assert claim_slot(tmp_db, "Home", "07:00", "2026-06-10") is True
    # A distinct key is an independent claim.
    assert claim_slot(tmp_db, "Home", "08:30", "2026-06-10") is True
    # Reset so the fire_slot leg below starts from an unclaimed slot.
    release_claim(tmp_db, "Home", "07:00", "2026-06-10")

    # --- Delivery-level exactly-once (Task 2): two overlapping fires, one POST.
    cfg = _home_config(days="mon-fri", time="07:00")
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()  # one shared channel counts POSTs across both fires
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)

    kwargs = dict(
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=channel,
        scheduled_dt=scheduled,
        late=True,
    )
    # Two overlapping fires for the SAME (location, send_time, local_date): the
    # first wins the atomic claim and POSTs; the second loses the claim and must
    # NOT POST. Net: EXACTLY ONE delivery (SCHD-07 at the delivery boundary).
    fire_slot(loc, slot, **kwargs)
    fire_slot(loc, slot, **kwargs)

    assert len(channel.sent_text) == 1


def test_jobs_registered_per_location_tz(tmp_db, load_fixture):
    from apscheduler.schedulers.background import BackgroundScheduler
    from weatherbot.scheduler.daemon import _register_jobs

    cfg = _two_tz_config()
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()
    scheduler = BackgroundScheduler()
    _register_jobs(
        scheduler,
        ConfigHolder(cfg),
        db_path=tmp_db,
        settings=None,
        client=client,
        channel=channel,
    )

    jobs = scheduler.get_jobs()
    # Home has one ENABLED slot (07:00 mon-fri; the 08:00 sat,sun is disabled)
    # + Weekend's 08:30 sat,sun = 2 jobs total (disabled slot → no job).
    assert len(jobs) == 2

    tz_by_id = {job.id: str(job.trigger.timezone) for job in jobs}
    home_id = "Home|07:00|mon-fri"
    weekend_id = "Weekend|08:30|sat,sun"
    assert tz_by_id[home_id] == "America/New_York"
    assert tz_by_id[weekend_id] == "America/Chicago"

    # The next fire computed from the trigger is tz-aware in the location's zone
    # (a not-yet-started scheduler exposes no next_run_time attribute, so the
    # announce path derives it from the trigger — mirror that here).
    home_job = next(j for j in jobs if j.id == home_id)
    next_fire = home_job.trigger.get_next_fire_time(
        None, datetime.now(ZoneInfo("America/New_York"))
    )
    assert next_fire is not None
    assert next_fire.tzinfo is not None
    assert str(next_fire.tzinfo) == "America/New_York"

    # The scheduler was never started (we only assert on registration), so there
    # is nothing to shut down.


# --- SCHD-05/D-09: --run CLI flag dispatches to run_daemon ------------------


def test_run_flag_dispatches_to_daemon(tmp_path, monkeypatch):
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot import cli

    # A minimal valid config on disk for _load_config_reporting to parse.
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[[locations]]
name = "Home"
lat = 40.7128
lon = -74.006
timezone = "America/New_York"

[[locations.schedule]]
time = "07:00"
days = "mon-fri"
""".strip(),
        encoding="utf-8",
    )

    # Stub load_settings (no real env secret needed) and run_daemon (no blocking).
    monkeypatch.setattr(cli, "load_settings", lambda: object())

    captured = {}

    def _stub_run_daemon(*, config, settings, db_path, config_path):
        captured["config"] = config
        captured["db_path"] = db_path
        captured["config_path"] = config_path
        return 0

    monkeypatch.setattr(daemon_mod, "run_daemon", _stub_run_daemon)

    rc = cli.main(["run", "--config", str(cfg_path)])

    assert rc == 0
    assert captured["config"].locations[0].name == "Home"
    assert captured["db_path"] is not None
    # Phase 9 (CFG-02): the run dispatch threads the config PATH so the reload engine
    # can re-read from disk on SIGHUP.
    assert captured["config_path"] == str(cfg_path)


def test_run_daemon_stamps_tick_at_startup(tmp_db, monkeypatch):
    """IN-02: run_daemon stamps a heartbeat tick once at startup (last_tick != NULL).

    A freshly-online daemon should not show last_tick=NULL while last_success is
    fresh. As of Plan 05-02 the startup tick is subsumed by the once-only online
    signal (``emit_online``), so it stamps only AFTER the startup self-check passes
    (D-05). We stub the self-check to pass and use a stop Event that lets the gate
    probe once (is_set False) but returns immediately from the foreground wait().
    """
    import sqlite3

    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    # A config with no enabled slots -> no jobs, no catch-up sends, no client needed.
    cfg = Config(
        locations=[
            Location(name="Home", lat=40.0, lon=-74.0, timezone="UTC", schedule=[])
        ]
    )

    init_db(tmp_db)

    # Self-check passes on the first call so the gate returns and emit_online stamps
    # the startup tick.
    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    # Fake scheduler so no real APScheduler threads start.
    class _FakeScheduler:
        def add_job(self, *a, **k):
            pass

        def get_jobs(self):
            return []

        def start(self):
            pass

        def shutdown(self, wait=False):
            pass

    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", _FakeScheduler)

    # A stop Event never "set" (so the gate probes once and passes) whose foreground
    # wait() returns immediately so run_daemon returns after emitting online.
    class _NeverSetImmediateWait:
        def is_set(self):
            return False

        def set(self):
            pass

        def wait(self, timeout=None):
            return True

    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)

    rc = daemon_mod.run_daemon(config=cfg, settings=None, db_path=tmp_db)

    assert rc == 0
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute("SELECT last_tick_utc FROM heartbeat WHERE id=1").fetchone()
    assert row[0] is not None  # startup tick stamped (IN-02) once online


# --- OPS-02 / D-03-D-08: startup self-check gate + one-time online signal ----


class _StartObservableScheduler:
    """A fake BackgroundScheduler whose start() is observable (records the call).

    Used to assert whether ``run_daemon`` reached ``scheduler.start()`` (it must NOT
    on a stop-during-gate, and MUST after the self-check first passes).
    """

    def __init__(self):
        self.started = False

    def add_job(self, *a, **k):
        pass

    def get_jobs(self):
        return []

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        pass


class _OnlinePingChannel:
    """Captures the channel-agnostic send(text) used by the one-time online ping."""

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self._result = DeliveryResult(ok=True)

    def send(self, text):
        self.sent_text.append(text)
        return self._result


def _no_slot_config():
    """A config with no enabled slots -> no jobs, no catch-up, no real client needed."""
    return Config(
        locations=[
            Location(name="Home", lat=40.0, lon=-74.0, timezone="UTC", schedule=[])
        ]
    )


def _read_health(db_path):
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT reason, detail FROM health WHERE id=1").fetchone()


def test_gate_stop_stays_alive_then_clean_exit_no_online(tmp_db, monkeypatch):
    """gate_stop: a failing self-check + a stop-during-the-loop exits cleanly WITHOUT
    starting the scheduler and WITHOUT emitting the online signal (D-04/D-05)."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult, NETWORK_NOT_READY
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    # Self-check always fails (not ready) — the daemon must stay alive and re-probe.
    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(
            ok=False, reason=NETWORK_NOT_READY, detail="ConnectError"
        ),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)

    # ready() must NOT be called when the gate never passes.
    ready_calls = []
    monkeypatch.setattr(
        daemon_mod.SystemdNotifier, "ready", lambda self: ready_calls.append(1)
    )

    # A stop Event that is NOT set at the top of the gate loop (so the daemon probes
    # once and stamps health), but whose re-probe wait() returns True (stop set
    # DURING the wait) -> the loop breaks cleanly without a real interval sleep. This
    # is the realistic "systemctl stop during the re-probe loop" shutdown path.
    class _StopDuringWait:
        def __init__(self):
            self._set = False

        def is_set(self):
            return self._set

        def set(self):
            self._set = True

        def wait(self, timeout=None):
            self._set = True  # stop arrives during the re-probe wait
            return True

    monkeypatch.setattr(daemon_mod.threading, "Event", _StopDuringWait)

    channel = _OnlinePingChannel()
    rc = daemon_mod.run_daemon(
        config=_no_slot_config(), settings=None, db_path=tmp_db, channel=channel
    )

    assert rc == 0
    assert sched.started is False  # scheduler NEVER started (gate did not pass)
    assert ready_calls == []  # READY=1 not sent
    assert channel.sent_text == []  # no Discord online ping
    reason, _detail = _read_health(tmp_db)
    assert (
        reason == NETWORK_NOT_READY
    )  # health stamped on the probe outcome, not online


def test_online_once_fires_all_signals_then_starts(tmp_db, monkeypatch):
    """online_once: a first-pass self-check fires the online signal exactly once —
    health=online + ready() once + channel.send once — then reaches scheduler.start()."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)

    ready_calls = []
    monkeypatch.setattr(
        daemon_mod.SystemdNotifier, "ready", lambda self: ready_calls.append(1)
    )

    # A stop Event that is never "set" (so the gate's `while not stop.is_set()` runs
    # and probes once, passing on the first call) but whose foreground `wait()`
    # returns immediately so run_daemon returns without blocking. The gate returns
    # True on the first pass BEFORE it ever calls wait(), so the online signal fires
    # and `scheduler.start()` is reached.
    class _NeverSetImmediateWait:
        def is_set(self):
            return False

        def set(self):
            pass

        def wait(self, timeout=None):
            return True

    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)

    channel = _OnlinePingChannel()
    rc = daemon_mod.run_daemon(
        config=_no_slot_config(), settings=None, db_path=tmp_db, channel=channel
    )

    assert rc == 0
    assert sched.started is True  # scheduler reached after the gate passed
    assert ready_calls == [1]  # READY=1 sent exactly once
    assert len(channel.sent_text) == 1  # one-time Discord online ping
    # Fixed literal — no template/user interpolation (T-05-T markdown-injection-safe).
    assert "online" in channel.sent_text[0].lower()
    reason, _detail = _read_health(tmp_db)
    assert reason == PASS  # health row flipped to online


class _NeverSetImmediateWait:
    """A stop Event that never reports set and whose foreground wait() returns at once.

    The gate's ``while not stop.is_set()`` probes once and passes, then run_daemon's
    ``stop.wait()`` returns immediately so the call returns without blocking.
    """

    def is_set(self):
        return False

    def set(self):
        pass

    def wait(self, timeout=None):
        return True


class _StopDuringWait:
    """A stop Event that is UNSET at the top of the gate loop (so the daemon probes
    once and stamps health) but whose re-probe ``wait()`` sets itself and returns True
    — the realistic "systemctl stop during the re-probe loop" clean-shutdown path.

    Module-level so the Phase 29 fatal/clean/auth tests can reuse it (the original
    lives as a local class inside test_gate_stop_stays_alive_then_clean_exit_no_online).
    """

    def __init__(self):
        self._set = False

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def wait(self, timeout=None):
        self._set = True  # stop arrives during the re-probe wait
        return True


def test_online_ping_built_from_settings_when_channel_none(tmp_db, monkeypatch):
    """REGRESSION (UAT 05-01 gap): the production --run shape — channel OMITTED
    (defaults to None) + settings PRESENT — must still deliver the one-time online
    ping by building the channel from config+settings (mirrors send_now). Every
    pre-existing online test INJECTS a channel, so none exercised this None path —
    which is exactly where the gap hid (cli.py:480 calls run_daemon without channel=).
    """
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)

    ready_calls = []
    monkeypatch.setattr(
        daemon_mod.SystemdNotifier, "ready", lambda self: ready_calls.append(1)
    )
    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)

    # Stub the LAZY build site run_daemon resolves to (`from weatherbot.channels
    # import build_channel`) — patch the name at its source module, NOT a channel
    # arg. Record invocation so we prove the None path actually built the channel.
    stub_channel = _OnlinePingChannel()
    build_calls: list[int] = []

    def _fake_build(config, settings):
        build_calls.append(1)
        return stub_channel

    monkeypatch.setattr("weatherbot.channels.build_channel", _fake_build)

    # Exact production shape: channel OMITTED (defaults to None), settings PRESENT.
    # A truthy sentinel suffices since run_self_check and build_channel are stubbed
    # and never touch settings' real attributes.
    rc = daemon_mod.run_daemon(
        config=_no_slot_config(), settings=object(), db_path=tmp_db
    )

    assert rc == 0
    assert sched.started is True  # gate passed, scheduler reached
    assert build_calls == [1]  # the None path built the channel from settings
    assert len(stub_channel.sent_text) == 1  # the online ping WAS delivered
    assert "online" in stub_channel.sent_text[0].lower()  # fixed literal (T-05-T)


def test_injected_channel_skips_build(tmp_db, monkeypatch):
    """An explicitly-injected channel WINS: build_channel must NOT be called, and the
    injected channel receives the online ping (guards the additive None path against a
    future refactor that always builds, keeping injected tests deterministic)."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.SystemdNotifier, "ready", lambda self: None)
    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)

    def _must_not_build(config, settings):
        raise AssertionError(
            "build_channel must not be called when channel is injected"
        )

    monkeypatch.setattr("weatherbot.channels.build_channel", _must_not_build)

    injected = _OnlinePingChannel()
    # settings present too, to prove the injected channel wins even when a build
    # would otherwise be possible.
    rc = daemon_mod.run_daemon(
        config=_no_slot_config(),
        settings=object(),
        db_path=tmp_db,
        channel=injected,
    )

    assert rc == 0
    assert sched.started is True
    assert len(injected.sent_text) == 1  # injected channel got the ping
    assert "online" in injected.sent_text[0].lower()


# --- Plan 11-04 / CMD-08 / T-11-11/T-11-12: inbound BotThread daemon lifecycle ---


class _FakeSettingsWithToken:
    """A settings stand-in carrying just the bot token the daemon reads.

    ``run_daemon`` builds the channel from settings (stubbed away here) and reads
    ``settings.discord_bot_token`` to construct the BotThread. The self-check and
    build_channel are stubbed, so no other settings attribute is touched.
    """

    discord_bot_token = "fake-bot-token"  # noqa: S105 — not a real secret, test stub


def _bot_config():
    """A config WITH a ``[bot]`` section (operator_id + panel_channel_id) and no enabled slots."""
    return Config(
        locations=[
            Location(name="Home", lat=40.0, lon=-74.0, timezone="UTC", schedule=[])
        ],
        bot=BotConfig(operator_id=12345, panel_channel_id=67890),
    )


def test_bot_thread_starts_strictly_after_online_signal(tmp_db, monkeypatch):
    """T-11-12 / Pitfall 4: with a ``[bot]`` config AND settings present, run_daemon
    starts the inbound BotThread STRICTLY AFTER emit_online/notifier.ready() — a bot
    failure can never delay or gate the systemd READY signal. Asserts the recorded
    order: ready() happens before the BotThread is started."""
    import weatherbot.scheduler.daemon as daemon_mod
    import weatherbot.scheduler.wiring as wiring_mod
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)

    # Record the global startup ORDER across emit_online's ready() and the bot start.
    order: list[str] = []
    monkeypatch.setattr(
        daemon_mod.SystemdNotifier, "ready", lambda self: order.append("ready")
    )

    # Build_channel stubbed so the settings sentinel never needs real channel fields.
    monkeypatch.setattr(
        "weatherbot.channels.build_channel",
        lambda config, settings: _OnlinePingChannel(),
    )

    started = []

    class _RecordingBotThread:
        def __init__(
            self,
            token,
            *,
            holder,
            operator_id,
            cache,
            daemon_state=None,
        ):
            self.token = token
            self.operator_id = operator_id
            self.daemon_state = daemon_state

        def start(self):
            order.append("bot_start")
            started.append(self)

        def stop(self, timeout=5.0):
            order.append("bot_stop")

    # Patch the COMPOSITION ROOT factory: post-Phase-27 (SEAM-07) run_daemon constructs
    # the bot via `from weatherbot.scheduler.wiring import build_inbound_bot` (a call-time
    # import resolving the name on the wiring module), so the mock injection point moved
    # here. The fake's ctor matches build_inbound_bot(token, *, holder, operator_id, cache,
    # daemon_state) and returns the recording stand-in (start/stop), a drop-in for the bot.
    monkeypatch.setattr(wiring_mod, "build_inbound_bot", _RecordingBotThread)

    rc = daemon_mod.run_daemon(
        config=_bot_config(),
        settings=_FakeSettingsWithToken(),
        db_path=tmp_db,
    )

    assert rc == 0
    assert sched.started is True  # gate passed, scheduler reached
    # The bot was started exactly once, with the configured operator_id + token ...
    assert len(started) == 1
    assert started[0].operator_id == 12345
    assert started[0].token == "fake-bot-token"  # noqa: S105 — test stub
    # ... and STRICTLY AFTER the online READY signal (the load-bearing ordering).
    assert "ready" in order and "bot_start" in order
    assert order.index("ready") < order.index("bot_start")


def test_run_daemon_threads_read_only_daemon_state_into_bot(tmp_db, monkeypatch):
    """CMD-12 / D-02: run_daemon constructs a read-only DaemonState (scheduler, holder,
    db_path, started_at, bot_alive) and threads it into the BotThread so the Discord
    ``status`` command works on the live daemon. Asserts the bot received a non-None
    DaemonState carrying the live scheduler + db_path and a callable bot_alive."""
    import weatherbot.scheduler.daemon as daemon_mod
    import weatherbot.scheduler.wiring as wiring_mod
    from weatherbot.interactive.state import DaemonState
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)
    monkeypatch.setattr(daemon_mod.SystemdNotifier, "ready", lambda self: None)
    monkeypatch.setattr(
        "weatherbot.channels.build_channel",
        lambda config, settings: _OnlinePingChannel(),
    )

    captured = {}

    class _CapturingBotThread:
        def __init__(
            self,
            token,
            *,
            holder,
            operator_id,
            cache,
            daemon_state=None,
        ):
            captured["daemon_state"] = daemon_state

        def start(self):
            pass

        def stop(self, timeout=5.0):
            pass

    monkeypatch.setattr(wiring_mod, "build_inbound_bot", _CapturingBotThread)

    rc = daemon_mod.run_daemon(
        config=_bot_config(),
        settings=_FakeSettingsWithToken(),
        db_path=tmp_db,
    )

    assert rc == 0
    ds = captured["daemon_state"]
    # A read-only DaemonState was threaded in (not None) carrying the live wiring.
    assert isinstance(ds, DaemonState)
    assert ds.scheduler is sched  # the LIVE scheduler (for next-send)
    assert ds.db_path == tmp_db  # the daemon db (for last-briefing heartbeat)
    assert callable(ds.bot_alive)  # bot-liveness callable
    # Read-only invariant: DaemonState exposes no scheduler-mutation / store-write API.
    for forbidden in ("add_job", "remove_job", "replace", "persist", "stamp_success"):
        assert not hasattr(ds, forbidden)


def test_bot_thread_start_failure_is_isolated_from_daemon(tmp_db, monkeypatch):
    """T-11-11: a BotThread whose ``start()`` RAISES at construction/startup must NOT
    take the daemon down — the failure is swallowed (logged + proceed), the scheduler
    still ran, READY was still sent, and run_daemon returns 0. The briefing path is
    untouched by a dead inbound bot (D-11)."""
    import weatherbot.scheduler.daemon as daemon_mod
    import weatherbot.scheduler.wiring as wiring_mod
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)

    ready_calls = []
    monkeypatch.setattr(
        daemon_mod.SystemdNotifier, "ready", lambda self: ready_calls.append(1)
    )
    channel = _OnlinePingChannel()
    monkeypatch.setattr(
        "weatherbot.channels.build_channel", lambda config, settings: channel
    )

    class _ExplodingBotThread:
        def __init__(
            self,
            token,
            *,
            holder,
            operator_id,
            cache,
            daemon_state=None,
        ):
            raise RuntimeError("bot failed to construct/start")

        def stop(self, timeout=5.0):  # pragma: no cover — never reached (bot is None)
            raise AssertionError("stop() must not be called on a failed-start bot")

    monkeypatch.setattr(wiring_mod, "build_inbound_bot", _ExplodingBotThread)

    # The exploding bot must NOT propagate out of run_daemon.
    rc = daemon_mod.run_daemon(
        config=_bot_config(),
        settings=_FakeSettingsWithToken(),
        db_path=tmp_db,
    )

    assert rc == 0  # daemon completed its run despite the bot failure
    assert sched.started is True  # scheduler still started (briefing path untouched)
    assert ready_calls == [1]  # READY still sent exactly once
    assert len(channel.sent_text) == 1  # online ping still delivered


def test_no_bot_thread_started_without_bot_config(tmp_db, monkeypatch):
    """Guard correctness: a config WITHOUT a ``[bot]`` section starts NO BotThread even
    when settings are present — the bot is opt-in via the config table (CFG-07). Proves
    the ``config.bot is not None`` guard, so a bot-less deployment never spins up the
    gateway thread."""
    import weatherbot.scheduler.daemon as daemon_mod
    import weatherbot.scheduler.wiring as wiring_mod
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)
    monkeypatch.setattr(daemon_mod.SystemdNotifier, "ready", lambda self: None)
    monkeypatch.setattr(
        "weatherbot.channels.build_channel",
        lambda config, settings: _OnlinePingChannel(),
    )

    constructed = []

    class _MustNotConstructBotThread:
        def __init__(self, *a, **k):
            constructed.append(1)

    monkeypatch.setattr(wiring_mod, "build_inbound_bot", _MustNotConstructBotThread)

    # _no_slot_config() has NO [bot] section; settings present so the guard's AND
    # is exercised (settings is not the thing that gates here — the bot config is).
    rc = daemon_mod.run_daemon(
        config=_no_slot_config(),
        settings=_FakeSettingsWithToken(),
        db_path=tmp_db,
    )

    assert rc == 0
    assert sched.started is True
    assert constructed == []  # NO BotThread constructed without a [bot] config


def test_gate_auth_failed_then_ok_stays_alive(tmp_db, monkeypatch):
    """auth stays alive: an auth_failed result does NOT crash the daemon — it logs
    CRITICAL, stamps health auth_failed, re-probes, then comes online (D-04)."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import AUTH_FAILED, CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    results = iter(
        [
            CheckResult(ok=False, reason=AUTH_FAILED, detail="401"),
            CheckResult(ok=True, reason=PASS),
        ]
    )
    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: next(results),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)

    ready_calls = []
    monkeypatch.setattr(
        daemon_mod.SystemdNotifier, "ready", lambda self: ready_calls.append(1)
    )

    # An Event whose wait() always returns False (never stop) so the gate loops to
    # the second (passing) probe — then a pre-set stop for the foreground block.
    class _LoopThenStop:
        def __init__(self):
            self._set = False

        def is_set(self):
            return self._set

        def set(self):
            self._set = True

        def wait(self, timeout=None):
            # Re-probe wait: never set during the gate (returns False -> keep looping).
            # The foreground stop.wait() after start() also returns False here, but
            # we set the flag so run_daemon's loop and final wait both terminate.
            return self._set

    # Two events would be created (one per run_daemon). Reuse a single instance whose
    # wait() returns False during the gate; we flip _set after start via a stubbed
    # scheduler.start so the foreground wait returns.
    ev = _LoopThenStop()

    def _start():
        sched.started = True
        ev.set()  # so the post-start foreground stop.wait() returns immediately

    sched.start = _start  # type: ignore[method-assign]
    monkeypatch.setattr(daemon_mod.threading, "Event", lambda: ev)

    critical_logged = []
    real_critical = daemon_mod._log.critical
    monkeypatch.setattr(
        daemon_mod._log,
        "critical",
        lambda *a, **k: critical_logged.append((a, k)) or real_critical(*a, **k),
    )

    channel = _OnlinePingChannel()
    rc = daemon_mod.run_daemon(
        config=_no_slot_config(), settings=None, db_path=tmp_db, channel=channel
    )

    assert rc == 0  # did NOT sys.exit / raise on the auth failure
    assert sched.started is True  # eventually came online and started
    assert ready_calls == [1]
    assert len(channel.sent_text) == 1
    assert critical_logged  # auth failure logged CRITICAL
    reason, _detail = _read_health(tmp_db)
    assert reason == PASS  # final state online after the recovering re-probe


# --- FCAST-06: scheduled forecast slots wired into the scheduler spine ------
#
# Plan 13-05 Task 1: a single namespaced ``_forecast_job_id`` helper feeds BOTH
# ``_register_jobs`` and ``_desired_job_ids`` (so they can never drift, Pitfall 4);
# enabled forecast slots register cron jobs at the location tz; a disabled slot
# registers none; a no-op reload is churn-free; a variant edit diffs as ADD+REMOVE;
# and a forecast id can never collide with a briefing id at the same time/days.


def _forecast_config(
    *,
    kind: str = "weekday",
    variant: str = "detailed",
    time: str = "06:30",
    days: str = "mon-fri",
    enabled: bool = True,
    with_briefing: bool = False,
):
    """A single-location Config carrying one ForecastSchedule slot (+ optional briefing).

    ``with_briefing`` adds a briefing slot at the SAME time/days so the collision
    test can assert the ``|fc|`` namespace keeps the two ids distinct.
    """
    from weatherbot.config.models import ForecastSchedule

    schedule = []
    if with_briefing:
        schedule = [Schedule(time=time, days=days)]
    return Config(
        locations=[
            Location(
                name="Home",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
                schedule=schedule,
                forecast=[
                    ForecastSchedule(
                        kind=kind,
                        variant=variant,
                        time=time,
                        days=days,
                        enabled=enabled,
                    )
                ],
            )
        ],
    )


def test_forecast_slot_registers_cron_job_at_location_tz(tmp_db, load_fixture):
    from apscheduler.schedulers.background import BackgroundScheduler
    from weatherbot.scheduler.daemon import _forecast_job_id, _register_jobs

    cfg = _forecast_config(kind="weekday", variant="detailed", time="06:30")
    fc = cfg.locations[0].forecast[0]
    scheduler = BackgroundScheduler()
    _register_jobs(
        scheduler,
        ConfigHolder(cfg),
        db_path=tmp_db,
        settings=None,
        client=_FakeClient(
            load_fixture("onecall_imperial_clear.json"),
            load_fixture("onecall_metric_clear.json"),
        ),
        channel=_FakeChannel(),
    )

    jobs = {j.id: j for j in scheduler.get_jobs()}
    fc_id = _forecast_job_id(cfg.locations[0], fc)
    assert "|fc|" in fc_id
    assert fc_id in jobs
    # The forecast trigger is pinned to the LOCATION's own IANA zone (FCAST-06).
    assert str(jobs[fc_id].trigger.timezone) == "America/New_York"


def test_disabled_forecast_slot_registers_no_job(tmp_db):
    from apscheduler.schedulers.background import BackgroundScheduler
    from weatherbot.scheduler.daemon import _forecast_job_id, _register_jobs

    cfg = _forecast_config(enabled=False)
    fc = cfg.locations[0].forecast[0]
    scheduler = BackgroundScheduler()
    _register_jobs(
        scheduler,
        ConfigHolder(cfg),
        db_path=tmp_db,
        settings=None,
    )
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert _forecast_job_id(cfg.locations[0], fc) not in job_ids


def test_desired_job_ids_includes_forecast_via_same_helper(tmp_db):
    from weatherbot.scheduler.daemon import _desired_job_ids, _forecast_job_id

    cfg = _forecast_config()
    fc = cfg.locations[0].forecast[0]
    desired = _desired_job_ids(ConfigHolder(cfg))
    # Byte-for-byte the SAME id the helper builds (no drift between the two sites).
    assert _forecast_job_id(cfg.locations[0], fc) in desired

    # A disabled slot is absent from the desired set (mirrors the enabled filter).
    cfg_off = _forecast_config(enabled=False)
    assert _forecast_job_id(
        cfg_off.locations[0], cfg_off.locations[0].forecast[0]
    ) not in _desired_job_ids(ConfigHolder(cfg_off))


def test_forecast_noop_reload_is_churn_free(tmp_db):
    from apscheduler.schedulers.background import BackgroundScheduler
    from weatherbot.scheduler.daemon import _reconcile_jobs, _register_jobs

    cfg = _forecast_config()
    holder = ConfigHolder(cfg)
    scheduler = BackgroundScheduler()
    _register_jobs(scheduler, holder, db_path=tmp_db, settings=None)

    # An identical config reconciled against the live set produces ZERO churn for
    # the forecast job (Pitfall 4): the stable id matches, so it is UNCHANGED.
    added, removed, changed, unchanged = _reconcile_jobs(
        scheduler, holder, db_path=tmp_db, settings=None
    )
    assert added == 0
    assert removed == 0
    assert unchanged == 1


def test_forecast_variant_edit_diffs_as_add_and_remove(tmp_db):
    from apscheduler.schedulers.background import BackgroundScheduler
    from weatherbot.scheduler.daemon import _reconcile_jobs, _register_jobs

    old = _forecast_config(variant="detailed")
    holder = ConfigHolder(old)
    scheduler = BackgroundScheduler()
    _register_jobs(scheduler, holder, db_path=tmp_db, settings=None)

    # Editing the variant (detailed -> compact) changes the id (it embeds variant),
    # so the reconcile surfaces exactly one ADD (new id) + one REMOVE (old id).
    holder.replace(_forecast_config(variant="compact"))
    added, removed, changed, unchanged = _reconcile_jobs(
        scheduler, holder, db_path=tmp_db, settings=None
    )
    assert added == 1
    assert removed == 1


def test_forecast_id_never_collides_with_briefing_id(tmp_db):
    from weatherbot.scheduler.daemon import _desired_job_ids, _forecast_job_id

    # A briefing AND a forecast at the SAME time/days: the |fc| namespace keeps the
    # two ids DISTINCT (Pitfall 4 anti-collision contract).
    cfg = _forecast_config(time="07:00", days="mon-fri", with_briefing=True)
    loc = cfg.locations[0]
    briefing_id = f"{loc.name}|{loc.schedule[0].time}|{loc.schedule[0].days}"
    forecast_id = _forecast_job_id(loc, loc.forecast[0])
    assert briefing_id != forecast_id
    desired = _desired_job_ids(ConfigHolder(cfg))
    assert briefing_id in desired
    assert forecast_id in desired


# --- FCAST-05/06: fire_forecast_slot (read-only, failure-isolated) ----------
#
# Plan 13-05 Task 2: a scheduled forecast fire renders via the SAME on-demand
# render path and POSTS to the channel, writing NOTHING to the store; a raising
# fire is isolated (returns None, never propagates); and the forecast templates
# are validated at load/reload and watched for edits.


class _PlainSendChannel:
    """Captures plain ``send(text)`` posts (the scheduled-forecast post path)."""

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self._result = DeliveryResult(ok=True)

    def send(self, text):
        self.sent_text.append(text)
        return self._result

    def send_briefing(self, text, forecast):  # pragma: no cover — forecasts use send()
        raise AssertionError(
            "scheduled forecast must post via send(), not send_briefing()"
        )


# The seven store write functions a read-only forecast fire must never touch.
_STORE_WRITES = (
    "persist",
    "claim_slot",
    "record_alert",
    "resolve_alert",
    "stamp_tick",
    "stamp_success",
    "stamp_health",
)


def test_fire_forecast_slot_posts_and_writes_no_store(
    tmp_db, load_fixture, monkeypatch
):
    from weatherbot.scheduler import daemon as daemon_mod
    from weatherbot.weather import store

    # Trip every store write so ANY store call fails the test (FCAST-05/A1).
    def _boom(*_a, **_k):
        raise AssertionError("scheduled forecast must not write the store (FCAST-05)")

    for fn in _STORE_WRITES:
        monkeypatch.setattr(store, fn, _boom)
        if hasattr(daemon_mod, fn):
            monkeypatch.setattr(daemon_mod, fn, _boom)

    cfg = _forecast_config(kind="weekday", variant="detailed")
    loc = cfg.locations[0]
    fc = loc.forecast[0]
    client = _FakeClient(
        load_fixture("onecall_8day_imperial.json"),
        load_fixture("onecall_8day_metric.json"),
    )
    channel = _PlainSendChannel()

    result = daemon_mod.fire_forecast_slot(
        loc,
        fc,
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=channel,
    )
    assert result is None  # the callback returns None on success (no DeliveryResult)
    assert len(channel.sent_text) == 1  # exactly one POST to the channel
    assert channel.sent_text[0].strip()  # non-empty rendered forecast


def test_fire_forecast_slot_isolates_exception(tmp_db, monkeypatch):
    from weatherbot.scheduler import daemon as daemon_mod

    # A render that raises must be swallowed (log + return None) so one bad forecast
    # cannot crash the scheduler thread (UV-06-style isolation, T-13-15).
    cfg = _forecast_config()
    loc = cfg.locations[0]
    fc = loc.forecast[0]

    class _BoomClient:
        def fetch_onecall(self, location, units):
            raise RuntimeError("forecast fetch boom")

    channel = _PlainSendChannel()
    result = daemon_mod.fire_forecast_slot(
        loc,
        fc,
        config=cfg,
        db_path=tmp_db,
        client=_BoomClient(),
        channel=channel,
    )
    assert result is None  # did NOT propagate
    assert channel.sent_text == []  # nothing posted on a failed render


def test_chronically_dead_forecast_slot_alerts_once_throttled(tmp_db, monkeypatch):
    """WR-05: a slot that fails every fire emits a THROTTLED operator alert.

    A one-off transient failure stays silent (only a log); once consecutive
    failures cross the dead-slot threshold, a single best-effort operator channel
    notice is posted (once per dead-streak, not on every subsequent failure), while
    the failure is STILL swallowed (isolation from the briefing spine untouched).
    """
    from weatherbot.scheduler import daemon as daemon_mod

    cfg = _forecast_config(kind="weekday", variant="detailed")
    loc = cfg.locations[0]
    fc = loc.forecast[0]

    # Isolate this slot's in-memory streak from any other test's state.
    monkeypatch.setattr(daemon_mod, "_forecast_failure_streaks", {})

    class _BoomClient:
        def fetch_onecall(self, location, units):
            raise RuntimeError("persistent forecast fetch failure")

    channel = _PlainSendChannel()

    def _fire():
        return daemon_mod.fire_forecast_slot(
            loc, fc, config=cfg, db_path=tmp_db, client=_BoomClient(), channel=channel
        )

    dead_after = daemon_mod._FORECAST_DEAD_AFTER
    # The first (dead_after - 1) failures are treated as transient — NO alert posted.
    for _ in range(dead_after - 1):
        assert _fire() is None  # always isolated (never propagates)
    assert channel.sent_text == []

    # The crossing fire posts exactly ONE operator alert.
    assert _fire() is None
    assert len(channel.sent_text) == 1
    assert loc.name in channel.sent_text[0]

    # Subsequent failures are throttled — no additional alerts (still isolated).
    for _ in range(3):
        assert _fire() is None
    assert len(channel.sent_text) == 1


def test_forecast_success_resets_failure_streak(tmp_db, load_fixture, monkeypatch):
    """WR-05: a clean delivery resets the streak so the alert counts only a
    CONSECUTIVE run of failures, never a scattered transient blip."""
    from weatherbot.scheduler import daemon as daemon_mod

    cfg = _forecast_config(kind="weekday", variant="detailed")
    loc = cfg.locations[0]
    fc = loc.forecast[0]
    monkeypatch.setattr(daemon_mod, "_forecast_failure_streaks", {})

    good_client = _FakeClient(
        load_fixture("onecall_8day_imperial.json"),
        load_fixture("onecall_8day_metric.json"),
    )

    class _BoomClient:
        def fetch_onecall(self, location, units):
            raise RuntimeError("boom")

    channel = _PlainSendChannel()
    dead_after = daemon_mod._FORECAST_DEAD_AFTER

    # Fail almost-to-threshold, then succeed: the streak must reset to zero.
    for _ in range(dead_after - 1):
        daemon_mod.fire_forecast_slot(
            loc, fc, config=cfg, db_path=tmp_db, client=_BoomClient(), channel=channel
        )
    daemon_mod.fire_forecast_slot(
        loc, fc, config=cfg, db_path=tmp_db, client=good_client, channel=channel
    )
    assert (
        daemon_mod._forecast_failure_streaks.get(
            daemon_mod._forecast_job_id(loc, fc), 0
        )
        == 0
    )

    # A subsequent SINGLE failure must NOT alert (streak restarted from zero).
    posts_before = len(channel.sent_text)
    daemon_mod.fire_forecast_slot(
        loc, fc, config=cfg, db_path=tmp_db, client=_BoomClient(), channel=channel
    )
    assert len(channel.sent_text) == posts_before  # no dead-slot alert yet


class _FailingSendChannel:
    """A channel whose ``send`` DELIVERS a non-ok DeliveryResult (a Discord non-2xx).

    Unlike a raising channel, ``send`` returns normally with ``ok=False`` — the
    forecast path must INSPECT that result and treat it as a failure (F08), not
    silently reset the streak. ``send_text`` captures every post so a test can
    distinguish the (ok=False) forecast POST from a dead-slot OPERATOR alert POST.
    """

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self._result = DeliveryResult(ok=False, detail="503 upstream")

    def send(self, text):
        self.sent_text.append(text)
        return self._result

    def send_briefing(self, text, forecast):  # pragma: no cover — forecasts use send()
        raise AssertionError(
            "scheduled forecast must post via send(), not send_briefing()"
        )


def test_forecast_delivery_failure_escalates(tmp_db, load_fixture, monkeypatch):
    """F08 (HARD-DELIV-02, D-02): a forecast ``send`` that returns ``ok=False`` is a
    FAILURE — it advances the dead-slot streak instead of resetting it.

    ``fire_forecast_slot`` today discards the ``DeliveryResult`` and unconditionally
    calls ``_note_forecast_success``, so a Discord ``ok=False`` resets the streak and
    the WR-05 dead-slot CRITICAL escalation NEVER fires. This test drives
    ``_FORECAST_DEAD_AFTER`` consecutive clean-fetch-but-ok=False deliveries and
    asserts the streak crosses the dead-slot threshold (an operator alert is posted
    and ``_note_forecast_success`` was NOT called). It FAILS against pre-fix daemon.py
    (the streak never advances) and PASSES once ``ok=False`` routes to
    ``_note_forecast_failure``.
    """
    from weatherbot.scheduler import daemon as daemon_mod

    cfg = _forecast_config(kind="weekday", variant="detailed")
    loc = cfg.locations[0]
    fc = loc.forecast[0]

    # Isolate this slot's in-memory streak from any other test's state.
    monkeypatch.setattr(daemon_mod, "_forecast_failure_streaks", {})

    # A clean fetch/render every time — the ONLY failure is at delivery (ok=False),
    # so this exercises the delivery-result inspection, not the render-raises path.
    good_client = _FakeClient(
        load_fixture("onecall_8day_imperial.json"),
        load_fixture("onecall_8day_metric.json"),
    )
    channel = _FailingSendChannel()

    def _fire():
        return daemon_mod.fire_forecast_slot(
            loc, fc, config=cfg, db_path=tmp_db, client=good_client, channel=channel
        )

    dead_after = daemon_mod._FORECAST_DEAD_AFTER
    job_id = daemon_mod._forecast_job_id(loc, fc)

    # Each ok=False fire posts exactly the forecast text (the failed delivery) and
    # must ADVANCE the streak (never reset it). The first (dead_after - 1) fires are
    # treated as transient — the forecast POST is the only channel traffic.
    for i in range(dead_after - 1):
        assert _fire() is None  # always isolated (never propagates)
        assert daemon_mod._forecast_failure_streaks.get(job_id, 0) == i + 1

    # The crossing fire escalates: the forecast POST PLUS one operator dead-slot
    # alert (both go through send(); count == crossing forecast post + alert).
    posts_before = len(channel.sent_text)
    assert _fire() is None
    assert daemon_mod._forecast_failure_streaks.get(job_id, 0) == dead_after
    # The crossing fire produced 2 posts (the ok=False forecast + the operator
    # alert), where a reset-on-success path would have produced only 1.
    assert len(channel.sent_text) == posts_before + 2
    # The operator alert mentions the location (the WR-05 dead-slot notice).
    assert any(loc.name in t for t in channel.sent_text[posts_before:])


# --- HARD-DELIV-04 (D-04): Discord 401/403 → auth_failed, short-circuit -------


class _AuthRaisingChannel:
    """A channel whose ``send_briefing`` raises the app-side auth carrier.

    Models what ``discord._post`` does on a 401/403 (DELIV-04, Task 4): it raises
    an ``httpx.HTTPStatusError`` carrying a REDACTED placeholder URL (never the
    real webhook) and a ``.response`` whose ``status_code`` is a plain int. This is
    the exact currency ``fire_slot``'s existing ``except httpx.HTTPStatusError``
    arm (daemon.py:263) classifies via ``is_auth_failure`` → ``REASON_AUTH_FAILED``.
    """

    def __init__(self, status: int = 401):
        self._status = status
        self.attempts = 0

    def send_briefing(self, text, forecast):
        import httpx

        self.attempts += 1
        request = httpx.Request("POST", "https://discord/redacted")
        response = httpx.Response(self._status, request=request)
        raise httpx.HTTPStatusError(
            f"discord auth {self._status}", request=request, response=response
        )


def test_discord_auth_short_circuit(tmp_db, load_fixture):
    """DELIV-04 (HARD-DELIV-04, D-04, F48): a permanent Discord send auth failure
    (401/403) maps to ``auth_failed`` and short-circuits the retry in ~1 attempt —
    NOT ``transient_exhausted`` after burning the full ~65-min two-burst schedule.

    A 401/403 raised as ``httpx.HTTPStatusError`` is non-transient, so
    ``build_retrying`` does not retry it: ``fire_slot``'s existing
    ``except httpx.HTTPStatusError`` arm classifies it via ``is_auth_failure`` and
    records ``REASON_AUTH_FAILED`` in exactly one attempt (no sleeps). This test
    fires a slot through the auth-raising channel and asserts the recorded alert
    reason is ``auth_failed`` and the delivery callable ran exactly once.
    """
    import sqlite3

    from weatherbot.reliability import REASON_AUTH_FAILED
    from weatherbot.scheduler.daemon import fire_slot

    cfg = _home_config(days="mon-fri", time="07:00")
    loc = cfg.locations[0]
    slot = loc.schedule[0]
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _AuthRaisingChannel(status=401)
    scheduled = datetime(2026, 6, 10, 7, 0, tzinfo=_NY)

    result = fire_slot(
        loc,
        slot,
        config=cfg,
        db_path=tmp_db,
        client=client,
        channel=channel,
        scheduled_dt=scheduled,
        late=True,
    )

    # The auth error short-circuited: fire_slot returns None (alert path) and the
    # delivery callable ran EXACTLY once (not the full two-burst schedule).
    assert result is None
    assert channel.attempts == 1

    # The recorded alert reason is auth_failed, NOT transient_exhausted.
    conn = sqlite3.connect(tmp_db)
    try:
        reasons = [
            r[0]
            for r in conn.execute(
                "SELECT reason FROM alerts WHERE slot_time=? AND local_date=?",
                ("07:00", "2026-06-10"),
            ).fetchall()
        ]
    finally:
        conn.close()
    assert reasons == [REASON_AUTH_FAILED]


def test_validate_rejects_bad_forecast_template(tmp_path):
    from weatherbot.config.loader import validate_config_and_templates

    # A config whose forecast slot references a template with a typo'd {token} must
    # be rejected at load (keep-old at reload, Pitfall 5/T-13-17). Point the loader at
    # a templates dir holding a GOOD briefing template + a BAD forecast template.
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / "briefing.txt").write_text("{location}: {temp}", encoding="utf-8")
    # weekday-detailed whole-message + a BAD per-day line (unknown {nope} token).
    (tdir / "forecast-weekday-detailed.txt").write_text(
        "{title}\n{days}", encoding="utf-8"
    )
    (tdir / "forecast-weekday-detailed.line.txt").write_text(
        "{label}: {nope}", encoding="utf-8"
    )

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "\n".join(
            [
                'template = "briefing.txt"',
                "[[locations]]",
                'name = "Home"',
                "lat = 40.7128",
                "lon = -74.006",
                'timezone = "America/New_York"',
                "[[locations.forecast]]",
                'kind = "weekday"',
                'variant = "detailed"',
                'time = "06:30"',
                'days = "mon-fri"',
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        validate_config_and_templates(cfg_path, templates_dir=tdir)


def test_watch_filter_matches_forecast_template_edit(tmp_path):
    from weatherbot.scheduler.daemon import _make_watch_filter

    cfg = _forecast_config(kind="weekday", variant="detailed")
    config_path = tmp_path / "config.toml"
    filt = _make_watch_filter(cfg, config_path)

    # Editing the referenced forecast whole-message template triggers a reload.
    assert filt(None, str(tmp_path / "forecast-weekday-detailed.txt")) is True
    # ... and its sibling per-day line template too.
    assert filt(None, str(tmp_path / "forecast-weekday-detailed.line.txt")) is True
    # An unrelated file (e.g. .env) is still rejected (secrets boundary unchanged).
    assert filt(None, str(tmp_path / ".env")) is False


def test_derive_watch_dirs_unchanged_includes_templates_dir(tmp_path):
    from weatherbot.scheduler.daemon import _derive_watch_dirs

    cfg = _forecast_config()
    dirs = _derive_watch_dirs(cfg, tmp_path / "config.toml")
    # The config dir is always present; the templates dir is added for the forecast
    # templates exactly as it is for the briefing template (no regression).
    assert (tmp_path).resolve() in dirs


# --- UV-04/UV-06: __uvmonitor__ IntervalTrigger registration + reconcile ----


def _uv_config(monitor_enabled: bool = True, interval_seconds: int = 900):
    """A single-location Config with a tunable [uv] monitor section (15-03 wiring)."""
    from weatherbot.config.models import UvConfig

    return Config(
        locations=[
            Location(
                name="Home",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
                schedule=[Schedule(time="07:00", days="mon-fri")],
            ),
        ],
        uv=UvConfig(monitor_enabled=monitor_enabled, interval_seconds=interval_seconds),
    )


def test_uvmonitor_job_registered_when_enabled(tmp_db):
    """UV-04: monitor_enabled=True registers a __uvmonitor__ IntervalTrigger job."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    from weatherbot.scheduler.daemon import _register_uvmonitor_job
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    holder = ConfigHolder(_uv_config(monitor_enabled=True, interval_seconds=600))
    client = _FakeClient({}, {})
    channel = _FakeChannel()
    scheduler = BackgroundScheduler()
    _register_uvmonitor_job(
        scheduler,
        holder,
        db_path=tmp_db,
        settings=None,
        client=client,
        channel=channel,
    )

    job = scheduler.get_job("__uvmonitor__")
    assert job is not None
    assert isinstance(job.trigger, IntervalTrigger)
    # The interval is baked from snapshot.uv.interval_seconds at registration (DP-2).
    assert job.trigger.interval == timedelta(seconds=600)
    # The callback is exactly Plan 15-02's tick.
    assert job.func is _uv_monitor_tick
    # The existing daemon instances are threaded through verbatim (one per process).
    assert job.kwargs["holder"] is holder
    assert job.kwargs["db_path"] == tmp_db
    assert job.kwargs["settings"] is None
    assert job.kwargs["client"] is client
    assert job.kwargs["channel"] is channel


def test_uvmonitor_job_absent_when_disabled(tmp_db, load_fixture):
    """UV-04: monitor_enabled=False registers NO __uvmonitor__ job (briefing intact)."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from weatherbot.scheduler.daemon import _register_jobs, _register_uvmonitor_job

    holder = ConfigHolder(_uv_config(monitor_enabled=False))
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()
    scheduler = BackgroundScheduler()
    # The briefing jobs still register (the monitor gate is independent of them).
    _register_jobs(
        scheduler,
        holder,
        db_path=tmp_db,
        settings=None,
        client=client,
        channel=channel,
    )
    _register_uvmonitor_job(
        scheduler,
        holder,
        db_path=tmp_db,
        settings=None,
        client=client,
        channel=channel,
    )

    assert scheduler.get_job("__uvmonitor__") is None
    # Home's single enabled mon-fri slot still produced its briefing job.
    assert scheduler.get_job("Home|07:00|mon-fri") is not None


def test_uvmonitor_job_apscheduler_kwargs(tmp_db):
    """UV-04/Pitfall 4: max_instances=1, misfire_grace_time=None, coalesce=True."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from weatherbot.scheduler.daemon import _register_uvmonitor_job

    holder = ConfigHolder(_uv_config(monitor_enabled=True))
    scheduler = BackgroundScheduler()
    _register_uvmonitor_job(
        scheduler,
        holder,
        db_path=tmp_db,
        settings=None,
        client=_FakeClient({}, {}),
        channel=_FakeChannel(),
    )

    job = scheduler.get_job("__uvmonitor__")
    assert job is not None
    assert job.max_instances == 1
    assert job.misfire_grace_time is None
    assert job.coalesce is True


def test_uvmonitor_survives_reconcile_pass(tmp_db, load_fixture):
    """UV-06/T-15-11: a reload (_reconcile_jobs) never removes or duplicates the monitor.

    The __uvmonitor__ job must be excluded by id exactly like __heartbeat__ so a
    config reload leaves it alone — and the briefing jobs reconcile normally around it.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from weatherbot.scheduler.daemon import (
        _reconcile_jobs,
        _register_jobs,
        _register_uvmonitor_job,
    )

    holder = ConfigHolder(_uv_config(monitor_enabled=True))
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )
    channel = _FakeChannel()
    scheduler = BackgroundScheduler()
    _register_jobs(
        scheduler, holder, db_path=tmp_db, settings=None, client=client, channel=channel
    )
    _register_uvmonitor_job(
        scheduler, holder, db_path=tmp_db, settings=None, client=client, channel=channel
    )

    before = scheduler.get_job("__uvmonitor__")
    assert before is not None
    briefing_id = "Home|07:00|mon-fri"
    assert scheduler.get_job(briefing_id) is not None

    # A reload pass over the SAME config: the monitor must be left untouched (not
    # counted in the desired/live diff), and the briefing job rides the holder swap.
    _reconcile_jobs(
        scheduler, holder, db_path=tmp_db, settings=None, client=client, channel=channel
    )

    # Exactly one monitor job survives — never removed, never duplicated.
    monitor_jobs = [j for j in scheduler.get_jobs() if j.id == "__uvmonitor__"]
    assert len(monitor_jobs) == 1
    assert scheduler.get_job(briefing_id) is not None


def test_raising_uvmonitor_tick_never_stops_scheduler():
    """UV-06/T-15-10: a raising __uvmonitor__ tick is isolated at the scheduler level.

    Register a monitor-shaped IntervalTrigger job whose callback raises immediately,
    alongside a sentinel interval job. Start a REAL BackgroundScheduler briefly and
    assert: (a) the sentinel still fires, (b) the scheduler stays running, (c) an
    EVENT_JOB_ERROR is observed for the raising job — i.e. APScheduler 3.x caught the
    exception, logged it, and kept every other job + the scheduler thread alive. This
    complements 15-02's in-tick envelope (the tick body never raises) by proving the
    scheduler survives even if it somehow did.
    """
    import threading
    import time

    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    sentinel_fired = threading.Event()
    monitor_errored = threading.Event()

    def _raising_monitor():
        raise RuntimeError("uv monitor boom")

    def _sentinel():
        sentinel_fired.set()

    scheduler = BackgroundScheduler()

    def _listener(event):
        if event.job_id == "__uvmonitor__" and event.exception is not None:
            monitor_errored.set()

    scheduler.add_listener(_listener, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)
    # The monitor-shaped job mirrors the real registration (id + max_instances=1).
    scheduler.add_job(
        _raising_monitor,
        trigger=IntervalTrigger(seconds=0.1),
        id="__uvmonitor__",
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _sentinel,
        trigger=IntervalTrigger(seconds=0.1),
        id="__sentinel__",
        misfire_grace_time=None,
        coalesce=True,
    )
    scheduler.start()
    try:
        # Give both jobs a few intervals to fire.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not (
            sentinel_fired.is_set() and monitor_errored.is_set()
        ):
            time.sleep(0.05)

        # (a) the sentinel still executed despite the monitor raising every tick.
        assert sentinel_fired.is_set()
        # (b) the scheduler thread is still alive — the raise did not kill it.
        assert scheduler.running is True
        # (c) APScheduler caught the monitor raise (EVENT_JOB_ERROR), not propagated.
        assert monitor_errored.is_set()
        # Both jobs are still scheduled — neither was removed by the raise.
        assert scheduler.get_job("__uvmonitor__") is not None
        assert scheduler.get_job("__sentinel__") is not None
    finally:
        scheduler.shutdown(wait=False)


def test_hanging_callback_never_stops_live_briefing(monkeypatch):
    """PANEL-11/T-20-01 (D-08/D-08a): a *hanging* panel callback never stops the briefing.

    This closes the **hanging** half of the milestone's load-bearing failure-isolation
    guarantee against a *live* ``BackgroundScheduler`` — the exact mirror of
    ``test_raising_uvmonitor_tick_never_stops_scheduler`` (which proves the *raising*
    half). A real sentinel briefing job (sub-second ``IntervalTrigger``) STILL fires on
    time and the scheduler stays running while a panel ``on_command`` callback is provably
    wedged on a never-completing ``await``.

    WHY the wedge is ``await``-shaped, not a CPU spin (D-08a, Pitfall 3): every blocking
    panel operation is already off-loop via ``dispatch.py``'s
    ``loop.run_in_executor(None, …)`` (dispatch.py:166-188), so the *realistic* way a panel
    callback hangs is a never-completing ``await`` on the gateway loop — which we model by
    monkeypatching ``panel.dispatch_spec`` to ``await asyncio.Event().wait()``. A
    ``while True: pass`` CPU spin would instead prove GIL-throttling — a *different* thing —
    and is deliberately NOT used. The callback runs via ``asyncio.run`` on a SEPARATE daemon
    thread so it never returns and never blocks the main test thread or scheduler teardown.

    This is the **test-only** proof (D-08): zero production change to the isolation path.
    The briefing runs on APScheduler's OWN OS thread, independent of the gateway loop the
    wedged callback occupies, so the hang cannot delay, drop, or stop it. No callback
    timeout/watchdog (``asyncio.wait_for``) is added to production (D-09 — out of scope).
    """
    import asyncio
    import threading
    import time
    from unittest.mock import AsyncMock, MagicMock

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    # The harness builds the relocated module PanelKit from the app contributors via the
    # centralized _make_panel seam (Phase-27 SEAM-07). _panel() seeds the harness-only
    # panel.dispatch_spec attribute the harness dispatch closure reads at call time, so the
    # wedge monkeypatch below (panel_mod.dispatch_spec) bites the on_command fetch path.
    from tests.test_panel import _make_panel, _panel

    panel_mod = _panel()

    _OPERATOR_ID = 12345

    # --- gateway-free panel stand-ins (no network, no live gateway) ------------ #
    class _FakeLocation:
        def __init__(self, name):
            self.name = name

    class _FakeConfig:
        def __init__(self, names):
            self.locations = [_FakeLocation(n) for n in names]

    class _FakeHolder:
        def __init__(self, names):
            self.config = _FakeConfig(names)

        def current(self):
            return self.config

    class _SpyCache:
        def lookup(
            self, name, config, *suffix
        ):  # never reached — the wedge precedes it
            return None

    view = _make_panel(
        panel_mod,
        holder=_FakeHolder(["home"]),
        cache=_SpyCache(),
        operator_id=_OPERATOR_ID,
    )

    # The wedge: replace the awaited dispatch seam with a coroutine that yields to the
    # loop and NEVER completes on its own (await-shaped per D-08a — not a CPU spin).
    # on_command awaits this inside its non-propagating envelope, so the callback hangs
    # until the test deterministically releases it during teardown (WR-03 cleanup).
    #
    # WR-03: capture the wedge's loop + Event so the test thread can unblock the await
    # via ``loop.call_soon_threadsafe(event.set)`` and join the thread — no dangling
    # daemon thread after the assertions. The handoff dict is populated INSIDE _hang
    # (on the wedge thread) and is safe to read once ``callback_entered`` is set, since
    # that flag is set in the same coroutine AFTER the loop/event are recorded.
    callback_entered = threading.Event()
    wedge_handle: dict = {}

    async def _hang(*args, **kwargs):
        release = asyncio.Event()
        wedge_handle["loop"] = asyncio.get_running_loop()
        wedge_handle["release"] = release
        callback_entered.set()
        await release.wait()  # D-08a: loop-yielding await; released only at teardown

    monkeypatch.setattr(panel_mod, "dispatch_spec", _hang, raising=True)

    interaction = MagicMock(name="discord.Interaction")
    interaction.user.id = _OPERATOR_ID
    interaction.user.bot = False
    interaction.data = {"custom_id": "wb:cmd:sun"}
    interaction.response.edit_message = AsyncMock(name="response.edit_message")
    interaction.response.send_message = AsyncMock(name="response.send_message")
    interaction.response.is_done = MagicMock(return_value=False)
    interaction.edit_original_response = AsyncMock(name="edit_original_response")
    interaction.followup.send = AsyncMock(name="followup.send")

    # Drive the wedged callback on a SEPARATE daemon thread via asyncio.run so it never
    # returns; daemon=True so a never-completing callback can't block test teardown.
    def _drive():
        asyncio.run(view.on_command(interaction, "sun"))

    wedge_thread = threading.Thread(target=_drive, name="panel-wedge", daemon=True)
    wedge_thread.start()
    # Confirm the callback actually entered the never-completing await before we judge
    # the briefing — so "the briefing fired" is measured WHILE the callback is wedged.
    assert callback_entered.wait(timeout=5.0), (
        "panel callback never reached the await wedge"
    )

    # --- live BackgroundScheduler sentinel "briefing" -------------------------- #
    sentinel_fired = threading.Event()
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        lambda: sentinel_fired.set(),
        trigger=IntervalTrigger(seconds=0.1),
        id="__sentinel__",
        misfire_grace_time=None,
        coalesce=True,
    )
    scheduler.start()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not sentinel_fired.is_set():
            time.sleep(0.05)

        # The "briefing" fired on time despite the panel callback being wedged ...
        assert sentinel_fired.is_set()
        # ... and the scheduler thread is still alive (the hang did not stop it).
        assert scheduler.running is True
        # The wedged callback is still hanging (it never returned) — isolation proven.
        assert wedge_thread.is_alive()
    finally:
        # WR-03 cleanup: tear down the scheduler AND deterministically release the
        # wedge so no daemon thread is left dangling — even on an assertion failure
        # above. Releasing the never-completing await lets asyncio.run finish and the
        # thread terminate; we then join + assert it is gone.
        scheduler.shutdown(wait=False)
        loop = wedge_handle.get("loop")
        release = wedge_handle.get("release")
        if loop is not None and release is not None:
            # Cross-thread wake-up: signal the wedge's Event on ITS OWN loop.
            loop.call_soon_threadsafe(release.set)
        wedge_thread.join(timeout=5.0)
        assert not wedge_thread.is_alive(), (
            "WR-03: the wedged panel-callback thread did not terminate after release"
        )


# --------------------------------------------------------------------------- #
# Phase 29 Wave 0 (Plan 29-02): fatal-exit / clean-shutdown / auth-not-fatal /
# F90 announce / F07 ping-order RED scaffolding.
#
# These pin the HARD-STARTUP-02 fatal-vs-clean exit distinction (a config-invalid
# self-check must return a NON-ZERO exit so systemd treats the death as a failure,
# while a clean SIGTERM must return 0), the D-03 regression guard (AUTH_FAILED must
# NEVER be turned fatal — the daemon re-probes a still-propagating key), plus the
# two STARTUP-03 observability corrections (F90 disabled-forecast-slot visibility,
# F07 online-ping-strictly-after-ready ordering).
#
# The production behavior lands in 29-05 (daemon/wiring) + 29-03 (CONFIG_INVALID
# constant), so the impl-dependent cases are xfail(strict=False) until then — RED
# here is SUCCESS. They MUST collect and run without erroring on collection.
#
# They reuse the established stub kit already in this file:
#   - _StartObservableScheduler (records scheduler.start())
#   - _OnlinePingChannel        (records the agnostic send(text) online ping)
#   - _no_slot_config           (no enabled slots -> no jobs, no real client)
#   - _read_health              (reads the health row)
#   - _NeverSetImmediateWait    (a stop Event: probes once, wait() returns at once)
# and structlog.testing.capture_logs (config-independent, matches test_lifecycle).
# --------------------------------------------------------------------------- #


def test_fatal_exit_code(tmp_db, monkeypatch):
    """HARD-STARTUP-02 / T-29-03: a CONFIG_INVALID self-check sets the fatal marker
    and makes run_daemon return a NON-ZERO exit code WITHOUT ever starting the
    scheduler — so systemd sees the death as a failure (restart -> start-limit),
    not a clean exit. The clean-shutdown companion below returns 0 with the marker
    unset; the two together pin the separate-marker distinction (dedicated fatal
    Event, NOT a reuse of ``stop``)."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    # A fatal config-invalid probe. `daemon.CONFIG_INVALID` is resolved through the
    # daemon module object (the daemon-suite monkeypatch/aliasing convention) so the
    # new fatal path bites — it does not yet exist, which is the RED reason pre-29-03.
    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(
            ok=False, reason=daemon_mod.CONFIG_INVALID, detail="ValidationError"
        ),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.SystemdNotifier, "ready", lambda self: None)
    monkeypatch.setattr(daemon_mod.threading, "Event", _StopDuringWait)
    monkeypatch.setattr(
        "weatherbot.channels.build_channel",
        lambda config, settings: _OnlinePingChannel(),
    )

    rc = daemon_mod.run_daemon(
        config=_no_slot_config(), settings=object(), db_path=tmp_db
    )

    assert isinstance(rc, int) and rc != 0  # fatal -> non-zero exit (systemd failure)
    assert sched.started is False  # scheduler NEVER started on the fatal path


def test_clean_shutdown_returns_zero(tmp_db, monkeypatch):
    """HARD-STARTUP-02 / T-29-03: a clean SIGTERM during the gate re-probe loop
    (stop set, fatal marker UNSET) makes run_daemon return 0 — systemd treats the
    death as clean, no restart. This is the NON-fatal companion to
    test_fatal_exit_code; it does NOT depend on the 29-05 impl (it exercises the
    existing NETWORK_NOT_READY re-probe/stop path), so it is NOT xfail — it guards
    that the fatal-exit change never regresses the clean-exit code to non-zero."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult, NETWORK_NOT_READY
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    # Never ready -> the daemon stays alive and re-probes; the stop arrives DURING
    # the re-probe wait (the realistic systemctl-stop shutdown), breaking the loop.
    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(
            ok=False, reason=NETWORK_NOT_READY, detail="ConnectError"
        ),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.SystemdNotifier, "ready", lambda self: None)
    monkeypatch.setattr(daemon_mod.threading, "Event", _StopDuringWait)

    channel = _OnlinePingChannel()
    rc = daemon_mod.run_daemon(
        config=_no_slot_config(), settings=None, db_path=tmp_db, channel=channel
    )

    assert rc == 0  # clean SIGTERM -> exit 0 (marker unset, systemd sees clean exit)
    assert sched.started is False  # gate never passed, scheduler never started


def test_auth_not_fatal(tmp_db, monkeypatch):
    """HARD-STARTUP-02 / D-03 / T-29-05 regression guard: an AUTH_FAILED self-check
    must NOT set the fatal marker and must NOT drive a non-zero exit — a 401/403 is
    a still-propagating key (new OpenWeather keys take up to ~2h to activate), so the
    daemon RE-PROBES rather than dying fatally. Only CONFIG_INVALID is fatal; auth is
    not. We drive the gate with AUTH_FAILED, then let a clean stop end the loop, and
    assert the exit is the clean 0 (fatal marker never set)."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult, AUTH_FAILED
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(
            ok=False, reason=AUTH_FAILED, detail="HTTPStatusError"
        ),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.SystemdNotifier, "ready", lambda self: None)

    # Capture the fatal marker the daemon threads out of build_runtime so we can
    # assert it is NEVER set on the auth path (the load-bearing D-03 guard). The
    # `parts.fatal` Event does not exist until 29-05, so this attribute access is
    # the RED reason pre-impl.
    seen = {}
    import weatherbot.scheduler.wiring as wiring_mod

    real_build = wiring_mod.build_runtime

    def _spy_build(*a, **k):
        parts = real_build(*a, **k)
        seen["fatal"] = parts.fatal
        return parts

    monkeypatch.setattr(daemon_mod, "build_runtime", _spy_build, raising=False)
    monkeypatch.setattr(daemon_mod.threading, "Event", _StopDuringWait)

    channel = _OnlinePingChannel()
    rc = daemon_mod.run_daemon(
        config=_no_slot_config(), settings=None, db_path=tmp_db, channel=channel
    )

    # AUTH_FAILED is NOT fatal: the marker stays unset and the exit is the clean 0.
    assert seen["fatal"].is_set() is False  # D-03: auth never turned fatal
    assert rc == 0  # re-probes then exits clean, not a non-zero fatal exit


def test_announce_forecast(tmp_db):
    """HARD-STARTUP-03 / F90: _announce_schedule logs a ``kind="forecast:*"`` line
    per forecast slot INCLUDING a DISABLED one (with next_run_time=None) so a
    silently-disabled forecast slot is visible in the startup log, not swallowed.
    Today _announce_schedule iterates only briefings and ``continue``s past disabled
    slots — the parallel forecast loop (keyed by _forecast_job_id) that stops
    skipping disabled slots lands in 29-05."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from structlog.testing import capture_logs

    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.config import Config, Location
    from weatherbot.config.holder import ConfigHolder
    from weatherbot.config.models import ForecastSchedule

    # One ENABLED and one DISABLED forecast slot on the same location.
    cfg = Config(
        locations=[
            Location(
                name="Home",
                lat=40.7128,
                lon=-74.006,
                timezone="America/New_York",
                schedule=[],
                forecast=[
                    ForecastSchedule(
                        kind="weekday",
                        variant="detailed",
                        time="06:30",
                        days="mon-fri",
                        enabled=True,
                    ),
                    ForecastSchedule(
                        kind="weekend",
                        variant="compact",
                        time="08:00",
                        days="sat,sun",
                        enabled=False,
                    ),
                ],
            )
        ]
    )
    holder = ConfigHolder(cfg)
    scheduler = BackgroundScheduler()
    daemon_mod._register_jobs(scheduler, holder, db_path=tmp_db, settings=None)

    with capture_logs() as logs:
        daemon_mod._announce_schedule(scheduler, holder)

    forecast_lines = [
        e for e in logs if str(e.get("kind", "")).startswith("forecast")
    ]
    # A line per forecast slot (enabled AND disabled) — F90 visibility.
    assert len(forecast_lines) == 2
    disabled = [e for e in forecast_lines if e.get("enabled") is False]
    assert len(disabled) == 1  # the disabled slot IS announced ...
    assert disabled[0]["next_run_time"] == "None"  # ... with no next fire (F90 signal)


def test_ping_after_ready(tmp_db, monkeypatch):
    """HARD-STARTUP-03 / F07: the one-time online Discord ping must fire STRICTLY
    AFTER notifier.ready() — today it lives inside _on_online, which the hub fires
    BEFORE ready(), so a slow/failed Discord post could delay the systemd READY
    signal. 29-05 relocates the ping into run_daemon after ready_gate.run returns.
    We record a global order across ready() (append "ready") and channel.send
    (append "ping") and assert the ping index is strictly after ready."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.ops import CheckResult, PASS
    from weatherbot.weather.store import init_db

    init_db(tmp_db)

    monkeypatch.setattr(
        daemon_mod,
        "run_self_check",
        lambda *, config, settings: CheckResult(ok=True, reason=PASS),
    )

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)
    monkeypatch.setattr(daemon_mod.threading, "Event", _NeverSetImmediateWait)

    order: list[str] = []
    monkeypatch.setattr(
        daemon_mod.SystemdNotifier, "ready", lambda self: order.append("ready")
    )

    class _OrderRecordingChannel:
        def __init__(self):
            from weatherbot.channels import DeliveryResult

            self._result = DeliveryResult(ok=True)

        def send(self, text):
            order.append("ping")
            return self._result

    monkeypatch.setattr(
        "weatherbot.channels.build_channel",
        lambda config, settings: _OrderRecordingChannel(),
    )

    rc = daemon_mod.run_daemon(
        config=_no_slot_config(), settings=object(), db_path=tmp_db
    )

    assert rc == 0
    assert "ready" in order and "ping" in order
    assert order.index("ping") > order.index("ready")  # F07: ping strictly after ready
