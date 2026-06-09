---
phase: 01-first-briefing-end-to-end
plan: 04
subsystem: delivery
tags: [discord, discord-webhook, channel-abstraction, cli, composition-root, send-now]

# Dependency graph
requires:
  - phase: 01-01
    provides: load_config, load_settings, resolve_location, WebhookIdentity, discord_webhook_url
  - phase: 01-02
    provides: OpenWeather client (fetch_current/fetch_forecast), Forecast.from_payloads, placeholders()
  - phase: 01-03
    provides: SQLite store persist(), load_template, render() guarded plain-text renderer
provides:
  - Channel ABC with send(text) -> DeliveryResult (provider-agnostic delivery seam)
  - DiscordWebhookChannel (text via send(); embed built internally via send_briefing)
  - build_channel(config, settings) registry factory (default "discord")
  - send_now(location) composition root — single fetch feeds persist + render + deliver
  - --send-now [location] CLI entrypoint (python -m weatherbot)
affects: [phase-2-real-config, phase-3-scheduler, phase-4-reliability, sms-telegram-channels]

# Tech tracking
tech-stack:
  added: [discord-webhook]
  patterns:
    - "Channel.send(text) is the SMS/Telegram-ready seam; Discord embed never crosses it (DELV-03)"
    - "Composition root (send_now) wires fetch -> persist -> render -> deliver from ONE fetch (DATA-03)"
    - "Registry-dict channel factory keyed by type so new channels are construction-only"
    - "send path logs outcome only — never the webhook URL or appid (T-04-01)"

key-files:
  created:
    - weatherbot/channels/__init__.py
    - weatherbot/channels/base.py
    - weatherbot/channels/discord.py
    - weatherbot/channels/factory.py
    - weatherbot/cli.py
    - weatherbot/__main__.py
    - tests/test_channel.py
  modified:
    - tests/test_send_now.py

key-decisions:
  - "Embed lives only inside send_briefing(text, forecast); send(text) takes str only (DELV-03 / T-04-03)"
  - "Bare --send-now (no location) resolves to the first configured location (D-07)"
  - "DeliveryResult(ok=False, detail=...) on non-2xx — expected failure returns a value, does not raise"

patterns-established:
  - "Provider-agnostic delivery: orchestration handles a str body; Discord-only enrichment stays inside the channel"
  - "Single-fetch dual-consumer: the same Forecast object is passed to both persist and render"

requirements-completed: [DELV-01, DELV-02, DELV-03, CONF-04]

# Metrics
duration: ~40min
completed: 2026-06-09
---

# Phase 1 Plan 4: Channel/Discord Delivery + `--send-now` Composition Summary

**Pluggable `Channel.send(text)` seam with `DiscordWebhookChannel` (embed kept internal) and the `send_now` composition root wiring fetch→persist→render→deliver from a single fetch — proven live end-to-end against the real OpenWeather API and Discord webhook.**

## Performance

- **Duration:** ~40 min (across the initial execution + this closeout)
- **Completed:** 2026-06-09
- **Tasks:** 3 (2 code/test, 1 live human-verify checkpoint)
- **Files modified:** 8 (7 created, 1 modified)

## Accomplishments

- `Channel` ABC + `DeliveryResult` dataclass — a provider-agnostic `send(text) -> DeliveryResult` seam ready for SMS/Telegram (DELV-02).
- `DiscordWebhookChannel` delivers the canonical plain-text body via `send(text)` under the custom `WeatherBot ☀️` identity + avatar; `send_briefing(text, forecast)` additionally builds the Discord embed — which never crosses the `send(text)` interface (DELV-01/DELV-03).
- `build_channel(config, settings)` registry factory selects the channel by `type` (default `"discord"`), making future channels construction-only.
- `send_now(location)` composition root: resolves the location, fetches ONCE (current+forecast in both unit systems), then feeds that SAME `Forecast` to `persist` and `render` (no second OpenWeather call — DATA-03) and delivers via `send_briefing`.
- `--send-now [location]` CLI wired via argparse + `python -m weatherbot`; the Plan 01 end-to-end test went from strict-xfail to green.
- **Live smoke verified (human-approved):** a correct briefing posted to Discord; persistence and secret hygiene confirmed (see Checkpoint section). The Walking Skeleton is proven end-to-end.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing Channel/DiscordWebhookChannel tests** - `a4b0d78` (test)
2. **Task 1 (GREEN): Channel ABC + DiscordWebhookChannel + build_channel factory** - `4c9037e` (feat)
3. **Task 2: send_now composition root + --send-now CLI; e2e test green (xfail removed)** - `c1b325a` (feat)

_Task 3 was a blocking live human-verify checkpoint — no code commit (verification only)._

**Plan metadata:** committed with this SUMMARY (docs: complete plan).

## Files Created/Modified

- `weatherbot/channels/__init__.py` - Package init for the delivery channel layer.
- `weatherbot/channels/base.py` - `Channel` ABC (`send(text) -> DeliveryResult`) + `DeliveryResult` dataclass. Contains NO `DiscordEmbed` (interface kept Discord-free — grep-verified).
- `weatherbot/channels/discord.py` - `DiscordWebhookChannel`: `send(text)` posts content only; `send_briefing(text, forecast)` builds + attaches the embed internally; both route through private `_post`; non-2xx → `DeliveryResult(ok=False)`.
- `weatherbot/channels/factory.py` - `build_channel(config, settings)` registry-dict factory keyed by channel type (default `"discord"`).
- `weatherbot/cli.py` - `send_now(...)` composition root + `main(argv)` argparse for `--send-now [location]`; logs outcome without secrets.
- `weatherbot/__main__.py` - `python -m weatherbot` entrypoint calling `main()`.
- `tests/test_channel.py` - Channel/Discord unit tests (offline, mocked webhook): signature inspection, embed isolation, custom identity, failure-returns-value, no-secret-in-logs.
- `tests/test_send_now.py` - Integration test completed and xfail marker removed: single fetch round feeds both persist and render; channel receives the rendered plain-text body; rows written to both tables.

## Decisions Made

- **Embed isolation:** the Discord embed is constructed only inside `send_briefing`/`_post`; `send(text)` accepts `str` only and `base.py` has zero `DiscordEmbed` references — keeping the interface SMS/Telegram-portable (DELV-03 / threat T-04-03).
- **Bare `--send-now`** with no location argument resolves to the first configured location (D-07).
- **Expected delivery failure returns a value** (`DeliveryResult(ok=False, detail=...)`) rather than raising, so the future retry/alert layer (Phase 4) can branch on it cleanly.

## Deviations from Plan

None - plan executed exactly as written.

## Checkpoint: Task 3 — Live End-to-End Smoke (blocking human-verify) — APPROVED

The blocking live-send checkpoint was performed against the real OpenWeather API and Discord webhook and **approved by the human**. Verified evidence:

- **Discord delivery succeeded:** `discord delivery ok status=200`; `send_now complete delivered=True location=Home`; process exit 0.
- **Correct briefing rendered** in the Discord channel under the `WeatherBot ☀️` identity — current temp, today's high/low, sky conditions, rain %, wind, humidity; imperial-primary with metric in parentheses.
- **Persistence from the SAME fetch (DATA-03):** `weather_current` has 2 rows (imperial + metric, `local_date 2026-06-09`); `weather_forecast` has 80 bucket rows. No extra OpenWeather call was made to persist.
- **Secret hygiene (T-04-01/02):** the API key, webhook URL, and `appid` are ALL absent from `data/weatherbot.db`; logs leak no secret; git tracks no `.env`/secrets/`data/`.

The gate's three acceptance criteria (correctly-located imperial-primary briefing under the custom identity; fetch row(s) in the SQLite store; no key/webhook URL in logs or git) are all satisfied.

> Note: per closeout instructions, no additional live `--send-now` was run during this closeout to avoid spamming the user's Discord — the human's verification stands.

## Issues Encountered

None during this closeout. The automated suite is green (52 passed) and `ruff check .` reports all checks passed.

## User Setup Required

None new for code. As documented in the checkpoint, live operation requires a populated `.env` (`OPENWEATHER_API_KEY`, `DISCORD_WEBHOOK_URL`) and a `config.toml` with at least one location — both already provided by the user during the live verification.

## Next Phase Readiness

- **Phase 1 is complete (4/4 plans).** The full pipeline — config + secrets → fetch (bucket-aggregated) → SQLite persistence → imperial-primary render → Discord delivery via `Channel.send(text)` → `--send-now` — runs and is verified live end-to-end.
- The provider-agnostic `Channel` seam is ready for Phase 2+ and the deferred SMS/Telegram channels.
- The `send_now` composition root is the natural call target for Phase 3's scheduler.
- Carried concern (STATE.md): Phase 4 must define what "independent enough" means for the out-of-band alert path in a single-channel v1.

## Self-Check: PASSED

- Prior task commits present: `a4b0d78`, `4c9037e`, `c1b325a` (all FOUND).
- All 8 plan files exist on disk (7 created + `tests/test_send_now.py` modified).
- Embed isolation: `base.py` has 0 `DiscordEmbed` references.
- `tests/test_send_now.py` has no active `xfail` marker (lone match is a historical docstring note).
- Suite green: 52 passed; `ruff check .` all checks passed.

---
*Phase: 01-first-briefing-end-to-end*
*Completed: 2026-06-09*
