# Deferred Items — Phase 13

- `tests/test_cache.py:21` — pre-existing unused `import pytest` (ruff F401). Predates
  Plan 13-04; out of scope for this plan's task (not caused by the forecast changes).
  Trivial one-line removal whenever test_cache.py is next touched for its own reasons.
