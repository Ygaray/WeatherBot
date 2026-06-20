---
phase: 11-discord-inbound-gateway-bot
plan: 02
subsystem: config
tags: [discord.py, cachetools, pydantic, pydantic-settings, uv, secrets, config]

# Dependency graph
requires:
  - phase: 11-01
    provides: inbound-bot RED scaffold (test_bot/test_cache/test_reload) + TTL cache test contract
  - phase: 01-foundation
    provides: Config/Settings models, load_config/load_settings, CONF-02 secrets boundary
provides:
  - "discord.py>=2.7.1,<3 + cachetools>=6,<8 pinned runtime deps (uv.lock)"
  - "Frozen BotConfig(operator_id:int) with extra=forbid"
  - "Config.bot: BotConfig | None = None (absence == no bot)"
  - "Settings.discord_bot_token: str (REQUIRED, fail-loud at load, D-14)"
  - "DISCORD_BOT_TOKEN documented in .env.example + deploy/README.md (Message Content Intent toggle)"
affects: [11-03, 11-04, discord-inbound-gateway-bot, bot, cache]

# Tech tracking
tech-stack:
  added: ["discord.py 2.7.1", "cachetools 7.1.4"]
  patterns:
    - "Single operator_id:int (not a list) for one-operator v1 bot (RESEARCH Pattern 5 / A3)"
    - "Plain optional bot:BotConfig|None=None (NOT default_factory) so absence means 'no bot'"
    - "New required secret on Settings = fail-loud at startup (D-14)"

key-files:
  created: []
  modified:
    - pyproject.toml
    - uv.lock
    - weatherbot/config/models.py
    - weatherbot/config/settings.py
    - weatherbot/config/__init__.py
    - .env.example
    - deploy/README.md
    - tests/test_config.py

key-decisions:
  - "operator_id is a single int, not a list — v1 is a one-operator bot (A3)"
  - "Config.bot uses None default (plain optional), NOT default_factory, so a [bot]-less config means 'no bot configured'"
  - "discord_bot_token is REQUIRED (no default): an existing .env lacking it fails loud at startup, by design (D-14)"
  - "Kept install string as discord.py in pyproject (PEP 508 normalizes to discord-py); import name is discord"

patterns-established:
  - "Pattern: new bearer secret => required field on Settings, documented in .env.example + deploy/README.md, never config.toml"
  - "Pattern: frozen + extra=forbid config models fail loud on unknown keys (T-11-03)"

requirements-completed: [CMD-02, CMD-07]

# Metrics
duration: ~15min
completed: 2026-06-17
---

# Phase 11 Plan 02: Bot config + secrets + deps foundation Summary

**Added discord.py + cachetools as pinned runtime deps, a frozen `BotConfig(operator_id)` optional on `Config`, and a REQUIRED `Settings.discord_bot_token` secret — with `.env.example` and deploy docs covering the new token and the privileged Message Content Intent toggle.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2 (Task 2 + Task 3; Task 1 checkpoint approved pre-continuation)
- **Files modified:** 8
- **Commits:** 3 task commits (1 chore, 1 RED test, 1 GREEN feat)

## Accomplishments
- `discord.py>=2.7.1,<3` and `cachetools>=6,<8` added as runtime deps via `uv add`, then hand-edited to house-style major ceilings and re-locked (`uv.lock` pins discord.py 2.7.1, cachetools 7.1.4).
- Frozen `BotConfig(extra="forbid")` with a single `operator_id: int`; wired onto `Config` as `bot: BotConfig | None = None` (absence == no bot).
- Required `Settings.discord_bot_token: str` — fails loud at load if `DISCORD_BOT_TOKEN` is absent (D-14).
- `BotConfig` exported from `weatherbot.config`.
- Docs: `.env.example` documents the new required token; `deploy/README.md` gains a required-secrets table, a fail-loud upgrade note, and the mandatory Message Content Intent privileged-intent portal step (D-02).

## Task Commits

1. **Task 1: Package legitimacy verification** — checkpoint (approved by operator before this continuation; pause marker `bb9304a`)
2. **Task 2: Add discord.py + cachetools deps; uv lock** — `cd5d5d5` (chore)
3. **Task 3: BotConfig + Config.bot + Settings.discord_bot_token + docs** (TDD)
   - RED: `54f3cdc` (test)
   - GREEN: `f7a268d` (feat)

_No REFACTOR commit needed — GREEN implementation was clean (ruff passed)._

## Files Created/Modified
- `pyproject.toml` — added `cachetools>=6,<8` and `discord.py>=2.7.1,<3` (alphabetical, house-style ceilings)
- `uv.lock` — re-locked; both deps + transitive (aiohttp etc.) pinned
- `weatherbot/config/models.py` — new frozen `BotConfig(operator_id:int)`; `Config.bot: BotConfig | None = None`
- `weatherbot/config/settings.py` — required `discord_bot_token: str`; updated docstrings
- `weatherbot/config/__init__.py` — export `BotConfig`
- `.env.example` — documented required `DISCORD_BOT_TOKEN`
- `deploy/README.md` — required-secrets table, fail-loud upgrade note, Message Content Intent toggle
- `tests/test_config.py` — 7 new tests (5 BotConfig, 2 token) + 2 existing Settings tests updated for the now-required token

## Decisions Made
- Kept the install string `discord.py` in `pyproject.toml` (PEP 508 normalizes `discord.py`/`discord-py` to the same name; matches the plan's acceptance grep). Import name is `discord`.
- Added BotConfig + token tests to `tests/test_config.py` (the existing Settings test module) rather than creating `tests/test_settings.py` — the plan explicitly allowed "the existing settings test module," and all Settings/Config tests already live there.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated two pre-existing Settings tests for the now-required token**
- **Found during:** Task 3 (GREEN)
- **Issue:** Making `discord_bot_token` REQUIRED (no default, per D-14) broke `test_settings_reads_both_secrets_from_env` and `test_load_settings_reads_from_dotenv_file`, which did not supply the new secret — they would raise `ValidationError` at `Settings()` load.
- **Fix:** Added `DISCORD_BOT_TOKEN` to the env/`.env` setup in both tests (the required-field semantics are exactly what the plan intends).
- **Files modified:** `tests/test_config.py`
- **Verification:** Both tests pass; full config suite green.
- **Committed in:** `f7a268d` (Task 3 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to keep the suite green after the intended required-field change. No scope creep.

## Issues Encountered
- The 12 currently-failing suite tests (`tests/test_bot.py`, `tests/test_cache.py`, `tests/test_reload.py`) are the **plan 11-01 RED scaffold tests** (commits `2c71421`, `f56eba5`) that import not-yet-implemented `weatherbot.bot` / `weatherbot.cache` modules and assert reload-posting behavior built in later plans (11-03/11-04). They were already RED before this plan and are explicitly OUT OF SCOPE for 11-02 (config/deps/docs only). All 8 bot/token tests added/touched by this plan pass; 271 of 283 suite tests pass.

## User Setup Required
**External service configuration required for the inbound bot.**
- Add `DISCORD_BOT_TOKEN` to `.env` (Discord Developer Portal -> Applications -> your app -> Bot -> Reset Token). REQUIRED — the process fails loud at startup without it.
- Enable the privileged **Message Content Intent** (Developer Portal -> Bot -> Privileged Gateway Intents). Without it the bot reads empty message bodies.
- See `deploy/README.md` section "Prepare the `.env`" for the full table and upgrade note.

## Next Phase Readiness
- 11-03/11-04 can now `import discord, cachetools` and read `config.bot.operator_id` / `settings.discord_bot_token`.
- The 11-01 RED scaffolds (`test_bot.py`, `test_cache.py`, `test_reload.py`) remain the work surface for those next plans — they turn GREEN as the bot/cache modules land.

## Self-Check: PASSED
- Files verified present: pyproject.toml, uv.lock, weatherbot/config/models.py, weatherbot/config/settings.py, weatherbot/config/__init__.py, .env.example (tracked), deploy/README.md, tests/test_config.py — all FOUND.
- Commits verified in git log: `cd5d5d5` FOUND, `54f3cdc` FOUND, `f7a268d` FOUND.

---
*Phase: 11-discord-inbound-gateway-bot*
*Completed: 2026-06-17*
