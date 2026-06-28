---
phase: 23-scheduler-engine-occurrencestore-jobstore-seam
reviewed: 2026-06-27T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - yahir_reusable_bot/scheduler/engine.py
  - yahir_reusable_bot/scheduler/__init__.py
  - yahir_reusable_bot/ports/occurrence.py
  - yahir_reusable_bot/ports/jobstore.py
  - yahir_reusable_bot/ports/__init__.py
  - weatherbot/scheduler/daemon.py
  - tests/test_scheduler_engine.py
  - tests/test_ports.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 23: Code Review Report

**Reviewed:** 2026-06-27
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

This phase un-braids WeatherBot's scheduler *mechanism* from weather *content*: a new
`SchedulerEngine` thin registrar in `yahir_reusable_bot` now owns the three invariant
`add_job` options (`misfire_grace_time=None`, `coalesce=True`, `max_instances=1`), and all
four daemon job types (briefing, forecast, heartbeat, uvmonitor) register through
`engine.register(...)` while `_reconcile_jobs` reads/removes through
`engine.list_live_ids()` / `engine.remove()`. Two define-only `@runtime_checkable` Protocols
(`OccurrenceStore`, `JobStore` + `MemoryJobStore`) ship as the next seam.

I verified the daemon rebind against the pre-extraction diff and at runtime:

- **Behavior-preservation holds for the rebind itself.** Every `add_job` call site lost its
  inline `misfire_grace_time`/`coalesce` (and uvmonitor's explicit `max_instances`) and gained
  the engine. I confirmed at runtime that the engine sets all three options explicitly on a
  non-started scheduler, that briefing/heartbeat sites which previously *omitted*
  `max_instances` are byte-identical to APScheduler's own default-of-1, and that `args`,
  `kwargs`, `id`, and `replace_existing` all forward with identical effective values. No job
  silently lost an option; no call shape drifted; the `__heartbeat__`/`__uvmonitor__` reconcile
  exclusion is preserved verbatim.
- **The two new Wave-0 test files are sound and non-vacuous.** I reproduced the
  explicit-vs-deferred-default distinction the read-back test rests on (an explicit
  `max_instances=1` is readable pre-start; a bare default is not, raising `AttributeError`
  until `start(paused=True)`), confirming the engine test genuinely proves the baking rather
  than reading back a coincidental default. `ruff` and the 8 new tests are green.

The findings below are NOT in the rebind correctness (that is clean). They are in the
**seam-design soundness** of the two new ports — specifically a claim/shape mismatch between
`OccurrenceStore` and the concrete `claim_slot` it purports to abstract, the always-true
`isinstance` trap of the empty `JobStore` Protocol, and a test-coverage gap around it. Per the
review brief I do NOT flag the define-only ports as "unused" — that is the intended deliverable.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: `OccurrenceStore` Protocol arity does not match the concrete `claim_slot` it claims any host adapter satisfies

**File:** `yahir_reusable_bot/ports/occurrence.py:43-77` (and the docstring claim at `14-15`, `38-40`)
**Issue:** The port's docstring asserts: *"a host's existing `INSERT OR IGNORE … rowcount == 1`
adapter satisfies it without any subclassing or registration (D-08)"* and that the only renaming
is the slot key → neutral `key`. But the shipped concrete gate is
`claim_slot(db_path, location_name, send_time, local_date)` — a **handle plus THREE** identity
components (`weatherbot/weather/store.py:251`). The Protocol's `claim(handle, key, occurrence)`
exposes a **handle plus TWO** (`key`, `occurrence`). The three-part real key
(`location, send_time, local_date`) has been collapsed into two neutral slots, so the existing
adapter does **not** structurally satisfy this Protocol the way the docstring claims — a future
Phase-24+ wiring that takes the docstring at face value (`def claim(handle, key, occurrence)`
adapter delegating to `claim_slot`) has to invent how to pack three real components into two
Protocol params (e.g. composite-encode `send_time|local_date` into `occurrence`), which is an
undocumented, error-prone mapping at the exactly-once boundary — precisely the place a silent
key-collision becomes a missed or double-sent briefing. This is a seam-design correctness gap,
not a runtime bug today (nothing is injected yet), but the contract as written is misleading.
**Fix:** Either make the Protocol shape match the real key, or document the collapse explicitly.
Preferred — match reality so the "existing adapter satisfies it" claim is true:
```python
def claim(
    self,
    handle: str | os.PathLike[str],
    key: str,          # location identity
    send_time: str,    # slot time-of-day
    occurrence: str,   # local_date (the per-fire occurrence)
) -> bool: ...
```
If the two-arg shape is intentional, change the docstring to state that the host adapter must
compose its `(send_time, local_date)` into the single `occurrence` slot, and name the encoding
contract (separator, collision-safety) — do not claim the existing adapter satisfies it as-is.

### WR-02: Empty `@runtime_checkable` `JobStore` Protocol makes `isinstance(anything, JobStore)` unconditionally `True`

**File:** `yahir_reusable_bot/ports/jobstore.py:21-58`
**Issue:** `JobStore` is `@runtime_checkable` with a body of only a docstring + `...` (no methods).
A runtime_checkable Protocol with zero members matches **every** object structurally: I confirmed
`isinstance(object(), JobStore)` and `isinstance(42, JobStore)` both return `True`. The whole
value of `@runtime_checkable` is to enable `isinstance`, but here it is a guard that can never
fail — so the moment any future code does `isinstance(x, JobStore)` to validate a host-supplied
store, it admits literally anything (an int, `None`-wrapping object, a half-built adapter),
silently. That is a latent correctness trap at exactly the injection boundary this port exists to
guard. The contract genuinely lives in the docstring (intended), but pairing that with
`@runtime_checkable` advertises a structural check that does not exist.
**Fix:** Drop `@runtime_checkable` from `JobStore` (keep it on `OccurrenceStore`, which has real
methods) so no caller is tempted to lean on a vacuous `isinstance`; OR give the Protocol at least
one method that a real durable store must expose (e.g. `add_job` / `get_jobs`) so the structural
check has teeth. If `@runtime_checkable` is retained on a memberless Protocol deliberately, add a
module comment stating the `isinstance`-is-always-True hazard so a future maintainer is not misled.

### WR-03: `test_ports.py` has no structural test for `JobStore` — the always-true-isinstance hazard is untested

**File:** `tests/test_ports.py:30-33` (vs the `OccurrenceStore` coverage at `36-56`)
**Issue:** `OccurrenceStore` gets a real structural test — a conforming class is accepted, a
`_PartialStore` missing a method is rejected (`test_occurrence_store_structurally_satisfied_by_instance`).
`JobStore` gets only `test_jobstore_is_runtime_checkable_protocol`, which asserts
`issubclass(JobStore, typing.Protocol)` and `_is_runtime_protocol is True`. There is no test
pinning what `isinstance(x, JobStore)` actually does, so the WR-02 footgun (every object matches)
is invisible to the suite — a future maintainer who adds a method to `JobStore` (tightening the
contract) would not see a single test change, and a future maintainer who relies on the vacuous
match would get no warning. For a phase whose explicit deliverable is *the contract*, the
contract's most surprising behavior is the one left unasserted.
**Fix:** Add a test that documents the current (intended-or-not) semantics so it is a conscious,
pinned decision rather than an accident:
```python
def test_jobstore_protocol_has_no_structural_members():
    """JobStore is contract-only: with no methods, runtime_checkable isinstance is vacuous.

    Pins the deliberate define-only shape so adding a real method (tightening the
    contract) is a visible, reviewed change — not a silent behavior flip.
    """
    assert isinstance(object(), JobStore)  # vacuous match — documented, see jobstore.py
    assert isinstance(MemoryJobStore(), JobStore)
```
(If WR-02 is fixed by adding a method, invert this to a real accept/reject pair like the
`OccurrenceStore` test.)

## Info

### IN-01: `SchedulerEngine(scheduler)` re-instantiated per call site rather than constructed once

**File:** `weatherbot/scheduler/daemon.py:624, 760, 813, 1446`
**Issue:** `_register_jobs`, `_register_uvmonitor_job`, `_reconcile_jobs`, and the inline
heartbeat registration each construct a fresh `SchedulerEngine(scheduler)`. The engine is a
stateless non-owning facade (it only holds a reference), so this is harmless and correct — but it
is mild repetition of a wrapper around the same `scheduler` instance within a single
`run_daemon` call. Not a bug; noting only because a future durable-jobstore or instrumentation
seam on the engine would benefit from a single shared instance threaded through, the same way
`holder`/`stop`/`channel` already are.
**Fix:** Optional — construct one `engine = SchedulerEngine(scheduler)` in `run_daemon` alongside
`holder`/`stop` and thread it into the registration helpers, so there is one engine per process
the way there is one scheduler. Leave as-is if the per-call construction reads clearer.

### IN-02: `SchedulerEngine.register` exposes only a subset of `add_job`; no docstring note that `next_run_time`/`name`/`jobstore` are intentionally unsupported

**File:** `yahir_reusable_bot/scheduler/engine.py:44-70`
**Issue:** `register(...)` forwards `job_id`, `trigger`, `callback`, `args`, `kwargs`,
`replace_existing` and bakes the three invariant options. That is exactly the set today's four
call sites use, which is correct and deliberately minimal (D-02 rejects trigger-sugar). But a
reusable-bot consumer reading the signature has no signal that omitted `add_job` knobs
(`name`, `next_run_time`, `jobstore`, `executor`) are *intentionally* unavailable vs simply
forgotten — relevant since this module is being lifted into `yahir_reusable_bot` for other bots
to import. The class docstring documents the *baked* options well but not the *withheld* ones.
**Fix:** Add one line to the `register` docstring naming the deliberately-unsupported `add_job`
parameters (and why — host keeps trigger/scheduling control, D-01/D-02), so a future bot author
knows the omission is a contract, not an oversight.

---

_Reviewed: 2026-06-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
