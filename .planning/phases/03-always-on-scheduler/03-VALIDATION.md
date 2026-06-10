---
phase: 3
slug: always-on-scheduler
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-10
audited: 2026-06-10
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| **Quick run command** | `uv run pytest tests/test_scheduler.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~10 seconds |

Shared fixtures (`tests/conftest.py`): `tmp_db` (fresh per-test SQLite path), `load_fixture`
(recorded One Call JSON loader). Fakes: `_FakeClient`/`_FakeChannel` in `tests/test_send_now.py`
(copied into `tests/test_scheduler.py` to drive `fire_slot` without network). No wall-clock waits —
catch-up/DST/idempotency are tested as pure functions with an injected `now_utc` and by invoking
the `fire_slot` callback directly.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_scheduler.py -q` (plus the touched `test_config`/`test_store`/`test_renderer`/`test_send_now`)
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | SCHD-(deps) | T-03-SC | apscheduler verified legitimate (PyPI) before install; no 4.x | manual+auto | `uv run python -c "import apscheduler; print(apscheduler.__version__)"` | ✅ existing import | ✅ green |
| 03-01-02 | 01 | 1 | SCHD-01/02/03 | T-03-02 | bad days/time token fails loud at config load (whitelist validators) | unit | `uv run pytest tests/test_scheduler.py::test_days_parsing_matrix tests/test_config.py::test_multiple_schedule_entries tests/test_config.py::test_bad_days_fails_load -x` | ✅ test_scheduler.py | ✅ green |
| 03-01-03 | 01 | 1 | SCHD-07 (store) | T-03-01 | sent_log inserts/reads use parameterized `?` only; UNIQUE backstop; no f-string SQL | unit | `uv run pytest tests/test_scheduler.py::test_sent_log_idempotent tests/test_config.py::test_example_config_loads_cleanly -x` | ✅ test_scheduler.py | ✅ green |
| 03-02-01 | 02 | 1 | SCHD-04 (display) | T-03-04 | 3 new placeholders are whitelist substitution, no eval/str.format | unit | `uv run pytest tests/test_renderer.py::test_new_placeholders_validate tests/test_scheduler.py -x` | ✅ extended | ✅ green |
| 03-02-02 | 02 | 1 | SCHD-04 (display) | T-03-06 | manual send renders empty `{schedule_note}` — no leak / None crash | unit | `uv run pytest tests/test_send_now.py::test_manual_send_schedule_placeholders tests/test_renderer.py::test_canonical_matches_forecast_placeholder_keys -x` | ✅ extended | ✅ green |
| 03-02-03 | 02 | 1 | SCHD-04 (display) | T-03-05 | timing strings are non-secret local times; no key/URL at render boundary | unit | `uv run pytest tests/test_renderer.py::test_compact_template_has_no_emoji tests/test_renderer.py::test_validate_template_passes_all_shipped_templates -x` | ✅ extended | ✅ green |
| 03-03-01 | 03 | 2 | SCHD-06, SCHD-03 | T-03-08 / T-03-09 | catch-up bounded to <90 min today (no quota burst); DST morning send → exactly one slot | unit | `uv run pytest tests/test_scheduler.py::test_catchup_window tests/test_scheduler.py::test_dst_exactly_once tests/test_scheduler.py::test_days_match_agrees_across_week -x` | ✅ test_scheduler.py | ✅ green |
| 03-03-02 | 03 | 2 | SCHD-05, SCHD-07 | T-03-01 / T-03-07 / T-03-08 | record-after-success only (D-07); one fire_slot exception isolated; no appid/webhook in logs | unit | `uv run pytest tests/test_scheduler.py::test_fire_slot_idempotent_double_fire tests/test_scheduler.py::test_jobs_registered_per_location_tz tests/test_scheduler.py::test_fire_slot_isolates_exception tests/test_scheduler.py::test_late_send_note -x` | ✅ test_scheduler.py | ✅ green |
| 03-03-03 | 03 | 2 | SCHD-05 | T-03-10 | `--run` dispatches to run_daemon only after config validates (fail-loud-at-load) | unit | `uv run pytest tests/test_scheduler.py::test_run_flag_dispatches_to_daemon -x && uv run python -c "import weatherbot.cli; import weatherbot.scheduler.daemon"` | ✅ test_scheduler.py | ✅ green |
| 03-04-01 | 04 | 2 | SCHD-04 (DST) | T-03-09 | spring-forward gap slots skipped + aware-instant compare → catch-up planner agrees with live CronTrigger across DST (no phantom/ dropped slot) | unit | `uv run pytest tests/test_scheduler.py::test_dst_transition_band_exactly_once -x` | ✅ test_scheduler.py | ✅ green |
| 03-05-01 | 05 | 2 | SCHD-07 (exactly-once) | T-03-01 / T-03-07 | atomic `claim_slot` (INSERT OR IGNORE + rowcount==1) before send, release-on-failure; parameterized-only; per-job isolation guarded | unit | `uv run pytest tests/test_scheduler.py::test_concurrent_double_fire_delivers_once -x` | ✅ test_scheduler.py | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** 11 tasks (9 original + 2 gap-closure plans 04/05), every task carries an
`<automated>` verify — no 3 consecutive tasks without an automated check (in fact zero gaps). 03-01-01
pairs a blocking-human legitimacy checkpoint with an automated import assertion. Plans 04 (DST
transition-band) and 05 (atomic exactly-once claim) are TDD gap-closure pairs whose shipping tests
(`test_dst_transition_band_exactly_once`, `test_concurrent_double_fire_delivers_once`) are green.

---

## Wave 0 Requirements

- [x] `tests/test_scheduler.py` — NEW, created by **Plan 01 Task 2/3** (days-matrix + sent-log idempotency scaffold); EXTENDED by Plan 02 Task 1 (context unit test), Plan 03 Tasks 1–3 (catch-up window, DST exactly-once, days-match, fire_slot record/idempotent/isolation, per-tz registration, --run dispatch), Plan 04 (DST transition-band) and Plan 05 (concurrent exactly-once). Plan 01 OWNS the file creation. **21 test functions present, all green.**
- [x] `tests/test_config.py` — EXTEND (Plan 01): `test_multiple_schedule_entries` (SCHD-01), `test_bad_days_fails_load` + `test_bad_time_fails_load` (SCHD-02). **All present, green.**
- [x] `tests/test_store.py` — touched by Plan 01 Task 3 (sent_log assertions reuse `_connect`/`tmp_db`). **Present, green.**
- [x] `tests/test_send_now.py` — EXTEND (Plan 02): `test_manual_send_schedule_placeholders`; `_FakeClient`/`_FakeChannel` reused by Plan 03/05. **Present, green.**
- [x] `tests/test_renderer.py` — EXTEND (Plan 02): `test_new_placeholders_validate`, updated `test_canonical_matches_forecast_placeholder_keys`, template-footer substitution. **Present, green.**
- [x] `tests/conftest.py` — NO new fixtures needed; existing `tmp_db`/`load_fixture` cover all scheduling tests (config + sent-log built inline; weather fakes reuse existing One Call fixtures). **Confirmed — no new fixtures added.**
- [x] Framework install: `apscheduler` via Plan 01 Task 1 (`uv add`). `time-machine` not needed — Phase 3 tests inject `now`. **apscheduler imports; suite runs without time-machine.**

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| apscheduler / time-machine package legitimacy | SCHD-(deps) | RESEARCH tagged both `[ASSUMED]` (offline sandbox could not run slopcheck/`pip index versions`); the legitimacy gate requires human PyPI verification before install | Open https://pypi.org/project/APScheduler/ (agronholm, ~10yr, 3.11.x) and https://pypi.org/project/time-machine/ (adamchainz); approve, then the executor runs `uv add` + `uv sync` (Plan 01 Task 1). Automated import assertion follows. |

> The end-to-end "real daemon blocks and fires on a live wall-clock trigger" is intentionally NOT a
> manual gate: per RESEARCH/MVP strategy it is verified WITHOUT wall-clock waits by invoking the
> `fire_slot` callback directly and unit-testing `plan_catchup` with an injected `now_utc`. The
> foreground block/shutdown is asserted via the `--run` dispatch test with `run_daemon` stubbed.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (zero gaps)
- [x] Wave 0 covers all MISSING references (test_scheduler.py created by Plan 01; extensions mapped per plan)
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-10

---

## Validation Audit 2026-06-10

Retroactive Nyquist audit of the executed phase (`/gsd-validate-phase 3`). Full suite green:
**130 passed in ~2.9s** (`uv run pytest -q`). Every test named in the Per-Task Map verified present.

| Metric | Count |
|--------|-------|
| Requirements audited | 7 (SCHD-01..07) |
| COVERED (green) | 7 |
| PARTIAL | 0 |
| MISSING | 0 |
| Gaps found | 0 (test coverage) |
| Resolved | 0 (no tests needed) |
| Escalated | 0 |

**Documentation corrections applied** (no test generation required — coverage was already complete):
- Flipped all 9 original task statuses `⬜ pending → ✅ green` (map was written pre-execution).
- Added rows **03-04-01** (`test_dst_transition_band_exactly_once`, SCHD-04 DST half) and
  **03-05-01** (`test_concurrent_double_fire_delivers_once`, SCHD-07 exactly-once) — the two
  gap-closure plans that shipped after the original map was authored.
- Set `wave_0_complete: true`; checked off all Wave 0 items (test files exist and run green).

**Result:** Phase 3 is Nyquist-compliant — all 7 scheduler requirements have automated verification.
