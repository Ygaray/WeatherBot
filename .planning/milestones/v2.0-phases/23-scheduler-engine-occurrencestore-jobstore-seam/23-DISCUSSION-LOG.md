# Phase 23: Scheduler Engine + OccurrenceStore + JobStore Seam - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-27
**Phase:** 23-scheduler-engine-occurrencestore-jobstore-seam
**Mode:** advisor (4 parallel research agents, calibration tier `standard`)
**Areas discussed:** Engine API & trigger model, Exactly-once OccurrenceStore seam, JobStore Protocol & in-memory impl, Catch-up/DST + Phase-24 boundary

**Framing note:** The ROADMAP Phase-23 detail block (L295–301) already pre-locks the headline
shape of all four areas (thin APScheduler facade; injected `occurrence_of` + `OccurrenceStore`;
serialization-clean in-memory-only `JobStore` Protocol; engine signatures name no weather concept).
Research confirmed each. Discussion therefore targeted the genuinely-open sub-decisions, not the
locked headlines.

---

## Engine API & trigger model

| Option | Description | Selected |
|--------|-------------|----------|
| Passthrough only | `register(...)` takes native CronTrigger/IntervalTrigger/DateTrigger; smallest diff, zero `next_run_time` drift, weather-free signature | ✓ |
| Add thin cron()/interval()/date() sugar | Passthrough still the mechanism + convenience constructors returning native triggers for future bots | |

**User's choice:** Passthrough only (Recommended)
**Notes:** Thin facade over APScheduler is roadmap-locked. The proven defaults
(`misfire_grace_time=None`, `coalesce=True`, `max_instances=1`, per-tz) move INTO `register()` as
engine invariants (lifted out of 4 call sites). All job types (briefing/forecast/uvmonitor/heartbeat)
re-register through the engine; "internal" is an app-side id convention. Neutral trigger-spec
abstraction deferred to a real second consumer.

---

## Exactly-once OccurrenceStore seam

| Option | Description | Selected |
|--------|-------------|----------|
| claim + was_fired + release in port | Full claim lifecycle on the Protocol; failure-path release is part of the exactly-once contract | ✓ |
| claim + was_fired only; release app-side | Minimal port; release_claim stays an app-side companion | |

**User's choice:** claim + was_fired + release in port (Recommended)
**Notes:** Roadmap-locked: `OccurrenceStore.claim(job_id, occurrence)` + app-supplied `occurrence_of`
callable (`local_date`). Ports & Adapters mirroring Phase-22 `AlertSink`; weather `sent_log` stays the
app-side adapter. The `(job_id, occurrence)` ↔ `(location_name, send_time, local_date)` decomposition
lives inside the adapter (pass already-separate parts, never concat-then-resplit) so `sent_log` rows
stay byte-identical. `local_date` stays computed app-side from `location.timezone` — engine never
imports `zoneinfo`.

---

## JobStore Protocol & in-memory impl

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal documented-contract seam | Smallest Protocol a durable store needs; 3 serialization constraints encoded as the contract; names MemoryJobStore + config-rederive as the impl | ✓ |
| Fuller Protocol mirroring APScheduler BaseJobStore | Job-level CRUD; maps to where a durable store plugs in but has zero shipped consumers + leaks the APScheduler Job type | |

**User's choice:** Minimal documented-contract seam (Recommended)
**Notes:** Roadmap-locked: Protocol + in-memory impl only, durable deferred (JOBSTORE-V2-01). The
contract encodes the 3 constraints already true today (importable callbacks, picklable identity-style
args, look-up-at-fire-time via `holder` in kwargs). Planner flag: the docstring must name the durable
boundary (relocate non-picklable handles `client`/`channel`/`stop_event`/`holder` to a fire-time
registry) WITHOUT building it — that doc is the SEAM-03 deliverable.

---

## Catch-up/DST + Phase-24 boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Primitives now, reconcile defers to 24 | Engine gets register/remove/list_live_ids now; reconcile/restore/do_reload + desired_jobs derivation defer to Phase 24; plan_catchup stays app-side | ✓ |
| Also move reconcile/do_reload now | Co-locate all scheduler+reload code in Phase 23 | |

**User's choice:** Primitives now, reconcile defers to 24 (Recommended)
**Notes:** `plan_catchup` stays app-side, unchanged — missed-slot/DST derivation is irreducibly
config/tz-coupled; only its `was_sent` reader rebinds onto the port. "Engine performs catch-up" =
provides the generic firing path catch-up rides, NOT derives missed slots. `_register_jobs` splits
into app-enumerate + engine-register. Pull-forward flags recorded (reject in planning): derivation
inside the engine, moving reconcile/reload in 23, or deriving `desired_jobs` as anything but an
app-side hook seed.

---

## Claude's Discretion

- Module sub-layout for the engine inside `yahir_reusable_bot/` + file naming.
- `SchedulerEngine` surface beyond register/remove/list_live_ids (whether it wraps
  start/shutdown/the BackgroundScheduler instance, or stays a thin registrar) — shaped by keeping
  `run_daemon` startup ordering byte-identical.
- Exact `OccurrenceStore` / `JobStore` Protocol method signatures + `release` naming.
- Daemon-internal id convention (`__heartbeat__`/`__uvmonitor__`) vs `list_live_ids()` + reconcile
  exclusion.
- `grimp`-graph assertion form for the new `scheduler` edges + isolated-import smoke extension.

## Deferred Ideas

- Durable/dynamic `JobStore` impl — JOBSTORE-V2-01 (built when a reminder bot makes it real).
- `_reconcile_jobs`/`_restore_jobs`/`_do_reload` + `desired_jobs` derivation — Phase 24 (SEAM-04).
- Heartbeat as a lifecycle/READY-gate concern — Phase 25.
- Neutral trigger-spec abstraction / thin trigger sugar — deferred to a real second consumer.
- Full weather-noun docstring scrub of the module — Phase 28 / DOCS-01 (signatures-only litmus now).
