# Phase 23: Scheduler Engine + OccurrenceStore + JobStore Seam - Pattern Map

**Mapped:** 2026-06-27
**Files analyzed:** 9 (4 new, 5 modified)
**Analogs found:** 9 / 9 (every file has a same-repo analog; `test_ports.py` is the only one with no direct test analog — written from Protocol contract)

> **D-06a LOCK honored:** `fire_slot` is NOT rewritten to thread an `OccurrenceStore` instance.
> The port ships as a defined-but-unconsumed type contract (the Phase-22 `AlertSink` precedent).
> `fire_slot` keeps calling the concrete `claim_slot` / `was_sent` / `release_claim` functions
> byte-identically. No `fire_slot` rewrite is mapped below.

> **Gate auto-scaling (verified):** the three import-hygiene gates in `tests/test_import_hygiene.py`
> scan by directory prefix — grimp builds over both top-level packages and filters module-owned
> importers (L165-170), the isolated-import smoke walks `pkgutil.walk_packages(pkg.__path__)`
> (L256), and the litmus `rglob("*.py")`s the whole module tree (L345). The NEW `scheduler/`
> subpackage and the two new `ports/` files are picked up with **zero gate edits**. The only
> additive test work is the *new coverage* (`test_scheduler_engine.py`, `test_ports.py`), not a
> gate rewrite. Coverage source already lists `yahir_reusable_bot` (`pyproject.toml:53`) → the
> relocated code is auto-covered; **no pyproject change** (Open Q2 resolved).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| NEW `yahir_reusable_bot/scheduler/engine.py` | service (thin registrar) | event-driven (job registration) | the 4 `add_job` sites in `weatherbot/scheduler/daemon.py` (L620, L659, L751, L1433) | role+flow exact |
| NEW `yahir_reusable_bot/scheduler/__init__.py` | config (barrel) | n/a | `yahir_reusable_bot/channels/__init__.py` | exact |
| NEW `yahir_reusable_bot/ports/occurrence.py` | port (Protocol) | request-response (claim/read/release) | `yahir_reusable_bot/ports/alerts.py` (`AlertSink`) | exact clone recipe |
| NEW `yahir_reusable_bot/ports/jobstore.py` | port (Protocol) + impl | event-driven (serialization contract) | `yahir_reusable_bot/ports/alerts.py` (altitude) + APScheduler serialization docs | role-match (altitude) |
| MOD `yahir_reusable_bot/ports/__init__.py` | config (barrel) | n/a | itself (the `AlertSink` export line) | exact |
| MOD `weatherbot/scheduler/daemon.py` | controller (orchestration) | event-driven | itself — adapt-don't-rewrite | n/a (in-place) |
| MOD `weatherbot/scheduler/catchup.py` | service (pure planner) | transform | itself — `was_sent` reader rebind only | n/a (in-place) |
| NEW `tests/test_scheduler_engine.py` | test | unit (read-back) | `tests/test_reliability.py::test_heartbeat_job_registered_with_slots` (L621-651) | exact |
| NEW `tests/test_ports.py` | test | unit (structural) | none (write from Protocol contract; `AlertSink` shipped untested) | no analog |

## Pattern Assignments

### `yahir_reusable_bot/ports/occurrence.py` (port, request-response)

**Analog:** `yahir_reusable_bot/ports/alerts.py` — clone this file's structure exactly.

**Module header + imports** (`ports/alerts.py:27-30`):
```python
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable
```

**Protocol shell + decorator** (`ports/alerts.py:33-41`):
```python
@runtime_checkable
class AlertSink(Protocol):
    """Out-of-band sink for missed-delivery alerts (record-once / resolve)."""
    ...
```

**Method shape to mirror** (`ports/alerts.py:43-66`) — note: methods take `self`, handle is
`str | os.PathLike[str]`, return is a plain `bool`/`None`, params are NEUTRAL nouns. The store's
native `location_name` was deliberately renamed to `target` here (litmus). For `OccurrenceStore`,
name params `handle`, `key`, `occurrence` (Pitfall 5 — `location_name` would trip `location`):
```python
    def record_alert(
        self,
        db_path: str | os.PathLike[str],
        target: str,            # store's native param is location_name — renamed neutral
        slot_time: str,
        local_date: str,
        reason: str,
        severity: str = "critical",
    ) -> bool:
        """Returns True iff THIS caller wrote the row (first alert for slot/day)."""
        ...
```

**Adapter body the port shapes to** (`weatherbot/weather/store.py`, UNCHANGED — D-09 adapter):
- `was_sent(db_path, location_name, send_time, local_date) -> bool` (L229-248) → port `was_fired(handle, key, occurrence) -> bool`
- `claim_slot(...) -> bool` — the `INSERT OR IGNORE … rowcount == 1` exactly-once primitive (L251-288) → port `claim(handle, key, occurrence) -> bool`
- `release_claim(...) -> None` (L291-314) → port `release(handle, key, occurrence) -> None`

**Lifecycle to name (D-07):** all three — `claim` + `was_fired` + `release`. The store's
parameterized `?`-only SQL (store.py:245, 285, 311) is the load-bearing invariant; the port
NEVER inlines a key into SQL (security: SQLi mitigation preserved by leaving the adapter untouched).

---

### `yahir_reusable_bot/ports/jobstore.py` (port + impl, event-driven)

**Analog:** `yahir_reusable_bot/ports/alerts.py` for the Protocol **altitude** (small, documented
contract — D-11) + APScheduler 3.x serialization docs for the contract payload.

**Same header/decorator pattern as `occurrence.py`** (clone `alerts.py:27-41`).

**The payload is the docstring, not the methods (D-11/D-12/D-13).** The Protocol body is
intentionally minimal; the three serialization constraints + the named-but-unbuilt durable
boundary ARE the deliverable. Grounding facts from the real call sites:
- **Importable callback:** `fire_slot` / `fire_forecast_slot` are module-level functions in `daemon.py` (defs at L131, L438) — referenceable by import path.
- **Picklable args:** every `add_job` site passes `args=[location, slot]` (pydantic models) + a plain-string `id` (`daemon.py:639-640`, `675-676`).
- **Look-up-at-fire-time:** `kwargs` carries `holder` (NOT a baked config) so a job re-reads `holder.current()` at fire — verified in the `_register_jobs` docstring (`daemon.py:605-608`) and the kwargs dict (`daemon.py:628-638`).
- **Durable boundary (name, build nothing — D-13):** today's `kwargs` thread NON-picklable handles `client`, `channel`, `stop_event`, `holder` (`daemon.py:632-637`). Docstring states a durable impl relocates these to a fire-time registry resolved by id.

Ship a trivial `MemoryJobStore` class (config-rederive impl) alongside — never serializes, carries the handles directly. Names `JobStore`, `MemoryJobStore` are litmus-clean.

---

### `yahir_reusable_bot/scheduler/engine.py` (service, event-driven)

**Analog:** the 4 `add_job` call sites in `weatherbot/scheduler/daemon.py`. The engine
centralizes the invariant kwargs spelled out at each.

**Briefing site** (`daemon.py:620-644`) — the full kwarg set to absorb:
```python
            scheduler.add_job(
                fire_slot,
                trigger=CronTrigger(
                    hour=hh, minute=mm,
                    day_of_week=slot.day_of_week, timezone=location.timezone,
                ),
                kwargs={ "holder": holder, "db_path": db_path, "settings": settings,
                         "client": client, "channel": channel, "stop_event": stop_event },
                args=[location, slot],
                id=f"{location.name}|{slot.time}|{slot.days}",
                replace_existing=replace_existing,
                misfire_grace_time=None,   # ← invariant
                coalesce=True,             # ← invariant
            )
```

**Heartbeat site** (`daemon.py:1433-1440`) — note the `IntervalTrigger` + NO `max_instances` here:
```python
    scheduler.add_job(
        _heartbeat_tick,
        trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S),
        kwargs={"db_path": db_path},
        id="__heartbeat__",
        misfire_grace_time=None,
        coalesce=True,
    )
```

**uvmonitor site** (`daemon.py:751-764`) — this one DOES pass `max_instances=1` (asymmetry, Pitfall 2):
```python
    scheduler.add_job(
        _uv_monitor_tick,
        trigger=IntervalTrigger(seconds=snapshot.uv.interval_seconds),
        kwargs={...},
        id="__uvmonitor__",
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1,
    )
```

**Engine surface (Discretion-resolved — thin registrar, app keeps the scheduler):**
`register(job_id, trigger, callback, *, args=None, kwargs=None, replace_existing=False)` →
`self._scheduler.add_job(callback, trigger=trigger, id=job_id, args=args, kwargs=kwargs,
replace_existing=replace_existing, misfire_grace_time=None, coalesce=True, max_instances=1)`.
Plus `remove(job_id)` → `remove_job` and `list_live_ids() -> set[str]` → `{j.id for j in get_jobs()}`.

**Byte-identical caveat (Pitfall 1+2):** baking `max_instances=1` into `register()` is safe because
APScheduler's `add_job` default IS `1` — but the schedule golden does NOT project `max_instances`/
`misfire_grace_time`/`coalesce` (it projects `str(trigger)` only). Assert these via a read-back test
(see `test_scheduler_engine.py` below), NOT via the golden.

---

### `yahir_reusable_bot/scheduler/__init__.py` (barrel)

**Analog:** `yahir_reusable_bot/channels/__init__.py` (full file) — clone exactly:
```python
"""..."""
from __future__ import annotations

from .engine import SchedulerEngine

__all__ = ["SchedulerEngine"]
```
(Module-side barrel imports NOTHING from `weatherbot` — the grimp gate enforces it.)

---

### `yahir_reusable_bot/ports/__init__.py` (barrel extension)

**Analog:** itself (`ports/__init__.py:10-12`) — extend the existing `AlertSink` export line:
```python
from .alerts import AlertSink         # existing line 10
# ADD:
from .occurrence import OccurrenceStore
from .jobstore import JobStore, MemoryJobStore

__all__ = ["AlertSink", "OccurrenceStore", "JobStore", "MemoryJobStore"]
```

---

### `weatherbot/scheduler/daemon.py` (controller — ADAPT, DON'T REWRITE)

**`_register_jobs` SPLIT (D-15):** the enumeration loop (`daemon.py:614-644` briefing,
`655-679` forecast) STAYS app-side as the Phase-24 `desired_jobs` seed. Inside the loop, swap
the inline `scheduler.add_job(...)` for `engine.register(job_id, trigger, callback, args=..., kwargs=..., replace_existing=...)`. Build the engine once at the top: `engine = SchedulerEngine(scheduler)`. The 4 invariant kwargs disappear from the call sites (they now live in `register`).

**Heartbeat (`daemon.py:1433`) + uvmonitor (`daemon.py:751`)** re-register through the engine identically (D-04 — internal jobs are an app-side id convention, not an engine concept).

**`run_daemon` startup ordering (`daemon.py:1419-1447+`)** — MUST stay byte-identical:
announce → `_register_jobs` → heartbeat → uvmonitor → catch-up → `scheduler.start()`. The app keeps
constructing/`start()`ing the scheduler (engine is a thin registrar holding a reference, NOT owning lifecycle).

**Reconcile read (`daemon.py:806-807`)** — the `{j.id for j in scheduler.get_jobs() if j.id not in ("__heartbeat__", "__uvmonitor__")}` becomes `engine.list_live_ids()` with the same app-side exclusion filter (D-04). `remove_job` (`daemon.py:832`) → `engine.remove(...)`.

**Import discipline (Pitfall 4):** import `SchedulerEngine` + ports INSIDE `daemon.py` (its import block at L60-79 / lazy), NEVER at `weatherbot/scheduler/__init__.py` top — that barrel runs during `weatherbot.config.models`'s `parse_days` import (PEP-562 lazy `run_daemon`, `__init__.py:23-28`) and an eager engine import could re-introduce a cycle.

**DO NOT TOUCH (D-16, Phase 24):** `_desired_job_ids`, `_reconcile_jobs`, `_restore_jobs`, `_do_reload`. Only the `list_live_ids`/`remove` read-throughs inside reconcile rebind.

---

### `weatherbot/scheduler/catchup.py` (pure planner — READER REBIND ONLY)

**STAYS app-side, unchanged except the `was_sent` reader binding (D-14).** `plan_catchup`'s
signature `was_sent: Callable[[str, str, str], bool]` (`catchup.py:106-108`) and its call
`was_sent(loc.id, slot.time, local_date)` (`catchup.py:175`) MUST keep the exact `(name, time, date)`
arg order (Pitfall 3 — 25 DST/catch-up goldens pin this). The rebind happens at the CALL SITE in
`daemon.py:1081` (`lambda name, time, date: was_sent(db_path, name, time, date)`), whose *body* may
forward through `OccurrenceStore.was_fired` — `catchup.py` itself gets no diff beyond docstring.

---

### `tests/test_scheduler_engine.py` (test, unit read-back) — NEW

**Analog:** `tests/test_reliability.py::test_heartbeat_job_registered_with_slots` (L621-651):
```python
    scheduler = BackgroundScheduler()
    daemon_mod._register_jobs(scheduler, ConfigHolder(config), db_path=tmp_db, settings=None,
                              stop_event=threading.Event())
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "__heartbeat__" in job_ids
    assert len(job_ids) == 2
```
**Extend it (Pitfall 1+2):** after `engine.register(...)` on a non-started `BackgroundScheduler`,
read each job back via `scheduler.get_jobs()` and assert `job.misfire_grace_time is None`,
`job.coalesce is True`, `job.max_instances == 1` — including on a BRIEFING job (proves the
`max_instances` default-of-1 baking is byte-identical). Also cover `engine.list_live_ids()` ==
`{j.id for j in get_jobs()}` and `engine.remove(id)` drops the job.

---

### `tests/test_ports.py` (test, unit structural) — NEW, NO ANALOG

`AlertSink` shipped untested, so write from the Protocol contract directly: assert
`OccurrenceStore` / `JobStore` are `runtime_checkable` Protocols; assert structural satisfaction
of `MemoryJobStore`; assert the litmus-clean param names. **Pitfall 6 caveat:** a `runtime_checkable`
`isinstance` checks attribute PRESENCE only, not the `self`-arg shape — a bare store *module* with
matching function names can spuriously pass. Test against a class instance (or document that the
port is the type contract, calls stay bare — the D-06a reading), not the bare `store` module.

## Shared Patterns

### Ports & Adapters (the milestone's recurring move — `OccurrenceStore` is #2, `JobStore` #3 after `AlertSink`)
**Source:** `yahir_reusable_bot/ports/alerts.py:27-66`
**Apply to:** `ports/occurrence.py`, `ports/jobstore.py`
- `from __future__ import annotations` + `import os` + `from typing import Protocol, runtime_checkable`
- `@runtime_checkable class X(Protocol):` with method bodies `...`
- Handle typed `str | os.PathLike[str]`; result `bool`/`None`; **neutral param names only**
- Structurally satisfied by existing app functions — **no subclassing** (D-08)

### Litmus-clean naming (Pitfall 5 — mandatory, not cosmetic)
**Source:** `tests/test_import_hygiene.py:61` (`_LITMUS = weather|forecast|location|openweather|\buv\b|briefing`)
**Apply to:** every `def`/`class`/param/annotation name in the new module files
- Store's native `location_name` → port `key` (Phase-22 renamed it `target` in `AlertSink`)
- Safe public names confirmed clean: `SchedulerEngine`, `OccurrenceStore`, `JobStore`, `MemoryJobStore`, `register`, `remove`, `list_live_ids`, `job_id`, `trigger`, `callback`, `handle`, `key`, `occurrence`, `claim`, `was_fired`, `release`

### Barrel + module-side import isolation
**Source:** `yahir_reusable_bot/channels/__init__.py` (subpackage barrel), `reliability/__init__.py` (multi-export barrel)
**Apply to:** `scheduler/__init__.py`, `ports/__init__.py` extension
- Module barrels import only from siblings, never from `weatherbot`

### Parameterized-SQL exactly-once primitive (security — preserve byte-identically)
**Source:** `weatherbot/weather/store.py:282-288` (`INSERT OR IGNORE … rowcount == 1`, `?`-bound)
**Apply to:** the `OccurrenceStore` adapter body stays this code UNCHANGED — never inline a key into SQL (SQLi mitigation T-03-01)

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tests/test_ports.py` | test | unit (structural) | `AlertSink` (the only prior port) shipped with no dedicated test; write asserts directly from the `runtime_checkable` Protocol contract + Pitfall-6 method-vs-function caveat. |

Every other file has a same-repo analog with cited line ranges.

## Metadata

**Analog search scope:** `yahir_reusable_bot/{ports,channels,reliability,scheduler}/`, `weatherbot/scheduler/{daemon,catchup,__init__}.py`, `weatherbot/weather/store.py`, `tests/{test_reliability,test_import_hygiene}.py`, `pyproject.toml`
**Files scanned:** 12
**Pattern extraction date:** 2026-06-27
