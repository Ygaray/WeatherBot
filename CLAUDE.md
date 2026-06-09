<!-- GSD:project-start source:PROJECT.md -->

## Project

**WeatherBot**

WeatherBot is a personal, always-on morning weather briefing bot. It pulls forecast
data from the OpenWeather API and delivers a templated daily briefing to the user
across messaging channels (Discord first; SMS and Telegram designed to slot in later).
It is built for one person who splits time between a home city on weekdays and a travel
city on weekends, so each location is configured independently with its own send
schedule.

**Core Value:** Every morning, the user reliably receives a clear, correctly-located weather briefing
for the place they'll actually be that day — without lifting a finger.

### Constraints

- **Dependency**: OpenWeather API — requires an API key and is subject to its rate limits and free-tier quotas
- **Delivery**: Discord incoming webhook for v1; channel layer must stay provider-agnostic for SMS/Telegram later
- **Runtime**: Long-running process on an always-on host (server/Pi) with an internal scheduler — must survive across days without manual restarts
- **Reliability**: Network/API calls can fail at send-time; must retry and then alert rather than silently miss a briefing
- **Config**: All user-facing settings (locations, schedules, templates, secrets) must be editable without code changes

<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->

## Technology Stack

## Executive Recommendation

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12+ (3.13 fine) | Language/runtime | Best-in-class ecosystem for exactly these pieces (scheduling, HTTP, Discord, Twilio, Telegram all have first-class libs). Runs cleanly on a Raspberry Pi or any server. A bot like this is I/O-bound glue code where Python's library coverage matters far more than raw speed. |
| uv | 0.11.x | Packaging / dependency / venv manager | 2025-2026 community consensus tool. 10-100x faster than pip/Poetry, single static binary (trivial on a Pi), `uv init`/`uv add`/`uv sync` cover the whole lifecycle, reads standard `pyproject.toml` + writes a `uv.lock` for reproducible installs across your dev machine and the host. |
| APScheduler | 3.11.x | In-process scheduler | The de-facto Python in-process scheduler. `BackgroundScheduler` + `CronTrigger` natively expresses "09:00 on Mon-Fri" and "08:00 on Sat-Sun" — exactly the day-of-week, multi-send-time, per-location model the project needs. Each (location, send-time) becomes one cron job; toggling = add/remove/pause a job. Survives for days in a long-running process. **Use 3.x, NOT 4.x** (see below). |
| httpx | 0.28.x | HTTP client for OpenWeather (and future HTTP-based channels like Telegram) | Modern, actively maintained, supports timeouts/retries cleanly, sync and async in one API. One client, connection pooling, explicit timeouts — important for a process that must not hang forever on a slow OpenWeather response. |
| discord-webhook | 1.4.x | Discord delivery (v1 channel) | Purpose-built wrapper around Discord incoming webhooks with embed support, no bot token or gateway connection required — matches the "free webhook, trivial setup" decision in PROJECT.md. Lighter than pulling in `discord.py` (which is built for full gateway bots, not fire-and-forget webhooks). |
| Jinja2 | 3.1.x | Message templating | The standard Python templating engine. Editable `.j2` (or `.txt` with `{{ }}`) templates with placeholders like `{{ temp }}`, `{{ high }}`, `{{ rain }}` — exactly the "editable templates with placeholders" requirement. Supports conditionals/loops if briefings grow richer, and `undefined` handling to catch typo'd placeholders. |
| pydantic + pydantic-settings | 2.13.x / 2.14.x | Config + secrets loading & validation | Validates the config at startup (e.g. malformed send-time, missing webhook URL fails loudly instead of at 9am silently). `pydantic-settings` cleanly layers `.env`/environment-variable secrets over a TOML/YAML config file, keeping API keys out of the committed config. |
| tenacity | 9.x | Retry / backoff | Decorator-based retry with exponential backoff + jitter, max-attempts, and retry-on-specific-exceptions. Directly implements the "retry on OpenWeather/send failure, then alert" requirement without hand-rolled loops. |
| structlog | 26.x | Structured logging | Structured, level-controlled logging that's readable in console on a Pi and parseable if you later ship logs somewhere. Far better than bare `print` for a multi-day unattended process where you need to reconstruct "did the 9am briefing actually send?". (Std-lib `logging` is an acceptable zero-dependency fallback.) |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tomllib (stdlib) | built-in (3.11+) | Read TOML config | Default config-file reader — no dependency needed. Use for the human-edited `config.toml`. (Writing TOML needs `tomli-w`; not required since config is hand-edited.) |
| python-dotenv | 1.2.x | Load `.env` secrets | If not using `pydantic-settings` for secrets, this loads `OPENWEATHER_API_KEY`, `DISCORD_WEBHOOK_URL`, etc. from a git-ignored `.env`. (Redundant if you adopt `pydantic-settings`, which reads `.env` natively.) |
| twilio | 9.10.x | SMS channel (deferred) | Only when the Twilio channel is implemented later. Official SDK. Keep out of v1 deps. |
| python-telegram-bot | 22.x | Telegram channel (deferred) | Only when the Telegram channel is implemented later. (Or just call the Bot API over httpx — a single POST — to avoid a heavy dependency for one message type.) |
| zoneinfo (stdlib) | built-in (3.9+) | Timezone-correct scheduling | Pin each location/schedule to an IANA timezone (e.g. `America/New_York`) so "9am" means 9am local, and DST is handled. Pass `timezone=` to APScheduler `CronTrigger`. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| ruff | Lint + format | Single fast tool replacing flake8/black/isort. `uv add --dev ruff`. |
| pytest | Tests | Test the forecast-aggregation logic and template rendering with recorded OpenWeather JSON fixtures; mock the channel send. |
| systemd (or Docker) | Keep the process alive on the host | On a Pi/server, run as a `systemd` service with `Restart=always` so the bot survives crashes/reboots — complements (does not replace) the in-process scheduler. |

## Installation

# Scaffold project (creates pyproject.toml, .venv, uv.lock)

# Core runtime dependencies

# Dev dependencies

# Deferred channel deps (add only when implementing those channels)

# uv add twilio

# uv add python-telegram-bot

# Run

## OpenWeather API: Endpoint Decision (explicit)

| Concern | Recommendation |
|---------|----------------|
| **Default endpoints** | `GET https://api.openweathermap.org/data/2.5/weather` (current conditions) + `GET https://api.openweathermap.org/data/2.5/forecast` (5-day / 3-hour). Query by `lat`/`lon` (city-name lookups are deprecated though still functional). |
| **Why not One Call 3.0 by default** | One Call 3.0 gives clean per-day aggregates AND requires entering credit-card details even for its free 1,000 calls/day tier. For a single-user personal bot, the no-card free tier is the right default. Keep One Call 3.0 behind a config flag as an upgrade if you want richer daily/hourly data and accept putting a card on file. |
| **Free-tier limits (no credit card)** | "Free Access" current weather + forecast APIs: **60 calls/minute, 1,000,000 calls/month**. A briefing = 1-2 calls; a few locations × a few send-times/day is a rounding error against this quota. (Note: as of 2025-2026, OpenWeather enforces the 60/min limit more strictly and new keys can take up to ~2 hours to activate.) |
| **Getting today's high/low/rain** | The `current` endpoint's `temp_min`/`temp_max` are "min/max at the current moment," NOT the day's high/low. Compute today's high/low by **aggregating the 3-hour `forecast` buckets that fall on the current local date** (max/min of `main.temp`). Rain chance = max `pop` (probability of precipitation, 0-1) across today's buckets. Wind/humidity/sky from `current` or the next forecast bucket. |
| **Auth** | API key passed as `appid` query param. Store in `.env` / environment, never in the committed config. Add `units=metric` (or `imperial`) and optional `lang=`. |

## Pluggable Channel Design (how SMS/Telegram slot in)

- v1: `DiscordChannel(webhook_url)` wraps `discord-webhook`.
- Later: `TwilioChannel(...)` (twilio SDK), `TelegramChannel(...)` (httpx POST or python-telegram-bot).
- Channels are selected/instantiated from config by name (a registry dict), so adding one =
- The retry/alert wrapper (tenacity) lives at the orchestration layer around `Channel.send`,

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Python | Node.js/TypeScript | If you strongly prefer JS and want `discord.js`. Python wins here on the breadth of weather/scheduling/Twilio/Telegram libraries and simplicity for a single-file-ish personal tool. |
| APScheduler 3.x | `schedule` library | `schedule` is simpler but has no native cron/day-of-week semantics and no timezone awareness — you'd hand-roll the Mon-Fri/Sat-Sun logic. APScheduler's `CronTrigger` models the requirement directly. |
| APScheduler 3.x | OS cron / systemd timers | The project explicitly chose an *in-process* scheduler so reliability doesn't depend on OS-level cron and so config (toggles, multiple send-times) lives in one place. Use systemd only to keep the *process* alive, not to schedule briefings. |
| discord-webhook | discord.py | Use `discord.py` only if you later want a full interactive bot (slash commands, gateway). For fire-and-forget webhook briefings it's overkill (persistent gateway connection, bot token). |
| httpx | requests | `requests` is fine and stable, but `httpx` gives a cleaner timeout model and one path to async if Telegram/multiple channels make concurrency useful. Either is acceptable; httpx is the more future-proof default. |
| TOML config | YAML / JSON | TOML (stdlib `tomllib`) is the recommended default: comment-friendly, less whitespace-fragile than YAML, and native to the Python toolchain. Choose YAML only if your schedules become deeply nested and you prefer its syntax. Avoid JSON for hand-edited config (no comments). |
| uv | Poetry | Poetry is still fine for libraries you publish. For a personal app, uv is faster, simpler on a Pi, and is where the ecosystem is heading. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| OpenWeather One Call API **2.5** | Deprecated; access being discontinued. Do not build on it. | One Call 3.0 (with card) or the free `2.5/weather` + `2.5/forecast` endpoints. |
| OpenWeather One Call 3.0 **as the default** | Requires credit-card details even for the free tier — unnecessary friction for a personal no-cost bot. | Free `2.5/weather` + `2.5/forecast` (60/min, 1M/month, no card). |
| APScheduler **4.0 (pre-release)** | Officially "do NOT use in production"; API still changing in backwards-incompatible ways, no job-store migration path yet. | APScheduler 3.11.x (stable). |
| OS cron **for the briefing logic** | Splits scheduling from config, can't express toggles cleanly, and contradicts the project's in-process-scheduler decision. | APScheduler in-process; systemd only to restart the process. |
| Hardcoded secrets / committing the config with keys | Leaks the OpenWeather key and Discord webhook URL. | Secrets in git-ignored `.env` via pydantic-settings; config file holds non-secret structure with references. |
| `discord.py` for webhooks | Heavy gateway bot framework for what is one HTTP POST. | discord-webhook (or a raw httpx POST to the webhook URL). |
| Bare `print()` logging | Useless for diagnosing a multi-day unattended process. | structlog (or stdlib `logging`). |
| City-name (`q=`) lookups as the primary geocoding | Deprecated by OpenWeather. | Resolve to `lat`/`lon` (configure coordinates per location, or use the Geocoding API once at setup). |

## Stack Patterns by Variant

- Use `2.5/weather` + `2.5/forecast`, compute daily high/low/rain by aggregating 3-hour buckets.
- 2 calls per briefing; trivially within 60/min and 1M/month.
- Switch to One Call 3.0 (`/data/3.0/onecall`) for ready-made `daily` summaries (no bucket aggregation).
- Stay under 1,000 calls/day to remain free; set a usage cap in your OpenWeather account to avoid surprise charges.
- Jinja2 may feel heavy; Python f-strings or `str.format(**data)` suffice. Jinja2 still recommended because the requirement is *user-editable* template files (logic should live in the template file, not code).
- Single small Dockerfile + `Restart` policy. Otherwise a `systemd` unit with `Restart=always` and `EnvironmentFile=.env` is the lightest reliable option.

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| APScheduler 3.11.x | Python 3.8+ | Use `BackgroundScheduler` + `CronTrigger(timezone=...)`. Do not jump to 4.x. |
| httpx 0.28.x | Python 3.8+ | Set explicit `timeout=` on the client; don't rely on no-timeout default behavior. |
| pydantic 2.13.x | pydantic-settings 2.14.x | Both are Pydantic v2; don't mix with any v1-era tutorials/APIs. |
| discord-webhook 1.4.x | Python 3.10+ | Webhook-only; no bot token needed. |
| tomllib | Python 3.11+ | Stdlib read-only. For writing TOML you'd need `tomli-w` (not required here). |
| structlog 26.x | Python 3.10+ | Can wrap stdlib `logging` for handlers/rotation. |

## Sources

- https://openweathermap.org/api/one-call-3 — One Call 3.0 free tier (1,000 calls/day) requires subscription + credit card. HIGH
- https://openweathermap.org/api/one-call-transfer — 2.5 One Call deprecated/being discontinued, migrate to 3.0. HIGH
- https://openweathermap.org/current — current weather endpoint URL, units, lang params. HIGH
- https://openweathermap.org/api/forecast5 — 5-day/3-hour forecast endpoint; `temp_min`/`temp_max` semantics; `pop`. HIGH
- https://apiscout.dev/guides/openweathermap-free-tier-limits-2026 — free access APIs 60 calls/min, 1M/month, no card; 2025 stricter enforcement, ~2h key activation. MEDIUM
- https://apscheduler.readthedocs.io/en/3.x/userguide.html + https://github.com/agronholm/apscheduler — 4.0 is pre-release, not for production; 3.11.x is the stable line; BackgroundScheduler/CronTrigger. HIGH
- https://packaging.python.org/en/latest/guides/writing-pyproject-toml/ + community 2025/2026 comparisons — uv as the current standard, pyproject.toml `[project]` table. MEDIUM
- PyPI version checks (2026-06-09): apscheduler 3.11.2, httpx 0.28.1, discord-webhook 1.4.1, tenacity 9.1.4, pydantic 2.13.4, pydantic-settings 2.14.1, jinja2 3.1.6, structlog 26.1.0, python-dotenv 1.2.2, uv 0.11.19, twilio 9.10.9, python-telegram-bot 22.7. HIGH

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
