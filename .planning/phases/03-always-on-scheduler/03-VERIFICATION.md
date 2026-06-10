---
phase: 03-always-on-scheduler
verified: 2026-06-10T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 3/5
  gaps_closed:
    - "DST exactly-once (SC#3 / SCHD-04 DST half): spring-forward gap no longer emits a phantom catch-up fire; fall-back fold is caught up once within grace, dropped beyond grace."
    - "Exactly-once delivery (SC#5 / SCHD-07): fire_slot now wins an atomic claim_slot BEFORE the network send; two overlapping fires deliver exactly once."
  gaps_remaining: []
  regressions: []
gaps: []
deferred: []
---

# Phase 3: Always-On Scheduler Verification Report

**Phase Goal:** An always-on, in-process scheduler that fires each location's daily briefing at its local wall-clock time, survives DST transitions, catches up missed sends after downtime, and delivers each (location, slot, local-date) exactly once.
**Verified:** 2026-06-10
**Status:** passed
**Re-verification:** Yes — after gap closure (plans 03-04 DST band, 03-05 atomic claim)

> Both blockers from the prior `gaps_found` report were independently re-verified against the LIVE code (not taken from the SUMMARY or the review on faith): the DST gap/fold logic in `catchup.py` was exercised in a fresh process across both the spring-forward gap and the fall-back fold, and the atomic claim was raced across 20 concurrent threads. The code review's CR-01 (dead-code gap detector) fix and WR-01 (test scanned where the bug was masked) fix were both confirmed present in the committed code.

## Goal Achievement

### Observable Truths (mapped to the five phase success criteria)

| #   | Truth (Success Criterion)                                                                                                                                      | Status     | Evidence                                                                                                                                                                                                                                                                       |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | SC#1: each location carries multiple send-times, each toggleable on/off without deletion, each with a day-of-week selection                                     | ✓ VERIFIED | `Schedule` model + `parse_days`; `Location.schedule: list[Schedule]`; `enabled=false` retained and excluded from jobs + catch-up; tests green. Unchanged since prior PASS.                                                                                                       |
| 2   | SC#2: a send fires at the location's local wall-clock time per-location IANA timezone; a different-tz location fires at its own local time                      | ✓ VERIFIED | `CronTrigger(hour, minute, day_of_week, timezone=location.timezone)` (daemon.py:195-200); `test_jobs_registered_per_location_tz` asserts trigger tz == loc tz per enabled slot (Home=America/New_York, Weekend=America/Chicago). Unchanged since prior PASS.                       |
| 3   | SC#3: across a simulated DST transition a morning send fires exactly once (no skipped spring-forward miss, no doubled fall-back send)                            | ✓ VERIFIED | **NOW FIXED.** `plan_catchup` (catchup.py:150-167) composes a naive wall-clock dt + attaches the zone, detects the spring-forward gap via `off0 != off1 and roundtrip != naive` (UTC round-trip), and compares aware instants vs `now_utc`. Independently reproduced (see spot-checks): 02:30 gap → 0 fires at BOTH 03:15 and 03:45 scans; 01:30 fold → exactly 1 within grace, 0 beyond. |
| 4   | SC#4: after downtime spanning a send-time, the bot sends the missed briefing once on recovery within the grace window                                           | ✓ VERIFIED | `plan_catchup` 90-min `GRACE` + `_run_catchup` fires each `MissedSlot` once with `late=True`; `test_catchup_window` + `test_dst_transition_band_exactly_once` cover normal AND transition-band slots. The DST-band subset that previously failed now passes.                       |
| 5   | SC#5: restarting mid-morning produces exactly one briefing per (location, slot, local-date); the dedup key prevents restart replay AND concurrent double-fire   | ✓ VERIFIED | **NOW FIXED.** `fire_slot` (daemon.py:113) wins an atomic `claim_slot` (INSERT OR IGNORE + `rowcount==1`) BEFORE `send_now` (daemon.py:129); a lost claim returns `None` (no POST); a non-ok/raised send `release_claim`s (guarded by `claimed`). Independently raced 20 threads → exactly 1 `True`; `test_concurrent_double_fire_delivers_once` asserts `len(channel.sent_text) == 1`. |

**Score:** 5/5 truths verified (was 3/5)

### Required Artifacts

| Artifact                          | Expected                                                              | Status     | Details                                                                                                                |
| --------------------------------- | --------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------- |
| `weatherbot/scheduler/catchup.py` | plan_catchup pure planner, DST-correct instant + gap skip             | ✓ VERIFIED | Naive wall-clock + `.replace(tzinfo=tz)`; gap detector `off0 != off1 and roundtrip != naive` (lines 156-163); aware-instant due/grace vs `now_utc`. `grep "now_local.replace(hour"` == 0. |
| `weatherbot/weather/store.py`     | atomic `claim_slot` (rowcount==1) + `release_claim` (3-key DELETE)     | ✓ VERIFIED | `claim_slot` returns `cur.rowcount == 1` after `INSERT OR IGNORE` (lines 265-275); `release_claim` binds all three key cols (298). Parameterized only. |
| `weatherbot/scheduler/daemon.py`  | fire_slot gates delivery on claim BEFORE send, releases on failure    | ✓ VERIFIED | `claim_slot` at 113 BEFORE `send_now` at 129; lost claim → early `None`; non-ok → `release_claim` (143); except → guarded `release_claim` (159-160). `record_sent` no longer called from daemon. |
| `tests/test_scheduler.py`         | transition-band DST test + concurrent-double-fire test                 | ✓ VERIFIED | `test_dst_transition_band_exactly_once` scans the GAP at 03:45 (past-due, within grace) so it truly exercises gap detection (WR-01 fix); `test_concurrent_double_fire_delivers_once` asserts one POST. |
| `weatherbot/config/models.py`     | Schedule model + Location.schedule                                    | ✓ VERIFIED | Unchanged since prior PASS.                                                                                            |
| `weatherbot/cli.py`               | `--run` flag dispatching to `run_daemon`                              | ✓ VERIFIED | `--run` (339); branch dispatches `daemon.run_daemon(...)` (381).                                                      |

### Key Link Verification

| From                      | To                            | Via                                          | Status   | Details                                                                       |
| ------------------------- | ----------------------------- | -------------------------------------------- | -------- | ----------------------------------------------------------------------------- |
| daemon.py fire_slot       | store.py claim_slot           | atomic INSERT OR IGNORE + rowcount==1        | ✓ WIRED  | Imported (daemon.py:49), gated at 113 BEFORE the send — non-atomic window removed. |
| daemon.py fire_slot       | store.py release_claim        | release on non-ok (143) and raised (160)     | ✓ WIRED  | Guarded by `claimed and local_date is not None` — only undoes a won claim.    |
| daemon.py fire_slot       | cli.py send_now               | claim-won → send_now POST                    | ✓ WIRED  | Claim gates the delivery; lost claim returns before send_now is called.       |
| catchup.py plan_catchup   | zoneinfo gap/fold resolution  | datetime(...).replace(tzinfo=tz) + UTC round-trip | ✓ WIRED | Gap skipped, fold kept at fold=0 first occurrence; aware-instant comparison vs now_utc. |
| catchup.py plan_catchup   | store.py was_sent             | injected reader pre-filters sent slots       | ✓ WIRED  | `_run_catchup` lambda (daemon.py:267); planner pre-filter, claim_slot is the authoritative dedup. |
| daemon.py run_daemon      | apscheduler CronTrigger       | one job per enabled slot at timezone=loc.tz  | ✓ WIRED  | Per-location tz trigger (195-200); `misfire_grace_time=None` (recovery owned by sent-log). |

### Behavioral Spot-Checks (run independently against live code)

| Behavior                                                          | Command / Method                                                                 | Result                          | Status  |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------- | ------------------------------- | ------- |
| Full test suite passes                                            | `uv run pytest -q`                                                               | 130 passed in 2.93s             | ✓ PASS  |
| Spring-forward 02:30 gap, scan 03:45 local (past-due, in grace)   | `plan_catchup(02:30 daily, now=03:45 EDT 2026-03-08)`                            | 0 MissedSlots (no phantom)      | ✓ PASS  |
| Spring-forward 02:30 gap, scan 03:15 local (prior masking point)  | `plan_catchup(02:30 daily, now=03:15 EDT 2026-03-08)`                            | 0 MissedSlots                   | ✓ PASS  |
| Normal 07:00 slot on DST day still fires                          | `plan_catchup(07:00 daily, now=07:30 2026-03-08)`                               | 1 MissedSlot                    | ✓ PASS  |
| Fall-back 01:30 fold, +60min within grace                        | `plan_catchup(01:30 daily, now=first_01:30_EDT+60m)`                            | 1 MissedSlot (local_date 11-01) | ✓ PASS  |
| Fall-back 01:30 fold, +120min beyond grace                       | `plan_catchup(01:30 daily, now=first_01:30_EDT+120m)`                           | 0 MissedSlots                   | ✓ PASS  |
| Atomic claim arbitration under concurrency                        | 20 threads racing `claim_slot` on one key (barrier-synced)                       | exactly 1 True                  | ✓ PASS  |
| Sequential claim + release + re-claim                             | claim→False on 2nd, was_sent True, release→was_sent False, re-claim True         | as expected                     | ✓ PASS  |
| Lost claim gates delivery                                         | pre-claim then 2nd `claim_slot` for same key                                     | False (caller must not POST)    | ✓ PASS  |
| CLI `--run` dispatches to run_daemon                              | `grep --run / run_daemon weatherbot/cli.py`                                      | flag at 339, dispatch at 381    | ✓ PASS  |

### Requirements Coverage

| Requirement | Source Plan        | Description                                                                  | Status        | Evidence                                                                                                   |
| ----------- | ------------------ | ---------------------------------------------------------------------------- | ------------- | ---------------------------------------------------------------------------------------------------------- |
| SCHD-01     | 03-01              | Each location owns its own schedule entries, multiple send-times per day      | ✓ SATISFIED   | `Location.schedule: list[Schedule]`; config examples; tests.                                               |
| SCHD-02     | 03-01              | Each schedule entry toggleable on/off without deleting it                     | ✓ SATISFIED   | `enabled` field retained; disabled slots excluded from jobs + catch-up.                                    |
| SCHD-03     | 03-01, 03-03, 03-04 | Day-of-week selection AND DST-survival exactly-once across transition        | ✓ SATISFIED   | Day-of-week works; DST exactly-once now verified (gap skip + fold catch-up). Was BLOCKED, now satisfied.   |
| SCHD-04     | 03-02, 03-04       | Each send fires at local wall-clock time, survives DST (IANA tz)             | ✓ SATISFIED   | Per-tz firing + render display + DST-correct catch-up planner. Was PARTIAL (DST half), now satisfied.      |
| SCHD-05     | 03-03              | Always-on in-process scheduler computes next run per location timezone        | ✓ SATISFIED   | BackgroundScheduler + per-tz CronTrigger; `--run` foreground lifecycle.                                    |
| SCHD-06     | 03-03, 03-04       | After downtime, bot sends missed briefing on recovery                         | ✓ SATISFIED   | 90-min catch-up scan; transition-band subset now correct. `release_claim` re-opens a slot on failure.      |
| SCHD-07     | 03-01, 03-03, 03-05 | Send idempotent per (location, slot, local-date) — never sent twice          | ✓ SATISFIED   | Atomic claim-before-send + release-on-failure; delivery-level exactly-once. Was BLOCKED, now satisfied.    |

All seven declared requirement IDs (SCHD-01..07) are accounted for and SATISFIED in the code.

**REQUIREMENTS.md annotations are STALE and should be cleared.** Lines 36, 39, 140, 143 still carry the pre-closure "DST-survival half unmet", "non-atomic check-then-send", and "In Progress" notes for SCHD-04 and SCHD-07. The code now contradicts these: SCHD-04 DST half and SCHD-07 delivery-level exactly-once both hold. Recommend updating those two table rows to "Complete" and removing the trailing italic caveats on lines 36 and 39.

### Anti-Patterns Found

| File                            | Line   | Pattern                                  | Severity | Impact                                                                                         |
| ------------------------------- | ------ | ---------------------------------------- | -------- | ---------------------------------------------------------------------------------------------- |
| (prior blockers)                | —      | DST `now_local.replace` / non-atomic check-then-act | ✓ RESOLVED | Both prior 🛑 blockers fixed and verified (grep `now_local.replace(hour` == 0; claim-before-send wired). |

No debt markers (TODO/FIXME/XXX/TBD/HACK/PLACEHOLDER) found in any phase-modified file.

**Deferred review items (NOT blockers — carried to future work, per 03-REVIEW.md / 03-05-SUMMARY.md):**
- **WR-02** (crash between claim-commit and send leaves a slot un-fireable on next startup): an inherent claim-before-send durability edge. Relevant to the project's "retry then alert rather than silently miss" constraint, but a single-crash-during-send window for a single-user bot; appropriate to address in Phase 4 (reliability / retry-then-alert), which builds on the release-on-failure seam.
- **WR-03** (per-call `executescript(_SCHEMA)` in the hot claim path): a performance/transaction-hygiene concern, not a correctness defect — the atomic claim was verified correct under 20-thread concurrency regardless.
- **WR-04** (APScheduler fall-back fold vs planner `fold=0` not cross-checked): bounded by the exactly-once claim (a fold disagreement cannot cause a double-send because the claim arbitrates). Worth a confirmatory test later.
- **IN-01/IN-02** (record_sent now dead on the live path; was_sent comment): cosmetic.

None of these block the phase goal. They are surfaced for Phase 4 planning.

### Human Verification Required

None required for goal achievement. Both distinctive guarantees (DST exactly-once and exactly-once delivery) are programmatically reproducible and were independently confirmed in-process. A live multi-day daemon run and an actual DST-day observation remain the ultimate real-world confidence check, but that is operational validation downstream of this phase, not a gate on the code-level goal.

### Gaps Summary

No gaps. The two BLOCKERS from the prior `gaps_found` report are closed and independently re-verified:

1. **DST exactly-once (SC#3 / SCHD-04 DST half) — CLOSED.** The dead-code gap detector flagged by the review (CR-01) was replaced with a UTC-round-trip + two-fold-offset detector (`off0 != off1 and roundtrip != naive`, commit a4ff487), and the test scan time was moved to 03:45 local (commit 8a49672) so it genuinely exercises gap detection rather than masking it via the "not due yet" branch. Independently reproduced: the 02:30 spring-forward gap produces ZERO phantom fires at both 03:15 and 03:45 scans, the 01:30 fall-back fold is caught up exactly once within grace and dropped beyond grace, and a normal 07:00 slot still fires.

2. **Exactly-once delivery (SC#5 / SCHD-07) — CLOSED.** `fire_slot` now wins an atomic `claim_slot` (INSERT OR IGNORE + `rowcount==1`, commits a2d2c95/367ea31) BEFORE the network send, returns early without delivering when the claim is lost, and releases the claim on a non-ok or raised delivery (guarded so it only undoes a claim this caller won). Independently raced across 20 concurrent threads: exactly one `True`. The shipping `test_concurrent_double_fire_delivers_once` asserts two overlapping `fire_slot` calls produce exactly one POST.

Full suite: 130 passed (was 128 + 2 new transition-band / concurrent-double-fire tests). The phase goal — an always-on scheduler that fires at local wall-clock time, survives DST, catches up missed sends within grace, and delivers each (location, slot, local-date) exactly once — is achieved. Recommend clearing the stale "In Progress / unmet" annotations for SCHD-04 and SCHD-07 in REQUIREMENTS.md.

---

_Verified: 2026-06-10_
_Verifier: Claude (gsd-verifier)_
