---
phase: 32-timezone-date-boundary-correctness
verified: 2026-07-11T00:00:00Z
status: passed
score: 4/4 must-haves verified
behavior_unverified: 0
overrides_applied: 0
re_verification: # No previous VERIFICATION.md — initial verification
---

# Phase 32: Timezone & Date-Boundary Correctness Verification Report

**Phase Goal:** Clean up the One Call 3.0 migration residue around "which local day is today" and `daily[0]` relative to the configured IANA timezone.
**Verified:** 2026-07-11
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (the four success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A slot missed late evening and recovered just after local midnight is still caught up within grace — catch-up composes the PRIOR local day's instant (HARD-TZ-01) | ✓ VERIFIED | `catchup.py:150-201` `plan_catchup` iterates `{today-local, yesterday-local}` candidates, composes each candidate's fold=0 instant, keys `MissedSlot.local_date` on the CANDIDATE day (`cand_date.isoformat()`, line 195, NOT `now_local.date()`), per-slot `emitted_dates` dedup (line 196). Test `test_catchup_prior_local_day` PASSED. F91 fold-grace pin `test_catchup_fold_grace_not_inflated` PASSED (documented non-bug: fold=0 CronTrigger/compose agreement pinned, both-folds-min deliberately NOT implemented to avoid regressing the locked band test — evidence-backed scope resolution). |
| 2 | The UV monitor does not declare the protect window over on a single momentary sub-threshold dip while UV is still peaking; no lifecycle never-fire gap (HARD-TZ-02) | ✓ VERIFIED | `uvmonitor.py:315-330` gates all-clear on `below AND past_peak AND window_over`, where `past_peak`/`window_over` are `None`-safe (lines 321-322: `is not None and now_local >= ...`) so empty hourly degrades to don't-post (no latch, no new store table). Lifecycle coverage audited in-source (lines 227-241 branch-coverage argument). Tests `test_allclear_not_latched_on_momentary_dip` + `test_lifecycle_full_day_no_never_fire_gap` PASSED. |
| 3 | Today's high/low, rain, UV window, and forecast day-windows are computed against the configured location IANA tz — `daily[0]`/positional indexing verify the entry's own local date is today (HARD-TZ-03) | ✓ VERIFIED | `models.from_payloads:300-301` selects both imperial+metric daily via `select_today_daily(...) or {}`; `uv._today_daytime_points:128` bounds the window from `select_today_daily`; `uv.compute_uv:256` today-anchors the display-max; hourly points sorted (`uv.py:167 points.sort`). Naive `now_utc`→UTC in BOTH paths: `models` via shared helper (`local_date_for`), `uv` at lines 119-120 and 244-248 (CR-01 fix). Tests `test_daily0_not_today_degrades`, `test_naive_now_utc_treated_as_utc`, `test_compute_uv_daily0_today_guard`, `test_hourly_points_sorted_before_interpolation`, `test_today_is_daily1_still_decides`, `test_naive_now_treated_as_utc_not_host_local` all PASSED. |
| 4 | Exactly one `_local_date_iso` implementation shared by models.py, store.py (and the former uvmonitor.py copy) (HARD-TZ-04) | ✓ VERIFIED | ONE `local_date_iso` defined in `weatherbot/weather/dates.py:39`; grep confirms NO other `def _local_date_iso(` anywhere in source (only doc-comment references in dates.py/multiday.py). All three callers import the shared helper: `models.py:30`, `store.py:31`, `uvmonitor.py:38`. Test `test_import_hygiene.py` (3 tests: no-local-copies + same-output/deterministic + no-cycle) PASSED. |

**Score:** 4/4 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `weatherbot/weather/dates.py` | single tz-correct helper: `local_date_iso` + `local_date_for` + `select_today_daily` | ✓ VERIFIED | Pure, dependency-free leaf module; all three functions present and substantive; naive→UTC + defensive-degrade + WR-03 explicit-None dt check. |
| `weatherbot/scheduler/catchup.py` | candidate-day catch-up, candidate-keyed dedup | ✓ VERIFIED | `plan_catchup` both-candidate loop, fold=0 compose, GRACE gate, was_sent dedup. |
| `weatherbot/scheduler/uvmonitor.py` | hysteresis all-clear via UvSummary | ✓ VERIFIED | `below AND past_peak AND window_over`, None-degrade; imports shared `local_date_iso`+`select_today_daily`; `_daily0_matches_today` removed (WR-02). |
| `weatherbot/weather/models.py` | today-by-own-local-date daily selection | ✓ VERIFIED | `select_today_daily` for imperial+metric daily; shared `local_date_for`. |
| `weatherbot/weather/uv.py` | today-anchored window + sorted hourly + naive→UTC | ✓ VERIFIED | `select_today_daily` window bound + display-max; `points.sort`; naive→UTC both entry points (CR-01). |
| `weatherbot/weather/store.py` | shared helper for local_date key | ✓ VERIFIED | `local_date_for` at `store.py:220`; no local copy. |
| 9 named regression tests + import-hygiene | RED-first, now GREEN | ✓ VERIFIED | All named phase tests run and PASS individually; full suite 845 passed. |

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| models.py / store.py / uvmonitor.py / uv.py | weather/dates.py | `from weatherbot.weather.dates import ...` | ✓ WIRED (4 import sites confirmed) |
| catchup.plan_catchup | MissedSlot.local_date | candidate `cand_date.isoformat()` keying + dedup | ✓ WIRED |
| uvmonitor all-clear | UvSummary.peak_time/window_end | `past_peak`/`window_over` guards | ✓ WIRED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 8 core named phase tests | `uv run pytest <8 named tests>` | 8 passed | ✓ PASS |
| import-hygiene single-helper | `uv run pytest tests/test_import_hygiene.py` | 3 passed | ✓ PASS |
| extra HARD-TZ-03 guards | `test_today_is_daily1_still_decides` + `test_naive_now_treated_as_utc_not_host_local` | exist (test_uv_monitor.py / test_uv.py), in green suite | ✓ PASS |
| full suite | `uv run pytest -q` | 845 passed, exit 0 | ✓ PASS |

Note: the "2 snapshots failed" syrupy line keeps exit 0 — known pre-existing quirk (per project memory pytest-snapshot-report-quirk), not a golden diff, not a failure.

### Requirements Coverage

| Requirement | Source Plan(s) | Status | Evidence |
|-------------|----------------|--------|----------|
| HARD-TZ-01 | 32-01, 32-03 | ✓ SATISFIED | catchup candidate-day + fold pin; REQUIREMENTS.md marked Complete |
| HARD-TZ-02 | 32-01, 32-05 | ✓ SATISFIED | uvmonitor hysteresis + lifecycle; REQUIREMENTS.md Complete |
| HARD-TZ-03 | 32-01, 32-02, 32-04 | ✓ SATISFIED | today-by-own-local-date across models/uv; REQUIREMENTS.md Complete |
| HARD-TZ-04 | 32-01, 32-02, 32-05 | ✓ SATISFIED | single dates.py helper; REQUIREMENTS.md Complete |

All four requirement IDs from every PLAN frontmatter (`[HARD-TZ-01..04]` in 32-01; subsets in 32-02..05) are accounted for and present in REQUIREMENTS.md. No orphaned requirements.

### Anti-Patterns Found

None. No TODO/FIXME/XXX/TBD/HACK/stub markers in any phase-modified source file. (The `placeholders()` matches in models.py are the legitimate template-renderer method name, not a debt marker.) Code-review gate (32-REVIEW.md) findings CR-01/WR-01/WR-02/WR-03 all resolved test-first (status: resolved, commits 4d9a088/44edb5c/6208155).

### Human Verification Required

None. All four success criteria are behavior-verified by named passing regression tests (test-first phase). No runtime-behavior gaps require human observation.

### Gaps Summary

No gaps. The phase goal is achieved: "which local day is today" is now computed against the configured IANA timezone through one shared `dates.py` helper; catch-up composes the prior local day across midnight; the UV all-clear has hysteresis with no never-fire gap; and daily/hourly indexing verifies each entry's own local date. The F91 both-folds-min was deliberately not implemented — this is an evidence-backed non-bug resolution (live CronTrigger fires fold=0, catch-up composes fold=0, they agree) protected by the `test_catchup_fold_grace_not_inflated` pin, NOT an unmet must_have.

---

_Verified: 2026-07-11_
_Verifier: Claude (gsd-verifier)_
