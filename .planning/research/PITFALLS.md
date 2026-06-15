# Pitfalls Research

**Domain:** Adding an inbound Discord gateway bot + full-config hot-reload to an existing always-on Python scheduler daemon (WeatherBot v1.1)
**Researched:** 2026-06-15
**Confidence:** HIGH (asyncio/thread + discord.py intents + APScheduler facts verified against current official docs; idempotency/secrets/systemd specifics derived from this codebase's documented v1 patterns)

> Scope note: These are integration pitfalls specific to bolting two NEW surfaces onto the *shipped* v1.0 daemon — a thread-based `BackgroundScheduler`, config-loaded-once-at-startup (tomllib + pydantic-settings, validate-on-load fail-loud), outbound `DiscordWebhookChannel`, SQLite sent-log with `(location, send_time, local_date)` exactly-once key, and systemd `Type=notify` `Restart=always`. Generic "use asyncio properly" advice is omitted; everything below is about the seam where the new feature meets the existing daemon.

## Critical Pitfalls

### Pitfall 1: The asyncio bot loop and the thread-based BackgroundScheduler stomp each other

**What goes wrong:**
v1 runs `APScheduler.BackgroundScheduler` (thread pool, no event loop). discord.py *requires* a running asyncio event loop on its own thread. Naively, devs either (a) call `bot.run()` (which calls `asyncio.run()` and **blocks the calling thread forever**, so it must not run on the thread that owns the scheduler/main lifecycle), or (b) try to drive both from one thread and one of them never gets serviced. The classic failure: the bot's `on_message` handler calls the existing **synchronous** briefing/fetch/SQLite code directly inside the coroutine, blocking the event loop. discord.py then logs `Heartbeat blocked for more than N seconds`, the gateway connection is dropped by Discord, and the bot silently reconnects in a loop or dies.

**Why it happens:**
v1's entire fetch → render → send → persist path is synchronous (httpx sync client, stdlib `sqlite3`, tenacity sync retry). Reusing it from an `async def on_message` is the obvious move, but every sync call inside a coroutine blocks the loop until it returns. A single slow OpenWeather call (the same calls v1 deliberately bounds with timeouts) freezes the heartbeat.

**How to avoid:**
- Run the bot on its **own dedicated thread/loop**, separate from the scheduler thread. Keep `BackgroundScheduler` exactly as v1 has it (do NOT migrate the briefing scheduler to `AsyncIOScheduler` — that's a bigger, riskier change and the briefing path is sync).
- Inside `on_message`, **never call sync code directly**. Wrap the existing sync lookup with `await loop.run_in_executor(None, do_lookup, location)` so the blocking work runs on a worker thread and the loop stays free.
- For the reverse direction (a scheduler-thread or signal-handler needs to tell the bot something), use `asyncio.run_coroutine_threadsafe(coro, bot.loop)` / `bot.loop.call_soon_threadsafe(...)` — never touch loop objects from the wrong thread.
- Share read-mostly state (the live config object) via a single guarded reference, not by calling across loops.

**Warning signs:**
`Heartbeat blocked for more than N seconds` in logs; bot goes unresponsive then reconnects; commands work the first time then hang; CPU pinned on one thread; `RuntimeError: ... attached to a different loop`.

**Phase to address:** Discord-bot phase (the inbound-command phase). Establish the "bot loop on its own thread + `run_in_executor` for all sync work" pattern as the very first structural decision of that phase.

---

### Pitfall 2: Bot replies to its own messages / to the outbound briefing webhook (feedback loop)

**What goes wrong:**
The bot's command parser fires on every message in the channel. Two loop sources: (a) the bot reacts to **its own** reply, re-triggering itself; (b) more subtly for THIS project — the v1 **outbound briefing is posted via a Discord *webhook* into the same channel the bot is listening in.** Webhook messages have `author.bot == True` but are NOT authored by the bot's own user ID. If the command trigger is loose (e.g. any message containing "weather"), the daily briefing or a manual `--send-now` post can trip the command handler, firing an OpenWeather call and a reply — an automated bot replying to an automated briefing.

**Why it happens:**
v1's outbound path and v1.1's inbound path share one Discord channel. Devs copy the canonical `if message.author == bot.user: return` guard but forget that the webhook is a *different* author that also needs filtering, and that briefing text legitimately contains the word "weather"/location names.

**How to avoid:**
- Guard with `if message.author.bot: return` (covers self AND the webhook — `webhook_id` is set / `author.bot` is True for webhook messages), not just `== bot.user`.
- Require an explicit, **unambiguous command form** (a prefix like `!weather home` or a slash command), never substring-matching free text. Slash commands sidestep the whole `message_content` privileged-intent problem (see Pitfall 3) and can't be triggered by the briefing text.
- Optionally restrict the bot to respond only to the single configured operator user ID (this is a single-user tool) and/or ignore messages whose `webhook_id is not None`.

**Warning signs:**
Bot replies right after each scheduled briefing; OpenWeather call count spikes at briefing times; reply-to-reply storms; quota burns down on a quiet day.

**Phase to address:** Discord-bot phase. Bake the `author.bot` + explicit-command-form guard into the handler from the first commit; add a test that feeds a simulated webhook-authored message and asserts no command fires.

---

### Pitfall 3: Gateway intents / token misconfiguration (message_content) — works locally, silent in prod

**What goes wrong:**
Prefix commands like `!weather home` need the **Message Content** intent, which is a **privileged intent**: it must be enabled BOTH in code (`intents.message_content = True`) AND toggled on in the Discord Developer Portal. If only one side is set, the bot connects fine, shows online, but `message.content` arrives empty and commands silently never match — no error. Separately, the **bot token** is a brand-new secret (distinct from the v1 webhook URL) and devs habitually paste it into `config.toml`.

**Why it happens:**
The portal toggle is out-of-band (not in code), so it's easy to miss; the failure is silent (empty content, not an exception). And v1 only ever needed the webhook URL in `.env`, so the bot token is a new kind of secret that doesn't have an established home yet.

**How to avoid:**
- Prefer **slash commands** (application commands) over prefix commands — they don't require the message_content privileged intent at all, are future-proof against Discord's privileged-intent crackdowns, and can't be tripped by briefing text (ties back to Pitfall 2).
- If using prefix commands, document the portal toggle as an explicit deploy step and assert at startup that the intent is set.
- Store `DISCORD_BOT_TOKEN` in the **git-ignored `.env`** exactly like `DISCORD_WEBHOOK_URL`; load via pydantic-settings; fail-loud on startup if missing. Never in `config.toml`. Add the token to any pre-commit secret scan.

**Warning signs:**
Bot online but ignores commands; `message.content` is `''`; slash commands not appearing (un-synced); token visible in `git diff`; `PrivilegedIntentsRequired` exception on connect.

**Phase to address:** Discord-bot phase. Secret-handling decision (token in `.env`) on day one of the phase; intent/command-type decision in the same phase's design step.

---

### Pitfall 4: A bot crash or gateway failure takes down the whole briefing daemon

**What goes wrong:**
v1's hard-won reliability guarantee is "the morning briefing always goes out." If the bot loop and the scheduler share a process (they do), an unhandled exception in `on_message`, an unrecoverable gateway error, or a token-revoked condition can propagate and kill the process — or worse, leave a half-dead process that systemd considers "active" so it doesn't restart it. The interactive nicety silently breaks the core value.

**Why it happens:**
The bot is the new, less-critical feature, but it's the one holding a fragile long-lived network connection (gateways disconnect routinely; tokens can be rotated). Without isolation, the fragile component's failure mode becomes the reliable component's failure mode. v1 already established **per-job exception isolation** for the scheduler; the bot needs the same discipline but it's a different mechanism (a loop on another thread, not an APScheduler job).

**How to avoid:**
- Mirror v1's per-job isolation: wrap the entire `on_message`/command handler in try/except that logs and replies with an error but **never** propagates out of the coroutine.
- Treat the bot as **non-critical and self-contained**: if the gateway connection dies and can't recover, the bot thread should log CRITICAL (reuse v1's alert table/structlog path) and stop — but the **scheduler thread and the briefing path must keep running untouched.** Briefings do not depend on the bot.
- Let discord.py handle reconnects (it auto-reconnects with backoff), but cap/alert on persistent failure rather than busy-looping.
- Keep systemd's health gate honest: a dead bot thread should NOT by itself flip the process to unhealthy if briefings still work — but a dead *scheduler* still must. Don't let bot health pollute the v1 `gate_until_healthy` READY=1 signal.

**Warning signs:**
A missed morning briefing that correlates with a bot stack trace; process exits with a discord.py traceback; systemd shows the unit restarting at odd times tied to gateway events; reconnect log spam.

**Phase to address:** Discord-bot phase. Isolation + "bot failure ≠ briefing failure" is a phase success criterion. Verify by killing the gateway connection (revoke/invalid token) and confirming a scheduled briefing still fires.

---

### Pitfall 5: Hot-reload reads a half-written config file (editor save semantics)

**What goes wrong:**
File-watchers fire on the first write event, but editors don't write atomically the way you'd hope: some truncate-then-write (a watcher firing mid-write sees an empty or partial TOML → parse error or, worse, a *valid-but-incomplete* config), some write to a temp file then rename, some fire multiple events per save. Reloading on the partial read either crashes the reload or — the dangerous case — loads a config that parses but is missing locations/schedules.

**Why it happens:**
"Watch file, on change reload" looks trivial. The complexity is entirely in *when* the file is in a consistent state. Different editors (vim with backup+rename, VS Code atomic-write, `>` truncation) produce different event sequences.

**How to avoid:**
- **Debounce** file events (e.g. coalesce events within ~200–500ms) before attempting a reload, so a multi-event save triggers one reload after writing settles.
- **Validate-then-swap, never mutate in place:** parse + run the full pydantic validation into a *new* config object; only on full success atomically replace the live reference. This is just v1's validate-on-load fail-loud logic, reused — but on failure it **keeps the old config** instead of exiting.
- Treat any parse/validation failure as "reject this reload, log it, alert, keep running on the old config" — exactly the milestone's stated "keep-the-old-config-on-failure" rule.
- Consider an **explicit trigger** (signal/CLI command/bot command) as the primary path and file-watch as convenience; the explicit trigger avoids editor-timing entirely.

**Warning signs:**
Reload fails intermittently and only with one editor; "config reloaded" log followed by missing-location behavior; `tomllib.TOMLDecodeError` on save; locations disappear after an edit that "looked fine."

**Phase to address:** Hot-reload phase. Debounce + atomic validate-then-swap is the core mechanic of the phase. Test with truncate-write, temp-then-rename, and multi-event saves.

---

### Pitfall 6: A bad reload leaves the daemon half-applied instead of cleanly keeping the old config

**What goes wrong:**
The reload partially succeeds: new templates loaded, but schedule re-registration threw halfway; or the config object swapped but the APScheduler jobs weren't rebuilt. The daemon is now in a state that matches *neither* the old nor the new config — undefined behavior, possibly no jobs scheduled, possibly stale templates with new locations.

**Why it happens:**
A full-config reload touches several subsystems (config object, APScheduler jobs, template cache, units). If reload mutates them one at a time, a failure midway leaves a torn state. The milestone explicitly wants "keep the old config on failure" — but that guarantee is only real if the *application* of the new config is all-or-nothing, not just the *parsing*.

**How to avoid:**
- Two-phase reload: **(1) build & fully validate** a complete new application state (config + the set of jobs it implies + rendered/validated templates) entirely off to the side; **(2) commit** by swapping the live references and re-registering jobs only after phase 1 fully succeeds.
- If job re-registration itself can fail, snapshot the old job set so you can roll back to it.
- Make the live config a single swappable reference read under a lock, so readers always see either fully-old or fully-new, never a torn mix.

**Warning signs:**
After a rejected reload, briefings stop firing or fire on the wrong schedule; template uses a location that no longer exists; "kept old config" logged but behavior changed anyway.

**Phase to address:** Hot-reload phase. "All-or-nothing apply" is a phase success criterion; verify by injecting a failure during job re-registration and asserting the old schedule still fires.

---

### Pitfall 7: Reload re-registering APScheduler jobs double-fires or drops the morning briefing

**What goes wrong:**
On reload you must reconcile the live job set with the new config. The naive approaches both break: (a) `remove_all_jobs()` then re-add — if a slot's fire time falls in the gap, that briefing is **dropped**; and removing/re-adding can race with a job that's mid-fire. (b) Add new jobs without removing old ones — now you have **duplicate jobs double-firing** the same briefing. Either way you've broken a core v1 guarantee on a reload.

**Why it happens:**
APScheduler jobs are identified by job IDs; reload tends to be written as "tear down and rebuild" rather than "diff and reconcile." The exactly-once sent-log (Pitfall 8) catches *some* double-fires, but not schedule drops, and not double-fires that map to different idempotency keys.

**How to avoid:**
- Use **stable, deterministic job IDs** derived from `(location, send_time)` and `scheduler.add_job(..., id=..., replace_existing=True)` so reconciliation is idempotent: re-adding an unchanged job is a no-op, changed jobs update in place, and only genuinely-removed slots get `remove_job`.
- **Diff** old vs new job sets; add/update/remove only the delta — don't blanket-clear.
- Lean on v1's exactly-once sent-log as the backstop, but design reload not to *rely* on it for correctness.
- Avoid reloading at a moment a job is firing where practical (see Pitfall 9).

**Warning signs:**
Two identical briefings arrive minutes apart after an edit; a briefing is missed only on days a reload happened; APScheduler logs "job added" without matching "job removed"; growing job count across reloads.

**Phase to address:** Hot-reload phase. Stable-job-ID + diff-reconcile is the scheduler-integration deliverable of the phase. Verify by reloading with one slot added, one changed, one removed, and asserting the live job set matches exactly once each.

---

### Pitfall 8: Reload changes a location's timezone/schedule and breaks the exactly-once idempotency key

**What goes wrong:**
v1's exactly-once key is `(location, send_time, local_date)`. If a reload renames a location, changes its IANA timezone, or shifts a `send_time`, the *new* config can compute a **different idempotency key for the same calendar morning**, so a slot that already sent (under the old key) is treated as un-sent under the new key → **duplicate briefing**. Conversely, a tz change can make "today's date" resolve differently and silently skip a send. This is the most subtle interaction between the two new features and the existing reliability machinery.

**Why it happens:**
The sent-log key embeds config-derived values (location name, send_time, and tz determines local_date). Hot-reload was scoped as "swap config," but nobody traced that the config feeds the idempotency key, which assumes config is stable within a day.

**How to avoid:**
- Treat the idempotency key's inputs as semi-stable: prefer a **stable location identifier** (an immutable `id`/slug) over the display name in the key, so renaming a location's display string doesn't reset its sent-state.
- On reload, for any slot whose tz/send_time changed, decide the policy explicitly: by default **do not re-fire** a slot already marked sent for today (check the sent-log on the *old* key OR treat "already sent today for this location id" as the guard). Document and test the chosen rule.
- When tz changes mid-day, recompute `local_date` carefully and ensure a slot already delivered today can't re-deliver.

**Warning signs:**
A second briefing arrives the same morning right after a config edit; renaming a location causes a duplicate send; changing tz around midnight causes a skipped or doubled send; sent-log rows with near-duplicate keys differing only by location string.

**Phase to address:** Hot-reload phase (high-risk — flag for deeper plan-phase research). This is the pitfall most likely to silently break a shipped guarantee; give it an explicit success criterion and a test that reloads a tz/name change for an already-sent slot and asserts no re-send.

---

### Pitfall 9: Reload during an in-flight send (or a send fired during a reload)

**What goes wrong:**
A briefing job is mid-execution (fetching/sending/persisting) when a reload swaps the config object out from under it. The in-flight job then reads a half-swapped config — wrong template, wrong location coords, or a units mismatch between the fetch (old config) and the render (new config). Or the sent-log claim was made under the old config and the persist happens under the new one.

**Why it happens:**
The reload thread and the scheduler worker thread both touch the shared config reference with no coordination. v1 jobs grab config once at start; reload assumes jobs read config atomically, which isn't guaranteed without a lock or a snapshot.

**How to avoid:**
- Each scheduled job should **snapshot the config reference once at the top of the job** and use that snapshot for its entire fetch→render→persist lifecycle, so a mid-job reload can't tear it.
- Guard the live-config swap with a lock; readers take the reference (cheap) under the lock and then operate on their immutable snapshot.
- Don't make the swap block on in-flight jobs — snapshotting makes that unnecessary and avoids deadlock between the reload path and the scheduler pool.

**Warning signs:**
A briefing sent with the old template but new location set (or vice versa); units mismatch in one message; intermittent `KeyError`/missing-field on render right after a reload.

**Phase to address:** Hot-reload phase. "Per-job config snapshot" is a small but mandatory part of the apply step. Verify by triggering a reload while a `--send-now`-style job is deliberately slowed.

---

### Pitfall 10: Command spam burns the OpenWeather quota / hits rate limits

**What goes wrong:**
v1's call volume is tiny and predictable (a couple of calls per scheduled briefing). The inbound bot makes call volume **user-driven and unbounded** — repeated `!weather home` (or a webhook-loop from Pitfall 2) can blow through the card-on-file One Call 3.0 quota, incurring cost, or trip the API rate limit so the *scheduled* briefing later fails.

**Why it happens:**
The interactive feature removes the natural rate limiting that the scheduler provided. Easy to forget that on-demand = unbounded.

**How to avoid:**
- **Cache** recent lookups per location with a short TTL (e.g. reuse the last fetch for N minutes — the forecast barely changes minute-to-minute), so rapid repeated commands serve from cache, not the API.
- Per-user / per-channel **cooldown** on the command (discord.py has built-in cooldown decorators).
- Since lookups are configured-locations-only (per PROJECT.md), the call surface is bounded to a handful of locations — exploit that with a shared cache the scheduled briefings could also benefit from.
- Keep an eye on the same quota the briefing depends on; never let interactive use endanger the guaranteed morning send.

**Warning signs:**
OpenWeather usage graph spikes; 429/quota errors; a scheduled briefing fails with rate-limit right after heavy interactive use; bill higher than expected.

**Phase to address:** Discord-bot phase. Cooldown + short-TTL cache is part of the command-handler deliverable.

---

### Pitfall 11: File-watch fd leaks / infinite reload loops / watching the wrong thing

**What goes wrong:**
Long-running file-watchers can (a) leak file descriptors / inotify watches over days if observers aren't reused or stopped cleanly, eventually hitting `inotify watch limit reached`; (b) loop forever if the reload process itself writes near the watched file (e.g. writing a `.bak`) re-triggering the watcher; (c) miss events if watching the file directly (atomic-rename replaces the inode, breaking a file-level watch) — you usually must watch the *directory*.

**Why it happens:**
inotify semantics are surprising: editors replace inodes, watchers on the old inode go deaf; and a daemon that runs for weeks exposes resource leaks a short test never shows.

**How to avoid:**
- Use a mature watcher (`watchdog`) with a **single long-lived observer**, started once and stopped on SIGTERM (reuse v1's clean-shutdown path).
- **Watch the config directory**, filter to the config filename, to survive atomic-rename inode swaps.
- Never write anything back near the watched file during reload (no auto-formatting/backup into the watched dir).
- The explicit-trigger path needs none of this — keep file-watch optional and the daemon fully functional without it.

**Warning signs:**
`OSError: inotify watch limit reached` after days of uptime; reload fires in a tight loop; edits stop being detected after the first save (inode swap); fd count climbing in `/proc/<pid>/fd`.

**Phase to address:** Hot-reload phase. Directory-watch + single observer + clean teardown; soak-test for fd stability.

---

### Pitfall 12: Secrets reload semantics — does `.env` reload too?

**What goes wrong:**
Hot-reload is scoped to the *config* (schedules/locations/units/templates), but operators will assume editing `.env` (rotating the OpenWeather key, the webhook URL, or the new bot token) is also picked up live. pydantic-settings reads env/`.env` **once at process start**; a reload that only re-reads `config.toml` will silently keep using the *old* secret, or a reload that naively re-instantiates settings might re-read `.env` inconsistently (env vars already in the process environment vs file).

**Why it happens:**
The mental model "reload = pick up my edits" doesn't distinguish config from secrets. And the bot token is a new secret whose rotation story didn't exist in v1.

**How to avoid:**
- **Decide and document the boundary explicitly:** hot-reload covers `config.toml` only; **secret changes require a process restart** (systemd `restart` is one command and re-reads `.env`). This matches the milestone scope (full-*config* reload) and avoids the half-reloaded-secret trap.
- If the bot token / API key rotates, restart — don't try to live-swap a gateway connection's token.
- Make the reject/keep-old logic apply only to config; never let a config reload silently re-read or partially apply secrets.

**Warning signs:**
Operator edits `.env`, expects new key, old key still used (or 401 after a rotation that "should" have reloaded); confusion about why a webhook/token change "didn't take."

**Phase to address:** Hot-reload phase. One sentence in the phase's design + the operator docs; cheap to get right, costly to leave ambiguous.

---

### Pitfall 13: systemd reload signaling — RELOADING=1 / READY=1 lifecycle

**What goes wrong:**
v1 is `Type=notify` and gates `READY=1` on a healthy startup self-check. If hot-reload is wired to `SIGHUP` (the conventional reload signal) without telling systemd, `systemctl reload weatherbot` either does nothing useful or systemd's view of the unit drifts from reality. And if a reload transiently makes the daemon unhealthy, not emitting `RELOADING=1`/`READY=1` around it can confuse the watchdog/health state.

**Why it happens:**
`Type=notify` units have a reload protocol (`ExecReload` + `sd_notify("RELOADING=1")` ... `sd_notify("READY=1")`); it's easy to implement an in-app reload and forget the systemd side exists, leaving two reload mechanisms (file-watch and `systemctl reload`) that disagree.

**How to avoid:**
- Pick the trigger surface deliberately. If you expose `systemctl reload`, implement the sd_notify `RELOADING=1` → `READY=1` handshake in the SIGHUP handler. If reload is purely file-watch + an app-level trigger, keep `ExecReload` out of the unit so operators don't get a misleading `systemctl reload`.
- Since reload keeps-old-config-on-failure (never goes unhealthy), the simplest correct choice is: reload does NOT touch the systemd ready state at all (it's always either old-good or new-good). Only a *restart* re-runs `gate_until_healthy`.
- Keep `WatchdogSec` (if used) satisfied throughout reload — a reload must not block the main thread long enough to miss a watchdog ping.

**Warning signs:**
`systemctl reload` says success but nothing changed; unit shows `reloading` and never returns to `active`; watchdog restarts the process during a reload.

**Phase to address:** Hot-reload phase (deployment/integration step). Decide the trigger surface and align the unit file; verify `systemctl reload` (if exposed) and file-watch produce identical results.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Run discord.py bot on the main thread with `bot.run()`, scheduler as background | Fewest lines; "it works" | `bot.run()` blocks; lifecycle/shutdown coordination with the scheduler thread gets tangled; SIGTERM handling becomes fragile | Never for this daemon — lifecycle is already non-trivial (systemd, catch-up, clean shutdown) |
| Call v1's sync fetch/SQLite directly inside `on_message` | Reuse existing code as-is | Blocks the event loop → heartbeat drops, gateway churn (Pitfall 1) | Never — always `run_in_executor` |
| `remove_all_jobs()` + rebuild on every reload | Simple reconciliation | Drops/double-fires briefings (Pitfall 7) | Only if combined with a date-window guard AND the exactly-once log is proven to cover the gap — generally avoid |
| Prefix commands + `message_content` intent | Familiar `!weather` UX | Privileged-intent approval friction; can be tripped by briefing text (Pitfall 2) | OK for a private single-server bot; slash commands are the cleaner default |
| File-watch as the only reload trigger | "Just edit and save" UX | Editor-timing fragility, inode-swap deafness, fd leaks (Pitfalls 5, 11) | OK only with debounce + directory-watch + an explicit-trigger fallback |
| Treat `.env`/secrets as hot-reloadable | "Everything is live" | Half-reloaded secrets, inconsistent env vs file (Pitfall 12) | Never — config-only reload; secrets need restart |
| Mutating the live config object field-by-field | Less plumbing than swap | Torn reads, half-applied state (Pitfalls 6, 9) | Never — build-then-atomic-swap |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| discord.py gateway ↔ BackgroundScheduler | Driving both from one thread/loop, or calling sync briefing code in coroutines | Bot loop on its own thread; `run_in_executor` for sync work; `run_coroutine_threadsafe`/`call_soon_threadsafe` to cross threads; keep BackgroundScheduler unchanged |
| discord.py message events ↔ v1 outbound webhook in same channel | `if message.author == bot.user` only (misses webhook author) | `if message.author.bot: return` + explicit command form (prefix/slash) + optional operator-user-ID allowlist |
| Discord Developer Portal ↔ code intents | Enabling `message_content` in code but not the portal (or vice versa) → silent empty content | Enable both, or use slash commands (no privileged intent); assert intent at startup |
| Bot token ↔ config file | Pasting `DISCORD_BOT_TOKEN` into `config.toml` | `.env` only, loaded via pydantic-settings, fail-loud if missing, in pre-commit secret scan — same handling as the v1 webhook URL |
| OpenWeather One Call 3.0 ↔ on-demand commands | Unbounded user-driven calls against the card-on-file quota | Short-TTL per-location cache + per-user cooldown; bounded to configured locations only |
| Config reload ↔ exactly-once sent-log | Key derived from mutable location name/tz; reload resets sent-state | Key off a stable location id; on reload don't re-fire already-sent-today slots; test tz/name change |
| Config reload ↔ APScheduler job set | Tear-down-and-rebuild | Stable job IDs `(location, send_time)` + `replace_existing=True` + diff/reconcile delta only |
| Config reload ↔ pydantic-settings secrets | Assuming `.env` reloads with config | Config-only reload; document that secret rotation needs a restart |
| In-app reload ↔ systemd `Type=notify` | SIGHUP reload with no sd_notify handshake, or a misleading `ExecReload` | Reload stays ready (old-good/new-good); don't expose `systemctl reload` unless you implement RELOADING=1→READY=1 |
| File-watch (inotify) ↔ editor save | Watching the file inode; reloading on first/partial event | Watch the directory; debounce; validate-then-swap; single long-lived observer stopped on SIGTERM |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Sync work blocking the bot loop | "Heartbeat blocked for N seconds"; bot unresponsive then reconnects | `run_in_executor` for all blocking calls | First slow OpenWeather/SQLite call inside a coroutine |
| inotify watch / fd leak over long uptime | fd count climbs; `inotify watch limit reached` | Single long-lived observer; clean teardown | After days/weeks of continuous running (won't show in a short test) |
| Unbounded on-demand API calls | OpenWeather usage spike; 429; scheduled briefing later fails | Short-TTL cache + cooldown | As soon as commands are used repeatedly / a webhook-loop fires |
| Job count growth across reloads | APScheduler job list grows each reload; duplicate fires | Stable job IDs + `replace_existing` + diff-reconcile | After several config edits over the daemon's lifetime |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Bot token committed in `config.toml` | Full control of the bot account; token must be regenerated; potential abuse of the server | Token in git-ignored `.env`; pre-commit secret scan; same handling as the v1 webhook URL |
| Bot responds to anyone in the channel | Any server member can drive OpenWeather calls / burn quota | Restrict to the operator's user ID (single-user tool); per-user cooldown |
| `message_content` intent enabled broadly when not needed | Bot reads all channel message content (privacy/scope creep) | Prefer slash commands (no message_content needed); minimal intents |
| Reloading a config that points at attacker-influenced paths/URLs | Less relevant (local single-user) but: a malformed reload accepted blindly | validate-then-swap rejects malformed config; keep-old on failure |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Reload silently rejected with no feedback | Operator edits config, nothing changes, no idea why | Log + alert (reuse v1 alert path) on rejected reload, with the validation error; reply in Discord if reload was bot-triggered |
| Bot gives no response on a bad/unknown location | User unsure if the bot is alive or just slow | Reply with a clear "unknown location: configured are X, Y" (configured-locations-only is a known constraint) |
| No "thinking" feedback during a slow OpenWeather fetch | User re-issues the command (→ quota burn) | Typing indicator / immediate ack, then edit the message with the result |
| Reload changes schedule but operator can't confirm it took | Uncertainty about whether tonight's briefing is right | On successful reload, log/reply a summary of the new active schedule |

## "Looks Done But Isn't" Checklist

- [ ] **Discord bot:** Often missing the `author.bot` guard against the *webhook* author — verify the daily briefing posted into the bot's channel does NOT trigger a command (test with a simulated webhook message).
- [ ] **Discord bot:** Often missing event-loop hygiene — verify no "Heartbeat blocked" warnings under a slow/real OpenWeather call (all sync work via `run_in_executor`).
- [ ] **Discord bot:** Often missing failure isolation — verify a revoked/invalid token or killed gateway does NOT stop a scheduled briefing from firing.
- [ ] **Discord bot:** Often missing the token-in-`.env` move — verify `DISCORD_BOT_TOKEN` is absent from `config.toml` and `git`-tracked files.
- [ ] **Hot-reload:** Often missing atomic all-or-nothing apply — verify a failure during job re-registration leaves the OLD schedule fully intact (not torn).
- [ ] **Hot-reload:** Often missing exactly-once preservation — verify renaming a location / changing its tz does NOT cause a duplicate or skipped send for an already-sent slot today.
- [ ] **Hot-reload:** Often missing debounce / partial-read handling — verify a multi-event editor save triggers exactly one reload and never parses a half-written file.
- [ ] **Hot-reload:** Often missing the job diff — verify reloading the SAME config produces zero job changes and no duplicate fires.
- [ ] **Hot-reload:** Often missing the secrets boundary — verify editing `.env` does NOT silently half-apply; document that secrets need a restart.
- [ ] **Hot-reload:** Often missing systemd alignment — verify `systemctl reload` (if exposed) and file-watch produce identical results and the unit returns to `active`.
- [ ] **Both:** Often missing clean shutdown — verify SIGTERM stops the bot thread, the file-watch observer, and the scheduler cleanly (reuse v1's shutdown path).

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Bot blocking the loop / gateway churn | LOW | Move offending sync call behind `run_in_executor`; restart process |
| Bot crash killed the daemon | MEDIUM | systemd `Restart=always` brings it back, but the gap is a missed bot window; root cause is missing isolation — add try/except around handler + decouple bot health from briefing health |
| Webhook/self message-loop burned quota | MEDIUM | Add `author.bot` guard + explicit command form; the quota cost is sunk for the period; add cooldown/cache to prevent recurrence |
| Bot token leaked in git history | HIGH | Regenerate token in Developer Portal immediately, move to `.env`, scrub history, audit for unauthorized use |
| Half-applied reload (torn state) | MEDIUM | Restart the process (re-loads clean config from disk + re-runs health gate); then fix to build-then-swap so reload is atomic |
| Reload caused duplicate/skipped briefing (idempotency-key break) | MEDIUM | Confirm sent-log rows; the duplicate is already delivered (annoyance, not data loss); fix key to use stable location id + already-sent-today guard |
| inotify fd leak / reload loop | LOW | Restart clears fds; switch to single directory-observer + debounce |
| systemd reload state stuck | LOW | `systemctl restart`; remove the misleading `ExecReload` or implement the sd_notify handshake |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. asyncio loop vs BackgroundScheduler | Discord-bot phase | No "Heartbeat blocked" under real OpenWeather latency; both surfaces responsive concurrently |
| 2. Bot replies to own/webhook messages | Discord-bot phase | Simulated webhook message triggers no command; reply does not re-trigger |
| 3. Intents/token misconfig | Discord-bot phase | Commands respond in prod; token absent from `config.toml`/git; startup asserts intent (or slash commands used) |
| 4. Bot crash kills briefings | Discord-bot phase | Revoked token / killed gateway leaves scheduled briefing firing on time |
| 5. Reload reads half-written file | Hot-reload phase | Truncate-write, temp-rename, multi-event saves each yield exactly one clean reload |
| 6. Half-applied reload state | Hot-reload phase | Injected job-registration failure leaves old schedule fully intact |
| 7. Job double-fire / drop on reload | Hot-reload phase | Add/change/remove one slot each → live job set correct; same-config reload = zero changes |
| 8. Reload breaks exactly-once key | Hot-reload phase (HIGH RISK — deeper plan research) | tz/name change for an already-sent slot → no re-send, no skip |
| 9. Reload during in-flight send | Hot-reload phase | Reload during a deliberately-slowed send → message uses one consistent config snapshot |
| 10. Command spam burns quota | Discord-bot phase | Rapid repeat commands serve from cache; cooldown enforced; scheduled briefing unaffected |
| 11. File-watch fd leak / loop | Hot-reload phase | fd count stable over a soak test; edits still detected after inode-swapping saves |
| 12. Secrets reload semantics | Hot-reload phase | `.env` edit not silently applied; restart picks it up; documented |
| 13. systemd reload signaling | Hot-reload phase | `systemctl reload` (if exposed) and file-watch identical; unit returns to `active`; watchdog satisfied |

## Sources

- discord.py FAQ — "Heartbeat blocked for more than N seconds", `time.sleep`/blocking in coroutines, `run_in_executor` (https://discordpy.readthedocs.io/en/stable/faq.html) — HIGH
- Discord message content privileged intent — portal + code toggle, `author.bot` self/webhook guard (https://www.pythondiscord.com/pages/tags/message-content-intent/, https://github.com/discord/discord-api-docs/discussions/5412) — HIGH
- APScheduler 3.x user guide — `BackgroundScheduler` is thread-based and isolated from the asyncio loop; `AsyncIOScheduler` for asyncio apps (https://apscheduler.readthedocs.io/en/3.x/userguide.html) — HIGH
- discord.py multithreading discussion — `run_coroutine_threadsafe` / crossing thread↔loop boundaries (https://github.com/Rapptz/discord.py/discussions/9749) — MEDIUM
- WeatherBot `.planning/PROJECT.md` Key Decisions — v1 patterns: per-job exception isolation, exactly-once `(location, send_time, local_date)` key + atomic claim, validate-on-load fail-loud, secrets-in-`.env`, systemd `Type=notify` `gate_until_healthy` — HIGH (project source of truth)
- WeatherBot `CLAUDE.md` — "don't use discord.py for webhooks" (applies to outbound only; inbound bot legitimately reverses this), reliability constraints — HIGH (project source of truth)
- systemd `Type=notify` reload protocol (RELOADING=1 → READY=1, `ExecReload`) — sd_notify(3) — MEDIUM (training data + standard systemd docs)

---
*Pitfalls research for: inbound Discord bot + config hot-reload on an existing always-on Python scheduler daemon*
*Researched: 2026-06-15*
