---
phase: 3
slug: always-on-scheduler
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-10
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
| 03-01-01 | 01 | 1 | SCHD-(deps) | T-03-SC | apscheduler verified legitimate (PyPI) before install; no 4.x | manual+auto | `uv run python -c "import apscheduler; print(apscheduler.__version__)"` | ✅ existing import | ⬜ pending |
| 03-01-02 | 01 | 1 | SCHD-01/02/03 | T-03-02 | bad days/time token fails loud at config load (whitelist validators) | unit | `uv run pytest tests/test_scheduler.py::test_days_parsing_matrix tests/test_config.py::test_multiple_schedule_entries tests/test_config.py::test_bad_days_fails_load -x` | ❌ W0 (this task creates) | ⬜ pending |
| 03-01-03 | 01 | 1 | SCHD-07 (store) | T-03-01 | sent_log inserts/reads use parameterized `?` only; UNIQUE backstop; no f-string SQL | unit | `uv run pytest tests/test_scheduler.py::test_sent_log_idempotent tests/test_config.py::test_example_config_loads_cleanly -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 1 | SCHD-04 (display) | T-03-04 | 3 new placeholders are whitelist substitution, no eval/str.format | unit | `uv run pytest tests/test_renderer.py::test_new_placeholders_validate tests/test_scheduler.py -x` | ⚠️ extend existing | ⬜ pending |
| 03-02-02 | 02 | 1 | SCHD-04 (display) | T-03-06 | manual send renders empty `{schedule_note}` — no leak / None crash | unit | `uv run pytest tests/test_send_now.py::test_manual_send_schedule_placeholders tests/test_renderer.py::test_canonical_matches_forecast_placeholder_keys -x` | ⚠️ extend existing | ⬜ pending |
| 03-02-03 | 02 | 1 | SCHD-04 (display) | T-03-05 | timing strings are non-secret local times; no key/URL at render boundary | unit | `uv run pytest tests/test_renderer.py::test_compact_template_has_no_emoji tests/test_renderer.py::test_validate_template_passes_all_shipped_templates -x` | ⚠️ extend existing | ⬜ pending |
| 03-03-01 | 03 | 2 | SCHD-06, SCHD-03 | T-03-08 / T-03-09 | catch-up bounded to <90 min today (no quota burst); DST morning send → exactly one slot | unit | `uv run pytest tests/test_scheduler.py::test_catchup_window tests/test_scheduler.py::test_dst_exactly_once tests/test_scheduler.py::test_days_match_agrees_across_week -x` | ❌ W0 (extends 03-01 scaffold) | ⬜ pending |
| 03-03-02 | 03 | 2 | SCHD-05, SCHD-07 | T-03-01 / T-03-07 / T-03-08 | record-after-success only (D-07); one fire_slot exception isolated; no appid/webhook in logs | unit | `uv run pytest tests/test_scheduler.py::test_fire_slot_idempotent_double_fire tests/test_scheduler.py::test_jobs_registered_per_location_tz tests/test_scheduler.py::test_fire_slot_isolates_exception tests/test_scheduler.py::test_late_send_note -x` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 2 | SCHD-05 | T-03-10 | `--run` dispatches to run_daemon only after config validates (fail-loud-at-load) | unit | `uv run pytest tests/test_scheduler.py::test_run_flag_dispatches_to_daemon -x && uv run python -c "import weatherbot.cli; import weatherbot.scheduler.daemon"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** 9 tasks, every task carries an `<automated>` verify — no 3 consecutive tasks
without an automated check (in fact zero gaps). 03-01-01 pairs a blocking-human legitimacy checkpoint
with an automated import assertion.

---

## Wave 0 Requirements

- [ ] `tests/test_scheduler.py` — NEW, created by **Plan 01 Task 2/3** (days-matrix + sent-log idempotency scaffold); EXTENDED by Plan 02 Task 1 (context unit test) and Plan 03 Tasks 1–3 (catch-up window, DST exactly-once, days-match, fire_slot record/idempotent/isolation, per-tz registration, --run dispatch). Plan 01 OWNS the file creation.
- [ ] `tests/test_config.py` — EXTEND (Plan 01): `test_multiple_schedule_entries` (SCHD-01), `test_bad_days_fails_load` + `test_bad_time_fails_load` (SCHD-02).
- [ ] `tests/test_store.py` — touched by Plan 01 Task 3 (sent_log assertions reuse `_connect`/`tmp_db`).
- [ ] `tests/test_send_now.py` — EXTEND (Plan 02): `test_manual_send_schedule_placeholders`; `_FakeClient`/`_FakeChannel` reused by Plan 03.
- [ ] `tests/test_renderer.py` — EXTEND (Plan 02): `test_new_placeholders_validate`, updated `test_canonical_matches_forecast_placeholder_keys`, template-footer substitution.
- [ ] `tests/conftest.py` — NO new fixtures needed; existing `tmp_db`/`load_fixture` cover all scheduling tests (config + sent-log built inline; weather fakes reuse existing One Call fixtures).
- [ ] Framework install: `apscheduler` via Plan 01 Task 1 (`uv add`). `time-machine` (dev) only if a test exercises APScheduler's OWN next-fire across a transition — most Phase 3 tests inject `now` and need neither, so it is OPTIONAL.

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
