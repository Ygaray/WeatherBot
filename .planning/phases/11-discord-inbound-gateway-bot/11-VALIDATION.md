---
phase: 11
slug: discord-inbound-gateway-bot
status: draft
nyquist_compliant: true
wave_0_complete: false
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
| 11-01-01 | 01 | 1 | CMD-02/06/07/08 | T-11-01 | RED node IDs collect, fail on unbuilt module | unit | `uv run pytest tests/test_bot.py tests/test_cache.py --collect-only -q` | ❌ W0 | ⬜ pending |
| 11-01-02 | 01 | 1 | CFG-07 | T-11-01 | cfg07 posting RED contract | unit | `uv run pytest tests/test_reload.py -k cfg07 --collect-only -q` | ⚠️ extend | ⬜ pending |
| 11-02-02 | 02 | 2 | CMD-02 | T-11-SC/04 | legitimate pinned deps importable | unit | `uv run python -c "import discord, cachetools"` | n/a | ⬜ pending |
| 11-02-03 | 02 | 2 | CMD-07 | T-11-02/03 | token in .env fail-loud; [bot] extra=forbid | unit | `uv run pytest tests/test_models.py -k "bot or BotConfig" tests/test_settings.py -x` | ✅ (11-01) | ⬜ pending |
| 11-03-01 | 03 | 3 | CMD-06 | T-11-06 | repeated same-loc within TTL → one fetch | unit | `uv run pytest tests/test_cache.py -x` | ✅ (11-01) | ⬜ pending |
| 11-03-02 | 03 | 3 | CMD-02/07/08 | T-11-05/07/08/09/10 | guard ladder, off-loop, embed, isolation | unit | `uv run pytest tests/test_bot.py -x` | ✅ (11-01) | ⬜ pending |
| 11-04-01 | 04 | 4 | CFG-07 | T-11-13 | both reload outcomes posted; best-effort | unit | `uv run pytest tests/test_reload.py -k cfg07 -x` | ✅ (11-01) | ⬜ pending |
| 11-04-02 | 04 | 4 | CMD-08 | T-11-11/12/14 | bot start-after-READY, stop-in-finally, isolated | unit | `uv run pytest tests/test_bot.py -k "isolation or lifecycle" -x` | ✅ (11-01) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_bot.py` — guard ladder (CMD-07), reply/embed (CMD-02), executor/off-loop (Pitfall 1), handler+token isolation (CMD-08)
- [ ] `tests/test_cache.py` — TTL hit/miss/expiry (CMD-06) + thread-safety smoke
- [ ] `tests/conftest.py` — `fake_discord_message` factory (AsyncMock channel, configurable author)
- [ ] Extend `tests/test_reload.py` — CFG-07 success + rejection + best-effort posting
- [ ] Framework install: none new (pytest + time-machine present); `discord.py`/`cachetools` added in 11-02 so bot/cache modules import

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

**Approval:** approved 2026-06-16
