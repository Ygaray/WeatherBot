# Codebase Concerns

**Analysis Date:** 2026-07-07

> **Cross-reference — authoritative bug findings:** A separate multi-agent whole-project
> bug audit is running concurrently and writes its ranked, behavior-level findings to
> `.planning/WHOLE-PROJECT-REVIEW.md`. As of this map that file is **not yet present**
> (`ls .planning/WHOLE-PROJECT-REVIEW.md` → absent). When it lands it is the AUTHORITATIVE
> source for correctness/behavioral bugs (send atomicity, DST math, race conditions). This
> document is complementary: it captures the STRUCTURAL / tech-debt / drift concerns a
> static map surfaces, plus fragile-area guidance. Where the two overlap
> (scheduler atomicity, timezone aggregation), defer to WHOLE-PROJECT-REVIEW.md for the
> verdict and treat the notes here as "where to look / why it's fragile."

## Tech Debt

**Oversized modules (single-file complexity):**
- Issue: Several modules carry far more than their share of logic, making them
  hard to review, test in isolation, and safely modify. Largest by LOC:
  - `weatherbot/scheduler/daemon.py` — **1598 LOC**. The single biggest risk surface.
    Owns fire_slot, fire_forecast_slot, job registration/reconciliation, catch-up
    orchestration, reload (`_do_reload`), file-watch observer, signal install, and
    the `run_daemon` main loop. This one file mixes delivery, scheduling, config
    reload, filesystem watching, and process lifecycle.
  - `weatherbot/cli.py` — **1035 LOC**. Command surface plus the `send_now` composition
    root that `daemon.fire_slot` lazily imports (documented import-cycle workaround).
  - `weatherbot/weather/models.py` — **634 LOC**. Forecast + ForecastDay + UV formatting.
  - `weatherbot/weather/store.py` — **523 LOC**. All SQLite persistence primitives.
  - `weatherbot/config/models.py` — **517 LOC**. Pydantic config validation.
  - `weatherbot/interactive/bot.py` — **514 LOC**; `weatherbot/scheduler/wiring.py` — 509 LOC.
- Files: as above.
- Impact: `daemon.py` at 1598 LOC concentrates the reliability-critical logic
  (exactly-once send, retry/alert, catch-up, reload) in one place; a change to any
  one concern forces re-reasoning about all of them. Review fatigue raises the odds a
  subtle scheduling/race regression slips through.
- Fix approach: Extract cohesive units from `daemon.py` into the existing
  `scheduler/` package — e.g. a `reload.py` (the `_do_reload`/reconcile block),
  `watch.py` (file-watch observer + filter), and keep `daemon.py` as the thin
  `run_daemon` loop + job callbacks. `catchup.py` and `uvmonitor.py` already show the
  target pattern (pure, single-responsibility, injectable clock). Do this
  behavior-preservingly behind the existing test suite (776 passing).

**Documentation drift — CLAUDE.md describes the RETIRED 2.5 strategy:**
- Issue: `CLAUDE.md` (the project tech-stack doc) prescribes the OpenWeather
  `2.5/weather` + `2.5/forecast` endpoints and "compute today's high/low by
  aggregating the 3-hour forecast buckets." The CODE no longer does this: it migrated
  to **One Call 3.0** (`/data/3.0/onecall`) and reads `daily[0].temp.max/min` /
  `daily[0].pop` / `daily[0].uvi` ready-made (D-01, Plan 02-01 — "that 2.5 logic was
  retired").
- Files: `CLAUDE.md` (Stack section) vs `weatherbot/weather/client.py:29`
  (`ONECALL = ".../data/3.0/onecall"`), `weatherbot/weather/models.py` (`from_payloads`,
  `from_daily` read `daily[i]`), `weatherbot/weather/store.py` (`weather_onecall` table).
- Impact: The dominant risk area named in the map brief ("timezone-correct today
  high/low aggregation from 3-hour buckets") **no longer exists in this code** — the
  bucket-aggregation surface was replaced by trusting the provider's daily rollup. A
  planner/executor reading CLAUDE.md would go looking for aggregation logic that isn't
  there, or reintroduce it. Also: One Call 3.0 requires a credit-card-backed
  subscription (the stack doc itself flags this as the reason to AVOID it as default) —
  so the deployed reality contradicts the documented "no-card free tier" decision.
- Fix approach: Update CLAUDE.md's stack + endpoint sections to state One Call 3.0 is
  now the implemented path, and note the card-on-file / 1,000-calls/day quota
  implication for a single-user bot. (Retired 2.5 tables are still present in the
  schema as historical, non-written — see Fragile Areas.)

**Retired-but-retained 2.5 schema tables:**
- Issue: `weather_current` and `weather_forecast` tables (with their generated columns
  and indexes) are still created by `_SCHEMA` on every connect but are **never written**
  to any more — all writes go to `weather_onecall`.
- Files: `weatherbot/weather/store.py:37-82` (dead-but-created tables), `store.py:207`
  (`conn.executescript(_SCHEMA)` runs on every persist/read).
- Impact: Dead schema surface; every store call re-runs the full multi-table
  `executescript` including the unused DDL. Minor, but it's latent confusion for anyone
  reading the schema ("which table is live?").
- Fix approach: Leave the historical data intact but consider splitting the live
  `_SCHEMA` (onecall + sent_log + alerts + uv_alerts + heartbeat + health) from a
  one-time legacy DDL, so hot-path connects don't re-declare retired tables.

## Known Bugs

- No open TODO/FIXME/HACK bug markers in source. A single non-bug NOTE exists:
  `weatherbot/scheduler/daemon.py:131` ("A module constant for now — promotable to
  config later (D-04)"), a deliberate deferral, not a defect.
- The full test suite passes: **776 passed** (`uv run pytest -q`). The reported
  "2 snapshots failed" is the known pre-existing **syrupy quirk** (suite still exits 0;
  trust the exit code + `.ambr` diff, per project memory `pytest-snapshot-report-quirk`),
  NOT a golden regression.
- Authoritative behavioral bugs (if any) will be enumerated in
  `.planning/WHOLE-PROJECT-REVIEW.md` — consult it before assuming "no known bugs."

## Security Considerations

**Secret hygiene (well-handled, noted for continued vigilance):**
- Risk: The OpenWeather `appid` travels as a query param, so the full request URL is a
  secret; the Discord webhook URL is a secret. A leaked log line or a persisted URL
  would expose them.
- Files: `weatherbot/weather/client.py:35-39` (raises the `httpx` logger to WARNING so
  the URL-with-`appid` cannot leak at INFO), `weatherbot/channels/discord.py:33`
  (mutes the `requests`/discord-webhook logger), `weatherbot/weather/store.py` (stores
  only response payloads, never the request URL — T-02-03), config split
  (`config/models.py:3-4` — only non-secret structure in the config file; API key +
  webhook URL live on `Settings`/`.env`).
- Current mitigation: Strong and consistent — secrets are kept off the config file, out
  of the DB, and out of logs by deliberate logger-level raises. All SQL is
  parameterized `?` (no f-string interpolation anywhere in `store.py`).
- Recommendations: Preserve the logger-level guards on any new httpx/requests call site
  (they are load-bearing, not cosmetic). Any new persisted field must be
  outcome-only (status code / exception class), never a URL or key (the `detail` column
  convention in `stamp_health`).

**PID-recycling signal safety (handled):**
- Risk: `weatherbot reload` sends SIGHUP to a PID read from a file; a recycled PID could
  receive a stray terminate.
- Files: `weatherbot/ops/pidfile.py` — verifies `/proc/<pid>/cmdline` names the
  weatherbot program (argv0 basename or `-m weatherbot`) BEFORE signaling, matching
  program identity not a substring. Atomic PID write via temp + `os.replace`.
- Current mitigation: Correct and defensive. Degrades to "signal" only off-Linux (host
  is Linux). No change needed.

## Performance Bottlenecks

**SQLite: no WAL / no busy_timeout, connection-per-call, schema re-run per call:**
- Problem: Every `store.py` primitive opens a fresh `sqlite3.connect(db_path)`, runs the
  entire `_SCHEMA` `executescript`, does one statement, commits, and closes. There is no
  `PRAGMA journal_mode=WAL`, no `busy_timeout`, and `check_same_thread` is default.
- Files: `weatherbot/weather/store.py` (every function: `persist`, `was_sent`,
  `claim_slot`, `release_claim`, `record_alert`, `claim_uv_alert`, `stamp_*`, `read_*`).
- Cause: Simplicity-first design. For a single-user bot with a handful of sends/day this
  is genuinely a rounding error — the load is trivial.
- Improvement path: Low priority given the workload. IF concurrency ever grows (the
  daemon thread + the discord.py gateway thread + a `reload` subprocess can all touch the
  DB), enabling WAL and a `busy_timeout` would remove the small risk of a
  `database is locked` under a concurrent writer. Re-running the full `_SCHEMA` (incl.
  retired 2.5 DDL) on every hot-path call is wasted work — see the schema-split note above.

## Fragile Areas

**`scheduler/daemon.py` — the exactly-once + retry/alert + reload nexus:**
- Files: `weatherbot/scheduler/daemon.py` (`fire_slot` ~136-395, `_do_reload` ~879-1028,
  `run_daemon` ~1354-end).
- Why fragile: This is where a regression would silently drop or double-send a morning
  briefing — the core value of the product. The exactly-once guarantee rests on
  `claim_slot` (atomic `INSERT OR IGNORE` BEFORE the network send) + `release_claim` on
  failure (`store.py:251-314`); the retry/alert budget is config-driven via
  `build_retrying`; catch-up re-derives missed sends at startup because the APScheduler
  memory jobstore loses all state on restart. Every one of these interacts with the
  others inside one 1598-LOC file.
- Safe modification: Do NOT touch the claim-before-fire ordering (claim → send →
  release-only-on-failure) without re-reading `store.claim_slot`/`release_claim`
  docstrings and the `test_scheduler.py` (2155 LOC) exactly-once/DST cases. Keep the
  broad `except Exception` isolation envelopes (annotated `# noqa: BLE001`) — they are
  deliberate "one bad slot must not kill the thread" guards, not sloppiness.
- Test coverage: Strong. `tests/test_scheduler.py` (2155 LOC) + `tests/test_reliability.py`
  (748) + `tests/test_reload.py` (980) + `tests/test_filewatch.py` (667) cover the risky
  paths. Coverage is a strength here, not a gap.

**Catch-up / DST missed-run math (`scheduler/catchup.py`):**
- Files: `weatherbot/scheduler/catchup.py` (`plan_catchup`, `fires_on`, `_weekday_set`).
- Why fragile: Correctly-hard timezone code. It composes a naive wall-clock, attaches the
  zone via `.replace(tzinfo=tz)`, and detects spring-forward GAP times by round-tripping
  through UTC (`catchup.py:161-168`); it compares only AWARE instants; the weekday parser
  must agree byte-for-byte with APScheduler's `CronTrigger.day_of_week`. A subtle error
  here means a missed or double morning send around a DST boundary — invisible until it
  happens twice a year.
- Safe modification: Never mutate `now_local`'s hour in place (documented anti-pattern —
  it carries the wrong offset). Keep `fires_on` as the SINGLE source of weekday truth
  (the UV monitor reuses it deliberately). Any change needs the DST exactly-once tests.
- Test coverage: Good (injected clock + `was_sent` reader make DST cases wall-clock-free).

**Timezone aggregation surface (now provider-trusted, not bucket-computed):**
- Files: `weatherbot/weather/models.py` (`from_payloads:267`, `from_daily:503`,
  `_local_date_iso:69`), `weatherbot/weather/store.py:169` (`_local_date_iso`).
- Why fragile: The high/low/rain now come from One Call `daily[0]`, but the definition of
  "today" is still computed from the **configured IANA tz** (authoritative, D-03) — NOT
  the API's `timezone_offset`. This tz-vs-tz distinction is duplicated in TWO
  `_local_date_iso` helpers (models.py and store.py), each with its own UTC fallback.
  If they ever diverge, the persisted `target_local_date` and the rendered briefing's
  "today" could disagree.
- Safe modification: Keep both `_local_date_iso` helpers behaviorally identical; consider
  promoting to one shared helper. Always prefer configured `Location.timezone` over the
  payload offset.
- Test coverage: `tests/test_models.py` (586) + golden coverage tests.

## Two-Repo Drift Risk (pinned hub vs editable overlay)

- Risk: WeatherBot is a CONSUMER of the shared hub `yahir_reusable_bot`, pinned in
  `pyproject.toml:36` to **tag `v0.1.1`** and frozen in `uv.lock` to sha
  `7f3cc001...` (`uv.lock:1324`). For live cross-repo dev the ecosystem convention is an
  UNCOMMITTED editable overlay: `uv pip install -e ../Reusable/YahirReusableBot`
  (`pyproject.toml:35`, reverted with `uv sync --frozen`).
- Impact — THREE distinct drift hazards:
  1. **Silent overlay drift.** If an editable overlay is left installed, the running
     process (and tests) exercise unpinned hub SOURCE, not the `v0.1.1` tag — so green
     tests locally can mask a bug that reappears in production (which runs the pin).
     Memory note `weatherbot-live-systemd-service` confirms the deployed bot uses an
     editable install and needs a restart — so the live host is itself in this
     overlay-vs-pin ambiguity zone.
  2. **Cross-repo jurisdiction / human-gated repin.** A bug that is actually IN the hub
     breaks WeatherBot in production, but fixing it (cut hub tag → repin here → deploy)
     is an explicitly **human-gated** step per `CLAUDE.md` and `deploy/REPIN-RITUAL.md`.
     An agent must route such a fix upstream and surface it, NOT ship it autonomously.
     Read `../Reusable/YahirReusableBot/ECOSYSTEM.md` before any cross-repo change.
  3. **Transitive discord.py pin lives in the hub.** `pyproject.toml:17-18` notes the hub
     transitively pins the exact discord.py version (the live-panel `custom_id` wire
     contract) and instructs "do NOT re-declare discord.py app-side." A hub bump could
     therefore change the gateway lib under WeatherBot without a WeatherBot-side edit.
- Mitigation in place: `uv.lock` freezes the resolved sha; `deploy/REPIN-RITUAL.md` and
  `deploy/PROMOTION-LEDGER.md` document the gated repin flow; the `_promotable/`
  quarantine convention keeps reusable-vs-app placement disciplined.
- Recommendation: Before trusting a local test run for anything reliability-critical,
  confirm the overlay state (`uv sync --frozen` restores the pin). Treat any "fix the
  hub" impulse as a surface-to-human action, not an autonomous commit.

## Scope / Dependency-Weight Expansion (design vs. reality)

- Problem: PROJECT.md / CLAUDE.md frame v1 as **fire-and-forget Discord WEBHOOK only**
  (`discord-webhook`, "lighter than pulling in discord.py which is built for full gateway
  bots"). The codebase now ALSO ships a full **discord.py GATEWAY** surface: an
  interactive bot with a persistent connection, intents, permission checks, and a live
  `!panel` (`weatherbot/interactive/bot.py`, `panel.py`, `commands/`), pulled in
  transitively via the hub.
- Files: `weatherbot/interactive/` (bot.py 514, panel.py 358, registry.py 244, etc.),
  `weatherbot/interactive/bot.py:47` (`import discord`).
- Impact: The bot now maintains a persistent gateway connection and a bot token in
  addition to the webhook — exactly the heavier posture the stack doc argued against for
  v1. This is a legitimate feature evolution (interactive commands), but the stack
  documentation still reads as if it's webhook-only. Also surfaces a `DeprecationWarning`
  from discord.py's `audioop` on Python 3.13 (currently just a warning on 3.12).
- Recommendation: Not debt to remove — it's shipped capability. But UPDATE the stack doc
  to acknowledge the gateway surface and its token/intents requirements, and track the
  `audioop`/Python-3.13 discord.py deprecation as a future-runtime concern (the project
  targets 3.12+/3.13).

## Test Coverage Gaps

- What's not tested / thin: No obvious untested critical path — the suite is large and
  targeted (776 tests; `test_scheduler.py` 2155, `test_bot.py` 1568, `test_panel.py`
  1566, `test_cli.py` 1114, `test_reload.py` 980, `test_config.py` 915). Coverage is a
  project STRENGTH.
- Residual risk: The two syrupy snapshot "failures" are noise, but they slightly erode
  signal — a real golden regression could hide behind the always-present "2 snapshots
  failed" line. Priority: Low. Mitigation: keep trusting exit code + `.ambr` diff
  (documented in project memory), or resolve the syrupy quirk so the snapshot summary is
  clean.
- The cross-repo hub is NOT tested from this repo (by design — it has its own suite).
  Overlay drift (above) is the way an untested hub change reaches WeatherBot silently.
  Priority: Medium — mitigated by the pin + frozen lock, not by tests here.

---

*Concerns audit: 2026-07-07*
