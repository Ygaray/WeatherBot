---
phase: 18
slug: persistence-summon-lifecycle-restart-durability
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-26
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (`[tool.pytest.ini_options]`, `testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.venv/bin/python -m pytest tests/test_bot.py tests/test_panel.py tests/test_config.py tests/test_models.py -q` |
| **Full suite command** | `.venv/bin/python -m pytest -q` |
| **Estimated runtime** | ~10 seconds (quick) / ~30 seconds (full ~600 tests) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest tests/test_bot.py tests/test_panel.py tests/test_config.py tests/test_models.py -q`
- **After every plan wave:** Run `.venv/bin/python -m pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green, then the live `systemctl restart` UAT on `yahir-mint`
- **Max feedback latency:** ~30 seconds (full suite)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | PANEL-09 | T-18-01 | `[bot]` table requires both keys; unknown key fails loud (`extra="forbid"`) | unit | `.venv/bin/python -m pytest tests/test_models.py tests/test_config.py -k "panel_channel or bot" -x -q` | ❌ W0 | ⬜ pending |
| 18-01-02 | 01 | 1 | PANEL-09 | T-18-02 / T-18-04 | `add_view` in `setup_hook` not `on_ready` (no reconnect duplication); wiring crash can't reach scheduler | unit | `.venv/bin/python -m pytest tests/test_bot.py -k "setup_hook or panel_channel" tests/test_panel.py -k "persistent" -x -q` | ❌ W0 | ⬜ pending |
| 18-01-03 | 01 | 1 | PANEL-09 | T-18-06 (foundation) | marker-strict `_is_owned_panel` (author + `wb:` only); Wave-0 fakes for Plan 02 | unit | `.venv/bin/python -m pytest tests/test_panel.py -k "owned or marker or scan" -x -q` | ❌ W0 | ⬜ pending |
| 18-02-01 | 02 | 2 | PANEL-01 | T-18-05 / T-18-07 / T-18-08 / T-18-09 | operator-gate + preflight refuse-without-orphan + Forbidden backstop + abort-not-crash | unit | `.venv/bin/python -m pytest tests/test_bot.py -k "panel_channel_missing or panel_perms or panel_forbidden" -x -q` | ❌ W0 | ⬜ pending |
| 18-02-02 | 02 | 2 | PANEL-01 | T-18-06 | marker-strict reuse-in-place + delete-extras (exactly one) | unit | `.venv/bin/python -m pytest tests/test_bot.py -k "panel_summon or panel_create or panel_reuse or panel_strays" -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/conftest.py` — an async-iterator `pins()` fake yielding `Message`-shaped mocks; a `Permissions`-shaped fake exposing boolean attrs `view_channel`/`send_messages`/`embed_links`/`read_message_history`/`pin_messages`; `message.edit`/`pin`/`delete`/`send` as `AsyncMock` (created in 18-01-03, consumed by Plan 02).
- [ ] `tests/test_models.py` / `tests/test_config.py` — `panel_channel_id` required-int + `extra="forbid"` fail-loud + happy-path load (18-01-01).
- [ ] `tests/test_bot.py` — `setup_hook` registers `add_view` (not `on_ready`); `build_client`/`BotThread` accept `panel_channel_id` (18-01-02); `!panel` channel-missing-abort, perm-refuse, Forbidden-backstop (18-02-01); find-or-create-one + delete-extras (18-02-02).
- [ ] `tests/test_panel.py` — `PanelView.is_persistent()` True (18-01-02); `_is_owned_panel` positive/negative (18-01-03).
- [ ] Framework install: none needed (pytest 9.0.3 / ruff 0.15.16 present).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| After `systemctl restart weatherbot`, every button + the dropdown on the already-pinned panel still route to callbacks (no "interaction failed") | PANEL-09 SC#1 | Requires a live gateway connection + a real restart of the production daemon; `add_view` re-bind is only observable against the live Discord client | Deploy `panel.py`/`bot.py`/config; `sudo systemctl restart weatherbot`; tap every button + the dropdown on the pinned panel; confirm each routes |
| Select a location → restart → tap → confirm `locations[0]` default | PANEL-09 SC#3 | Default-on-restart selection state is only observable across a real process restart | Select a non-default location; `sudo systemctl restart weatherbot`; tap a location-taking button; confirm it uses `locations[0]` (documented default) |
| Re-`!panel` → exactly one panel remains | PANEL-01 SC#2 | Idempotent reconcile against live pinned state on the host | After restart, run `!panel`; confirm exactly one pinned panel remains, strays removed |

> Gate 2 (deferred, blocks milestone-close): the three live items above run on host `yahir-mint` after one deploy + `sudo systemctl restart weatherbot` (new modules + `setup_hook` + the new `[bot] panel_channel_id` load only on next process start). Tracked as the existing Pending Todo. Gate 1 (autonomous self-UAT) is fully covered by the gateway-free unit suite above.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-26
