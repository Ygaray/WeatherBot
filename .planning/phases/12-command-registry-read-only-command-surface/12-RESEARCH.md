# Phase 12: Command Registry & Read-Only Command Surface - Research

**Researched:** 2026-06-18
**Domain:** Self-describing command registry feeding both a discord.py gateway bot and an argparse CLI, over already-fetched OpenWeather One Call 3.0 data, behind an existing operator guard ladder.
**Confidence:** HIGH (brownfield — every claim verified against the installed code + `uv.lock` + One Call 3.0 docs)

## Summary

This is a **brownfield extension**, not greenfield. Almost everything needed already exists: a shared read-only `lookup_weather` core (`interactive/lookup.py`), a thread-safe `ForecastCache` (`interactive/cache.py`), a load-bearing guard ladder + off-loop dispatch + embed reply in `interactive/bot.py`, and an argparse `add_subparsers` CLI in `cli.py`. The phase's real work is to (a) **introduce ONE command registry** that both the Discord `on_message` dispatch and the CLI subparser-builder consume, so `help` auto-generates and the two surfaces can never drift, and (b) **add six read-only command handlers** (`alerts`/`locations`/`status`/`sun`/`wind`/`next-cloudy`) plus `help`, every one routed through the existing guard ladder and failure-isolation envelope.

Three findings change the plan materially. **(1) The One Call client excludes `hourly`.** `weatherbot/weather/client.py` fetches with `exclude=minutely,hourly`, so `hourly[]` is NOT in the payload — `next-cloudy`'s hybrid (D-03: 48h hourly + daily 3–8) requires widening the `exclude` to keep `hourly`. **(2) `status` cannot be served from the bot layer as it stands.** `BotThread`/`build_on_message` receive only `holder`, `operator_id`, and `cache` — they have NO handle on the live `BackgroundScheduler`, the daemon's `db_path`, the process start time, or the bot/monitor liveness. `status` (CMD-12) needs all four, so the phase must thread a small read-only "daemon state" accessor into the bot + cache layers. **(3) The heartbeat/health rows have writers but no readers** — `stamp_tick`/`stamp_success`/`stamp_health` exist; there is NO `read_heartbeat`/`read_health`. `status`'s "last briefing result" and uptime story needs new read functions in `weather/store.py`.

The CLAUDE.md stack table is mostly right but has **two drift points to ignore**: this project does NOT use Jinja2 (it uses a custom regex `{name}` renderer in `templates/renderer.py`), and `cachetools` is **7.1.4**, not 6.x. All versions below are taken from `uv.lock` (authoritative for what is installed), not training data.

**Primary recommendation:** Build one `interactive/registry.py` module holding an immutable list of `CommandSpec` records (name, group, one-line help, takes-location flag, handler callable). The Discord dispatch, the CLI subparser-builder, and the `help` renderer all derive from this single list. Generalize `parse_weather_command` into a registry-driven `parse_command` (keyword → spec + raw arg) keeping the exact word-boundary guard. Widen the One Call `exclude` to include `hourly`, add read-only `read_heartbeat`/`read_health` store functions, and thread a read-only `DaemonState` accessor into the bot/cache layer so `status` can report live scheduler + liveness + last-briefing. Keep every handler read-only and inside the existing non-propagating try/except.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Command registry (single source of truth) | Shared core (`interactive/registry.py`) | — | Both Discord dispatch and CLI must derive from one list; it belongs in neither surface |
| Command parsing (keyword → spec + arg) | Shared core (`interactive/command.py`) | — | Already surface-agnostic, parse-don't-validate; generalize in place |
| Guard ladder (bot drop / operator-id / `!` prefix) | Discord bot (`interactive/bot.py`) | — | Discord-specific; ORDER load-bearing; CLI has no equivalent (terminal == operator) |
| Off-loop fetch + TTL cache | Shared core (`interactive/cache.py`) | Discord bot (dispatch via `run_in_executor`) | Network/render is blocking; must stay off the gateway loop |
| Read-only weather views (`alerts`/`sun`/`wind`/`next-cloudy`) | Shared core (`lookup`/`Forecast` + raw payload) | both surfaces (render) | Data derivation is surface-agnostic; only the final embed-vs-text differs |
| `status` (next-send / uptime / liveness / last-briefing) | Daemon state accessor (new, read-only) | Discord bot + CLI (render) | Reads live scheduler + db heartbeat + process start; must be injected into the command layer |
| `help` (auto-generated) | Shared core (registry render) | both surfaces (embed vs plain) | Same content both surfaces (D-04); only the wrapper differs |
| CLI subcommand wiring | CLI (`cli.py` argparse) | registry (spec list) | argparse is CLI-only; subparsers generated from the shared registry |

## Standard Stack

No new third-party libraries are required. The phase is built entirely on the installed stack.

### Core (already installed — verified against `uv.lock`, 2026-06-18)
| Library | Version (uv.lock) | Purpose in this phase | Why Standard |
|---------|-------------------|------------------------|--------------|
| discord.py | 2.7.1 | Gateway bot + `discord.Embed` reply (registry dispatch plugs into existing `on_message`) | [VERIFIED: uv.lock] Already the inbound surface (Phase 11) |
| APScheduler | 3.11.2 | `status` reads next-fire times via `scheduler.get_jobs()` + `job.trigger.get_next_fire_time(...)` / `job.next_run_time` | [VERIFIED: uv.lock + daemon.py `_announce_schedule`] The exact introspection `status` needs already exists |
| httpx | 0.28.1 | One Call 3.0 fetch (unchanged; only `exclude` widened) | [VERIFIED: uv.lock] |
| cachetools | 7.1.4 | `ForecastCache` TTLCache the new commands reuse | [VERIFIED: uv.lock] **Note: 7.x, not the 6.x in CLAUDE.md** |
| pydantic | 2.13.4 | `BotConfig`/`Config`/`Location` models; add the global cloud-threshold knob here | [VERIFIED: uv.lock] |
| pydantic-settings | 2.14.1 | Secrets (`discord_bot_token`); unchanged | [VERIFIED: uv.lock] |
| structlog | 26.1.0 | Outcome-only logging; unchanged | [VERIFIED: uv.lock] |
| (stdlib) argparse | 3.12+ | `add_subparsers` CLI surface generated from the registry | [VERIFIED: cli.py:593] |
| (custom) `templates/renderer.py` | n/a | Plain-text `{name}` regex renderer — **the project does NOT use Jinja2** | [VERIFIED: templates/renderer.py] CLAUDE.md's Jinja2 row is aspirational, not actual |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (stdlib) `zoneinfo` | built-in | Convert One Call Unix `sunrise`/`sunset` to location-local wall-clock for `sun` + the `next-cloudy` daytime window | sun command, daytime gating |
| (stdlib) `datetime` | built-in | Uptime computation (process start vs now); Unix-ts → local time | status, sun |
| (stdlib) `sqlite3` | built-in | New read-only `read_heartbeat`/`read_health` in `weather/store.py` for `status` | status last-briefing |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| One registry list both surfaces consume | discord.py `commands.Bot` + `app_commands` (slash commands) | REJECTED — Phase 11 deliberately uses a bare `discord.Client` + manual guard ladder for a one-operator private server (see bot.py docstring). Adopting the command framework would re-introduce the gateway-bot machinery Phase 11 avoided and bypass the load-bearing guard ladder. Stay with the manual registry. |
| `wind_deg` → 16-point compass in code | store a compass string | Compute the 8/16-point compass label in a small pure helper (don't hand-roll a wind-bearing parser library — it's a `int((deg+11.25)/22.5) % 16` table lookup). |
| New `read_heartbeat` SQL | reuse `was_sent` | `was_sent` answers a different question (was THIS slot sent). `status`'s "last briefing result" wants the most-recent success across all slots — the heartbeat `last_success_utc` row already holds it; just add a reader. |

**Installation:** none — `uv sync` already provides everything.

**Version verification (performed 2026-06-18):** Read from `uv.lock` (the lockfile is authoritative for what is installed; the `.venv` on this research host is partially populated, but production runs an editable install per MEMORY.md). Confirmed: discord.py 2.7.1, apscheduler 3.11.2, httpx 0.28.1, cachetools 7.1.4, pydantic 2.13.4, pydantic-settings 2.14.1, structlog 26.1.0, tenacity 9.1.4, watchfiles 1.2.0.

## Package Legitimacy Audit

> No new external packages are installed in this phase. All dependencies are already present and pinned in `uv.lock`. The Package Legitimacy Gate is therefore N/A for new installs.

| Package | Registry | Disposition |
|---------|----------|-------------|
| (none added) | — | Phase uses only already-locked deps; no new install, no slopcheck needed |

**Packages removed due to slopcheck [SLOP] verdict:** none (no new packages)
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Discord operator types "!sun home"          CLI: weatherbot sun home
        │                                            │
        ▼                                            ▼
on_message GUARD LADDER (bot.py)            argparse dispatch (cli.py)
  1. author.bot?  drop                         (terminal == operator;
  2. author.id != operator_id?  drop            no guard ladder needed)
  3. startswith("!")?  else drop                       │
        │                                              │
        ▼                                              │
  parse_command(text[1:])  ───────────┐                │
  (registry-driven, word-boundary     │                │
   guard preserved)                   ▼                │
        │                    ┌──────────────────┐      │
        │                    │  COMMAND REGISTRY │◄─────┘  (CLI subparsers
        │                    │  registry.py      │          generated from
        │                    │  [CommandSpec...] │          the same list)
        │                    │  name/group/help/ │
        │                    │  takes_location/  │
        │                    │  handler          │
        │                    └────────┬──────────┘
        │                             │ resolve spec → handler
        ▼                             ▼
  run_in_executor(handler, arg, ctx)  ── OFF the event loop (Discord)
        │
        ├── weather views (alerts/sun/wind/next-cloudy):
        │      ForecastCache.lookup(name, config)  ──► lookup_weather
        │         resolve_location → fetch One Call (imp+met) → Forecast
        │         (READ-ONLY: zero store writes)            │
        │         handler reads forecast.raw_onecall_imp ───┘
        │           current.sunrise/sunset, wind_deg, alerts[], hourly[].clouds
        │
        ├── locations: read config.locations (no fetch)
        ├── help:      render the registry (no fetch)
        └── status:    DaemonState accessor (NEW, read-only)
                 scheduler.get_jobs() → next_run_time per location
                 read_heartbeat(db) → last_success_utc, last_tick_utc
                 process start time → uptime
                 bot.is_alive() / monitor state (Phase 15)
        │
        ▼
  Discord: discord.Embed   |   CLI: plain text
  (WHOLE body inside the non-propagating try/except — a command
   failure NEVER touches the scheduled briefing path, CMD-16)
```

### Recommended Project Structure
```
weatherbot/interactive/
├── registry.py     # NEW: CommandSpec dataclass + COMMANDS list + help renderer
├── command.py      # generalize parse_weather_command → parse_command(registry)
├── commands/       # NEW (optional): one handler per command, or a single handlers.py
│   ├── weather_views.py   # alerts/sun/wind/next_cloudy (read forecast + raw payload)
│   ├── info.py            # help, locations
│   └── status.py          # status (consumes DaemonState)
├── bot.py          # on_message dispatch becomes registry-driven (ladder unchanged)
├── cache.py        # reused as-is; consider a generic fetch entry if needed
└── lookup.py       # reused; LookupResult already carries forecast (+ raw payloads)
weatherbot/weather/
├── client.py       # widen exclude: keep hourly (drop only minutely) for next-cloudy
├── store.py        # NEW: read_heartbeat(db), read_health(db) (read-only)
└── models.py       # Forecast.raw_onecall_imp already retains the full payload
weatherbot/config/
└── models.py       # NEW: global cloud_threshold knob (Config or a [commands] table)
```

### Pattern 1: The Command Registry (single source of truth, D-04/D-05)
**What:** One immutable list of `CommandSpec` records. Discord dispatch, CLI subparsers, and `help` all read it.
**When to use:** Always — this is the phase's reason to exist.
**Example (house style — frozen dataclass, mirrors `Command`/`LookupResult`):**
```python
# weatherbot/interactive/registry.py  (pattern — verify handler signatures during planning)
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class CommandSpec:
    name: str                 # "sun", "next-cloudy", "help"
    group: str                # "Weather" | "Forecasts" | "Info"  (help grouping, D-04)
    summary: str              # one-line help text (D-04)
    takes_location: bool      # True → resolves default-first location when arg omitted (D-01)
    handler: Callable         # (arg: str | None, ctx: CommandContext) -> Reply

# A single ordered tuple is the source of truth. help renders it grouped;
# the CLI builds one subparser per spec; the bot dispatch looks up by name.
COMMANDS: tuple[CommandSpec, ...] = ( ... )
BY_NAME = {c.name: c for c in COMMANDS}
```
**Source:** house pattern derived from `interactive/command.py` (frozen `@dataclass`) and `lookup.py` (`LookupResult`).

### Pattern 2: Registry-driven parse, guard ladder UNCHANGED
**What:** Generalize `parse_weather_command` into `parse_command(text)` that matches the FIRST whitespace-delimited token against `BY_NAME`, preserving the exact word-boundary guard (whitespace must follow the keyword; `"sunny"` must not match `sun`).
**When:** Replaces step (4) of the guard ladder in `bot.py`. Steps (1)–(3) (`author.bot` → `operator_id` → `!` prefix) and the off-loop `run_in_executor` + non-propagating try/except stay byte-for-byte.
**Example:**
```python
# Keep the word-boundary discipline from command.py (the anti-feedback-loop guard, T-06-02).
# Match the longest keyword first so "next-cloudy" wins over a hypothetical "next".
def parse_command(text: str) -> ParsedCommand:
    stripped = text.strip()
    for spec in COMMANDS_BY_KEYWORD_LEN_DESC:        # longest keyword first
        kw = spec.name
        if not stripped.casefold().startswith(kw):
            continue
        rest = stripped[len(kw):]
        if rest and not rest[0].isspace():           # word-boundary guard (unchanged)
            continue
        arg = rest.strip() or None
        return ParsedCommand(spec=spec, arg=arg)
    return ParsedCommand(spec=None, arg=None)         # NOT_A_COMMAND
```
**Source:** generalizes `command.py:parse_weather_command` (lines 50–70).

### Pattern 3: `status` via a read-only DaemonState accessor (the integration seam)
**What:** `status` needs four things the bot layer does NOT currently have. Inject a small read-only accessor (a frozen object or a callable bundle) constructed in `run_daemon` and threaded into `BotThread`/the registry context alongside `cache`:
- **Next scheduled send per location** — `scheduler.get_jobs()` then `job.next_run_time` (running scheduler) falling back to `job.trigger.get_next_fire_time(None, datetime.now(tz))`. This is EXACTLY what `_announce_schedule` (daemon.py:697–731) already does — extract it into a reusable read-only helper.
- **Alive + uptime** — capture a `started_at = datetime.now(timezone.utc)` in `run_daemon` and pass it through; uptime = now − started_at.
- **Bot + monitor state** — `bot.is_alive()` exists (bot.py:242). The UV monitor (Phase 15) doesn't exist yet; `status` should report it as "not running"/absent for now and have a clean slot to add it.
- **Last briefing result** — read the heartbeat row's `last_success_utc` / `last_tick_utc` via a NEW `read_heartbeat(db_path)` (the writers `stamp_success`/`stamp_tick` exist; no reader does).
**When:** Only `status` needs this; keep the weather-view handlers free of it.
**Source:** `daemon.py:_announce_schedule` (next-fire), `bot.py:is_alive`, `store.py:stamp_success/stamp_tick`.

### Pattern 4: Reading sun/wind/alerts/clouds off the already-fetched payload
**What:** `Forecast` retains both raw One Call payloads (`raw_onecall_imp` / `raw_onecall_met`, models.py:134). The new views read fields the `Forecast` model doesn't surface yet:
- **wind:** `wind_imp`/`wind_met` + `wind_display` already exist on `Forecast`; **wind direction** needs `current.wind_deg` from the raw payload → compass label.
- **sun:** `current.sunrise` / `current.sunset` (Unix UTC) from the raw payload → location-local time via `ZoneInfo(location.timezone)`. (Also available per-day at `daily[].sunrise/sunset`.)
- **alerts:** `alerts[]` already drives `Forecast.alert` (a one-line summary); the `alerts` COMMAND wants the fuller `event`/`start`/`end`/`description` per alert from `raw_onecall_imp["alerts"]`.
- **next-cloudy:** `hourly[].clouds` (near-term, ONCE the exclude is widened) + `daily[].clouds` (days 3–8) from the raw payload.
**Anti-pattern:** Do NOT add a second fetch. Everything is in the One Call payload `Forecast` already holds — except `hourly`, which is excluded today (see Pitfall 1).

### Anti-Patterns to Avoid
- **Adopting `discord.ext.commands` / slash commands** — bypasses the load-bearing manual guard ladder Phase 11 deliberately built; re-introduces gateway-bot weight. Stay with the bare client + registry dispatch.
- **A separate Discord registry and CLI registry** — defeats the entire phase (the `help`-drift problem D-04 exists to kill). One list, two consumers.
- **Writing to the store from any handler** — HARD constraint D-06 / SC#5. `lookup_weather` is already store-free; keep new handlers store-free (the zero-store-writes spy test pattern from Phase 6 should be extended to cover them).
- **Letting a handler exception escape `on_message`** — CMD-16 / D-11. Keep the WHOLE dispatch inside the existing non-propagating try/except; a per-command bug must never reach the scheduler thread.
- **Re-reading `operator_id` per message expecting live reload** — it is intentionally baked at construction (bot.py:96–101); unchanged in this phase.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Next-fire-time computation | A cron-expansion calculator | `job.next_run_time` / `job.trigger.get_next_fire_time(...)` (APScheduler) | Already used in `_announce_schedule`; tz-correct, DST-correct |
| Location resolution / default-first | Name-matching loop | `resolve_location(config, name)` (loader.py:40) | Handles None→default, casefold match, raises `UnknownLocationError` |
| TTL fetch caching | A dict + timestamps | `ForecastCache` (cache.py) | Thread-safe, lock-scoped, invalidation already wired to reload |
| Unknown-location hint | Custom error string | `UnknownLocationError(.requested, .valid_names)` (lookup.py:44) | Already the corrective-hint path the ladder catches |
| Timezone / sunrise local time | Manual UTC offset math | `ZoneInfo` + `datetime.fromtimestamp(ts, tz)` | Stdlib owns the IANA DB; offsets vary with DST |
| Wind compass label | A bearing library | `("N","NNE",...)[int((deg+11.25)/22.5)%16]` pure helper | 5-line lookup; no dependency |
| Template rendering | Jinja2 (CLAUDE.md aspiration) | the existing `templates/renderer.py` `{name}` regex renderer | Project never adopted Jinja2; the injection-safe renderer is the house seam |

**Key insight:** Phase 12 is wiring, not invention. The expensive, edge-case-laden pieces (tz, scheduling, caching, resolution, error semantics, injection-safe rendering) are all built and tested. The risk is in the *seams* — widening `exclude`, threading `DaemonState`, and keeping every handler inside the isolation envelope.

## Runtime State Inventory

> This is a code-addition phase (new module + new handlers + a widened query param + new read-only SQL), not a rename/refactor/migration. No stored strings are renamed and no live external config is re-keyed. Inventory completed for completeness:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | The SQLite `heartbeat`/`health`/`sent_log` rows are READ by `status` but never re-keyed or migrated. New `weather_onecall` rows are NOT written by any command (read-only). | None — read-only additions; no migration |
| Live service config | `config.toml` gains an optional global cloud-threshold knob (default 60%). It is a NEW optional key, so existing configs load unchanged (extra-key-tolerant only because it's an added field; note `extra="forbid"` means it must be a declared field, not an arbitrary key). | Add the field to the pydantic model; document in deploy README |
| OS-registered state | None — no systemd unit, task, or PID registration changes. | None — verified: no unit/timer edits in scope |
| Secrets/env vars | None — `discord_bot_token` / `OPENWEATHER_API_KEY` unchanged; no new secret. | None |
| Build artifacts | Production runs an editable install (`uv` editable) per MEMORY.md; adding `interactive/registry.py` + handlers is picked up live by an editable install, but the **running daemon must be restarted** to load new modules (the bot thread is constructed at daemon start). | Restart `weatherbot` service after deploy (UAT touches a live daemon — MEMORY.md) |

**The canonical question — after every file is updated, what runtime systems still have old state?** Only the **running daemon process** itself: new command modules and the widened `exclude` take effect on the NEXT process start, not via hot-reload (hot-reload covers config + templates, not Python modules). Plan a service restart in the deploy/UAT step.

## Common Pitfalls

### Pitfall 1: `hourly` is excluded — `next-cloudy`'s near-term half is empty
**What goes wrong:** `next-cloudy` (D-03) wants 48h **hourly** cloud cover for the precise near term, but `client.py:fetch_onecall` sends `exclude=minutely,hourly`, so `raw_onecall["hourly"]` is absent — the hybrid silently falls back to daily-only or KeyErrors.
**Why:** The exclude was set in v1.0 when only `current`/`daily`/`alerts` were needed (smaller payload).
**How to avoid:** Change `exclude` to `minutely` only (keep `hourly`). Verify the daily/current/alerts paths still work (they're untouched). This adds ~48 hourly entries to the payload — trivially within free-tier and well under the httpx timeout. Confirm `Forecast.from_payloads` still ignores `hourly` (it reads `current`/`daily[0]`/`alerts`, so no change needed there).
**Warning signs:** `next-cloudy` returns a day 3+ answer even when tomorrow morning is overcast; or a `KeyError: 'hourly'` in the handler.

### Pitfall 2: `status` has no path to the scheduler/db/start-time from the bot layer
**What goes wrong:** A naive `status` handler tries to read `scheduler` or `db_path` but `build_on_message`/`BotThread` were never given them (they receive only `holder`, `operator_id`, `cache`).
**Why:** Phase 11 scoped the bot to `!weather` only, which needs nothing beyond the cache + holder.
**How to avoid:** Construct a read-only `DaemonState` (or pass `scheduler`, `db_path`, `started_at`, and a `bot_alive` callable) in `run_daemon` and thread it into the registry context the same way `cache` is threaded into `BotThread`. Keep it READ-ONLY — `status` reports, never mutates (D-02 note / "no two-way config editing").
**Warning signs:** `status` only works in tests with hand-built fakes; or the handler reaches for a module global.

### Pitfall 3: Heartbeat/health rows have writers but no readers
**What goes wrong:** `status`'s "last briefing result" needs `last_success_utc`, but `store.py` only has `stamp_success`/`stamp_tick`/`stamp_health` — no `read_*`.
**How to avoid:** Add parameterized read-only `read_heartbeat(db_path)` and `read_health(db_path)` returning the single seeded row (id=1). Use `?` placeholders (SQLi house rule T-03-01) and `executescript(_SCHEMA)` on connect so they tolerate a never-initialized db (mirroring the stamp functions).
**Warning signs:** `status` reports "unknown" for last-briefing because nothing reads the row.

### Pitfall 4: Word-boundary guard regression on multi-command parse
**What goes wrong:** Generalizing the parser, `sun` matches `"sunny day"` or `next-cloudy` collides with a future `next` command, re-opening the feedback-loop / mis-parse risk `command.py` carefully closed (T-06-02).
**How to avoid:** Preserve the exact "whitespace must follow the keyword" guard per spec, and match **longest keyword first** so `next-cloudy` is tested before any shorter prefix. Keep the parser pure (no `str.format`/`eval`) — it already is.
**Warning signs:** `!sunny` triggers `sun`; a hypothetical future command shadows another.

### Pitfall 5: A command failure leaking out of `on_message`
**What goes wrong:** A new handler raises (bad payload, missing field) and the exception escapes the non-propagating envelope, reaching the gateway/scheduler.
**Why:** Adding a second `try`/dispatch branch outside the existing wrapper.
**How to avoid:** Keep the WHOLE dispatch — registry lookup + `run_in_executor(handler)` + reply — INSIDE the existing `try/except Exception` in `build_on_message` (bot.py:124–148). The `UnknownLocationError` branch stays a sub-except. CMD-16 is satisfied by reusing the envelope verbatim, not by adding new ones.
**Warning signs:** A handler bug shows up as a gateway disconnect or a missed briefing instead of a generic "something went wrong" reply.

### Pitfall 6: `extra="forbid"` rejects an ad-hoc threshold key
**What goes wrong:** Adding the cloud threshold as a loose `config.toml` key fails load because every config model is `extra="forbid"` (models.py).
**How to avoid:** Add it as a DECLARED pydantic field (e.g. `cloud_threshold: int = 60` on `Config`, or a new frozen `[commands]`/`[next_cloudy]` sub-model with a default), so an existing config with no such key loads unchanged via the default. Validate range (0–100) fail-loud at load, matching the `Schedule`/`Reliability` tradition.
**Warning signs:** Existing configs fail to load after the field is added (means it wasn't given a default), or an arbitrary key is silently accepted (it won't be).

## Code Examples

### Reading sunrise/sunset as location-local time (sun)
```python
# Source: One Call 3.0 docs (current.sunrise/sunset are Unix UTC) + house ZoneInfo pattern
from datetime import datetime
from zoneinfo import ZoneInfo

def sun_times(forecast, location):
    cur = (forecast.raw_onecall_imp.get("current") or {})
    tz = ZoneInfo(location.timezone)
    sunrise = datetime.fromtimestamp(cur["sunrise"], tz)  # local wall-clock
    sunset  = datetime.fromtimestamp(cur["sunset"], tz)
    return sunrise.strftime("%H:%M"), sunset.strftime("%H:%M")
```

### Wind direction → compass (wind)
```python
# Source: One Call 3.0 (current.wind_deg is meteorological degrees). Pure helper, no dep.
_COMPASS = ("N","NNE","NE","ENE","E","ESE","SE","SSE",
            "S","SSW","SW","WSW","W","WNW","NW","NNW")
def compass(deg: float) -> str:
    return _COMPASS[int((deg + 11.25) // 22.5) % 16]
# forecast already exposes wind_display (speed + units); append compass(current["wind_deg"]).
```

### next-cloudy hybrid (hourly near-term + daily 3–8, daytime-weighted, configurable)
```python
# Source: One Call 3.0 (hourly[].clouds, daily[].clouds, daily[].sunrise/sunset all %/Unix).
# REQUIRES the exclude widening (Pitfall 1) so hourly[] is present.
def next_cloudy(forecast, location, threshold: int):  # threshold default 60 (config)
    tz = ZoneInfo(location.timezone)
    raw = forecast.raw_onecall_imp
    # Near term: hourly buckets in the next ~48h, DAYTIME only (D-03), first >= threshold.
    for h in raw.get("hourly", []):
        t = datetime.fromtimestamp(h["dt"], tz)
        if _is_daytime(t, raw) and h.get("clouds", 0) >= threshold:
            return t                         # first cloudy daytime hour
    # Days 3–8: daytime-weighted daily clouds (daily[].clouds is already a day aggregate).
    for d in raw.get("daily", [])[2:]:       # skip today/tomorrow covered by hourly
        if d.get("clouds", 0) >= threshold:
            return datetime.fromtimestamp(d["dt"], tz)
    return None                              # "no cloudy day in the next N days" (D-03)
```
*(`_is_daytime` compares against `daily[].sunrise/sunset`; D-05 of CONTEXT notes the daytime-window derivation should be reusable with Phases 14/15. For Phase 12, a `daily[].sunrise/sunset` lookup or a simple fixed window is acceptable per CONTEXT D-05.)*

### Next-fire-time read for status (reuse the announce logic)
```python
# Source: daemon.py:_announce_schedule (lines 715-724) — extract into a read-only helper.
def next_fire(job, tz):
    nr = getattr(job, "next_run_time", None)
    if nr is None:                                  # pending/not-started scheduler
        nr = job.trigger.get_next_fire_time(None, datetime.now(tz))
    return nr
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single hard-coded `parse_weather_command` keyword | Registry-driven multi-command parse | This phase | `help` auto-generates; CLI + Discord derive from one list |
| `exclude=minutely,hourly` (v1.0 payload trim) | `exclude=minutely` (keep hourly) | This phase | Enables `next-cloudy` near-term precision; tiny payload growth |
| Heartbeat/health rows write-only | Add read-only readers | This phase | `status` can report last-briefing + liveness |

**Deprecated/outdated:**
- **CLAUDE.md "Jinja2 3.1.x" row** — the project never adopted Jinja2; it uses a custom injection-safe `{name}` renderer (`templates/renderer.py`). Do NOT introduce Jinja2 for command output; render via the existing seam or build embeds/plain text directly.
- **CLAUDE.md "cachetools 6.x" / "2.5 forecast bucket aggregation"** — installed cachetools is **7.1.4**; the 2.5 endpoint + 3-hour bucket logic was retired in Plan 02-01 (the project is on One Call 3.0 `daily`).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Widening `exclude` to keep `hourly` stays within free-tier limits and httpx 10s timeout | Pitfall 1 | LOW — one call/briefing, hourly adds ~48 small objects; well under quota |
| A2 | `daily[].clouds` is a single daytime-representative aggregate suitable for the days-3–8 half of `next-cloudy` | next-cloudy example | MEDIUM — if the user wants strict daytime-weighting on the daily half too, may need per-day daytime reasoning; CONTEXT D-05 explicitly permits a simpler daily approach for Phase 12 |
| A3 | The cloud threshold is a single GLOBAL knob (CONTEXT D-03 says "a single knob"), not per-location | Pitfall 6 | LOW — CONTEXT D-03 is explicit ("global config, a single knob") |
| A4 | `status` should report the UV monitor as absent/not-running until Phase 15 lands | Pattern 3 | LOW — Phase 15 doesn't exist yet; CONTEXT D-02 says "once Phase 15 lands" |
| A5 | Process `started_at` for uptime is captured in `run_daemon` (no existing start-time record) | Pattern 3 / Pitfall 2 | LOW — daemon controls its own lifecycle; capture at start |

**If this table looks small:** the One Call field shapes, version pins, code seams, and guard-ladder behavior were all VERIFIED against the live code / `uv.lock` / One Call 3.0 docs — only the items above rest on judgment the planner/user should confirm.

## Open Questions

1. **Where does the cloud-threshold knob live in the schema?**
   - What we know: CONTEXT D-03 says global, single knob, default 60%, editable via the existing reload path.
   - What's unclear: a top-level `Config.cloud_threshold: int = 60` vs a `[commands]`/`[next_cloudy]` sub-table. Either satisfies `extra="forbid"` + reload.
   - Recommendation: a small frozen sub-model (room to grow other command knobs) OR a single top-level field; planner to pick. Must have a default so existing configs load unchanged.

2. **How is `DaemonState` shaped — object vs. injected primitives?**
   - What we know: `status` needs scheduler, db_path, started_at, bot_alive, (later) monitor state; the bot currently takes only `holder`/`operator_id`/`cache`.
   - What's unclear: pass a single frozen `DaemonState` accessor vs. extend `BotThread.__init__`/`build_on_message` with the extra params.
   - Recommendation: a single read-only accessor object threaded alongside `cache` keeps the signatures clean and gives Phase 15's monitor a clean slot. Planner decides; keep it read-only.

3. **Do CLI subcommands need the guard ladder?**
   - What we know: the ladder is Discord-specific (drops other bots / non-operators). The CLI runs as the operator in their own terminal.
   - What's unclear: CMD-16 says "same guard ladder"; for the CLI the equivalent is "no remote actor exists."
   - Recommendation: CLI subcommands inherit the *registry + read-only + failure-isolation* guarantees but not the Discord-author guards (there is no author). Document this as the CLI's equivalent of the ladder. Confirm with planner that this satisfies CMD-16's intent.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| OpenWeather One Call 3.0 | all weather views | ✓ (live in prod) | 3.0 | — (read-only, reuses existing fetch) |
| discord.py | Discord dispatch | ✓ | 2.7.1 | — |
| APScheduler | status next-fire | ✓ | 3.11.2 | — |
| Running daemon (live service) | status (scheduler/db/start-time) | ✓ on host `yahir-mint` | n/a | UAT/ops touch a LIVE daemon — needs restart to load new modules (MEMORY.md) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none. (Note: the research-host `.venv` is partially populated; production runs an editable install — versions confirmed from `uv.lock`.)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (+ time-machine 2.16 for clock control) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=tests, pythonpath=.) |
| Quick run command | `uv run pytest tests/test_command.py tests/test_bot.py -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CMD-09 | `help` auto-generated from registry, grouped, one-line, same both surfaces | unit | `uv run pytest tests/test_registry.py -k help` | ❌ Wave 0 (`test_registry.py`) |
| CMD-10 | `alerts <loc>` reads `alerts[]` from payload | unit | `uv run pytest tests/test_command_views.py -k alerts` | ❌ Wave 0 |
| CMD-11 | `locations` lists configured names (no fetch) | unit | `uv run pytest tests/test_command_views.py -k locations` | ❌ Wave 0 |
| CMD-12 | `status` reports next-send/uptime/liveness/last-briefing (read-only) | unit | `uv run pytest tests/test_status.py` | ❌ Wave 0 |
| CMD-13 | `sun <loc>` sunrise/sunset local time | unit | `uv run pytest tests/test_command_views.py -k sun` | ❌ Wave 0 |
| CMD-14 | `wind <loc>` speed + compass direction | unit | `uv run pytest tests/test_command_views.py -k wind` | ❌ Wave 0 |
| CMD-15 | `next-cloudy <loc>` hybrid hourly+daily, configurable threshold | unit | `uv run pytest tests/test_command_views.py -k cloudy` | ❌ Wave 0 |
| CMD-16 | guard ladder + failure isolation for every command; zero store writes | unit | `uv run pytest tests/test_bot.py -k "ladder or isolation"` + zero-write spy | ⚠️ extend `tests/test_bot.py` + Phase-6 zero-store-write spy |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_registry.py tests/test_command.py -x`
- **Per wave merge:** `uv run pytest tests/test_bot.py tests/test_command_views.py tests/test_status.py tests/test_cli.py`
- **Phase gate:** `uv run pytest` (full suite green) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_registry.py` — covers CMD-09 (help auto-generation + grouping; registry/CLI/Discord derive-from-one-list invariant)
- [ ] `tests/test_command_views.py` — covers CMD-10/13/14/15 (payload-reading handlers; extend with `next-cloudy` threshold + hourly-present cases)
- [ ] `tests/test_status.py` — covers CMD-12 (DaemonState read: next-fire, uptime, liveness, last-briefing via new `read_heartbeat`)
- [ ] Extend `tests/test_bot.py` — registry-driven dispatch keeps the guard ladder + non-propagating isolation (CMD-16)
- [ ] Extend the Phase-6 zero-store-writes spy to cover every new handler (SC#5 / D-06)
- [ ] `tests/test_store.py` — add `read_heartbeat`/`read_health` reader tests
- [ ] `tests/test_client.py` — assert the widened `exclude` keeps `hourly` (and still trims `minutely`)

## Security Domain

> `security_enforcement: true`, ASVS level 1, block-on high.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth; bot token unchanged (secret on `Settings`) |
| V3 Session Management | no | No sessions |
| V4 Access Control | yes | The operator-id guard ladder (bot.py) is the access control; every new command reuses it verbatim (CMD-16). CLI = local operator. |
| V5 Input Validation | yes | Command text parsed by the pure word-boundary parser (no `str.format`/`eval`); location names resolved via `resolve_location`; `{name}` renderer is injection-safe |
| V6 Cryptography | no | No crypto introduced |
| V7 Error Handling/Logging | yes | Outcome-only logging (no `appid`/webhook/token in logs — existing T-04-01 discipline); non-propagating handler; secrets never in `UnknownLocationError` |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Command-injection via template/format string in a reply | Tampering | Use the existing injection-safe `{name}` regex renderer or build embeds/plain text directly; never `str.format` user text (house rule, renderer.py) |
| Discord feedback loop (bot answering its own/other bots' messages) | DoS | Guard-ladder step 1 (`author.bot`) + word-boundary parse guard — unchanged, reused for all commands |
| Non-operator issuing commands | Elevation of Privilege | Guard-ladder step 2 (`author.id != operator_id`) — silently dropped |
| Secret leakage in a command reply or log (`appid`/webhook/token) | Information Disclosure | `UnknownLocationError` never carries secrets (lookup.py:52); httpx URL logging suppressed (client.py:39); status reports state only, never config secrets |
| `@everyone`/mention injection in a reply | Tampering | Fixed-literal / field-structured replies; no user text interpolated into mentionable content (existing emit_online discipline) |
| A command failure stalling/dropping a briefing | DoS / availability | CMD-16 failure isolation: whole dispatch inside the non-propagating try/except; handlers off the event loop |

## Sources

### Primary (HIGH confidence)
- Installed codebase (read in full this session): `interactive/{command,bot,lookup,cache,__init__}.py`, `scheduler/daemon.py`, `weather/{models,client,store}.py`, `config/{models,loader}.py`, `cli.py`, `templates/renderer.py`, `branding.py`
- `uv.lock` — authoritative installed versions (discord.py 2.7.1, apscheduler 3.11.2, httpx 0.28.1, cachetools 7.1.4, pydantic 2.13.4, pydantic-settings 2.14.1, structlog 26.1.0, tenacity 9.1.4, watchfiles 1.2.0)
- `.planning/phases/12-.../12-CONTEXT.md` (locked decisions D-01..D-05), `.planning/REQUIREMENTS.md` (CMD-09..16), `.planning/ROADMAP.md` (Phase 12 success criteria), `.planning/STATE.md`
- https://openweathermap.org/api/one-call-3 — One Call 3.0 response field shapes (current/hourly/daily sunrise/sunset/clouds/wind_deg/uvi/pop, alerts[], exclude values). HIGH

### Secondary (MEDIUM confidence)
- CLAUDE.md stack table — used for context; corrected where it drifts from installed reality (Jinja2 unused, cachetools 7.x)

### Tertiary (LOW confidence)
- none — all load-bearing claims verified against code or official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — read from `uv.lock` + pyproject; no new deps
- Architecture: HIGH — every seam (registry parse, guard ladder, cache, lookup, scheduler introspection, store) read directly from source
- Pitfalls: HIGH — `exclude=minutely,hourly` (client.py:58), missing heartbeat readers (store.py), and the bot layer's missing scheduler/db handles (bot.py `__init__`) all confirmed in code
- One Call field shapes: HIGH — confirmed against official One Call 3.0 docs

**Research date:** 2026-06-18
**Valid until:** ~2026-07-18 (stable internal codebase; One Call 3.0 field shapes stable). Re-verify `uv.lock` versions if dependencies are bumped before planning.
