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


def test_severity_branches_log_level_not_reason_string():
    """Behavior 4: CRITICAL rung logs at critical; WARNING rung logs at warning.

    The gate branches the startup log on the NEUTRAL ``severity`` rung, never by
    comparing ``reason`` to a string. Asserted via ``structlog.testing.capture_logs``
    (config-independent — it intercepts at the proxy level, so it is robust to other
    tests reconfiguring structlog, unlike stdlib ``caplog`` or monkeypatching the
    lazy logger proxy).
    """
    from structlog.testing import capture_logs

    # CRITICAL rung -> a critical-level entry, NO warning entry for the failing probe.
    gate_crit = ReadyGate(
        _scripted_health_check(
            [
                HealthResult(
                    ok=False, reason="bad", detail="401", severity=Severity.CRITICAL
                ),
                HealthResult(ok=True, reason="online"),
            ]
        ),
        _RecordingNotifier(),
        re_probe_interval=0.0,
    )
    with capture_logs() as logs:
        assert gate_crit.run(threading.Event()) is True
    crit = [e for e in logs if e["log_level"] == "critical"]
    warn = [e for e in logs if e["log_level"] == "warning"]
    assert len(crit) == 1, "CRITICAL severity must log at critical level"
    assert warn == []

    # WARNING rung -> a warning-level entry, NO critical entry.
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
    with capture_logs() as logs:
        assert gate_warn.run(threading.Event()) is True
    crit = [e for e in logs if e["log_level"] == "critical"]
    warn = [e for e in logs if e["log_level"] == "warning"]
    assert len(warn) == 1
    assert crit == [], "WARNING severity must NOT log at critical level"


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


# --------------------------------------------------------------------------- #
# Phase 33 Plan 03 (HARD-UI-02, D-04/F17/F22): _on_applied side-effect ordering
# + SelectedContext reconcile-on-reload.
#
# F17 — `_on_applied` must run `cache.invalidate()` BEFORE the (slow) Discord
#       `channel.send(...)` reload-outcome post, so a slow post can no longer
#       delay invalidation and serve OLD coords to an inbound `!weather <loc>`.
# F22 — a `SelectedContext` naming a location the reloaded config no longer has
#       (renamed/removed) is reconciled to the default (config.locations[0].name)
#       so a later `resolve_location(selection.value)` cannot raise
#       UnknownLocationError for a location the user never sees selected.
#
# Both fixes ride the extracted, testable module-level seams in wiring.py:
#   `wiring._apply_reload_side_effects(...)` — the ordered best-effort trio +
#   reconcile that `_on_applied` delegates to; and `wiring._reconcile_selection`.
# RED until Task 2 lands those seams (send-before-invalidate today; no reconcile).
# --------------------------------------------------------------------------- #


class _OrderSpyChannel:
    """Records `send` into a shared order list (best-effort reload-outcome post)."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.sent_text: list[str] = []

    def send(self, text: str) -> None:
        self._order.append("send")
        self.sent_text.append(text)


class _OrderSpyCache:
    """Records `invalidate` into the same shared order list."""

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.invalidate_calls = 0

    def invalidate(self) -> None:
        self._order.append("invalidate")
        self.invalidate_calls += 1


def _loc(name: str, *, lat: float = 40.0, lon: float = -74.0):
    from weatherbot.config.models import Location

    return Location(name=name, lat=lat, lon=lon, timezone="UTC", schedule=[])


def _cfg(*locations):
    from weatherbot.config.models import Config

    return Config(locations=list(locations))


def test_invalidate_before_send(holder_scheduler):
    """F17: `_apply_reload_side_effects` invalidates the cache BEFORE posting the
    reload outcome — a slow Discord `send` can no longer delay invalidation and
    serve OLD coords to an inbound `!weather <loc>`. The spy channel + spy cache
    append their names to a shared order list; invalidate must precede send."""
    import weatherbot.scheduler.wiring as wiring

    config = _cfg(_loc("Home"))
    holder, _scheduler, _db = holder_scheduler(config)

    order: list[str] = []
    channel = _OrderSpyChannel(order)
    cache = _OrderSpyCache(order)

    wiring._apply_reload_side_effects(
        "loc:Home",
        channel=channel,
        cache=cache,
        holder=holder,
        selection=None,
    )

    assert cache.invalidate_calls == 1
    assert channel.sent_text == ["✅ config reloaded: loc:Home"], (
        "the reload-outcome send string must stay byte-identical"
    )
    assert order.index("invalidate") < order.index("send"), (
        "invalidate must fire BEFORE the slow reload-outcome send (F17)"
    )


def test_selection_reconcile_on_reload(holder_scheduler):
    """F22: a `SelectedContext` naming a location the reloaded config dropped/renamed
    is reconciled to the default (config.locations[0].name) on hot-reload, so a
    subsequent `resolve_location(config, selection.value)` does NOT raise
    UnknownLocationError for a location the user never sees selected."""
    import weatherbot.scheduler.wiring as wiring
    from weatherbot.config.loader import resolve_location
    from yahir_reusable_bot.discord import SelectedContext

    # Initial config the selection was seeded against (the user picked "London").
    old = _cfg(_loc("Toronto"), _loc("London"))
    selection: SelectedContext[str] = SelectedContext("London")
    assert resolve_location(old, selection.value).name == "London"  # sanity: live now

    # Hot-reload a config that RENAMES/REMOVES "London" — the selection now dangles.
    new = _cfg(_loc("Toronto"), _loc("Paris"))
    holder, _scheduler, _db = holder_scheduler(new)

    wiring._apply_reload_side_effects(
        "loc:Paris",
        channel=None,
        cache=None,
        holder=holder,
        selection=selection,
    )

    # Reconciled to the default (first configured location), never left stale.
    assert selection.value == new.locations[0].name == "Toronto"
    # And the reconciled selection resolves cleanly — no UnknownLocationError.
    assert resolve_location(new, selection.value).name == "Toronto"


def test_reconcile_selection_leaves_a_still_present_selection_untouched(
    holder_scheduler,
):
    """F22 no-op case: a selection whose location SURVIVES the reload is left as-is
    (the reconcile only fires on a gone location — it never resets a live pick)."""
    import weatherbot.scheduler.wiring as wiring

    new = _cfg(_loc("Toronto"), _loc("London"))

    from yahir_reusable_bot.discord import SelectedContext

    selection: SelectedContext[str] = SelectedContext("London")
    wiring._reconcile_selection(selection, new)
    assert selection.value == "London", "a still-present selection must not be reset"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
