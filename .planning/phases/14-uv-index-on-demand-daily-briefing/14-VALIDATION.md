---
phase: 14
slug: uv-index-on-demand-daily-briefing
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-19
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing; `tests/` with fixtures) |
| **Config file** | `pyproject.toml` (project uses `uv`) |
| **Quick run command** | `uv run pytest tests/test_uv.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~25 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_uv.py -x`
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| — | — | — | UV-03 | — | `[uv]` threshold/lead loads, validates, hot-reloads; unknown key fails loud | unit | `uv run pytest tests/test_config_uv.py -x` | ❌ W0 | ⬜ pending |
| — | — | — | UV-02 | — | compute_uv: crossing interpolation, stays-below, window, peak, category | unit | `uv run pytest tests/test_uv.py -x` | ❌ W0 | ⬜ pending |
| — | — | — | UV-02 | — | UV tokens render in briefing; CANONICAL ↔ placeholders lockstep | unit | `uv run pytest tests/test_models.py tests/test_renderer.py -x` | ✅ extend | ⬜ pending |
| — | — | — | UV-01/02 | — | sunscreen hint reads configured threshold (not literal 6) | unit | `uv run pytest tests/test_models.py -k hint -x` | ✅ extend | ⬜ pending |
| — | — | — | UV-01 | — | `uv <loc>` command (CLI + Discord) returns summary + hourly line via read-only core | unit/integration | `uv run pytest tests/test_interactive*.py -x` | ✅ extend (Phase-12 registry) | ⬜ pending |
| — | — | — | UV-02 | — | no extra API call; hourly kept via exclude change | unit | `uv run pytest tests/test_client.py -x` | ✅ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] **Fixtures with `hourly[]`** — the critical Wave-0 deliverable: a "UV crosses 6 mid-morning" fixture, a "stays below threshold all day" fixture, and `hourly[]` added to `onecall_imperial_highuv.json`. No UV interpolation test can exist without these.
- [ ] `tests/test_uv.py` — UV-02 compute_uv math (up-cross, down-cross, already-above-at-sunrise, never-crosses, multi-peak, missing-sunrise fallback, category boundaries)
- [ ] `tests/test_config_uv.py` — UV-03 (`[uv]` load/validate/reload/unknown-key)
- [ ] Extend `tests/test_models.py` (UV placeholders + threshold-driven hint), `tests/test_renderer.py` (UV tokens in CANONICAL), `tests/test_client.py` (exclude no longer drops hourly)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live `uv <loc>` on Discord + CLI and UV section in a live daily briefing on host `yahir-mint` | UV-01, UV-02, UV-03 | New modules + the UV briefing section load only on daemon restart; live config/API | `systemctl restart weatherbot`, run `uv <loc>` on Discord + CLI, confirm the next daily briefing carries current UV / today's max UV / sunscreen-crossing time |

*Automated tests cover all UV math, rendering, config, and read-only command logic; only live-daemon delivery is manual.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-19
