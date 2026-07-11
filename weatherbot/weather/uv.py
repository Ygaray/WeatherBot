"""Pure UV-index computation over the One Call ``hourly[]``/``daily[0]``/``current``.

This is the shared reuse seam for Phase 14's UV work (UV-02). It takes the
already-fetched One Call payload(s) + the configured threshold and emits a frozen
:class:`UvSummary`: current / today's max / WHO category / peak / interpolated
threshold-crossing time / protect window / stays-below.

Three consumers call this exact helper with the same threshold: the ``Forecast``
briefing fields (Plan 14-03), the ``uv <loc>`` command (Plan 14-04), and the
Phase-15 background monitor. To keep that reuse cycle-free, this module imports
**nothing** from the interactive layer — only stdlib + dataclasses.

Design decisions (from 14-RESEARCH):
- ``current.uvi`` is "now" verbatim; ``daily[0].uvi`` is the day's max verbatim;
  ``hourly[]`` is used ONLY for crossing/window/peak (Pitfall 6).
- UV index is unitless, so only ``onecall_imp`` is read; ``onecall_met`` is accepted
  for signature parity with ``Forecast.from_payloads`` and ignored (A1).
- All "today"/daytime time math uses the passed-in CONFIGURED location tz, never the
  API ``timezone`` field (Pitfall 3).
- The WHO category word is round-then-band (A2).
- Malformed/empty ``hourly[]`` degrades to ``stays_below=True`` (never raises), so a
  briefing render can never crash/gate on bad UV data (T-14-04 briefing-spine isolation).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from weatherbot.weather.dates import select_today_daily

__all__ = ["UvSummary", "compute_uv", "uv_category"]


@dataclass(frozen=True)
class UvSummary:
    """Structured UV facts for a single day. Display formatting is NOT done here.

    Fields ``crossing_time``/``window_start``/``window_end``/``peak_time`` are
    ``None`` when the threshold is never reached across today's daytime points
    (``stays_below`` is then ``True``). ``current``/``max`` are always populated
    (read from ``current.uvi``/``daily[0].uvi``, independent of ``hourly[]``).
    """

    current: float
    max: float
    category: str
    peak_uvi: float
    peak_time: datetime | None
    crossing_time: datetime | None
    window_start: datetime | None
    window_end: datetime | None
    stays_below: bool
    hourly_points: tuple[tuple[datetime, float], ...]


def _epoch_local(unix_ts: int, tz: ZoneInfo) -> datetime:
    """Convert a Unix-UTC timestamp to location-local wall-clock (DST-correct)."""
    return datetime.fromtimestamp(unix_ts, tz)


def _coerce_uvi(value: object) -> float:
    """Coerce a verbatim ``uvi`` value to ``float``, degrading to ``0.0`` (CR-01).

    A present-but-non-numeric value (``"NA"``, a list, ``None``) must NOT raise out
    of ``compute_uv`` — the briefing-spine isolation invariant (T-14-04) requires it
    to degrade. ``float(x or 0.0)`` alone still raises on ``"NA"``, so guard it.
    """
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


# WHO/EPA UV bands on the ROUND-then-band integer value (A2):
# 0-2 Low, 3-5 Moderate, 6-7 High, 8-10 Very High, 11+ Extreme.
# Ordered (ceiling, label) table — NOT an inline if-chain in compute_uv.
_BANDS: tuple[tuple[int, str], ...] = (
    (2, "Low"),
    (5, "Moderate"),
    (7, "High"),
    (10, "Very High"),
)


def uv_category(uvi: float) -> str:
    """WHO band word for a UV index, round-then-band (A2).

    ``uv_category(5.6) == "High"`` (rounds to 6). Uses Python's banker's rounding,
    consistent with how the displayed integer UV is derived.
    """
    u = round(uvi)
    for ceiling, label in _BANDS:
        if u <= ceiling:
            return label
    return "Extreme"


def _today_daytime_points(
    raw: dict, tz: ZoneInfo, now: datetime
) -> tuple[tuple[datetime, float], ...]:
    """Today's daytime ``(local_dt, uvi)`` hourly points, configured-tz bounded.

    Selects ``hourly[]`` buckets whose location-local date equals ``now``'s local
    date AND fall within ``[sunrise, sunset]`` from the TODAY daily entry (matched
    by its own local date via ``select_today_daily`` — D-05/F31, never positional
    ``daily[0]``). Falls back to a fixed 06:00-20:00 local window when no today entry
    matches / sun data is absent (Pitfall 5). Returns points time-sorted (D-07/F32).
    Defensive
    reads throughout: a missing ``hourly`` key, an empty list, or a bucket with a
    ``None`` ``dt``/``uvi`` is skipped, never subscripted blind (WR-01).

    CR-01/F33: a NAIVE ``now`` is treated as UTC (never HOST-local). This is a
    module-level helper that could be called directly, so it re-applies the same
    naive→UTC guard ``compute_uv`` applies — ``now.astimezone(tz)`` on a naive
    value would otherwise reinterpret in the host tz and host-shift "today" a day.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(tz).date()
    # D-05 / F31: source the [sunrise, sunset] window bound from the TODAY daily
    # entry (matched by its OWN local date), NOT positional daily[0]. A yesterday-
    # dated daily[0] otherwise supplies a ~24h-stale sunset that filters out today's
    # afternoon buckets → empty points → false stays_below. When no entry matches,
    # the selector returns None → ``or {}`` → sunrise/sunset None → has_sun False →
    # the EXISTING fixed 06:00-20:00 fallback below (never a fabricated window).
    daily0 = select_today_daily(raw.get("daily"), tz, today.isoformat()) or {}
    sunrise = daily0.get("sunrise")
    sunset = daily0.get("sunset")
    has_sun = sunrise is not None and sunset is not None

    points: list[tuple[datetime, float]] = []
    for bucket in raw.get("hourly") or []:
        bucket = bucket or {}
        ts = bucket.get("dt")
        uvi = bucket.get("uvi")
        if ts is None or uvi is None:
            continue
        # CR-01: a PRESENT-but-non-numeric ``dt``/``uvi`` (provider schema drift —
        # e.g. ``"NA"``, a list, a non-int epoch) must be SKIPPED, never raise. The
        # null/empty guards above don't cover this; coerce defensively so the
        # "never raises on a malformed hourly[]" promise (T-14-04) holds literally.
        try:
            local = _epoch_local(int(ts), tz)
            uvi_f = float(uvi)
        except (TypeError, ValueError, OverflowError, OSError):
            continue  # malformed bucket — skip, never fatal (T-14-04)
        if local.date() != today:
            continue
        if has_sun:
            try:
                if not (sunrise <= ts <= sunset):
                    continue
            except TypeError:
                # A non-numeric sunrise/sunset can't bound the window; treat the
                # bucket as in-range rather than crash the whole computation.
                pass
        else:
            # Fixed daytime window fallback (mirrors weather_views._is_daytime).
            if not (6 <= local.hour < 20):
                continue
        points.append((local, uvi_f))
    # D-07 / F32: sort by timestamp so the zip-based interpolators
    # (_first_up_cross/_first_down_cross_after) never straddle the wrong pair on an
    # out-of-order payload or a DST fall-back duplicate hour.
    points.sort(key=lambda p: p[0])
    return tuple(points)


def _first_up_cross(
    points: tuple[tuple[datetime, float], ...], threshold: float
) -> datetime | None:
    """First instant UV rises to ``threshold``, linearly interpolated.

    Returns the interpolated crossing instant between the straddling hourly points
    (``t0 + (t1 - t0) * (threshold - u0) / (u1 - u0)``). If the first daytime point
    is already at/above the threshold, returns that point's time (no interpolation).
    ``None`` if the threshold is never reached.
    """
    for (t0, u0), (t1, u1) in zip(points, points[1:]):
        if u0 < threshold <= u1:
            frac = (threshold - u0) / (u1 - u0)
            return t0 + (t1 - t0) * frac
    if points and points[0][1] >= threshold:
        return points[0][0]
    return None


def _first_down_cross_after(
    points: tuple[tuple[datetime, float], ...], threshold: float, start: datetime
) -> datetime | None:
    """First instant UV falls back below ``threshold`` at/after ``start``.

    Linearly interpolated like the up-cross. ``None`` if UV never drops back below
    the threshold within today's daytime points (caller bounds by sunset via the
    last daytime point).
    """
    for (t0, u0), (t1, u1) in zip(points, points[1:]):
        if t1 < start:
            continue
        if u0 >= threshold > u1:
            frac = (u0 - threshold) / (u0 - u1)
            cross = t0 + (t1 - t0) * frac
            # WR-03: on a non-monotone profile the interpolated down-cross can land
            # in a pair whose EARLIER portion already dipped below ``start`` (UV
            # dips, climbs back, then the real up-cross happens later). Returning
            # such an instant would yield a window whose end precedes its start.
            # Bound the down-cross at/after ``start`` so the window never reverses.
            if cross >= start:
                return cross
    return None


def compute_uv(
    onecall_imp: dict | None,
    onecall_met: dict | None,
    threshold: float,
    *,
    tz: ZoneInfo,
    now: datetime | None = None,
) -> UvSummary:
    """Compute today's :class:`UvSummary` from the One Call payload.

    Reads UV numbers from ``onecall_imp`` only (A1 — UV is unitless); ``onecall_met``
    is accepted for signature parity with ``Forecast.from_payloads`` and ignored.
    ``current`` is ``current.uvi`` verbatim, ``max`` is the TODAY daily entry's
    ``uvi`` (matched by its own local date — D-05/F31, not positional ``daily[0]``),
    and the crossing/window/peak fields derive from today's daytime ``hourly[]``
    points (Pitfall 6). All time math uses ``tz`` (the configured location tz),
    never the API ``timezone`` field (Pitfall 3). ``now`` defaults to
    ``datetime.now(tz)``; an injected ``now`` may be NAIVE — it is then treated as
    UTC (CR-01/F33), never reinterpreted in the HOST-local tz. This keeps the UV
    "today" anchored to the same UTC-derived local date as the briefing ``{date}``
    and the store ``target_local_date`` (both via ``local_date_for``), so they can
    never diverge by a day on a non-UTC host near midnight.

    Never raises on a malformed/empty ``hourly[]``: with no usable daytime points it
    returns ``stays_below=True`` with ``None`` crossing/window/peak (T-14-04).
    """
    raw = onecall_imp or {}
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        # CR-01/F33: a naive ``now`` is UTC, never host-local. Mirrors
        # ``local_date_iso`` so the normalized ``now`` flows into both the
        # ``today_iso`` anchor below and ``_today_daytime_points`` consistently.
        now = now.replace(tzinfo=timezone.utc)

    cur = raw.get("current") or {}
    # D-05 / F31: display-max reads the TODAY daily entry (matched by its own local
    # date), NOT positional daily[0]. When no entry matches today the selector
    # returns None → ``or {}`` → max_uvi degrades to 0.0 (the existing display
    # degrade), never shipping a non-today uvi as today's max.
    today_iso = now.astimezone(tz).date().isoformat()
    daily0 = select_today_daily(raw.get("daily"), tz, today_iso) or {}
    # CR-01: coerce verbatim current/max defensively — a present-but-non-numeric
    # ``current.uvi``/``daily[0].uvi`` (schema drift) degrades to 0.0 rather than
    # raising out of the briefing spine (T-14-04).
    current = _coerce_uvi(cur.get("uvi"))
    max_uvi = _coerce_uvi(daily0.get("uvi"))
    category = uv_category(max_uvi)

    points = _today_daytime_points(raw, tz, now)

    # Peak CLOCK derives from the hourly argmax (peak VALUE prefers daily[0].uvi for
    # display, but we expose the hourly-argmax value here as peak_uvi per the plan's
    # "peak value should agree with daily[0].uvi" + "clock from hourly argmax").
    peak_time: datetime | None = None
    peak_uvi = 0.0
    if points:
        peak_dt, peak_uvi = max(points, key=lambda p: p[1])
        peak_time = peak_dt

    crossing_time = _first_up_cross(points, threshold)
    window_start: datetime | None = None
    window_end: datetime | None = None
    stays_below = crossing_time is None

    if crossing_time is not None:
        window_start = crossing_time
        down = _first_down_cross_after(points, threshold, crossing_time)
        # Bound by the last daytime point (sunset-bounded) when UV never drops back
        # below threshold within today's daytime horizon.
        window_end = down if down is not None else (points[-1][0] if points else None)
        # WR-03 belt-and-suspenders: never present a reversed window. If a
        # pathological non-monotone profile still yields an end before the start,
        # fall back to the sunset-bounded last daytime point.
        if window_end is not None and window_end < window_start:
            window_end = points[-1][0] if points else None

    if stays_below:
        # No crossing → null out the window/crossing fields; peak still reflects the
        # day's hourly argmax (it remains informative even below threshold).
        crossing_time = None
        window_start = None
        window_end = None

    return UvSummary(
        current=current,
        max=max_uvi,
        category=category,
        peak_uvi=peak_uvi,
        peak_time=peak_time,
        crossing_time=crossing_time,
        window_start=window_start,
        window_end=window_end,
        stays_below=stays_below,
        hourly_points=points,
    )
