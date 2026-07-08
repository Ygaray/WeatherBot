# Phase 24: Config Hot-Reload Engine - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Generalize WeatherBot's config hot-reload machinery into the `yahir_reusable_bot` module so it
runs **validate → atomic-swap → job-reconcile** (+ file-watch, SIGHUP, `check-config` dry-run,
keep-old-on-failure all-or-nothing rollback) over an **app-defined** config schema it never names
— driven by **injected** hooks. Carries **SEAM-04**. This is the highest-effort, highest-coupling
seam of the v2.0 extraction (the config seam touches every app field name).

**HOW is what we clarified here. The WHAT — and most of the headline shape — is LOCKED by the
roadmap (Phase-24 detail block, ROADMAP.md L303–308) + REQUIREMENTS (SEAM-04), and behavior must
stay byte-identical** (the ~649-test suite + the Phase-21 golden snapshots — schedule plan, the
reload reconcile-diff `+a -r ~c =u`, keep-old-rollback, exactly-once-across-reload, and the
`sent_log` DB rows — are the oracle; any non-empty snapshot diff is a failure to investigate,
never rubber-stamped).

**Governing acceptance lens (every seam):** *"could a hypothetical reminder bot reuse this with
zero weather assumptions?"* — this milestone's north star is a **reusable bot module shipped as its
own repo and imported across several future projects**, so every decision below favors the lowest
coupling + the most reuse-complete seam. The config seam must name no app field
(`Location`/`send_time`/`local_date`/`forecast`/`[uv]`); the litmus grep over the config seam must
be clean (a reminder bot supplies its own schema + `validate` + `desired_jobs`).

**Stays entirely app-side (never enters the module):** WeatherBot's `Config` / `Location` /
`UvConfig` / templates, the `[uv]` table, the CR-01 ForecastCache invalidation, the CFG-07
in-channel reject/applied posts, and the restart-boundary **policy** (which keys are restart-only).

**Cross-cutting gates re-run this phase:** PKG-01 (module imports zero app code; `grimp`-in-pytest
+ isolated-import smoke), APP-02 litmus grep (no weather noun in module config-seam signatures),
BHV-01/BHV-02 (suite + goldens green).

New capabilities (durable `JobStore` impl, lifecycle READY-gate, new channels) stay deferred to
their named later phases/milestones.

</domain>

<decisions>
## Implementation Decisions

The roadmap Phase-24 detail block pre-locks the headline (generic `ConfigHolder[T]`, `ReloadEngine`
running validate→swap→reconcile, watch + SIGHUP, `check-config`, keep-old rollback, injected
`validate`/`desired_jobs`, the pydantic-generic-validation pitfall). Four parallel advisor research
agents (read the live code) confirmed the direction and surfaced the genuinely-open sub-decisions
below. **The user delegated the final calls** ("you chose for me"), anchored on the reusable-module
goal — all four picks below also minimize byte-identical risk. Decisions marked **[roadmap-locked]**
are ratified, not re-opened; **[DEVIATION]** decisions intentionally override the literal roadmap
wording with a research-backed reason (the planner must NOT "correct" them back).

### Reconcile generalization model (SEAM-04) — the crux
- **D-01 [DEVIATION from roadmap `desired_jobs(cfg)→set[JobSpec]`]:** **The injected job-deriver
  returns `set[str]` (stable job ids), and a SECOND injected `register_jobs(cfg)` registrar runs the
  ADD phase.** The module's `ReloadEngine` owns the genuinely-reusable orchestration — the id-keyed
  diff (`desired - live` = add, `desired & live` = unchanged, `live - desired` = remove), the
  remove, and the all-or-nothing rollback — while *what a job actually is* (briefing / forecast /
  future reminder) stays an app concern supplied through `register_jobs`. WeatherBot's
  `_register_jobs` canonical builder is kept **verbatim** and injected, not moved.
  - **Why over the roadmap's `set[JobSpec]` (Option A):** the live code (`_reconcile_jobs`,
    daemon.py L775–845) ALREADY computes its entire diff from `set[str]` and ADDs via a *separate*
    `_register_jobs(..., replace_existing=True)` call — the seam line is already drawn on the
    `set[str]` boundary, so this is a near-verbatim lift. `set[JobSpec]` would force re-deriving
    `CronTrigger(timezone=…)` + the `args=[location,slot]` / `kwargs={holder,…}` threading inside a
    spec object — the single most likely place to silently shift `next_run_time` and break the
    Phase-21 schedule-plan golden — AND re-opens **Phase-23 D-10's explicit rejection** of a
    `JobSpec`/desired-jobs registry. A `JobSpec` does not actually move more reusable logic into the
    module (the app still constructs id+trigger+callback+args either way); it only adds risk now.
- **D-01a (registrar contract):** the injected `register_jobs(cfg)` registers the **full desired
  set** as an idempotent swap (`add_job(replace_existing=True)` for every enabled slot), NOT just the
  newly-added delta — so an unchanged id rides the holder swap and a new id is created in the same
  pass. This must be documented in the hook's contract so a future reminder bot's registrar does not
  register only `added` ids and silently break the holder-swap-of-unchanged-jobs behavior.
- **Load-bearing cases that fall out for free** (because the diff keys on the id string):
  a **send_time/days edit** changes the `name|time|days` id → new id in `desired - live` (ADD) + old
  id in `live - desired` (REMOVE) = one `+1 -1`; a **disabled slot** is filtered by `if slot.enabled`
  in both the deriver and the registrar → pure REMOVE, no churn. Both already pass the Phase-21
  reload-reconcile goldens.
- **Rejected:** `desired_jobs→set[JobSpec]` with engine-owned registration (Option A — roadmap text;
  re-opens D-10, highest golden risk); thin-passthrough `JobSpec` (Option D — defer until a real
  second consumer needs the module to own registration).

### ConfigHolder[T] generic + the pydantic-v2 validation pitfall (SEAM-04)
- **D-02 [DEVIATION from roadmap "holding an app-defined frozen `BaseConfig`"]:** **`ConfigHolder[T]`
  uses an UNBOUND `TypeVar("T")`; the module ships NO `BaseConfig` base class for apps to subclass.**
  "BaseConfig" becomes the *conceptual role of `T`* (the app's frozen config), not a literal module
  type. The holder stays a pure storage cell — it NEVER calls pydantic.
  - **Why over a bound `TypeVar`/module `BaseConfig` (Option B):** for a module imported across
    several future repos, forcing every consuming app to inherit a module base class is needless
    coupling; an unbound `T` lets any bot pass its own config type with zero inheritance — the
    cleanest cross-repo import story. The bound buys little (validation is injected anyway) and its
    mere existence *tempts* the fatal `BaseConfig.model_validate()` call. If matching the roadmap
    wording is later judged more important than the looser coupling, Option B (an empty frozen
    `BaseConfig` the app subclasses) was verified harmless to WeatherBot's `extra="forbid"` /
    validators / frozen — but A is the chosen default.
- **D-03 [roadmap-locked — the pitfall]:** **Validation routes ONLY through the app's concrete
  injected `validate(path) → T` callable; the module never validates the config itself.** WeatherBot
  already does the right thing: `validate_config_and_templates(path) → Config` (loader.py L99)
  validates the *concrete* `Config` with all `locations`/`[uv]`/`Location` subfields, `extra="forbid"`,
  and field validators intact. The empirically-confirmed pydantic-v2 facts that make this mandatory:
  (1) `BaseConfig.model_validate(subclass_data)` returns a bare base and **silently discards every
  subclass field** (round-trips to `{}`); (2) a `Generic[T]` holder **cannot self-parametrize at
  runtime** — `TypeVar` is erased, so `Holder[AppConfig]()` reports empty `get_args()` and cannot
  reconstruct the concrete type to build a `TypeAdapter`. The injected validator is typed `-> T` (or
  `-> BaseConfig` conceptually) but returns the full concrete `Config` (covariant; `isinstance` holds).
- **D-03a:** the holder's concurrency contract is **preserved byte-for-byte**: `current()` is
  lock-free (one atomic `LOAD_ATTR` under the GIL) and `replace()` is a locked `STORE_ATTR`. Only the
  type annotations generalize; the mechanism does not change (`test_concurrent_read_swap_safe` stays
  the oracle).
- **Rejected:** holder-validates-internally via `TypeAdapter(T)`/`Generic[T]` self-parametrization
  (the named anti-pattern — broken by TypeVar erasure, drops fields); non-generic `object` store
  (Option D — discards the static typing `current() -> Config` the daemon already relies on).

### Trigger ownership — watch + SIGHUP + check-config (SEAM-04)
- **D-04 [roadmap-locked direction]:** **The module owns the reusable trigger machinery.** The
  `ReloadEngine` owns: the core `reload(path)` (validate→swap→reconcile→rollback), a
  `request_reload()` / `service_pending()` flag pair, and an **optional** `start_watching(dirs,
  filter)` that spawns the watchfiles observer thread. The whole reason the module exists is so each
  new bot does NOT re-hand-write the ~100 LOC of pitfall-dense file-watch/reload plumbing — capturing
  it here is the reuse payoff (Option B).
- **D-05 [the load-bearing invariant]:** **Reload work runs ONLY on the host's main poll thread,
  never re-entrantly in a signal handler or on the observer thread (Pitfall #6/#9).** `request_reload()`
  is flag-set-only (safe to call from the SIGHUP handler AND the watch thread); `service_pending()`
  runs the actual reload synchronously on whatever thread the caller invokes it from — and the app
  calls it from the main loop. The app KEEPS: the SIGHUP install (its handler now calls
  `engine.request_reload()` instead of `.set()`ing its own Event), the main poll loop, and the
  byte-identical startup ordering (announce → register → catch-up → `scheduler.start()`). The
  `reload_requested` Event ownership moves into the engine; a clean `stop`/join contract lets the
  app's existing `finally` join the engine-owned watch thread.
  - **Why not Option C (engine owns full `start()/stop()` lifecycle incl. SIGHUP install):**
    disqualified — a library seizing the process-global SIGHUP handler is hostile to any host, and
    servicing its own flag on an internal thread *breaks* the main-thread invariant. Mirrors Phase-23
    `SchedulerEngine` owning NO lifecycle. **Fallback if the planner wants Phase 24 minimal:** Option
    A (engine owns only `reload()`; all triggers stay app-side) is strictly safer for the goldens but
    leaves the watch plumbing duplicated per host — accept only if observer-thread extraction is
    explicitly deferred.
- **D-06 (check-config dry-run):** a thin **`engine.check(path)`** runs PHASE-1 validate-only (calls
  the injected `validate`, no swap, no reconcile, no scheduler touch) and returns a structured
  pass/fail; the `weatherbot check` CLI command stays a ~3-line app-side wrapper mapping that result
  to an exit code. De-dups the validator path; CLI parsing/exit-codes/stdout stay app-specific.
- **`__heartbeat__` / `__uvmonitor__` survival is unaffected** by this split — their exclusion lives
  inside the reconcile/`desired_jobs` hook (an app-side id convention), not in the trigger layer.

### ReloadEngine surface + hook injection + rollback home (SEAM-04)
- **D-07:** **Constructor-injected dependencies + thin verbs** — `ReloadEngine(holder,
  scheduler_engine, *, validate, desired_jobs, register_jobs, on_applied=None, on_rejected=None)`
  exposing `reload(path)` / `check(path)`. A consuming bot wires its validator, job-deriver,
  registrar, and side-effect callbacks ONCE at construction, then drives by path/SIGHUP — the most
  reuse-complete surface. Directly continues Phase-23 `SchedulerEngine(scheduler)`'s
  constructor-injection + opaque-passthrough precedent.
  - **Why not per-call hooks (Option B):** re-threading every dep on every SIGHUP/watch tick is noise
    for a long-lived daemon and diverges from the established engine shape.
- **D-08:** **The engine owns the rollback CONTROL FLOW; the reconcile + restore STEPS are injected
  callables it invokes opaquely.** "Engine owns rollback" = the engine owns the verbatim two-phase
  skeleton (`old_cfg = holder.current()` → `holder.replace(new_cfg)` → reconcile → on any throw
  `holder.replace(old_cfg)` + restore-old-jobs + re-raise; daemon.py L944–978). But because reconcile
  /restore need six weather-runtime handles (`db_path`/`settings`/`client`/`channel`/`stop_event` +
  scheduler) and the desired set is app-derived, those steps are injected — same opaque-passthrough
  discipline `SchedulerEngine` uses for `callback`/`args`/`kwargs`. Keep-old contract stays
  byte-identical: a validator raise leaves holder+jobs untouched and re-raises; a reconcile throw
  rolls both back and re-raises.
- **D-09:** **Weather side-effects ride symmetric injected hooks invoked at today's exact points** —
  `on_rejected(exc)` fires immediately before the validator re-raise (preserving the CFG-07 "⛔
  rejected" post-then-raise timing, daemon.py L931–938), `on_applied(summary)` fires at the
  committed-success point alongside where CR-01 `cache.invalidate()` already lives (L997–1015). Each
  hook is best-effort (failure logged + swallowed, never masks the engine's own result). The module
  surface names no weather noun; the posts + ForecastCache invalidation stay app-supplied closures.
  - **Why not a returned `ReloadResult` (Option C):** it can't honor "post-then-raise" on the reject
    path without either swallowing the re-raise (changing the daemon's outer `except`-swallow at
    L1649 and risking the keep-old goldens) or losing the rejection the app needed to post. Hybrid
    (Option D — `on_applied` hook + plain reject re-raise) is an acceptable simpler fallback if
    symmetric hooks feel over-built.

### Claude's Discretion
- Exact module sub-layout for the reload seam (`config/` package inside `yahir_reusable_bot/` holding
  `ConfigHolder[T]` + `ReloadEngine`, vs a flatter shape) and file naming — planner/executor, guided
  by the existing `channels/` / `reliability/` / `scheduler/` / `ports/` shapes.
- Precise `ReloadEngine` method names beyond `reload`/`check`/`request_reload`/`service_pending`/
  `start_watching` (e.g. whether `stop`/join is a method or a context-manager), and the exact
  `on_applied`/`on_rejected`/`register_jobs` parameter signatures — keep minimal and weather-clean;
  shaped by what `run_daemon` actually needs to stay byte-identical.
- How the watch-filter's host knowledge (config basename + referenced template paths) is injected into
  `start_watching` (an injected filter callable vs a small spec), and how `watch_dirs_ref` re-derive
  (today daemon.py ~L1017–1026) moves into the engine that owns the thread.
- The `grimp`-graph assertion form for the growing module (new `config` reload edges) and the
  isolated-import smoke-test extension; the precise litmus-grep target set for the config seam.
- Whether `ConfigHolder` and `ReloadEngine` are separate classes (recommended) or the engine holds the
  holder internally — shaped by how `fire_slot`/`_uv_monitor_tick` read `holder.current()` at fire time.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & milestone contract
- `.planning/ROADMAP.md` § "Phase 24: Config Hot-Reload Engine" (L303–308) — the **pre-locked
  design** (generic `ConfigHolder[T]` lock-free `current()`/locked `replace()` over an app-defined
  frozen config; `ReloadEngine` validate→atomic-swap→job-reconcile + file-watch + SIGHUP +
  `check-config` + keep-old all-or-nothing rollback; injected `validate(path)→BaseConfig` +
  `desired_jobs(cfg)→set[JobSpec]`; validation through the app validator callable NOT an
  unparametrized pydantic generic; `[uv]`/`Location`/templates + restart-policy stay app-side) and
  the 4 locked success criteria. **NOTE the two deliberate deviations recorded above** (D-01:
  `set[str]`+`register_jobs` instead of `set[JobSpec]`; D-02: unbound `TypeVar`, no literal module
  `BaseConfig`) — these are ratified, do not "correct" them back.
- `.planning/ROADMAP.md` § "v2.0 Bot Module Extraction" milestone header + phase spine — leaf-seams-
  first, split-last; establishes why the config seam is the highest-coupling extraction and why
  lifecycle/READY-gate defers to Phase 25.
- `.planning/REQUIREMENTS.md` § **SEAM-04** (immutable `ConfigHolder[T]` snapshots, validate→swap→
  reconcile, watch+SIGHUP, `check-config`, keep-old, over injected `validate`+`desired_jobs`, knowing
  no app field names) and the **Cross-cutting acceptances** (PKG-01 on 23–27; APP-02 litmus standing
  gate; BHV-01/BHV-02 re-run every phase). Traceability: SEAM-04 → Phase 24.

### Prior-phase contracts this phase must honor
- `.planning/phases/23-scheduler-engine-occurrencestore-jobstore-seam/23-CONTEXT.md` — the **D-16
  hand-off** that explicitly defers `_desired_job_ids`/`_reconcile_jobs`/`_restore_jobs`/`_do_reload`
  to THIS phase; **D-10's rejection of a `JobSpec`/desired-jobs registry** (the basis for D-01's
  `set[str]` choice); the `SchedulerEngine.register`/`remove`/`list_live_ids` surface this phase's
  reconcile drives through; the constructor-injection + opaque-passthrough precedent (basis for D-07).
- `.planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-CONTEXT.md` — the Ports
  & Adapters / DI template, the flat-sibling `yahir_reusable_bot/` package layout, the `grimp`-in-
  pytest import gate + isolated-import smoke, the signatures-only litmus, and "adapt the orchestrator,
  don't rewrite it" (basis for keeping `_register_jobs`/`fire_slot` app-side).
- `.planning/phases/21-characterization-golden-test-harness/21-CONTEXT.md` — the golden oracle: the
  schedule-plan golden `(job_id, trigger spec, next_run_time)`, the reload reconcile-diff `+a -r ~c
  =u`, the keep-old-rollback / exactly-once-across-reload tests, the `sent_log` DB-row goldens, and the
  discipline rule (any non-empty snapshot diff during extraction is a failure to investigate).
- `.planning/phases/21-characterization-golden-test-harness/21-PATTERNS.md` — move-path package
  pattern map (present in the working tree).

### Source surfaces this phase moves / touches
- `weatherbot/config/holder.py` — the current weather-typed `ConfigHolder` (`current()` lock-free
  `LOAD_ATTR` / `replace()` locked `STORE_ATTR`, no checking, secrets never enter) → **generalized to
  `ConfigHolder[T]`** in the module, mechanism byte-identical (D-02/D-03a).
- `weatherbot/scheduler/daemon.py` — `_desired_job_ids` (~L689, → the injected `desired_jobs(cfg)`
  hook returning `set[str]`), `_reconcile_jobs` (~L775, → the engine's id-keyed diff + the injected
  `register_jobs` ADD phase), `_restore_jobs` (~L848, → the engine's injected restore step),
  `_do_reload` (~L879, → `ReloadEngine.reload()` two-phase skeleton + `on_applied`/`on_rejected` at
  L931–938 / L997–1015), the watchfiles observer + `_watch_filter` + `watch_dirs_ref` re-derive
  (~L1017–1026, L1240–1280, → `start_watching`), the SIGHUP install + `reload_requested` Event
  (`_install_reload_signal` ~L1331–1351, → `request_reload()`), the main poll-loop servicing
  (~L1621–1654, → `service_pending()`), `run_self_check` (~L1135, → `engine.check()`), and the
  byte-identical `run_daemon` startup ordering (~L1429–1474, 1553).
- `weatherbot/config/loader.py` — `validate_config_and_templates(path) -> Config` (~L99): the ONE
  shared offline validator → **the injected `validate(path)→T` hook** (D-03). Stays app-side, returns
  the concrete `Config`.
- `weatherbot/config/models.py` — `Config`/`Location`/`UvConfig` (all `frozen=True, extra="forbid"`):
  **stay entirely app-side**; `T` is bound to `Config` only by the app's injected hooks, never by the
  module.
- `yahir_reusable_bot/scheduler/engine.py` — `SchedulerEngine(scheduler)` (`register`/`remove`/
  `list_live_ids`): the constructor-injection + opaque-passthrough precedent to mirror, and the
  collaborator the reconcile remove-phase drives.
- `yahir_reusable_bot/ports/` + `pyproject.toml` — the package layout to extend (`[tool.hatch...
  packages]` already lists `yahir_reusable_bot`; `[tool.coverage]` must keep covering moved code;
  `grimp`/`watchfiles` already in deps).

### Tooling docs (for the planner)
- pydantic-v2 (2.13.x) `model_validate` / `TypeAdapter` / generics & inheritance — **why validating
  on an unparametrized base or a `Generic[T]` self-parametrization drops subclass fields** —
  https://docs.python.org/3/library/typing.html#typing.TypeVar +
  https://docs.pydantic.dev/2.13/concepts/models/ + https://docs.pydantic.dev/2.13/concepts/type_adapter/
- watchfiles `watch` / filters / `yield_on_timeout` (the observer thread the engine owns) —
  https://watchfiles.helpmanual.io/
- APScheduler 3.x `BackgroundScheduler` / `add_job(replace_existing=True)` / `get_jobs` (the reconcile
  add/remove primitives via `SchedulerEngine`) — https://apscheduler.readthedocs.io/en/3.x/userguide.html
- `typing.Protocol` / `runtime_checkable`, `TypeVar`, `Generic` (the generic holder) —
  https://docs.python.org/3/library/typing.html

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weatherbot/config/holder.py` (`ConfigHolder`): already the exact lock-free-read / locked-swap cell
  to generalize to `ConfigHolder[T]` — only the type annotations change; the GIL-atomicity contract
  and its `test_concurrent_read_swap_safe` oracle move unchanged.
- `weatherbot/scheduler/daemon.py` (`_reconcile_jobs`): the diff is ALREADY computed from `set[str]`
  with the ADD phase delegated to a separate `_register_jobs(..., replace_existing=True)` call — the
  seam line is pre-drawn on the `set[str]` boundary, making D-01 a near-verbatim lift.
- `weatherbot/config/loader.py` (`validate_config_and_templates`): already the concrete-class offline
  validator the injected `validate` hook needs — returns full `Config`, no module change required.
- `yahir_reusable_bot/scheduler/engine.py` (`SchedulerEngine`): the constructor-injection +
  opaque-passthrough recipe to clone for `ReloadEngine`, and the collaborator the reconcile drives.
- The Phase-21 golden suite + ~649 tests: the standing byte-identical oracle.

### Established Patterns
- **Engines take collaborators by constructor injection + drive opaque callables** (`SchedulerEngine`
  precedent) — distinct from the define-only `AlertSink`/`OccurrenceStore` Protocol pattern; the
  reload orchestrator is an active engine, so it follows the engine branch (D-07/D-08).
- **Adapt-don't-rewrite for irreducibly-coupled orchestration** — `_register_jobs`/`fire_slot`/the
  validator are injected, never moved/rewritten (same rule that kept `fire_slot` put in Phase 22/23).
- **Reload runs on the main thread only** — flag-set-only triggers + main-loop servicing; a library
  never seizes SIGHUP nor services its own flag on a side thread (D-05).
- **Design-the-seam-now for cross-repo reuse** — the module owns the reusable orchestration; per-app
  specifics (config shape, job type, side-effects) are injected, so a reminder bot reuses the whole
  engine with zero weather assumptions.

### Integration Points
- `run_daemon` is this phase's composition root: it constructs the `ReloadEngine` (wiring `holder`,
  the `SchedulerEngine`, the injected `validate`/`desired_jobs`/`register_jobs`/`on_applied`/
  `on_rejected`), keeps the SIGHUP install + main poll loop calling `service_pending()`, and preserves
  the byte-identical startup ordering. (Full consolidation of wiring is Phase-25's composition-root
  job; here `run_daemon` keeps its current call sites.)
- The watch observer thread becomes engine-owned via `start_watching`; the app's `finally` joins it
  through a `stop` contract.
- The import-hygiene + litmus gates gain new `config`-reload-edge coverage — additive test/config, no
  production behavior change beyond the relocation.

</code_context>

<specifics>
## Specific Ideas

- The single load-bearing insight: **the live `_reconcile_jobs` already splits diff (`set[str]`) from
  job-building (`_register_jobs`)** — so generalizing it is a relocation along an existing seam, not a
  redesign. The roadmap's `set[JobSpec]` wording was written before that factoring was confirmed;
  D-01 amends it.
- **"app-defined frozen `BaseConfig`" is a role, not a module class** (D-02). For a module imported
  across several repos, the cleanest contract is "give me your config type + your validator," with no
  inheritance demanded — an unbound `TypeVar` expresses exactly that.
- The pydantic pitfall is real and confirmed: never let the module call pydantic on the config — the
  app's concrete validator is the only safe path (validating on the base silently yields `{}`).
- The reject/applied in-channel posts and ForecastCache invalidation are **weather side-effects pinned
  to today's exact timing** (post-then-raise on reject) — symmetric `on_applied`/`on_rejected` hooks
  preserve that timing while keeping the module surface weather-noun-free.

</specifics>

<deferred>
## Deferred Ideas

- **`desired_jobs→set[JobSpec]` with engine-owned registration** (and the thin-passthrough `JobSpec`
  variant) — a viable evolution once a real second (reminder-bot) consumer needs the module to own job
  *construction*, not just orchestration. Deferred per D-01 (and Phase-23 D-10); revisit at the
  physical split / first real second consumer.
- **A literal module `BaseConfig` base class** (Option B for the holder) — kept on the table if
  matching the roadmap wording or sharing common config behavior across bots later outweighs the
  looser unbound-`TypeVar` coupling. Verified harmless; not adopted now.
- **Engine owning the full trigger lifecycle (`start()/stop()` incl. SIGHUP install)** — rejected for
  the main-thread / process-global-signal reasons (D-05); a reminder bot keeps its own main loop and
  signal map.
- **Lifecycle READY-gate / systemd `Type=notify` / heartbeat-as-health** — **Phase 25** (SEAM-05).
  This phase touches none of the restart boundary or READY gate; the holder never sees secrets/.env.
- **Single composition-root consolidation of all wiring** — **Phase 25** (APP-01/APP-02). Here
  `run_daemon` keeps its existing call sites; it only gains the `ReloadEngine` construction.
- **Durable / dynamic `JobStore` impl** — JOBSTORE-V2-01, deferred to a reminder-style consumer
  (designed in Phase 23).
- **Full docstring/comment scrub of weather nouns from the module** — cosmetic; defer to the physical
  extraction (**Phase 28** / DOCS-01). The signatures-only litmus governs now.

None of these are scope creep — they are alternatives/extensions within the extraction domain,
consciously placed in their correct later phase.

</deferred>

---

*Phase: 24-config-hot-reload-engine*
*Context gathered: 2026-06-27*
