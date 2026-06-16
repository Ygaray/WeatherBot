"""Tests for the Phase-4 reliability engine (RELY-01..06 + D-07).

This is the Wave-0 test scaffold every later Phase-4 plan extends. The engine
tests below (the two-burst wait shape, the transient/auth classifiers, the
capped ``Retry-After`` parser, the ``build_retrying`` behavior and the
``Retry-After`` *honoring* test) are REAL and pass now (implemented in Plan
04-01). The remaining behavior tests (alerts, heartbeat, exception isolation,
interruptible pause) are present as ``pytest.mark.skip`` stubs so the file
collects green today and each downstream plan (04-03 / 04-04) just removes the
skip and fills the body — nobody re-invents test names.

Secret-hygiene assertion convention (carried from ``tests/test_store.py``
lines 135-147 / T-04-01): when a test exercises a path that could persist or
log untrusted text, grep the stored rows / captured log fields for ``"appid"``
and ``"api.openweathermap.org"`` and assert they are absent — no secret (the
OpenWeather key lives only in the ``appid`` query param / request URL) may ever
reach a DB row or a log field.

The fast-test technique (RESEARCH "Wave 0 Gaps"): pass a RECORDING MOCK as
tenacity's ``sleep=`` callable so the two-burst durations are recorded in
milliseconds instead of really slept — the schedule is asserted without any
real wall-clock waiting.
"""

from __future__ import annotations

import sqlite3
import threading
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from weatherbot.channels.base import Channel, DeliveryResult
from weatherbot.reliability import (
    build_retrying,
    is_auth_failure,
    is_transient,
    parse_retry_after,
)
from weatherbot.reliability.retry import (
    BURST_SIZE,
    BURST_SPREAD_S,
    MID_PAUSE_S,
    REASON_AUTH_FAILED,
    REASON_INTERNAL_ERROR,
    REASON_TRANSIENT_EXHAUSTED,
    RETRY_AFTER_CAP_S,
    two_burst_wait,
)


def _connect(db_path):
    """sqlite3 connection with row access by name (copied from test_store.py)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _status_error(status: int, *, headers: dict | None = None) -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError carrying a real response (status + headers)."""
    request = httpx.Request("GET", "https://example.test/")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


class _Outcome:
    """Minimal stand-in for tenacity's Future-like outcome (failed + exception())."""

    def __init__(self, exc: BaseException | None):
        self._exc = exc

    @property
    def failed(self) -> bool:
        return self._exc is not None

    def exception(self) -> BaseException | None:
        return self._exc


class _State:
    """Minimal RetryCallState stand-in for unit-testing two_burst_wait directly."""

    def __init__(self, attempt_number: int, outcome: _Outcome | None = None):
        self.attempt_number = attempt_number
        self.outcome = outcome


# --------------------------------------------------------------------------- #
# Engine tests (REAL — implemented in Plan 04-01)
# --------------------------------------------------------------------------- #


def test_two_burst_wait_shape():
    """Within-burst attempts are a bounded spread (< ~150s); attempt 8 → MID_PAUSE."""
    # Attempts 1..7 and 9..15 are within-burst spread waits (small, bounded).
    for n in list(range(1, BURST_SIZE)) + list(range(BURST_SIZE + 1, 2 * BURST_SIZE)):
        wait = two_burst_wait(_State(n))
        assert 0.0 <= wait < 150.0, f"attempt {n} wait {wait} out of within-burst range"
    # Attempt == BURST_SIZE is the long burst-1 -> burst-2 pause, exactly MID_PAUSE_S.
    assert two_burst_wait(_State(BURST_SIZE)) == MID_PAUSE_S


def test_is_transient_classification():
    assert is_transient(httpx.TimeoutException("t")) is True
    assert is_transient(httpx.ConnectError("c")) is True
    assert is_transient(httpx.ReadError("r")) is True
    for status in (429, 500, 502, 503, 504):
        assert is_transient(_status_error(status)) is True, status
    for status in (400, 401, 403, 404):
        assert is_transient(_status_error(status)) is False, status
    assert is_transient(ValueError("bug")) is False


def test_is_auth_failure_classification():
    assert is_auth_failure(_status_error(401)) is True
    assert is_auth_failure(_status_error(403)) is True
    for status in (400, 404, 500):
        assert is_auth_failure(_status_error(status)) is False, status
    assert is_auth_failure(httpx.TimeoutException("t")) is False


def test_parse_retry_after_seconds_date_absent_and_capped():
    # Seconds form.
    request = httpx.Request("GET", "https://example.test/")
    resp = httpx.Response(429, headers={"Retry-After": "30"}, request=request)
    assert parse_retry_after(resp) == 30.0
    # Absent header.
    resp_none = httpx.Response(429, request=request)
    assert parse_retry_after(resp_none) is None
    # Oversized seconds value is capped (DoS-of-self mitigation).
    resp_big = httpx.Response(429, headers={"Retry-After": "9999"}, request=request)
    assert parse_retry_after(resp_big) == RETRY_AFTER_CAP_S
    # HTTP-date form (a near-future date) parses to a small positive, capped.
    future = datetime.now(timezone.utc) + timedelta(seconds=20)
    resp_date = httpx.Response(
        429, headers={"Retry-After": format_datetime(future)}, request=request
    )
    parsed = parse_retry_after(resp_date)
    assert parsed is not None and 0.0 <= parsed <= RETRY_AFTER_CAP_S


def test_parse_retry_after_malformed_returns_none():
    """WR-05: a garbage Retry-After header returns None instead of raising.

    The header is untrusted input (V5). A malformed HTTP-date must not raise out
    of the wait callable (where it would be mislabeled internal_error on the daemon
    path or crash the manual CLI) — it degrades to "no usable header".
    """
    request = httpx.Request("GET", "https://example.test/")
    for garbage in ("not-a-date", "Mon, 99 Zzz 9999 99:99:99 GMT", "!!!", "2026-13-40"):
        resp = httpx.Response(429, headers={"Retry-After": garbage}, request=request)
        assert parse_retry_after(resp) is None, garbage


def test_malformed_retry_after_falls_back_to_base():
    """WR-05: a 429 with a garbage Retry-After waits the plain base, never crashes."""
    stop = threading.Event()
    slept: list[float] = []
    retrying = build_retrying(stop)
    retrying.sleep = lambda d: slept.append(d)

    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status_error(429, headers={"Retry-After": "not-a-date"})
        return DeliveryResult(ok=True)

    result = retrying(attempt)
    assert result.ok is True
    # The garbage header parsed to None -> the wait fell back to the within-burst
    # base (>= step), not a crash.
    step = BURST_SPREAD_S / (BURST_SIZE - 1)
    assert len(slept) == 1 and slept[0] >= step


def test_build_retrying_transient_then_success():
    """A transient-then-success callable succeeds through the schedule (mock sleep)."""
    stop = threading.Event()
    slept: list[float] = []
    retrying = build_retrying(stop)
    retrying.sleep = lambda d: slept.append(d)  # record, never really sleep

    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("transient")
        return DeliveryResult(ok=True)

    result = retrying(attempt)
    assert result.ok is True
    assert calls["n"] == 3
    assert len(slept) == 2  # waited after the two failing attempts


def test_build_retrying_auth_not_retried():
    """A 401-raising callable is NOT retried — it raises out on attempt 1."""
    stop = threading.Event()
    retrying = build_retrying(stop)
    retrying.sleep = lambda d: None

    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        raise _status_error(401)

    with pytest.raises(httpx.HTTPStatusError):
        retrying(attempt)
    assert calls["n"] == 1  # single attempt, no retry (RELY-02)


def test_build_retrying_sleep_is_stop_event_wait():
    """The builder wires sleep=stop_event.wait (interruptible pause, D-07)."""
    stop = threading.Event()
    retrying = build_retrying(stop)
    assert retrying.sleep == stop.wait


def test_build_retrying_stops_at_16_attempts():
    """An always-transient callable exhausts after exactly 2*BURST_SIZE attempts."""
    stop = threading.Event()
    slept: list[float] = []
    retrying = build_retrying(stop)
    retrying.sleep = lambda d: slept.append(d)

    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        raise httpx.ConnectError("always transient")

    with pytest.raises(httpx.ConnectError):
        retrying(attempt)
    assert calls["n"] == 2 * BURST_SIZE  # 16 attempts (D-07)


def test_retry_after_capped():
    """HONORING (not merely parsing): the schedule WAITS the capped Retry-After.

    A callable raising HTTPStatusError(429) with `Retry-After: 9999` once, then
    succeeding, run through build_retrying with a recording-mock sleep=, must
    record a sleep EQUAL to RETRY_AFTER_CAP_S for that attempt (9999 > base AND
    > cap → honored value is the cap). Proves the wait callable actually waits
    the honored Retry-After, not just that parse_retry_after returns it.
    """
    stop = threading.Event()
    slept: list[float] = []
    retrying = build_retrying(stop)
    retrying.sleep = lambda d: slept.append(d)

    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status_error(429, headers={"Retry-After": "9999"})
        return DeliveryResult(ok=True)

    result = retrying(attempt)
    assert result.ok is True
    assert slept == [RETRY_AFTER_CAP_S]  # honored the CAPPED Retry-After

    # A 429 with a tiny Retry-After falls back to the larger two-burst base.
    stop2 = threading.Event()
    slept2: list[float] = []
    retrying2 = build_retrying(stop2)
    retrying2.sleep = lambda d: slept2.append(d)
    calls2 = {"n": 0}

    def attempt2():
        calls2["n"] += 1
        if calls2["n"] == 1:
            raise _status_error(429, headers={"Retry-After": "1"})
        return DeliveryResult(ok=True)

    # max() semantics: the within-burst base (floor = step ~85.7s) wins over the
    # tiny 1s Retry-After. Compare against the jitter-free floor, not a second
    # jittered base evaluation.
    step = BURST_SPREAD_S / (BURST_SIZE - 1)
    retrying2(attempt2)
    assert slept2[0] >= step  # base (>= step) won over the capped 1s Retry-After

    # A transient WITHOUT a Retry-After (a ConnectError carries no .response) uses
    # the plain two-burst base — no honoring kicks in, so the wait stays within the
    # jitter-bounded within-burst range [step, step*1.5).
    state_no_ra = _State(1, _Outcome(httpx.ConnectError("no header")))
    no_ra_wait = two_burst_wait(state_no_ra)
    assert step <= no_ra_wait < step * 1.5


def test_before_sleep_honors_configured_attempts_per_burst(capsys):
    """WR-03: the retry log's burst index uses the CONFIGURED attempts_per_burst.

    With attempts_per_burst=3, burst 1 is attempts 1-3 and burst 2 starts at
    attempt 4. The default module BURST_SIZE=8 would have logged burst=1 for
    attempt 4 — the bug. structlog renders the event to stdout, so we capture and
    assert the boundary is honored.
    """
    stop = threading.Event()
    retrying = build_retrying(stop, attempts_per_burst=3)
    retrying.sleep = lambda d: None  # never really sleep

    def attempt():
        # Always transient -> exhausts after 2*3 = 6 attempts, logging each retry.
        raise httpx.ConnectError("always transient")

    with pytest.raises(httpx.ConnectError):
        retrying(attempt)

    captured = capsys.readouterr()
    blob = captured.out + captured.err
    # The before_sleep log fires AFTER each failing attempt (attempts 1..5 before
    # the 6th/final): attempts 1-3 are burst 1, attempt 4 onward is burst 2.
    assert "attempt=4 burst=2" in blob
    # The buggy module-constant path would render attempt 4 as burst=1 (8-wide).
    assert "attempt=4 burst=1" not in blob


def test_non_ok_delivery_result_is_retried():
    """RELY-01: a non-ok DeliveryResult (send failure, no exception) is retried."""
    stop = threading.Event()
    slept: list[float] = []
    retrying = build_retrying(stop)
    retrying.sleep = lambda d: slept.append(d)

    calls = {"n": 0}

    def attempt():
        calls["n"] += 1
        if calls["n"] < 2:
            return DeliveryResult(ok=False, detail="503 service unavailable")
        return DeliveryResult(ok=True)

    result = retrying(attempt)
    assert result.ok is True
    assert calls["n"] == 2


# --------------------------------------------------------------------------- #
# Daemon patient-path behavior tests (Plan 04-03 — fire_slot wraps the two-burst
# retry, classifies into the reason taxonomy, resolves + stamps heartbeat).
# Named EXACTLY per RESEARCH "Phase Requirements -> Test Map".
# --------------------------------------------------------------------------- #

from weatherbot.config.holder import ConfigHolder  # noqa: E402
from weatherbot.config.models import Config, Location, Schedule  # noqa: E402
from weatherbot.scheduler import daemon as daemon_mod  # noqa: E402


class _RecordingStop:
    """A stand-in for the daemon ``threading.Event`` whose ``.wait`` records the
    requested durations instead of really sleeping (so the two bursts run in ms).

    ``build_retrying`` wires ``sleep=stop_event.wait``; passing one of these as
    ``fire_slot``'s ``stop_event`` makes the patient retry's pauses instantaneous
    and asserts the exact wait schedule. ``set``/``is_set`` keep the interruptible
    contract for ``test_pause_interruptible``.
    """

    def __init__(self):
        self.slept: list[float] = []
        self._set = False

    def wait(self, timeout=None):  # noqa: ANN001 — Event.wait signature
        self.slept.append(timeout)
        return self._set

    def set(self):
        self._set = True

    def is_set(self):
        return self._set


class _Channel(Channel):
    """A recording channel — proves the alert path makes NO Discord call."""

    name = "fake"

    def __init__(self):
        self.calls = 0

    def send(self, text: str) -> DeliveryResult:  # pragma: no cover - unused
        self.calls += 1
        return DeliveryResult(ok=True)


def _config() -> Config:
    """A minimal one-location config (UTC tz so local_date is deterministic)."""
    loc = Location(
        name="Home",
        lat=40.0,
        lon=-74.0,
        timezone="UTC",
        schedule=[Schedule(time="09:00", days="daily", enabled=True)],
    )
    return Config(locations=[loc], template="briefing.txt")


def _slot(config: Config) -> tuple[Location, Schedule]:
    loc = config.locations[0]
    return loc, loc.schedule[0]


def _patch_send_now(monkeypatch, fn):
    """Replace the lazily-imported ``weatherbot.cli.send_now`` seam."""
    import weatherbot.cli as cli

    monkeypatch.setattr(cli, "send_now", fn)


def _alerts(db_path):
    with _connect(db_path) as conn:
        return list(conn.execute("SELECT * FROM alerts"))


def _heartbeat(db_path):
    with _connect(db_path) as conn:
        return conn.execute("SELECT * FROM heartbeat WHERE id=1").fetchone()


def test_transient_retries_then_succeeds(tmp_db, monkeypatch):
    """RELY-01: transient (5xx/timeout) retries then succeeds within bursts."""
    config = _config()
    loc, slot = _slot(config)
    stop = _RecordingStop()
    channel = _Channel()
    calls = {"n": 0}

    def fake_send_now(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("transient blip")
        return DeliveryResult(ok=True)

    _patch_send_now(monkeypatch, fake_send_now)
    result = daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, channel=channel, stop_event=stop
    )

    assert result is not None and result.ok is True
    assert calls["n"] == 3
    assert _alerts(tmp_db) == []  # no alert on eventual success
    assert _heartbeat(tmp_db)["last_success_utc"] is not None  # success stamped


def test_auth_no_retry(tmp_db, monkeypatch):
    """RELY-02: 401/403 short-circuits, NO retry, reason=auth_failed."""
    config = _config()
    loc, slot = _slot(config)
    stop = _RecordingStop()
    calls = {"n": 0}

    def fake_send_now(*args, **kwargs):
        calls["n"] += 1
        raise _status_error(401)

    _patch_send_now(monkeypatch, fake_send_now)
    result = daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, stop_event=stop
    )

    assert result is None
    assert calls["n"] == 1  # single attempt — auth short-circuits (RELY-02)
    rows = _alerts(tmp_db)
    assert len(rows) == 1
    assert rows[0]["reason"] == REASON_AUTH_FAILED


def test_exhaustion_alerts(tmp_db, monkeypatch, capsys):
    """RELY-03: exhausted retry writes one alerts row + CRITICAL briefing_missed."""
    config = _config()
    loc, slot = _slot(config)
    stop = _RecordingStop()
    calls = {"n": 0}

    def fake_send_now(*args, **kwargs):
        calls["n"] += 1
        raise httpx.ConnectError("always transient")

    _patch_send_now(monkeypatch, fake_send_now)
    result = daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, stop_event=stop
    )

    assert result is None
    assert calls["n"] == 2 * config.reliability.attempts_per_burst  # exhausted
    rows = _alerts(tmp_db)
    assert len(rows) == 1
    assert rows[0]["reason"] == REASON_TRANSIENT_EXHAUSTED
    assert rows[0]["severity"] == "critical"
    # The slot is released (re-fireable) — no sent_log row remains.
    with _connect(tmp_db) as conn:
        sent = list(conn.execute("SELECT * FROM sent_log"))
    assert sent == []
    # CRITICAL briefing_missed event emitted (structlog renders to stdout/stderr),
    # secret-free.
    out = capsys.readouterr()
    blob = out.out + out.err
    assert "briefing_missed" in blob
    assert "transient_exhausted" in blob
    assert "appid" not in blob and "api.openweathermap.org" not in blob


def test_nonok_delivery_exhaustion_alerts_transient(tmp_db, monkeypatch, capsys):
    """RELY-03 / UAT Test 1: an all-attempts-fail DELIVERY (non-ok DeliveryResult,
    NO exception — the Discord-outage case) must alert reason=transient_exhausted,
    NOT internal_error.

    Regression for the live-UAT finding: with bare reraise=True, tenacity raises
    RetryError on non-ok-RESULT exhaustion (it can only reraise a real exception),
    which fire_slot's broad except mis-classified as internal_error — leaving the
    `if not result.ok` (transient_exhausted) branch dead. build_retrying's
    retry_error_callback now returns the last non-ok result instead.
    """
    config = _config()
    loc, slot = _slot(config)
    stop = _RecordingStop()
    calls = {"n": 0}

    def fake_send_now(*args, **kwargs):
        calls["n"] += 1
        return DeliveryResult(ok=False, detail="404 Unknown Webhook")  # never raises

    _patch_send_now(monkeypatch, fake_send_now)
    result = daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, stop_event=stop
    )

    assert result is None
    assert calls["n"] == 2 * config.reliability.attempts_per_burst  # all attempts ran
    rows = _alerts(tmp_db)
    assert len(rows) == 1
    assert rows[0]["reason"] == REASON_TRANSIENT_EXHAUSTED  # NOT internal_error
    assert rows[0]["severity"] == "critical"
    blob = (lambda o: o.out + o.err)(capsys.readouterr())
    assert "briefing_missed" in blob and "transient_exhausted" in blob
    assert "internal_error" not in blob


def test_daemon_retry_after_honored(tmp_db, monkeypatch):
    """RELY-02: a 429 fetch with Retry-After is honored on the daemon path.

    Proves the fetch HTTPStatusError (carrying the header) propagates out of
    send_now into the Retrying wait callable — the daemon waits the CAPPED value.
    """
    config = _config()
    loc, slot = _slot(config)
    stop = _RecordingStop()
    calls = {"n": 0}

    def fake_send_now(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _status_error(429, headers={"Retry-After": "9999"})
        return DeliveryResult(ok=True)

    _patch_send_now(monkeypatch, fake_send_now)
    result = daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, stop_event=stop
    )

    assert result is not None and result.ok is True
    # Exactly one wait was recorded, and it HONORS the capped Retry-After: the
    # daemon waited AT LEAST the capped value (max(base, capped)), proving the
    # fetch HTTPStatusError (with the header) reached the wait callable. The wait
    # never exceeds the cap UNLESS the jittered within-burst base does (max
    # semantics) — so bound it by the cap-or-base ceiling, never below the cap.
    assert len(stop.slept) == 1
    assert stop.slept[0] >= RETRY_AFTER_CAP_S
    assert _alerts(tmp_db) == []


def test_alert_dedup_no_loop(tmp_db, monkeypatch):
    """RELY-04: alert path touches no Discord; at most one row per slot/day."""
    config = _config()
    loc, slot = _slot(config)
    channel = _Channel()

    def fake_send_now(*args, **kwargs):
        raise httpx.ConnectError("always transient")

    _patch_send_now(monkeypatch, fake_send_now)
    # Two consecutive exhausted fires for the same (location, slot, local_date).
    for _ in range(2):
        daemon_mod.fire_slot(
            loc, slot, config=config, db_path=tmp_db, channel=channel,
            stop_event=_RecordingStop(),
        )

    rows = _alerts(tmp_db)
    assert len(rows) == 1  # INSERT-OR-IGNORE dedup (D-11)
    assert channel.calls == 0  # alert path NEVER calls Discord (D-02)


def test_heartbeat_upsert(tmp_db, capsys):
    """RELY-05: tick stamps last_tick; success stamps last_success; event emitted."""
    from weatherbot.weather.store import init_db

    init_db(tmp_db)
    daemon_mod._heartbeat_tick(tmp_db)

    row = _heartbeat(tmp_db)
    assert row["last_tick_utc"] is not None
    out = capsys.readouterr()
    blob = out.out + out.err
    assert "heartbeat" in blob
    assert "appid" not in blob and "webhook" not in blob


def test_heartbeat_job_registered_with_slots(tmp_db):
    """run_daemon registers an __heartbeat__ IntervalTrigger job alongside slots.

    Exercises the registration path without a real wait: register the slot jobs +
    the heartbeat job on a non-started scheduler and assert both are present.
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    config = _config()
    scheduler = BackgroundScheduler()
    daemon_mod._register_jobs(
        scheduler, ConfigHolder(config), db_path=tmp_db, settings=None,
        stop_event=threading.Event(),
    )
    scheduler.add_job(
        daemon_mod._heartbeat_tick,
        trigger=IntervalTrigger(seconds=daemon_mod.HEARTBEAT_INTERVAL_S),
        kwargs={"db_path": tmp_db},
        id="__heartbeat__",
        misfire_grace_time=None,
        coalesce=True,
    )
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "__heartbeat__" in job_ids
    # The one enabled slot job coexists with the heartbeat job.
    assert any(jid.startswith("Home|") for jid in job_ids)
    assert len(job_ids) == 2


def test_exception_isolation(tmp_db, monkeypatch, capsys):
    """RELY-06: injected exception → traceback + internal_error alert + survives."""
    config = _config()
    loc, slot = _slot(config)
    calls = {"n": 0}

    def fake_send_now(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("unexpected bug")
        return DeliveryResult(ok=True)

    _patch_send_now(monkeypatch, fake_send_now)
    first = daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, stop_event=_RecordingStop()
    )

    assert first is None  # does NOT propagate — thread survives (RELY-06)
    rows = _alerts(tmp_db)
    assert len(rows) == 1
    assert rows[0]["reason"] == REASON_INTERNAL_ERROR
    # Full traceback logged (_log.exception → the traceback + the raised
    # ValueError text appear in the rendered output).
    out = capsys.readouterr()
    blob = out.out + out.err
    assert "Traceback" in blob and "unexpected bug" in blob

    # A second INDEPENDENT slot still fires successfully (scheduler survives).
    loc2 = Location(
        name="Away",
        lat=10.0,
        lon=20.0,
        timezone="UTC",
        schedule=[Schedule(time="08:00", days="daily", enabled=True)],
    )
    config2 = Config(locations=[loc2], template="briefing.txt")
    second = daemon_mod.fire_slot(
        loc2, loc2.schedule[0], config=config2, db_path=tmp_db,
        stop_event=_RecordingStop(),
    )
    assert second is not None and second.ok is True


def test_resolve_on_eventual_success(tmp_db, monkeypatch):
    """D-13: an exhausted slot's alert is resolved by a later successful fire."""
    config = _config()
    loc, slot = _slot(config)

    def failing(*args, **kwargs):
        raise httpx.ConnectError("transient")

    _patch_send_now(monkeypatch, failing)
    daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, stop_event=_RecordingStop()
    )
    rows = _alerts(tmp_db)
    assert len(rows) == 1 and rows[0]["resolved_at_utc"] is None

    def ok(*args, **kwargs):
        return DeliveryResult(ok=True)

    _patch_send_now(monkeypatch, ok)
    daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, stop_event=_RecordingStop()
    )
    rows = _alerts(tmp_db)
    assert len(rows) == 1 and rows[0]["resolved_at_utc"] is not None  # D-13
    assert _heartbeat(tmp_db)["last_success_utc"] is not None


def test_pause_interruptible(tmp_db, monkeypatch):
    """D-07: mid-pause is interruptible (set stop_event → retry abandons fast)."""
    import time

    config = _config()
    loc, slot = _slot(config)
    stop = threading.Event()
    calls = {"n": 0}

    def fake_send_now(*args, **kwargs):
        calls["n"] += 1
        # Set the stop event during the FIRST failing attempt so the very next
        # interruptible wait (stop_event.wait) returns immediately.
        stop.set()
        raise httpx.ConnectError("transient")

    _patch_send_now(monkeypatch, fake_send_now)
    started = time.monotonic()
    daemon_mod.fire_slot(
        loc, slot, config=config, db_path=tmp_db, stop_event=stop
    )
    elapsed = time.monotonic() - started

    assert elapsed < 1.0  # abandoned the mid-pause immediately on stop.set()
