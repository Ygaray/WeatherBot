# Walking Skeleton — WeatherBot

**Phase:** 1
**Generated:** 2026-06-09

## Capability Proven End-to-End

> One sentence: the smallest user-visible capability that exercises the full stack.

Running `uv run python -m weatherbot --send-now` fetches live weather for the single configured location, persists the fetch to a local SQLite store, renders an imperial-primary plain-text briefing from an editable template, and posts it to the configured Discord channel under the `WeatherBot ☀️` identity — the entire fetch → aggregate → persist → render → deliver pipeline proven once, on demand.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language / runtime | Python 3.12+ (host verified 3.12.3) | Locked by CLAUDE.md; stdlib `tomllib`, `sqlite3`, `zoneinfo` available |
| Packaging / deps | uv (`uv init`, `uv add`, `uv sync`, `uv.lock`) | Locked by CLAUDE.md; single static binary, reproducible installs on dev + Pi |
| Package layout | Single importable package `weatherbot/` with sub-packages `config/`, `weather/`, `channels/` + top-level `templates/`, run via `python -m weatherbot` | Mirrors RESEARCH.md "Recommended Project Structure"; sub-packages are the seams later phases (`scheduler/`, `reliability/`) extend |
| HTTP client | httpx 0.28.x with explicit `timeout=` | Locked; process must never hang on a slow OpenWeather response |
| Weather source | Free OpenWeather 2.5 `weather` + `forecast` endpoints by lat/lon, today's high/low/rain by 3-hour-bucket aggregation on the location's LOCAL date | Locked (no credit card); One Call 3.0 explicitly rejected as default |
| Units strategy (FCST-04) | Fetch each endpoint twice — once `units=imperial`, once `units=metric` (4 calls/briefing, trivially within 60/min · 1M/month quota) | Avoids in-code conversion rounding drift; each persisted row tagged with its `units` (RESEARCH Open Question 1 — "fetch both" recommendation) |
| Normalized model | `weather/models.py` `Forecast` dataclass — the contract the store, renderer, and Discord embed all consume; hides raw JSON shape | RESEARCH Architectural Responsibility Map; the load-bearing seam between data layer and presentation |
| Templating | Editable `.txt` files in top-level `templates/`, flat `{type}-{style}.txt` naming, guarded `{placeholder}` substitution (no full engine) via a stable `render(template_text, values) -> str` signature | D-01/D-02/D-03/D-04; Phase 2 EXTENDS this renderer (adds strict validation + hint/severe fields), does not replace it. Anti-feature: a full template engine |
| Persistence | stdlib `sqlite3`, two tables `weather_current` + `weather_forecast`, raw-JSON TEXT + GENERATED virtual columns + indexes, one row per fetch / one row per forecast bucket, `target_ts_utc` on forecast rows | D-08/D-09/D-10; the generated-column pattern lets v2 analysis add columns with NO data migration (DATA-02). DB file at gitignored `data/weatherbot.db` |
| Channel seam | `channels/base.py` `Channel` ABC with `send(text: str) -> DeliveryResult`; `DiscordWebhookChannel` is the one impl; the Discord embed is built INSIDE the channel (`send_briefing(text, forecast)`) and never crosses the `send(text)` interface | D-12/D-13/DELV-02/DELV-03; the plain-text path is the exact body SMS/Telegram reuse in v2 |
| Secrets | `OPENWEATHER_API_KEY` + `DISCORD_WEBHOOK_URL` loaded from `.env`/environment via `pydantic-settings` `BaseSettings`; never in `config.toml`, never committed, never logged | CONF-02; `.env` already gitignored. Webhook URL treated as a credential |
| Non-secret config | Hand-edited `config.toml` read by stdlib `tomllib`, validated by Pydantic at load: `locations` LIST (`name`, `lat`, `lon`), template filename, webhook `username` + `avatar_url` | D-05/D-06; list-of-locations from day one is the Phase 2 multi-location seam |
| Logging | structlog with secret redaction (never echo request URLs, API key, or webhook URL) | RESEARCH Security Domain V7; stdlib `logging` acceptable fallback |
| Run / entry | `python -m weatherbot --send-now [location]` composition root in `weatherbot/cli.py` + `weatherbot/__main__.py` | CONF-04, D-07 (bare = first location, `<name>` = match). Supervised long-running run is Phase 5 |
| Test runner | pytest, recorded OpenWeather JSON fixtures + mocked httpx/webhook; `uv run pytest -x -q` | RESEARCH Validation Architecture; no network needed for the unit/integration suite |

## Stack Touched in Phase 1

- [x] Project scaffold (uv init → `pyproject.toml`/`uv.lock`, ruff lint, pytest test runner, package layout)
- [x] Routing / entry — real `python -m weatherbot --send-now [location]` entrypoint
- [x] Database — real SQLite read AND write (persist a fetch, query it back in tests)
- [x] External I/O wired — real OpenWeather fetch (httpx) and real Discord webhook post wired through the composition root
- [x] Local full-stack run command — `uv run python -m weatherbot --send-now` with `.env` populated posts a briefing to Discord (documented; supervised deploy is Phase 5)

## Out of Scope (Deferred to Later Slices)

> Anything that is *not* in the skeleton. Explicit so future phases do not re-litigate Phase 1's minimalism.

- Multiple locations / city-name → lat/lon geocoding / per-location units override (Phase 2 — LOC-01/02/03)
- "Feels like", umbrella/coat hints, severe-weather line, strict missing-placeholder validation (Phase 2 — FCST-05/06, TMPL-01/02)
- `--check` config-validation command (Phase 2 — CONF-05)
- Any scheduling — APScheduler, day-of-week, DST, idempotency, missed-send recovery (Phase 3 — SCHD-01..07)
- Retry/backoff, retry-then-alert, out-of-band alert, heartbeat, job exception-isolation (Phase 4 — RELY-01..06)
- Supervised process / reboot survival / startup self-check / online signal (Phase 5 — OPS-01/02)
- SMS (Twilio) and Telegram channels (v2 — CHAN-V2-01/02); the `compact` template + plain-text `send(text)` lay the seam
- Weather-pattern analysis / history query / export (v2 — ANLY-V2-01/02); Phase 1 only WRITES the analysis-ready store
- A full template engine with logic/loops/conditionals (permanent anti-feature)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions (the `Forecast` model, the `Channel` seam, the `templates/` directory, the SQLite schema, and secrets-from-env are fixed contracts):

- Phase 2: Real config — 2+ independent locations (name/lat/lon/IANA tz/units override), geocoding at setup, richer briefing (feels-like + hints + severe-weather line), editable template with strict validation, `--check`.
- Phase 3: Always-on in-process scheduler — per-location local wall-clock sends, day-of-week selection, DST-safe, missed-send recovery, idempotent per `(location, slot, local-date)`.
- Phase 4: Retry-then-alert reliability — bounded backoff (honor `Retry-After`, never retry 401/403), out-of-band missed-briefing alert, heartbeat, per-job exception isolation.
- Phase 5: Deployment & reboot survival — supervised process (systemd `Restart=always` / container), startup self-check (config + key reachability), "online" signal.
