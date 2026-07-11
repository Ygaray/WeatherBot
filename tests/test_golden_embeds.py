"""Byte-exact embed goldens — one named case per command × the 📍/Updated states (Plan 21-02).

These are the load-bearing visual-output snapshots the later Discord-adapter extraction
(Phase 27) re-runs. They pin the FULL rendered ``discord.Embed`` per command — title,
description (the 📍 indicator + the self-ageing ``Updated <t:…:t> (<t:…:R>)`` stamp), color,
and the ordered field tuple incl. ``inline`` — so a field REORDER, an inline-flip, or a
copy-edit anywhere in the render surfaces as a real diff (D-02/D-10).

Drive (gateway-free, NO network): each case builds a REAL :class:`LookupResult` from a
recorded ``onecall_*`` fixture via the shipped read-only ``lookup_weather`` core (with an
injected fixture-returning client — the ``test_cli.py`` ``_FakeClient`` idiom), runs the
REAL registry handler through the shared :func:`dispatch_reply` ladder, and renders the
resulting ``CommandReply`` via :func:`render_embed`. So the golden pins the actual
production render of actual recorded data, not a hand-built embed.

Frozen clock (D-11 — freeze, don't scrub): every render runs inside
``time_machine.travel(FROZEN, tick=False)`` so the ``Updated <t:{epoch}:t> (<t:{epoch}:R>)``
stamp is the deterministic literal ``Updated <t:1781960400:t> (<t:1781960400:R>)`` — the
epoch frozen to the shared FROZEN instant while the ``:t``/``:R`` format string is KEPT in
the golden (the over-scrubbing trap, avoided). ``embed.timestamp`` is excluded by
``embed_to_golden`` (outside the byte contract per ``test_weather_spec_byte_identical``).

📍 coverage (D-10 — additive/orthogonal, no cartesian cross-multiply): 📍-ON is covered once
via a location-bearing reply (``render_embed(reply, location="home")``) — every weather/
forecast case carries it; 📍-OFF is covered once via the argless ``status`` reply
(``location=None``), which suppresses the indicator line.
"""

from __future__ import annotations

import json
from pathlib import Path

import time_machine

from tests.conftest import FROZEN, embed_to_golden
from weatherbot.config import Config, Location, WebhookIdentity
from weatherbot.interactive import lookup_weather, registry
from weatherbot.interactive.bot import render_embed
from weatherbot.interactive.command import ForecastFlags
from weatherbot.interactive.dispatch import dispatch_reply

_FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    """Read a recorded OpenWeather fixture by file name (offline, no network)."""
    with (_FIXTURE_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# Phase 32 (D-05/F35): ``Forecast.from_payloads`` now selects today's ``daily[]``
# entry by its OWN local date instead of positional ``daily[0]``. The recorded
# ``clear`` fixtures are dated 2024-06-14, which never matches the ``FROZEN``
# (2026-06-20) "today" these goldens build under, so the today-selector would
# correctly degrade High/Low/Rain to the empty path. Re-date the fixture's single
# ``daily[0]`` to FROZEN's calendar day (shift by whole 24h so DST offsets stay
# intact) so the golden keeps asserting the recorded values under the corrected
# date-matched selection — the goldens exercise DISPLAY, not the F35 date guard.
def _redate_daily_to_frozen(payload: dict) -> dict:
    """Shift each ``daily[]`` entry's dt/sunrise/sunset onto FROZEN's day (whole days)."""
    daily = payload.get("daily") or []
    if not daily:
        return payload
    dt0 = daily[0].get("dt")
    if dt0 is None:
        return payload
    one_day = 24 * 3600
    # Whole-day delta from the fixture's daily[0] date to FROZEN's UTC epoch day.
    day_delta = (int(FROZEN.timestamp()) // one_day - int(dt0) // one_day) * one_day
    for entry in daily:
        for key in ("dt", "sunrise", "sunset"):
            if entry.get(key) is not None:
                entry[key] += day_delta
    return payload


class _FakeClient:
    """Returns recorded imperial/metric One Call fixtures — NO network (test_cli.py idiom)."""

    def __init__(self, *, imperial: dict, metric: dict) -> None:
        self._onecall = {"imperial": imperial, "metric": metric}

    def fetch_onecall(self, location, units):  # noqa: ANN001 — mirrors the real client sig
        return self._onecall[units]


# A single fixed configured location (a stable IANA tz so every clock-derived value is
# deterministic). The recorded fixtures already carry the weather payloads; the config
# only supplies the resolved location + the global uv/cloud thresholds the handlers read.
_CONFIG = Config(
    locations=[
        Location(name="New York", lat=40.7128, lon=-74.006, timezone="America/New_York")
    ],
    template="briefing-sectioned.txt",
    webhook=WebhookIdentity(),
)


def _lookup(imperial: str, metric: str, *, redate: bool = False):
    """Build a REAL LookupResult from a recorded fixture pair (gateway-free, store-free).

    Phase 32 (D-05/F35): the ``weather``/``uv`` command goldens (which surface today's
    ``daily[0]``-derived High/Low/Rain/UV DISPLAY) pass ``redate=True`` so the fixture
    ``daily[]`` is shifted onto FROZEN's day and the ``from_payloads`` build clock is
    frozen — the today-selector then matches the fixture's entry and the golden keeps
    asserting the recorded DISPLAY values (NOT the F35 date-degrade path). The forecast
    variants do NOT re-date: they drive multiday logic off the raw recorded dates via
    their handler's ``now=FROZEN`` seam and must keep the fixture calendar intact.
    """
    if redate:
        client = _FakeClient(
            imperial=_redate_daily_to_frozen(_load(imperial)),
            metric=_redate_daily_to_frozen(_load(metric)),
        )
        with time_machine.travel(FROZEN, tick=False):
            return lookup_weather("New York", config=_CONFIG, client=client)
    client = _FakeClient(imperial=_load(imperial), metric=_load(metric))
    return lookup_weather("New York", config=_CONFIG, client=client)


def _command_embed(name: str, *, imperial: str, metric: str):
    """Drive a location-taking command through the REAL handler → embed (📍-on)."""
    result = _lookup(imperial, metric, redate=True)  # D-05/F35: today-matched display
    spec = registry.BY_NAME[name]
    # Freeze the clock across BOTH dispatch and render: the ``uv`` handler recomputes
    # ``compute_uv`` with ``now=datetime.now(tz)`` (weather_views.uv), which — post
    # D-05/F35 — must land on FROZEN's day so the re-dated fixture's today entry is
    # selected for "Today's max" (else it degrades to 0). location="home" → the 📍 cell.
    with time_machine.travel(FROZEN, tick=False):
        reply = dispatch_reply(
            spec, result=result, config=_CONFIG, flags=None, daemon_state=None
        )
        return render_embed(reply, location="home")


def _forecast_embed(command_name: str, variant: str, *, imperial: str, metric: str):
    """Drive a forecast variant through the REAL handler → embed (📍-on, frozen window)."""
    result = _lookup(imperial, metric)
    flags = ForecastFlags(variant=variant, location="New York")
    # ``now=FROZEN`` pins the window/notice selection deterministically (the handler's
    # documented test seam) so the rendered day set is stable across runs.
    reply = registry.BY_NAME[command_name].handler(result, flags, now=FROZEN)
    with time_machine.travel(FROZEN, tick=False):
        return render_embed(reply, location="home")


# --------------------------------------------------------------------------- #
# Per-command embed goldens — one named case per command (D-10). Each name maps to
# its exact cell so a failing diff names the command.
# --------------------------------------------------------------------------- #


def test_weather_embed_golden(json_snapshot):
    """The ``weather`` command embed (Now / High·Low / Rain), 📍-on, frozen Updated stamp."""
    embed = _command_embed(
        "weather",
        imperial="onecall_imperial_clear.json",
        metric="onecall_metric_clear.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_uv_embed_golden(json_snapshot):
    """The ``uv`` command embed (current/max/peak/window/hourly), 📍-on."""
    embed = _command_embed(
        "uv",
        imperial="onecall_imperial_highuv.json",
        metric="onecall_metric_clear.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_next_cloudy_embed_golden(json_snapshot):
    """The ``next-cloudy`` command embed (When / Cloud cover), 📍-on."""
    embed = _command_embed(
        "next-cloudy",
        imperial="onecall_imperial_cloudy_hourly.json",
        metric="onecall_metric_clear.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_sun_embed_golden(json_snapshot):
    """The ``sun`` command embed (Sunrise / Sunset, location-local), 📍-on."""
    embed = _command_embed(
        "sun",
        imperial="onecall_imperial_clear.json",
        metric="onecall_metric_clear.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_wind_embed_golden(json_snapshot):
    """The ``wind`` command embed (Speed / Direction compass), 📍-on."""
    embed = _command_embed(
        "wind",
        imperial="onecall_imperial_clear.json",
        metric="onecall_metric_clear.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_alerts_embed_golden(json_snapshot):
    """The ``alerts`` command embed (active alert event + window), 📍-on."""
    embed = _command_embed(
        "alerts",
        imperial="onecall_imperial_alert.json",
        metric="onecall_metric_clear.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_status_embed_golden_indicator_suppressed(json_snapshot):
    """The argless ``status`` reply embed — the 📍-OFF cell (D-10, location=None).

    Driven through the REAL ``status`` handler with ``daemon_state=None`` (the stable
    "unavailable" reply — deterministic, no scheduler/heartbeat state). ``location=None``
    so ``render_embed`` SUPPRESSES the 📍 indicator line (the description carries only the
    frozen Updated stamp), pinning the 📍-off render surface exactly once (D-01/D-10).
    """
    spec = registry.BY_NAME["status"]
    reply = dispatch_reply(
        spec, result=None, config=_CONFIG, flags=None, daemon_state=None
    )
    with time_machine.travel(FROZEN, tick=False):
        embed = render_embed(reply, location=None)  # 📍 suppressed (argless)
    assert embed_to_golden(embed) == json_snapshot


# --------------------------------------------------------------------------- #
# Forecast variant goldens — weekday/weekend × detailed/compact (D-10, one-per-cell).
# --------------------------------------------------------------------------- #


def test_weekday_forecast_detailed_embed_golden(json_snapshot):
    """Weekday × detailed forecast embed (full multi-day body), 📍-on, frozen window."""
    embed = _forecast_embed(
        "weekday-forecast",
        "detailed",
        imperial="onecall_8day_imperial.json",
        metric="onecall_8day_metric.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_weekday_forecast_compact_embed_golden(json_snapshot):
    """Weekday × compact forecast embed, 📍-on, frozen window."""
    embed = _forecast_embed(
        "weekday-forecast",
        "compact",
        imperial="onecall_8day_imperial.json",
        metric="onecall_8day_metric.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_weekend_forecast_detailed_embed_golden(json_snapshot):
    """Weekend × detailed forecast embed, 📍-on, frozen window."""
    embed = _forecast_embed(
        "weekend-forecast",
        "detailed",
        imperial="onecall_8day_imperial.json",
        metric="onecall_8day_metric.json",
    )
    assert embed_to_golden(embed) == json_snapshot


def test_weekend_forecast_compact_embed_golden(json_snapshot):
    """Weekend × compact forecast embed, 📍-on, frozen window."""
    embed = _forecast_embed(
        "weekend-forecast",
        "compact",
        imperial="onecall_8day_imperial.json",
        metric="onecall_8day_metric.json",
    )
    assert embed_to_golden(embed) == json_snapshot
