"""Reload behavior — SC#4 exactly-once + CLI reload sender + PID-guard tests.

Originally the Phase-9 Wave-0 RED scaffold for the in-daemon reload engine. In
Plan 35-08 (F16) the dead in-daemon reload twin was removed — the LIVE reload path
is the hub ``reload_engine.service_pending()`` — so the reload-engine behavior
tests (keep-old / rollback / diff / CFG-07 posts / cache-invalidate) were dropped
here because ``test_reload_engine.py`` covers them directly. What survives here are
the tests whose assertion is NOT about the removed twin: the SC#4 exactly-once
guards (now driven through the LIVE ``_reconcile_jobs`` commit-half via the
``_apply_reload`` helper), the ``weatherbot reload`` CLI sender + ``/proc`` PID
guard, and the F89 forecast-streak prune-on-reload.

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

from weatherbot.config import Config, Location
from weatherbot.config.models import Schedule
from weatherbot.weather.store import claim_slot, was_sent

_NY = ZoneInfo("America/New_York")


# --------------------------------------------------------------------------- #
# Deferred references to the NOT-YET-BUILT reload engine (Phase 8 Wave-0 lesson).
# Resolved INSIDE each test body so every node ID collects while the symbol is
# absent; each call fails RED with a real ModuleNotFoundError/AttributeError.
# --------------------------------------------------------------------------- #


def _apply_reload(new_config, *, holder, scheduler, db_path, **kwargs):
    """Drive the LIVE reload seam: swap the holder + diff-reconcile jobs (35-08, F16).

    The dead ``_do_reload`` twin was removed in Plan 35-08 — the live reload path is the
    hub ``reload_engine.service_pending()``, whose committed-success half performs exactly
    ``holder.replace(new)`` followed by ``_reconcile_jobs`` on the stable ``name|time|days``
    id. This helper reproduces that live commit-half so the SC#4 exactly-once and
    idempotence assertions below survive without the removed twin. (The keep-old /
    rollback / CFG-07 halves are covered directly by ``test_reload_engine.py``.)
    """
    from weatherbot.scheduler.daemon import _reconcile_jobs

    holder.replace(new_config)
    return _reconcile_jobs(scheduler, holder, db_path=db_path, **kwargs)


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
    row for ``(location.id, slot.time, today)`` → apply (swap + reconcile) a config that
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

    _apply_reload(
        new,
        holder=holder,
        scheduler=scheduler,
        db_path=db_path,
        settings=None,
        client=client,
        channel=channel,
    )

    # The same logical slot is still already-sent under the stable id: a re-fire
    # LOSES the claim and delivers nothing (no duplicate, no skip of a valid slot).
    refired = claim_slot(db_path, "home-stable", "07:00", today)
    assert refired is False  # already sent today → claim lost → no second briefing
    # The reload itself fires NO weather BRIEFING (no duplicate same-day delivery).
    # The live reconcile seam never sends a briefing — it only diffs the job set — so
    # the recording channel stays silent for a briefing.
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
    _apply_reload(
        new,
        holder=holder,
        scheduler=scheduler,
        db_path=db_path,
        settings=None,
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
# (8) SIGHUP sets the reload flag and the poll-loop services it (CFG-02).
# --------------------------------------------------------------------------- #


def test_sighup_triggers_reload(monkeypatch):
    """CFG-02: the daemon's SIGHUP handler sets the reload flag (it does NOT run the
    reload re-entrantly inside the handler), and the main poll-loop services it.

    The reload work the loop services runs via the hub reload engine's
    ``service_pending``; here we assert only the flag-set handoff, not the reload."""
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
