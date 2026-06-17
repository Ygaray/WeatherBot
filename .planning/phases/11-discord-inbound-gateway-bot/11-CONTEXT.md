# Phase 11: Discord Inbound Gateway Bot - Context

**Gathered:** 2026-06-16
**Status:** Ready for planning

<domain>
## Phase Boundary

A user types `!weather <location>` in the Discord channel and gets the briefing back
as an in-channel reply, served by an **isolated inbound gateway bot** that runs on its
own asyncio thread/loop, never blocks on or crashes the scheduled-briefing path, and
guards the shared OpenWeather quota with a short-TTL cache. The same bot surface also
posts each **reload outcome** (applied summary / rejection reason) to Discord so the
operator need not tail logs.

This is the LAST v1.1 phase, built on proven foundations:
- **Phase 6** — the shared read-only `lookup_weather` core (returns both rendered `text`
  and structured `forecast`) and `parse_weather_command` (three-state parser). The bot
  reuses both verbatim — no new fetch/render/parse logic.
- **Phase 8** — `ConfigHolder.current()` lock-free snapshot read. The bot receives the
  same `holder` instance the daemon owns and reads live config through it.
- **Phase 9/10** — the reload engine (`_do_reload`) already receives a `channel` handle
  and produces a structured `(added, removed, changed, unchanged)` job-diff on success /
  a validation reason on rejection. CFG-07 hangs Discord posting off that existing seam.

**Closes:** CMD-02 (in-channel `weather <loc>` reply), CMD-06 (short-TTL cache quota
guard), CMD-07 (responds only to explicit commands, never to self/webhook), CMD-08
(bot failure never stops a scheduled briefing), CFG-07 (reload outcome posted to Discord).

**Out of scope (own phases / milestones):**
- Arbitrary/geocoded `weather <any city>` lookups — v2.0 (CMD-V2-02); v1.1 is
  configured-locations-only (reuses `lookup_weather`'s `UnknownLocationError`).
- Telegram / SMS inbound — v2.0 channels (CHAN-V2-01/02).
- Per-user cooldown tables / multi-user anti-spam — explicitly rejected for this
  single-user tool (REQUIREMENTS.md non-goals); the TTL cache + operator allowlist
  are the right quota guards.
- Migrating the briefing scheduler to `AsyncIOScheduler` — `BackgroundScheduler` stays
  exactly as v1 has it (Pitfall #1; bigger, riskier change, briefing path is sync).
- `.env`/secret hot-reload — permanent restart boundary (Pitfall #12); the new bot
  token follows that rule.
</domain>

<decisions>
## Implementation Decisions

### Command form & invocation (CMD-02, CMD-07; roadmap-flagged decision)
- **D-01: Prefix command `!weather <location>`** (chosen over bare `weather …` and over
  slash `/weather`). The `!` makes the trigger unambiguous and immune to briefing text /
  the webhook feedback loop. Bare `weather` was rejected as too exposed to substring
  trips; slash was considered (no privileged intent) but the operator preferred the
  conventional prefix UX.
- **D-02: `message_content` privileged intent is REQUIRED** as a consequence of D-01.
  Enable it BOTH in code (`intents.message_content = True`) AND in the Discord Developer
  Portal — the portal toggle is an explicit, documented deploy step (Pitfall #3). The bot
  SHOULD assert at startup that the intent is set so a half-configured deploy fails loud
  rather than silently receiving empty `message.content`.
- **D-03: Reuse `parse_weather_command` for the three-state parse.** `!weather` strips the
  `!weather` prefix and feeds the remainder to the existing parser: bare `!weather` →
  default location (DEFAULT), `!weather <loc>` → LOCATED, garbage → NOT_A_COMMAND (no
  reply). Unknown location → reply with the configured-names error from
  `UnknownLocationError.valid_names` (CMD-02 error path; UX pitfall "no response on bad
  location").
- **Spec-tension note (for the verifier):** CMD-02 / SC#1 literally say "typing
  `weather home`". `!weather home` satisfies the *intent* (issue a weather command in the
  channel and get a reply) but prepends `!`. This is an operator-confirmed deviation, NOT
  a missed requirement — do not flag the `!` as a gap.

### Feedback-loop & access guards (CMD-07)
- **D-04: `if message.author.bot: return` as the first guard** — covers the bot's own
  replies AND the outbound briefing webhook (webhook messages have `author.bot == True`
  but a different author id). NOT `== bot.user` (Pitfall #2). MANDATORY test: feed a
  simulated webhook-authored message and assert no command fires (roadmap SC#3).
- **D-05: Operator-only allowlist.** The bot responds only to the configured operator's
  Discord user ID; messages from any other channel member are **silently ignored** (no
  reply, no OpenWeather call). This is a single-user personal tool — stops any other
  server member from driving the quota (security table). No "not authorized" reply (avoids
  revealing the bot / spending a reply).
- **D-06: Operator user ID lives in `config.toml`** (non-secret identity), e.g. a `[bot]`
  section — reloadable like other config via the Phase 9/10 reload engine. Only the bot
  **token** is a secret in `.env`. Changing the allowed operator is a config edit, not a
  restart.

### Reply format (CMD-02)
- **D-07: Reply as a Discord embed built from `LookupResult.forecast`** — same look as the
  scheduled briefing (mirror `DiscordWebhookChannel.send_briefing`'s embed construction).
  The inbound reply should be visually identical to the morning briefing. Plain-text-only
  was rejected; the shared core already returns `forecast` precisely so the bot can build
  the embed without re-fetching.
- **D-08: Typing indicator during the fetch.** Show Discord's "Bot is typing…"
  (`async with channel.typing():`) while the blocking lookup runs off-loop, then post the
  embed. Cheap reassurance that discourages the user re-issuing (which would burn quota).

### Event-loop hygiene & failure isolation (CMD-08; Pitfalls #1, #4)
- **D-09: Bot runs on its OWN dedicated thread + asyncio loop**, separate from the
  `BackgroundScheduler` thread, started alongside the existing file-watch observer in
  `run_daemon` and joined/stopped in the same `finally` teardown (mirror the observer
  lifecycle). `BackgroundScheduler` is unchanged.
- **D-10: ALL blocking work goes through `run_in_executor`.** `lookup_weather` is sync
  (httpx + template render) and SQLite/cache I/O is sync; the `on_message` coroutine wraps
  every sync call with `await loop.run_in_executor(None, …)` so the gateway heartbeat is
  never blocked (no "Heartbeat blocked"; roadmap SC#1). Cross-thread signalling (if the
  scheduler/reload path needs to reach the bot loop) uses `run_coroutine_threadsafe` /
  `call_soon_threadsafe` — never touch loop objects from the wrong thread.
- **D-11: Bot failure ≠ briefing failure.** Wrap the entire command handler in
  try/except that logs (reuse structlog/alert path) and replies with an error but NEVER
  propagates out of the coroutine. A revoked/disconnected/erroring gateway lets discord.py
  auto-reconnect with backoff; persistent failure logs CRITICAL and the bot thread stops,
  but the scheduler thread and briefing path keep running untouched. A dead bot thread
  does **NOT** flip the systemd READY gate / `gate_until_healthy` (Pitfall #4; roadmap
  SC#4). MANDATORY test: revoke the token and confirm the next scheduled briefing still
  fires.

### Quota guard / cache (CMD-06; Pitfall #10)
- **D-12: Shared per-location TTL cache, ~10 minute TTL.** Repeated `!weather <loc>`
  within the TTL serve from the cached fetch instead of calling OpenWeather again. The
  cache is keyed per configured location and designed so the **scheduled briefings could
  also read it** (Pitfall #10's "shared cache" suggestion) — bounded to configured
  locations only. ~10 min chosen because the forecast barely moves minute-to-minute.
  Invalidation is now WIRED: `_do_reload` calls `cache.invalidate()` best-effort after a
  successful swap, so the next `!weather <loc>` refetches against the reloaded config
  (CR-01 closed, quick task 260617-fua). The requirement is "same location within a short
  TTL reuses the fetch" — roadmap SC#2.

### Reload outcome posting (CFG-07)
- **D-13: Post BOTH success and rejection outcomes as a short status embed**, visually
  distinct from briefing embeds. Success posts the job-diff summary (the
  `+added -removed ~changed =unchanged` figures from `_reconcile_jobs`); rejection posts
  the validation reason. Hook into the EXISTING `_do_reload` channel handle — capture the
  structured `(added, removed, changed, unchanged)` tuple from `_reconcile_jobs` (do NOT
  scrape the log line). Both file-watch and explicit-trigger reloads post identically
  (same `_do_reload` path).

### Secrets (Pitfall #3)
- **D-14: `DISCORD_BOT_TOKEN` is a NEW required secret in git-ignored `.env`**, loaded via
  pydantic-settings `Settings` alongside `openweather_api_key` / `discord_webhook_url`,
  fail-loud on missing. NEVER in `config.toml`. Add to any pre-commit secret scan. The
  outbound webhook URL stays the briefing path — do NOT reuse it for inbound replies.

### Claude's Discretion
Left to research/planning — no operator preference expressed:
- Exact bot-thread lifecycle wiring: `client.start()`/`close()` coroutine lifecycle on the
  dedicated loop, clean shutdown on SIGTERM (reuse v1's shutdown path), and how the loop is
  created/torn down. The roadmap flags this as the highest-blast-radius integration mechanic
  (`/gsd-plan-phase --research-phase 11` recommended for thread lifecycle + `client.start()`
  wiring).
- Cache implementation details: structure (dict + timestamp vs a small TTL lib), exact
  invalidation on reload (does a config change purge it?), and whether the scheduled path
  actually wires into it now or just leaves the seam.
- discord.py library version + whether to use `commands.Bot` (prefix command framework) vs
  a bare `Client` with manual `on_message` parsing. (D-01/D-03 favor explicit `on_message`
  + `parse_weather_command` reuse, but the planner may use `commands.Bot`'s `!` prefix
  machinery if it composes cleanly with the `author.bot`/operator guards.)
- Startup-intent assertion mechanism (D-02) and the "bot is typing" + embed-edit UX detail.
- Whether the operator user ID is a single int or a list (config schema shape under `[bot]`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & requirements
- `.planning/ROADMAP.md` — Phase 11 entry: goal, depends-on (Phase 6 shared lookup,
  Phase 8 holder), the 5 success criteria, and the **Research flag** recommending
  `/gsd-plan-phase --research-phase 11` for thread lifecycle + failure isolation + the
  command-type decision.
- `.planning/REQUIREMENTS.md` — CMD-02, CMD-06, CMD-07, CMD-08, CFG-07 (the five
  requirements this phase closes); the non-goals table (no per-user cooldown tables —
  TTL cache is the right guard).

### Pitfalls research — THIS PHASE IS THE PRIMARY TARGET (MANDATORY)
- `.planning/research/PITFALLS.md` — read the Discord-bot pitfalls in full:
  - **Pitfall #1** — asyncio loop vs BackgroundScheduler; own thread + `run_in_executor` (D-09/D-10).
  - **Pitfall #2** — bot replies to own/webhook messages; `author.bot` guard (D-04).
  - **Pitfall #3** — intents/token misconfig; `message_content` portal+code toggle, token in `.env` (D-02/D-14).
  - **Pitfall #4** — bot crash must not kill briefings; isolation + don't pollute READY gate (D-11).
  - **Pitfall #10** — command spam burns quota; short-TTL cache (D-12).
  - Plus the "Looks Done But Isn't" Discord checklist, Integration Gotchas, Security/UX tables.

### Prior-phase context this phase builds on
- `.planning/phases/06-shared-lookup-core-command-parser/06-CONTEXT.md` — the
  `lookup_weather` / `parse_weather_command` seam the bot reuses (read-only core,
  returns `text` + `forecast`; three-state parser).
- `.planning/phases/08-configholder-fire-slot-reads-from-holder-refactor/08-CONTEXT.md` —
  `ConfigHolder.current()` snapshot read the bot uses for live config.
- `.planning/phases/09-reload-engine-explicit-trigger/09-CONTEXT.md` — the reload engine
  (`_do_reload`, `_reconcile_jobs` diff summary, `channel` handle) that CFG-07 posting
  hooks into; D-07 there defines the `+added -removed ~changed =unchanged` summary.

### Code this phase extends
- `weatherbot/interactive/lookup.py` — `lookup_weather(name, *, config, settings, …) ->
  LookupResult(text, forecast, location)` (SYNC — wrap in `run_in_executor`); raises
  `UnknownLocationError(requested, valid_names)`.
- `weatherbot/interactive/command.py` — `parse_weather_command(text) -> Command(kind, location)`
  (three-state: NOT_A_COMMAND / DEFAULT / LOCATED).
- `weatherbot/scheduler/daemon.py` — `run_daemon` (bot thread start ~alongside the
  file-watch observer; shutdown/join in the `finally`); `_do_reload` (~line 549, already
  takes a `channel`) and `_reconcile_jobs` (returns the `(added, removed, changed,
  unchanged)` tuple — CFG-07 reads it here, ~lines 516/605/637-646); `ConfigHolder`
  created ~line 1009 and threaded to jobs/reload.
- `weatherbot/channels/discord.py` — `DiscordWebhookChannel` (`send(text)` from `base.py`;
  `send_briefing(text, forecast)` builds the embed — mirror its embed construction for the
  inbound reply, D-07); `channels/base.py` `Channel.send` interface; `channels/factory.py`
  `build_channel` / `_build_discord`.
- `weatherbot/config/settings.py` — `Settings(BaseSettings)` (~lines 14-29): add the
  required `discord_bot_token` field next to `openweather_api_key` / `discord_webhook_url`
  (D-14). `weatherbot/config/loader.py` `load_settings()` is the fail-loud load point.
- `weatherbot/config/models.py` — add the operator user ID to a config model (`[bot]`
  section; D-06) following the existing pydantic-model + `frozen=True` house style.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`lookup_weather` (Phase 6)** — the entire fetch→render path; returns `forecast` for
  the embed (D-07) and `text` if ever needed. Sync → `run_in_executor` (D-10). No new
  weather code in this phase.
- **`parse_weather_command` (Phase 6)** — three-state parser; reused after stripping the
  `!weather` prefix (D-03). Bare `!weather` → default location for free.
- **`DiscordWebhookChannel.send_briefing(text, forecast)`** — the embed builder to mirror
  for inbound replies (D-07); `channel.send(text)` for plain status posts.
- **`ConfigHolder.current()` (Phase 8)** — lock-free live-config read the bot uses to
  resolve locations / read the operator id; reloads are atomic via the holder.
- **`_do_reload(channel=…)` + `_reconcile_jobs` diff (Phase 9/10)** — the reload-outcome
  seam; the `channel` is ALREADY passed in, and the `(added, removed, changed, unchanged)`
  tuple is already produced — CFG-07 (D-13) reads the structured values, not the log line.
- **File-watch observer lifecycle in `run_daemon`** — the model for the bot thread's
  start-and-join-in-`finally` pattern (D-09); SIGTERM clean-shutdown path to reuse.
- **`Settings` + `load_settings()` fail-loud** — the home for `DISCORD_BOT_TOKEN` (D-14).

### Established Patterns
- **Per-job/handler exception isolation** — v1's "one failure can't stop the briefing"
  discipline; the bot mirrors it with a try/except around the whole handler (D-11), a
  different mechanism (loop-on-another-thread) for the same guarantee.
- **systemd `Type=notify` + `gate_until_healthy`** — only startup/restart runs the health
  gate; the bot deliberately never touches READY (D-11). Mirrors Phase 9 D-04 (reload also
  stays out of the READY gate).
- **Secrets in git-ignored `.env` via pydantic-settings; non-secret structure in
  `config.toml`** — the token goes in `.env` (D-14), the operator id in `config.toml` (D-06).
- **`frozen=True` config snapshots** — any new `[bot]` config model follows the house style.

### Integration Points
- New inbound path: Discord gateway → `on_message` → `author.bot`/operator guards →
  strip `!weather` → `parse_weather_command` → `run_in_executor(lookup_weather, holder.current())`
  → build embed → reply.
- CFG-07: `_do_reload` (file-watch OR explicit trigger) → capture `_reconcile_jobs` tuple /
  validation reason → post status embed via the channel handle.
- Shared quota cache sits between `lookup_weather`'s fetch and OpenWeather; bounded to
  configured locations; designed so the scheduled path could read it too (D-12).
- Bot thread ↔ daemon: bot receives the same `holder` instance + a `channel`; started and
  torn down inside `run_daemon`'s lifecycle (D-09).
</code_context>

<specifics>
## Specific Ideas

- The inbound reply should look **identical to the morning briefing embed** — same
  `forecast`-driven embed, so the channel reads consistently (D-07).
- Reload status posts should be **visually distinct** from briefing embeds (a small status
  embed, not a full briefing) so the operator can tell config chatter from weather (D-13).
- The single most important verifications (roadmap SCs / Pitfalls):
  1. **SC#3 (Pitfall #2):** feed a simulated *webhook-authored* message → assert NO command
     fires.
  2. **SC#4 (Pitfall #4):** revoke/invalidate the bot token → assert the next scheduled
     briefing STILL fires and the systemd READY gate is untouched.
  3. **SC#1 (Pitfall #1):** a real/slow OpenWeather fetch inside `on_message` produces NO
     "Heartbeat blocked" warning (all sync work via `run_in_executor`).
  4. **SC#2 (Pitfall #10):** two `!weather <same loc>` within the TTL → second serves from
     cache, no second OpenWeather call.
- Unknown location replies with the configured-names hint (`UnknownLocationError.valid_names`).

</specifics>

<deferred>
## Deferred Ideas

- **Arbitrary/geocoded `weather <any city>`** — v2.0 (CMD-V2-02); v1.1 is
  configured-locations-only.
- **Telegram / SMS inbound channels** — v2.0 (CHAN-V2-01/02).
- **Per-user cooldown / multi-user anti-spam** — explicitly a non-goal for this
  single-user tool; the TTL cache (D-12) + operator allowlist (D-05) are the guards.
- **Slash commands `/weather`** — considered (no privileged intent, future-proof) but the
  operator chose the prefix form (D-01). Revisit if Discord tightens `message_content`
  privileged-intent access or a multi-user need appears.
- **Wiring the scheduled briefing path to actually READ the shared cache** — the cache is
  *designed* to be shareable (D-12), but the scheduler-READ seam is still DEFERRED; full
  scheduler-cache integration can be a later tidy-up. (Distinct from cache INVALIDATION on
  reload, which is now WIRED: `_do_reload` invalidates the bot cache best-effort after a
  successful swap — CR-01 closed, quick task 260617-fua.)

</deferred>

---

*Phase: 11-Discord Inbound Gateway Bot*
*Context gathered: 2026-06-16*
