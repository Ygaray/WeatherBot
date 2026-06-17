# Phase 11: Discord Inbound Gateway Bot - Pattern Map

**Mapped:** 2026-06-16
**Files analyzed:** 8 (3 new, 5 modified/extended)
**Analogs found:** 8 / 8 (every file has a strong in-tree analog)

> The RESEARCH.md skeletons (Patterns 1–6) are copy-ready and verified against the live
> tree. This PATTERNS.md ties each new/modified file to the **existing** file the planner
> should copy house-style from (imports, docstring voice, guard ordering, frozen-model
> conventions, channel-guard idiom). Prefer the in-tree analog for *style*; use the
> RESEARCH skeleton for the *discord.py-specific mechanics* it adds.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/interactive/bot.py` (NEW) | service / gateway handler | event-driven (gateway → `on_message`) | `weatherbot/scheduler/daemon.py` (`fire_slot`/`_run_watch_observer` threaded handler + non-propagating try/except) + `weatherbot/interactive/lookup.py` (module voice) | role-match |
| `weatherbot/interactive/cache.py` (NEW) | utility / cache | transform (wrap sync `lookup_weather` with TTL) | `weatherbot/config/holder.py` (lock-guarded shared state) + `weatherbot/interactive/lookup.py` (the wrapped core) | role-match |
| `weatherbot/scheduler/daemon.py` (EDIT: bot thread lifecycle) | service / lifecycle | event-driven | itself — the `weatherbot-filewatch` thread block (lines 1078–1102 start, 1186–1194 teardown) | exact (self-template) |
| `weatherbot/scheduler/daemon.py` (EDIT: CFG-07 reload post) | service / lifecycle | request-response | itself — `emit_online` `channel.send` guard (lines 813–821) + `_do_reload` success/reject branches (lines 593, 637–646) | exact (self-template) |
| `weatherbot/config/models.py` (EDIT: `BotConfig`) | model / config | CRUD (load-time validate) | `weatherbot/config/models.py` (`ReloadConfig` / `WebhookIdentity` frozen models) | exact (self-template) |
| `weatherbot/config/settings.py` (EDIT: `discord_bot_token`) | config / secrets | CRUD (env load) | `weatherbot/config/settings.py` (`openweather_api_key` / `discord_webhook_url` fields) | exact (self-template) |
| `tests/test_bot.py` (NEW) | test | event-driven | existing `tests/` (AsyncMock fixtures per RESEARCH Validation Architecture) | role-match |
| `tests/test_cache.py` (NEW) | test | transform | existing `tests/` (counting-spy + time-machine) | role-match |

## Pattern Assignments

### `weatherbot/interactive/bot.py` (service, event-driven) — NEW

**Analogs:** `weatherbot/interactive/lookup.py` (module docstring voice, `from __future__`,
`structlog` logger), `weatherbot/scheduler/daemon.py` (the non-propagating handler + the
threaded-lifecycle idiom).

**Imports / module-header pattern** — copy from `lookup.py:23–41`:
```python
from __future__ import annotations

import structlog

from weatherbot.config import resolve_location          # used inside cache, mirrored here
from weatherbot.interactive.command import CommandKind, parse_weather_command  # D-03
from weatherbot.interactive.lookup import UnknownLocationError  # D-03 error path

_log = structlog.get_logger(__name__)
```
House style: `structlog.get_logger(__name__)` (NOT stdlib `logging`) is the established
bot/handler logger — every interactive + scheduler module uses it (`lookup.py:41`,
`command.py` is pure/no-logger, daemon uses `_log = structlog...`).

**Core `on_message` guard ladder** — use RESEARCH Pattern 2 skeleton verbatim; the guard
ORDER is the load-bearing part (D-04 → D-05 → `!` → parser → executor). The existing
`parse_weather_command` (command.py:50–70) is the reused parser — feed it `content[1:]`
after stripping `!` (D-03). Bare `!weather` → `CommandKind.DEFAULT` → `name = None` →
`lookup_weather` resolves the default location.

**Non-propagating handler pattern** — mirror the daemon's reload-swallow idiom
(`daemon.py:1164–1169`), which is the in-tree precedent for "a failure here must never
crash the always-on process":
```python
except Exception:  # noqa: BLE001 — D-11: log + error reply, NEVER propagate
    _log.exception("discord on_message handler error")
```
The `# noqa: BLE001` + `_log.exception(...)` + swallow shape is exactly how `daemon.py`
guards `_do_reload` (line 1164) and how `BotThread._run` should guard the thread body.

**Embed builder (`build_inbound_embed`)** — mirror `DiscordWebhookChannel.send_briefing`
(`channels/discord.py:54–70`) field-for-field, but with `discord.Embed` (gateway lib) NOT
`DiscordEmbed` (webhook lib). The EXACT live fields to reproduce (D-07 visual parity):
```python
# channels/discord.py:60-69 — the canonical embed shape to mirror:
embed = DiscordEmbed(title=f"Weather — {forecast.location}", color="03b2f8")
embed.add_embed_field(name="Now", value=forecast.temp_display)
embed.add_embed_field(name="High / Low",
                      value=f"{forecast.high_display} / {forecast.low_display}")
embed.add_embed_field(name="Rain", value=f"{forecast.rain_chance}%")
embed.set_timestamp()
```
Note the existing color is the STRING `"03b2f8"` (webhook lib) — the discord.py mirror
uses the int `0x03b2f8` (RESEARCH Pattern 3). `Forecast` exposes `.location`,
`.temp_display`, `.high_display`, `.low_display`, `.rain_chance` (verified
`weather/models.py:102,235,249,256,122`).

**Typing indicator (D-08)** + `run_in_executor` (D-10): RESEARCH Pattern 2 skeleton.

---

### `weatherbot/interactive/cache.py` (utility, transform) — NEW

**Analog:** `weatherbot/config/holder.py` — the in-tree precedent for "shared mutable state
behind a `threading.Lock` with a documented concurrency contract."

**Lock-guarded shared-state pattern** — copy `holder.py`'s structure: a class owning the
state + a `threading.Lock`, a short method that takes the lock only around the mutation,
and a module docstring spelling out the concurrency contract (`holder.py:1–27`). The Lock
is held ONLY around the dict get/set, NEVER across the network fetch (RESEARCH Pattern 4
"Lock + executor note"):
```python
import threading
from cachetools import TTLCache
from weatherbot.config import resolve_location          # raises UnknownLocationError
from weatherbot.interactive.lookup import lookup_weather

class ForecastCache:
    def __init__(self, *, settings, ttl_seconds: int = 600, maxsize: int = 16):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)
        self._lock = threading.Lock()
        self._settings = settings

    def lookup(self, name, config):  # SYNC — always called via run_in_executor (D-10)
        key = resolve_location(config, name).id   # UnknownLocationError bubbles (good)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return hit
        result = lookup_weather(name, config=config, settings=self._settings)
        with self._lock:
            self._cache[key] = result
        return result
```

**Key choice** — key on `resolve_location(config, name).id`. The `.id` field is the stable
sent-log identity that defaults to the raw `name` (`config/models.py:96–118`
`_default_id_from_name`), so `!weather home` / `!weather Home` / bare-default collapse to
one entry. `resolve_location` lives at `config/loader.py:40` and is re-exported from
`weatherbot.config`; it raises `UnknownLocationError` (`lookup.py:44–60`) — let it bubble.

**Invalidation hook** — `invalidate()` clears under the lock (mirror `holder.replace`'s
lock-guarded write); wire into `_do_reload`'s success branch (Discretion / Q2 — leave the
scheduler-read seam unwired for now).

---

### `weatherbot/scheduler/daemon.py` — EDIT 1: bot-thread lifecycle (service, event-driven)

**Analog (self-template):** the `weatherbot-filewatch` thread block in `run_daemon`.

**Start site** — mirror `daemon.py:1078–1102`. Construct the `ForecastCache` next to
`holder`/`channel`/`stop` (`daemon.py:1004–1009`), then build + start the bot thread AFTER
`scheduler.start()` + `emit_online()` (`daemon.py:1120–1131`) so a bot failure can never
delay or gate the online signal (CMD-08 / Pitfall 4). Guard exactly like the filewatch
thread does (`if config.bot is not None and settings is not None:`), mirroring the
`if config.reload.watch and config_path is not None:` guard at line 1080:
```python
# mirror daemon.py:1091-1098 (thread construction + start, daemon=True, named):
watch_thread = threading.Thread(
    target=_run_watch_observer,
    args=(watch_dirs_ref, request_reload, stop),
    name="weatherbot-filewatch",
    daemon=True,
)
watch_thread.start()
```
The bot thread is `name="weatherbot-discord"`, `daemon=True` (RESEARCH `BotThread`).

**Teardown site** — mirror the filewatch teardown in the SAME `finally`
(`daemon.py:1186–1194`): `stop.set()` is already idempotent there; add `bot.stop()` (which
cross-thread schedules `client.close()` via `run_coroutine_threadsafe` — RESEARCH Pattern 1)
ALONGSIDE `watch_thread.join(...)`, with the same "log if it didn't stop within join
timeout" diagnostic (lines 1193–1194):
```python
# mirror daemon.py:1186-1194 — join in the same finally, warn on timeout:
if watch_thread is not None:
    stop.set()
    watch_thread.join(timeout=2.0)
    if watch_thread.is_alive():
        _log.warning("file-watch observer did not stop within join timeout")
```

**Signal handlers stay on the main thread** — `daemon.py:1052` (`signal.signal(SIGTERM)`)
and `1057` (`SIGHUP`) are UNCHANGED. The bot uses `asyncio.run(client.start(token))` (NOT
`client.run()`) precisely so it never installs signal handlers off-main-thread (RESEARCH
Pattern 1 / Anti-Patterns). The bot thread NEVER calls `emit_online` / touches
`notifier.ready()` (`daemon.py:1126`).

---

### `weatherbot/scheduler/daemon.py` — EDIT 2: CFG-07 reload-outcome post (service, request-response)

**Analog (self-template):** `emit_online`'s `channel.send` guard idiom + the two existing
`_do_reload` branches that already carry the structured outcome.

**Channel-guard idiom** — copy `emit_online` (`daemon.py:813–821`): guard `if channel is
not None`, send, and treat the result as best-effort (a non-ok / raising send is logged,
never allowed to abort the surrounding operation):
```python
# daemon.py:813-821 — the exact channel.send best-effort guard to mirror:
if channel is not None:
    result = channel.send("WeatherBot online — startup self-check passed.")
    if result is not None and not getattr(result, "ok", True):
        _log.warning("online ping not delivered", detail=getattr(result, "detail", ""))
```

**Success post site** — `_do_reload` already computes the tuple and builds `summary` at
`daemon.py:637`. Add the post immediately after (capture the tuple/`summary`, D-13 — do
NOT scrape `_stdlog.info("reload applied %s", summary)` at line 646):
```python
# after daemon.py:637  summary = f"+{added} -{removed} ~{changed} ={unchanged}"
if channel is not None:
    channel.send(f"✅ config reloaded: {summary}")   # plain text, distinct from briefing embed (D-13)
```

**Rejection post site** — inside the PHASE-1 except block, after the existing
`_log.error("reload rejected", reason=str(exc))` (`daemon.py:593`):
```python
# after daemon.py:593, inside the except block, BEFORE `raise`:
if channel is not None:
    channel.send(f"⛔ config reload rejected: {exc}")
```
`_do_reload` already receives `channel` as a parameter (`daemon.py:558`) and both
file-watch and SIGHUP/CLI reloads funnel through this one function on the main poll-loop
thread (`daemon.py:1153`), so a single pair of post sites covers all triggers (D-13). A
`channel.send` failure here must be swallowed/logged — never abort the (already
succeeded/failed) reload.

---

### `weatherbot/config/models.py` — EDIT: `BotConfig` (model, CRUD)

**Analog (self-template):** `ReloadConfig` (`models.py:230–245`) and `WebhookIdentity`
(`models.py:138–147`) — both frozen, `extra="forbid"`, optional-with-default config
sub-models.

**Frozen-model house style** — copy the `model_config` line verbatim and the
optional-on-`Config` wiring:
```python
# mirror ReloadConfig (models.py:243) / WebhookIdentity (models.py:144):
class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operator_id: int          # Discord user ID — non-secret identity (D-06)
```
Wire onto `Config` (`models.py:248–261`) as OPTIONAL so a `[bot]`-less config loads
unchanged (mirror how `webhook`/`reliability`/`reload` are added with defaults at
`models.py:259–261`):
```python
class Config(BaseModel):
    ...
    bot: BotConfig | None = None   # no [bot] table = inbound bot disabled
```
Use `bot: BotConfig | None = None` (not `Field(default_factory=...)`) because absence MUST
mean "no bot," not "a default bot with no operator." `extra="forbid"` preserves the v1
fail-closed-on-unknown-key posture (`models.py:255`). RESEARCH Pattern 5 recommends a
single `operator_id: int`, NOT a list (single-user tool; A3).

---

### `weatherbot/config/settings.py` — EDIT: `discord_bot_token` (config, CRUD/secrets)

**Analog (self-template):** the two existing secret fields (`settings.py:28–29`).

**Secret-field pattern** — append one field next to the existing two; the `Settings`
class + `SettingsConfigDict(env_file=".env", extra="ignore")` are unchanged
(`settings.py:22–26`). `extra="ignore"` already tolerates unrelated host env vars:
```python
# settings.py:28-29 — add the new required secret here:
openweather_api_key: str
discord_webhook_url: str
discord_bot_token: str         # NEW required secret (D-14), fail-loud if missing
```
The field name maps case-insensitively to `DISCORD_BOT_TOKEN` (pydantic-settings, per the
class docstring `settings.py:18–20`). `load_settings()` (`config/loader.py`) is the
fail-loud point — a missing token raises `ValidationError` at startup. **Open Question Q1
(A4):** if the operator wants the bot strictly optional, make it `str | None = None`
instead — surface in planning.

---

### `tests/test_bot.py` / `tests/test_cache.py` (test) — NEW

**Analog:** existing `tests/` suite (pytest + `time-machine`, already present per RESEARCH
Validation Architecture). No live gateway — call `on_message(fake_message)` directly with
`AsyncMock` channel + configurable `author` (RESEARCH "How to test a discord.py handler").
Add a `fake_discord_message` factory to `tests/conftest.py`. CMD-06 cache test uses a
counting spy on `lookup_weather` + `time-machine` to cross the TTL.

## Shared Patterns

### Structured logging
**Source:** every interactive/scheduler module — `_log = structlog.get_logger(__name__)`
(`lookup.py:41`, daemon's `_log`).
**Apply to:** `bot.py`, `cache.py`. NEVER bare `print`; CLAUDE.md mandates structlog.
Outcome-only fields, NEVER the token/webhook URL (`channels/discord.py:34` raises the
`discord_webhook` logger to WARNING for exactly this reason; the bot's logs must stay
token-free).

### Non-propagating failure isolation
**Source:** `daemon.py:1164–1169` (reload swallow) — the in-tree precedent for "a failure
in a non-critical path must never crash the always-on process."
**Apply to:** `bot.py` `on_message` body (D-11) AND `BotThread._run` (catch
`discord.LoginFailure` + bare `Exception`, log CRITICAL, die alone). Pattern shape:
`except Exception:  # noqa: BLE001` → `_log.exception(...)` → no re-raise.

### Lock-guarded shared state
**Source:** `config/holder.py` (whole file) — class owning state + `threading.Lock`,
documented concurrency contract, lock held only around the mutation.
**Apply to:** `cache.py` `ForecastCache` (Lock around dict get/set only, never across the
fetch).

### Best-effort `channel.send` guard
**Source:** `emit_online` (`daemon.py:813–821`).
**Apply to:** the CFG-07 reload-outcome posts — `if channel is not None`, send, log a
non-ok / raising result, never abort the surrounding operation.

### Frozen `extra="forbid"` config models
**Source:** `ReloadConfig` / `WebhookIdentity` / `Location` (`models.py`) — all use
`model_config = ConfigDict(extra="forbid", frozen=True)`.
**Apply to:** `BotConfig`. Optional-on-`Config` so absence disables the feature.

### Secrets stay in `.env`, identity in `config.toml`
**Source:** `settings.py` (secrets) vs `models.py` (non-secret structure) — the CONF-02
split (`settings.py:1–7`, `models.py:1–6`).
**Apply to:** token → `Settings.discord_bot_token` (D-14); `operator_id` → `BotConfig`
(D-06). NEVER the token in `config.toml` or the holder.

## No Analog Found

None. Every new file maps to a strong in-tree analog. The only genuinely NEW mechanics —
the discord.py gateway lifecycle (`asyncio.run(client.start())` on a thread + cross-thread
`client.close()`) and the `cachetools.TTLCache` itself — are library mechanics with no
prior in-tree code; for those the planner uses the verified RESEARCH.md Patterns 1 and 4
skeletons (which are already grounded in the live tree's thread/holder idioms). discord.py
and cachetools are not yet installed — `uv add 'discord.py>=2.7.1' cachetools` (RESEARCH
Standard Stack; gate behind the human-verify ack, A1).

## Metadata

**Analog search scope:** `weatherbot/interactive/`, `weatherbot/scheduler/`,
`weatherbot/channels/`, `weatherbot/config/`, `weatherbot/weather/`
**Files scanned (read in full or targeted):** `channels/discord.py`, `config/settings.py`,
`config/models.py`, `interactive/lookup.py`, `interactive/command.py`, `config/holder.py`,
`scheduler/daemon.py` (`_reconcile_jobs` / `_do_reload` / `emit_online` / `run_daemon`
lifecycle sections), `weather/models.py` (display fields, grep), `config/loader.py`
(`resolve_location`, grep)
**Pattern extraction date:** 2026-06-16
