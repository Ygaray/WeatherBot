# Milestones

## v2.1 Hardening (Shipped: 2026-07-17)

**Phases completed:** 7 phases, 37 plans, 42 tasks

**Key accomplishments:**

- RED executable contracts pinning the fatal-vs-clean daemon exit distinction, the AUTH_FAILED-stays-non-fatal D-03 guard, the F90/F07 observability fixes, the F89 streak-prune, and the static D-05 systemd restart-policy directives — before any production code lands in 29-03/05/06.
- Split the self-check's pre-probe config/template/empty-locations checks into their own CONFIG_INVALID (CRITICAL) branch so a permanent config fault stops warn-looping as a fake NETWORK_NOT_READY network fault, and re-exported the reason onto the daemon namespace for the 29-05 fatal hook.
- 1. [Rule 3 - Blocking] `daemon.build_runtime` monkeypatch did not bite the local import
- Task 1 — `deploy/weatherbot.service` restart policy (D-05, HARD-STARTUP-02/03).
- The OpenWeather appid is now unreachable in any surfaced error: redacted at both client.py raise sites via a type-preserving `HTTPStatusError(...) from None` re-raise and scrubbed again at the `_LiveStderr` stderr choke point — belt-and-suspenders (D-01 + D-02) delivering HARD-SEC-01.
- Shared `_connect()` helper with persistent WAL + per-connection busy_timeout, `init_db` made the sole schema owner, and the four status reads opened `mode=ro` so a read concurrent with a daemon write no longer raises `database is locked` (F10) — de-risking the F01 duplicate-briefing critical.
- Closed the two send-detection seams in `daemon.py`, F01 verify-first: the post-send bookkeeping tail is now a log-and-swallow so a `database is locked` error after a delivered briefing keeps the won claim (no duplicate, no false `internal_error`), and `fire_forecast_slot` now inspects `channel.send()`'s `DeliveryResult` so a Discord `ok=False` routes to the WR-05 dead-slot escalation instead of silently resetting the streak.
- Two coupled send-path corrections landed with zero hub changes: DELIV-03 makes a delivery-only retry reuse the ONE already-fetched payload (a single-slot `fetch_cache` threaded through the retried `send_now`, so `lookup_weather` runs exactly once per fire while a fetch-429 still raises pre-cache and honors Retry-After), and DELIV-04 makes app-side `discord._post` raise a REDACTED `httpx.HTTPStatusError` on 401/403 that lands in the existing `daemon.py:263` arm → `auth_failed`, short-circuiting the retry in ~1 attempt instead of burning the full ~65-min schedule as `transient_exhausted`.
- Authored nine failing-first (RED) regression tests (10 functions across five test files) that pin every locked timezone/date-boundary decision (D-01..D-08) — including both CONFIRMED scenarios (F14 catch-up-across-midnight, F15 UV all-clear latch) — with the F31 test made un-cheatable by asserting stays_below/crossing_time instead of max.
- 1. [Rule 3 - Blocking] Repointed pre-existing store test off deleted `store._local_date_iso`
- 1. [Rule 3 - Orchestrator override] Did NOT implement the plan's mandated both-folds `min()` grace comparison (D-02/F91)
- 1. [Rule 1 - Bug] Re-dated golden/oracle fixtures exposed by the correct F35 selector
- Task 1 — All-clear window-end hysteresis (D-03/F15) + D-08 helper swap
- Task 1 — RED regressions (`cba3bb3`)
- Panel never freezes on an empty config (zero-locations degrades to a disabled placeholder Select instead of recursing into a swallowed ValueError) and never silently advances the selection on a failed/expired interaction ack (roll-back + re-raise) — both cured app-side against the frozen hub.
- Forecast header de-duplicated to once-per-surface (F28), empty-token blank lines collapsed in the shared renderer, out-of-today date labels humanized to 'Wed Jun 24' (D-06), and status/next-fires timestamps humanized to local 24h '09:00' (D-07) — leaving the embed `<t:>` relative markdown untouched — closing HARD-UI-03.
- 1. [Rule 3 — Blocking] Updated two existing `_fmt_epoch` unit-test callers
- Corrected two false-green reliability tests (F114 tick/success separation, F112 constant-derived within-burst ceiling) and added the missing F110 Retry-After-collapses-mid-pause regression — all tests-only, hub source untouched.
- Two assertion-by-construction pinning tests in `tests/test_multiday.py` — one genuinely firing the weekend whole-block roll-forward branch (multiday.py:104-107), one exercising the null-dt skip in `_date_index_map` — both green, `multiday.py` untouched.
- Transactional both-or-neither `persist` regression (mid-INSERT raise → zero committed rows, WAL-persistent) added to test_store.py, and the F01 post-send re-fire escape confirmed [EXISTS] in test_scheduler.py and tagged for the SC-3 ledger.
- A start-state-green negative-grep pytest gate (tests/test_dead_code_removed.py) that pins F16/F46/F76/F92 as staying gone — green at HEAD, ready for Plans 02/03/08 to delete the symbols and flip it to enforcing.
- 1. [Rule 3 - Blocking] Updated `_patched_run_weather` test shim to the pruned signature
- Task 1 — F74: canonical-only HH:MM validator.
- 1. [Rule 1 - Bug] Recursion in the F68 helper (self-inflicted during implementation)
- Marked the default location in !locations, dated the next_cloudy hourly label, corrected the F66 alerts docstring, and resolved the cosmetic F82/F79/F51/F80/F83/F62/F104 findings as one-char fixes or in-code accept-annotations — all with finding-tagged regressions and moved goldens.
- Task 1 — F71 accept-annotation (`docs`).
- Task 1 — v2.1 Disposition Ledger (commit `382d193`).

---

## v2.0 Bot Module Extraction (Shipped: 2026-07-07)

**Phases completed:** 8 phases (21–28), 26 plans, 61 tasks
**Closeout:** override_closeout — 6 non-blocking self-UAT log artifacts acknowledged (all 0 pending scenarios; every phase VERIFICATION `passed`). Milestone audit PASSED (15/15 requirements, 6/6 module seams wired). Live `yahir-mint` Gate-2 UAT passed.

**Key accomplishments:**

- **Byte-identical golden/characterization oracle (Phase 21)** — embeds, CLI stdout/exit, schedule plan, DB rows, `custom_id` bytes, exception identity — stood up as the standing contract re-run after every seam extraction and the physical split; move-path branch audit 89%→93% with 39 characterization fills.
- **Seven reusable seams un-braided weather-free** — Channel + delivery-reliability (22), scheduler engine + serialization-clean `JobStore` Protocol (23), config hot-reload `ConfigHolder[T]`/`ReloadEngine` (24), lifecycle READY-gate + composition root (25), command registry/dispatcher (26), Discord adapter/`PanelKit` (27) — each importing zero app code, enforced by a standing litmus grep + grimp one-way gate.
- **Four app-coupling leak-points injected at a single composition root** (`build_runtime`) — SelectedContext, config id-deriver, health-check, panel cosmetics — keeping the module domain-free; the `render_embed`↔`PanelView` cycle resolved by ownership (injected `render`), both edges dead.
- **Physical repo split to `YahirReusableBot`** (Phase 28) — `git mv` the clean boundary into its own PUBLIC repo, re-point WeatherBot via a uv git **tag pin** (`v0.1.1`) + frozen `uv.lock`, startup provenance line (`direct_url.json` sha), `EXTENSION-GUIDE`, repin-ritual + promotion-ledger; `discord.py==2.7.1` pin relocated into the module (inherited transitively).
- **Live Gate-2 on host `yahir-mint`** — restart against the pinned module + panel/reload/briefing/CLI verified; a live-only `on_message` recursion bug (invisible to 776 mocked-Discord tests) found + fixed + shipped as module `v0.1.1`, which the deploy is repinned to.
- **Close-time assurance fan-out** — retroactive security gate across phases 23–28 (`threats_open: 0`) + a cross-phase integration audit (6/6 seams wired, verified against the pinned VCS install).

**Known deferred (non-blocking):** durable `JobStore` impl (JOBSTORE-V2-01, seam designed), 2nd `Channel` adapter (Telegram/SMS/Slack), an optional `ReloadEngine` reject-path boot UAT. See STATE.md Deferred Items.

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
