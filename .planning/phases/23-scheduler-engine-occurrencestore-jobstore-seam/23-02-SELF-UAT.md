# Phase 23 Plan 02 — Self-UAT Log (Gate 1, autonomous)

**Date:** 2026-06-28
**Scope:** SEAM-02 — route all 4 WeatherBot job registrations + reconcile read-throughs through `SchedulerEngine`, byte-identically.
**Policy:** Two-Gate UAT. This is Gate 1 (agent self-UAT, autonomous — gates the phase/PR). No blocking human-verify checkpoint emitted. The live `yahir-mint` daemon restart-catch-up verification is recorded as a **deferred Gate-2 milestone obligation** (see bottom).

**Oracle:** the full ~740-test suite + every Phase-21 golden is the byte-identical oracle. Any non-empty golden snapshot diff is a FAIL to root-cause, never to overwrite/regenerate.

**Change surface (git diff `e7438b5~1..HEAD`):** `weatherbot/scheduler/daemon.py` only — 1 file. Hunks confined to: import block, `_register_jobs` (briefing+forecast loops), `_register_uvmonitor_job`, `_reconcile_jobs` (two read-throughs), heartbeat site in `run_daemon`. `catchup.py` and `store.py` diff = empty. `fire_slot`/`fire_forecast_slot`/`_desired_job_ids`/`_restore_jobs`/`_do_reload` def-bodies unchanged (no hunks).

---

## Criterion 1 — Full suite green, zero-flake (definitive byte-identical oracle)

**Command:** `uv run pytest -q`

**Evidence (tail):**
```
2 snapshots failed. 27 snapshots passed.
748 passed, 1 warning in 39.31s
```

**Analysis of the "2 snapshots failed" line:** This is a syrupy **unused-snapshot** report-summary line (`0 failed` tests), NOT a test failure and NOT a golden diff. It is **pre-existing** and unrelated to this plan: 23-01-SUMMARY's deferred-items records it present on the full suite BEFORE any Phase-23 test files (`740 passed, 2 snapshots failed` with both new files ignored). Test count is `748 passed, 0 failed` — identical to Wave-1's post-state, with zero new failures introduced by the daemon rebind.

**Verdict:** PASS (748 passed, 0 test failures; the 2-unused-snapshots line is the documented pre-existing syrupy artifact, not a regression).

---

## Criterion 2 — Phase-21 goldens byte-identical (schedule, DB rows, DST/catch-up/reload)

**Command:** `uv run pytest tests/test_golden_schedule.py tests/test_golden_db.py tests/test_scheduler.py tests/test_reload.py -q`

**Evidence (tail):**
```
4 snapshots passed.
79 passed, 1 warning in 5.35s
```

Covers: schedule-plan golden (`next_run_time`/`str(trigger)`), `sent_log` DB-row goldens, ALL DST/catch-up goldens (arg-order `was_sent(name, time, date)` pinned), and exactly-once-across-reload (`test_reload.py`). **4 snapshots passed, 0 failed → zero non-empty golden diff.**

**Verdict:** PASS (every targeted golden byte-identical).

---

## Criterion 3 — Import hygiene (grimp + isolated-import smoke + litmus)

**Command:** `uv run pytest tests/test_import_hygiene.py -q`

**Evidence:**
```
........                                                                 [100%]
8 passed in 0.24s
```

grimp confirms the module imports zero app code; litmus confirms no weather noun in the new scheduler/ports signatures; gates auto-scaled to the new files. Note: `daemon.py` imports `SchedulerEngine` from the module side (app → module is allowed and expected); the module barrel never imports `weatherbot` (Pitfall 4 honored — import lives inside `daemon.py`, not at `weatherbot/scheduler/__init__.py` top).

**Verdict:** PASS.

---

## Criterion 4 — Wave-0 oracle (engine read-back + ports structural)

**Command:** `uv run pytest tests/test_scheduler_engine.py tests/test_ports.py -q`

**Evidence:**
```
........                                                                 [100%]
8 passed in 0.22s
```

The job-options read-back (`misfire_grace_time is None`, `coalesce is True`, `max_instances == 1` incl. on a briefing job) + Protocol structural-satisfaction oracle stay green — the engine's baked-default-of-1 `max_instances` is proven byte-identical, which is what licenses dropping the explicit `max_instances=1` at the uvmonitor site and omitting it at heartbeat.

**Verdict:** PASS.

---

## Boundary / prohibition checks (git-proven)

| Check | Command | Result |
|-------|---------|--------|
| Only `daemon.py` changed | `git diff --stat e7438b5~1 HEAD -- weatherbot/` | 1 file changed (daemon.py) — PASS |
| `catchup.py`/`store.py` untouched | `git diff e7438b5~1 HEAD -- catchup.py store.py` | empty — PASS (D-14/D-09) |
| `fire_slot`/`fire_forecast_slot` bodies | hunk-header scan | no def-line / body hunks — PASS (D-06a) |
| `_desired_job_ids`/`_restore_jobs`/`_do_reload` | hunk-header scan | no hunks in those functions — PASS (D-16) |
| No invariant kwargs at call sites | `grep misfire_grace_time\|coalesce\|max_instances daemon.py` | only docstring/comment hits remain; zero at any `engine.register` call site — PASS |
| All 4 sites route through engine | `grep "scheduler.add_job" daemon.py` | none remain — PASS (D-04) |
| `__heartbeat__`/`__uvmonitor__` exclusion | reconcile read | unchanged, stays app-side — PASS |

---

## Overall Verdict: PASS

Full suite (748 passed, 0 failures) + every Phase-21 golden byte-identical; all 4 job types (briefing, forecast, uvmonitor, heartbeat) register through `engine.register`; reconcile reads via `engine.list_live_ids()`/`engine.remove()`; `fire_slot`/`fire_forecast_slot`/`catchup.py`/`store.py` untouched. Phase boundary met autonomously.

## Deferred Gate-2 obligation (milestone-close, NOT a phase blocker)

- **Live `yahir-mint` daemon restart-catch-up.** The bot runs in production as a systemd service on host `yahir-mint` (editable install). After this milestone merges, restart the live daemon and confirm the startup catch-up scan + per-slot exactly-once delivery behave identically post-rebind (no duplicate/missed briefing across the restart boundary). Mechanism + result are already verified at the test level (full DST/catch-up/reload goldens byte-identical); only the physical live-daemon restart is deferred. Verdict for the deferred item: **PENDING (Gate-2)** — does not block this phase.
