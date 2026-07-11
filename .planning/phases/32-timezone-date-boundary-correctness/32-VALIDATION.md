---
phase: 32
slug: timezone-date-boundary-correctness
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-11
---

# Phase 32 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from 32-RESEARCH.md §Validation Architecture. All Phase 32 fixes land **test-shaped**
> (failing-first regression per CONFIRMED scenario); the comprehensive backfill is Phase 34.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (installed via uv) |
| **Config file** | `pyproject.toml` (pytest config) · `tests/conftest.py` (fixtures: `tmp_db`, `load_fixture`) |
| **Quick run command** | `uv run pytest tests/test_scheduler.py tests/test_uv_monitor.py tests/test_models.py tests/test_uv.py -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~15–30 seconds (quick) · full suite < ~2 min |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_scheduler.py tests/test_uv_monitor.py tests/test_models.py tests/test_uv.py -x -q`
- **After every plan wave:** Run `uv run pytest -q` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

Wave 0 authors these failing-first; the fix task in the later wave turns each green. `File Exists: ❌ W0` = the test is new and created in Wave 0.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| tz-catchup-priorday | catchup | — | HARD-TZ-01 (F14) | — | 23:45 slot recovered at 00:15 next local day → exactly ONE MissedSlot keyed on YESTERDAY | unit | `uv run pytest tests/test_scheduler.py::test_catchup_prior_local_day -x` | ❌ W0 | ⬜ pending |
| tz-catchup-fold | catchup | — | HARD-TZ-01/F91 | — | fall-back 01:30 slot minutes-late inside repeated hour → still due (grace not inflated), agrees with CronTrigger fold=0 | unit | `uv run pytest tests/test_scheduler.py::test_catchup_fold_grace_not_inflated -x` | ❌ W0 | ⬜ pending |
| tz-uv-allclear | uvmonitor | — | HARD-TZ-02 (F15) | — | momentary UV dip at solar noon (5.8<6.0) then climb back → all-clear NOT posted | unit | `uv run pytest tests/test_uv_monitor.py::test_allclear_not_latched_on_momentary_dip -x` | ❌ W0 | ⬜ pending |
| tz-uv-lifecycle | uvmonitor | — | HARD-TZ-02/D-04 | — | full-day tick sequence → prewarn/crossing/all-clear each post exactly once, no never-fire state | unit | `uv run pytest tests/test_uv_monitor.py::test_lifecycle_full_day_no_never_fire_gap -x` | ❌ W0 | ⬜ pending |
| tz-daily0-degrade | models | — | HARD-TZ-03 (F35/F109) | — | payload whose `daily[0]` is dated YESTERDAY → briefing degrades (no yesterday numbers as today) | unit | `uv run pytest tests/test_models.py::test_daily0_not_today_degrades -x` | ❌ W0 | ⬜ pending |
| tz-uv-daily0 | uv | — | HARD-TZ-03/F31 | — | `compute_uv` with `daily[0]`=yesterday → does not falsely report stays_below for a real today crossing | unit | `uv run pytest tests/test_uv.py::test_compute_uv_daily0_today_guard -x` | ❌ W0 | ⬜ pending |
| tz-hourly-sort | uv | — | HARD-TZ-03/F32 | — | out-of-order hourly buckets → crossing/window computed on time-sorted points | unit | `uv run pytest tests/test_uv.py::test_hourly_points_sorted_before_interpolation -x` | ❌ W0 | ⬜ pending |
| tz-naive-now | models | — | HARD-TZ-03/F33 | — | naive `now_utc` near midnight → local_date not shifted a day (treated as UTC) | unit | `uv run pytest tests/test_models.py::test_naive_now_utc_treated_as_utc -x` | ❌ W0 | ⬜ pending |
| tz-unify-dates | dates | — | HARD-TZ-04 (F69) | — | `models`, `store`, `uvmonitor` all call the ONE `dates` helper; identical output for same `(now,tz)`; no import cycle | unit + import-hygiene | `uv run pytest tests/test_import_hygiene.py -k dates -x` + same-output test | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_scheduler.py::test_catchup_prior_local_day` — HARD-TZ-01 (F14), failing-first: 23:45→00:15 recovery keyed on yesterday.
- [ ] `tests/test_scheduler.py::test_catchup_fold_grace_not_inflated` — HARD-TZ-01/F91, fall-back-hour grace, CronTrigger fold=0 agreement (extends existing `test_dst_transition_band_exactly_once`).
- [ ] `tests/test_uv_monitor.py::test_allclear_not_latched_on_momentary_dip` — HARD-TZ-02 (F15), failing-first.
- [ ] `tests/test_uv_monitor.py::test_lifecycle_full_day_no_never_fire_gap` — HARD-TZ-02/D-04 state-machine walk.
- [ ] `tests/test_models.py::test_daily0_not_today_degrades` + `::test_naive_now_utc_treated_as_utc` — HARD-TZ-03 (F109/F35/F33).
- [ ] `tests/test_uv.py::test_compute_uv_daily0_today_guard` + `::test_hourly_points_sorted_before_interpolation` — HARD-TZ-03 (F31/F32).
- [ ] `weather/dates.py` shared-helper same-output test + import-hygiene assertion — HARD-TZ-04.
- [ ] Framework install: **none** — pytest + `tmp_db`/`load_fixture` fixtures already exist. Confirm exact test-file names against the repo during Wave 0 (research inferred `test_uv_monitor.py`/`test_uv.py`; if the actual filenames differ, use the repo's).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| New `weather/dates.py` module loads and catch-up runs without error at boot | HARD-TZ-04 (+ all) | Live editable systemd service on `yahir-mint` — module-load / boot path not exercised by unit tests | `systemctl restart weatherbot` then check `journalctl -u weatherbot` for a clean start + first catch-up pass with no ImportError/traceback |
| True local-midnight boundary catch-up recovery observed on the wall clock | HARD-TZ-01 | Cannot fast-forward the real system clock on a live service; unit tests inject `now_utc` to prove the mechanism | **Deferred Gate-2 milestone item** (mark PARTIAL, not skipped): observe a real just-after-midnight recovery, or a scheduled DST-day, in production logs |

*Mechanism proof is Gate-1 (injected-`now_utc` unit tests); the physical wall-clock observation is a deferred Gate-2 obligation per the two-gate UAT policy.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
