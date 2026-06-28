# Phase 25: Lifecycle READY-Gate + Composition Root - Context

**Gathered:** 2026-06-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Two tightly-linked halves of the v2.0 extraction:

**(A) Lifecycle layer extraction (SEAM-05).** Lift the process-lifecycle layer — the systemd
`Type=notify` READY-gate, the interruptible startup re-probe loop, the heartbeat tick, and the
supervised-restart contract — into `yahir_reusable_bot` so it gates systemd `READY=1` on an
**app-provided health-check callback**. The weather/API probe (`run_self_check`) **stays app-side
and is injected**. PID path / runtime dir / unit name / `/proc` console marker are **parameterized**
(no `weatherbot` literal in the module's lifecycle), and the `.service` ships as a parameterized
**template** (identity supplied by the app).

**(B) Single composition root (APP-01) + four-leak-point injection proof (APP-02).** Consolidate
WeatherBot's wiring at **one** site that registers its weather commands, config schema, health
probe, `render_embed`, and selected-**location** context — with **zero duplicated copy of any module
mechanism**. Prove the four "secretly app-coupled" leak points — `SelectedContext`=location, the
config id-deriver / exactly-once key, the health-check, and panel cosmetics (`render_embed`) — are
**injected, not baked**, verified by the litmus check that no weather term appears in the module
package.

**HOW is what we clarified here. The WHAT — and the headline shape — is LOCKED by the roadmap
(Phase-25 detail block) + REQUIREMENTS (SEAM-05, APP-01, APP-02), and behavior must stay
byte-identical** (the Phase-21 golden snapshots + ~649-test suite are the oracle). The load-bearing
invariants the goldens pin: `READY=1` reaches systemd **only after** the app probe passes (emit
strictly after the gate returns True and after `scheduler.start()`); the re-probe wait is an
interruptible `stop.wait(...)`, **never** `time.sleep` (a `systemctl stop` mid-probe must break
promptly, Pitfall 2); and the exactly-once online emit subsumes the startup heartbeat tick. Any
non-empty snapshot diff during extraction is a failure to investigate, never rubber-stamped.

**Governing acceptance lens (every seam):** *"could a hypothetical reminder bot reuse this with zero
weather assumptions?"* — the milestone's north star is a reusable bot module shipped as its own repo
and imported across future projects. The module lifecycle must name no weather noun; APP-02's litmus
grep over the lifecycle seam must be clean (a reminder bot supplies its own health predicate +
filesystem identity + the four injected parts).

**Stays entirely app-side (never enters the module):** `run_self_check` + `CheckResult` + the
`AUTH_FAILED`/`NETWORK_NOT_READY` classification vocabulary, the durable `stamp_health` / `stamp_tick`
rows (they live in `weatherbot/weather/store.py` — a literal weather path; the module owns zero
durable DB I/O), the Discord online ping, and WeatherBot's `[project.scripts] weatherbot` console
identity (the `/proc` argv0 marker the staleness guard matches).

**Cross-cutting gates re-run this phase:** PKG-01 (module imports zero app code; `grimp`-in-pytest +
isolated-import smoke), APP-02 litmus grep (no weather noun in the module lifecycle seam) **plus the
new positive injection-registry assertion**, BHV-01/BHV-02 (suite + goldens green).

New capabilities (durable `JobStore` impl, new channels, the Command Registry, the PanelKit/Discord
adapter relocation) stay deferred to their named later phases.

</domain>

<decisions>
## Implementation Decisions

The roadmap Phase-25 detail block pre-locks the headline (READY-gate over an injected health-check,
parameterized identity, `.service` template, single composition root, four injected leak points, the
litmus). Four parallel advisor research agents (read the live code) confirmed the direction and
surfaced the genuinely-open sub-decisions below. **The user selected every recommended option** —
all four anchor on the reusable-module goal and minimize byte-identical risk. The design is coherent:
the **`ReadyGate` engine (D-01)** drives the **generic `HealthResult` predicate + app-side hooks
(D-02)**; the **`LifecycleIdentity` struct (D-03)** is one of the things the **single `wiring.py`
composition root (D-04)** injects.

### Lifecycle surface shape (SEAM-05) — the extraction crux
- **D-01 [chosen: Option (a) `ReadyGate` engine]:** The module gets a **`ReadyGate` engine** —
  constructor-injected `health_check` callable + a `SystemdNotifier` + a re-probe interval — that
  **owns the genuinely-reusable triad**: the interruptible `while not stop.is_set()` re-probe loop
  (`stop.wait(interval)`, never `time.sleep`), the `READY=1` emit, and the heartbeat IntervalTrigger
  tick registration. Directly mirrors the `SchedulerEngine` / `ReloadEngine` constructor-injection +
  opaque-passthrough precedent (Phase-23/24 D-07).
  - **Why over the thinner split (Option b):** capturing the pitfall-dense re-probe loop + heartbeat
    in the module IS the reuse payoff — the same rationale that justified extracting `ReloadEngine`
    one phase earlier; (b) leaves a reminder bot to re-hand-write the loop. (b) remains the strictly
    safer **fallback if loop extraction is explicitly deferred** (the D-05-style "safer for goldens,
    leaves plumbing duplicated" posture).
  - **Why over engine-owns-more (Option c — rejected):** `stamp_health`/`stamp_tick` resolve to
    `weatherbot/weather/store.py`; an engine owning the durable health row would force the module to
    import weather/DB code and **fail the APP-02 litmus + the SEAM-05 "no weather code in module
    lifecycle" criterion**. The health row + Discord ping must ride injected hooks.
  - **`SystemdNotifier` (`weatherbot/ops/sdnotify.py`) is already pure-stdlib and weather-clean** — it
    moves into the module's lifecycle layer directly.
  - **Heartbeat-handle note (Option d on the table):** the gate holding a `SchedulerEngine` handle for
    the heartbeat is accepted (the chosen (a)). If the planner finds the handle awkward, Option (d) —
    heartbeat re-registered app-side via the existing one-liner `SchedulerEngine.register("__heartbeat__", …)`
    — is a sanctioned lighter variant that keeps the gate dependency-free; not the default.

### Health-check callback contract (SEAM-05)
- **D-02 [chosen: generic `HealthResult` + symmetric app-side hooks]:** the injected `health_check`
  returns a **generic `HealthResult(ok, reason, detail)`** (a module-owned, weather-noun-free
  dataclass — maps 1:1 onto today's app-side `CheckResult`). The `ReadyGate` **logs `reason`/`detail`
  opaquely** and branches re-probe severity on a **neutral field** (NOT by comparing to a weather
  string like `"auth_failed"`) — so today's CRITICAL-on-auth / WARNING-on-network split is preserved
  with the lowest byte-identical risk. All weather-coupled side-effects ride **symmetric best-effort
  hooks** at today's exact points (the Phase-24 `on_applied`/`on_rejected` precedent): an
  `on_fail`/`on_probe`-style hook for the per-outcome `stamp_health` row, and an **`on_online`** hook
  carrying `emit_online`'s five-part bundle (health-row `reason="online"`, `stamp_tick`, the
  structured `weatherbot online` log, and the Discord ping). Hooks are best-effort (logged + swallowed,
  never mask the gate result).
  - **The neutral-severity field is mandatory:** if the engine branched on `reason == "auth_failed"`
    it would name an app concept and trip the litmus. Carry severity as an explicit neutral field
    (e.g. `severity`/`level`) the module never authored, OR have the app pre-select the log level in
    the hook. Planner's discretion which, as long as the module never sniffs a weather-named reason.
  - **Why not bare `bool` + hooks (runner-up):** strongest precedent fit, but it strips the module of
    the signal today's per-attempt severity-log branch keys on, forcing that log app-side and making
    byte-identical per-attempt logging the hardest thing to re-prove. Acceptable if the planner would
    rather the app own all per-attempt logging.
  - **Why not a `Protocol` health port (rejected):** a single nullary `probe()` is a Callable in heavy
    clothing — it doesn't clear the bar the existing multi-method ports (`AlertSink`/`OccurrenceStore`)
    set. Revisit only if the lifecycle layer grows a second app-health operation.
- **D-02a [forced — durable stamping stays app-side]:** the module owns **zero durable I/O**.
  `stamp_health` / `stamp_tick` (weather-side SQLite single-row table) and the Discord online ping stay
  app-side closures invoked by the engine at one well-defined first-pass / per-outcome call site —
  preserving `emit_online`'s ordering (the real byte-identical risk) with zero module knowledge of any
  of them. This is settled by Phase-24 D-09 (the same class of question) + the `ports/alerts.py` D-07
  rule ("where the row is written / what the backend is belongs to the app").

### Process-identity parameterization + `.service` template (SEAM-05, APP-02 criterion 4)
- **D-03 [chosen: Option (A) `LifecycleIdentity` dataclass]:** a single **immutable
  `LifecycleIdentity`** struct (`name`, `pid_file: Path`, `runtime_dir`, `console_name`,
  `proc_marker`) constructed app-side and wired once at the composition root, threaded into the
  lifecycle layer. Best fit for the injection idiom + the composition-root phase.
  - **Why independent fields, not one `name` (Option B — rejected as default):** the four identity
    facts are **not** the same string today. The `/proc` staleness marker comes from WeatherBot's
    `[project.scripts] weatherbot` console-script argv0 (and the `python -m weatherbot` form), which
    the module must NOT assume equals the pid-dir name. Independent fields express that honestly; (B)
    silently fuses them and bakes a `/run/{name}/{name}.pid` convention into the module a second bot
    might not honor.
  - **Drops the `weatherbot` literal cleanly:** `weatherbot/ops/pidfile.py` today hardcodes
    `PID_FILE = Path("/run/weatherbot/weatherbot.pid")` (with a per-callsite override already threaded
    through `write_pid_atomic`/`read_pid`). The path becomes `identity.pid_file`; `is_weatherbot_pid`
    generalizes to a marker-parameterized guard (e.g. `is_running_process(pid, *, proc_marker)`)
    keeping the argv0-basename + `-m`-module match logic — so the PID-recycling defense + reload-sender
    exit codes stay byte-identical. The default `LifecycleIdentity` must reproduce
    `/run/weatherbot/weatherbot.pid` + the `b"weatherbot"` marker exactly.
  - **Fallback:** Option (C) individual kwargs (extend the existing per-callsite override; smallest
    diff, lowest golden risk, identity scatters) is the sanctioned lighter path if the struct feels
    heavy this phase.
- **D-03a [unit ships as a sed-template — Claude's-discretion default, not separately discussed]:**
  the `.service` extends today's `<REPO>`/`<USER>` install-time sed-placeholder convention with
  `<NAME>`/`<RUNTIME_DIR>` (module/deploy ships a generic `bot.service.template`; `RuntimeDirectory=`,
  `PIDFile=`, `Description=` parameterize). Reuses the shipped install model documented in
  `deploy/README.md`, no new dep, rendered unit byte-identical after substitution. A generator-from-
  `LifecycleIdentity` (optionally Jinja2, already a dep) is the more-elegant single-sourced
  alternative, **deferred** as over-built for a single-host personal bot now. **Flag to revisit if you
  want the unit + runtime identity provably single-sourced.**

### Composition-root form + four-leak-point injection proof (APP-01, APP-02)
- **D-04 [chosen: Option (d) thin app-side `wiring.py` → `build_runtime(...)`]:** lift `run_daemon`'s
  ~230-line wiring block into **one delegated app-side function** (`build_runtime(...)` in a new
  `weatherbot/.../wiring.py`) that constructs holder + `SchedulerEngine` + `ReloadEngine` + the new
  `ReadyGate` + channel + the four injected leak points and returns the wired parts; `run_daemon`
  **keeps the load-bearing lifecycle ordering** (SIGTERM-handler-before-gate, single-channel-build-once,
  observer-armed-in-`finally`, `READY` strictly after gate+start). Satisfies APP-01's "one greppable
  wiring site, zero duplicated module mechanism" **structurally** — as a **move, not a redesign** — so
  the goldens are far easier to keep green.
  - **Why not the explicit `BotApp.compose()` object (Option b — deferred):** the "right" end-state,
    but relocating 230 lines of order-sensitive wiring **now** is the highest golden-risk option, and
    the Phase-26 Command Registry it should wire **doesn't exist yet**. Defer to **after Phase 26**,
    when the registry gives the assembly object something real to compose.
  - **Why not a module-side `compose()` (Option c — rejected):** pulls weather concepts back across the
    litmus boundary the whole milestone defends; inverts the proven "app injects into module" direction.
  - **Fallback floor:** Option (a) — keep the procedural `run_daemon`, make the four injections explicit
    + documented (lowest risk, APP-01 by discipline) — if any reload-golden perturbs under (d).
- **D-05 [leak-point proof — Claude's-discretion default, not separately discussed]:** keep the
  existing 3-gate `tests/test_import_hygiene.py` litmus (the **D-13-locked negative gate**: `grimp` +
  isolated-import + AST noun scan over `yahir_reusable_bot/**`, term set
  `weather|forecast|location|openweather|\buv\b|briefing`) running every phase, **and ADD a positive
  "injection-registry" test** asserting each of the four leak points — `SelectedContext` (location),
  the config id-deriver / exactly-once key, the health-check, and `render_embed` / panel cosmetics — is
  supplied **as an injected arg at the single root** with **no module-side baked default**. Turns
  APP-02 from "no weather noun" into "no weather noun AND wired-from-app" (and seeds the DOCS-01
  EXTENSION-GUIDE). **Do NOT broaden the locked term set** — `SelectedContext`/`health`/`embed`-render
  are exactly the *generic* names the module is meant to expose; widening the regex would over-fit,
  contradict the D-13 lock, and redden settled module surface.

### Claude's Discretion
- The module sub-layout for the lifecycle seam (a `lifecycle/` package inside `yahir_reusable_bot/`
  holding `ReadyGate` + the relocated `SystemdNotifier`, vs a flatter shape) and file naming — guided
  by the existing `channels/` / `config/` / `scheduler/` / `ports/` shapes.
- Exact `ReadyGate` method/param names and whether the heartbeat handle is (a) (gate holds the
  `SchedulerEngine`) or the sanctioned (d) variant (heartbeat re-registered app-side) — shaped by what
  `run_daemon` needs to stay byte-identical.
- Whether `HealthResult`'s severity is a discrete neutral field (`severity`/`level`) the engine branches
  on, or the app pre-selects the log level in the `on_fail` hook — either keeps the module from sniffing
  a weather-named reason.
- Whether identity threads as a `LifecycleIdentity` struct (D-03 default) or the (C) kwargs fallback,
  and the exact generalized guard name (`is_running_process(pid, *, proc_marker)` vs other).
- The exact home/name of the `wiring.py` `build_runtime(...)` function and where the daemon/wiring
  boundary is drawn (must not split order-sensitive lifecycle steps), and the precise form of the new
  positive injection-registry assertion.
- The `grimp`-graph assertion form for the growing module (new `lifecycle` edges) and the
  isolated-import smoke-test extension; the precise litmus-grep target set for the lifecycle seam.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & milestone contract
- `.planning/ROADMAP.md` § "Phase 25: Lifecycle READY-Gate + Composition Root" — the **pre-locked
  design** (READY-gate over an app-provided health-check callable; `run_self_check` stays app-side;
  PID path / runtime dir / unit name / console name parameterized, no `weatherbot` literal in the
  module; `.service` as a parameterized template; single composition root registering commands /
  config schema / health probe / `render_embed` / selected-location context with zero duplicated
  module mechanism; the four injected leak points; the litmus) and the **4 locked success criteria**.
- `.planning/ROADMAP.md` § "v2.0 Bot Module Extraction" milestone header + phase spine (leaf-seams-
  first, split-last) — establishes why lifecycle is the next seam and why the registry/PanelKit
  relocation defer to Phases 26/27.
- `.planning/REQUIREMENTS.md` § **SEAM-05** (lifecycle gates READY on an app-provided health-check;
  weather probe stays app-side), **APP-01** (single composition root, zero duplicated module
  mechanism), **APP-02** (four leak points injected not baked; litmus = no weather term in the module),
  and the **Cross-cutting acceptances** (PKG-01 on 23–27; APP-02 standing grep gate; BHV-01/BHV-02
  re-run every phase). Traceability: SEAM-05 / APP-01 / APP-02 → Phase 25.

### Prior-phase contracts this phase must honor
- `.planning/phases/24-config-hot-reload-engine/24-CONTEXT.md` — the **explicit hand-off** deferring
  the lifecycle READY-gate / systemd `Type=notify` / heartbeat-as-health AND the single-composition-
  root consolidation to THIS phase; **D-09's symmetric best-effort hook pattern** (`on_applied`/
  `on_rejected`) that D-02's `on_online`/`on_fail` mirror; **D-08's durable-stamping-stays-app-side**
  rule; the constructor-injection + opaque-passthrough engine precedent (basis for D-01).
- `.planning/phases/23-scheduler-engine-occurrencestore-jobstore-seam/23-CONTEXT.md` — the
  `SchedulerEngine(scheduler)` constructor-injection precedent the `ReadyGate` mirrors; the
  define-only `OccurrenceStore` Protocol (the port pattern D-02 weighed the health-port option
  against and rejected for a nullary probe).
- `.planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-CONTEXT.md` — the Ports &
  Adapters / DI template, the flat-sibling `yahir_reusable_bot/` layout, the `grimp`-in-pytest import
  gate + isolated-import smoke + signatures-only litmus (basis for D-05), and "adapt the orchestrator,
  don't rewrite it" (basis for keeping `run_self_check` / the wiring app-side).
- `.planning/phases/21-characterization-golden-test-harness/21-CONTEXT.md` + `21-PATTERNS.md` — the
  golden oracle (schedule-plan golden, the reload reconcile-diff, keep-old-rollback, exactly-once,
  the `sent_log` DB-row goldens) and the move-path package pattern map; the discipline rule (any
  non-empty snapshot diff during extraction is a failure to investigate).

### Source surfaces this phase moves / touches
- `weatherbot/scheduler/daemon.py` — `gate_until_healthy` (~L1108, → the `ReadyGate`'s interruptible
  re-probe loop), `emit_online` (~L1159, → the `on_online` hook's five-part bundle), `_heartbeat_tick`
  (~L574) + the `__heartbeat__` IntervalTrigger registration (~L1446, → the gate's heartbeat tick),
  `RE_PROBE_INTERVAL_S` (~L133) / `HEARTBEAT_INTERVAL_S` (~L108) constants, the `write_pid_atomic(PID_FILE)`
  call site (~L1576) + `finally` unlink, and **`run_daemon` (~L1354–1610, → the new `wiring.py`
  `build_runtime(...)`; lifecycle ordering stays here)**.
- `weatherbot/ops/sdnotify.py` — `SystemdNotifier` (pure-stdlib `READY=1` wire; **moves into the module
  lifecycle layer directly** — already weather-clean).
- `weatherbot/ops/selfcheck.py` — `run_self_check` + `CheckResult(ok, reason, detail)` +
  `PASS`/`NETWORK_NOT_READY`/`AUTH_FAILED` vocabulary (**stays app-side**, becomes the injected
  `health_check`; `CheckResult` maps onto the module's generic `HealthResult`).
- `weatherbot/ops/pidfile.py` — `PID_FILE` constant + `write_pid_atomic` / `read_pid` /
  `is_weatherbot_pid` (the `/proc` cmdline guard, `_argv_is_weatherbot` argv0-basename / `-m`-module
  match) → **path becomes `identity.pid_file`; the guard generalizes to a `proc_marker`-parameterized
  predicate** (D-03), byte-identical defaults.
- `weatherbot/ops/__init__.py` — the `PID_FILE` / `is_weatherbot_pid` re-exports that generalize.
- `weatherbot/weather/store.py` — `stamp_health` / `stamp_tick` (the durable single-row health table,
  weather-side DB) + the `UNIQUE(location_name, send_time, local_date)` exactly-once key (leak point 2).
  **Stays app-side**; reached only via the injected hooks.
- `weatherbot/cli.py` — the `do_reload` sender using `read_pid` / `is_weatherbot_pid` (~L465–480) +
  `PID_FILE` import (~L50) — must keep byte-identical exit codes under the generalized guard.
- `weatherbot/interactive/panel.py` — `SelectedContext` / `_selected_location` + `render_embed` call
  sites (leak points 1 + 4). **Only the injection SEAM is proven here; the PanelKit/Discord adapter
  physical relocation is Phase 27.**
- `deploy/weatherbot.service` + `deploy/README.md` — the existing `<REPO>`/`<USER>` sed-template +
  `RuntimeDirectory=weatherbot` + documented substitution → extend with `<NAME>`/`<RUNTIME_DIR>`
  (D-03a).
- `tests/test_import_hygiene.py` — the mature 3-gate APP-02 litmus (grimp + isolated-import + AST noun
  scan, D-13-locked term set) to **re-run + extend with the positive injection-registry assertion** (D-05).
- `pyproject.toml` — `[project.scripts] weatherbot = "weatherbot.cli:main"` (the app-owned argv0 marker
  the guard matches), `[tool.hatch...packages]` (two-package wheel), the `grimp` import-gate config,
  `[tool.coverage]` (must keep covering moved code).
- `yahir_reusable_bot/scheduler/engine.py` (`SchedulerEngine`) + `yahir_reusable_bot/config/reload.py`
  (`ReloadEngine` + `on_applied`/`on_rejected`) — the constructor-injection + symmetric-hook precedents
  the `ReadyGate` clones; `yahir_reusable_bot/ports/` — the (rejected) Protocol-port precedent.

### Tooling docs (for the planner)
- systemd `sd_notify` `Type=notify` / `NOTIFY_SOCKET` / `READY=1`, `RuntimeDirectory=`, `PIDFile=`,
  `TimeoutStartSec=infinity` + `Restart=always` (the supervised-restart contract) —
  https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html +
  https://www.freedesktop.org/software/systemd/man/latest/sd_notify.html
- APScheduler 3.x `BackgroundScheduler` / `IntervalTrigger` (the heartbeat tick the gate registers) —
  https://apscheduler.readthedocs.io/en/3.x/userguide.html
- `typing.Protocol` / `dataclass` / `TypeVar` (the generic `HealthResult` + the rejected health-port) —
  https://docs.python.org/3/library/typing.html
- `grimp` (the import-graph gate over the growing module) — https://pypi.org/project/grimp/

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weatherbot/ops/sdnotify.py` (`SystemdNotifier`): already pure-stdlib (`socket`/`os` only) and
  weather-clean — moves into the module's lifecycle layer with no change; the `READY=1` wire of the
  `ReadyGate`.
- `weatherbot/scheduler/daemon.py` (`gate_until_healthy` / `emit_online`): the re-probe loop +
  five-part online bundle are the lift candidates; the loop body + emit ordering move verbatim with
  only the weather/DB/Discord touches lifted out behind injected hooks (`health_check` + `on_fail` +
  `on_online`).
- `weatherbot/ops/selfcheck.py` (`run_self_check` → `CheckResult`): already the concrete app-side
  probe the injected `health_check` needs; `CheckResult(ok, reason, detail)` maps 1:1 onto the
  module's generic `HealthResult` — no app-side rewrite, just an adapter at the boundary.
- `weatherbot/ops/pidfile.py`: already threads a per-callsite path override through
  `write_pid_atomic`/`read_pid` — the seam for `identity.pid_file` is pre-drawn; only the module
  constant + the guard's hardcoded marker generalize.
- `yahir_reusable_bot/scheduler/engine.py` + `config/reload.py`: the constructor-injection +
  symmetric-best-effort-hook recipe to clone for `ReadyGate`.
- `tests/test_import_hygiene.py`: the mature, self-proven 3-gate APP-02 litmus to re-run + extend.
- The Phase-21 golden suite + ~649 tests: the standing byte-identical oracle.

### Established Patterns
- **Engines take collaborators by constructor injection + drive opaque callables/hooks**
  (`SchedulerEngine` / `ReloadEngine` precedent) — the `ReadyGate` follows this (D-01); distinct from
  the define-only `AlertSink`/`OccurrenceStore` Protocol-port pattern (which a nullary health probe
  does not warrant, D-02).
- **Weather side-effects + durable I/O ride injected best-effort hooks at today's exact points** —
  the Phase-24 D-09 rule; `stamp_health` / `stamp_tick` / the Discord ping stay app-side (D-02a) just
  as `cache.invalidate()` / the CFG-07 posts did.
- **Module-constant-with-per-callsite-override for filesystem identity** (`store.py` DEFAULT_DB_PATH /
  templates TEMPLATES_DIR / pidfile PID_FILE) — generalizes to the app-supplied `LifecycleIdentity`
  (D-03).
- **App injects WeatherBot specifics into generic module engines; the module never assembles the app**
  — rules out a module-side `compose()` (D-04); the single root is app-side `wiring.py`.
- **Litmus is a negative gate over `yahir_reusable_bot/**`; the locked term set stays weather-specific**
  — generic seam names (`SelectedContext`/`health`/`embed`-render) are allowed; the *injection*
  registry test (D-05) proves the positive half.

### Integration Points
- The new `wiring.py` `build_runtime(...)` becomes the single composition root: it constructs holder +
  `SchedulerEngine` + `ReloadEngine` + `ReadyGate` (wiring the injected `health_check` + `on_fail` +
  `on_online` + the `LifecycleIdentity`) + channel + the four injected leak points; `run_daemon` keeps
  the SIGTERM/SIGHUP installs, the gate→`scheduler.start()`→`READY` ordering, the PID write, the watch
  observer in `finally`.
- The `ReadyGate` runs BEFORE `scheduler.start()` (the gate semantics are preserved); `READY=1` is
  emitted by the `on_online` first-pass hook only after the probe passes.
- The generalized `proc_marker` guard must keep `cli.py`'s `do_reload` sender byte-identical.
- The import-hygiene + litmus gates gain new `lifecycle`-edge coverage + the positive injection-
  registry assertion — additive test/config, no production behavior change beyond the relocation.

</code_context>

<specifics>
## Specific Ideas

- The decisive live-code finding: **`stamp_health`/`stamp_tick` live in `weatherbot/weather/store.py`**
  — a literal weather path. That single fact forces durable stamping app-side (D-02a) and disqualifies
  an engine-owns-the-health-row design (D-01 Option c). The module owns zero durable I/O.
- **The four "identity facts" are not one string.** The `/proc` staleness marker is WeatherBot's
  `[project.scripts] weatherbot` console-script argv0 — independent of the pid-dir name. The
  `LifecycleIdentity` struct (D-03) carries them as separate fields rather than fusing them under one
  `name` convention baked into the module.
- The byte-identical risk concentrates in three spots the goldens pin: `stop.wait` interruptibility
  (a `systemctl stop` mid-probe must break promptly), `READY=1` reaching systemd ONLY after the probe
  passes (emit strictly after gate-returns-True + `scheduler.start()`), and the exactly-once online
  emit subsuming the startup heartbeat tick. None change semantically under the chosen design — the
  loop body + emit ordering move verbatim with weather/DB/Discord touches lifted behind hooks.
- APP-02 has two halves and the existing litmus only proves one ("no weather noun in the module"). The
  requirement's verb is *"injected, not baked"* — so the positive injection-registry test (D-05) is
  the piece that proves the second half.

</specifics>

<deferred>
## Deferred Ideas

- **`BotApp.compose()` explicit assembly object** (D-04 Option b) — the right end-state for the single
  root, but defer to **after Phase 26** so the Command Registry it should wire already exists; building
  it now is the highest golden-risk option for a structure Phase 26/27 immediately reshapes.
- **Generator-from-`LifecycleIdentity` `.service` rendering** (optionally Jinja2) — the more-elegant
  single-sourced unit template (D-03a alternative); deferred as over-built for a single-host personal
  bot. Revisit if provably single-sourcing the unit + runtime identity becomes valued.
- **`typing.Protocol` health port** (D-02 Option c) — revisit only if the lifecycle layer grows a
  second app-health operation that warrants a multi-method port.
- **PanelKit / Discord adapter physical relocation + the generic `SelectedContext[I]` type** — **Phase
  27** (PanelKit builds from the registry, injects `render`). Here only the `SelectedContext`/panel-
  cosmetics INJECTION seam is proven at the root.
- **Command Registry + dispatcher into the module** — **Phase 26**; the composition root registers
  commands but the registry mechanism relocates next phase.
- **Broadening the litmus term set** (D-05 Option c) — rejected; the locked D-13 term set stays
  weather-specific. Generic seam names are exactly what the module is meant to expose.
- **Full docstring/comment scrub of weather nouns from the module** — cosmetic; defer to the physical
  extraction (**Phase 28** / DOCS-01). The signatures-only litmus + injection-registry govern now.
- **Durable / dynamic `JobStore` impl** — JOBSTORE-V2-01, deferred to a reminder-style consumer.

None of these are scope creep — they are alternatives/extensions within the extraction domain,
consciously placed in their correct later phase.

</deferred>

---

*Phase: 25-lifecycle-ready-gate-composition-root*
*Context gathered: 2026-06-28*
