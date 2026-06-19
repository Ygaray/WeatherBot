"""Read-only weather-view handlers: alerts / sun / wind / next-cloudy (Plan 12-02).

Every handler reads fields off the already-fetched One Call payload retained on
``Forecast`` (``raw_onecall_imp``) — there is NEVER a second fetch (Pattern 4
anti-pattern). All handlers are store-free (D-06 / SC#5): this module imports
nothing from ``weatherbot.weather.store`` and writes nothing.

Each handler takes the :class:`~weatherbot.interactive.lookup.LookupResult` the
shared lookup core returns (carrying ``.forecast`` + the resolved ``.location``)
and returns a surface-agnostic :class:`~weatherbot.interactive.commands.CommandReply`
that Plan 03 renders as a Discord embed or CLI plain text (D-04).

Covers CMD-10 (alerts), CMD-13 (sun), CMD-14 (wind), CMD-15 (next-cloudy),
UV-01 (uv).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from weatherbot.interactive.commands import CommandReply
from weatherbot.weather.uv import compute_uv

if TYPE_CHECKING:
    from weatherbot.interactive.lookup import LookupResult


# 16-point compass lookup (RESEARCH Code Example — pure table, no bearing library).
_COMPASS = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


def compass(deg: float) -> str:
    """Return the 16-point compass label for a meteorological bearing in degrees.

    ``compass(0) == "N"``, ``compass(90) == "E"``, ``compass(180) == "S"``,
    ``compass(270) == "W"``. Wraps at 360 (``compass(360) == "N"``). Pure helper —
    no dependency, no I/O.
    """
    return _COMPASS[int((deg + 11.25) // 22.5) % 16]


def _epoch_local(unix_ts: int, tz: ZoneInfo) -> datetime:
    """Convert a Unix-UTC timestamp to location-local wall-clock (DST-correct)."""
    return datetime.fromtimestamp(unix_ts, tz)


def _is_daytime(dt: datetime, raw: dict) -> bool:
    """True if ``dt`` falls between that day's sunrise and sunset (D-05).

    Daytime is judged against the ``daily[]`` sunrise/sunset for the day ``dt``
    falls on (the One Call ``daily[].sunrise/sunset`` are Unix UTC). The derivation
    lives in this one helper so Phases 14/15 can reuse it. Falls back to a simple
    fixed daytime window (06:00-20:00 local) when the daily block lacks sun data
    (CONTEXT D-05 permits a simpler Phase-12 approach).
    """
    tz = dt.tzinfo
    target_date = dt.date()
    for day in raw.get("daily") or []:
        sr = day.get("sunrise")
        ss = day.get("sunset")
        if sr is None or ss is None:
            continue
        sr_local = datetime.fromtimestamp(sr, tz)
        if sr_local.date() == target_date:
            ss_local = datetime.fromtimestamp(ss, tz)
            return sr_local <= dt <= ss_local
    # No matching daily sun data — fall back to a fixed local daytime window.
    return 6 <= dt.hour < 20


def _tz_for(result: LookupResult) -> ZoneInfo:
    return ZoneInfo(result.location.timezone)


def alerts(result: LookupResult) -> CommandReply:
    """Active weather alerts for the location (CMD-10).

    Reads ``raw_onecall_imp["alerts"]`` (absent on a clear day — defensive
    ``or []``, Pitfall 2) and surfaces each alert's ``event`` plus its
    location-local start/end window and a short description. Reports a clear
    "no active alerts" reply when none are present. Never carries a secret.
    """
    raw = result.forecast.raw_onecall_imp or {}
    tz = _tz_for(result)
    location_name = result.location.name
    active = raw.get("alerts") or []

    if not active:
        return CommandReply(
            title=f"Alerts — {location_name}",
            text="No active alerts.",
        )

    lines: list[tuple[str, str]] = []
    for a in active:
        a = a or {}
        event = a.get("event") or "Alert"
        start = a.get("start")
        end = a.get("end")
        when = ""
        if start is not None and end is not None:
            # Include the date (WR-07): alerts can span multiple days / be up to a
            # week out, so '%a %H:%M' alone is ambiguous and can read as the past.
            # Matches next-cloudy's daily '%a %b %d' date style.
            start_local = _epoch_local(start, tz).strftime("%a %b %d %H:%M")
            end_local = _epoch_local(end, tz).strftime("%a %b %d %H:%M")
            when = f"{start_local} → {end_local}"
        desc = (a.get("description") or "").strip()
        # Keep the description short for a chat reply (event text only — no URL/key).
        if len(desc) > 200:
            desc = desc[:197] + "..."
        value = " — ".join(part for part in (when, desc) if part) or "active"
        lines.append((event, value))

    return CommandReply(title=f"Alerts — {location_name}", lines=tuple(lines))


def sun(result: LookupResult) -> CommandReply:
    """Sunrise and sunset times as location-local wall-clock (CMD-13).

    Reads ``current.sunrise``/``current.sunset`` (Unix UTC) off the retained
    payload and converts them to the location's IANA timezone.
    """
    raw = result.forecast.raw_onecall_imp or {}
    cur = raw.get("current") or {}
    tz = _tz_for(result)
    location_name = result.location.name

    lines: list[tuple[str, str]] = []
    # Bind once rather than re-subscript a guarded key (WR-03) — matches the
    # defensive single-read pattern used elsewhere in this module.
    sr = cur.get("sunrise")
    if sr is not None:
        lines.append(("Sunrise", _epoch_local(sr, tz).strftime("%H:%M")))
    ss = cur.get("sunset")
    if ss is not None:
        lines.append(("Sunset", _epoch_local(ss, tz).strftime("%H:%M")))
    if not lines:
        return CommandReply(
            title=f"Sun — {location_name}",
            text="No sunrise/sunset data available.",
        )
    return CommandReply(title=f"Sun — {location_name}", lines=tuple(lines))


def wind(result: LookupResult) -> CommandReply:
    """Current wind speed plus a compass direction (CMD-14).

    Uses the forecast's existing ``wind_display`` for speed/units and derives the
    compass label from ``current.wind_deg`` via the pure :func:`compass` helper.
    """
    forecast = result.forecast
    raw = forecast.raw_onecall_imp or {}
    cur = raw.get("current") or {}
    location_name = result.location.name

    lines: list[tuple[str, str]] = [("Speed", forecast.wind_display)]
    deg = cur.get("wind_deg")
    if deg is not None:
        lines.append(("Direction", f"{compass(deg)} ({int(deg)}°)"))
    return CommandReply(title=f"Wind — {location_name}", lines=tuple(lines))


def next_cloudy(result: LookupResult, threshold: int) -> CommandReply:
    """The next cloudy day/time at or above ``threshold`` cloud cover (CMD-15).

    Hybrid lookahead (D-03): scan ``hourly[]`` (daytime buckets only) for the first
    near-term hour with ``clouds >= threshold``; if none, fall back to
    ``daily[]`` days 3-8 (the ``[2:]`` slice — today/tomorrow are covered by
    hourly). Returns a clear "no cloudy day in the next N days" reply when neither
    half finds a match. All times are location-local wall-clock.
    """
    raw = result.forecast.raw_onecall_imp or {}
    tz = _tz_for(result)
    location_name = result.location.name

    # Near term: first daytime hourly bucket at/above the threshold.
    for h in raw.get("hourly") or []:
        clouds = h.get("clouds")
        dt_ts = h.get("dt")
        # A bucket missing ``dt`` (malformed/partial payload) is skipped, mirroring
        # the ``clouds`` guard — never subscript a key only assumed present (WR-01).
        if clouds is None or dt_ts is None or clouds < threshold:
            continue
        when = _epoch_local(dt_ts, tz)
        if _is_daytime(when, raw):
            return CommandReply(
                title=f"Next cloudy — {location_name}",
                lines=(
                    ("When", when.strftime("%a %H:%M")),
                    ("Cloud cover", f"{clouds}%"),
                ),
            )

    # Days 3-8: daytime-weighted daily clouds (skip today/tomorrow, covered above).
    daily = raw.get("daily") or []
    for d in daily[2:]:
        clouds = d.get("clouds")
        dt_ts = d.get("dt")
        if clouds is None or dt_ts is None or clouds < threshold:
            continue
        when = _epoch_local(dt_ts, tz)
        return CommandReply(
            title=f"Next cloudy — {location_name}",
            lines=(
                ("When", when.strftime("%a %b %d")),
                ("Cloud cover", f"{clouds}%"),
            ),
        )

    # Report the horizon ACTUALLY scanned (WR-02). When ``daily`` is empty the
    # hybrid scan only inspected ``hourly`` — claiming "next 8 days" would assert
    # coverage the function never had, so phrase it honestly about the window.
    if daily:
        text = f"No cloudy day in the next {len(daily)} days."
    else:
        text = "No cloudy day in the forecast window."
    return CommandReply(
        title=f"Next cloudy — {location_name}",
        text=text,
    )


def _threshold_display(threshold: float) -> str:
    """Render the UV threshold without a trailing ``.0`` for whole values.

    ``6.0 -> "6"``, ``4.5 -> "4.5"`` — mirrors the briefing's ``_format_uv``
    threshold display so the command and the briefing read identically.
    """
    return str(round(threshold)) if float(threshold).is_integer() else f"{threshold:g}"


def _uv_hourly_line(points: tuple[tuple[datetime, float], ...]) -> str:
    """A compact daytime hourly UV line of raw ``HH:UV`` pairs (D-04, Open Q2).

    Each daytime ``(local_dt, uvi)`` point renders as ``HH:UV`` (hour zero-padded,
    UV rounded to an integer), space-joined — e.g. ``08:3 10:6 12:8 14:8 16:5``.
    This is the command-only richness on top of the summary the briefing also
    carries (the briefing shows summary fields only).
    """
    return " ".join(f"{dt:%H}:{round(uvi)}" for dt, uvi in points)


def uv(
    result: LookupResult, threshold: float, *, now: datetime | None = None
) -> CommandReply:
    """Current + today's max UV and the sunscreen window for a location (UV-01).

    Reads ONLY the already-fetched One Call payload off the shared ``LookupResult``
    (``result.forecast.raw_onecall_imp`` — never a second fetch, store-free) and calls
    the Plan 14-02 :func:`~weatherbot.weather.uv.compute_uv` with the CONFIGURED
    ``threshold`` (both dispatch sites thread ``config.uv.threshold`` — never a literal).

    The reply carries the full summary set — current UV, today's max + WHO category,
    the day's peak (value + clock), the interpolated threshold-crossing time, and the
    protect window — PLUS a compact daytime hourly UV line (D-04: richer than the
    briefing, which carries summary fields only). When the threshold is never reached
    today the reply states "stays below threshold today" and omits the crossing/window
    while still listing current/max/category + the hourly line.

    ``now`` is injectable for deterministic tests (the anchored UV fixtures); the live
    dispatch passes nothing, so ``compute_uv`` uses ``datetime.now(tz)`` (Pitfall 3:
    the configured location tz, never the API ``timezone`` field).
    """
    raw = result.forecast.raw_onecall_imp or {}
    tz = _tz_for(result)
    location_name = result.location.name

    # onecall_met is accepted by compute_uv for signature parity and ignored (UV is
    # unitless, A1); pass the retained metric payload when present, else None.
    raw_met = result.forecast.raw_onecall_met
    summary = compute_uv(raw, raw_met, threshold, tz=tz, now=now)

    threshold_disp = _threshold_display(threshold)
    lines: list[tuple[str, str]] = [
        ("Now", f"{round(summary.current)} ({summary.category})"),
        ("Today's max", f"{round(summary.max)} ({summary.category})"),
    ]

    if summary.peak_time is not None:
        lines.append(("Peak", f"{round(summary.peak_uvi)} at {summary.peak_time:%H:%M}"))

    if summary.stays_below:
        lines.append(
            ("Sunscreen", f"stays below {threshold_disp} today")
        )
    else:
        if summary.crossing_time is not None:
            lines.append(
                ("Crosses", f"climbs above {threshold_disp} around {summary.crossing_time:%H:%M}")
            )
        if summary.window_start is not None and summary.window_end is not None:
            lines.append(
                ("Protect", f"{summary.window_start:%H:%M}–{summary.window_end:%H:%M}")
            )
        elif summary.window_start is not None:
            lines.append(("Protect", f"from {summary.window_start:%H:%M}"))

    hourly = _uv_hourly_line(summary.hourly_points)
    if hourly:
        lines.append(("Hourly", hourly))

    return CommandReply(title=f"UV — {location_name}", lines=tuple(lines))
