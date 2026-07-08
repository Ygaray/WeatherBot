# Phase 23: Scheduler Engine + OccurrenceStore + JobStore Seam - Research

**Researched:** 2026-06-27
**Domain:** Behavior-preserving extraction of a generic scheduler facade + exactly-once port + serialization-clean job-store Protocol out of `weatherbot/scheduler/daemon.py` into `yahir_reusable_bot`
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Scheduler Engine API & trigger model (SEAM-02)**
- **D-01 [roadmap-locked]:** Thin facade over APScheduler. `SchedulerEngine.register(job_id, trigger, callback, *, args=None, kwargs=None, replace_existing=False)` forwards to `BackgroundScheduler.add_job(callback, trigger=trigger, id=job_id, args=args, kwargs=kwargs, replace_existing=..., misfire_grace_time=None, coalesce=True, max_instances=1)`. The **same native trigger object the caller built reaches `add_job` untouched** — keeps the Phase-21 schedule-plan golden (`next_run_time`) byte-identical. APScheduler-as-trigger-type is an acceptable dependency (litmus forbids *weather* nouns, not scheduler deps).
- **D-02:** Passthrough native triggers only — caller constructs `CronTrigger(timezone=…)` / `IntervalTrigger(seconds=…)` / one-shot `DateTrigger`. **No** `engine.cron()/interval()/date()` sugar this phase.
- **D-03:** The proven defaults move INTO the engine as invariants — `misfire_grace_time=None`, `coalesce=True`, `max_instances=1`, per-tz. Centralizing the 4 copy-pasted call sites in `register()` *reduces* drift; values reaching APScheduler unchanged.
- **D-04 [roadmap-locked]:** Every job type re-registers through the engine — briefing, forecast, uvmonitor, **and** heartbeat. "Internal" jobs are an app-side convention (the `__name__`-style id prefix + reconcile exclusion list); the engine treats them identically. Engine also exposes `remove(job_id)` and `list_live_ids()` (the `get_jobs()` read) so the app keeps owning reconcile/catch-up.
- **D-05:** Callback + bound data pass through opaquely — `fire_slot`'s `args=[location, slot]` and runtime `kwargs` (`holder`, `client`, `channel`, `stop_event`) pass through unchanged; the engine never names or inspects them.
- **Rejected:** a neutral trigger-spec abstraction the engine owns (deferred to a real 2nd consumer).

**Exactly-once OccurrenceStore seam (SEAM-02)**
- **D-06 [roadmap-locked]:** Extract exactly-once out of `fire_slot` into a generic `OccurrenceStore` port + an app-supplied `occurrence_of` callable. The engine/port speak `(job_id, occurrence)`; WeatherBot supplies `occurrence = local_date` computed **app-side** from `location.timezone`/`scheduled_dt` exactly as `fire_slot` does today — engine never imports `zoneinfo`.
- **D-07:** The port carries the full claim lifecycle — `claim` + `was_fired` + `release`. `fire_slot`'s failure-path `release_claim` is part of the exactly-once contract, belongs with `claim`.
- **D-08:** Ports & Adapters, mirroring Phase-22 `AlertSink` exactly — `@runtime_checkable typing.Protocol` in `yahir_reusable_bot/ports/`, neutral param names, **structurally satisfied** by existing `weatherbot/weather/store.py` functions with no subclassing. The SQLite `sent_log` stays the app-side adapter.
- **D-09:** The adapter owns the `(job_id, occurrence)` ↔ `(location_name, send_time, local_date)` decomposition so `sent_log` rows stay byte-identical. The port is the *type contract*; `claim_slot(db_path, location.id, slot.time, local_date)` / `was_sent` / `release_claim` remain the *adapter body* unchanged. Cleanest no-drift form: `fire_slot` passes the already-separate `location.id` / `slot.time` / `local_date` so the adapter never concatenates then re-splits. The `INSERT OR IGNORE … rowcount==1` exactly-once primitive never moves.
- **Rejected:** engine-computed occurrence; engine-owned generic occurrence table (breaks `sent_log` goldens); `claim`+`was_fired` only with `release` stranded app-side.

**JobStore Protocol & in-memory impl (SEAM-03)**
- **D-10 [roadmap-locked]:** Ship a serialization-clean `JobStore` Protocol with the in-memory / config-rederive impl ONLY — durable impl deferred (JOBSTORE-V2-01). Seam-DESIGN task, not implementation.
- **D-11:** Minimal documented-contract seam altitude (not a fat `BaseJobStore`-mirroring Protocol). Smallest surface a future durable store needs, naming `MemoryJobStore` + config-rederive as the shipped impl, zero behavior change. Mirrors Phase-22 `AlertSink` altitude.
- **D-12:** The Protocol's real payload is the encoded serialization contract, locking 3 constraints already true today: (1) **importable callbacks** — `fire_slot`/`fire_forecast_slot` are module-level functions; (2) **picklable identity-style args** — `id` is a plain string, `args=[location, slot]` are pydantic models (never close a live client/channel into `args`); (3) **look-up-at-fire-time** — per-fire `kwargs` carry the `holder` (not a baked `config`), so a job re-resolves `holder.current()` at fire time.
- **D-13 (planner flag):** today's jobs thread **non-picklable runtime handles** (`client`, `channel`, `stop_event`, `holder`) through `kwargs`. The Protocol docstring MUST state that a *durable* impl would relocate those to a look-up-at-fire-time registry (resolved by id at fire, not pickled). **Name that boundary now — build none of it.**
- **Rejected:** a Protocol over `Job`-level CRUD mirroring `BaseJobStore`; a higher-level `JobSpec`/desired-jobs registry.

**Catch-up / DST ownership + Phase-23/24 demarcation**
- **D-14:** `plan_catchup` (catchup.py) STAYS app-side, unchanged. Only its `was_sent` reader **rebinds onto `OccurrenceStore`**. DST-safety lives in the planner. "The engine performs catch-up" means the engine provides the generic exactly-once firing path the app's catch-up drives, NOT that the engine derives missed slots.
- **D-15:** Moves into the engine NOW (Phase 23): the single-job `register` primitive, `remove(job_id)`, `list_live_ids()`, generic exactly-once via `OccurrenceStore` + `occurrence_of`, the `JobStore` Protocol (in-memory impl). `_register_jobs` **splits** into "enumerate desired slots (app)" + "register one job (engine)" — the enumeration loop stays app-side as the Phase-24 `desired_jobs` seed.
- **D-16:** Defers to Phase 24 (SEAM-04): `_desired_job_ids`, `_reconcile_jobs`, `_restore_jobs`, `_do_reload`.
- **Pull-forward flags (reject in planning):** (a) missed-slot/DST derivation *inside* the engine, (b) moving `_reconcile_jobs`/`_restore_jobs`/`_do_reload` in Phase 23, (c) deriving `desired_jobs` as anything but an app-side hook seed.

### Claude's Discretion
- Exact module sub-layout for the engine (`scheduler/` package inside `yahir_reusable_bot/` vs flatter) and file naming.
- Precise `SchedulerEngine` class surface beyond `register`/`remove`/`list_live_ids` (whether `start`/`shutdown`/the `BackgroundScheduler` ownership wraps too, or the app keeps the scheduler and the engine is a thin registrar) — shaped by what `run_daemon` needs to keep byte-identical startup ordering (announce → register → catch-up → `scheduler.start()`).
- Exact `OccurrenceStore` / `JobStore` Protocol method signatures and whether `release` is named `release`/`release_claim`.
- How the daemon-internal id convention (`__heartbeat__` / `__uvmonitor__`) + reconcile exclusion list is expressed against `list_live_ids()`.
- The `grimp`-graph assertion form for the new `scheduler` edges + isolated-import smoke extension.

### Deferred Ideas (OUT OF SCOPE)
- Durable / dynamic `JobStore` implementation (JOBSTORE-V2-01) — Protocol + in-memory impl only ship here.
- `_reconcile_jobs` / `_restore_jobs` / `_do_reload` + `desired_jobs` derivation — Phase 24.
- Heartbeat as a lifecycle concern / READY-gate — Phase 25. This phase only re-registers the existing heartbeat job through the engine.
- Neutral trigger-spec abstraction (`CronSpec`/`IntervalSpec`/`DateSpec`) or `engine.cron()/interval()/date()` sugar — until a real 2nd consumer.
- Full docstring/comment scrub of weather nouns — Phase 28 / DOCS-01. The signatures-only litmus governs now.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEAM-02 | Scheduler engine exposes `register(job_id, trigger, callback)` accepting arbitrary triggers, fires exactly-once keyed on a generic `(job_id, occurrence)`, is DST-safe, and performs restart catch-up — containing no location/weather concept. | `SchedulerEngine` thin-facade pattern (Pattern 1) preserves the 4 call-site `add_job` defaults byte-identically; `OccurrenceStore` Protocol (Pattern 2) extracts the `INSERT OR IGNORE` exactly-once primitive as a type contract; DST-safety stays in app-side `plan_catchup` (D-14); the engine provides the generic exactly-once *firing path*, app derives *what* to fire. |
| SEAM-03 | Job persistence is a serialization-clean `JobStore` Protocol seam (importable callbacks, picklable ids, look-up-at-fire-time); in-memory / config-rederive impl ships; durable impl deferred. | The serialization contract (Pattern 3) is verified true of today's jobs against APScheduler's own serialization requirements; `MemoryJobStore` config-rederive impl name + docstring-encoded durable-store boundary (D-13) is the entire deliverable. |
</phase_requirements>

## Summary

This phase is a **pure, behavior-preserving extraction**, not a redesign. The hard architectural calls are roadmap-locked (D-01/D-06/D-10); the work is mechanically un-braiding three already-existing-and-proven mechanisms out of `daemon.py` into `yahir_reusable_bot`, while the ~740-test suite plus the Phase-21 schedule-plan golden (`(job_id, str(trigger), next_run_time)`) and `sent_log` DB-row goldens stay byte-identical. Any non-empty snapshot diff is a failure to investigate, never to rubber-stamp.

The single most important structural insight from inspecting the Phase-22 precedent: **Phase 22 moved the real code (the `Channel` ABC into `yahir_reusable_bot/channels/base.py`, the retry engine into `yahir_reusable_bot/reliability/retry.py`) and left app-side re-export shims** (`weatherbot/channels/base.py`, `weatherbot/reliability/__init__.py`) so every pre-existing importer resolves to the *identical object* — the Phase-21 exception-identity pins depend on this. Critically, the `AlertSink` **port was DEFINED but is NOT yet consumed in production** (`grep` confirms zero production references outside `ports/`): it is a forward-declared, structurally-satisfiable type contract. Phase 23 follows this exact dual move: relocate the engine mechanism, define the two ports, and keep `fire_slot` calling its store functions (now through the port-typed seam) byte-identically.

**Primary recommendation:** Build `SchedulerEngine` as a **thin registrar that wraps the app-owned `BackgroundScheduler`** (the app keeps constructing and `start()`ing the scheduler in `run_daemon` so the announce→register→catch-up→start ordering stays byte-identical; the engine owns only `register`/`remove`/`list_live_ids` and bakes in the `misfire_grace_time=None`/`coalesce=True`/`max_instances=1` defaults). Define `OccurrenceStore` and `JobStore` as `@runtime_checkable typing.Protocol`s in `yahir_reusable_bot/ports/` cloned exactly from `ports/alerts.py`. The `JobStore` deliverable is a small Protocol + a `MemoryJobStore` impl + a docstring that *names* the durable-store boundary — built none of it.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Single-job registration with proven defaults | Module (`SchedulerEngine`) | App (`run_daemon` owns the scheduler instance) | The `add_job` defaults are mechanism, weather-free — centralizing them is the SEAM-02 deliverable. The scheduler instance + lifecycle (`start`/`shutdown`) stay app-side because `run_daemon`'s startup ordering is the byte-identical contract. |
| Exactly-once delivery primitive (`INSERT OR IGNORE … rowcount==1`) | App (`store.py` adapter) | Module (`OccurrenceStore` Protocol = type contract only) | The primitive produces `sent_log` rows the Phase-21 goldens pin — it must stay in the SQLite adapter. The module owns only the structural shape. |
| Occurrence derivation (`local_date` from per-tz `scheduled_dt`) | App (`fire_slot` / `occurrence_of` callable) | — | Irreducibly tz-coupled; the engine never imports `zoneinfo`. |
| Missed-slot / DST derivation (`plan_catchup`) | App (`catchup.py`, unchanged) | Module (engine provides the generic firing path the planner drives) | Config/tz-coupled and already a pure function; only its `was_sent` reader rebinds onto the port. |
| Serialization contract (importable callbacks, picklable args, fire-time lookup) | Module (`JobStore` Protocol + `MemoryJobStore`) | App (the daemon jobs already satisfy it today) | The contract is generic; the encoded constraints + the durable-store boundary doc are the SEAM-03 deliverable. |
| Job lifecycle / reconcile / reload | App (`daemon.py`) — **defers to Phase 24** | — | Moving it now hijacks SEAM-04 and bakes weather config into the engine. |

## Standard Stack

No new runtime dependencies. This is a relocation within the existing, frozen stack.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| APScheduler | 3.11.2 | The `BackgroundScheduler` + `CronTrigger`/`IntervalTrigger`/`DateTrigger` the engine wraps untouched | `[VERIFIED: .venv import]` already pinned `apscheduler>=3.11.2,<4` in pyproject.toml. 3.x is the stable line (4.x is pre-prod). |
| typing (stdlib) | 3.12 | `Protocol` + `runtime_checkable` for `OccurrenceStore` / `JobStore` ports | `[VERIFIED: codebase]` the exact pattern Phase 22 used for `AlertSink`. |

### Supporting (dev / gate)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| grimp | >=3.14 | Static import-graph gate (module→app edge detection) | `[VERIFIED: pyproject.toml L36]` already a dev dep from Phase 22. The new `scheduler` edges re-run the standing gate; no per-module test edit needed — `_scan_app_leaks` auto-scales by prefix. |
| pytest | (installed) | Drives the import-hygiene gates + the goldens | `[VERIFIED: codebase]` 740 tests collected. |
| syrupy / time-machine | (installed) | The schedule-plan + `sent_log` goldens (the byte-identical oracle) | `[VERIFIED: 21-PATTERNS.md]` |

**Installation:** None. `uv sync` against the existing lock.

**Version verification:** `[VERIFIED: .venv/bin/python -c "import apscheduler"]` → `apscheduler.__version__ == 3.11.2`. `grimp>=3.14` present in `pyproject.toml`.

## Package Legitimacy Audit

> No external packages are installed in this phase. All dependencies (apscheduler 3.11.2, grimp 3.14, typing stdlib) are pre-existing, already-locked, and verified present in the environment. **No new packages → audit table empty by design.**

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

Conceptual data flow after the extraction (the dashed boundary is the one-way `yahir_reusable_bot` ↔ `weatherbot` line the grimp gate enforces):

```
                         ┌──────────────────────── weatherbot (app) ────────────────────────┐
  config.toml ─────────▶ │  run_daemon  (composition root — OWNS BackgroundScheduler)        │
                         │     │  announce → register → catch-up → scheduler.start()          │
                         │     ▼                                                              │
  enabled slots ───────▶ │  _register_jobs (ENUMERATE loop — Phase-24 desired_jobs seed)      │
                         │     │  for each (location, slot): build CronTrigger(tz=…)           │
                         │     ▼                                                              │
                         │  engine.register(job_id, trigger, fire_slot, args=[loc,slot],      │
                         │                   kwargs={holder,client,channel,stop_event}) ───┐  │
                         │                                                                 │  │
                         │  fire_slot (per-fire callback, UNCHANGED orchestration)         │  │
                         │     occurrence = local_date  ← occurrence_of(loc, scheduled_dt) │  │
                         │     store.claim_slot(db, loc.id, slot.time, local_date) ──┐      │  │
                         │     ...send... ; on fail: store.release_claim(...) ───────┤      │  │
                         └──────────────────────────────────────────────────────────┼──────┼──┘
                            (app-side SQLite adapter — sent_log rows byte-identical)  │      │
                                                                                     │      │
                         ╔═════════════════════ yahir_reusable_bot (module) ═════════╪══════╪══╗
                         ║  OccurrenceStore (Protocol)  ◀── store.py satisfies ──────┘      │  ║
                         ║     claim(handle, key, occurrence) → bool                        │  ║
                         ║     was_fired(handle, key, occurrence) → bool                    │  ║
                         ║     release(handle, key, occurrence) → None                      │  ║
                         ║                                                                  ▼  ║
                         ║  SchedulerEngine (thin registrar over the app's scheduler)          ║
                         ║     register(job_id, trigger, callback, *, args, kwargs,             ║
                         ║              replace_existing)                                       ║
                         ║       → scheduler.add_job(..., misfire_grace_time=None,              ║
                         ║                            coalesce=True, max_instances=1)           ║
                         ║     remove(job_id)        list_live_ids() → set[str]                 ║
                         ║                                                                      ║
                         ║  JobStore (Protocol) + MemoryJobStore   ← serialization contract     ║
                         ║     (importable callback + picklable id/args + fire-time lookup)     ║
                         ║     docstring NAMES the durable-store registry boundary (D-13)       ║
                         ╚══════════════════════════════════════════════════════════════════════╝
```

### Recommended Project Structure (Claude's discretion — recommendation)

Mirror the existing `channels/` (subpackage with `base.py` + barrel `__init__.py`) and `ports/` shapes:

```
yahir_reusable_bot/
├── ports/
│   ├── __init__.py          # extend barrel: + OccurrenceStore, JobStore
│   ├── alerts.py            # AlertSink (Phase 22 — clone this exactly)
│   ├── occurrence.py        # NEW — OccurrenceStore Protocol
│   └── jobstore.py          # NEW — JobStore Protocol + MemoryJobStore impl
└── scheduler/               # NEW subpackage (the "scheduler" move-path package)
    ├── __init__.py          # barrel: export SchedulerEngine
    └── engine.py            # NEW — SchedulerEngine (thin registrar)
```

App-side `weatherbot/scheduler/daemon.py` stays put (it is the irreducibly-coupled orchestration — "adapt, don't rewrite"); it grows an `import` of `SchedulerEngine` and the two ports and rebinds its `add_job`/`claim_slot`/`release_claim`/`was_sent` call sites onto them.

> **Note on `JobStore`/`MemoryJobStore` naming and the litmus:** `JobStore`, `MemoryJobStore`, `OccurrenceStore`, `SchedulerEngine`, `register`, `occurrence`, `job_id`, `claim`, `was_fired`, `release` are all weather-clean (`_LITMUS = weather|forecast|location|openweather|\buv\b|briefing`). Verified mentally against the pattern — none of the proposed public names match.

### Pattern 1: SchedulerEngine — thin registrar over the app-owned scheduler

**What:** A small class wrapping a `BackgroundScheduler` instance, centralizing the four copy-pasted `add_job` invariant kwargs.
**When to use:** Every job registration (briefing, forecast, uvmonitor, heartbeat) routes through `engine.register(...)`.
**Recommendation (Discretion resolution — the app keeps scheduler ownership):** `run_daemon` must keep building the scheduler and calling `scheduler.start()`/`scheduler.shutdown(wait=False)` itself, because the startup ordering and the `getattr(scheduler, "running", True)` shutdown guard are load-bearing and golden-pinned. The cleanest no-drift form is an engine that *holds a reference* to the app's scheduler and exposes only the three primitives — NOT one that owns `start`/`shutdown`. This keeps the byte-identical announce→register→catch-up→start sequence entirely inside `run_daemon`.

```python
# Source: synthesized from weatherbot/scheduler/daemon.py:620-680, 1433-1440 (the 4 add_job sites)
#         + apscheduler 3.x add_job contract. [VERIFIED: codebase + apscheduler docs]
# yahir_reusable_bot/scheduler/engine.py
from __future__ import annotations
from typing import Any, Callable

class SchedulerEngine:
    """Thin registrar over a host-owned APScheduler BackgroundScheduler.

    Centralizes the proven invariants (misfire_grace_time=None, coalesce=True,
    max_instances=1) that the host currently copy-pastes at every registration
    site, so a missed kwarg can never drift one job off the contract. The host
    constructs, starts, and shuts down the scheduler; this engine only registers,
    removes, and lists jobs — it learns no reconcile/catch-up concept.
    """

    def __init__(self, scheduler) -> None:
        self._scheduler = scheduler

    def register(
        self,
        job_id: str,
        trigger,                       # native APScheduler trigger, passed THROUGH untouched
        callback: Callable[..., Any],
        *,
        args: list | None = None,
        kwargs: dict | None = None,
        replace_existing: bool = False,
    ) -> None:
        self._scheduler.add_job(
            callback,
            trigger=trigger,
            id=job_id,
            args=args,
            kwargs=kwargs,
            replace_existing=replace_existing,
            misfire_grace_time=None,   # recovery owned by the occurrence store + catch-up
            coalesce=True,
            max_instances=1,
        )

    def remove(self, job_id: str) -> None:
        self._scheduler.remove_job(job_id)

    def list_live_ids(self) -> set[str]:
        return {job.id for job in self._scheduler.get_jobs()}
```

**Byte-identical caveat (HIGH-confidence pitfall):** today only the heartbeat/uvmonitor sites pass `max_instances=1`; the briefing/forecast `add_job` sites at daemon.py:620 and :659 do **NOT** pass `max_instances` (they rely on the APScheduler default of `1`). Since the default *is* `1`, baking `max_instances=1` into `register()` is behavior-preserving — but this must be **verified against the schedule-plan golden** (`str(job.trigger)` is unaffected by `max_instances`, and `max_instances` is not in the golden projection, so the golden will not catch a regression here — see Pitfall 2). `[VERIFIED: daemon.py:620,659,751,1433]`

### Pattern 2: OccurrenceStore — clone of the AlertSink port recipe

**What:** A `@runtime_checkable typing.Protocol` with neutral param names, structurally satisfied by `weatherbot/weather/store.py`'s `claim_slot`/`was_sent`/`release_claim` with no subclassing.
**When to use:** It is the *type contract* `fire_slot` and `_run_catchup`'s `was_sent` reader bind onto. Like `AlertSink`, it may be defined now and not threaded through every call site beyond the rebind — but D-07/D-09 want `fire_slot` to call through it.

```python
# Source: cloned from yahir_reusable_bot/ports/alerts.py [VERIFIED: codebase]
# yahir_reusable_bot/ports/occurrence.py
from __future__ import annotations
import os
from typing import Protocol, runtime_checkable

@runtime_checkable
class OccurrenceStore(Protocol):
    """Generic exactly-once gate keyed on (job identity, occurrence).

    The host supplies the implementation (e.g. an INSERT-OR-IGNORE against a
    UNIQUE key). `claim` is the atomic check-and-mark taken BEFORE the
    side-effecting work; `was_fired` is the read; `release` re-opens a claim
    when the work later fails so the occurrence stays re-fireable. Neutral by
    construction — no domain noun appears in the name surface.
    """

    def claim(self, handle: str | os.PathLike[str], key: str, occurrence: str) -> bool:
        """Atomically claim (job key, occurrence). True iff THIS caller won."""
        ...

    def was_fired(self, handle: str | os.PathLike[str], key: str, occurrence: str) -> bool:
        ...

    def release(self, handle: str | os.PathLike[str], key: str, occurrence: str) -> None:
        ...
```

**Critical D-09 friction point (the one real decomposition decision):** the store functions take `(db_path, location_name, send_time, local_date)` — a *four*-arg, weather-shaped triple-plus-handle — while the port speaks `(handle, key, occurrence)` — a *three*-arg neutral pair-plus-handle. The two key components (`location.id` + `slot.time`) collapse into one port `key` while `local_date` is the `occurrence`. **Resolution per D-09: keep the decomposition inside the app-side adapter — never concat-then-resplit.** The recommended adapter is a thin app-side class that holds the `(location, slot)` identity and forwards to the bare store functions:

```python
# Source: app-side — weatherbot/weather/store.py functions unchanged behind this. [VERIFIED]
# weatherbot/scheduler/...  (app side; NOT in the module)
class _SlotOccurrenceAdapter:           # structurally an OccurrenceStore
    """Decomposes (key, occurrence) back to (location_name, send_time, local_date)
    so sent_log rows stay byte-identical. The triple lives ONLY here."""
    def claim(self, handle, key, occurrence) -> bool:
        loc_id, send_time = key.split("\x00", 1)         # or pass parts separately — see note
        return claim_slot(handle, loc_id, send_time, occurrence)
    ...
```

> **No-drift refinement (recommended, resolves the split risk):** D-09 explicitly prefers `fire_slot` to **pass the already-separate parts** rather than concat-then-split. Two viable shapes for the planner to choose between — both keep `sent_log` byte-identical:
> 1. **Port `key` is opaque, adapter splits** (shown above) — risks a separator collision if `location.id` ever contains the sentinel. Lower-altitude port.
> 2. **`fire_slot` calls the bare store functions directly** (today's behavior) and the `OccurrenceStore` Protocol is defined-but-bound-as-a-type-annotation only (the AlertSink precedent — defined, not yet threaded). This is the **lowest-risk, most byte-identical** option and is consistent with how Phase 22 shipped AlertSink. **Recommendation: option 2 for the production call sites, with the Protocol shipped as the contract** — it guarantees zero `sent_log` byte change and defers the concat/split question to a real reminder-bot consumer. Flag for `/gsd-discuss-phase` if the planner reads D-07 ("`fire_slot` rebinds onto it") as mandating option 1.

### Pattern 3: JobStore Protocol + MemoryJobStore — the serialization contract IS the deliverable

**What:** A minimal Protocol whose docstring encodes the three serialization constraints, plus a trivial in-memory / config-rederive impl. The Protocol is NOT a `BaseJobStore` mirror.
**When to use:** Shipped as a contract + the one concrete impl; the durable impl is named in the docstring and built nowhere.

```python
# Source: synthesized from apscheduler 3.x serialization requirements [CITED: apscheduler.readthedocs.io/en/3.x/userguide.html]
#         + daemon.py job-registration analysis [VERIFIED: codebase]
# yahir_reusable_bot/ports/jobstore.py
from __future__ import annotations
from typing import Protocol, runtime_checkable

@runtime_checkable
class JobStore(Protocol):
    """Where registered jobs live — shaped so a future DURABLE store is a drop-in.

    SERIALIZATION CONTRACT (true of every job the host registers today; a durable
    backend inherits it for free):
      1. IMPORTABLE CALLBACK — the registered callable is a module-level function
         referenceable by import path (what a serializing store pickles by reference).
      2. PICKLABLE IDENTITY-STYLE ARGS — the job id is a plain string and positional
         args are plain data (e.g. dataclasses / pydantic models); a live network
         client, socket, channel, or threading primitive is NEVER closed over args.
      3. LOOK-UP-AT-FIRE-TIME — per-fire keyword data carries a holder/registry that
         is re-resolved at fire time, never a baked-in snapshot, so an unchanged job
         picks up live state on its next fire.

    DURABLE-STORE BOUNDARY (named here, BUILT NOWHERE — JOBSTORE-V2-01): the host's
    jobs currently thread NON-picklable runtime handles (a live client, a delivery
    channel, a stop signal, a config holder) through per-fire keyword data. A durable
    impl that serializes jobs would relocate those handles to a process-level registry
    resolved BY ID at fire time, rather than pickling them. Designing that registry is
    deferred to the first consumer that needs persistence; this in-memory impl never
    serializes, so it carries the handles directly.
    """
    ...   # intentionally minimal — the contract is the payload (D-11/D-12)

class MemoryJobStore:                  # the shipped impl (config-rederive)
    """In-memory job store: holds jobs directly, never serializes (so the
    non-picklable handles above are carried as-is). The job set is re-derived
    from config on each (re)start — surviving a restart is the deferred durable
    impl's job, not this one."""
    ...
```

**APScheduler grounding `[CITED: apscheduler.readthedocs.io/en/3.x/userguide.html]`:** the docs state a serializing job store imposes exactly two requirements — "the target callable must be globally accessible" and "any arguments to the callable must be serializable" — and confirm "only `MemoryJobStore` doesn't serialize jobs." This is precisely the contract D-12 encodes: today's daemon uses the default `MemoryJobStore` (no jobstore configured → APScheduler's default), so nothing serializes today, but the jobs are *already* written serialization-clean (module-level `fire_slot`, string ids, pydantic-model args) — the contract documents an invariant that already holds.

### Anti-Patterns to Avoid
- **Engine owns `start`/`shutdown`/the scheduler instance:** would force `run_daemon`'s byte-identical announce→register→catch-up→start ordering to thread through the engine, risking a reorder the schedule-plan golden cannot catch. Keep the scheduler app-owned (Pattern 1).
- **Engine computes the occurrence:** rejected by D-06 — the engine would have to `import zoneinfo` and learn `local_date`, breaking the litmus.
- **Engine-owned generic occurrence table:** rejected by D-09 — stops producing `sent_log` rows → breaks the DB-row goldens.
- **Fat `JobStore` mirroring `BaseJobStore`:** rejected by D-12 — a durable store subclasses `BaseJobStore` directly, so the Protocol would have zero shipped consumers and leak APScheduler's `Job` type into the seam.
- **Moving `_reconcile_jobs`/`_restore_jobs`/`_do_reload`/`_desired_job_ids` in this phase:** Phase-24 deliverable (D-16). `_register_jobs` *splits* (enumerate app-side, register engine-side) but the reconcile/reload functions stay put.
- **Concat-then-resplit the `(location_name, send_time, local_date)` triple:** D-09 — pass the already-separate parts so `sent_log` bytes are identical.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exactly-once delivery | A new generic occurrence table in the engine | The existing `store.py` `INSERT OR IGNORE … rowcount==1` behind the `OccurrenceStore` Protocol | The primitive is proven, race-tested (claim_slot docstring documents the SCHD-07 gap it closes), and produces the golden-pinned `sent_log` rows. |
| Cron/interval/date trigger semantics | An `engine.cron()/interval()/date()` translation layer (D-02 rejected) | Pass the caller's native APScheduler trigger object straight through | Spec→`CronTrigger` translation is the single most likely place to silently shift `next_run_time` and break the golden. |
| DST-safe missed-slot derivation | A re-implementation inside the engine | `plan_catchup` (app-side, unchanged) | It is already a pure, DST-correct function with the gap/fold round-trip logic (catchup.py:161-168) in lockstep with the live `CronTrigger` via the shared normalized `day_of_week`. |
| Serialization machinery | A custom pickling layer for jobs | APScheduler's own `MemoryJobStore` (default) + the documented contract | Today's jobs already satisfy APScheduler's serialization requirements; the contract just *names* them. |
| Job-store persistence | A durable backend (JOBSTORE-V2-01) | Ship the Protocol + in-memory impl; document the boundary | YAGNI — no v2.0 consumer; building it blind risks guessing the reminder bot's needs wrong. |

**Key insight:** Every "new" thing in this phase is a *relocation or a type contract over already-proven app code*. The only genuinely-new code is `SchedulerEngine` (≈30 lines), two Protocol files (clones of `alerts.py`), and a `MemoryJobStore` stub. Net production-behavior change: zero.

## Runtime State Inventory

> This is an in-place package-boundary refactor (no rename, no rebrand, no string replacement, no data migration). The Phase-21/22 precedent moved code via shims with the SQLite store untouched. Each category checked explicitly below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None affecting this phase.** The `sent_log` / `alerts` / `heartbeat` / `health` SQLite tables and their `UNIQUE` keys are UNCHANGED — D-09 keeps every column and the `INSERT OR IGNORE` primitive byte-identical. No collection/key/id string is renamed. | None — verified against `store.py` schema (L108-153) and D-09. |
| Live service config | **None.** This phase touches no external service config. APScheduler job ids (`{name}\|{time}\|{days}`, `__heartbeat__`, `__uvmonitor__`) are in-process only (default `MemoryJobStore`, lost on exit by design) — not persisted anywhere external. | None — verified: daemon uses the default in-memory jobstore (no `add_jobstore` call in `run_daemon`). |
| OS-registered state | **None.** The live systemd service (`weatherbot` on host `yahir-mint`, per MEMORY.md) runs the daemon, but no unit/timer/task description embeds a scheduler-internal string. The systemd unit calls `weatherbot --run`; the relocation is purely internal Python packaging. | None — but the editable-install on the host means a deploy needs `systemctl restart` (a Gate-2 milestone obligation, not a Phase-23 task — Phase 28 owns the live-restart UAT). |
| Secrets / env vars | **None.** No secret key or env var name references the scheduler engine, occurrence store, or job store. `OPENWEATHER_API_KEY` / `DISCORD_*` stay inside the injected client/channel, untouched. | None — verified: the engine signatures name no secret. |
| Build artifacts / installed packages | **`yahir_reusable_bot` is an editable install** (`[tool.hatch.build.targets.wheel] packages` already lists it per CONTEXT canonical_refs). Adding the `scheduler/` subpackage + `ports/occurrence.py`/`jobstore.py` is auto-discovered (it is a package directory under the listed root) — **no pyproject change needed** for the wheel target. `[tool.coverage.run] source` lists `weatherbot/scheduler` (Phase-21 21-PATTERNS L364) — the moved engine lives under `yahir_reusable_bot/`, which is NOT in that coverage source list. | **Confirm coverage scope:** decide whether `yahir_reusable_bot/scheduler` and the new ports need adding to `[tool.coverage.run] source` (Phase 22 added `yahir_reusable_bot/*` packages? — VERIFY in Wave 0). Reinstall not required (editable). |

**The canonical question — "after every file is updated, what runtime systems still have the old string cached/stored/registered?":** Nothing. No string is renamed; the only "old vs new" is the *import location* of the engine code, resolved at import time, with app-side shims (the Phase-22 pattern) keeping every existing importer's resolution identical.

## Common Pitfalls

### Pitfall 1: The schedule-plan golden does NOT cover `max_instances` / `misfire_grace_time` / `coalesce`
**What goes wrong:** The Phase-21 schedule golden projects `(job_id, str(job.trigger), next_run_time)`. `str(CronTrigger)` renders only the cron fields — it does **not** include `max_instances`, `misfire_grace_time`, or `coalesce`. So if `register()` accidentally drops `misfire_grace_time=None` (reverting to APScheduler's default grace), the golden stays GREEN while behavior silently changes (a restart could now replay a missed fire through APScheduler instead of through the sent-log/catch-up path).
**Why it happens:** The golden pins the *trigger spec*, not the *job options*.
**How to avoid:** Add a focused characterization assert (not relying on the golden) that reads back each registered job's `misfire_grace_time`, `coalesce`, and `max_instances` from `scheduler.get_jobs()` after `register()` — the existing `tests/test_reliability.py::test_heartbeat_job_registered_with_slots` (21-PATTERNS L184) is the analog. `[VERIFIED: 21-PATTERNS.md golden projection + daemon.py:642-644]`
**Warning signs:** A green schedule golden after touching `add_job` defaults — treat as insufficient evidence; assert the job options directly.

### Pitfall 2: Briefing/forecast sites omit `max_instances` today; baking it in is *probably* but not *trivially* identical
**What goes wrong:** The briefing (daemon.py:620) and forecast (daemon.py:659) `add_job` calls do NOT pass `max_instances`, relying on the default of `1`. The heartbeat (`:1433`) and uvmonitor (`:751`) DO pass `max_instances=1`. Centralizing `max_instances=1` in `register()` is correct *only because the default equals 1*.
**Why it happens:** Inconsistent original call sites.
**How to avoid:** Confirm APScheduler 3.11.2's `add_job` default `max_instances` is `1` (it is, per the BackgroundScheduler defaults) and assert it via the Pitfall-1 read-back test on a briefing job. `[VERIFIED: daemon.py call-site diff]`
**Warning signs:** None visible in goldens — must be asserted explicitly.

### Pitfall 3: `plan_catchup`'s `was_sent` reader rebind must keep the `(loc.id, slot.time, local_date)` arg order
**What goes wrong:** `_run_catchup` passes `lambda name, time, date: was_sent(db_path, name, time, date)` and `plan_catchup` calls it as `was_sent(loc.id, slot.time, local_date)` (catchup.py:175). If the rebind onto `OccurrenceStore.was_fired` reorders or relabels these, the DST/catch-up goldens (25 tests) break. The port's `was_fired(handle, key, occurrence)` must receive the SAME three values in the same roles.
**Why it happens:** The port's neutral `(key, occurrence)` naming invites a re-split.
**How to avoid:** Keep `plan_catchup`'s `was_sent` callable signature `(name, time, date)` exactly; only its *body* may forward through the port. Do not change catchup.py's call shape (D-14: it stays app-side, unchanged except the reader's binding). `[VERIFIED: catchup.py:106-110,175 + daemon.py:1079-1082]`
**Warning signs:** Any diff to `catchup.py` beyond the `was_sent` lambda's target.

### Pitfall 4: The PEP-562 lazy `run_daemon` export + exception-identity pins
**What goes wrong:** `weatherbot/scheduler/__init__.py` lazily exports `run_daemon` (PEP 562) and re-exports `parse_days`/`plan_catchup`/`MissedSlot` to dodge an import cycle (`daemon → ops → config` while `config` is initializing). Adding a `from yahir_reusable_bot.scheduler import SchedulerEngine` to `daemon.py` (a leaf module of the module package) is fine, but importing the *engine* eagerly at `weatherbot/scheduler/__init__.py` top-level could re-introduce a cycle.
**Why it happens:** The scheduler package barrel runs during `weatherbot.config.models`'s `parse_days` import.
**How to avoid:** Import `SchedulerEngine`/the ports inside `daemon.py` (or lazily), not at the `weatherbot/scheduler/__init__.py` top. The module side (`yahir_reusable_bot/scheduler/engine.py`) imports nothing from `weatherbot` (the grimp gate enforces this). `[VERIFIED: weatherbot/scheduler/__init__.py:1-28]`
**Warning signs:** An `ImportError`/partial-init during `pytest` collection, or the isolated-import smoke gate going red.

### Pitfall 5: The litmus gate is a NAME scan — neutral names are mandatory, not cosmetic
**What goes wrong:** `_LITMUS = weather|forecast|location|openweather|\buv\b|briefing` over every `def`/`class`/param/annotation name under `yahir_reusable_bot/`. A port param named `location_name` (as the store function uses) would trip `location`. (Phase 22 hit this exactly — renamed `location_name → target` in `AlertSink`, per STATE.md decision log.)
**Why it happens:** The store's native param is `location_name`; the obvious port param name leaks.
**How to avoid:** Name the `OccurrenceStore`/`JobStore` params neutrally: `handle`, `key`, `occurrence`, `job_id`, `callback`, `trigger`. Run `tests/test_import_hygiene.py::test_litmus_clean` after writing the ports. Note the documented `\buv\b` gap (matches standalone `uv` only) — irrelevant here (no `uv` names in the moving code). `[VERIFIED: test_import_hygiene.py:61 + STATE.md L85]`
**Warning signs:** `test_litmus_clean` red with a `(file, name)` hit.

### Pitfall 6: `OccurrenceStore` structural satisfaction — method vs module-function shape
**What goes wrong:** `AlertSink` declares methods (`def record_alert(self, ...)`), but the store's `record_alert` is a **module-level function** (no `self`). A `@runtime_checkable` Protocol's `isinstance` check only verifies *attribute presence*, not signature — but if the planner wires an *instance* expecting `obj.claim(...)`, a bare module won't satisfy it the way a class instance would. Phase 22 shipped `AlertSink` defined-but-unconsumed precisely to sidestep this.
**Why it happens:** The store exposes free functions; the Protocol implies methods.
**How to avoid:** Either (a) define the Protocol as the contract and keep `fire_slot` calling the bare store functions (the AlertSink precedent — zero behavior change, recommended), or (b) introduce a thin app-side adapter *class* (`_SlotOccurrenceAdapter`) that satisfies the Protocol structurally and forwards to the bare functions. Do NOT subclass the Protocol (D-08). `[VERIFIED: alerts.py method shape vs store.py:251 free-function shape + grep showing AlertSink unconsumed]`
**Warning signs:** A `runtime_checkable` `isinstance(store_module, OccurrenceStore)` that unexpectedly passes/fails — Protocols check duck-typed attributes, so a module with matching function names *can* pass, masking the self-arg mismatch.

## Code Examples

### Splitting `_register_jobs` (enumerate app-side, register engine-side) — D-15
```python
# Source: refactor of weatherbot/scheduler/daemon.py:585-644 [VERIFIED: codebase]
# App-side: the ENUMERATION loop stays here (Phase-24 desired_jobs seed).
def _register_jobs(scheduler, holder, *, db_path, settings, client=None,
                   channel=None, stop_event=None, replace_existing=False):
    engine = SchedulerEngine(scheduler)            # thin wrapper over the app's scheduler
    config = holder.current()
    for location in config.locations:
        for slot in location.schedule:
            if not slot.enabled:
                continue
            hh, mm = slot.parsed_time()
            engine.register(                       # was: scheduler.add_job(...)
                f"{location.name}|{slot.time}|{slot.days}",
                CronTrigger(hour=hh, minute=mm,
                            day_of_week=slot.day_of_week, timezone=location.timezone),
                fire_slot,
                args=[location, slot],
                kwargs={"holder": holder, "db_path": db_path, "settings": settings,
                        "client": client, "channel": channel, "stop_event": stop_event},
                replace_existing=replace_existing,
            )
        # forecast loop: identical shape, _forecast_job_id + fire_forecast_slot
```
The `misfire_grace_time=None`/`coalesce=True`/`max_instances=1` kwargs that were spelled out at each `add_job` site now live once inside `engine.register()` — fewer call-site bytes, identical job options.

### `list_live_ids()` consumed by reconcile (D-04, stays app-side)
```python
# Source: weatherbot/scheduler/daemon.py:804-808 [VERIFIED: codebase]
# The app's reconcile keeps owning the internal-id exclusion convention:
live_ids = {
    jid for jid in engine.list_live_ids()          # was: {j.id for j in scheduler.get_jobs()}
    if jid not in ("__heartbeat__", "__uvmonitor__")
}
```
The engine returns the raw live id set; the `__heartbeat__`/`__uvmonitor__` exclusion is an app-side convention the engine never learns (D-04).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `add_job` defaults copy-pasted at 4 sites in `daemon.py` | Centralized once in `SchedulerEngine.register()` | This phase | Eliminates drift risk; values reaching APScheduler unchanged. |
| Exactly-once inline in `fire_slot` (`claim_slot`/`release_claim` calls) | `OccurrenceStore` Protocol as the type contract; store functions stay the adapter body | This phase | Reusable exactly-once seam; `sent_log` rows byte-identical. |
| No documented job-serialization contract | `JobStore` Protocol docstring encodes the 3 constraints + names the durable boundary | This phase | A future durable store is a drop-in, not a redesign. |

**Deprecated/outdated:** APScheduler 4.x — explicitly out (pyproject pins `<4`); 3.11.2 is the stable line. `[VERIFIED: pyproject.toml:7]`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | APScheduler 3.11.2 `BackgroundScheduler.add_job` default `max_instances` is `1`, so baking `max_instances=1` into `register()` is byte-identical for the briefing/forecast sites that omit it today | Pattern 1 / Pitfall 2 | A briefing job could gain/lose concurrent-instance protection. LOW risk (default is documented `1`), but assert via read-back test (Pitfall 1). |
| A2 | Phase 22 added `yahir_reusable_bot/*` packages to `[tool.coverage.run] source` (or coverage is non-gating per Phase-21 D-08) so the moved engine stays covered | Runtime State Inventory | The engine code could fall out of coverage scope. LOW — coverage is a one-time audit, not a standing gate (21-PATTERNS L375). Verify in Wave 0. |
| A3 | The recommended "option 2" (ship the `OccurrenceStore` Protocol as a contract; keep `fire_slot` calling bare store functions) satisfies D-07's "`fire_slot` rebinds onto it" — reading "rebind" as "bind as the type contract" not "thread every call through an instance" | Pattern 2 refinement | If D-07 mandates a live adapter instance threaded through `fire_slot`, planning must use option 1 (adapter class). MEDIUM — surface to `/gsd-discuss-phase` as the one genuine open sub-decision. |
| A4 | `SchedulerEngine` as a thin registrar (app keeps `start`/`shutdown`) is acceptable under the Discretion clause; the engine need not wrap the `BackgroundScheduler` lifecycle | Pattern 1 | If a later phase wants the engine to own lifecycle, a small surface addition is needed. LOW — Discretion explicitly allows "the engine is a thin registrar". |

## Open Questions (RESOLVED)

1. **Does `fire_slot` thread an `OccurrenceStore` *instance*, or stay on bare store functions with the Protocol as a defined-but-unconsumed contract (the AlertSink precedent)?**
   - What we know: Phase 22 shipped `AlertSink` defined-but-unconsumed (grep-verified zero production references). D-07/D-09 say the lifecycle belongs in the port and `fire_slot` "rebinds onto it."
   - What's unclear: whether "rebind" = "call through a port-typed instance" (option 1, an app-side adapter class) or "the port is the contract, calls stay bare" (option 2).
   - **RESOLVED (2026-06-27, user decision → CONTEXT.md D-06a):** Option 2 — define-only port. `fire_slot` stays on the bare `claim_slot`/`was_sent`/`release_claim` calls UNCHANGED; `OccurrenceStore` ships as the defined-but-unconsumed type contract (AlertSink precedent). Maximally byte-identical `sent_log`. No `_SlotOccurrenceAdapter` is built.

2. **Coverage source scope for the relocated engine (Wave-0 verify).**
   - What we know: 21-PATTERNS lists `weatherbot/scheduler` in `[tool.coverage.run] source`; the engine moves under `yahir_reusable_bot/`.
   - What's unclear: whether Phase 22 already extended the source list to `yahir_reusable_bot/*`.
   - **RESOLVED (2026-06-27, verified):** `pyproject.toml [tool.coverage.run] source` already lists `yahir_reusable_bot` (added Phase 22) → the relocated code is auto-covered, NO pyproject change needed. Non-gating anyway (coverage is not a standing gate per Phase-21 D-08).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| APScheduler | `SchedulerEngine` (wraps `BackgroundScheduler`) | ✓ | 3.11.2 | — |
| grimp | import-hygiene gate (new scheduler edges) | ✓ | >=3.14 | — |
| pytest | gates + goldens | ✓ | installed (740 tests) | — |
| Python typing.Protocol | the two ports | ✓ | 3.12 stdlib | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none. This phase introduces no new external dependency.

## Validation Architecture

> `nyquist_validation` config key not located in a `.planning/config.json` (no such file surfaced); per the agent contract, absent ⇒ treat as enabled. Section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (+ syrupy 5.3.4 goldens, time-machine frozen clock) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/test_import_hygiene.py tests/test_golden_schedule.py -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEAM-02 | `engine.register` produces the byte-identical schedule plan `(job_id, str(trigger), next_run_time)` | golden | `uv run pytest tests/test_golden_schedule.py -q` | ✅ (Phase 21) |
| SEAM-02 | Registered job OPTIONS (`misfire_grace_time=None`, `coalesce=True`, `max_instances=1`) survive the centralization | unit (read-back) | `uv run pytest tests/test_scheduler_engine.py -q` | ❌ Wave 0 — analog: `test_reliability.py::test_heartbeat_job_registered_with_slots` |
| SEAM-02 | Exactly-once `sent_log` rows + claim/release lifecycle byte-identical through the `OccurrenceStore` rebind | golden + unit | `uv run pytest tests/test_golden_db.py tests/test_store.py -q` | ✅ (Phase 21) |
| SEAM-02 | DST / catch-up across reload unchanged (`plan_catchup` `was_sent` reader rebind) | golden | `uv run pytest tests/test_catchup*.py -q` (25 DST/catch-up tests) | ✅ (Phase 21) |
| SEAM-02 | `engine.list_live_ids()` / `engine.remove()` behave as the raw `get_jobs()`/`remove_job` reads | unit | `uv run pytest tests/test_scheduler_engine.py -q` | ❌ Wave 0 |
| SEAM-03 | `JobStore`/`OccurrenceStore` Protocols are `runtime_checkable` and structurally satisfied; no subclassing | unit | `uv run pytest tests/test_ports.py -q` | ❌ Wave 0 — analog: none yet (AlertSink has no dedicated test) |
| SEAM-02/03 (PKG-01) | Module imports zero app code; no weather noun in the new scheduler/ports signatures | gate | `uv run pytest tests/test_import_hygiene.py -q` | ✅ (Phase 22, auto-scales) |
| SEAM-02/03 (BHV-01/02) | Full suite + all goldens green at the phase boundary | suite | `uv run pytest -q` | ✅ |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_import_hygiene.py tests/test_golden_schedule.py tests/test_golden_db.py -x -q`
- **Per wave merge:** `uv run pytest -q` (full suite, 740+ tests, zero-flake)
- **Phase gate:** Full suite green + every Phase-21 golden byte-identical before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_scheduler_engine.py` — covers SEAM-02 register/remove/list_live_ids + the job-OPTIONS read-back (Pitfall 1/2). Analog: `tests/test_reliability.py::test_heartbeat_job_registered_with_slots`.
- [ ] `tests/test_ports.py` — covers SEAM-03 `OccurrenceStore`/`JobStore` `runtime_checkable` + structural-satisfaction asserts (Pitfall 6). No existing analog (AlertSink shipped untested); write from the Protocol contract directly.
- [ ] Wave-0 verify: `[tool.coverage.run] source` includes the relocated module packages (Open Q2).
- [ ] Wave-0 confirm: APScheduler 3.11.2 `add_job` default `max_instances == 1` via a read-back assert on a briefing job (A1 / Pitfall 2).

## Security Domain

> `security_enforcement` config not located (absent ⇒ enabled). This phase is an internal refactor with no new external input surface, network call, auth, or crypto. The relevant standing control is **input-handling / SQL-injection avoidance**, already satisfied and preserved byte-identically.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface in the scheduler engine; the `appid`/`DISCORD_*` secrets stay inside the injected client/channel, never named by the engine (verified: engine signatures name no secret). |
| V3 Session Management | no | N/A (no sessions). |
| V4 Access Control | no | N/A (single-operator personal bot; operator gate is Phase-26/27 surface, untouched here). |
| V5 Input Validation | yes | Config validation stays in `validate_config_and_templates` (app-side, Phase 24). The engine accepts only already-validated `(job_id, trigger, callback)` from `run_daemon`. |
| V6 Cryptography | no | No crypto. |
| V5.3.4 (SQLi) | yes | The `OccurrenceStore` adapter body (`claim_slot`/`release_claim`/`was_sent`) is **parameterized `?`-only, never f-string'd** (store.py:285,311,245 + docstrings cite T-03-01). The extraction must NOT inline-format any key into SQL. |

### Known Threat Patterns for the scheduler-extraction stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `(location_name, send_time, local_date)` keys | Tampering | Keep the existing parameterized binds — the extraction passes the triple through unchanged (D-09); never concatenate into SQL. `[VERIFIED: store.py parameterization]` |
| Secret leakage into logs/job repr | Information disclosure | Engine logging is outcome-only and the engine never names a secret; `args=[location, slot]` carry no credential (pydantic models), `kwargs` client/channel hold secrets internally and are never logged. Preserve the existing outcome-only log discipline (T-04-01). |
| Job callback / args becoming non-picklable (future durable store) | Tampering / DoS | The `JobStore` serialization contract (D-12) forbids closing a live client/socket into `args`; the durable-boundary doc (D-13) relocates handles to a fire-time registry. Designed-now, not a v2.0 attack surface (in-memory store never serializes). |

## Sources

### Primary (HIGH confidence)
- `weatherbot/scheduler/daemon.py` (full read, 1685 lines) — `fire_slot` (L131-370), `_register_jobs` (L585-680), `_desired_job_ids` (L683-707), `_register_uvmonitor_job` (L710-765), `_reconcile_jobs`/`_restore_jobs`/`_do_reload` (L768-1016), `_run_catchup` (L1056-1095), heartbeat registration (L1433-1440), `run_daemon` (L1344-1685).
- `weatherbot/weather/store.py` (L90-314) — `sent_log` schema (L108-115), `was_sent` (L229), `claim_slot` (L251, the `INSERT OR IGNORE … rowcount==1` primitive), `release_claim` (L291).
- `weatherbot/scheduler/catchup.py` (full) — `plan_catchup` (L106), the DST gap/fold round-trip (L161-168), `was_sent(loc.id, slot.time, local_date)` call (L175).
- `weatherbot/scheduler/__init__.py` (full) — PEP-562 lazy `run_daemon` export.
- `yahir_reusable_bot/ports/alerts.py` + `ports/__init__.py` + `channels/base.py` + `channels/__init__.py` + `reliability/__init__.py` — the Ports & Adapters + barrel + shim recipe to clone.
- `tests/test_import_hygiene.py` (full) — the three standing gates (grimp graph, isolated-import smoke, AST litmus) + their self-proofs; `_LITMUS` pattern (L61); auto-scaling `_scan_app_leaks` (L71).
- `.planning/phases/21-characterization-golden-test-harness/21-PATTERNS.md` — the schedule-plan golden serializer (`schedule_plan_golden`, `str(job.trigger)` primary byte), the register-then-read drive seam, coverage `[tool.coverage.run]` block.
- `tests/test_golden_schedule.py` (header + config) — the byte-identical oracle this phase re-runs.
- `grep` verifications: `AlertSink` zero production references; `apscheduler==3.11.2`; `grimp>=3.14`; 740 tests collected; Phase-22 reliability/channel shim pattern.

### Secondary (MEDIUM confidence)
- `[CITED]` https://apscheduler.readthedocs.io/en/3.x/userguide.html — serializing job stores require "the target callable must be globally accessible" + "any arguments to the callable must be serializable"; "only MemoryJobStore doesn't serialize jobs." Grounds the D-12 serialization contract.
- `.planning/STATE.md` decision log — Phase-22 `AlertSink` param rename (`location_name → target`), reliability/channel shim "identical objects" pattern.

### Tertiary (LOW confidence)
- None. All claims are codebase-verified or doc-cited.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; every version verified against the live env + pyproject.
- Architecture: HIGH — patterns are direct clones of the shipped Phase-22 `AlertSink`/`Channel` precedent and the existing 4 `add_job` sites, read line-by-line.
- Pitfalls: HIGH — each pitfall is grounded in a specific verified line (golden projection scope, call-site `max_instances` asymmetry, catchup arg order, PEP-562 lazy export, litmus name scan, Protocol method-vs-function shape).
- Open sub-decision (OccurrenceStore threading depth): MEDIUM — flagged for discuss-phase confirmation.

**Research date:** 2026-06-27
**Valid until:** 2026-07-27 (stable brownfield stack; frozen pins). Re-verify only if APScheduler/grimp pins change or Phase 22's shim/coverage layout is revised.
