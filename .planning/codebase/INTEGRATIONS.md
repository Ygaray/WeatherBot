# External Integrations

**Analysis Date:** 2026-07-07

## APIs & External Services

**Weather data — OpenWeather:**
- **One Call 3.0** (`GET https://api.openweathermap.org/data/3.0/onecall`) — the send-path fetch. `weatherbot/weather/client.py` → `fetch_onecall()`. Queries by `lat`/`lon`, `units` (imperial|metric per-location), `lang=en`, `exclude=minutely` (KEEPS `current`/`hourly`/`daily`/`alerts`). Returns today's high/low/pop/uvi (`daily[0]`), current conditions incl. `feels_like`/`uvi`, `hourly[]` (UV window math), and `alerts[]`.
  - SDK/Client: raw `httpx.Client` with explicit `timeout=10.0` (never hangs).
  - Auth: `OPENWEATHER_API_KEY` passed as the `appid` query param. The full URL is a secret — the module raises the `httpx` logger to WARNING so the key can never leak into logs.
  - NOTE (discrepancy vs. CLAUDE.md stack doc): the CLAUDE.md recommendation described the free `2.5/weather` + `2.5/forecast` endpoints; the shipped code uses **One Call 3.0** (`/data/3.0/onecall`), which requires the "One Call by Call" subscription. A 401/403 most often means that subscription is not active/propagated.
- **Geocoding** (`GET https://api.openweathermap.org/geo/1.0/direct`) — setup-time ONLY, via `weatherbot/weather/client.py` → `geocode()`, reached by the `weatherbot --geocode "<city>"` command. NEVER on the send path (LOC-03).

**UV index:**
- Not a separate API — derived from the same One Call payload (`current.uvi`, `daily[0].uvi`, `hourly[].uvi`). Pure computation in `weatherbot/weather/uv.py` (`compute_uv`), consumed by the briefing, the `uv <loc>` command, and a background UV monitor (`weatherbot/scheduler/uvmonitor.py`).

## Delivery — Discord (two directions)

**Outbound (v1 briefing) — Incoming Webhook:**
- `weatherbot/channels/discord.py` → `DiscordWebhookChannel`, using the `discord-webhook` lib (posts via `requests`).
- Auth: `DISCORD_WEBHOOK_URL` (bearer credential; stored privately, never logged, never in a `DeliveryResult.detail`). The `discord_webhook` logger is raised to WARNING to prevent URL leakage.
- `send(text)` is the channel-agnostic interface; `send_briefing(text, forecast)` adds a Discord-only rich embed. Non-2xx = `ok=False` (never raises); `rate_limit_retry=True` honors Discord 429s.

**Inbound (interactive commands + control panel) — Gateway bot:**
- `weatherbot/interactive/bot.py` (app half) on top of `discord.py`. The generic gateway plumbing (`BotThread`, `build_client`, persistent-view/PanelKit machinery, `summon_panel` create-before-delete ordering, `REQUIRED_PANEL_PERMS`) lives in the **hub** (`yahir_reusable_bot.discord`).
- Auth: `DISCORD_BOT_TOKEN` (bearer; `.env` only, required, fail-loud).
- Guard ladder (order load-bearing): drop bots → ignore non-operator (`[bot] operator_id`) → require `!` prefix → registry dispatch. `!panel` summons a pinned control panel in `[bot] panel_channel_id`. All blocking fetches run off the event loop; the whole handler is wrapped in a non-propagating try/except so the always-on process survives a bad fetch.

## Internal Integration — the `yahir_reusable_bot` hub (PRIMARY)

WeatherBot is a **consumer** in a two-repo ecosystem; the hub is its most important integration.

- **Package:** `yahir_reusable_bot` (repo `github.com/Ygaray/YahirReusableBot`; dev checkout `../Reusable/YahirReusableBot`).
- **Pin:** `[tool.uv.sources]` → git tag `v0.1.1`; `uv.lock` freezes SHA `7f3cc001f814f6a7d37b5f18f254c8baaa7c1546`. Transitively pins discord-py 2.7.1.
- **What the app imports from it** (app-side files are mostly thin shims/wiring):
  - `.channels` — `Channel`, `DeliveryResult` base (`channels/base.py` shim).
  - `.config` — `ConfigHolder`, `ReloadEngine` (`config/holder.py` shim; `cli.py`; `scheduler/`).
  - `.lifecycle` — `SystemdNotifier` (`ops/sdnotify.py` shim), `ReadyGate`, `LifecycleIdentity`, `is_running_process` (`ops/pidfile.py`), `HealthResult`/`Severity` (`ops/selfcheck.py`).
  - `.scheduler` — `SchedulerEngine` (`scheduler/daemon.py`, `wiring.py`).
  - `.discord` — `BotThread`, `build_client`, `PanelKit`, `gateway.summon_panel`/`REQUIRED_PANEL_PERMS`, `panelkit.is_owned_panel`.
  - `.registry` — `dispatch_spec`, `dispatch_reply`, `match_command`, `DispatchContext`.
  - `.reliability` — the retry engine (`reliability/` shims).
- **Cross-repo rules:** a bug in the hub is fixed upstream in the hub; cutting a hub tag + repinning + deploying is **human-gated** (`deploy/REPIN-RITUAL.md`), never autonomous. New reusable impls are built in this repo's `_promotable/` quarantine, then `git mv`'d to the hub. Read `../Reusable/YahirReusableBot/ECOSYSTEM.md` before cross-repo work.

## Data Storage

**Databases:**
- SQLite - local file DB written by `weatherbot/weather/store.py` (records send/forecast rows; `status` command reads it off-loop). App-side, single-file, no external server.

**File Storage:**
- Local filesystem only - `data/` (runtime state, DB), `templates/` (briefing bodies), pidfile (`weatherbot/ops/pidfile.py`).

**Caching:**
- In-process TTL cache - `weatherbot/interactive/cache.py` (`cachetools`), per-location forecast cache for the interactive path.

## Authentication & Identity

- **OpenWeather:** API key (`appid`).
- **Discord webhook & bot token:** bearer credentials.
- **Operator gating:** inbound commands accepted only from the single `[bot] operator_id` (single-user tool). Baked at bot construction — changing it needs a process restart.

## Monitoring & Observability

**Error Tracking:**
- None (external). Failures surface via structured logs + a Discord alert on send failure after retry exhaustion.

**Logs:**
- structlog structured logging. Credential-carrying library loggers (`httpx`, `discord_webhook`) are deliberately raised to WARNING to prevent secret leakage.

**Self-check:**
- `weatherbot/ops/selfcheck.py` produces `HealthResult`/`Severity` (hub types) for a readiness/health report.

## CI/CD & Deployment

**Hosting:**
- Always-on Linux host (`yahir-mint`), systemd service.

**Systemd integration (`deploy/bot.service.template`):**
- `Type=notify` with `NotifyAccess=main` — the bot signals readiness via `sd_notify` (`SystemdNotifier` from the hub, `ReadyGate` for gating). No finite start timeout (long boot tolerated).
- `ExecStart=/usr/bin/uv run weatherbot run`, `Restart=always`, `RestartSec=5`.
- `EnvironmentFile=<REPO>/.env` (never inline `Environment=`; `.env` chmod 600).
- No `WatchdogSec` in v1 (deferred — a watchdog without periodic `WATCHDOG=1` keep-alives would false-kill).

**CI Pipeline:**
- None detected (no `.github/workflows`, etc.). Quality gates (ruff, pytest, grimp import-hygiene) run locally / via GSD.

## Environment Configuration

**Required env vars (`.env`, git-ignored):**
- `OPENWEATHER_API_KEY`, `DISCORD_WEBHOOK_URL`, `DISCORD_BOT_TOKEN` (all required, fail-loud at startup).

**Secrets location:**
- `.env` file (chmod 600), loaded only by `weatherbot/config/settings.py`. Never in `config.toml`, git, or logs.

## Webhooks & Callbacks

**Incoming:**
- Discord gateway events (`on_message`) via the persistent WebSocket connection (`discord.py` `BotThread`), not HTTP endpoints. Handled in `weatherbot/interactive/bot.py`.

**Outgoing:**
- Discord incoming webhook POST (briefings + alerts) via `discord-webhook`.

---

*Integration audit: 2026-07-07*
