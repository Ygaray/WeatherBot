---
phase: 05-deployment-reboot-survival
reviewed: 2026-06-14T23:10:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - weatherbot/scheduler/daemon.py
  - tests/test_scheduler.py
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-06-14T23:10:00Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Scope was the gap-closure change from commits `360d253` (fix) and `36e10b0` (test): the
new channel-from-settings fallback in `run_daemon` and its two regression tests. The
pre-existing daemon and scheduler-test code were already reviewed at phase 05's prior
completion and were not re-litigated.

The fix is correct and well-reasoned. I verified the key claims by reverting `daemon.py`
to the pre-fix tree (`360d253^`) and re-running the new tests:

- **Single instance threaded into both consumers** — confirmed. `build_channel` is called
  once at the top of `run_daemon`; the resulting `channel` flows into `_register_jobs`
  (line 588), `_run_catchup` (line 610), and `emit_online` (line 650). One construction
  point, one instance per process. No double-build.
- **Lazy import / monkeypatch seam is sound** — confirmed. The code does an in-function
  `from weatherbot.channels import build_channel` (line 572), so the name resolves from the
  `weatherbot.channels` package namespace at call time; the test patches exactly that
  (`monkeypatch.setattr("weatherbot.channels.build_channel", ...)`). The seam is real and
  the patch lands.
- **Un-guarded build raising at an unexpected point** — acceptable by design. A
  `build_channel` `ValueError` (unknown type / missing webhook) propagates out of
  `run_daemon` before the SIGTERM handler is installed, before the gate, and before
  `scheduler.start()`. Nothing is half-constructed (no DB writes, no scheduler started,
  no signal handler), so this is a clean fail-loud-at-load with no resource leak. Matches
  the documented OPS-02 posture.
- **New tests actually fail without the fix** — confirmed for the primary regression test.
  Against the pre-fix `daemon.py`, `test_online_ping_built_from_settings_when_channel_none`
  fails (`assert [] == [1]` — `build_channel` was never called, ping dropped). See WR-01
  for the caveat on the second test.
- **Secret-leak risk in the new paths** — none. The online ping is a fixed literal with no
  interpolation; `build_channel` failures surface the channel *type* and a missing-webhook
  message, never the webhook URL value; no new logging added.

One warning and two info items below.

## Warnings

### WR-01: `test_injected_channel_skips_build` does not fail without the production fix (weak regression value)

**File:** `tests/test_scheduler.py:940-983`
**Issue:** I ran both new tests against the pre-fix `daemon.py`. The primary test fails as
intended, but `test_injected_channel_skips_build` **passes against the pre-fix code too**.
That is expected from its own logic — in both old and new code an injected channel takes
the same path and `build_channel` is never reached — but it means this test does not guard
the behavior its docstring claims to ("guards the additive None path against a future
refactor that always builds"). It only proves "an injected channel delivers the ping,"
which `test_online_once_fires_all_signals_then_starts` already covers. The one *new*
assertion with teeth — that `build_channel` is not called when a channel is injected — would
only fail under a hypothetical future refactor, not under any current or pre-fix code, so
it adds little regression coverage for *this* change.

This is not a correctness bug; it is a coverage-quality gap. The more valuable missing test
is the **fail-loud path**: there is no test asserting that a `build_channel` `ValueError`
propagates out of `run_daemon` (the explicitly-documented "fails loud at startup" contract
in the WR-04 / OPS-02 comment). That contract is currently unverified.

**Fix:** Add a test that monkeypatches `weatherbot.channels.build_channel` to raise
`ValueError` and asserts `run_daemon` re-raises it before the scheduler starts:
```python
def test_build_channel_failure_fails_loud(tmp_db, monkeypatch):
    import weatherbot.scheduler.daemon as daemon_mod
    from weatherbot.weather.store import init_db
    init_db(tmp_db)

    sched = _StartObservableScheduler()
    monkeypatch.setattr(daemon_mod, "BackgroundScheduler", lambda: sched)

    def _boom(config, settings):
        raise ValueError("Unknown channel type 'sms'")
    monkeypatch.setattr("weatherbot.channels.build_channel", _boom)

    with pytest.raises(ValueError):
        daemon_mod.run_daemon(
            config=_no_slot_config(), settings=object(), db_path=tmp_db
        )
    assert sched.started is False  # never came "online" with no delivery path
```

## Info

### IN-01: `channel=None` + `settings=None` diverges silently from `send_now`'s contract

**File:** `weatherbot/scheduler/daemon.py:568`
**Issue:** The guard is `if channel is None and settings is not None`. When BOTH are None,
`send_now` (cli.py:119-122) raises `ValueError("send_now requires either a channel or
settings")`, but `run_daemon` silently leaves `channel = None`: the online ping is dropped
by `emit_online`'s guard, and any *enabled* slot that fires will defer the same `ValueError`
to `fire_slot` at fire-time (where it is swallowed and turned into an `internal_error`
alert). The production CLI path always passes a non-None `settings` (cli.py:480), so this
only affects direct/test callers and is documented in the comment — hence info, not a
warning. Worth a one-line note so a future caller is not surprised that a both-None daemon
comes "online" with no delivery path and only discovers it at first fire.
**Fix:** Optional — either accept the documented behavior, or mirror `send_now` and raise
when both are None so a no-delivery-path daemon fails loud at startup like the bad-webhook
case it sits next to.

### IN-02: Third copy of the `_NeverSetImmediateWait` fake (now module-level)

**File:** `tests/test_scheduler.py:869-883` (also defined locally at lines 674-682 and
842-851)
**Issue:** The fix commit promotes `_NeverSetImmediateWait` to a module-level class, but the
two earlier in-test copies (inside `test_run_daemon_stamps_tick_at_startup` and
`test_online_once_fires_all_signals_then_starts`) remain. Three identical definitions of the
same fake is duplication that will drift. Not a test-correctness issue (all 27 pass), purely
maintainability.
**Fix:** Delete the two local copies and let those tests reference the module-level class
that now exists above them — or move all of these stop-Event fakes into a shared test helper /
`conftest.py` fixture.

---

_Reviewed: 2026-06-14T23:10:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
