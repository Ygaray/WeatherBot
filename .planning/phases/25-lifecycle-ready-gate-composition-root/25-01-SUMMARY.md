---
phase: 25-lifecycle-ready-gate-composition-root
plan: 01
subsystem: infra
tags: [lifecycle, systemd, sd_notify, ready-gate, dependency-injection, dataclass, structlog, pidfile, proc-guard]

# Dependency graph
requires:
  - phase: 24-config-hot-reload-engine
    provides: ReloadEngine constructor-injection + symmetric best-effort hook (_best_effort_hook) recipe cloned by ReadyGate
  - phase: 23-scheduler-engine-occurrencestore-jobstore-seam
    provides: SchedulerEngine non-owning registrar (the __heartbeat__ re-registration seam ReadyGate option-d defers to the app)
provides:
  - "yahir_reusable_bot/lifecycle/ module package (SEAM-05) — litmus-clean reusable process-lifecycle layer"
  - "SystemdNotifier moved verbatim into the module (pure-stdlib READY=1 wire)"
  - "HealthResult DTO + neutral Severity(IntEnum) field the gate branches log-level on"
  - "LifecycleIdentity (5 independent fields) + marker-parameterized is_running_process /proc guard + write_pid_atomic/read_pid"
  - "ReadyGate engine — interruptible re-probe loop + READY=1 emit + symmetric best-effort on_online/on_fail hooks"
affects: [25-02-composition-root-wiring, 26-command-registry, 27-panelkit-relocation, reminder-bot-reuse]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Constructor-injection + opaque passthrough + symmetric best-effort hooks (ReadyGate clones ReloadEngine)"
    - "Neutral severity field (IntEnum) for log-level branching — never compare an opaque reason string"
    - "Interruptible re-probe via stop.wait(interval), never time.sleep (Pitfall 2)"
    - "Immutable identity struct with independent fields; module owns zero durable I/O"
    - "structlog.testing.capture_logs for config-independent log-level assertions"

key-files:
  created:
    - yahir_reusable_bot/lifecycle/__init__.py
    - yahir_reusable_bot/lifecycle/sdnotify.py
    - yahir_reusable_bot/lifecycle/health.py
    - yahir_reusable_bot/lifecycle/identity.py
    - yahir_reusable_bot/lifecycle/ready_gate.py
    - tests/test_lifecycle_module.py
  modified: []

key-decisions:
  - "Severity carried as a module-owned IntEnum (WARNING=10, CRITICAL=30) the gate branches on via `>= Severity.CRITICAL` — discrete neutral field, not app-side log pre-selection"
  - "Heartbeat tick: Option (d) — ReadyGate holds NO scheduler handle; the app re-registers __heartbeat__ via SchedulerEngine.register(...) at the composition root (keeps run_daemon byte-identical in 25-02)"
  - "Generalized proc guard named is_running_process(pid, *, proc_marker) with internal _argv_matches_marker (no weather noun); decode marker for argv0 basename match, bytes match for the -m form"

patterns-established:
  - "lifecycle barrel mirrors scheduler/config barrels (docstring + explicit re-export + __all__)"
  - "Online emit split: module owns notifier.ready() + a noun-free 'bot online' log; durable health row/tick/ping ride on_online"

requirements-completed: [SEAM-05]

# Metrics
duration: 10min
completed: 2026-06-28
status: complete
---

# Phase 25 Plan 01: Lifecycle READY-Gate Module Surface Summary

**Created the litmus-clean `yahir_reusable_bot/lifecycle/` package — SystemdNotifier (verbatim move), a HealthResult DTO with a neutral Severity rung, a 5-field LifecycleIdentity + marker-parameterized /proc guard, and a ReadyGate engine that drives an injected health-check through an interruptible re-probe loop and emits READY=1 — with zero app behavior change.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-28T06:42:29Z
- **Completed:** 2026-06-28T06:52:49Z
- **Tasks:** 2
- **Files modified:** 6 created

## Accomplishments
- Moved `SystemdNotifier` verbatim into `lifecycle/sdnotify.py` (pure-stdlib, already weather-clean; the app re-export shim lands in 25-02).
- Defined `HealthResult(ok, reason, detail, severity)` with a module-owned neutral `Severity` IntEnum (WARNING/CRITICAL rungs); dropped the weather-reason constants entirely.
- Defined `LifecycleIdentity` with the five independent identity facts (name, pid_file, runtime_dir, console_name, proc_marker) per D-03; generalized the pid helpers (no module default constant) and the `/proc` staleness guard to `is_running_process(pid, *, proc_marker)`, renaming the internal helper to `_argv_matches_marker` so the module names no weather noun.
- Built `ReadyGate` cloning the ReloadEngine recipe: constructor-injection, `_best_effort_hook` copied verbatim, an interruptible `stop.wait(interval)` re-probe loop (never `time.sleep`), severity-branched startup logging on the neutral field, and an online transition that owns only `notifier.ready()` + a noun-free `"bot online"` log (durable health row/tick/ping ride the injected `on_online` hook).
- Wrote `tests/test_lifecycle_module.py` covering all six gate behaviors; full suite 768 passed, litmus 9 passed, Phase-21 goldens 25/25 passed.

## Task Commits

1. **Task 1: Move SystemdNotifier + create HealthResult + LifecycleIdentity/identity helpers** - `5ff73e3` (feat)
2. **Task 2 (RED): failing ReadyGate tests** - `3592666` (test)
3. **Task 2 (GREEN): ReadyGate engine + barrel export + test isolation fix** - `4873c14` (feat)

_TDD task 2 = RED test commit then GREEN implementation commit._

## Files Created/Modified
- `yahir_reusable_bot/lifecycle/sdnotify.py` - `SystemdNotifier` moved verbatim (READY=1 / WATCHDOG=1 sd_notify wire).
- `yahir_reusable_bot/lifecycle/health.py` - `HealthResult` DTO + neutral `Severity` IntEnum.
- `yahir_reusable_bot/lifecycle/identity.py` - `LifecycleIdentity` + `write_pid_atomic`/`read_pid` + `is_running_process` marker-parameterized guard.
- `yahir_reusable_bot/lifecycle/ready_gate.py` - `ReadyGate` engine (re-probe loop + READY emit + symmetric best-effort hooks).
- `yahir_reusable_bot/lifecycle/__init__.py` - barrel exporting the public lifecycle surface.
- `tests/test_lifecycle_module.py` - six-behavior unit suite for `ReadyGate`.

## Decisions Made
- **Severity representation: a module-owned `IntEnum`** (`WARNING=10`, `CRITICAL=30`). The gate branches via `result.severity >= Severity.CRITICAL`, an honest neutral field rather than app-side log pre-selection — it keeps the severity signal inside the reusable module (a reminder bot maps its own classification onto the two rungs) while never sniffing a weather-named reason.
- **Heartbeat handle: Option (d)** — `ReadyGate` holds NO `SchedulerEngine` handle. The app re-registers `__heartbeat__` via the existing one-liner at the composition root. Chosen so `run_daemon`'s heartbeat registration stays exactly where it is today (byte-identical risk minimized for Plan 25-02) and the gate carries zero scheduler dependency.
- **Guard name: `is_running_process(pid, *, proc_marker)`** with internal `_argv_matches_marker`. The argv0-basename + `-m`-module match logic is preserved exactly; `prog == "weatherbot"` becomes `prog == proc_marker.decode(...)` and `b"weatherbot" in argv[1:4]` becomes `proc_marker in argv[1:4]`; the non-Linux /proc degrade returns the supplied `proc_marker`.

## Deviations from Plan

None - plan executed exactly as written. (One test-harness adjustment, below, was an implementation detail of Task 2's own test, not a deviation from planned scope.)

## Issues Encountered
- **Severity-branch test was config-dependent.** The first cut monkeypatched the module logger's `.critical`/`.warning`; it passed in isolation but failed in the full suite because another test reconfigures structlog and the lazy proxy rebinds. Fixed by switching the assertion to `structlog.testing.capture_logs`, which intercepts at the proxy level and is config-independent. The gate's actual severity branching was correct throughout (confirmed by captured stderr); only the assertion mechanism was brittle. Full suite green after the fix.
- **"2 snapshots failed" in the full-suite syrupy report is pre-existing.** Verified by running the suite with all lifecycle additions removed: the identical "2 snapshots failed. 27 snapshots passed." report appears at baseline (762 passed). It is a standing syrupy unused-snapshot artifact, not a golden assertion failure — all 25 golden snapshots pass in isolation and zero test assertions fail. BHV-01/BHV-02 intact (768 passed after this plan, up from 762 baseline, zero new failures).

## Known Stubs
None. The module surface is complete; wiring into `run_daemon` (the app-side `on_online`/`on_fail`/`health_check` closures + `LifecycleIdentity` construction) is the explicit scope of Plan 25-02, not a stub.

## Next Phase Readiness
- The reusable lifecycle surface is ready for Plan 25-02 to wire into `build_runtime(...)`: construct the default `LifecycleIdentity` reproducing `/run/weatherbot/weatherbot.pid` + `b"weatherbot"`, adapt `CheckResult` → `HealthResult` (with `AUTH_FAILED` → `Severity.CRITICAL`, else `WARNING`), and supply the `on_online`/`on_fail` closures carrying the durable `stamp_health`/`stamp_tick` + Discord ping.
- `weatherbot/ops/sdnotify.py` is intentionally NOT deleted yet — 25-02 turns it into a re-export shim so daemon imports stay byte-identical.
- The `__heartbeat__` tick stays app-registered (option d) — 25-02 keeps that registration in place.

## Self-Check: PASSED

All six created files exist on disk; all three task commits (`5ff73e3`, `3592666`, `4873c14`) are present in git history.

---
*Phase: 25-lifecycle-ready-gate-composition-root*
*Completed: 2026-06-28*
