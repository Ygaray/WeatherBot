# Deferred Items — Phase 11

Out-of-scope discoveries logged during execution (NOT fixed in the discovering plan).

## From Plan 11-03

- **`tests/test_reload.py::test_cfg07_success_posts_summary` and `::test_cfg07_rejection_posts_reason` fail (pre-existing).**
  - Confirmed RED before 11-03 touched anything (reproduced with 11-03's files stashed).
  - These pin the CFG-07 reconcile-summary in-channel post on a config reload — daemon-channel wiring scoped to Plan **11-04**, not 11-03.
  - 11-03 changes (`weatherbot/interactive/cache.py`, `bot.py`, `__init__.py`) are not imported by `test_reload.py`; they do not affect these failures.
  - Action: resolve in 11-04 (CFG-07 daemon wiring).

- **`DeprecationWarning: 'audioop' is deprecated` from discord.py player module (Python 3.12).**
  - Emitted on importing `discord`; harmless, upstream discord.py issue. Not actionable in this repo.
