# Project Research Summary

**Project:** WeatherBot
**Domain:** Personal always-on scheduled weather-briefing bot (multi-location, multi-channel, Discord-first)
**Researched:** 2026-06-09
**Confidence:** HIGH

## Executive Summary

WeatherBot is a single-user, self-hosted briefing daemon — not a public Discord bot — and the research strongly converges on that distinction. Experts build this class of tool as a **textbook `scheduler -> fetch -> render -> dispatch` pipeline** wrapped around a validated config layer, running as one long-running Python process supervised by `systemd`/Docker. There is no web server, no database, and no user accounts: the only mutable runtime state is a small in-memory forecast cache plus a tiny persisted "already-sent-today" record. The recommended stack (Python 3.12+, `uv`, APScheduler 3.x, `httpx`, `discord-webhook`, Jinja2, Pydantic, `tenacity`, `structlog`) is mature, has first-class libraries for every piece, and runs cleanly on a Raspberry Pi. Confidence is HIGH because the load-bearing facts — OpenWeather's subscription model, APScheduler's DST/misfire semantics, and Discord rate limits — were all verified against official sources.

The recommended approach is to ship the smallest thing that reliably delivers the core value (a clear, correctly-located morning briefing for where the user will actually be), while getting two foundational decisions right from line one: **timezone handling and secrets separation**. All four research dimensions independently flag these as non-deferrable. Each location must store an IANA timezone (`America/New_York`), never a fixed offset, and the scheduler must be timezone-aware per job so "8 AM" means 8 AM local and survives DST automatically. Day-of-week support must be a field on the schedule model from day one, because the weekday-home / weekend-travel split *is* the entire product. Secrets (OpenWeather key, Discord webhook URL — itself a credential) must live in a git-ignored `.env`, separated from the checked-in config, *before* the first real key is introduced. Both are foundational because retrofitting them is a data migration, not a tweak.

The key risks are all failure-mode risks, not throughput risks: a single uncaught exception silently killing the daemon for days; scheduling drift across DST; restart/reboot replay producing duplicate or missed briefings; and a retry storm or an alert sent through the very channel that just failed. Mitigations are well-understood — top-level try/except per job, a process supervisor with `Restart=always`, a `(location, slot, local-date)` dedup key, bounded exponential backoff that honors `Retry-After` and never retries a 401, and an alert path independent of the primary channel. **One cross-dimension tension was reconciled** (OpenWeather endpoint choice — see below); the recommended default is the free, no-credit-card 2.5 endpoints with bucket aggregation.

### Reconciled Decision: OpenWeather Endpoint (default = free 2.5 + aggregation)

The Features research assumed **One Call 3.0** (which returns clean per-day `daily[0]` high/low/pop/wind/humidity in a single call). Stack, Architecture, and Pitfalls all independently converged on a different default: **One Call 3.0 requires a credit card on file even for its free 1,000-calls/day tier**, which is unnecessary friction for a no-cost personal bot. The resolved recommendation:

- **Default (v1):** free, no-card `GET /data/2.5/weather` (current) + `GET /data/2.5/forecast` (5-day / 3-hour), 60 calls/min and 1M/month, no card. Derive **today's high/low** and **rain chance** by **aggregating the 3-hour forecast buckets that fall on the location's local calendar date** (max/min of `main.temp`; rain = max `pop`). Wind/humidity/sky come from `current`.
- **Optional later upgrade:** One Call 3.0 behind a config flag, for ready-made daily summaries (no aggregation), accepting a card on file with a daily cap set.
- **Flag:** the **bucket-aggregation logic is the trickiest unit-testable piece** in the whole project. It deserves a focused spike with recorded OpenWeather JSON fixtures (clear-sky day with no `rain` field, a rainy day, a day spanning a local-midnight boundary). The `current` endpoint's `temp_min`/`temp_max` are "min/max *at the current moment*," NOT the day's range — using them is a silent correctness bug.

## Key Findings

### Recommended Stack

A single long-running **Python 3.12+** process managed by **uv**, scheduling per-`(location, send-time)` cron jobs via **APScheduler 3.x** (explicitly *not* 4.x, which is pre-release and unsafe for production). Each job fetches over **httpx**, renders a **Jinja2** template, and delivers through a thin `Channel` interface whose first implementation wraps **discord-webhook**. **tenacity** provides retry/backoff, **structlog** structured logging, and **Pydantic + pydantic-settings** load/validate a **TOML config + `.env` secrets**. Deferred channel SDKs (`twilio`, `python-telegram-bot`) stay out of v1 dependencies. See `.planning/research/STACK.md`.

**Core technologies:**
- **Python 3.12+ / uv**: language + packaging — best library coverage for scheduling/HTTP/Discord/Twilio/Telegram; `uv` is the 2026 standard, trivial on a Pi.
- **APScheduler 3.11.x**: in-process scheduler — `CronTrigger` natively expresses "09:00 Mon-Fri" with a per-job `timezone=`; one cron job per (location, send-time).
- **httpx 0.28.x**: HTTP client — clean explicit timeouts so the process never hangs on a slow OpenWeather response; one path to async for future channels.
- **discord-webhook 1.4.x**: v1 delivery — outbound webhook only, no bot token or gateway connection (lighter than `discord.py`).
- **Jinja2 3.1.x**: user-editable templates with `{{ temp }}`/`{{ high }}`/`{{ rain }}` placeholders (rendered with guards against bad placeholders).
- **Pydantic / pydantic-settings 2.x**: validate config at boot, fail loudly; layer `.env` secrets over a TOML config so keys never live in the committed file.
- **tenacity 9.x + structlog 26.x**: bounded retry-then-alert; structured logging for diagnosing a 3 AM silent failure on a headless Pi.

### Expected Features

WeatherBot is firmly a **personal briefing daemon**, so many "table stakes" of public multi-tenant Discord weather bots (slash commands, dashboards, per-user defaults, anti-spam) are explicit **anti-features** here. See `.planning/research/FEATURES.md`.

**Must have (table stakes):**
- Core forecast content (temp, today's high/low, conditions, rain %, wind, humidity) — this *is* the briefing.
- Multiple independent locations (>=2) with pre-resolved lat/lon — the central use case.
- Per-location, multi-time, toggleable schedules **with day-of-week** — models the weekday/weekend split.
- IANA timezone per location + always-on in-process scheduler — "morning" must mean local morning, DST-safe.
- Units (metric/imperial) per location — raw Kelvin is unusable.
- Editable template with named placeholders; Discord webhook behind a `Channel` interface.
- Retry-then-alert on failure; file-based config + secrets via `.env`; validate-on-load + `--send-now` dry-run.

**Should have (competitive / v1.x):**
- Out-of-band failure-alert sink (so a Discord outage doesn't swallow its own alert).
- Liveness/heartbeat ping — distinguishes "no weather today" from "crashed days ago."
- Derived/actionable fields (feels-like, umbrella/coat hint, sunrise/sunset, UV).
- Passive severe-weather line (surface any active `alerts[]` inside the scheduled briefing — no new polling loop).
- Telegram channel (validates the abstraction with a second free channel).

**Defer (v2+):**
- SMS via Twilio — paid provider + number setup; only when push-to-phone is proven.
- Real-time severe-weather push alerts — a separate product from morning briefing.
- Config hot-reload; multi-week/hourly views; slash commands / GUI / multi-user / history DB (anti-features).

### Architecture Approach

A one-way `scheduler -> producer -> renderer -> dispatcher` pipeline over a config layer, with retry-then-alert as a cross-cutting concern. Config is loaded and validated **once at boot** into immutable typed objects; nothing re-reads raw config or `os.getenv` later. The `weather/`, `templates/`, and `channels/` units are siblings that don't import each other — that independence is what makes channels swappable. The `channels/factory.py` + `base.py` registry is the pluggability seam: adding SMS/Telegram is one new file + one config entry, zero changes elsewhere. See `.planning/research/ARCHITECTURE.md`.

**Major components:**
1. **Config layer** (Pydantic over TOML + `.env`) — load, validate, fail loudly at boot; produce typed objects.
2. **Scheduler** (APScheduler) — expand `locations x send-times x days x tz` into cron jobs firing `send_job`.
3. **Weather data layer** (httpx client + TTL cache keyed by `(lat,lon)`) — return a normalized `Forecast`; hide endpoint/HTTP/JSON and the bucket-aggregation.
4. **Template renderer** — pure function, `Forecast` + template -> text, no I/O.
5. **Channel dispatch** — `Channel.send(text) -> DeliveryResult`, one class per provider behind a factory.
6. **Reliability wrapper** (tenacity) — retry fetch + send with backoff; on exhaustion, route to an independent alert channel.

**Suggested build order** (architecture): config -> weather -> renderer -> channel+Discord -> `send_job` (manually-invokable end-to-end briefing, the highest-value early checkpoint) -> scheduler -> reliability -> cache/dedup -> later channels.

### Critical Pitfalls

Top items from `.planning/research/PITFALLS.md` — all failure-mode, not throughput:

1. **Scheduling in UTC/naive local time** — wrong hour, and DST breaks twice a year (skipped spring-forward fire, doubled fall-back fire); home and travel cities may differ entirely. Store `(local time + IANA zone)`, use tz-aware triggers, keep sends out of the 1-3 AM DST window, and dedup by `(location, slot, local-date)`.
2. **Wrong OpenWeather endpoint / subscription assumption** — One Call 3.0 needs a card and returns 401/403 without the subscription; deprecated 2.5 `onecall` dies on retirement. Default to free 2.5 `weather` + `forecast` with bucket aggregation, isolate the endpoint in one client module, and probe on startup.
3. **Daemon dies on one unhandled exception and stays dead** — silent for days. Top-level try/except per job, a supervisor with `Restart=always`, a startup "online" heartbeat, and defensive `.get()` parsing of an untrusted payload (`rain` is absent on clear days).
4. **Restart/reboot replay** — missed or stacked-burst briefings. Recompute schedule from config on every startup, enforce the persisted dedup key, keep `misfire_grace_time` short, enable coalescing, and document a backfill-vs-skip policy (e.g. send if <90 min late, else skip).
5. **Retry storm / alert-loop** — unbounded retries burn the quota and trip 429; alerting via the failing channel can't reach the user. Bounded exponential backoff + jitter, honor `Retry-After`, never retry 401/403, and make the alert path independent and fire-and-forget.
6. **Secrets committed/logged** (foundational) — key + webhook URL in git, config, or log output. Separate secrets into a git-ignored `.env` before the first key, redact request URLs in logs, `chmod 600` on the Pi.

## Implications for Roadmap

Based on combined research, the natural phase structure follows the dependency-driven build order, front-loading the two foundational concerns (tz model + secrets) and reaching a manually-sendable end-to-end briefing *before* scheduling.

### Phase 1: Foundation — Config + Secrets
**Rationale:** Everything downstream receives typed, validated config; secrets separation must exist before any real key is introduced (retrofitting is a security/migration cost). Both research-flagged as foundational.
**Delivers:** Pydantic config models (`Location` with IANA `timezone` + `units`, `ScheduleSlot` with `days`/`enabled`, channels, template), TOML loader + `.env` secrets, `config.example.toml`, `.env.example`, `.gitignore` for secrets, validate-on-load with loud failure.
**Addresses:** "Editable config without code changes," per-location units, the schedule data model (tz + day-of-week fields baked in from day one).
**Avoids:** Pitfall 7 (secrets), and pre-empts Pitfall 1 by putting IANA tz + day-of-week into the schema before any schedule is stored.

### Phase 2: Weather Data Layer (incl. aggregation spike)
**Rationale:** The `Forecast` model is depended on by both the renderer and `send_job`; the endpoint/subscription decision must be resolved before the template, since available fields depend on it.
**Delivers:** `httpx` OpenWeather client (free 2.5 `weather` + `forecast`), normalized `Forecast` dataclass, **the 3-hour-bucket -> today's high/low/rain aggregation** (the flagged spike, with fixtures), startup live-probe distinguishing auth/subscription errors, defensive parsing of optional fields. Cache can be a stub here.
**Uses:** httpx, tomllib/Pydantic config from Phase 1.
**Implements:** Weather data layer component.
**Avoids:** Pitfalls 2 (endpoint/subscription), 6 (call discipline), 8 (key-activation delay messaging); the "looks done but isn't" daily-fields trap.

### Phase 3: Rendering + Discord Delivery + send_now
**Rationale:** With config + a real `Forecast`, the renderer and the first channel complete a manually-invokable end-to-end briefing — the highest-value early checkpoint, shippable as a CLI before scheduling exists.
**Delivers:** Guarded Jinja2 renderer (plain-text-first, whitelisted placeholders, never crashes the send), `Channel` ABC + `DiscordWebhookChannel` + factory/registry, `send_job` composition, `--send-now <location>` dry-run.
**Addresses:** Editable templates, Discord webhook behind the channel abstraction, dry-run tester.
**Avoids:** Template-injection/format-string abuse, the "channels format their own messages" anti-pattern, over-building the abstraction (minimal interface, one concrete channel).

### Phase 4: Scheduler (tz-aware, day-of-week, dedup)
**Rationale:** Turns the manual pipeline into the always-on daemon; depends on Phases 1-3. The hardest correctness surface in the project.
**Delivers:** APScheduler config-as-jobs expansion (one `CronTrigger` per `(location, send-time, days, tz)`), per-location timezone, persisted `(location, slot, local-date)` dedup, schedule recomputed from config on startup, short misfire grace + coalescing.
**Uses:** APScheduler 3.x.
**Avoids:** Pitfalls 1 (DST/tz) and 4 (restart/reboot replay).

### Phase 5: Reliability — Retry-then-Alert
**Rationale:** Wraps already-working fetch + send calls, so it layers cleanly last; the alert-independence decision is an explicit design point, not an afterthought.
**Delivers:** tenacity bounded backoff + jitter, retryable/non-retryable distinction (never retry 401/403), `Retry-After` honoring, independent fire-and-forget alert path, loop-survives-exception hardening.
**Avoids:** Pitfalls 3 (loop survival) and 5 (retry storm / alert loop).

### Phase 6: Deployment + Hardening
**Rationale:** Reliability of "every morning" depends on supervision and reboot survival, which are ops concerns verified end-to-end.
**Delivers:** `systemd` unit (`Restart=always`, `WantedBy=multi-user.target`, `EnvironmentFile=.env`) or Docker `restart: unless-stopped`, rotating logs, startup "online" heartbeat, reboot/crash-recovery verification.
**Avoids:** Pitfall 3 (supervision/reboot), unbounded-logfile and fd-leak performance traps.

### Phase Ordering Rationale
- **Dependency-driven:** config -> leaf services (weather, render, channel) -> composition (`send_job`) -> scheduler -> reliability -> deployment, matching the architecture's suggested build order. End-to-end "send one briefing now" is reachable at Phase 3, before scheduling.
- **Foundational concerns front-loaded:** the tz model and secrets separation are placed in Phase 1 because all four dimensions agree retrofitting them is a data migration, not a tweak.
- **Reliability/dedup deliberately late:** they wrap already-working code (reliability) or only matter once multiple jobs fire (dedup is introduced with the scheduler in Phase 4), so they don't block the early end-to-end checkpoint.
- **Anti-features excluded entirely:** slash commands, GUI, multi-user, history DB — never roadmapped.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Weather Data Layer):** the **3-hour-bucket aggregation** is the trickiest unit-testable piece and the highest-risk correctness surface — worth a focused `--research-phase` spike with recorded JSON fixtures (clear-sky/no-rain, rainy, local-midnight boundary, units).
- **Phase 4 (Scheduler):** DST and restart/replay semantics are subtle; APScheduler misfire/coalescing behavior and the dedup-key design merit phase research even though the library is well-documented.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Config):** Pydantic + TOML + `.env` is a well-trodden pattern.
- **Phase 3 (Rendering + Discord):** Jinja2 rendering and a single webhook POST are well-documented; the only nuance (guarded placeholders, plain-text-first) is already captured.
- **Phase 5 / Phase 6:** tenacity backoff and `systemd` supervision are established patterns documented in the research.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Library choices + versions verified against PyPI (2026-06-09) and official docs; OpenWeather/APScheduler caveats confirmed from source. |
| Features | HIGH | Table-stakes and API facts verified against OpenWeather docs and multiple real bot implementations. Differentiator/anti-feature framing is MEDIUM (reasoned from the single-user constraint), but well-grounded. |
| Architecture | HIGH | Standard scheduler->fetch->render->dispatch pipeline; APScheduler tz/trigger and tenacity behavior verified against official docs. |
| Pitfalls | HIGH | OpenWeather subscription model, DST scheduling, Discord rate limits, and APScheduler misfire semantics all verified against official/vendor sources. |

**Overall confidence:** HIGH

### Gaps to Address

- **Endpoint default reconciled, but aggregation unproven:** the free-2.5 + bucket-aggregation path is the chosen default; its correctness (matching what a user would call "today's high/low") is the one piece that must be validated with real fixtures during Phase 2, not assumed.
- **OpenWeather free-tier enforcement / key activation:** 2025-2026 stricter 60/min enforcement and up-to-~2-hour new-key activation are MEDIUM-sourced operational facts — surface them in setup docs and the startup probe so a fresh-key 401 isn't misdiagnosed.
- **Backfill-vs-skip policy is a decision, not a finding:** research recommends "send if <90 min late, else skip" but the exact window is a product call to confirm during Phase 4 planning.
- **Out-of-band alert sink for a single-channel v1:** if Discord is the only channel, the truly-independent alert path degrades to "conspicuous local log + process health signal + the supervisor + the user noticing." Confirm what "independent enough" means for v1 vs deferring a second channel.

## Sources

### Primary (HIGH confidence)
- OpenWeather official docs — One Call 3.0 (subscription + card, 1,000/day), 2.5->3.0 transfer/deprecation, current + 5-day/3-hour forecast endpoints, `pop` semantics, units default Kelvin, new-key activation delay.
- APScheduler 3.x official docs — `CronTrigger` `day_of_week` + per-job `timezone`, `BackgroundScheduler`, `misfire_grace_time`/coalescing/jobstore semantics, 4.0 not for production.
- Discord developer docs — webhook rate limits (~30 msg/min per webhook, 429 + `Retry-After`).
- tenacity official docs/repo — exponential backoff, stop conditions, retry-on-exception.
- PyPI version checks (2026-06-09) — apscheduler 3.11.2, httpx 0.28.1, discord-webhook 1.4.1, tenacity 9.1.4, pydantic 2.13.4, pydantic-settings 2.14.1, jinja2 3.1.6, structlog 26.1.0, uv 0.11.19.

### Secondary (MEDIUM confidence)
- apiscout.dev — OpenWeather free-tier limits 2026 (60/min, 1M/month, stricter enforcement, ~2h activation); corroborates official.
- Cron/scheduler DST guides (cronjob.live, healthchecks.io, cronmonitor) — spring-forward skip / fall-back double-run, store IANA ids.
- OneUptime heartbeat / dead-man's-switch — alert via a path independent of the monitored thing.
- Real bot implementations (smmhrdmn/WeatherBot, yannickkirschen, lacanlale, Meshbot_weather, discordbotlist Weather Bot) — schedule+tz model, multi-location, units-config gap, plain-text vs embed patterns.

### Tertiary (LOW confidence)
- Domain experience (process supervision, retry-then-alert independence, format-string injection) — corroborated across the above and general practice; the backfill-vs-skip window and v1 alert-independence threshold are inferences to confirm during planning.

---
*Research completed: 2026-06-09*
*Ready for roadmap: yes*
