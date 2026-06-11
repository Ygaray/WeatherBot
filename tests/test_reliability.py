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

from weatherbot.channels.base import DeliveryResult
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
# Wave-0 stubs — downstream plans (04-03 / 04-04) remove the skip + fill body.
# Named EXACTLY per RESEARCH "Phase Requirements -> Test Map".
# --------------------------------------------------------------------------- #


@pytest.mark.skip(reason="implemented in Plan 04-03")
def test_transient_retries_then_succeeds():
    """RELY-01: transient (5xx/timeout) retries then succeeds within bursts."""


@pytest.mark.skip(reason="implemented in Plan 04-03")
def test_auth_no_retry():
    """RELY-02: 401/403 short-circuits, NO retry, reason=auth_failed."""


@pytest.mark.skip(reason="implemented in Plan 04-03")
def test_exhaustion_alerts():
    """RELY-03: exhausted retry writes one alerts row + CRITICAL briefing_missed."""


@pytest.mark.skip(reason="implemented in Plan 04-03")
def test_alert_dedup_no_loop():
    """RELY-04: alert path touches no Discord; at most one row per slot/day."""


@pytest.mark.skip(reason="implemented in Plan 04-03")
def test_heartbeat_upsert():
    """RELY-05: tick stamps last_tick; success stamps last_success; event emitted."""


@pytest.mark.skip(reason="implemented in Plan 04-03")
def test_exception_isolation():
    """RELY-06: injected exception → traceback + internal_error alert + survives."""


@pytest.mark.skip(reason="implemented in Plan 04-03")
def test_pause_interruptible():
    """D-07: mid-pause is interruptible (set stop_event → retry abandons fast)."""
