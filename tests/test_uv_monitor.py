"""Phase-15 UV monitor — Wave-0 scaffold + build-time dependency canary.

This file is the Wave-0 home for the proactive UV monitor. It currently holds
ONLY the dependency canary (the Phase-14/Phase-12 contract the monitor consumes)
and the cross-module import guards — it asserts the primitives exist BEFORE any
monitor logic is built, so a regression in compute_uv's signature or in the
``hourly[].uvi`` payload widening fails LOUDLY at build time rather than silently
at a noon tick (RESEARCH §"Phase-14 Dependency Contract" / Pitfall 1).

Pending coverage (Plan 15-02 fills these in — UV-04 / UV-05 / UV-06):
- the per-tick active-today + daylight gate (reuses ``catchup.fires_on``),
- the three decision branches (pre-warn / crossing-or-already-high / all-clear),
- the once/day/location/kind dedup via ``claim_uv_alert`` / ``claimed_uv_kinds``,
- failure isolation (a bad location/post never gates a briefing, UV-06).
"""

from __future__ import annotations

import inspect


# --- Dependency canary: Phase-14 compute_uv signature + UvSummary shape ------


def test_dependency_canary():
    """compute_uv exists with the signature the monitor (15-02) will call.

    Pins the (onecall_imp, onecall_met, threshold, *, tz, now) shape and the
    UvSummary fields the decision branches consume. If Phase 14 ever changes
    this contract, this canary fails before the monitor is even wired.
    """
    from weatherbot.weather.uv import UvSummary, compute_uv

    params = list(inspect.signature(compute_uv).parameters)
    assert params == ["onecall_imp", "onecall_met", "threshold", "tz", "now"]

    # tz is keyword-only (the monitor passes ZoneInfo(location.timezone) by name).
    sig = inspect.signature(compute_uv)
    assert sig.parameters["tz"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["now"].kind is inspect.Parameter.KEYWORD_ONLY

    # The UvSummary fields the three decision branches read.
    fields = set(getattr(UvSummary, "__annotations__", {}))
    assert {
        "current",
        "crossing_time",
        "window_start",
        "window_end",
        "stays_below",
    } <= fields


# --- Canary: the One Call payload still carries hourly[].uvi (Pitfall 1) -----


def test_hourly_uvi_present(load_fixture):
    """The recorded One Call fixture keeps a non-empty hourly[] with uvi.

    Proves the Phase-12 ``exclude="minutely"`` widening (KEEP ``hourly``) still
    feeds the monitor: with ``hourly`` stripped the crossing-time/window math has
    nothing to interpolate (Pitfall 1). Every bucket must carry a ``uvi`` key.
    """
    payload = load_fixture("onecall_imperial_uvcross.json")
    hourly = payload.get("hourly")
    assert isinstance(hourly, list) and len(hourly) > 0
    assert all("uvi" in bucket for bucket in hourly)

    # Daylight bounding (15-02) needs daily[0].sunrise/sunset — confirm present.
    daily0 = (payload.get("daily") or [{}])[0]
    assert "sunrise" in daily0 and "sunset" in daily0


# --- Canary: fires_on is the public, importable active-today symbol ----------


def test_fires_on_public():
    """``catchup.fires_on`` imports (promoted from ``_fires_on``).

    The monitor reuses this single source-of-truth active-today logic instead of
    forking the weekday parsing.
    """
    from weatherbot.scheduler.catchup import fires_on

    assert callable(fires_on)
