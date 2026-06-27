# Phase 18 — Deferred / Out-of-Scope Items

Discovered during execution; NOT fixed (out of scope per the scope boundary rule).

## Pre-existing ruff-format drift (not introduced this phase)

`ruff format --check` flags several files with pre-existing formatting drift on
lines this phase did NOT touch (the installed ruff is newer than when those lines
were written, so it now collapses multi-line calls that were previously accepted):

- `weatherbot/config/models.py:149` — `ForecastSchedule` variant-error f-string (Phase 13 code).
- `tests/test_models.py` — `_build()` signature + `test_hints_*` calls (Phase 14 code).
- `tests/test_config.py:616` — `ForecastSchedule(...)` call (Phase 13 code).
- `tests/test_scheduler.py` — pre-existing call wrapping.

My Plan 18-01 additions (`panel_channel_id` field + new tests) ARE ruff-format-clean.
Reformatting the unrelated pre-existing lines would balloon the diff and touch code
outside this plan's scope, so it is deferred. A standalone `ruff format` sweep across
the repo (its own quick task) is the right place to absorb this drift.

## Pre-existing ruff lint F841 (not introduced this phase)

`ruff check tests/test_panel.py` flags `F841 Local variable 'view' is assigned to but
never used` at `tests/test_panel.py:194` — inside `test_dropdown_rederives_on_hot_reload`,
a Phase-17 test. Verified present at commit `dcd5092` (HEAD before Task 3), so it is
pre-existing, not introduced by Plan 18-01. My Task-3 additions (`_is_owned_panel`
tests + conftest fakes) are lint-clean. Left untouched per the scope boundary; fold
into the same repo-wide ruff sweep above.
