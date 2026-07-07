# Codebase Structure

**Analysis Date:** 2026-07-07

## Directory Layout

```
WeatherBot/
├── weatherbot/                 # The application package (consumer of the hub)
│   ├── __main__.py             # `python -m weatherbot` entry → cli.main
│   ├── cli.py                  # CLI dispatch + one-shot composition roots (send_now, run_weather, do_check, do_geocode)
│   ├── branding.py             # Display identity constants
│   ├── scheduler/              # Always-on daemon spine + composition root
│   │   ├── daemon.py           # run_daemon lifecycle + fire_slot per-slot callback (the long-running heart)
│   │   ├── wiring.py           # build_runtime / build_inbound_bot — THE single injection site into the hub
│   │   ├── catchup.py          # 90-min startup catch-up planner
│   │   ├── uvmonitor.py        # proactive UV-index alert job
│   │   ├── context.py          # ScheduleContext + intended-vs-actual placeholders
│   │   └── days.py             # weekday/weekend day parsing
│   ├── interactive/            # Shared read-only core + command surfaces (CLI + Discord)
│   │   ├── lookup.py           # lookup_weather / lookup_forecast — read-only fetch→render core
│   │   ├── registry.py         # COMMANDS / BY_NAME single command list (anti-drift)
│   │   ├── dispatch.py         # sync + async dispatch of a CommandSpec
│   │   ├── command.py          # command + forecast-flag parsing
│   │   ├── bot.py              # Discord on_message guard ladder + render_embed + panel summon
│   │   ├── panel.py            # live-panel cosmetics/contributors
│   │   ├── cache.py            # per-location TTL ForecastCache
│   │   ├── state.py            # DaemonState (status reads)
│   │   ├── lookup.py / lookup* # resolve + fetch seam
│   │   └── commands/           # per-command handlers (forecast, info, status, weather_views)
│   ├── weather/                # Weather data layer
│   │   ├── client.py           # httpx One Call 3.0 + geocoding
│   │   ├── models.py           # Forecast domain model
│   │   ├── multiday.py         # 3-hour / multiday bucket aggregation
│   │   ├── uv.py               # UV-index helpers
│   │   └── store.py            # analysis-ready SQLite persistence + liveness rows
│   ├── channels/               # Provider-agnostic delivery seam
│   │   ├── base.py             # app-side Channel subclass adding send_briefing
│   │   ├── discord.py          # DiscordWebhookChannel (embed enrichment, internal)
│   │   └── factory.py          # build_channel registry keyed by config "type"
│   ├── config/                 # Config models + loaders + live holder
│   │   ├── models.py           # non-secret pydantic models (Config, Location, Schedule, …)
│   │   ├── loader.py           # load_config / resolve_location / validate_config_and_templates
│   │   ├── settings.py         # secrets via pydantic-settings (.env)
│   │   └── holder.py           # app ConfigHolder wrapper
│   ├── ops/                    # Supervision helpers
│   │   ├── sdnotify.py         # systemd sd_notify (READY/WATCHDOG)
│   │   ├── pidfile.py          # PID file write + /proc staleness guard
│   │   └── selfcheck.py        # classified startup self-check (run_self_check / to_health_result)
│   └── reliability/            # re-export shim over hub two-burst retry contract
│       ├── __init__.py         # re-exports yahir_reusable_bot.reliability symbols
│       └── retry.py            # retry constants/helpers
├── templates/                  # Editable briefing + forecast templates + renderer
│   ├── renderer.py             # load_template / render / validate_template
│   ├── briefing-*.txt          # briefing variants (sectioned default, compact, multiline)
│   └── forecast-*.txt          # weekday/weekend × detailed/compact (+ .line variants)
├── tests/                      # pytest suite + golden snapshots + fixtures
├── deploy/                     # systemd unit + promotion ledger + repin ritual
├── data/                       # runtime SQLite db (gitignored)
├── config.toml                 # live non-secret config (locations, schedules, template)
├── config.example.toml         # documented config template
├── .env / .env.example         # secrets (OPENWEATHER_API_KEY, DISCORD_WEBHOOK_URL) — gitignored
├── pyproject.toml              # deps, uv.sources hub pin, scripts, coverage/pytest config
└── uv.lock                     # frozen resolution (incl. hub git sha)
```

## Directory Purposes

**`weatherbot/scheduler/`:**
- Purpose: The always-on daemon and the single hub-injection composition root.
- Contains: daemon lifecycle, per-slot delivery callback, catch-up/uv jobs, wiring.
- Key files: `daemon.py` (the heart), `wiring.py` (`build_runtime`/`build_inbound_bot`).

**`weatherbot/interactive/`:**
- Purpose: The read-only fetch→render core shared by the scheduled path, CLI, and Discord bot.
- Contains: `lookup_weather`, the command registry, dispatch, Discord bot + panel, per-command handlers.
- Key files: `lookup.py`, `registry.py`, `dispatch.py`, `bot.py`.

**`weatherbot/weather/`:**
- Purpose: Fetch, aggregate, model, and persist forecast data.
- Key files: `client.py`, `models.py`, `store.py`.

**`weatherbot/channels/`:**
- Purpose: Provider-agnostic delivery; Discord webhook impl with internal embed enrichment.
- Key files: `base.py` (seam), `discord.py`, `factory.py` (registry).

**`weatherbot/config/`:**
- Purpose: Non-secret pydantic config, secret settings, live config holder, shared validator.
- Key files: `models.py`, `loader.py`, `settings.py`.

**`weatherbot/ops/`:**
- Purpose: Deployment/supervision — systemd readiness, PID guard, self-check.

**`templates/`:**
- Purpose: User-editable briefing/forecast templates + the renderer/validator (`renderer.py`).

## Key File Locations

**Entry Points:**
- `weatherbot/__main__.py`: `python -m weatherbot`.
- `weatherbot/cli.py:main`: subcommand dispatcher + one-shot composition roots.
- `weatherbot/scheduler/daemon.py:run_daemon`: the `run` daemon path.

**Composition Roots (single wiring sites):**
- `weatherbot/scheduler/wiring.py`: `build_runtime` (daemon), `build_inbound_bot` (Discord bot).
- `weatherbot/cli.py:send_now`: the manual fetch→persist→render→deliver pipeline.

**Configuration:**
- `config.toml` / `config.example.toml`: non-secret structure.
- `.env` / `.env.example`: secrets (never committed).
- `pyproject.toml`: `[tool.uv.sources]` hub pin (`v0.1.1`), `[project.scripts]`, coverage/pytest config.

**Core Logic:**
- `weatherbot/interactive/lookup.py`: read-only resolve→fetch→render core.
- `weatherbot/weather/store.py`: SQLite persistence + liveness rows.

**Testing:**
- `tests/`: unit + golden snapshot suites (`test_golden_*.py`), fixtures in `tests/fixtures/`, snapshots in `tests/__snapshots__/`.

**Deployment:**
- `deploy/weatherbot.service` + `bot.service.template`: systemd unit.
- `deploy/PROMOTION-LEDGER.md`, `deploy/REPIN-RITUAL.md`: hub-pin governance.

## Naming Conventions

**Files:**
- snake_case module names (`weather_views.py`, `uvmonitor.py`).
- Package barrels (`__init__.py`) re-export the public surface and `__all__`.
- Template files: `<kind>-<variant>.txt`, forecast grid `forecast-<weekday|weekend>-<detailed|compact>[.line].txt`.

**Directories:**
- One package per architectural layer (`scheduler/`, `weather/`, `channels/`, `config/`, `ops/`, `interactive/`, `reliability/`).

**Code identifiers:**
- Composition roots: `build_*` (`build_runtime`, `build_channel`, `build_client`).
- One-shot CLI paths: `run_*` / `do_*` (`run_send_now`, `run_weather`, `do_check`, `do_geocode`).
- Injected hub closures: `_health_check`, `_on_online`, `_on_fail`, `_dispatch`, `_render_bridge`.

## Where to Add New Code

**New delivery channel (SMS/Telegram):**
- Implementation: new class in `weatherbot/channels/` subclassing the app `Channel`.
- Register: add one entry to `_REGISTRY` in `weatherbot/channels/factory.py`.
- Secrets: add the credential field to `weatherbot/config/settings.py`.

**New command (appears on BOTH CLI and Discord):**
- Add a `CommandSpec` to `weatherbot/interactive/registry.py` (`COMMANDS`).
- Handler: new module in `weatherbot/interactive/commands/`.
- No second list — subparsers and panel buttons derive from the registry automatically.

**New scheduled job:**
- Register via `SchedulerEngine` inside `weatherbot/scheduler/wiring.py:build_runtime` (mirror `__heartbeat__` / `__uvmonitor__`); add its id to the `excluded_ids` frozenset if it must survive reload.

**New config field:**
- Non-secret → `weatherbot/config/models.py` (+ document in `config.example.toml`).
- Secret → `weatherbot/config/settings.py` (+ `.env.example`).

**New reusable mechanism (weather-agnostic):**
- Incubate in the app's `_promotable/` quarantine, then promote via `git mv` into the hub `../Reusable/YahirReusableBot`. App-specific wiring stays in `weatherbot/scheduler/wiring.py`.

**New template:**
- Add a `.txt` under `templates/`; validate with `templates/renderer.py:validate_template`.

## Special Directories

**`data/`:**
- Purpose: runtime SQLite db (`weatherbot.db`).
- Generated: Yes. Committed: No (gitignored).

**`tests/__snapshots__/` & `tests/fixtures/`:**
- Purpose: golden snapshots (syrupy) and recorded OpenWeather JSON fixtures.
- Generated: snapshots via syrupy. Committed: Yes.

**`dist/`:**
- Purpose: build artifacts. Committed: No (gitignored generated artifacts).

**`_promotable/` (convention, when present):**
- Purpose: hub-clean quarantine for reusable impls awaiting promotion to `yahir_reusable_bot`.

---

*Structure analysis: 2026-07-07*
