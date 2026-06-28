# Phase 24: Config Hot-Reload Engine - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-27
**Phase:** 24-config-hot-reload-engine
**Areas discussed:** Reconcile generalization model, ConfigHolder[T] + validation pitfall, Trigger ownership (watch + SIGHUP + check-config), Engine surface + hook injection + rollback home
**Mode:** advisor (4 parallel research agents, full_maturity calibration tier)

The user selected all 4 gray areas, requested clarification (found the technical language hard to
follow), then explicitly delegated the final calls — "you do not understand most of the language
here, you chose for me" — anchoring on the milestone north star: **a reusable bot module shipped as
its own repo and imported across several future projects.** Claude chose each option on that lens;
all four picks also minimize byte-identical risk against the Phase-21 goldens.

---

## Reconcile generalization model

| Option | Description | Selected |
|--------|-------------|----------|
| B: ids + injected registrar | `desired_jobs(cfg)→set[str]`; engine owns diff/remove/rollback; app keeps `_register_jobs` verbatim as an injected `register_jobs(cfg)` registrar. Lowest golden risk, honors Phase-23 D-10. Amends roadmap `set[JobSpec]` wording. | ✓ |
| A: `desired_jobs→set[JobSpec]` | Engine registers generically via SchedulerEngine. Matches roadmap text but re-opens D-10 and is the highest byte-identical risk. | |
| D: thin passthrough JobSpec | JobSpec carries a pre-built trigger + bound callable; defer until a real 2nd consumer needs the module to own registration. | |

**User's choice:** Delegated to Claude → **B** (hardened with the "registrar registers the full
desired set as an idempotent swap" contract, D-01a).
**Notes:** DEVIATION from roadmap `set[JobSpec]`. Justified: the live `_reconcile_jobs` already
splits diff (`set[str]`) from job-building (`_register_jobs`), so B is a near-verbatim lift; `set[JobSpec]`
adds no reusable logic to the module (the app constructs id+trigger+callback+args either way) while
maximizing the chance of silently shifting `next_run_time`. Serves reuse: module owns the reusable
orchestration, each bot plugs in its own job type.

---

## ConfigHolder[T] + validation pitfall

| Option | Description | Selected |
|--------|-------------|----------|
| A: unbound TypeVar + injected validator | `TypeVar('T')` unbound; holder never calls pydantic; `validate(path)→T` injected (returns the app's concrete Config). Zero pitfall surface, full static typing, no base-class coupling. | ✓ |
| B: TypeVar bound to module BaseConfig | Module ships an empty frozen BaseConfig the app subclasses. Matches roadmap wording but the bound tempts the fatal `BaseConfig.model_validate()` field-drop. | |
| D: non-generic, store object | Simplest, fully app-agnostic, but discards the static typing the current code already provides. | |

**User's choice:** Delegated to Claude → **A** (with D-03 locking the pydantic pitfall: validation
routes only through the app's concrete injected validator).
**Notes:** DEVIATION from roadmap "holding an app-defined frozen BaseConfig" — under A there is no
literal module BaseConfig base class; "BaseConfig" is the conceptual role of `T`. Justified for
cross-repo reuse: forcing every future bot to inherit a module base class is needless coupling; an
unbound `T` lets any bot pass its own config type with zero inheritance. Option B verified harmless
and kept on the table if matching the wording later outweighs the looser coupling.

---

## Trigger ownership (watch + SIGHUP + check-config)

| Option | Description | Selected |
|--------|-------------|----------|
| B: engine owns reload()+flag+watch; app keeps SIGHUP+loop | Engine owns `reload()` + `request_reload()`/`service_pending()` + optional `start_watching`. App keeps SIGHUP install + main poll loop. Moves the reusable watch plumbing into the module; main-thread invariant becomes a contract. | ✓ |
| A: engine owns only reload(); triggers app-side | Safest/smallest, mirrors SchedulerEngine. Leaves watch/SIGHUP plumbing duplicated per host. | |
| C: engine owns full lifecycle start()/stop() | Disqualified: library seizing process-global SIGHUP + servicing on an internal thread breaks the reload-on-main-thread invariant. | |

**User's choice:** Delegated to Claude → **B**. `check-config` = thin `engine.check(path)` validate-only;
CLI stays a ~3-line app-side wrapper (D-06).
**Notes:** Reuse strengthens B — the module exists precisely so each new bot doesn't re-hand-write the
~100 LOC of pitfall-dense watch/reload plumbing. A is the safe fallback if the planner wants Phase 24
minimal and defers observer-thread extraction. C rejected. Hard invariant preserved: reload runs only
on the main poll thread (D-05).

---

## Engine surface + hook injection + rollback home

| Option | Description | Selected |
|--------|-------------|----------|
| A: constructor-injected + on_applied/on_rejected hooks | `ReloadEngine(holder, scheduler_engine, validate, desired_jobs, register_jobs, on_applied, on_rejected)` + thin `reload(path)`/`check(path)`. Engine owns the try/replace/except/rollback skeleton; reconcile+restore+side-effects injected. Matches SchedulerEngine precedent. | ✓ |
| D: hybrid — on_applied hook, reject re-raises | Applied side-effects ride `on_applied`; reject path keeps existing log+post+raise. Less uniform but leaves the load-bearing reject re-raise identical. | |
| C: structured ReloadResult, no hooks | Most litmus-defensible but breaks the post-then-raise reject timing the goldens pin. | |
| B: per-call validate/desired_jobs | Closest to today's free-function shape but re-threads deps every reload and diverges from constructor-injection precedent. | |

**User's choice:** Delegated to Claude → **A** ("engine owns rollback" = owns the control-flow
skeleton; reconcile+restore steps are injected callables; weather side-effects ride symmetric
`on_applied`/`on_rejected` hooks at today's exact timing, D-08/D-09).
**Notes:** D is the acceptable simpler fallback if symmetric hooks feel over-built.

---

## Claude's Discretion

- Module sub-layout / file naming for the reload seam; exact method names beyond the core verbs;
  precise hook signatures; how the watch-filter host knowledge is injected; `watch_dirs_ref` re-derive
  relocation; the grimp/litmus assertion forms; whether `ConfigHolder` and `ReloadEngine` are separate
  classes (recommended). See CONTEXT.md § Claude's Discretion.

## Deferred Ideas

- `desired_jobs→set[JobSpec]` engine-owned registration (revisit at first real second consumer).
- A literal module `BaseConfig` base class (kept on the table).
- Engine owning the full trigger lifecycle incl. SIGHUP install (rejected).
- Lifecycle READY-gate / systemd `Type=notify` / heartbeat-as-health → Phase 25.
- Single composition-root wiring consolidation → Phase 25.
- Durable/dynamic `JobStore` impl → JOBSTORE-V2-01.
- Full weather-noun docstring scrub → Phase 28 / DOCS-01.
