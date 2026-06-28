"""Unit tests for the reusable lifecycle module's ``ReadyGate`` engine (SEAM-05).

Covers the six load-bearing behaviors of the constructor-injection + symmetric
best-effort hook + interruptible re-probe recipe cloned from ``ReloadEngine``:

1. health ok first pass        -> True, on_online once, notifier.ready() once.
2. not-ok then ok              -> loops, on_fail on the failing outcome, then True.
3. stop set during the wait    -> False, NO notifier.ready(), NO on_online.
4. severity branches the log   -> CRITICAL rung logs critical; WARNING logs warning.
5. on_online raises            -> swallowed; gate still True; ready() still fired.
6. on_fail is None             -> no-op; gate still loops/returns correctly.

The fakes: a scripted ``health_check`` returning queued ``HealthResult``s, a
recording fake notifier, a ``threading.Event`` for stop, and recording hook spies.
"""

from __future__ import annotations

import threading

import pytest

from yahir_reusable_bot.lifecycle import HealthResult, ReadyGate, Severity


class _RecordingNotifier:
    """Fake SystemdNotifier: counts ready() calls (READY=1 must be exactly-once)."""

    def __init__(self) -> None:
        self.ready_calls = 0

    def ready(self) -> None:
        self.ready_calls += 1


def _scripted_health_check(results):
    """Return a nullary callable that yields each queued HealthResult in turn.

    After the queue drains it keeps returning the last result (so a misbehaving
    loop can't IndexError; the tests assert it never gets that far).
    """
    queue = list(results)

    def _check() -> HealthResult:
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    return _check


def test_ok_first_pass_returns_true_fires_ready_and_online_once():
    """Behavior 1: ok on the first probe -> True, ready() once, on_online once."""
    notifier = _RecordingNotifier()
    online_calls = []
    gate = ReadyGate(
        _scripted_health_check([HealthResult(ok=True, reason="online")]),
        notifier,
        on_online=lambda _arg: online_calls.append(_arg),
    )
    stop = threading.Event()

    assert gate.run(stop) is True
    assert notifier.ready_calls == 1
    assert len(online_calls) == 1


def test_not_ok_then_ok_loops_then_returns_true_and_calls_on_fail():
    """Behavior 2: not-ok then ok -> loops, on_fail on the failing outcome, then True."""
    notifier = _RecordingNotifier()
    fail_outcomes = []
    gate = ReadyGate(
        _scripted_health_check(
            [
                HealthResult(ok=False, reason="not_ready", severity=Severity.WARNING),
                HealthResult(ok=True, reason="online"),
            ]
        ),
        notifier,
        re_probe_interval=0.0,  # don't actually wait between probes
        on_fail=lambda res: fail_outcomes.append(res),
    )
    stop = threading.Event()

    assert gate.run(stop) is True
    assert notifier.ready_calls == 1
    # on_fail fired exactly once on the failing outcome; not on the passing one.
    assert len(fail_outcomes) == 1
    assert fail_outcomes[0].ok is False


def test_stop_during_wait_returns_false_without_ready_or_online():
    """Behavior 3: stop set during the wait -> False, NO ready(), NO on_online."""
    notifier = _RecordingNotifier()
    online_calls = []
    stop = threading.Event()
    stop.set()  # pre-set: stop.wait returns immediately True after the first fail
    gate = ReadyGate(
        _scripted_health_check(
            [HealthResult(ok=False, reason="not_ready", severity=Severity.WARNING)]
        ),
        notifier,
        re_probe_interval=10.0,
        on_online=lambda _arg: online_calls.append(_arg),
    )

    assert gate.run(stop) is False
    assert notifier.ready_calls == 0
    assert online_calls == []


def test_severity_branches_log_level_not_reason_string(caplog):
    """Behavior 4: CRITICAL rung logs at critical; WARNING rung logs at warning."""
    import logging

    notifier = _RecordingNotifier()

    # CRITICAL rung -> a critical-level record.
    gate_crit = ReadyGate(
        _scripted_health_check(
            [
                HealthResult(
                    ok=False, reason="bad", detail="401", severity=Severity.CRITICAL
                ),
                HealthResult(ok=True, reason="online"),
            ]
        ),
        notifier,
        re_probe_interval=0.0,
    )
    with caplog.at_level(logging.WARNING):
        assert gate_crit.run(threading.Event()) is True
    assert any(r.levelno == logging.CRITICAL for r in caplog.records), (
        "CRITICAL severity must log at critical level"
    )

    caplog.clear()

    # WARNING rung -> a warning-level record, NO critical record.
    gate_warn = ReadyGate(
        _scripted_health_check(
            [
                HealthResult(
                    ok=False, reason="bad", detail="conn", severity=Severity.WARNING
                ),
                HealthResult(ok=True, reason="online"),
            ]
        ),
        _RecordingNotifier(),
        re_probe_interval=0.0,
    )
    with caplog.at_level(logging.WARNING):
        assert gate_warn.run(threading.Event()) is True
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert not any(r.levelno == logging.CRITICAL for r in caplog.records), (
        "WARNING severity must NOT log at critical level"
    )


def test_on_online_raising_is_swallowed_gate_still_true_and_ready_fired():
    """Behavior 5: on_online raises -> swallowed; gate still True; ready() still fired."""
    notifier = _RecordingNotifier()

    def _boom(_arg):
        raise RuntimeError("hook blew up")

    gate = ReadyGate(
        _scripted_health_check([HealthResult(ok=True, reason="online")]),
        notifier,
        on_online=_boom,
    )

    assert gate.run(threading.Event()) is True
    assert notifier.ready_calls == 1  # best-effort hook never masks the gate result


def test_none_on_fail_is_a_noop_gate_still_loops_and_returns():
    """Behavior 6: on_fail is None -> no-op; gate still loops and returns True."""
    notifier = _RecordingNotifier()
    gate = ReadyGate(
        _scripted_health_check(
            [
                HealthResult(ok=False, reason="not_ready", severity=Severity.WARNING),
                HealthResult(ok=True, reason="online"),
            ]
        ),
        notifier,
        re_probe_interval=0.0,
        on_fail=None,
    )

    assert gate.run(threading.Event()) is True
    assert notifier.ready_calls == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
