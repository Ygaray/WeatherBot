---
phase: 14
slug: uv-index-on-demand-daily-briefing
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-19
audited: 2026-06-23
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
| — | 14-01 | W0 | UV-03 | T-14-01/02 | `[uv]` threshold/lead loads, validates, hot-reloads; unknown key fails loud | unit | `uv run pytest tests/test_config_uv.py -x` | ✅ 10 tests (load/range/fail-loud/frozen) | ✅ green |
| — | 14-02 | W0 | UV-02 | T-14-04/05 | compute_uv: crossing interpolation, stays-below, window, peak, category | unit | `uv run pytest tests/test_uv.py -x` | ✅ 20+ tests (bands, interp, stays-below, peak) | ✅ green |
| — | 14-03 | W0 | UV-02 | T-14-06/07 | UV tokens render in briefing; CANONICAL ↔ placeholders lockstep; degrades w/o raising | unit | `uv run pytest tests/test_models.py tests/test_renderer.py -k uv` | ✅ `test_uv_tokens_lockstep_canonical_and_placeholders`, `test_uv_malformed_hourly_does_not_crash_briefing` (+6) | ✅ green |
| — | 14-03 | W0 | UV-01/02 | T-14-08 | sunscreen hint reads configured threshold (not literal 6) | unit | `uv run pytest tests/test_models.py -k "hint or sunscreen"` | ✅ `test_hints_sunscreen_fires_at_configured_lower_threshold`, `test_from_payloads_threads_uv_threshold_into_hint` (+3) | ✅ green |
| — | 14-04 | W0 | UV-01 | T-14-09/10/11/12 | `uv <loc>` (CLI + Discord) returns summary + hourly line via read-only core; isolated; threaded threshold | unit/integration | `uv run pytest tests/test_command_views.py tests/test_bot.py tests/test_cli.py -k uv` | ✅ `test_uv_crossing_reports_summary_and_hourly_line`, `test_raising_uv_handler_is_isolated`, `test_cli_uv_unknown_location_exits_1` (+8) | ✅ green |
| — | 14-01 | W0 | UV-02 | — | no extra API call; hourly kept via exclude change | unit | `uv run pytest tests/test_client.py -k hourly` | ✅ `test_fetch_onecall_keeps_hourly_regression_canary` + handler `test_uv_handler_reads_only_retained_payload` | ✅ green |

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

---

## Validation Audit 2026-06-23

Retroactive State-A audit of the plan-time contract against the executed codebase. All
Wave-0 test assets (incl. the `hourly[]` crossing / stays-below fixtures) now exist; every
UV requirement maps to named, green tests. Phase-14 subset: **208 passed, 0 failed**
(`uv run pytest` over the 8 UV-touching test files, ~2s); full suite green (575 passed).

| Metric | Count |
|--------|-------|
| Requirements audited | 3 (UV-01, UV-02, UV-03) across 6 task rows |
| COVERED (green) | 6/6 rows |
| PARTIAL | 0 |
| MISSING | 0 |
| Gaps found | 0 |
| Resolved | 0 (none needed) |
| Escalated | 0 |

No gaps — no auditor spawn or test generation required. `nyquist_compliant: true` confirmed
against reality. Briefing-spine isolation is explicitly tested: `test_uv_malformed_hourly_does_not_crash_briefing`
and `test_uv_missing_hourly_degrades_without_raising` (T-14-07), the configured-threshold hint
(`test_hints_sunscreen_fires_at_configured_lower_threshold`, T-14-08), and the read-only/isolated
command (`test_raising_uv_handler_is_isolated`, T-14-10). Only the live-daemon `uv <loc>` + UV
briefing section on host `yahir-mint` remains manual (already confirmed per the deferred-UAT commits).
