"""Wave-0 Nyquist RED scaffold for Phase 11 — the TTL forecast cache (CMD-06).

These tests are the EXECUTABLE CONTRACT that Plan 11-03 turns green. They are written
BEFORE ``weatherbot.interactive.cache`` exists: the not-yet-built ``ForecastCache`` is
referenced through a PER-TEST lazy-import helper (``_ForecastCache`` below), NOT at
module top. A hard top-level ``from weatherbot.interactive.cache import ForecastCache``
would raise at COLLECTION and HIDE every node ID — the Phase 8/9/10 Wave-0 lesson.
Deferring the import lets all four node IDs COLLECT while each still fails RED on a real
``ModuleNotFoundError``/``AttributeError`` until the cache module lands (T-11-01).

The cache contract (Pattern 4): ``lookup(name, config)`` keys on
``resolve_location(config, name).id`` (so ``home`` / ``Home`` / bare-default collapse to
ONE entry), returns the cached :class:`LookupResult` within the TTL, refetches after the
TTL expires, holds distinct entries per location, and clears on ``invalidate()``. The
wrapped fetch is the real ``lookup_weather`` — these tests patch it with a COUNTING SPY
so the hit/miss assertions exercise the real key path, never a mock that always passes.
"""

from __future__ import annotations


# --------------------------------------------------------------------------- #
# Deferred reference to the NOT-YET-BUILT cache (Phase 8/9/10 Wave-0 lesson).
# Resolved INSIDE each test body so every node ID collects while the symbol is
# absent; each call fails RED with a real ModuleNotFoundError/AttributeError.
# --------------------------------------------------------------------------- #


def _ForecastCache(*args, **kwargs):
    """Build the not-yet-built ``ForecastCache`` — RED until Plan 11-03 lands it.

    Deferred import (NOT module-top) so the node IDs collect. ``ForecastCache`` wraps
    the sync ``lookup_weather`` behind a ``cachetools.TTLCache`` keyed on the resolved
    location ``.id``, exposing ``lookup(name, config)`` and ``invalidate()``.
    """
    from weatherbot.interactive.cache import ForecastCache

    return ForecastCache(*args, **kwargs)


def _cache_module():
    """Import the cache module (for monkeypatching ``lookup_weather``) — deferred."""
    from weatherbot.interactive import cache

    return cache


# --------------------------------------------------------------------------- #
# Local config builders (mirror tests/test_reload.py — no new fixtures needed).
# --------------------------------------------------------------------------- #


def _loc(name, *, id=None, tz="America/New_York", lat=40.7128, lon=-74.006):
    from weatherbot.config import Location

    kwargs = dict(name=name, lat=lat, lon=lon, timezone=tz, schedule=[])
    if id is not None:
        kwargs["id"] = id
    return Location(**kwargs)


def _cfg(*locations):
    from weatherbot.config import Config

    return Config(locations=list(locations))


# --------------------------------------------------------------------------- #
# (1) Second lookup within the TTL HITS the cache (CMD-06) — one fetch, two reads.
# --------------------------------------------------------------------------- #


def test_second_lookup_within_ttl_hits_cache(monkeypatch):
    """CMD-06: two ``lookup("home", cfg)`` calls inside the TTL trigger exactly ONE
    underlying ``lookup_weather`` fetch — the second is served from the cache. This
    is the rate-limit guard that keeps repeated ``!weather`` commands off OpenWeather."""
    cache_mod = _cache_module()  # RED until the module exists

    fetches: list = []
    monkeypatch.setattr(
        cache_mod,
        "lookup_weather",
        lambda name, *, config, **k: fetches.append(name) or object(),
        raising=False,
    )

    cfg = _cfg(_loc("home"))
    cache = _ForecastCache(settings=None, ttl_seconds=600)

    cache.lookup("home", cfg)
    cache.lookup("home", cfg)

    assert len(fetches) == 1  # second read served from cache, not refetched


# --------------------------------------------------------------------------- #
# (2) Lookup after the TTL expires REFETCHES (CMD-06) — controllable clock.
# --------------------------------------------------------------------------- #


def test_lookup_after_ttl_refetches(monkeypatch):
    """CMD-06: once the TTL elapses, the next lookup REFETCHES (the stale entry is
    evicted). Cross the TTL deterministically with a controllable timer injected into
    the cache rather than a wall-clock sleep."""
    cache_mod = _cache_module()

    fetches: list = []
    monkeypatch.setattr(
        cache_mod,
        "lookup_weather",
        lambda name, *, config, **k: fetches.append(name) or object(),
        raising=False,
    )

    # A controllable clock the TTLCache reads for expiry (inject via the cache's
    # ``timer=`` seam so the test advances time without sleeping).
    clock = {"t": 1000.0}
    cfg = _cfg(_loc("home"))
    cache = _ForecastCache(settings=None, ttl_seconds=600, timer=lambda: clock["t"])

    cache.lookup("home", cfg)
    clock["t"] += 601  # advance past the TTL boundary
    cache.lookup("home", cfg)

    assert len(fetches) == 2  # the expired entry was refetched


# --------------------------------------------------------------------------- #
# (3) Distinct locations get distinct entries — two configured names, two fetches.
# --------------------------------------------------------------------------- #


def test_distinct_locations_distinct_entries(monkeypatch):
    """Two DIFFERENT configured locations map to two distinct cache keys (their stable
    ``.id``s), so each is fetched independently — a cached ``home`` never satisfies a
    ``!weather away`` command."""
    cache_mod = _cache_module()

    fetches: list = []
    monkeypatch.setattr(
        cache_mod,
        "lookup_weather",
        lambda name, *, config, **k: fetches.append(name) or object(),
        raising=False,
    )

    cfg = _cfg(_loc("home"), _loc("away", lat=41.0, lon=-75.0))
    cache = _ForecastCache(settings=None, ttl_seconds=600)

    cache.lookup("home", cfg)
    cache.lookup("away", cfg)

    assert len(fetches) == 2  # distinct keys → two independent fetches


# --------------------------------------------------------------------------- #
# (4) invalidate() clears the cache — a repeat call after invalidate refetches.
# --------------------------------------------------------------------------- #


def test_invalidate_clears_cache(monkeypatch):
    """``invalidate()`` clears every entry (the hook a successful config reload calls,
    Pattern 4) so a stale forecast is never served against a freshly reloaded config —
    the next lookup refetches."""
    cache_mod = _cache_module()

    fetches: list = []
    monkeypatch.setattr(
        cache_mod,
        "lookup_weather",
        lambda name, *, config, **k: fetches.append(name) or object(),
        raising=False,
    )

    cfg = _cfg(_loc("home"))
    cache = _ForecastCache(settings=None, ttl_seconds=600)

    cache.lookup("home", cfg)
    cache.invalidate()
    cache.lookup("home", cfg)

    assert len(fetches) == 2  # invalidate dropped the entry → refetch


# --------------------------------------------------------------------------- #
# (5) Widened key (A5): a forecast suffix never collides with a plain weather entry.
# --------------------------------------------------------------------------- #


def test_forecast_suffix_does_not_collide_with_weather(monkeypatch):
    """A5: a forecast ``lookup`` (command/variant/flags suffix) and a plain weather
    ``lookup`` on the SAME location resolve to DISTINCT cache entries — so a
    ``!weekday-forecast home --compact +sat`` never serves a ``!weather home`` result
    (or vice versa). The widened key keeps the two surfaces' results separate."""
    cache_mod = _cache_module()

    fetches: list = []
    monkeypatch.setattr(
        cache_mod,
        "lookup_weather",
        lambda name, *, config, **k: fetches.append(name) or object(),
        raising=False,
    )

    cfg = _cfg(_loc("home"))
    cache = _ForecastCache(settings=None, ttl_seconds=600)

    # Plain weather lookup (no suffix) + a distinct forecast lookup (suffix).
    weather = cache.lookup("home", cfg)
    forecast = cache.lookup("home", cfg, "weekday-forecast|compact|+sat|-")

    # Two DISTINCT keys → two fetches → two distinct cached objects (no collision).
    assert len(fetches) == 2
    assert weather is not forecast

    # A repeat of EACH key is served from cache (no third/fourth fetch).
    assert cache.lookup("home", cfg) is weather
    assert cache.lookup("home", cfg, "weekday-forecast|compact|+sat|-") is forecast
    assert len(fetches) == 2
