# Milestones

## v1.3 Discord Control Panel (Shipped: 2026-06-27)

**Phases completed:** 5 phases (16–20), 11 plans, 12 tasks
**Timeline:** ~4 days (2026-06-23 → 2026-06-27) · ~10k LOC `weatherbot/` + ~16.4k LOC `tests/` · 649 tests green · 18 feat commits
**Requirements:** 13/13 v1.3 requirements satisfied (audit: passed — see milestones/v1.3-MILESTONE-AUDIT.md)

**Delivered:** The bot is now tap-to-drive — a pinned, restart-durable Discord control panel (location dropdown + emoji-coded command grid + always-visible 2×2 forecast grid) renders every read-only command result in-place, operator-gated, as a third caller of one shared `dispatch_spec` core so the panel can never drift from the real command set. A pure UI layer: no new weather data, no new dependencies, no new gateway intent — and the briefing spine's failure-isolation re-proven for the interaction path. Gate-2 live UAT driven on host `yahir-mint` at close (found+fixed 1 production bug, +2 UX refinements: `!panel` re-summon-to-bottom 260626-uqp, always-visible forecast grid 260626-u8y).

**Key accomplishments:**

- `weather` is now a real registry CommandSpec routing through the shared dispatch_spec → render_embed ladder, byte-identical to build_inbound_embed (Now / High·Low / Rain), with a CLI skip-guard that prevents the new spec from crashing the entire CLI via an argparse subparser collision.
- A persistent operator panel (`PanelView`) wiring tap-to-drive Discord components onto the Phase-16 `dispatch_spec` seam — single-ack defer-then-edit, operator-gated interaction_check, and per-callback failure isolation, all 11 `test_panel.py` nodes GREEN.
- Restart-durable panel foundation: required `[bot] panel_channel_id` threaded daemon→BotThread→client, PanelView registered via `add_view` in `setup_hook` (not `on_ready`), and the `_is_owned_panel`/`wb:` marker matcher + Wave-0 pins/Permissions fakes the Plan-02 `!panel` summon will consume.
- Idempotent `!panel` lifecycle summon (PANEL-01): an operator-gated `on_message` branch (D-07, NOT via `dispatch_spec`) that resolves `[bot] panel_channel_id` (abort-not-crash, D-04), eagerly preflights the exact D-10 permission set (`pin_messages`, NOT `manage_messages`), scans `channel.pins()` via `async for` for bot-owned panels (`_is_owned_panel`, D-03/D-05), reuses the first in place + deletes the strays (D-06) or posts+pins a fresh panel — always reconciling to exactly one — with a per-write `discord.Forbidden` TOCTOU backstop (D-09) and prescribed operator-feedback copy.
- Two test-only proofs closing PANEL-11's hanging case: a live `BackgroundScheduler` sentinel briefing keeps firing while a panel `on_command` callback is wedged on `await asyncio.Event().wait()`, and a structural audit confirms the briefing spine never borrows the asyncio default executor the panel's read-only fetch uses — zero `weatherbot/` change.

---

## v1.2 Forecasts, Commands & UV (Shipped: 2026-06-20)

**Phases completed:** 4 phases, 15 plans, 34 tasks

**Delivered:** A self-describing command registry powering a full read-only command surface, multi-day forecast templates, and end-to-end UV awareness — on-demand, in the daily briefing, and via a proactive intraday monitor — all failure-isolated from the briefing spine.

**Key accomplishments:**

- **Phase 12 — Command registry & read-only surface (CMD-09…16):** one self-describing `registry.COMMANDS` list auto-derives the CLI subparsers, Discord dispatch, and `help` (no second hardcoded list); seven read-only commands (`help`/`locations`/`status`/`sun`/`wind`/`alerts`/`next-cloudy`); the One Call `exclude` widened to retain `hourly[]` as the shared data seam — all behind the existing operator guard ladder + failure-isolation envelope.
- **Phase 13 — Multi-day forecast templates (FCAST-01…07):** weekday (Mon–Fri) and weekend (Fri–Sat–Sun) forecasts in detailed/compact variants with additive `+day`/`-day` flags, on demand (CLI + Discord) and per-location scheduled, rendered from editable templates reusing the already-fetched `daily[]` — no extra API call, zero store writes.
- **Phase 14 — UV index on-demand & in the briefing (UV-01…03):** a pure interactive-layer-free `compute_uv()`/`UvSummary` (current / today's max / WHO category / interpolated threshold-crossing time / sunset-bounded protect window), the `uv <loc>` command on both surfaces, a UV section in the daily briefing, and a configurable `[uv]` threshold + pre-warn lead — with a briefing-spine isolation gap (UV math crashing a briefing on a malformed payload) caught and fixed at two layers.
- **Phase 15 — Proactive UV sunscreen monitor (UV-04…06):** an `__uvmonitor__` IntervalTrigger watching today's active location(s) during daylight, firing pre-warn / crossing / all-clear alerts at most once per day per location (durable `uv_alerts` dedup table, atomic claim), failure-isolated from the briefing spine (two-layer envelope + `max_instances=1`, proven on a live scheduler).
- **Quality:** 575 tests passing on `main`; every phase research-resolved → plan-checked → goal-verified → code-reviewed with all findings fixed (1 critical + 21 warnings across the milestone); all 5 cross-phase integration seams wired (1 integration gap — `status` monitor liveness — found and fixed during the audit).

**Known deferred items at close:** 4 host UATs require one deploy + `systemctl restart weatherbot` on `yahir-mint` (see STATE.md Deferred Items / `<N>-UAT.md`, run via `/gsd-verify-work <N>`).

---

## v1.1 Interactive & Live-Config (Shipped: 2026-06-19)

**Phases completed:** 6 phases (6–11), 22 plans, 29 tasks
**Timeline:** ~4 days (2026-06-15 → 2026-06-18) · ~13.5k LOC Python · 291 tests green
**Requirements:** 16/16 v1.1 requirements satisfied (audit: passed — see milestones/v1.1-MILESTONE-AUDIT.md)

**Delivered:** The always-on briefing daemon became interactive and live-editable — on-demand `weather <location>` lookups over a standalone CLI and an isolated Discord gateway bot, plus full config hot-reload (explicit trigger + debounced file-watch), all without regressing v1.0's "the morning briefing always goes out, exactly once" guarantee.

**Key accomplishments:**

- **Shared lookup core & command parser (Phase 6):** extracted one read-only fetch→render core (`lookup_weather` → `LookupResult`, provably zero sent-log/alert/heartbeat writes) and one pure three-state `weather <loc>` parser, so the CLI and Discord bot call identical code with identical semantics; `send_now` delegates to it byte-identically.
- **Standalone CLI one-shot (Phase 7):** `weatherbot` became a real installed console command (hatchling `[build-system]` + `[project.scripts]`) with argparse subcommands; `weatherbot weather [location]` prints a configured location's v1 briefing with no daemon, a clean 0/1/2/3 exit contract, and quiet-by-default logging (CMD-01/03/04/05).
- **ConfigHolder & fire_slot refactor (Phase 8):** a lock-guarded `ConfigHolder` hands out immutable snapshots (all 5 config models `frozen=True`) and `fire_slot` reads `holder.current()` once per job — the correctness prerequisite that lets a later reload actually change what unchanged jobs render, proven by concurrent read/swap and mid-job-snapshot tests.
- **Reload engine & explicit trigger (Phase 9):** `_do_reload` validates → atomic holder swap → diff-reconciles jobs by stable `(location, send_time, days)` id via SIGHUP / `weatherbot reload`, keeping the old config on any failure; the exactly-once key moved name→stable `location.id` (zero-migration) so a name/tz edit on an already-sent slot never double-fires or skips. Ships an offline `check-config` dry-run (CFG-01/02/04/05/06/08).
- **File-watch auto-reload (Phase 10):** a single long-lived watchfiles observer debounces editor save-storms and funnels saves through the same Phase 9 `_do_reload`; `.env` is never watched, the watch set re-derives on each successful reload, and the observer tears down sub-second on SIGTERM (CFG-03).
- **Discord inbound gateway bot (Phase 11):** an isolated `BotThread` (started after the systemd READY signal, torn down in `finally`) answers `!weather <loc>` with an embed reply via an off-loop fetch behind a guard ladder + short-TTL `ForecastCache`, can never stop a scheduled briefing or flip READY, and posts every reload outcome to Discord (CMD-02/06/07/08, CFG-07).

**Tech debt carried forward (non-blocking, see v1.1-MILESTONE-AUDIT.md):** Phase 9 advisory hardening (`/proc`-absent fail-open, rollback re-invokes failing `_register_jobs`); Phase 11 `[bot] operator_id` / `[reload] watch` are restart-deferred (within CFG-01's enumerated scope; secret/token hot-reload is explicitly Out of Scope).

**Known deferred items at close:** 0 blockers. All 3 pre-close audit flags were stale tracking status on completed-and-verified work (Phase 11 UAT, quick-260617-fua cache-invalidate wiring, quick-260617-idm PID-file fix) — statuses corrected before close.

---

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
