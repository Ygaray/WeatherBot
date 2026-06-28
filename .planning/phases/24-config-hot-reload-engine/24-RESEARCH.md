# Phase 24: Config Hot-Reload Engine - Research

**Researched:** 2026-06-27
**Domain:** Generic config hot-reload (immutable holder + validate→swap→reconcile engine) extraction into `yahir_reusable_bot`, over an app-defined schema via injected hooks
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

All four crux decisions are LOCKED in 24-CONTEXT.md. This research surfaces the implementation-level HOW; it does NOT re-open them. The planner MUST NOT "correct" the two [DEVIATION] picks back to the roadmap text.

- **D-01 [DEVIATION]:** Injected job-deriver returns `set[str]` (stable job ids), and a SECOND injected `register_jobs(cfg)` registrar runs the ADD phase. Engine owns the id-keyed diff (`desired - live` = add, `desired & live` = unchanged, `live - desired` = remove), drives `SchedulerEngine.remove` for the REMOVE phase, and delegates ADD to the injected registrar. NOT `set[JobSpec]` (re-opens Phase-23 D-10; highest golden risk). WeatherBot's `_register_jobs` is kept **verbatim** and injected, not moved.
- **D-01a:** `register_jobs(cfg)` registers the **full desired set** as an idempotent swap (`add_job(replace_existing=True)` for every enabled slot), NOT just the `added` delta — so an unchanged id rides the holder swap and a new id is created in the same pass. Document in the hook contract.
- **D-02 [DEVIATION]:** `ConfigHolder[T]` uses an UNBOUND `TypeVar("T")`; the module ships NO `BaseConfig` base class. "BaseConfig" is the conceptual role of `T`. The holder NEVER calls pydantic.
- **D-03 [roadmap-locked]:** Validation routes ONLY through the app's injected `validate(path) → T` callable (`validate_config_and_templates`). The module never validates the config itself.
- **D-03a:** Holder concurrency contract preserved byte-for-byte: `current()` lock-free `LOAD_ATTR`, `replace()` locked `STORE_ATTR`. Only annotations generalize. `test_concurrent_read_swap_safe` stays the oracle.
- **D-04:** Module owns the reusable trigger machinery: `reload(path)`, a `request_reload()`/`service_pending()` flag pair, and an OPTIONAL `start_watching(dirs, filter)` spawning the watchfiles observer thread.
- **D-05 [load-bearing invariant]:** Reload work runs ONLY on the host's main poll thread — never re-entrantly in a signal handler or on the observer thread. `request_reload()` is flag-set-only (safe from SIGHUP handler AND watch thread); `service_pending()` runs the reload synchronously on the caller's thread. App KEEPS the SIGHUP install, the main poll loop, and the byte-identical startup ordering. The `reload_requested` Event ownership moves into the engine; a `stop`/join contract lets the app's `finally` join the engine-owned watch thread.
- **D-06:** `engine.check(path)` = thin validate-only (calls injected `validate`, no swap/reconcile/scheduler touch) returning structured pass/fail. The `weatherbot check` CLI stays a ~3-line app-side wrapper.
- **D-07:** `ReloadEngine(holder, scheduler_engine, *, validate, desired_jobs, register_jobs, on_applied=None, on_rejected=None)` exposing `reload(path)`/`check(path)`. Constructor injection + thin verbs (Phase-23 `SchedulerEngine` precedent).
- **D-08:** Engine owns the rollback CONTROL FLOW; reconcile + restore STEPS are injected callables invoked opaquely. Keep-old byte-identical: a validator raise leaves holder+jobs untouched and re-raises; a reconcile throw rolls both back and re-raises.
- **D-09:** Weather side-effects ride symmetric injected hooks at today's exact points — `on_rejected(exc)` fires immediately before the validator re-raise (CFG-07 post-then-raise timing); `on_applied(summary)` fires at committed-success alongside CR-01 `cache.invalidate()`. Each hook best-effort (failure logged + swallowed, never masks the engine's result).

### Claude's Discretion

- Exact module sub-layout (`config/` package inside `yahir_reusable_bot/` holding `ConfigHolder[T]` + `ReloadEngine` vs flatter), guided by the existing `channels/`/`reliability/`/`scheduler/`/`ports/` shapes.
- Precise method names beyond `reload`/`check`/`request_reload`/`service_pending`/`start_watching` (e.g. whether `stop`/join is a method or context-manager), and exact `on_applied`/`on_rejected`/`register_jobs` parameter signatures — minimal and weather-clean.
- How the watch-filter's host knowledge (config basename + referenced template paths) is injected into `start_watching` (filter callable vs spec), and how `watch_dirs_ref` re-derive moves into the engine.
- The `grimp`-graph assertion form for the new `config` reload edges, the isolated-import smoke extension, the litmus-grep target set.
- Whether `ConfigHolder` and `ReloadEngine` are separate classes (recommended) or the engine holds the holder internally — shaped by how `fire_slot`/`_uv_monitor_tick` read `holder.current()` at fire time.

### Deferred Ideas (OUT OF SCOPE)

- `desired_jobs→set[JobSpec]` with engine-owned registration (and thin-passthrough `JobSpec`) — deferred per D-01 / Phase-23 D-10; revisit at the physical split / first real second consumer.
- A literal module `BaseConfig` base class (Option B for the holder) — kept on the table; verified harmless; not adopted now.
- Engine owning the full trigger lifecycle (`start()/stop()` incl. SIGHUP install) — rejected (main-thread / process-global-signal reasons, D-05).
- Lifecycle READY-gate / systemd `Type=notify` / heartbeat-as-health — **Phase 25** (SEAM-05).
- Single composition-root consolidation of all wiring — **Phase 25** (APP-01/APP-02). Here `run_daemon` keeps its existing call sites, only gaining the `ReloadEngine` construction.
- Durable / dynamic `JobStore` impl — JOBSTORE-V2-01, deferred.
- Full docstring/comment scrub of weather nouns from the module — cosmetic; defer to Phase 28 / DOCS-01. The signatures-only litmus governs now.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEAM-04 | The config hot-reload engine (immutable `ConfigHolder[T]` snapshots, validate→atomic-swap→job-reconcile, file-watch + SIGHUP triggers, `check-config` dry-run, keep-old-on-failure) operates over an app-defined config schema via injected `validate` + `desired_jobs` hooks — knowing none of the app's field names. | This research maps the exact lift of `holder.py` → `ConfigHolder[T]`, `_do_reload` → `ReloadEngine.reload()`, `_reconcile_jobs`/`_restore_jobs` → engine diff + injected steps, `_run_watch_observer`/`_make_watch_filter`/`watch_dirs_ref` → `start_watching`, `reload_requested` Event → `request_reload()`/`service_pending()`, `run_self_check`→`check()`. Empirically confirms the pydantic-v2 generic-validation pitfall (D-03). Extends the litmus + import-isolation gates to the config seam. |
| BHV-01 / BHV-02 (cross-cutting) | Suite + Phase-21 goldens stay byte-identical. | The "byte-identical move sequence" section names what moves verbatim, what stays app-side, what gets injected — keyed to the schedule-plan golden, the `+a -r ~c =u` reconcile-diff golden, keep-old-rollback, exactly-once-across-reload, and the `sent_log` DB-row golden. |
| PKG-01 / APP-02 (cross-cutting) | Module imports zero app code; no weather noun in the module config-seam public surface. | The import-hygiene / litmus extension section gives the exact `test_import_hygiene.py` mechanics (already package-agnostic via prefix scan — no per-module edit needed) and the clean-signature checklist for `ConfigHolder[T]`/`ReloadEngine`. |
</phase_requirements>

## Summary

This phase is a **relocation along seams that are already drawn**, not a redesign. Two pieces move into the module; the rest stays app-side and arrives through injected callables.

1. **`ConfigHolder` → `ConfigHolder[T]`** (`weatherbot/config/holder.py`, 67 lines). The holder is already a pure storage cell that NEVER calls pydantic — the only change is replacing the concrete `Config` annotation with an unbound `TypeVar("T")` (D-02). The GIL-atomicity contract (`current()` = lock-free `LOAD_ATTR`, `replace()` = locked `STORE_ATTR`) is preserved verbatim (`test_concurrent_read_swap_safe` is the oracle). [VERIFIED: codebase read holder.py L38-67]

2. **`_do_reload` → `ReloadEngine.reload()`** (`daemon.py` L879-1027). The two-phase validate-or-keep-old / swap / reconcile / all-or-nothing rollback skeleton moves into the engine; the steps that need weather-runtime handles (validate, desired-id derivation, job registration, restore, side-effects) are injected. The live `_reconcile_jobs` (L775-845) **already** computes its diff from `set[str]` and delegates the ADD phase to a separate `_register_jobs(..., replace_existing=True)` call — so D-01's `set[str]` + `register_jobs` split is a **near-verbatim lift along the existing seam line**, not new factoring. [VERIFIED: codebase read daemon.py L775-845, L879-1027]

The single highest-risk technical claim — **D-03's pydantic-v2 generic-validation pitfall** — is empirically confirmed below on pydantic 2.13.4: validating on a bare/base model either silently returns `{}` (default `extra="ignore"`) or raises (`extra="forbid"`, WeatherBot's posture), and a `Generic[T]` holder cannot self-parametrize at construction (`__orig_class__` is unset inside `__init__`, `get_args()` is empty). The module therefore must NEVER call pydantic on the config; validation routes ONLY through the app's injected concrete `validate(path) → T`.

**Primary recommendation:** Create a `yahir_reusable_bot/config/` package (mirroring `scheduler/`) holding `ConfigHolder[T]` (generalized holder) and `ReloadEngine` (the orchestration). Keep `validate_config_and_templates`, `_register_jobs`, `_desired_job_ids`, `_restore_jobs`'s reconcile call, the SIGHUP install, the main poll loop, and the CFG-07/CR-01 side-effects **app-side**, wired into the engine at `run_daemon` as injected callables. Drive every behavior change through the existing Phase-21 goldens — any non-empty snapshot diff is a failure to investigate, never rubber-stamped.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Immutable config storage cell (`current()`/`replace()`) | Module (`ConfigHolder[T]`) | — | Pure mechanism, app-field-agnostic; the holder already calls no pydantic |
| Reload control flow (validate→swap→reconcile→rollback) | Module (`ReloadEngine`) | — | The reusable orchestration skeleton; the reuse payoff |
| Id-keyed reconcile diff (`add`/`unchanged`/`remove`) | Module (`ReloadEngine`) | App (`desired_jobs` supplies the desired id set) | Diff is generic over `set[str]`; what an id *means* is app policy |
| Config schema validation | App (`validate_config_and_templates`) | — | Concrete pydantic `Config`; module never validates (D-03 pitfall) |
| Desired-id derivation | App (`_desired_job_ids` → injected `desired_jobs`) | — | Reads `Location`/`schedule`/`forecast` field names — app-coupled |
| Job construction (cron triggers + callbacks + args) | App (`_register_jobs` → injected `register_jobs`) | Module (`SchedulerEngine.register` bakes invariant opts) | Builds weather callbacks/args; the seam is the `set[str]` boundary, not the JobSpec |
| File-watch observer thread | Module (`ReloadEngine.start_watching`) | App (supplies dirs + filter) | ~100 LOC of pitfall-dense plumbing; the reuse payoff |
| Watch filter (which basenames trigger) | App (`_make_watch_filter`) | Module (invokes it opaquely) | Knows config basename + referenced template names — app policy |
| SIGHUP install + handler | App (`run_daemon`) | Module (handler calls `request_reload()`) | A library must never seize the process-global SIGHUP handler (D-05) |
| Main poll loop / flag servicing | App (`run_daemon`) | Module (`service_pending()` body) | Reload must run on the host's main thread only (D-05) |
| Restart-boundary policy (`[bot]`/`[reload] watch`/`[uv].interval`) | App | — | "Which keys are restart-only" stays app-side; module never enshrines a key list |
| In-channel reject/applied posts (CFG-07) | App (closures → `on_rejected`/`on_applied`) | Module (invokes hooks at exact timing) | Weather side-effect; module surface names no weather noun |
| ForecastCache invalidation (CR-01) | App (closure → `on_applied`) | Module (invokes hook) | Weather side-effect at committed-success point |
| `check-config` dry-run | Module (`engine.check(path)`) | App (CLI wrapper maps to exit code) | Validate-only de-dups the validator path; CLI parsing stays app-side |

## Standard Stack

This is a **pure extraction** — no new runtime dependencies. The runtime stack is unchanged and already declared in `pyproject.toml`. Versions below were verified against the installed `.venv` and PyPI.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | 2.13.4 (installed) | App-side config validation — the injected `validate` returns a concrete `Config` | Already the project's config layer; the module must NEVER call it (D-03). [VERIFIED: `.venv` `pydantic.VERSION` == 2.13.4] |
| apscheduler | >=3.11.2,<4 | `BackgroundScheduler` + `add_job(replace_existing=True)` + `get_jobs()` — the reconcile add/remove primitives, driven via `SchedulerEngine` | The reconcile diff already routes through Phase-23's `SchedulerEngine.register`/`remove`/`list_live_ids`. [VERIFIED: codebase read engine.py + pyproject.toml] |
| watchfiles | >=1.2.0 | The `watch()` observer thread the engine owns via `start_watching` | Already the file-watch impl (`_run_watch_observer`); the directory-watch + filter + debounce semantics move verbatim. [VERIFIED: codebase read daemon.py L1266-1328 + pyproject.toml] |
| typing (stdlib) | 3.12 | `TypeVar`, `Generic` for `ConfigHolder[T]` | The generic holder; unbound `TypeVar("T")` per D-02. [VERIFIED: codebase read] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| structlog | >=26.1.0 | The engine's outcome-only logging (`reload applied`/`reload rejected`/`reconcile failed`) | Moves verbatim with `_do_reload`; the log calls (`_log`/`_stdlog`) need a home — keep them weather-noun-free (prose is litmus-immune, but the engine should log generic "reload" events). [VERIFIED: codebase read daemon.py L924-989] |
| grimp | >=3.14 (dev) | Import-hygiene gate — no module→app edge across the new `config` reload edges | The standing PKG-01 gate; already package-agnostic (prefix scan auto-scales). [VERIFIED: codebase read test_import_hygiene.py L165-179] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `desired_jobs → set[str]` + `register_jobs` | `desired_jobs → set[JobSpec]` (engine owns registration) | LOCKED REJECTED (D-01): re-opens Phase-23 D-10, forces re-deriving `CronTrigger(timezone=…)` + `args=[location,slot]` inside a spec object — the single most likely place to shift `next_run_time` and break the schedule-plan golden. Defer until a real second consumer. |
| Unbound `TypeVar("T")` (no module base) | Bound `TypeVar` / empty module `BaseConfig` the app subclasses | LOCKED REJECTED (D-02): forces inheritance coupling on every consuming bot; the bound's mere existence tempts the fatal `BaseConfig.model_validate()` call. Verified harmless but not adopted. |
| Symmetric `on_applied`/`on_rejected` hooks | Returned `ReloadResult` | LOCKED REJECTED (D-09): a result object can't honor "post-then-raise" on the reject path without either swallowing the re-raise (risking keep-old goldens) or losing the rejection the app needs to post. |

**Installation:** None — no new dependencies. The two new module files live under `yahir_reusable_bot/config/`, already covered by `[tool.hatch.build.targets.wheel].packages = ["weatherbot", "yahir_reusable_bot"]` and `[tool.coverage.run].source` (which lists `yahir_reusable_bot`). [VERIFIED: codebase read pyproject.toml L26-54]

## Package Legitimacy Audit

> No external packages are installed in this phase — it is a pure in-place code relocation within the existing repo. All libraries touched (pydantic, apscheduler, watchfiles, structlog, grimp) are already declared in `pyproject.toml` and pinned. **Package Legitimacy Gate: N/A (no new installs).**

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────── run_daemon (app composition root) ───────────────────────┐
                          │                                                                                  │
  config.toml edit ──┐    │  SIGHUP ──► _install_reload_signal._handle_hup ──► engine.request_reload()       │
                     │    │                                                          │ (flag-set ONLY)       │
  watchfiles thread ─┼────┼─► [engine-owned] observer ──► request_reload() ─────────┤                       │
   (start_watching)  │    │      (filter: app basename allow-list)                   ▼                       │
                     │    │                                              reload_requested Event (engine)      │
  weatherbot reload ─┘    │                                                          │                       │
   (SIGHUP to PID)        │   MAIN POLL LOOP:  while not stop.wait(1.0):             │                       │
                          │       if engine.service_pending():  ◄────────────────────┘ (services on MAIN thr)│
                          │            └─► ReloadEngine.reload(path)                                          │
                          └──────────────────────────────────┼───────────────────────────────────────────────┘
                                                              │
        ┌─────────────────────────────────── ReloadEngine.reload(path) ──────────────────────────────────────┐
        │  PHASE 1 validate-or-keep-old:  new_cfg = validate(path)   [injected app validator → concrete T]     │
        │     on raise: on_rejected(exc)  [injected: posts "⛔ rejected"] → RE-RAISE (holder+jobs untouched)   │
        │                                                                                                       │
        │  PHASE 2 atomic swap + reconcile:                                                                     │
        │     old_cfg = holder.current();  holder.replace(new_cfg)                                              │
        │     desired = desired_jobs(holder.current())  [injected → set[str]]                                   │
        │     live    = scheduler_engine.list_live_ids() − {app-excluded ids: __heartbeat__/__uvmonitor__}      │
        │              (exclusion lives INSIDE the injected desired_jobs/register_jobs — engine never learns it) │
        │     register_jobs(holder.current())  [injected: ADD full desired set, replace_existing=True]          │
        │     for id in (live − desired): scheduler_engine.remove(id)   [engine owns REMOVE]                    │
        │     on throw → holder.replace(old_cfg) + restore(old_cfg)  [injected] → RE-RAISE (all-or-nothing)     │
        │                                                                                                       │
        │     on success: on_applied(summary)  [injected: posts "✅ +a -r ~c =u" + cache.invalidate()]          │
        │                 + (app) re-derive watch_dirs_ref                                                       │
        └───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

The diagram traces the primary use case (an operator edits `config.toml` → a reload is requested by any of three triggers → serviced on the main thread → validate/swap/reconcile with all-or-nothing rollback). The **load-bearing invariant** is the single funnel: all three triggers only *set a flag*; the actual reload runs exactly once per tick on the main poll thread.

### Recommended Project Structure

```
yahir_reusable_bot/
├── config/                  # NEW — mirrors scheduler/ shape
│   ├── __init__.py          # barrel: exports ConfigHolder, ReloadEngine
│   ├── holder.py            # ConfigHolder[T] (generalized from weatherbot/config/holder.py)
│   └── reload.py            # ReloadEngine (generalized from daemon._do_reload + reconcile + watch)
├── scheduler/
│   └── engine.py            # SchedulerEngine (the collaborator the reconcile drives — unchanged)
├── ports/                   # AlertSink / OccurrenceStore / JobStore (unchanged)
├── channels/                # Channel (unchanged)
└── reliability/             # retry primitives (unchanged)

weatherbot/                  # STAYS app-side
├── config/
│   ├── holder.py            # → re-export shim of yahir_reusable_bot.config.ConfigHolder (Pattern: 22-02 shim)
│   ├── loader.py            # validate_config_and_templates — UNCHANGED, injected as `validate`
│   └── models.py            # Config/Location/UvConfig — UNCHANGED, app-side
└── scheduler/
    └── daemon.py            # _register_jobs / _desired_job_ids / _make_watch_filter / SIGHUP /
                             #   main poll loop — STAY; run_daemon now CONSTRUCTS + drives ReloadEngine
```

**Discretion call (recommended):** `ConfigHolder` and `ReloadEngine` are **separate classes**, with the engine holding a *reference* to the holder (constructor-injected, D-07). Rationale: `fire_slot`/`_uv_monitor_tick`/`_announce_schedule`/`_run_catchup`/`DaemonState` all read `holder.current()` directly at fire time (daemon.py L619, L749, L1041, L1088, L1601) — the holder must be independently constructable and shareable, not buried inside the engine. [VERIFIED: codebase read daemon.py — 6 direct `holder.current()` readers outside the reload path]

### Pattern 1: Generalize the storage cell, not its mechanism (D-02/D-03a)

**What:** Replace the concrete `Config` annotation with an unbound `TypeVar`; change nothing else.
**When to use:** The `ConfigHolder` lift.
**Example:**
```python
# Source: generalized from weatherbot/config/holder.py L38-67 (mechanism byte-identical)
from __future__ import annotations
import threading
from typing import Generic, TypeVar

T = TypeVar("T")  # UNBOUND (D-02) — no module BaseConfig; any bot passes its own frozen config type

class ConfigHolder(Generic[T]):
    """Owns one live config reference with a lock-free read / locked swap.

    current() is lock-free (one atomic LOAD_ATTR under the GIL); replace() is a
    locked STORE_ATTR. Never validates, copies, clones, or records. Holds the
    app's frozen config snapshot ONLY — secrets never enter (the .env stays behind
    the restart boundary).
    """
    def __init__(self, config: T) -> None:
        self._config = config
        self._lock = threading.Lock()

    def current(self) -> T:
        return self._config            # lock-free LOAD_ATTR (atomic under the GIL)

    def replace(self, new_config: T) -> None:
        with self._lock:               # locked STORE_ATTR — serializes writers
            self._config = new_config
```
The mechanism is **identical**; only the two `Config` annotations become `T`. `test_concurrent_read_swap_safe` must stay green unchanged. Keep `weatherbot/config/holder.py` as a re-export shim (`from yahir_reusable_bot.config import ConfigHolder`) so the ~6 app-side importers + `test_config_holder.py` resolve to the identical class object (the 22-02 shim pattern — STATE.md L83-84).

### Pattern 2: Engine owns control flow; steps are injected opaquely (D-07/D-08)

**What:** The `ReloadEngine` owns the verbatim two-phase skeleton and the id-keyed diff; the validator, desired-id deriver, registrar, restore, and side-effects are constructor-injected callables it invokes without inspecting.
**When to use:** The `_do_reload` lift.
**Example:**
```python
# Source: generalized from daemon._do_reload (L879-1027) + _reconcile_jobs (L775-845)
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")

class ReloadEngine(Generic[T]):
    def __init__(
        self,
        holder: ConfigHolder[T],
        scheduler_engine: Any,      # the Phase-23 SchedulerEngine (remove + list_live_ids)
        *,
        validate: Callable[[str | Path], T],          # app: validate_config_and_templates
        desired_jobs: Callable[[T], set[str]],         # app: _desired_job_ids over current cfg
        register_jobs: Callable[[T], None],            # app: _register_jobs(replace_existing=True)
        restore: Callable[[T], None],                  # app: _restore_jobs(old_cfg) (D-08)
        on_applied: Callable[[str], None] | None = None,
        on_rejected: Callable[[Exception], None] | None = None,
    ) -> None:
        ...

    def check(self, path: str | Path) -> T:            # D-06: validate-only, no swap/reconcile
        return self._validate(path)

    def reload(self, path: str | Path) -> None:
        # PHASE 1 — validate-or-keep-old
        try:
            new_cfg = self._validate(path)
        except Exception as exc:
            self._best_effort(self._on_rejected, exc)   # post BEFORE re-raise (D-09 timing)
            raise                                       # holder + jobs untouched (keep-old)
        # PHASE 2 — atomic swap + diff-reconcile, all-or-nothing rollback
        old_cfg = self._holder.current()
        self._holder.replace(new_cfg)
        try:
            summary = self._reconcile()                # diff on set[str]; ADD via register_jobs; REMOVE via engine
        except Exception:
            self._holder.replace(old_cfg)
            self._best_effort_restore(old_cfg)         # best-effort; never masks the real cause
            raise
        self._best_effort(self._on_applied, summary)   # post "✅ summary" + cache.invalidate (D-09)
```
The reconcile body keys entirely on `set[str]`:
```python
def _reconcile(self) -> str:
    desired = self._desired_jobs(self._holder.current())          # injected → set[str]
    live = self._scheduler_engine.list_live_ids()                 # engine read
    # NOTE: __heartbeat__/__uvmonitor__ exclusion lives INSIDE the injected
    # desired_jobs/register_jobs (an app id convention) — the engine never names them.
    added = len(desired - live)
    unchanged = len(desired & live)
    changed = 0  # content edits ride the holder swap (kept for the +a -r ~c =u contract)
    self._register_jobs(self._holder.current())                  # injected ADD (replace_existing=True)
    removed = 0
    for job_id in live - desired:
        self._scheduler_engine.remove(job_id)                    # engine owns REMOVE
        removed += 1
    return f"+{added} -{removed} ~{changed} ={unchanged}"
```

> **Critical exclusion subtlety:** today `_reconcile_jobs` computes `live_ids` by *excluding* `__heartbeat__`/`__uvmonitor__` from `engine.list_live_ids()` (daemon.py L814-818). For the module's `live` set to match `desired` cleanly, that exclusion must move into the **app-side `desired_jobs` boundary**, not the engine. Two equivalent options for the planner: (a) the engine's `live` is the full `list_live_ids()` and the injected `desired_jobs` is responsible for the app never listing the internal ids (so they fall into `live − desired` = REMOVE — WRONG, would delete them); OR (b) the app injects an `excluded_ids: frozenset[str]` (or an `is_managed(id)->bool` predicate) that the engine subtracts from `live` before diffing. **Recommend (b):** a small injected `excluded_ids` frozenset keeps the engine generic (it never *names* heartbeat/uvmonitor) while preserving the exact L814-818 behavior. This is the one spot where a naive lift would silently start removing the heartbeat/uvmonitor jobs on every reload — a Phase-21 reconcile-diff golden break (`-2` extra removes). [VERIFIED: codebase read daemon.py L806-845]

### Pattern 3: Triggers set a flag; the engine owns the flag + the watch thread (D-04/D-05)

**What:** `request_reload()` is flag-set-only (safe from the SIGHUP handler AND the observer thread); `service_pending()` checks-and-clears the flag and, if set, runs `reload()` synchronously on the caller's (main) thread. `start_watching(dirs_ref, filter)` spawns the engine-owned observer; a `stop()`/join contract lets the app's `finally` tear it down.
**When to use:** The `reload_requested` Event + `_run_watch_observer` + SIGHUP-handler integration.
**Example:**
```python
# Source: generalized from daemon.py — _install_reload_signal (L1330-1351),
#   _run_watch_observer (L1266-1328), main poll loop (L1625-1654)
class ReloadEngine(Generic[T]):
    # ... __init__ also creates: self._reload_requested = threading.Event()
    #     and self._watch_thread = None, self._watch_dirs_ref = None

    def request_reload(self) -> None:
        """FLAG-SET ONLY. Safe to call from the SIGHUP handler AND the observer
        thread — never does reload work here (Pitfall #6/#9)."""
        self._reload_requested.set()

    def service_pending(self, path: str | Path) -> bool:
        """Run a pending reload on the CALLER's thread (the app's main poll loop).
        Returns True if a reload was serviced. The app calls this each ~1s tick."""
        if not self._reload_requested.is_set():
            return False
        self._reload_requested.clear()
        self.reload(path)   # the app's try/except still swallows so a bad reload never crashes
        return True

    def start_watching(self, watch_dirs_ref, *, watch_filter, stop) -> None:
        """Spawn the single long-lived observer thread (engine-owned). The thread
        calls self.request_reload() on each settled non-empty change-set."""
        ...   # body = _run_watch_observer verbatim, calling self.request_reload()

    def stop(self) -> None:
        """Join the observer thread (the app's finally calls this)."""
        ...
```
**App side (`run_daemon`) keeps:** the SIGHUP install (its `_handle_hup` now calls `engine.request_reload()` instead of `.set()`ing its own Event), the main poll loop (now calling `engine.service_pending(config_path)` instead of inlining `_do_reload`), the `stop` Event, and the byte-identical startup ordering (register → announce → catch-up → `scheduler.start()`). The app's existing `finally` calls `engine.stop()` to join the observer. [VERIFIED: codebase read daemon.py L1485-1654, L1671-1679]

### Anti-Patterns to Avoid
- **Letting the module call pydantic on the config.** Validating on a bare/base model drops fields or raises (see Pitfall 1). The module holds an opaque `T`; only the injected app validator ever touches pydantic. (D-03)
- **Moving `_register_jobs` into the module.** It builds `CronTrigger(timezone=…)` + `args=[location, slot]` weather callbacks — irreducibly app-coupled. Inject it (adapt-don't-rewrite, the rule that kept `fire_slot` put in 22/23). (D-01)
- **A library seizing SIGHUP or servicing its own flag on a side thread.** Hostile to any host and breaks the main-thread invariant. The app keeps signal install + poll loop. (D-05)
- **Spawning a second watchfiles observer per event or per re-derive.** One long-lived `watch()` generator for the process; a watch-set re-derive BREAKS and re-enters the SAME generator (Pitfall #11a, daemon.py L1294-1325). (D-04)
- **Naming `__heartbeat__`/`__uvmonitor__` in the engine.** The exclusion is an app id convention (inject `excluded_ids`); the module must never learn these ids (litmus + reuse). (D-04)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Concurrent config read/swap | A lock around every reader | The existing lock-free `LOAD_ATTR` / locked `STORE_ATTR` cell (move verbatim) | A reader lock would serialize every `holder.current()` at fire time; the GIL already makes the single attr load atomic. Proven by `test_concurrent_read_swap_safe`. |
| File-watch debounce / atomic-save survival | A `stat()` mtime poll loop | watchfiles `watch()` with directory-watch + `watch_filter` (move verbatim) | A temp-then-rename save swaps the inode; a file-pinned watch goes deaf. Directory watch + basename filter + debounce handles all editor-save patterns (`test_editor_save_patterns_one_reload`). |
| Reload-on-edit reentrancy safety | Reloading inside the signal handler / observer thread | The flag-set + main-thread-service split (move verbatim) | Reload work in an async-signal context or on the observer thread is the classic deadlock/torn-state bug (Pitfall #6/#9). |
| Job diff / reconcile | Clear-and-rebuild the whole job table | The id-keyed `set[str]` diff (`add`/`unchanged`/`remove`) | A wholesale clear shifts `next_run_time` on every unchanged job (breaks the schedule-plan golden) and loses the "unchanged rides the holder swap" property. |
| Config schema validation | A module-side `TypeAdapter(T)` / `Generic[T]` self-parametrization | The injected app validator returning a concrete `Config` | TypeVar erasure makes self-parametrization impossible; base validation drops fields. Empirically confirmed below. |

**Key insight:** Every piece this phase touches already exists and is golden-pinned. The work is *drawing the module boundary in the right place* and injecting the app specifics — not writing new reload logic. The riskiest "hand-roll" temptation is making the module validate the config itself; D-03 forbids it precisely because pydantic-v2's generic/inheritance semantics make it unsafe.

## Runtime State Inventory

> This is a **code-only relocation** (in-place module boundary, no physical repo split, no data migration, no service reconfiguration). It changes import paths and class generics, not stored data, live service config, OS registrations, or secrets.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the holder holds an in-memory frozen `Config`; the `sent_log` / health DB rows are written by `weatherbot/weather/store.py` (app-side, untouched). No DB key, collection, or id embeds `ConfigHolder`/`ReloadEngine`. | None — verified by reading holder.py (no persistence) + the reconcile path (no DB writes; `db_path` is threaded through to `fire_slot` only). |
| Live service config | None — the live `weatherbot` systemd unit on host `yahir-mint` imports `weatherbot.scheduler.daemon`; this phase keeps `run_daemon`'s public call sites intact (it only gains the `ReloadEngine` construction). No `.service` file, n8n workflow, or external service config references the moved classes. | None this phase — the live-host restart UAT is Phase 28 (PKG-02). An **editable install** means import-path changes take effect on the next `systemctl restart` (MEMORY: weatherbot-live-systemd-service). |
| OS-registered state | None — no Task Scheduler / pm2 / launchd entry names `ConfigHolder` or `ReloadEngine`. The SIGHUP handler + PID file (`PID_FILE`) stay app-side and unchanged. | None — verified by reading the SIGHUP install (L1330-1351) + PID write (L1497); both stay in `run_daemon`. |
| Secrets/env vars | None — the holder NEVER sees secrets (`.env`/`Settings` stay behind the restart boundary, holder.py L26 / Pitfall #12). The watch filter explicitly rejects `.env` edits (zero reloads, L1257-1261). No secret key name changes. | None — verified by reading holder.py + `_watch_filter` (`.env` basename never in the allow-list). |
| Build artifacts / installed packages | The package is installed **editable** (`weatherbot` + `yahir_reusable_bot` already in `[tool.hatch...packages]`). Adding `yahir_reusable_bot/config/` needs no `pyproject.toml` packages change (hatch globs subpackages); `[tool.coverage.run].source` already lists `yahir_reusable_bot`. A stale `.pyc` for the moved `weatherbot/config/holder.py` (now a shim) is harmless (pytest reimports). | Confirm no `egg-info`/build cache pins the old holder path; an editable reinstall is NOT required for a pure subpackage add (hatch editable installs resolve subpackages at import time). |

**The canonical question:** *After every file is updated, what runtime systems still have the old string cached, stored, or registered?* — **Answer: none.** This is an in-place relocation; the only "old string" is the import path `weatherbot.config.holder.ConfigHolder`, which is preserved as a re-export shim so every existing importer + test resolves to the identical class object.

## Common Pitfalls

### Pitfall 1: The pydantic-v2 generic-validation trap (the phase's defining technical risk — D-03)

**What goes wrong:** If the module tries to validate the config itself — on a base model or via a `Generic[T]` self-parametrization — it either silently drops every subclass field or raises.

**Empirically confirmed on pydantic 2.13.4** (this session, `.venv/bin/python`):
```python
# Case A — base with DEFAULT extra="ignore": subclass fields SILENTLY DROPPED
class BaseIgnore(BaseModel): pass
class AppIgnore(BaseIgnore):
    locations: list[str]
BaseIgnore.model_validate({"locations": ["Home"]}).model_dump()
#  → {}        ← 'locations' silently gone; hasattr(..., "locations") is False

# Case B — base with extra="forbid" (WeatherBot's actual posture): RAISES
class BaseForbid(BaseModel):
    model_config = ConfigDict(extra="forbid")
class AppForbid(BaseForbid):
    locations: list[str]
BaseForbid.model_validate({"locations": ["Home"]})
#  → raises ValidationError (extra field 'locations' not permitted)

# Case C — Generic[T] cannot self-parametrize at construction: __orig_class__ unset in __init__
class Holder(Generic[T]):
    def __init__(self, raw):
        get_args(getattr(self, "__orig_class__", type(self)))
        #  → ()   ← empty inside __init__; __orig_class__ is only set AFTER __init__ returns,
        #            so the holder cannot reconstruct the concrete type to build a TypeAdapter
```
[VERIFIED: ran all three cases on pydantic 2.13.4 — Case A returns `{}`, Case B raises `ValidationError`, Case C `get_args()` returns `()` inside `__init__`]

**Why it happens:** (1) pydantic builds the validator from the class it's *called on*, so a base class validates only the base's fields. (2) `TypeVar` is erased at runtime — `Holder[AppConfig]()` reports empty `get_args(type(h))`, and `__orig_class__` is not yet bound during `__init__`, so a generic holder has no runtime handle on its concrete type parameter.

**How to avoid:** The module NEVER calls pydantic. Validation routes ONLY through the injected `validate(path) → T`, which IS `weatherbot.config.loader.validate_config_and_templates` — it validates the *concrete* `Config` (all `locations`/`[uv]`/`Location` subfields, `extra="forbid"`, every field validator intact) and returns the full object. The injected validator is typed `-> T` but returns the concrete `Config` (covariant; `isinstance` holds). [VERIFIED: codebase read loader.py L99-168 — `Config.model_validate(raw)` on the concrete class]

**Warning signs:** Any `import pydantic`, `TypeAdapter`, `model_validate`, or `BaseConfig` in a `yahir_reusable_bot/config/*` file. The grimp gate won't catch pydantic (it's third-party), so the planner must add an explicit "no pydantic import in the config module" assertion OR rely on code review — recommend the assertion.

### Pitfall 2: The `__heartbeat__`/`__uvmonitor__` exclusion silently moves into the engine

**What goes wrong:** A naive lift makes the engine's `live` set the full `list_live_ids()`. The internal ids (`__heartbeat__`, `__uvmonitor__`) then land in `live − desired` and get **removed on every reload** — a `-2` extra in the `+a -r ~c =u` summary, breaking the Phase-21 reconcile-diff golden and tearing down the heartbeat + UV monitor live.
**Why it happens:** Today the exclusion is a hardcoded tuple inside `_reconcile_jobs` (L814-818) that names the two ids. That naming cannot move into a weather-noun-free module.
**How to avoid:** Inject the exclusion. Recommend an `excluded_ids: frozenset[str]` (or `is_managed(id)->bool`) passed to the engine; the engine subtracts it from `live` before diffing. The engine never *names* the ids; the app supplies `frozenset({"__heartbeat__", "__uvmonitor__"})`. [VERIFIED: codebase read daemon.py L806-845]
**Warning signs:** The reconcile-diff golden shows extra removes; the heartbeat/UV-monitor jobs disappear after a SIGHUP in an integration test.

### Pitfall 3: `_restore_jobs` re-uses `_reconcile_jobs` against a transient holder — the engine must too (D-08)

**What goes wrong:** The rollback `restore(old_cfg)` must rebuild the OLD job set *and remove any half-applied new id*. If the planner injects a `restore` that only re-adds old jobs (without the remove phase), a reconcile-throw mid-add leaves a stray new id.
**Why it happens:** `_restore_jobs` (L848-876) wraps `old_cfg` in a **transient `ConfigHolder`** and calls `_reconcile_jobs` against it — so the restore is itself a full diff-reconcile (re-add old via `replace_existing=True`, remove any half-applied new id). That whole-reconcile-against-old semantics must be preserved.
**How to avoid:** The injected `restore(old_cfg)` should remain `_restore_jobs` verbatim (it constructs a transient `ConfigHolder(old_cfg)` and reconciles). Keep it app-side and inject it; do NOT try to make the engine's own `_reconcile` serve double duty against `old_cfg` (the engine's holder is already rolled back to `old_cfg` by that point, but the restore must reconcile *jobs*, and `_restore_jobs` already encapsulates that). [VERIFIED: codebase read daemon.py L848-876, L957-978]
**Warning signs:** `test`-level keep-old-rollback / exactly-once-across-reload goldens drift; a stray job survives a rolled-back reload.

### Pitfall 4: The watch re-derive cell vs the engine-owned thread (D-04)

**What goes wrong:** On a successful reload, the watch set is re-derived (a template moved to a new dir becomes watched) by mutating `watch_dirs_ref[0]` (L1025-1026). The single observer thread detects the changed cell on its next timeout tick, breaks its `watch()` generator, and re-enters with the new dirs. If the engine owns the thread but the app owns the re-derive (or vice versa) without sharing the `watch_dirs_ref` box, the re-derive never reaches the observer.
**Why it happens:** The re-derive (`_derive_watch_dirs`, app-coupled — it knows `config.template` + `TEMPLATES_DIR`) and the observer (generic) are split across the boundary.
**How to avoid:** The engine owns the **thread** and the `watch_dirs_ref` box; the app owns the **re-derive function** (`_derive_watch_dirs`) and writes into `engine`'s shared box after a successful swap (via `on_applied`, or a small `engine.update_watch_dirs(new_dirs)` method the `on_applied` closure calls). Discretion: pass the re-derive as an injected callable to `start_watching`, OR have `on_applied` call back into the engine to update the box. Recommend the latter (keeps `start_watching`'s signature minimal). [VERIFIED: codebase read daemon.py L1017-1026, L1278-1325, L1512-1535]
**Warning signs:** `test_watch_set_rederived_on_reload` (D-04) fails; a moved-template dir is not watched after a reload.

### Pitfall 5: The `on_applied`/`on_rejected` timing must match byte-for-byte (D-09)

**What goes wrong:** CFG-07 posts the "⛔ rejected" message **before** the validator re-raise (L931-938) and the "✅ +a -r ~c =u" message **after** the committed swap (L997-1001), with CR-01 `cache.invalidate()` right after (L1011-1015). If the engine fires `on_rejected` after the re-raise (impossible) or `on_applied` before the reconcile commits, the in-channel post order / cache-invalidation timing shifts.
**Why it happens:** The post-then-raise ordering is load-bearing and the daemon's outer `except`-swallow (L1649) depends on the original exception still propagating.
**How to avoid:** `on_rejected(exc)` fires inside the `except` block immediately before `raise` (so the post lands, then the original error propagates). `on_applied(summary)` fires only in the committed-success branch, after the reconcile returns and before/at the watch re-derive. Both hooks are best-effort (wrapped in try/except, logged + swallowed, never mask the engine's result). [VERIFIED: codebase read daemon.py L924-1015]
**Warning signs:** A reject test sees the "✅" post or no "⛔" post; the cache is invalidated on a rejected reload; the keep-old goldens drift.

## Code Examples

### Wiring the engine at `run_daemon` (the composition root for this phase)
```python
# Source: NEW wiring in run_daemon, replacing the inlined _do_reload call (daemon.py L1636-1648).
# Phase-25 consolidates this; here run_daemon keeps its existing call sites and ADDS the construction.
from yahir_reusable_bot.config import ConfigHolder, ReloadEngine
from yahir_reusable_bot.scheduler import SchedulerEngine

holder = ConfigHolder(config)                       # (was ConfigHolder(config); now generic)
sched_engine = SchedulerEngine(scheduler)

reload_engine = ReloadEngine(
    holder,
    sched_engine,
    validate=lambda p: validate_config_and_templates(p),          # app validator → concrete Config
    desired_jobs=lambda cfg: _desired_job_ids(ConfigHolder(cfg)),  # app id-deriver → set[str]
    register_jobs=lambda cfg: _register_jobs(                      # app ADD phase (replace_existing=True)
        scheduler, ConfigHolder(cfg), db_path=db_path, settings=settings,
        client=client, channel=channel, stop_event=stop, replace_existing=True,
    ),
    restore=lambda old: _restore_jobs(                             # app rollback rebuild (D-08)
        scheduler, old, db_path=db_path, settings=settings,
        client=client, channel=channel, stop_event=stop,
    ),
    on_rejected=lambda exc: channel.send(f"⛔ config reload rejected: {exc}") if channel else None,
    on_applied=lambda summary: (
        channel.send(f"✅ config reloaded: {summary}") if channel else None,
        cache.invalidate() if cache else None,
    ),
    # excluded_ids=frozenset({"__heartbeat__", "__uvmonitor__"}),  # see Pitfall 2
)

# SIGHUP handler now flag-sets through the engine:
def _handle_hup(signum, frame):
    reload_engine.request_reload()
signal.signal(signal.SIGHUP, _handle_hup)

# Main poll loop services on the MAIN thread (try/except still swallows — CFG-04 keep-old end-to-end):
while not stop.wait(timeout=1.0):
    if stop.is_set():
        break
    try:
        reload_engine.service_pending(config_path)
    except Exception:
        _log.exception("reload failed; live config left intact")
```
> The `desired_jobs`/`register_jobs`/`restore` closures wrap a transient `ConfigHolder(cfg)` because the existing app helpers take a `holder`, not a bare `cfg`. This is the thinnest adapter that preserves byte-identical behavior. The planner may instead refactor those helpers to take `cfg` directly (smaller closures) — but that is a larger app-side change; the wrapping closures are the lower-golden-risk path. [VERIFIED: signatures read daemon.py L689, L600, L848]

### Extending the import-hygiene gate (already package-agnostic)
```python
# Source: tests/test_import_hygiene.py — NO new gate code needed for the prefix scan.
# The grimp gate (_scan_app_leaks) auto-scales: it flags ANY yahir_reusable_bot.* → weatherbot.* edge,
# so yahir_reusable_bot/config/reload.py and holder.py are covered the instant they exist (L80-85).
# The litmus (_public_names + _LITMUS) walks _MODULE_ROOT.rglob("*.py") — config/*.py auto-included (L343-348).
# The isolated-import smoke walks pkgutil.walk_packages — config subpackage auto-included (L255-257).
#
# REQUIRED NEW assertion (Pitfall 1): no pydantic in the config module surface.
def test_config_module_never_imports_pydantic():
    import grimp
    graph = grimp.build_graph("yahir_reusable_bot", cache_dir=None)
    for mod in graph.modules:
        if mod.startswith("yahir_reusable_bot.config"):
            imported = graph.find_modules_directly_imported_by(mod)
            assert not any(t == "pydantic" or t.startswith("pydantic.") for t in imported), \
                f"{mod} must NOT import pydantic — validation is injected (D-03)"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ConfigHolder` typed to concrete `Config` | `ConfigHolder[T]` unbound generic | This phase (D-02) | Any bot passes its own frozen config type with zero inheritance |
| `_do_reload` inlined in `daemon.py`, weather-coupled | `ReloadEngine` in module, injected hooks | This phase (D-07/D-08) | A reminder bot reuses the whole reload orchestration |
| Reconcile names `__heartbeat__`/`__uvmonitor__` inline | Exclusion injected (`excluded_ids`) | This phase (Pitfall 2) | Module never learns app job-id conventions |
| `set[JobSpec]` (roadmap text) | `set[str]` + injected `register_jobs` (D-01 deviation) | This phase | Lift along the existing seam line; lowest golden risk |

**Deprecated/outdated:**
- None. No library is deprecated; this is a relocation of current, working code.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Adding `yahir_reusable_bot/config/` needs NO `pyproject.toml` `packages` change (hatch globs subpackages) and NO editable reinstall for tests | Runtime State Inventory / Stack | LOW — if hatch does not glob, add `yahir_reusable_bot/config` is implicit under the package root; worst case is one `pyproject.toml` line. Verify with a clean `uv sync` + import smoke in Wave 0. |
| A2 | Wrapping app helpers in transient-`ConfigHolder` closures (rather than refactoring them to take `cfg`) is the lower-golden-risk wiring path | Code Examples | LOW — both paths are behavior-identical; the closure path touches fewer lines. The planner may choose either; goldens arbitrate. |
| A3 | `excluded_ids: frozenset[str]` (vs an `is_managed` predicate) is the cleaner injection for the heartbeat/uvmonitor exclusion | Pitfall 2 | LOW — both preserve L814-818 behavior; this is a signature-shape preference, weather-clean either way. |
| A4 | The `on_applied` closure (not a new `engine.update_watch_dirs` method) is the cleaner home for the watch re-derive callback | Pitfall 4 | LOW — discretion item per CONTEXT; both keep `start_watching` minimal. Goldens (`test_watch_set_rederived_on_reload`) arbitrate. |

**Note:** All four assumptions are LOW-risk wiring-shape preferences within Claude's-Discretion areas — the locked decisions (D-01..D-09) are fully specified and not assumed. The byte-identical Phase-21 goldens arbitrate any wiring-shape choice.

## Open Questions

1. **Does `desired_jobs`/`register_jobs`/`restore` take a `cfg` or a `holder`?**
   - What we know: the existing helpers (`_desired_job_ids`, `_register_jobs`, `_restore_jobs`) all take a `holder` and call `holder.current()` once. The engine has the `holder` and could pass it, OR pass `cfg = holder.current()`.
   - What's unclear: whether to refactor the helpers to take `cfg` (cleaner injected signatures) or wrap in transient-`ConfigHolder` closures (fewer line changes).
   - Recommendation: Wrap in closures (A2) for minimal golden risk; defer a helper-signature refactor to Phase 25's composition-root consolidation if desired.

2. **Is the watch re-derive callback routed through `on_applied` or a dedicated engine method?**
   - What we know: today the re-derive mutates `watch_dirs_ref[0]` only on a successful reload with a real `config_path` (L1025-1026), and only the app knows how to derive dirs (`_derive_watch_dirs`).
   - What's unclear: discretion item (CONTEXT L185-186).
   - Recommendation: have the engine own the `watch_dirs_ref` box and expose a tiny `update_watch_dirs(new_dirs)` the `on_applied` closure calls — or fold it into `on_applied`. Either keeps the engine weather-clean.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | runtime | ✓ | 3.12 (`.venv`) | — |
| pydantic | app-side validator (injected) | ✓ | 2.13.4 | — |
| apscheduler | reconcile add/remove via SchedulerEngine | ✓ | >=3.11.2,<4 (pinned) | — |
| watchfiles | observer thread | ✓ | >=1.2.0 (pinned) | — |
| grimp | import-hygiene gate (dev) | ✓ | >=3.14 (dev group) | — |
| pytest / syrupy / time-machine | suite + goldens | ✓ | pinned (dev group) | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — pure extraction, no new deps.

## Validation Architecture

> `workflow.nyquist_validation` is enabled (no `.planning/config.json` override found disabling it). Section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=9.0.3 + pytest-cov + syrupy (goldens) + time-machine (frozen clock) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=`tests`, pythonpath=`.`) |
| Quick run command | `.venv/bin/python -m pytest tests/test_config_holder.py tests/test_reload.py tests/test_filewatch.py tests/test_import_hygiene.py -x` |
| Full suite command | `.venv/bin/python -m pytest` (the ~732-test byte-identical oracle) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEAM-04 | `ConfigHolder[T]` lock-free read / locked swap preserved | unit | `pytest tests/test_config_holder.py::test_concurrent_read_swap_safe -x` | ✅ (move-path oracle) |
| SEAM-04 | Reload validate→swap→reconcile + keep-old + rollback | unit | `pytest tests/test_reload.py -x` | ✅ |
| SEAM-04 | exactly-once-across-reload (name/tz change, no re-fire) | unit | `pytest tests/test_reload.py::test_already_sent_slot_not_refired_after_tz_name_change -x` | ✅ |
| SEAM-04 | send_time change = new slot fires today if ahead | unit | `pytest tests/test_reload.py::test_send_time_change_is_new_slot_fires_today_if_ahead -x` | ✅ |
| SEAM-04 | reconcile diff `+a -r ~c =u` golden (incl. heartbeat/uvmonitor untouched) | golden | `pytest tests/test_filewatch.py::test_identical_save_zero_job_changes -x` + the Phase-21 reconcile-diff golden | ✅ |
| SEAM-04 | file-watch save→one-reload, .env→zero, keep-old-through-watch, re-derive | unit | `pytest tests/test_filewatch.py -x` | ✅ |
| SEAM-04 | `check-config` validate-only dry-run | unit/CLI | the existing `weatherbot check` / `--check-config` test (CFG-08) | ✅ (app-side CLI test) |
| PKG-01 | module imports zero app code (incl. new config edges) | gate | `pytest tests/test_import_hygiene.py::test_module_imports_zero_app_code -x` | ✅ (auto-scales) |
| APP-02 | no weather noun in module config-seam public surface | gate | `pytest tests/test_import_hygiene.py::test_litmus_clean -x` | ✅ (auto-scales) |
| D-03 | config module never imports pydantic | gate | NEW `test_config_module_never_imports_pydantic` | ❌ Wave 0 |
| BHV-01 | full suite byte-identical | suite | `.venv/bin/python -m pytest` | ✅ |

### Sampling Rate
- **Per task commit:** the Quick run command (holder + reload + filewatch + import-hygiene).
- **Per wave merge:** full suite + the Phase-21 golden snapshots (`pytest --snapshot-warn-unused` or the project's golden invocation) — any non-empty diff is investigated, never `--snapshot-update`'d blindly.
- **Phase gate:** Full suite green + zero golden diff + the new pydantic-isolation gate green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_import_hygiene.py::test_config_module_never_imports_pydantic` — NEW assertion pinning D-03 (no pydantic in `yahir_reusable_bot.config.*`).
- [ ] Optional: a module-level `tests/test_reload_engine.py` exercising `ReloadEngine` *directly* (construct with stub `validate`/`desired_jobs`/`register_jobs`/`restore`; assert reload/check/rollback/keep-old + flag-pair `request_reload`/`service_pending` servicing) so the engine is provable WITHOUT standing up the whole daemon — mirrors `test_scheduler_engine.py`'s direct-engine pattern.
- [ ] Optional: a module-level `tests/test_config_holder_generic.py` (or extend `test_config_holder.py`) proving `ConfigHolder[T]` holds a NON-weather type (e.g. a plain dataclass) — proves the generic genuinely carries any `T`, the reminder-bot litmus in test form.
- No framework install needed — pytest + syrupy + time-machine + grimp are all present.

## Security Domain

> `security_enforcement` is not explicitly `false` in config (absent = enabled). This is a pure code-relocation phase with no new attack surface, but two existing invariants must be preserved.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth in this seam (the operator gate is the Discord adapter, Phase 27) |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | Config validation routes through the injected concrete `validate_config_and_templates` (pydantic `extra="forbid"` + field validators + template token allow-list). The module never weakens this — it never validates. (D-03) |
| V6 Cryptography | no | No crypto; the holder never sees secrets (`.env` stays behind the restart boundary) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leak via config hot-reload (`.env` edit triggers a reload that exposes secrets) | Information Disclosure | The watch filter rejects `.env` (zero reloads, daemon.py L1257-1261); the holder holds a `Config` ONLY, never `Settings`/secrets (holder.py L26). Both invariants move unchanged; `test_env_save_never_reloads` pins it. [VERIFIED: codebase read] |
| Malicious/malformed config crashing the always-on daemon | Denial of Service | Keep-old all-or-nothing rollback (D-08): a validator raise leaves holder+jobs untouched and re-raises; the daemon's outer `except` swallows so a bad edit + SIGHUP never takes the process down (CFG-04 end-to-end). Pinned by `test_invalid_save_keeps_old_config`. [VERIFIED: codebase read daemon.py L1649-1654] |
| Job-id injection via a `|` in a location name (craft a colliding id) | Tampering | App-side `_no_pipe_in_identity` validator (models.py L209-224) — stays in the concrete `Config`, unaffected by the extraction. [VERIFIED: codebase read models.py] |

## Sources

### Primary (HIGH confidence)
- Codebase: `weatherbot/config/holder.py` (L1-67) — the storage cell to generalize; lock-free/locked contract; no pydantic, no secrets.
- Codebase: `weatherbot/config/loader.py` (L99-168) — `validate_config_and_templates` returns the concrete `Config`; the injected validator.
- Codebase: `weatherbot/config/models.py` (L37-518) — `Config`/`Location`/`UvConfig`/`Schedule`/`ForecastSchedule`, all `frozen=True, extra="forbid"`; `_no_pipe_in_identity`.
- Codebase: `weatherbot/scheduler/daemon.py` — `_register_jobs` (L600-686), `_desired_job_ids` (L689-713), `_reconcile_jobs` (L775-845), `_restore_jobs` (L848-876), `_do_reload` (L879-1027), `_derive_watch_dirs`/`_make_watch_filter`/`_run_watch_observer` (L1214-1328), `_install_reload_signal` (L1330-1351), `run_daemon` wiring + main poll loop (L1354-1688).
- Codebase: `yahir_reusable_bot/scheduler/engine.py` (L1-79) — the `SchedulerEngine` precedent + the `register`/`remove`/`list_live_ids` surface the reconcile drives.
- Codebase: `yahir_reusable_bot/ports/jobstore.py` + `ports/__init__.py` — the module sub-layout + barrel pattern to mirror.
- Codebase: `tests/test_import_hygiene.py` (L1-372) — the standing grimp/isolated-import/litmus gates (already package-agnostic).
- Codebase: `pyproject.toml` (L1-68) — hatch packages, coverage source, dev deps (grimp/watchfiles already present).
- Empirical: pydantic 2.13.4 in `.venv` — confirmed all three D-03 failure modes (base-validate drops fields / forbid-base raises / `Generic[T]` cannot self-parametrize at `__init__`).

### Secondary (MEDIUM confidence)
- `24-CONTEXT.md` — the four LOCKED decisions (D-01..D-09), source line-range map, discretion + deferred items.
- `21-CONTEXT.md` / `21-PATTERNS.md` (referenced) — the golden oracle this phase must keep byte-identical.
- `23-CONTEXT.md` (referenced) — D-10 rejection of a JobSpec registry (basis for D-01), the `SchedulerEngine` surface, D-16 hand-off of the reconcile helpers.

### Tertiary (LOW confidence)
- None — every claim is verified against the live codebase or empirically confirmed in this session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — pure extraction; all deps pinned + installed, versions verified against `.venv`.
- Architecture (move sequence + injection shapes): HIGH — every source surface read with exact line ranges; the seams (set[str] diff, lock-free holder) are pre-drawn.
- Pydantic pitfall (D-03): HIGH — all three failure modes empirically reproduced on the exact installed pydantic 2.13.4.
- Pitfalls: HIGH — each traced to a specific golden test + source line range.

**Research date:** 2026-06-27
**Valid until:** 2026-07-27 (stable — brownfield extraction; the only external moving part is pydantic, pinned at 2.13.4)
</content>
</invoke>
