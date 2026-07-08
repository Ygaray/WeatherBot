---
phase: 21-characterization-golden-test-harness
plan: 03
subsystem: testing
tags: [syrupy, golden-snapshot, characterization, time-machine, cli, apscheduler, sqlite, byte-exact]

# Dependency graph
requires:
  - phase: 21-01
    provides: shared conftest harness (FROZEN epoch 1781960400, json_snapshot/bytes_snapshot fixtures, schedule_plan_golden / onecall_rows_golden serializers) the goldens consume verbatim
provides:
  - "tests/test_golden_cli.py — 8 byte-exact CLI stdout goldens (bytes_snapshot) + inline exit-code pins for help/check-config/locations/status + weekday/weekend × detailed/compact forecast variants (D-02/D-03/D-10)"
  - "tests/test_golden_schedule.py — the registered-job schedule plan (job_id, str(CronTrigger), frozen tz-local next_run_time) read off a never-started BackgroundScheduler, sorted by job_id (D-11)"
  - "tests/test_golden_db.py — weather_onecall (imperial+metric) / sent_log / alerts row goldens via persist/claim_slot/record_alert with explicit ORDER BY + rowid scrub + frozen clock (D-11)"
  - "fix: conftest schedule_plan_golden now reads job.next_run_time defensively (getattr) — a pending scheduler's Job lacks the attribute entirely"
  - 12 committed goldens under tests/__snapshots__/test_golden_{cli,schedule,db}/
affects: [21-04, 21-05, 23-scheduler-seam, 24-config-reload, 25-lifecycle, 26-registry, 27-discord-adapter, 28-physical-split]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CLI stdout pinned via raw-bytes bytes_snapshot (one byte flip fails); exit code pinned as an inline literal (D-02/D-03)"
    - "status golden redirects cli.DEFAULT_DB_PATH off the live host db so Last-briefing is the deterministic 'none yet' branch (no live-state / wall-clock leak)"
    - "schedule plan read off a NEVER-started scheduler: str(CronTrigger) is the deterministic primary; next_run_time computed via the state._next_fire fallback under time_machine (pending Job has no next_run_time)"
    - "DB-row determinism = explicit ORDER BY (never sort-scrub) + scrub ONLY the autoincrement rowid + FREEZE the clock fields to FROZEN (target_local_date / *_at_utc become stable literals)"

key-files:
  created:
    - tests/test_golden_cli.py
    - tests/test_golden_schedule.py
    - tests/test_golden_db.py
    - tests/__snapshots__/test_golden_cli/ (8 .raw goldens)
    - tests/__snapshots__/test_golden_schedule/test_schedule_plan_golden.json
    - tests/__snapshots__/test_golden_db/ (3 .json goldens)
  modified:
    - tests/conftest.py

key-decisions:
  - "status CLI golden redirects DEFAULT_DB_PATH at a tmp db: the shipped CLI status reads the live daemon's heartbeat db (this host runs the bot as a systemd service), whose last_success_utc is a moving wall-clock value — snapshotting it would embed a real send time and flake on every other machine. Redirected → deterministic 'Last briefing: none yet'."
  - "schedule_plan_golden's next_run_time access made defensive (getattr): a NOT-started BackgroundScheduler's Job has NO next_run_time attribute at all (set only post-start()), so the bare access raised AttributeError on exactly the pending scheduler the helper targets (Pitfall 3). Fixed in the shared conftest helper."
  - "forecast-variant stdout driven through main(argv) with a monkeypatched cli.lookup_weather returning a fixture-built LookupResult (the test_cli.py precedent) — fully offline, no network/secret, deterministic under FROZEN + now=FROZEN."

requirements-completed: []

# Metrics
duration: ~22min
completed: 2026-06-27
status: complete
---

# Phase 21 Plan 03: CLI / Schedule-Plan / DB-Row Golden Pins (Wave 1) Summary

**Pinned the three non-visual output surfaces as byte-exact goldens — CLI stdout/exit per subcommand+forecast variant, the registered-job schedule plan (job_id + str(CronTrigger) + frozen next_run_time), and the rows a briefing persists (weather_onecall imperial+metric / sent_log / alerts) — using the Wave-0 harness (FROZEN clock, syrupy JSON/bytes serializers, conftest readers). 12 new goldens, full suite 683 passed, zero `weatherbot/` source change.**

## Performance

- **Duration:** ~22 min
- **Completed:** 2026-06-27
- **Tasks:** 3 (all `type=auto tdd=true`)
- **Files:** 3 created (518 LOC) + 1 modified (conftest fix); 12 goldens committed

## Accomplishments

- **Task 1 — CLI stdout/exit goldens (`ce712f6`):** 8 byte-exact stdout goldens (raw `bytes_snapshot`) + inline exit-code pins (D-03) for the offline subcommands (`help`, `check-config`, `locations`, `status`) and each forecast variant (weekday/weekend × detailed/compact, D-10). All offline (temp config, never the host `.env`), fixture-injected `lookup_weather` for the forecast cells, `time.sleep` no-op'd, frozen clock. No `appid`/`OPENWEATHER`/webhook/home-path in any golden (V7 grep clean).
- **Task 2 — schedule-plan golden (`010f29a`):** the full registered-job plan read off a NEVER-started `BackgroundScheduler` via the shared `schedule_plan_golden` serializer (sorted by job_id), pinning `str(CronTrigger)` (the deterministic primary) + a frozen tz-local `next_run_time` (via the `state._next_fire` fallback) for two Home briefing slots, the Home forecast slot, and the Travel daily slot. The disabled Home 22:00 slot is ABSENT — the SCHD-02 toggle proof. `cron` appears in the golden (acceptance ✓).
- **Task 3 — DB-row goldens (`af6760e`):** `weather_onecall` (imperial+metric, via the conftest `onecall_rows_golden` reader), `sent_log` (via `claim_slot`), and `alerts` (via `record_alert`) pinned byte-exact. Explicit `ORDER BY` in every read path (8 occurrences); only the autoincrement rowid scrubbed; clock fields frozen to FROZEN (`target_local_date=2026-06-20`, `*_at_utc=1781960400`). No `appid=`/`api.openweathermap.org` in any `raw_json` (V7 grep clean).

## Verification

- `uv run pytest tests/test_golden_cli.py tests/test_golden_schedule.py tests/test_golden_db.py -q` → **12 passed**.
- Every golden generated with one `--snapshot-update`, then re-run WITHOUT the flag (twice) — **zero flake**.
- **Full suite: 683 passed** (671 prior + 12 new), zero regression.
- `git diff --name-only weatherbot/` is **empty** — PURELY ADDITIVE, zero production-source change.
- Secret-hygiene greps (V7 / Pitfall 5) all clean; explicit ORDER BY present in schedule + DB read paths.

## Decisions Made

- **status golden isolated from the live host db.** See key-decisions — the shipped CLI `status` reads `DEFAULT_DB_PATH` (this host's live daemon heartbeat). Redirected at a tmp db so the golden is the deterministic "none yet" branch, not the running daemon's last send time.
- **Conftest serializer hardened for the pending-scheduler case it was built for** (see Deviations).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `schedule_plan_golden` crashed on a pending scheduler — made `next_run_time` read defensive**
- **Found during:** Task 2
- **Issue:** The Wave-0 conftest helper accessed `job.next_run_time` directly. A NOT-started `BackgroundScheduler`'s `Job` has NO `next_run_time` attribute at all (APScheduler sets it only after `start()` wakes the job), so the bare access raised `AttributeError` on exactly the pending scheduler the helper is designed for (Pitfall 3). The plan's own Task 2 ("read off a NOT-started scheduler") could not run.
- **Fix:** Changed the access to `getattr(job, "next_run_time", None)` — the same defensive guard `state._next_fire` already uses — so the primary `str(trigger)` byte is always captured and a pending job degrades to `next_run_time=None` instead of crashing. The test then fills the deterministic frozen next-fire via the documented `_next_fire` fallback.
- **Files modified:** tests/conftest.py
- **Verification:** all 4 conftest-consuming golden files (harness/embeds/custom_ids/schedule) green after the change; schedule golden generates + re-runs zero-flake.
- **Committed in:** `010f29a` (Task 2 commit)

**2. [Rule 1 - Determinism] status CLI golden was leaking the live daemon's send time**
- **Found during:** Task 1 (inspecting the generated `status` golden before commit)
- **Issue:** The first-generated `status` golden contained `Last briefing: 2026-06-27 14:30 UTC` — a real wall-clock value read from the LIVE daemon's heartbeat db (`DEFAULT_DB_PATH`) on this host (the bot runs as a systemd service). That is host-specific, non-deterministic (moves as the daemon ticks), and would flake on any other machine — violating the D-11 freeze/determinism mandate and the "never snapshot live state" hygiene rule.
- **Fix:** Monkeypatched `weatherbot.cli.DEFAULT_DB_PATH` at a fresh tmp db so the heartbeat read hits the deterministic "never run yet" branch → `Last briefing: none yet`. Regenerated the golden.
- **Files modified:** tests/test_golden_cli.py (test-only; no weatherbot/ change)
- **Verification:** regenerated golden shows `Last briefing: none yet`; zero-flake across repeated runs.
- **Committed in:** `ce712f6` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — one a latent shared-helper bug, one a determinism/host-state leak). No scope creep: the pinned surfaces are exactly those specified (CLI × forecast variants, schedule plan, the three DB tables). Ruff format applied to the new files (project lint convention) — ruff additionally dropped an unused `pytest` import from test_golden_cli.py (no `pytest.raises` in this file).

## Issues Encountered

None beyond the two deviations above. Note for downstream authors: JSONSnapshotExtension serializes object KEYS alphabetically while preserving LIST order — so the schedule/DB goldens show keys in alpha order but the load-bearing ROW order (sorted by job_id / explicit ORDER BY) is preserved, which is the actual contract.

## User Setup Required

None — purely additive offline test infrastructure. No external service / config.

## Next Phase Readiness

- Plans 21-04 (exception-identity / oracle self-proof) and 21-05 (coverage audit) are unblocked and unaffected — no file overlap.
- The hardened `schedule_plan_golden` (defensive `next_run_time`) is the version any future scheduler-seam test (Phase 23) should rely on.
- BHV-02 surface is partially pinned (CLI + schedule + DB); the embed/custom_id half shipped in 21-02. (REQUIREMENTS tracks BHV-02 at the requirement level; this plan's frontmatter lists it as the driving requirement but completion is asserted at phase close, not per-plan.)

## Self-Check: PASSED

- Created files verified on disk: tests/test_golden_cli.py, tests/test_golden_schedule.py, tests/test_golden_db.py, 12 goldens under tests/__snapshots__/test_golden_{cli,schedule,db}/.
- Modified file verified: tests/conftest.py.
- Commits verified in git log: `ce712f6` (Task 1), `010f29a` (Task 2), `af6760e` (Task 3).
- Full suite: 683 passed; `git diff --name-only weatherbot/` empty.

---
*Phase: 21-characterization-golden-test-harness*
*Completed: 2026-06-27*
