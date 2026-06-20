---
phase: 12
slug: command-registry-read-only-command-surface
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-18
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (+ time-machine 2.16 for clock control) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=tests, pythonpath=.) |
| **Quick run command** | `uv run pytest tests/test_command.py tests/test_bot.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~20 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_registry.py tests/test_command.py -x`
- **After every plan wave:** Run `uv run pytest tests/test_bot.py tests/test_command_views.py tests/test_status.py tests/test_cli.py`
- **Before `/gsd-verify-work`:** Full suite (`uv run pytest`) must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01 | 01 | 1 | CMD-09 | — | help auto-generated from one registry list | unit | `uv run pytest tests/test_registry.py -k help` | ❌ W0 (`test_registry.py`) | ⬜ pending |
| 12-01 | 01 | 1 | CMD-16 / D-06 | T-12-SC | widened `exclude` keeps `hourly`, trims `minutely`; readers don't write | unit | `uv run pytest tests/test_client.py tests/test_store.py` | ❌ W0 | ⬜ pending |
| 12-02 | 02 | 2 | CMD-10 | T-12-02 | `alerts <loc>` reads `alerts[]` only | unit | `uv run pytest tests/test_command_views.py -k alerts` | ❌ W0 | ⬜ pending |
| 12-02 | 02 | 2 | CMD-13 | T-12-02 | `sun <loc>` sunrise/sunset local time | unit | `uv run pytest tests/test_command_views.py -k sun` | ❌ W0 | ⬜ pending |
| 12-02 | 02 | 2 | CMD-14 | T-12-02 | `wind <loc>` speed + compass direction | unit | `uv run pytest tests/test_command_views.py -k wind` | ❌ W0 | ⬜ pending |
| 12-02 | 02 | 2 | CMD-15 | T-12-02 | `next-cloudy <loc>` hourly+daily, configurable threshold | unit | `uv run pytest tests/test_command_views.py -k cloudy` | ❌ W0 | ⬜ pending |
| 12-02 | 02 | 2 | CMD-11 | T-12-02 | `locations` lists configured names, no fetch | unit | `uv run pytest tests/test_command_views.py -k locations` | ❌ W0 | ⬜ pending |
| 12-02 | 02 | 2 | CMD-12 | T-12-10 | `status` read-only DaemonState (next-fire/uptime/liveness/last-briefing) | unit | `uv run pytest tests/test_status.py` | ❌ W0 | ⬜ pending |
| 12-03 | 03 | 3 | CMD-16 | T-12-13/14 | guard ladder + non-propagating isolation; zero store writes | unit | `uv run pytest tests/test_bot.py -k "ladder or isolation"` + zero-write spy | ⚠️ extend `tests/test_bot.py` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_registry.py` — covers CMD-09 (help auto-generation + grouping; registry/CLI/Discord derive-from-one-list invariant)
- [ ] `tests/test_command_views.py` — covers CMD-10/13/14/15 (payload-reading handlers; extend with `next-cloudy` threshold + hourly-present cases)
- [ ] `tests/test_status.py` — covers CMD-12 (DaemonState read: next-fire, uptime, liveness, last-briefing via new `read_heartbeat`)
- [ ] Extend `tests/test_bot.py` — registry-driven dispatch keeps the guard ladder + non-propagating isolation (CMD-16)
- [ ] Extend the Phase-6 zero-store-writes spy to cover every new handler (SC#5 / D-06)
- [ ] `tests/test_store.py` — add `read_heartbeat`/`read_health` reader tests
- [ ] `tests/test_client.py` — assert the widened `exclude` keeps `hourly` (and still trims `minutely`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live Discord command surface on host `yahir-mint` | CMD-09..16 | New Python modules don't hot-reload; UAT touches the live daemon | `systemctl restart weatherbot`, then issue each command in Discord and confirm the read-only views render |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-18
