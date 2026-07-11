---
phase: 32-timezone-date-boundary-correctness
plan: 05
subsystem: scheduler
tags: [timezone, uv-monitor, D-03, D-04, D-08, F15, hysteresis, tdd-green]
status: complete
requires:
  - "32-01 RED tests (test_allclear_not_latched_on_momentary_dip, test_lifecycle_full_day_no_never_fire_gap, import-hygiene no-local-copy)"
  - "32-02 weatherbot.weather.dates.local_date_iso(now_utc, tz) — the shared local-date primitive"
provides:
  - "uvmonitor all-clear window-end hysteresis gate (D-03/F15) — no latch on a momentary sub-threshold dip"
  - "uvmonitor _decide D-04 reachability invariant (documented, no code gap found)"
  - "uvmonitor unified onto weatherbot.weather.dates.local_date_iso (D-08) — the THIRD and final _local_date_iso copy deleted"
affects:
  - "Closes phase 32 (final plan): all nine 32-01 RED tests now GREEN; full suite fully green"
  - "HARD-TZ-02 (F15 all-clear latch) + HARD-TZ-04 (F69 third helper copy) requirements satisfied"
tech-stack:
  added: []
  patterns:
    - "Stateless prediction-anchored hysteresis: gate the durable once-per-day all-clear on the day's PREDICTED window-end/peak from the same UvSummary compute_uv already returns — no new store table (F36/F37 stay deferred)"
    - "Fail-safe degrade: None peak_time/window_end (empty/missing hourly[]) => don't-post-yet, never a premature latch, never a raise"
    - "Reachability-invariant audit documented inline (D-04) — no speculative code added when the state machine already covers the day"
key-files:
  created: []
  modified:
    - "weatherbot/scheduler/uvmonitor.py — (1) deleted local `def _local_date_iso` (:84-90), added `from weatherbot.weather.dates import local_date_iso`, swapped the tick call site to `local_date_iso(now_utc, tz)` (D-08); (2) replaced branch-3 all-clear latch with a `below AND past_peak AND window_over` hysteresis gate reusing UvSummary.peak_time/window_end (D-03/F15), degrading to don't-post on None window facts; (3) added a `# D-04 REACHABILITY INVARIANT` comment to `_decide` documenting the audit verdict. `_daily0_matches_today` (WR-05 guard) kept unchanged."
decisions:
  - "D-03/F15: all-clear gates on below AND past_peak (now_local >= summary.peak_time) AND window_over (now_local >= summary.window_end), not a bare instantaneous current<threshold — a passing-cloud dip at solar noon cannot burn the durable once-per-day allclear slot"
  - "D-03 degrade: None peak_time/window_end (empty hourly[]) => past_peak/window_over both False => all-clear deferred; NO new persistence table / uv_alerts kind added (F36/F37 stay out of scope)"
  - "D-04: audit found NO never-fire gap — branch 3 keys on `crossing` (not `prewarn`), so the WR-02 moot-prewarn suppression can never orphan/block a legitimate later all-clear; documented as an inline invariant, no code fix needed"
  - "D-08: uvmonitor now uses the ONE shared local_date_iso helper; the third _local_date_iso copy is deleted — all three (models/store/uvmonitor) now unified (HARD-TZ-04)"
metrics:
  duration_minutes: 6
  completed: 2026-07-11
  tasks_completed: 2
  files_created: 0
  files_modified: 1
---

# Phase 32 Plan 05: UV All-Clear Hysteresis + Lifecycle Audit + Third-Copy Unification Summary

Anchored the intraday UV monitor's all-clear to the day's PREDICTED window-end (reusing
`UvSummary.peak_time`/`window_end`) so a momentary solar-noon dip can no longer latch "protect
window over" (F15), documented the `_decide` lifecycle reachability invariant (D-04, no gap
found), and deleted the third `_local_date_iso` copy in favor of the shared
`weatherbot.weather.dates.local_date_iso` (D-08/HARD-TZ-04) — the last plan of phase 32.

## What Was Built

**Task 1 — All-clear window-end hysteresis (D-03/F15) + D-08 helper swap** (`e5309af`):
- Branch 3 previously latched all-clear on a bare instantaneous `summary.current < threshold`
  (uvmonitor.py:318). One passing cloud at solar noon (UV 5.8 vs threshold 6.0) — with a
  `crossing` already claimed and the forecast still peaking — durably claimed `allclear` and
  posted "protect window over", and the window could never re-open for the day.
- Replaced it with `below AND "crossing" in prior AND "allclear" not in prior AND window_over
  AND past_peak`, where `past_peak = summary.peak_time is not None and now_local >=
  summary.peak_time` and `window_over = summary.window_end is not None and now_local >=
  summary.window_end`. Both facts come from the SAME `UvSummary` `compute_uv` already returns —
  no second interpolation, no new store state.
- Empty/missing `hourly[]` => `peak_time`/`window_end` are `None` => both guards False =>
  all-clear deferred (don't-post-yet). No new persistence table / `uv_alerts` kind (F36/F37
  stay deferred).
- Deleted the local `def _local_date_iso` (:84-90), added `from weatherbot.weather.dates import
  local_date_iso`, and swapped the tick call site (:157) to `local_date_iso(now_utc, tz)`. The
  `_daily0_matches_today` WR-05 guard is kept unchanged.

**Task 2 — Lifecycle no-never-fire-gap audit (D-04)** (`7a0b5ae`):
- Enumerated the `_decide` branch state machine; found NO never-fire gap. Added an inline
  `# D-04 REACHABILITY INVARIANT` comment recording the verdict. No speculative code added.

## D-04 Reachability Enumeration (audit verdict: NO GAP)

State space = (in_daylight ∈ {T,F}) × (current vs threshold ∈ {≥T, <T}) × (prior ⊆ {prewarn, crossing, allclear}).

| in_daylight | current | prior (relevant) | Fires | Reachable next / verdict |
|-------------|---------|------------------|-------|--------------------------|
| T | ≥T | crossing∉ | Branch 1 (crossing; first-poll also suppresses moot prewarn) | claims `crossing` |
| T | ≥T | crossing∈ | none | terminal — nothing left to do (correct) |
| T | <T | prewarn∉, crossing∉, near | Branch 2 (pre-warn) | claims `prewarn` |
| T | <T | prewarn∉, crossing∉, not-near | none | pre-warn correctly not yet due; later tick re-evaluates |
| T | <T | crossing∈, allclear∉, window_over∧past_peak | Branch 3 (all-clear) | claims `allclear` |
| T | <T | crossing∈, allclear∉, mid-window | none | all-clear correctly deferred (D-03); later tick re-evaluates |
| F | <T | crossing∈, allclear∉, window_over∧past_peak | Branch 3 (all-clear; WR-01 not daylight-gated) | closes the day at/after sunset |
| F | any | crossing∉ | none | pre-daylight/post-sunset with nothing to close — early-returned before `_decide` (WR-01) |
| any | <T | allclear∈ | none | day fully closed (correct) |

**Key invariant:** Branch 3 keys on `"crossing" in prior`, NOT `"prewarn" in prior`. The WR-02
ordering (claim `crossing` before the moot-`prewarn` suppression) only suppresses the pre-warn
POST — it never sets a state that blocks a legitimate later crossing (branch 1 already fired to
reach it) or all-clear (branch 3 ignores `prewarn`). Every "none fires" state above is a terminal
state that SHOULD not fire. No orphaning, no never-fire gap.

## Tests Turned GREEN (owned by this plan — the last 3 failures in the suite)

- `tests/test_uv_monitor.py::test_allclear_not_latched_on_momentary_dip` (D-03/F15) — a 5.8<6.0
  solar-noon dip (and the threshold-epsilon 5.99 edge) at 12:00, before peak 13:00 / window_end
  15:20, posts NOTHING and claims no `allclear`.
- `tests/test_uv_monitor.py::test_lifecycle_full_day_no_never_fire_gap` (D-04) — the full-day
  walk (10:00 pre-warn → 11:00 crossing → 12:00 mid-window dip NO all-clear → 16:00 genuine
  all-clear) posts prewarn/crossing/allclear exactly once each; the empty-hourly edge degrades
  without raising or latching.
- `tests/test_import_hygiene.py::test_dates_single_helper_no_local_copies` (HARD-TZ-04/F69) —
  uvmonitor no longer defines its own `_local_date_iso` and imports `weatherbot.weather.dates`;
  all three copies (models/store/uvmonitor) are now unified.

## Verification

- `uv run pytest tests/test_uv_monitor.py -q` → 36 passed (both newly-GREEN tests + all existing
  crossing/pre-warn/all-clear behavior unregressed).
- Grep gates: `grep -c "def _local_date_iso" weatherbot/scheduler/uvmonitor.py` == 0;
  `from weatherbot.weather.dates import local_date_iso` present; branch 3 uses
  `window_over`/`past_peak` computed from `summary.window_end`/`summary.peak_time`; no new store
  table / `uv_alerts` kind introduced.
- `uv run pytest -q` → **843 passed, exit 0**. The only non-pass line is the known pre-existing
  syrupy "2 snapshots failed. 27 snapshots passed." report summary, which keeps exit 0 (documented
  project quirk — trust the exit code + `.ambr` diff, not the syrupy report line). No pre-existing
  regression. `claim_uv_alert` exactly-once gating and the WR-01 post-sunset all-clear behavior
  are preserved.

## Deviations from Plan

None — plan executed exactly as written. The D-04 audit found no code gap (the anticipated
common case), so Task 2 added only the documented `# D-04` reachability invariant, exactly as the
plan's `<action>` prescribed ("If the audit finds NO gap ... add a `# D-04` comment ... do NOT add
speculative code").

## Known Stubs

None. No hardcoded empty/placeholder values, no unwired data sources introduced. The empty-hourly
"don't-post-yet" degrade is an intentional fail-safe (D-03), not a stub — it is exercised by the
lifecycle test's empty-hourly edge.

## Threat Register Outcome

| Threat ID | Disposition | Outcome |
|-----------|-------------|---------|
| T-32-12 (all-clear latch on momentary dip, F15) | mitigate | Done — all-clear gates on `window_over AND past_peak`; pinned by `test_allclear_not_latched_on_momentary_dip`. |
| T-32-13 (never-fire lifecycle gap, D-04) | mitigate | Done — state machine enumerated; full-day tick test proves each kind reachable exactly once. |
| T-32-14 (empty/malformed hourly → premature latch) | mitigate | Done — None window facts degrade to don't-post-yet (no raise, no new table). |
| T-32-SC (npm/pip/cargo installs) | accept | No package installs performed. |

## Self-Check: PASSED

- `weatherbot/scheduler/uvmonitor.py` modified — FOUND (git shows the two commits touching it).
- Commit `e5309af` (Task 1) — FOUND in git log.
- Commit `7a0b5ae` (Task 2) — FOUND in git log.
- `.planning/phases/32-timezone-date-boundary-correctness/32-05-SUMMARY.md` — FOUND (this file).
