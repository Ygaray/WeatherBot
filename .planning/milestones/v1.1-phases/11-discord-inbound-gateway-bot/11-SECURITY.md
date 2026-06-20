---
phase: 11
slug: discord-inbound-gateway-bot
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-17
---

# Phase 11 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
>
> Register authored at plan time across the four 11-0x PLAN `<threat_model>` blocks.
> Each `mitigate` disposition was verified by locating the declared mitigation in
> implemented code (file:line) — not by accepting plan intent. No implementation
> files were modified by this audit.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| test harness → unbuilt modules | Deferred per-test import; no live gateway, no network | none (collection-only) |
| operator → `.env` | `DISCORD_BOT_TOKEN` bearer secret crosses here (git-ignored) | bot token (high sensitivity) |
| `config.toml` → process | non-secret `operator_id` crosses here (reloadable, schema-validated) | operator Discord ID (low) |
| PyPI → build | two new third-party packages installed (discord.py, cachetools) | dependency code (supply chain) |
| Discord gateway → `on_message` | untrusted user-typed message content crosses here | command text (untrusted) |
| outbound webhook → channel | the bot's OWN briefing posts re-enter the same channel | bot messages (feedback risk) |
| bot loop ↔ executor threads | the shared TTL cache is touched across threads | cached forecasts |
| bot thread → daemon process | a bot/gateway failure must not cross into the scheduler/briefing path | failure isolation |
| bot thread → systemd READY gate | bot health must never flip the readiness signal | readiness state |
| reload path → Discord channel | a reload-outcome post must not abort the reload | reload outcome message |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation (evidence) | Status |
|-----------|----------|-----------|-------------|------------------------|--------|
| T-11-01 | Tampering | RED scaffold masks node IDs via top-level import | mitigate | Deferred per-test import idiom; node IDs collect and fail RED on unbuilt modules (11-01 acceptance) | closed |
| T-11-SC | Tampering | uv installs of discord.py / cachetools | mitigate | Blocking human-verify legitimacy checkpoint precedes install (11-02 Task 1, marker `bb9304a`); `uv.lock` pins discord.py 2.7.1 + cachetools 7.1.4; `pyproject.toml:8-9` | closed |
| T-11-02 | Information disclosure / Elevation | bot token committed in config.toml or git | mitigate | Token only on `config/settings.py:33`; no secret field in `models.py`; `.gitignore:4,7` ignores `.env` + `config.toml`; `deploy/README.md:60` `.env`-only | closed |
| T-11-03 | Tampering | unknown/extra key under `[bot]` smuggles config | mitigate | `BotConfig` `ConfigDict(extra="forbid", frozen=True)` — `config/models.py:267`; unknown key fails loud (test-asserted) | closed |
| T-11-04 | Spoofing | wrong/abandoned `discord` PyPI package | mitigate | Human-verify legitimacy gate confirmed discord.py / Rapptz before `uv add` (11-02 Task 1); pinned in `uv.lock` | closed |
| T-11-05 | Denial of Service | feedback loop: bot replies to webhook briefing / its own reply | mitigate | `if message.author.bot: return` FIRST guard `bot.py:107` + `!` prefix `:114` + word-boundary guard `command.py:64-65` | closed |
| T-11-06 | Denial of Service | any server member drives the OpenWeather quota | mitigate | Operator-only allowlist `bot.py:110` + per-location TTLCache keyed on `.id` `cache.py:93-108` | closed |
| T-11-07 | Tampering | injection via the location string | mitigate | Parse-don't-validate (`strip`/`casefold`/slice only, no `format`/`eval`/shell) `command.py:57-70`; only configured names resolve else `UnknownLocationError` | closed |
| T-11-08 | Denial of Service (core value) | unhandled handler exception crashes the process | mitigate | Non-propagating `try/except` over `on_message` body `bot.py:124-148`; generic reply, never a stack trace to the user | closed |
| T-11-09 | Information disclosure | over-broad intents read all messages | mitigate | `Intents.none()` + only guilds/guild_messages/message_content `bot.py:167-170`; on_ready CRITICAL assert `:178-185` | closed |
| T-11-10 | Information disclosure | token/forecast internals leaked in logs | mitigate | structlog outcome-only; token never passed to a log call (`bot.py` log sites 144,148,259,275,280); generic error reply | closed |
| T-11-11 | Denial of Service (core value) | bot/gateway failure stops scheduled briefings | mitigate | BotThread started AFTER `emit_online` (`daemon.py:1196-1206` > `:1179`), start try/except proceeds; `_run` catches LoginFailure + Exception `bot.py:264-280` | closed |
| T-11-12 | Tampering | bot health flips the systemd READY gate | mitigate | `notifier.ready()` once in `emit_online` `daemon.py:850`, never from bot path; bot start after gate `:1164`; dead bot thread untouched | closed |
| T-11-13 | Denial of Service | failing reload-outcome post aborts the reload | mitigate | CFG-07 posts best-effort: reject `daemon.py:601-606`, success `:665-669`; channel.send failure logged, never propagated | closed |
| T-11-14 | Tampering | off-main-thread signal handler crashes the bot thread | mitigate | `asyncio.run(client.start())` not `client.run()` `bot.py:272,287`; daemon keeps main-thread `signal.signal` (×2); `add_signal_handler` count = 0 | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|

No accepted risks.

### Notes / Deferred (informational, not threats)

- `operator_id` is baked at BotThread construction; a config reload that changes
  `[bot] operator_id` is not picked up by a running bot (process restart required).
  Documented at `weatherbot/interactive/bot.py:97-101` and in deploy docs. This
  narrows, not widens, the trust boundary — a reload cannot silently re-authorize a
  new operator.
- The shared `ForecastCache` scheduler-read seam is intentionally left unwired
  (Q2/D-12); the cache serves the bot only. No security impact.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-17 | 15 | 15 | 0 | gsd-security-auditor |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-17
