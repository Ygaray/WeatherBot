---
phase: 15-proactive-uv-sunscreen-monitor
verified: 2026-06-19T00:00:00Z
status: human_needed
score: 13/13 must-haves verified (code-checkable); 1 live-crossing UAT deferred to human
re_verification:
  previous_status: none
  previous_score: n/a
human_verification:
  - test: "Live daylight-crossing UAT on host yahir-mint (PLAN 15-03 Task 3, blocking checkpoint, operator-DEFERRED)"
    expected: "Over a real daylight UV crossing for today's active location, a pre-warn arrives as UV approaches the threshold, a crossing alert arrives when it reaches it, and an all-clear arrives when it drops back below — each EXACTLY ONCE. A mid-day `sudo systemctl restart weatherbot` after alerts fired causes NO re-spam. The morning briefing still went out exactly once, unaffected by the monitor."
    why_human: "Requires a real OpenWeather daylight UV crossing on the live systemd service; cannot be reproduced by fixtures. Unit-level decision branches + durable dedup + scheduler isolation are all green; only the end-to-end live behavior remains. Per the live-service MEMORY precedent (Phase-12), this UAT was deferred non-halting by the operator to let the milestone chain complete."
---

# Phase 15: Proactive UV Sunscreen Monitor Verification Report

**Phase Goal:** A new background intraday monitor watches today's active location(s) during daylight and proactively warns the user before and when UV crosses the sunscreen threshold — at most once per day per location — running failure-isolated from the briefing spine in the same discipline as the v1.1 inbound bot thread.

**Verified:** 2026-06-19
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

Every code-checkable must-have across all three plans is VERIFIED against the actual codebase. The full test suite is green at **565 passed** (matching the SUMMARY claim). The three critical structural guarantees the goal hinges on (failure isolation, no time-series pollution, dedup durability) are STRUCTURALLY enforced in shipped code, not merely claimed. The only outstanding item is the live daylight-crossing UAT (PLAN 15-03 Task 3), a blocking operator checkpoint deferred non-halting — routed to human verification.

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Absent/partial `[uv]` table loads with monitor defaults (enabled, 900s, margin 1.0) | VERIFIED | `models.py:410,415,416` — `monitor_enabled=True`, `interval_seconds=900`, `value_margin=1.0`; `tests/test_config_uv.py` green |
| 2 | `claim_uv_alert` returns True exactly once per (loc,date,kind); False on repeats; durable across fresh connection | VERIFIED | `store.py:351-386` atomic `INSERT OR IGNORE` + `rowcount==1`, own `sqlite3.connect` per call; store tests green |
| 3 | `claimed_uv_kinds` returns durable set of prior kinds | VERIFIED | `store.py:389-406` `SELECT alert_kind ... WHERE location_id=? AND local_date=?`; own connection (restart-safe) |
| 4 | `catchup.fires_on` is public and the catch-up planner still uses it | VERIFIED | `grep def fires_on`==1, `def _fires_on`==0; `test_scheduler.py` (47 catchup tests) green |
| 5 | Tick reads `holder.current()` once, polls only active-today during daylight, never persists | VERIFIED | `uvmonitor.py:302` snapshot-once, `:314` `_active_today` gate, `:136` `_is_daylight` gate; `grep persist`==0; `test_tick_never_persists` spy asserts 0 calls |
| 6 | Pre-warn fires once on time-proximity OR value-proximity (whichever first) | VERIFIED | `uvmonitor.py:231-254` `time_close or value_close`; `test_prewarn_time_proximity_fires_once`, `test_prewarn_value_proximity_fires_once` green |
| 7 | Crossing fires once when UV reaches threshold; first-poll already-high posts crossing wording AND claims prewarn to suppress moot pre-warn | VERIFIED | `uvmonitor.py:210-228`; `test_crossing_fires_once`, `test_already_high_first_poll_suppresses_prewarn` green |
| 8 | All-clear fires once when UV drops below after a crossing was claimed | VERIFIED | `uvmonitor.py:257-266` independent branch gated on `"crossing" in prior`; `test_all_clear_after_crossing` green |
| 9 | Each of the three kinds posts at most once/day/location, durable across restart | VERIFIED | every post gated by `claim_uv_alert` rowcount; `test_restart_dedup_preclaimed_kinds_post_nothing` pre-claims rows and asserts ZERO posts |
| 10 | A raising fetch/post/per-location iteration is swallowed and logged; tick never raises | VERIFIED | `uvmonitor.py:313-323` per-location try/except, `:301-328` outermost envelope; `test_per_location_fetch_raise_isolated`, `test_channel_send_raise_does_not_propagate`, `test_compute_uv_raise_swallowed`, `test_holder_current_raise_caught_by_outer_envelope` green |
| 11 | On daemon start (monitor_enabled true) `__uvmonitor__` IntervalTrigger job registered with interval_seconds, max_instances=1, misfire_grace_time=None, coalesce=True | VERIFIED | `daemon.py:745-758`; `test_uvmonitor_job_registered_when_enabled`, `test_uvmonitor_job_apscheduler_kwargs` green |
| 12 | monitor_enabled false → no job registered | VERIFIED | `daemon.py:738-739` early return; `test_uvmonitor_job_absent_when_disabled` green |
| 13 | Reload (`_reconcile_jobs`) leaves `__uvmonitor__` alone (excluded by id like `__heartbeat__`) | VERIFIED | `daemon.py:798-802` `j.id not in ("__heartbeat__", "__uvmonitor__")`; `test_uvmonitor_survives_reconcile_pass` green |
| 14 | A raising `__uvmonitor__` tick does not stop the scheduler or any briefing job (live daylight crossing once-each, no re-spam, briefing unaffected) | PARTIAL → human | Scheduler-level isolation PROVEN (`test_raising_uvmonitor_tick_never_stops_scheduler`). The LIVE once-each-over-a-real-crossing + restart-no-respam + briefing-unaffected behavior is the operator-deferred UAT (PLAN 15-03 Task 3) — routed to human verification, not a gap |

**Score:** 13/13 code-checkable truths VERIFIED. Truth #14's automated portion (scheduler isolation) is VERIFIED; its live end-to-end portion is human-deferred.

### Three Critical Structural Guarantees (per task context)

| Guarantee | Requirement | Status | Structural Evidence |
|-----------|-------------|--------|---------------------|
| FAILURE ISOLATION | UV-06 | VERIFIED | Two-layer in-tick try/except (`uvmonitor.py:313`, `:326`) + APScheduler job config `max_instances=1`/`misfire_grace_time=None`/`coalesce=True` on `__uvmonitor__` (`daemon.py:755-758`); scheduler-level isolation proven by real-BackgroundScheduler test (EVENT_JOB_ERROR observed, sentinel keeps firing, `scheduler.running` stays True) |
| NO TIME-SERIES POLLUTION | UV-04 | VERIFIED | `grep 'store.persist\|.persist('` on `uvmonitor.py` == 0; only durable write is `claim_uv_alert` → dedicated `uv_alerts` table; `test_tick_never_persists` spies `store.persist` and asserts 0 invocations; the monitor never writes the briefing `sent_log` |
| DEDUP DURABILITY | UV-05 | VERIFIED | Three kinds (prewarn/crossing/allclear) each via atomic `INSERT OR IGNORE` + `rowcount==1` claim against `UNIQUE(location_id, local_date, alert_kind)`; durable across a fresh sqlite connection (own `connect()` per call); `grep 'claim_slot\|sent_log\|record_sent\|release_claim'` on `uvmonitor.py` == 0 (structurally cannot touch briefing exactly-once namespace) — also enforced by `test_monitor_never_touches_briefing_namespace` |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `weatherbot/config/models.py` | UvConfig + 3 frozen validated monitor knobs | VERIFIED | `monitor_enabled`/`interval_seconds`(60..86400 validator)/`value_margin`(0..20 validator) on existing UvConfig |
| `weatherbot/weather/store.py` | uv_alerts table + claim_uv_alert + claimed_uv_kinds | VERIFIED | table at `:129`, functions at `:351`/`:389`, parameterized `?`-only SQL |
| `weatherbot/scheduler/catchup.py` | public fires_on | VERIFIED | promoted from `_fires_on`; planner uses renamed symbol unchanged |
| `weatherbot/scheduler/uvmonitor.py` | tick + gates + 3-branch decision + isolation | VERIFIED | 329 lines, substantive, wired (imported by daemon), no stubs, no debt markers |
| `weatherbot/scheduler/daemon.py` | `__uvmonitor__` registration + reconcile exclusion | VERIFIED | `_register_uvmonitor_job` (gated) wired into `run_daemon:1441` after heartbeat; reconcile exclusion at `:801` |
| `tests/test_uv_monitor.py` | tick/decision/dedup/daylight/isolation/no-persist tests | VERIFIED | 24+ behavior tests incl. canary, all decision branches, restart-dedup, 5 isolation cases |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| uvmonitor.py | weather.uv.compute_uv | import + call with threshold | WIRED | `:39` import, `:144` `compute_uv(onecall_imp, None, threshold, tz=tz, now=now_local)` |
| uvmonitor.py | store.claim_uv_alert/claimed_uv_kinds | dedup claim per kind | WIRED | `:38` import, 8 `claim_uv_alert` references across branches, `:145` `claimed_uv_kinds` |
| uvmonitor.py | catchup.fires_on | active-today gate | WIRED | `:37` import, `:62` `fires_on(s, now_local)` over enabled slots |
| daemon.run_daemon | uvmonitor._uv_monitor_tick | add_job id=`__uvmonitor__` | WIRED | lazy import `:743`, `add_job(_uv_monitor_tick, ... id="__uvmonitor__")` `:745-758`; `test_daemon_registers_this_exact_tick` ties them |
| daemon._reconcile_jobs | `__uvmonitor__` | exclude-by-id | WIRED | `:801` excluded alongside `__heartbeat__` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| uvmonitor `_evaluate_location` | `onecall_imp` | `client.fetch_onecall(location, "imperial")` (live One Call payload) | Yes (real API fetch, read-only) | FLOWING |
| uvmonitor `_decide` | `summary` | `compute_uv(onecall_imp, ...)` (Phase-14 verbatim) | Yes (derived from real payload hourly[].uvi) | FLOWING |
| uvmonitor `_decide` | `prior` | `claimed_uv_kinds(db_path, location.id, local_date)` (sqlite) | Yes (durable rows) | FLOWING |

Note: alert posts go to `channel.send` (live Discord webhook) in production; in tests a RecordingChannel captures them. No hardcoded/empty data paths.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite green | `uv run pytest -q` | 565 passed, 1 pre-existing unrelated audioop DeprecationWarning | PASS |
| UV/scheduler/store/config suites | `uv run pytest tests/test_uv_monitor.py tests/test_scheduler.py tests/test_store.py tests/test_config_uv.py -q` | 120 passed | PASS |
| Lint clean | `uv run ruff check` (4 source files) | All checks passed | PASS |
| Scheduler-level isolation (real BackgroundScheduler) | `test_raising_uvmonitor_tick_never_stops_scheduler` | sentinel fires, scheduler.running True, EVENT_JOB_ERROR observed | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| UV-04 | 15-01/02/03 | Background intraday monitor polls on configurable interval for today's active location(s), daylight only | SATISFIED | `__uvmonitor__` IntervalTrigger job (gated, reconcile-stable), active-today + daylight gates, read-only no-persist fetch |
| UV-05 | 15-01/02/03 | Pre-warn + threshold-reached, each at most once/day/location, to Discord | SATISFIED (code) / live UAT human | Three durable-dedup decision branches unit-green; live once-each-over-real-crossing is the deferred operator UAT |
| UV-06 | 15-02/03 | Monitor failure-isolated — never gates/delays/stops a briefing | SATISFIED | Two-layer in-tick envelope + APScheduler per-job isolation (proven) + structural briefing-namespace separation |

All three declared requirement IDs (UV-04, UV-05, UV-06) appear in PLAN frontmatter and are accounted for in REQUIREMENTS.md (lines 30-32, 103-105). No orphaned requirements: REQUIREMENTS.md maps exactly UV-04/05/06 to Phase 15, all claimed by the plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | none | — | No TBD/FIXME/XXX/HACK/PLACEHOLDER in any phase-15 source file; no empty-return stubs in production paths; no hardcoded-empty data flowing to output |

### Human Verification Required

#### 1. Live daylight-crossing UAT on host yahir-mint (PLAN 15-03 Task 3 — blocking checkpoint, operator-DEFERRED)

**Test:**
1. Deploy the new code to host `yahir-mint` (editable install); optionally add `[uv]` monitor fields to host `config.toml` (defaults work unedited).
2. `sudo systemctl restart weatherbot` (a new module + new job load only on next process start).
3. Confirm the daemon log shows `__uvmonitor__` registered and ticking on the configured interval during daylight, skipping outside daylight / for non-active locations.
4. Over a real daylight UV crossing for today's active location, confirm a pre-warn arrives as UV approaches, a crossing alert when it reaches the threshold, and an all-clear when it drops below — each EXACTLY ONCE.
5. `sudo systemctl restart weatherbot` mid-day after alerts fired — confirm NO re-spam.
6. Confirm the morning briefing still went out exactly once, unaffected by the monitor.

**Expected:** Three alerts once each over the crossing; no re-spam after a mid-day restart; briefing unaffected.

**Why human:** Requires a real OpenWeather daylight UV crossing on the live systemd service — cannot be reproduced by fixtures. All unit-level decision/dedup/isolation behavior is green and all structural guarantees are enforced in code; only the live end-to-end confirmation remains. Per the live-service MEMORY precedent (Phase-12), the operator deferred this UAT non-halting to let the milestone chain complete.

### Gaps Summary

No gaps. Every code-checkable must-have is VERIFIED in the actual codebase, the full suite is green at 565 passed, and the three high-risk structural guarantees (failure isolation UV-06, no time-series pollution UV-04, dedup durability UV-05) are STRUCTURALLY enforced — confirmed by direct code reading AND by dedicated tests (spy-based no-persist, source-scan briefing-namespace separation, real-scheduler isolation, pre-claimed-rows restart-dedup), not by SUMMARY narrative alone.

The single outstanding item is the live daylight-crossing UAT, a blocking operator checkpoint the operator deferred per the live-service precedent. Phase 15 is the last phase in the milestone, so this item cannot be deferred to a later phase — it is correctly surfaced as a human-verification item, making the overall status `human_needed` rather than `passed` or `gaps_found`.

---

_Verified: 2026-06-19_
_Verifier: Claude (gsd-verifier)_
