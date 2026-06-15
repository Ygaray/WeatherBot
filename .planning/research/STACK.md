# Stack Research

**Domain:** v1.1 additions to an always-on single-user Python weather-briefing daemon — adding an inbound Discord command bot + full-config hot-reload
**Researched:** 2026-06-15
**Confidence:** HIGH

> Scope note: This file covers ONLY the NEW stack needed for v1.1 (CMD-V2-01, ENH-V2-01).
> The v1.0 stack (Python 3.12+, uv, httpx, APScheduler 3.11.x, tenacity, structlog, SQLite,
> discord-webhook, pydantic/pydantic-settings, tomllib, systemd) is treated as fixed and is
> NOT re-evaluated here. Only two new third-party packages are recommended; everything else
> reuses what is already in the process. (The v1.0 stack rationale lives in CLAUDE.md.)

## Recommended Stack

### Core Technologies (new for v1.1)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **discord.py** | 2.7.1 | Inbound Discord command bot — persistent gateway connection that listens for `weather <location>` in a channel and replies in-channel | The canonical, most widely documented, actively-maintained Python Discord gateway library. `requires_python >=3.8`, so 3.12 is fine. `commands.Bot` with a single prefix command + `message_content` intent is the smallest possible inbound surface — exactly what a one-user "reply to a command" bot needs, with no command-tree/slash-sync ceremony required. Mature enough that the threading-coexistence pattern with a non-async host is well-trodden (run the bot's asyncio loop in its own thread; see Discord section below). NOTE: this does **not** contradict CLAUDE.md's "don't use discord.py for webhooks" — that rule was about *outbound fire-and-forget* sends. The outbound briefing path stays on `discord-webhook`; discord.py is added *only* for the new inbound gateway. |
| **watchfiles** | 1.2.0 | File-watching for config hot-reload — detect edits to `config.toml` and template files and trigger a validated reload | Modern, Rust-`notify`-backed watcher. `requires_python >=3.10` (3.12 fine). Two decisive advantages for this exact job: (1) **built-in debounce + settle** (the `debounce`/`step` args on `watch()`), which natively absorbs editor save-storms (temp file → rename → write) that otherwise fire 3-5 events per save; (2) tiny footprint and a single blocking generator (`for changes in watch(path): ...`) that drops cleanly into its own thread next to APScheduler. Maintained by the Pydantic org (Samuel Colvin), so it tracks Python releases promptly. Lighter mental model than watchdog's observer/handler/event-queue object graph for what is "watch ~2 paths, debounce, call reload()". |

### Supporting Libraries / stdlib (reused — NO new dependency)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **APScheduler** | 3.11.2 (already in stack) | Runtime job mutation for hot-reload | Already present. Reloading schedules at runtime needs **no new dependency**: `BackgroundScheduler` supports `add_job`, `remove_job`, `get_jobs()`, `remove_all_jobs()`, `modify_job`, and `reschedule_job` on a *running* scheduler. The clean reload pattern: build the new job set from the validated new config, then `scheduler.remove_all_jobs()` + re-`add_job` each `(location, send_time)` (or diff against `get_jobs()` and add/remove deltas). The default `MemoryJobStore` makes this trivial — no persistence/migration concerns. |
| **signal** | stdlib | Explicit SIGHUP-style reload trigger | For "reload on signal" use stdlib `signal.signal(signal.SIGHUP, handler)` — **no new dependency**. Caveat: Python signal handlers only run in the **main thread**, and the handler must do near-nothing (set a flag / `threading.Event`), with the actual reload performed off the handler. This dovetails with the existing v1 SIGTERM clean-shutdown handling already in `--run`. Pair SIGHUP (operator: `kill -HUP` / `systemctl reload`) with a `weatherbot reload` CLI subcommand for ergonomics. |
| **tomllib** | stdlib (3.11+, already used) | Re-read `config.toml` on reload | Already the v1 config reader. Reload = re-run the *same* tomllib + pydantic validation path used at startup, against the new file contents, in a try/except that keeps the old in-memory config on failure (the "validate-on-load, keep old on failure" requirement is a code pattern, not a library). |
| **pydantic / pydantic-settings** | 2.13.x / 2.14.x (already in stack) | Validate-on-reload | Reuse the existing startup validation models verbatim. A failed `model_validate` on the new config → log + keep old config. No new dependency. |
| **argparse / existing CLI layer** | stdlib (already used) | `weather <location>` one-shot CLI + `weatherbot reload` | The CLI lookup (CMD-V2-01 part a) must work standalone with **no running daemon** — it reuses the existing fetch/render code paths directly. `weatherbot reload` either signals the running PID (SIGHUP) or pokes a control path; no framework needed. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| ruff | Lint + format (already in stack) | discord.py event handlers are `async def`; ensure no false "unused" flags on event callbacks. |
| pytest | Tests (already in stack) | Test the reload logic with good/bad config fixtures (assert old config retained on bad input) and the command parser in isolation. **Do not** require a live Discord gateway in tests — unit-test the command handler function with a fake message object; the gateway itself is integration-only/manual. |

## Installation

```bash
# New v1.1 runtime dependencies (added to the existing uv project)
uv add discord.py        # inbound gateway command bot  -> 2.7.1
uv add watchfiles        # config file-watch hot-reload -> 1.2.0

# No other additions: APScheduler runtime mutation, signal, tomllib,
# pydantic, and the CLI layer are already present in the v1.0 stack.
```

## Discord: bot-vs-webhook, intents, and coexistence (explicit)

| Concern | Answer |
|---------|--------|
| **Can the existing outbound webhook and the new inbound bot share ONE Discord application?** | **Yes — one Discord *application* can hold both.** A Discord app has a bot user (with a **bot token**, used by discord.py for the gateway) *and* you can create incoming webhooks on a channel independently. They are separate credentials/transports under one app: the webhook URL (v1 outbound) and the bot token (v1.1 inbound) are unrelated secrets that happen to belong to the same app/server. **Recommendation: keep them logically separate anyway** — the outbound briefing path continues to POST to the webhook URL exactly as in v1 (provider-agnostic `Channel.send`), and the bot token is a *new* secret (`DISCORD_BOT_TOKEN` in `.env`) used only by the inbound listener. This preserves the v1 channel abstraction and means a bot-gateway outage never affects scheduled briefing delivery. |
| **Token / intents setup** | In the Discord Developer Portal: enable the **Message Content** privileged intent on the app's Bot page (self-serve — **no Discord approval required** for a private bot under the small-bot threshold), then in code `intents = discord.Intents.default(); intents.message_content = True`. Without `message_content`, a prefix bot cannot read `weather <location>` text. Alternative that avoids the privileged intent entirely: use **slash commands** (`/weather location:...`) instead of a text prefix — slash command payloads don't need `message_content`. For a single-user bot the prefix approach is simplest; slash is the cleaner long-term option if intent friction appears. |
| **Coexistence with APScheduler `BackgroundScheduler` (asyncio vs threads)** | This is the critical integration point. `BackgroundScheduler` runs jobs on its own **thread pool** (not asyncio). discord.py is **asyncio** and wants to own an event loop. They coexist by **running the discord.py bot in its own dedicated thread** that creates and runs an asyncio loop: `loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop); loop.run_until_complete(bot.start(token))` inside a `threading.Thread`. The BackgroundScheduler thread(s), the watchfiles watcher thread, and the discord bot thread then all run in the same process under systemd, with the main thread free to host the signal handler and supervise. To call into the bot loop from another thread use `asyncio.run_coroutine_threadsafe(coro, bot_loop)`. Do **not** run BackgroundScheduler jobs *inside* the bot's loop or vice-versa — keep them as independent threads communicating via thread-safe primitives. |

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| **discord.py 2.7.1** | **interactions.py 5.16.0** | Slash-command-first framework with automated command sync and 100% API coverage. Choose it if you want *only* slash commands and like its batteries-included sync. For a single-user reply-to-a-command bot it's more framework than needed; discord.py has far more answers for the "run alongside a non-async app in a thread" question. |
| **discord.py 2.7.1** | **hikari 2.5.0** | Static-typed microframework aimed at large/performance-sensitive bots, usually paired with a command framework (lightbulb/tanjun). Overkill for one user; more assembly required. Pick only if you specifically want strict typing and a microframework architecture. |
| **discord.py 2.7.1** | **Pycord** | Active discord.py fork with strong slash-command ergonomics. Reasonable, but discord.py is the more universally documented baseline; no compelling reason to fork-shop for this scope. |
| **discord.py 2.7.1** | **Raw gateway over websockets/httpx** | Only if you want zero Discord framework dependency and are willing to hand-implement gateway heartbeat, reconnect/resume, and intents. Not worth it — reconnect logic alone is exactly what a library should own for a multi-day unattended process. |
| **watchfiles 1.2.0** | **watchdog 6.0.0** | Mature, broadest-platform observer/handler library. Choose it if you need an event *type* granularity or platform that watchfiles lacks, or already standardize on it. For "watch 2 paths, debounce editor saves, call reload" watchfiles is the lighter, more direct fit; watchdog needs hand-rolled debounce (e.g. `threading.Timer`) to coalesce save-storms. |
| **watchfiles 1.2.0** | **Polling (stat mtime on a timer)** | Zero-dependency fallback: poll `config.toml` + template mtimes every N seconds from a thread or an APScheduler interval job. Choose it if you want *no* new dependency at all and a few-seconds reload latency is acceptable — config edits are rare, so polling is genuinely defensible here. watchfiles is recommended for instant, debounced, lower-CPU reaction, but polling is a legitimate "minimize dependencies" choice for a personal bot. |
| **SIGHUP + `weatherbot reload`** | systemd `ExecReload=` | `systemctl reload weatherbot` mapping to SIGHUP is the natural operator UX on the systemd host — worth wiring `ExecReload=/bin/kill -HUP $MAINPID` into the unit so reload is a first-class systemd verb. (Complement, not replacement, of the CLI command.) |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Replacing `discord-webhook` with discord.py for the **outbound** briefing | The v1 outbound path is fire-and-forget and provider-agnostic; making briefings depend on a live gateway connection adds failure modes and contradicts the v1 channel abstraction. The webhook needs no token and no persistent connection. | Keep `discord-webhook` for outbound; add discord.py **only** for inbound. |
| Running discord.py with `asyncio.run()` / `bot.run()` on the **main thread** | It would block the process and starve the signal handler, the supervisor logic, and prevent BackgroundScheduler/watchfiles from owning their threads cleanly. | Run `bot.start()` inside a dedicated thread with its own `new_event_loop()`; keep the main thread for signal handling + supervision. |
| Doing real work **inside** the SIGHUP handler | Python only delivers signals to the main thread and handlers must be re-entrant-safe; heavy work (re-read + validate + rebuild jobs) in the handler risks races and partial state. | Handler sets a `threading.Event`/flag; a supervisor loop (or the watchfiles thread) performs the validated reload. |
| APScheduler **4.0.0aX** for runtime job mutation | Still alpha/pre-release (`4.0.0a6`), API unstable, explicitly not for production. The 3.11.x runtime mutation API already does everything hot-reload needs. | APScheduler **3.11.2** `add_job` / `remove_all_jobs` / `get_jobs` / `reschedule_job` on the running scheduler. |
| Enabling Discord intents you don't need (members, presence) | Extra privileged intents widen the bot's access surface for no benefit on a single-command bot. | Enable **only** `message_content` (prefix bot) — or use slash commands and enable **none** of the privileged intents. |
| A second outbound webhook as the bot reply transport | The inbound bot should reply **in-channel via the gateway** (`message.channel.send(...)`), which is the whole point of the gateway connection. | Reply through the bot's gateway connection, not the v1 outbound webhook. |
| Restarting the daemon to pick up config | Defeats the v1.1 hot-reload requirement and risks missing a scheduled briefing during the restart window. | watchfiles (or polling) → validate → swap config + rebuild jobs in place. |

## Stack Patterns by Variant

**If minimizing dependencies is the priority (Pi / "personal bot, keep it tiny"):**
- Skip watchfiles; poll config + template mtimes from an existing APScheduler interval job (e.g. every 5-10s) and reload on change. Zero new file-watch dependency.
- Use slash commands so you can avoid even the `message_content` privileged-intent toggle.
- Net new dependency footprint: just discord.py.

**If responsiveness / cleanliness is the priority (recommended default):**
- Use watchfiles for instant, debounced reload on save.
- Use discord.py prefix command (`weather <location>`) with `message_content` intent for the most natural chat UX.
- Wire `ExecReload=/bin/kill -HUP $MAINPID` in the systemd unit so `systemctl reload` works too.

**Reload-safety pattern (both variants):**
1. New config file event (watchfiles / SIGHUP flag / `reload` command) →
2. Re-read with tomllib → validate with the **existing** pydantic models →
3. On success: atomically swap the in-memory config object and rebuild APScheduler jobs (`remove_all_jobs()` then re-add from new config) →
4. On failure: log loudly (structlog), keep the **old** config + existing jobs untouched, optionally alert. A bad edit never takes down a live daemon.

## Version Compatibility

| Package@version | Compatible With | Notes |
|-----------------|-----------------|-------|
| discord.py@2.7.1 | Python 3.8+ (3.12 fine) | asyncio-based; run in its own thread+loop alongside the thread-based `BackgroundScheduler`. Use `asyncio.run_coroutine_threadsafe` to cross thread→loop. Requires `message_content` privileged intent for prefix commands (slash commands don't). |
| watchfiles@1.2.0 | Python 3.10+ (3.12 fine) | Rust-`notify` backend; built-in debounce coalesces editor save-storms. Blocking `watch()` generator runs in its own thread. |
| APScheduler@3.11.2 | Python 3.8+ (already validated in v1) | Runtime `add_job` / `remove_all_jobs` / `get_jobs` / `reschedule_job` work on a running `BackgroundScheduler` with the default `MemoryJobStore`. **Stay on 3.x — do NOT adopt 4.0.0aX** for this. |
| signal (stdlib) | main thread only | SIGHUP handler must run in the main thread and only set a flag; do the reload elsewhere. Coexists with the existing v1 SIGTERM clean-shutdown handler. |

## Sources

- https://pypi.org/pypi/discord.py/json — version 2.7.1, `requires_python >=3.8` (fetched 2026-06-15). HIGH
- https://pypi.org/pypi/watchfiles/json — version 1.2.0, `requires_python >=3.10` (fetched 2026-06-15). HIGH
- https://pypi.org/pypi/watchdog/json — version 6.0.0, `requires_python >=3.9` (fetched 2026-06-15). HIGH
- https://pypi.org/pypi/interactions.py/json — version 5.16.0, `requires_python >=3.10` (fetched 2026-06-15). HIGH
- https://pypi.org/pypi/hikari/json — version 2.5.0, `requires_python <3.15,>=3.10` (fetched 2026-06-15). HIGH
- https://pypi.org/pypi/APScheduler/json — stable 3.11.2; 4.0.0a6 is the latest alpha (pre-release, not for production) (fetched 2026-06-15). HIGH
- https://apscheduler.readthedocs.io/en/3.x/userguide.html — "you can add a job any time the scheduler is running"; `remove_all_jobs`, `reschedule_job` on a running scheduler. HIGH
- https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/base.html — `add_job` / `remove_job` / `get_jobs` / `reschedule_job` API on `BaseScheduler`. HIGH
- https://github.com/discord/discord-api-docs/discussions/5412 + https://www.pythondiscord.com/pages/tags/message-content-intent/ — Message Content is a privileged intent; self-enable in Developer Portal, no approval needed for small/private bots; prefix commands need it, slash commands do not. HIGH
- https://discordpy.readthedocs.io/en/stable/ — discord.py `commands.Bot`, `Intents`, gateway lifecycle. HIGH
- https://watchfiles.helpmanual.io/ — Rust-notify backend, async/sync `watch()`, built-in debounce. MEDIUM (official docs, version cross-checked against PyPI)
- WebSearch (multiple, 2026-06-15) — threading pattern for running discord.py in a background thread with its own event loop (`new_event_loop` / `run_until_complete`, `run_coroutine_threadsafe`). MEDIUM (community consensus, corroborated across sources)

---
*Stack research for: WeatherBot v1.1 inbound Discord bot + config hot-reload*
*Researched: 2026-06-15*
