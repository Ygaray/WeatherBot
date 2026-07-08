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

from zoneinfo import ZoneInfo

import pytest


from weatherbot.config import Config, Location
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


def _loc(
    name, *, id=None, tz="America/New_York", schedule=None, lat=40.7128, lon=-74.006
):
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
    # The reload itself fires NO weather BRIEFING (no duplicate same-day delivery).
    # It MAY post the CFG-07 reload-outcome confirmation (✅ config reloaded …) —
    # that plain-text post is not a briefing, so assert only that no briefing went
    # out, not that the channel was wholly silent (the CFG-07 post is expected here).
    briefings = [t for t in channel.sent_text if not t.startswith("✅")]
    assert briefings == []  # the reload itself delivered no briefing


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
    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")]))
    holder, scheduler, db_path = holder_scheduler(old)

    # Register the OLD schedule so there is a real live job set to preserve.
    import weatherbot.scheduler.daemon as daemon_mod

    daemon_mod._register_jobs(scheduler, holder, db_path=db_path, settings=None)
    jobs_before = _job_ids(scheduler)
    assert jobs_before == {"Home|07:00|mon-fri"}

    # Inject a failure in the job-reconcile step (mid-reload). The exact symbol the
    # engine reconciles through is _register_jobs; make it raise so the commit phase
    # blows up AFTER validation passed, exercising the rollback path.
    def _boom(*a, **k):
        raise RuntimeError("injected reconcile failure")

    monkeypatch.setattr(daemon_mod, "_register_jobs", _boom)

    new = _cfg(_loc("Home", id="home", schedule=[_slot(time="09:00", days="mon-fri")]))
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
    cfg = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")]))
    holder, scheduler, db_path = holder_scheduler(cfg)

    import weatherbot.scheduler.daemon as daemon_mod

    daemon_mod._register_jobs(scheduler, holder, db_path=db_path, settings=None)
    jobs_before = _job_ids(scheduler)

    # Reload the SAME structure (a fresh-but-equal Config) → reconcile is a no-op.
    same = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")]))
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
    rc = _reload_cli(
        pid_file=str(pid_file), _cmdline_reader=lambda pid: b"weatherbot\x00run"
    )

    assert rc == 0
    assert killed == [(4242, _signal.SIGHUP)]


def test_reload_cli_safe_fails_when_target_exits_before_signal(tmp_path, monkeypatch):
    """CR-01 / CFG-02: the ``/proc`` guard only narrows the TOCTOU window — the daemon
    can still exit between the guard read and ``os.kill``. A ``ProcessLookupError`` from
    ``os.kill`` must safe-fail to rc 1 (outcome-only log), NOT crash with a traceback,
    honoring do_reload's documented "all safe-fail branches return 1" contract."""
    import os

    pid_file = tmp_path / "weatherbot.pid"
    pid_file.write_text("4242\n", encoding="utf-8")

    def _kill_raises(pid, sig):
        raise ProcessLookupError(3, "No such process")

    monkeypatch.setattr(os, "kill", _kill_raises)

    rc = _reload_cli(
        pid_file=str(pid_file), _cmdline_reader=lambda pid: b"weatherbot\x00run"
    )
    assert rc == 1


def test_reload_cli_safe_fails_when_not_permitted_to_signal(tmp_path, monkeypatch):
    """CR-01 / CFG-02: a recycled PID the sender cannot signal raises ``PermissionError``
    from ``os.kill``; the sender must safe-fail to rc 1, never a traceback."""
    import os

    pid_file = tmp_path / "weatherbot.pid"
    pid_file.write_text("4242\n", encoding="utf-8")

    def _kill_raises(pid, sig):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "kill", _kill_raises)

    rc = _reload_cli(
        pid_file=str(pid_file), _cmdline_reader=lambda pid: b"weatherbot\x00run"
    )
    assert rc == 1


def test_reload_cli_safe_fails_on_unreadable_pid_file(tmp_path):
    """WR-01 / CFG-02: a PID file that exists but is not readable (PermissionError /
    IsADirectoryError, both ``OSError`` subclasses) must safe-fail to rc 1, not escape
    the catch set as an uncaught traceback. Use a directory at the PID path to provoke
    an ``OSError`` (``IsADirectoryError``) on read without relying on chmod-as-root."""
    pid_dir = tmp_path / "weatherbot.pid"
    pid_dir.mkdir()  # reading this path as a file raises IsADirectoryError (OSError)

    rc = _reload_cli(
        pid_file=str(pid_dir), _cmdline_reader=lambda pid: b"weatherbot\x00run"
    )
    assert rc == 1


# --------------------------------------------------------------------------- #
# (9b) PID-recycling guard identity — argv0, not substring (CR-02 / T-09-06).
# --------------------------------------------------------------------------- #


def test_is_weatherbot_pid_rejects_unrelated_substring_match():
    """CR-02 / T-09-06: the guard must match the PROGRAM identity (argv0 / ``-m`` target),
    not "the token appears anywhere in argv". After PID recycling, unrelated processes
    whose argv merely CONTAINS ``weatherbot`` in a path/argument must be REJECTED so a
    routine ``weatherbot reload`` can never SIGHUP (default disposition: terminate) an
    operator's editor / log tail."""
    from weatherbot.ops.pidfile import is_weatherbot_pid

    decoys = [
        b"vim\x00/home/me/weatherbot/config.toml\x00",
        b"tail\x00-f\x00/var/log/weatherbot.log\x00",
        b"grep\x00weatherbot\x00/etc/hosts\x00",
        b"less\x00weatherbot.log\x00",
    ]
    for cmdline in decoys:
        assert (
            is_weatherbot_pid(4242, cmdline_reader=lambda pid, c=cmdline: c) is False
        ), cmdline


def test_is_weatherbot_pid_accepts_real_invocations():
    """CR-02 / T-09-06: genuine weatherbot daemons must still pass the guard — both the
    console-script form (``/usr/bin/weatherbot run``) and the ``python -m weatherbot run``
    form."""
    from weatherbot.ops.pidfile import is_weatherbot_pid

    real = [
        b"/usr/bin/weatherbot\x00run\x00",
        b"weatherbot\x00run\x00",
        b"/usr/bin/python3\x00-m\x00weatherbot\x00run\x00",
    ]
    for cmdline in real:
        assert (
            is_weatherbot_pid(4242, cmdline_reader=lambda pid, c=cmdline: c) is True
        ), cmdline


# --------------------------------------------------------------------------- #
# (9b') Generalized-guard byte-identity (Plan 25-02 Task 1): the app-side
#       ``is_weatherbot_pid`` now DELEGATES to the relocated, marker-parameterized
#       lifecycle guard ``is_running_process(pid, proc_marker=b"weatherbot")``.
#       This load-bearing invariant (PID-recycling defense + do_reload exit codes)
#       had no dedicated direct test before the move; pin that the delegation is
#       byte-identical for the three representative /proc cmdlines so a future
#       module-side change to the guard can never silently drift the app behavior.
# --------------------------------------------------------------------------- #


def test_is_weatherbot_pid_delegates_byte_identically_to_module_guard():
    """Plan 25-02 acceptance: for the argv0-basename ``weatherbot`` form, the
    ``python -m weatherbot`` form, and a non-matching process, the app wrapper
    ``is_weatherbot_pid`` and the module guard ``is_running_process`` with
    ``proc_marker=b"weatherbot"`` return the SAME bool — the value the pre-25-02
    guard returned. Proves the marker-parameterized relocation kept the guard
    byte-identical."""
    from weatherbot.ops.pidfile import WEATHERBOT_PROC_MARKER, is_weatherbot_pid
    from yahir_reusable_bot.lifecycle import is_running_process

    cases = [
        (b"weatherbot\x00run\x00", True),  # argv0 basename match
        (b"/usr/bin/python3\x00-m\x00weatherbot\x00run\x00", True),  # -m module form
        (b"vim\x00/home/me/weatherbot/config.toml\x00", False),  # mere mention -> no match
    ]
    assert WEATHERBOT_PROC_MARKER == b"weatherbot"
    for cmdline, expected in cases:
        reader = lambda pid, c=cmdline: c
        app = is_weatherbot_pid(4242, cmdline_reader=reader)
        module = is_running_process(
            4242, proc_marker=b"weatherbot", cmdline_reader=reader
        )
        assert app is expected, cmdline
        assert module is expected, cmdline
        assert app is module, cmdline  # byte-identical delegation


# --------------------------------------------------------------------------- #
# (9c) Default PID path lives inside the systemd per-service runtime dir
#      (Phase 11 UAT crash-loop fix: /run/weatherbot/, not bare /run).
# --------------------------------------------------------------------------- #


def test_default_pid_file_is_under_service_runtime_dir():
    """OPS-01 / CFG-02 (UAT fix): the default ``PID_FILE`` must live INSIDE the
    per-service systemd ``RuntimeDirectory=weatherbot`` dir (``/run/weatherbot/``),
    which systemd creates owned by the non-root service ``User=`` at start — NOT in
    bare root-owned ``/run`` where the non-root daemon's atomic temp-write hits
    ``PermissionError [Errno 13]`` and crash-loops on ``systemctl restart``.

    Pins both the exact default path and that its PARENT is the writable runtime dir
    (``parent.name == "weatherbot"``), so a regression that points the default back at
    bare ``/run`` fails here. The override-parameter API (``write_pid_atomic(pid_file=)``
    / ``read_pid(pid_file=)``) is exercised unchanged by the tests above; this only
    asserts the production DEFAULT."""
    from pathlib import Path

    from weatherbot.ops.pidfile import PID_FILE

    assert PID_FILE == Path("/run/weatherbot/weatherbot.pid")
    assert PID_FILE.parent.name == "weatherbot"
    assert PID_FILE.parent != Path("/run")  # not bare /run — the crash-loop root cause


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
    _do_reload(
        config_path=str(good_path), holder=holder, scheduler=scheduler, db_path=db_path
    )
    assert holder.current().locations[0].name == "Home"

    # A config the shared validator REJECTS is rejected by reload too (keep-old).
    bad_path = tmp_path / "bad.toml"
    bad_path.write_text("this is = not = valid toml\n", encoding="utf-8")
    with pytest.raises(Exception):
        validate_config_and_templates(str(bad_path))
    with pytest.raises(Exception):
        _do_reload(
            config_path=str(bad_path),
            holder=holder,
            scheduler=scheduler,
            db_path=db_path,
        )


# --------------------------------------------------------------------------- #
# (12) CFG-07 — reload-outcome POSTING to the channel (Plan 11-01 Wave-0 RED).
#
# CFG-06 (tests 10 above) pins that _do_reload LOGS the outcome. CFG-07 pins that
# _do_reload also POSTS the outcome to the Discord channel so the operator gets a
# confirmation/rejection IN-CHANNEL, distinct from the briefing embed (RESEARCH
# Pattern 6, D-13). These fail RED today because _do_reload does NOT yet call
# ``channel.send`` on either branch — Plan 11-04 adds the two post sites (after the
# success ``summary`` at daemon.py:637 and inside the PHASE-1 reject except at
# daemon.py:593). The node IDs contain the ``cfg07`` substring so the research's
# ``-k cfg07`` selector isolates them. A ``channel.send`` failure must be swallowed
# and never change the reload outcome (best-effort, mirror emit_online).
# --------------------------------------------------------------------------- #


class _SpyChannel:
    """Records every ``send`` so a CFG-07 test can assert on the posted text.

    Implements the agnostic ``send`` seam (the CFG-07 reload posts are plain text,
    NOT a briefing embed — D-13) and returns a best-effort ok DeliveryResult, the
    same shape ``emit_online`` treats as best-effort.
    """

    def __init__(self):
        from weatherbot.channels import DeliveryResult

        self.sent_text: list[str] = []
        self._result = DeliveryResult(ok=True)

    def send(self, text):
        self.sent_text.append(text)
        return self._result

    def send_briefing(self, text, forecast):
        # CFG-07 posts go through the plain ``send`` seam; record here too defensively.
        self.sent_text.append(text)
        return self._result


class _RaisingChannel(_SpyChannel):
    """A spy whose ``send`` RAISES — to pin best-effort isolation (send failure must
    not change the reload outcome)."""

    def send(self, text):
        self.sent_text.append(text)
        raise RuntimeError("channel send exploded")


def test_cfg07_success_posts_summary(holder_scheduler):
    """CFG-07: a SUCCESSFUL reload POSTS the ``+a -r ~c =u`` diff summary to the
    channel so the operator sees in-channel exactly what took effect (D-13). The
    posted text contains the same summary token the CFG-06 log line reports."""
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
                _slot(time="18:00", days="daily"),  # added (+1)
            ],
        )
    )
    channel = _SpyChannel()
    _do_reload(
        new, holder=holder, scheduler=scheduler, db_path=db_path, channel=channel
    )

    # The success post carries the reconcile summary string ``+1 -0 ~0 =1``.
    posted = " ".join(channel.sent_text)
    assert "+1" in posted  # at least one slot added is reported in-channel
    assert "=1" in posted  # the unchanged count is part of the summary token


def test_cfg07_rejection_posts_reason(holder_scheduler, tmp_path):
    """CFG-07: a REJECTED reload POSTS the validation reason to the channel AND still
    raises (keep-old contract preserved — the live config never swaps). The operator
    learns in-channel why the edit was refused."""
    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="daily")]))
    holder, scheduler, db_path = holder_scheduler(old)

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text("this is = not = valid toml\n", encoding="utf-8")

    channel = _SpyChannel()
    with pytest.raises(Exception):
        _do_reload(
            config_path=str(cfg_path),
            holder=holder,
            scheduler=scheduler,
            db_path=db_path,
            channel=channel,
        )

    assert holder.current() is old  # keep-old: the rejected config never swapped
    assert channel.sent_text, "rejection was not posted to the channel"
    # The posted reason references the rejection (token-free; outcome only).
    assert "reject" in " ".join(channel.sent_text).lower()


def test_cfg07_channel_send_failure_does_not_abort_reload(holder_scheduler, tmp_path):
    """CFG-07 best-effort (mirror emit_online): a ``channel.send`` that RAISES must be
    swallowed and never change the reload OUTCOME — a success still swaps, and a
    rejection still raises the ORIGINAL validation error (not the send error)."""
    # Success branch: a raising post must NOT prevent the swap from taking effect.
    old = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="mon-fri")]))
    holder, scheduler, db_path = holder_scheduler(old)

    import weatherbot.scheduler.daemon as daemon_mod

    daemon_mod._register_jobs(scheduler, holder, db_path=db_path, settings=None)

    new = _cfg(_loc("Home", id="home", schedule=[_slot(time="06:30", days="mon-fri")]))
    channel = _RaisingChannel()
    # The raising post is swallowed; the reload still succeeds (no exception escapes).
    _do_reload(
        new, holder=holder, scheduler=scheduler, db_path=db_path, channel=channel
    )
    assert holder.current() is new  # swap took effect despite the send failure

    # Rejection branch: a raising post must surface the ORIGINAL validation error,
    # not the send RuntimeError (keep-old still holds).
    old2 = _cfg(_loc("Home", id="home", schedule=[_slot(time="07:00", days="daily")]))
    holder2, scheduler2, db_path2 = holder_scheduler(old2)
    bad_path = tmp_path / "bad.toml"
    bad_path.write_text("this is = not = valid toml\n", encoding="utf-8")

    channel2 = _RaisingChannel()
    with pytest.raises(Exception) as excinfo:
        _do_reload(
            config_path=str(bad_path),
            holder=holder2,
            scheduler=scheduler2,
            db_path=db_path2,
            channel=channel2,
        )
    # The escaping error is the validation rejection, NOT the channel send RuntimeError.
    assert "channel send exploded" not in str(excinfo.value)
    assert holder2.current() is old2  # keep-old preserved


# --------------------------------------------------------------------------- #
# (CR-01) Daemon-level integration: a successful reload invalidates the bot's
#         ForecastCache so the next lookup REFETCHES against the new config.
#         Distinct from the ISOLATED tests/test_cache.py::test_invalidate_clears_cache
#         (which calls cache.invalidate() directly) — this drives the REAL
#         _do_reload(..., cache=cache) wiring end-to-end.
# --------------------------------------------------------------------------- #


def test_reload_invalidates_forecast_cache_so_next_lookup_refetches(
    holder_scheduler, monkeypatch
):
    """CR-01 (Pattern 4): a committed reload clears the bot's ``ForecastCache`` so the
    next ``!weather <loc>`` refetches against the freshly reloaded config — no stale
    pre-reload forecast served for up to the TTL (D-12, ~10 min).

    This is the DAEMON-LEVEL integration proof, distinct from the isolated
    ``tests/test_cache.py::test_invalidate_clears_cache`` (which calls
    ``cache.invalidate()`` directly): here the real ``_do_reload(..., cache=cache)``
    wiring from quick task 260617-fua does the invalidating.

    Recipe (the exact CR-01 stale-key scenario): prime the cache for ``home`` (spy
    count → 1), then reload a config that KEEPS the same stable ``id`` but CHANGES a
    field (lat/lon) so the cache key is byte-identical across the edit — without the
    reload-invalidation the stale entry would still satisfy the next lookup. After the
    committed reload, the next ``cache.lookup("home", new_cfg)`` must refetch (spy count
    → 2), proving the reload cleared the entry.
    """
    from weatherbot.interactive import ForecastCache
    from weatherbot.interactive import cache as cache_mod

    fetches: list = []
    monkeypatch.setattr(
        cache_mod,
        "lookup_weather",
        lambda name, *, config, **k: fetches.append(name) or object(),
        raising=False,
    )

    old = _cfg(
        _loc("home", id="home-stable", schedule=[_slot(time="07:00", days="daily")])
    )
    holder, scheduler, db_path = holder_scheduler(old)
    cache = ForecastCache(settings=None)

    # Prime the cache against the pre-reload config (one underlying fetch).
    cache.lookup("home", old)
    assert len(fetches) == 1

    # Reload a config with the SAME stable id but a CHANGED location field (lat/lon),
    # so the cache key survives the edit — the precise stale-read CR-01 describes.
    new = _cfg(
        _loc(
            "home",
            id="home-stable",
            lat=51.5074,
            lon=-0.1278,
            schedule=[_slot(time="07:00", days="daily")],
        )
    )
    _do_reload(new, holder=holder, scheduler=scheduler, db_path=db_path, cache=cache)
    assert holder.current() is new  # the swap committed

    # The reload-invalidation forced a refetch — NOT served from the pre-reload entry.
    cache.lookup("home", new)
    assert len(fetches) == 2


# --------------------------------------------------------------------------- #
# Phase 29 Wave 0 (Plan 29-02): F89 forecast-failure-streak prune-on-reload.
#
# `_forecast_failure_streaks` is an IN-PROCESS dict keyed by `_forecast_job_id`.
# A reload that DROPS a forecast slot must prune that slot's streak entry so a
# removed/renamed slot does not leave a stale in-memory streak that could later
# mis-classify a NEW slot at the same id. The prune helper (`_prune_forecast_streaks`)
# lands in 29-05 wired into `_on_applied`; here we call it directly (per the plan)
# and xfail until then. RED reason: the helper does not exist yet.
# --------------------------------------------------------------------------- #


def test_streak_prune(holder_scheduler):
    """HARD-STARTUP-03 / F89: pruning drops the streak entry of a REMOVED forecast
    slot (dead key) and KEEPS the entry of a still-configured slot (live key). Both
    keys are built via `daemon._forecast_job_id` so they byte-match the prune's
    set-difference against `_desired_job_ids` — never a hand-written id string."""
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.config.models import ForecastSchedule

    live_fc = ForecastSchedule(
        kind="weekday", variant="detailed", time="06:30", days="mon-fri", enabled=True
    )
    dead_fc = ForecastSchedule(
        kind="weekend", variant="compact", time="08:00", days="sat,sun", enabled=True
    )
    # Both slots present in the STARTING config; the reload below drops the dead one.
    location = Location(
        name="Home",
        id="home",
        lat=40.7128,
        lon=-74.006,
        timezone="America/New_York",
        schedule=[],
        forecast=[live_fc, dead_fc],
    )
    old = _cfg(location)
    holder, scheduler, db_path = holder_scheduler(old)

    live_key = daemon_mod._forecast_job_id(location, live_fc)
    dead_key = daemon_mod._forecast_job_id(location, dead_fc)

    # Reset the module dict around the test so no state leaks into sibling tests.
    saved = dict(daemon_mod._forecast_failure_streaks)
    daemon_mod._forecast_failure_streaks.clear()
    try:
        # Seed BOTH streaks (live + dead), keyed via the single-source helper.
        daemon_mod._forecast_failure_streaks[live_key] = 2
        daemon_mod._forecast_failure_streaks[dead_key] = 3

        # Reload to a config that DROPS the dead slot (keeps the live one), then apply
        # the prune against the now-live desired set.
        new_location = Location(
            name="Home",
            id="home",
            lat=40.7128,
            lon=-74.006,
            timezone="America/New_York",
            schedule=[],
            forecast=[live_fc],
        )
        new = _cfg(new_location)
        holder.replace(new)

        daemon_mod._prune_forecast_streaks(holder)

        # Dead key pruned (its slot is gone) ...
        assert dead_key not in daemon_mod._forecast_failure_streaks
        # ... and the live key retained with its streak intact (both directions).
        assert daemon_mod._forecast_failure_streaks.get(live_key) == 2
    finally:
        daemon_mod._forecast_failure_streaks.clear()
        daemon_mod._forecast_failure_streaks.update(saved)
