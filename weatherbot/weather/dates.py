"""The D-08 single tz-correct local-date helper (pure, dependency-free).

This module is intentionally dependency-free (no config, no apscheduler, no
store import) — mirroring ``weatherbot/scheduler/days.py`` and
``weatherbot/weather/multiday.py`` — so it stays an acyclic leaf and every
caller (``weather.models``, ``weather.store``, ``scheduler.uvmonitor``) can
import it without an import cycle.

It is the ONE source of truth for "which local day is today" (D-08): the three
former verbatim ``_local_date_iso`` copies (models.py:69, store.py:210,
uvmonitor.py:84) collapse into ``local_date_iso`` here, so the rendered
``{date}``/UV-day and the persisted ``local_date`` key can never diverge (F69).

The configured ``Location.timezone`` is authoritative for "today" (D-03), NOT
the API ``timezone`` field (Pitfall 3). A naive ``now_utc`` is treated as UTC
(D-06/F33) so a naive injection near midnight can never be reinterpreted in the
HOST tz by ``astimezone()`` and shift the computed date by a day.

``select_today_daily`` (D-05) matches a ``daily[]`` entry to today by that
entry's OWN local date (from its ``dt``/``sunrise`` in the configured tz) — never
by positional ``daily[0]`` math (Pitfall 1) — reusing the
``uvmonitor._daily0_matches_today`` derive-from-sunrise idea and the
``multiday._date_index_map`` no-positional-math idea; it returns ``None`` (→
caller degrades) when no entry matches.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from weatherbot.config.models import Location

__all__ = ["local_date_iso", "local_date_for", "select_today_daily"]


def local_date_iso(now_utc: datetime, tz: timezone | ZoneInfo) -> str:
    """The ``YYYY-MM-DD`` local date for ``now_utc`` in the resolved ``tz``.

    The core primitive shared by every caller. If ``now_utc`` is naive (no
    ``tzinfo``), it is treated as UTC (D-06/F33) — a naive 23:30 UTC-wall-clock
    value yields the UTC-interpreted date, never a host-tz-shifted date — before
    converting into ``tz`` and taking the calendar date.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(tz).date().isoformat()


def _resolve_tz(tz_name: str | None) -> timezone | ZoneInfo:
    """Resolve an IANA tz name to a tzinfo, falling back to UTC (D-03 authority).

    Belt-and-suspenders: ``Location.timezone`` is a required/IANA-validated field
    at config load, so the fallback is effectively dead — but we keep it explicit
    (never silently store a wrong date) mirroring ``multiday._resolve_tz``.
    """
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            return timezone.utc
    return timezone.utc


def local_date_for(location: Location, now_utc: datetime) -> str:
    """The location's local ``YYYY-MM-DD`` today, from its CONFIGURED IANA tz.

    Thin ``Location``-resolving wrapper over ``local_date_iso``: resolves
    ``location.timezone`` via ``_resolve_tz`` and delegates, so it is byte-identical
    to the primitive for the same resolved ``(now, tz)``.
    """
    return local_date_iso(now_utc, _resolve_tz(getattr(location, "timezone", None)))


def select_today_daily(
    daily: list[dict] | None,
    tz: timezone | ZoneInfo,
    local_date: str,
) -> dict | None:
    """Return the ``daily[]`` entry whose OWN local date == ``local_date`` (D-05).

    Each entry's date is derived from its ``dt`` (or ``sunrise`` fallback) as a
    calendar date in ``tz`` — never positional ``daily[0]`` math (Pitfall 1). A
    malformed entry (non-numeric/out-of-range ``dt``/``sunrise``) is skipped, never
    raised (ASVS V5 defensive-degrade). Returns ``None`` when no entry matches or
    ``daily`` is empty/None, so callers degrade down the existing empty/stays_below
    path.
    """
    for entry in daily or []:
        entry = entry or {}
        stamp = entry.get("dt") or entry.get("sunrise")
        if stamp is None:
            continue
        try:
            entry_date = datetime.fromtimestamp(int(stamp), tz=tz).date().isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if entry_date == local_date:
            return entry
    return None
