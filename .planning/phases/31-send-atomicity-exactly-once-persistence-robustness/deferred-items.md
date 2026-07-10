# Deferred Items — Phase 31

Out-of-scope discoveries found during execution (not fixed; logged per SCOPE BOUNDARY).

## Plan 31-01: pre-existing ruff errors (out of scope)

Discovered during the full-suite ruff gate for 31-01; these files were NOT touched
by this plan (store hardening only). Not fixed — logged for a future cleanup pass:

- `tests/test_golden_cli.py:33` — ruff finding (pre-existing)
- `tests/test_reload.py:626` — ruff finding (pre-existing)
- `weatherbot/scheduler/daemon.py:69,71` — ruff findings (pre-existing)
- `weatherbot/scheduler/daemon.py:1418` — unused variable `notifier` (pre-existing)

The full pytest suite is green (815 passed, exit 0); these are lint-only.
