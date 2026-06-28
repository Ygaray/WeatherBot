# Phase 23: Scheduler Engine + OccurrenceStore + JobStore Seam - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Un-braid the scheduler's **mechanism** from weather **content**: carve WeatherBot's scheduling
core out of the weather-coupled `weatherbot/scheduler/daemon.py` into the `yahir_reusable_bot`
module as three weather-clean seams — (1) a generic `SchedulerEngine.register(job_id, trigger,
callback)` wrapping APScheduler, (2) exactly-once keyed on a generic `(job_id, occurrence)` via
an injected `OccurrenceStore` + an app-supplied `occurrence_of` callable, and (3) a
serialization-clean `JobStore` Protocol (in-memory impl only). Carries **SEAM-02 + SEAM-03**.

**HOW is what we clarified here. The WHAT — and most of the headline shape — is LOCKED by the
roadmap (Phase-23 detail block, ROADMAP.md L295–301) + REQUIREMENTS (SEAM-02, SEAM-03), and
behavior must stay byte-identical** (the ~649-test suite + the Phase-21 golden snapshots — the
schedule plan `(job_id, trigger spec, next_run_time)`, the DST/catch-up/exactly-once-across-reload
tests, and the briefing's persisted `sent_log` DB rows — are the oracle; any non-empty snapshot
diff is a failure to investigate, never rubber-stamped).

**Governing acceptance lens (every seam):** *"could a hypothetical reminder bot reuse this with
zero weather assumptions?"* — the engine's signatures must name no `Location` / `send_time` /
`local_date` / `forecast` (litmus grep clean).

**Cross-cutting gates re-run this phase:** PKG-01 (module imports zero app code; `grimp`-in-pytest
+ isolated-import smoke), APP-02 litmus grep (no weather noun in module signatures), BHV-01/BHV-02
(suite + goldens green).

New capabilities (durable `JobStore` impl, new channels, weather analysis) stay deferred to their
named later phases/milestones.

</domain>

<decisions>
## Implementation Decisions

The roadmap Phase-23 detail block pre-locks the headline of each area; research (4 parallel
advisor agents) confirmed that direction and surfaced the genuinely-open sub-decisions below.
Decisions marked **[roadmap-locked]** are ratified, not re-opened; the rest are the choices made
in this discussion.

### Scheduler Engine API & trigger model (SEAM-02)
- **D-01 [roadmap-locked]:** **Thin facade over APScheduler.** `SchedulerEngine.register(job_id,
  trigger, callback, *, args=None, kwargs=None, replace_existing=False)` forwards to
  `BackgroundScheduler.add_job(callback, trigger=trigger, id=job_id, args=args, kwargs=kwargs,
  replace_existing=..., misfire_grace_time=None, coalesce=True, max_instances=1)`. The **same
  native trigger object the caller built reaches `add_job` untouched** — this is what keeps the
  Phase-21 schedule-plan golden (`next_run_time`) byte-identical. APScheduler-as-trigger-type is
  an acceptable dependency (the litmus forbids *weather* nouns, not scheduler deps).
- **D-02:** **Passthrough native triggers only** — caller constructs `CronTrigger(timezone=…)` /
  `IntervalTrigger(seconds=…)` / one-shot `DateTrigger`. **No** `engine.cron()/interval()/date()`
  sugar this phase (the optional reuse affordance was considered and declined — passthrough is the
  byte-identical default and a future reminder bot can construct native triggers directly). The
  full neutral trigger-spec abstraction is deferred until a real second consumer exists.
- **D-03:** **The proven defaults move INTO the engine as invariants** — `misfire_grace_time=None`
  (recovery is owned by the sent-log + catch-up, never APScheduler misfire/coalesce, because the
  memory jobstore loses state on exit), `coalesce=True`, `max_instances=1`, per-tz. These are
  currently copy-pasted at 4 call sites; centralizing them in `register()` *reduces* drift risk
  while leaving the values reaching APScheduler unchanged.
- **D-04 [roadmap-locked]:** **Every job type re-registers through the engine** — briefing,
  forecast, uvmonitor, **and** heartbeat. "Internal" jobs are purely an app-side convention (the
  `__name__`-style id prefix + the reconcile exclusion list); the engine treats them identically.
  The engine also exposes `remove(job_id)` and `list_live_ids()` (the `get_jobs()` read) so the
  app keeps owning reconcile/catch-up rather than the engine learning those concepts.
- **D-05:** **Callback + bound data pass through opaquely** — `fire_slot`'s `args=[location, slot]`
  and its runtime `kwargs` (`holder`, `client`, `channel`, `stop_event`) pass through unchanged;
  the engine never names or inspects them. A reminder bot binds its own callable + args through
  the identical hole.
- **Rejected:** a neutral trigger-spec abstraction the engine owns (spec→`CronTrigger` translation
  is the single most likely place to silently shift `next_run_time` and break the golden, for zero
  v1 benefit with one consumer — deferred to a real second consumer).

### Exactly-once OccurrenceStore seam (SEAM-02)
- **D-06 [roadmap-locked]:** **Extract exactly-once out of `fire_slot` into a generic
  `OccurrenceStore` port + an app-supplied `occurrence_of` callable.** The engine/port speak
  `(job_id, occurrence)`; WeatherBot supplies `occurrence = local_date` (its per-tz date bucket),
  computed **app-side** from `location.timezone`/`scheduled_dt` exactly as `fire_slot` does today —
  so the engine never imports `zoneinfo` and a reminder bot defines its own occurrence semantics.
- **D-07:** **The port carries the full claim lifecycle — `claim` + `was_fired` + `release`.**
  `fire_slot`'s failure-path `release_claim` is part of the exactly-once contract (it lets a failed
  send be re-fired / caught-up), so it belongs with `claim`, not split off app-side. Keeps a
  reminder bot's exactly-once reuse complete (no re-implementing release).
- **D-08:** **Ports & Adapters, mirroring Phase-22 `AlertSink` exactly** — define `OccurrenceStore`
  as a small `@runtime_checkable typing.Protocol` in `yahir_reusable_bot/ports/`, with neutral
  param names (no weather noun), **structurally satisfied** by the existing
  `weatherbot/weather/store.py` functions with no subclassing. The weather SQLite `sent_log` stays
  the **app-side adapter**.
- **D-09:** **The adapter owns the `(job_id, occurrence)` ↔ `(location_name, send_time, local_date)`
  decomposition so `sent_log` rows stay byte-identical.** The port is the *type contract*; the
  existing `claim_slot(db_path, location.id, slot.time, local_date)` (and `was_sent` /
  `release_claim`) remain the *adapter body* unchanged. Cleanest no-drift form: `fire_slot` passes
  the already-separate `location.id` / `slot.time` / `local_date` so the adapter never concatenates
  then re-splits — the weather-shaped triple lives only inside the adapter. The load-bearing
  `INSERT OR IGNORE … rowcount==1` "exactly once" guarantee never moves.
- **Rejected:** engine-computed occurrence (roadmap chose the injected callable); engine owns its
  own generic occurrence table (would stop producing `sent_log` rows → breaks Phase-21 DB-row
  goldens + violates host-owns-persistence); `claim`+`was_fired` only with `release` stranded
  app-side (splits one lifecycle across two homes).

### JobStore Protocol & in-memory impl (SEAM-03)
- **D-10 [roadmap-locked]:** **Ship a serialization-clean `JobStore` Protocol with the in-memory /
  config-rederive impl ONLY** — durable impl deferred (JOBSTORE-V2-01, the milestone's canonical
  "design-the-seam-now, build-the-impl-later" example). This is a seam-DESIGN task, not an
  implementation task.
- **D-11:** **Minimal documented-contract seam altitude** (not a fat `BaseJobStore`-mirroring
  Protocol). The smallest surface a future durable store needs, naming `MemoryJobStore` +
  config-rederive as the shipped impl, with **zero behavior change** (goldens stay byte-identical).
  Mirrors the Phase-22 `AlertSink` altitude.
- **D-12:** **The Protocol's real payload is the encoded serialization contract**, locking the
  three constraints that are already true today so a future durable store inherits them for free:
  (1) **importable callbacks** — `fire_slot`/`fire_forecast_slot` are module-level functions
  referenceable by import path (what APScheduler pickles); (2) **picklable identity-style args** —
  `id` is a plain string, `args=[location, slot]` are pydantic models (keep picklable; never close
  a live client/channel into `args`); (3) **look-up-at-fire-time** — per-fire `kwargs` carry the
  `holder` (not a baked `config` snapshot), so a job re-resolves `holder.current()` at fire time.
- **D-13 (planner flag):** today's jobs thread **non-picklable runtime handles** (`client`,
  `channel`, `stop_event`, `holder`) through `kwargs`. The Protocol docstring MUST state that a
  *durable* impl would relocate those to a look-up-at-fire-time registry (resolved by id at fire,
  not pickled). **Naming that boundary now — building none of it — is what makes the future durable
  store a drop-in rather than a redesign.**
- **Rejected:** a Protocol over `Job`-level CRUD mirroring APScheduler `BaseJobStore` (a durable
  store subclasses `BaseJobStore` directly, so this Protocol has zero shipped consumers and leaks
  the APScheduler `Job` type into the seam); a higher-level `JobSpec`/desired-jobs registry (invents
  a second job-model parallel to APScheduler's `Job` and would refactor the byte-identical reconcile
  path the goldens pin).

### Catch-up / DST ownership + Phase-23/24 demarcation (SEAM-02 vs SEAM-04)
- **D-14:** **`plan_catchup` (catchup.py) STAYS app-side, unchanged.** Missed-slot derivation is
  irreducibly config/tz-coupled (reads `loc.timezone` / `loc.schedule` / `slot.parsed_time()` /
  `loc.id`) and is already a PURE function (injected `now_utc` + `was_sent` reader). Only its
  `was_sent` reader **rebinds onto `OccurrenceStore`**. DST-safety lives where the tz lives — in the
  planner — and stays in lockstep with the live `CronTrigger` via the shared normalized
  `day_of_week` (Pitfall 3). The 25 golden DST/catch-up tests keep oracle-ing the same function.
  "The engine performs catch-up" means **the engine provides the generic exactly-once firing path
  that the app's catch-up drives**, NOT that the engine derives missed slots.
- **D-15:** **Moves into the engine NOW (Phase 23):** the single-job `register` primitive, the
  `remove(job_id)` primitive, the `list_live_ids()` read, generic exactly-once via
  `OccurrenceStore` + `occurrence_of`, and the `JobStore` Protocol (in-memory impl). `_register_jobs`
  **splits** into "enumerate desired slots (app)" + "register one job (engine)" — the enumeration
  loop stays app-side as the future Phase-24 `desired_jobs` hook seed.
- **D-16:** **Defers to Phase 24 (SEAM-04, config hot-reload engine):** `_desired_job_ids`,
  `_reconcile_jobs`, `_restore_jobs`, `_do_reload`. These ARE the reload engine (validate →
  atomic-swap → reconcile, keep-old rollback, file-watch + SIGHUP) over an injected
  `validate`+`desired_jobs` — moving them now would hijack SEAM-04's deliverable and bake weather
  config into the supposed-to-be-weather-free engine. Same boundary discipline that held heartbeat
  out of Phase 22 → Phase 25.
- **Pull-forward flags (reject in planning):** any task that (a) puts missed-slot/DST derivation
  *inside* the engine, (b) moves `_reconcile_jobs`/`_restore_jobs`/`_do_reload` in Phase 23, or
  (c) derives `desired_jobs` as anything but an app-side hook seed.

### Claude's Discretion
- Exact module sub-layout for the engine (`scheduler/` package inside `yahir_reusable_bot/` vs a
  flatter shape) and file naming — planner/executor, guided by the existing `channels/` /
  `reliability/` / `ports/` shapes.
- Precise `SchedulerEngine` class surface beyond `register`/`remove`/`list_live_ids` (e.g. whether
  `start`/`shutdown`/the `BackgroundScheduler` instance ownership wraps too, or the app keeps the
  scheduler and the engine is a thin registrar) — shaped by what `run_daemon` actually needs to keep
  byte-identical startup ordering (announce → register → catch-up → `scheduler.start()`).
- Exact `OccurrenceStore` / `JobStore` Protocol method signatures and whether `release` is named
  `release`/`release_claim` — keep minimal and weather-clean; shaped by `fire_slot`'s real calls.
- How the daemon-internal id convention (`__heartbeat__` / `__uvmonitor__`) and the reconcile
  exclusion list are expressed against `list_live_ids()`.
- The `grimp`-graph assertion form for the growing module (new `scheduler` edges) and the
  isolated-import smoke-test extension.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & milestone contract
- `.planning/ROADMAP.md` § "Phase 23: Scheduler Engine + OccurrenceStore + JobStore Seam"
  (L293–301) — the **pre-locked design** (`SchedulerEngine.register(job_id, trigger, callback)`
  wrapping APScheduler with `misfire_grace_time=None`/`coalesce=True`/`max_instances=1`/per-tz;
  exactly-once via `OccurrenceStore.claim(job_id, occurrence)` + app-supplied `occurrence_of` =
  per-tz `local_date`; serialization-clean `JobStore` Protocol, in-memory impl only; no
  `Location`/`send_time`/`local_date`/`forecast` in engine signatures) and the 2 locked success
  criteria.
- `.planning/ROADMAP.md` § "v2.0 Bot Module Extraction" milestone header + **phase spine** (L219)
  — leaf-seams-first, split-last; establishes why reconcile/reload defers to Phase 24 and the
  durable JobStore impl is deferred.
- `.planning/REQUIREMENTS.md` § **SEAM-02** (engine + generic `(job_id, occurrence)` + DST +
  catch-up, no weather concept), § **SEAM-03** (serialization-clean `JobStore` Protocol seam;
  in-memory/config-rederive impl ships, durable deferred), and the **Cross-cutting acceptances**
  (PKG-01 enforced on 23–27; APP-02 litmus grep standing gate; BHV-01/BHV-02 re-run every phase).
  Traceability table: SEAM-02 + SEAM-03 → Phase 23.

### Prior-phase contract this phase must honor
- `.planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-CONTEXT.md` — the
  **Ports & Adapters template** this phase reuses twice (`OccurrenceStore`, `JobStore` mirror the
  D-07 `AlertSink` recipe), the flat-sibling `yahir_reusable_bot/` package layout (D-01/D-02 there),
  the `grimp`-in-pytest import gate + isolated-import smoke (D-09/D-10 there), the signatures-only
  litmus (D-11 there), and "adapt `fire_slot`, don't rewrite" (D-07 there).
- `.planning/phases/21-characterization-golden-test-harness/21-CONTEXT.md` — the golden oracle:
  the schedule-plan golden `(job_id, trigger spec, next_run_time)`, the briefing `sent_log` DB-row
  goldens, the DST/exactly-once/catch-up-across-reload tests, the discipline rule (any non-empty
  snapshot diff during extraction is a failure to investigate).
- `.planning/phases/21-characterization-golden-test-harness/21-PATTERNS.md` — move-path package
  pattern map (present in the working tree).

### Source surfaces this phase moves / touches
- `weatherbot/scheduler/daemon.py` — `fire_slot` (claim/`local_date` derivation ~L188–209,
  failure-path `release_claim`; **adapted behind `OccurrenceStore`, not moved**); `_register_jobs`
  (~L585, **split** into app-enumerate + engine-register); `_desired_job_ids` (~L683, **stays /
  Phase 24 seed**); `_reconcile_jobs`/`_restore_jobs`/`_do_reload` (~L768–874, **defer to Phase
  24**); `_run_catchup` (~L1068, `was_sent` lambda rebinds to the port); `run_daemon` (~L1344,
  startup ordering announce→register→catch-up→`scheduler.start()` must stay byte-identical);
  `_register_uvmonitor_job` (~L710) + heartbeat registration (~L1433) — re-register through engine.
- `weatherbot/scheduler/catchup.py` — `plan_catchup` + `MissedSlot` (**stays app-side**, only the
  `was_sent` reader rebinds; hardcoded 90-min `GRACE`; `fires_on`/`day_of_week` lockstep with the
  live trigger).
- `weatherbot/weather/store.py` — `claim_slot` / `was_sent` / `release_claim` (~L229–314) over the
  `sent_log` `UNIQUE(location_name, send_time, local_date)` (~L108): the **adapter bodies** behind
  `OccurrenceStore`; rows must stay byte-identical.
- `weatherbot/scheduler/__init__.py` — PEP-562 lazy `run_daemon` export + `parse_days`/`plan_catchup`
  re-exports; keep the import paths stable (exception-identity pins).
- `yahir_reusable_bot/ports/alerts.py` + `yahir_reusable_bot/ports/__init__.py` — the `AlertSink`
  Protocol convention to mirror + the barrel export to extend.
- `pyproject.toml` — `[tool.hatch.build.targets.wheel] packages` (already lists `yahir_reusable_bot`),
  `[tool.coverage.*]` source paths (must keep covering moved code), dev-dep group (`grimp` already in
  from Phase 22).

### Tooling docs (for the planner)
- APScheduler 3.x `BackgroundScheduler` / `add_job` / triggers / `BaseJobStore` (what
  "serialization-clean: importable callback + picklable id/args + lookup-at-fire-time" means there)
  — https://apscheduler.readthedocs.io/en/3.x/userguide.html
- grimp `ImportGraph` API — https://grimp.readthedocs.io/en/stable/usage.html
- `typing.Protocol` / `runtime_checkable` (structural ports) —
  https://docs.python.org/3/library/typing.html#typing.Protocol

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `yahir_reusable_bot/ports/alerts.py` (`AlertSink`): the exact Protocol-port recipe to clone for
  `OccurrenceStore` (and the altitude reference for `JobStore`) — `runtime_checkable`, neutral
  nouns, structurally satisfied by existing app functions with no subclassing.
- `weatherbot/scheduler/catchup.py` (`plan_catchup`): already a PURE, APScheduler-free, weather-
  config-driven planner with injected `now_utc` + `was_sent` — ports byte-identically; only the
  reader rebinds.
- `weatherbot/weather/store.py` (`claim_slot`/`was_sent`/`release_claim`): already the right shape
  to be the `OccurrenceStore` adapter body — the `INSERT OR IGNORE … rowcount==1` exactly-once
  primitive moves nowhere.
- The Phase-21 golden suite + ~649 tests: the standing byte-identical oracle.

### Established Patterns
- **Ports & Adapters / DI** — the milestone's recurring un-braiding move; `OccurrenceStore` is the
  2nd instance after `AlertSink`, `JobStore` the 3rd.
- **Design-the-seam-now, build-the-impl-later** — durable `JobStore` is the canonical deferred
  example; SEAM-03 is pure seam design.
- **Adapt-don't-rewrite for irreducibly-coupled orchestration** — `fire_slot` is threaded with the
  injected port, never moved/rewritten (same rule that kept `fire_slot` put in Phase 22).
- **Respect fixed phase boundaries** — reconcile/reload → Phase 24, mirroring heartbeat → Phase 25.
- The 6 move-path packages from Phase 21 (`channels`, `scheduler`, `config`, `reliability`, `ops`,
  `interactive`); `scheduler` is this phase's.

### Integration Points
- `run_daemon` is the composition root for this phase: it builds the `BackgroundScheduler`, and the
  startup ordering (announce → register all jobs → catch-up scan → `scheduler.start()`) plus the
  per-job interruptible-sleep `stop_event` threading must stay byte-identical.
- `fire_slot` is the integration seam for `OccurrenceStore` (claim/was_fired/release flow through
  the injected port); `_run_catchup`'s `was_sent` lambda is the second consumer of the same port.
- The import-hygiene + litmus gates (from Phase 22) gain new `scheduler`-edge coverage — additive
  test/config, no production behavior change beyond the relocation.

</code_context>

<specifics>
## Specific Ideas

- The single load-bearing insight: **the roadmap Phase-23 detail block already pre-decided the
  hard architectural calls** (injected `occurrence_of`, thin APScheduler facade, in-memory-only
  JobStore) — research confirmed each, so discussion focused on the sub-decisions underneath
  (trigger sugar: no; `release` in the port: yes; JobStore altitude: minimal; 23/24 split:
  primitives-now). Downstream planning should treat L295–301 as a spec, not a suggestion.
- The `(location_name, send_time, local_date)` triple ↔ generic `(job_id, occurrence)` pair is the
  one real friction point — resolved by keeping the decomposition **inside the app-side adapter**
  (pass the already-separate parts, never concat-then-resplit) so `sent_log` bytes are identical.
- "The engine performs catch-up" is a wording trap — it provides the firing path; the app derives
  what to fire. DST-safety lives in `plan_catchup`, not the engine.
- Name the durable-store boundary in the `JobStore` docstring (relocate non-picklable handles to a
  fire-time registry) **without building it** — that doc IS the SEAM-03 deliverable.

</specifics>

<deferred>
## Deferred Ideas

- **Durable / dynamic `JobStore` implementation** (runtime add/remove jobs surviving restart) —
  JOBSTORE-V2-01, the headline deferred extension point; built when a reminder-style bot makes it
  real. Only the Protocol + in-memory impl ship here.
- **`_reconcile_jobs` / `_restore_jobs` / `_do_reload` + `desired_jobs` derivation** — belong to
  **Phase 24** (Config Hot-Reload Engine / SEAM-04), their named home. Tracked as the D-16 hand-off.
- **Heartbeat as a lifecycle concern / READY-gate** — **Phase 25** (Lifecycle READY-gate + systemd
  `Type=notify`). This phase only re-registers the existing heartbeat job through the engine; it
  adds no heartbeat/health semantics.
- **Neutral trigger-spec abstraction** (`CronSpec`/`IntervalSpec`/`DateSpec` the engine translates)
  or thin `engine.cron()/interval()/date()` sugar — viable reuse affordance, deferred until a real
  second (reminder-bot) consumer exists (D-02 rejected list).
- **Full docstring/comment scrub of weather nouns from the module** — cosmetic; defer to the physical
  extraction (**Phase 28** / DOCS-01). The signatures-only litmus governs now.

None of these are scope creep — they are alternatives/extensions within the extraction domain,
consciously placed in their correct later phase.

</deferred>

---

*Phase: 23-scheduler-engine-occurrencestore-jobstore-seam*
*Context gathered: 2026-06-27*
