---
phase: 03-always-on-scheduler
verified: 2026-06-10T19:49:14Z
status: gaps_found
score: 3/5 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Across a simulated DST transition, a morning send fires exactly once (no skipped spring-forward miss, no doubled fall-back send) — SCHD-03, success criterion #3"
    status: failed
    reason: >
      plan_catchup builds the intended fire instant with
      now_local.replace(hour=hh, minute=mm), which keeps now_local's offset/fold
      and does NOT re-resolve the UTC offset for the new wall-clock time.
      Empirically confirmed: a 02:30 slot on the spring-forward day (2026-03-08,
      02:00->03:00 skipped) is a wall-clock time that never occurs, yet
      plan_catchup returns ONE MissedSlot for it (phantom catch-up fire) while the
      live CronTrigger would skip it — planner and trigger silently DISAGREE. In
      the fall-back fold (01:30 on 2026-11-01, scanned at the second 01:15) the
      replace() arithmetic yields a negative-day delta so scheduled > now_local
      and the slot is treated as "not due yet" and never caught up. The phase goal
      explicitly requires "surviving DST"; SC #3 explicitly requires "no skipped
      spring-forward miss, no doubled fall-back send." Neither holds in the
      transition band. The shipping test test_dst_exactly_once only exercises a
      07:00 slot (far outside the 01:00-02:59 band) so the 128-test green suite
      gives FALSE confidence (WR-01) — the SUMMARY cites this test as proof of
      "SCHD-03 DST exactly-once."
    artifacts:
      - path: "weatherbot/scheduler/catchup.py"
        issue: "Line 137: scheduled = now_local.replace(hour=hh, minute=mm, ...) does not re-resolve the tz offset; spring-forward gap and fall-back fold produce phantom/ambiguous instants that disagree with the live CronTrigger."
      - path: "tests/test_scheduler.py"
        issue: "test_dst_exactly_once (lines 248-264) only tests a 07:00 slot; no transition-band slot (02:30 gap / 01:30 fold) is asserted, so the DST guarantee is untested."
    missing:
      - "Build the scheduled instant by composing a naive wall-clock datetime and attaching the zone (datetime(y,m,d,hh,mm).replace(tzinfo=tz)) so the offset/fold is resolved correctly; compare aware instants (now_utc vs scheduled), never two wall-clock-derived locals."
      - "Detect the spring-forward gap (round-trip the wall-clock value through the zone; if it changes, the slot did not exist) and skip it so the planner agrees with the CronTrigger."
      - "Add DST tests with slot times INSIDE the affected hours — 02:30 on 2026-03-08 (gap) and 01:30 on 2026-11-01 (fold) — asserting exactly one fire and agreement with the live trigger. These should fail against the current code."
  - truth: "Restarting the process mid-morning produces exactly one briefing per (location, schedule-slot, local-date); the idempotency key prevents restart replay AND DST double-fire — SCHD-07, success criterion #5, goal's 'never sending a slot twice'"
    status: failed
    reason: >
      fire_slot performs a was_sent READ (daemon.py:96) on one SQLite connection,
      then a network fetch + Discord DELIVERY via send_now (daemon.py:111), then a
      record_sent WRITE (daemon.py:123) on a separate connection. This is a
      check-then-act window with the side-effecting delivery inside it. The
      sent_log UNIQUE(location_name, send_time, local_date) constraint + INSERT OR
      IGNORE dedups ROWS but NOT DELIVERIES: two overlapping fires for the same
      slot both pass was_sent (neither has recorded yet) and both POST to Discord;
      the user receives two messages, then one INSERT wins and the other is
      ignored. This window is real in this phase: the catch-up scan in _run_catchup
      fires a missed slot (synchronous network fetch) at the same wall-clock minute
      the live CronTrigger is due, and BackgroundScheduler runs jobs on a thread
      pool so two near-simultaneous fires of the same job id (e.g. a fall-back
      repeated minute, or a coalesced misfire) are possible. No atomic claim_slot /
      rowcount arbitration exists (grep found NONE). The result is at-most-once
      ROWS, not exactly-once DELIVERY — the daemon docstring/SUMMARY claim
      "exactly-once" but the goal's "never sending a slot twice" is not guaranteed
      at the delivery boundary.
    artifacts:
      - path: "weatherbot/scheduler/daemon.py"
        issue: "fire_slot (lines 96-123): was_sent read and record_sent write are separate connections with a live send_now delivery in between — non-atomic check-then-act, no claim arbitration."
      - path: "weatherbot/weather/store.py"
        issue: "record_sent (lines 213-235) is row-idempotent (INSERT OR IGNORE on UNIQUE) but provides no way to gate delivery on winning the insert; there is no claim_slot returning rowcount==1."
    missing:
      - "Add an atomic claim_slot(db_path, name, time, date) -> bool that does INSERT OR IGNORE and returns cur.rowcount == 1 (this caller won the claim), and gate delivery in fire_slot on the claim instead of on a prior was_sent read."
      - "On delivery failure, DELETE the claim so the slot stays re-fireable (preserve mark-after-success intent for the failure case)."
      - "Add a test that simulates two overlapping fire_slot calls for the same (location,time,date) and asserts the channel delivers exactly once."
deferred: []
---

# Phase 3: Always-On Scheduler Verification Report

**Phase Goal:** The manual pipeline becomes an always-on daemon that fires each location's briefings at the right local wall-clock time, honoring day-of-week selection, surviving DST, recovering missed sends, and never sending a slot twice.
**Verified:** 2026-06-10T19:49:14Z
**Status:** gaps_found
**Re-verification:** No — initial verification

> **MVP-mode note:** ROADMAP marks this phase `mode: mvp`, but the phase Goal is a declarative outcome statement, not an "As a..., I want to..., so that..." User Story. Rather than refuse verification, I verified against the roadmap's five explicit Success Criteria (the contract), which are concrete and testable. Flagging the goal-format mismatch for the maintainer.

## Goal Achievement

### Observable Truths (mapped to ROADMAP Success Criteria)

| #   | Truth (Success Criterion)                                                                                                                                  | Status     | Evidence                                                                                                                                                                                                                                  |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | SC#1: each location carries multiple send-times, each toggleable on/off without deletion, each with a day-of-week selection                                 | ✓ VERIFIED | `Schedule` model + `parse_days` (config/models.py:25, days.py:28); `Location.schedule` list (models.py:94); `enabled=false` retained; config.example.toml has Home mon-fri 07:00 + Weekend sat,sun 08:30; tests green                      |
| 2   | SC#2: a send fires at the location's local wall-clock time per-location IANA timezone; a different-tz location fires at its own local time                  | ✓ VERIFIED | `CronTrigger(hour, minute, day_of_week, timezone=location.timezone)` (daemon.py:168-173); `test_jobs_registered_per_location_tz` asserts trigger tz == loc tz per enabled slot                                                            |
| 3   | SC#3: across a simulated DST transition a morning send fires exactly once (no skipped spring-forward miss, no doubled fall-back send)                        | ✗ FAILED   | `now_local.replace(hour=hh,minute=mm)` (catchup.py:137) does not re-resolve offset. Reproduced: 02:30 spring-forward gap slot → 1 phantom MissedSlot (CronTrigger skips it); 01:30 fall-back fold → negative-day delta, never caught up. Test only covers 07:00. |
| 4   | SC#4: after downtime spanning a send-time, the bot sends the missed briefing once on recovery within the grace window                                       | ✓ VERIFIED | `plan_catchup` 90-min GRACE window + `_run_catchup` fires each MissedSlot once with `late=True`; `test_catchup_window` covers <90/≥90/before/already-sent. Works for normal-time slots; the DST-band math (CR-01) is a subset that fails. |
| 5   | SC#5: restarting mid-morning produces exactly one briefing per (location, slot, local-date); idempotency key prevents restart replay AND DST double-fire   | ✗ FAILED   | Restart replay (sequential) IS prevented (was_sent check + record_sent; `test_fire_slot_idempotent_double_fire`). But concurrent/overlapping fires are NOT: non-atomic read(daemon.py:96)→deliver(111)→write(123); UNIQUE dedups rows, not deliveries. |

**Score:** 3/5 truths verified

### Required Artifacts

| Artifact                              | Expected                                                     | Status     | Details                                                                                          |
| ------------------------------------- | ------------------------------------------------------------ | ---------- | ------------------------------------------------------------------------------------------------ |
| `weatherbot/scheduler/days.py`        | parse_days() preset/list validator+normalizer                | ✓ VERIFIED | `parse_days` present; presets + comma-list; raises on bad token (days.py:28)                     |
| `weatherbot/config/models.py`         | Schedule model + Location.schedule field                     | ✓ VERIFIED | `class Schedule` (25), `schedule: list[Schedule]` (94), parsed_time/day_of_week, parse_days wired |
| `weatherbot/weather/store.py`         | sent_log table + was_sent/record_sent                        | ✓ VERIFIED | DDL + UNIQUE (108-114), parameterized was_sent/record_sent (191-235); SQL is parameterized       |
| `weatherbot/scheduler/context.py`     | ScheduleContext + schedule_placeholders                      | ✓ VERIFIED | Both present (context.py:30,50); threaded into send_now                                          |
| `templates/renderer.py`               | CANONICAL extended with sent_at/checked_at/schedule_note     | ✓ VERIFIED | All three in CANONICAL (renderer.py:52-54)                                                        |
| `weatherbot/scheduler/catchup.py`     | plan_catchup pure planner + MissedSlot + _fires_on           | ⚠️ DEFECT  | Exists and wired, but DST instant computation is incorrect (CR-01) — see gap #1                  |
| `weatherbot/scheduler/daemon.py`      | run_daemon lifecycle + fire_slot callback                    | ⚠️ DEFECT  | Exists and wired, but check-then-act is non-atomic (CR-02) — see gap #2                          |
| `weatherbot/cli.py`                   | --run flag branch dispatching to run_daemon                  | ✓ VERIFIED | `--run` (339), `hasattr(args,"run")` branch (368), `run_daemon(...)` (381)                       |

### Key Link Verification

| From                          | To                                | Via                                          | Status   | Details                                                                 |
| ----------------------------- | --------------------------------- | -------------------------------------------- | -------- | ----------------------------------------------------------------------- |
| config/models.py              | scheduler/days.py                 | parse_days in Schedule.days validator        | ✓ WIRED  | Imported (models.py:14), called in validator + day_of_week              |
| weather/store.py              | sent_log table                    | parameterized INSERT OR IGNORE / SELECT      | ✓ WIRED  | Both helpers operate on sent_log with bound params                      |
| cli.py send_now               | scheduler/context.py              | schedule_placeholders merged into render()   | ✓ WIRED  | Imported (cli.py:38), merged at render call (151)                       |
| daemon.py fire_slot           | cli.py send_now                   | send_now(..., schedule_ctx=...)              | ✓ WIRED  | Lazy import (daemon.py:108), called (111)                               |
| daemon.py fire_slot           | store.py was_sent/record_sent     | check-before-fire then record-after-success  | ⚠️ PARTIAL | Both called, but NON-ATOMIC across the delivery — duplicate-delivery window (CR-02) |
| daemon.py run_daemon          | apscheduler CronTrigger           | one job per enabled slot at timezone=loc.tz  | ✓ WIRED  | CronTrigger per enabled slot with per-location tz (168-185)             |
| catchup.py plan_catchup       | store.py was_sent                 | injected was_sent reader skips sent slots    | ✓ WIRED  | Injected via lambda in _run_catchup (daemon.py:240)                     |

### Behavioral Spot-Checks

| Behavior                                                                  | Command                                                                                              | Result                                          | Status  |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------- | ------- |
| Full test suite passes                                                    | `uv run pytest -q`                                                                                  | 128 passed                                      | ✓ PASS  |
| CLI + daemon import without circular-import error                         | `uv run python -c "import weatherbot.cli; import weatherbot.scheduler.daemon"`                       | imports clean                                   | ✓ PASS  |
| Spring-forward 02:30 slot (non-existent wall-clock) → catch-up decision   | `plan_catchup` with 02:30 daily slot, scan 03:15 EDT 2026-03-08                                     | returns 1 MissedSlot (PHANTOM — should be 0)    | ✗ FAIL  |
| Fall-back 01:30 slot scanned at second 01:15 → due-yet decision           | `replace()` arithmetic on fold                                                                      | delta = -1 day 23:45 → "not due yet" (never caught up) | ✗ FAIL  |
| Non-atomic claim arbitration present (claim_slot / rowcount)              | `grep -rn "claim_slot\|rowcount" weatherbot/`                                                        | NONE FOUND                                      | ✗ FAIL  |

### Requirements Coverage

| Requirement | Source Plan        | Description                                                                              | Status        | Evidence                                                                                          |
| ----------- | ------------------ | ---------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------- |
| SCHD-01     | 03-01              | Each location owns its own schedule entries, multiple send-times per day                  | ✓ SATISFIED   | `Location.schedule: list[Schedule]`; config examples; tests                                       |
| SCHD-02     | 03-01              | Each schedule entry toggleable on/off without deleting it                                 | ✓ SATISFIED   | `enabled` field retained; disabled slots excluded from jobs + catch-up                            |
| SCHD-03     | 03-01, 03-03       | Day-of-week selection AND DST-survival (exactly-once across transition)                   | ✗ BLOCKED     | Day-of-week works; DST exactly-once FAILS (CR-01, gap #1) — the DST half of SCHD-03 is not met    |
| SCHD-04     | 03-02              | Each send fires at the location's local wall-clock time, survives DST (IANA tz)           | ⚠️ PARTIAL    | Per-tz firing + render display VERIFIED (SC#2); "survives DST" inherits the CR-01 failure         |
| SCHD-05     | 03-03              | Always-on in-process scheduler computes next run per location timezone                    | ✓ SATISFIED   | BackgroundScheduler + per-tz CronTrigger; announce computes next fire; `--run` foreground         |
| SCHD-06     | 03-03              | After downtime, bot sends missed briefing on recovery                                     | ✓ SATISFIED   | 90-min catch-up scan for normal-time slots (the DST-band subset fails via CR-01)                  |
| SCHD-07     | 03-01, 03-03       | Send idempotent per (location, slot, local-date) — never sent twice                       | ✗ BLOCKED     | Sequential restart-replay prevented; concurrent/overlap duplicate DELIVERY not prevented (CR-02, gap #2) |

All seven declared requirement IDs (SCHD-01..07) are accounted for. REQUIREMENTS.md currently marks all seven "Complete" for Phase 3 — that status is premature for SCHD-03 (DST half) and SCHD-07 (delivery-level exactly-once).

### Anti-Patterns Found

| File                              | Line   | Pattern                                       | Severity   | Impact                                                                                      |
| --------------------------------- | ------ | --------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------- |
| weatherbot/scheduler/catchup.py   | 137    | `datetime.replace(hour=,minute=)` for tz instant | 🛑 Blocker | Phantom/ambiguous instants in DST transition band → exactly-once-across-DST broken (SC#3)    |
| weatherbot/scheduler/daemon.py    | 96-123 | non-atomic check-then-act around a side effect | 🛑 Blocker | Concurrent/overlapping fires can deliver twice → "never sending a slot twice" broken (SC#5)  |
| tests/test_scheduler.py           | 248-264| DST test only covers 07:00 (non-band)          | ⚠️ Warning | False-confidence: the green suite asserts "exactly once" without testing any transition slot |
| weatherbot/scheduler/catchup.py   | 33,140 | docstring says "skipped + logged"; code only `continue`s | ℹ️ Info | Beyond-grace missed briefing is silently dropped — no log/alert (WR-05); relevant to CLAUDE.md "alert rather than silently miss" |

No debt markers (TODO/FIXME/XXX/TBD/HACK/PLACEHOLDER) found in any phase-modified file.

### Human Verification Required

None requested at the gate. The two blockers are programmatically confirmed (reproduced in-process), so no human spot-check is needed to establish them. Once fixed, a live multi-day daemon run and an actual DST-day observation would be the final confidence check, but that is downstream of closing these gaps.

### Gaps Summary

Two confirmed BLOCKERS strike the phase goal directly, and both were independently reproduced against the code (not taken from the review on faith):

1. **DST exactly-once is not met (SC#3 / SCHD-03 DST half).** `plan_catchup` computes the intended fire instant with `now_local.replace(hour=, minute=)`, which does not re-resolve the UTC offset/fold for the new wall-clock time. A spring-forward-gap slot (02:30 on 2026-03-08) that never exists yields a *phantom* catch-up fire that the live CronTrigger would never produce; a fall-back-fold slot (01:30 on 2026-11-01) produces a negative-day delta and is misclassified as "not due yet." The shipping `test_dst_exactly_once` only tests 07:00 — far outside the transition band — so the 128-test green run is false confidence and the SUMMARY's "SCHD-03 DST exactly-once" claim overstates what is proven.

2. **Exactly-once *delivery* is not met (SC#5 / SCHD-07).** `fire_slot` reads `was_sent`, then performs the network+Discord delivery, then writes `record_sent`, across separate connections with no atomic claim. The `UNIQUE` constraint dedups rows, not deliveries; two overlapping fires (catch-up overlapping the live cron at the same minute, a coalesced misfire, or a fall-back-repeated minute on the thread pool) both pass the read and both deliver — the user gets two messages. The system provides at-most-once rows, not exactly-once delivery as the goal ("never sending a slot twice") requires.

The remaining four success criteria (multiple toggleable day-of-week slots, per-location-tz firing, normal-time missed-send recovery, the in-process per-tz scheduler) ARE genuinely met and well-tested. The phase is close, but two of its five named guarantees — the two most distinctive ones (DST + never-twice) — do not hold. These must be closed before the phase goal is achieved.

---

_Verified: 2026-06-10T19:49:14Z_
_Verifier: Claude (gsd-verifier)_
