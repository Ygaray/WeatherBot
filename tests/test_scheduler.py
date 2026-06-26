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
    import weatherbot.interactive as interactive_mod
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

    # Patch the LAZY import site: run_daemon does `from weatherbot.interactive import
    # BotThread`, which resolves the name on the interactive package object.
    monkeypatch.setattr(interactive_mod, "BotThread", _RecordingBotThread)

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
    import weatherbot.interactive as interactive_mod
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

    monkeypatch.setattr(interactive_mod, "BotThread", _CapturingBotThread)

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
    import weatherbot.interactive as interactive_mod
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

    monkeypatch.setattr(interactive_mod, "BotThread", _ExplodingBotThread)

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
    import weatherbot.interactive as interactive_mod
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

    monkeypatch.setattr(interactive_mod, "BotThread", _MustNotConstructBotThread)

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
        raise AssertionError("scheduled forecast must post via send(), not send_briefing()")


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


def test_fire_forecast_slot_posts_and_writes_no_store(tmp_db, load_fixture, monkeypatch):
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
    assert daemon_mod._forecast_failure_streaks.get(
        daemon_mod._forecast_job_id(loc, fc), 0
    ) == 0

    # A subsequent SINGLE failure must NOT alert (streak restarted from zero).
    posts_before = len(channel.sent_text)
    daemon_mod.fire_forecast_slot(
        loc, fc, config=cfg, db_path=tmp_db, client=_BoomClient(), channel=channel
    )
    assert len(channel.sent_text) == posts_before  # no dead-slot alert yet


def test_validate_rejects_bad_forecast_template(tmp_path):
    from weatherbot.config.loader import validate_config_and_templates

    # A config whose forecast slot references a template with a typo'd {token} must
    # be rejected at load (keep-old at reload, Pitfall 5/T-13-17). Point the loader at
    # a templates dir holding a GOOD briefing template + a BAD forecast template.
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / "briefing.txt").write_text("{location}: {temp}", encoding="utf-8")
    # weekday-detailed whole-message + a BAD per-day line (unknown {nope} token).
    (tdir / "forecast-weekday-detailed.txt").write_text("{title}\n{days}", encoding="utf-8")
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
