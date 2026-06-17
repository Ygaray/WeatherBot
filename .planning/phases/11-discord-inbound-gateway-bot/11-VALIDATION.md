---
phase: 11
slug: discord-inbound-gateway-bot
status: verified
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-16
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (>=9.0.3) + time-machine + unittest.mock (AsyncMock) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`) |
| **Quick run command** | `uv run pytest tests/test_bot.py tests/test_cache.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~20 seconds (no live gateway — handlers called directly) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_bot.py tests/test_cache.py -x` (+ `tests/test_reload.py -k cfg07` for 11-04)
- **After every plan wave:** Run `uv run pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 25 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | CMD-02/06/07/08 | T-11-01 | RED node IDs collect, fail on unbuilt module | unit | `uv run pytest tests/test_bot.py tests/test_cache.py -q` | ✅ | ✅ green |
| 11-01-02 | 01 | 1 | CFG-07 | T-11-01 | cfg07 posting RED contract → now GREEN | unit | `uv run pytest tests/test_reload.py -k cfg07 -q` | ✅ | ✅ green |
| 11-02-02 | 02 | 2 | CMD-02 | T-11-SC/04 | legitimate pinned deps importable | unit | `uv run python -c "import discord, cachetools"` | n/a | ✅ green |
| 11-02-03 | 02 | 2 | CMD-07 | T-11-02/03 | token in .env fail-loud; [bot] extra=forbid, frozen | unit | `uv run pytest tests/test_config.py -k "bot or token or forbid or frozen" -x` | ✅ (test_config.py) | ✅ green |
| 11-03-01 | 03 | 3 | CMD-06 | T-11-06 | repeated same-loc within TTL → one fetch | unit | `uv run pytest tests/test_cache.py -x` | ✅ | ✅ green |
| 11-03-02 | 03 | 3 | CMD-02/07/08 | T-11-05/07/08/09/10 | guard ladder, off-loop, embed, handler isolation | unit | `uv run pytest tests/test_bot.py -x` | ✅ | ✅ green |
| 11-04-01 | 04 | 4 | CFG-07 | T-11-13 | both reload outcomes posted; best-effort | unit | `uv run pytest tests/test_reload.py -k cfg07 -x` | ✅ | ✅ green |
| 11-04-02 | 04 | 4 | CMD-08 | T-11-11/12/14 | bot start-after-READY, stop-in-finally, startup-failure isolation | unit+integration | `uv run pytest tests/test_bot.py -k "dies_alone or clean_start" tests/test_scheduler.py -k "bot_thread or no_bot_thread"` | ✅ (added 2026-06-17) | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> **Audit note (2026-06-17):** 11-04-02 was the one gap at audit time — its CMD-08
> isolation guarantees were verified at plan execution by source-grep only (the
> plan's `tests/test_daemon.py -k "isolation or lifecycle"` never existed, per
> 11-04-SUMMARY). Six behavioral tests now cover it: `BotThread` LoginFailure /
> unexpected-crash isolation + clean start/stop (`test_bot.py`), and `run_daemon`
> start-after-`emit_online` ordering, startup-failure isolation, and no-bot-without-config
> guard (`test_scheduler.py`). Also corrected: 11-02-03 coverage lives in
> `test_config.py` (not the never-created `test_models.py`/`test_settings.py` paths).

---

## Wave 0 Requirements

- [x] `tests/test_bot.py` — guard ladder (CMD-07), reply/embed (CMD-02), executor/off-loop (Pitfall 1), handler+token isolation (CMD-08), **+ BotThread lifecycle/isolation (CMD-08, added 2026-06-17)**
- [x] `tests/test_cache.py` — TTL hit/miss/expiry (CMD-06) + thread-safety smoke
- [x] `tests/conftest.py` — `fake_discord_message` factory (AsyncMock channel, configurable author)
- [x] Extend `tests/test_reload.py` — CFG-07 success + rejection + best-effort posting
- [x] Framework install: none new (pytest + time-machine present); `discord.py`/`cachetools` added in 11-02 so bot/cache modules import

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `message_content` privileged intent enabled in Developer Portal | D-02 (CMD-02) | Discord portal toggle has no API/CLI | Enable Message Content Intent in the Discord Developer Portal; `on_ready` asserts `client.intents.message_content` and logs CRITICAL if off |
| End-to-end "revoke token → next scheduled briefing still fires" | CMD-08 SC#4 | Requires a live (deliberately invalid) token + a real scheduled fire | Start daemon with an invalid `DISCORD_BOT_TOKEN` + a near-term slot (time-machine); confirm the briefing sends and READY emitted exactly once (unit test covers `BotThread._run` LoginFailure isolation) |
| Live `!weather home` in the real channel returns the embed | CMD-02 | Requires a live gateway connection | Type `!weather home` as the operator in the configured channel; confirm the embed reply matches the morning briefing |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 25s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-16 · re-validated 2026-06-17 (all tasks green)

---

## Validation Audit 2026-06-17

| Metric | Count |
|--------|-------|
| Gaps found | 1 |
| Resolved | 1 |
| Escalated | 0 |

Reconciled the plan-time Per-Task Map against the executed suite: 7/8 tasks were
already COVERED & green (one path correction — 11-02-03 lives in `test_config.py`).
The single gap, 11-04-02 (CMD-08 bot lifecycle/isolation, T-11-11/12/14), was filled
with 6 behavioral tests (3 in `test_bot.py`, 3 in `test_scheduler.py`). Full suite:
290 passed. Phase 11 is Nyquist-compliant.
