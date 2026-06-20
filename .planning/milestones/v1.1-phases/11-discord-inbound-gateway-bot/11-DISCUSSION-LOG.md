# Phase 11: Discord Inbound Gateway Bot - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-16
**Phase:** 11-Discord Inbound Gateway Bot
**Areas discussed:** Command form, Reply format, Access control, Quota cache, Reload-outcome posting, Operator-ID storage, Slow-fetch UX

---

## Command form

| Option | Description | Selected |
|--------|-------------|----------|
| Bare `weather home` | Matches CMD-02/SC#1 literally, but requires message_content privileged intent and is most exposed to the webhook/briefing-text feedback loop | |
| Slash `/weather home` | Research-recommended; no privileged intent, immune to briefing text; diverges from literal "type weather home" wording | |
| Prefix `!weather home` | Conventional bot UX; still needs message_content intent, but `!` makes the trigger unambiguous and briefing-text-immune | ✓ |

**User's choice:** Prefix `!weather home`
**Notes:** `!` keeps the trigger immune to briefing text / webhook feedback. Consequence: `message_content` privileged intent required (portal + code toggle, documented deploy step). Spec-tension flagged in CONTEXT for the verifier — `!weather` satisfies CMD-02's intent, the `!` is an operator-confirmed deviation, not a miss.

---

## Reply format

| Option | Description | Selected |
|--------|-------------|----------|
| Match the briefing embed | Build a Discord embed from LookupResult.forecast, same look as the scheduled briefing (send_briefing already does this) | ✓ |
| Plain text | Post LookupResult.text via channel.send(); simplest, matches v1 template verbatim | |

**User's choice:** Match the briefing embed
**Notes:** The inbound reply should look identical to the morning briefing. The shared lookup core already returns `forecast` precisely so the bot can build the embed without re-fetching.

---

## Access control

| Option | Description | Selected |
|--------|-------------|----------|
| Operator user ID only | Restrict replies to the operator's Discord user ID; single-user tool; stops others burning quota | ✓ |
| Anyone in the channel | Respond to any non-bot human; relies only on TTL cache + author.bot guard | |

**User's choice:** Operator user ID only
**Notes:** Non-operator messages are silently ignored (no reply, no quota spend).

---

## Quota cache

| Option | Description | Selected |
|--------|-------------|----------|
| Shared cache, ~10 min TTL | Per-location TTL cache the scheduled briefings could also read (Pitfall #10); bounded to configured locations | ✓ |
| Bot-only cache, ~10 min TTL | Cache lives only in the bot surface; scheduled path untouched | |
| Let me set the TTL | Pick a different TTL / scope | |

**User's choice:** Shared cache, ~10 min TTL
**Notes:** Designed to be shareable with the scheduled path; whether the scheduler actually wires into it now vs leaving the seam is left to the planner.

---

## Reload-outcome posting (CFG-07)

| Option | Description | Selected |
|--------|-------------|----------|
| Both, as a short embed | Post successful reloads (job-diff summary) AND rejections (validation reason) as a small status embed, visually distinct from briefings | ✓ |
| Both, plain text | Same coverage, one-line plain text, no embed | |
| Rejections only | Only post rejected reloads; successes stay log-only | |

**User's choice:** Both, as a short embed
**Notes:** Hook the existing `_do_reload` channel handle; capture the structured `(added, removed, changed, unchanged)` tuple from `_reconcile_jobs`, not the log line. Both file-watch and explicit-trigger reloads post identically.

---

## Operator-ID storage

| Option | Description | Selected |
|--------|-------------|----------|
| config.toml, silently ignore others | Non-secret identity in config.toml ([bot] section), reloadable; non-operator messages silently ignored | ✓ |
| .env, silently ignore others | Store as env var alongside the token; needs restart to change | |
| config.toml, reply "not authorized" | Same storage, but reply to non-operators instead of silent ignore | |

**User's choice:** config.toml, silently ignore others
**Notes:** Only the bot token is a secret (`.env`); the operator user ID is non-secret config, reloadable via the Phase 9/10 engine. No "not authorized" reply — avoids revealing the bot / spending a reply.

---

## Slow-fetch UX

| Option | Description | Selected |
|--------|-------------|----------|
| Typing indicator | Show "Bot is typing…" (async with channel.typing()) during the off-loop fetch, then post the embed | ✓ |
| No feedback, reply when ready | Just post the embed when the fetch completes | |

**User's choice:** Typing indicator
**Notes:** Cheap reassurance that discourages the user re-issuing the command (which would burn quota).

---

## Claude's Discretion

- Bot-thread lifecycle wiring: `client.start()`/`close()` on the dedicated loop, clean shutdown on SIGTERM, loop create/teardown (roadmap flags `--research-phase 11` for this).
- Cache implementation details: structure, invalidation on reload, whether the scheduled path wires in now vs leaves the seam.
- discord.py version + `commands.Bot` (prefix framework) vs bare `Client` + manual `on_message`.
- Startup `message_content` intent assertion mechanism; the typing-indicator + embed-edit UX detail.
- Operator user ID schema shape (single int vs list) under `[bot]`.

## Deferred Ideas

- Arbitrary/geocoded `weather <any city>` — v2.0 (CMD-V2-02).
- Telegram / SMS inbound channels — v2.0 (CHAN-V2-01/02).
- Per-user cooldown / multi-user anti-spam — non-goal for this single-user tool.
- Slash commands `/weather` — considered, deferred in favor of the prefix form; revisit if Discord tightens privileged-intent access or a multi-user need appears.
- Wiring the scheduled briefing path to actually read the shared cache — left to the planner.
