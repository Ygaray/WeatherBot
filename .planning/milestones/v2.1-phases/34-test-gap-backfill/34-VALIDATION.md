---
phase: 34
slug: test-gap-backfill
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-13
---

# Phase 34 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + syrupy 5.3.4 + time-machine 2.16 (`pyproject.toml [dependency-groups] dev`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| **Quick run command** | `uv run pytest tests/test_<module>.py -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~30 seconds (869 tests baseline, exit 0) |

> **Known quirk:** the suite prints "2 snapshots failed" but exits 0 — pre-existing syrupy report noise, not a golden diff. **Trust the exit code + `.ambr` diff**, never the snapshot summary line.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_<edited_module>.py -x -q`
- **After every plan wave:** Run `uv run pytest -q` (full suite; trust exit code over the snapshot report line)
- **Before `/gsd-verify-work`:** Full suite must be green (exit 0)
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

Each finding → one observable signal (the Nyquist sampling point). Task IDs are indicative; the planner assigns final IDs/waves.

| Finding | Req | Type | Secure/Correct Behavior (observable) | Automated Command |
|---------|-----|------|--------------------------------------|-------------------|
| F106 | HARD-TEST-01 | concurrency (real threads) | `len(channel.sent_text) == 1` AND one `sent_log` row AND `errors == []`; meta-guard: weakened SELECT-then-INSERT claim → 2 deliveries (test goes red) | `uv run pytest tests/test_scheduler.py -k concurrent -x` |
| F114 | HARD-TEST-01 | unit (store row) | after a bare tick: `last_tick_utc is not None` AND `last_success_utc is None` | `uv run pytest tests/test_reliability.py -k heartbeat -x` |
| F112 | HARD-TEST-01 | unit (wait value) | within-burst wait bounded `85.71 <= wait <= 128.57` (`step` … `step*1.5`), not the loose `< 150.0` | `uv run pytest tests/test_reliability.py -k two_burst_wait -x` |
| F115 | HARD-TEST-01 | unit (cache key) | distinct `id != name`: two `"Cabin"` lookups → 1 fetch (collapse on `.id`); id-mismatch → no hit | `uv run pytest tests/test_cache.py -x` |
| F116 | HARD-TEST-01 | unit (order log) | `order.index("register") < order.index("remove:gone")` (register-before-remove) | `uv run pytest tests/test_reload_engine.py -k committed -x` |
| F108 | HARD-TEST-02 | integration (fire_slot) | `sent_log.location_name == "loc-7"` (the id, not the name); `plan_catchup`/dedup key on `.id` | `uv run pytest tests/test_scheduler.py -k rename -x` |
| F110 | HARD-TEST-02 | unit (wait value) | Retry-After 429 on `attempt==BURST_SIZE` → wait `== 120` (cap), not `2700` (mid-pause collapse) | `uv run pytest tests/test_reliability.py -k retry_after -x` |
| F107 | HARD-TEST-02 | unit (model) | dt-skewed payloads pair metric/imperial by `dt`, or degrade to None — never mispair | `uv run pytest tests/test_models.py -k dt_pair -x` |
| F109 | HARD-TEST-02 | unit (model) | today-not-at-`daily[0]` → selector still picks today's high/low (⚠ D-07 watchpoint) | `uv run pytest tests/test_models.py -k daily0 -x` |
| F111 | HARD-TEST-02 | unit (multiday) | weekend whole-block-past → next-week Fri/Sat/Sun (or horizon notice), no IndexError | `uv run pytest tests/test_multiday.py -k weekend -x` |
| F113 | HARD-TEST-02 | unit (multiday) | `dt=None` entry skipped in the date-index map; no TypeError | `uv run pytest tests/test_multiday.py -k null_dt -x` |
| F14 | HARD-TEST-02 | unit (catchup) | `plan_catchup` at 00:15 returns a yesterday-dated MissedSlot for a 23:45 slot; dedup → exactly one | `uv run pytest tests/test_scheduler.py -k catchup_midnight -x` |
| F37/F63/F01 | HARD-TEST-02 | unit (store) | a mid-persist raise → 0 committed `weather_onecall` rows (both-or-neither atomicity); no re-fireable slot | `uv run pytest tests/test_store.py -k atomic -x` |

*Status legend: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

*Existing infrastructure covers all phase requirements.* All six target test files exist
(`test_scheduler.py`, `test_reliability.py`, `test_models.py`, `test_multiday.py`,
`test_cache.py`, `test_reload_engine.py`) plus `test_store.py`; `conftest.py` fixtures
(`tmp_db` file-backed, `load_fixture`) exist; the real-thread harness
(`tests/test_config_holder.py::test_concurrent_read_swap_safe`) exists to copy; recorded
OpenWeather JSON fixtures (dt-skew, 8-day) exist. No framework install, no new fixture module.

- [ ] (optional) shared `threading.Barrier` helper in `conftest.py` — Claude's Discretion (D-01), not required.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Pre-fix **red** demonstration for F106, F114, F112 (SC-3 / D-06) | HARD-TEST-01 | Requires temporarily reverting/weakening the shipped fix, which cannot live in the committed suite | In the Gate-1 self-UAT log: `git stash`/local shim to weaken the fix (e.g. claim_slot→SELECT-then-INSERT, drop the F112 tightening), run the new test, capture **red**, restore, capture **green**. No mutation-testing dependency added. |

*All other phase behaviors have automated verification (assertion-by-construction, D-05).*

---

## Validation Sign-Off

- [ ] All findings have an `<automated>` verify command (table above)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (none — existing infra)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
