---
phase: 15
slug: proactive-uv-sunscreen-monitor
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-19
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from 15-RESEARCH.md Architecture Patterns + Decision Points (no explicit
> Validation Architecture section existed; test map inferred from the requirements).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing; `tests/`) + time-machine/clock injection for deterministic tick timing |
| **Config file** | `pyproject.toml` (project uses `uv`) |
| **Quick run command** | `uv run pytest tests/test_uv_monitor.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_uv_monitor.py -x`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| — | — | — | UV-04 | — | intraday monitor tick reuses `compute_uv`, no extra/persisted fetch, well under API budget | unit | `uv run pytest tests/test_uv_monitor.py -k "tick or no_persist" -x` | ❌ W0 | ⬜ pending |
| — | — | — | UV-05 | — | three decision branches (pre-warn / crossing-or-already-high / all-clear) fire correctly; dedup once/day/location | unit | `uv run pytest tests/test_uv_monitor.py -k "prewarn or crossing or dedup" -x` | ❌ W0 | ⬜ pending |
| — | — | — | UV-05 | — | daylight-only + active-today gate (reuse `_fires_on`); no fire outside the window | unit | `uv run pytest tests/test_uv_monitor.py -k "daylight or active" -x` | ❌ W0 | ⬜ pending |
| — | — | — | UV-06 | — | monitor tick failure-isolated: a raising tick logs+returns, never crashes the scheduler or gates/delays a briefing | unit | `uv run pytest tests/test_uv_monitor.py -k isolation -x` | ❌ W0 | ⬜ pending |
| — | — | — | UV-06 | — | dedup store reads/writes only the uv-alert dedup record; no time-series pollution | unit + spy | `uv run pytest tests/test_uv_monitor.py -k "no_pollution or store" -x` | ❌ W0 (reuse Phase-6 store spy) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_uv_monitor.py` — covers UV-04/05/06 (tick decision branches, dedup once/day/location, daylight+active gate, failure isolation, no-persist/no-pollution)
- [ ] **Clock-controlled fixtures** — reuse the Phase-14 `hourly[].uvi` UV fixtures (uvcross / uvbelow / highuv) with injected `now` to land ticks before/at/after the crossing and pre-warn lead.
- [ ] Dedup-store fixtures — model the durable "prior alerts for location/day" set (`record_alert`-shaped) per DP-1.
- [ ] Extend `tests/test_scheduler.py` (or equivalent) — monitor job registers on an IntervalTrigger and a raising tick does not stop the scheduler.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live proactive UV alert on host `yahir-mint` over a real daylight crossing | UV-04, UV-05, UV-06 | Real intraday wall-clock + live OpenWeather data + restarted daemon; cannot be confirmed by fixtures | `systemctl restart weatherbot`, let the monitor run through a real daylight UV crossing, confirm the pre-warn + crossing alerts fire at most once/day/location and the briefing is unaffected |

*Automated tests cover all decision/dedup/gate/isolation logic with injected clocks; only the live daylight crossing is manual.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-19
