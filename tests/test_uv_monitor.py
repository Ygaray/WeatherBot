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


# --- Task 2: the three decision branches + once/day/location dedup -----------


def _clone(payload: dict) -> dict:
    """Deep-ish clone so a test can tweak ``current.uvi`` without mutating fixtures."""
    import copy

    return copy.deepcopy(payload)


def _at(hh: int, mm: int = 0):
    """A UTC instant for 2024-06-14 ``hh:mm`` NY (the fixtures' anchor day)."""
    return datetime(2024, 6, 14, hh, mm, tzinfo=NY).astimezone(timezone.utc)


def _run(payload, *, tmp_db, now_utc, uv=None, channel=None):
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    channel = channel if channel is not None else RecordingChannel()
    holder = _holder(_config([_location(name="home", days="daily")], uv=uv))
    client = FakeClient(payload)
    _uv_monitor_tick(holder, tmp_db, None, client, channel, now_utc=now_utc)
    return channel


def test_prewarn_time_proximity_fires_once(load_fixture, tmp_db):
    from weatherbot.weather.store import claimed_uv_kinds

    # current 4.5 (< 6, value-gap 1.5 > a tight margin), crossing_time 10:20, now
    # 10:00 → 20 min away ≤ lead 30 → TIME-close fires the pre-warn.
    payload = _clone(load_fixture("onecall_imperial_uvcross.json"))
    payload["current"]["uvi"] = 4.5
    uv = UvConfig(threshold=6.0, pre_warn_lead_minutes=30, value_margin=0.1)

    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(10, 0), uv=uv)
    assert len(ch.sent) == 1
    assert "prewarn" in claimed_uv_kinds(tmp_db, "home", "2024-06-14")

    # A later tick in the same window posts NOTHING (dedup).
    ch2 = _run(payload, tmp_db=tmp_db, now_utc=_at(10, 10), uv=uv)
    assert ch2.sent == []


def test_prewarn_value_proximity_fires_once(load_fixture, tmp_db):
    # current 5.5 (6 - 5.5 = 0.5 ≤ margin 1.0) but now 08:00 is OUTSIDE the 30-min
    # time-lead window (crossing 10:20) → VALUE-close alone fires the pre-warn.
    payload = _clone(load_fixture("onecall_imperial_uvcross.json"))
    payload["current"]["uvi"] = 5.5
    uv = UvConfig(threshold=6.0, pre_warn_lead_minutes=30, value_margin=1.0)

    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(8, 0), uv=uv)
    assert len(ch.sent) == 1


def test_crossing_fires_once(load_fixture, tmp_db):
    from weatherbot.weather.store import claimed_uv_kinds

    # uvcross current 7.0 ≥ 6 with a prior pre-warn already claimed (so this is a
    # genuine CROSSING, not a first-poll already-high). Seed prewarn first.
    from weatherbot.weather.store import claim_uv_alert

    claim_uv_alert(tmp_db, "home", "2024-06-14", "prewarn")
    payload = load_fixture("onecall_imperial_uvcross.json")
    uv = UvConfig(threshold=6.0)

    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(11, 0), uv=uv)
    assert len(ch.sent) == 1
    assert "now" in ch.sent[0]  # "UV now ≥T" wording (not "already")
    assert "crossing" in claimed_uv_kinds(tmp_db, "home", "2024-06-14")

    ch2 = _run(payload, tmp_db=tmp_db, now_utc=_at(11, 30), uv=uv)
    assert ch2.sent == []


def test_already_high_first_poll_suppresses_prewarn(load_fixture, tmp_db):
    from weatherbot.weather.store import claimed_uv_kinds

    # highuv: current 8.2 ≥ 6 at the FIRST daylight poll, no prior rows → posts the
    # "already ≥T" wording AND claims prewarn (so the moot pre-warn never fires).
    payload = load_fixture("onecall_imperial_highuv.json")
    uv = UvConfig(threshold=6.0)

    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(9, 0), uv=uv)
    assert len(ch.sent) == 1
    assert "already" in ch.sent[0]
    kinds = claimed_uv_kinds(tmp_db, "home", "2024-06-14")
    assert "crossing" in kinds and "prewarn" in kinds

    # A later tick emits no pre-warn (already-high precedes + suppresses it).
    ch2 = _run(payload, tmp_db=tmp_db, now_utc=_at(10, 0), uv=uv)
    assert ch2.sent == []


def test_all_clear_after_crossing(load_fixture, tmp_db):
    from weatherbot.weather.store import claim_uv_alert, claimed_uv_kinds

    # Crossing already claimed; UV now below threshold → all-clear fires once.
    claim_uv_alert(tmp_db, "home", "2024-06-14", "crossing")
    payload = _clone(load_fixture("onecall_imperial_uvcross.json"))
    payload["current"]["uvi"] = 4.0  # back below 6
    uv = UvConfig(threshold=6.0, value_margin=0.1)

    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(16, 0), uv=uv)
    assert len(ch.sent) == 1
    assert "below" in ch.sent[0]
    assert "allclear" in claimed_uv_kinds(tmp_db, "home", "2024-06-14")

    ch2 = _run(payload, tmp_db=tmp_db, now_utc=_at(16, 30), uv=uv)
    assert ch2.sent == []


def test_all_clear_fires_after_sunset_when_crossing_claimed(load_fixture, tmp_db):
    from weatherbot.weather.store import claim_uv_alert, claimed_uv_kinds

    # WR-01: UV stayed high past sunset (the common case), so the all-clear must
    # still fire once UV drops below threshold even though it is now NIGHT (after
    # the 19:40 NY sunset). A prior crossing is claimed; current is back below 6.
    claim_uv_alert(tmp_db, "home", "2024-06-14", "crossing")
    payload = _clone(load_fixture("onecall_imperial_uvcross.json"))
    payload["current"]["uvi"] = 3.0  # back below 6
    uv = UvConfig(threshold=6.0, value_margin=0.1)

    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(21, 0), uv=uv)  # 21:00 NY = night
    assert len(ch.sent) == 1
    assert "below" in ch.sent[0]
    assert "allclear" in claimed_uv_kinds(tmp_db, "home", "2024-06-14")


def test_no_post_sunset_crossing_without_prior(load_fixture, tmp_db):
    # WR-01 guard: a post-sunset tick with NO prior crossing must take no branch —
    # the fall-through is ONLY for closing out an existing crossing, never for
    # emitting a spurious post-sunset crossing/pre-warn.
    payload = load_fixture("onecall_imperial_highuv.json")  # current 8.2 ≥ 6
    uv = UvConfig(threshold=6.0)
    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(21, 0), uv=uv)
    assert ch.sent == []


def test_post_sunset_high_uv_does_not_allclear_prematurely(load_fixture, tmp_db):
    # WR-01 edge: a crossing is claimed but UV is STILL high after sunset → the
    # all-clear must NOT fire yet (it only fires once UV drops below threshold).
    from weatherbot.weather.store import claim_uv_alert

    claim_uv_alert(tmp_db, "home", "2024-06-14", "crossing")
    payload = load_fixture("onecall_imperial_highuv.json")  # current 8.2 still ≥ 6
    uv = UvConfig(threshold=6.0)
    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(21, 0), uv=uv)
    assert ch.sent == []


def test_ordering_late_already_high_never_prewarns(load_fixture, tmp_db):
    # A mid-day start that is already-high must NEVER emit a pre-warn (the
    # already-high branch precedes pre-warn). highuv current 8.2, no prior rows.
    payload = load_fixture("onecall_imperial_highuv.json")
    uv = UvConfig(threshold=6.0)
    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(13, 0), uv=uv)
    assert len(ch.sent) == 1
    assert "already" in ch.sent[0]
    assert all("soon" not in t for t in ch.sent)  # no pre-warn wording


def test_restart_dedup_preclaimed_kinds_post_nothing(load_fixture, tmp_db):
    from weatherbot.weather.store import claim_uv_alert

    # Simulate a pre-restart day: prewarn + crossing already in the db.
    claim_uv_alert(tmp_db, "home", "2024-06-14", "prewarn")
    claim_uv_alert(tmp_db, "home", "2024-06-14", "crossing")
    payload = load_fixture("onecall_imperial_uvcross.json")  # current 7.0 ≥ 6
    uv = UvConfig(threshold=6.0)

    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(11, 0), uv=uv)
    assert ch.sent == []  # both kinds durable-claimed → no re-post


def test_stays_below_posts_nothing(load_fixture, tmp_db):
    # uvbelow: current 4.2, never crosses 6. With a tight margin and a now far from
    # any (non-existent) crossing, nothing fires all day.
    payload = load_fixture("onecall_imperial_uvbelow.json")
    uv = UvConfig(threshold=6.0, value_margin=0.1)
    ch = _run(payload, tmp_db=tmp_db, now_utc=_at(12, 0), uv=uv)
    assert ch.sent == []


def test_monitor_disabled_live_does_nothing(load_fixture, tmp_db):
    # WR-03: a live ``monitor_enabled=false`` must short-circuit the tick — no
    # fetch, no post — even though the job stays registered (the daemon does not
    # re-reconcile __uvmonitor__). An already-high payload would otherwise post.
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    payload = load_fixture("onecall_imperial_highuv.json")
    uv = UvConfig(threshold=6.0, monitor_enabled=False)
    holder = _holder(_config([_location(name="home", days="daily")], uv=uv))
    client = FakeClient(payload)
    channel = RecordingChannel()
    result = _uv_monitor_tick(
        holder, tmp_db, None, client, channel, now_utc=_at(9, 0)
    )
    assert result is None
    assert client.calls == []  # no fetch when live-disabled
    assert channel.sent == []  # and no post


# --- Task 3: failure isolation (UV-06) ---------------------------------------


def test_per_location_fetch_raise_isolated(load_fixture, tmp_db):
    """One location's fetch raising never aborts the others; the tick returns None."""
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    payload = load_fixture("onecall_imperial_highuv.json")
    holder = _holder(
        _config([_location(name="bad", days="daily"),
                 _location(name="good", days="daily")])
    )

    class PartialClient:
        def __init__(self):
            self.calls = []

        def fetch_onecall(self, location, units):
            self.calls.append(location.name)
            if location.name == "bad":
                raise RuntimeError("fetch boom")
            return payload

    client = PartialClient()
    channel = RecordingChannel()
    result = _uv_monitor_tick(
        holder, tmp_db, None, client, channel, now_utc=_at(9, 0)
    )
    assert result is None
    # The good location was still processed (fetched + posted its already-high alert).
    assert "good" in client.calls
    assert len(channel.sent) == 1


def test_channel_send_raise_does_not_propagate(load_fixture, tmp_db):
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    payload = load_fixture("onecall_imperial_highuv.json")
    holder = _holder(_config([_location(name="home", days="daily")]))
    client = FakeClient(payload)
    channel = RecordingChannel(raises=True)
    # Must not raise even though channel.send raises.
    result = _uv_monitor_tick(
        holder, tmp_db, None, client, channel, now_utc=_at(9, 0)
    )
    assert result is None


def test_compute_uv_raise_swallowed(load_fixture, tmp_db, monkeypatch):
    from weatherbot.scheduler import uvmonitor

    payload = load_fixture("onecall_imperial_highuv.json")
    holder = _holder(_config([_location(name="home", days="daily")]))
    client = FakeClient(payload)
    channel = RecordingChannel()

    def _boom(*a, **k):
        raise RuntimeError("compute boom")

    monkeypatch.setattr(uvmonitor, "compute_uv", _boom)
    result = uvmonitor._uv_monitor_tick(
        holder, tmp_db, None, client, channel, now_utc=_at(9, 0)
    )
    assert result is None
    assert channel.sent == []


def test_holder_current_raise_caught_by_outer_envelope(tmp_db):
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    class BoomHolder:
        def current(self):
            raise RuntimeError("holder boom")

    # The outermost envelope must catch even a holder.current() failure.
    result = _uv_monitor_tick(
        BoomHolder(), tmp_db, None, FakeClient({}), RecordingChannel(),
        now_utc=_at(9, 0),
    )
    assert result is None


def test_monitor_never_touches_briefing_namespace():
    """The monitor source references NONE of the briefing exactly-once namespace."""
    import pathlib

    src = pathlib.Path(
        "weatherbot/scheduler/uvmonitor.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("claim_slot", "sent_log", "record_sent", "release_claim"):
        assert forbidden not in src, f"monitor must not reference {forbidden} (UV-06)"


def test_daemon_registers_this_exact_tick():
    """Wiring assertion (15-03): the daemon's __uvmonitor__ job IS this module's tick.

    Closes the cross-plan link — Plan 15-03's _register_uvmonitor_job registers the
    callback that Plan 15-02's _uv_monitor_tick provides (UV-04). A signature drift
    in the tick would surface here as a registration/kwargs mismatch.
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    from weatherbot.scheduler.daemon import _register_uvmonitor_job
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick

    holder = _holder(_config([_location(name="home", days="daily")]))
    scheduler = BackgroundScheduler()
    _register_uvmonitor_job(
        scheduler, holder, db_path="x.db", settings=None, client=object(),
        channel=object(),
    )
    job = scheduler.get_job("__uvmonitor__")
    assert job is not None
    assert job.func is _uv_monitor_tick
    # The kwargs keys match the tick's (holder, db_path, settings, client, channel)
    # positional contract from 15-02 — a rename on either side breaks this.
    assert set(job.kwargs) == {"holder", "db_path", "settings", "client", "channel"}
