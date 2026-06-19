"""Read-only on-demand multi-day forecast handlers (Plan 13-04, FCAST-01..05/07).

``weekday_forecast`` / ``weekend_forecast`` mirror the ``weather_views`` module
contract exactly: each takes the :class:`~weatherbot.interactive.lookup.LookupResult`
the shared lookup core returns (carrying ``.forecast`` with BOTH raw One Call
payloads + the resolved ``.location``) and returns a surface-agnostic
:class:`~weatherbot.interactive.commands.CommandReply` the CLI prints and the
Discord bot embeds (D-04). They read off the ALREADY-FETCHED ``daily[]`` — there
is NEVER a second fetch (FCAST-07) — and import NOTHING from
``weatherbot.weather.store`` (read-only, FCAST-05).

The per-day rendering loop lives in :func:`~templates.renderer.render_forecast`
(the "no logic in templates" invariant, T-13-04): this handler selects the
in-window days (:func:`~weatherbot.weather.multiday.select_days`), extracts a
:class:`~weatherbot.weather.models.ForecastDay` per selected index, computes its
human label, loads the variant template + sibling per-day line-format, and hands
the lot to ``render_forecast``. Out-of-horizon ``+day`` notices from
``select_days`` render into the ``{notice}`` token (D-03).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from weatherbot.interactive.commands import CommandReply
from weatherbot.weather import multiday
from weatherbot.weather.models import ForecastDay
from templates.renderer import (
    FORECAST_TEMPLATE_NAMES,
    forecast_day_allowed,
    load_template,
    render_forecast,
)

if TYPE_CHECKING:
    from weatherbot.interactive.command import ForecastFlags
    from weatherbot.interactive.lookup import LookupResult


# Weekday-abbreviation labels for days beyond Today/Tomorrow (an explicit table —
# NOT a locale-dependent date-format directive, and never the glibc-only %-m/%-d).
_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# (kind, variant) -> (whole-message template, sibling per-day line-format). The map
# lives in templates.renderer as the ONE source of truth so the scheduled-fire +
# config validator + file-watch sets (Plan 13-05) never drift from this handler.
_TEMPLATES = FORECAST_TEMPLATE_NAMES

# Human title per kind (the {title} header token).
_TITLE = {"weekday": "Weekday forecast", "weekend": "Weekend forecast"}


def _tz_for(result: LookupResult) -> ZoneInfo:
    """The location's IANA timezone (mirrors weather_views._tz_for)."""
    return ZoneInfo(result.location.timezone)


def _day_label(dt_local: datetime, today_local: datetime) -> str:
    """Compute a per-day label by local-date diff from ``today_local`` (D-04).

    First two upcoming days → "Today"/"Tomorrow"; the rest →
    ``f"{abbr} {month}/{day}"`` built with an EXPLICIT f-string (NOT a glibc-specific
    ``%-m/%-d`` date-format directive; State-of-the-Art / Pitfall 6).
    """
    delta = (dt_local.date() - today_local.date()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    abbr = _ABBR[dt_local.weekday()]
    return f"{abbr} {dt_local.month}/{dt_local.day}"


def _render(
    kind: str,
    result: LookupResult,
    flags: ForecastFlags,
    *,
    now: datetime | None = None,
) -> CommandReply:
    """Shared body for ``weekday_forecast``/``weekend_forecast`` (kind differs only).

    ``now`` is injectable (keyword-only, defaults to the location-local wall clock)
    so the window/notice logic is deterministically testable without a frozen
    system clock; production callers omit it.
    """
    raw_imp = result.forecast.raw_onecall_imp or {}
    raw_met = result.forecast.raw_onecall_met or {}
    daily_imp = raw_imp.get("daily") or []
    daily_met = raw_met.get("daily") or []

    tz = _tz_for(result)
    tz_name = result.location.timezone
    now_local = now.astimezone(tz) if now is not None else datetime.now(tz)
    today_local = now_local.date()

    indices, notices = multiday.select_days(
        kind,
        today_local,
        daily_imp,
        add=set(flags.add),
        drop=set(flags.drop),
        tz=tz_name,
    )

    variant = flags.variant if flags.variant in ("detailed", "compact") else "detailed"
    detailed = variant == "detailed"
    day_allowed = forecast_day_allowed(variant)

    day_token_maps: list[dict[str, str]] = []
    for i in indices:
        day_imp = daily_imp[i] if i < len(daily_imp) else {}
        day_met = daily_met[i] if i < len(daily_met) else {}
        dt_ts = (day_imp or {}).get("dt")
        if dt_ts is not None:
            dt_local = datetime.fromtimestamp(dt_ts, tz)
            label = _day_label(dt_local, now_local)
        else:
            label = ""
        fday = ForecastDay.from_daily(
            day_imp,
            day_met,
            label=label,
            primary=result.forecast.primary,
            tz_name=tz_name,
        )
        day_token_maps.append(fday.day_tokens(detailed))

    template_name, line_name = _TEMPLATES[(kind, variant)]
    template_text = load_template(template_name)
    line_fmt = load_template(line_name)

    title = _TITLE[kind]
    range_label = _range_label(day_token_maps)
    header_values = {
        "location": result.location.name,
        "title": title,
        "range_label": range_label,
        "footer_note": "",
        "notice": "\n".join(notices),
    }

    rendered = render_forecast(
        template_text,
        line_fmt,
        day_token_maps,
        header_values,
        day_allowed,
    )
    return CommandReply(title=f"{title} — {result.location.name}", text=rendered)


def _range_label(day_token_maps: list[dict[str, str]]) -> str:
    """A short "first → last day" label from the rendered day labels."""
    if not day_token_maps:
        return ""
    first = day_token_maps[0].get("label") or ""
    last = day_token_maps[-1].get("label") or ""
    if not first and not last:
        return ""
    if first == last or not last:
        return first
    return f"{first} \N{RIGHTWARDS ARROW} {last}"


def weekday_forecast(
    result: LookupResult, flags: ForecastFlags, *, now: datetime | None = None
) -> CommandReply:
    """The on-demand weekday (Mon-Fri) multi-day forecast (FCAST-01).

    Reads the already-fetched ``daily[]`` off ``result.forecast``, selects the
    still-upcoming weekday block (honoring ``+day``/``-day`` flags), extracts a
    :class:`ForecastDay` per in-window day, and renders the chosen variant via
    ``render_forecast``. Out-of-horizon flags surface as a ``{notice}`` line
    (D-03). Read-only: no store import, no extra fetch (FCAST-05/07). ``now`` is
    injectable for deterministic tests (defaults to the location-local clock).
    """
    return _render("weekday", result, flags, now=now)


def weekend_forecast(
    result: LookupResult, flags: ForecastFlags, *, now: datetime | None = None
) -> CommandReply:
    """The on-demand weekend (Fri-Sat-Sun) multi-day forecast (FCAST-02).

    Identical to :func:`weekday_forecast` with ``kind="weekend"``.
    """
    return _render("weekend", result, flags, now=now)
