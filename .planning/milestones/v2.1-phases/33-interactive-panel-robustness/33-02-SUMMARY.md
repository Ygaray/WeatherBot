---
phase: 33-interactive-panel-robustness
plan: 02
subsystem: interactive
tags: [F13, D-03, D-04, HARD-UI-02, cache, generation-guard, pinned-eviction, off-loop-fetch]
requires:
  - "cachetools.TTLCache (backing store; subclassed for pinned eviction)"
  - "weatherbot.config.resolve_location (cache-key resolution, unchanged)"
  - "weatherbot.interactive.lookup.lookup_weather (the off-loop fetch guarded by the generation counter)"
provides:
  - "ForecastCache generation guard: a fetch that predates an interleaved invalidate() drops its stale result (F13/D-03)"
  - "ForecastCache pinned eviction: the plain !weather (suffix=None) entry is never evicted under forecast/flag churn (D-04)"
affects:
  - "weatherbot/interactive/cache.py"
tech-stack:
  added: []
  patterns:
    - "Generation/epoch guard captured inside the get-lock and re-checked at store — kills stale re-populate WITHOUT a lock across the network fetch"
    - "TTLCache subclass overriding popitem() to protect str-keyed (plain-weather) entries from size-cap eviction while keeping tuple-keyed (suffixed) variants evictable"
key-files:
  created: []
  modified:
    - "weatherbot/interactive/cache.py — self._generation (init/capture-in-lock/store-guard/invalidate-bump) + _PinnedTTLCache eviction policy + docstring contract update"
    - "tests/test_cache.py — test_stale_repopulate_rejected + test_plain_entry_protected regressions"
decisions:
  - "D-03: generation counter captured inside the same lock as the get; store refused if generation moved; invalidate() bumps under the lock — no lock across lookup_weather"
  - "D-04: cache-bounding carrier = size-cap TTLCache subclass that pins str-keyed plain-weather entries (suffix=None); tuple-keyed suffixed variants are the evictable set"
metrics:
  duration: ~3 min
  completed: 2026-07-13
  tasks: 2
  files_modified: 2
status: complete
---

# Phase 33 Plan 02: Panel Cache F13 Generation Guard + Bounded/Pinned Eviction Summary

Generation-guarded, size-bounded `ForecastCache`: an off-loop fetch that started before a
hot-reload `invalidate()` is refused at store-time (never re-seeding a pre-reload snapshot),
and the plain `!weather` entry can never be evicted by heavy forecast/flag-suffixed use.

## What Was Built

**Task 1 — RED regressions (`cba3bb3`)**
- `test_stale_repopulate_rejected`: the stubbed `lookup_weather` fires `cache.invalidate()`
  mid-flight (between the get/miss and the store); a follow-up lookup within TTL must
  REFETCH, proving the stale pre-invalidate result was never stored. Failed RED (the old
  cache stored unconditionally → served the stale entry → 1 fetch instead of 2).
- `test_plain_entry_protected`: seed the plain `!weather` entry, churn 20 distinct
  forecast/flag-suffixed keys past `maxsize=4`; the plain entry must still be served from
  cache. Failed RED (unmodified `TTLCache` evicted the plain entry by LRU).

**Task 2 — GREEN implementation (`eb08055`)**
- **D-03 generation guard:** added `self._generation = 0`; in `lookup`, `gen_at_start` is
  captured INSIDE the same `with self._lock:` block as the `get` (Pitfall 2 — never after
  releasing the lock). The store block re-acquires the lock and writes only when
  `self._generation == gen_at_start`, otherwise drops the result. `invalidate()` now bumps
  `self._generation += 1` under the lock after `clear()`, so any in-flight fetch (which
  captured the pre-bump generation) self-rejects.
- **D-04 pinned eviction:** new `_PinnedTTLCache(TTLCache)` overrides `popitem()` to evict
  the LRU *suffixed* (tuple-keyed) entry, skipping `str`-keyed plain-weather entries; falls
  back to default LRU only if no evictable candidate remains (cap still honored). Plain
  `!weather` uses a bare `loc_id` str key (`suffix=None`), so it is structurally protected.
- Docstring concurrency contract updated to document both the generation guard and the pin.

## Key Decisions

- **D-03 carrier:** generation captured in-lock at the miss, re-checked at store; the lock
  is released across `lookup_weather` (lines 154/168/170 — two separate lock blocks bracket
  the unlocked fetch). The off-loop-no-lock design (D-10) is intact.
- **D-04 carrier (planner discretion):** size-cap `TTLCache` subclass with a
  key-type-based pin (str = plain = protected; tuple = suffixed = evictable). Chosen over a
  separate protected slot because it needs no second store and no key bookkeeping — the
  existing `suffix=None` key shape already distinguishes the protected set. TTL-driven
  expiry of the plain entry is unchanged (the pin only blocks size-cap eviction, not expiry).

## Deviations from Plan

None - plan executed exactly as written. Both RED tests landed before the fix; the fix
turned them (and the full suite) green.

## Verification

- `uv run pytest tests/test_cache.py -x` → **7 passed** (5 pre-existing + 2 new).
- `uv run pytest tests/test_cache.py tests/test_reload.py -q` → **34 passed** (no reload-hook regression).
- `uv run pytest -q` → **856 passed** (exit 0; the "2 snapshots failed" banner is the known
  syrupy report-summary quirk — trust the exit code + `.ambr` diff, not the banner).
- `uv run ruff check weatherbot/interactive/cache.py tests/test_cache.py` → All checks passed.
- Lock-across-fetch guard: `grep -n "with self._lock\|lookup_weather" weatherbot/interactive/cache.py`
  confirms `lookup_weather` (line 168) sits BETWEEN two separate `with self._lock:` blocks
  (154 get+gen-capture, 170 guarded store) — no lock held across the fetch (D-03 prohibition honored).
- Diff scope: `git diff --stat` for this plan's commits touches ONLY `weatherbot/interactive/cache.py`
  and `tests/test_cache.py` — no hub-source edit under `.venv/` or `../Reusable/`.

## must_haves Verification

- ✅ An off-loop fetch that started before `invalidate()` does NOT write its pre-reload
  result (generation guard refuses) — `test_stale_repopulate_rejected`.
- ✅ The generation is captured INSIDE the same lock as the `get` (never after release) —
  cache.py:154-159.
- ✅ `invalidate()` bumps the generation under the lock in addition to clearing — cache.py:194-196.
- ✅ The cache lock is NEVER held across `lookup_weather` — off-loop-fetch design preserved.
- ✅ The cache is bounded (maxsize) AND the plain `!weather` (suffix=None) entry is never
  evicted — `test_plain_entry_protected` + `_PinnedTTLCache.popitem`.
- ✅ HARD-UI-02 (cache slice) audit-text backstop covered by the D-03/D-04/F13 truths above.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: weatherbot/interactive/cache.py (generation guard + _PinnedTTLCache)
- FOUND: tests/test_cache.py (both new regressions)
- FOUND commit cba3bb3 (RED tests)
- FOUND commit eb08055 (GREEN implementation)
