# Phase 8: ConfigHolder & `fire_slot` Reads-From-Holder Refactor - Research

**Researched:** 2026-06-15
**Domain:** Python concurrency (thread-safe mutable-reference holder) + Pydantic v2 immutability + APScheduler job-kwarg refactor
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01: `holder` param + optional `config=` override.** `fire_slot` takes a
  `holder: ConfigHolder` and reads `holder.current()` at fire time. Keep an optional
  `config=` keyword that, when explicitly passed, WINS over the holder — so tests and
  standalone catch-up fires can inject a fixed config without constructing a holder.
  Rejected: holder-only required param; module/process-level holder singleton.
- **D-02: `frozen=True` on `Config` and ALL nested models** (`Config`, `Location`,
  `Schedule`, `Reliability`, `WebhookIdentity`). Immutability enforced by the type.
  A source grep found NOTHING that mutates a loaded config today, so freezing breaks
  no existing code. Adds `frozen=True` to the existing `ConfigDict(extra="forbid")`.
  Rejected: immutable-by-convention; freezing only top-level `Config`.
- **D-03: All daemon config readers go through the holder.** `_register_jobs`,
  `_run_catchup`, and `_announce_schedule` all source config from `holder.current()`.
  `_heartbeat_tick` reads no config and is left UNTOUCHED. Rejected: fire_slot-only.
- **D-04: Ship `ConfigHolder.replace(new_config)` in Phase 8** — both `current()` and
  the lock-guarded atomic `replace()` exist now. Include a Phase-8 test that calls
  `replace()` and asserts an UNCHANGED `fire_slot` job renders the new config.
  Explicitly OUT: the validate-before-swap boundary (Phase 9's reload engine).

### Claude's Discretion
- **Lock type** (`threading.Lock` vs `RLock`) and whether `current()` reads under the
  lock or via an atomic reference read. Daemon runs jobs on APScheduler's default
  threadpool (`max_workers=10`) — holder must be thread-safe.
- **Read consistency within a single fire** — recommend `fire_slot` calls
  `holder.current()` ONCE at the top and threads that single snapshot through the whole
  delivery (incl. into `send_now` as `config=`), so a mid-fire `replace()` cannot tear a
  single delivery. Planner to confirm.
- **Module location / naming** of `ConfigHolder` (e.g. `weatherbot/config/holder.py`).
- **Where the holder is constructed/owned** — recommend `run_daemon` builds it and
  threads it into `_register_jobs` / `_run_catchup` / `_announce_schedule`, mirroring
  `stop_event` and `channel`.

### Deferred Ideas (OUT OF SCOPE)
- **Validate-before-swap boundary** — Phase 9's reload engine (CFG-04). `replace()` in
  Phase 8 just swaps; it does NOT validate.
- **Reload engine, SIGHUP / `weatherbot reload`, job diff/re-registration,
  `--check-config`** — Phase 9 (CFG-01/02/04/05/06/08).
- **`settings`/`.env` reloadability** — out of scope permanently. The holder owns
  `Config` ONLY, never `Settings`. Secrets are a restart boundary (Pitfall #12).
</user_constraints>

<phase_requirements>
## Phase Requirements

This is a **foundation/prerequisite phase — it closes no v1.1 requirement.** It exists
to unblock the two requirements below, both of which land in **Phase 9**, not here.

| ID | Description | Research Support |
|----|-------------|------------------|
| CFG-01 (Phase 9) | Edit config and apply without restart | This phase makes `fire_slot` read live config from a holder instead of a baked-in kwarg, so a Phase-9 `replace()` actually changes what an unchanged job renders. Holder + `replace()` land here as the ready seam. |
| CFG-05 (Phase 9) | Reload preserves exactly-once | Per-fire single-snapshot read (Discretion #2) guarantees an in-flight delivery can't be torn by a mid-fire swap — the property a Phase-9 job-diff relies on. The `(location, slot.time, local_date)` claim key is untouched. |

**Phase 8 acceptance is its own three Success Criteria** (ROADMAP) — see Validation
Architecture below.
</phase_requirements>

## Summary

This phase is a **mechanical, low-risk refactor whose correctness rests on two
well-understood Python facts**: (1) a single attribute assignment is atomic under the
GIL, and (2) Pydantic v2 `frozen=True` raises on mutation. Both are verified below
against the project's exact versions (Python 3.12.3, pydantic 2.13.4). There is no new
runtime dependency, no new external service, and no networking change. The only library
research that matters is the canonical thread-safe-holder pattern and the precise
frozen-model mechanics/gotchas — both nailed down empirically in this session.

The recommended design is a tiny `ConfigHolder` class holding one `Config` reference
behind a `threading.Lock`. `current()` returns the reference via a **lock-free atomic
read** (a bare attribute load — correct under the GIL because the store in `replace()`
is a single atomic bytecode). `replace(new_config)` takes the lock and rebinds the
reference. The lock exists not to protect the single read/write (those are atomic) but
to serialize writers and give Phase 9 a place to hang a future read-modify-write
(validate-then-swap) atomically. `fire_slot` reads `holder.current()` ONCE at the top
and threads that single snapshot through its whole fetch→render→persist lifecycle
(including into `send_now(config=…)` and the `config.reliability.*` budget read) so a
concurrent `replace()` can never tear one delivery.

The single highest-value finding for the planner: **freezing a model that contains a
`list` field makes it unhashable** — `hash(config)` raises `TypeError: unhashable type:
'list'`. `Config.locations` and `Location.schedule` are lists. This is harmless today
(a grep confirms nothing hashes a Config or puts it in a set/dict-key), but the planner
must add a verification step asserting the existing 215 tests stay green AND that no
code path hashes a frozen config. The mutation guard itself works perfectly and raises
`pydantic.ValidationError` (type `frozen_instance`), NOT `dataclasses.FrozenInstanceError`.

**Primary recommendation:** Add `weatherbot/config/holder.py` with a `ConfigHolder`
(`threading.Lock` + lock-free `current()` + lock-guarded `replace()`); add `frozen=True`
to all five config models' existing `ConfigDict`; refactor `fire_slot` to accept
`holder` and read `holder.current()` once (with `config=` override winning); thread the
holder from `run_daemon` into `_register_jobs`/`_run_catchup`/`_announce_schedule`
exactly as `stop_event` is threaded today. Use the name **`replace`** (flag the
ROADMAP `swap` discrepancy for the planner — see Open Questions).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Own the live `Config` reference | In-process state (`ConfigHolder`) | — | Single owner of mutable "which config is live"; the seam Phase 9 swaps against. |
| Hand out an immutable snapshot | `ConfigHolder.current()` | Pydantic `frozen=True` | Holder returns the reference; the *type* enforces the snapshot can't be mutated. |
| Atomic rebind of the live config | `ConfigHolder.replace()` | `threading.Lock` | Serializes writers; gives Phase 9 a place for read-modify-write. |
| Read config at fire time | `fire_slot` (job callback) | `ConfigHolder` | The job is the consumer; it pulls one snapshot per fire. |
| Construct + own the holder | `run_daemon` | — | Mirrors `stop_event`/`channel` ownership — one construction point per process. |
| Thread-safety context | APScheduler default threadpool (`max_workers=10`) | — | The concurrency the holder's lock/atomic-read must be correct under. |

## Standard Stack

**No new packages.** This phase uses only the standard library and the already-pinned
Pydantic. The entire stack is in-repo + stdlib.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `threading` (stdlib) | built-in (3.12) | `Lock` for `replace()`; the holder's mutex | The canonical Python mutex; no external dep. `[VERIFIED: stdlib]` |
| `pydantic` | 2.13.4 (already pinned) | `frozen=True` on config models | Already the project's config layer; `frozen=True` is one field on the existing `ConfigDict`. `[VERIFIED: uv.lock 2026-05-06]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | (pinned) | Concurrency + frozen + swap tests | The project's only test framework. `[VERIFIED: pyproject.toml]` |
| `structlog` | 26.x | (No new logging needed) | Holder ops are silent; Phase 9 logs reload outcomes, not Phase 8. `[CITED: CLAUDE.md]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `threading.Lock` | `threading.RLock` | RLock allows re-entrant acquire by one thread but carries slight overhead. The holder never re-acquires its own lock (no nested `replace`), so `Lock` is correct and marginally cheaper. Choose `RLock` ONLY if Phase 9's validate-then-swap calls back into `replace` from inside a held section (it won't). **Recommend `Lock`.** |
| Lock-free `current()` (atomic read) | `current()` reads under the lock | Reading under the lock is *also* correct and arguably clearer, but unnecessary: a bare attribute load is one atomic bytecode under the GIL, so an unsynchronized read can never observe a half-written reference (the old or new whole `Config` object — never a torn one). Lock-free read avoids any contention between the 10 worker threads. **Recommend lock-free `current()`, lock-guarded `replace()`.** Either is defensible; document the choice. |
| Atomic reference swap | `copy.deepcopy` on read | Pointless: snapshots are already immutable (`frozen=True`), so handing out the shared reference is safe — no defensive copy needed. |

**Installation:**
```bash
# No installation. No new dependencies. uv.lock unchanged.
```

**Version verification:**
```
pydantic 2.13.4 — verified in uv.lock (upload-time 2026-05-06). [VERIFIED: uv.lock]
Python 3.12.3 — verified via .venv/bin/python --version. [VERIFIED: local]
```

## Package Legitimacy Audit

> Not applicable — this phase installs **zero** external packages. `uv.lock` is unchanged.
> All code uses the Python standard library (`threading`) and the already-pinned,
> already-audited `pydantic 2.13.4`.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                    run_daemon(config, settings, db_path)
                              │
              ┌───────────────┴───────────────┐
              │  holder = ConfigHolder(config) │   ← single construction point
              │  (mirrors `stop = Event()`)    │     (Discretion #4)
              └───────────────┬───────────────┘
                              │ holder threaded in (like stop_event)
        ┌─────────────────────┼─────────────────────┬────────────────────┐
        ▼                     ▼                     ▼                    ▼
  _register_jobs        _announce_schedule     _run_catchup        (_heartbeat_tick
  (reads holder         (reads holder          (reads holder        — UNTOUCHED,
   .current() for        .current() for         .current() for       reads no config)
   the slot loop)        the announce loop)      plan_catchup)
        │                                            │
        │ add_job(kwargs={"holder": holder, ...})    │ fire_slot(loc, slot,
        │   ← NO "config" in kwargs anymore          │   holder=holder, ...)
        ▼                                            ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │ fire_slot(location, slot, *, holder, config=None, ...)            │
  │                                                                   │
  │  snapshot = config if config is not None else holder.current()    │ ← ONE read
  │            (D-01: explicit config= override WINS)                 │   per fire
  │                                                                   │   (Discretion #2)
  │  ... claim_slot(...) ...                                          │
  │  retrying = build_retrying(stop,                                  │
  │      attempts_per_burst=snapshot.reliability.attempts_per_burst,  │ ← reliability
  │      ...)                                                         │   from snapshot
  │  send_now(location.name, config=snapshot, ...)                    │ ← SAME object
  └──────────────────────────────────────────────────────────────────┘
                              ▲
                              │ holder.replace(new_config)   (Phase 9 calls this;
   ┌──────────────────────────┴────┐                          Phase 8 only TESTS it)
   │ ConfigHolder                  │
   │   _config: Config             │   current()  → return self._config   (lock-free)
   │   _lock: threading.Lock       │   replace(c) → with self._lock: self._config = c
   └───────────────────────────────┘
```

A reader can trace the primary case: `run_daemon` builds one holder → threads it to the
registrars → each live cron job calls `fire_slot(holder=…)` → `fire_slot` reads one
snapshot and threads it through `send_now`. A `replace()` between two fires changes what
the *next* fire reads — an in-flight fire keeps its already-read snapshot.

### Recommended Project Structure
```
weatherbot/config/
├── models.py        # +frozen=True on all 5 ConfigDict blocks (D-02)
├── loader.py        # unchanged — still produces the Config the holder owns
├── settings.py      # unchanged — Settings NEVER enters the holder
└── holder.py        # NEW: ConfigHolder (Discretion #3 — recommend this location/name)

weatherbot/scheduler/
├── daemon.py        # fire_slot, _register_jobs, _run_catchup, _announce_schedule,
│                    #   run_daemon — all refactored to the holder (D-01/D-03)
└── catchup.py       # plan_catchup — stays PURE-INPUT (see Pattern 3)
```

**Module placement rationale:** `weatherbot/config/holder.py` keeps the holder beside the
`Config` it owns and avoids any new import edge into `scheduler`. `daemon.py` imports
`ConfigHolder` under `TYPE_CHECKING` for annotations (it already does this for
`Config`/`Location`/`Schedule` — line 74-77), so no runtime import cycle is introduced.

### Pattern 1: Atomic-reference holder (lock-free read, lock-guarded write)
**What:** A class owning one reference; reads are unsynchronized atomic loads, writes
take a lock.
**When to use:** Single mutable "which immutable object is current" shared across threads.
**Example:**
```python
# Source: stdlib threading semantics + GIL atomicity (verified this session).
# weatherbot/config/holder.py
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weatherbot.config.models import Config


class ConfigHolder:
    """Single owner of the live, immutable Config.

    ``current()`` is a lock-free atomic reference read (a bare attribute load is one
    atomic bytecode under the GIL, so a reader sees either the old or the new whole
    Config — never a torn one). ``replace()`` takes the lock so writers are serialized
    and Phase 9 can hang an atomic validate-then-swap here.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()

    def current(self) -> Config:
        # Lock-free: one STORE_ATTR in replace() is atomic, so this load is safe.
        return self._config

    def replace(self, new_config: Config) -> None:
        with self._lock:
            self._config = new_config
```

### Pattern 2: Single-snapshot-per-fire (no torn delivery)
**What:** Read the holder ONCE at the top of `fire_slot`; thread that one object through
the whole delivery.
**When to use:** Any job whose multi-step body must see a consistent config even if a
swap lands mid-job.
**Example:**
```python
# Source: existing daemon.py fire_slot body (lines 181-201), refactored.
def fire_slot(location, slot, *, holder, config=None, db_path, ...):
    # D-01: explicit config= override WINS (tests / standalone fires).
    snapshot = config if config is not None else holder.current()
    # ... claim_slot(...) ...
    retrying = build_retrying(
        stop,
        attempts_per_burst=snapshot.reliability.attempts_per_burst,   # from snapshot
        burst_spread_s=snapshot.reliability.burst_spread_seconds,
        mid_pause_s=snapshot.reliability.mid_pause_seconds,
    )

    def _attempt():
        return send_now(location.name, config=snapshot, ...)          # SAME object
```

### Anti-Patterns to Avoid
- **Reading `holder.current()` more than once per fire:** a swap between two reads inside
  one delivery could mix old-reliability with new-template. Read once, bind to a local.
- **Putting `Settings` in the holder:** secrets are a restart boundary (Pitfall #12). The
  holder owns `Config` ONLY. `send_now`/`fire_slot` keep taking `settings=` separately.
- **`copy.deepcopy` on read:** snapshots are already `frozen=True`-immutable; a defensive
  copy is wasted work and would break object-identity assertions in the swap test.
- **Hashing a frozen `Config` / using it as a dict key or set member:** raises
  `TypeError: unhashable type: 'list'` (see Pitfall 1). Don't introduce any such use.
- **Catching `dataclasses.FrozenInstanceError` to test the mutation guard:** wrong
  exception type — pydantic raises `pydantic.ValidationError` (see Pitfall 2).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Snapshot immutability | A `__setattr__` override / manual freeze flag | Pydantic `frozen=True` | One config field; the type enforces it and raises a clear `ValidationError`. (D-02) |
| Thread-safe rebind | A hand-rolled double-checked-locking / `volatile`-style flag | `threading.Lock` + atomic attribute store | Python has no `volatile`; the GIL already makes a single store atomic. A `Lock` is the canonical writer-serializer. |
| "Which config is live" global | A module-level mutable global | An instance threaded through `run_daemon` | CONTEXT rejected the singleton (D-01) — instance injection is testable and mirrors `stop_event`. |
| Deep-copying snapshots | `copy.deepcopy(config)` per read | Hand out the shared frozen reference | Immutable ⇒ shared reads are safe; no copy needed. |

**Key insight:** Every primitive this phase needs already exists — the GIL gives atomic
reference swaps, `threading.Lock` gives writer serialization, and pydantic gives
enforced immutability. The work is *wiring*, not *building*.

## Runtime State Inventory

> This is a code-only refactor (new class + `frozen=True` + kwarg rename). There is no
> stored data, no renamed string that any datastore/service/OS keys on, and no build
> artifact change. Each category is explicitly checked below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the holder owns an in-memory `Config` reference only; nothing is persisted. The SQLite store's `(location, slot.time, local_date)` claim key is UNCHANGED by this phase (verified: `claim_slot`/`was_sent` calls in `fire_slot` are untouched). | None |
| Live service config | None — no external service config references any string this phase introduces. APScheduler job `id=f"{name}\|{time}\|{days}"` is UNCHANGED (D-06 stable id preserved). | None |
| OS-registered state | None — no systemd unit, Task Scheduler, or process-name change. The `weatherbot --run` entrypoint and service file are untouched. | None |
| Secrets/env vars | None — `Settings`/`.env` are explicitly OUT of the holder (Pitfall #12). No secret name changes. | None |
| Build artifacts | None — no `pyproject.toml`/package-name change; no new dependency; `uv.lock` unchanged. Adding `holder.py` is a new module, not a renamed/rebuilt artifact. | None |

**The canonical question — "after every file is updated, what runtime systems still have
the old string cached?":** Nothing. This phase renames a *kwarg* (`config` → `holder`) on
an in-process call, not any persisted/registered/external identifier.

## Common Pitfalls

### Pitfall 1: Frozen model with a `list` field is UNHASHABLE
**What goes wrong:** Adding `frozen=True` makes pydantic generate a `__hash__`. If any
code then hashes a `Config` (e.g. `set()`, dict key, `lru_cache` on a config arg,
`functools.cache`), it raises `TypeError: unhashable type: 'list'` at *runtime*, because
`Config.locations` and `Location.schedule` are lists and lists aren't hashable.
**Why it happens:** `frozen=True` opts the model into hashability, but pydantic's hash
hashes the field values, and a `list` value can't be hashed.
**How to avoid:** Verified this session that **nothing in the codebase hashes a Config or
nested model** (grep for `hash(`/`set(`/`frozenset`/`lru_cache`/dict-key use on config
types returned empty). The 215-test suite passing after the change is the regression
proof. Do NOT introduce any hashing of these models. If a future phase needs hashable
config, that's a separate design (e.g. tuple-of-locations), out of scope here.
**Warning signs:** A `TypeError: unhashable type: 'list'` traceback anywhere config flows
into a set/dict/cache.
**Evidence (this session, pydantic 2.13.4):**
```python
hash(frozen_config_with_list_field)  # -> TypeError: unhashable type: 'list'
```

### Pitfall 2: The mutation guard raises `pydantic.ValidationError`, not `FrozenInstanceError`
**What goes wrong:** A test (or future code) that does `with pytest.raises(FrozenInstanceError)`
or `except dataclasses.FrozenInstanceError` to assert immutability will NOT catch the real
exception and the test will error.
**Why it happens:** Pydantic v2 `frozen=True` is not a dataclass; mutating a field raises
`pydantic.ValidationError` with error type `frozen_instance`.
**How to avoid:** Assert on `pydantic.ValidationError` (or just `Exception`) in the
immutability test. Verified this session:
```python
try:
    config.template = "other.txt"
except pydantic.ValidationError as e:   # <- this is the right type
    ...   # e.errors()[0]["type"] == "frozen_instance"
```
**Warning signs:** An immutability test that "passes" because it never actually triggered
the guard, or one that errors with "DID NOT RAISE FrozenInstanceError."

### Pitfall 3: `list` field CONTENTS remain mutable under `frozen=True`
**What goes wrong:** `frozen=True` blocks *rebinding a field* (`config.locations = [...]`)
but does NOT freeze the list itself — `config.locations.append(x)` and
`config.locations[0].schedule.append(y)` still mutate in place (the latter only because
the inner model rebinding is blocked but the list container isn't).
**Why it happens:** Pydantic freezes attribute *assignment*, not the mutability of
contained mutable containers.
**How to avoid:** This is acceptable for Phase 8 — the threat model is a *job accidentally
rebinding a config field*, which IS blocked. No code mutates the lists today (verified
grep). Do not rely on `frozen=True` to prevent list-content mutation; rely on the verified
fact that nothing does it. If Phase 9 ever needs deep immutability, use `tuple` fields
(out of scope here).
**Evidence (this session):** `frozen_config.items.append(99)` succeeded (`[1, 2, 99]`).

### Pitfall 4: Two config-access patterns left in the daemon
**What goes wrong:** Refactoring only `fire_slot` (literal ROADMAP wording) but leaving
`_run_catchup`/`_announce_schedule` reading a captured `config` leaves two patterns and a
seam Phase 9 must re-touch.
**Why it happens:** ROADMAP Success Criterion #2 names only `fire_slot`; CONTEXT D-03
broadens it to ALL daemon readers.
**How to avoid:** Follow **D-03** (it wins): route `_register_jobs`, `_run_catchup`, and
`_announce_schedule` through the holder; leave `_heartbeat_tick` untouched (reads no
config). One source of truth in the daemon.

### Pitfall 5: `model_copy(update=…)` is the safe way to build a "changed" config for the swap test
**What goes wrong:** Constructing a second `Config` by hand for the swap test risks
diverging from the loader's shape; mutating the first is impossible (frozen).
**How to avoid:** Build the "new" config for the `replace()` test via
`original.model_copy(update={"template": "other.txt"})` (verified this session: returns a
new frozen instance, leaves the original untouched). This gives a clean, minimal "config B"
that differs only in the field the test asserts on.

## Code Examples

### Construct + thread the holder in `run_daemon` (mirror `stop_event`)
```python
# Source: existing run_daemon (daemon.py lines 576-612), holder added alongside `stop`.
def run_daemon(config, settings, db_path, *, client=None, channel=None) -> int:
    ...
    scheduler = BackgroundScheduler()
    stop = threading.Event()
    holder = ConfigHolder(config)            # NEW: single construction point (D-04/Discretion #4)

    _register_jobs(scheduler, holder, db_path=db_path, settings=settings,
                   client=client, channel=channel, stop_event=stop)
    # _heartbeat_tick job: UNCHANGED (no config).
    _announce_schedule(scheduler, holder)    # reads holder.current() (D-03)
    _run_catchup(holder, db_path=db_path, settings=settings,
                 client=client, channel=channel, stop_event=stop)   # (D-03)
```

### `_register_jobs` drops the captured `config` kwarg, passes `holder`
```python
# Source: existing _register_jobs (daemon.py lines 330-377).
def _register_jobs(scheduler, holder, *, db_path, settings, client=None,
                   channel=None, stop_event=None) -> None:
    config = holder.current()                # read ONCE to build the job set (D-03)
    for location in config.locations:
        for slot in location.schedule:
            if not slot.enabled:
                continue
            hh, mm = slot.parsed_time()
            scheduler.add_job(
                fire_slot,
                trigger=CronTrigger(hour=hh, minute=mm,
                                    day_of_week=slot.day_of_week,
                                    timezone=location.timezone),
                kwargs={
                    "holder": holder,        # NEW — replaces "config": config
                    "db_path": db_path,
                    "settings": settings,
                    "client": client,
                    "channel": channel,
                    "stop_event": stop_event,
                },
                args=[location, slot],
                id=f"{location.name}|{slot.time}|{slot.days}",   # UNCHANGED stable id
                misfire_grace_time=None,
                coalesce=True,
            )
```
> Note: `_register_jobs` reads `holder.current()` once to enumerate the *current* jobs;
> each registered job still receives the live `holder` and re-reads `current()` at fire
> time. (In Phase 8 the set of jobs is fixed at startup; Phase 9 re-diffs them.)

### `plan_catchup` stays pure-input (the holder reads at the call site)
```python
# Source: catchup.py plan_catchup (line 101) + daemon _run_catchup (line 433).
# RECOMMENDATION: keep plan_catchup PURE (takes a Config, not a holder). The daemon
# resolves the snapshot and passes it in — consistent with plan_catchup's documented
# purity contract (now_utc + was_sent injected; no I/O, no global state).
def _run_catchup(holder, *, db_path, settings, client=None, channel=None,
                 stop_event=None) -> None:
    config = holder.current()                          # resolve once at the call site
    missed = plan_catchup(config, lambda n, t, d: was_sent(db_path, n, t, d))
    for ms in missed:
        fire_slot(ms.location, ms.slot, holder=holder, db_path=db_path,   # live holder
                  settings=settings, client=client, channel=channel,
                  scheduled_dt=ms.scheduled_dt, late=True, stop_event=stop_event)
```
> Catch-up runs once at startup, so passing the live `holder` to `fire_slot` here is
> equivalent to passing `config=config`; threading the holder keeps the call uniform
> (D-03) and avoids a second access pattern. `plan_catchup` itself does NOT change.

### Mutation guard + swap, verified shape for tests
```python
import pydantic, pytest

def test_frozen_config_rejects_mutation(some_loaded_config):
    with pytest.raises(pydantic.ValidationError):          # NOT FrozenInstanceError
        some_loaded_config.template = "x.txt"

def test_swap_changes_unchanged_job(holder, fire_slot_args, config_b):
    # ... register/run a fire_slot job that reads holder.current() ...
    holder.replace(config_b)
    # assert the SAME job now renders config_b (the whole point — D-04)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Pydantic v1 `class Config: allow_mutation = False` | v2 `model_config = ConfigDict(frozen=True)` | Pydantic 2.0 (2023) | The project is on v2.13.4 — use `ConfigDict(frozen=True)`, never the v1 inner-class form. `[VERIFIED: pydantic 2.13.4]` |
| v1 `Config.copy(update=…)` | v2 `model.model_copy(update=…)` | Pydantic 2.0 | Use `model_copy` for the swap-test's "config B". `[VERIFIED: this session]` |
| v1 mutation raised `TypeError` | v2 mutation raises `pydantic.ValidationError` (`frozen_instance`) | Pydantic 2.0 | Assert on `ValidationError`. `[VERIFIED: this session]` |

**Deprecated/outdated:**
- Pydantic v1 `allow_mutation`/`Config` inner-class idioms — do not use; this is a v2
  codebase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `threading.Lock` (not `RLock`) is sufficient because no nested/re-entrant `replace` is needed in Phase 8 or planned for Phase 9. | Standard Stack / Discretion #1 | LOW — if Phase 9 ever validates-then-swaps re-entrantly, switch to `RLock` (one-line change). Lock is correct for Phase 8 regardless. |
| A2 | Lock-free `current()` is preferred over reading under the lock. | Pattern 1 / Discretion #1 | LOW — both are correct; this is a documented preference, not a correctness claim. Reading under the lock is a safe fallback if the planner prefers maximal explicitness. |
| A3 | `plan_catchup` should stay pure-input (takes a `Config`); the daemon resolves the snapshot. | Code Examples | LOW — CONTEXT D-03 routes *daemon readers* through the holder; `plan_catchup` is a pure planner, not a daemon reader. If the planner prefers passing the holder into `plan_catchup`, that's a minor variation with identical runtime behavior. |
| A4 | Canonical name is `replace` (not `swap`). | Open Questions | LOW (naming only) — flagged for planner; pick one and use it in both the method and the test. |

**Note:** Items A1-A4 are all in *Claude's Discretion* per CONTEXT.md, so they are
recommendations the planner finalizes — not unverified facts presented as locked. The
*technical* claims (GIL atomicity, frozen mechanics, unhashable-list gotcha, exception
type) are all `[VERIFIED]` this session, not assumed.

## Open Questions

1. **Canonical method name: `replace` vs `swap`?**
   - What we know: CONTEXT.md D-04 says `replace(new_config)`; ROADMAP Success Criterion
     #1 says `swap(new_cfg)`.
   - What's unclear: which name ships.
   - Recommendation: **`replace(new_config)`** — it's the explicit operator-facing name in
     the LOCKED decision (D-04 wins over ROADMAP wording, consistent with how D-03 wins
     over the ROADMAP's `fire_slot`-only phrasing). Planner should pick one name and use
     it in both the method and the swap test; optionally note the alias for Phase 9.

2. **Does `current()` read under the lock or lock-free?** (Discretion #1)
   - What we know: a single attribute load is atomic under the GIL; both forms are correct.
   - Recommendation: **lock-free `current()`**, lock-guarded `replace()` (Pattern 1). If
     the planner wants maximal symmetry/explicitness, `with self._lock: return self._config`
     is an equally-correct alternative — document whichever is chosen.

## Environment Availability

> Skipped — this phase has **no external dependencies**. It is a code-only refactor using
> the Python standard library (`threading`) and the already-installed pydantic 2.13.4. No
> network, service, CLI tool, or runtime beyond the existing `.venv` is required.

## Validation Architecture

> nyquist_validation is enabled (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pinned in pyproject.toml `[tool.pytest.ini_options]`) |
| Config file | `pyproject.toml` — `testpaths=["tests"]`, `pythonpath=["."]`, `addopts="-ra"` |
| Quick run command | `.venv/bin/python -m pytest tests/test_config_holder.py -x` (new file) |
| Full suite command | `.venv/bin/python -m pytest -q` |

**Baseline:** `215 passed in 4.52s` (verified this session). **NOTE:** the
CONTEXT/ROADMAP "186 tests" figure is the v1.0 close count; Phases 6-7 added 29 more.
**The real constraint is: all 215 existing tests stay green** (ROADMAP SC#3 generalized).

### Phase Requirements → Test Map
| Req / SC | Behavior | Test Type | Automated Command | File Exists? |
|----------|----------|-----------|-------------------|-------------|
| SC#1a | `ConfigHolder.current()` returns the held config | unit | `pytest tests/test_config_holder.py::test_current_returns_held -x` | ❌ Wave 0 |
| SC#1b | `replace()` rebinds; subsequent `current()` returns the new config | unit | `pytest tests/test_config_holder.py::test_replace_rebinds -x` | ❌ Wave 0 |
| SC#1c | **Concurrent read/swap safety** — N reader threads call `current()` while a writer thread loops `replace()`; every read returns a *whole valid* Config (old or new), never a torn/None one | concurrency | `pytest tests/test_config_holder.py::test_concurrent_read_swap_safe -x` | ❌ Wave 0 |
| SC#2 | **Mid-job swap → in-flight job keeps its snapshot** — start a `fire_slot` (or a holder-reading callable) that reads `current()` then pauses; `replace()` mid-flight; assert the in-flight delivery used the ORIGINAL snapshot (per-job single read, Pitfall #9/Discretion #2) | integration | `pytest tests/test_config_holder.py::test_inflight_job_keeps_snapshot -x` | ❌ Wave 0 |
| SC#2/D-04 | **Unchanged job renders NEW config after replace** — register/run a `fire_slot` job reading the holder; `replace(config_b)`; assert it now renders config_b (the phase's core proof) | integration | `pytest tests/test_config_holder.py::test_unchanged_job_renders_after_replace -x` | ❌ Wave 0 |
| D-01 | Explicit `config=` override WINS over the holder | unit | `pytest tests/test_config_holder.py::test_config_override_wins -x` | ❌ Wave 0 |
| D-02 | All 5 models reject field mutation with `pydantic.ValidationError` | unit | `pytest tests/test_models.py::test_frozen_rejects_mutation -x` | extend `tests/test_models.py` |
| D-02 | Nothing hashes a Config (regression: suite stays green) | full suite | `.venv/bin/python -m pytest -q` | existing 215 |
| SC#3 | Daemon behaves identically; existing 215 tests green | full suite | `.venv/bin/python -m pytest -q` | existing |

**Concurrency-test guidance (SC#1c):** spawn ~8 reader threads (matching the
`max_workers=10` context) in a tight loop asserting `holder.current() is config_a or
holder.current() is config_b`, plus one writer alternating `replace(config_a)/replace(config_b)`,
for a few thousand iterations. Use `is`-identity checks (the holder hands out the shared
reference, no copy). A torn read is impossible by construction (atomic store), so this
test documents/guards the invariant rather than chasing a race — keep it short and
deterministic (bounded iteration count, `join()` all threads, fail on any caught
exception via a shared error list).

**Mid-job snapshot test (SC#2):** the cleanest deterministic form injects a fake
`send_now` (the suite already does this — `tests/test_reliability.py` `_patch_send_now`)
that, on first call, records the `config` it received, signals the test, and blocks on an
event; the test then calls `holder.replace(config_b)`, releases the block, and asserts the
recorded config is `config_a` (`is config_a`). This proves the single-read-per-fire
property without real sleeps.

### Sampling Rate
- **Per task commit:** `.venv/bin/python -m pytest tests/test_config_holder.py tests/test_models.py -x`
- **Per wave merge:** `.venv/bin/python -m pytest -q` (all 215 + new)
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_config_holder.py` — NEW file: holder unit tests (current/replace/override),
  concurrency safety, mid-job snapshot, unchanged-job-renders-after-replace (covers SC#1/SC#2/D-01/D-04)
- [ ] `tests/test_models.py` — EXTEND: add `frozen=True` mutation-guard test asserting
  `pydantic.ValidationError` on each of the 5 models (covers D-02)
- [ ] No new fixtures needed — reuse `tmp_db`, `load_fixture` (conftest) and the existing
  `_FakeClient`/`_FakeChannel`/`_patch_send_now` helpers in `test_scheduler.py`/`test_reliability.py`
- [ ] No framework install — pytest already configured

## Security Domain

> security_enforcement is enabled (config.json), ASVS level 1.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface touched; OpenWeather key handling unchanged. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | no | Single-user personal bot; no access control surface. |
| V5 Input Validation | yes (indirect) | Config is validated by pydantic at load (`extra="forbid"` + field validators). `frozen=True` adds *integrity* (a validated snapshot can't be silently mutated post-load). `replace()` in Phase 8 does NOT validate — validation is Phase 9 (CFG-04); Phase 8's `replace()` is only ever fed an already-loaded `Config` by tests. |
| V6 Cryptography | no | No crypto. |
| V14 Config | yes | **Secrets stay out of the holder** — `Settings`/`.env` are NEVER placed in `ConfigHolder` (Pitfall #12, locked deferred decision). The holder owns non-secret `Config` only; the API key / webhook URL remain on `Settings`, threaded separately. Outcome-only logging is preserved (the holder logs nothing). |

### Known Threat Patterns for in-process config holder

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leak via the reloadable surface | Information Disclosure | Holder owns `Config` (non-secret) ONLY; `Settings` is a restart boundary and never enters the holder (Pitfall #12). |
| Torn/partial config read under concurrency | Tampering | Atomic reference swap (single `STORE_ATTR` under the GIL) + `frozen=True` snapshots ⇒ a reader always sees a whole, immutable, previously-validated Config. |
| Post-load config tampering by a buggy job | Tampering | `frozen=True` raises `ValidationError` on any field rebind — a job can't silently corrupt the shared snapshot. |
| Unbounded/invalid config injected via `replace()` | Tampering | OUT OF SCOPE for Phase 8 — `replace()` does not validate; Phase 9's reload engine (CFG-04, validate-before-swap) owns this. Phase 8 only ever calls `replace()` with an already-loaded `Config` in tests. Flag for Phase 9. |

## Sources

### Primary (HIGH confidence)
- **This session — empirical verification against pydantic 2.13.4 / Python 3.12.3:**
  frozen mutation raises `pydantic.ValidationError` (type `frozen_instance`); nested
  frozen models raise; `frozen=True`+`list` field ⇒ `hash()` raises `TypeError:
  unhashable type: 'list'`; list *contents* stay mutable; `model_copy(update=…)` returns a
  new instance leaving the original untouched.
- **Local codebase grep** — no code hashes/sets/dict-keys/`lru_cache`es a Config or nested
  model; no code mutates a loaded config (confirms D-02's low-risk claim).
- `weatherbot/scheduler/daemon.py`, `catchup.py`, `config/models.py`, `config/loader.py` —
  read in full; current signatures and call sites mapped.
- `pyproject.toml` / `uv.lock` — pydantic 2.13.4 (upload-time 2026-05-06), pytest config,
  Python 3.12.3.
- **`pytest -q` run this session** — baseline `215 passed` (corrects the "186" figure).

### Secondary (MEDIUM confidence)
- [docs.python.org/3/library/threading.html](https://docs.python.org/3/library/threading.html)
  — `Lock` vs `RLock` semantics; `Lock` is the canonical non-reentrant mutex.
- [realpython.com/python-thread-lock](https://realpython.com/python-thread-lock/) — GIL
  atomicity of single bytecode ops; locks still needed for compound operations.
- [geeksforgeeks.org Lock vs RLock](https://www.geeksforgeeks.org/python/python-difference-between-lock-and-rlock-objects/)
  — RLock reentrancy + overhead tradeoff.

### Tertiary (LOW confidence)
- None — every load-bearing claim was verified against the local environment or official
  stdlib/pydantic behavior.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new deps; stdlib + already-pinned pydantic, both verified.
- Architecture: HIGH — holder pattern + single-snapshot-per-fire verified against the
  actual `fire_slot`/`run_daemon` code and GIL semantics.
- Pitfalls: HIGH — the unhashable-list gotcha, exception type, and list-content mutability
  were reproduced empirically this session against pydantic 2.13.4.

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable — no fast-moving deps; pydantic/Python versions pinned)
