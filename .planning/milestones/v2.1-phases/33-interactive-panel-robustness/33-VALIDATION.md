---
phase: 33
slug: interactive-panel-robustness
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-12
---

# Phase 33 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + syrupy 5.3.4 (golden `.ambr` snapshots) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=`["tests"]`, pythonpath=`["."]`, addopts=`-ra`) |
| **Quick run command** | `uv run pytest tests/test_dispatch.py tests/test_cache.py tests/test_panel.py tests/test_models.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~15 seconds (in-repo harnesses; no live gateway or network) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_<touched>.py -x`
- **After every plan wave:** Run `uv run pytest` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

> **Syrupy quirk:** trust the exit code + the `.ambr` diff, NOT the "N snapshots failed" banner — the suite can print "N snapshots failed" but exit 0 (MEMORY: pytest-snapshot-report-quirk).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 33-01-01 | 01 | 1 | HARD-UI-01 | — | Bare `!weather` PRE-fix reproduces the crash → generic error (verify-first, D-02) | unit | `uv run pytest tests/test_bot.py -k bare_weather_crashes -x` | ❌ W0 | ⬜ pending |
| 33-01-02 | 01 | 1 | HARD-UI-01 | — | Bare `!weather` POST-fix → default-location embed (`config.locations[0]`), no user string reaches the flag parser (ASVS V5) | unit | `uv run pytest tests/test_bot.py -k bare_weather_default -x` | ❌ W0 | ⬜ pending |
| 33-01-02 | 01 | 1 | HARD-UI-01 | — | All six bare location commands (`weather/sun/wind/alerts/uv/next-cloudy`) resolve the default | unit | `uv run pytest tests/test_dispatch.py -k takes_location_default -x` | ❌ W0 | ⬜ pending |
| 33-01-02 | 01 | 1 | HARD-UI-03 | — | D-05/F27: bare → `📍 Toronto (default)`; named → `📍 London`; inbound shows 📍 | unit/golden | `uv run pytest tests/test_golden_embeds.py -k default_marker -x` | ❌ W0 | ⬜ pending |
| 33-02-01 | 02 | 1 | HARD-UI-02 | T-33-02 | F13: in-flight fetch that started before `invalidate()` does NOT re-populate (serve current config, not a pre-reload snapshot) | unit | `uv run pytest tests/test_cache.py -k stale_repopulate_rejected -x` | ❌ W0 | ⬜ pending |
| 33-02-02 | 02 | 1 | HARD-UI-02 | T-33-02 | Cache bounding: heavy forecast/flag entries never evict the plain `!weather` entry | unit | `uv run pytest tests/test_cache.py -k plain_entry_protected -x` | ❌ W0 | ⬜ pending |
| 33-03-02 | 03 | 1 | HARD-UI-02 | T-33-03 | F17: `_on_applied` invalidates cache BEFORE `channel.send` (no stale coords served during a slow post) | unit | `uv run pytest tests/test_lifecycle_module.py -k invalidate_before_send -x` | ❌ W0 | ⬜ pending |
| 33-03-02 | 03 | 1 | HARD-UI-02 | T-33-03 | F22: renamed/removed selected location reconciled on reload (no stale `resolve_location` reject) | unit | `uv run pytest tests/test_lifecycle_module.py -k selection_reconcile -x` | ❌ W0 | ⬜ pending |
| 33-04-02 | 04 | 1 | HARD-UI-02 | T-33-04 | F23: zero-locations reload → panel degrades (no recursion, `_build_clone_view` non-raising) — recoverable, never a swallowed freeze | unit | `uv run pytest tests/test_panel.py -k empty_locations_recover -x` | ❌ W0 | ⬜ pending |
| 33-04-02 | 04 | 1 | HARD-UI-02 | T-33-04 | F24: failed/expired ack rolls back selection (not silently advanced) | unit | `uv run pytest tests/test_panel.py -k ack_failure_rollback -x` | ❌ W0 | ⬜ pending |
| 33-05-02 | 05 | 1 | HARD-UI-03 | — | F11/F107: metric-missing daily → imperial high preserved (not current temp) | unit | `uv run pytest tests/test_models.py -k metric_missing_keeps_imperial -x` | ❌ W0 | ⬜ pending |
| 33-05-02 | 05 | 1 | HARD-UI-03 | — | F107: briefing dt-pairs imperial/metric daily by dt, not index (skewed payload) | unit | `uv run pytest tests/test_models.py -k dt_paired_briefing -x` | ❌ W0 | ⬜ pending |
| 33-06-02 | 06 | 1 | HARD-UI-03 | T-33-06 | F28: forecast header appears exactly once (embed + CLI) | golden | `uv run pytest tests/test_forecast_render.py tests/test_golden_embeds.py --snapshot-update` then review `.ambr` | ✅ (regen) | ⬜ pending |
| 33-06-02 | 06 | 1 | HARD-UI-03 | — | Empty-token render leaves no trailing blank line | unit/golden | `uv run pytest tests/test_forecast_render.py -k empty_token -x` | ❌ W0 | ⬜ pending |
| 33-06-02 | 06 | 1 | HARD-UI-03 | T-33-06 | D-07: timestamps render `09:00`, not raw ISO (no internal-representation leak) | unit | `uv run pytest tests/test_command_views.py -k humanized_timestamp -x` | ❌ W0 | ⬜ pending |
| 33-06-02 | 06 | 1 | HARD-UI-03 | — | D-06: out-of-today label renders `Thu Jul 17` | unit/golden | `uv run pytest tests/test_forecast_render.py -k date_label -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Each plan's Task 1 is the test-shaped RED regression that fails pre-fix / passes post-fix (test-shaped-fix convention inherited from Phase 32; the comprehensive backfill is Phase 34):

- [ ] `tests/test_bot.py` — F02 bare-command crash (RED) + default-resolution (GREEN); covers HARD-UI-01 (Plan 01 Task 1)
- [ ] `tests/test_dispatch.py` — `takes_location` + `arg=None` forces fetch with the default name; covers HARD-UI-01 (Plan 01 Task 1)
- [ ] `tests/test_cache.py` — F13 stale-repopulate rejection + cache-bounding plain-entry protection; covers HARD-UI-02 (Plan 02 Task 1)
- [ ] `tests/test_lifecycle_module.py` — F17 invalidate-before-send ordering + F22 selection-reconcile; covers HARD-UI-02 (Plan 03 Task 1)
- [ ] `tests/test_panel.py` — F23 empty-locations recovery + F24 ack-failure rollback; covers HARD-UI-02 (Plan 04 Task 1)
- [ ] `tests/test_models.py` — F11 metric-missing keeps imperial + F107 dt-paired briefing (skewed fixture); covers HARD-UI-03 (Plan 05 Task 1)
- [ ] `tests/fixtures/` — a deliberately dt-SKEWED briefing payload fixture for F107 (existing fixtures are pre-aligned) (Plan 05 Task 1)
- [ ] `tests/test_forecast_render.py` + `tests/test_command_views.py` — F28 dedup (golden regen), empty-token blanks, D-05/06/07 formatting; covers HARD-UI-03 (Plan 06 Task 1)

*Framework already installed — no `uv add` needed. All harnesses (`fake_interaction`, `fake_discord_message`, `load_fixture`, injectable `timer`) already exist in `tests/conftest.py`.*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.* The F02 Discord-surface repro is faithfully harnessed via `on_message` → `dispatch_spec` (the gateway-free `fake_discord_message` factory, conftest.py), the panel interactions via the `fake_interaction` factory, and the off-loop cache writes via the injectable `timer` — no row requires the live gateway or network.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 15s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-12
