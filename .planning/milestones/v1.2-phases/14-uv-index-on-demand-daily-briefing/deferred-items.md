# Deferred Items — Phase 14

## Plan 14-04 (out-of-scope, pre-existing)

- `tests/test_cache.py:21` — unused import flagged by ruff (`F401`). Pre-existing; not touched by 14-04.
- `tests/test_reload.py:30,35,38` — unused import(s) flagged by ruff (incl. `ConfigHolder`). Pre-existing; not touched by 14-04.

These are pre-existing lint warnings in files unrelated to the uv command; left untouched per the executor scope boundary.
