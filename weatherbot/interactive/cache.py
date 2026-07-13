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
- ``invalidate`` clears every entry AND bumps a generation counter under the lock —
  the hook a successful config reload calls (Pattern 4). An in-flight off-loop fetch
  captures the generation at its miss (inside the get lock) and refuses to store its
  result if the generation moved, so a fetch that predates the reload can never
  re-seed a stale (pre-reload) forecast (D-03/F13).
- The backing cache is a :class:`_PinnedTTLCache`: it is size-capped (``maxsize``)
  but eviction NEVER targets the plain ``!weather`` (``suffix=None``, ``str``-keyed)
  entry — heavy forecast/flag-suffixed (tuple-keyed) use evicts only the suffixed
  variants, keeping the base weather entry warm (D-04).

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


class _PinnedTTLCache(TTLCache):
    """A ``TTLCache`` whose eviction NEVER targets the plain-weather entry (D-04).

    The cache key is either a bare ``loc_id`` (``str``) for a plain ``!weather``
    lookup (``suffix=None``) or a ``(loc_id, suffix)`` tuple for a forecast/flag
    variant. The invariant is that the plain-weather (``str``-keyed) entry is never
    the one evicted under a size-cap: heavy forecast/flag-suffixed churn evicts only
    the SUFFIXED (tuple-keyed) entries. We override :meth:`popitem` (the hook
    ``cachetools`` calls when ``maxsize`` is exceeded) to pop the least-recently-used
    *suffixed* entry, skipping any pinned plain-weather key. TTL-driven expiry is
    unchanged — an expired plain entry still drops on its own (correctness), the pin
    only protects it from being *evicted to make room* for suffixed variants.
    """

    def popitem(self):
        """Evict the LRU entry, but never a pinned plain-weather (``str``) key.

        ``cachetools`` calls this to make room when the cache exceeds ``maxsize``.
        We scan the underlying LRU order and pop the first evictable (tuple-keyed,
        i.e. suffixed) entry, protecting the ``str``-keyed plain-weather entries.
        If every remaining entry is a protected plain key (no evictable candidate),
        fall back to the default LRU eviction so the size cap is still honored.
        """
        # ``TTLCache`` stores live keys with their LRU order in the parent
        # ``Cache.__data`` / order structures; iterate the public keys (oldest→newest
        # LRU) and delete the first suffixed (tuple) key, returning it as evicted.
        for key in list(self):
            if isinstance(key, tuple):
                value = self[key]
                del self[key]
                return (key, value)
        # No evictable (suffixed) entry left — honor the cap via default LRU.
        return super().popitem()


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
        # ACCEPTED (F50, v2.1): a single maxsize=16 is shared across the plain-weather
        # entry and every forecast/flag SUFFIX key, so in principle heavy suffixed churn
        # could evict entries the base was meant to keep warm. This is latent at the
        # 2-location deployment (~10 live keys < 16 → the cap is never reached, no
        # eviction fires) and the _PinnedTTLCache.popitem override already PINS the plain
        # weather entry so suffixed variants are always evicted first. Retuning/partitioning
        # the cap has subtle eviction/warmth effects and buys nothing at current scale, so
        # the shared cap stays as an intentional, bounded default.
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
            self._cache: TTLCache = _PinnedTTLCache(
                maxsize=maxsize, ttl=ttl_seconds, timer=timer
            )
        else:
            self._cache = _PinnedTTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = threading.Lock()
        # Generation/epoch counter (D-03): bumped under the lock by ``invalidate``.
        # An in-flight off-loop fetch captures the generation at the same instant it
        # observes the miss (INSIDE the get lock) and refuses to store its result if
        # the generation has since moved — killing the F13 stale re-populate WITHOUT
        # ever holding the lock across ``lookup_weather``.
        self._generation = 0

    def lookup(
        self, name: str | None, config: Config, suffix: str | None = None
    ) -> LookupResult:
        """Return a (possibly cached) ``LookupResult`` for ``name`` (ALWAYS off-loop).

        Resolve the cache key via ``resolve_location(config, name).id`` — this lets
        ``UnknownLocationError`` bubble out un-cached (the CMD-02 error path). Take
        the ``Lock`` ONLY around the dict ``get``; on a hit return it. On a miss call
        ``lookup_weather`` WITHOUT holding the lock (the network must not serialize),
        then take the ``Lock`` only to store the result.

        ``suffix`` widens the key to ``(location.id, suffix)`` so the on-demand
        FORECAST dispatch (command name + variant + sorted flags) NEVER collides a
        ``!weather home`` result with a ``!weekday-forecast home --compact +sat``
        result (A5). A bare ``!weather`` lookup passes ``suffix=None`` → the original
        location-id-only key, so the existing weather-command cache behavior is
        unchanged. (The fetched One Call payload is identical across variants/flags —
        the suffix only keeps the per-command CACHED ENTRY distinct, never causes an
        extra fetch beyond the first miss for each key.)

        MUST be dispatched via ``loop.run_in_executor`` (D-10) — it blocks on httpx.
        """
        loc_id = resolve_location(config, name).id
        key = loc_id if suffix is None else (loc_id, suffix)

        with self._lock:
            hit = self._cache.get(key)
            # Capture the generation INSIDE the same lock as the get (Pitfall 2 —
            # NEVER after releasing the lock, which would race ``invalidate`` and
            # capture a post-invalidate generation, defeating the guard). This value
            # is consistent with the miss we just observed.
            gen_at_start = self._generation
        if hit is not None:
            _log.debug("forecast cache hit", key=key)
            return hit

        # Cache miss: fetch OUTSIDE the lock so a slow OpenWeather response never
        # serializes lookups for other locations (the off-loop-no-lock design, D-03).
        # ACCEPTED (F49, v2.1): each forecast SUFFIX key (variant + flags) is a distinct
        # cache key, so a first miss on each suffix triggers its own dual One Call fetch
        # of the identical payload rather than sharing one fetch across variants. This is
        # an intentional, documented, bounded tradeoff (see the method docstring): keying
        # per-command keeps each cached ENTRY distinct without a shared-payload rewrite,
        # and the extra fetches are trivially bounded against the 60/min & 1M/month free
        # tier at this single-user scale. De-duplicating fetches across suffixes would add
        # a payload-sharing indirection to this hot path for no live quota benefit.
        _log.debug("forecast cache miss", key=key)
        result = lookup_weather(name, config=config, settings=self._settings)

        with self._lock:
            # Generation guard (D-03/F13): only store if no ``invalidate`` fired while
            # this fetch was in flight. If the generation moved, the config was
            # reloaded mid-fetch and ``result`` is a pre-reload snapshot — drop it so
            # a stale (wrong lat/lon/units/template) entry is never served to TTL.
            if self._generation == gen_at_start:
                self._cache[key] = result
            else:
                _log.debug(
                    "forecast cache store dropped (stale generation)",
                    key=key,
                    gen_at_start=gen_at_start,
                    generation=self._generation,
                )
        return result

    def invalidate(self) -> None:
        """Clear every entry and bump the generation under the lock (Pattern 4, D-03).

        Bumping ``self._generation`` under the same lock that guards the store makes
        any in-flight off-loop fetch (which captured the pre-bump generation at its
        miss) self-reject its result — so a fetch that predates this reload can never
        re-seed stale data after we clear.
        """
        with self._lock:
            self._cache.clear()
            self._generation += 1
        _log.info("forecast cache invalidated")
