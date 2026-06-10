# Phase 3: Always-On Scheduler - Research

**Researched:** 2026-06-10
**Domain:** In-process wall-clock scheduling (APScheduler 3.x), DST-safe per-location firing, SQLite idempotency, missed-send recovery, render-boundary metadata threading
**Confidence:** HIGH

## Summary

Phase 3 converts the proven manual `send_now` pipeline into a foreground daemon (`weatherbot --run`)
that fires each location's briefings at its own local wall-clock time. The technical core is small and
well-bounded: register one APScheduler `BackgroundScheduler` cron job per enabled `(location, schedule-entry)`
with the job's `timezone=` set to the **location's** IANA zone, then sit in a foreground block until SIGTERM/Ctrl-C.
The hard correctness comes not from APScheduler but from **two project-owned mechanisms** the CONTEXT locked: a
SQLite **sent-log** keyed on `(location, send-time, local-date)` (D-06/D-08) and a **startup catch-up scan**
(D-04/D-10) that re-derives "what should have fired in the last 90 minutes" from config + the sent-log. APScheduler's
own misfire/coalesce machinery is explicitly NOT trusted for cross-restart recovery because the memory jobstore
loses all missed-fire state on restart — the sent-log + scan own SCHD-06/SCHD-07.

DST safety (success criterion #3) is the product of two facts together: (a) `CronTrigger(timezone=tz)` fires at
**wall-clock** local time, so a 07:00 morning send is never inside the skipped spring-forward hour and never inside
the repeated fall-back hour (those are the 01:00–02:59 band, far from morning sends), and (b) the per-day idempotency
key collapses any theoretical double-fire to exactly one send. The render boundary gains a small `ScheduleContext`
(scheduled time, actual send time, late?) threaded into `send_now` alongside the `Forecast`, populating the three
new placeholders `{sent_at}`/`{checked_at}`/`{schedule_note}` and collapsing `{schedule_note}` to empty for on-time
and manual sends (mirroring the existing `{hint}`/`{alert}` empty-collapse pattern).

**Primary recommendation:** Add `apscheduler>=3.11.2,<4` and `time-machine` (dev) to `pyproject.toml`. Build a
`weatherbot/scheduler/` package with three testable-in-isolation pieces — a **`days` parser** (presets→APScheduler
`day_of_week` string), a **catch-up planner** (pure function: config + sent-log + now → list of slots to fire), and
a **sent-log store** helper in `weather/store.py` — then a thin `run_daemon()` that wires them to `BackgroundScheduler`
and calls the existing `send_now` per fire. Test the planner, parser, and sent-log as pure units; test firing by invoking
the job callback directly (never by sleeping real wall-clock time).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cron job registration per (location, slot) | Scheduler (`weatherbot/scheduler/`) | Config (`config/models.py`) | Scheduler owns trigger construction; config supplies the validated declarative schedule |
| `days` preset/list → `day_of_week` | Config validation (parse/validate at load) + Scheduler (consume) | — | Fail-loud-at-load discipline (Phase 2) requires the vocabulary validate in pydantic; the scheduler just consumes the normalized form |
| DST-correct wall-clock firing | Scheduler (`CronTrigger(timezone=)`) | stdlib `zoneinfo` | APScheduler owns wall-clock semantics; zoneinfo owns the IANA tz database |
| Idempotency (was this slot sent today?) | Data layer (`weather/store.py` sent-log) | Scheduler (queries before fire) | Persistence is the source of truth; the scheduler only reads/writes through the store seam |
| Missed-send catch-up | Scheduler (pure catch-up planner) | Data layer (sent-log) + Config | Recovery is a derived computation over config + sent-log; it must NOT depend on APScheduler misfire state |
| Send composition (fetch→persist→render→deliver) | CLI composition root (`cli.send_now`) | weather/templates/channels | Unchanged seam; the scheduler is just a new *caller* of `send_now` |
| Schedule metadata for `{sent_at}`/`{schedule_note}` | Render boundary (`send_now` ↔ `placeholders()`) | Scheduler (supplies context) | The render call must accept scheduler-derived timing that does not live on `Forecast` |
| Foreground lifecycle / signal handling | CLI `--run` (`main`) | Scheduler | The daemon's block/shutdown is a CLI concern; Phase 5 owns supervision/backgrounding |

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Schedule entries are nested under each location as a TOML array of tables `[[locations.schedule]]` (chosen over a separate top-level `[[schedule]]`).
- **D-02:** Each schedule entry has three fields: `time` (`"HH:MM"` 24-hour string), `days` (friendly presets `"mon-fri"`/`"weekends"`/`"daily"`/`"weekdays"` AND explicit comma lists like `"sat,sun"`/`"mon,wed,fri"`), `enabled` (boolean, default `true`; `false` pauses without deleting). Define and validate the exact accepted vocabulary at config load, fail loud on a bad token.
- **D-03:** A location may carry multiple `[[locations.schedule]]` blocks.
- **D-04:** Recovery uses a bounded grace window of **90 minutes, hardcoded (not config)**. A missed briefing is delivered only if recovery is < 90 min after the scheduled time; otherwise skip and log.
- **D-05:** Pipeline re-fetches live weather at send time, so a recovered send shows *current* weather, not stale data. Recovery is about timing relevance, not data freshness.
- **D-06:** Dedup key is `(location, send-time, local-date)`. A slot is identified by its send-time string (`"HH:MM"`), not an id or list index. Editing a send-time naturally becomes a new slot.
- **D-07:** A slot is marked sent **only AFTER successful delivery** (Discord confirms). A crash mid-send leaves it unsent so it can re-fire; the tiny crash-after-send-before-record window is accepted for v1 (hardened by Phase 4).
- **D-08:** The "already sent" log is a **new table in the existing `data/weatherbot.db`**, keyed by the D-06 tuple. Reuse the store's connection/secret-hygiene discipline.
- **D-09:** Add `weatherbot --run` (flag style). Runs in the **foreground**, blocks, logs to stdout, shuts down cleanly on Ctrl-C / SIGTERM. Does NOT self-daemonize (Phase 5 owns supervision). `--send-now` stays available.
- **D-10:** On startup the daemon **announces its schedule** (every enabled slot: location, time, days, computed next-fire), runs the missed-send catch-up scan, then idles.
- **D-11:** Scheduler is **APScheduler 3.x** (`BackgroundScheduler` + per-job `CronTrigger(timezone=<location IANA tz>)`). Add `apscheduler` (3.11.x line — NOT 4.x). Each enabled `(location, schedule-entry)` is one cron job in the location's configured IANA zone (config tz authoritative). DST safety = `CronTrigger` + the D-06 key together.
- **D-12:** Add three new editable template placeholders: `{sent_at}` (delivery time), `{checked_at}` (weather fetch time), `{schedule_note}` (human late-note, wording Claude's discretion).
- **D-13:** Display rule: `{sent_at}`/`{checked_at}` render on **every** message (scheduled and manual `--send-now`). `{schedule_note}` is populated **only when the send is late/off-schedule** (recovered within the 90-min window); empty on on-time sends and manual `--send-now`, collapsing like `{hint}`/`{alert}`.
- **D-14:** All displayed times use the **location's local time** (its configured IANA tz).
- **D-15:** These placeholders **extend Phase 2's canonical placeholder set** — add to `Forecast.placeholders()` (or wherever the map is built) AND to the `validate_template` canonical set, and reference them in the three starter templates. `{sent_at}`/`{schedule_note}` derive from **scheduler context**, NOT the weather payload, so the render call must thread scheduling metadata in alongside the `Forecast`. Design it so manual `--send-now` still renders `{sent_at}`/`{checked_at}` with an empty `{schedule_note}`.

### Claude's Discretion

- Exact accepted `days` vocabulary/aliases and their parsing (D-02) — sensible, validated.
- Exact wording/format of `{schedule_note}` and the time formatting of `{sent_at}`/`{checked_at}` (e.g. `7:30 AM` vs `07:30`); carry a sensible default, user will edit.
- Sent-log table name/columns and the catch-up scan implementation (D-08/D-10).
- The dual-unit / two-call fetch strategy and module layout carry forward from Phase 2 — the scheduler invokes the existing `send_now` composition root; planner decides exactly how scheduling metadata is threaded in (D-15).
- APScheduler job-build details (job ids, coalesce/misfire settings) — note that cross-restart catch-up is OWNED by the D-08 sent-log scan (memory jobstore won't recover missed fires across a restart), so don't rely on APScheduler's misfire handling alone for SCHD-06.

### Deferred Ideas (OUT OF SCOPE)

- **Configurable grace window** — hardcoded 90 min (D-04). Config exposure is a later enhancement.
- **Self-daemonizing / background `--run`** — explicitly rejected (D-09); supervision/reboot survival/run-on-boot are Phase 5 (OPS-01/02).
- **Retry-then-alert on a failed scheduled send, heartbeat/liveness** — Phase 4 (RELY-*). Phase 3 marks a slot sent only on success (D-07).
- **Configurable hint/annotation thresholds & richer schedule semantics** (per-slot template overrides, skip-on-holiday) — not requested, out of scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCHD-01 | Each location owns its own schedule entries, supporting multiple send-times per day | `Location.schedule: list[Schedule]` nested model (D-01/D-03); one cron job per enabled entry (Config-as-jobs expansion, ARCHITECTURE Pattern 1) |
| SCHD-02 | Each schedule entry can be toggled on/off without deleting it | `Schedule.enabled: bool = True`; disabled entries are skipped at job registration AND at catch-up (stay in the file) |
| SCHD-03 | Each schedule entry supports day-of-week selection | `days` field → APScheduler `day_of_week` string; the parser maps presets/lists to `mon-fri`/`sat,sun`/etc. (`day_of_week` accepts ranges and comma lists natively) |
| SCHD-04 | Each send-time fires at the location's local wall-clock time and survives DST | `CronTrigger(hour, minute, day_of_week, timezone=loc.timezone)` — wall-clock semantics; per-job tz, not host tz |
| SCHD-05 | An always-on in-process scheduler computes the next run per location timezone | `BackgroundScheduler` foreground daemon; `scheduler.get_jobs()[i].next_run_time` gives the per-tz next fire for the D-10 announce |
| SCHD-06 | After downtime, send any missed briefing on recovery (bounded by 90-min grace, D-04) | Pure catch-up planner over config + sent-log; does NOT use APScheduler misfire (memory jobstore loses it across restart) |
| SCHD-07 | Idempotent per `(location, schedule-slot, local-date)` — never sent twice | Sent-log table with the D-06 tuple as a UNIQUE key; check-before-fire + mark-after-success (D-07) prevents DST double-fire and restart replay |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| APScheduler | `>=3.11.2,<4` | In-process cron scheduler | [CITED: apscheduler.readthedocs.io/en/3.x] De-facto Python in-process scheduler; `BackgroundScheduler` + `CronTrigger` natively express "07:00 Mon–Fri" with a per-job IANA `timezone=`. Locked by STACK.md/CLAUDE.md. **3.x line — NOT 4.x** (4.0 is pre-release, "do NOT use in production"). |
| zoneinfo (stdlib) | built-in (3.12) | IANA tz lookups | [VERIFIED: codebase] Already used in `config/models.py`, `weather/models.py`, `weather/store.py` for the authoritative configured tz. Reuse it for the catch-up scan's local-date/time math. |
| sqlite3 (stdlib) | built-in | Sent-log persistence | [VERIFIED: codebase] The existing `weather/store.py` already owns `data/weatherbot.db`; the sent-log is a new table there (D-08), no new dependency. |
| structlog | `>=26.1.0` | Structured logging | [VERIFIED: codebase] Already the project's logger (`cli.py`). The daemon's schedule-announce, catch-up decisions, and per-fire outcomes log through it — outcome-only, never secrets (T-04-01). |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| signal (stdlib) | built-in | SIGTERM/Ctrl-C clean shutdown | [CITED: docs.python.org/3/library/signal] `--run` registers a handler (or catches `KeyboardInterrupt`) and calls `scheduler.shutdown(wait=False)` for clean foreground exit (D-09). |
| time-machine | `>=2.16` (dev) | Deterministic clock/tz in tests | [CITED: time-machine.readthedocs.io] C-extension time mocking; when the target `datetime` carries a `ZoneInfo` tzinfo it also mocks the *current timezone* via `time.tzset()` (Unix). Use it ONLY for tests that need a frozen "now" for the catch-up planner. **Not needed to test job firing** — call the job callback directly instead. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| APScheduler `day_of_week` native parsing | Hand-rolled preset→weekday-set mapping | `day_of_week` already accepts `"mon-fri"`, `"sat,sun"`, `"mon,wed,fri"` natively — but the project still needs a thin validator to (a) fail loud on a bad token at config load (Phase 2 discipline) and (b) normalize friendly aliases (`"weekends"`, `"weekdays"`, `"daily"`) that APScheduler does NOT understand. So: validate+normalize in pydantic, then hand the normalized string to `day_of_week`. |
| time-machine | freezegun | freezegun is simpler but does NOT mock the OS timezone via `tzset()`; time-machine does, which matters if any test relies on APScheduler reading wall-clock. Both are acceptable; prefer time-machine for the tz-mocking and the migration CLI. Most Phase 3 tests need neither — inject `now` explicitly. |
| BackgroundScheduler | BlockingScheduler | `BlockingScheduler.start()` blocks the calling thread itself (no separate `--run` loop needed). Viable, but `BackgroundScheduler` keeps the main thread free to run the catch-up scan, announce the schedule, and own the signal handler/`while True: sleep` block explicitly — clearer lifecycle for D-09/D-10. Either is defensible; **BackgroundScheduler is the CONTEXT-locked choice (D-11).** |
| New `scheduler/` package | Inline in `cli.py` | A `weatherbot/scheduler/` package keeps the pure pieces (days-parser, catch-up planner) independently unit-testable and keeps `cli.py` a thin composition root (matches the Phase 1–2 module discipline). |

**Installation:**
```bash
uv add "apscheduler>=3.11.2,<4"
uv add --dev time-machine
```

**Version verification:** `apscheduler` latest is **3.11.2** (3.11.2.post1 docs build) per PyPI/readthedocs as of 2026-06-10 [CITED: pypi.org/project/APScheduler]. `time-machine` latest is **3.2.0** [CITED: time-machine.readthedocs.io] (pin `>=2.16` to be permissive; any 2.16+/3.x is fine). The offline sandbox blocked `pip index versions`; versions were confirmed via official docs/PyPI pages, not the registry CLI — treat the exact patch as `[ASSUMED]` until `uv add` resolves it.

## Package Legitimacy Audit

> `slopcheck` could not be installed in the offline sandbox; `pip index versions` returned no output (no network). Per the graceful-degradation rule, both new packages are tagged `[ASSUMED]` and the planner SHOULD gate the `uv add` behind a `checkpoint:human-verify` (or rely on `uv`/`uv.lock` resolution against the real registry at execution time). Both are extremely well-known, long-lived packages with high downloads and official source repos, so risk is low.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| APScheduler | PyPI | ~10 yrs | very high (millions/mo) | github.com/agronholm/apscheduler | unavailable | `[ASSUMED]` — Approved (locked by CLAUDE.md/STACK.md), verify on `uv add` |
| time-machine | PyPI | ~6 yrs | high | github.com/adamchainz/time-machine | unavailable | `[ASSUMED]` — Approved (dev-only), verify on `uv add` |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
config.toml ──load_config()──► Config (Location[].schedule[]: Schedule)   [validated at load: HH:MM, days vocab]
   │                                   │
   │                                   ▼
   │                        ┌────────────────────────────────────────────────┐
   │   weatherbot --run ───►│  run_daemon(config, settings, db_path)          │
   │                        │                                                 │
   │                        │  1. announce schedule (D-10)                    │
   │                        │     for each enabled slot: log loc/time/days    │
   │                        │     + computed next_run_time                    │
   │                        │                                                 │
   │   data/weatherbot.db   │  2. CATCH-UP SCAN (D-04/D-10) ─── pure planner  │
   │   ┌──────────────┐     │     plan_catchup(config, sent_log, now)         │
   │   │ sent_log     │◄────┤        → [slots whose scheduled time passed     │
   │   │ (loc,time,   │     │           today, <90min ago, NOT in sent_log]   │
   │   │  local_date) │     │     for each: fire_slot(..., late=True)         │
   │   └──────────────┘     │                                                 │
   │          ▲             │  3. register jobs: BackgroundScheduler          │
   │          │             │     for each enabled slot →                     │
   │          │             │       CronTrigger(hour,minute,                  │
   │          │  mark after │                   day_of_week=days,             │
   │          │  success    │                   timezone=loc.tz)              │
   │          │  (D-07)     │     job callback = fire_slot(loc, slot)         │
   │          │             │                                                 │
   │          │             │  4. block: signal handler / KeyboardInterrupt   │
   │          │             │     → scheduler.shutdown(wait=False)            │
   │          │             └───────────────┬────────────────────────────────┘
   │          │                             │ (each fire)
   │          │                             ▼
   │          │              fire_slot(location, slot, scheduled_dt, late?)
   │          │                 │  check sent_log(loc,time,local_date)? skip if present
   │          │                 ▼
   │          │              send_now(location, ..., schedule_ctx=ScheduleContext(...))
   │          │                 │  fetch(live) → persist → render(+sent_at/checked_at/
   │          │                 │  schedule_note) → channel.send_briefing
   │          │                 ▼
   │          └──── on result.ok: record sent_log(loc,time,local_date)  (D-07)
   ▼
.env ──load_settings()──► Settings (secrets: appid, webhook URL — never logged)
```

### Recommended Project Structure
```
weatherbot/
├── scheduler/
│   ├── __init__.py
│   ├── days.py          # parse_days(): preset/list → APScheduler day_of_week + validation (D-02)
│   ├── catchup.py       # plan_catchup(config, sent_log_reader, now) -> list[MissedSlot] (D-04/D-10) — PURE
│   ├── context.py       # ScheduleContext dataclass (scheduled_dt, sent_dt, checked_dt, late, tz) (D-15)
│   └── daemon.py        # run_daemon(): announce + catch-up + register jobs + block/shutdown (D-09/D-10/D-11)
├── config/
│   └── models.py        # + Schedule model; Location.schedule: list[Schedule] (D-01/D-02/D-03)
├── weather/
│   ├── store.py         # + sent_log table in _SCHEMA; record_sent()/was_sent() helpers (D-08)
│   └── models.py        # Forecast.placeholders() + sent_at/checked_at/schedule_note (D-12/D-15)
└── cli.py               # + --run branch in main(); send_now() accepts schedule_ctx (D-09/D-15)
templates/
├── renderer.py          # CANONICAL set += sent_at, checked_at, schedule_note (D-15)
└── *.txt                # footer line referencing the 3 new placeholders (D-15)
```

### Pattern 1: Config-as-jobs expansion (declarative schedule → concrete triggers)
**What:** Walk the validated `Config` at boot; register one `BackgroundScheduler` cron job per enabled `(location, schedule-entry)`. Config is the source of truth; the scheduler holds derived state only.
**When to use:** Editable file config with day-of-week + multiple toggleable send-times per location — exactly this phase.
**Example:**
```python
# Source: ARCHITECTURE.md Pattern 1 (adapted for the nested Schedule model)
# CITED: apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler()
for loc in config.locations:
    for slot in loc.schedule:
        if not slot.enabled:                      # D-02 toggle: skip, don't delete
            continue
        hh, mm = slot.parsed_time()               # "07:00" -> (7, 0)
        scheduler.add_job(
            fire_slot,
            trigger=CronTrigger(
                hour=hh, minute=mm,
                day_of_week=slot.day_of_week,      # normalized: "mon-fri" / "sat,sun"
                timezone=loc.timezone,             # per-LOCATION IANA tz (D-11/SCHD-04)
            ),
            args=[loc, slot],
            id=f"{loc.name}|{slot.time}|{slot.days}",
            misfire_grace_time=None,               # we OWN recovery via the sent-log (D-08)
            coalesce=True,                         # belt-and-suspenders; sent-log is the real guard
        )
scheduler.start()
```

### Pattern 2: `days` preset/list → APScheduler `day_of_week`
**What:** A small parser that validates the D-02 vocabulary at config-load and normalizes it to a string `day_of_week` accepts.
**When to use:** Whenever the config carries the friendly `days` field.
**Example:**
```python
# Source: project-defined (Claude's discretion D-02); day_of_week grammar per
# CITED: apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html
# day_of_week natively accepts: "mon", "sat,sun", "mon-fri", "0-4", "*"
_PRESETS = {
    "daily":    "mon-sun",      # or "*"
    "weekdays": "mon-fri",
    "mon-fri":  "mon-fri",
    "weekends": "sat,sun",
}
_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

def parse_days(raw: str) -> str:
    """Validate + normalize the D-02 days vocabulary; raise ValueError on a bad token."""
    key = raw.strip().lower()
    if key in _PRESETS:
        return _PRESETS[key]
    tokens = [t.strip() for t in key.split(",") if t.strip()]
    bad = [t for t in tokens if t not in _DAYS]
    if not tokens or bad:
        raise ValueError(
            f"invalid days value {raw!r}: use a preset "
            f"({sorted(_PRESETS)}) or a comma list of {sorted(_DAYS)}"
        )
    return ",".join(tokens)
```
> Wire `parse_days` into the `Schedule` pydantic `field_validator` (mirror `Location._tz_must_be_real`) so a bad token fails loud at load (Phase 2 fail-at-load tradition, D-02).

### Pattern 3: Pure catch-up planner (recovery owned by the sent-log, not APScheduler)
**What:** A side-effect-free function that, given the config, a sent-log reader, and "now", returns the slots that should have already fired today but did not — within the 90-min grace window (D-04).
**When to use:** Once at startup (D-10), before `scheduler.start()`.
**Example:**
```python
# Source: project-defined (D-04/D-06/D-10). PURE — inject `now` and the sent-log reader for tests.
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

GRACE = timedelta(minutes=90)   # D-04: hardcoded, NOT config

@dataclass
class MissedSlot:
    location: object
    slot: object
    scheduled_dt: datetime       # tz-aware, in the location's zone
    local_date: str              # YYYY-MM-DD (the dedup key's date component)

def plan_catchup(config, was_sent, now_utc: datetime) -> list[MissedSlot]:
    missed: list[MissedSlot] = []
    for loc in config.locations:
        tz = ZoneInfo(loc.timezone)
        now_local = now_utc.astimezone(tz)
        for slot in loc.schedule:
            if not slot.enabled:
                continue
            if not _fires_on(slot, now_local):     # day-of-week match for TODAY local
                continue
            hh, mm = slot.parsed_time()
            scheduled = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if scheduled > now_local:              # not due yet today — the live job will fire it
                continue
            if now_local - scheduled > GRACE:       # >90 min late — skip + log (D-04)
                continue
            local_date = now_local.date().isoformat()
            if was_sent(loc.name, slot.time, local_date):   # already delivered (D-06)
                continue
            missed.append(MissedSlot(loc, slot, scheduled, local_date))
    return missed
```
> `_fires_on(slot, now_local)` must reuse the SAME day-of-week semantics as the cron trigger (Monday-first, `mon-sun`). Derive it from the normalized `day_of_week` string so the planner and the live trigger never disagree.

### Pattern 4: Sent-log idempotency (check-before-fire, mark-after-success)
**What:** A SQLite table keyed `(location, time, local_date)` with a UNIQUE constraint; `was_sent()` reads it, `record_sent()` writes it AFTER `result.ok` (D-07).
**Example:**
```python
# Source: project-defined (D-06/D-07/D-08). Add to weather/store.py _SCHEMA + helpers.
SENT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS sent_log (
    id            INTEGER PRIMARY KEY,
    location_name TEXT    NOT NULL,
    send_time     TEXT    NOT NULL,   -- "HH:MM" slot identity (D-06)
    local_date    TEXT    NOT NULL,   -- YYYY-MM-DD in the location's tz
    sent_at_utc   INTEGER NOT NULL,
    UNIQUE(location_name, send_time, local_date)
);
"""

def was_sent(db_path, location_name, send_time, local_date) -> bool:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)   # idempotent; same discipline as persist()
        row = conn.execute(
            "SELECT 1 FROM sent_log WHERE location_name=? AND send_time=? AND local_date=?",
            (location_name, send_time, local_date),
        ).fetchone()
    return row is not None

def record_sent(db_path, location_name, send_time, local_date) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO sent_log "
            "(location_name, send_time, local_date, sent_at_utc) VALUES (?, ?, ?, ?)",
            (location_name, send_time, local_date, int(datetime.now(timezone.utc).timestamp())),
        )
        conn.commit()
```
> `INSERT OR IGNORE` on the UNIQUE key makes `record_sent` itself idempotent — even a concurrent re-fire records once. The `was_sent` check is the primary guard; the UNIQUE constraint is the backstop against any race (DST fall-back double-fire, restart replay).

### Pattern 5: Threading schedule metadata through the render boundary (D-15)
**What:** A `ScheduleContext` dataclass carries the scheduler-derived timing the `Forecast` cannot (scheduled time, actual send time, late flag, tz). `send_now` accepts it optionally; when `None` (manual `--send-now`), `{sent_at}`/`{checked_at}` still render (from "now"/fetch time) and `{schedule_note}` collapses to empty (D-13).
**Example:**
```python
# Source: project-defined (D-12/D-13/D-14/D-15).
@dataclass
class ScheduleContext:
    scheduled_dt: datetime | None    # None for manual --send-now (no scheduled time)
    tz: ZoneInfo
    late: bool = False               # True only for a recovered, within-grace send

# send_now signature gains: schedule_ctx: ScheduleContext | None = None
# placeholders are built by MERGING the weather map with a schedule map:
def schedule_placeholders(ctx, sent_dt, checked_dt) -> dict[str, str]:
    tz = ctx.tz if ctx else None
    def fmt(dt): return dt.astimezone(tz).strftime("%-I:%M %p") if (dt and tz) else dt.strftime("%-I:%M %p")
    note = ""
    if ctx and ctx.late and ctx.scheduled_dt is not None:
        note = (f"(intended for {ctx.scheduled_dt.astimezone(tz).strftime('%-I:%M %p')}, "
                f"sent {sent_dt.astimezone(tz).strftime('%-I:%M %p')})")
    return {
        "sent_at": fmt(sent_dt),         # D-13: every message
        "checked_at": fmt(checked_dt),   # D-13: every message; maps to the fetch timestamp
        "schedule_note": note,           # D-13: empty unless late; collapses like {hint}
    }
# render(template, {**forecast.placeholders(), **schedule_placeholders(...)})
```
> Keep these THREE keys out of `Forecast.placeholders()`'s weather concern OR add them as empty-by-default keys there and override at the call site — either works, but the canonical `CANONICAL` set in `renderer.py` MUST include all three so templates validate (D-15). Time format `%-I:%M %p` ("7:30 AM") matches the user's reaction example; it's Claude's discretion (D-12). `%-I` is platform-specific (Linux); use `.lstrip("0")` on `%I` if cross-platform formatting is ever needed.

### Anti-Patterns to Avoid
- **Relying on APScheduler misfire/coalesce for cross-restart recovery:** The memory jobstore discards all next-fire/missed state on process exit. `misfire_grace_time` only covers misses *while the process is alive*. SCHD-06 across a restart is OWNED by the sent-log + catch-up scan (D-08/D-10). Set `misfire_grace_time=None` and treat coalesce as a harmless backstop.
- **Scheduling in UTC or host-local time:** Breaks DST and multi-tz (PITFALLS Pitfall 1). Always pass the location's IANA `timezone=` to `CronTrigger`.
- **Marking a slot sent on attempt:** D-07 requires mark-after-success only. Mark-on-attempt silently loses a failed send and conflicts with Phase 4's retry-then-alert.
- **List-index or explicit-id slot identity:** D-06 keys on the send-time string. Editing a time = a new slot, intentionally.
- **Letting the daemon die on one bad job:** Exception-isolation per job is RELY-06 (Phase 4) — but for Phase 3, wrap each `fire_slot` in a try/except that logs and continues so one bad fire doesn't crash the scheduler thread. (Phase 4 hardens this into retry-then-alert; do the minimal isolation now so success criterion behavior is observable.)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Wall-clock cron firing with DST | A `while True: if now == target` loop | APScheduler `CronTrigger(timezone=)` | DST skip/repeat handling, next-fire computation, day-of-week ranges are all solved and tested in APScheduler |
| Day-of-week range parsing | A weekday-set bitmask | APScheduler `day_of_week` native grammar (`"mon-fri"`, `"sat,sun"`) | Only a thin alias-normalizer (`weekends`/`weekdays`/`daily`) is project-specific |
| IANA tz / DST rules | A tz-offset table | stdlib `zoneinfo.ZoneInfo` | Already the project standard; OS tz database owns the rules incl. DST changes |
| Idempotency store | A JSON file with manual locking | SQLite `UNIQUE` constraint + `INSERT OR IGNORE` | Atomic, race-safe, and the DB already exists (D-08) |
| Deterministic time in tests | `monkeypatch` of `datetime.now` everywhere | Inject `now`/`sent_dt` as params; `time-machine` only where OS-tz mocking is needed | Pure functions with injected time are simpler and faster than global clock patching |

**Key insight:** Almost all the genuinely hard correctness in this phase (DST, day-of-week, race-free dedup) is delegated to APScheduler + zoneinfo + SQLite. The project-owned logic is deliberately small and PURE — the `days` parser, the catch-up planner, the sent-log helpers, and the render-context merge — which is exactly what makes the phase highly testable without wall-clock waits.

## Runtime State Inventory

> This phase ADDS runtime state (the sent-log) rather than renaming, but the inventory still matters because the daemon is the first long-running process and the sent-log is new persisted state.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | NEW `sent_log` table in `data/weatherbot.db` keyed `(location_name, send_time, local_date)`. No existing data carries this. | Additive schema only (`CREATE TABLE IF NOT EXISTS`); no migration. The dedup key uses `location.name` and the `"HH:MM"` slot string — renaming a location or editing a send-time in config naturally orphans old rows (intended per D-06), which is harmless (they just stop matching). |
| Live service config | None — there is no external service holding scheduler state; the config file is the single source of truth and jobs are re-derived on every `--run` (ARCHITECTURE: schedule is declarative/recomputed). | None. |
| OS-registered state | None in Phase 3 — `--run` is foreground and does NOT register systemd/cron (D-09; that's Phase 5 OPS-01). | None — verified by D-09 ("does NOT self-daemonize"). |
| Secrets/env vars | None new. The daemon reads the same `OPENWEATHER_API_KEY` / Discord webhook URL via `load_settings()` as `--send-now`. No new secret. | None. |
| Build artifacts / installed packages | New dependency `apscheduler` enters `pyproject.toml`/`uv.lock`; dev `time-machine`. After adding, `uv sync` so the daemon imports resolve. | `uv add` updates the lock; CI/host must `uv sync`. |

## Common Pitfalls

### Pitfall 1: DST spring-forward skip / fall-back double-fire
**What goes wrong:** A job scheduled inside the skipped hour (01:00–02:59 in US zones) never fires on spring-forward; a job inside the repeated fall-back hour can fire twice.
**Why it happens:** Naive/UTC scheduling, or trusting the scheduler alone for exactly-once.
**How to avoid:** (1) `CronTrigger(timezone=loc.tz)` fires at wall-clock — a 07:00 morning send is never in the 01:00–02:59 transition band, so spring-forward never skips it and fall-back never repeats it. (2) Even if a future send-time landed in the band, the per-day idempotency key (D-06) collapses any double-fire to one. Success criterion #3 is the AND of these two.
**Warning signs:** Two briefings on the November fall-back Sunday; a missing briefing on the March spring-forward Sunday.

### Pitfall 2: Trusting APScheduler to recover missed fires across a restart
**What goes wrong:** The bot is down across 07:00; on restart at 07:20 nothing fires (memory jobstore lost the miss) — SCHD-06 fails. Or, with a persistent jobstore + wrong misfire config, a stale 07:00 briefing fires at noon.
**Why it happens:** Conflating "misfire grace while alive" with "recovery after restart."
**How to avoid:** Own recovery in the catch-up scan (Pattern 3): on startup, re-derive what should have fired today within 90 min and isn't in the sent-log, and fire those once. Set `misfire_grace_time=None`.
**Warning signs:** A reboot mid-morning produces zero or a stale-late briefing; restarting twice produces two briefings (means the sent-log check is missing).

### Pitfall 3: Day-of-week semantics disagreeing between trigger and planner
**What goes wrong:** The catch-up planner thinks "today is Saturday, slot fires" but the cron trigger (or vice versa) disagrees because of a Monday-first vs Sunday-first off-by-one, producing a spurious or missing catch-up send.
**Why it happens:** APScheduler's `day_of_week` is Monday-first (`mon`=0); Python's `date.weekday()` is also Monday-first but `isoweekday()`/`strftime('%w')` differ.
**How to avoid:** Drive `_fires_on()` in the planner from the SAME normalized `day_of_week` string the trigger uses — map weekday names to `date.weekday()` (Mon=0…Sun=6) consistently. Add a unit test that asserts planner-fires == trigger-would-fire for each preset across all 7 weekdays.
**Warning signs:** A `weekends` slot catches up on Friday, or a `mon-fri` slot skips Monday.

### Pitfall 4: `{schedule_note}` / time placeholders leaking into manual sends
**What goes wrong:** Manual `--send-now` renders a stray `(intended for …)` note or crashes because `scheduled_dt` is `None`.
**Why it happens:** The render path assumes a `ScheduleContext` is always present, or formats `None`.
**How to avoid:** `schedule_ctx` defaults to `None`; `{schedule_note}` is `""` unless `ctx.late and ctx.scheduled_dt is not None`; `{sent_at}`/`{checked_at}` always have a value (send "now" / fetch time). Mirror the `{hint}`/`{alert}` empty-collapse. Add a test: `send_now` with no `schedule_ctx` renders `{sent_at}`/`{checked_at}` non-empty and `{schedule_note}` empty.
**Warning signs:** A manual test send shows "(intended for …)"; a `KeyError`/`AttributeError` on `scheduled_dt`.

### Pitfall 5: OpenWeather quota under many catch-up fires
**What goes wrong:** A long outage spanning many days/slots, on restart, could attempt a burst of catch-up sends. (Bounded here: only TODAY's slots within 90 min are eligible — D-04 — so the burst is naturally tiny.)
**Why it happens:** Unbounded backfill.
**How to avoid:** The 90-min/today-only window (D-04) already caps catch-up to at most the slots whose time passed in the last 90 minutes — a rounding error against 60/min, 1M/month. No extra throttle needed for v1. (Phase 4 adds retry/backoff.)
**Warning signs:** N/A for v1 given the bound; watch only if the grace window is ever widened (deferred).

## Code Examples

### Foreground `--run` lifecycle with clean shutdown (D-09)
```python
# Source: project-defined (D-09); BackgroundScheduler + signal per
# CITED: apscheduler.readthedocs.io/en/3.x/userguide.html  &  docs.python.org/3/library/signal
import signal, threading
from apscheduler.schedulers.background import BackgroundScheduler

def run_daemon(config, settings, db_path) -> int:
    scheduler = BackgroundScheduler()
    _register_jobs(scheduler, config, settings, db_path)   # Pattern 1
    _announce_schedule(scheduler, config)                  # D-10: log slots + next_run_time
    _run_catchup(config, settings, db_path)                # Pattern 3 (before start so it logs first)
    scheduler.start()

    stop = threading.Event()
    def _handle(signum, frame):
        stop.set()
    signal.signal(signal.SIGTERM, _handle)
    try:
        stop.wait()                # block foreground until SIGTERM
    except KeyboardInterrupt:       # Ctrl-C
        pass
    finally:
        scheduler.shutdown(wait=False)   # clean exit (D-09)
    return 0
```
> Run the catch-up scan and the announce BEFORE `scheduler.start()` so the log reads cleanly (schedule, then any recovered sends, then "idle"). The `fire_slot` job callback used in catch-up and in the live job is the SAME function — it queries `was_sent`, calls `send_now(..., schedule_ctx=...)`, and on `result.ok` calls `record_sent` (D-07).

### `Schedule` config model (D-01/D-02/D-03)
```python
# Source: project-defined (D-01/D-02); mirrors Location validators in config/models.py
from pydantic import BaseModel, ConfigDict, field_validator
from weatherbot.scheduler.days import parse_days

class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")   # same strictness as Location
    time: str            # "HH:MM"
    days: str            # preset or comma list (validated/normalized)
    enabled: bool = True # D-02 default true; false pauses without deleting

    @field_validator("time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        try:
            hh, mm = v.split(":")
            h, m = int(hh), int(mm)
            assert 0 <= h <= 23 and 0 <= m <= 59 and len(mm) == 2
        except Exception as e:
            raise ValueError(f"time must be 'HH:MM' 24-hour, got {v!r}") from e
        return v

    @field_validator("days")
    @classmethod
    def _days(cls, v: str) -> str:
        parse_days(v)    # raises on a bad token (fail-loud-at-load, D-02)
        return v         # keep the raw form for the dedup key/announce; normalize at use
# Location gains:  schedule: list[Schedule] = Field(default_factory=list)
```
> Decide: store `days` raw (and normalize at trigger/planner use) or normalize on validation. Raw-store keeps the announce/log human-friendly ("weekends") while the trigger consumes `parse_days(days)`. Add `parsed_time()` and `day_of_week` helpers to `Schedule` (or a thin adapter) so the trigger and planner share them.

### Template footer for the new placeholders (D-15)
```text
... existing briefing body ...
{hint}
{alert}
— sent {sent_at} · weather checked {checked_at}
{schedule_note}
```
> Add an analogous footer line to all three starter templates (`briefing-sectioned.txt`, `briefing-multiline.txt`, `briefing-compact.txt`). `{schedule_note}` on its own line collapses to nothing on on-time/manual sends (like `{hint}`/`{alert}`).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| APScheduler 4.0 API | APScheduler 3.11.x stable line | 4.0 still pre-release as of 2026 | Stay on 3.x; 4.0 "do NOT use in production", no jobstore migration path |
| freezegun for time mocking | time-machine (C-extension, mocks OS tz via `tzset()`) | time-machine matured ~2020→3.x | Faster, and the only one that mocks the *current timezone* — relevant if a test ever relies on APScheduler reading wall-clock; most Phase 3 tests inject `now` and need neither |

**Deprecated/outdated:**
- APScheduler 4.x — pre-release, excluded by CLAUDE.md/STACK.md.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Exact patch versions (apscheduler 3.11.2, time-machine 3.2.0) — confirmed via official docs/PyPI pages, not the registry CLI (offline sandbox) | Standard Stack | LOW — `uv add` resolves the real current version against the registry; pins are permissive (`>=3.11.2,<4`) |
| A2 | `%-I:%M %p` time formatting ("7:30 AM") is acceptable and Linux-only | Pattern 5 / Code Examples | LOW — Claude's discretion (D-12); user will edit. Use `%I`.lstrip("0") if cross-platform output is ever needed |
| A3 | `days` stored raw + normalized at use (vs normalized on validation) | Code Examples | LOW — both work; raw-store is a readability choice, planner may pick either |
| A4 | Minimal per-job try/except exception isolation is in-scope for Phase 3 (full RELY-06 is Phase 4) | Anti-Patterns | LOW — without it, one bad fire kills the scheduler thread and breaks the observable success criteria; the minimal guard is justified, full retry-then-alert is deferred |

## Open Questions (RESOLVED)

1. **Should `days` be stored normalized or raw in the `Schedule` model?**
   - What we know: APScheduler `day_of_week` needs the normalized form; the announce/log reads nicer with the raw friendly form.
   - What's unclear: purely a code-style choice with no correctness impact.
   - RESOLVED: store raw, normalize via `parse_days()` at trigger/planner use; keep a `day_of_week` property on `Schedule`. Adopted by Plan 03-01 Task 2.

2. **Where do `{sent_at}`/`{checked_at}`/`{schedule_note}` live — in `Forecast.placeholders()` (empty defaults) or merged at the `send_now` call site?**
   - What we know: `CANONICAL` in `renderer.py` MUST include all three (D-15). `{sent_at}`/`{schedule_note}` derive from scheduler context, not weather.
   - What's unclear: cleanest seam.
   - RESOLVED: merge at the call site (`render(template, {**forecast.placeholders(), **schedule_placeholders(...)})`) so `Forecast` stays weather-only; add the three keys to `CANONICAL` regardless. Adopted by Plan 03-02 (placeholders() stays weather-only).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | runtime | ✓ | 3.12 (`requires-python>=3.12`) | — |
| uv | dependency mgmt | ✓ (project standard) | — | `pip install` as last resort |
| apscheduler | scheduler (D-11) | ✗ (not yet in deps) | — | none — must `uv add`; no viable substitute given D-11 |
| time-machine | DST/clock tests | ✗ (not yet in deps) | — | inject `now` explicitly (most tests need no clock mock); freezegun as alt |
| IANA tz database | DST correctness | ✓ (OS-provided via zoneinfo) | OS | `tzdata` pip package if the host lacks the system db (Pi/minimal container) |
| OpenWeather API + key | live send only | ✓ (used since Phase 1) | — | tests mock the client (no network) |

**Missing dependencies with no fallback:**
- `apscheduler` — must be installed (`uv add "apscheduler>=3.11.2,<4"`). This is the only hard install for the phase.

**Missing dependencies with fallback:**
- `time-machine` (dev) — explicit `now` injection covers most tests; install only for tests that exercise OS-tz/wall-clock behavior.
- IANA tz db — add the `tzdata` package if running on a minimal host without the system zoneinfo database.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"`) |
| Quick run command | `uv run pytest tests/test_scheduler.py -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SCHD-01 | Multiple `[[locations.schedule]]` parse into `Location.schedule` list | unit | `uv run pytest tests/test_config.py::test_multiple_schedule_entries -x` | ❌ Wave 0 |
| SCHD-02 | `enabled=false` slot is skipped at registration AND catch-up, stays in config | unit | `uv run pytest tests/test_scheduler.py::test_disabled_slot_not_fired -x` | ❌ Wave 0 |
| SCHD-02 | `parse_days` rejects bad token at config load (fail-loud) | unit | `uv run pytest tests/test_config.py::test_bad_days_fails_load -x` | ❌ Wave 0 |
| SCHD-03 | Each preset/list maps to the right weekdays; planner agrees with trigger across all 7 days | unit | `uv run pytest tests/test_scheduler.py::test_days_parsing_matrix -x` | ❌ Wave 0 |
| SCHD-04 | Job registered with `timezone=loc.timezone`; two locations in different tz fire at own local time | unit | `uv run pytest tests/test_scheduler.py::test_per_location_timezone -x` | ❌ Wave 0 |
| SCHD-05 | `run_daemon` registers one enabled job per slot; announce logs next_run_time | unit | `uv run pytest tests/test_scheduler.py::test_jobs_registered_and_announced -x` | ❌ Wave 0 |
| SCHD-06 | Catch-up planner returns a slot whose time passed <90 min ago and not sent; skips >90 min; skips already-sent | unit | `uv run pytest tests/test_scheduler.py::test_catchup_window -x` | ❌ Wave 0 |
| SCHD-07 | Firing a slot twice records/sends once (was_sent guard + UNIQUE backstop); DST fall-back double-fire collapses to one | unit | `uv run pytest tests/test_scheduler.py::test_idempotent_double_fire -x` | ❌ Wave 0 |
| SCHD-04/07 | Simulated DST spring-forward morning send fires once; fall-back morning send fires once | unit | `uv run pytest tests/test_scheduler.py::test_dst_exactly_once -x` | ❌ Wave 0 |
| D-15 | `send_now` with no `schedule_ctx` renders `{sent_at}`/`{checked_at}` non-empty, `{schedule_note}` empty | unit | `uv run pytest tests/test_send_now.py::test_manual_send_schedule_placeholders -x` | ⚠️ extend existing |
| D-15 | `validate_template` accepts the 3 new placeholders; rejects unknown still | unit | `uv run pytest tests/test_renderer.py::test_new_placeholders_validate -x` | ⚠️ extend existing |
| D-07/D-13 | A within-grace recovered send renders a populated `{schedule_note}` ("intended for…, sent…") | unit | `uv run pytest tests/test_scheduler.py::test_late_send_note -x` | ❌ Wave 0 |

> **Testing strategy (MVP-mode, no wall-clock waits):** test the `days` parser, the catch-up planner, and the sent-log as **pure units** with injected `now`/readers. Test "firing" by **invoking the `fire_slot` job callback directly** with a fake client+channel (exactly like the existing `tests/test_send_now.py` fakes) — never `scheduler.start()` + sleep. Simulate DST by passing a `now_utc` that, in the location's tz, is just before/after a known transition (e.g. `America/New_York` 2026-03-08 02:00 spring-forward, 2026-11-01 fall-back) and asserting the planner/sent-log yield exactly one fire. `time-machine` is only needed if a test asserts APScheduler's own next-fire across a transition; the pure-function tests don't need it.

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_scheduler.py -x -q` (plus the touched `test_config`/`test_renderer`/`test_send_now`)
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_scheduler.py` — covers SCHD-02..07 (days matrix, per-tz, catch-up window, idempotent double-fire, DST-once, late note)
- [ ] Extend `tests/test_config.py` — multiple schedule entries (SCHD-01), bad-`days` fail-load (SCHD-02)
- [ ] Extend `tests/test_send_now.py` — manual-send schedule placeholders (D-15)
- [ ] Extend `tests/test_renderer.py` — 3 new placeholders validate (D-15)
- [ ] No new fixtures needed for scheduling tests (config + sent-log are built inline; weather fakes reuse existing One Call fixtures). `tests/conftest.py` already supplies `tmp_db`.
- [ ] Framework install: `uv add --dev time-machine` only if a DST test exercises APScheduler's own scheduling (otherwise skip)

## Security Domain

> `security_enforcement: true`, ASVS level 1. This phase adds no auth/session/access-control surface; it adds a new SQLite write path and a long-running process. The relevant categories are input validation and injection.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user auth; single-user file-config tool |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No multi-user/authorization |
| V5 Input Validation | yes | pydantic validation of `time`/`days`/`enabled` at config load (fail-loud, D-02). `parse_days` whitelists tokens; `time` validated `HH:MM`. |
| V6 Cryptography | no | No new crypto; secrets handling unchanged (env-only, never logged — inherited T-04-01) |
| V5 (SQLi) | yes | Sent-log inserts/reads use parameterized `?` placeholders (same discipline as `persist`); never string-format the location name or time into SQL |

### Known Threat Patterns for Python scheduler + SQLite

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `location_name`/`send_time` in the sent-log | Tampering | Parameterized `?` queries only (mirror `store.persist`); `UNIQUE` constraint; never f-string SQL |
| Secret leakage in daemon logs (key/webhook over a long-running process) | Information disclosure | Outcome-only logging (T-04-01) carried into the scheduler — log location/time/delivered bool, never the `appid` or webhook URL |
| Config-driven DoS (absurd schedule, e.g. every minute) | Denial of service | Single-user tool; OpenWeather 60/min, 1M/month gives huge headroom. The 90-min/today catch-up bound caps recovery bursts. No further control needed for v1. |
| Template injection via the new placeholders | Tampering | The renderer already does whitelist `{name}` substitution with NO `str.format`/`eval` (T-03-02); the 3 new keys are plain strings added to the same whitelist — no new injection surface |
| Untrusted IANA tz string | Tampering | `Location.timezone` already validated against the IANA db via `zoneinfo` at load (Phase 2); the scheduler consumes the validated value |

## Sources

### Primary (HIGH confidence)
- https://apscheduler.readthedocs.io/en/3.x/userguide.html — BackgroundScheduler vs BlockingScheduler, misfire_grace_time/coalesce, memory jobstore (no cross-restart recovery), DST wall-clock warning
- https://apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html — CronTrigger `day_of_week` grammar (mon–sun, ranges, comma lists), per-job `timezone=`, DST behavior
- https://pypi.org/project/APScheduler/ — current version 3.11.2 (3.11.2.post1 docs)
- https://time-machine.readthedocs.io/en/latest/usage.html — `tzset()`/ZoneInfo timezone mocking, freezegun migration CLI, version 3.2.0
- Codebase (`weatherbot/cli.py`, `config/models.py`, `weather/store.py`, `weather/models.py`, `templates/renderer.py`, `tests/`) — existing seams, validator/parameterized-SQL discipline, fake-client/channel test pattern, canonical placeholder set
- `.planning/research/ARCHITECTURE.md` Pattern 1 — config-as-jobs expansion, per-location tz note
- `.planning/research/PITFALLS.md` Pitfall 1 & 4 — DST skip/repeat, restart-replay, "don't rely on scheduler replay; persist a (loc,slot,date) dedup key", 90-min grace suggestion

### Secondary (MEDIUM confidence)
- `.planning/research/STACK.md` — APScheduler 3.x lock, zoneinfo, structlog, 4.x exclusion (corroborates CLAUDE.md)
- https://betterstack.com/community/guides/testing/time-machine-vs-freezegun/ — time-machine vs freezegun tradeoffs (corroborates official docs)

### Tertiary (LOW confidence)
- (none — all load-bearing claims verified against official docs or the codebase)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — APScheduler 3.x and zoneinfo/sqlite/structlog are codebase- or CLAUDE.md-locked and verified against official docs; exact patch versions `[ASSUMED]` pending `uv add` (offline sandbox).
- Architecture: HIGH — patterns are CONTEXT-locked (D-01..D-15) and grounded in existing seams; the sent-log + pure catch-up planner directly satisfy SCHD-06/07.
- Pitfalls: HIGH — DST and restart-replay pitfalls are documented in PITFALLS.md and cross-verified against APScheduler official docs.

**Research date:** 2026-06-10
**Valid until:** 2026-07-10 (stable stack; APScheduler 3.x is mature/slow-moving)
