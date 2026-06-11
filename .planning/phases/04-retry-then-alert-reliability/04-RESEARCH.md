# Phase 4: Retry-then-Alert Reliability - Research

**Researched:** 2026-06-10
**Domain:** Reliability machinery for an always-on Python daemon — bounded retry/backoff (tenacity), structured alerting (structlog + SQLite), heartbeat/liveness, per-job exception isolation, HTTP error classification (httpx)
**Confidence:** HIGH

## Summary

Phase 4 is **pure orchestration-layer hardening** — it wraps the *already-working* Phase 3 pipeline (`fire_slot` → `claim_slot` → `send_now` → fetch + `send_briefing`) in reliability machinery without changing the pipeline's shape. Every locked decision (D-01..D-13) is an *additive* concern: new SQLite tables (`alerts`, `heartbeat`) modeled on the existing `_SCHEMA` / `INSERT OR IGNORE` idioms, a retry wrapper around the two I/O calls, a periodic heartbeat tick in the existing `run_daemon` loop, and a hardened `try/except` in `fire_slot`. No existing table, signature, or flow is rewritten.

The single highest-leverage technical finding: **the two-burst retry schedule with a 45-minute mid-pause AND the SIGTERM-interruptibility requirement (D-07) are solved together by `tenacity`'s `Retrying(sleep=...)` parameter.** `Retrying` accepts a custom `sleep` callable; passing the daemon's existing `threading.Event.wait` as that callable makes the *entire* retry schedule — including the long pause — instantly interruptible on shutdown, while a custom `wait=` callable produces the burst/pause/burst timing. This avoids both a hand-rolled loop and a non-interruptible `time.sleep` that would block clean shutdown. `[VERIFIED: tenacity.readthedocs.io API]`

**Primary recommendation:** Adopt `tenacity` 9.1.4 for the retry engine. Build one orchestration helper (`reliability/retry.py`) that runs a passed callable under a `Retrying` configured with (a) a custom two-burst `wait`, (b) `stop_after_attempt(16)` plus a wall-clock cap, (c) a `retry`/`stop` predicate that classifies transient vs permanent from `httpx.HTTPStatusError.response.status_code`, and (d) `sleep=stop_event.wait` for interruptibility. Model `alerts` + `heartbeat` on `store.py`'s existing INSERT-OR-IGNORE (dedup) and ON CONFLICT DO UPDATE (upsert) patterns. Keep the manual `--send-now` path on a tight bounded retry with no alert/heartbeat rows (D-10).

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Out-of-band alert path (RELY-03/04):**
- **D-01:** "briefing missed" alert delivered via **log + durable DB record**, NOT a network channel. Two coordinated outputs: (1) a structured CRITICAL log event with stable key `briefing_missed` and fields `location`, `slot` (`"HH:MM"`), `local_date`, `reason`, `severity` — never a secret; (2) a durable row in `data/weatherbot.db` (new `alerts` table).
- **D-02:** Rationale = a future log-monitoring bot is the intended consumer; the DB row makes a miss detectable even if the monitor wasn't tailing. A second Discord webhook rejected (not independent of a Discord-wide outage).
- **D-03:** `alerts` table keyed by `(location, slot_time, local_date)` (parallels `sent_log`), plus `reason`, `severity`, `created_at`, and a `resolved_at`/`resolved` flag (D-10/D-13). Reuse parameterized-`?` + secret-hygiene; additive `CREATE TABLE IF NOT EXISTS` only.

**Heartbeat / liveness (RELY-05):**
- **D-04:** Liveness on **two triggers**: a periodic **tick** from the daemon loop (proves alive-but-idle ≠ crashed) AND a **per-send success** stamp (proves briefings land). Together they let a monitor distinguish *crashed* (no tick) from *failing-to-send* (ticking, no recent success).
- **D-05:** Liveness recorded as **both** a DB heartbeat row (`last_tick`, `last_success`, upserted in place) AND a periodic structured `heartbeat` log event. Same dual shape, same store, same secret-hygiene as D-01.
- **D-06:** Periodic tick interval is **Claude's discretion** (~5–15 min default). May be promoted into config (D-09) but not required.

**Retry budget & policy (RELY-01/02):**
- **D-07:** Deliberate **two-burst schedule**, NOT a single exponential ramp: Burst 1 = 8 attempts across ~10 min (backoff + jitter); wait ~45 min; Burst 2 = 8 attempts across ~10 min; still failing → alert (D-01). Total ≈ 65 min, intentionally under Phase 3's 90-min catch-up grace window. A send that succeeds on burst 2 (~55–65 min late) lands within grace and renders the Phase 3 `{schedule_note}` late annotation.
- **D-08:** Two-burst applies to **both** transient OpenWeather *fetch* and Discord *send* failures. A **401/403 auth failure short-circuits the whole schedule and alerts immediately** (`reason=auth_failed` vs `transient_exhausted`). `Retry-After` on 429 honored, **capped** so an oversized value can't blow the ~65-min budget (cap = Claude's discretion).
- **D-09:** Retry timings (attempts-per-burst, ~10-min spread, ~45-min wait) **exposed in `config.toml`** (new reliability/retry section), **validated at load** (Phase-2 fail-loud tradition), surfaced by `--check`. Defaults match D-07.
- **D-10 (manual vs daemon split):** Full patient schedule + alert + heartbeat is **daemon-only**. Manual `--send-now` does a **tight/quick retry (or none)**, reports failure **immediately to the terminal**, writes **no `alerts`/`heartbeat` rows**. Tight-vs-none = Claude's discretion (lean to a short bounded retry).

**Alert behavior & anti-loop (RELY-03/04/06):**
- **D-11 (dedup / anti-loop):** **At most one `briefing_missed` alert per `(location, slot, local_date)`.** INSERT-OR-IGNORE on the key, mirroring the Phase 3 `sent_log` idempotency. This is the concrete RELY-04 "does not loop" guarantee.
- **D-12 (exception isolation → alert):** An unexpected exception caught by per-job isolation (RELY-06) **also writes a `briefing_missed` alert** with `reason=internal_error`, logs the **full traceback**, and the **scheduler keeps running**. Every miss looks uniform to the monitor.
- **D-13 (resolve on success):** The `alerts` row carries a `resolved_at`/`resolved` flag; a later success (restart-within-grace finally delivers) stamps the alert resolved so the monitor can query "currently-unresolved alerts".

### Claude's Discretion
- Heartbeat tick interval (~5–15 min default), D-06.
- `Retry-After` cap value, D-08.
- Exact transient-vs-permanent classification (timeouts/connection errors/5xx/429 retry; 400/404/401/403 no-retry), D-08.
- `tenacity` vs hand-rolled retry — implementation choice. **Implementation note (locked constraint):** the ~45-min mid-pause MUST stay SIGTERM/Ctrl-C-interruptible (Phase 3 D-09 clean shutdown) and MUST NOT block other scheduled jobs (one slot's long retry ties up at most one APScheduler worker thread — confirm threadpool/job design preserves per-job isolation). If `tenacity` adopted, add it to `pyproject.toml` (9.x).
- Exact `alerts`/`heartbeat` table + column names (D-03/D-05) and retry config section keys (D-09) — follow store + config conventions.

### Deferred Ideas (OUT OF SCOPE)
- **Active push/email/SMS alert delivery** (SMTP, ntfy/Pushover, second Discord webhook) — NOT v1; alert path is log + DB for a future monitoring bot.
- **The future log-monitoring bot itself** — Phase 4 only produces the artifacts it will consume. Its own future project.
- **Promoting heartbeat tick interval / `Retry-After` cap into config** — carried as discretion defaults now; expose later if proven wrong.
- **Routing the structured log event to journald→email / external monitoring** — Phase 5 territory.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RELY-01 | Weather fetch and channel send retry with bounded exponential backoff on transient failure | Two-burst `tenacity` `Retrying` with custom `wait` (Pattern 1); covers BOTH fetch (`httpx.HTTPStatusError`/timeout/connect) and send (`DeliveryResult.ok=False`) via `retry_if_result` + `retry_if_exception_type` (D-08 classification) |
| RELY-02 | Auth failures (401/403) never retried; honor `Retry-After` on rate limits | Status-code classifier short-circuits 401/403 (raise to abort, no retry); `Retry-After` parser (seconds OR HTTP-date) capped at a budget ceiling (Pattern 4); avoid double-retry of 429 (discord-webhook already does `rate_limit_retry=True`) |
| RELY-03 | If delivery fails after retries, alert the user a briefing was missed | `alerts` table + structured CRITICAL `briefing_missed` event (Pattern 2/3); fired on retry exhaustion from the orchestration helper |
| RELY-04 | Failure alert delivered out-of-band — independent of the failing primary channel | Log → stderr/journald + DB row — neither touches Discord (D-01/D-02). Anti-loop via INSERT-OR-IGNORE on the slot key (D-11) |
| RELY-05 | Emit a heartbeat/liveness signal so silence ≠ crash | `heartbeat` table (upsert `last_tick` / `last_success`) + periodic `heartbeat` log event; periodic tick driven from `run_daemon` (Pattern 5/6) |
| RELY-06 | Each scheduled job exception-isolated; one bad run can't kill the loop | Harden `fire_slot`'s existing `try/except` (already present, T-03-07) to ALSO write an `internal_error` alert + full traceback while keeping the scheduler thread alive (D-12) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Bounded two-burst retry | Orchestration (`reliability/` + `send_now`/`fire_slot` boundary) | — | PROJECT.md locks "retry/alert wrapper at the orchestration layer around `Channel.send`"; fetch + send are the two I/O calls it wraps |
| Transient/permanent classification | Orchestration (reads `httpx`/`DeliveryResult`) | Weather data layer (raises `HTTPStatusError`) | The classifier interprets errors surfaced by lower tiers; lower tiers stay retry-agnostic (existing contract) |
| `briefing_missed` alert (log) | Orchestration | Logging (structlog) | Decision to alert is made where exhaustion is detected; structlog only renders it |
| `briefing_missed` alert (DB row) | Storage (`store.py`) | Orchestration (caller) | Mirrors `sent_log`: store owns the SQL + dedup primitive; orchestration calls it |
| Heartbeat tick | Daemon lifecycle (`run_daemon`) | Storage + Logging | The loop owns wall-clock; it stamps the DB and emits the event |
| Heartbeat success stamp | Orchestration (on `result.ok`) | Storage | Per-send success is known at the send site |
| Exception isolation | Daemon callback (`fire_slot`) | Orchestration (alert) | Isolation must wrap the whole per-job body so the APScheduler worker thread survives |
| Retry config validation | Config layer (pydantic) | CLI (`--check`) | Phase-2 fail-loud-at-load tradition; `--check` surfaces it |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| tenacity | 9.1.4 | Retry/backoff engine (the two-burst schedule, classification predicates, interruptible sleep) | The canonical Python retry library (`jd/tenacity`); recommended in this project's own STACK.md from official sources. Its `Retrying(sleep=...)` + custom `wait` callable express the exact D-07 shape AND the interruptibility constraint without hand-rolling a loop. `[CITED: STACK.md / tenacity.readthedocs.io]` |

### Supporting (already in the project — reused, not added)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | 26.1.0 (installed) | Structured CRITICAL `briefing_missed` / `heartbeat` events | Already used via `structlog.get_logger(__name__)` throughout; emit new events with stable keys + fields |
| httpx | 0.28.1 (installed) | Source of `HTTPStatusError` (`.response.status_code`, `.response.headers["Retry-After"]`) for classification | Already the OpenWeather client; the classifier reads its exceptions |
| sqlite3 (stdlib) | built-in | `alerts` + `heartbeat` tables | Reuse `store.py`'s connection + `_SCHEMA` discipline |
| APScheduler | 3.11.x (installed) | `BackgroundScheduler` threadpool — one slot's long retry consumes exactly one worker thread | Confirm `max_workers` sizing (see Pitfall 3) |
| pydantic / pydantic-settings | 2.13.x / 2.14.x (installed) | Validate the new retry config block at load (D-09) | Extend `config/models.py` with a `Reliability`/`Retry` model |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| tenacity | Hand-rolled `for`-loop with `stop_event.wait(backoff)` | A hand-rolled loop is ~30 lines and fully interruptible, but you re-implement attempt counting, jitter, classification dispatch, and exhaustion signaling — the exact things tenacity already tests. tenacity wins *because* its `sleep=` hook removes the only reason to hand-roll (interruptibility). Pick tenacity. `[ASSUMED]` |
| `Retrying` (imperative) | `@retry` decorator | The decorator can't take a runtime `stop_event` per call. Use the imperative `Retrying(...)` object built per-fire so it can close over the daemon's `stop_event` and the per-location `Retry-After` cap. `[VERIFIED: tenacity API docs]` |

**Installation:**
```bash
uv add tenacity
```

**Version verification (2026-06-10):** `https://pypi.org/pypi/tenacity/json` → latest **9.1.4**, `requires_python: >=3.10`, home `https://github.com/jd/tenacity`. Recent releases: 8.5.0, 9.0.0, 9.1.2, 9.1.3, 9.1.4. `[VERIFIED: PyPI registry]` (compatible with the project's Python 3.12+ and STACK.md's pinned `tenacity 9.1.4`).

## Package Legitimacy Audit

> slopcheck was **not available** in this research environment (`pip install slopcheck` failed, no binary). Per protocol the single new package below is therefore tagged `[ASSUMED]` and the planner SHOULD gate its install behind a `checkpoint:human-verify` task. Mitigating context: `tenacity` is already pinned in the project's own STACK.md (verified against tenacity's official docs + GitHub), is the canonical Python retry library, and was confirmed on PyPI with a real source repo and 9 years of history.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| tenacity | PyPI | ~9 yrs (since 2016) | very high (tens of M/mo, top-tier) | github.com/jd/tenacity | unavailable | `[ASSUMED]` — planner adds `checkpoint:human-verify` before `uv add` |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none (slopcheck unavailable; tenacity is well-established but tagged `[ASSUMED]` per the graceful-degradation rule)

Python ecosystem registry verification: confirmed on **PyPI** (the correct registry for this Python phase), not a cross-ecosystem name. `[VERIFIED: PyPI registry]`

## Architecture Patterns

### System Architecture Diagram

```
  APScheduler BackgroundScheduler (threadpool, default 10 workers)
        │  fires CronTrigger at location wall-clock         periodic tick (D-04)
        ▼                                                          │
  ┌─────────────────────────── fire_slot (one worker thread) ─────┼──────────┐
  │  [D-12 hardened try/except wraps the WHOLE body]              │           │
  │      │                                                        ▼           │
  │      ▼                                          run_daemon loop stamps    │
  │  claim_slot (atomic INSERT OR IGNORE) ── lost ─► return (already sent)    │
  │      │ won                                       heartbeat.last_tick +    │
  │      ▼                                           emit `heartbeat` event   │
  │  ┌── retry_with_two_bursts(stop_event) ──────────────────┐               │
  │  │  Retrying( wait=two_burst, stop=attempts+walltime,     │               │
  │  │            retry=classify(), sleep=stop_event.wait )   │               │
  │  │      │ calls send_now → fetch (httpx) + send (Discord) │               │
  │  │      ├─ transient (5xx/429/timeout/connect) ─► backoff & retry         │
  │  │      ├─ 401/403 auth ─► raise immediately (no retry)   │               │
  │  │      └─ result.ok ─► success                           │               │
  │  └───────────────────────────────────────────────────────┘               │
  │      │ success                    │ auth_failed            │ exhausted    │
  │      ▼                            ▼                        ▼              │
  │  heartbeat.last_success      record_alert(             record_alert(      │
  │  resolve_alert(slot)         reason=auth_failed)       reason=transient_  │
  │  (D-13)                      + CRITICAL log            exhausted)+ log    │
  │      │ on any non-ok: release_claim (slot re-fireable, Phase 3 D-07)      │
  │      └─ except Exception ─► record_alert(reason=internal_error)           │
  │                              + full traceback + thread SURVIVES (D-12)    │
  └──────────────────────────────────────────────────────────────────────────┘
        │                                            │
        ▼                                            ▼
   data/weatherbot.db                          stderr / journald
   (alerts, heartbeat — additive)              (structured events, no secrets)
        ▲
        └─ a future log-monitoring bot POLLS alerts/heartbeat (out of scope, D-02)
```

### Recommended Project Structure (additive)
```
weatherbot/
├── reliability/              # NEW package (mirrors ARCHITECTURE.md's reliability/)
│   ├── __init__.py
│   ├── retry.py             # two-burst Retrying builder + classify + Retry-After parse
│   └── alerts.py            # (optional) alert-reason taxonomy / severity constants
├── scheduler/
│   └── daemon.py            # MODIFY: heartbeat tick in run_daemon; harden fire_slot (D-12)
├── cli.py                   # MODIFY: send_now grows daemon-vs-manual retry; do_check validates retry config
├── config/
│   └── models.py            # MODIFY: add Reliability/Retry pydantic model (D-09)
└── weather/
    └── store.py             # MODIFY: add alerts + heartbeat to _SCHEMA + helpers
```
> Placement of the retry call is the planner's choice: wrap *inside* `fire_slot` (around its `send_now` call) for the daemon patient path, and pass a `retry_profile`/`stop_event` into `send_now` (or keep retry entirely in `fire_slot` and give `send_now` a `retry=` knob) for the manual tight path. Either keeps the orchestration-layer locus PROJECT.md mandates.

### Pattern 1: Two-burst schedule via a custom `wait` callable
**What:** A function `(RetryCallState) -> float` returning seconds, producing burst/pause/burst timing keyed off `retry_state.attempt_number`.
**When to use:** The D-07 schedule exactly (8 / ~10 min / ~45 min / 8). NOT a single `wait_exponential`.
**Example:**
```python
# Source: tenacity.readthedocs.io (custom wait = callable(RetryCallState) -> float)
import random
from tenacity import Retrying, stop_after_attempt, RetryCallState

# Defaults from D-07/D-09 (planner moves these into the config model).
BURST_SIZE = 8           # attempts per burst
BURST_SPREAD_S = 600     # ~10 min spread per burst
MID_PAUSE_S = 2700       # ~45 min between bursts

def two_burst_wait(retry_state: RetryCallState) -> float:
    n = retry_state.attempt_number          # 1-based; wait fires AFTER attempt n
    # spread the 8 attempts of a burst across ~10 min (base step + jitter)
    step = BURST_SPREAD_S / (BURST_SIZE - 1)         # ~85.7 s
    jitter = random.uniform(0, step * 0.5)
    if n == BURST_SIZE:                     # just finished burst 1 → long pause
        return MID_PAUSE_S
    return step + jitter

# 16 attempts total = 2 bursts of 8 (D-07). reraise so the final failure surfaces.
def build_retrying(stop_event) -> Retrying:
    return Retrying(
        wait=two_burst_wait,
        stop=stop_after_attempt(2 * BURST_SIZE),     # plus a wall-clock cap, see Pattern 4
        sleep=stop_event.wait,                        # ← interruptible (Pattern 7)
        retry=...,                                    # classify, Pattern 4
        reraise=True,
    )
```

### Pattern 2: `alerts` table + dedup helper (model on `store.py`)
**What:** Additive `CREATE TABLE IF NOT EXISTS`, keyed by the same `(location, slot, local_date)` tuple as `sent_log`, written via `INSERT OR IGNORE` so a restart-replay within grace writes no duplicate (D-11).
**Example:**
```python
# Source: weatherbot/weather/store.py existing sent_log / claim_slot idioms
_ALERTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY,
    location_name TEXT    NOT NULL,
    slot_time     TEXT    NOT NULL,          -- "HH:MM" (parallels sent_log.send_time)
    local_date    TEXT    NOT NULL,          -- YYYY-MM-DD in the location's tz
    reason        TEXT    NOT NULL,          -- transient_exhausted | auth_failed | internal_error
    severity      TEXT    NOT NULL,          -- e.g. 'critical'
    created_at_utc INTEGER NOT NULL,
    resolved_at_utc INTEGER,                 -- NULL = unresolved (D-13)
    UNIQUE(location_name, slot_time, local_date)
);
"""

def record_alert(db_path, location_name, slot_time, local_date, reason, severity="critical"):
    """At most one alert per (location, slot, local_date) — D-11 anti-loop.
    INSERT OR IGNORE makes a restart-within-grace re-attempt write no duplicate,
    mirroring claim_slot. Parameterized ? only (T-04-01 SQLi/secret hygiene)."""
    created = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)          # _SCHEMA gains the new tables
        conn.execute(
            "INSERT OR IGNORE INTO alerts "
            "(location_name, slot_time, local_date, reason, severity, created_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (location_name, slot_time, local_date, reason, severity, created),
        )
        conn.commit()

def resolve_alert(db_path, location_name, slot_time, local_date):
    """Stamp resolved when the slot later succeeds (D-13). No-op if no row exists."""
    resolved = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "UPDATE alerts SET resolved_at_utc=? "
            "WHERE location_name=? AND slot_time=? AND local_date=? AND resolved_at_utc IS NULL",
            (resolved, location_name, slot_time, local_date),
        )
        conn.commit()
```

### Pattern 3: Structured CRITICAL alert event (structlog, secret-hygiene)
**What:** A stable event key + flat fields the monitoring bot can match on. Logged ALONGSIDE the DB row (D-01), never carrying a secret.
**Example:**
```python
# Source: existing weatherbot codebase (structlog.get_logger pattern)
import structlog
_log = structlog.get_logger(__name__)

_log.critical(
    "briefing_missed",            # ← stable event key the monitor greps
    location=location.name,
    slot=slot.time,               # "HH:MM"
    local_date=local_date,
    reason="transient_exhausted", # | auth_failed | internal_error
    severity="critical",
)
# NEVER pass key=, webhook_url=, or a request URL — outcome fields only (T-04-01).
```
> Note: the codebase calls `logging.basicConfig(level=logging.INFO)` in `cli.py:main` and uses structlog's default (stdlib-wrapped) logger. `_log.critical(...)` will emit at CRITICAL through that handler. If the planner wants machine-parseable JSON for the monitoring bot, a one-time `structlog.configure(processors=[...JSONRenderer()])` in `main` is a clean, optional enhancement — but the *stable event key + fields* (above) are what the monitor needs, and they survive either renderer.

### Pattern 4: Transient/permanent classification + capped `Retry-After`
**What:** A predicate that retries timeouts/connect-errors/5xx/429 (honoring a capped `Retry-After`) and SHORT-CIRCUITS 400/404/401/403.
**Example:**
```python
# Source: httpx error model + tenacity retry predicates
import httpx
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

RETRY_AFTER_CAP_S = 120          # D-08 cap (Claude's discretion) — keep total under 65 min

PERMANENT = {400, 401, 403, 404} # never retry (auth + bad request) — RELY-02
TRANSIENT = {429, 500, 502, 503, 504}

def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in TRANSIENT
    return False

def parse_retry_after(resp: httpx.Response) -> float | None:
    """Retry-After is EITHER an int (seconds) OR an HTTP-date. Cap either form."""
    ra = resp.headers.get("Retry-After")
    if not ra:
        return None
    try:
        secs = float(ra)                      # seconds form
    except ValueError:
        dt = parsedate_to_datetime(ra)        # HTTP-date form
        secs = (dt - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, min(secs, RETRY_AFTER_CAP_S))
```
**Auth short-circuit:** when `is_transient` is False, do NOT retry — let the exception propagate out of `Retrying` (with `reraise=True`) so the caller writes `reason=auth_failed` (401/403) vs lets a genuine bug surface. Distinguish 401/403 from 400/404 in the caller when choosing the alert `reason`.

**Send-side (no exception) path:** the Discord channel returns `DeliveryResult(ok=False, detail=...)` rather than raising (existing contract). Wrap the send so a non-ok result is retryable — either translate `ok=False` into a raised sentinel inside the wrapped callable, or use `retry=retry_if_result(lambda r: not r.ok)`. The `detail` already carries the HTTP status as text (e.g. `"503 ..."`) for classification, but it never carries the URL.

### Pattern 5: Heartbeat table (upsert in place, D-05)
```python
# Source: SQLite UPSERT (ON CONFLICT DO UPDATE) — single authoritative row
_HEARTBEAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS heartbeat (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- single-row table
    last_tick_utc   INTEGER,
    last_success_utc INTEGER
);
INSERT OR IGNORE INTO heartbeat (id, last_tick_utc, last_success_utc) VALUES (1, NULL, NULL);
"""

def stamp_tick(db_path):
    now = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute("UPDATE heartbeat SET last_tick_utc=? WHERE id=1", (now,))
        conn.commit()

def stamp_success(db_path):
    now = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        conn.execute("UPDATE heartbeat SET last_success_utc=? WHERE id=1", (now,))
        conn.commit()
```
> A single fixed-`id` row makes "upsert in place" trivial — the monitor always reads row 1. (Alternatively `ON CONFLICT(id) DO UPDATE`; the seeded single row + UPDATE is simpler and equally correct.)

### Pattern 6: Periodic heartbeat tick in `run_daemon` (interruptible, no extra thread)
**What:** Register the tick as one more APScheduler `IntervalTrigger` job (cleanest — reuses the existing scheduler/threadpool), OR drive it from the existing `stop.wait(interval)` block. The IntervalTrigger approach keeps `run_daemon`'s shutdown logic untouched.
**Example:**
```python
# Source: APScheduler 3.x IntervalTrigger + existing _register_jobs pattern
from apscheduler.triggers.interval import IntervalTrigger

HEARTBEAT_INTERVAL_S = 600   # ~10 min (D-06, Claude's discretion)

scheduler.add_job(
    _heartbeat_tick,                         # stamp_tick(db_path) + _log.info("heartbeat", ...)
    trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S),
    kwargs={"db_path": db_path},
    id="__heartbeat__",
    misfire_grace_time=None,
    coalesce=True,
)
```
> The tick job runs on the same threadpool; with default 10 workers it never starves slot jobs. The `heartbeat` log event uses the same stable-key + fields shape as Pattern 3 (event key `"heartbeat"`, fields like `last_tick`, optionally `last_success`).

### Pattern 7: Interruptible long pause via `Retrying(sleep=stop_event.wait)` (THE key pattern)
**What:** Replace tenacity's default `time.sleep` with the daemon's `threading.Event.wait`, so the 45-min mid-pause (and every backoff) aborts the instant `stop_event` is set on SIGTERM/Ctrl-C.
**Why it matters:** `time.sleep(2700)` is NOT interruptible by an event — a SIGTERM during the pause would hang shutdown for up to 45 min, violating Phase 3 D-09. `Event.wait(timeout)` returns immediately when set. `tenacity`'s `Retrying(sleep=...)` parameter (signature `Callable[[float], None]`) is exactly the seam for this. `[VERIFIED: tenacity API — Retrying accepts sleep callable]`
```python
# Source: tenacity.readthedocs.io/en/latest/api.html (Retrying sleep parameter)
# run_daemon already owns: stop = threading.Event()  (daemon.py:319)
# Thread the SAME stop event into fire_slot's retry builder so a long pause is
# abandoned on shutdown. Event.wait(timeout) -> bool ignores its return (sleep
# signature is -> None), which is fine; the next attempt sees stop and the
# scheduler.shutdown(wait=False) tears the worker down.
retrying = Retrying(wait=two_burst_wait, stop=..., retry=..., sleep=stop.wait, reraise=True)
```
> **Threadpool confirmation (D-07 constraint answered):** APScheduler 3.x `BackgroundScheduler` uses a `ThreadPoolExecutor` (default `max_workers=10`). One slot's full ~65-min retry occupies **exactly one** worker thread for its duration — it does NOT block other jobs as long as concurrent long-running slots `< max_workers`. With a personal bot's handful of slots this is never a concern, but the planner should (a) keep `max_workers` at or above the count of slots that could plausibly retry simultaneously, and (b) NOT make the retry block the scheduler's main thread. Per-job isolation (D-12) plus the one-thread-per-slot model together satisfy "MUST NOT block the other scheduled jobs." `[VERIFIED: APScheduler 3.x BackgroundScheduler uses ThreadPoolExecutor default 10 — CITED: STACK.md + apscheduler docs]`

### Pattern 8: Daemon-vs-manual retry split (D-10)
**What:** Two retry profiles. Daemon = patient two-burst + alert + heartbeat. Manual `--send-now` = tight bounded retry (e.g. `stop_after_attempt(3)` + short `wait_exponential`), terminal-only, NO `alerts`/`heartbeat` rows.
**How:** Pass a `retry_profile` (or a pre-built `Retrying`) and a flag like `record_liveness: bool` into the send path. `fire_slot` (daemon) passes the patient profile + `stop_event` + `record_liveness=True`; `main`'s `--send-now` branch passes the tight profile + `record_liveness=False`. The manual path's failure already prints via `cli.main`'s existing `_log.error("briefing delivery failed", detail=...)`.

### Anti-Patterns to Avoid
- **Double-retrying 429.** `discord-webhook` is constructed with `rate_limit_retry=True` (discord.py:83), so it ALREADY honors Discord 429s internally before returning. Do NOT *also* retry a Discord 429 at the orchestration layer — that compounds delays and can trip the ~30 msg/min webhook cap. **Resolution:** treat a Discord `DeliveryResult(ok=False)` as a single transient unit for the two-burst schedule, but rely on the channel for the *within-attempt* 429 wait; the orchestration layer's `Retry-After` cap logic (Pattern 4) applies primarily to the **OpenWeather fetch** 429, not the Discord send. The planner should document this split explicitly.
- **Retrying 401/403.** Locked never-retry (RELY-02). Short-circuit to `auth_failed` immediately.
- **`time.sleep` for the mid-pause.** Blocks clean shutdown — use Pattern 7.
- **Alert via Discord.** D-02 rejects it; alert is log + DB only.
- **Looping alerts.** INSERT-OR-IGNORE on the slot key (D-11) makes the alert idempotent.
- **Burning quota.** The 65-min budget is bounded; never an unbounded loop (Pitfall 5/6).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry attempt counting, jitter, backoff, exhaustion signaling | A bespoke `for`-loop state machine | `tenacity.Retrying` | It's tested; the only reason to hand-roll (interruptibility) is solved by `sleep=stop_event.wait` |
| Interruptible sleep | `time.sleep` + signal flags + polling | `threading.Event.wait(timeout)` as tenacity's `sleep` | Already the daemon's shutdown primitive (daemon.py:319) |
| `Retry-After` HTTP-date parsing | Custom date parser | `email.utils.parsedate_to_datetime` (stdlib) | RFC-compliant; `Retry-After` may be seconds OR an HTTP-date |
| Alert dedup | A "have I alerted?" SELECT-then-INSERT | `INSERT OR IGNORE` on the UNIQUE key | Atomic, race-free, mirrors `claim_slot` |
| Heartbeat "latest" row | Delete+insert | seeded single row + `UPDATE` (or UPSERT) | Avoids unbounded row growth; monitor reads one row |
| IANA tz / local-date | Manual offset math | `zoneinfo` + the existing `local_date` computation in `fire_slot`/`store` | Already correct from Phase 3 |

**Key insight:** Phase 4 introduces almost no genuinely new algorithm — it *composes* existing primitives (`claim_slot`/`release_claim` idempotency, `threading.Event` shutdown, `httpx` errors, structlog events) under a tenacity retry. The risk is in *wiring*, not invention.

## Runtime State Inventory

> Phase 4 is additive code + additive schema (greenfield tables on an existing DB). No rename/refactor of stored keys. The one stateful concern is the new tables.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New `alerts` + `heartbeat` tables in existing `data/weatherbot.db`. Existing `sent_log` / `weather_onecall` rows UNCHANGED. The `(location, slot, local_date)` key is REUSED verbatim from `sent_log` — no key rename. | Additive `CREATE TABLE IF NOT EXISTS` in `_SCHEMA`. No data migration. |
| Live service config | None — no external service stores Phase-4 state (alert path is local log + local DB, by design D-02). | None. |
| OS-registered state | None this phase (systemd / supervision is Phase 5). The foreground daemon's SIGTERM handler is unchanged except the retry now honors `stop`. | None. |
| Secrets/env vars | None new. Alert/heartbeat events and rows carry only `location`/`slot`/`reason` etc. — never the key or webhook URL (T-04-01 carried forward). | None — verify no secret leaks into a new log field (test asserts this). |
| Build artifacts | Adding `tenacity` to `pyproject.toml` requires `uv add tenacity` / `uv sync` so the lockfile + venv update. | Run `uv add tenacity`; commit `uv.lock`. |

## Common Pitfalls

### Pitfall 1: Non-interruptible mid-pause blocks clean shutdown
**What goes wrong:** A SIGTERM during the 45-min pause hangs the process for up to 45 min, breaking Phase 3 D-09 clean shutdown.
**Why it happens:** tenacity defaults to `time.sleep`, which ignores the daemon's `threading.Event`.
**How to avoid:** Pass `sleep=stop_event.wait` to `Retrying` (Pattern 7); thread the SAME `stop` event `run_daemon` already creates into `fire_slot`'s retry builder.
**Warning signs:** A shutdown test (Ctrl-C / SIGTERM during a simulated retry) that takes more than ~1 s to exit.

### Pitfall 2: Double-retrying Discord 429 at both layers
**What goes wrong:** `discord-webhook`'s `rate_limit_retry=True` waits out a 429 internally, THEN the orchestration retry waits again — compounding delays and risking the ~30 msg/min webhook cap.
**Why it happens:** Two independent retry mechanisms unaware of each other.
**How to avoid:** Let the channel own within-attempt 429 handling; the orchestration two-burst treats the *returned* `ok=False` as one transient unit. Apply the orchestration `Retry-After` cap to the OpenWeather fetch 429, not the Discord send (Anti-Patterns).
**Warning signs:** Send retries taking far longer than the configured spread; webhook 429s in logs after a retry.

### Pitfall 3: A long retry starves the threadpool
**What goes wrong:** If many slots retry concurrently and `max_workers` is small, a ~65-min retry could occupy all workers and delay other jobs (incl. the heartbeat tick).
**Why it happens:** One slot's full retry holds one worker for its whole duration.
**How to avoid:** Default `max_workers=10` comfortably exceeds a personal bot's slot count. Keep it ≥ plausible simultaneous-retry count; the heartbeat tick is its own job and will still fire on a free worker. Document the relationship.
**Warning signs:** Heartbeat ticks or other slots delayed when one slot is mid-retry.

### Pitfall 4: Alert/heartbeat row written on the manual path
**What goes wrong:** `--send-now` failures write `alerts`/`heartbeat` rows, polluting the monitor's view with non-daemon noise (violates D-10).
**Why it happens:** Sharing one retry/alert helper without a daemon-vs-manual flag.
**How to avoid:** Gate liveness/alert writes behind a `record_liveness`/daemon flag (Pattern 8); manual path reports to the terminal only.
**Warning signs:** An `alerts` row appears after a manual `--send-now` test.

### Pitfall 5: Retry budget exceeds the 90-min grace window
**What goes wrong:** If bursts/pause are mis-tuned (or `Retry-After` uncapped), total > 90 min, so a burst-2 success lands OUTSIDE Phase 3's catch-up grace and the late-send annotation/recovery semantics break.
**Why it happens:** Sum of (2×spread + pause + per-attempt timeouts + uncapped Retry-After) drifts past 90 min.
**How to avoid:** Keep total ≈ 65 min with headroom; CAP `Retry-After` (Pattern 4); add a wall-clock `stop` (e.g. `stop_after_delay`) as a belt-and-suspenders ceiling alongside `stop_after_attempt`.
**Warning signs:** A recovered send rendering no `{schedule_note}` or being skipped by catch-up.

### Pitfall 6: Secret leaks into a new log field
**What goes wrong:** A new alert/heartbeat event accidentally logs `detail` containing a URL, or the OpenWeather request URL.
**Why it happens:** Copy-pasting a logging call without auditing fields.
**How to avoid:** Carry only `location`/`slot`/`local_date`/`reason`/`severity` + timestamps. The existing `DeliveryResult.detail` is already credential-free (status + body snippet only) — safe to log, but audit it.
**Warning signs:** A test grepping log output for the webhook host or `appid` finds a match.

## Code Examples

### Reading attempt number / outcome from RetryCallState (for logging which burst exhausted)
```python
# Source: tenacity.readthedocs.io — RetryCallState.attempt_number / .outcome
def before_sleep_log(retry_state):
    _log.info(
        "retry_attempt",
        attempt=retry_state.attempt_number,
        burst=1 if retry_state.attempt_number <= BURST_SIZE else 2,
    )
# pass before_sleep=before_sleep_log to Retrying(...)
```

### Imperative retry of a callable that returns DeliveryResult
```python
# Source: tenacity Retrying imperative form + retry_if_result
from tenacity import Retrying, retry_if_result, retry_if_exception, stop_after_attempt

def attempt_send():               # closes over location/config/...
    return send_now(...)          # returns DeliveryResult

retrying = Retrying(
    wait=two_burst_wait,
    stop=stop_after_attempt(2 * BURST_SIZE),
    retry=(retry_if_result(lambda r: not r.ok) | retry_if_exception(is_transient)),
    sleep=stop.wait,
    reraise=True,
)
try:
    result = retrying(attempt_send)          # raises on a non-transient / exhausted
except Exception:
    result = ...                             # exhausted or auth — caller alerts
```
> `retry_if_result | retry_if_exception` combines value-based and exception-based retry — the send path returns `ok=False` (no raise) while the fetch path raises `HTTPStatusError`/timeouts. `[VERIFIED: tenacity API — retry predicates combine with |]`

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `for i in range(n): try/except sleep` | `tenacity.Retrying` with custom wait/stop/retry/sleep | tenacity mature since ~2016 | Declarative, tested; `sleep=` hook removes the interruptibility objection |
| `time.sleep` in a daemon | `threading.Event.wait(timeout)` | long-standing best practice | Interruptible shutdown |
| tenacity 8.x | tenacity 9.x (9.1.4) | 9.0.0 release | Drops Python <3.10; project is 3.12+ so fine. `requires_python >=3.10` `[VERIFIED: PyPI]` |

**Deprecated/outdated:** none relevant — the project's STACK.md pins are current.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `tenacity` is legitimate/safe to add (slopcheck unavailable, so tagged `[ASSUMED]` per protocol) | Package Legitimacy Audit | LOW — tenacity is the canonical retry lib in the project's own STACK.md, ~9 yrs on PyPI, real source repo; planner should still add a `checkpoint:human-verify` before `uv add` |
| A2 | A hand-rolled loop is the inferior choice vs tenacity | Alternatives Considered | LOW — both work; if the planner prefers zero new deps, the hand-rolled loop with `stop_event.wait` is a viable fallback and would make A1 moot |
| A3 | `Retry-After` cap of ~120 s is sensible (Claude's discretion, D-08) | Pattern 4 | LOW — just keep total < 90 min; planner picks the exact value |
| A4 | Heartbeat tick ~10 min is sensible (Claude's discretion, D-06) | Pattern 6 | LOW — any 5–15 min value satisfies D-06 |
| A5 | Discord `DeliveryResult.detail` is credential-free and safe to log | Pitfall 6 | LOW — verified in discord.py:`_post` (status + body snippet only, never URL); a test should still assert it |

## Open Questions

1. **Where exactly to place the retry call — inside `fire_slot` vs inside `send_now`?**
   - What we know: PROJECT.md locks the orchestration layer; both `fire_slot` and `send_now` are orchestration. `fire_slot` owns claim/release + the `stop_event` context (daemon-only); `send_now` is shared by manual + daemon.
   - What's unclear: cleanest seam for the daemon-vs-manual split (D-10).
   - Recommendation: wrap the retry in `fire_slot` (it already has `stop_event` access and is daemon-only), and give the manual `--send-now` path its own tight `Retrying` in `cli.main`'s send branch. Keep `send_now` retry-agnostic (a single attempt) so it stays the shared composition root — the planner confirms.

2. **JSON log rendering for the monitoring bot — now or defer?**
   - What we know: codebase uses structlog's default (stdlib-wrapped) renderer; D-01/D-05 only require stable event keys + fields.
   - What's unclear: whether the future monitor will tail text logs or parse JSON.
   - Recommendation: ship the stable-key events now (renderer-agnostic). Treat a `structlog.configure(... JSONRenderer())` as an optional small task or a Phase-5 concern — do not block Phase 4 on it.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| tenacity (PyPI) | Two-burst retry engine | ✗ (not yet a project dep) | 9.1.4 (latest, verified) | Hand-rolled `for`-loop with `stop_event.wait` (A2) — zero new deps |
| structlog | Alert/heartbeat events | ✓ | 26.1.0 (in deps) | — |
| httpx | Error classification | ✓ | 0.28.1 (in deps) | — |
| APScheduler | Heartbeat IntervalTrigger + threadpool | ✓ | 3.11.x (in deps) | Drive tick from `stop.wait(interval)` loop |
| sqlite3 / zoneinfo / email.utils | tables / tz / Retry-After date | ✓ (stdlib) | built-in | — |
| uv | Install tenacity + lock | ✓ (project standard) | — | pip (not preferred) |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** `tenacity` — install via `uv add tenacity`; fallback is a hand-rolled interruptible loop (no functional loss, more code).

## Validation Architecture

> nyquist_validation not explicitly disabled in config; treated as enabled. The phase's reliability behaviors are deterministically testable with the existing fixture + tmp_db infrastructure.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (dev dep) + time-machine 2.16 (clock control) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=["tests"], pythonpath=["."]) |
| Quick run command | `uv run pytest tests/test_reliability.py -x` |
| Full suite command | `uv run pytest -ra` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RELY-01 | Transient (5xx/timeout) retries then succeeds within bursts | unit | `pytest tests/test_reliability.py::test_transient_retries_then_succeeds -x` | ❌ Wave 0 |
| RELY-01 | Two-burst schedule produces expected wait sequence (mock sleep, assert durations) | unit | `pytest tests/test_reliability.py::test_two_burst_wait_shape -x` | ❌ Wave 0 |
| RELY-02 | 401/403 short-circuits, NO retry, `reason=auth_failed` | unit | `pytest tests/test_reliability.py::test_auth_no_retry -x` | ❌ Wave 0 |
| RELY-02 | `Retry-After` parsed (seconds + HTTP-date) and capped | unit | `pytest tests/test_reliability.py::test_retry_after_capped -x` | ❌ Wave 0 |
| RELY-03 | Exhausted retry writes one `alerts` row + CRITICAL `briefing_missed` event | unit | `pytest tests/test_reliability.py::test_exhaustion_alerts -x` | ❌ Wave 0 |
| RELY-04 | Alert path touches no Discord; dedup writes at most one row per slot/day | unit | `pytest tests/test_reliability.py::test_alert_dedup_no_loop -x` | ❌ Wave 0 |
| RELY-05 | Heartbeat tick stamps `last_tick`; success stamps `last_success`; periodic event emitted | unit | `pytest tests/test_reliability.py::test_heartbeat_upsert -x` | ❌ Wave 0 |
| RELY-06 | Injected exception in one slot → traceback logged + `internal_error` alert + scheduler survives + other slot fires | unit | `pytest tests/test_reliability.py::test_exception_isolation -x` | ❌ Wave 0 |
| D-07 | Mid-pause is interruptible (set stop_event → retry abandons fast) | unit | `pytest tests/test_reliability.py::test_pause_interruptible -x` | ❌ Wave 0 |
| D-10 | Manual `--send-now` failure writes NO alerts/heartbeat rows, reports to terminal | unit | `pytest tests/test_cli.py::test_send_now_no_liveness_rows -x` | ✅ (extend test_cli.py) |
| D-09 | Malformed retry config fails loud at load + surfaced by `--check` | unit | `pytest tests/test_config.py::test_retry_config_validation -x` | ✅ (extend test_config.py) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_reliability.py -x`
- **Per wave merge:** `uv run pytest -ra`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_reliability.py` — covers RELY-01..06 + D-07/D-10 (new file; the bulk of the phase's tests)
- [ ] Extend `tests/test_cli.py` — D-10 manual-path no-liveness-rows
- [ ] Extend `tests/test_config.py` — D-09 retry config validation
- [ ] Extend `tests/test_store.py` — `alerts`/`heartbeat` table helpers (record/resolve/dedup, stamp_tick/stamp_success)
- [ ] Dependency install: `uv add tenacity` (gate behind `checkpoint:human-verify` per Package Legitimacy Audit)
- [ ] Test technique note: use tenacity's `sleep=` hook with a mock (record durations instead of really sleeping) so the two-burst-shape test runs in milliseconds; use `time-machine` for any wall-clock `stop_after_delay` assertions.

> Existing infra (conftest `tmp_db`, `load_fixture`; time-machine) covers most needs — primary gap is the new `test_reliability.py`.

## Security Domain

> `security_enforcement` not disabled in config (absent = enabled). This phase adds logging + local DB writes; the dominant concern is secret hygiene + SQLi discipline (both already established).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surface (OpenWeather key/Discord webhook unchanged; this phase classifies their 401/403 but never handles credentials) |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | Single-user local tool |
| V5 Input Validation | yes | New retry config block validated via pydantic at load (D-09), Phase-2 fail-loud tradition. `Retry-After` header is untrusted input → parse defensively + CAP (Pattern 4) |
| V6 Cryptography | no | No new crypto; secrets remain on `Settings` only |
| V7 Error/Logging | yes | New CRITICAL alert + heartbeat events MUST NOT log the API key / webhook URL / request URL (T-04-01 carried forward). All inserts parameterized `?` (T-03-01 SQLi). |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leak via a new log field (alert `detail`, request URL) | Information Disclosure | Outcome-only fields; audited `DeliveryResult.detail` (credential-free); test grep asserts no host/`appid` in logs (Pitfall 6) |
| Untrusted `Retry-After` header forcing an unbounded wait (DoS-of-self) | Denial of Service | Cap `Retry-After` (Pattern 4) + wall-clock `stop` ceiling (Pitfall 5) |
| Malformed retry config silently mis-tuning the budget | Tampering / DoS | pydantic validation at load + `--check` surface (D-09) |
| SQL injection into new `alerts`/`heartbeat` tables | Tampering | Parameterized `?` only (mirrors store.py); never f-string into SQL |
| Retry storm burning OpenWeather quota | Denial of Service | Bounded 65-min budget, never unbounded; 401/403 short-circuit (Pitfall 5/6, PITFALLS.md P5/P6) |

## Sources

### Primary (HIGH confidence)
- tenacity API docs `https://tenacity.readthedocs.io/en/latest/api.html` — `Retrying(sleep=..., stop=..., wait=..., retry=..., before_sleep=..., reraise=...)`, custom wait callable signature, `wait_chain`/`wait_combine`, `retry_if_result`/`retry_if_exception_type`, `RetryCallState.attempt_number`/`.outcome`
- tenacity guide `https://tenacity.readthedocs.io/en/latest/` — custom wait `(RetryCallState)->float`, `Retrying` imperative use, `stop_after_attempt`, `wait_exponential`/`wait_random`
- PyPI `https://pypi.org/pypi/tenacity/json` (fetched 2026-06-10) — tenacity 9.1.4 latest, `requires_python >=3.10`, repo github.com/jd/tenacity
- Project codebase (read directly): `weatherbot/scheduler/daemon.py`, `cli.py`, `weather/client.py`, `weather/store.py`, `channels/discord.py`, `channels/base.py`, `config/models.py`, `config/settings.py`, `tests/*`
- Project planning docs (read directly): `04-CONTEXT.md` (D-01..D-13), `03-CONTEXT.md` (90-min grace, dedup key, mark-on-success), REQUIREMENTS.md (RELY-01..06), STACK.md, ARCHITECTURE.md, PITFALLS.md

### Secondary (MEDIUM confidence)
- APScheduler 3.x `BackgroundScheduler` threadpool (default `max_workers=10`) — corroborated by STACK.md + apscheduler 3.x user guide (one thread per concurrent job)

### Tertiary (LOW confidence)
- none — all load-bearing claims verified against official docs, PyPI, or the codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — tenacity verified on PyPI + official API docs + project STACK.md pin
- Architecture/patterns: HIGH — all patterns derived from the actual codebase idioms (`claim_slot`, `_SCHEMA`, structlog, `threading.Event`) + verified tenacity API
- Pitfalls: HIGH — drawn from PITFALLS.md P3/P5/P6 + verified library behavior (interruptible sleep, double-429)
- Package legitimacy: MEDIUM — slopcheck unavailable; tenacity `[ASSUMED]` per protocol but strongly corroborated

**Research date:** 2026-06-10
**Valid until:** 2026-07-10 (30 days — stable stack; tenacity 9.x and the project's pinned deps are not fast-moving)
