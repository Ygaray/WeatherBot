---
phase: 23
slug: scheduler-engine-occurrencestore-jobstore-seam
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-27
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `23-RESEARCH.md` § Validation Architecture. This is a behavior-preserving
> extraction: the Phase-21 golden suite + the full ~740-test suite are the byte-identical oracle.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (+ syrupy 5.3.4 goldens, time-machine frozen clock) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_import_hygiene.py tests/test_golden_schedule.py tests/test_golden_db.py -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~quick <10s · full ~60s (740+ tests, zero-flake) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_import_hygiene.py tests/test_golden_schedule.py tests/test_golden_db.py -x -q`
- **After every plan wave:** Run `uv run pytest -q` (full suite)
- **Before `/gsd-verify-work`:** Full suite green AND every Phase-21 golden byte-identical (any non-empty snapshot diff is a failure to investigate, never rubber-stamped)
- **Max feedback latency:** ~10 seconds (quick) / ~60 seconds (full)

---

## Per-Task Verification Map

> Task IDs are assigned by the planner; this map is completed against the finalized PLAN.md
> task list during execution. The Requirement→Test rows below are the authoritative coverage
> contract every task must trace back to.

| Req | Behavior | Test Type | Automated Command | File Exists |
|-----|----------|-----------|-------------------|-------------|
| SEAM-02 | `engine.register` produces byte-identical schedule plan `(job_id, str(trigger), next_run_time)` | golden | `uv run pytest tests/test_golden_schedule.py -q` | ✅ (Phase 21) |
| SEAM-02 | Registered job OPTIONS (`misfire_grace_time=None`, `coalesce=True`, `max_instances=1`) survive centralization | unit (read-back on `scheduler.get_jobs()`) | `uv run pytest tests/test_scheduler_engine.py -q` | ❌ W0 |
| SEAM-02 | Exactly-once `sent_log` rows + claim/release lifecycle byte-identical | golden + unit | `uv run pytest tests/test_golden_db.py tests/test_store.py -q` | ✅ (Phase 21) |
| SEAM-02 | DST / catch-up + across-reload unchanged (`plan_catchup` `was_sent` reader rebind) | golden | `uv run pytest tests/test_scheduler.py tests/test_reload.py -q` | ✅ (Phase 21) |
| SEAM-02 | `engine.list_live_ids()` / `engine.remove()` match raw `get_jobs()` / `remove_job` | unit | `uv run pytest tests/test_scheduler_engine.py -q` | ❌ W0 |
| SEAM-03 | `JobStore` / `OccurrenceStore` Protocols are `runtime_checkable`, structurally satisfied, no subclassing | unit | `uv run pytest tests/test_ports.py -q` | ❌ W0 |
| PKG-01 | Module imports zero app code; no weather noun in new `scheduler`/`ports` signatures | gate | `uv run pytest tests/test_import_hygiene.py -q` | ✅ (Phase 22, auto-scales) |
| BHV-01/02 | Full suite + all goldens green at phase boundary | suite | `uv run pytest -q` | ✅ |

*Status legend: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_scheduler_engine.py` — SEAM-02 `register`/`remove`/`list_live_ids` + job-OPTIONS read-back assert (Pitfall 1/2). Analog: `tests/test_reliability.py::test_heartbeat_job_registered_with_slots`.
- [ ] `tests/test_ports.py` — SEAM-03 `OccurrenceStore`/`JobStore` `runtime_checkable` + structural-satisfaction asserts (Pitfall 6). No existing analog (AlertSink shipped untested); write from the Protocol contract directly.
- [ ] Wave-0 verify: `[tool.coverage.run] source` includes the relocated module packages (Open Q2; coverage is non-gating per Phase-21 D-08).
- [ ] Wave-0 confirm: APScheduler 3.11.2 `add_job` default `max_instances == 1` via a read-back assert on a real briefing job (Pitfall 2 — centralization is identical only because the default equals 1).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live daemon restart-catch-up on `yahir-mint` | SEAM-02 | Touches the live systemd service / real clock | Deferred Gate-2 milestone obligation; the restart-catch-up goldens (`tests/test_scheduler.py` + `tests/test_reload.py`) are the automated oracle for the mechanism. |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`test_scheduler_engine.py`, `test_ports.py`)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
