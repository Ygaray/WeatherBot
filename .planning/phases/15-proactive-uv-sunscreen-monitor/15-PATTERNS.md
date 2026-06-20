# Phase 15: Proactive UV Sunscreen Monitor - Pattern Map

**Mapped:** 2026-06-19
**Files analyzed:** 5 (1 new, 4 modified)
**Analogs found:** 5 / 5 (every new/modified file has a direct in-repo precedent)

> Upstream status note (verified by reading the code, not assumed): the two Phase-14/Phase-12
> prerequisites the research flags as risks have **already landed**:
> - `weatherbot/weather/uv.py` `compute_uv` / `UvSummary` exists (Phase 14) — exposes
>   `current`, `max`, `crossing_time`, `window_start`, `window_end`, `peak_time`, `stays_below`.
> - `weatherbot/weather/client.py:62` `exclude` is already `"minutely"` (KEEPS `hourly[]`) (Phase 12 D-06).
> - `weatherbot/config/models.py:381` `UvConfig` exists with `threshold` (6.0) + `pre_warn_lead_minutes` (30).
>
> The Phase-15 planner should STILL keep a Wave-0 verification (the research's Dependency Contract)
> as a build-time canary, but these are present today — they are extension points, not blockers.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/scheduler/uvmonitor.py` (NEW) | service / scheduler-tick | event-driven (interval poll) → transform → pub | `weatherbot/scheduler/catchup.py` (pure decision module beside daemon) + `_heartbeat_tick` (daemon.py:569) | exact (structure) / role-match (logic is new) |
| `weatherbot/weather/store.py` (MODIFY: `uv_alerts` table + `claim_uv_alert` + `claimed_uv_kinds`) | model / persistence | CRUD (INSERT OR IGNORE dedup) | `record_alert` (store.py:308) + `claim_slot` (store.py:242) + `alerts` table (store.py:117) | exact |
| `weatherbot/config/models.py` (MODIFY: extend `UvConfig`) | config | — | existing `UvConfig` (models.py:381) + `Reliability`/`ReloadConfig` validators | exact |
| `weatherbot/scheduler/daemon.py` (MODIFY: register `__uvmonitor__` job in `run_daemon`) | route / wiring | event-driven (IntervalTrigger registration) | `__heartbeat__` registration (daemon.py:1365) | exact |
| `weatherbot/scheduler/catchup.py` (MODIFY: promote `_fires_on` → public `fires_on`) | utility | transform | existing `_fires_on` (catchup.py:90) | exact (in-place reuse) |

---

## Pattern Assignments

### `weatherbot/scheduler/uvmonitor.py` (NEW — service / scheduler-tick, event-driven)

**Primary structural analog:** `weatherbot/scheduler/catchup.py` (a pure, APScheduler-free decision
module that lives beside `daemon.py` and is *called from* it — exactly the placement RESEARCH §"Recommended
Project Structure" recommends so the tick + decision branches are unit-testable in isolation).

**Isolation-discipline analog:** the `fire_slot` try/except envelope (daemon.py:163-165) and the
`BotThread._run` swallow-and-flag pattern (bot.py:458-474) — both prove the UV-06 invariant: a tick
body wrapped so one bad location/post can never crash the scheduler thread or gate a briefing.

**Tick-entrypoint analog (the job callback shape):** `_heartbeat_tick` (daemon.py:569-582) — a small
top-level function that takes `db_path` (the monitor takes more kwargs: `holder`, `db_path`, `settings`,
`client`, `channel`), does in-function `from datetime import datetime, timezone` imports, and logs an
outcome-only event.

**Live-config re-read pattern** (copy from `fire_slot`, daemon.py:174-186): resolve the snapshot ONCE
per tick from the injected `holder`, then thread that same object through the whole tick — so a mid-tick
`replace()` (reload) can never tear a single tick, and threshold/lead/margin edits take effect on the
NEXT tick:
```python
# fire_slot, daemon.py:181-186 (the snapshot-once idiom to copy)
if config is not None:
    snapshot = config
elif holder is not None:
    snapshot = holder.current()
else:
    raise ValueError("fire_slot requires holder= or config=")
```
For the monitor: `snapshot = holder.current()` at the top of the tick; read
`snapshot.uv.threshold` / `snapshot.uv.pre_warn_lead_minutes` / the new monitor knobs from it.

**Active-today + daylight gate** (reuse `fires_on`; convert sun epochs in the CONFIGURED tz):
```python
# RESEARCH Code Examples — reuse catchup.fires_on, never re-derive weekday logic
from zoneinfo import ZoneInfo
from datetime import datetime
from weatherbot.scheduler.catchup import fires_on  # promoted from _fires_on (see below)

def _active_today(location, now_utc) -> bool:
    tz = ZoneInfo(location.timezone)
    now_local = now_utc.astimezone(tz)
    return any(s.enabled and fires_on(s, now_local) for s in location.schedule)
```
Daylight bound uses `daily[0].sunrise`/`sunset` epochs from the One Call payload, converted via
`datetime.fromtimestamp(epoch, tz=ZoneInfo(location.timezone))` — the SAME configured-tz discipline as
`uv.py:_today_daytime_points` (uv.py:56-58, 109-112) and `store.py:_local_date_iso` (store.py:160-167).
**Anti-pattern (Pitfall 3):** never use the API `timezone`/`timezone_offset` field.

**Forecast fetch — MUST NOT persist** (copy `lookup_weather`'s read-only fetch, NOT the briefing path):
```python
# lookup.py:117-118 — the "fetch without store.persist" precedent the monitor follows
onecall_imp = client.fetch_onecall(location, "imperial")
onecall_met = client.fetch_onecall(location, "metric")
```
The monitor calls `client.fetch_onecall(...)` directly and **never** calls `store.persist` (Pattern 4 /
UV-04 / DATA-03 delivered-only). UV is unitless (uv.py A1), so a single `imperial` fetch suffices for the
UV decision unless alert wording needs a temperature (RESEARCH Assumption A1 — planner confirms).

**UV computation — reuse Phase 14, do NOT re-derive** (uv.py:193 `compute_uv`):
```python
from weatherbot.weather.uv import compute_uv  # UvSummary with crossing_time/window/stays_below
summary = compute_uv(onecall_imp, onecall_met, snapshot.uv.threshold,
                     tz=ZoneInfo(location.timezone), now=now_local)
# summary.current, summary.crossing_time, summary.window_start/window_end, summary.stays_below
```

**Three decision branches** (RESEARCH Pattern 3 is authoritative — already-high checked BEFORE pre-warn):
- `prior = claimed_uv_kinds(db_path, location.id, local_date)` (new store reader, below)
- already-high / crossing: `summary.current >= threshold and "crossing" not in prior`
  → on first poll (no prior rows) also `claim_uv_alert(..., "prewarn")` to suppress the moot pre-warn,
    then `claim_uv_alert(..., "crossing")`; post only if the crossing claim wins.
- pre-warn: `summary.current < threshold and "prewarn"/"crossing" not in prior` and
  (`time_close` from `summary.crossing_time - now <= lead`) OR (`value_close`: `threshold - current <= margin`).
- all-clear: `summary.current < threshold and "crossing" in prior and "allclear" not in prior`.

**Best-effort post** (mirror `_do_reload`'s idiom, daemon.py:919-923):
```python
if channel is not None:
    try:
        channel.send(f"☀️ UV now ≥{threshold} in {location.name} — sunscreen on. Protect ~{win}.")
    except Exception:  # noqa: BLE001 — best-effort; a failed post never gates the monitor
        _log.warning("uv alert post failed; monitor unaffected")
```
Note: use `channel.send(text)` (the channel-agnostic plain-text path, discord.py:52-54) — NOT
`send_briefing` (which adds the briefing embed). `send` returns a `DeliveryResult` and never raises on a
non-2xx, but wrap it anyway for the network-raise + UV-06 belt-and-suspenders.

---

### `weatherbot/weather/store.py` (MODIFY — model / persistence, CRUD dedup)

**Analog:** `record_alert` (store.py:308-339) + `claim_slot` (store.py:242-279); table modeled on
`alerts` (store.py:117-127). **DP-1 decision: a NEW dedicated `uv_alerts` table** (keep UV dedup in its
own namespace so a UV bug can NEVER touch the briefing `sent_log`/`alerts` rows — a UV-06 safety property).

**Schema addition** — append to `_SCHEMA` (store.py:36-145), idempotent `CREATE TABLE IF NOT EXISTS` like
`alerts`/`heartbeat`/`health` (no migration script — auto-applied on first connect, RESEARCH Runtime State):
```sql
-- model on the alerts table shape (store.py:117), keyed for once/day/location/kind
CREATE TABLE IF NOT EXISTS uv_alerts (
    id             INTEGER PRIMARY KEY,
    location_id    TEXT    NOT NULL,   -- Location.id (rename-safe identity, models.py:188)
    local_date     TEXT    NOT NULL,   -- YYYY-MM-DD in the location's configured tz
    alert_kind     TEXT    NOT NULL,   -- 'prewarn' | 'crossing' | 'allclear'
    created_at_utc INTEGER NOT NULL,
    UNIQUE(location_id, local_date, alert_kind)   -- at-most-once/location/day/kind
);
```

**`claim_uv_alert` — structural copy of `record_alert`** (store.py:308-339, the `INSERT OR IGNORE` +
`rowcount==1` atomic "I am first" arbitration; parameterized `?` only, schema-on-connect):
```python
def claim_uv_alert(db_path, location_id: str, local_date: str, alert_kind: str) -> bool:
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

**`claimed_uv_kinds` — the prior-set reader** (modeled on `was_sent`'s read shape, store.py:220-239):
```python
def claimed_uv_kinds(db_path, location_id: str, local_date: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        rows = conn.execute(
            "SELECT alert_kind FROM uv_alerts WHERE location_id=? AND local_date=?",
            (location_id, local_date),
        ).fetchall()
    return {r[0] for r in rows}
```
**Key on `location.id`, not `location.name`** (store.py briefing key uses `location.id` — claim_slot is
called with `location.id` at daemon.py:201; `Location.id` defaults to `name` but is rename-safe, models.py:188-207).

---

### `weatherbot/config/models.py` (MODIFY — config; extend existing `UvConfig`)

**Analog:** the existing `UvConfig` (models.py:381-428) — DO NOT create a second `[uv]` table. Add the
three monitor-only knobs to the existing frozen model so there is ONE `[uv]` table (DP-3 / RESEARCH note:
"coordinate field placement so there's one `[uv]` table, not two"). The monitor READS `threshold` +
`pre_warn_lead_minutes` (already present); it ADDS:
```python
# add to UvConfig (models.py:402-405), each with a field_validator mirroring
# _threshold_in_range / _lead_in_range (models.py:407-428) — fail loud at both ends:
monitor_enabled: bool = True       # config gate, default on (the run_daemon registration guard)
interval_seconds: int = 900        # 15 min default (UV-04); restart-deferred (DP-2 — see daemon note)
value_margin: float = 1.0          # D-03 value-proximity ("within ~1 of threshold")
```
**Validator style to copy** (models.py:407-414) — `@field_validator` + `@classmethod`, raise `ValueError`
with the field name + got-value (e.g. `interval_seconds` bounded to a sane floor like ≥60 so a typo can't
hammer the API; `value_margin` 0..20 like `threshold`). The whole-`Config` reload re-reads the model, so
no reload-wiring change is needed (mirrors the `cloud_threshold` comment, models.py:448-453).

**Frozen-snapshot compatibility:** `model_config = ConfigDict(extra="forbid", frozen=True)` is already on
`UvConfig` (models.py:402) — keep it; the new fields inherit it, staying `ConfigHolder`-compatible.

---

### `weatherbot/scheduler/daemon.py` (MODIFY — route / wiring; register `__uvmonitor__`)

**Analog:** the `__heartbeat__` registration in `run_daemon` (daemon.py:1365-1372). Register the monitor
job IMMEDIATELY after it, gated on the config enable, with the extra `max_instances=1`:
```python
# EXISTING precedent to copy, verbatim (daemon.py:1365-1372):
scheduler.add_job(
    _heartbeat_tick,
    trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S),
    kwargs={"db_path": db_path},
    id="__heartbeat__",
    misfire_grace_time=None,
    coalesce=True,
)
```
```python
# NEW — register right after, gated on the config enable (read holder.current() here)
snapshot = holder.current()
if snapshot.uv.monitor_enabled:
    from weatherbot.scheduler.uvmonitor import _uv_monitor_tick  # lazy, like the in-function imports
    scheduler.add_job(
        _uv_monitor_tick,
        trigger=IntervalTrigger(seconds=snapshot.uv.interval_seconds),
        kwargs={"holder": holder, "db_path": db_path, "settings": settings,
                "client": client, "channel": channel},
        id="__uvmonitor__",
        misfire_grace_time=None,   # a missed tick is skipped, not stacked (same reasoning as heartbeat)
        coalesce=True,
        max_instances=1,           # never two concurrent ticks (Pitfall 4)
    )
```
The `holder`, `db_path`, `client`, `channel` are all already constructed in `run_daemon` (daemon.py:1324-1349)
and threaded into `_register_jobs` — the monitor reuses the SAME instances (one channel/process, WR-04).

**DP-2 (restart-deferred interval):** `IntervalTrigger(seconds=...)` bakes the interval at registration.
Document `interval_seconds` as restart-deferred (like `[reload] watch`, read once at startup). Do NOT
re-register `__uvmonitor__` in `_reconcile_jobs` — the reconcile already excludes `__heartbeat__`
(daemon.py:741, 787) by id; exclude `__uvmonitor__` the same way so a reload never disturbs it.
threshold/lead/margin/enable ARE live (read from `holder.current()` each tick).

---

### `weatherbot/scheduler/catchup.py` (MODIFY — utility; promote `_fires_on` → `fires_on`)

**Analog:** `_fires_on` itself (catchup.py:90-98) — it is now shared by two callers (the catch-up planner
and the UV monitor). Promote it to a PUBLIC `fires_on` (drop the underscore) so the monitor imports the
single source of truth; the catch-up planner keeps calling it. Do NOT copy-paste the weekday logic into
`uvmonitor.py` (Anti-Pattern: two divergent day-of-week implementations — catchup.py docstring Pitfall 3).
`_weekday_set` (catchup.py:68-87) can stay private; only `fires_on` needs promotion.

---

## Shared Patterns

### Failure isolation (UV-06)
**Source:** `fire_slot` try/except envelope (daemon.py:163-165) + `BotThread._run` (bot.py:458-474) +
APScheduler 3.x per-job exception catch.
**Apply to:** the `_uv_monitor_tick` body and the per-location loop inside it.
Two layers: APScheduler swallows any exception the job raises and keeps every other job running; the tick
ALSO wraps its body (and ideally each per-location iteration) so a single bad location/fetch/post isolates.
```python
# bot.py:472-474 — the swallow-and-log discipline to mirror in the tick body
except Exception:  # noqa: BLE001 — die alone; never crash the process (D-11)
    self._failed = True
    _log.critical("inbound bot thread crashed; briefings unaffected")
```
**Invariant:** the monitor NEVER calls `claim_slot`/`release_claim`/`sent_log` — it is structurally
incapable of touching the briefing exactly-once namespace (its dedup is the separate `uv_alerts` table).

### Configured-tz discipline (Pitfall 3)
**Source:** `uv.py:_epoch_local` (uv.py:56-58), `store.py:_local_date_iso` (store.py:160-167),
`catchup.py` `ZoneInfo(loc.timezone)` (catchup.py:139).
**Apply to:** every "today"/daylight computation in the monitor.
Always `ZoneInfo(location.timezone)`; convert `daily[0].sunrise`/`sunset` epochs with
`datetime.fromtimestamp(epoch, tz=...)`. Never the API `timezone`/`timezone_offset` field.

### Atomic once-per-X dedup (INSERT OR IGNORE + rowcount==1)
**Source:** `claim_slot` (store.py:242-279) / `record_alert` (store.py:308-339).
**Apply to:** all three UV alert kinds via `claim_uv_alert`. `rowcount == 1` ⇒ this caller is first ⇒
post. Restart-durable (the row survives a `systemctl restart` — defeats Pitfall 2 re-spam). Race-safe even
under a stacked tick.

### Best-effort in-channel post
**Source:** `_do_reload` (daemon.py:919-923) — `if channel is not None: try: channel.send(...) except: log`.
**Apply to:** every UV alert post. A failed post is logged and swallowed; it never gates the monitor or a
briefing.

### Lazy in-function imports (cycle avoidance)
**Source:** `fire_slot`'s `from weatherbot.cli import send_now` (daemon.py:214), `lookup.py`'s lazy
`build_client` (lookup.py:111-113), `run_daemon`'s in-function imports (daemon.py:1313, 1347).
**Apply to:** importing `_uv_monitor_tick` inside `run_daemon` and any `cli.build_client` use in the
monitor, so the new module doesn't widen the daemon's import-time graph.

---

## No Analog Found

None. Every new/modified file maps to a direct in-repo precedent. The only genuinely NEW *code* (not
*pattern*) is the three-branch decision logic in `_uv_monitor_tick` (RESEARCH Pattern 3) — and even that
consumes the existing `compute_uv` outputs and the existing dedup primitive; it composes proven parts.

## Metadata

**Analog search scope:** `weatherbot/scheduler/{daemon,catchup}.py`, `weatherbot/weather/{store,uv,client}.py`,
`weatherbot/config/models.py`, `weatherbot/channels/discord.py`, `weatherbot/interactive/{bot,lookup}.py`.
**Files scanned:** 10 (read targeted ranges; daemon.py and store.py read by grep-located sections).
**Pattern extraction date:** 2026-06-19
