---
phase: 33-interactive-panel-robustness
plan: 33-07
subsystem: interactive/status
type: review-fix
status: complete
closes:
  - HR-01  # status "Last briefing" rendered UTC, not local (D-07)
  - MR-01  # _fmt_epoch non-None path had zero coverage
key-files:
  modified:
    - weatherbot/interactive/commands/status.py
    - tests/test_status.py
    - tests/test_command_views.py
    - tests/test_golden_coverage_fill.py
commits:
  - beda1cb  # test(33-07) RED regression
  - 369442d  # fix(33-07) GREEN local-time fix
completed: 2026-07-12
---

# Phase 33 Plan 07: Review-Fix — `!status` "Last briefing" local time Summary

Fixed the sole HIGH finding from `33-REVIEW.md`: `!status` "Last briefing"
rendered its timestamp in **UTC** while locked decision **D-07** mandates local
24-hour time and `_fmt_epoch`'s own docstring already claimed local. On a
non-UTC host this drove a visible, self-inconsistent card — "Next send — Home:
09:00" (correctly local, via `state.next_fires`) sitting beside "Last briefing:
13:00" (UTC) for the same 09:00-local event. Closes **HR-01** and its paired
coverage gap **MR-01** in one atomic RED→GREEN pair.

## What changed

- **RED (`beda1cb`):** `test_last_briefing_renders_local_not_utc` stamps a known
  Unix-UTC epoch (`1718874000` = 2024-06-20 09:00 UTC = 05:00 America/New_York,
  EDT) and asserts the rendered "Last briefing" line is the LOCAL `05:00`. It
  failed against the UTC code (`'09:00' == '05:00'`), proving the bug and closing
  the MR-01 coverage hole — the only prior test on this path (`test_status_stdout_golden`)
  deliberately hits the `None`/"none yet" branch, so `_fmt_epoch`'s formatting
  never ran in tests.
- **GREEN (`369442d`):** `_fmt_epoch(epoch, tz)` now localizes the Unix-UTC epoch
  into a display zone (`datetime.fromtimestamp(epoch, tz)`), dropping the
  hard-coded `timezone.utc`. `status()` resolves that zone from the first
  configured location's `timezone` (the same F02 default-resolution zone),
  falling back to UTC only when no locations are configured — mirroring exactly
  how `state.next_fires` localizes "Next send". Docstring updated so
  "already-localized clock" is now true.

## Scope discipline

`git diff --stat` touches only `weatherbot/interactive/commands/status.py` plus
the three test files (the new regression + the two direct `_fmt_epoch` unit-test
callers updated for the new `tz` argument). No `.ambr` golden was regenerated
(the status golden hits the `None` branch, unaffected). No hub-source edit
(app-side only, per cross-repo rule). The two LOW findings (LR-01 per-day
blank-line collapse footgun; LR-02 bare leading `:` on missing-`dt` day) were
**left untouched** — deferred to Phase 35 (the cleanup sweep) as instructed.

## Verification

- New regression RED against UTC code, GREEN after fix.
- `uv run pytest tests/test_status.py tests/test_golden_cli.py` → 18 passed.
- Full suite `uv run pytest` → **869 passed, exit 0** (the "2 snapshots failed"
  banner is the known syrupy report quirk — trust the exit code + `.ambr`, per
  CLAUDE.md; no golden diff).
- `uv run ruff check` on all touched files → clean.

## Deviations from Plan

**1. [Rule 3 — Blocking] Updated two existing `_fmt_epoch` unit-test callers**
- **Found during:** GREEN full-suite run.
- **Issue:** `tests/test_command_views.py::test_humanized_timestamp` and
  `tests/test_golden_coverage_fill.py::test_fmt_epoch_none_yet` call `_fmt_epoch`
  directly with the old single-argument signature → `TypeError` after the `tz`
  parameter was added.
- **Fix:** Passed an explicit `timezone.utc` at both call sites (they assert
  format shape, not zone semantics — zone semantics are now pinned by the new
  RED test), preserving their existing assertions.
- **Commit:** `369442d`.

## Self-Check: PASSED

- `weatherbot/interactive/commands/status.py` — modified (verified).
- `tests/test_status.py` — RED test present (verified: `test_last_briefing_renders_local_not_utc`).
- Commits `beda1cb`, `369442d` — present in `git log` (verified).
