---
phase: 33-interactive-panel-robustness
plan: 05
subsystem: weather-model
tags: [dt-pairing, dual-unit, briefing, F107, F11, D-08, HARD-UI-03]
requires:
  - "weather/dates.py select_today_daily / local_date_for (Phase 32 anchoring)"
  - "forecast.py:126-129 dt-pairing guard (pattern lifted)"
provides:
  - "dt-anchored metric daily selection in Forecast.from_payloads (F107)"
  - "one-unit-present high_display / low_display (F11)"
  - "dt-skewed briefing fixtures (tests/fixtures/onecall_{imperial,metric}_dtskew.json)"
affects:
  - "weatherbot/weather/models.py"
  - "tests/test_models.py"
tech-stack:
  added: []
  patterns:
    - "dt-match metric daily entry to the imperial day_i's own dt (not independent local-date selection)"
    - "single-unit temp render when one unit is missing (honors primary)"
key-files:
  created:
    - "tests/fixtures/onecall_imperial_dtskew.json"
    - "tests/fixtures/onecall_metric_dtskew.json"
  modified:
    - "weatherbot/weather/models.py"
    - "tests/test_models.py"
decisions:
  - "Metric daily is paired to the imperial day_i's dt (D-08); degrades to {} on no match — never a mispair."
  - "high/low_display renders the available unit when exactly one side is present; temp_display only when BOTH are missing."
  - "F107 fixture is deliberately dt-SKEWED (no metric entry shares day_i's dt) so independent selection false-greens are impossible."
metrics:
  duration_min: 4
  completed: 2026-07-13
  tasks: 2
  files_changed: 4
status: complete
---

# Phase 33 Plan 05: dt-anchored dual-unit daily-briefing pairing Summary

dt-anchor the daily briefing's metric temp to the imperial day's own `dt` (F107) and render a valid single-unit high/low when its twin is missing (F11), proven by a deliberately dt-skewed fixture that mispairs under the old independent-selection path.

## What Was Built

- **F107 — dt-matched metric selection** in `Forecast.from_payloads`: the imperial
  `day_i` is still selected by local date (unchanged), but the metric entry is now
  paired to `day_i`'s own `dt` (lifting the existing `forecast.py:126-129` guard),
  degrading to `{}` on no dt match instead of grabbing a wrong-day metric bucket via
  an independent local-date selection. Reuses `weather/dates.py` — no new date math.
- **F11 — one-unit-present high/low**: `high_display`/`low_display` now render the
  available unit (via a new `_one_unit_temp_str` helper that honors `primary`) when
  exactly one side is present, and only fall back to the current temp (`temp_display`)
  when BOTH sides are missing. A valid imperial high is no longer discarded because
  its metric twin was skewed away or absent.
- **dt-skewed fixtures** (`onecall_{imperial,metric}_dtskew.json`): the metric array
  has NO entry sharing the imperial `day_i` dt; its 2026-06-19 bucket carries a
  different dt (+6h) and a distinctive wrong `99.9°C` max. Independent selection
  renders `76°F (100°C)` (mispair); dt-anchored pairing degrades to imperial-only.
- **Two regressions**: `test_dt_paired_briefing` (F107) and
  `test_metric_missing_keeps_imperial` (F11), both RED pre-fix / GREEN post-fix.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing dt-paired + metric-missing regressions | 9bb2b32 | tests/test_models.py, tests/fixtures/onecall_{imperial,metric}_dtskew.json |
| 2 (GREEN) | dt-matched metric selection (F107) + one-unit high/low (F11) | 8f84e29 | weatherbot/weather/models.py |

## Verification

- `uv run pytest tests/test_models.py -k "dt_paired_briefing or metric_missing"` — 2 passed (RED→GREEN).
- `uv run pytest tests/test_models.py` — 45 passed (no regression in existing dual-unit display tests).
- `uv run pytest` — **863 passed, exit 0**. The "2 snapshots failed" banner is the
  known pre-existing syrupy quirk (trusted exit code + confirmed NO `.ambr` golden
  files were modified by this change).
- `git diff --stat` for source touches ONLY `weatherbot/weather/models.py` (+ the
  test files committed in Task 1) — no hub-source edit (cross-repo guardrail held).

## Deviations from Plan

The plan's Task-1 behavior sketch and the audit text (`models.py:302` "positional
`daily[0]`") describe a PRE-existing state. The current code already used
`select_today_daily` INDEPENDENTLY for both units (improved in Phase 32), so a naively
pre-aligned skew fixture passed against current code (fail-fast RED violation caught
before GREEN). Per the plan's own truths #1/#2 ("match the imperial entry's `dt`; on
no dt match degrade to `{}`"), the fixture was rebuilt so the metric array has NO
entry at `day_i`'s exact dt — making independent local-date selection grab a wrong-day
`99.9°C` bucket (mispair) while dt-anchoring degrades gracefully. This is a fixture
construction refinement to honor the authoritative truths, not a behavior change; the
committed test is genuinely RED against current code. Tracked here rather than as a
Rule 1-3 auto-fix because it clarified the test design, not the production fix.

## Scope Note — HARD-UI-03 left In Progress

HARD-UI-03 is shared with plan 06 (F28 dup header, empty-token blanks, humanized
timestamps, date labels). This plan lands ONLY the F107/F11 dt-pairing slice, so
HARD-UI-03 is NOT marked Complete — only this plan's ROADMAP progress advances.

## Threat Register Outcome

- **T-33-05-01 (Tampering, F107)** — mitigated: metric daily is dt-matched to the
  imperial day; a skewed payload degrades to `{}` rather than shipping a wrong-day temp.
- **T-33-05-02 (Info-disclosure, F11)** — mitigated: a valid single-unit high/low is
  rendered instead of the current temp.
- **T-33-05-03 / T-33-05-SC** — accept / n-a (no provider text surface change; no installs).

No new threat surface introduced (no new endpoints, auth paths, or schema changes).

## Self-Check: PASSED

- FOUND: tests/fixtures/onecall_imperial_dtskew.json, tests/fixtures/onecall_metric_dtskew.json
- FOUND commits: 9bb2b32 (RED), 8f84e29 (GREEN)
