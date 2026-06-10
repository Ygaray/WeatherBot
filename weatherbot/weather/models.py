"""The normalized ``Forecast`` model (FCST-03/04/05/06).

``Forecast`` hides the OpenWeather One Call 3.0 JSON shape behind a small object
the renderer, persistence layer, and Discord channel all consume. It:

* carries normalized current fields (temp, feels-like, conditions, wind,
  humidity) plus the day's high/low/rain straight from One Call ``daily[0]``
  (no 3-hour bucket aggregation — that 2.5 logic was retired in Plan 02-01, D-01);
* reads BOTH ``imperial`` and ``metric`` One Call payloads so display can show
  imperial-primary-with-metric (``72°F (22°C)`` / ``8 mph (3.6 m/s)``, FCST-04)
  without conversion drift;
* derives the briefing content: five threshold-driven ``{hint}`` lines
  (umbrella/cold/heat/wind/sunscreen, D-06/07) and a passive ``{alert}`` summary
  from ``alerts[]`` (D-08), each collapsing to an empty string when nothing fires;
* computes the location-local date from the CONFIGURED IANA timezone (D-03), NOT
  the API ``timezone`` field;
* retains BOTH raw One Call payloads so the store (DATA-03) reuses this single
  fetch;
* exposes ``placeholders()`` -- a flat ``str -> str`` map keyed by the canonical
  placeholder set -- as the stable renderer-input seam (D-04/09).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from weatherbot.config.models import Location


def _local_date_iso(loc: Location, now_utc: datetime) -> str:
    """The location's local ``YYYY-MM-DD`` today, from the CONFIGURED IANA tz.

    The configured ``Location.timezone`` is authoritative for "today" (D-03), NOT
    the API ``timezone`` field (Pitfall 3). Falls back to UTC if the location has
    no/blank timezone (Plan 03 makes ``timezone`` a required field).
    """
    tz_name = getattr(loc, "timezone", None)
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
    else:
        tz = timezone.utc
    return now_utc.astimezone(tz).date().isoformat()


def _hints(
    rain_chance: int, feels_imp: float, wind_imp: float, uvi_max: float
) -> str:
    """The five code-driven hints (D-06/07) joined one per line; "" when none.

    Hardcoded imperial thresholds (configurable thresholds are deferred to v2).
    Cold/heat read FEELS-LIKE (not raw temp); sunscreen reads the day's MAX uv.
    """
    lines: list[str] = []
    if rain_chance > 40:
        lines.append("Bring an umbrella ☔")
    if feels_imp < 40:
        lines.append("Bundle up, it's cold \U0001F9E5")
    if feels_imp > 90:
        lines.append("Stay hydrated, it's hot \U0001F975")
    if wind_imp > 25:
        lines.append("Windy out there \U0001F4A8")
    if uvi_max >= 6:
        lines.append("Wear sunscreen \U0001F9F4")
    return "\n".join(lines)


def _alert_line(alerts: list[dict]) -> str:
    """A concise summary of distinct active alert events (D-08); "" when none.

    ``alerts`` is ABSENT on a clear day (Pitfall 2), so callers pass ``or []``.
    """
    if not alerts:
        return ""
    events: list[str] = []
    for a in alerts:
        ev = (a or {}).get("event")
        if ev and ev not in events:
            events.append(ev)
    if not events:
        return ""
    return "⚠️ " + "; ".join(events)


@dataclass
class Forecast:
    """Normalized weather for one location, ready for render/persist/embed."""

    location: str
    lat: float
    lon: float

    # Current conditions (both units; imperial is primary for display).
    temp_imp: float
    temp_met: float
    feels_imp: float
    feels_met: float
    conditions: str
    wind_imp: float
    wind_met: float
    humidity: int

    # Today's high/low straight from One Call ``daily[0]`` (location-local day).
    # ``None`` only if the payload is missing the field entirely (defensive).
    high_imp: float | None
    high_met: float | None
    low_imp: float | None
    low_met: float | None
    rain_chance: int

    # The day's max UV (``daily[0].uvi``) — drives the sunscreen hint.
    uvi_max: float

    # Derived briefing content (D-06/07/08); empty strings collapse the line.
    hint: str
    alert: str

    # Location-local date (YYYY-MM-DD) for the {date} placeholder (D-03 tz).
    local_date: str

    # Retained raw One Call payloads for the store (DATA-03 single-fetch reuse).
    raw_onecall_imp: dict
    raw_onecall_met: dict

    @classmethod
    def from_payloads(
        cls,
        loc: Location,
        onecall_imp: dict,
        onecall_met: dict,
        now_utc: datetime | None = None,
    ) -> Forecast:
        """Build a Forecast from the two raw One Call 3.0 payloads (imp + met).

        Reads ``current`` (temp/feels_like/wind_speed/humidity/weather),
        ``daily[0]`` (temp.max/min, pop, uvi) and ``alerts[]`` from each payload.
        Defensive ``.get() or {}``/``or []`` access tolerates malformed/partial
        payloads and the clear-day case where ``alerts`` is absent (T-02-02 /
        Pitfall 2). The local date derives from the CONFIGURED IANA tz, not the
        API ``timezone`` (D-03). ``now_utc`` is injectable for deterministic tests.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)

        # ``or {}`` / ``or []`` because a present-but-null field returns None.
        cur_i = onecall_imp.get("current") or {}
        cur_m = onecall_met.get("current") or {}
        day_i = (onecall_imp.get("daily") or [{}])[0] or {}
        day_m = (onecall_met.get("daily") or [{}])[0] or {}
        alerts = onecall_imp.get("alerts") or []

        weather = cur_i.get("weather") or [{}]
        first = weather[0] if weather else {}
        conditions = (first or {}).get("main", "")

        temp_i = day_i.get("temp") or {}
        temp_m = day_m.get("temp") or {}
        rain_chance = round((day_i.get("pop") or 0.0) * 100)
        uvi_max = day_i.get("uvi") or 0.0

        feels_imp = cur_i.get("feels_like") or 0.0
        feels_met = cur_m.get("feels_like") or 0.0
        wind_imp = cur_i.get("wind_speed") or 0.0
        wind_met = cur_m.get("wind_speed") or 0.0

        return cls(
            location=loc.name,
            lat=loc.lat,
            lon=loc.lon,
            temp_imp=cur_i.get("temp") or 0.0,
            temp_met=cur_m.get("temp") or 0.0,
            feels_imp=feels_imp,
            feels_met=feels_met,
            conditions=conditions,
            wind_imp=wind_imp,
            wind_met=wind_met,
            humidity=cur_i.get("humidity") or 0,
            high_imp=temp_i.get("max"),
            high_met=temp_m.get("max"),
            low_imp=temp_i.get("min"),
            low_met=temp_m.get("min"),
            rain_chance=rain_chance,
            uvi_max=uvi_max,
            hint=_hints(rain_chance, feels_imp, wind_imp, uvi_max),
            alert=_alert_line(alerts),
            local_date=_local_date_iso(loc, now_utc),
            raw_onecall_imp=onecall_imp,
            raw_onecall_met=onecall_met,
        )

    # --- display properties (imperial primary, metric in parens, FCST-04) ---

    @staticmethod
    def _temp_str(imp: float, met: float) -> str:
        return f"{round(imp)}°F ({round(met)}°C)"

    @property
    def temp_display(self) -> str:
        return self._temp_str(self.temp_imp, self.temp_met)

    @property
    def feels_like_display(self) -> str:
        return self._temp_str(self.feels_imp, self.feels_met)

    @property
    def wind_display(self) -> str:
        return f"{round(self.wind_imp)} mph ({round(self.wind_met, 1)} m/s)"

    @property
    def high_display(self) -> str:
        # Fallback to current temp when the high is unavailable (defensive).
        if self.high_imp is None or self.high_met is None:
            return self.temp_display
        return self._temp_str(self.high_imp, self.high_met)

    @property
    def low_display(self) -> str:
        if self.low_imp is None or self.low_met is None:
            return self.temp_display
        return self._temp_str(self.low_imp, self.low_met)

    def placeholders(self) -> dict[str, str]:
        """Flat ``str -> str`` map keyed by the canonical set (D-04/09 seam)."""
        return {
            "temp": self.temp_display,
            "feels_like": self.feels_like_display,
            "high": self.high_display,
            "low": self.low_display,
            "rain": f"{self.rain_chance}%",
            "wind": self.wind_display,
            "humidity": f"{self.humidity}%",
            "conditions": self.conditions,
            "location": self.location,
            "date": self.local_date,
            "hint": self.hint,
            "alert": self.alert,
        }
