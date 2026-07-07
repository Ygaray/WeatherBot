<!-- refreshed: 2026-07-07 -->
# Architecture

**Analysis Date:** 2026-07-07

## System Overview

WeatherBot is a long-running personal weather-briefing daemon and a **consumer** of the
reusable hub library `yahir_reusable_bot`. The app owns weather/domain concepts and all
wiring; the hub owns weather-agnostic mechanism (scheduler engine, reload engine, lifecycle
gate, channel/retry ABCs, Discord gateway plumbing). The load-bearing invariant: **consumers
import from the hub; no hub file imports a consumer.** Every app-specific concern reaches the
hub as an injected closure at the single composition root `weatherbot/scheduler/wiring.py`.

```text
┌─────────────────────────────────────────────────────────────┐
│                     Entry Points (CLI)                       │
│   `weatherbot/__main__.py`  ──►  `weatherbot/cli.py:main`    │
│   subcommands: weather · run · check · send-now · geocode ·  │
│                reload · check-config · registry commands     │
└──────────┬───────────────────────────────────┬──────────────┘
           │ run (daemon)                       │ one-shot (weather/send-now/…)
           ▼                                    ▼
┌──────────────────────────────┐   ┌──────────────────────────────┐
│  Scheduler / Daemon spine    │   │  Composition roots (cli.py)  │
│  `scheduler/daemon.py`       │   │  send_now · run_weather ·    │
│  `scheduler/wiring.py`       │   │  do_check · do_geocode       │
│  (build_runtime injects hub) │   └───────────────┬──────────────┘
└──────────┬───────────────────┘                   │
           │  fire_slot / lookup_weather           │
           ▼                                        ▼
┌─────────────────────────────────────────────────────────────┐
│         Shared read-only core: `interactive/lookup.py`       │
│  resolve_location ► fetch (dual-unit) ► Forecast ► render    │
└──────────┬───────────────────────────┬──────────────────────┘
           ▼                           ▼
┌────────────────────────┐   ┌──────────────────────────────────┐
│  weather/ (fetch,model) │   │  channels/ (deliver)  templates/ │
│  client·models·store·uv │   │  Channel ABC ► Discord webhook   │
└──────────┬─────────────┘   └──────────────────────────────────┘
           ▼
┌─────────────────────────────────────────────────────────────┐
│  SQLite store `weather/store.py` (data/weatherbot.db)        │
│  weather_onecall · sent_log · heartbeat · alerts · health    │
└─────────────────────────────────────────────────────────────┘

        ▲  hub library `yahir_reusable_bot` (imported, never imports app)
        │  config.ReloadEngine · config.ConfigHolder · scheduler.SchedulerEngine
        │  lifecycle.ReadyGate/LifecycleIdentity · channels.Channel/DeliveryResult
        │  reliability.build_retrying · discord.BotThread/PanelKit/build_client
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| CLI dispatch / one-shot roots | Parse subcommands, build client+channel, run pipeline, exit codes | `weatherbot/cli.py` |
| Module entry point | `python -m weatherbot` delegates to `cli.main` | `weatherbot/__main__.py` |
| Daemon spine | Always-on foreground lifecycle, per-slot `fire_slot` callback, SIGTERM/reload/heartbeat | `weatherbot/scheduler/daemon.py` |
| Composition root (daemon) | `build_runtime` / `build_inbound_bot` — wire hub engines with injected closures | `weatherbot/scheduler/wiring.py` |
| Catch-up planner | Plan missed slots inside the 90-min startup grace window | `weatherbot/scheduler/catchup.py` |
| UV monitor | Proactive UV-index alert job | `weatherbot/scheduler/uvmonitor.py` |
| Schedule context | Timezone + intended-vs-actual placeholders for a fire | `weatherbot/scheduler/context.py` |
| Shared read-only core | `lookup_weather` / `lookup_forecast`: resolve → fetch → Forecast → render | `weatherbot/interactive/lookup.py` |
| Command registry + dispatch | Single command list driving CLI subparsers AND Discord panel | `weatherbot/interactive/registry.py`, `dispatch.py` |
| Discord inbound bot | Gateway `on_message` guard ladder, live panel | `weatherbot/interactive/bot.py`, `panel.py`, `commands/` |
| Weather fetch | httpx One Call 3.0 + geocoding client | `weatherbot/weather/client.py` |
| Weather model / aggregation | `Forecast`, 3-hour bucket + multiday aggregation | `weatherbot/weather/models.py`, `multiday.py`, `uv.py` |
| Persistence | Analysis-ready SQLite (weather + liveness rows) | `weatherbot/weather/store.py` |
| Channel seam | App-side `Channel` subclass adding `send_briefing`; Discord webhook impl | `weatherbot/channels/base.py`, `discord.py`, `factory.py` |
| Config | Non-secret pydantic models + TOML loader; secrets via pydantic-settings | `weatherbot/config/models.py`, `loader.py`, `settings.py`, `holder.py` |
| Ops / supervision | systemd sd_notify, PID file guard, classified self-check | `weatherbot/ops/sdnotify.py`, `pidfile.py`, `selfcheck.py` |
| Reliability | Re-export shim over hub two-burst retry contract | `weatherbot/reliability/retry.py`, `__init__.py` |
| Templates | Jinja/`str.format`-style briefing + forecast templates + renderer | `templates/renderer.py`, `templates/*.txt` |

## Pattern Overview

**Overall:** Layered, dependency-injected daemon built on a **hub/consumer (extracted-mechanism)**
split with a **single composition root**.

**Key Characteristics:**
- One read-only fetch→render core (`lookup_weather`) shared by the scheduled path, the CLI, and the Discord bot — surfaces can never drift.
- All hub engines are weather-agnostic; every app specific arrives as an **injected closure** at `wiring.py` (`build_runtime`, `build_inbound_bot`).
- Channel-agnostic delivery seam (`Channel.send(text)`), with provider enrichment (Discord embed) kept internal via `send_briefing`.
- Fail-loud-at-load config validation; outcome-only logging (never the `appid`/webhook URL).
- Recovery owned by the SQLite `sent_log` + catch-up scan, not by APScheduler misfire state.

## Layers

**Entry / CLI layer:**
- Purpose: Parse the subcommand surface, choose a path, own exit codes and logging config.
- Location: `weatherbot/__main__.py`, `weatherbot/cli.py`
- Depends on: composition roots below, config loaders, channel factory, hub `ReloadEngine`/`ConfigHolder` (only for offline `check-config`).

**Composition-root layer:**
- Purpose: The ONE greppable place fetch, persist, render, deliver, and lifecycle wiring meet.
- Location: `cli.py:send_now` (manual pipeline) and `scheduler/wiring.py:build_runtime` (daemon).
- Depends on: hub engines + app closures + channel + client.
- Used by: `run_send_now`/`run_weather` (cli) and `daemon.run_daemon`.

**Daemon / scheduler layer:**
- Purpose: Long-running lifecycle, per-slot delivery, hot-reload, heartbeat, catch-up.
- Location: `weatherbot/scheduler/`
- Depends on: hub `SchedulerEngine`/`ReloadEngine`/`ReadyGate`, `weather/store.py`, the shared core.

**Shared domain core:**
- Purpose: Read-only resolve→fetch→build→render. HARD constraint: no DB writes, no store imports.
- Location: `weatherbot/interactive/lookup.py`
- Used by: send_now, run_weather, CLI registry commands, Discord dispatch.

**Weather + persistence layer:**
- Purpose: Fetch OpenWeather, aggregate buckets into `Forecast`, persist analysis-ready rows.
- Location: `weatherbot/weather/`

**Delivery layer:**
- Purpose: Provider-agnostic send + Discord-specific enrichment.
- Location: `weatherbot/channels/`, `templates/`

## Data Flow

### Primary Request Path (scheduled briefing)

1. APScheduler cron job (or catch-up scan) fires `fire_slot` at the location's IANA wall-clock time (`weatherbot/scheduler/daemon.py`).
2. `fire_slot` atomically claims the slot via `claim_slot` (delivery-level exactly-once) (`weatherbot/weather/store.py`).
3. It threads a `ScheduleContext` into `send_now` (`weatherbot/cli.py:142`).
4. `send_now` delegates the read-only head to `lookup_weather` — resolve → dual-unit One Call fetch → one `Forecast` → render (`weatherbot/interactive/lookup.py`).
5. Delivery via `channel.send_briefing(text, forecast)`; Discord attaches an embed internally (`weatherbot/channels/discord.py`).
6. On success ONLY, the SAME `Forecast` is persisted (no second fetch) via `persist` (`weatherbot/cli.py:217`); a failed send releases the claim so the slot stays re-fireable.

### Manual one-shot path (`send-now` / `weather`)

1. `cli.main` parses subcommand, `_load_config_reporting` validates config (clean exit codes) (`weatherbot/cli.py:569`).
2. `run_send_now` / `run_weather` wrap the single-attempt core in a SHORT bounded tenacity retry (3 attempts) — attended, no alerts/heartbeat rows (`weatherbot/cli.py:236`, `:307`).
3. `weather` prints `LookupResult.text` to stdout only; exit codes 0/1/2/3.

### Daemon startup lifecycle (order-sensitive)

1. `run_daemon` calls `build_runtime` to CONSTRUCT all collaborators (`weatherbot/scheduler/wiring.py:108`).
2. `run_daemon` SEQUENCES the load-bearing order: install SIGTERM handler → write PID file → arm file-watch observer (`finally`) → drive `ReadyGate` → `on_online` runs `scheduler.start()` → `notifier.ready()` (READY=1) reaches systemd STRICTLY after the scheduler is up.
3. Inbound Discord `BotThread` is started only after READY (`build_inbound_bot`, `wiring.py:340`).

**State Management:**
- Live config held in hub `ConfigHolder` (per-tap `holder.current()` snapshots survive hot-reload).
- Durable state in SQLite `data/weatherbot.db` (`sent_log`, `weather_onecall`, heartbeat, alerts, health).

## Key Abstractions

**`Channel` (delivery seam):**
- Purpose: Provider-agnostic `send(text) -> DeliveryResult`; app subclass adds `send_briefing`.
- Examples: `weatherbot/channels/base.py`, `weatherbot/channels/discord.py`.
- Pattern: Registry factory keyed by config `type` (`weatherbot/channels/factory.py`).

**`Forecast` (domain payload):**
- Purpose: One dual-unit forecast carrying both retained One Call payloads for render + persist.
- Examples: `weatherbot/weather/models.py`.

**Command registry (`COMMANDS` / `BY_NAME`):**
- Purpose: ONE command list generates CLI subparsers AND Discord panel buttons (anti-drift).
- Examples: `weatherbot/interactive/registry.py`, dispatched via `weatherbot/interactive/dispatch.py`.

**Hub engines (injected):**
- `ConfigHolder`, `ReloadEngine` (`yahir_reusable_bot.config`); `SchedulerEngine` (`.scheduler`); `ReadyGate`/`LifecycleIdentity` (`.lifecycle`); `Channel`/`DeliveryResult` (`.channels`); `PanelKit`/`BotThread` (`.discord`).

## Entry Points

**`python -m weatherbot`:**
- Location: `weatherbot/__main__.py` → `weatherbot/cli.py:main`.
- Triggers: shell / systemd `ExecStart`.
- Responsibilities: subcommand dispatch, logging config, exit codes.

**`weatherbot` console script:**
- Location: `pyproject.toml [project.scripts]` → `weatherbot.cli:main`.

**`weatherbot run` (daemon):**
- Location: `cli.py:main` → `scheduler.daemon.run_daemon` → `wiring.build_runtime`.
- Triggers: systemd unit `deploy/weatherbot.service`.

## Hub / Consumer Boundary (load-bearing)

- **Direction:** WeatherBot imports `yahir_reusable_bot`; the hub imports nothing from `weatherbot`. Enforced by the dev-only import-hygiene gate (`grimp`, `tests/test_import_hygiene.py`).
- **Pin:** Hub is a git dependency pinned at tag `v0.1.1` via `[tool.uv.sources]`; `uv.lock` freezes the resolved sha. Deployed sha is read from the installed dist's PEP 610 `direct_url.json` and logged once per boot as "module provenance" (`cli.py:_module_provenance`).
- **Injection sites:** All app specifics reach the hub as closures at `weatherbot/scheduler/wiring.py`:
  - leak point 1 + 4: selected-location `SelectedContext` + `render_embed` panel cosmetics (`build_inbound_bot`).
  - leak point 2: `ReloadEngine` `desired_jobs`/`register_jobs`/`restore` closures + `excluded_ids` frozenset.
  - leak point 3: `ReadyGate` `health_check` closure adapting app `CheckResult` → neutral `HealthResult` via `to_health_result`.
- **Re-export shims:** `weatherbot/reliability/__init__.py`, `weatherbot/channels/base.py`, and `weatherbot/interactive/__init__.py` re-export relocated hub symbols so existing app imports stay byte-identical.
- **Placement litmus:** "Could a different bot reuse this with zero domain assumptions?" → yes ⇒ hub; no ⇒ app. New reusable impls incubate in `_promotable/` before promotion.

## Architectural Constraints

- **Threading:** APScheduler `BackgroundScheduler` threadpool (default max_workers=10) runs cron/heartbeat/uv jobs; the Discord `BotThread` runs the gateway on its own asyncio loop, started only after READY. A shared `threading.Event` (`stop`) is the interruptible sleep source for retries and the gate re-probe wait.
- **Read-only core:** `lookup_weather` MUST NOT write the DB or import the store package (spy-tested).
- **Recovery:** owned by `sent_log` + catch-up scan; every job registered with `misfire_grace_time=None` (memory jobstore loses state on exit).
- **Circular imports:** `daemon` imports `send_now` from `cli`, so `cli` imports `daemon` LAZILY inside the `run` branch; `wiring` imports `daemon` lazily; `SchedulerEngine`/discord.py imports stay off the import-time graph via lazy imports.
- **Secret hygiene:** the `appid` and webhook URL live only inside the injected client/channel; logging is outcome-only; the store never persists the request URL.

## Anti-Patterns

### Duck-typing the channel for enrichment

**What happens:** Checking `hasattr(channel, "send_embed")` before delivery.
**Why it's wrong:** Couples the composition root to a provider capability and crosses the agnostic `send(text)` seam.
**Do this instead:** Every channel exposes `send_briefing`; the base default delegates to `send`, Discord overrides internally (`weatherbot/channels/base.py:44`).

### Re-fetching to persist

**What happens:** Fetching OpenWeather a second time to write the analysis row.
**Why it's wrong:** Doubles API calls and can persist a different payload than was delivered (DATA-03).
**Do this instead:** Persist the SAME `Forecast` the render used, only after a successful delivery (`weatherbot/cli.py:217`).

### Emitting systemd READY before the scheduler is up

**What happens:** Calling `notifier.ready()` before `scheduler.start()`.
**Why it's wrong:** systemd considers the service live while it cannot yet deliver — the most golden-sensitive invariant.
**Do this instead:** `ReadyGate.on_online` runs `scheduler.start()` first; the hub emits READY strictly after (`weatherbot/scheduler/wiring.py:300`).

### Duplicating the command list per surface

**What happens:** Maintaining separate CLI and Discord command lists.
**Why it's wrong:** They drift; a command appears on one surface only.
**Do this instead:** Derive both from the single `registry.COMMANDS` (`weatherbot/interactive/registry.py`).

## Error Handling

**Strategy:** Fail-loud-at-load for config; bounded-retry-then-report for transient send failures; per-job isolation in the daemon.

**Patterns:**
- Config errors surface as clean exit codes, never a raw traceback (`_load_config_reporting`, `cli.py:569`).
- Transient (429/5xx/timeout) vs permanent (401/403) split via `is_transient`/`is_auth_failure` (hub reliability shim); manual path = 3-attempt tenacity, daemon = patient two-burst.
- `fire_slot` wraps its body so one bad slot cannot crash the scheduler thread; failed send releases the claim.
- `UnknownLocationError` IS-A `ValueError`, reraised on attempt 1 (never retried), carries `valid_names` for a corrective hint.

## Cross-Cutting Concerns

**Logging:** structlog, rendered to STDERR via `PrintLoggerFactory` (keeps `weather` stdout a clean pipe); outcome-only, never a secret (`cli.py:_configure_logging`). Reload outcomes mirrored through stdlib logging for the journal.
**Validation:** pydantic v2 models validate all non-secret config at load; `validate_config_and_templates` is the shared validate seam used by `check`, `check-config`, and hot-reload.
**Authentication:** OpenWeather `appid` and Discord webhook URL held only on the injected client/channel, sourced from `Settings` (pydantic-settings, `.env`); Discord operator guard ladder in `interactive/bot.py`.

---

*Architecture analysis: 2026-07-07*
