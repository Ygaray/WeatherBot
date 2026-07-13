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
  the One Call fetch AND the geocode call. It ALSO redacts the key from the
  ``raise_for_status()`` message (HARD-SEC-01, D-01): that message embeds the full
  request URL, the gap the "never logs the URL" note above missed. Both raise sites
  catch the key-bearing ``HTTPStatusError`` and re-raise a fresh, REDACTED one
  ``from None`` (the ``from None`` drops the key-bearing ``__context__`` so the FULL
  traceback stays clean), keeping the type + ``.response.status_code`` intact.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

from weatherbot._redact import redact_appid

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
#
# ACCEPTED (F67, v2.1): intentional httpx-URL-log suppression retained; redaction is
# the primary control. The Phase-30 ``_LiveStderr`` backstop (__init__.py, D-02) only
# scrubs structlog output; the ``httpx`` logger emits its request-URL INFO line through
# STDLIB logging, which ``cli._configure_logging``'s ``logging.basicConfig`` routes to
# the RAW ``sys.stderr`` — bypassing that backstop. So this setLevel is NOT superseded
# by redaction and stays as defense-in-depth (verified: ``test_redact_hygiene.py`` green
# either way; httpx ``logger.info`` at INFO carries ``appid`` in the URL).
logging.getLogger("httpx").setLevel(logging.WARNING)


def _parse_json_or_transient(response: httpx.Response) -> dict | list:
    """Parse a 2xx body as JSON, mapping a non-JSON body to a transient error (F68).

    A captive-portal / proxy interception can return an HTTP 200 whose body is HTML,
    not JSON. ``response.json()`` then raises a bare ``json.JSONDecodeError`` — an
    unclassified type the send-path transient/auth handlers never catch, so it degrades
    to an "unexpected" outcome instead of the retry/transient contract. Re-raise it as
    an ``httpx.ReadError`` (a ``TransportError`` that ``reliability.is_transient``
    retries and the daemon maps to ``transient_exhausted``), redacting the URL from the
    message. ``from None`` drops the key-bearing ``__context__`` (HARD-SEC-01 parity).
    """
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise httpx.ReadError(
            redact_appid(f"non-JSON 2xx body from {response.request.url}: {exc}"),
            request=response.request,
        ) from None


def fetch_onecall(loc: Location, key: str, units: str = "imperial") -> dict:
    """Fetch the One Call 3.0 payload for ``loc`` from ``/data/3.0/onecall``.

    Trims only the unused ``minutely`` block via ``exclude`` while KEEPING
    ``current``, ``hourly``, ``daily`` and ``alerts``. ``hourly[]`` is required by
    ``next-cloudy`` (Phase 12) and the UV features (Phases 14/15) — it was widened
    here (D-06), so the One Call payload must never drop it again (a regression
    canary in the client tests guards this). The ``appid`` is a query param and is
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
                # Drop only minutely; KEEP hourly (next-cloudy + Phases 14/15, D-06).
                "exclude": "minutely",
            },
        )
        # Surface 401/403/etc. clearly (subscription not active — Pitfall 1); not
        # retried here (retry is a Phase-4 concern). Redact the ``appid`` from the
        # surfaced message and re-raise a fresh, type-preserving HTTPStatusError
        # ``from None`` (HARD-SEC-01, D-01) — the key rides the URL in the default
        # message, and ``from None`` drops the key-bearing __context__.
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # WR-01: scrub the key from the request URL in place too. ``exc.request`` IS
            # ``exc.response.request`` (the same httpx object), so one mutation clears the
            # key from BOTH — no raw key survives on any exception attribute for a future
            # APM/Sentry capture or a repr-based traceback formatter to leak.
            exc.request.url = httpx.URL(redact_appid(str(exc.request.url)))
            raise httpx.HTTPStatusError(
                redact_appid(str(exc)),
                request=exc.request,
                response=exc.response,
            ) from None
        # F68: a 2xx-with-non-JSON body maps to a transient error, not a bare
        # JSONDecodeError (redacted URL, matches the caller's retry/classify contract).
        return _parse_json_or_transient(response)


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
        # Same redacted, type-preserving re-raise as fetch_onecall (HARD-SEC-01, D-01):
        # the geocode URL also carries ``appid``. ``from None`` keeps the full traceback
        # clean; the type + ``.response.status_code`` stay intact.
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # WR-01: scrub the key from the request URL in place too. ``exc.request`` IS
            # ``exc.response.request`` (the same httpx object), so one mutation clears the
            # key from BOTH — no raw key survives on any exception attribute for a future
            # APM/Sentry capture or a repr-based traceback formatter to leak.
            exc.request.url = httpx.URL(redact_appid(str(exc.request.url)))
            raise httpx.HTTPStatusError(
                redact_appid(str(exc)),
                request=exc.request,
                response=exc.response,
            ) from None
        # F68: a 2xx-with-non-JSON body maps to a transient error, not a bare
        # JSONDecodeError (redacted URL, matches the caller's retry/classify contract).
        return _parse_json_or_transient(response)
