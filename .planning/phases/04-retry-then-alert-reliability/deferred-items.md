# Phase 04 Deferred Items

- [Plan 04-02 / out-of-scope] `tests/test_reliability.py::test_retry_after_capped` is timing-sensitive: intermittently asserts ~121.96s against the 120s Retry-After cap when the full suite runs (passes in isolation and on re-run). Belongs to Plan 04-01 (`weatherbot/reliability/`), not 04-02 files. Not fixed (scope boundary). Suggest a frozen/injected clock for the HTTP-date parse path.
