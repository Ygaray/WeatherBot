"""httpx client for the free OpenWeather 2.5 endpoints (FCST-01).

Fetches current conditions (``/data/2.5/weather``) and the 5-day/3-hour forecast
(``/data/2.5/forecast``) by ``lat``/``lon``. Notes:

* An explicit ``timeout`` is always set so the process never hangs forever on a
  slow OpenWeather response (T-02-03).
* ``raise_for_status()`` lets a non-2xx (e.g. a fresh-key 401, Pitfall 7) surface
  clearly. Retries are a Phase-4 concern; nothing is retried here.
* The API key travels in the ``appid`` query param, so the full request URL is a
  secret. This module never logs the URL or the key (Pitfall 5 / T-02-01).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from weatherbot.config.models import Location

BASE = "https://api.openweathermap.org/data/2.5"

# Explicit, finite timeout so a slow/hanging response can never wedge the process.
_TIMEOUT = 10.0

# httpx logs the FULL request URL (which carries the secret ``appid``) at INFO on
# its own "httpx" logger. Raise that logger to WARNING so the key cannot leak
# into logs (Pitfall 5 / T-02-01). Errors/warnings (which do not include the URL)
# still propagate.
logging.getLogger("httpx").setLevel(logging.WARNING)


def _get(path: str, lat: float, lon: float, key: str, units: str) -> dict:
    """GET one OpenWeather 2.5 endpoint and return parsed JSON.

    The ``appid`` is passed as a query param and is therefore never logged.
    """
    with httpx.Client(timeout=_TIMEOUT) as c:
        response = c.get(
            f"{BASE}/{path}",
            params={
                "lat": lat,
                "lon": lon,
                "appid": key,
                "units": units,
                "lang": "en",
            },
        )
        # Surface 401/403/etc. clearly; not retried in Phase 1 (Pitfall 7).
        response.raise_for_status()
        return response.json()


def fetch_current(loc: Location, key: str, units: str = "imperial") -> dict:
    """Fetch current conditions for ``loc`` from ``/data/2.5/weather``."""
    return _get("weather", loc.lat, loc.lon, key, units)


def fetch_forecast(loc: Location, key: str, units: str = "imperial") -> dict:
    """Fetch the 5-day/3-hour forecast for ``loc`` from ``/data/2.5/forecast``."""
    return _get("forecast", loc.lat, loc.lon, key, units)
