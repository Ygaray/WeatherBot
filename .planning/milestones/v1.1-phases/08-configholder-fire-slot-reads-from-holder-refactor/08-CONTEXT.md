# Phase 8: ConfigHolder & `fire_slot` Reads-From-Holder Refactor - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Introduce a lock-guarded `ConfigHolder` that becomes the **single owner of the live
`Config`** and hands out immutable snapshots, and refactor `fire_slot` (plus its
catch-up and schedule-announce callers) to read `holder.current()` at fire time
instead of capturing a `config` kwarg at job-registration time.

This is the **mandatory correctness prerequisite** for live reload: today a live cron
job bakes the `Config` object into its `add_job(kwargs={"config": config})` at
registration, so even if a future reload swapped in new config, unchanged jobs would
keep rendering the *stale captured* object. After this phase, an unchanged job reads
whatever the holder currently owns — so a Phase 9 reload actually changes what it
renders.

Concretely:
1. New `ConfigHolder` owning a `Config` behind a lock, exposing `current()` (returns
   the live immutable snapshot) and `replace(new_config)` (lock-guarded atomic swap).
2. `fire_slot` takes a `holder` param and reads `holder.current()` at fire time; an
   optional `config=` override wins when explicitly passed (tests / standalone fires).
3. `_register_jobs`, `_run_catchup`, and `_announce_schedule` all source config from
   the holder (one source of truth in the daemon). The heartbeat job reads no config
   and is untouched.
4. `Config` and all nested config models become `frozen=True` so a handed-out snapshot
   is truly immutable (a job that tries to mutate it raises).
5. A test proves the core promise: swapping the held config via `replace()` changes
   what an **unchanged** `fire_slot` job renders.

**Out of scope (own phases):** the reload engine itself — validation, validate-before-swap,
job re-registration/diff, SIGHUP / `weatherbot reload`, `--check-config` dry-run
(all Phase 9, CFG-01/02/04/05/06/08); file-watch auto-reload (Phase 10, CFG-03);
Discord reload reporting (Phase 11, CFG-07). `settings`/`.env` secrets stay OUTSIDE
the holder — they are a restart boundary, not reloadable (roadmap Pitfall #12).

**Closes no requirement directly** — this is a foundation/prerequisite phase that
unblocks CFG-01 and CFG-05 in Phase 9.
</domain>

<decisions>
## Implementation Decisions

### Config seam (how fire_slot gets config)
- **D-01: `holder` param + optional `config=` override.** `fire_slot` takes a
  `holder: ConfigHolder` and reads `holder.current()` at fire time. Keep an optional
  `config=` keyword that, when explicitly passed, WINS over the holder — so tests and
  standalone catch-up fires can inject a fixed config without constructing a holder.
  Live cron jobs and catch-up pass the holder (live config); the override keeps the
  test surface simple. Rejected: a holder-only required param (more churn in every
  test + catch-up), and a module/process-level holder singleton (global state, harder
  to test/inject).

### Snapshot immutability
- **D-02: `frozen=True` on `Config` and ALL nested models** (`Config`, `Location`,
  `Schedule`, `Reliability`, `WebhookIdentity`). The "immutable snapshot" guarantee is
  enforced by the type, not by discipline — a job that mutates the shared snapshot
  raises immediately. Verified low-risk: a source grep found **nothing** that mutates a
  loaded config today, so freezing breaks no existing code. Models already use
  `ConfigDict(extra="forbid")`; this adds `frozen=True` to the same `model_config`.
  Rejected: immutable-by-convention (unenforced), and freezing only the top-level
  `Config` (nested mutation still slips through).

### Holder read scope (which readers go through the holder)
- **D-03: All daemon config readers go through the holder.** `_register_jobs`
  (live `fire_slot` jobs), `_run_catchup`, and `_announce_schedule` all source config
  from `holder.current()` — one source of truth in the daemon. Catch-up and announce
  run once at startup, so runtime behavior is identical today, but the seam is uniform
  and ready for Phase 9. The heartbeat job (`_heartbeat_tick`) reads no config and is
  left untouched. Rejected: fire_slot-only (literal roadmap wording but leaves two
  config-access patterns in the daemon).

### Swap API surface (how much reload seam lands now)
- **D-04: Ship `ConfigHolder.replace(new_config)` in Phase 8** — both `current()` and
  the lock-guarded atomic `replace()` exist now. Include a Phase-8 test that calls
  `replace()` and asserts an **unchanged** `fire_slot` job renders the new config — this
  proves the whole point of the refactor and hands Phase 9 a ready seam to call.
  Explicitly OUT: the validate-before-swap boundary (that's Phase 9's reload engine);
  do not stub or pull reload-validation concerns into this phase.

### Claude's Discretion
The following are left to research/planning — no operator preference expressed:
- **Lock type** (`threading.Lock` vs `RLock`) and whether `current()` reads under the
  lock or via an atomic reference read. The daemon runs jobs on APScheduler's default
  threadpool (`max_workers=10`), so the holder must be thread-safe.
- **Read consistency within a single fire** — recommend `fire_slot` calls
  `holder.current()` ONCE at the top and threads that single snapshot through the whole
  delivery (incl. into `send_now` as `config=`), so a mid-fire `replace()` cannot tear a
  single delivery. Planner to confirm.
- **Module location / naming** of `ConfigHolder` (e.g. `weatherbot/config/holder.py`).
- **Where the holder is constructed/owned** — recommend `run_daemon` builds it from the
  loaded config and threads it into `_register_jobs` / `_run_catchup` / `_announce_schedule`,
  mirroring how `stop_event` and `channel` are threaded today.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & requirements
- `.planning/ROADMAP.md` — Phase 8 entry (goal, depends-on, the "reads holder.current()
  instead of a captured config kwarg" mandate) and Phase 9 entry (the reload engine this
  unblocks — keep its concerns OUT of Phase 8).
- `.planning/REQUIREMENTS.md` — CFG-01 (edit config, apply without restart) and CFG-05
  (reload preserves exactly-once) are the requirements this prerequisite unblocks; both
  land in Phase 9, not here.

### Code this phase refactors
- `weatherbot/scheduler/daemon.py` — `fire_slot` (signature + the `config=config` →
  `send_now` forward + `config.reliability.*` reads), `_register_jobs` (the
  `add_job(kwargs={"config": config})` capture being removed), `_run_catchup`,
  `_announce_schedule`, `run_daemon` (holder construction/ownership point).
- `weatherbot/scheduler/catchup.py` — `plan_catchup` (reads `config.locations`); confirm
  whether it sources config from the holder or stays pure-input.
- `weatherbot/config/models.py` — `Config`, `Location`, `Schedule`, `Reliability`,
  `WebhookIdentity` model_config blocks getting `frozen=True`.
- `weatherbot/config/loader.py` — `load_config` (produces the `Config` the holder will own).

### Pitfalls reference
- PITFALLS.md (roadmap "Research flag" for Phases 8–9) — Pitfall #6 (all-or-nothing
  apply / no torn live state) and Pitfall #8 (exactly-once across reload, HIGHEST RISK)
  are Phase 9 concerns but motivate WHY the holder + frozen snapshots must be correct here.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`run_daemon` threading pattern** (`daemon.py`): `stop_event` and `channel` are built
  once in `run_daemon` and threaded through `_register_jobs` / `_run_catchup`. The holder
  should follow the exact same construction-and-thread pattern.
- **`ConfigDict(extra="forbid")`** already on every config model — adding `frozen=True` is
  a one-field change to each existing `model_config`.

### Established Patterns
- **Job id keys on `name|time|days`** (P3 D-06) — unchanged this phase, but it's the stable
  id Phase 9's job-diff will rely on; the holder refactor must not disturb it.
- **Lazy in-function imports** in `daemon.py` (`send_now`, `build_channel`) to avoid import
  cycles — follow the same approach if the holder needs anything from `cli`.
- **`misfire_grace_time=None` + sent-log/catch-up ownership of recovery** — the holder
  changes WHAT config a job reads, not WHEN/whether it fires; recovery semantics are untouched.

### Integration Points
- `fire_slot` → `send_now(config=...)`: the snapshot read from `holder.current()` must be
  the same object forwarded into `send_now` (single read per fire — see Claude's Discretion).
- `fire_slot` → `config.reliability.*`: the retry-budget read also comes from the per-fire
  snapshot.
- APScheduler default threadpool (`max_workers=10`) is the concurrency context the holder's
  lock must be safe under.

</code_context>

<specifics>
## Specific Ideas

- The Phase-8 acceptance test is concrete: build a holder, register a `fire_slot` job (or
  call `fire_slot` with the holder), call `holder.replace(new_config)`, and assert the job
  now renders the NEW config — demonstrating that an *unchanged* job picks up a swap. This
  is the single most important verification of the phase.

</specifics>

<deferred>
## Deferred Ideas

- **Validate-before-swap boundary** — validating a new config before `replace()` accepts it
  belongs to Phase 9's reload engine (CFG-04, all-or-nothing apply). The holder's `replace()`
  in Phase 8 just swaps; it does not validate. Considered as an option and explicitly excluded
  to avoid pulling reload concerns into this phase.
- **Reload engine, SIGHUP / `weatherbot reload`, job diff/re-registration, `--check-config`** —
  Phase 9 (CFG-01/02/04/05/06/08).
- **`settings`/`.env` reloadability** — out of scope permanently for reload; secrets are a
  restart boundary (roadmap Pitfall #12). The holder owns `Config` only, never `Settings`.

</deferred>

---

*Phase: 8-ConfigHolder & `fire_slot` Reads-From-Holder Refactor*
*Context gathered: 2026-06-15*
