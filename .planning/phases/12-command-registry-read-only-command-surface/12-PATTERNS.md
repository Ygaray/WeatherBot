# Phase 12: Command Registry & Read-Only Command Surface - Pattern Map

**Mapped:** 2026-06-18
**Files analyzed:** 14 (8 new, 6 modified)
**Analogs found:** 13 / 14 (1 partial — `next-cloudy` derivation has no in-repo analog)

> This is a **brownfield wiring phase**. Every new file copies an existing in-repo
> pattern almost verbatim. The analogs below are real, current, and load-bearing —
> prefer them over the RESEARCH.md code sketches (which are illustrative). RESEARCH.md
> is authoritative only for the One Call 3.0 field shapes and the `next-cloudy` algorithm.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/interactive/registry.py` (NEW) | config/registry | transform (spec→dispatch) | `weatherbot/interactive/command.py` (frozen dataclass + module-level constant) | role-match |
| `weatherbot/interactive/command.py` (MOD) | utility/parser | transform (text→spec) | itself — generalize `parse_weather_command` in place | exact (self) |
| `weatherbot/interactive/commands/weather_views.py` (NEW: alerts/sun/wind/next-cloudy) | handler/view | transform (Forecast→reply) | `weatherbot/interactive/bot.py:build_inbound_embed` + `Forecast` payload reads | role-match |
| `weatherbot/interactive/commands/info.py` (NEW: help/locations) | handler/view | transform (registry/config→reply) | `weatherbot/interactive/bot.py:build_inbound_embed` | partial |
| `weatherbot/interactive/commands/status.py` (NEW) | handler/view | event-driven (live state→reply) | `weatherbot/scheduler/daemon.py:_announce_schedule` + `bot.py:is_alive` | role-match |
| `weatherbot/interactive/bot.py` (MOD: registry dispatch) | controller | request-response | itself — guard ladder in `build_on_message` | exact (self) |
| `weatherbot/interactive/cache.py` (MOD: optional generic entry) | service/cache | CRUD (TTL) | itself — `ForecastCache.lookup` | exact (self) |
| `weatherbot/weather/client.py` (MOD: widen `exclude`) | service/client | request-response (HTTP) | itself — `fetch_onecall` line 58 | exact (self) |
| `weatherbot/weather/store.py` (MOD: `read_heartbeat`/`read_health`) | service/store | CRUD (read) | `store.py:was_sent` (read shape) + `stamp_success`/`stamp_health` (row identity) | exact (self) |
| `weatherbot/config/models.py` (MOD: cloud-threshold knob) | model/config | n/a | `models.py:Reliability` (validated knob w/ default) + `BotConfig` (optional sub-model) | role-match |
| `weatherbot/cli.py` (MOD: registry-driven subparsers) | route/CLI | request-response | `cli.py:main` `add_subparsers` (~line 593) | exact (self) |
| `tests/test_registry.py` (NEW) | test | n/a | `tests/test_command.py` (pure parser matrix) | role-match |
| `tests/test_command_views.py` (NEW) | test | n/a | `tests/test_bot.py` + fixture-driven `Forecast` tests | role-match |
| `tests/test_status.py` (NEW) | test | n/a | `tests/test_store.py` + fake-scheduler patterns | role-match |

## Pattern Assignments

### `weatherbot/interactive/registry.py` (NEW — the single source of truth)

**Analog:** `weatherbot/interactive/command.py` (frozen dataclass house style) + `weatherbot/interactive/lookup.py:LookupResult`

**Frozen-dataclass + module-constant pattern** (`command.py:38-48` and `:22`):
```python
_KEYWORD = "weather"          # module-level constant source of truth

@dataclass(frozen=True)
class Command:
    kind: CommandKind
    location: str | None = None
```
Copy this shape for `CommandSpec` (frozen dataclass) and `COMMANDS: tuple[CommandSpec, ...]` (immutable module constant). Build the `BY_NAME` / longest-keyword-first index as module-level derived constants, exactly as RESEARCH Pattern 1 sketches. The `from __future__ import annotations` + `from dataclasses import dataclass` header (`command.py:17-19`) is the house import block.

**Why a tuple, not a list:** mirrors `Config.locations` being immutable-friendly and the frozen-model discipline across the config layer.

---

### `weatherbot/interactive/command.py` (MODIFY — generalize the parser in place)

**Analog:** itself — `parse_weather_command` (lines 50-70).

**Word-boundary guard to PRESERVE verbatim** (lines 57-69) — this is the anti-feedback-loop guard (T-06-02); generalizing it is Pitfall 4:
```python
stripped = text.strip()
if not stripped.casefold().startswith(_KEYWORD):
    return Command(CommandKind.NOT_A_COMMAND)
rest = stripped[len(_KEYWORD):]
# Word-boundary guard: anything other than whitespace right after the keyword
# (e.g. "weatherman", "weather:") is not the command.
if rest and not rest[0].isspace():
    return Command(CommandKind.NOT_A_COMMAND)
```
Generalize `_KEYWORD` (single) → iterate `COMMANDS` **longest-keyword-first** so `next-cloudy` beats a hypothetical `next` (RESEARCH Pattern 2). Keep the parser **pure** — only `str.strip`/`str.casefold`/slicing, never `str.format`/`eval` (the T-06-01 security contract in the module docstring lines 11-14). Preserve the parse-don't-validate boundary: return a spec + raw arg; do NOT import `Config` or resolve locations here.

---

### `weatherbot/interactive/commands/weather_views.py` (NEW — alerts/sun/wind/next-cloudy)

**Analog:** `weatherbot/interactive/bot.py:build_inbound_embed` (lines 61-81) for the embed shape; `Forecast` raw-payload reads for the data.

**Reading the already-fetched payload (no second fetch)** — `Forecast` retains both raw One Call payloads (`models.py:134-136`):
```python
raw_onecall_imp: dict
raw_onecall_met: dict
```
Handlers receive a `LookupResult` (from `cache.lookup`) and read `result.forecast.raw_onecall_imp`. For `alerts`, mirror the existing `_alert_line` consumer (`models.py:81-95`) but surface fuller per-alert `event`/`start`/`end`/`description`. For `wind`/`sun`/`next-cloudy` use the RESEARCH.md Code Examples (compass table, `ZoneInfo` + `datetime.fromtimestamp`, hybrid hourly+daily) — those are verified against One Call 3.0 docs.

**Embed-build house style to copy** (`bot.py:70-81`):
```python
embed = discord.Embed(title=f"Weather — {forecast.location}", color=BRIEFING_COLOR_INT)
embed.add_field(name="Now", value=forecast.temp_display, inline=True)
embed.timestamp = discord.utils.utcnow()
```
Each handler returns a surface-agnostic reply that the bot renders as `discord.Embed` and the CLI prints as plain text (D-04: same content both surfaces). Use `BRIEFING_COLOR_INT` from `weatherbot.branding` (the gateway lib takes an int — see `bot.py:23`).

**HARD constraint (D-06):** these handlers MUST be store-free. `lookup_weather` already takes no `db_path` and imports nothing from the store (`lookup.py:10-15`); inherit that. Extend the Phase-6 zero-store-writes spy to cover them.

---

### `weatherbot/interactive/commands/info.py` (NEW — help/locations)

**Analog:** `bot.py:build_inbound_embed` (embed assembly) — partial; `help` renders the registry, `locations` reads `config.locations` (no fetch).

`help` iterates `registry.COMMANDS` grouped by `.group`, one `.summary` line each (D-04 auto-generation). `locations` reads the resolved config (`holder.current().locations`) — no `ForecastCache`/fetch. Both return the surface-agnostic reply rendered as embed (Discord) or plain text (CLI). No `Forecast`, no network.

---

### `weatherbot/interactive/commands/status.py` (NEW — the integration seam)

**Analog:** `weatherbot/scheduler/daemon.py:_announce_schedule` (lines 697-731) for next-fire; `bot.py:is_alive` (line 242); new `store.read_heartbeat`.

**Next-fire-time read to extract into a reusable read-only helper** (`daemon.py:719-724`) — RESEARCH says extract this verbatim:
```python
next_run = getattr(job, "next_run_time", None)
if next_run is None:
    next_run = job.trigger.get_next_fire_time(None, datetime.now(tz))
```
**Job-id keying convention to reuse** (`daemon.py:717`): `f"{location.name}|{slot.time}|{slot.days}"`.

**Liveness** — `bot.is_alive()` already exists (`bot.py:242-249`). UV monitor (Phase 15) absent → report "not running" with a clean slot (A4).

**`status` needs four things the bot layer does NOT currently receive** (Pitfall 2): `build_on_message`/`BotThread` take only `holder`, `operator_id`, `cache` (`bot.py:84-89`, `:204-211`). Thread a read-only `DaemonState` accessor (scheduler, db_path, started_at, bot_alive callable) into the registry context alongside `cache`, constructed in `run_daemon` where `cache`/`holder`/`scheduler` already live (`daemon.py:1037-1062`). Capture `started_at = datetime.now(timezone.utc)` at daemon start for uptime (A5). Keep it READ-ONLY (D-02: reports, never mutates).

---

### `weatherbot/interactive/bot.py` (MODIFY — registry dispatch, ladder UNCHANGED)

**Analog:** itself — `build_on_message` (lines 104-150).

**Guard ladder steps (1)-(3) + the non-propagating envelope stay BYTE-FOR-BYTE** (lines 105-148). Only step (4) changes from `parse_weather_command` to the registry-driven `parse_command`:
```python
if message.author.bot:                       # (1) drop bots — UNCHANGED
    return
if message.author.id != operator_id:         # (2) operator-only — UNCHANGED
    return
content = message.content or ""
if not content.startswith("!"):              # (3) ! prefix — UNCHANGED
    return
cmd = parse_weather_command(content[1:])     # (4) → parse_command(registry) — CHANGE HERE
```
**Failure-isolation envelope to keep the WHOLE dispatch inside** (lines 124-148, Pitfall 5 / CMD-16):
```python
try:
    loop = asyncio.get_running_loop()
    config = holder.current()
    async with message.channel.typing():     # D-08 typing indicator
        try:
            result = await loop.run_in_executor(None, cache.lookup, name, config)
        except UnknownLocationError as exc:
            await message.channel.send(str(exc))   # CMD-02 corrective-hint path
            return
        payload = build_inbound_embed(result.forecast)
    await message.channel.send(embed=payload)
except Exception:  # noqa: BLE001 — non-propagating handler (CMD-08, D-11)
    _log.exception("inbound handler failed")
    ...
```
The new dispatch reuses this `run_in_executor` off-loop call and the `UnknownLocationError` sub-except. Do NOT add a second try/except branch (Pitfall 5) — extend the existing one. `operator_id` stays baked at construction (lines 96-101); do not re-read per message.

---

### `weatherbot/weather/client.py` (MODIFY — widen `exclude`, Phase 12 OWNS this seam)

**Analog:** itself — `fetch_onecall` line 58.

**The exact one-line change** (line 58) plus the now-false docstring (lines 44-45):
```python
"exclude": "minutely,hourly",   # CHANGE → "minutely"  (keep hourly for next-cloudy)
```
Docstring line 44 ("Trims the unused `minutely`/`hourly` blocks") must be corrected — it becomes false. `Forecast.from_payloads` reads only `current`/`daily[0]`/`alerts` (`models.py:153-154`), so briefing/render/store paths are untouched. Add the regression-canary test (D-06): assert the parsed payload has a non-empty `hourly[]` (protects Phases 14/15). The secret-hygiene comment (lines 35-39, httpx logger raised to WARNING) and the `_TIMEOUT = 10.0` (line 33) stay unchanged.

---

### `weatherbot/weather/store.py` (MODIFY — add `read_heartbeat`/`read_health`)

**Analog:** `store.py:was_sent` (lines 220-239) for the read shape; `stamp_success` (lines 384-396) for the single-row identity.

**Read-function house pattern to copy** (`was_sent`, lines 232-239):
```python
with sqlite3.connect(db_path) as conn:
    conn.executescript(_SCHEMA)               # idempotent — tolerates uninitialized db
    row = conn.execute(
        "SELECT 1 FROM sent_log WHERE location_name=? AND send_time=? AND local_date=?",
        (location_name, send_time, local_date),   # ? placeholders only (T-03-01 SQLi)
    ).fetchone()
return row is not None
```
`read_heartbeat` SELECTs `last_tick_utc, last_success_utc FROM heartbeat WHERE id=1` (single seeded row, schema lines 129-135); `read_health` SELECTs `reason, detail, updated_at_utc FROM health WHERE id=1` (lines 137-144). Use `?` placeholders, `executescript(_SCHEMA)` on connect, and return the single row (or a default when NULL). Add `tests/test_store.py` cases mirroring the existing reader tests.

---

### `weatherbot/config/models.py` (MODIFY — global cloud-threshold knob)

**Analog:** `models.py:Reliability` (lines 150-227) for a validated knob with a default; `BotConfig` (lines 248-270) for an optional sub-model that loads existing configs unchanged.

**Validated-knob-with-default pattern** (`Reliability`, lines 172-183):
```python
model_config = ConfigDict(extra="forbid", frozen=True)
attempts_per_burst: int = 8                    # field with a default → existing configs load

@field_validator("attempts_per_burst", "burst_spread_seconds", "mid_pause_seconds")
@classmethod
def _must_be_positive(cls, v: int) -> int:
    if v <= 0:
        raise ValueError(f"reliability timing values must be > 0, got {v!r}")
    return v
```
Add `cloud_threshold: int = 60` as a DECLARED field with a default (Pitfall 6 — `extra="forbid"` rejects loose keys; a default keeps existing configs loading). Validate range 0-100 fail-loud at load, in the `Schedule`/`Reliability` tradition. Planner picks top-level `Config` field vs. a frozen `[commands]` sub-model (Open Question 1) — either satisfies `extra="forbid"` + reload. If a sub-model, attach it on `Config` like `reliability: Reliability = Field(default_factory=Reliability)` (line 284).

---

### `weatherbot/cli.py` (MODIFY — registry-driven subparsers)

**Analog:** `cli.py:main` `add_subparsers` block (lines 593-667) + `run_weather`/`_cmd_weather` dispatch (lines 257-346).

**Subparser pattern to generate per spec** (lines 595-611):
```python
subparsers = parser.add_subparsers(dest="command")
p_weather = subparsers.add_parser("weather", parents=[config_parent], help="...")
p_weather.add_argument("location", nargs="?", default=None, help="...")
```
Build one subparser per `registry.COMMANDS` spec; for `takes_location` specs add the `nargs="?", default=None` location arg (mirrors `weather`/`send-now`, lines 600-605 / 649-655). The `config_parent` parent parser (lines 582-587) is attached to every config-loading subcommand. **CLI has no guard ladder** (Open Question 3): the terminal IS the operator; CLI inherits the registry + read-only + failure-isolation guarantees but not the Discord-author guards. Reuse the `_load_config_reporting` → exit-code dispatch shape (`_cmd_weather`, lines 330-346).

## Shared Patterns

### Read-only discipline (D-06 — HARD constraint, applies to EVERY new handler)
**Source:** `weatherbot/interactive/lookup.py` (lines 10-15 docstring; no `db_path` param, no store import)
**Apply to:** all of `commands/weather_views.py`, `commands/info.py`, `commands/status.py`
```python
# HARD CONSTRAINT (D-06): this core is READ-ONLY. It takes no database path, imports
# nothing from the SQLite store package, and writes none of the seven store functions
# — proven by the zero-store-writes spy test.
```
Extend the Phase-6 zero-store-writes spy to cover every new handler (SC#5).

### Failure isolation (CMD-16 — applies to EVERY command)
**Source:** `weatherbot/interactive/bot.py:build_on_message` (lines 124-148)
**Apply to:** the bot dispatch wrapping every registry handler
```python
except Exception:  # noqa: BLE001 — non-propagating handler (CMD-08, D-11)
    _log.exception("inbound handler failed")
    try:
        await message.channel.send(_ERROR_REPLY)
    except Exception:  # noqa: BLE001 — best-effort reply; never re-raise
        _log.exception("inbound error reply failed")
```
A per-command bug must surface as a generic reply, never as a gateway/scheduler crash.

### Off-loop dispatch (D-10 — applies to every fetching command)
**Source:** `weatherbot/interactive/bot.py` (lines 131-134) + `cache.py` lookup contract (lines 82-108)
**Apply to:** alerts/sun/wind/next-cloudy (all ride `cache.lookup` → `lookup_weather`)
```python
result = await loop.run_in_executor(None, cache.lookup, name, config)
```
Network/render is blocking; it must stay off the gateway loop. `ForecastCache.lookup` is reused verbatim — the new commands share the same TTL cache key (`Location.id`).

### Location resolution / default-first (D-01 — applies to location-taking commands)
**Source:** `resolve_location(config, name)` (called in `lookup.py:103`, `cache.py:93`)
**Apply to:** uv/wind/alerts/sun/next-cloudy (None → first/default; raises `UnknownLocationError`)
```python
location = resolve_location(config, name)   # None → default; UnknownLocationError on no-match
```
The `UnknownLocationError` corrective-hint path (`lookup.py:44-60`, carries `.requested` + `.valid_names`) is already the bot's error reply (`bot.py:135-138`) — reuse it; never carry secrets.

### Timezone-local time from Unix ts (sun / next-cloudy daytime window)
**Source:** `weatherbot/interactive/lookup.py:137-138`, `weather/store.py:160-174` (`ZoneInfo` + fallback)
**Apply to:** sun (sunrise/sunset local), next-cloudy (daytime gating)
```python
tz = ZoneInfo(location.timezone)
local = datetime.fromtimestamp(unix_ts, tz)   # location wall-clock; DST-correct
```
Do NOT hand-roll UTC offset math (RESEARCH "Don't Hand-Roll").

### SQLi-safe parameterized SQL (T-03-01 — applies to new store readers)
**Source:** every function in `weatherbot/weather/store.py` (e.g. `was_sent` line 234-238)
**Apply to:** `read_heartbeat`, `read_health`
```python
conn.execute("SELECT ... WHERE id=?", (1,))   # ? placeholders ONLY — never f-string into SQL
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `next-cloudy` derivation (within `commands/weather_views.py`) | handler/view | transform | No existing hybrid hourly+daily cloud-cover logic in repo. Use RESEARCH.md "next-cloudy hybrid" Code Example (verified against One Call 3.0 docs). The *handler shell* (cache.lookup → read raw payload → reply) copies the weather-views analog; only the algorithm body is novel. |

## Metadata

**Analog search scope:** `weatherbot/interactive/`, `weatherbot/weather/`, `weatherbot/config/`, `weatherbot/scheduler/`, `weatherbot/cli.py`, `tests/`, `tests/fixtures/`
**Files scanned:** command.py, lookup.py, cache.py, bot.py, client.py, models.py (weather + config), store.py, daemon.py, cli.py, test_command.py + test-dir/fixture listing
**Pattern extraction date:** 2026-06-18
