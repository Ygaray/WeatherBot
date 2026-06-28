# Phase 25: Lifecycle READY-Gate + Composition Root - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-28
**Phase:** 25-lifecycle-ready-gate-composition-root
**Areas discussed:** Lifecycle surface shape, Health-check contract, Identity + .service template, Composition-root form + leak-point proof
**Mode:** advisor (calibration tier: full_maturity — thorough-evaluator); four parallel advisor-researcher agents read the live code and returned comparison tables.

---

## ① Lifecycle surface shape (SEAM-05)

| Option | Description | Selected |
|--------|-------------|----------|
| (a) `ReadyGate` engine | Ctor-injected health_check + notifier + interval; engine owns re-probe loop + READY emit + heartbeat job. Best precedent fit, most reuse-complete. | ✓ |
| (d) ReadyGate engine, heartbeat app-side | Same reusable core but gate stays dependency-free; app re-registers the heartbeat one-liner. Sanctioned lighter variant. | |
| (b) Thin split | Move only SystemdNotifier + a free gate fn. Lowest byte-identical risk, but the re-probe loop stays duplicated per host. Fallback. | |
| ~~(c) engine-owns-more~~ | Disqualified — would import stamp_health (weather/DB) into the module. | |

**User's choice:** (a) ReadyGate engine.
**Notes:** Captures the genuinely-reusable triad (interruptible `stop.wait` loop, `READY=1` emit, heartbeat tick) — the same reuse payoff that justified extracting `ReloadEngine`. `SystemdNotifier` moves into the module directly (already pure-stdlib, weather-clean).

---

## ② Health-check callback contract (SEAM-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Generic `HealthResult(ok, reason, detail)` + on_online/on_fail hooks | Maps 1:1 onto today's CheckResult → lowest byte-identical risk for the per-attempt severity log; module logs opaquely + branches severity on a NEUTRAL field. | ✓ |
| Bare bool + symmetric hooks | Module bool-only; app does all logging/stamping/ping in hooks (pure ReloadEngine twin). Per-attempt severity log must relocate app-side. | |
| typing.Protocol health port | Consistent with AlertSink/OccurrenceStore but over-keyed for a single nullary probe. | |

**User's choice:** Generic HealthResult + hooks.
**Notes:** Durable stamping (`stamp_health`/`stamp_tick`) + the Discord ping stay app-side via hooks — **forced**, not a choice, since `stamp_health` lives in `weatherbot/weather/store.py` (a weather path; the module owns zero durable DB I/O). The neutral-severity field is mandatory so the module never sniffs a weather-named reason like `"auth_failed"`.

---

## ③ Process-identity parameterization + .service template (SEAM-05, APP-02 criterion 4)

| Option | Description | Selected |
|--------|-------------|----------|
| (A) `LifecycleIdentity` dataclass | One immutable struct (name, pid_file, runtime_dir, console_name, proc_marker) wired once at the root. Honest about the 4 facts differing. | ✓ |
| (C) Individual kwargs | Extend the per-callsite override; smallest diff / lowest golden risk; identity scatters. Fallback. | |
| (B) Derive all from one name | Smallest surface, but fuses four facts that differ today and bakes a convention into the module. | |

**User's choice:** (A) LifecycleIdentity dataclass.
**Notes:** The `/proc` staleness marker = WeatherBot's `[project.scripts] weatherbot` argv0, independent of the pid-dir name — independent fields express that honestly. Drops the `weatherbot` literal from `ops/pidfile.py` (path → `identity.pid_file`; guard generalizes to a `proc_marker`-parameterized predicate), byte-identical defaults.
**.service template (Claude's-discretion default, not separately discussed):** extend the existing `<REPO>`/`<USER>` sed convention with `<NAME>`/`<RUNTIME_DIR>` (ship a generic `bot.service.template`). User flagged no objection.

---

## ④ Composition-root form + four-leak-point injection proof (APP-01, APP-02)

| Option | Description | Selected |
|--------|-------------|----------|
| (d) Thin app-side `wiring.py` → `build_runtime(...)` | One delegated wiring function; lifecycle ordering stays in daemon.py. Satisfies APP-01 structurally as a MOVE not a redesign → goldens easier to keep green. | ✓ |
| (a) Procedural run_daemon, injections explicit | Keep the ~230-line block, name + document the 4 injections. Lowest-risk floor; APP-01 by discipline. Fallback. | |
| (b) BotApp.compose() assembly object | The "right" end-state, but high golden-risk now and Phase 26's registry doesn't exist yet → deferred to after Phase 26. | |
| ~~(c) module-side compose()~~ | Not recommended — pulls weather concepts back across the litmus boundary. | |

**User's choice:** (d) thin wiring.py build_runtime().
**Notes:** A move, not a redesign — lifecycle ordering (SIGTERM-before-gate, single-channel-build, observer-in-finally, READY-after-gate+start) stays in `daemon.py`.
**Leak-point proof (Claude's-discretion default, not separately discussed):** keep the existing 3-gate `test_import_hygiene.py` litmus (D-13-locked negative gate) AND add a positive injection-registry test proving each of the 4 leak points is supplied from the app with no baked module default. Do NOT broaden the locked term set. User flagged no objection.

---

## Claude's Discretion

- Module sub-layout for the lifecycle seam (`lifecycle/` package vs flatter) + file naming.
- Exact `ReadyGate` method/param names; whether the heartbeat handle is (a) or the (d) variant.
- Whether `HealthResult` severity is a discrete neutral field or the app pre-selects the log level in the hook.
- Whether identity is the `LifecycleIdentity` struct (default) or the (C) kwargs fallback; the generalized guard name.
- The home/name of `wiring.py` `build_runtime(...)` and where the daemon/wiring boundary is drawn; the precise form of the injection-registry assertion.
- The `grimp`-graph assertion form for the new `lifecycle` edges + the isolated-import smoke extension + the litmus target set.
- The `.service` template form (sed-default vs deferred generator) and the leak-point proof structure — both Claude's-discretion defaults the user did not flag.

## Deferred Ideas

- `BotApp.compose()` explicit assembly object — defer to after Phase 26 (registry must exist first).
- Generator-from-`LifecycleIdentity` `.service` rendering (optionally Jinja2) — over-built for one host now.
- `typing.Protocol` health port — revisit only if a second app-health operation appears.
- PanelKit / Discord adapter physical relocation + generic `SelectedContext[I]` — Phase 27.
- Command Registry + dispatcher into the module — Phase 26.
- Broadening the litmus term set — rejected; locked D-13 set stays weather-specific.
- Full docstring/comment weather-noun scrub of the module — Phase 28 / DOCS-01.
- Durable / dynamic `JobStore` impl — JOBSTORE-V2-01, deferred to a reminder-style consumer.
