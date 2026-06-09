"""The normalized ``Forecast`` model (FCST-03/04).

``Forecast`` hides the OpenWeather JSON shape behind a small object the renderer,
persistence layer, and Discord channel all consume. It:

* carries normalized current fields (temp, conditions, wind, humidity) plus the
  aggregated high/low/rain for the location's local date;
* fetches BOTH ``imperial`` and ``metric`` units so display can show
  imperial-primary-with-metric (``72°F (22°C)`` / ``8 mph (3.6 m/s)``, FCST-04)
  without conversion drift;
* applies the late-day high/low fallback (Open Question 2): when the forecast has
  no buckets left for local-today, ``today_aggregate`` returns ``None`` and the
  ``high_display``/``low_display`` fall back to the current temp;
* retains the four raw payloads so the store (DATA-03) reuses this single fetch;
* exposes ``placeholders()`` -- a flat ``str -> str`` map keyed by the D-01
  placeholder set -- as the stable renderer-input seam (D-04).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from weatherbot.weather.aggregate import today_aggregate

if TYPE_CHECKING:
    from weatherbot.config.models import Location


def _local_date_iso(forecast_payload: dict, now_utc: datetime) -> str:
    """The location's local ``YYYY-MM-DD`` today, from ``city.timezone`` offset."""
    city = forecast_payload.get("city") or {}
    offset = timedelta(seconds=city.get("timezone") or 0)
    return (now_utc + offset).date().isoformat()


@dataclass
class Forecast:
    """Normalized weather for one location, ready for render/persist/embed."""

    location: str
    lat: float
    lon: float

    # Current conditions (both units; imperial is primary for display).
    temp_imp: float
    temp_met: float
    conditions: str
    wind_imp: float
    wind_met: float
    humidity: int

    # Aggregated today (location-local). ``None`` => late-day, no buckets left.
    high_imp: float | None
    high_met: float | None
    low_imp: float | None
    low_met: float | None
    rain_chance: int

    # Location-local date (YYYY-MM-DD) for the {date} placeholder.
    local_date: str

    # Retained raw payloads for the store (DATA-03 single-fetch reuse).
    raw_current_imp: dict
    raw_current_met: dict
    raw_forecast_imp: dict
    raw_forecast_met: dict

    @classmethod
    def from_payloads(
        cls,
        loc: Location,
        current_imp: dict,
        current_met: dict,
        forecast_imp: dict,
        forecast_met: dict,
        now_utc: datetime | None = None,
    ) -> Forecast:
        """Build a Forecast from the four raw payloads.

        ``today_aggregate`` runs on BOTH forecast payloads so high/low exist in
        each unit. Defensive ``.get()`` access tolerates malformed/partial
        payloads (T-02-02). ``now_utc`` is injectable for deterministic tests.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        agg_imp = today_aggregate(forecast_imp, now_utc=now_utc)
        agg_met = today_aggregate(forecast_met, now_utc=now_utc)

        # ``or {}`` / ``or []`` because a present-but-null field returns None.
        imp_main = current_imp.get("main") or {}
        met_main = current_met.get("main") or {}
        imp_wind = current_imp.get("wind") or {}
        met_wind = current_met.get("wind") or {}
        weather = current_imp.get("weather") or [{}]
        first = weather[0] if weather else {}
        conditions = (first or {}).get("main", "")

        return cls(
            location=loc.name,
            lat=loc.lat,
            lon=loc.lon,
            temp_imp=imp_main.get("temp", 0.0),
            temp_met=met_main.get("temp", 0.0),
            conditions=conditions,
            wind_imp=imp_wind.get("speed", 0.0),
            wind_met=met_wind.get("speed", 0.0),
            humidity=imp_main.get("humidity") or 0,
            high_imp=agg_imp["high"],
            high_met=agg_met["high"],
            low_imp=agg_imp["low"],
            low_met=agg_met["low"],
            rain_chance=agg_imp["rain_chance"],
            local_date=_local_date_iso(forecast_imp, now_utc),
            raw_current_imp=current_imp,
            raw_current_met=current_met,
            raw_forecast_imp=forecast_imp,
            raw_forecast_met=forecast_met,
        )

    # --- display properties (imperial primary, metric in parens, FCST-04) ---

    @staticmethod
    def _temp_str(imp: float, met: float) -> str:
        return f"{round(imp)}°F ({round(met)}°C)"

    @property
    def temp_display(self) -> str:
        return self._temp_str(self.temp_imp, self.temp_met)

    @property
    def wind_display(self) -> str:
        return f"{round(self.wind_imp)} mph ({round(self.wind_met, 1)} m/s)"

    @property
    def high_display(self) -> str:
        # Late-day fallback to current temp (Open Question 2).
        if self.high_imp is None or self.high_met is None:
            return self.temp_display
        return self._temp_str(self.high_imp, self.high_met)

    @property
    def low_display(self) -> str:
        if self.low_imp is None or self.low_met is None:
            return self.temp_display
        return self._temp_str(self.low_imp, self.low_met)

    def placeholders(self) -> dict[str, str]:
        """Flat ``str -> str`` map keyed by the D-01 placeholder set (D-04 seam)."""
        return {
            "temp": self.temp_display,
            "high": self.high_display,
            "low": self.low_display,
            "rain": f"{self.rain_chance}%",
            "wind": self.wind_display,
            "humidity": f"{self.humidity}%",
            "conditions": self.conditions,
            "location": self.location,
            "date": self.local_date,
        }
