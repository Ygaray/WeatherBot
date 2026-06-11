# Phase 4: Retry-then-Alert Reliability - Pattern Map

**Mapped:** 2026-06-10
**Files analyzed:** 11 (2 new, 9 modified)
**Analogs found:** 11 / 11 (every new/modified file has a strong in-repo analog)

## File Classification

| New/Modified File | New? | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|------|-----------|----------------|---------------|
| `weatherbot/reliability/retry.py` | NEW | utility (retry engine) | transform / request-response wrapper | `weatherbot/weather/client.py` (httpx error surface) + `weatherbot/scheduler/context.py` (small focused module) | role-match |
| `weatherbot/reliability/__init__.py` | NEW | config (package barrel) | — | `weatherbot/config/__init__.py` (barrel re-export) | exact |
| `weatherbot/weather/store.py` | MOD | model / store | CRUD (INSERT-OR-IGNORE dedup + UPSERT) | self — existing `sent_log` / `claim_slot` / `release_claim` | exact (same file, same idioms) |
| `weatherbot/scheduler/daemon.py` | MOD | service (daemon lifecycle + per-job callback) | event-driven (scheduler-fired) | self — existing `fire_slot` try/except + `run_daemon` `threading.Event` loop | exact (same file) |
| `weatherbot/cli.py` | MOD | controller (composition root + CLI) | request-response / orchestration | self — existing `send_now` + `do_check` | exact (same file) |
| `weatherbot/weather/client.py` | MOD (maybe) | service (HTTP client) | request-response (httpx) | self — existing `fetch_onecall` raise-for-status | exact (same file) |
| `weatherbot/config/models.py` | MOD | model (pydantic config) | transform / validation | self — existing `Schedule` field_validators | exact (same file) |
| `config.toml` / `config.example.toml` | MOD | config | — | self — existing `[[locations]]` / `[[locations.schedule]]` blocks | exact |
| `pyproject.toml` | MOD | config (deps) | — | self — existing `[project] dependencies` array | exact |
| `tests/test_reliability.py` | NEW | test | unit | `tests/test_store.py` + `tests/test_scheduler.py` (tmp_db / load_fixture fixtures) | role-match |
| `tests/test_store.py` / `test_cli.py` / `test_config.py` | MOD | test | unit | self — existing test bodies | exact |

> Channels (`channels/discord.py`, `channels/base.py`) are a **decision point** the retry layer *reads*, not files that need new patterns copied in — see Shared Patterns -> "Send-failure retry decision (DeliveryResult)" and the 429 anti-pattern. They likely need **no edit** (the `DeliveryResult(ok, detail)` seam already exists); included here only so the planner does not accidentally add a second retry inside the channel.

## Pattern Assignments

### `weatherbot/weather/store.py` (model/store, CRUD) — add `alerts` + `heartbeat`

**Analog:** itself — the existing `sent_log` table + `claim_slot`/`record_sent`/`release_claim` helpers. Every new helper is a near-copy.

**Schema pattern** (store.py lines 108-116) — append the two new tables to the SAME `_SCHEMA` string so `executescript(_SCHEMA)` in every helper creates them idempotently. Copy the `sent_log` shape verbatim for `alerts` (same `(location_name, send_time/slot_time, local_date)` UNIQUE key):
```python
CREATE TABLE IF NOT EXISTS sent_log (
    id            INTEGER PRIMARY KEY,
    location_name TEXT    NOT NULL,
    send_time     TEXT    NOT NULL,   -- "HH:MM" slot identity (D-06)
    local_date    TEXT    NOT NULL,   -- YYYY-MM-DD in the location's tz
    sent_at_utc   INTEGER NOT NULL,
    UNIQUE(location_name, send_time, local_date)
);
```
New `alerts` adds `reason TEXT`, `severity TEXT`, `created_at_utc INTEGER`, `resolved_at_utc INTEGER` (NULL = unresolved, D-13), same `UNIQUE(location_name, slot_time, local_date)`. New `heartbeat` is a single-row table (`id INTEGER PRIMARY KEY CHECK (id = 1)`, `last_tick_utc`, `last_success_utc`) seeded with `INSERT OR IGNORE INTO heartbeat (id,...) VALUES (1, NULL, NULL)`.

**Dedup-write helper pattern (the D-11 anti-loop primitive)** — copy `claim_slot` (store.py lines 238-275) structurally. The load-bearing lines are the `INSERT OR IGNORE` + connection discipline:
```python
def claim_slot(db_path, location_name, send_time, local_date) -> bool:
    sent_at_utc = int(datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)          # idempotent schema-on-connect
        cur = conn.execute(
            "INSERT OR IGNORE INTO sent_log "
            "(location_name, send_time, local_date, sent_at_utc) "
            "VALUES (?, ?, ?, ?)",
            (location_name, send_time, local_date, sent_at_utc),
        )
        conn.commit()
        return cur.rowcount == 1
```
`record_alert` is this exact shape against `alerts` (returns nothing or `rowcount==1` if the planner wants "was-this-the-first-alert"). `INSERT OR IGNORE` on the UNIQUE key gives "at most one alert per slot/day" for free — never a SELECT-then-INSERT.

**Resolve/stamp (UPDATE) pattern** — copy `release_claim` (store.py lines 278-301), which is a parameterized `DELETE ... WHERE` on all three key columns. `resolve_alert` is the same shape with `UPDATE alerts SET resolved_at_utc=? WHERE location_name=? AND slot_time=? AND local_date=? AND resolved_at_utc IS NULL`. `stamp_tick`/`stamp_success` are `UPDATE heartbeat SET last_tick_utc=? WHERE id=1`.

**Secret hygiene + SQLi discipline (carry verbatim):** every value bound as `?` (never f-string into SQL); rows carry only `location`/`slot`/`local_date`/`reason`/`severity`/timestamps — never a key or URL (docstrings at lines 199-202, 261-263 state the T-03-01 / T-04-01 rule).

---

### `weatherbot/reliability/retry.py` (NEW, utility) — two-burst tenacity engine

**Analog:** `weatherbot/weather/client.py` for the module shape (small, single-purpose, httpx-error-aware, secret-conscious docstring) and the httpx error classification source.

**Module-docstring + import convention** (client.py lines 1-30): a focused docstring stating the secret-hygiene rule, `from __future__ import annotations`, `TYPE_CHECKING` guard for model imports, module-level constants in CAPS (client.py `ONECALL`, `_TIMEOUT`). Mirror this for `BURST_SIZE`, `BURST_SPREAD_S`, `MID_PAUSE_S`, `RETRY_AFTER_CAP_S`, `PERMANENT`, `TRANSIENT`.

**httpx error classification source** (client.py lines 42-64): `fetch_onecall` calls `response.raise_for_status()`, so the orchestration layer receives `httpx.HTTPStatusError` carrying `.response.status_code` and `.response.headers`. The classifier in retry.py reads exactly these:
```python
# client.py raises this on non-2xx; retry.py classifies it:
response.raise_for_status()   # -> httpx.HTTPStatusError(.response.status_code)
```
- `is_transient(exc)`: True for `httpx.TimeoutException`/`ConnectError`/`ReadError`, and `HTTPStatusError` with status in `{429,500,502,503,504}`. False (no retry) for `{400,401,403,404}` -> auth/permanent short-circuit (RELY-02).
- `parse_retry_after(resp)`: read `resp.headers.get("Retry-After")`, parse seconds OR HTTP-date (`email.utils.parsedate_to_datetime`), cap at `RETRY_AFTER_CAP_S` (D-08).

**Interruptible-sleep wiring (THE key pattern)** — the `Retrying(sleep=...)` callable is the daemon's existing `stop` event's `.wait`. The analog is `run_daemon`'s shutdown primitive:
```python
# daemon.py:319 already creates this:
stop = threading.Event()
# retry.py: thread the SAME event in as tenacity's sleep callable so the
# ~45-min mid-pause aborts instantly on SIGTERM (Pattern 7 / Pitfall 1):
Retrying(wait=two_burst_wait, stop=..., retry=..., sleep=stop.wait, reraise=True)
```

**`reliability/__init__.py`** — copy the barrel-export shape from `config/__init__.py` (re-export the public builder + classifier + reason constants in `__all__`).

> **Add `tenacity` to `pyproject.toml` deps** (line 6-13 array) before importing it; per RESEARCH Package Legitimacy Audit, gate the `uv add tenacity` behind a `checkpoint:human-verify` task. Fallback (no new dep) is a hand-rolled loop using `stop.wait(backoff)` — same interruptibility, more code.

---

### `weatherbot/scheduler/daemon.py` (service, event-driven) — wrap retry + heartbeat tick + harden isolation

**Analog:** itself — `fire_slot` (lines 59-167) and `run_daemon` (lines 283-332).

**Per-job isolation to HARDEN (D-12)** — the existing try/except is at `fire_slot` lines 99-167. The pattern to preserve and extend:
```python
local_date = None
claimed = False
try:
    ...
    if not claim_slot(db_path, location.name, slot.time, local_date):
        return None              # lost claim -> already sent (D-11 backstop)
    claimed = True
    result = send_now(...)       # <- WRAP THIS in retry.Retrying for the daemon path
    if not result.ok:
        release_claim(db_path, location.name, slot.time, local_date)
        claimed = False
    return result
except Exception as exc:  # noqa: BLE001 — one bad slot must not kill the thread
    if claimed and local_date is not None:
        release_claim(db_path, location.name, slot.time, local_date)
    _log.error("slot fire failed", location=location.name, time=slot.time, error=str(exc))
    return None
```
D-12 changes: the except block ALSO calls `record_alert(reason="internal_error")` + logs the **full traceback** (`_log.exception(...)` or `exc_info=True`) while still returning `None` so the scheduler thread survives. On retry exhaustion (transient) -> `record_alert(reason="transient_exhausted")`; on 401/403 short-circuit -> `record_alert(reason="auth_failed")`; on eventual success -> `resolve_alert(...)` + `stamp_success(...)` (D-13).

**Daemon `stop` event lifecycle (thread into the retry builder)** — `run_daemon` lines 319-332:
```python
stop = threading.Event()
def _handle(signum, frame):
    stop.set()
signal.signal(signal.SIGTERM, _handle)
try:
    stop.wait()
except KeyboardInterrupt:
    pass
finally:
    scheduler.shutdown(wait=False)
```
Pass this same `stop` into `fire_slot` (via the `kwargs` dict in `_register_jobs`, lines 201-208) so the retry's `sleep=stop.wait` shares it.

**Heartbeat tick registration** — copy the `_register_jobs` `scheduler.add_job(...)` shape (lines 193-212), swapping `CronTrigger` for `IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S)`, `id="__heartbeat__"`, `misfire_grace_time=None`, `coalesce=True`. The tick callback does `stamp_tick(db_path)` + `_log.info("heartbeat", last_tick=...)`. Register it inside `run_daemon` alongside `_register_jobs` (lines 300-307).

**Outcome-only logging convention (carry verbatim):** every `_log.*` call in this file passes flat kwargs `location=`, `time=`, `late=`, `delivered=` (lines 114-119, 146-152, 161-166) — never a secret. New `briefing_missed`/`heartbeat` events use the same flat-kwargs style with stable event keys.

---

### `weatherbot/cli.py` (controller) — daemon-vs-manual retry split + `--check` validation

**Analog:** itself — `send_now` (lines 81-165), `do_check` (lines 216-279), `main` (lines 303-409).

**`send_now` stays the shared composition root (retry-agnostic, single attempt).** Per RESEARCH Open Question 1, the recommended seam is: keep `send_now` one attempt; wrap retry in `fire_slot` (daemon, patient profile + `stop`); give `main`'s `--send-now` branch its own tight `Retrying` (D-10). The manual-path failure already reports to the terminal here (cli.py lines 405-409):
```python
if result.ok:
    _log.info("briefing delivered")
    return 0
_log.error("briefing delivery failed", detail=result.detail)
return 1
```
The manual tight retry wraps the `send_now(...)` call at lines 398-403 with a small `Retrying(stop=stop_after_attempt(3), wait=wait_exponential(...))` and `record_liveness=False` — **writes NO `alerts`/`heartbeat` rows** (D-10, Pitfall 4).

**`do_check` retry-config validation pattern (D-09)** — `do_check` already runs ordered validation steps and surfaces failures as exit 1 (lines 235-279). The 401/403 distinguishing block (lines 257-267) is the model for surfacing a config problem cleanly:
```python
try:
    client.fetch_onecall(config.locations[0], "imperial")
except httpx.HTTPStatusError as exc:
    status = exc.response.status_code
    if status in (401, 403):
        raise ValueError("... key/subscription may not be active ...") from exc
    raise
```
For D-09, the retry config is already validated at load by pydantic (see config/models.py pattern below); `--check` just surfaces it — add a step that echoes the resolved retry budget (attempts/spread/wait/total) so a mis-tune is visible, and let a malformed value fail at `load_config` exactly like a bad `time`/`timezone` does today.

**`_load_config_reporting` clean-failure pattern (lines 282-300)** — a malformed retry config raises `pydantic.ValidationError`, already caught and reported cleanly here (line 298-299). No change needed; the new `Reliability` model just rides this existing path.

---

### `weatherbot/config/models.py` (model) — new `Reliability`/`Retry` pydantic model (D-09)

**Analog:** itself — the `Schedule` model (lines 25-73) with `model_config = ConfigDict(extra="forbid")` and `@field_validator` fail-loud validators.

**Validator pattern to copy** (Schedule `_hhmm`, lines 45-55):
```python
model_config = ConfigDict(extra="forbid")

@field_validator("time")
@classmethod
def _hhmm(cls, v: str) -> str:
    try:
        ...
        if not (... valid range ...):
            raise ValueError
    except Exception as e:
        raise ValueError(f"time must be 'HH:MM' 24-hour, got {v!r}") from e
    return v
```
New `Reliability` model: fields like `attempts_per_burst: int = 8`, `burst_spread_seconds: int = 600`, `mid_pause_seconds: int = 2700`, each with a `@field_validator` enforcing positivity and (belt-and-suspenders, Pitfall 5) that `2*spread + mid_pause` stays under the 90-min grace window. Add it to `Config` (lines 126-138) as an optional field with `Field(default_factory=Reliability)` (mirrors `webhook` line 137) so existing configs without the section still load with D-07 defaults.

---

### `config.toml` / `config.example.toml` (config)

**Analog:** itself — the commented `[[locations]]` / `[[locations.schedule]]` blocks (config.example.toml lines 25-46), which document each field inline with `time`/`days`/`enabled` semantics.

Add a new top-level `[reliability]` (or `[retry]`) table with the same comment-above-each-key style documenting `attempts_per_burst`, `burst_spread_seconds`, `mid_pause_seconds` and the ~65-min total / under-90-min-grace constraint. Keep it optional (defaults match D-07) so `--check` passes on an un-edited file.

---

### `pyproject.toml` (config/deps)

**Analog:** itself — `[project] dependencies` array (lines 6-13). Add `"tenacity>=9.1.4"` to that array (pinned per STACK.md). Run `uv add tenacity` so `uv.lock` updates; gate behind `checkpoint:human-verify` (RESEARCH Package Legitimacy Audit).

---

### `tests/test_reliability.py` (NEW, unit test)

**Analog:** `tests/test_store.py` (lines 1-148) for store-helper tests + `tests/test_scheduler.py` (lines 1-90) for fire_slot/daemon behavior tests. Both use the shared `conftest.py` fixtures.

**Fixtures available (conftest.py lines 20-33):** `tmp_db` (fresh per-test SQLite path; schema created on first connect) and `load_fixture` (recorded OpenWeather JSON loader). Use `tmp_db` for every `alerts`/`heartbeat` assertion.

**Store-test pattern to copy** (test_store.py lines 34-77): a local `_connect` helper with `sqlite3.Row`, then arrange-act-assert over rows:
```python
def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def test_persist_onecall_writes_both_unit_rows(load_fixture, tmp_db):
    forecast = _build(load_fixture)
    persist(tmp_db, LOC, forecast)
    with _connect(tmp_db) as conn:
        rows = list(conn.execute("SELECT * FROM weather_onecall"))
    assert len(rows) == 2
```
Apply to: `test_exhaustion_alerts` (one `alerts` row + reason), `test_alert_dedup_no_loop` (two `record_alert` calls -> still one row, the INSERT-OR-IGNORE guarantee), `test_heartbeat_upsert` (`stamp_tick`/`stamp_success` -> single row 1 updates in place).

**Secret-leak assertion pattern to copy** (test_store.py lines 135-147): grep stored blobs / captured log output for `"appid"` and `"api.openweathermap.org"` and assert absent (Pitfall 6 / T-04-01).

**Time/sleep technique (RESEARCH Wave-0 note):** pass a recording mock as tenacity's `sleep=` to assert the two-burst wait sequence in milliseconds (`test_two_burst_wait_shape`); use `time-machine` (dev dep, pyproject line 19) for any wall-clock `stop_after_delay` assertion; for `test_pause_interruptible`, set the `stop` event and assert the retry abandons fast.

**Extend existing test files** (per RESEARCH Wave-0 gaps): `tests/test_store.py` (alerts/heartbeat helpers — same file, same idioms), `tests/test_cli.py` (`test_send_now_no_liveness_rows`, D-10), `tests/test_config.py` (`test_retry_config_validation`, D-09 — copy the existing field-validation test shape).

---

## Shared Patterns

### Idempotent dedup write (`INSERT OR IGNORE` on a UNIQUE key)
**Source:** `weatherbot/weather/store.py` `claim_slot` (lines 238-275) / `record_sent` (lines 213-235)
**Apply to:** `record_alert` (D-11 anti-loop), and conceptually the `heartbeat` seed row.
**Rule:** never SELECT-then-INSERT; the atomic `INSERT OR IGNORE` on `UNIQUE(location_name, slot_time, local_date)` is the race-free dedup primitive. `rowcount == 1` tells you THIS caller was first.

### Schema-on-connect + parameterized SQL (SQLi/secret hygiene)
**Source:** `weatherbot/weather/store.py` every helper (`conn.executescript(_SCHEMA)` then parameterized `?`, lines 203-210, 266-275)
**Apply to:** all new `alerts`/`heartbeat` helpers.
**Rule:** every value bound as `?`; new tables appended to the single `_SCHEMA` string; rows carry only `location`/`slot`/`local_date`/`reason`/`severity`/timestamps — never a key or URL (T-03-01 / T-04-01).

### Outcome-only structured logging (structlog, stable event key + flat fields)
**Source:** `weatherbot/scheduler/daemon.py` (`_log.info("slot fired", location=..., time=..., delivered=...)`, lines 146-152) and `_log = structlog.get_logger(__name__)` (line 56)
**Apply to:** the `briefing_missed` (CRITICAL) and `heartbeat` (INFO) events.
**Rule:** stable lowercase event key the future monitor greps; flat kwargs only; NEVER `key=`, `webhook_url=`, `detail=<url>`, or a request URL (T-04-01 / Pitfall 6). `cli.py:main` already calls `logging.basicConfig(level=logging.INFO)` (line 305) so CRITICAL emits.

### Interruptible wait via `threading.Event.wait` (clean shutdown)
**Source:** `weatherbot/scheduler/daemon.py` `run_daemon` `stop = threading.Event()` + `stop.wait()` (lines 319, 326)
**Apply to:** tenacity `Retrying(sleep=stop.wait)` so the ~45-min mid-pause aborts on SIGTERM (Pitfall 1). Thread the SAME `stop` event through `fire_slot`'s kwargs.
**Rule:** never `time.sleep` for the mid-pause.

### Fail-loud-at-load config validation (pydantic), surfaced by `--check`
**Source:** `weatherbot/config/models.py` `Schedule` `@field_validator` (lines 45-73) + `Config.model_validate` in `loader.load_config` (lines 18-27) + clean-report in `cli._load_config_reporting` (lines 282-300)
**Apply to:** the new `Reliability` model (D-09). A malformed retry value raises `ValidationError` at load and is reported cleanly + surfaced by `--check` — never discovered at 9am.

### Send-failure retry decision (DeliveryResult contract — DO NOT double-retry 429)
**Source:** `weatherbot/channels/base.py` `DeliveryResult(ok, detail)` (lines 23-34) + `weatherbot/channels/discord.py` `_post` (lines 72-117, note `rate_limit_retry=True` at line 83)
**Apply to:** the retry classifier — treat a Discord `DeliveryResult(ok=False)` as ONE transient unit (`retry_if_result(lambda r: not r.ok)`); the channel already waits out Discord 429s internally (line 83), so do NOT also retry a Discord 429 at the orchestration layer (Pitfall 2). The orchestration `Retry-After` cap applies to the OpenWeather **fetch** 429 (the `httpx.HTTPStatusError` path), not the Discord send. `detail` already carries status + body snippet only (lines 115-117) — credential-free, safe to log.

## No Analog Found

None. Every Phase-4 file maps to an existing in-repo pattern; the phase is pure additive composition over Phase 1-3 primitives (claim/release idempotency, `threading.Event` shutdown, httpx errors, structlog events, pydantic validators). The single genuinely new dependency is `tenacity` (engine), and even its usage shape (custom `wait`, `sleep=` hook, classification predicate) is fully specified by RESEARCH Patterns 1/4/7 against the existing `httpx`/`Event` surfaces.

## Metadata

**Analog search scope:** `weatherbot/weather/`, `weatherbot/scheduler/`, `weatherbot/channels/`, `weatherbot/config/`, `weatherbot/cli.py`, `tests/`, `config*.toml`, `pyproject.toml`
**Files scanned (read in full or targeted):** store.py, daemon.py, cli.py, client.py, channels/base.py, channels/discord.py, config/models.py, config/loader.py, config/__init__.py, conftest.py, test_store.py, test_scheduler.py (head), config.example.toml, pyproject.toml
**Pattern extraction date:** 2026-06-10
