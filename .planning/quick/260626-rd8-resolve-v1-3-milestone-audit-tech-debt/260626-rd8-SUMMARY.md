---
phase: quick-260626-rd8
plan: 01
subsystem: interactive
tags: [tech-debt, milestone-audit, ruff, test-hygiene, frontmatter, v1.3]
status: complete
requires:
  - .planning/v1.3-MILESTONE-AUDIT.md (the 5 non-blocking cleanup items)
  - weatherbot/interactive/dispatch.py (dispatch_spec — WR-01 test target, WR-02 verify)
  - tests/test_dispatch.py (existing _SpyCache/_FakeSpec fakes reused for WR-01)
  - tests/test_scheduler.py (WR-03 hanging-callback isolation test)
provides:
  - requirements-completed frontmatter on 16-01, 20-02, 20-03 SUMMARYs (PANEL-10/12/13)
  - clean ruff check + ruff format --check across weatherbot + tests
  - WR-01 dispatch_spec text-command forecast unit test (flags=None parse path)
  - self-cleaning WR-03 hanging-callback test (no dangling daemon thread)
affects:
  - v1.3 milestone close (audit tech-debt cleared)
tech-stack:
  added: []
  patterns:
    - "Cross-thread wedge release: capture the wedge's loop + asyncio.Event, signal via loop.call_soon_threadsafe(event.set) in a finally, then join the thread"
    - "ruff format reflow is non-behavioral: argument-per-line expansion, comment-spacing, set-literal wrapping — token semantics unchanged"
key-files:
  created:
    - .planning/quick/260626-rd8-resolve-v1-3-milestone-audit-tech-debt/260626-rd8-SUMMARY.md
  modified:
    - .planning/phases/16-extract-shared-dispatch-spec/16-01-SUMMARY.md
    - .planning/phases/20-isolation-hardening-polish/20-02-SUMMARY.md
    - .planning/phases/20-isolation-hardening-polish/20-03-SUMMARY.md
    - tests/test_dispatch.py
    - tests/test_scheduler.py
    - "tests/test_cache.py, tests/test_reload.py (F401 removals)"
    - "~30 weatherbot/ + tests/ files (ruff format whitespace only)"
decisions:
  - "WR-02 was verify-only: the off-loop divergence comment was already present in dispatch.py (2 mentions, lines 130 + 172) — NO edit made, dispatch.py stays byte-identical to its committed state (no ruff-format change either)"
  - "WR-01 test uses a distinct location+token (travel +sun) vs the existing forecast tests (home +sat) to prove the lookup name is derived from the PARSED flags.location, not the raw arg verbatim"
  - "WR-03 cleanup releases the wedge deterministically via loop.call_soon_threadsafe in the finally (not a timeout-only join) so the thread actually terminates and the test asserts not is_alive()"
  - "ruff check --fix removed 4 F401 unused imports — all in test files (pytest in test_cache; datetime, BackgroundScheduler, ConfigHolder in test_reload); zero production code touched"
requirements-completed: [PANEL-10, PANEL-12, PANEL-13]
metrics:
  duration: ~4m
  tasks: 2
  files-created: 1
  files-modified: 5 (+ ruff-format-only whitespace across ~30 files)
  completed: 2026-06-27
---

# Quick Task 260626-rd8: Resolve v1.3 Milestone-Audit Tech Debt Summary

Cleared all five non-blocking tech-debt items from `.planning/v1.3-MILESTONE-AUDIT.md`
so the v1.3 "Discord Control Panel" milestone closes clean — doc-only frontmatter backfill,
a repo-wide ruff format/lint sweep, one new isolated `dispatch_spec` unit test, a verify-only
WR-02 comment check, and a WR-03 test-hygiene cleanup — with ZERO production behavior change.

## What Was Built

### Task 1 — SUMMARY frontmatter backfill + ruff sweep (commit `686e959`)

- **Frontmatter backfill (audit item #1):** added a `requirements-completed:` line (18-01
  style — hyphenated key, inline bracket-list, standalone line after the last `decisions:`
  block and before `metrics:`) to three SUMMARY frontmatter blocks:
  - `16-01-SUMMARY.md` → `requirements-completed: [PANEL-10]`
  - `20-02-SUMMARY.md` → `requirements-completed: [PANEL-12, PANEL-13]`
  - `20-03-SUMMARY.md` → `requirements-completed: [PANEL-12, PANEL-13]`
- **Ruff sweep (audit item #2):** the audit's named lines were stale; absorbed the current
  tree's actual drift:
  - `ruff check --fix` removed **4 F401 unused imports** (all in test files: `pytest` in
    `tests/test_cache.py`; `datetime`, `BackgroundScheduler`, `ConfigHolder` in
    `tests/test_reload.py`) — no production code touched.
  - `ruff format` reformatted ~30 files (whitespace/reflow only — argument-per-line
    expansion, comment-spacing normalization, set-literal wrapping; no logic change).

### Task 2 — WR-01 test + WR-02 verify + WR-03 cleanup (commit `3c89508`)

- **WR-01:** added `test_dispatch_spec_text_forecast_parses_flags_and_widens_suffix` to
  `tests/test_dispatch.py` (reusing the existing `_SpyCache`/`_FakeSpec`/`_recording_handler`
  fakes — no new fixtures). It drives a `Forecast`-group spec through
  `dispatch_spec(spec, "travel +sun", …)` with NO `flags=` kwarg so the text-command parse
  path runs, then asserts: (1) exactly one 3-arg `cache.lookup`; (2) `name == "travel"`
  (derived from the parsed `flags.location`, not the raw arg); (3) a non-None cache suffix;
  (4) the handler received the fetched result + a parsed `ForecastFlags` with
  `.location == "travel"` and `.add == {"sun"}`. This pins the drift-prone text-command
  lookup-name + cache-suffix derivation at the unit level (previously only transitively
  covered via test_bot.py).
- **WR-02:** VERIFY-ONLY. Confirmed the off-loop divergence comment is already present in
  `weatherbot/interactive/dispatch.py` (2 `WR-02` mentions — the docstring "Off-loop scope"
  block at line 130 and the inline run_in_executor-tail comment at line 172). NO edit made;
  `dispatch.py` stays byte-identical to its committed state.
- **WR-03:** made `test_hanging_callback_never_stops_live_briefing` self-cleaning. The wedge
  coroutine now creates its own `asyncio.Event`, captures its running loop + the Event into
  a handoff dict, and awaits `release.wait()`. After the isolation assertions (sentinel
  briefing fired + scheduler running while the callback is provably wedged), a `finally`
  block shuts the scheduler down, releases the wedge via
  `loop.call_soon_threadsafe(release.set)`, `wedge_thread.join(timeout=5.0)`, and asserts the
  thread is no longer alive. The isolation proof (`callback_entered.wait` + sentinel +
  `scheduler.running`) is fully preserved — only the dangling-thread leak is fixed.

## Verification

- `uv run ruff check weatherbot tests` → **All checks passed!** (0 errors)
- `uv run ruff format --check weatherbot tests` → **79 files already formatted** (0 would-reformat)
- `uv run pytest -q` → **650 passed** (baseline 649 + 1 new WR-01 test), 1 warning (pre-existing
  `audioop` deprecation from the discord library — unrelated)
- Both new tests pass individually:
  `test_dispatch_spec_text_forecast_parses_flags_and_widens_suffix` and
  `test_hanging_callback_never_stops_live_briefing` → 2 passed
- WR-02: `grep -c 'WR-02' weatherbot/interactive/dispatch.py` → 2 (comment present)
- `weatherbot/` carries only whitespace/formatting changes (ruff format) — no logic diff;
  `dispatch.py` unmodified

## INVARIANT Compliance

ZERO production behavior change. The only `weatherbot/` edits were `ruff format`
whitespace/reflow on existing lines (no comment added — WR-02's comment was already present).
All non-format edits were test files + planning-doc frontmatter.

## Deviations from Plan

None — plan executed exactly as written. The planning expectations held precisely: exactly
4 F401 errors (all auto-fixed, all in test files), the WR-02 comment was already present
(verify-only, no edit), and `ruff format` proposed only whitespace/reflow changes.

## Self-Check: PASSED

- FOUND: `.planning/phases/16-extract-shared-dispatch-spec/16-01-SUMMARY.md` → `requirements-completed: [PANEL-10]`
- FOUND: `.planning/phases/20-isolation-hardening-polish/20-02-SUMMARY.md` → `requirements-completed: [PANEL-12, PANEL-13]`
- FOUND: `.planning/phases/20-isolation-hardening-polish/20-03-SUMMARY.md` → `requirements-completed: [PANEL-12, PANEL-13]`
- FOUND: commit `686e959` (Task 1)
- FOUND: commit `3c89508` (Task 2)
- FOUND: new test `test_dispatch_spec_text_forecast_parses_flags_and_widens_suffix` (passes)
- VERIFIED: ruff check + format --check clean; full suite 650 passed
