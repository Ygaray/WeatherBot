---
phase: 11-discord-inbound-gateway-bot
verified: 2026-06-17T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null
  previous_score: null
human_verification:
  - test: "Type `!weather home` (and `!weather <unknown>`) in the real private Discord channel as the operator"
    expected: "An embed briefing reply for a known location (Now / High-Low / Rain fields); the configured-names error text for an unknown location; no 'Heartbeat blocked' warning in logs"
    why_human: "Requires a live gateway connection, real bot token, and a human reading the rendered embed in-channel — cannot be exercised without the live Discord gateway"
  - test: "In the Discord Developer Portal, confirm the Message Content Intent (privileged) is toggled ON for the bot application"
    expected: "Message Content Intent enabled; on_ready logs 'inbound bot ready' (not the CRITICAL 'message_content intent missing' line). With it OFF, the bot reads empty message bodies"
    why_human: "Developer Portal dashboard state is external to the codebase and cannot be inspected programmatically"
  - test: "Revoke / invalidate the bot token (or kill the gateway connection) while the daemon is running, then wait for the next scheduled briefing slot"
    expected: "BotThread logs CRITICAL 'invalid Discord token; inbound bot disabled, briefings unaffected' and dies alone; the next scheduled briefing still fires via the webhook; systemd READY gate is unaffected"
    why_human: "End-to-end failure-isolation across a real scheduled slot + live token revocation requires a running deployment over time; cannot be simulated in a unit test"
---

# Phase 11: Discord Inbound Gateway Bot Verification Report

**Phase Goal:** A user can type `weather <location>` in the Discord channel and get the briefing as an in-channel reply, served by an isolated gateway bot whose failures can never stop a scheduled briefing; the bot also posts each reload outcome to Discord.
**Verified:** 2026-06-17T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria + merged PLAN must_haves)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | (SC#1, CMD-02) `!weather home` returns the briefing as an in-channel embed reply; an unknown location returns the configured-names error; all blocking fetch/SQLite work runs off the event loop | ✓ VERIFIED (code+tests) / human for live channel | `bot.py:102-146` guard ladder → `loop.run_in_executor(None, cache.lookup, name, config)` (off-loop, D-10) → `message.channel.send(embed=build_inbound_embed(...))`; `UnknownLocationError` caught inside typing block → `channel.send(str(exc))` (valid_names). `test_bot.py` 6 IDs GREEN. Live in-channel render → human |
| 2 | (SC#2, CMD-06) Repeated requests for the same location within the TTL serve from cache instead of refetching | ✓ VERIFIED | `cache.py:49-114` `ForecastCache` = `cachetools.TTLCache` behind `threading.Lock`, keyed on `resolve_location(config, name).id`; fetch runs UNLOCKED on miss. `test_cache.py` 4 IDs GREEN (hit, post-TTL refetch, distinct keys, invalidate) |
| 3 | (SC#3, CMD-07) Bot responds only to explicit commands, never to its own replies or the webhook's posts | ✓ VERIFIED (code+tests) / human for live | `bot.py:105-109` FIRST guard `if message.author.bot: return` (drops webhook + self), then `if message.author.id != operator_id: return`. `test_guard_webhook_author_fires_nothing` + `test_guard_non_operator_silently_ignored` GREEN |
| 4 | (SC#4, CMD-08) A bot/gateway failure never prevents a scheduled briefing; bot health never flips the READY gate | ✓ VERIFIED (structural) / human for live revocation | `daemon.py:1179-1193` BotThread start is AFTER `emit_online()` (line 1162) and wrapped in try/except that logs+proceeds; `bot.py:237-246` `_run` catches `discord.LoginFailure` + bare `Exception` (dies alone). `add_signal_handler`=0, `signal.signal`=2 unchanged, `client.run(`=0. Live token-revocation across a real slot → human |
| 5 | (SC#5, CFG-07) Each reload outcome (applied summary / rejection reason) is posted to Discord | ✓ VERIFIED | `daemon.py:664-668` success → `channel.send(f"✅ config reloaded: {summary}")`; `daemon.py:600-604` reject branch → `channel.send(f"⛔ config reload rejected: {exc}")`; both best-effort (try/except, never aborts reload). `test_reload.py` 3 `cfg07` IDs GREEN |

**Score:** 5/5 truths verified in code (3 carry live-environment human confirmation items)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `weatherbot/interactive/bot.py` | Guard ladder, embed, executor dispatch, BotThread lifecycle | ✓ VERIFIED | 254 lines; `build_inbound_embed`, `build_on_message`, `build_client`, `BotThread` (start/stop/_run/_amain). Uses `asyncio.run(client.start())`, cross-thread `run_coroutine_threadsafe`. Wired + imported by daemon |
| `weatherbot/interactive/cache.py` | ForecastCache (TTLCache + Lock) keyed on Location.id | ✓ VERIFIED | 115 lines; lock-around-dict-only contract; `invalidate()` present (intentionally unwired, see Anti-Patterns/Deferred) |
| `weatherbot/interactive/__init__.py` | Barrel exports | ✓ VERIFIED | `ForecastCache`, `BotThread`, `build_client` importable (spot-check passed) |
| `weatherbot/config/models.py` | Frozen BotConfig + optional Config.bot | ✓ VERIFIED | `class BotConfig` (`extra=forbid`, `frozen=True`, `operator_id: int`) line 248; `bot: BotConfig \| None = None` line 288 |
| `weatherbot/config/settings.py` | Required discord_bot_token | ✓ VERIFIED | `discord_bot_token: str` line 33 (no default, fail-loud, D-14) |
| `weatherbot/scheduler/daemon.py` | Bot lifecycle + CFG-07 posts | ✓ VERIFIED | ForecastCache construct (1040-1045), BotThread start after emit_online (1179-1193), stop in finally (1261-1265), CFG-07 both branches (600-604, 664-668) |
| `pyproject.toml` / `uv.lock` | discord.py + cachetools pinned | ✓ VERIFIED | `discord.py>=2.7.1,<3`, `cachetools>=6,<8`; lock has both (grep count 8) |
| `.env.example` / `deploy/README.md` | Token + Message Content Intent docs | ✓ VERIFIED | `deploy/README.md` documents Message Content Intent (3 occurrences); token documented per 11-02 SUMMARY + passing test_config suite |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| bot.py on_message | ForecastCache.lookup | `run_in_executor(None, cache.lookup, name, config)` | ✓ WIRED | `bot.py:128-130` |
| cache.py lookup | lookup_weather | cache-miss fetch under no lock | ✓ WIRED | `cache.py:104` outside `with self._lock` |
| bot.py on_message | author.bot guard | first guard returns | ✓ WIRED | `bot.py:105-106`, before operator/parse |
| daemon run_daemon | BotThread | construct+start after emit_online, stop in finally | ✓ WIRED | start line 1183 > emit_online line 1162; stop line 1263 in finally |
| daemon _do_reload success | channel.send (summary) | post after summary computed | ✓ WIRED | `daemon.py:666` |
| daemon _do_reload reject | channel.send (reason) | post reason before raise | ✓ WIRED | `daemon.py:602` before `raise` (605) |
| Config | BotConfig | `bot: BotConfig \| None` | ✓ WIRED | `models.py:288` |
| Settings | DISCORD_BOT_TOKEN | pydantic field map | ✓ WIRED | `settings.py:33` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Phase-11 test suites pass | `pytest tests/test_bot.py tests/test_cache.py tests/test_reload.py -q` | 33 passed | ✓ PASS |
| Full suite green (no regression) | `pytest -q` | 283 passed, 1 warning | ✓ PASS |
| Interactive package exports resolve | `python -c "from weatherbot.interactive import ForecastCache, BotThread, build_client..."` | exports OK | ✓ PASS |
| No blocking `client.run()` (CMD-08 mechanic) | `grep -c "client.run(" bot.py` | 0 | ✓ PASS |
| Live `!weather` in real channel | (requires live gateway) | — | ? SKIP → human |

### Probe Execution

No project probes (`scripts/*/tests/probe-*.sh`) declared or found for this phase. Verification is test-suite based (pytest). Step 7c: SKIPPED (no probes for a Python/pytest phase).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| CMD-02 | 11-01/02/03 | `weather [location]` command → in-channel reply | ✓ SATISFIED | bot.py guard ladder + embed reply + UnknownLocationError path; test_bot.py GREEN (live render → human) |
| CMD-06 | 11-01/03 | Short-TTL cache reuse instead of refetch | ✓ SATISFIED | cache.py TTLCache; test_cache.py GREEN |
| CMD-07 | 11-01/02/03 | Bot responds only to explicit commands, no feedback loop | ✓ SATISFIED | author.bot + operator-id guards; tests GREEN |
| CMD-08 | 11-01/03/04 | Bot failure never blocks a scheduled briefing | ✓ SATISFIED (structural) | bot started after emit_online, wrapped; BotThread._run isolates failures (live revocation → human) |
| CFG-07 | 11-01/04 | Reload outcome posted to Discord | ✓ SATISFIED | _do_reload both branches; cfg07 tests GREEN |

No orphaned requirements: REQUIREMENTS.md maps exactly CMD-02/06/07/08 + CFG-07 to Phase 11, all claimed by plan frontmatter. Phase 11 is the final v1.1 phase — no later phases exist to defer items to.

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| bot.py `build_inbound_embed` | `forecast` (Now/High-Low/Rain) | `cache.lookup` → `lookup_weather` (real OpenWeather One Call read core, Phase 6) | Yes (live fetch path; tests use counting spies on the real key path, not hollow mocks) | ✓ FLOWING |
| daemon CFG-07 post | `summary` = `f"+{added} -{removed} ~{changed} ={unchanged}"` | `_reconcile_jobs` diff tuple captured directly (D-13, not log-scraped) | Yes | ✓ FLOWING |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| cache.py | 110-114 | `ForecastCache.invalidate()` exists but is NOT called from daemon (`grep invalidate daemon.py` = 0) | ℹ️ Info (intentional deferral) | After a config reload the bot may serve a stale forecast for up to the TTL (~10 min). Explicitly DEFERRED per decision Q2/D-12 (seam left unwired); flagged by 11-REVIEW.md as a finding but ratified as intentional scope, not a phase-goal failure. The phase goal does not require reload→cache invalidation |

No debt markers (`TBD`/`FIXME`/`XXX`) in any phase-11 file. No `TODO`/`HACK`/`PLACEHOLDER` stubs in bot.py/cache.py. No empty-return stubs — all handlers carry real logic. The `# noqa: BLE001` broad-excepts are the deliberate non-propagating-handler design (CMD-08/D-11), not stubs.

### Human Verification Required

#### 1. Live `!weather` in the real Discord channel

**Test:** Type `!weather home` and `!weather <unknown>` in the real private Discord channel as the operator.
**Expected:** An embed briefing reply (Now / High-Low / Rain) for a known location; the configured-names error text for an unknown location; no "Heartbeat blocked" warning in logs.
**Why human:** Requires a live gateway connection, real token, and a human reading the rendered embed in-channel.

#### 2. Message Content Intent toggle (Developer Portal)

**Test:** Confirm the Message Content Intent (privileged) is enabled for the bot application in the Discord Developer Portal.
**Expected:** `on_ready` logs "inbound bot ready" (not the CRITICAL "message_content intent missing" line). With it OFF, the bot reads empty bodies.
**Why human:** Developer Portal dashboard state is external to the codebase.

#### 3. Live failure isolation across a scheduled slot

**Test:** Revoke/invalidate the bot token (or kill the gateway) while the daemon runs, then wait for the next scheduled briefing slot.
**Expected:** BotThread logs CRITICAL "invalid Discord token; inbound bot disabled, briefings unaffected" and dies alone; the next scheduled briefing still fires; systemd READY gate unaffected.
**Why human:** End-to-end isolation across a real scheduled slot + live token revocation requires a running deployment over time.

### Gaps Summary

No gaps block the phase goal. All five ROADMAP success criteria are achieved in code with passing test coverage (33 phase-11 tests, 283 full-suite, zero failures). All eight required artifacts exist, are substantive, are wired, and (for dynamic-data artifacts) carry real data flow. All five requirement IDs (CMD-02/06/07/08, CFG-07) are accounted for in both plan frontmatter and REQUIREMENTS.md with no orphans.

The single 11-REVIEW.md "BLOCKER" — `ForecastCache.invalidate()` left unwired — is an explicitly ratified scope decision (Q2/D-12: the invalidation seam is deferred), and the phase goal does not require reload→cache invalidation. It is recorded here as an Info-level intentional deferral, not a gap. The "bot token REQUIRED" choice (D-14/Q1) is likewise intentional and verified working (fail-loud `Settings.discord_bot_token`).

Status is `human_needed` (not `passed`) because three success criteria have live-environment confirmation steps — in-channel `!weather` rendering (SC#1), the Developer Portal Message Content Intent toggle (SC#1/D-02), and live token-revocation failure isolation across a real briefing slot (SC#4) — that cannot be exercised programmatically. The codebase implementation for all three is complete and verified; only the live runtime confirmation remains.

---

_Verified: 2026-06-17T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
