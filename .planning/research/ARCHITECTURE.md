# Architecture Research

**Domain:** WeatherBot v1.1 — "Interactive & Live-Config" (inbound Discord command bot + full-config hot-reload) integrated into the already-shipped always-on v1.0 daemon
**Researched:** 2026-06-15
**Confidence:** HIGH (v1.0 architecture read directly from source; external libs verified against PyPI + official docs)

> Scope note: This file answers *how the two NEW v1.1 features integrate with the
> already-shipped v1.0 architecture*. It does NOT re-derive the v1.0 design (scheduler,
> One Call client, channel seam, sent-log) — those are read from source and treated as
> fixed integration points. The full v1.0 architecture lives in the v1.0 milestone record.

## Standard Architecture

### System Overview (v1.1 target topology)

```
┌──────────────────────────────────────────────────────────────────────┐
│  weatherbot --run   (ONE process, systemd Type=notify, Restart=always) │
├───────────────────────────────────────┬────────────────────────────────┤
│  MAIN THREAD                           │  BACKGROUND THREAD(S)           │
│  ┌────────────────────────────────┐    │  ┌──────────────────────────┐   │
│  │ APScheduler BackgroundScheduler│    │  │ Discord gateway bot      │   │
│  │  (UNCHANGED v1.0)              │    │  │ (discord.py, asyncio loop│   │
│  │  - per-location CronTrigger    │    │  │  in its OWN thread)      │   │
│  │  - heartbeat IntervalTrigger   │    │  │  on_message → command    │   │
│  │  - threadpool fire_slot jobs   │    │  │   parse → lookup → reply │   │
│  └───────────────┬────────────────┘    │  └────────────┬─────────────┘   │
│                  │                      │               │                 │
│  ┌───────────────┴─────────────────┐   │  ┌────────────┴─────────────┐   │
│  │ stop.wait() blocks main thread  │   │  │ config reload watcher    │   │
│  │ (SIGTERM + NEW SIGHUP handlers) │   │  │ (watchfiles thread, OR   │   │
│  └─────────────────────────────────┘   │  │  SIGHUP-driven)          │   │
│                  │                      │  └────────────┬─────────────┘   │
├──────────────────┴──────────────────────┴──────────────┴─────────────────┤
│                    SHARED CORE (pure, thread-agnostic)                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ lookup_weather│ │ OpenWeather  │  │ template     │  │ ConfigHolder │  │
│  │ (NEW, read-   │ │ client       │  │ renderer     │  │ (NEW: atomic │  │
│  │  only core)   │ │ (httpx)      │  │ (regex)      │  │  swap box)   │  │
│  └──────┬────────┘ └──────────────┘  └──────────────┘  └──────────────┘  │
├─────────┴─────────────────────────────────────────────────────────────────┤
│  PERSISTENCE: SQLite (fresh sqlite3.connect() PER CALL → thread-safe)      │
│  sent_log · weather_onecall · alerts · heartbeat · health                 │
└──────────────────────────────────────────────────────────────────────────┘

SEPARATE one-shot process (no daemon needed):
   weatherbot weather <location>  →  load config → lookup_weather → print → exit
   (reuses the SAME shared-core fetch/render code, zero daemon coupling)
```

### Component Responsibilities

| Component | Responsibility | Status | Implementation |
|-----------|----------------|--------|----------------|
| `BackgroundScheduler` | Fire scheduled briefings on the threadpool | UNCHANGED | APScheduler 3.x, sync threads |
| Discord gateway bot | Receive `weather <loc>` commands, reply in-channel | NEW | discord.py 2.7.x, asyncio loop in dedicated thread |
| `ConfigHolder` | Hold the live `Config`; atomically swap on reload | NEW | tiny lock-guarded box (registry/holder pattern) |
| Reload watcher | Detect config edits (file-watch) + explicit trigger (SIGHUP / command) | NEW | watchfiles thread + signal handler → reload fn |
| `reload_config` | Re-validate → swap holder → diff & re-register APScheduler jobs | NEW | wraps existing `load_config`/validators + job diff |
| `lookup_weather` | The shared read-only fetch→render core | NEW (extracted) | sibling of `send_now`; both CLI + bot call it |
| `send_now` | Scheduled-briefing composition root (fetch→render→deliver→persist) | UNCHANGED | existing `cli.send_now` |
| OpenWeather client (`_WeatherClient`) | One Call 3.0 fetch | REUSED | per-call collaborator, no shared mutable state |
| Template renderer | regex substitution + fail-loud validate | REUSED | `templates.renderer` |
| SQLite store | sent-log / persistence / alerts | REUSED | fresh connection per call (already thread-safe) |
| Outbound `DiscordWebhookChannel` | Scheduled briefing delivery + online ping | UNCHANGED | the gateway bot does NOT replace it |

## Recommended Project Structure

```
weatherbot/
├── cli.py                     # MODIFY: add `weather`/`reload` subcommands; keep send_now
├── scheduler/
│   ├── daemon.py              # MODIFY: thread the bot + watcher into run_daemon; read holder
│   ├── reload.py              # NEW: ConfigHolder + reload_config + job-diff/re-register
│   └── context.py             # unchanged
├── interactive/               # NEW package: the inbound surface
│   ├── __init__.py
│   ├── lookup.py              # NEW: shared read-only fetch/render (CLI + bot both call)
│   ├── command.py             # NEW: parse "weather <loc>" → location name | None
│   └── discord_bot.py         # NEW: discord.py gateway Client, on_message handler
├── channels/                  # unchanged (outbound webhook stays the briefing path)
├── config/                    # unchanged loaders/models
└── weather/                   # unchanged client/store/models
```

### Structure Rationale

- **`interactive/lookup.py` is the keystone.** Both the CLI one-shot subcommand and the
  in-daemon Discord bot call ONE function — `lookup_weather(name, *, config, settings, ...)`
  — that resolves a configured location, fetches via the existing client, renders via the
  existing template, and returns text. This guarantees the two on-demand surfaces share core
  code (quality-gate requirement). It deliberately does NOT touch the sent-log, alerts, or
  heartbeat — on-demand lookups are stateless reads (see Pattern 4).
- **`scheduler/reload.py` is separate from `daemon.py`** so the atomic-swap + job-diff logic
  is unit-testable without standing up a full daemon, and so `daemon.py` only gains wiring.
- **`interactive/discord_bot.py` is isolated** so the heavyweight discord.py gateway import and
  asyncio code never leak into the one-shot CLI path (which must stay startup-cheap and
  daemon-free).
- **`command.py` separated from the bot** so the `weather <loc>` grammar is parsed/tested
  identically for the CLI and the Discord surfaces (one parser, two callers).

## Architectural Patterns

### Pattern 1: Concurrency topology — sync scheduler in main thread, asyncio bot in its own thread

**What:** Keep the v1.0 `BackgroundScheduler` exactly as-is (it already runs jobs on its own
threadpool while the main thread blocks on `stop.wait()`). Add the discord.py gateway bot in a
*dedicated daemon thread that owns its own asyncio event loop*. The two never share a loop; they
communicate only through the thread-safe shared core (SQLite + pure functions).

**When to use:** This is the recommended topology for WeatherBot.

**Trade-offs / why this beats the alternatives:**

| Option | Verdict | Reasoning |
|--------|---------|-----------|
| **(A) Keep `BackgroundScheduler`; run bot in its own thread+loop** | **RECOMMENDED** | Zero changes to the proven v1.0 scheduler/fire_slot/catch-up code. The bot thread is fully independent: a thread running `asyncio.run(client.start(token))`. No async rewrite of `fire_slot`. Lowest blast radius against 186 green tests. |
| (B) Switch to `AsyncIOScheduler`, run everything on one loop | REJECTED | Forces rewriting `fire_slot`, `_run_catchup`, `gate_until_healthy`, the tenacity retry, and the `stop_event` interruption model into async — a full rewrite of the verified v1.0 spine for no user-facing gain. High risk. |
| (C) Scheduler in a bg thread, asyncio loop in the main thread | VIABLE alt | discord.py's `run()` likes the main thread (signal handling). But v1.0 already puts the scheduler-owner + signal handlers in the main thread; flipping that re-plumbs the self-check gate and SIGTERM handling. (A) is less churn — choose (C) only if running discord.py off-main-thread proves troublesome (it generally is not — see note). |

> discord.py note (verified, 2.7.x): `Client.run()` installs its own signal handlers and is
> meant to be the LAST call on the main thread — do NOT use it in a child thread. Instead use
> the coroutine form `await client.start(token)` inside `asyncio.run(...)` on the bot thread,
> and let the MAIN thread keep owning SIGTERM/SIGHUP (it already does in v1.0 via
> `signal.signal(...)` + `stop.wait()`).

**Crossing the thread boundary (and why v1.1 barely needs to):** The gateway bot only ever
*reacts* to inbound `on_message` in v1.1 — scheduled briefings still go out via the outbound
*webhook*, not the bot — so the scheduler thread never needs to call a bot coroutine. The one
care point is the reverse: inside `on_message`, the shared core is **blocking** httpx + blocking
SQLite, so run it OFF the event loop with `await asyncio.to_thread(lookup_weather, ...)` — a slow
OpenWeather fetch must not stall the gateway heartbeat. (If a future feature ever needs the
scheduler thread to push to the bot, the correct primitive is
`asyncio.run_coroutine_threadsafe(coro, client.loop)` — out of scope for v1.1.)

**Example:**
```python
# interactive/discord_bot.py  (sketch)
import asyncio, discord

class WeatherBotClient(discord.Client):
    def __init__(self, holder, settings, db_path):
        intents = discord.Intents.none()
        intents.guilds = True; intents.guild_messages = True; intents.message_content = True
        super().__init__(intents=intents)
        self._holder, self._settings, self._db = holder, settings, db_path

    async def on_message(self, msg):
        if msg.author == self.user:
            return
        name = parse_weather_command(msg.content)     # `weather <loc>` → name | None
        if name is None:
            return
        cfg = self._holder.current()                  # snapshot the LIVE config
        try:                                          # blocking core, off the loop
            text = await asyncio.to_thread(
                lookup_weather, name, config=cfg, settings=self._settings, db_path=self._db
            )
        except ValueError as e:                       # unknown configured location
            text = str(e)
        await msg.channel.send(text)

def run_bot_thread(holder, settings, db_path, token):
    async def _main():
        client = WeatherBotClient(holder, settings, db_path)
        async with client:
            await client.start(token)                 # NOT .run() — own loop, child thread
    asyncio.run(_main())
```

### Pattern 2: ConfigHolder — atomic-swap holder for the live config

**What:** Replace "config is a local in `run_daemon`" with a tiny holder that owns the single
source of truth and hands out immutable snapshots. Reload re-validates a *candidate* config and,
only on success, atomically rebinds the holder's reference.

**When to use:** Required by ENH-V2-01. Every consumer (fire_slot jobs, the bot's `on_message`,
the announce/diff logic) reads `holder.current()` at the moment it needs config, never a
captured-at-startup reference.

**Trade-offs:** Pydantic `Config` objects are effectively immutable value snapshots, so a reader
holding an old reference is *safe* (it uses slightly stale config for the microseconds until it
re-reads). A single `threading.Lock` (or even a bare attribute rebind, atomic in CPython under
the GIL) suffices — no RW-lock needed at single-user scale. Keep-old-on-failure falls out
naturally: if validation throws, the holder is never rebound.

**Example:**
```python
# scheduler/reload.py  (sketch)
class ConfigHolder:
    def __init__(self, cfg): self._cfg, self._lock = cfg, threading.Lock()
    def current(self):
        with self._lock: return self._cfg            # return the snapshot reference
    def swap(self, new_cfg):
        with self._lock: self._cfg = new_cfg          # atomic rebind, only on success
```

### Pattern 3: Reload = re-validate → swap → diff-and-re-register jobs

**What:** A single `reload_config(path, holder, scheduler, ...)` triggered by EITHER a watchfiles
change event OR a SIGHUP / explicit command. Steps, in order:

1. **Re-validate** via the existing `load_config(path)` (+ `assert_unique_names`,
   `validate_template` on the new template). On ANY exception: log a WARNING with the error and
   **return without touching the holder or scheduler** — the live daemon keeps the old config
   (keep-old-on-failure, the headline requirement).
2. **Swap** `holder.swap(new_cfg)` — now all readers see the new config.
3. **Diff & re-register APScheduler jobs** using the SAME id scheme already in `_register_jobs`:
   `id = f"{location.name}|{slot.time}|{slot.days}"`. Compute the desired job-id set from the new
   config (enabled slots only), then:
   - `scheduler.remove_job(id)` for every live job-id absent from the new set (covers deleted
     slots and slots newly `enabled=false`);
   - `scheduler.add_job(...)` for every new-set id not currently live;
   - **leave unchanged ids untouched** — never remove-then-re-add a job whose id is identical.

**When to use:** The reload path for ENH-V2-01.

**The imminent-fire question (quality gate):** Because the job id encodes `name|time|days`, an
*unchanged* slot keeps the *same job object and its computed `next_run_time`* across reload — it
is never touched, so it cannot be dropped or double-fired. Only slots the user actually edited
change; momentarily removing/re-adding an edited slot around its fire instant is acceptable (the
user just changed it). APScheduler 3.x `add_job`/`remove_job` are thread-safe on a running
`BackgroundScheduler`, so the reload may run from the watcher thread.

**Idempotency interaction (quality gate):** The sent-log is the durable arbiter and is keyed on
`(location_name, send_time, local_date)` in SQLite — **completely independent of the APScheduler
job object.** This is the critical safety property:
- If a job is removed and re-added, or even fires twice around a reload, `claim_slot`'s atomic
  `INSERT OR IGNORE` still guarantees exactly-once delivery for that `(location, time, date)`
  key. The re-registered job cannot double-send: the first fire already wrote the sent_log row,
  so the second claim loses and returns early.
- An **in-flight send during reload** is unaffected: a running `fire_slot` already wrote its
  claim row and is executing its own retry loop; swapping the holder mid-send does not retract
  that attempt. The slot's idempotency key is unchanged, so a re-registered identical job can't
  duplicate it.

> **Pitfall flagged for the roadmap (the single most important hot-reload refactor):** v1.0
> `_register_jobs` passes `config=config` as a *captured job kwarg*, and `fire_slot` receives
> `config` as a parameter. If reload only swaps the holder but leaves unchanged jobs carrying the
> OLD config kwarg, an unchanged slot would render with stale templates/units after a reload.
> **Fix:** have `fire_slot` read `holder.current()` (pass the holder, not the frozen `config`,
> into the job kwargs). Make this a named, early task — it is a prerequisite for correct
> hot-reload and must land before the reload logic.

### Pattern 4: Shared stateless on-demand core (CLI one-shot == bot path)

**What:** `lookup_weather()` is a *read-only* sibling of `send_now`: resolve a configured location
→ fetch One Call (reusing `_WeatherClient`) → render the template → return text. It is the SINGLE
code path both the standalone CLI subcommand and the in-daemon Discord bot invoke.

**When to use:** CMD-V2-01, both surfaces.

**Trade-offs:** On-demand lookups deliberately do NOT write sent_log / alerts / heartbeat (those
are unattended-briefing liveness concerns — mirroring the existing `run_send_now`/`send_now`
attended-vs-daemon split). Because the OpenWeather client and renderer hold no shared mutable
state and SQLite uses a fresh connection per call, the on-demand path and a simultaneously-firing
scheduled briefing **cannot contend** — confirmed against `store.py` (every function opens its
own `sqlite3.connect()`). The CLI one-shot needs NO running daemon; the bot path runs inside it.
Both call the identical function with identical semantics, satisfying the shared-core gate.

**Example:**
```python
# interactive/lookup.py  (sketch — read-only, no liveness writes)
def lookup_weather(name, *, config, settings, db_path=None, client=None):
    location = resolve_location(config, name)          # configured-only (raises if unknown)
    client = client or build_client(settings)
    forecast = Forecast.from_payloads(location,
        client.fetch_onecall(location, "imperial"),
        client.fetch_onecall(location, "metric"),
        primary=location.units or "imperial")
    tz = ZoneInfo(location.timezone); now = datetime.now(tz)
    return render(load_template(config.template),
                  {**forecast.placeholders(),
                   **schedule_placeholders(None, now, now)})  # manual-send semantics (no note)
```

## Data Flow

### On-demand request flow (both surfaces converge on one core)

```
CLI:    `weatherbot weather home`                  Discord: user types "weather home"
          ↓ load_config + load_settings              ↓ on_message (bot thread)
          ↓                                           ↓ holder.current()  (live config)
          └───────────────→  lookup_weather()  ←──────┘ (via asyncio.to_thread)
                                   ↓
            resolve_location → client.fetch_onecall ×2 → Forecast → render
                                   ↓
   CLI: print()/exit         Discord: await msg.channel.send(text)
```

### Hot-reload flow

```
config.toml edited  ──(watchfiles event)──┐
SIGHUP received     ──(signal handler)─────┤→  reload_config(path, holder, scheduler)
explicit `reload`   ───────────────────────┘         ↓
                                          1. load_config + validate  ──fail──→ WARN, keep old
                                                     ↓ ok
                                          2. holder.swap(new_cfg)   (atomic)
                                                     ↓
                                          3. diff job-id set → remove stale / add new
                                             (unchanged ids untouched; sent_log arbitrates)
```

### Key Data Flows

1. **Inbound command → reply:** a NEW direction for WeatherBot (v1 was outbound-only). Stays
   read-only against the store; never enqueues a scheduled briefing or writes liveness rows.
2. **Config edit → live re-registration:** the only writer of the holder; everything else reads
   `holder.current()` at use-time.

## Scaling Considerations

This remains a single-user personal tool; "scale" means commands/minute and config-reload
frequency, not users.

| Scale | Architecture adjustments |
|-------|--------------------------|
| 1 user (this project) | The recommended topology is already right-sized. No queue, no RW-lock, no async rewrite of the scheduler. |
| Bursty commands | discord.py rate-limits replies automatically; `asyncio.to_thread` caps concurrent fetches at the default thread-pool size — fine for one user. |
| OpenWeather quota | On-demand adds 2 calls/command. Trivial against the One Call 3.0 daily cap for one user; add a short-TTL cache on `lookup_weather` ONLY if command-spamming becomes real. |

### Scaling Priorities

1. **First "bottleneck":** none at single-user scale. The realistic risk is *correctness* (stale
   config in captured job kwargs — Pattern 3 pitfall), not throughput.
2. **Second:** OpenWeather rate-limit if commands are spammed; mitigate with a short-TTL in-memory
   cache, not an architecture change.

## Anti-Patterns

### Anti-Pattern 1: Rewriting the scheduler to AsyncIOScheduler "to match" the bot

**What people do:** Assume one process must have one event loop, so they port the verified v1.0
sync scheduler to async.
**Why it's wrong:** Discards 186 green tests and a hardened fire_slot/retry/catch-up spine for
zero user benefit. The sync scheduler and the asyncio bot coexist fine in separate threads.
**Do this instead:** Pattern 1 — leave the scheduler alone; isolate the bot in its own thread+loop.

### Anti-Pattern 2: Mutating the live Config in place on reload

**What people do:** `config.locations = new_locations` on the shared object.
**Why it's wrong:** A reader mid-iteration (a firing job, an in-flight `on_message`) sees a
half-updated object → torn reads, irreproducible bugs.
**Do this instead:** Pattern 2 — build a NEW validated Config and atomically rebind the holder.
Old readers keep their consistent snapshot.

### Anti-Pattern 3: Swapping config but not refreshing the scheduler

**What people do:** `holder.swap()` and stop, assuming jobs pick up new schedules.
**Why it's wrong:** APScheduler jobs are already registered with the old triggers; a new
send-time never fires until restart — defeating the feature.
**Do this instead:** Pattern 3 step 3 — diff the job-id set and add/remove jobs, AND make
`fire_slot` read the holder (not a captured config kwarg).

### Anti-Pattern 4: Blocking the gateway loop on the OpenWeather fetch

**What people do:** call blocking httpx directly inside `on_message`.
**Why it's wrong:** A slow/timing-out fetch stalls the single gateway event loop → missed
heartbeats → Discord disconnects the bot.
**Do this instead:** `await asyncio.to_thread(lookup_weather, ...)` so the blocking core runs off
the loop.

### Anti-Pattern 5: Reusing the v1 webhook to deliver command replies

**What people do:** Reply to a `weather home` command by POSTing to the outbound briefing webhook.
**Why it's wrong:** The webhook can't reply in the channel/thread the user asked in, and conflates
the unattended-briefing path with the interactive path.
**Do this instead:** Reply via the gateway bot's `msg.channel.send(...)`. The outbound webhook
stays exclusively for scheduled briefings + the online ping.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Discord gateway (inbound) | discord.py 2.7.x `Client` + **`message_content` privileged intent**, started via `client.start()` in a dedicated thread loop | NEW persistent connection + **bot token** (distinct from the v1 webhook). Must enable the Message Content intent in the Discord dev portal. Reverses the v1 "don't use discord.py" guidance — that applied only to fire-and-forget webhook sends; receiving commands genuinely needs the gateway. |
| Discord webhook (outbound) | existing `DiscordWebhookChannel` | UNCHANGED — scheduled briefings + the online ping still go out via the webhook, NOT the gateway bot. |
| OpenWeather One Call 3.0 | existing `_WeatherClient` via httpx | REUSED unchanged by the on-demand path; 2 calls per command. |
| File system (config watch) | **watchfiles 1.2.x** (recommended): Rust/Notify-backed, ~0% idle CPU, same author as pydantic | Run `watch(path)` in a daemon thread that calls `reload_config`. Alternative: `watchdog 6.0.x` (more mature, heavier, observer/handler API). For a single-file watch on an always-on host, watchfiles is the lighter modern pick. SIGHUP is the dependency-free explicit-trigger fallback. |
| systemd | existing Type=notify | UNCHANGED. Wire SIGHUP via `ExecReload=/bin/kill -HUP $MAINPID` so `systemctl reload weatherbot` becomes the operator's explicit reload trigger. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| bot thread ↔ scheduler thread | NONE direct; both touch only the thread-safe shared core | No cross-thread coroutine scheduling needed in v1.1 (bot only reacts to inbound). |
| watcher/signal ↔ scheduler | `reload_config` called synchronously; uses thread-safe `add_job`/`remove_job` | APScheduler 3.x `BackgroundScheduler` mutation is thread-safe while running. |
| all consumers ↔ ConfigHolder | `holder.current()` snapshot read | The single source of truth; rebind only on validated reload. |
| any thread ↔ SQLite | fresh `sqlite3.connect()` per call | Already the v1.0 pattern — no shared connection, no contention. |

## Suggested Build Order (for roadmap decomposition)

1. **Extract `interactive/lookup.py` + `command.py`** — refactor the read-only fetch/render core
   out of `send_now` so both surfaces share it; add the `weather <loc>` parser. Foundation, no
   concurrency. Independently unit-testable.
2. **CLI `weather <location>` subcommand** — the one-shot standalone path. Lowest risk, no daemon
   coupling, validates `lookup_weather` end-to-end. Ship first.
3. **ConfigHolder + `fire_slot` reads-from-holder refactor** — prerequisite correctness fix for
   hot-reload (Pattern 3 pitfall). Touches daemon job kwargs; do BEFORE reload logic.
4. **`reload_config` (re-validate → swap → job diff) + SIGHUP trigger** — the explicit-trigger
   half of ENH-V2-01. Testable without the file watcher.
5. **watchfiles file-watch thread** — the auto-on-save half; a thin wrapper that calls step 4.
6. **Discord gateway bot in its own thread** — the in-daemon inbound surface (CMD-V2-01). Built
   last: depends on the shared lookup (step 1) and benefits from the holder (step 3) existing so
   the bot reads live config.

Rationale: each step is independently shippable/testable, dependencies flow strictly upward
(1 → {2,3}; 3 → 4 → 5; {1,3} → 6), and the highest-risk async/threading work (the bot) lands last
on proven foundations.

## Sources

- WeatherBot v1.0 source (read directly): `weatherbot/scheduler/daemon.py`, `weatherbot/scheduler/context.py`,
  `weatherbot/cli.py`, `weatherbot/channels/base.py`, `weatherbot/channels/factory.py`,
  `weatherbot/config/loader.py`, `weatherbot/config/models.py`, `weatherbot/weather/store.py`
  — HIGH (authoritative; the integration target)
- discord.py API docs — `Client.run()` vs `Client.start()` for custom loop/thread management:
  https://discordpy.readthedocs.io/en/stable/api.html — HIGH
- discord.py + APScheduler/threading + `run_coroutine_threadsafe` cross-thread pattern (community,
  verified against asyncio stdlib semantics): https://discordpy.readthedocs.io/en/stable/ext/tasks/ — MEDIUM
- watchfiles vs watchdog (2025 recommendation; Rust/Notify-backed, low idle CPU):
  https://watchfiles.helpmanual.io/ , https://adamj.eu/tech/2025/09/22/introducing-django-watchfiles/ — MEDIUM
- APScheduler 3.x — thread-safe `add_job`/`remove_job` on a running `BackgroundScheduler`:
  https://apscheduler.readthedocs.io/en/3.x/userguide.html — HIGH
- PyPI current versions (checked 2026-06-15): discord.py 2.7.1, watchfiles 1.2.0, watchdog 6.0.0 — HIGH

---
*Architecture research for: WeatherBot v1.1 Interactive & Live-Config*
*Researched: 2026-06-15*
