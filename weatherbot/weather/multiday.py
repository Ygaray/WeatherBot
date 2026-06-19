"""The D-01 multi-day window/roll-forward day selector (pure, testable).

This module is intentionally dependency-free (no config, no apscheduler, no store
import) — mirroring ``weatherbot/scheduler/days.py`` — so it stays acyclic and can
be unit-tested in isolation. It implements exactly two pieces of genuinely-new
logic for Phase 13:

* the **window** rule (D-01): a weekday/weekend forecast resolves to the
  still-upcoming days of its block, silently dropping days already past, and
  rolling the whole block to next week when the current block is exhausted;
* the **horizon** rule (D-03, Pitfall 2): a desired calendar date with no matching
  entry in the fetched ``daily[]`` (i.e. beyond One Call's today+7 horizon) becomes
  a notice string, never a silent drop or an ``IndexError``.

Dates are NEVER indexed into ``daily[]`` positionally by day-of-week math
(Pitfall 1). Each desired date is matched to its ``daily[i]`` by converting that
entry's ``dt`` (Unix UTC) to a date in the configured IANA tz — the same authority
rule as ``models._local_date_iso`` (Pitfall 6: never the naive system today nor
the API ``timezone`` field). The ``+day``/``-day`` token vocabulary is reused from
``weatherbot.scheduler.days._DAYS`` (one source of truth — A4: abbreviations only,
presets are NOT valid flag tokens).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from weatherbot.scheduler.days import _DAYS

# Block day sets by forecast kind (Monday-first ordering matches APScheduler).
_WEEKDAY_DAYS = ("mon", "tue", "wed", "thu", "fri")
_WEEKEND_DAYS = ("fri", "sat", "sun")

# Map a day token to its Python ``date.weekday()`` index (Mon=0 .. Sun=6).
_WD_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _resolve_tz(tz: str | None) -> timezone | ZoneInfo:
    """Resolve an IANA tz name to a tzinfo, falling back to UTC (D-03 authority)."""
    if tz:
        try:
            return ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            return timezone.utc
    return timezone.utc


def _date_index_map(daily: list[dict], tz: timezone | ZoneInfo) -> dict[date, int]:
    """Map each ``daily[i]`` local date → its index (Pitfall 1: no positional math)."""
    out: dict[date, int] = {}
    for i, day in enumerate(daily or []):
        dt = (day or {}).get("dt")
        if dt is None:
            continue
        local = datetime.fromtimestamp(dt, tz).date()
        out.setdefault(local, i)
    return out


def select_days(
    kind: str,
    today_local: date,
    daily: list[dict],
    add: set[str],
    drop: set[str],
    tz: str | None = None,
) -> tuple[list[int], list[str]]:
    """Return ``(in-window daily[] indices in calendar order, out-of-window notices)``.

    1. base day set = ``_WEEKDAY_DAYS``/``_WEEKEND_DAYS`` by ``kind`` (raise
       ``ValueError`` on any other kind — fail loud, T-13-03); apply ``drop`` then
       ``add``; dedup.
    2. resolve each base day to its still-upcoming calendar date relative to
       ``today_local`` (today counts as in-window); drop days already past. If the
       whole base block is past, roll it forward one week. ``add`` days always use
       their next-occurrence date (so an added day past in this week's block rolls
       to next week, where it may fall beyond the horizon → notice).
    3. sort desired dates into calendar order.
    4. map each desired date → its ``daily[]`` index via the local-date map; desired
       dates with no in-window match become notice strings (Pitfall 2).
    """
    if kind == "weekday":
        base = _WEEKDAY_DAYS
    elif kind == "weekend":
        base = _WEEKEND_DAYS
    else:
        raise ValueError(
            f"unknown forecast kind {kind!r}: expected 'weekday' or 'weekend'"
        )

    # Sanitize flag tokens against the single source of truth (days._DAYS).
    add = {t for t in (add or set()) if t in _DAYS}
    drop = {t for t in (drop or set()) if t in _DAYS}

    base_tokens = [d for d in base if d not in drop]

    today_wd = today_local.weekday()

    # --- resolve the base block, with whole-block roll-forward when exhausted ----
    # signed delta within this week's block (negative = already past this week).
    base_deltas = [(_WD_INDEX[d] - today_wd) for d in base_tokens]
    upcoming = [delta for delta in base_deltas if delta >= 0]
    if base_tokens and not upcoming:
        # Whole block is in the past → roll the entire block to next week.
        base_deltas = [delta + 7 for delta in base_deltas]
        upcoming = base_deltas
    else:
        # Keep only the still-upcoming days of the current block (drop past days).
        upcoming = [delta for delta in base_deltas if delta >= 0]

    desired: set[date] = {today_local + timedelta(days=delta) for delta in upcoming}

    # --- additive flags: always the next occurrence (today or future) -----------
    for tok in add:
        delta = (_WD_INDEX[tok] - today_wd) % 7
        desired.add(today_local + timedelta(days=delta))

    # --- map desired dates → indices; unmatched (beyond horizon) → notices -------
    tzinfo = _resolve_tz(tz)
    by_date = _date_index_map(daily, tzinfo)

    indices: list[int] = []
    notices: list[str] = []
    for d in sorted(desired):
        idx = by_date.get(d)
        if idx is None:
            notices.append(
                f"{d.isoformat()} is beyond the 7-day forecast horizon"
            )
        else:
            indices.append(idx)

    return sorted(indices), notices
