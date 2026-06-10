"""httpx client for OpenWeather One Call 3.0 + Geocoding (FCST-01, LOC-03).

Fetches a single One Call 3.0 payload (``/data/3.0/onecall``) per unit system —
``current`` (incl. ``feels_like``/``uvi``), ``daily[0]`` (high/low/``pop``/``uvi``),
and ``alerts[]`` — by ``lat``/``lon`` (D-01). It also exposes a setup-time
``geocode`` helper (``/geo/1.0/direct``) used only by the ``--geocode`` command,
never on the send path (LOC-03). Notes:

* An explicit ``timeout`` is always set so the process never hangs forever on a
  slow OpenWeather response (T-02-04).
* ``raise_for_status()`` lets a non-2xx surface clearly — a 401/403 from One Call
  most often means the "One Call by Call" subscription is not active or not yet
  propagated (Pitfall 1). Retries are a Phase-4 concern; nothing is retried here.
* The API key travels in the ``appid`` query param, so the full request URL is a
  secret. This module never logs the URL or the key (Pitfall 6 / T-02-01) — for
  the One Call fetch AND the geocode call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from weatherbot.config.models import Location

ONECALL = "https://api.openweathermap.org/data/3.0/onecall"
GEOCODE = "https://api.openweathermap.org/geo/1.0/direct"

# Explicit, finite timeout so a slow/hanging response can never wedge the process.
_TIMEOUT = 10.0

# httpx logs the FULL request URL (which carries the secret ``appid``) at INFO on
# its own "httpx" logger. Raise that logger to WARNING so the key cannot leak
# into logs (Pitfall 6 / T-02-01). Errors/warnings (which do not include the URL)
# still propagate. This covers BOTH the One Call fetch and the geocode call.
logging.getLogger("httpx").setLevel(logging.WARNING)


def fetch_onecall(loc: Location, key: str, units: str = "imperial") -> dict:
    """Fetch the One Call 3.0 payload for ``loc`` from ``/data/3.0/onecall``.

    Trims the unused ``minutely``/``hourly`` blocks via ``exclude`` while keeping
    ``current``, ``daily`` and ``alerts``. The ``appid`` is a query param and is
    therefore never logged.
    """
    with httpx.Client(timeout=_TIMEOUT) as c:
        response = c.get(
            ONECALL,
            params={
                "lat": loc.lat,
                "lon": loc.lon,
                "appid": key,
                "units": units,
                "lang": "en",
                "exclude": "minutely,hourly",
            },
        )
        # Surface 401/403/etc. clearly (subscription not active — Pitfall 1); not
        # retried here (retry is a Phase-4 concern).
        response.raise_for_status()
        return response.json()


def geocode(query: str, key: str, limit: int = 5) -> list[dict]:
    """Resolve a free-text place to coordinates via ``/geo/1.0/direct`` (LOC-03).

    Returns a list of ``{name, lat, lon, country, state}`` matches (up to
    ``limit``, max 5 for an ambiguous name). Used ONLY by the setup-time
    ``--geocode`` command — never the send path. The ``appid`` is a query param
    and is never logged (Pitfall 6).
    """
    with httpx.Client(timeout=_TIMEOUT) as c:
        response = c.get(
            GEOCODE,
            params={"q": query, "limit": limit, "appid": key},
        )
        response.raise_for_status()
        return response.json()
