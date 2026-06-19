# Phase 15: Proactive UV Sunscreen Monitor - Research

**Researched:** 2026-06-18
**Domain:** In-process intraday polling loop (APScheduler IntervalTrigger) + three-state once/day/location dedup over SQLite + daylight-window bounding across timezones
**Confidence:** HIGH (brownfield — nearly every decision maps to an existing, read verbatim, precedent in the codebase; external facts verified against official docs)

## Summary

Phase 15 is a **pure extension of patterns already proven in this codebase** — it introduces no new library and no new architectural primitive. Every locked decision in `15-CONTEXT.md` maps to code I read directly:

- The "new IntervalTrigger job like the heartbeat" mechanism is `_heartbeat_tick` + its `scheduler.add_job(..., trigger=IntervalTrigger(...), id="__heartbeat__", misfire_grace_time=None, coalesce=True)` registration at `daemon.py:1078`. Copying that shape gives UV-06 (failure isolation) for free: APScheduler 3.x catches any exception a job raises, logs it with a traceback, emits an `EVENT_JOB_ERROR`, and **keeps the scheduler and all other jobs running** — verified against the official 3.x user guide.
- The "restart-safe three-state once/day/location dedup" is the exact `INSERT OR IGNORE` + `rowcount==1` discipline of `record_alert` / `claim_slot` in `store.py`. The `alerts` table's `UNIQUE(location_name, slot_time, local_date)` constraint extends naturally to a UV-alert key by repurposing the `slot_time` column to carry the `alert_kind ∈ {prewarn,crossing,allclear}` discriminator (or adding a dedicated `uv_alerts` table with the same shape — see Decision Point DP-1).
- "active = a location with an enabled briefing slot whose days include today in its tz" is **already implemented** as `_fires_on(slot, now_local)` + `_weekday_set(day_of_week)` in `scheduler/catchup.py`. Reuse it; do not re-derive weekday logic.
- The UV computation helper the monitor "MUST reuse" is built in **Phase 14, which is not yet planned or implemented** (only `14-CONTEXT.md` exists). This is the single biggest cross-phase dependency and the one real risk — see Open Question 1 and the Phase-14 Dependency Contract section.

**Primary recommendation:** Add one `IntervalTrigger` job (`id="__uvmonitor__"`, default 900s, `misfire_grace_time=None`, `coalesce=True`, `max_instances=1`) registered in `run_daemon` right after the heartbeat job. Its tick reads `holder.current()` once, filters to active+daylight locations using the reused `_fires_on` helper and One Call `daily[0].sunrise/sunset`, fetches forecast through a **monitor-local fetch path that does NOT call `store.persist`** (no time-series pollution), consumes the Phase-14 UV helper, and posts the three alert kinds best-effort via the existing `channel.send`, each gated by an `INSERT OR IGNORE` dedup row keyed `(location.id, local_date, alert_kind)`. **A One Call client `exclude` change (keep `hourly`, add `sunrise`/`sunset`) is a hard prerequisite owned by Phase 14** — flag it loudly to the planner.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Periodic intraday trigger | Scheduler spine (APScheduler `IntervalTrigger` on the existing `BackgroundScheduler`) | — | The heartbeat precedent already runs an isolated interval job on this scheduler; a new asyncio thread was explicitly rejected in D-01. |
| Active-location selection | Config/domain (`_fires_on` + `holder.current()`) | — | Pure function over the frozen `Config` snapshot; no I/O. Same logic the cron registration and catch-up planner use. |
| Daylight windowing | Weather/domain (One Call `daily[0].sunrise/sunset` + `zoneinfo`) | — | Sunrise/sunset come from the already-fetched payload; tz math is stdlib `zoneinfo`. |
| Forecast fetch (per tick) | Weather client (`fetch_onecall`) | Cache (optional) | Read-only fetch; MUST bypass `store.persist` to avoid polluting the SQLite time series (UV-04 budget + DATA-03 "delivered-only persistence"). |
| UV crossing/window/peak computation | Weather/domain (**Phase 14 UV helper**) | — | Locked: "MUST reuse, not re-derive." Lives in Phase 14. |
| Three-state once/day/location dedup | Persistence (`store.py` SQLite, `INSERT OR IGNORE`) | In-memory set (rejected — see DP-1) | Must survive restart AND reload without re-spamming; SQLite is the only restart-durable option in the codebase. |
| Alert delivery | Channel (`DiscordWebhookChannel.send`) | — | Best-effort plain-text `send(text)`, identical to the reload-outcome post idiom. A failed post never gates anything. |
| Failure isolation (UV-06) | Scheduler spine (APScheduler per-job exception catch) | Defensive `try/except` in the tick body | Two layers: APScheduler swallows job exceptions; the tick also wraps its own body like `fire_slot` does, so even a partial failure isolates per-location. |

## Standard Stack

No new dependencies. Everything Phase 15 needs is already installed and in use.

### Core (all already present)
| Library | Version (verified installed) | Purpose | Why Standard |
|---------|------------------------------|---------|--------------|
| APScheduler | 3.11.2 `[VERIFIED: uv run python -c "import apscheduler; apscheduler.__version__"]` | `IntervalTrigger` monitor job on the existing `BackgroundScheduler` | The heartbeat job (`daemon.py:1078`) is the exact precedent. 3.x per-job exception isolation is the UV-06 mechanism. |
| httpx | 0.28.1 `[VERIFIED: uv run python -c]` | Per-tick One Call fetch via `weatherbot.weather.client.fetch_onecall` | Already the fetch path; explicit 10s timeout already set (`client.py:33`). |
| discord-webhook | 1.4.1 (pyproject pin) `[CITED: pyproject.toml]` | Best-effort alert delivery via `channel.send(text)` | Same channel object the daemon already threads into every job; `send(text)` is the channel-agnostic plain-text path. |
| pydantic / pydantic-settings | 2.13.4 / 2.14.1 `[VERIFIED: uv run python -c]` / `[CITED: pyproject.toml]` | New `[uv]` config fields (interval, lead minutes, value-proximity margin) on a `frozen=True` model | Mirrors `Reliability` / `ReloadConfig` / `BotConfig` exactly. |
| sqlite3 (stdlib) | built-in | Three-state once/day/location dedup table | `store.py` already owns the `alerts`/`sent_log` `INSERT OR IGNORE` discipline. |
| zoneinfo (stdlib) | built-in | Daylight-window bounding in each location's IANA tz | Already used throughout (`models.py`, `store.py`, `daemon.py`). |

**Installation:** None. `uv sync` already provides the full stack.

**Version verification (run this session):**
```
apscheduler 3.11.2   # uv run python -c "import apscheduler; print(apscheduler.__version__)"
httpx 0.28.1
pydantic 2.13.4
```
These match the CLAUDE.md recommended stack exactly. APScheduler stays on the 3.x line (4.x is explicitly forbidden in CLAUDE.md "What NOT to Use").

## Package Legitimacy Audit

No new external packages are introduced by this phase. All libraries are pre-existing, pinned in `pyproject.toml`, and already imported by shipped code (v1.0/v1.1). slopcheck not required — the dependency set is unchanged.

| Package | Registry | Status | Disposition |
|---------|----------|--------|-------------|
| apscheduler | PyPI | Pinned `>=3.11.2,<4`, in use since Phase 3 | No change — already trusted |
| httpx | PyPI | Pinned `>=0.28.1`, in use since Phase 1 | No change — already trusted |
| discord-webhook | PyPI | Pinned `>=1.4.1`, in use since Phase 1 | No change — already trusted |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UV-04 | Background intraday monitor polls forecast on a configurable interval (default ~15 min, well under API limits) for today's active location(s), daylight only | IntervalTrigger job pattern (`daemon.py:1078`); active-location filter via reused `_fires_on` (`catchup.py:90`); daylight bound via One Call `daily[0].sunrise/sunset`; API-budget math (this doc) shows ~256 calls/day worst case ≪ 1,000/day One Call free cap |
| UV-05 | Pre-warning + threshold-reached alerts, ≤ once/day/location, posted to Discord (refined to also include all-clear) | `INSERT OR IGNORE` three-state dedup keyed `(location.id, local_date, alert_kind)`; pre-warn time-vs-value logic + already-high path + all-clear downslope (Architecture Patterns §); `channel.send(text)` best-effort delivery |
| UV-06 | Monitor failure-isolated — errors never gate/delay/stop a scheduled briefing | APScheduler 3.x catches job exceptions and keeps the scheduler + all other jobs running (verified, official 3.x docs); plus a `fire_slot`-style `try/except` wrapper in the tick body; the monitor job NEVER touches `claim_slot`/`sent_log`, so it is structurally incapable of blocking a briefing |

## Architecture Patterns

### System Architecture Diagram

```
                          run_daemon() [existing]
                                 │
            ┌────────────────────┼─────────────────────────┐
            │                    │                          │
     CronTrigger jobs      IntervalTrigger          IntervalTrigger
     (briefings, per       __heartbeat__            __uvmonitor__   ◀── NEW
      enabled slot)        (existing, 600s)         (NEW, default 900s)
            │                    │                          │
            ▼                    ▼                          ▼
       fire_slot()         _heartbeat_tick()        _uv_monitor_tick(holder, db_path,
   (claim_slot → send →                              settings, client, channel)
    persist; OWNS sent_log)                                 │
                                                            │ reads holder.current() ONCE
                                                            ▼
                                          for each location in config.locations:
                                                            │
                                          ┌─────────────────┴──────────────────┐
                                          │ active today?  (_fires_on over any  │
                                          │ enabled slot, in location.timezone) │──no──▶ skip
                                          └─────────────────┬──────────────────┘
                                                            │ yes
                                                            ▼
                                          fetch One Call (imp+met) via client
                                          *** does NOT call store.persist ***
                                          (needs hourly[] + daily[0].sunrise/sunset
                                           — Phase-14 `exclude` change required)
                                                            │
                                          ┌─────────────────┴──────────────────┐
                                          │ now within [sunrise, sunset] tz?    │──no──▶ skip
                                          └─────────────────┬──────────────────┘
                                                            │ yes (daylight)
                                                            ▼
                                          Phase-14 UV helper(hourly uvi, threshold)
                                          → current uvi, interpolated crossing time,
                                            protect-window, peak
                                                            │
                          ┌─────────────────────────────────┼──────────────────────────────┐
                          ▼                                  ▼                               ▼
                  current ≥ threshold              within N min of crossing        current < threshold
                  AND no crossing row yet          OR within margin of threshold   AFTER a crossing row exists
                          │                        AND no prewarn/crossing row     AND no allclear row yet
                  is this the FIRST poll                     │                               │
                  of the day (no prior rows)?                ▼                               ▼
                          │                          claim_uv_alert(prewarn)         claim_uv_alert(allclear)
                ┌─────────┴──────────┐                  rowcount==1 ⇒ post           rowcount==1 ⇒ post "✅ over"
                ▼                    ▼                "☀️ UV hits T in ~30m"
        already-high path      normal crossing
        claim_uv_alert(           claim_uv_alert(
          crossing)                 crossing)
        AND ALSO mark             rowcount==1 ⇒ post
        prewarn claimed           "☀️ UV now ≥T"
        (skip moot pre-warn)
                          all posts: channel.send(text) — best-effort, failure swallowed
```

### Recommended Project Structure

The monitor is small enough to live alongside the existing scheduler module. Two viable placements:

```
weatherbot/
├── scheduler/
│   ├── daemon.py          # add _uv_monitor_tick + register __uvmonitor__ job in run_daemon
│   └── uvmonitor.py       # NEW (recommended): _uv_monitor_tick + active/daylight/decision helpers
│                          #   keeps daemon.py from growing; mirrors catchup.py living beside daemon.py
├── weather/
│   ├── store.py           # add uv_alerts table + claim_uv_alert() (INSERT OR IGNORE)
│   └── uv.py              # Phase-14-OWNED UV helper the monitor imports (DO NOT create here in P15)
└── config/
    └── models.py          # add UvConfig (frozen) + uv: UvConfig field on Config
```

Recommendation: put the tick + decision logic in a new `weatherbot/scheduler/uvmonitor.py` (testable in isolation, like `catchup.py`), and keep `daemon.py`'s change to just the `add_job` registration + the import — mirroring how `plan_catchup` lives in `catchup.py` and is called from `daemon.py`.

### Pattern 1: The IntervalTrigger monitor job (copy the heartbeat shape)
**What:** One `add_job` call registered in `run_daemon` immediately after the heartbeat registration.
**When to use:** This is the UV-04/UV-06 backbone.
**Example (the existing heartbeat, the precedent to copy):**
```python
# Source: weatherbot/scheduler/daemon.py:1078 (existing, verbatim)
scheduler.add_job(
    _heartbeat_tick,
    trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S),
    kwargs={"db_path": db_path},
    id="__heartbeat__",
    misfire_grace_time=None,
    coalesce=True,
)
```
The UV job is the same shape, plus `max_instances=1` (so a slow tick that overruns the 15-min interval never stacks a second concurrent run) and the extra kwargs the tick needs:
```python
# NEW — register right after the heartbeat job
if snapshot.uv.monitor_enabled:                       # config gate, default on
    scheduler.add_job(
        _uv_monitor_tick,
        trigger=IntervalTrigger(seconds=snapshot.uv.interval_seconds),
        kwargs={
            "holder": holder,        # re-read holder.current() each tick (live config)
            "db_path": db_path,
            "settings": settings,
            "client": client,
            "channel": channel,
        },
        id="__uvmonitor__",
        misfire_grace_time=None,     # a missed tick is simply skipped, not stacked
        coalesce=True,               # collapse queued runs to one
        max_instances=1,             # never two concurrent ticks
    )
```
**Why `misfire_grace_time=None` + `coalesce=True` is correct here:** identical reasoning to the slot/heartbeat jobs (`daemon.py:1083` comment) — recovery is NOT owned by APScheduler misfire (the memory jobstore loses all state on exit); a tick missed during a pause/restart should simply be skipped, and the next tick re-evaluates fresh from live forecast + the durable dedup rows. There is no value in replaying a stale 15-min-old UV reading.

### Pattern 2: Live-config re-read each tick (kwargs carry the holder, not a baked config)
**What:** The job's kwargs carry `holder`, and the tick calls `holder.current()` at the top of each run — exactly how `fire_slot` resolves its snapshot (`daemon.py:181`).
**When to use:** So a hot-reload of `[uv]` fields (threshold, margin, lead) takes effect on the next tick without a restart, matching CFG-01.
**Caveat (acceptable, must be noted to the planner):** the **interval itself** is baked into the `IntervalTrigger` at registration time. Changing `interval_seconds` requires re-registering the job. The codebase already accepts this class of restart-deferred config (`[reload] watch` is read once at startup — `daemon.py:1127` Open Question Q2; `[bot] operator_id` likewise). **Recommendation:** treat `interval_seconds` as restart-deferred (document it like `[reload] watch`), but make the threshold/lead/margin/enable fields live-reloadable via the holder re-read. Optionally, the reload reconcile (`_reconcile_jobs`) could re-add `__uvmonitor__` with `replace_existing=True` to pick up a new interval live — but that adds reconcile surface; restart-deferred is the lower-risk default and is consistent with existing precedent.

### Pattern 3: The three decision branches (pre-warn / crossing-or-already-high / all-clear)
**What:** Per active+daylight location, evaluate three independent once/day/location gates against live UV + the Phase-14 interpolated crossing prediction.
**Decision logic (the load-bearing core):**

Let `T` = configured threshold, `uvi_now` = live current UV, `cross_at` = interpolated crossing time from the morning/▸current forecast (Phase-14 helper), `now` = current local time, `lead` = configured pre-warn lead minutes (default 30), `margin` = value-proximity margin (default ~1.0).

```
prior = set of alert_kinds already claimed for (location.id, local_date)

# --- ALREADY-HIGH (D-04): first daylight poll finds UV already at/above T ---
if uvi_now >= T and "crossing" not in prior:
    if "prewarn" not in prior:           # nothing fired yet today ⇒ a late/mid-day start
        claim "prewarn"  (mark moot, DO NOT post)   # suppress the now-pointless pre-warn
    if claim "crossing" wins:
        post  "☀️ UV already ≥{T} in {loc} — sunscreen on. Protect ~{win_start}-{win_end}."

# --- normal CROSSING: UV crosses up through T ---
elif uvi_now >= T and "crossing" not in prior:   # (covered above; kept for clarity)
    if claim "crossing" wins:
        post  "☀️ UV now ≥{T} in {loc} — sunscreen on. Protect ~{win_start}-{win_end}."

# --- PRE-WARN: whichever of (time-proximity | value-proximity) fires first ---
elif uvi_now < T and "prewarn" not in prior and "crossing" not in prior:
    time_close  = (cross_at is not None) and (0 <= (cross_at - now) <= lead)
    value_close = (T - uvi_now) <= margin
    if time_close or value_close:
        if claim "prewarn" wins:
            post  "☀️ UV hits {T} in ~{mins} min in {loc} — sunscreen soon."

# --- ALL-CLEAR: UV drops back below T after a crossing fired ---
if uvi_now < T and "crossing" in prior and "allclear" not in prior:
    if claim "allclear" wins:
        post  "✅ UV back below {T} in {loc} — protect window over."
```
**Ordering note:** the already-high branch MUST be checked before the normal pre-warn branch (a late start that's already high should never emit a pre-warn). The all-clear check is independent and runs every tick once a crossing exists.
**`claim X wins`** = `claim_uv_alert(db_path, location.id, local_date, kind)` returns `rowcount == 1` — the same atomic "I am the first" arbitration as `record_alert`. This makes the post-once guarantee hold even across overlapping ticks and across a restart (the row is durable).

### Pattern 4: Monitor fetch must NOT persist (no time-series pollution)
**What:** The per-tick One Call fetch calls `client.fetch_onecall(loc, units)` directly (as `lookup_weather` does) and **never** calls `store.persist`.
**Why:** `store.persist` writes a `weather_onecall` row per units variant per call. At 4 polls/hr × daylight × 2 locations that would dump ~hundreds of rows/day into the analysis time series, violating UV-04's "well under limits" spirit and DATA-03's delivered-only persistence semantic (STATE.md Deferred Items confirms DATA-03 is "delivered-only"). The read-only lookup core (`lookup.py`) is the established "fetch without writing" precedent — the monitor follows the same posture.
**Optional cache reuse:** `ForecastCache` (TTL ~600s) could be reused to collapse the monitor's fetch and a near-simultaneous `!weather`/`uv` command into one call — but the monitor needs `hourly[]` which the briefing path may not (verify the cache stores the full payload). Simplest correct default: the monitor fetches directly with its own `client.fetch_onecall`, accepting a few extra calls (budget math below shows this is trivial). Cache reuse is an optimization, not a requirement.

### Anti-Patterns to Avoid
- **A new asyncio thread for the loop.** Explicitly rejected (D-01). APScheduler job isolation already satisfies UV-06; a second thread adds teardown/lifecycle surface for zero benefit.
- **Persisting every monitor fetch.** Pollutes the SQLite time series and inflates API/DB load. Fetch read-only (Pattern 4).
- **An in-memory `set()` as the dedup store.** Loses all state on restart AND on the daemon's reload path is irrelevant (reload doesn't restart the process, but a `systemctl restart` does). A mid-day restart would re-spam every alert. Durable SQLite rows are the only correct choice (DP-1).
- **Re-deriving weekday/active logic.** `_fires_on` + `_weekday_set` already exist and are the SAME logic the cron registration uses. Reuse, don't fork (the catch-up planner Pitfall 3 warns precisely against two divergent day-of-week implementations).
- **Touching `claim_slot` / `sent_log` from the monitor.** Those own briefing exactly-once. The monitor's dedup is a SEPARATE namespace; never let UV dedup and briefing dedup share a table key, or a UV bug could block a briefing (would violate UV-06).
- **Reading the API `timezone` offset instead of the configured IANA `Location.timezone`.** `store.py`/`models.py` both warn (Pitfall 3): the configured `Location.timezone` is authoritative for "today" and for daylight bounding. Use `ZoneInfo(location.timezone)`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Periodic isolated loop | A `while True: sleep(900)` thread | APScheduler `IntervalTrigger` job (heartbeat precedent) | Per-job exception isolation, clean shutdown, coalesce/misfire semantics all free; matches D-01 |
| Once/day/location dedup | A Python dict/set + manual date rollover | `INSERT OR IGNORE` + `rowcount==1` against a `UNIQUE` key (`record_alert` shape) | Atomic, restart-durable, race-safe, zero rollover logic (the date is in the key) |
| "Is this location active today?" | Hand-rolled weekday parsing | `_fires_on(slot, now_local)` / `_weekday_set` (`catchup.py`) | Single source of truth shared with the live cron trigger |
| UV crossing-time interpolation | New linear-interpolation code in P15 | **Phase-14 UV helper** (locked: MUST reuse) | Phase 14 owns the interpolation/window/peak math; duplicating it risks the two drifting |
| Local "today" + daylight bounds | Manual UTC-offset arithmetic | `ZoneInfo(location.timezone)` + One Call `daily[0].sunrise/sunset` epochs | DST-correct, IANA-authoritative; the API offset is NOT the configured tz (Pitfall 3) |
| Best-effort alert post | A try/except around raw httpx | `channel.send(text)` (returns `DeliveryResult`, never raises) | Already credential-safe, 429-aware, non-raising; same idiom as reload-outcome posts |

**Key insight:** This phase is ~90% wiring existing, individually-proven primitives together. The only genuinely new code is (a) the decision-branch logic in Pattern 3, (b) one new config model, and (c) one new dedup table + helper. Resist the urge to build anything the codebase already provides.

## Runtime State Inventory

This is a **greenfield-feature phase** (adds a new monitor job + new config + new dedup table) — it does NOT rename, refactor, or migrate any existing string/identity. The Runtime State Inventory categories are therefore mostly N/A, but two are worth an explicit answer because the phase adds durable state:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | NEW `uv_alerts` rows keyed `(location_id, local_date, alert_kind)` will accumulate in the existing `data/weatherbot.db`. No existing data is renamed or migrated. | Add `CREATE TABLE IF NOT EXISTS uv_alerts (...)` to `store.py`'s idempotent `_SCHEMA` (auto-applied on first connect — no migration script needed, matching how `alerts`/`heartbeat`/`health` were added). |
| Live service config | The live systemd service on host `yahir-mint` (MEMORY: weatherbot-live-systemd-service) runs an **editable install** — a code change requires `systemctl restart weatherbot` to take effect. The new `[uv]` config section is added to the host's `config.toml`. | Plan must note: after deploy, the host's `config.toml` needs the `[uv]` section (with sensible defaults so an unedited config still works), and the service restarts to load the new monitor job. Interval changes are restart-deferred (Pattern 2). |
| OS-registered state | None — no new systemd unit, timer, or OS registration (the monitor is an in-process APScheduler job, not an OS-level cron/timer; this is the explicit design choice over OS cron per CLAUDE.md). | None. |
| Secrets/env vars | None — the monitor reuses the existing `OPENWEATHER_API_KEY` / `DISCORD_WEBHOOK_URL` via the already-built `client` and `channel`. No new secret. | None. |
| Build artifacts | None — no package rename, no new entry point. | None. |

**The canonical question — "after every file is updated, what runtime systems still have old state?":** Only the host's `config.toml` (needs the new `[uv]` section) and the running daemon (needs a restart to register the new job). Both are normal deploy steps, not migrations. The new `uv_alerts` table is auto-created by the idempotent schema on first connect. **Nothing else.**

## Common Pitfalls

### Pitfall 1: The One Call client currently STRIPS `hourly[]` — Phase 15 cannot compute crossing without it
**What goes wrong:** `weatherbot/weather/client.py:58` sets `"exclude": "minutely,hourly"`. The interpolated crossing-time / protect-window logic needs `hourly[].uvi` (48h), and daylight bounding needs `daily[0].sunrise`/`sunset`. With the current `exclude`, `hourly` is absent and the UV helper has nothing to interpolate.
**Why it happens:** v1.0 only needed `current` + `daily[0]` for the briefing, so `hourly`/`minutely` were excluded to trim payload size.
**How to avoid:** **Phase 14 owns this change** (its `14-CONTEXT.md` already says "Hourly `uvi` (One Call `hourly[]`, 48h) is in the raw payload for crossing-time/window/peak computation" — implying Phase 14 must change `exclude` to `"minutely"` only, keeping `hourly`). Phase 15 RESEARCH flags it because **if Phase 14's plan forgets to keep `hourly`, Phase 15 silently breaks.** The Phase-15 planner must add a verification step: "confirm `client.fetch_onecall` returns a non-empty `hourly` list and `daily[0].sunrise`/`sunset`."
**Warning signs:** A monitor tick that never finds a crossing time, or a `KeyError`/empty-list on `payload["hourly"]`.

### Pitfall 2: Re-spam after a mid-day `systemctl restart`
**What goes wrong:** If dedup lives in memory, a restart at noon re-fires every already-sent alert (pre-warn, crossing) because the in-memory "already sent" set is empty on boot.
**Why it happens:** The bot runs as an always-on service that can restart for deploys/crashes mid-day (MEMORY: live systemd service, editable install).
**How to avoid:** Durable SQLite dedup rows (DP-1). On restart the `INSERT OR IGNORE` for an already-sent kind returns `rowcount==0` ⇒ no re-post. The all-clear and already-high paths are also covered because they consult the same durable `prior` set.
**Warning signs:** Duplicate UV alerts in Discord after a daemon restart.

### Pitfall 3: All-clear / pre-warn firing on the wrong side of the window across DST
**What goes wrong:** Daylight bounding or "is it still daylight" computed with a fixed UTC offset rather than the IANA zone gives a one-hour error around a DST transition, so the monitor polls an hour past sunset or stops an hour early.
**Why it happens:** Mixing the API `timezone_offset` field with the configured `Location.timezone`.
**How to avoid:** Use `ZoneInfo(location.timezone)` for "now local" and convert the `sunrise`/`sunset` epoch seconds (UTC) to that same zone for the comparison — `datetime.fromtimestamp(sunrise_epoch, tz=ZoneInfo(loc.timezone))`. This is exactly the Pitfall-3 discipline `store.py`/`models.py` already follow. `daily[0].sunrise/sunset` are absolute epoch instants, so the comparison is naturally DST-safe as long as "now" is tz-aware.
**Warning signs:** Off-by-one-hour daylight window at the spring/fall DST boundary.

### Pitfall 4: A slow tick stacking concurrent monitor runs
**What goes wrong:** Two active locations + a slow OpenWeather response could make one tick exceed 15 min; without `max_instances=1` APScheduler could start a second overlapping tick, double-fetching and racing on dedup claims.
**Why it happens:** The default `max_instances` is 1 in APScheduler 3.x (verified), so this is actually safe by default — but the heartbeat job doesn't set it explicitly. Set it explicitly for clarity and to document intent.
**How to avoid:** `max_instances=1` on the `add_job` call. The `INSERT OR IGNORE` dedup is race-safe regardless, so even a stacked run can't double-post — but `max_instances=1` avoids the wasted double-fetch.
**Warning signs:** Doubled API calls in a tick window (visible if you log per-tick fetch counts).

### Pitfall 5: The monitor consuming a forecast cached against a stale config after reload
**What goes wrong:** If the monitor reuses `ForecastCache` and a reload changes a location's coords, a pre-reload cached forecast could feed a UV decision.
**Why it happens:** TTL caches serve stale entries until expiry; the reload path already invalidates the bot's cache (`_do_reload(..., cache=cache)` / CR-01) but a separate monitor cache would need the same wiring.
**How to avoid:** Simplest: the monitor does NOT use a cache (Pattern 4 — direct fetch). If a cache is added later for budget reasons, wire its `invalidate()` into `_do_reload` exactly as the bot cache is.
**Warning signs:** A UV alert for the wrong location after a coords reload.

## Code Examples

### The dedup helper (copy `record_alert`'s exact shape)
```python
# NEW in weatherbot/weather/store.py — structural copy of record_alert (store.py:308)
# Schema addition (add to _SCHEMA, idempotent like alerts/heartbeat/health):
#   CREATE TABLE IF NOT EXISTS uv_alerts (
#       id            INTEGER PRIMARY KEY,
#       location_id   TEXT    NOT NULL,
#       local_date    TEXT    NOT NULL,   -- YYYY-MM-DD in the location's tz
#       alert_kind    TEXT    NOT NULL,   -- 'prewarn' | 'crossing' | 'allclear'
#       created_at_utc INTEGER NOT NULL,
#       UNIQUE(location_id, local_date, alert_kind)   -- once/day/location/kind
#   );

def claim_uv_alert(db_path, location_id: str, local_date: str, alert_kind: str) -> bool:
    """Atomically claim one UV alert (kind) for a location/day. True ⇒ first claim (post now)."""
    created_at_utc = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        cur = conn.execute(
            "INSERT OR IGNORE INTO uv_alerts "
            "(location_id, local_date, alert_kind, created_at_utc) VALUES (?, ?, ?, ?)",
            (location_id, local_date, alert_kind, created_at_utc),
        )
        conn.commit()
        return cur.rowcount == 1
```

### Reading the durable "prior" set for a location/day (drives the decision branches)
```python
def claimed_uv_kinds(db_path, location_id: str, local_date: str) -> set[str]:
    """The set of alert_kinds already claimed today for this location (restart-durable)."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        rows = conn.execute(
            "SELECT alert_kind FROM uv_alerts WHERE location_id=? AND local_date=?",
            (location_id, local_date),
        ).fetchall()
    return {r[0] for r in rows}
```

### Active-today + daylight gate (reuse existing `_fires_on`)
```python
# Source: reuse weatherbot/scheduler/catchup.py _fires_on (catchup.py:90) — DO NOT re-derive
from datetime import datetime
from zoneinfo import ZoneInfo
from weatherbot.scheduler.catchup import _fires_on  # promote to public if importing cross-module

def _active_today(location, now_utc) -> bool:
    tz = ZoneInfo(location.timezone)
    now_local = now_utc.astimezone(tz)
    return any(s.enabled and _fires_on(s, now_local) for s in location.schedule)

def _is_daylight(now_utc, sunrise_epoch, sunset_epoch, tz_name) -> bool:
    tz = ZoneInfo(tz_name)
    now_local = now_utc.astimezone(tz)
    sunrise = datetime.fromtimestamp(sunrise_epoch, tz=tz)
    sunset  = datetime.fromtimestamp(sunset_epoch,  tz=tz)
    return sunrise <= now_local <= sunset
```
**Note:** `_fires_on` and `_weekday_set` are currently underscore-prefixed (module-private) in `catchup.py`. The planner should either (a) promote `_fires_on` to a public `fires_on` in `catchup.py` (cleanest — it's now shared by two callers) or (b) add a thin public wrapper. Do not copy-paste the weekday logic.

### Best-effort alert post (mirror the reload-outcome idiom)
```python
# Mirrors daemon.py:665 _do_reload's best-effort channel post
if channel is not None:
    try:
        channel.send(f"☀️ UV now ≥{threshold} in {loc.name} — sunscreen on. Protect ~{win}.")
    except Exception:  # noqa: BLE001 — best-effort; a failed post never gates the monitor
        _log.warning("uv alert post failed; monitor unaffected")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 2.5 `weather`+`forecast` endpoints, 3-hour bucket aggregation for high/low | One Call 3.0 `daily[0]` + `hourly[]` (incl. `uvi`, `sunrise`/`sunset`) | v1.0 Plan 02-01 (already shipped) | UV data (`hourly[].uvi`, `daily[0].uvi`) is in the already-fetched payload — no new endpoint. Phase 15 just needs `hourly` kept in `exclude`. |
| OS cron / separate process for intraday loops | In-process APScheduler interval job | Project decision (CLAUDE.md "What NOT to Use") | Keeps scheduling + config in one process; the heartbeat already proves the pattern. |

**Deprecated/outdated:**
- APScheduler 4.x: forbidden (CLAUDE.md). Stay on 3.11.x. The `IntervalTrigger`/`add_job`/`misfire_grace_time` API used here is 3.x-stable.

## Decision Points (for the planner)

### DP-1: Dedup store — dedicated `uv_alerts` table vs. reuse the `alerts` table
**Recommendation: a NEW dedicated `uv_alerts` table.** Rationale:
- The existing `alerts` table's columns are briefing-failure-shaped (`slot_time`, `reason`, `severity`, `resolved_at_utc`) and its `UNIQUE(location_name, slot_time, local_date)` key has no `alert_kind` dimension. Overloading `slot_time` to carry `'prewarn'`/`'crossing'`/`'allclear'` is possible but semantically muddy and risks a future briefing-alert query accidentally matching UV rows.
- A dedicated table keyed `(location_id, local_date, alert_kind)` keeps the UV namespace fully separate from briefing exactly-once — which is also a UV-06 safety property (a UV dedup bug can never touch the briefing `sent_log`/`alerts` rows).
- It's the same `INSERT OR IGNORE` + idempotent-schema discipline, so it costs ~30 lines and reuses the established pattern.
- Keying on `location.id` (the stable rename-safe identity, `models.py:96`) not `location.name` is the correct choice — matches what the briefing exactly-once key would use today.

**In-memory set: rejected.** Loses state on the mid-day restarts this service actually experiences (Pitfall 2).

### DP-2: `interval_seconds` live-reload vs restart-deferred
**Recommendation: restart-deferred** (document like `[reload] watch`). Threshold/lead/margin/enable ARE live-reloadable via the holder re-read (Pattern 2). Re-registering `__uvmonitor__` in `_reconcile_jobs` to pick up a new interval live is possible but adds reconcile surface for a knob that rarely changes — defer it.

### DP-3: New config model shape
Mirror `Reliability`/`ReloadConfig`. Suggested (planner finalizes names — Claude's discretion per CONTEXT):
```python
class UvConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    monitor_enabled: bool = True
    interval_seconds: int = 900            # 15 min (UV-04 default)
    prewarn_lead_minutes: int = 30         # D-03 time-proximity (configurable)
    value_margin: float = 1.0              # D-03 value-proximity (~1 of threshold)
    # threshold lives in Phase-14's UV config (UV-03) — the monitor READS it, does not redefine it
```
**Note:** the **threshold** (default 6) and **pre-warning lead** are owned by Phase 14 (UV-03: "User configures a UV sunscreen threshold and a pre-warning lead in config"). Phase 15 must READ Phase-14's threshold/lead, not redefine them — coordinate field placement with the Phase-14 plan so there's one `[uv]` table, not two. The monitor-only knobs (interval, value-margin, enable) are Phase 15's additions to that same table.

## Phase-14 Dependency Contract (READ THIS)

Phase 15 cannot be implemented until Phase 14 lands the following. The Phase-15 planner MUST add a Wave-0 verification that these exist before building the monitor:

1. **A reusable UV computation helper** that, given the One Call payload (with `hourly[].uvi`) and a threshold, returns: current UV, today's max UV, interpolated (~minute) threshold-crossing time, protect-window start/end, and peak time/value. (14-CONTEXT D-02/D-03; "design it for reuse" / "Phase 15's monitor reuses this same helper".)
2. **`exclude` changed to keep `hourly`** in `weatherbot/weather/client.py` (currently `"minutely,hourly"` → must become `"minutely"` or similar so `hourly[].uvi` is present). Also confirm `daily[0].sunrise`/`sunset` are present (they are, since `daily` is not excluded).
3. **A configurable UV threshold + pre-warn lead** in config (UV-03), in a `[uv]`-style table the monitor extends.

If Phase 14's plan is written without "design the helper for reuse" and "keep hourly," Phase 15 inherits hidden breakage. **Recommend the Phase-15 planner cross-checks the Phase-14 SUMMARY before planning, or that Phase 14 and 15 are planned together.**

## Open Questions

1. **Does the Phase-14 UV helper exist with the right signature when Phase 15 is implemented?**
   - What we know: Phase 14 (`14-CONTEXT.md`) commits to building a reusable helper and exposing crossing/window/peak; phases execute 12→13→14→15 in order, so Phase 14 lands first.
   - What's unclear: Phase 14 is not yet planned (only CONTEXT exists) — the exact helper module path, function name, and return shape are undetermined.
   - Recommendation: Phase-15 plan adds a Wave-0 task "verify Phase-14 UV helper API + `hourly` in payload"; if Phase 14/15 are planned back-to-back, pin the helper signature in Phase 14's plan and reference it in Phase 15's.

2. **Cache reuse vs. direct fetch for the monitor.**
   - What we know: `ForecastCache` exists (TTL 600s) and is wired for the bot; the monitor needs `hourly[]`.
   - What's unclear: whether the bot cache stores the full payload incl. `hourly` (it stores a `LookupResult`/`Forecast`, which may not retain `hourly`).
   - Recommendation: default to a direct `client.fetch_onecall` in the monitor (budget allows it — see below); revisit cache reuse only if call volume becomes a concern.

3. **Should the monitor post a daily "already high at first poll" exactly like a crossing, or with distinct wording?**
   - What we know: D-04 says "send one 'already high' alert" phrased like crossing; D-06 gives the wording.
   - Recommendation: reuse the `crossing` dedup kind (so it still counts once/day) but select the "already ≥" wording when `uvi_now >= T` on the first poll with no prior crossing row.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| APScheduler 3.x | Interval monitor job | ✓ | 3.11.2 | — |
| httpx | Per-tick One Call fetch | ✓ | 0.28.1 | — |
| discord-webhook | Alert delivery | ✓ | 1.4.1 (pin) | — |
| pydantic / pydantic-settings | `[uv]` config model | ✓ | 2.13.4 / 2.14.1 | — |
| sqlite3, zoneinfo (stdlib) | Dedup + daylight bounding | ✓ | built-in (3.12) | — |
| OpenWeather One Call 3.0 (live, card-on-file) | Forecast polling | ✓ (already in production use) | API 3.0 | — |
| Phase-14 UV helper + `exclude` change | Crossing/window/daylight computation | ✗ (not yet implemented — Phase 14 precedes 15) | — | **No fallback — hard prerequisite.** Phase 14 must land first. |

**Missing dependencies with no fallback:**
- The Phase-14 UV helper and the `hourly`-preserving `exclude` change. These are owned by Phase 14, which executes before Phase 15 in the roadmap order — so the dependency is satisfied by sequencing, not by a fallback. The Phase-15 planner MUST verify them at Wave 0 (Phase-14 Dependency Contract above).

## API-Budget Math (UV-04: "well under API limits")

**Cap:** One Call 3.0 free tier = **1,000 calls/day** (card-on-file; charged only beyond 1,000). `[VERIFIED: WebSearch — apiscout.dev + openweathermap.org/api/one-call-3, 2026]`

**Monitor worst case (summer, both cities active same day — though the two-city split means usually only one is active):**
- Daylight ≈ 16 h max (high-summer northern-mid-latitude).
- Polls/hour at 15-min interval = 4.
- Fetches/poll = 2 (imperial + metric, matching `lookup_weather`/`send_now`). *If the monitor only needs one unit system for UV decisions, this halves to 1.*
- Active locations same day ≤ 2.

Worst case: `16 h × 4 polls/h × 2 units × 2 locations = 256 calls/day`.
Plus briefings (a handful) + on-demand commands. Even doubling for safety stays **< 600/day ≪ 1,000/day cap.** With the realistic single-active-city pattern and one-unit UV decisions it's ~64 calls/day.

**Conclusion:** The 15-min default is comfortably within budget with large headroom. The daylight-only + active-only scoping is what keeps it lean (a naive 24×7×all-locations loop would be `24×4×2×2 = 384`/day even without scoping — still under cap, but the scoping is correct design and leaves room for the future severe-weather loop ENH-V2-03). **Optimization available if ever needed:** fetch a single unit system for UV (UV index is unit-independent), halving the count.

## Sources

### Primary (HIGH confidence)
- `weatherbot/scheduler/daemon.py` (read in full) — `_heartbeat_tick` + `IntervalTrigger` registration (line 1078), `fire_slot` per-job isolation + try/except discipline, `run_daemon` wiring, `_reconcile_jobs`, best-effort channel-post idiom (`_do_reload` line 665).
- `weatherbot/weather/store.py` (read in full) — `record_alert`/`claim_slot` `INSERT OR IGNORE` + `rowcount==1` dedup, idempotent `_SCHEMA` table-add pattern, `alerts`/`heartbeat`/`health` table shapes, tz-from-configured-`Location.timezone` discipline.
- `weatherbot/weather/models.py` (read in full) — `Forecast` shape, `daily[0].uvi`, the `uvi_max >= 6` hardcoded threshold Phase 14 unifies.
- `weatherbot/weather/client.py` (read in full) — `fetch_onecall` with `exclude=minutely,hourly` (the Pitfall-1 blocker), 10s timeout, key-hygiene.
- `weatherbot/scheduler/catchup.py` + `scheduler/days.py` (read) — `_fires_on`/`_weekday_set`/`parse_days` (the reusable active-today logic).
- `weatherbot/config/models.py`, `holder.py`, `loader.py`, `interactive/lookup.py`, `interactive/cache.py` (read) — config model pattern (`Reliability`/`ReloadConfig`/`BotConfig`), `ConfigHolder.current()` lock-free read, read-only fetch precedent, TTL cache + invalidate wiring.
- Installed versions verified this session: `apscheduler 3.11.2`, `httpx 0.28.1`, `pydantic 2.13.4` (`uv run python -c`).
- APScheduler 3.x user guide — exception isolation, misfire_grace_time, coalesce, max_instances, default ThreadPoolExecutor max_workers=10. https://apscheduler.readthedocs.io/en/3.x/userguide.html

### Secondary (MEDIUM confidence)
- APScheduler 3.x exception-isolation behavior (job exceptions logged + `EVENT_JOB_ERROR`, scheduler + other jobs keep running) — WebSearch cross-referenced with apscheduler.readthedocs.io events/FAQ pages.
- OpenWeather One Call 3.0 free-tier 1,000 calls/day + pay-as-you-go beyond — https://apiscout.dev/guides/openweathermap-free-tier-limits-2026 and https://openweathermap.org/api/one-call-3 (consistent with CLAUDE.md's recorded HIGH-confidence sources).

### Project context (HIGH confidence)
- `15-CONTEXT.md`, `14-CONTEXT.md`, `REQUIREMENTS.md` (UV-04..06), `ROADMAP.md` (Phase 15), `STATE.md`, `CLAUDE.md` (stack + "What NOT to Use"), MEMORY.md (live systemd service, editable install).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The monitor needs BOTH imperial+metric fetches per poll (mirroring `lookup_weather`). UV index is actually unit-independent, so one fetch may suffice. | API-Budget Math / Pattern 4 | Low — over-estimates budget (conservative); if true, halve the call count. Planner should confirm whether the alert wording needs temp in a unit. |
| A2 | Phase 14 will keep `hourly` in `exclude` and build a reusable UV helper. Inferred from `14-CONTEXT.md` intent, not yet implemented. | Pitfall 1 / Phase-14 Dependency Contract / Open Q1 | HIGH if wrong — Phase 15 silently breaks. Mitigated by a mandatory Wave-0 verification. |
| A3 | `_fires_on`/`_weekday_set` semantics (Mon=0) exactly match what "active today" needs. Verified by reading the code; the only change is promoting `_fires_on` to public. | Pattern / Code Examples | Low — direct code read confirms it. |
| A4 | DATA-03 "delivered-only persistence" means the monitor must NOT call `store.persist`. Inferred from STATE.md Deferred Items + `persist` being on the delivery path only. | Pattern 4 | Low-Medium — if monitor persistence were actually desired, it'd inflate the time series; the safe default (don't persist) matches the stated semantic. |
| A5 | `max_instances` default is 1 in APScheduler 3.x (so stacking is already prevented); setting it explicitly is for clarity. | Pitfall 4 | Low — verified against official docs ("By default, only one instance of each job is allowed to be run at the same time"). |

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all versions verified installed; matches CLAUDE.md.
- Architecture / mechanism (IntervalTrigger job + isolation): HIGH — direct heartbeat precedent read verbatim; APScheduler 3.x isolation verified against official docs.
- Dedup design: HIGH — exact `record_alert`/`claim_slot` pattern already in the codebase.
- Active/daylight logic: HIGH — reuses existing `_fires_on`; tz discipline matches existing Pitfall-3 guards.
- Decision-branch logic (pre-warn/crossing/all-clear): MEDIUM-HIGH — derived directly from the locked D-03/D-04/D-05 decisions; the exact interpolated-crossing inputs depend on the Phase-14 helper (Open Q1).
- API budget: HIGH — arithmetic against the verified 1,000/day cap.
- Cross-phase dependency on Phase 14: MEDIUM — Phase 14 not yet implemented; satisfied by roadmap sequencing + a mandatory Wave-0 check (A2).

**Research date:** 2026-06-18
**Valid until:** ~2026-07-18 (stable stack; the one volatile input is the not-yet-built Phase-14 helper — re-verify its API the moment Phase 14 lands).
