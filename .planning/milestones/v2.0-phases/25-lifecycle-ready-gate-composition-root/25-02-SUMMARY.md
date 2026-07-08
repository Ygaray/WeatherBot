---
phase: 25-lifecycle-ready-gate-composition-root
plan: 02
subsystem: infra
tags: [composition-root, dependency-injection, ready-gate, systemd, sd_notify, lifecycle, pidfile, re-export-shim, byte-identical, service-template]

# Dependency graph
requires:
  - phase: 25-lifecycle-ready-gate-composition-root
    provides: "lifecycle module surface (ReadyGate constructor, HealthResult+Severity, LifecycleIdentity, is_running_process, SystemdNotifier) wired here at the single composition root"
provides:
  - "weatherbot/scheduler/wiring.py:build_runtime — the single app-side composition root (APP-01)"
  - "ReadyGate driven by run_daemon with the four leak points injected at root (APP-02: health-check, config id-deriver, selected-location, render_embed)"
  - "ops re-export shim (sdnotify) + marker-parameterized pid guard delegation + CheckResult->HealthResult boundary adapter (byte-identical)"
  - "deploy/bot.service.template — <NAME>/<RUNTIME_DIR> parameterized unit, byte-identical WeatherBot render"
affects: [25-03-injection-registry-self-uat, 26-command-registry, 27-panelkit-relocation, reminder-bot-reuse]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single app-side composition root (build_runtime) constructs; the controller (run_daemon) sequences the load-bearing ordering"
    - "Swappable collaborators resolved through the daemon module object at call time so daemon-suite monkeypatches keep biting across the wiring boundary"
    - "READY=1 emitted by the gate strictly after on_online runs scheduler.start() — start() lives in the on_online hook so the gate's post-hook notifier.ready() is correctly ordered"
    - "Re-export shim for a relocated symbol (sdnotify) + thin app wrapper delegating to a marker-parameterized module guard (pidfile)"
    - "sed-placeholder .service template with a byte-identical concrete render"

key-files:
  created:
    - weatherbot/scheduler/wiring.py
    - deploy/bot.service.template
  modified:
    - weatherbot/ops/sdnotify.py
    - weatherbot/ops/pidfile.py
    - weatherbot/ops/selfcheck.py
    - weatherbot/ops/__init__.py
    - weatherbot/scheduler/daemon.py
    - deploy/README.md
    - tests/test_reload.py

key-decisions:
  - "build_runtime lives in weatherbot/scheduler/wiring.py and resolves swappable collaborators (BackgroundScheduler, run_self_check, SystemdNotifier, _register_*, stamp_*, threading.Event) via a lazy `import weatherbot.scheduler.daemon as daemon` — so every daemon_mod.X monkeypatch in the suite keeps biting the constructed parts byte-identically across the new wiring boundary"
  - "scheduler.start() moved INTO the on_online hook so READY=1 (the module's notifier.ready(), fired by the gate AFTER on_online) reaches systemd strictly after scheduler.start() — the most golden-sensitive invariant; build_runtime never emits READY"
  - "the app's classified CRITICAL/WARNING per-attempt startup log was preserved app-side via the on_fail hook (daemon._log.critical/warning) to keep the daemon-suite's daemon_mod._log.critical assertion green; the module's ReadyGate ALSO logs a generic severity line to its own logger (additive, failure-path-only)"
  - "is_weatherbot_pid kept app-side as a thin wrapper delegating to is_running_process(proc_marker=WEATHERBOT_PROC_MARKER); write_pid_atomic/read_pid/_argv_is_weatherbot kept app-side bodies (directly tested + monkeypatch on pidfile.os.replace)"
  - ".service template parameterizes ONLY Description (<NAME>) and RuntimeDirectory (<RUNTIME_DIR>); no PIDFile= line (advisory for Type=notify); comments stay literal so the WeatherBot render diffs empty"

patterns-established:
  - "Composition-root-constructs / controller-sequences split for order-sensitive lifecycle code"
  - "Cross-module monkeypatch transparency via lazy module-object resolution at call time"

requirements-completed: [SEAM-05, APP-01, APP-02]

# Metrics
duration: 30min
completed: 2026-06-28
status: complete
---

# Phase 25 Plan 02: Lifecycle Composition Root Wiring Summary

**Wired the reusable lifecycle module into WeatherBot at a single app-side composition root (`build_runtime`) that constructs the scheduler + holder + ReloadEngine + ReadyGate + channel + the four injected leak points and a byte-identical default `LifecycleIdentity`; `run_daemon` now drives the ReadyGate while keeping the load-bearing SIGTERM-before-gate / gate→start→READY / observer-in-finally ordering — with the ops surface re-pointed at the module via a shim + marker-parameterized guard, and the `.service` shipped as a parameterized template — all byte-identical (769 passed, every Phase-21 golden green, zero golden edited).**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-06-28
- **Tasks:** 3
- **Files:** 2 created, 7 modified

## Accomplishments
- **Task 1 — ops boundary re-point (byte-identical):** turned `weatherbot/ops/sdnotify.py` into a re-export shim resolving to the identical module `SystemdNotifier`; re-pointed `is_weatherbot_pid` to delegate to the module's marker-parameterized `is_running_process(proc_marker=b"weatherbot")` (added the `WEATHERBOT_PROC_MARKER` app-side constant); added the `CheckResult → HealthResult` boundary adapter `to_health_result` (AUTH_FAILED → CRITICAL severity, else WARNING); kept `write_pid_atomic`/`read_pid`/`_argv_is_weatherbot` app-side (directly tested + the `pidfile.os.replace` monkeypatch). Added the explicit pid-guard byte-identity assertion to `tests/test_reload.py` (the load-bearing invariant had no direct test before).
- **Task 2 — composition root + driven gate:** created `weatherbot/scheduler/wiring.py:build_runtime(...)` lifting `run_daemon`'s ~200-line constructor/wiring block into the single greppable site; constructed the `ReadyGate` with the four injected leak points + the byte-identical default `LifecycleIdentity` + the `on_fail`/`on_online` best-effort hooks (D-02a). Refactored `run_daemon` to call `build_runtime` and drive `ready_gate.run(stop)`, keeping the load-bearing lifecycle ordering inline. READY=1 is emitted by the gate strictly after `on_online` runs `scheduler.start()`.
- **Task 3 — .service template:** created `deploy/bot.service.template` extending the `<REPO>`/`<USER>` convention with `<NAME>`/`<RUNTIME_DIR>`; the WeatherBot render (`<NAME>=WeatherBot`, `<RUNTIME_DIR>=weatherbot`) `diff`s EMPTY against `deploy/weatherbot.service`; documented the placeholders + the optional `PIDFile=` note in `deploy/README.md`. No `PIDFile=` line in the render.

## Task Commits

1. **Task 1: ops re-point (shim + guard delegation + adapter)** - `ef004ef` (feat)
2. **Task 2: build_runtime composition root + run_daemon drives the ReadyGate** - `2bfb6ae` (feat)
3. **Task 3: parameterized .service template (byte-identical render)** - `2d77154` (feat)

## The build_runtime / run_daemon boundary (what MOVED vs what STAYED)

**MOVED into `build_runtime` (constructors only):** the channel-build-once block, `BackgroundScheduler` + `stop` Event + `ConfigHolder` + `ForecastCache`, `_register_jobs` + the `__heartbeat__` re-registration (Option d) + `_register_uvmonitor_job` + `_announce_schedule` + `_run_catchup`, the `ReloadEngine` + its `_on_applied` closure, and the NEW `ReadyGate` construction (health_check / on_fail / on_online / default LifecycleIdentity).

**STAYED in `run_daemon` (the load-bearing ORDERING):** the SIGTERM handler installed BEFORE the gate, the SIGHUP→`reload_engine.request_reload()` handler, `write_pid_atomic(identity.pid_file)` at startup, arming the file-watch observer, the gate→`scheduler.start()`→online→READY ordering (now driving `ready_gate.run(stop)`), the inbound BotThread start strictly after online, the main park→poll loop, and the `finally` teardown (`identity.pid_file.unlink`).

## D-04 floor fallback — NOT needed

The full ReadyGate drive (D-04 option d) held with zero golden perturbation. The floor (procedural `run_daemon` with the four injections explicit) was NOT required. The one byte-identical risk that surfaced — the daemon-suite asserting `daemon_mod._log.critical` on an auth-failed probe — was resolved by keeping the app's classified per-attempt log app-side in the `on_fail` hook (rather than relying on the module's generic severity log), so the assertion stays green AND the durable health row + classification stay app-side per D-02a.

## Byte-identical risks investigated
- **Cross-module monkeypatch transparency.** The daemon suite patches `daemon_mod.{BackgroundScheduler, run_self_check, SystemdNotifier, _register_jobs, threading.Event, stamp_*}` then calls `daemon_mod.run_daemon`. Since construction moved into `wiring.py`, a naive import would dodge those patches. Resolved by having `build_runtime` resolve every swappable collaborator through `import weatherbot.scheduler.daemon as daemon` (`daemon.X`) at call time — so the patches bite identically. All 86 scheduler/reload tests pass unchanged.
- **READY-before-start ordering.** The 25-01 `ReadyGate.run()` fires `on_online` then `notifier.ready()` on the first passing probe and returns True — so a naive drive would emit READY before `run_daemon` could call `scheduler.start()`. Resolved by placing `scheduler.start()` as the FIRST step of the injected `on_online` hook, so the gate's post-hook `notifier.ready()` is strictly after start (the most golden-sensitive invariant). Verified by `test_online_once_fires_all_signals_then_starts` + `test_bot_thread_starts_strictly_after_online_signal`.
- **pid guard byte-identity.** `is_weatherbot_pid` now delegates to the module guard; pinned the three representative `/proc` cmdlines (argv0 basename, `python -m`, non-match) return the same bool via both the app wrapper and the module guard (new `test_is_weatherbot_pid_delegates_byte_identically_to_module_guard`).
- **.service render.** `diff <(sed -e 's/<NAME>/WeatherBot/' -e 's/<RUNTIME_DIR>/weatherbot/' deploy/bot.service.template) deploy/weatherbot.service` is EMPTY.

## Deviations from Plan

### Auto-fixed / preserved behavior

**1. [Rule 1 — Bug-avoidance] App-side per-attempt CRITICAL/WARNING log kept in the on_fail hook**
- **Found during:** Task 2.
- **Issue:** The 25-01 design intends the module's `ReadyGate` to own the per-attempt severity log (branching on the neutral `Severity` field). But the daemon suite (`tests/test_scheduler.py`, the auth-recovery test) asserts `daemon_mod._log.critical` was called — that recorder cannot observe the module's `ready_gate._log.critical` (a different logger). A pure module-owned log would have broken the test, which may not be edited to accommodate.
- **Fix:** the injected `on_fail` hook does the durable `stamp_health` AND logs the app's classified CRITICAL/WARNING line through `daemon._log`, preserving today's daemon-logger split. The module's `ReadyGate` still logs a generic severity line to its own logger (additive, on the startup-failure path only).
- **Files modified:** `weatherbot/scheduler/wiring.py`.
- **Commit:** `2bfb6ae`.
- **Note:** the only observable production change is a second (module-side) startup-failure log line on the failure path — additive, never wrong, not golden-pinned. No suite assertion or golden depends on the single-line count.

### Carried-forward (intentional, not removed)
- `gate_until_healthy` and `emit_online` remain DEFINED in `daemon.py` but are no longer called by `run_daemon` (the ReadyGate + injected hooks supersede them). They have no imports anywhere and there is no standing coverage gate (pyproject D-08), so they are harmless documented adapters. Left in place to minimize churn/risk; a later cleanup phase may remove them.

## Known Stubs
None. The four leak points are injected at the single root; the durable side-effects ride the injected hooks; the `.service` renders byte-identical. The positive injection-registry proof + the Gate-1 self-UAT are the explicit scope of Plan 25-03, not stubs.

## Threat Flags
None. No new network endpoint / auth path / file-access pattern / schema change was introduced — this was a pure move/re-point within existing packages (T-25-SC: zero new dependencies). The reload-sender PID guard (T-25-04) stays byte-identical; the online-ping literal (T-25-06) is preserved verbatim in the on_online hook; the `.service` keeps `User=<USER>` least-privilege (T-25-05).

## Next Phase Readiness
- `build_runtime` is the single greppable wiring site Plan 25-03's `test_injection_registry.py` introspects for the four injected args; the `ReadyGate` it constructs has no module-side default probe (constructing without `health_check` is a `TypeError`).
- READY=1 ordering is gate-driven and can be proven byte-level in 25-03 via a captured `NOTIFY_SOCKET` (no READY before the passing probe + `scheduler.start()`; no READY on stop-preempt).
- The full suite is green (769 passed) and every Phase-21 golden passes with zero diff (BHV-01/BHV-02) — the byte-identical oracle Plan 25-03 records in the self-UAT log.

## Self-Check: PASSED

All created files exist; all three task commits are present in git history.

---
*Phase: 25-lifecycle-ready-gate-composition-root*
*Completed: 2026-06-28*
