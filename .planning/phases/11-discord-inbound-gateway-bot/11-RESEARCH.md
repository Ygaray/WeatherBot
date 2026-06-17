# Phase 11: Discord Inbound Gateway Bot - Research

**Researched:** 2026-06-16
**Domain:** Inbound discord.py gateway bot bolted onto a shipped thread-based `BackgroundScheduler` daemon (asyncio-loop-in-a-thread lifecycle, failure isolation, TTL quota cache)
**Confidence:** HIGH (discord.py 2.7.1 version + threading/signal-handler lifecycle + intent facts verified against PyPI JSON and official docs/issues; every code seam verified against the live tree by line number)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01: Prefix command `!weather <location>`** (chosen over bare `weather …` and slash `/weather`). The `!` makes the trigger unambiguous and immune to briefing text / webhook feedback.
- **D-02: `message_content` privileged intent is REQUIRED.** Enable in code (`intents.message_content = True`) AND in the Discord Developer Portal (out-of-band deploy step). Assert at startup the intent is set so a half-configured deploy fails loud rather than silently receiving empty `message.content`.
- **D-03: Reuse `parse_weather_command`.** Strip the `!weather` prefix, then feed the remainder to the existing parser. Bare `!weather` → DEFAULT; `!weather <loc>` → LOCATED; garbage → NOT_A_COMMAND (no reply). Unknown location → reply with `UnknownLocationError.valid_names`.
  - **Spec-tension note (verifier):** CMD-02/SC#1 literally say "typing `weather home`". `!weather home` satisfies the intent with a `!` prefix — an operator-confirmed deviation, NOT a missed requirement. Do not flag the `!`.
- **D-04: `if message.author.bot: return` as the FIRST guard** — covers the bot's own replies AND the outbound briefing webhook (webhook author has `author.bot == True`). NOT `== bot.user`. MANDATORY test: feed a simulated webhook-authored message and assert no command fires.
- **D-05: Operator-only allowlist.** Respond only to the configured operator's Discord user ID; messages from any other member are SILENTLY ignored (no reply, no OpenWeather call). No "not authorized" reply.
- **D-06: Operator user ID lives in `config.toml`** (non-secret identity), e.g. a `[bot]` section — reloadable via the Phase 9/10 reload engine. Only the bot **token** is a secret in `.env`.
- **D-07: Reply as a Discord embed built from `LookupResult.forecast`** — mirror `DiscordWebhookChannel.send_briefing`'s embed construction; visually identical to the morning briefing.
- **D-08: Typing indicator during the fetch** (`async with channel.typing():`) while the blocking lookup runs off-loop, then post the embed.
- **D-09: Bot runs on its OWN dedicated thread + asyncio loop**, separate from `BackgroundScheduler`, started alongside the file-watch observer in `run_daemon` and joined/stopped in the same `finally` teardown. `BackgroundScheduler` unchanged (do NOT migrate to AsyncIOScheduler).
- **D-10: ALL blocking work via `run_in_executor`.** `lookup_weather` and SQLite/cache I/O are sync; wrap every sync call with `await loop.run_in_executor(None, …)`. Cross-thread signalling uses `run_coroutine_threadsafe` / `call_soon_threadsafe` — never touch loop objects from the wrong thread.
- **D-11: Bot failure ≠ briefing failure.** Whole handler wrapped in try/except that logs and replies with an error but NEVER propagates out of the coroutine. discord.py auto-reconnects with backoff; persistent failure logs CRITICAL and the bot thread stops, but the scheduler thread + briefing path keep running. A dead bot thread does NOT flip the systemd READY gate / `gate_until_healthy`. MANDATORY test: revoke the token, confirm the next scheduled briefing still fires.
- **D-12: Shared per-location TTL cache, ~10 minute TTL.** Repeated `!weather <loc>` within TTL serves from the cached fetch. Keyed per configured location, bounded to configured locations, designed so the scheduled path could also read it.
- **D-13: Post BOTH success and rejection reload outcomes as a short status embed**, visually distinct from briefing embeds. Success = the `+added -removed ~changed =unchanged` job-diff from `_reconcile_jobs`; rejection = the validation reason. Hook into the EXISTING `_do_reload` channel handle — capture the structured tuple, not the log line. Both file-watch and explicit-trigger reloads post identically.
- **D-14: `DISCORD_BOT_TOKEN` is a NEW required secret in git-ignored `.env`**, loaded via pydantic-settings `Settings` alongside `openweather_api_key` / `discord_webhook_url`, fail-loud on missing. NEVER in `config.toml`. Add to any pre-commit secret scan. The outbound webhook URL stays the briefing path — do NOT reuse it for inbound replies.

### Claude's Discretion (researched & recommended below)

1. Exact bot-thread lifecycle wiring: `client.start()`/`close()` on the dedicated loop, clean SIGTERM shutdown reusing v1's path, how the loop is created/torn down. — **See Architecture Pattern 1.**
2. Cache implementation: dict+timestamp vs a small TTL lib; exact invalidation on reload; whether the scheduled path wires in now or just leaves the seam. — **See Architecture Pattern 4 + Don't Hand-Roll.**
3. discord.py version + `commands.Bot` (prefix framework) vs bare `Client` + manual `on_message`. — **See Standard Stack + Architecture Pattern 2.**
4. Startup-intent assertion mechanism (D-02) and the "bot is typing" + embed-edit UX detail. — **See Architecture Pattern 2 + Code Examples.**
5. Operator user ID as a single int or a list under `[bot]`. — **See Architecture Pattern 5 (recommend a single `operator_id: int`).**

### Deferred Ideas (OUT OF SCOPE)

- Arbitrary/geocoded `weather <any city>` lookups — v2.0 (CMD-V2-02); v1.1 is configured-locations-only.
- Telegram / SMS inbound channels — v2.0 (CHAN-V2-01/02).
- Per-user cooldown / multi-user anti-spam — explicit non-goal; the TTL cache (D-12) + operator allowlist (D-05) are the guards.
- Slash commands `/weather` — considered (no privileged intent) but the operator chose the prefix form (D-01).
- Wiring the scheduled briefing path to actually read the shared cache — the cache is *designed* to be shareable (D-12), but whether the scheduler reads it now vs just leaving the seam is left to the planner.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CMD-02 | Issue a `weather [location]` command in the Discord channel, receive the briefing as an in-channel reply | `on_message` → strip `!weather` → `parse_weather_command` → `run_in_executor(lookup_weather, holder.current())` → mirror `send_briefing` embed (Pattern 2/3). Unknown location → reply `UnknownLocationError.valid_names`. |
| CMD-06 | Repeated same-location requests within a short TTL reuse a cached fetch | Shared per-location `TTLCache(ttl=600)` guarded by a `threading.Lock`, wrapping the `lookup_weather` fetch (Pattern 4 / Don't Hand-Roll). |
| CMD-07 | Bot responds only to explicit commands, never to its own replies or the outbound webhook | `if message.author.bot: return` first guard (D-04) + operator allowlist (D-05) + `!`-prefix unambiguity (D-01). Tested with a simulated webhook-authored message (Pattern 2, Validation Architecture). |
| CMD-08 | A bot/gateway failure never prevents a scheduled briefing from firing | Bot on its own thread/loop via `client.start()`; handler wrapped in non-propagating try/except; `LoginFailure`/disconnect logged CRITICAL, bot thread dies alone; READY gate untouched (Pattern 1/3, Pitfall 4). Tested by revoking the token. |
| CFG-07 | Each reload outcome posted to Discord (success summary / rejection reason) | Capture the `(added, removed, changed, unchanged)` tuple inside `_do_reload`'s success path and the rejection reason inside its PHASE-1 except block; post a status embed via the existing `channel` handle (Pattern 6, D-13). |
</phase_requirements>

## Summary

Phase 11 adds an inbound discord.py gateway bot to the shipped v1 daemon. The dominant constraint is not regressing v1's "the morning briefing always goes out, exactly once" guarantee. Every hard part is an *integration* concern at the seam between a fragile, long-lived asyncio gateway connection and a proven, sync, thread-based `BackgroundScheduler` — not new weather logic. The bot reuses `lookup_weather`, `parse_weather_command`, the `send_briefing` embed shape, `ConfigHolder.current()`, and the `_do_reload`/`_reconcile_jobs` seam verbatim.

The single highest-blast-radius mechanic — confirmed against discord.py issues #1529/#1598/#1962 and the official API docs — is that `Client.run()` installs OS signal handlers via `loop.add_signal_handler()`, which raises `ValueError: set_wakeup_fd only works in main thread` when called off the main thread. **Therefore the bot MUST run on its own thread via `asyncio.run(client.start(token))` (NOT `client.run()`),** and the daemon's existing main-thread `signal.signal(SIGTERM/SIGHUP)` handlers stay exactly where they are. The bot thread is shut down cross-thread from the daemon's `finally` via `run_coroutine_threadsafe(client.close(), bot_loop)`. The file-watch observer thread in `run_daemon` (lines 1080–1118 start, 1186–1197 teardown) is the exact structural template to copy: a single long-lived daemon thread, started after `holder`/`channel` exist, joined in the same `finally`.

**Primary recommendation:** Add `discord.py>=2.7.1` and `cachetools>=6` (TTL cache). Use a **bare `discord.Client` with a manual `on_message`** (not `commands.Bot`) — the `author.bot` + operator-allowlist + `parse_weather_command`-reuse guards compose more cleanly with explicit `on_message` than with `commands.Bot`'s prefix/cog machinery, and the bot only has one command. Run it on a dedicated thread via `asyncio.run(client.start(token))`, wrap the whole handler in a non-propagating try/except, push every sync call through `run_in_executor`, and never let the bot thread touch the systemd READY gate (which fires exactly once in `run_daemon` before `scheduler.start()` via `emit_online`/`SystemdNotifier`).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Receive `!weather` command | Bot thread / asyncio loop (`on_message`) | — | Only the gateway connection sees inbound messages |
| Parse command text | Pure core (`parse_weather_command`) | — | Surface-agnostic, I/O-free; already shared with the CLI |
| Resolve location + fetch + render | Sync core (`lookup_weather`) run via `run_in_executor` | TTL cache | Read-only core stays sync; loop must not block (Pitfall 1) |
| Quota cache | Shared `cachetools.TTLCache` + `threading.Lock` | — | Crosses bot-executor threads AND (future) scheduler threads — must be thread-safe |
| Build + post inbound reply | Bot loop (embed mirror of `send_briefing`) | `DiscordWebhookChannel` (shape reference only) | Inbound replies go over the gateway, NOT the webhook (D-14) |
| Post reload outcome | `_do_reload` on the main poll-loop thread | `channel.send` (existing handle) | Reload already runs on the main thread with a `channel` in scope (CFG-07) |
| Lifecycle (start/stop) | `run_daemon` main thread | Bot thread | Daemon owns process liveness; bot thread is a managed child (mirror file-watch observer) |
| Secrets (token) | `Settings` / `.env` | — | Restart boundary; never in `config.toml` or the holder (Pitfall 12) |
| systemd READY gate | `run_daemon` main thread (`emit_online`) ONLY | — | Bot health must NEVER flip READY (CMD-08 / Pitfall 4) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | `>=2.7.1,<3` | Inbound gateway bot (`Client`, intents, `on_message`, `channel.typing()`, embeds) | The canonical maintained Python Discord gateway library (Rapptz/discord.py, ~14k stars, 8+ yrs). 2.7.1 verified on PyPI, released 2026-03-03. STATE.md already locked `discord.py 2.7.x` as the one new runtime dep for this phase. `[CITED: pypi.org/pypi/discord.py/json]` |
| cachetools | `>=6,<8` | `TTLCache` for the per-location quota guard (CMD-06) | The standard small TTL-cache library; `TTLCache(maxsize, ttl)` is purpose-built ("cache weather data for no longer than ten minutes" is literally its docs example). NOT thread-safe by itself — must wrap mutating access in a `threading.Lock` (see Don't Hand-Roll). `[CITED: pypi.org/pypi/cachetools/json]` — latest 7.1.4 |

> **`<3` / `<8` upper bounds** follow the house style (`apscheduler>=3.11.2,<4` in pyproject.toml). Pin a major-version ceiling on discord.py especially — it has a history of breaking minors.

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio (stdlib) | built-in | Owns the bot loop; `run_in_executor`, `run_coroutine_threadsafe`, `asyncio.run(client.start())` | Always — the loop-in-a-thread machinery |
| threading (stdlib) | built-in | The dedicated bot thread + the cache `Lock` | Mirror the existing `weatherbot-filewatch` thread |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| bare `discord.Client` + manual `on_message` | `discord.ext.commands.Bot` (prefix framework) | `commands.Bot` gives `!`-prefix parsing + `@bot.command` for free, but for a ONE-command bot it adds a cog/command-tree layer and its own `bot.process_commands` flow that you'd then have to reconcile with the `author.bot`+operator guards and the `parse_weather_command` reuse (D-03). Bare `Client` keeps the guard order explicit and obvious (`author.bot` → operator-id → `parse_weather_command`). **Recommend bare `Client`.** D-01/D-03 already lean this way. |
| cachetools `TTLCache` | plain `dict` + `time.monotonic()` timestamps | A hand-rolled dict works for ~3 keys but you re-implement expiry sweeping and bounding. Given the library is one tiny dependency and `TTLCache` is the documented weather-cache example, prefer it. (Either way you still need an external `Lock` — cachetools is not thread-safe.) |
| `client.start()` on a thread | `AsyncIOScheduler` migration | Explicitly OUT OF SCOPE (REQUIREMENTS.md non-goals): forces an async rewrite of the verified v1 scheduler spine for zero user benefit. |

**Installation:**
```bash
uv add 'discord.py>=2.7.1'
uv add 'cachetools>=6'
```
> Use `uv add` (writes `pyproject.toml` + `uv.lock`), matching the Phase 10 `watchfiles` precedent (STATE.md: "watchfiles>=1.2.0 added as runtime dep (uv add, not pip/dev)"). Place alphabetically in the `dependencies` array. discord.py installs as the import name `discord`; the PyPI/distribution name is `discord.py`.

**Version verification (run during planning to confirm currency):**
```bash
uv run python -c "import discord; print(discord.__version__)"   # expect 2.7.x
pip index versions discord.py
pip index versions cachetools
```

## Package Legitimacy Audit

> slopcheck could not be installed in this research session (`pip install slopcheck` unavailable in the sandbox). Both packages are nonetheless long-established, high-trust dependencies verified directly against the official PyPI JSON API. Per the graceful-degradation rule, the planner SHOULD still gate the two `uv add` steps behind a brief human-verify acknowledgement, but the supply-chain risk here is low.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| discord.py | PyPI | 8+ yrs (2.7.1 rel. 2026-03-03) | tens of millions/mo | github.com/Rapptz/discord.py (~14k★) | unavailable | Approved (`[CITED: pypi.org]`) |
| cachetools | PyPI | 10+ yrs (latest 7.1.4) | tens of millions/mo | github.com/tkem/cachetools | unavailable | Approved (`[CITED: pypi.org]`) |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

> Cross-ecosystem note: the PyPI distribution name is `discord.py`; the import name is `discord`. There is a separate, **abandoned** PyPI package literally named `discord` — do NOT depend on that one. `uv add 'discord.py>=2.7.1'` resolves to the correct Rapptz package.

## Architecture Patterns

### System Architecture Diagram

```
                          run_daemon (MAIN THREAD)
                          ├─ signal.signal(SIGTERM/SIGHUP)  ← stays on main thread
                          ├─ holder = ConfigHolder(config)
                          ├─ channel = build_channel(...)
                          ├─ scheduler.start()  (BackgroundScheduler — UNCHANGED)
                          ├─ emit_online() → SystemdNotifier READY=1  ← bot NEVER touches this
                          ├─ start filewatch thread   (existing model)
                          ├─ start BOT THREAD ─────────────────┐
                          └─ poll loop: stop.wait(1.0)          │
                               └─ reload_requested → _do_reload(channel=…)
                                       └─ CFG-07: post reload outcome embed
                                                                │
   ┌────────────────────────────────────────────────────────── ▼ ──────────────┐
   │ BOT THREAD: asyncio.run(client.start(DISCORD_BOT_TOKEN))                    │
   │   on_message(msg):                                                          │
   │     if msg.author.bot: return            ← D-04 (self AND webhook)          │
   │     if msg.author.id != operator_id: return  ← D-05 (silent)               │
   │     cmd = parse_weather_command(msg.content.removeprefix("!"))  ← D-03      │
   │     if NOT_A_COMMAND: return                                                │
   │     async with msg.channel.typing():     ← D-08                            │
   │         result = await loop.run_in_executor(                               │
   │                       None, cached_lookup, cmd.location, holder.current()) │
   │     await msg.channel.send(embed=build_embed(result.forecast))  ← D-07     │
   │   (whole body in try/except → log + error reply, NEVER propagate)  ← D-11  │
   └────────────────────────────────────────────────────────────────────────────┘
                                   │
   Discord gateway ──(inbound)─────┘        OpenWeather ◄── cached_lookup ──► TTLCache+Lock
   Discord webhook ──(outbound briefings, UNCHANGED — fire-and-forget POST)
```

Data flow for the primary use case: operator types `!weather home` → gateway delivers to `on_message` on the bot thread → guards pass → parser yields `LOCATED("home")` → typing indicator on → `lookup_weather` runs on an executor thread (cache-checked) → embed built from `forecast` → posted as an in-channel reply.

### Recommended Project Structure
```
weatherbot/
├── interactive/
│   ├── command.py        # parse_weather_command (EXISTS — reuse)
│   ├── lookup.py         # lookup_weather, LookupResult (EXISTS — reuse, sync)
│   ├── bot.py            # NEW: build_bot(client/intents), on_message handler, build_inbound_embed
│   └── cache.py          # NEW: ForecastCache (TTLCache + Lock) wrapping lookup_weather
├── scheduler/
│   └── daemon.py         # EDIT: start/stop bot thread in run_daemon; CFG-07 posting in _do_reload
├── config/
│   ├── models.py         # EDIT: add BotConfig ([bot] section, operator_id) → Config.bot
│   └── settings.py       # EDIT: add discord_bot_token: str
```

### Pattern 1: Bot loop on its own thread — start with `client.start()`, stop cross-thread with `client.close()`  [CONFIDENCE: HIGH]
**What:** The bot runs on a dedicated daemon thread that owns its own asyncio event loop via `asyncio.run(client.start(token))`. The daemon's main thread keeps its existing signal handlers and shuts the bot down from the `finally` block by scheduling `client.close()` onto the bot loop cross-thread.
**When to use:** Always — this is the load-bearing CMD-08 mechanic.
**Why `start()` not `run()`:** `Client.run()` calls `loop.add_signal_handler(...)` for SIGINT/SIGTERM, which raises `ValueError: set_wakeup_fd only works in main thread` on a worker thread (discord.py issues #1529, #1598, #1962). `Client.start()` is "a shorthand coroutine for `login()` + `connect()`" with no signal-handler setup `[CITED: discordpy.readthedocs.io/en/stable/api.html]`, so it composes on a non-main thread. The daemon already owns SIGTERM/SIGHUP on the main thread (daemon.py:1044, 1057) — leave those alone.

```python
# weatherbot/interactive/bot.py  (lifecycle skeleton — verify against live discord.py 2.7.1)
import asyncio, threading
import discord
import structlog

_log = structlog.get_logger(__name__)

class BotThread:
    """Owns the discord.py client on its own thread + loop (D-09).

    A failure here logs CRITICAL and lets the thread die alone — it NEVER
    propagates to the scheduler thread or touches the systemd READY gate (D-11).
    """
    def __init__(self, token, *, holder, operator_id, cache):
        self._token = token
        self._client = build_client(holder=holder, operator_id=operator_id, cache=cache)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="weatherbot-discord", daemon=True
        )

    def start(self) -> None:
        self._thread.start()
        self._loop_ready.wait(timeout=5.0)  # so close() has a loop to target

    def _run(self) -> None:
        try:
            # asyncio.run creates + owns the loop for this thread.
            asyncio.run(self._amain())
        except discord.LoginFailure:
            # Revoked / invalid token (D-11 / Pitfall 4). CRITICAL + die alone.
            _log.critical("discord bot: invalid token; bot disabled, briefings unaffected")
        except Exception:  # noqa: BLE001 — bot thread is non-critical; never crash the process
            _log.critical("discord bot thread died; briefings unaffected", exc_info=True)

    async def _amain(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._loop_ready.set()
        async with self._client:                  # ensures clean close on cancel
            await self._client.start(self._token)  # NOT client.run()

    def stop(self, timeout: float = 5.0) -> None:
        # Cross-thread shutdown from the daemon's finally (D-10): schedule close()
        # onto the bot loop; never call loop methods directly from the main thread.
        if self._loop is not None and not self._loop.is_closed():
            fut = asyncio.run_coroutine_threadsafe(self._client.close(), self._loop)
            try:
                fut.result(timeout=timeout)
            except Exception:  # noqa: BLE001 — best-effort teardown
                _log.warning("discord bot close timed out/raised during shutdown")
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            _log.warning("discord bot thread did not stop within join timeout")
```

**Daemon wiring (mirror the file-watch observer):** construct the `BotThread` AFTER `holder`/`channel` exist and AFTER `scheduler.start()`+`emit_online()` (so a bot failure can never delay or gate the online signal), guard on `settings is not None` (token comes from `Settings`) and on the operator id being configured; call `.start()` there; call `.stop()` in the same `finally` block that joins `watch_thread` and unlinks the PID file (daemon.py:1186–1197). Use a try/except around `.start()` so a startup bot failure logs and the daemon proceeds to serve briefings.

### Pattern 2: Bare `Client` + manual `on_message` with the guard ladder  [CONFIDENCE: HIGH]
**What:** Construct `discord.Client(intents=…)` and register `@client.event async def on_message(message)`. The handler runs guards in a fixed order before doing any work.
**When to use:** The one command this bot has.

```python
def build_client(*, holder, operator_id, cache):
    intents = discord.Intents.none()
    intents.guilds = True            # needed to resolve channels
    intents.guild_messages = True    # receive messages in the server
    intents.message_content = True   # PRIVILEGED (D-02) — also toggle in the portal
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        # D-02 startup intent assertion: fail loud if message_content is off.
        if not client.intents.message_content:
            _log.critical("message_content intent NOT enabled; commands will never match")

    @client.event
    async def on_message(message: discord.Message):
        try:
            if message.author.bot:                 # D-04: self AND webhook
                return
            if message.author.id != operator_id:   # D-05: silent ignore
                return
            content = message.content
            if not content.startswith("!"):
                return
            cmd = parse_weather_command(content[1:])   # strip "!", reuse parser (D-03)
            if cmd.kind is CommandKind.NOT_A_COMMAND:
                return
            name = cmd.location  # None for DEFAULT → lookup_weather resolves default
            loop = asyncio.get_running_loop()
            async with message.channel.typing():       # D-08
                try:
                    result = await loop.run_in_executor(   # D-10: sync work off-loop
                        None, cache.lookup, name, holder.current()
                    )
                except UnknownLocationError as exc:
                    await message.channel.send(str(exc))   # CMD-02 error path / valid_names
                    return
            await message.channel.send(embed=build_inbound_embed(result.forecast))  # D-07
        except Exception:  # noqa: BLE001 — D-11: log + error reply, NEVER propagate
            _log.exception("discord on_message handler error")
            try:
                await message.channel.send("Sorry — something went wrong fetching that.")
            except Exception:  # noqa: BLE001
                pass
    return client
```

**Anti-pattern avoided:** matching `"weather" in message.content` (free-text substring) — that re-triggers on the briefing text (Pitfall 2). The `!` prefix + `author.bot` guard + `parse_weather_command`'s own word-boundary guard are three independent backstops.

### Pattern 3: Mirror `send_briefing`'s embed (don't import the webhook channel)  [CONFIDENCE: HIGH]
**What:** Build a `discord.Embed` from `LookupResult.forecast` with the SAME fields the outbound webhook embed uses, but using discord.py's `discord.Embed` (the gateway library's embed type), NOT `discord_webhook.DiscordEmbed` (the webhook library's type — different class, different transport).
**Why:** D-07 wants visual parity. The existing `DiscordWebhookChannel.send_briefing` (discord.py NOT involved there) builds: title `f"Weather — {forecast.location}"`, color `0x03b2f8`, fields `Now`=`temp_display`, `High / Low`=`f"{high_display} / {low_display}"`, `Rain`=`f"{rain_chance}%"`, plus a timestamp. Reproduce those exact fields with `discord.Embed` for the inbound reply.

```python
def build_inbound_embed(forecast) -> discord.Embed:
    e = discord.Embed(title=f"Weather — {forecast.location}", color=0x03b2f8)
    e.add_field(name="Now", value=forecast.temp_display)
    e.add_field(name="High / Low",
                value=f"{forecast.high_display} / {forecast.low_display}")
    e.add_field(name="Rain", value=f"{forecast.rain_chance}%")
    e.timestamp = discord.utils.utcnow()
    return e
```

### Pattern 4: Thread-safe shared TTL cache wrapping the sync lookup  [CONFIDENCE: HIGH]
**What:** A small `ForecastCache` that holds a `cachetools.TTLCache` behind a `threading.Lock`, keyed by the canonical location identity, wrapping `lookup_weather`.
**Why thread-safe matters:** the cache is touched from bot executor threads (`run_in_executor` worker pool) AND is *designed* (D-12) so the scheduler threads could read it too. `cachetools.TTLCache` is NOT thread-safe `[CITED: cachetools docs]` — concurrent mutation must be serialized.
**Key choice:** key on `Location.id` (the stable sent-log identity — defaults to the raw name, see models.py `_default_id_from_name`), resolved via `resolve_location(config, name)`, so `!weather home` / `!weather Home` / bare-default all collapse to one cache entry and a rename doesn't silently fork the cache.

```python
# weatherbot/interactive/cache.py
import threading
from cachetools import TTLCache
from weatherbot.config import resolve_location
from weatherbot.interactive.lookup import lookup_weather

class ForecastCache:
    def __init__(self, *, settings, ttl_seconds: int = 600, maxsize: int = 16):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = threading.Lock()
        self._settings = settings

    def lookup(self, name, config):  # SYNC — always called via run_in_executor
        key = resolve_location(config, name).id   # raises UnknownLocationError (good)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        result = lookup_weather(name, config=config, settings=self._settings)
        with self._lock:
            self._cache[key] = result
        return result

    def invalidate(self):  # optional reload hook (Discretion item)
        with self._lock:
            self._cache.clear()
```

> **Invalidation-on-reload (Claude's discretion):** simplest correct choice is to `invalidate()` (clear) the cache inside `_do_reload`'s success path so a location whose coords/units changed never serves a stale fetch. ~10-min staleness on a *non-reloaded* entry is acceptable (D-12). If the planner wants to defer scheduler-side cache reads, leave `ForecastCache` constructed and passed to the bot only, with `invalidate()` wired into reload — that satisfies CMD-06 without touching the briefing path.

> **Lock + executor note:** the executor worker holds the GIL during the `lookup_weather` httpx call; the `Lock` is only held around the dict get/set, never across the network call — so two concurrent `!weather A` / `!weather B` don't serialize on the network, only on the tiny dict ops. (A more aggressive single-flight that dedupes two concurrent fetches of the SAME key is possible but unnecessary at single-user volume — leave it out.)

### Pattern 5: `[bot]` config section + `discord_bot_token` secret  [CONFIDENCE: HIGH]
**What:** A new frozen `BotConfig` model (operator id) on `config.toml`, and a new `discord_bot_token` field on `Settings`.

```python
# config/models.py — follows the frozen+extra=forbid house style
class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operator_id: int          # Discord user ID — non-secret identity (D-06)

class Config(BaseModel):
    ...
    bot: BotConfig | None = None   # optional: a config with no [bot] table = no inbound bot
```
```python
# config/settings.py
class Settings(BaseSettings):
    ...
    openweather_api_key: str
    discord_webhook_url: str
    discord_bot_token: str         # NEW required secret (D-14), fail-loud if missing
```

**Recommend a single `operator_id: int`,** not a list — REQUIREMENTS.md is explicit this is a single-user tool and a list invites the multi-user scope creep that's a non-goal. (`bot: BotConfig | None` keeps the bot opt-in: a `config.toml` with no `[bot]` table loads unchanged and the daemon simply doesn't start the bot thread — the v1.0 fail-closed-on-extra-key posture is preserved because `BotConfig` is `extra="forbid"`.)

> **Fail-loud caveat (D-14):** `discord_bot_token` is now REQUIRED on `Settings`. Adding it makes `load_settings()` raise `ValidationError` for any existing deployment whose `.env` lacks the token — that is the intended fail-loud behavior, but the planner MUST update `.env.example` / deploy docs and the README in the same phase so the upgrade isn't a surprise 500 at startup. If the operator wants the bot strictly optional even at the secrets layer, make it `discord_bot_token: str | None = None` and skip the bot when it's absent — flag this as an Open Question for the operator.

### Pattern 6: CFG-07 — post reload outcome from inside `_do_reload`  [CONFIDENCE: HIGH]
**What:** `_do_reload` already (a) re-raises with a logged `reason=str(exc)` in its PHASE-1 reject branch (daemon.py ~605) and (b) computes `(added, removed, changed, unchanged)` in its PHASE-2 success branch (~636). Add a `channel.send(...)`/status-embed post at BOTH points, using the `channel` already threaded into `_do_reload` (it's already a parameter, line ~556).
**Why "capture the tuple, not the log line" (D-13):** the structured values are right there; never parse `_stdlog.info("reload applied %s", summary)`.
**Where to post:** both file-watch and SIGHUP/CLI reloads funnel through the SAME `_do_reload` on the main poll-loop thread (daemon.py:1162), so a single post site covers all reload triggers (D-13). The post is a normal outbound Discord call on the main thread — it does NOT need the bot loop and is independent of bot health.

```python
# inside _do_reload, success branch (after the summary line):
if channel is not None:
    status = discord_status_embed_text(f"✅ config reloaded: {summary}")
    channel.send(status)        # plain text status (distinct from briefing embed, D-13)

# inside the PHASE-1 except branch (after _log.error("reload rejected", ...)):
if channel is not None:
    channel.send(f"⛔ config reload rejected: {exc}")
```

> Keep the reload post a **plain `channel.send(text)`** (or a small distinct embed) so it's visually different from the rich briefing embed (D-13). Reuse the existing `Channel.send` seam — no new transport. Guard `if channel is not None` exactly like `emit_online` does (daemon.py pattern). A `channel.send` failure here must be swallowed/logged, never allowed to abort the reload (the reload already succeeded/failed independently of whether the Discord notice posts).

### Anti-Patterns to Avoid
- **`client.run()` on the bot thread** — raises `ValueError: set_wakeup_fd only works in main thread`. Use `asyncio.run(client.start(token))`.
- **Calling `lookup_weather`/SQLite directly inside `on_message`** — blocks the loop → "Heartbeat blocked" → gateway drop (Pitfall 1). Always `run_in_executor`.
- **`if message.author == bot.user`** — misses the webhook author (Pitfall 2). Use `message.author.bot`.
- **Touching `loop` objects from the main thread** — only `run_coroutine_threadsafe`/`call_soon_threadsafe` cross the boundary (Pitfall 1).
- **Letting bot health flip the READY gate** — `emit_online`/`SystemdNotifier.notify("READY=1")` fires once in `run_daemon` before/independent of the bot; never call it from the bot (Pitfall 4).
- **Reusing the outbound webhook URL for inbound replies** — inbound replies go over the gateway via `message.channel.send`; the webhook stays the briefing path (D-14).
- **Reading the bot token into `ConfigHolder` / `config.toml`** — token is `.env`-only behind the restart boundary (Pitfall 12).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TTL expiry + bounding for the cache | A dict with manual `time.monotonic()` sweeps | `cachetools.TTLCache(maxsize, ttl)` + a `threading.Lock` | Expiry sweeping and `maxsize` eviction are exactly what TTLCache does; hand-rolling re-introduces off-by-one/leak bugs. (You still own the Lock — TTLCache isn't thread-safe.) |
| Gateway reconnect/backoff on disconnect | A reconnect loop around `connect()` | discord.py's built-in `reconnect=True` (default on `start()`/`connect()`) | discord.py auto-reconnects with exponential backoff on network/gateway failures `[CITED: discord.py API docs]`; wrapping it yourself fights the library. |
| Signal handling for the bot | `loop.add_signal_handler` on the bot thread | Daemon's existing main-thread `signal.signal` + cross-thread `client.close()` | Signal handlers only work on the main thread; the daemon already owns them. |
| Prefix-command parsing | Re-parsing `!weather <x>` ad hoc | `content[1:]` → existing `parse_weather_command` (D-03) | The parser is the shared, tested source of truth (word-boundary guard, three-state). |
| Embed construction from scratch | Manual JSON embed dicts | `discord.Embed` mirroring `send_briefing`'s fields | Library type handles serialization/limits; mirror keeps visual parity (D-07). |

**Key insight:** Almost everything hard in this phase is *coordination* (threads, loops, lifecycle, isolation), not computation. The weather/parse/render code already exists and is sync — the discipline is to never run it on the loop and never let its failures escape the bot thread.

## Common Pitfalls

(Full catalogue in `.planning/research/PITFALLS.md` — Pitfalls #1, #2, #3, #4, #10 are this phase's primary targets. Summarized with the verified fix below.)

### Pitfall 1: Sync work blocks the bot loop → "Heartbeat blocked" → gateway churn
**What goes wrong:** `lookup_weather`/SQLite called directly in the coroutine freezes the heartbeat; Discord drops the connection.
**How to avoid:** every sync call via `await loop.run_in_executor(None, fn, …)`. Bot on its own thread so it can't block the scheduler either.
**Warning signs:** `Heartbeat blocked for more than N seconds`; commands work once then hang; `RuntimeError: attached to a different loop`.

### Pitfall 2: Bot replies to its own/webhook messages (feedback loop)
**What goes wrong:** the daily briefing (posted via webhook into the SAME channel) trips the command handler; or the bot replies to its own reply.
**How to avoid:** `if message.author.bot: return` FIRST (covers webhook + self), then operator-id allowlist, then the `!` prefix + `parse_weather_command` word-boundary guard.
**Verification:** MANDATORY — feed a simulated webhook-authored message (`author.bot = True`, `webhook_id` set) and assert no command fires (SC#3).

### Pitfall 3: `message_content` intent / token misconfig — works locally, silent in prod
**What goes wrong:** intent set in code but not the Developer Portal → `message.content` arrives empty, commands silently never match. Or the token gets pasted into `config.toml`.
**How to avoid:** enable the intent in BOTH places (document the portal toggle as a deploy step); assert at `on_ready` that `client.intents.message_content` is True; store `DISCORD_BOT_TOKEN` in `.env` via `Settings`, fail-loud, add to any pre-commit secret scan.
**Warning signs:** bot online but ignores commands; `message.content == ''`; `PrivilegedIntentsRequired` on connect; token in `git diff`.

### Pitfall 4: A bot/gateway failure takes down the briefing daemon
**What goes wrong:** an unhandled `on_message` exception, an unrecoverable gateway error, or a revoked token kills the process — or leaves a half-dead process systemd still thinks is "active".
**How to avoid:** bot on its own thread; whole handler in non-propagating try/except; `LoginFailure`/fatal gateway error → log CRITICAL and let the bot thread die alone; scheduler thread + briefing path untouched; bot health NEVER touches `gate_until_healthy`/READY.
**Verification:** MANDATORY — revoke/invalidate the token and confirm the next scheduled briefing still fires and READY is unaffected (SC#4).

### Pitfall 10: Command spam burns the OpenWeather quota
**What goes wrong:** repeated `!weather home` (or a webhook loop from Pitfall 2) blows the quota / trips the rate limit so the *scheduled* briefing later fails.
**How to avoid:** per-location `TTLCache` (~10 min) wrapping the fetch; operator-only allowlist already bounds the caller set to one user; configured-locations-only bounds the key set.
**Verification:** two `!weather <same loc>` within the TTL → the second serves from cache, no second OpenWeather call (SC#2).

## Runtime State Inventory

> This phase ADDS a surface; it does not rename/migrate existing runtime state. The relevant "state" is new configuration and a new secret.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the inbound bot is read-only w.r.t. the SQLite sent-log (it never claims/records slots; explicit non-goal: on-demand fetches are NOT persisted). Verified by `lookup_weather`'s D-06 read-only contract. | none |
| Live service config | **Discord Developer Portal: the `message_content` privileged intent toggle** must be enabled out-of-band (not in git). This is a manual deploy step (D-02). | manual portal toggle + documented deploy step + `on_ready` assertion |
| OS-registered state | None — no new systemd units/timers; the existing `Type=notify Restart=always` unit is reused. The bot thread is in-process. | none (confirm `.env` reaches the unit via `EnvironmentFile=` so `DISCORD_BOT_TOKEN` is present) |
| Secrets/env vars | **NEW required secret `DISCORD_BOT_TOKEN`** in git-ignored `.env`, read by `Settings` (D-14). Existing `.env` deployments lack it → fail-loud `ValidationError` at startup until added. | add to `.env`, `.env.example`, deploy docs; add to pre-commit secret scan |
| Build artifacts | None stale. Two new runtime deps (`discord.py`, `cachetools`) require `uv sync`/`uv lock` after `uv add`. | `uv add` + commit `uv.lock` |

## Code Examples

(See Architecture Patterns 1–6 above for the verified, copy-ready skeletons: `BotThread` lifecycle, `build_client`/`on_message` guard ladder, `build_inbound_embed`, `ForecastCache`, `BotConfig`/`Settings`, and the `_do_reload` CFG-07 post sites. All are grounded in live-tree signatures.)

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `client.run()` everywhere | `asyncio.run(client.start(token))` / `async with client:` for non-main-thread or custom lifecycles | discord.py 2.x | `run()` is main-thread-only (signal handlers); `start()` composes on a worker thread — the basis of this phase's lifecycle |
| Substring command matching | Explicit prefix/slash + `author.bot` guard | long-standing best practice | Prevents the webhook/self feedback loop |
| `if author == bot.user` | `if author.bot` | — | Webhook messages are bot-authored but not `bot.user`; the briefing webhook posts into the same channel |

**Deprecated/outdated:**
- The abandoned PyPI package named `discord` (import `discord`) — NOT the maintained library. Depend on `discord.py`.
- `CLAUDE.md`'s "don't use discord.py for webhooks" guidance is about the OUTBOUND briefing (a single fire-and-forget POST via `discord-webhook`). It explicitly does NOT forbid discord.py for the INBOUND gateway bot — a gateway connection genuinely requires it. **This phase legitimately uses both libraries for different directions; that is not a CLAUDE.md violation.**

## Project Constraints (from CLAUDE.md)

| Directive | How this phase complies |
|-----------|-------------------------|
| Python 3.12+, `uv` for deps | `uv add 'discord.py>=2.7.1' cachetools` (mirrors Phase 10 `watchfiles`); `requires-python >=3.12` unchanged |
| `httpx` for HTTP | Unchanged — the bot reuses `lookup_weather`'s existing httpx client; discord.py owns the gateway/REST socket internally |
| `structlog` (no bare `print`) | All bot logging via `structlog.get_logger(__name__)` |
| `pydantic-settings` for secrets in `.env` | `DISCORD_BOT_TOKEN` added to `Settings`, fail-loud (D-14) |
| `tenacity` for retry | Not needed here — discord.py owns gateway reconnect/backoff; the existing briefing retry path is untouched |
| Channel layer stays provider-agnostic | Inbound bot is a NEW surface, not a new `Channel`; the `Channel.send(text)` seam is reused only for the CFG-07 reload-status post |
| "Don't use discord.py for webhooks" | Applies to OUTBOUND only; the inbound gateway bot legitimately uses discord.py (documented above) |
| Secrets never in `config.toml` / git | Token in `.env`; operator id (non-secret) in `config.toml` `[bot]` |
| GSD workflow enforcement | All edits go through the planned phase |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest `>=9.0.3` (+ `time-machine` for clock control) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`) |
| Quick run command | `uv run pytest tests/test_bot.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CMD-02 | `!weather home` → embed reply built from `forecast`; unknown loc → `valid_names` error | unit | `uv run pytest tests/test_bot.py -k reply -x` | ❌ Wave 0 |
| CMD-06 | second same-location call within TTL serves from cache (one fetch) | unit | `uv run pytest tests/test_cache.py -x` | ❌ Wave 0 |
| CMD-07 | webhook-authored message fires no command; non-operator silently ignored | unit | `uv run pytest tests/test_bot.py -k guard -x` | ❌ Wave 0 |
| CMD-08 | `LoginFailure` / handler exception isolated; scheduler + READY untouched | unit/integration | `uv run pytest tests/test_bot.py -k isolation -x` | ❌ Wave 0 |
| CFG-07 | success + rejection reload outcomes posted via `channel` | unit | `uv run pytest tests/test_reload.py -k cfg07 -x` | ⚠️ extend existing `tests/test_reload.py` |
| (Pitfall 1) | no sync work runs on the loop (`run_in_executor` used) | unit | `uv run pytest tests/test_bot.py -k executor -x` | ❌ Wave 0 |

### How to test a discord.py handler WITHOUT a live gateway
- **Don't connect.** Call `on_message(fake_message)` directly. Build `fake_message` with `unittest.mock.MagicMock`/`AsyncMock`: set `author.bot`, `author.id`, `content`, and make `channel.send`/`channel.typing()` awaitable mocks (`channel.send = AsyncMock()`; `channel.typing` returns an async-context-manager mock).
- **CMD-07 (Pitfall 2):** `msg.author.bot = True` (webhook case) → assert `channel.send` was NOT called and the lookup mock was NOT called. Separately `author.bot=False, author.id != operator_id` → assert silent (no send, no lookup).
- **Pitfall 1 (off-loop):** patch `loop.run_in_executor` (or assert the cache/lookup is invoked through it) and assert `lookup_weather` is never called directly in the coroutine; assert the cache function is the executor target. A `time.sleep`-injected lookup must not block (run the handler under `asyncio.run` with a watchdog asserting the coroutine yields).
- **CMD-08 (isolation):** make the lookup raise → assert the error reply is sent and the exception does NOT propagate out of `on_message`. For the token case, unit-test that `BotThread._run` catches `discord.LoginFailure`, logs CRITICAL, and the thread exits without raising — and that a separate (real or faked) scheduler `fire_slot` still runs. The end-to-end "revoke token → next briefing still fires" is an integration test: start the daemon with a deliberately-invalid token and a near-term scheduled slot (time-machine) and assert the briefing send fires and `SystemdNotifier.notify` READY was emitted exactly once (not gated by the bot).
- **CMD-06 (cache):** call `cache.lookup("home", cfg)` twice with `lookup_weather` patched to a counting spy; assert the spy ran once. Advance time past TTL (cachetools honors wall-clock via its `timer`; inject a controllable timer or use `time-machine`) and assert a second fetch.
- **CFG-07:** call `_do_reload(channel=spy_channel, config_path=bad_toml)` → assert `spy_channel.send` got the rejection text; call with a good config → assert it got the `+a -r ~c =u` summary.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_bot.py tests/test_cache.py -x`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_bot.py` — guard ladder (CMD-07), reply/embed (CMD-02), executor/off-loop (Pitfall 1), handler+token isolation (CMD-08)
- [ ] `tests/test_cache.py` — TTL hit/miss + expiry (CMD-06), thread-safety smoke
- [ ] Extend `tests/test_reload.py` — CFG-07 success + rejection posting
- [ ] Shared fixtures in `tests/conftest.py` — a `fake_discord_message` factory (`AsyncMock` channel, configurable `author`)
- [ ] Framework install: none new (pytest + time-machine already present); add `discord.py`/`cachetools` so tests can import the bot module (`uv add`)

## Security Domain

### Applicable ASVS Categories (Level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Bot identity = `DISCORD_BOT_TOKEN` (bearer secret) in `.env` only, fail-loud; never logged/committed (mirror the webhook-URL hygiene already in `discord.py` channel: its logger raised to WARNING to prevent URL leaks) |
| V3 Session Management | no | Stateless command handler; no sessions |
| V4 Access Control | yes | **Operator-only allowlist (D-05):** respond only to the configured `operator_id`; all other users silently ignored — prevents any server member driving OpenWeather quota |
| V5 Input Validation | yes | `parse_weather_command` is parse-don't-validate, uses only `strip`/`casefold`/slicing, never `format`/`eval`/shell (T-06-01); location validated against configured names → `UnknownLocationError` |
| V6 Cryptography | no | No crypto authored; TLS owned by discord.py/httpx |
| V7 Error Handling/Logging | yes | Outcome-only structured logging (no token/URL in logs); handler errors logged + a generic reply, never a stack trace to the user |

### Known Threat Patterns for a single-server inbound Discord bot

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Bot token leaked in git (`config.toml`) | Information disclosure / Elevation | Token in `.env` only; pre-commit secret scan; `Settings` fail-loud (D-14) |
| Any channel member drives the quota | Denial of service | Operator-id allowlist (D-05) + TTL cache (CMD-06); configured-locations-only bounds the surface |
| Webhook/self feedback loop spends quota | DoS | `author.bot` guard (D-04) + `!` prefix + word-boundary parser (Pitfall 2) |
| Bot crash takes down briefings | Denial of service (of the core value) | Thread isolation + non-propagating handler + READY gate untouched (CMD-08 / Pitfall 4) |
| Over-broad `message_content` intent reads all messages | Information disclosure (privacy) | Minimal intents (`guilds`, `guild_messages`, `message_content` only); single private server; operator-only action |
| Injection via location string | Tampering | Parser never interpolates the string through `format`/`eval`/shell; only configured names resolve |

**Block-on-high:** no HIGH-severity unmitigated threat identified; all six map to a locked decision or an existing v1 control.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | slopcheck unavailable, so the two packages are documented from PyPI JSON rather than slop-scanned | Package Legitimacy Audit | LOW — both are 8-10yr, tens-of-millions-of-downloads packages with known source repos; planner should still add a brief human-verify ack before `uv add` |
| A2 | `cachetools.TTLCache` is NOT thread-safe and needs an external `Lock` | Pattern 4 / Don't Hand-Roll | LOW — well-documented; the Lock is cheap and correct regardless |
| A3 | A single `operator_id: int` (not a list) is the right `[bot]` shape | Pattern 5 | LOW — operator confirmed single-user; trivially widened later if needed |
| A4 | Making `discord_bot_token` strictly REQUIRED (vs `str \| None`) is acceptable | Pattern 5 caveat | MEDIUM — forces existing `.env` deployments to add the token before next start; flagged as Open Question Q1 |
| A5 | Clearing the whole cache on every successful reload is the right invalidation policy | Pattern 4 | LOW — over-conservative (a few extra fetches after a reload) but never stale; cheap |
| A6 | `discord.Embed.color = 0x03b2f8` + the four fields reproduce `send_briefing`'s look closely enough for D-07 "visually identical" | Pattern 3 | LOW — fields/title/color mirror the live `send_briefing`; exact byte-parity across two different embed libraries is not achievable nor required |

## Open Questions

1. **Is the bot strictly required at startup, or opt-in?** (Q1)
   - What we know: D-14 says `DISCORD_BOT_TOKEN` is a NEW *required* secret, fail-loud. `Config.bot` can be optional (`[bot]`-less config = no bot).
   - What's unclear: should a deployment that doesn't want the inbound bot still be forced to set a token? Two consistent options: (a) token always required (strict D-14) — bot starts whenever `[bot]` is configured; (b) `discord_bot_token: str | None` — bot is fully optional and skipped when token OR `[bot]` is absent.
   - Recommendation: default to (a) per D-14's literal "required", but surface this to the operator in planning; it's a one-line change either way.

2. **Does the scheduled `fire_slot` path read the shared cache now, or just leave the seam?** (Q2)
   - What we know: D-12 designs the cache to be shareable; the Deferred list says full scheduler-cache integration "can be a later tidy-up."
   - What's unclear: whether to wire `fire_slot` → `ForecastCache.lookup` in this phase.
   - Recommendation: leave the seam (construct `ForecastCache` so both could use it, wire ONLY the bot now). Wiring the scheduler in risks the briefing path serving a stale-but-cached forecast at send time for marginal benefit — defer unless the operator wants it.

3. **Exact placement of `ForecastCache` construction in `run_daemon`.** (Q3)
   - What we know: it must outlive individual fires and be shared with the bot.
   - Recommendation: construct it next to `holder`/`channel` (daemon.py ~1009) and pass it into `BotThread`; if Q2 says "wire scheduler too," also thread it into `_register_jobs`. Invalidate on successful reload inside `_do_reload`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| discord.py | inbound gateway bot | ✗ (not yet installed) | target 2.7.1 | none — install via `uv add` |
| cachetools | CMD-06 TTL cache | ✗ (not yet installed) | target ≥6 | plain dict+lock (worse; avoid) |
| Python 3.12+ | runtime | ✓ | per `requires-python` | — |
| pytest + time-machine | tests | ✓ | 9.0.3 / 2.16 | — |
| Discord Developer Portal `message_content` intent | D-02 prefix commands | ✗ (operator action) | — | none — manual portal toggle is mandatory for prefix commands |
| `DISCORD_BOT_TOKEN` in `.env` | bot auth | ✗ (operator action) | — | none — fail-loud at startup |

**Missing dependencies with no fallback:** discord.py + cachetools (install via `uv add`); the portal intent toggle and the bot token (operator deploy steps — document explicitly).
**Missing dependencies with fallback:** cachetools could be a plain dict+lock, but the library is the recommended path.

## Sources

### Primary (HIGH confidence)
- `pypi.org/pypi/discord.py/json` — latest stable **2.7.1**, released 2026-03-03, requires Python ≥3.8. `[CITED]`
- `pypi.org/pypi/cachetools/json` — `TTLCache(maxsize, ttl)`; docs example is a 10-minute weather cache; thread-safety not provided by the library. `[CITED]`
- `discordpy.readthedocs.io/en/stable/api.html` — `Client.run()` vs `start()` (=`login()`+`connect()`) vs `close()`; `reconnect=True` default; `LoginFailure` on bad credentials. `[CITED]`
- discord.py issues #1529 ("Signal handling in run() prevents threading"), #1598, #1962 — `run()` installs signal handlers via `add_signal_handler`, which raises `ValueError: set_wakeup_fd only works in main thread` off the main thread; use `start()` on a worker thread + `run_coroutine_threadsafe`. `[CITED: github.com/Rapptz/discord.py]`
- Live codebase (verified by line number): `weatherbot/interactive/lookup.py` (`lookup_weather`, `LookupResult`, `UnknownLocationError`), `interactive/command.py` (`parse_weather_command`, `CommandKind`), `scheduler/daemon.py` (`run_daemon` lifecycle 1000–1200, file-watch thread 1080–1118 + teardown 1186–1197, `_do_reload` 549/605/636, `_reconcile_jobs` tuple), `channels/discord.py` (`send_briefing` embed shape), `config/settings.py`, `config/models.py` (frozen `extra="forbid"` house style), `config/holder.py` (lock-free `current()`), `weather/models.py` (`Forecast` display fields). `[VERIFIED: codebase grep/read]`
- `.planning/research/PITFALLS.md` — Pitfalls #1/#2/#3/#4/#10 + the Discord "Looks Done But Isn't" checklist + Security/UX tables. `[CITED]`

### Secondary (MEDIUM confidence)
- discord.py FAQ — "Heartbeat blocked", `run_in_executor` for blocking work in coroutines. `[CITED]`

### Tertiary (LOW confidence)
- None — all load-bearing claims (version, signal-handler limitation, intent requirement, lifecycle methods) verified against primary sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — discord.py 2.7.1 + cachetools verified on PyPI JSON; both established.
- Architecture (thread/loop lifecycle, isolation, embed, cache): HIGH — lifecycle facts verified against discord.py docs + issues; every seam verified against the live tree.
- Pitfalls: HIGH — the phase's own PITFALLS.md is the primary research, cross-checked against current discord.py behavior.
- CFG-07 / reload seam: HIGH — `_do_reload`/`_reconcile_jobs` read directly; the `channel` param and the tuple already exist.

**Research date:** 2026-06-16
**Valid until:** 2026-07-16 (discord.py minors can move; re-verify the version + the `start()`/signal-handler behavior if planning slips past this window).
