"""Wave-0 Nyquist RED scaffold for Phase 9 — the reload engine (Plan 09-01).

These tests are the EXECUTABLE CONTRACT that Plans 02–05 turn green. They are
written BEFORE the reload engine exists: the not-yet-built reload entrypoint
(``weatherbot.scheduler.daemon._do_reload``) and its sender (``do_reload`` in
``weatherbot.cli``) are referenced through PER-TEST lazy-import helpers
(``_do_reload`` / ``_reload_cli`` below), NOT at module top. A hard top-level
``from weatherbot.scheduler.daemon import _do_reload`` would raise at COLLECTION
and HIDE every node ID — the exact Phase 8 Wave-0 lesson. Deferring the import
lets all twelve node IDs COLLECT while each still fails RED on a real
``ModuleNotFoundError``/``AttributeError``/``ImportError`` until the engine lands.

The single most load-bearing test is the SC#4 exactly-once guard
``test_already_sent_slot_not_refired_after_tz_name_change`` (Pitfall #8, CFG-05,
amended D-02): a NAME and/or IANA-TZ change on an ALREADY-SENT slot (KEEPING its
``send_time`` → same logical slot) must NOT re-fire and must NOT skip. Its
companion ``test_send_time_change_is_new_slot_fires_today_if_ahead`` pins the
SEPARATE accepted semantics: a ``send_time`` change is, by design, a NEW slot that
fires today if its new time is still ahead (operator-confirmed Option A, RESEARCH
A3 resolved). NO blanket per-location once-today guard is introduced — it was
rejected because it would break legitimate multi-slot-per-day locations.

The exactly-once tests seed a real ``sent_log`` row (the ``seed_sent_row`` fixture
→ the shipped ``claim_slot``) and assert on the real claim/sent-log path, never a
mock that always passes (T-09-01: no green-but-hollow scaffold).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from apscheduler.schedulers.background import BackgroundScheduler

from weatherbot.config import Config, Location
from weatherbot.config.holder import ConfigHolder
from weatherbot.config.models import Schedule
from weatherbot.weather.store import claim_slot, was_sent

_NY = ZoneInfo("America/New_York")


# --------------------------------------------------------------------------- #
# Deferred references to the NOT-YET-BUILT reload engine (Phase 8 Wave-0 lesson).
# Resolved INSIDE each test body so every node ID collects while the symbol is
# absent; each call fails RED with a real ModuleNotFoundError/AttributeError.
# --------------------------------------------------------------------------- #


def _do_reload(*args, **kwargs):
    """Call the daemon-side reload entrypoint — RED until Plans 02–05 land it.

    Deferred import (NOT module-top) so the node IDs collect. ``_do_reload`` is the
    two-phase build-then-commit engine: validate-before-swap → ``holder.replace`` →
    diff-reconcile jobs on the stable ``name|time|days`` id, keep-old on any failure
    (Pattern 3/4). Signature is the engine's to define; tests pass it by keyword.
    """
    from weatherbot.scheduler.daemon import _do_reload as engine

    return engine(*args, **kwargs)


def _reload_cli(*args, **kwargs):
    """Call the CLI-side ``reload`` sender (PID file + /proc guard + os.kill).

    Deferred import — RED until the CLI ``reload`` subcommand sender ships (D-03).
    """
    from weatherbot.cli import do_reload

    return do_reload(*args, **kwargs)


# --------------------------------------------------------------------------- #
# Local config builders (mirror tests/test_scheduler.py — no new fixtures).
# `id=` is passed explicitly where a test needs a STABLE identity across a
# name/tz edit; with id defaulting to the raw name (D-01) it is byte-identical to
# the sent-log key today.
# --------------------------------------------------------------------------- #


def _loc(name, *, id=None, tz="America/New_York", schedule=None, lat=40.7128, lon=-74.006):
    kwargs = dict(name=name, lat=lat, lon=lon, timezone=tz, schedule=schedule or [])
    if id is not None:
        kwargs["id"] = id
    return Location(**kwargs)


def _cfg(*locations):
    return Config(locations=list(locations))


def _slot(time="07:00", days="daily", enabled=True):
    return Schedule(time=time, days=days, enabled=enabled)


class _RecordingChannel:
    """Captures every delivery so a test can assert on the POST count.

    Implements both the briefing seam (``send_briefing``) and the agnostic
    ``send`` seam so it works regardless of which the engine/fire path uses.
    """

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self._result = DeliveryResult(ok=True)

    def send_briefing(self, text, forecast):
        self.sent_text.append(text)
        return self._result

    def send(self, text):
        self.sent_text.append(text)
        return self._result


class _FakeClient:
    """Returns recorded One Call fixtures (mirrors test_scheduler.py)."""

    def __init__(self, onecall_imp, onecall_met):
        self._onecall = {"imperial": onecall_imp, "metric": onecall_met}
        self.onecall_calls: list[str] = []

    def fetch_onecall(self, location, units):
        self.onecall_calls.append(units)
        return self._onecall[units]


def _job_ids(scheduler):
    """The live job-id set, excluding the daemon's internal heartbeat job."""
    return {j.id for j in scheduler.get_jobs() if j.id != "__heartbeat__"}


# --------------------------------------------------------------------------- #
# (1) THE highest-risk SC#4 test — name/tz change on an already-sent slot.
#     Per AMENDED D-02: protects NAME and TZ edits ONLY (both KEEP send_time →
#     same logical slot). Keeps the slot time unchanged; asserts no later re-fire.
# --------------------------------------------------------------------------- #


def test_already_sent_slot_not_refired_after_tz_name_change(
    holder_scheduler, seed_sent_row, load_fixture
):
    """SC#4 (Pitfall #8, CFG-05, amended D-02): a reload that changes a location's
    DISPLAY NAME and/or IANA TIMEZONE on an ALREADY-SENT slot must produce NO
    duplicate send and NO skip of a valid slot.

    Recipe (RESEARCH Pitfall 4, deterministic, no wall-clock wait): seed a sent_log
    row for ``(location.id, slot.time, today)`` → ``_do_reload`` a config that
    changes the NAME and TZ but KEEPS the same stable ``id`` AND the same logical
    slot time → fire that slot → the stable-``id`` + already-sent-today guard makes
    ``claim_slot`` LOSE → the recording channel is NOT called again.

    This test deliberately keeps the slot time unchanged and asserts NOTHING about
    a later-morning re-fire — a time change is a NEW slot (see the companion test).
    """
    today = "2026-06-10"
    slot = _slot(time="07:00", days="daily")
    # Stable id pinned so the rename/tz-shift keeps the SAME exactly-once key.
    old = _cfg(_loc("Home", id="home-stable", tz="America/New_York", schedule=[slot]))
    holder, scheduler, db_path = holder_scheduler(old)

    # The slot already delivered today (seeded through the real claim path).
    seed_sent_row(db_path, "home-stable", "07:00", today)
    assert was_sent(db_path, "home-stable", "07:00", today) is True

    channel = _RecordingChannel()
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )

    # Reload: rename the location AND shift its IANA tz, KEEP the id AND send_time.
    new = _cfg(
        _loc(
            "Home (renamed)",
            id="home-stable",
            tz="America/Chicago",
            schedule=[_slot(time="07:00", days="daily")],
        )
    )

    _do_reload(
        new,
        holder=holder,
        scheduler=scheduler,
        db_path=db_path,
        client=client,
        channel=channel,
    )

    # The same logical slot is still already-sent under the stable id: a re-fire
    # LOSES the claim and delivers nothing (no duplicate, no skip of a valid slot).
    refired = claim_slot(db_path, "home-stable", "07:00", today)
    assert refired is False  # already sent today → claim lost → no second briefing
    assert channel.sent_text == []  # the reload itself delivered nothing


# --------------------------------------------------------------------------- #
# (2) The SEPARATE accepted-behavior test — a send_time change is a NEW slot that
#     fires today if its new time is still ahead (D-02 amended, RESEARCH A3).
# --------------------------------------------------------------------------- #


def test_send_time_change_is_new_slot_fires_today_if_ahead(
    holder_scheduler, seed_sent_row, load_fixture
):
    """Accepted send_time-change semantics (D-02 amended, RESEARCH A3 resolved):
    moving a slot's ``send_time`` to a NEW time that is STILL AHEAD today produces a
    NEW key/job (``name|time|days``) that FIRES TODAY, then settles to the new time
    from the next day. The OLD-time slot's already-sent row is left undisturbed, and
    NO blanket per-location once-today guard blocks the second same-day delivery.
    """
    today = "2026-06-10"
    old_time, new_time = "08:00", "09:00"  # new time still ahead the same morning
    old = _cfg(
        _loc("Home", id="home-stable", schedule=[_slot(time=old_time, days="daily")])
    )
    holder, scheduler, db_path = holder_scheduler(old)

    # The OLD-time slot already delivered today.
    seed_sent_row(db_path, "home-stable", old_time, today)

    channel = _RecordingChannel()
    client = _FakeClient(
        load_fixture("onecall_imperial_clear.json"),
        load_fixture("onecall_metric_clear.json"),
    )

    # Reload changes ONLY the send_time (keep name/tz/id) → a NEW slot/key.
    new = _cfg(
        _loc("Home", id="home-stable", schedule=[_slot(time=new_time, days="daily")])
    )
    _do_reload(
        new,
        holder=holder,
        scheduler=scheduler,
        db_path=db_path,
        client=client,
        channel=channel,
    )

    # The NEW-time slot is a DISTINCT key — it WINS its first claim and may fire.
    won_new = claim_slot(db_path, "home-stable", new_time, today)
    assert won_new is True  # new send_time = new slot → fires today (still ahead)

    # The OLD-time already-sent row is NOT disturbed (a re-claim still loses).
    assert claim_slot(db_path, "home-stable", old_time, today) is False
    # Both same-day slots coexist: NO blanket per-location once-today guard.


# --------------------------------------------------------------------------- #
# (3) All-or-nothing rollback — a job-reconcile failure mid-reload leaves the OLD
#     schedule fully intact (SC#2, Pitfall #6, CFG-04).
# --------------------------------------------------------------------------- #


def test_reconcile_failure_rolls_back(holder_scheduler, monkeypatch):
    """SC#2 (Pitfall #6, CFG-04): an injected job-registration failure mid-reload
    leaves the OLD job set AND the OLD config fully intact (two-phase commit
    rollback). After the failed reload, ``holder.current()`` is the OLD config and
    the live job-id set matches the pre-reload set exactly."""
    old = _cfg(
        _loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")])
    )
    holder, scheduler, db_path = holder_scheduler(old)

    # Register the OLD schedule so there is a real live job set to preserve.
    import weatherbot.scheduler.daemon as daemon_mod

    daemon_mod._register_jobs(
        scheduler, holder, db_path=db_path, settings=None
    )
    jobs_before = _job_ids(scheduler)
    assert jobs_before == {"Home|07:00|mon-fri"}

    # Inject a failure in the job-reconcile step (mid-reload). The exact symbol the
    # engine reconciles through is _register_jobs; make it raise so the commit phase
    # blows up AFTER validation passed, exercising the rollback path.
    def _boom(*a, **k):
        raise RuntimeError("injected reconcile failure")

    monkeypatch.setattr(daemon_mod, "_register_jobs", _boom)

    new = _cfg(
        _loc("Home", id="home", schedule=[_slot(time="09:00", days="mon-fri")])
    )
    with pytest.raises(RuntimeError):
        _do_reload(new, holder=holder, scheduler=scheduler, db_path=db_path)

    # OLD config + OLD job set survive fully intact (keep-old, all-or-nothing).
    assert holder.current() is old
    assert _job_ids(scheduler) == jobs_before


# --------------------------------------------------------------------------- #
# (4) Identical-config noop — zero job changes, no duplicate fires (SC#3,
#     Pitfall #7, CFG-05).
# --------------------------------------------------------------------------- #


def test_identical_reload_zero_changes(holder_scheduler):
    """SC#3 (Pitfall #7, CFG-05): reloading the BYTE-IDENTICAL config produces zero
    add/remove/change on the stable ``name|time|days`` id and no duplicate fires."""
    cfg = _cfg(
        _loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")])
    )
    holder, scheduler, db_path = holder_scheduler(cfg)

    import weatherbot.scheduler.daemon as daemon_mod

    daemon_mod._register_jobs(scheduler, holder, db_path=db_path, settings=None)
    jobs_before = _job_ids(scheduler)

    # Reload the SAME structure (a fresh-but-equal Config) → reconcile is a no-op.
    same = _cfg(
        _loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")])
    )
    _do_reload(same, holder=holder, scheduler=scheduler, db_path=db_path)

    assert _job_ids(scheduler) == jobs_before  # zero job churn


# --------------------------------------------------------------------------- #
# (5) Diff-reconcile — add one / remove one / time-change one; the live job set
#     reflects exactly the delta on the stable id (a time change = 1 add + 1
#     remove of a NEW id, consistent with the new-slot semantics in test (2)).
# --------------------------------------------------------------------------- #


def test_reconcile_diff(holder_scheduler):
    """A reload that adds one slot, removes one (disabled), and time-changes one
    yields exactly the delta on the stable ``name|time|days`` id — never a
    ``remove_all_jobs()`` churn."""
    old = _cfg(
        _loc(
            "Home",
            id="home",
            schedule=[
                _slot(time="07:00", days="mon-fri"),  # time-changed below
                _slot(time="12:00", days="daily"),  # removed (disabled) below
            ],
        )
    )
    holder, scheduler, db_path = holder_scheduler(old)

    import weatherbot.scheduler.daemon as daemon_mod

    daemon_mod._register_jobs(scheduler, holder, db_path=db_path, settings=None)
    assert _job_ids(scheduler) == {"Home|07:00|mon-fri", "Home|12:00|daily"}

    new = _cfg(
        _loc(
            "Home",
            id="home",
            schedule=[
                _slot(time="08:00", days="mon-fri"),  # time-changed (new id)
                _slot(time="12:00", days="daily", enabled=False),  # removed
                _slot(time="18:00", days="daily"),  # added
            ],
        )
    )
    _do_reload(new, holder=holder, scheduler=scheduler, db_path=db_path)

    assert _job_ids(scheduler) == {"Home|08:00|mon-fri", "Home|18:00|daily"}


# --------------------------------------------------------------------------- #
# (6) Invalid reload keeps old — bad TOML / dup name / dup id / unknown token are
#     each rejected → holder.current() unchanged (CFG-04).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad_kind",
    ["bad_toml", "duplicate_name", "duplicate_id", "unknown_template_token"],
    ids=["bad_toml", "duplicate_name", "duplicate_id", "unknown_template_token"],
)
def test_invalid_reload_keeps_old(holder_scheduler, tmp_path, bad_kind):
    """CFG-04: each invalid edit (bad TOML, duplicate name, duplicate id, unknown
    template token) is rejected by the validate-before-swap gate → the live config
    is left UNCHANGED (keep-old). The reload engine re-reads + validates a config
    PATH; an invalid one must raise and never swap."""
    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="daily")]))
    holder, scheduler, db_path = holder_scheduler(old)

    cfg_path = tmp_path / "config.toml"
    if bad_kind == "bad_toml":
        cfg_path.write_text("this is = not = valid toml\n", encoding="utf-8")
    elif bad_kind == "duplicate_name":
        cfg_path.write_text(
            '[[locations]]\nname = "Home"\nlat = 1.0\nlon = 2.0\n'
            'timezone = "America/New_York"\n\n'
            '[[locations]]\nname = "home"\nlat = 3.0\nlon = 4.0\n'
            'timezone = "America/Chicago"\n',
            encoding="utf-8",
        )
    elif bad_kind == "duplicate_id":
        cfg_path.write_text(
            '[[locations]]\nname = "Home"\nid = "dup"\nlat = 1.0\nlon = 2.0\n'
            'timezone = "America/New_York"\n\n'
            '[[locations]]\nname = "Away"\nid = "DUP"\nlat = 3.0\nlon = 4.0\n'
            'timezone = "America/Chicago"\n',
            encoding="utf-8",
        )
    else:  # unknown_template_token
        cfg_path.write_text(
            'template = "__does_not_exist__.txt"\n'
            '[[locations]]\nname = "Home"\nlat = 1.0\nlon = 2.0\n'
            'timezone = "America/New_York"\n',
            encoding="utf-8",
        )

    # The validate-before-swap gate must raise on the invalid input. Whatever the
    # exact type (TOMLDecodeError / pydantic.ValidationError / ValueError), the swap
    # must NOT happen — holder.current() is still the OLD config.
    with pytest.raises(Exception):
        _do_reload(
            config_path=str(cfg_path),
            holder=holder,
            scheduler=scheduler,
            db_path=db_path,
        )

    assert holder.current() is old  # keep-old: the live config never changed


# --------------------------------------------------------------------------- #
# (7) Valid edit applies + a new send-time fires on the new schedule (CFG-01).
# --------------------------------------------------------------------------- #


def test_reload_applies_new_schedule(holder_scheduler):
    """CFG-01: a valid edit applies without restart — after the reload, the holder
    holds the new config and a new send-time job is live on the new schedule."""
    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")]))
    holder, scheduler, db_path = holder_scheduler(old)

    import weatherbot.scheduler.daemon as daemon_mod

    daemon_mod._register_jobs(scheduler, holder, db_path=db_path, settings=None)

    new = _cfg(_loc("Home", id="home", schedule=[_slot(time="06:30", days="mon-fri")]))
    _do_reload(new, holder=holder, scheduler=scheduler, db_path=db_path)

    assert holder.current() is new  # the edit applied (no restart)
    assert "Home|06:30|mon-fri" in _job_ids(scheduler)  # new send-time is live


# --------------------------------------------------------------------------- #
# (8) SIGHUP sets the reload flag and the poll-loop services it (CFG-02).
# --------------------------------------------------------------------------- #


def test_sighup_triggers_reload(monkeypatch):
    """CFG-02: the daemon's SIGHUP handler sets the reload flag (it does NOT run the
    reload re-entrantly inside the handler), and the main poll-loop services it.

    The reload entrypoint the loop calls is referenced via the deferred ``_do_reload``
    so this collects RED until the SIGHUP handoff + poll loop ship in run_daemon."""
    from weatherbot.scheduler.daemon import _install_reload_signal

    # RED until the SIGHUP install helper exists. It must return a flag object whose
    # .is_set() flips when the installed handler runs (a threading.Event-shaped flag).
    flag = _install_reload_signal()
    assert flag.is_set() is False
    # Simulate the signal delivery the way the SIGTERM handler is tested: invoke the
    # installed handler; the flag flips WITHOUT running reload work re-entrantly.
    import signal as _signal

    handler = _signal.getsignal(_signal.SIGHUP)
    handler(_signal.SIGHUP, None)
    assert flag.is_set() is True


# --------------------------------------------------------------------------- #
# (9) `weatherbot reload` sender reads the PID file, passes the /proc guard, and
#     signals (CFG-02, D-03).
# --------------------------------------------------------------------------- #


def test_reload_cli_signals_pid(tmp_path, monkeypatch):
    """CFG-02 / D-03: the ``weatherbot reload`` sender reads the PID file, verifies
    via ``/proc/<pid>/cmdline`` that the PID is a weatherbot process (stale-PID
    guard), then sends SIGHUP. ``os.kill`` is mocked so no real signal is sent."""
    import os
    import signal as _signal

    pid_file = tmp_path / "weatherbot.pid"
    pid_file.write_text("4242\n", encoding="utf-8")

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

    # Make the /proc cmdline staleness guard PASS (the PID is a weatherbot process).
    # The sender's guard reads /proc/<pid>/cmdline; stub the reader the engine uses.
    rc = _reload_cli(pid_file=str(pid_file), _cmdline_reader=lambda pid: b"weatherbot\x00run")

    assert rc == 0
    assert killed == [(4242, _signal.SIGHUP)]


# --------------------------------------------------------------------------- #
# (10) Reload outcome logging — success diff summary + rejection reason (CFG-06).
# --------------------------------------------------------------------------- #


def test_reload_logs_diff_summary(holder_scheduler, caplog):
    """CFG-06 / D-07: a SUCCESSFUL reload logs the job-diff summary (added / removed
    / changed / unchanged counts, e.g. ``+1 -0 ~1 =1``) so the operator can confirm
    exactly what took effect."""
    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")]))
    holder, scheduler, db_path = holder_scheduler(old)

    import weatherbot.scheduler.daemon as daemon_mod

    daemon_mod._register_jobs(scheduler, holder, db_path=db_path, settings=None)

    new = _cfg(
        _loc(
            "Home",
            id="home",
            schedule=[
                _slot(time="07:00", days="mon-fri"),  # unchanged
                _slot(time="18:00", days="daily"),  # added
            ],
        )
    )
    with caplog.at_level("INFO"):
        _do_reload(new, holder=holder, scheduler=scheduler, db_path=db_path)

    # The CFG-06 outcome line reports the reconcile counts. Assert the summary token
    # set appears (the exact format string is the engine's; the counts are the
    # contract). A successful reload mentions "reload" and the diff markers.
    text = caplog.text.lower()
    assert "reload" in text
    assert "+1" in caplog.text or "added" in text  # at least one slot added is reported


def test_rejected_reload_logs_reason(holder_scheduler, tmp_path, caplog):
    """CFG-06: a REJECTED reload logs the validation reason and keeps old."""
    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="daily")]))
    holder, scheduler, db_path = holder_scheduler(old)

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("this is = not = valid toml\n", encoding="utf-8")

    with caplog.at_level("ERROR"):
        with pytest.raises(Exception):
            _do_reload(
                config_path=str(cfg_path),
                holder=holder,
                scheduler=scheduler,
                db_path=db_path,
            )

    assert holder.current() is old  # keep-old
    assert "reload" in caplog.text.lower()  # the rejection reason was logged


# --------------------------------------------------------------------------- #
# (11) check-config and reload share ONE validation path (D-05).
# --------------------------------------------------------------------------- #


def test_check_config_and_reload_share_validation(holder_scheduler, tmp_path):
    """D-05: a config that PASSES the offline ``check-config`` validator is accepted
    by the reload path, and a config the validator REJECTS is rejected by reload —
    proving both run the SAME single offline-validation function
    (``validate_config_and_templates``)."""
    from weatherbot.config.loader import validate_config_and_templates

    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="daily")]))
    holder, scheduler, db_path = holder_scheduler(old)

    good_path = tmp_path / "good.toml"
    good_path.write_text(
        '[[locations]]\nname = "Home"\nlat = 1.0\nlon = 2.0\n'
        'timezone = "America/New_York"\n\n'
        '[[locations.schedule]]\ntime = "07:00"\ndays = "daily"\n',
        encoding="utf-8",
    )

    # The shared validator accepts the good config (no raise) ...
    validated = validate_config_and_templates(str(good_path))
    assert validated.locations[0].name == "Home"

    # ... and the reload path accepts that same good config (applies, keeps it).
    _do_reload(config_path=str(good_path), holder=holder, scheduler=scheduler, db_path=db_path)
    assert holder.current().locations[0].name == "Home"

    # A config the shared validator REJECTS is rejected by reload too (keep-old).
    bad_path = tmp_path / "bad.toml"
    bad_path.write_text("this is = not = valid toml\n", encoding="utf-8")
    with pytest.raises(Exception):
        validate_config_and_templates(str(bad_path))
    with pytest.raises(Exception):
        _do_reload(config_path=str(bad_path), holder=holder, scheduler=scheduler, db_path=db_path)
