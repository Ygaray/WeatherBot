# Milestones

## v1.0 WeatherBot MVP (Shipped: 2026-06-15)

**Phases completed:** 5 phases, 21 plans, 36 tasks
**Timeline:** 11 days (2026-06-04 → 2026-06-15) · ~7.9k LOC Python · 186 tests green
**Requirements:** 37/37 v1 requirements satisfied (audit: passed — see milestones/v1.0-MILESTONE-AUDIT.md)

**Delivered:** A hands-off, always-on morning weather-briefing daemon — correct, correctly-located briefings fetched from OpenWeather, persisted to SQLite, rendered imperial/metric-primary, delivered to Discord on a per-location DST-safe schedule, with retry-then-alert reliability, and reboot survival under systemd (confirmed live on host `yahir-mint`).

**Key accomplishments:**

- **End-to-end briefing pipeline (Phase 1):** config+secrets → OpenWeather fetch → SQLite persistence → imperial/metric-primary render → Discord webhook, behind a pluggable `Channel.send(text)` seam reused by both manual and scheduled paths; proven live against the real API and webhook.
- **Real multi-location config (Phase 2):** ≥2 independent locations with per-location IANA timezone + units override, feels-like + threshold hints + passive severe-weather alert line, safe editable templates with fail-loud validation, and `--check`/`--geocode`/`--send-now` CLI. Migrated the data source to OpenWeather One Call 3.0.
- **Always-on scheduler (Phase 3):** APScheduler daemon firing per-location local wall-clock times, DST exactly-once (spring-forward gap skip + fall-back fold), 90-min missed-send catch-up, and atomic `claim_slot` idempotency per `(location, slot, local-date)`.
- **Retry-then-alert reliability (Phase 4):** two-burst tenacity backoff honoring `Retry-After` (never retries 401/403), an out-of-band log+DB alert path independent of Discord (dedup, no loop), periodic heartbeat, and per-job exception isolation.
- **Reboot survival (Phase 5):** startup self-check gate + `sd_notify` READY=1 online signal under a `Type=notify`/`Restart=always` systemd unit — READY=1 reaches systemd only after the self-check passes; live post-reboot auto-start confirmed on host `yahir-mint`.

**Known deferred items at close:** 0 blockers. One non-critical wording note carried forward (see v1.0-MILESTONE-AUDIT.md): DATA-03 delivered-only persistence semantics, to confirm when v2 analysis reads the store.

---
