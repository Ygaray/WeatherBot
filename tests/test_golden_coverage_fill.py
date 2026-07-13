"""Branch-coverage FILL tests for the one-time Phase-21 move-path audit (Plan 21-05).

These are CHARACTERIZATION tests, not aspirational ones: each pins the *current*
observable behavior of an UNTAKEN branch side that the output-only goldens cannot
see. Extraction risk lives on the untaken `except`/`else`/false-path of a move-path
branch — an unexercised branch that silently behaves differently in the new package
is exactly what branch mode + this fill closes (D-06/D-08).

Every test below targets a specific partial-branch miss reported by
``uv run pytest --cov --cov-branch --cov-report=term-missing`` over the six move-path
packages (channels / scheduler / config / reliability / ops / interactive). The
audit log (`21-COVERAGE-AUDIT.md`) records the before/after and which branch each
test resolves. These tests touch NO ``weatherbot/`` source (characterization only).

Runtime-only lifecycle branches (daemon shutdown/signal/watchfiles loops, bot
thread-loop teardown, real ``/proc`` and real ``build_client`` production-default
paths) are NOT filled here — they are excused per D-09 either with an inline
reason-bearing ``# pragma: no cover - <reason>`` marker (the four lazy-build /
cross-version guards) or as a documented runtime-lifecycle / defensive category in
``21-COVERAGE-AUDIT.md`` §3. Each excused branch NAMES why it is unreachable offline;
none was excused merely to make the number green.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.interactive.lookup import LookupResult
from weatherbot.weather.models import Forecast


# --------------------------------------------------------------------------- #
# Shared builders (mirror tests/test_command_views.py conventions)
# --------------------------------------------------------------------------- #


def _ny_location() -> Location:
    return Location(
        name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York"
    )


def _result_from(
    load_fixture, imp_name: str, met_name: str | None = None
) -> LookupResult:
    loc = _ny_location()
    onecall_imp = load_fixture(imp_name)
    onecall_met = load_fixture(met_name or "onecall_metric_clear.json")
    forecast = Forecast.from_payloads(loc, onecall_imp, onecall_met)
    return LookupResult(text="", forecast=forecast, location=loc)


# --------------------------------------------------------------------------- #
# weatherbot/channels/factory.py:49-51 — `except KeyError` on an unknown type
# --------------------------------------------------------------------------- #


def test_build_channel_unknown_type_raises_value_error():
    """factory.py:49-51 — the untaken `except KeyError` path.

    A misconfigured channel type must fail loud at construction (a ValueError that
    NAMES the unknown type + the known set), never silently fall through. This is
    the error branch every later channel-extraction phase relies on.
    """
    from weatherbot.channels import factory

    cfg = Config(locations=[_ny_location()], webhook=WebhookIdentity())

    with pytest.raises(ValueError) as exc:
        factory.build_channel(cfg, settings=None, channel_type="carrier-pigeon")

    msg = str(exc.value)
    assert "carrier-pigeon" in msg
    assert "discord" in msg  # the known-types list is named in the error


def test_build_channel_default_type_is_discord(monkeypatch):
    """factory.py — the `channel_type or DEFAULT_TYPE` default (taken side recorded).

    Bare ``channel_type=None`` resolves to the v1 default ("discord") via the
    registry, so a config with no explicit type still builds. Stub the discord
    builder so this stays offline (no webhook POST).
    """
    from weatherbot.channels import factory

    sentinel = object()
    monkeypatch.setitem(factory._REGISTRY, "discord", lambda config, settings: sentinel)

    cfg = Config(locations=[_ny_location()], webhook=WebhookIdentity())
    assert factory.build_channel(cfg, settings=None) is sentinel


# --------------------------------------------------------------------------- #
# weatherbot/config/loader.py:37 — load_settings() with no env_file (else side)
# --------------------------------------------------------------------------- #


def test_load_settings_no_env_file_uses_default(monkeypatch):
    """loader.py:35->37 — the `env_file is None` false side returns plain Settings().

    Tests always pass an explicit env file, leaving the production default branch
    (``Settings()`` reading the ambient environment) unexercised. Pin it.
    """
    from weatherbot.config import loader

    monkeypatch.setenv("OPENWEATHER_API_KEY", "fill-test-key")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/x")
    settings = loader.load_settings()  # no env_file -> the default branch
    assert settings.openweather_api_key == "fill-test-key"


# --------------------------------------------------------------------------- #
# weatherbot/config/loader.py:51 — resolve_location with no locations
# --------------------------------------------------------------------------- #


def test_resolve_location_no_locations_raises():
    """loader.py:50-51 — empty `config.locations` raises a plain ValueError.

    Distinct from the UnknownLocationError subclass raised when a *named* location
    misses; the no-locations-at-all case is the bare ValueError every
    `except ValueError` caller already catches.
    """
    from weatherbot.config import loader

    cfg = Config.model_construct(locations=[])
    with pytest.raises(ValueError) as exc:
        loader.resolve_location(cfg, None)
    assert "No locations configured" in str(exc.value)


# --------------------------------------------------------------------------- #
# weatherbot/config/models.py:302 — attempts_per_burst < 2 validator
# --------------------------------------------------------------------------- #


def test_attempts_per_burst_below_two_rejected():
    """models.py:297-302 — the `v < 2` validator raise (CR-01 div-by-zero guard).

    A single attempt makes the within-burst spread `step = spread/(n-1)` a division
    by zero, so it is rejected loud at load instead of crashing at 9am. Pin the
    untaken validation branch.
    """
    from weatherbot.config.models import Reliability

    with pytest.raises(ValueError) as exc:
        Reliability(attempts_per_burst=1)
    assert "attempts_per_burst must be >= 2" in str(exc.value)

    # The valid (false) side returns v unchanged (models.py:302).
    ok = Reliability(attempts_per_burst=3)
    assert ok.attempts_per_burst == 3


# --------------------------------------------------------------------------- #
# weatherbot/reliability/retry.py:125-126 — malformed Retry-After header -> None
# --------------------------------------------------------------------------- #


def test_retry_after_unparseable_header_falls_back():
    """retry.py:128-129 — any Retry-After parse failure -> None (WR-05).

    A malformed `Retry-After` must degrade to "no usable header" (the wait callable
    falls back to the plain base) rather than escape into the daemon's broad handler
    or crash the CLI. Drives the `except (TypeError, ValueError)` parse-failure path
    with an untrusted, non-numeric, non-HTTP-date header value.

    NOTE: the sibling `if dt is None: return None` guard (retry.py:125-126) is a
    cross-version defensive branch — on CPython 3.12 ``parsedate_to_datetime`` ALWAYS
    raises ``ValueError`` on malformed input (it never returns ``None``), so that
    guard is unreachable here and is excused with a reason-bearing pragma in source.
    """
    import httpx

    from weatherbot.reliability import retry

    def _resp(retry_after: str | None) -> httpx.Response:
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        return httpx.Response(429, headers=headers)

    # A garbage non-date, non-number header -> parse failure -> None (no escape).
    assert retry.parse_retry_after(_resp("not-a-date")) is None
    # Absent header is likewise unusable.
    assert retry.parse_retry_after(_resp(None)) is None
    # The numeric (taken) side is recorded for contrast: capped seconds form.
    assert retry.parse_retry_after(_resp("5")) == 5.0


# --------------------------------------------------------------------------- #
# weatherbot/scheduler/catchup.py:80 — empty day-of-week part skipped
# weatherbot/scheduler/catchup.py (fires_on) — false weekday side
# --------------------------------------------------------------------------- #


def test_weekday_set_skips_empty_parts():
    """catchup.py:79-80 — a trailing/double comma yields an empty part that is skipped.

    `"mon,,fri"` (or a trailing comma) must not crash on the empty token — the
    `if not part: continue` guard drops it. Pins the untaken continue branch.
    """
    from weatherbot.scheduler import catchup

    # mon=0, fri=4; the empty middle token is skipped, not parsed.
    assert catchup._weekday_set("mon,,fri") == {0, 4}
    assert catchup._weekday_set("mon-fri,") == {0, 1, 2, 3, 4}


def test_fires_on_false_for_non_matching_weekday():
    """catchup.py (fires_on) — the False side of the weekday membership test.

    A weekday-only slot must report False on a weekend `now_local`, so the catch-up
    planner skips it (catchup.py:149-150 `not fires_on(...) -> continue`).
    """
    from weatherbot.config.models import Schedule
    from weatherbot.scheduler import catchup

    slot = Schedule(time="09:00", days="weekdays")
    # 2026-06-20 is a Saturday in America/New_York.
    sat = datetime(2026, 6, 20, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    assert catchup.fires_on(slot, sat) is False
    # 2026-06-22 is a Monday -> fires.
    mon = datetime(2026, 6, 22, 9, 0, tzinfo=ZoneInfo("America/New_York"))
    assert catchup.fires_on(slot, mon) is True


def test_plan_catchup_skips_non_firing_weekday():
    """catchup.py:149-150 — `not fires_on(...) -> continue` inside plan_catchup.

    A weekday-only slot evaluated on a Saturday `now_utc` is skipped by the planner
    (no MissedSlot emitted) — the live CronTrigger would not fire it either, so the
    catch-up planner must agree. Pure: `now_utc` + `was_sent` injected.
    """
    from weatherbot.config.models import Location, Schedule
    from weatherbot.scheduler import catchup

    loc = Location(
        name="Home",
        lat=40.0,
        lon=-74.0,
        timezone="America/New_York",
        schedule=[Schedule(time="09:00", days="weekdays")],
    )
    cfg = Config(locations=[loc])
    # 2026-06-20 13:00 UTC is a Saturday morning in New York -> weekday slot skipped.
    sat_utc = datetime(2026, 6, 20, 13, 0, tzinfo=timezone.utc)
    missed = catchup.plan_catchup(cfg, was_sent=lambda *a: False, now_utc=sat_utc)
    assert missed == []


# --------------------------------------------------------------------------- #
# weatherbot/scheduler/__init__.py:25-28 — lazy run_daemon + bad-attr AttributeError
# --------------------------------------------------------------------------- #


def test_scheduler_lazy_run_daemon_and_bad_attr():
    """scheduler/__init__.py:24-28 — the PEP-562 `__getattr__` both sides.

    `from weatherbot.scheduler import run_daemon` resolves lazily (the
    `name == "run_daemon"` true side), and any other attribute raises AttributeError
    (the false side). Both are observable and currently only the import side runs.
    """
    import weatherbot.scheduler as sched

    run_daemon = sched.run_daemon  # lazy import path (line 25-27)
    assert callable(run_daemon)

    with pytest.raises(AttributeError) as exc:
        _ = sched.no_such_attribute  # the raise side (line 28)
    assert "no_such_attribute" in str(exc.value)


# --------------------------------------------------------------------------- #
# weatherbot/interactive/commands/info.py:42 — empty locations reply
# --------------------------------------------------------------------------- #


def test_locations_reply_empty_config():
    """info.py:41-42 — the `if not lines` branch (no locations configured).

    The untaken side of `locations()` returns the "No locations configured." reply
    rather than an empty list of pairs.
    """
    from weatherbot.interactive.commands import info

    cfg = Config.model_construct(locations=[])
    reply = info.locations(cfg)
    assert reply.title == "Locations"
    assert reply.text == "No locations configured."


# --------------------------------------------------------------------------- #
# weatherbot/interactive/commands/status.py:33,39,41 — uptime formatting branches
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (-5, "0m"),  # status.py:33 — negative clamps to 0 -> "0m"
        (0, "0m"),
        (59, "0m"),
        (60, "1m"),
        (3600, "1h 0m"),  # status.py:41 — hours present (days==0)
        (90061, "1d 1h 1m"),  # status.py:39 — days present
    ],
)
def test_fmt_uptime_branches(seconds, expected):
    """status.py:32-43 — the negative-clamp, days, and hours-or-days branches.

    `_fmt_uptime` is a pure formatter; its day/hour conditionals and the negative
    guard are only partially exercised by the suite. Pin each branch's output.
    """
    from datetime import timedelta

    from weatherbot.interactive.commands import status

    assert status._fmt_uptime(timedelta(seconds=seconds)) == expected


def test_fmt_epoch_none_yet():
    """status.py — the `epoch is None` side of `_fmt_epoch` ("none yet")."""
    import re

    from datetime import timezone

    from weatherbot.interactive.commands import status

    assert status._fmt_epoch(None, timezone.utc) == "none yet"
    # The non-None side now formats a humanized local 24-hour HH:MM (D-07),
    # localized into the passed display zone, no longer the raw `... UTC` stamp.
    assert re.fullmatch(r"\d{2}:\d{2}", status._fmt_epoch(0, timezone.utc))


# --------------------------------------------------------------------------- #
# weatherbot/interactive/commands/forecast.py:175,177 — _range_label edge sides
# --------------------------------------------------------------------------- #


def test_range_label_edges():
    """forecast.py:170-178 — the empty / no-labels / single-label false sides.

    `_range_label` collapses to "" when there are no day maps or no labels, and to
    a single label when first==last or last is empty — the untaken sides of the
    arrow-join. Pure function; pin each.
    """
    from weatherbot.interactive.commands import forecast

    assert forecast._range_label([]) == ""  # 170-171
    assert forecast._range_label([{"label": ""}, {"label": ""}]) == ""  # 174-175
    assert (
        forecast._range_label([{"label": "Mon"}, {"label": "Mon"}]) == "Mon"
    )  # 176-177
    assert (
        forecast._range_label([{"label": "Mon"}, {"label": ""}]) == "Mon"
    )  # last empty
    out = forecast._range_label([{"label": "Mon"}, {"label": "Wed"}])
    assert "Mon" in out and "Wed" in out  # the taken arrow-join side


# --------------------------------------------------------------------------- #
# weatherbot/interactive/commands/weather_views.py — alert/sun/daytime false sides
# --------------------------------------------------------------------------- #


def test_alerts_clear_reports_no_active(load_fixture):
    """weather_views.alerts — the no-alerts false side (loop body never appends).

    A clear payload has no `alerts`, so the loop at 143-160 never runs and the reply
    reports no active alerts. Records the untaken loop-entry side (148->155 partial).
    """
    from weatherbot.interactive.commands import weather_views

    result = _result_from(load_fixture, "onecall_imperial_clear.json")
    reply = weather_views.alerts(result)
    assert reply.title.startswith("Alerts")


def test_sun_missing_data_reports_no_data(load_fixture, monkeypatch):
    """weather_views.sun:185-188 — the `if not lines` side ("No sunrise/sunset data").

    When neither `current.sunrise` nor `current.sunset` is present, the handler
    returns the "No ... data available." text rather than a Sunrise/Sunset list.
    """
    from weatherbot.interactive.commands import weather_views

    result = _result_from(load_fixture, "onecall_imperial_clear.json")
    # Strip the sun keys off the retained current payload to force the empty side.
    raw = dict(result.forecast.raw_onecall_imp or {})
    cur = dict(raw.get("current") or {})
    cur.pop("sunrise", None)
    cur.pop("sunset", None)
    raw["current"] = cur
    object.__setattr__(result.forecast, "raw_onecall_imp", raw)

    reply = weather_views.sun(result)
    assert reply.title.startswith("Sun")
    assert "No sunrise/sunset data" in (reply.text or "")


def test_is_daytime_fallback_window(load_fixture):
    """weather_views._is_daytime:86-87 — the no-matching-daily fixed-window fallback.

    When no daily sun row matches the target date (sr/ss missing or date mismatch),
    `_is_daytime` falls back to the fixed `6 <= hour < 20` local window. Drives the
    81->77 continue and the 86-87 fallback return.
    """
    from weatherbot.interactive.commands import weather_views

    tz = ZoneInfo("America/New_York")
    # A raw payload whose daily rows have NO sunrise/sunset -> every row is skipped.
    raw = {"daily": [{"dt": 0}, {"dt": 1}]}
    noon = datetime(2026, 6, 20, 12, 0, tzinfo=tz)
    midnight = datetime(2026, 6, 20, 3, 0, tzinfo=tz)
    assert weather_views._is_daytime(noon, raw) is True  # 12:00 in window
    assert weather_views._is_daytime(midnight, raw) is False  # 03:00 outside window


# --------------------------------------------------------------------------- #
# weatherbot/ops/sdnotify.py:35,55 — abstract-socket addr + watchdog()
# --------------------------------------------------------------------------- #


def test_sdnotify_abstract_socket_and_watchdog(monkeypatch):
    """sdnotify.py:34-35 (abstract '@' -> NUL) and :55 (watchdog WATCHDOG=1).

    A `NOTIFY_SOCKET` starting with '@' is an abstract-namespace socket whose leading
    '@' must become a NUL byte. And `watchdog()` is present-but-unused in v1 (its
    `_send("WATCHDOG=1")` line is never driven by the suite). Pin both.
    """
    from weatherbot.ops import sdnotify

    monkeypatch.setenv("NOTIFY_SOCKET", "@abstract-sock")
    n = sdnotify.SystemdNotifier()
    assert n._addr == "\0abstract-sock"  # line 35

    sent: list[str] = []
    monkeypatch.setattr(n, "_send", sent.append)
    n.watchdog()  # line 55
    assert sent == ["WATCHDOG=1"]
    n.ready()
    assert sent == ["WATCHDOG=1", "READY=1"]


# --------------------------------------------------------------------------- #
# weatherbot/ops/pidfile.py:100-102,120 — not-running + empty-argv guard sides
# --------------------------------------------------------------------------- #


def test_is_weatherbot_pid_not_running():
    """pidfile.py:100-102 — injected reader raising FileNotFoundError -> False.

    A PID whose `/proc/<pid>/cmdline` is gone is not running (stale/recycled), so the
    guard returns False BEFORE any signal — the PID-recycling defense (T-09-06).
    """
    from weatherbot.ops import pidfile

    def _gone(pid: int) -> bytes:
        raise FileNotFoundError

    assert pidfile.is_weatherbot_pid(4242, cmdline_reader=_gone) is False


def test_write_pid_atomic_cleans_up_on_failure(tmp_path, monkeypatch):
    """pidfile.py:56-65 — the `except BaseException` temp-file cleanup + re-raise.

    A PID write failure in daemon startup must be LOUD (re-raised), and must leave NO
    orphan temp file behind. Force ``os.replace`` to raise and assert (1) it propagates
    and (2) no ``.wbpid-*`` temp file lingers in the target dir.
    """
    from weatherbot.ops import pidfile

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pidfile.os, "replace", _boom)
    target = tmp_path / "weatherbot.pid"

    with pytest.raises(OSError):
        pidfile.write_pid_atomic(target)

    # The error re-raised (loud) AND the temp file was unlinked (no orphan).
    assert not target.exists()
    assert list(tmp_path.glob(".wbpid-*")) == []


# --------------------------------------------------------------------------- #
# weatherbot/ops/selfcheck.py:80,94-95 — no-locations + no-client/no-settings
# --------------------------------------------------------------------------- #


def test_self_check_no_locations_is_config_invalid():
    """selfcheck.py — empty locations -> ValueError -> classified CONFIG_INVALID.

    HARD-STARTUP-02 (29-03): a config with no locations is a PERMANENT operator
    error, caught by the pre-probe config branch and classified CONFIG_INVALID
    (fatal), NOT swept into NETWORK_NOT_READY where the daemon would re-probe forever.
    Detail is the exception CLASS name only (T-04-01), never str(exc).
    """
    from weatherbot.ops.selfcheck import CONFIG_INVALID, run_self_check

    cfg = Config.model_construct(locations=[])

    class _Ok:
        def fetch_onecall(
            self, location, units
        ):  # pragma: no cover - never reached (the no-locations guard raises first)
            return {}

    result = run_self_check(config=cfg, client=_Ok())
    assert result.ok is False
    assert result.reason == CONFIG_INVALID
    assert result.detail.isidentifier()  # class name only, never str(exc)


def test_self_check_requires_client_or_settings():
    """selfcheck.py:93-95 — no client AND no settings -> ValueError -> not-ready.

    With neither an injected client nor settings to build one, the probe cannot run;
    the raised ValueError is classified as NETWORK_NOT_READY rather than escaping.
    """
    from weatherbot.ops.selfcheck import NETWORK_NOT_READY, run_self_check

    cfg = Config(locations=[_ny_location()])
    result = run_self_check(config=cfg, settings=None, client=None)
    assert result.ok is False
    assert result.reason == NETWORK_NOT_READY


# --------------------------------------------------------------------------- #
# weatherbot/scheduler/uvmonitor.py — pure helper branch sides
# --------------------------------------------------------------------------- #


def test_uvmonitor_active_today_false_for_disabled_slot():
    """uvmonitor._active_today — the `any(...)` False side (no enabled firing slot).

    A location whose only slot is disabled is not polled today (UV-04) — the monitor
    only watches a place the user will actually be.
    """
    from weatherbot.config.models import Location, Schedule
    from weatherbot.scheduler import uvmonitor

    loc = Location(
        name="Home",
        lat=40.0,
        lon=-74.0,
        timezone="America/New_York",
        schedule=[Schedule(time="09:00", days="weekdays", enabled=False)],
    )
    mon = datetime(2026, 6, 22, 13, 0, tzinfo=timezone.utc)  # a Monday
    assert uvmonitor._active_today(loc, mon) is False


def test_select_today_daily_stamp_edges():
    """dates.select_today_daily — stamp derivation edges (WR-02 successor + WR-03).

    WR-02 removed ``uvmonitor._daily0_matches_today``; its non-numeric-stamp →
    skip-safely posture now lives here in the single source of truth. WR-03: an
    explicit ``dt is None`` check (not truthiness) means a legitimate ``dt == 0``
    is NOT swallowed / does not fall through to ``sunrise``.
    """
    from weatherbot.weather.dates import select_today_daily

    tz = ZoneInfo("America/New_York")

    # A non-numeric dt (and no usable sunrise) can't be dated → entry skipped →
    # None (the fail-safe "skip safely", formerly _daily0_matches_today's False).
    assert select_today_daily([{"dt": "not-an-epoch"}], tz, "2026-06-20") is None

    # A real epoch on the matching day is selected (the True-side contrast).
    noon = int(datetime(2026, 6, 20, 16, 0, tzinfo=timezone.utc).timestamp())
    entry = {"dt": noon, "sunrise": 1, "sunset": 2}
    assert select_today_daily([entry], tz, "2026-06-20") is entry

    # WR-03: dt == 0 is 1970-01-01 (a valid-if-nonsensical epoch), NOT absent — it
    # must be used verbatim (dated to 1969-12-31 in NY), NEVER fall through to a
    # differing ``sunrise``. Proven by matching the dt=0 day, not the sunrise day.
    zero_dt = {"dt": 0, "sunrise": noon}  # sunrise would date to 2026-06-20.
    assert select_today_daily([zero_dt], tz, "2026-06-20") is None  # dt=0 wins → no match
    dt0_date = datetime.fromtimestamp(0, tz=tz).date().isoformat()
    assert select_today_daily([zero_dt], tz, dt0_date) is zero_dt  # dt=0 day matches


def test_uvmonitor_post_none_channel_is_noop():
    """uvmonitor._post:120-121 — the `channel is None` guard returns without sending."""
    from weatherbot.scheduler import uvmonitor

    # Must not raise with a None channel (headless/test runs).
    assert uvmonitor._post(None, "anything") is None


def test_uvmonitor_fmt_threshold_and_window_fallbacks():
    """uvmonitor._fmt_threshold:207 (non-integer) + _fmt_window:214-215 (no window).

    `_fmt_threshold` keeps the decimal for a non-integer threshold (5.5 -> '5.5'); the
    integer side drops the '.0'. `_fmt_window` returns 'today' when either bound is
    missing — the untaken None-side of the protect-window render.
    """
    from types import SimpleNamespace

    from weatherbot.scheduler import uvmonitor

    assert uvmonitor._fmt_threshold(6.0) == "6"  # integer side
    assert uvmonitor._fmt_threshold(5.5) == "5.5"  # non-integer side (line 207)

    no_window = SimpleNamespace(window_start=None, window_end=None)
    assert uvmonitor._fmt_window(no_window) == "today"  # line 214-215


# --------------------------------------------------------------------------- #
# weatherbot/interactive/lookup.py:106-107 — no client AND no settings -> raise
# --------------------------------------------------------------------------- #


def test_lookup_weather_requires_client_or_settings():
    """lookup.py:105-107 — the `client is None and settings is None` ValueError.

    The read-only core cannot fetch with neither an injected client nor settings to
    build one, so it fails loud at the call site (the lazy-build_client branch below
    is production-only and excused with a reason-bearing pragma).
    """
    from weatherbot.interactive.lookup import lookup_weather

    cfg = Config(locations=[_ny_location()])
    with pytest.raises(ValueError) as exc:
        lookup_weather("New York", config=cfg, settings=None, client=None)
    assert "requires either a client or settings" in str(exc.value)


# --------------------------------------------------------------------------- #
# weatherbot/interactive/bot.py:176-182,189->191 — _split_body oversized-line split
# --------------------------------------------------------------------------- #


def test_split_body_hard_splits_oversized_line():
    """bot.py:176-191 — a single line longer than the limit is hard-split mid-line.

    `_split_body` packs whole lines under the limit, but a pathological single line
    that alone exceeds the limit must be hard-split into limit-sized pieces (rather
    than rejected by Discord). Drives the 176-182 over-limit branch and the trailing
    `if current` flush (189->191).
    """
    from weatherbot.interactive.bot import _split_body

    limit = 10
    # A short line, then an oversized line, then a final short line.
    text = "ab\n" + ("X" * 25) + "\ncd"
    chunks = _split_body(text, limit)

    # Every chunk fits under the limit (no over-limit field).
    assert all(len(c) <= limit for c in chunks)
    # Reassembling the non-boundary content preserves all characters (no data loss).
    assert "".join(chunks).count("X") == 25
    assert "ab" in chunks[0]
    assert chunks[-1] == "cd"  # the trailing flush (189-190)


def test_split_body_oversized_line_first_no_pending(load_fixture):
    """bot.py:177->180 + 189->191 — oversized line with NO pending `current`.

    When the FIRST line alone exceeds the limit, the `if current:` flush is skipped
    (177->180 false side: nothing accumulated yet). And when the text ENDS on such an
    oversized line (which `continue`s), the loop exits with empty `current`, so the
    trailing `if current:` is also the false side (189->191). Pin both.
    """
    from weatherbot.interactive.bot import _split_body

    limit = 10
    chunks = _split_body("Y" * 25, limit)  # one oversized line, nothing before/after
    assert all(len(c) <= limit for c in chunks)
    assert "".join(chunks).count("Y") == 25


# --------------------------------------------------------------------------- #
# weatherbot/interactive/commands/weather_views.py — wind no-deg + next_cloudy empties
# --------------------------------------------------------------------------- #


def test_wind_omits_direction_when_no_deg(load_fixture):
    """weather_views.wind:206->208 — the `wind_deg is None` side omits Direction.

    A payload with no `current.wind_deg` reports Speed only (the Direction line is
    not appended) — the untaken false side of the direction guard.
    """
    from weatherbot.interactive.commands import weather_views

    result = _result_from(load_fixture, "onecall_imperial_clear.json")
    raw = dict(result.forecast.raw_onecall_imp or {})
    cur = dict(raw.get("current") or {})
    cur.pop("wind_deg", None)
    raw["current"] = cur
    object.__setattr__(result.forecast, "raw_onecall_imp", raw)

    reply = weather_views.wind(result)
    names = [n for n, _ in (reply.lines or ())]
    assert "Speed" in names
    assert "Direction" not in names


def test_next_cloudy_empty_window_phrasing(load_fixture):
    """weather_views.next_cloudy:258-264 — the empty-`daily` honest-horizon phrasing.

    When neither hourly nor daily yields a cloudy hit AND `daily` is empty, the reply
    must phrase the window honestly ("in the forecast window") rather than claiming a
    day-count it never scanned (the `else` at line 264).
    """
    from weatherbot.interactive.commands import weather_views

    result = _result_from(load_fixture, "onecall_imperial_clear.json")
    raw = dict(result.forecast.raw_onecall_imp or {})
    raw["hourly"] = []
    raw["daily"] = []  # force the empty-daily else side (line 264)
    object.__setattr__(result.forecast, "raw_onecall_imp", raw)

    reply = weather_views.next_cloudy(result, threshold=60)
    assert "forecast window" in (reply.text or "")


def test_next_cloudy_daily_count_phrasing(load_fixture):
    """weather_views.next_cloudy:261-262 — the non-empty-`daily` "next N days" side.

    The contrasting taken side: a non-empty `daily` with no cloudy match reports the
    actual day count scanned ("No cloudy day in the next N days.").
    """
    from weatherbot.interactive.commands import weather_views

    result = _result_from(load_fixture, "onecall_imperial_clear.json")
    reply = weather_views.next_cloudy(result, threshold=99)  # nothing reaches 99%
    assert "next" in (reply.text or "") and "day" in (reply.text or "")


def test_render_embed_overflow_marker():
    """bot.py:243-247,256 — more lines than the field budget -> "+N more" marker.

    A reply with more `(name, value)` pairs than Discord's 25-field cap must keep room
    for the overflow marker field and append "+N more" rather than silently dropping
    fields (or being rejected by Discord). Drives the overflow-trim branch.
    """
    import time_machine

    from tests.conftest import FROZEN
    from weatherbot.interactive.bot import _MAX_FIELDS, render_embed
    from weatherbot.interactive.commands import CommandReply

    n = _MAX_FIELDS + 5  # comfortably over the 25-field cap
    lines = tuple((f"k{i}", f"v{i}") for i in range(n))
    reply = CommandReply(title="Overflow", lines=lines)

    with time_machine.travel(FROZEN, tick=False):
        embed = render_embed(reply)

    field_names = [f.name for f in embed.fields]
    # The overflow marker is present and reports the dropped count.
    assert "…" in field_names
    marker = next(f for f in embed.fields if f.name == "…")
    assert marker.value.startswith("+") and "more" in marker.value
    # Total fields never exceed Discord's hard cap.
    assert len(embed.fields) <= _MAX_FIELDS
