---
phase: 16-extract-shared-dispatch-spec
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - weatherbot/interactive/dispatch.py
  - weatherbot/interactive/bot.py
  - weatherbot/cli.py
  - tests/test_dispatch.py
findings:
  critical: 0
  warning: 0
  info: 3
  total: 3
status: resolved
resolved_in: 695e22f
---

> **Resolution (695e22f):** Both warnings addressed. **WR-01** — added 4 direct
> `dispatch_spec` async tests (`tests/test_dispatch.py`): forecast 3-arg+suffix
> lookup, plain-weather 2-arg lookup, `UnknownLocationError` propagation, and
> argless-spec-never-fetches. Suite now 587 passed. **WR-02** — `dispatch.py`
> docstring + inline comment now state explicitly that running the whole ladder
> off-loop (every handler, not just `status`) is a deliberate, behavior-preserving
> widening. The 3 Info items are left as-is (acceptable for v1 per the notes).

# Phase 16: Code Review Report

**Reviewed:** 2026-06-23
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

This is a behavior-preserving refactor that lifts the duplicated arg-adaptation
`if/elif` ladder out of `on_message` (bot.py) and `_run_registry_command`
(cli.py) into `weatherbot/interactive/dispatch.py` (`dispatch_reply` sync ladder +
`dispatch_spec` async fetch wrapper).

I verified all five stated correctness properties against the pre-refactor code
(commits `57f890a` bot, `83be161` cli) and the supporting modules
(`registry.py`, `command.py`, `cache.py`, `commands/status.py`):

1. **No behavior drift in the ladder** — `dispatch_reply`'s seven branches match
   the two old ladders verbatim, in identical order, with identical handler arg
   shapes. Cross-checked against `registry.COMMANDS` (`group`/`name`/
   `takes_location` values) and handler signatures in `_wire_handlers`. PASS.
2. **Shared code is read-only** — `dispatch_reply` only invokes the handler and
   reads `DaemonState`; `dispatch_spec` only fetches via `cache.lookup` and parses
   flags. No store/sent-log/scheduler writes anywhere in `dispatch.py`. PASS.
3. **`UnknownLocationError` bubbles** — `dispatch_spec` does not catch it; both
   call sites (`on_message` try/except at bot.py:292, `_run_registry_command` at
   cli.py:600) still own their surface-specific reply. PASS.
4. **Bot `status` path stays off-loop** — the whole `dispatch_reply` now runs via
   `run_in_executor` (dispatch.py:158), so `status`'s `read_heartbeat` SQLite read
   stays off the gateway loop. PASS (and strengthened — see WR-02).
5. **No new import cycle** — `command.py` imports `registry`/`scheduler.days`, not
   `dispatch`; only `bot.py`/`cli.py` import `dispatch`. Verified by importing both
   modules together at runtime (acyclic). `ruff check` clean; full suite (583
   tests) green. PASS.

The refactor is correct and faithful. The findings below are a test-coverage gap
on the new async wrapper and a documented-but-unguarded behavior change, plus
minor quality notes. No blockers.

## Warnings

### WR-01: `dispatch_spec` (the async wrapper) has zero direct test coverage

**File:** `tests/test_dispatch.py` (entire file); `weatherbot/interactive/dispatch.py:105-167`
**Issue:** `test_dispatch.py` exercises only the sync `dispatch_reply` ladder. The
new `dispatch_spec` wrapper — which owns three non-trivial responsibilities that
were *moved* out of `on_message`: the forecast-flags parse, the cache-key `suffix`
widening (the A5 collision guard), and the 2-arg vs 3-arg `cache.lookup` dispatch —
is never tested directly. `grep -rln dispatch_spec tests/` returns nothing. The
bot-level tests (`test_bot.py`) cover it only transitively through `on_message`, so
a regression in the wrapper's branch selection (e.g. forecast vs plain-weather
suffix logic, or `flags.location` vs raw `arg` as the lookup name) would not be
caught by the unit tests that exist for this module. For a module whose entire
stated purpose is "the one place the binding lives so it can never drift," the
drift-prone half is the one left untested.
**Fix:** Add async tests for `dispatch_spec` mirroring the `dispatch_reply` table.
Drive it with a fake `cache` recording its `lookup` args and a real event loop, and
assert per spec shape:
```python
import asyncio

class _SpyCache:
    def __init__(self): self.calls = []
    def lookup(self, name, config, *rest):
        self.calls.append((name, config, rest))
        return object()

def test_dispatch_spec_forecast_widens_cache_key():
    cache = _SpyCache()
    loop = asyncio.new_event_loop()
    spec = _FakeSpec("weekday-forecast", "Forecast", True, lambda r, f: _SENTINEL)
    reply = loop.run_until_complete(
        dispatch_spec(spec, "home +sat", cache=cache, config=_FakeConfig(),
                      loop=loop, daemon_state=None)
    )
    # forecast → 3-arg lookup with a non-None suffix, lookup_name == flags.location
    (name, _cfg, rest), = cache.calls
    assert name == "home" and rest and rest[0] is not None

def test_dispatch_spec_plain_weather_uses_2arg_lookup():
    cache = _SpyCache()
    loop = asyncio.new_event_loop()
    spec = _FakeSpec("weather", "Weather", True, lambda r: _SENTINEL)
    loop.run_until_complete(
        dispatch_spec(spec, "home", cache=cache, config=_FakeConfig(),
                      loop=loop, daemon_state=None)
    )
    (name, _cfg, rest), = cache.calls
    assert name == "home" and rest == ()  # back-compat 2-arg form, no suffix
```
Also add a case asserting `UnknownLocationError` raised by `cache.lookup`
propagates out of `dispatch_spec` (criterion #3), and a non-`takes_location` case
asserting `cache.lookup` is never called.

### WR-02: Undocumented behavior change — weather-view / locations / help handlers now run off-loop in the bot

**File:** `weatherbot/interactive/dispatch.py:156-167` vs old `bot.py` ladder
**Issue:** In the pre-refactor bot ladder, only the `status` handler ran via
`run_in_executor`; the `takes_location` handler invocation
(`spec.handler(result, flags)` etc.), `locations`, and `help` all ran *on* the
event loop (the fetch ran off-loop, but the handler call did not). The new
`dispatch_spec` runs the **entire** `dispatch_reply` off-loop, so every handler
invocation — not just `status` — is now dispatched to the executor. This is benign
(the weather-view/locations/help handlers are pure in-memory reads of an
already-fetched payload, no I/O) and the dispatch.py docstring justifies the
whole-ladder-off-loop choice solely by `status`'s SQLite read. But it is a real
divergence from the old on-loop behavior for several commands and is not called out
as a deliberate change — and the only guard against it regressing,
`test_blocking_work_runs_off_loop`, asserts `assert executor_dispatched` (at least
one executor dispatch), so it cannot distinguish "fetch off-loop, handler on-loop"
from "both off-loop."
**Fix:** Either (a) make the docstring at dispatch.py:156-157 explicit that the
whole ladder — every handler, not only `status` — is now off-loop and that this is
an intentional, harmless widening; or (b) if minimal behavior change is preferred,
keep only the `status` branch off-loop (run `dispatch_reply` on-loop and have the
`status` handler alone go through the executor) to exactly mirror the old ladder.
Option (a) is the lower-risk choice given the handlers are non-blocking. Optionally
tighten the test to assert the handler invocation itself is among the off-loop
dispatches.

## Info

### IN-01: `dispatch_spec` accepts `cache` even when it is never used

**File:** `weatherbot/interactive/dispatch.py:105-167`
**Issue:** `cache` is a required keyword argument, but it is only touched inside the
`if spec.takes_location:` branch. For a non-location spec (`status`, `locations`,
`help`) the caller must still pass a real cache that goes unused. The bot always has
one so this is harmless today, but it couples the convenience wrapper to a
collaborator it does not need for half the command set.
**Fix:** Acceptable as-is for v1 (single caller). If the Phase-17 panel ends up
dispatching argless commands without a cache handy, consider documenting that
`cache` may be any object for non-location specs, or splitting the argless path.

### IN-02: `_log` in `dispatch.py` is defined but never used

**File:** `weatherbot/interactive/dispatch.py:41,57`
**Issue:** `import structlog` and `_log = structlog.get_logger(__name__)` are present
but neither `dispatch_reply` nor `dispatch_spec` ever logs. `ruff` does not flag it
(module-level binding), but it is dead scaffolding. Read-only dispatchers that let
errors bubble legitimately have nothing to log, so the logger may be intentional
forward-room.
**Fix:** Remove the unused `_log`/`structlog` import, or add a brief comment that
it is reserved for future diagnostics so a reader does not assume logging happens
here.

### IN-03: Off-loop dispatch uses two sequential `run_in_executor` round-trips for a location command

**File:** `weatherbot/interactive/dispatch.py:147-167`
**Issue:** For a `takes_location` command, `dispatch_spec` awaits one
`run_in_executor` for `cache.lookup`, then a second `run_in_executor` for the whole
`dispatch_reply`. The handler call could be folded into the same executor task as
the fetch (or the handler call left on-loop, per WR-02) to avoid a second
thread-pool hop. This is a clarity/structure note, not a correctness issue —
performance is explicitly out of v1 review scope and the extra hop is negligible.
**Fix:** Optional. If WR-02 is resolved by keeping only `status` off-loop, this hop
disappears naturally for location commands.

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
