"""The thread-safe per-location TTL forecast cache (``ForecastCache``, CMD-06).

``ForecastCache`` wraps the sync read-only core ``lookup_weather`` behind a
:class:`cachetools.TTLCache`, keyed on the *resolved* :class:`~weatherbot.config.models.Location`
``.id`` so that ``home`` / ``Home`` / a bare default all collapse to ONE entry.
Two repeated ``!weather <same loc>`` commands within the TTL therefore trigger
exactly ONE OpenWeather fetch — the rate-limit guard that keeps the operator's
repeated commands off the free-tier quota (T-11-06).

Concurrency contract (mirrors ``ConfigHolder``'s lock-guarded-shared-state house
style — class owns state + a ``threading.Lock``, the lock held ONLY around the
dict mutation, never across the network fetch):

- ``lookup`` is ALWAYS called via ``loop.run_in_executor`` from the bot's event
  loop (D-10) — it is plain blocking code (resolve + httpx fetch + render).
- The ``Lock`` is taken ONLY around the cache ``get``/store dict operations. The
  ``lookup_weather`` network fetch on a miss runs WITHOUT the lock held, so two
  misses for two different locations never serialize behind one slow OpenWeather
  response. (A double-fetch for the SAME key under a race is acceptable and
  bounded — correctness over a marginal extra call.)
- ``invalidate`` clears every entry under the lock — the hook a successful config
  reload calls (Pattern 4) so a stale forecast is never served against a freshly
  reloaded config.

An unknown location name is NOT cached: ``resolve_location`` raises
:class:`~weatherbot.interactive.lookup.UnknownLocationError` before any dict touch,
and that error bubbles straight out of ``lookup`` (the desired CMD-02 error path).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

import structlog
from cachetools import TTLCache

from weatherbot.config import resolve_location
from weatherbot.interactive.lookup import lookup_weather

if TYPE_CHECKING:
    from weatherbot.config.models import Config
    from weatherbot.config.settings import Settings
    from weatherbot.interactive.lookup import LookupResult

_log = structlog.get_logger(__name__)


class ForecastCache:
    """A thread-safe, per-location TTL cache wrapping ``lookup_weather`` (CMD-06).

    Keyed on the resolved ``Location.id`` so case variants / the bare default
    collapse to one entry. Serves repeats within the TTL from memory; refetches
    after expiry. The ``Lock`` guards only the dict ops, never the network fetch.
    """

    def __init__(
        self,
        *,
        settings: Settings | None,
        ttl_seconds: int = 600,
        maxsize: int = 16,
        timer: Callable[[], float] | None = None,
    ) -> None:
        """Build the cache.

        ``ttl_seconds`` defaults to ~10 minutes (D-12). ``timer`` is injectable so
        tests can advance a controllable clock across the TTL boundary without a
        wall-clock sleep; when ``None`` the ``TTLCache`` default monotonic timer is
        used. ``settings`` is forwarded to ``lookup_weather`` to build the One Call
        client on a miss (tests pass ``None`` because they patch ``lookup_weather``).
        """
        self._settings = settings
        if timer is not None:
            self._cache: TTLCache = TTLCache(
                maxsize=maxsize, ttl=ttl_seconds, timer=timer
            )
        else:
            self._cache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = threading.Lock()

    def lookup(self, name: str | None, config: Config) -> LookupResult:
        """Return a (possibly cached) ``LookupResult`` for ``name`` (ALWAYS off-loop).

        Resolve the cache key via ``resolve_location(config, name).id`` — this lets
        ``UnknownLocationError`` bubble out un-cached (the CMD-02 error path). Take
        the ``Lock`` ONLY around the dict ``get``; on a hit return it. On a miss call
        ``lookup_weather`` WITHOUT holding the lock (the network must not serialize),
        then take the ``Lock`` only to store the result.

        MUST be dispatched via ``loop.run_in_executor`` (D-10) — it blocks on httpx.
        """
        key = resolve_location(config, name).id

        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            _log.debug("forecast cache hit", key=key)
            return hit

        # Cache miss: fetch OUTSIDE the lock so a slow OpenWeather response never
        # serializes lookups for other locations.
        _log.debug("forecast cache miss", key=key)
        result = lookup_weather(name, config=config, settings=self._settings)

        with self._lock:
            self._cache[key] = result
        return result

    def invalidate(self) -> None:
        """Clear every cached entry under the lock (the config-reload hook, Pattern 4)."""
        with self._lock:
            self._cache.clear()
        _log.info("forecast cache invalidated")
