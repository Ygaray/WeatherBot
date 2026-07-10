---
phase: 31
slug: send-atomicity-exactly-once-persistence-robustness
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-10
---

# Phase 31 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (via uv) |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest tests/test_daemon.py tests/test_store.py -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~30–60 seconds |

---

## Sampling Rate

- **After every task commit:** Run the quick run command scoped to the touched module.
- **After every plan wave:** Run the full suite command.
- **Before `/gsd-verify-work`:** Full suite must be green.
- **Max feedback latency:** ~60 seconds.

---

## Per-Task Verification Map

> Populated by the planner / Nyquist auditor from PLAN.md task IDs. Every
> requirement below MUST map to at least one automated verification.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | 01 | 1 | HARD-DELIV-01 | — | Post-delivery DB error never releases the won claim; no duplicate briefing, no false internal_error | unit | `uv run pytest tests/test_daemon.py -k atomicity -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | HARD-DELIV-02 | — | Forecast-slot ok=False is detected → failure streak / dead-slot alert | unit | `uv run pytest tests/test_daemon.py -k forecast_fail -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | HARD-DELIV-03 | — | Delivery-only retry reuses the fetched payload (no re-fetch) | unit | `uv run pytest tests/test_send_now.py -q` | ❌ W0 | ⬜ pending |
| TBD | 01 | 1 | HARD-DELIV-04 | — | Discord 401/403 → auth_failed, retry short-circuits | unit | `uv run pytest tests/test_daemon.py -k auth -q` | ❌ W0 | ⬜ pending |
| TBD | 02 | 1 | HARD-STORE-01 | — | Multi-step store writes are atomic (single transaction) | unit | `uv run pytest tests/test_store.py -k atomic -q` | ❌ W0 | ⬜ pending |
| TBD | 02 | 1 | HARD-STORE-02 | — | SQLite opens WAL + busy_timeout; reads take no write lock | unit | `uv run pytest tests/test_store.py -k concurrency -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_daemon.py` — reproduce-first F01 duplicate-send test (inject OperationalError into `resolve_alert`/`stamp_success` after a successful `send_now`); forecast ok=False detection; auth-classification test.
- [ ] `tests/test_store.py` — WAL/busy_timeout assertion (`PRAGMA journal_mode`/`busy_timeout`), read-takes-no-write-lock, atomic multi-step write.
- [ ] `tests/test_send_now.py` — retry-reuses-payload (no second fetch on delivery-only failure); keep existing Retry-After tests green (D-03 open question A1).
- [ ] Existing pytest infrastructure covers the framework — no install needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| WAL journal on the live systemd DB file | HARD-STORE-02 | Live daemon owns the real SQLite file; journal-mode change needs a clean daemon restart on host `yahir-mint` | After deploy: restart service, then `PRAGMA journal_mode;` on the live DB returns `wal`; confirm `-wal`/`-shm` sidecars appear. (Deferred Gate-2 milestone obligation.) |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
