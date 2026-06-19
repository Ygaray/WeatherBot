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
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from weatherbot.config.holder import ConfigHolder
from weatherbot.config.models import Config, Location, Schedule, UvConfig

NY = ZoneInfo("America/New_York")


# --- Shared test builders + spies (Task 1/2/3) -------------------------------


def _location(
    *,
    name: str = "home",
    loc_id: str | None = None,
    tz: str = "America/New_York",
    days: str = "everyday",
    enabled: bool = True,
    time: str = "09:00",
) -> Location:
    """A single configured location with one schedule slot (lat/lon = NY)."""
    return Location(
        name=name,
        id=loc_id,
        lat=40.71,
        lon=-74.01,
        timezone=tz,
        schedule=[Schedule(time=time, days=days, enabled=enabled)],
    )


def _config(locations: list[Location], *, uv: UvConfig | None = None) -> Config:
    return Config(locations=locations, uv=uv or UvConfig())


def _holder(config: Config) -> ConfigHolder:
    return ConfigHolder(config)


class FakeClient:
    """A spy One Call client mirroring ``_WeatherClient.fetch_onecall(loc, units)``.

    Records every ``(location.name, units)`` call so a test can assert ZERO
    fetches for a skipped (inactive) location. ``payloads`` maps a units string to
    the recorded fixture dict to return; a single-payload client returns the same
    dict for any units.
    """

    def __init__(self, payload: dict | None = None, *, raises: bool = False) -> None:
        self._payload = payload
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    def fetch_onecall(self, location, units: str) -> dict:
        self.calls.append((location.name, units))
        if self._raises:
            raise RuntimeError("boom-fetch")
        return self._payload or {}


class SpyStore:
    """A module-level monkeypatch target proving ``store.persist`` is never called."""

    def __init__(self) -> None:
        self.persist_calls = 0

    def persist(self, *args, **kwargs) -> None:  # pragma: no cover - must not run
        self.persist_calls += 1


class RecordingChannel:
    """Captures every ``send(text)`` so decision tests can assert post wording/count."""

    def __init__(self, *, raises: bool = False) -> None:
        self.sent: list[str] = []
        self._raises = raises

    def send(self, text: str):
        if self._raises:
            raise RuntimeError("boom-send")
        self.sent.append(text)
        return None


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


# --- Task 1: active-today / daylight gates + read-only fetch ------------------

# Fixtures are anchored to 2024-06-14 NY (sunrise 04:40, sunset 19:40). Pin
# ``now`` against that date so the daylight + decision math is deterministic.
NOON_NY = datetime(2024, 6, 14, 12, 0, tzinfo=NY).astimezone(timezone.utc)
PREDAWN_NY = datetime(2024, 6, 14, 3, 0, tzinfo=NY).astimezone(timezone.utc)
NIGHT_NY = datetime(2024, 6, 14, 22, 0, tzinfo=NY).astimezone(timezone.utc)


def test_active_today_true_for_enabled_slot_firing_today():
    from weatherbot.scheduler.uvmonitor import _active_today

    loc = _location(days="daily", enabled=True)
    assert _active_today(loc, NOON_NY) is True


def test_active_today_false_when_no_enabled_slot_fires_today():
    from weatherbot.scheduler.uvmonitor import _active_today

    # 2024-06-14 is a Friday — a weekends-only slot does NOT fire today.
    weekend = _location(days="weekends", enabled=True)
    assert _active_today(weekend, NOON_NY) is False
    # A disabled everyday slot is skipped even though the weekday matches.
    disabled = _location(days="daily", enabled=False)
    assert _active_today(disabled, NOON_NY) is False


def test_is_daylight_true_between_sun_epochs():
    from weatherbot.scheduler.uvmonitor import _is_daylight

    sunrise = int(datetime(2024, 6, 14, 4, 40, tzinfo=NY).timestamp())
    sunset = int(datetime(2024, 6, 14, 19, 40, tzinfo=NY).timestamp())
    assert _is_daylight(NOON_NY, sunrise, sunset, "America/New_York") is True
    assert _is_daylight(PREDAWN_NY, sunrise, sunset, "America/New_York") is False
    assert _is_daylight(NIGHT_NY, sunrise, sunset, "America/New_York") is False


def test_is_daylight_uses_configured_tz_not_api_offset():
    from weatherbot.scheduler.uvmonitor import _is_daylight

    # Absolute sun epochs expressed at NY wall-clock (04:40 / 19:40 NY). Converted
    # into the LA tz those same instants land at 01:40 / 16:40 LA. So at 18:00 LA
    # it is AFTER the (LA-converted) sunset → NOT daylight, and at 12:00 LA it is
    # in-window. This proves the conversion uses the CONFIGURED tz, not a fixed
    # offset (a naive offset error would flip both answers).
    sunrise = int(datetime(2024, 6, 14, 4, 40, tzinfo=NY).timestamp())
    sunset = int(datetime(2024, 6, 14, 19, 40, tzinfo=NY).timestamp())
    LA = ZoneInfo("America/Los_Angeles")
    la_evening = datetime(2024, 6, 14, 18, 0, tzinfo=LA).astimezone(timezone.utc)
    la_midday = datetime(2024, 6, 14, 12, 0, tzinfo=LA).astimezone(timezone.utc)
    assert _is_daylight(la_evening, sunrise, sunset, "America/Los_Angeles") is False
    assert _is_daylight(la_midday, sunrise, sunset, "America/Los_Angeles") is True


def test_inactive_location_performs_zero_fetches(load_fixture, tmp_db):
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    payload = load_fixture("onecall_imperial_uvcross.json")
    # weekends-only on a Friday → never active → never fetched.
    holder = _holder(_config([_location(days="weekends")]))
    client = FakeClient(payload)
    channel = RecordingChannel()
    _uv_monitor_tick(
        holder, tmp_db, None, client, channel, now_utc=NOON_NY
    )
    assert client.calls == []
    assert channel.sent == []


def test_outside_daylight_fetches_but_takes_no_branch(load_fixture, tmp_db):
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    payload = load_fixture("onecall_imperial_highuv.json")
    holder = _holder(_config([_location(days="daily")]))
    client = FakeClient(payload)
    channel = RecordingChannel()
    # 22:00 NY is after sunset — fetch happens (sun epochs come from payload) but
    # no decision branch runs, so nothing is posted.
    _uv_monitor_tick(holder, tmp_db, None, client, channel, now_utc=NIGHT_NY)
    assert client.calls != []  # fetched
    assert channel.sent == []  # but posted nothing


def test_tick_never_persists(load_fixture, tmp_db, monkeypatch):
    from weatherbot.scheduler import uvmonitor

    payload = load_fixture("onecall_imperial_uvcross.json")
    holder = _holder(_config([_location(days="daily")]))
    client = FakeClient(payload)
    channel = RecordingChannel()

    calls = {"persist": 0}

    def _spy_persist(*args, **kwargs):  # pragma: no cover - must never run
        calls["persist"] += 1

    # If the monitor ever imported store.persist, this would catch it.
    import weatherbot.weather.store as store_mod

    monkeypatch.setattr(store_mod, "persist", _spy_persist)
    uvmonitor._uv_monitor_tick(
        holder, tmp_db, None, client, channel, now_utc=NOON_NY
    )
    assert calls["persist"] == 0


def test_tick_reads_holder_current_once(load_fixture, tmp_db):
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    payload = load_fixture("onecall_imperial_uvcross.json")

    class CountingHolder(ConfigHolder):
        def __init__(self, config):
            super().__init__(config)
            self.current_calls = 0

        def current(self):
            self.current_calls += 1
            return super().current()

    holder = CountingHolder(
        _config([_location(name="home", days="daily"),
                 _location(name="away", days="daily")])
    )
    client = FakeClient(payload)
    channel = RecordingChannel()
    _uv_monitor_tick(holder, tmp_db, None, client, channel, now_utc=NOON_NY)
    assert holder.current_calls == 1  # snapshot-once across the per-location loop
