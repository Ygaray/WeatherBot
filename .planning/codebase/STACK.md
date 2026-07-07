# Technology Stack

**Analysis Date:** 2026-07-07

## Languages

**Primary:**
- Python 3.12+ - Entire codebase (`weatherbot/**`, `tests/**`). `.python-version` pins `3.12`; `pyproject.toml` sets `requires-python = ">=3.12"`.

**Secondary:**
- TOML - Human-edited config (`config.toml`, `config.example.toml`), read via stdlib `tomllib`.
- systemd unit syntax - `deploy/bot.service.template`, `deploy/weatherbot.service`.
- Jinja-flavored `.txt` templates - `templates/*.txt` (briefing bodies, `{{ }}` placeholders).

## Runtime

**Environment:**
- CPython 3.12+, single long-running process on an always-on host (`yahir-mint`, systemd `Type=notify`).
- Threading model: a main scheduler process plus a Discord gateway `BotThread` (from the hub) running the async event loop; blocking work is dispatched off-loop via `loop.run_in_executor`.

**Package Manager:**
- uv (0.11.x line) - manages venv, resolution, lockfile.
- Lockfile: `uv.lock` present (310 KB, committed). Host installs via `uv sync --frozen`.

## Frameworks

**Core:**
- APScheduler >=3.11.2,<4 - In-process cron scheduler (per (location, send-time) slot). 4.x explicitly avoided.
- httpx >=0.28.1 - HTTP client for OpenWeather One Call 3.0 + Geocoding.
- discord-webhook >=1.4.1 - Outbound briefing delivery (v1 channel). Posts via the `requests` library under the hood.
- discord.py 2.7.1 - Inbound interactive gateway. NOT declared app-side; pulled transitively (and pinned) by the `yahir-reusable-bot` hub. Do NOT re-declare it here.

**Testing:**
- pytest >=9.0.3 - Test runner.
- pytest-cov >=7.1.0 - Branch coverage (audit tool, not a standing gate).
- syrupy >=5.3.4 - Snapshot/golden tests (`.ambr`).
- time-machine >=2.16 - Deterministic time control for schedule/UV tests.

**Build/Dev:**
- hatchling - Build backend (`[build-system]`). Wheel packages `["weatherbot"]` explicitly.
- ruff >=0.15.16 - Lint + format (single tool).
- grimp >=3.14 - Import-hygiene gate (dev-only; enforces the app/hub split litmus).

## Key Dependencies

**Critical:**
- **yahir-reusable-bot** (the hub) - The shared reusable bot core, an EXTERNAL git dependency. This is the primary internal integration. See below and INTEGRATIONS.md.
- pydantic >=2.13.4 / pydantic-settings >=2.14.1 - Config validation + secrets loading (the only place secrets enter the process).
- tenacity >=9.1.4 - Retry/backoff primitive (retry engine itself now lives in the hub's `reliability` layer).
- structlog >=26.1.0 - Structured logging (multi-day unattended process).

**Infrastructure:**
- watchfiles >=1.2.0 - Config file-watch for live reload.
- cachetools >=6,<8 - TTL cache backing the per-location interactive forecast cache.

### Hub dependency (yahir-reusable-bot) — pin details

WeatherBot is a **consumer** in a two-repo ecosystem. Its reusable infrastructure was
extracted into the hub `yahir_reusable_bot` (repo `github.com/Ygaray/YahirReusableBot`).

- **Declared:** `pyproject.toml` `dependencies` lists bare `yahir-reusable-bot`.
- **Sourced:** `[tool.uv.sources]` → `{ git = "https://github.com/Ygaray/YahirReusableBot", tag = "v0.1.1" }` (public repo, no credentials needed on the host).
- **Frozen SHA:** `uv.lock` pins the resolved commit `7f3cc001f814f6a7d37b5f18f254c8baaa7c1546` (tag `v0.1.1`).
- **Transitive pins:** the hub pins discord-py 2.7.1, httpx, structlog — so the app must NOT re-declare discord.py (the live-panel `custom_id` wire contract depends on that exact version).
- **Live cross-repo dev:** `uv pip install -e ../Reusable/YahirReusableBot` (uncommitted editable overlay); revert with `uv sync --frozen`.
- **Cutting a new hub tag + repinning is human-gated** (see `deploy/REPIN-RITUAL.md`), never shipped autonomously.

Hub-provided modules imported app-side: `yahir_reusable_bot.channels` (Channel/DeliveryResult), `.config` (ConfigHolder/ReloadEngine), `.lifecycle` (SystemdNotifier/ReadyGate/LifecycleIdentity/is_running_process/HealthResult/Severity), `.scheduler` (SchedulerEngine), `.discord` (BotThread/build_client/PanelKit/gateway.summon_panel), `.registry` (dispatch_spec/match_command), `.reliability` (retry engine).

## Configuration

**Environment (secrets — `.env`, git-ignored, never committed/logged):**
Loaded exclusively via `weatherbot/config/settings.py` (pydantic-settings `Settings`, `env_file=".env"`). Required env vars (all no-default, fail-loud at startup):
- `OPENWEATHER_API_KEY` - One Call 3.0 auth (`appid` query param).
- `DISCORD_WEBHOOK_URL` - Outbound briefing webhook (bearer credential).
- `DISCORD_BOT_TOKEN` - Inbound gateway bot token (bearer credential).

**Non-secret structure (`config.toml`, hand-edited):**
Read via stdlib `tomllib` (`weatherbot/config/loader.py`). Holds `template`, `[[locations]]` (name/lat/lon/timezone/optional units), `[[locations.schedule]]` (time/days/enabled), `[webhook]` display identity, optional `[reliability]` retry budget, and `[bot]` (operator_id / panel_channel_id). Validate without sending via `weatherbot --check`.

**Build:**
- `pyproject.toml` - single source for deps, scripts (`weatherbot = weatherbot.cli:main`), build, coverage, pytest, ruff.
- `uv.lock` - frozen resolution.

## Platform Requirements

**Development:**
- Python 3.12+, uv, a hub checkout at `../Reusable/YahirReusableBot` for cross-repo work.

**Production:**
- Always-on Linux host (`yahir-mint`) running the bot as a systemd `Type=notify` service (`ExecStart=/usr/bin/uv run weatherbot run`, `Restart=always`, `EnvironmentFile=<REPO>/.env`). No WatchdogSec in v1.

---

*Stack analysis: 2026-07-07*
