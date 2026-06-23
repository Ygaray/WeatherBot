---
phase: 13
slug: multi-day-forecast-templates
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-19
audited: 2026-06-23
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing — `tests/` with `test_models.py`, `test_renderer.py`, `test_scheduler.py`) |
| **Config file** | `pyproject.toml` (project uses `uv`); no separate pytest.ini |
| **Quick run command** | `uv run pytest tests/test_multiday.py tests/test_forecast_render.py -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~20 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_multiday.py tests/test_forecast_render.py -x -q`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| — | 13-01 | W0 | FCAST-01 | T-13-01/02/03 | weekday (Mon–Fri) per-day hi/lo/sky/rain from editable template | unit | `uv run pytest tests/test_multiday.py -k weekday -x` | ✅ 3 tests | ✅ green |
| — | 13-01 | W0 | FCAST-02 | T-13-01/02/03 | weekend (Fri–Sat–Sun) per-day from its own template | unit | `uv run pytest tests/test_multiday.py -k weekend -x` | ✅ `test_weekend_run_returns_fri_sat_sun` | ✅ green |
| — | 13-02 | W0 | FCAST-03 | T-13-04/05 | detailed (default) vs compact variant selection | unit | `uv run pytest tests/test_forecast_render.py -k variant -x` | ✅ `test_render_forecast_compact_variant` | ✅ green |
| — | 13-03 | W0 | FCAST-04 | T-13-07 | `+day`/`-day` flags: append/drop, dedup, calendar-sort, out-of-window notice | unit | `uv run pytest tests/test_flags.py tests/test_multiday.py -k flag -x` | ✅ 16 tests | ✅ green |
| — | 13-04 | W0 | FCAST-05 | T-13-11/16 | on-demand both surfaces; zero store writes | unit + spy | `uv run pytest tests/test_forecast_lookup.py -k "no_store" tests/test_scheduler.py -k writes_no_store` | ✅ `test_forecast_module_imports_no_store`, `test_fire_forecast_slot_posts_and_writes_no_store` | ✅ green |
| — | 13-05 | W0 | FCAST-06 | T-13-15/17/18 | per-location schedule slots register + reconcile churn-free | unit | `uv run pytest tests/test_scheduler.py -k forecast -x` | ✅ 12 tests | ✅ green |
| — | 13-04 | W0 | FCAST-07 | — | reuse `daily[]`, no extra fetch (call count unchanged) | unit | `uv run pytest tests/test_forecast_lookup.py -k no_extra_fetch -x` | ✅ `test_lookup_forecast_no_extra_fetch` | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] **8-element synthetic `daily[]` fixture** — the single most important Wave 0 asset; existing fixtures only carry `daily[0]`. Build with known dates for deterministic window tests.
- [ ] `tests/test_multiday.py` — window/roll-forward/horizon selection (FCAST-01/02/04)
- [ ] `tests/test_forecast_render.py` — forecast token-set validation + detailed/compact render (FCAST-03); covers feels-like hi/lo derivation and typo-fails-loud
- [ ] `tests/test_flags.py` — shared `+day`/`-day`/`+compact` grammar (FCAST-04)
- [ ] `tests/test_forecast_lookup.py` — read-only no-store-write spy + no-extra-fetch assertion (FCAST-05/07); reuse the Phase-6 zero-store-writes spy harness
- [ ] Extend `tests/test_scheduler.py` — forecast job register + reconcile no-op-churn + variant-edit ADD/REMOVE (FCAST-06)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live multi-day forecast on host `yahir-mint` (Discord + CLI + scheduled slot) | FCAST-01..07 | New modules + scheduled slots load only on daemon restart; live config/API | `systemctl restart weatherbot`, request `forecast`/weekday/weekend on Discord + CLI, confirm a scheduled forecast slot fires |

*Automated tests cover all rendering/window/flag/read-only logic; only live-daemon delivery is manual.*

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
Wave-0 test assets now exist; every FCAST requirement maps to named, green tests. Full
suite: **575 passed, 0 failed** (`uv run pytest -q`, ~38s).

| Metric | Count |
|--------|-------|
| Requirements audited | 7 (FCAST-01..07) |
| COVERED (green) | 7 |
| PARTIAL | 0 |
| MISSING | 0 |
| Gaps found | 0 |
| Resolved | 0 (none needed) |
| Escalated | 0 |

No gaps — no auditor spawn or test generation required. `nyquist_compliant: true` confirmed
against reality. Only the live-daemon delivery on host `yahir-mint` remains manual (already
confirmed per the deferred-UAT commits); all rendering/window/flag/read-only/scheduler logic
is automated.
