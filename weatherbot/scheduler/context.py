"""The render-boundary timing seam: ``ScheduleContext`` + ``schedule_placeholders``.

This is the *display half* of SCHD-04 (D-12/13/14/15). It carries scheduler-derived
timing into the renderer WITHOUT coupling the weather model to the scheduler:
``Forecast.placeholders()`` stays weather-only, and the three timing keys
(``{sent_at}``/``{checked_at}``/``{schedule_note}``) are merged in at the single
``render(...)`` call site in ``send_now`` (the recommended merge-at-call-site seam,
Open Question 2). Plan 03 (the daemon) supplies a real :class:`ScheduleContext` per
fire; manual ``--send-now`` passes ``None`` and still renders ``{sent_at}``/
``{checked_at}`` (location-local) with an empty ``{schedule_note}``.

The value object mirrors ``channels.base.DeliveryResult``: a frozen-ish dataclass
that travels through the pipeline. ``schedule_note`` follows the ``{hint}``/``{alert}``
empty-collapse precedent — it is ``""`` unless the send was genuinely late.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

# "7:30 AM" — no leading zero on the hour. ``%-I`` is the GNU/Linux strftime
# extension; A2 (D-12, Claude's discretion) — Linux is the deployment target
# (Pi/server, see CLAUDE.md systemd note), so this is acceptable.
_TIME_FMT = "%-I:%M %p"


@dataclass
class ScheduleContext:
    """Scheduler-derived timing for one briefing fire (Plan 03 populates it).

    ``scheduled_dt`` is the cron-intended send instant (``None`` for a manual
    send that has no scheduled slot); ``tz`` is the location's IANA zone so all
    rendered times are location-local (D-14); ``late`` marks a within-grace
    catch-up send. ``schedule_note`` is only populated when ``late`` AND a
    ``scheduled_dt`` exists — so an on-time or manual send never leaks a note.
    """

    scheduled_dt: datetime | None
    tz: ZoneInfo
    late: bool = False


def _fmt(dt: datetime, tz: ZoneInfo) -> str:
    """Render ``dt`` as a location-local wall-clock time (``"7:30 AM"``)."""
    # F88 (v2.1, cheap PRESERVE fix over accept-annotate): a NAIVE dt would have
    # ``astimezone`` silently reinterpret it as system-local (wrong wall-clock). No caller
    # feeds a naive dt today (all sources — scheduled_dt/sent/checked — are tz-aware), so
    # this assert never trips in production; it makes a future naive-dt regression fail
    # LOUD here instead of mis-rendering a briefing time.
    assert dt.tzinfo is not None, "_fmt requires a tz-aware datetime (F88)"
    return dt.astimezone(tz).strftime(_TIME_FMT)


def schedule_placeholders(
    ctx: ScheduleContext | None,
    sent_dt: datetime,
    checked_dt: datetime,
) -> dict[str, str]:
    """Build the three timing placeholders merged into the render values (D-15).

    Returns ``{"sent_at", "checked_at", "schedule_note"}``. ``sent_at``/
    ``checked_at`` are ALWAYS non-empty, formatted in the location tz (``ctx.tz``
    when a context is present, else from the datetimes' own tzinfo). ``schedule_note``
    is ``""`` unless ``ctx is not None and ctx.late and ctx.scheduled_dt is not None``,
    in which case it reads ``(intended for <scheduled>, sent <actual>)`` — both
    location-local (Pitfall 4: no None crash, no leak on manual/on-time sends).
    """
    # Choose the formatting tz: the context's location zone when present;
    # otherwise honor each datetime's own tzinfo (manual --send-now passes
    # already-localized datetimes, D-14).
    tz = ctx.tz if ctx is not None else None

    sent_at = _fmt(sent_dt, tz) if tz is not None else sent_dt.strftime(_TIME_FMT)
    checked_at = (
        _fmt(checked_dt, tz) if tz is not None else checked_dt.strftime(_TIME_FMT)
    )

    note = ""
    if ctx is not None and ctx.late and ctx.scheduled_dt is not None:
        scheduled_local = _fmt(ctx.scheduled_dt, ctx.tz)
        sent_local = _fmt(sent_dt, ctx.tz)
        note = f"(intended for {scheduled_local}, sent {sent_local})"

    return {
        "sent_at": sent_at,
        "checked_at": checked_at,
        "schedule_note": note,
    }
