"""PURE 3-hour-bucket aggregation: today's high/low/rain on the LOCATION's date.

This is the highest-risk correctness surface of the briefing (FCST-02). It avoids
the two documented silent-correctness bugs:

* It selects buckets by the *location's local date* (derived from
  ``city.timezone`` seconds offset against each bucket's unix ``dt``), NOT the
  host/UTC date and NOT the UTC-ISO ``dt_txt`` string (Pitfall 1).
* It derives today's high/low from the *forecast buckets* (max/min of
  ``main.temp``), NOT the current-endpoint ``temp_min``/``temp_max`` which are
  "min/max at the current moment" (Pitfall 2).

It also tolerates a clear-sky day where ``rain`` is absent and ``pop`` is 0
(Pitfall 6) via defensive ``.get()`` access, and returns ``high``/``low`` as
``None`` when no buckets fall on local-today (late-in-the-day fetch); the
fallback for that case is applied by the Forecast model, not here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def today_aggregate(
    forecast_payload: dict, now_utc: datetime | None = None
) -> dict:
    """Compute today's (location-local) high, low, and rain chance.

    Args:
        forecast_payload: a raw OpenWeather ``/data/2.5/forecast`` payload.
        now_utc: the current UTC instant; injectable so timezone-boundary tests
            are deterministic. Defaults to ``datetime.now(timezone.utc)``.

    Returns:
        ``{"high": float | None, "low": float | None, "rain_chance": int}`` where
        ``high``/``low`` are the max/min of ``main.temp`` over local-today's
        buckets (``None`` if none remain), and ``rain_chance`` is
        ``round(max(pop) * 100)`` over those buckets (0 if none).
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    # ``or {}`` because a present-but-null field returns None from ``.get``.
    city = forecast_payload.get("city") or {}
    offset = timedelta(seconds=city.get("timezone") or 0)

    # "Today" in the LOCATION's local time, not the host's.
    target_date = (now_utc + offset).date()

    temps: list[float] = []
    pops: list[float] = []
    for item in forecast_payload.get("list", []):
        unix_dt = item.get("dt")
        if unix_dt is None:
            continue
        # Offset the unix ``dt`` (NEVER ``dt_txt``, which is UTC ISO).
        bucket_local = datetime.fromtimestamp(unix_dt, tz=timezone.utc) + offset
        if bucket_local.date() != target_date:
            continue
        main = item.get("main") or {}
        temp = main.get("temp")
        if temp is not None:
            temps.append(temp)
        # ``pop`` is normally present, but coerce a missing-OR-null value to 0.0
        # (``.get(key, default)`` returns None when the key is present-but-null).
        pop = item.get("pop")
        pops.append(pop if pop is not None else 0.0)

    high = max(temps) if temps else None
    low = min(temps) if temps else None
    rain_chance = round(max(pops) * 100) if pops else 0
    return {"high": high, "low": low, "rain_chance": rain_chance}
