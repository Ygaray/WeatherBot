# Phase 8: ConfigHolder & `fire_slot` Reads-From-Holder Refactor - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 6 (2 NEW, 3 MODIFY, 1 EXTEND)
**Analogs found:** 6 / 6 (all in-repo — code-only refactor, zero new deps)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/config/holder.py` (NEW) | store (in-process state owner) | request-response (read/replace) | `weatherbot/scheduler/daemon.py` `run_daemon` threading of `stop`/`channel` | role-match (no existing holder class) |
| `weatherbot/scheduler/daemon.py` (MODIFY) | service / job-callback | event-driven (cron fire) | itself (in-place refactor of `fire_slot`/`_register_jobs`/`_run_catchup`/`_announce_schedule`/`run_daemon`) | exact (self) |
| `weatherbot/config/models.py` (MODIFY) | model | transform (validated load) | itself — every model already has `ConfigDict(extra="forbid")` | exact (self) |
| `weatherbot/scheduler/catchup.py` (MODIFY?) | service (pure planner) | transform (pure input→output) | itself — `plan_catchup` purity contract | exact (self); recommend **NO change** (stays pure-input) |
| `tests/test_config_holder.py` (NEW) | test | request-response + concurrency | `tests/test_reliability.py` (`fire_slot` tests + `_patch_send_now`/`_RecordingStop`/`_Channel`) | role-match |
| `tests/test_models.py` (EXTEND) | test | transform | itself — existing model-construction tests (`tests/test_models.py`) | exact (self) |

## Pattern Assignments

### `weatherbot/config/holder.py` (NEW — store, request-response)

**Analog:** `weatherbot/scheduler/daemon.py` — module-header docstring style, `from __future__ import annotations`, `TYPE_CHECKING`-gated `Config` import, and the `stop = threading.Event()` construct-once-thread-everywhere pattern in `run_daemon` (lines 580-612).

**Imports / module-top pattern** (mirror `daemon.py` lines 36-40, 74-77 — `TYPE_CHECKING`-gated config import avoids any new `config → scheduler` or runtime import edge):
```python
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weatherbot.config.models import Config
```

**Core pattern — atomic-reference holder** (RESEARCH Pattern 1; the holder is the analog target itself — it does not exist yet). Lock-free `current()`, lock-guarded `replace()`:
```python
class ConfigHolder:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._lock = threading.Lock()

    def current(self) -> Config:
        # Lock-free: one STORE_ATTR in replace() is atomic under the GIL.
        return self._config

    def replace(self, new_config: Config) -> None:
        with self._lock:
            self._config = new_config
```

**Naming decision (Open Question 1):** ship **`replace`** — CONTEXT D-04 (locked) wins over the ROADMAP `swap` wording, consistent with how D-03 wins over the ROADMAP's `fire_slot`-only phrasing. Use the same name in method + test.

**Lock decision (Discretion #1 / Assumption A1-A2):** `threading.Lock` (not `RLock`); lock-free `current()`. Both documented as defensible; planner finalizes.

**Error handling:** none — the holder is silent (no logging, no validation). `replace()` does NOT validate (validate-before-swap is Phase 9 / CFG-04, explicitly deferred).

---

### `weatherbot/scheduler/daemon.py` (MODIFY — service / job-callback, event-driven)

**Analog:** itself — this is an in-place refactor. The exact current signatures and call sites are below so the planner edits against real line numbers.

**`fire_slot` signature change** (current lines 97-109): replace the required `config: Config` keyword with `holder` + an optional `config=None` override (D-01):
```python
# CURRENT (lines 97-109):
def fire_slot(location, slot, *, config: Config, db_path, settings=None,
              client=None, channel=None, scheduled_dt=None, late=False, stop_event=None):

# REFACTOR (D-01 — explicit config= override WINS):
def fire_slot(location, slot, *, holder: ConfigHolder, config: Config | None = None,
              db_path, settings=None, client=None, channel=None,
              scheduled_dt=None, late=False, stop_event=None):
    snapshot = config if config is not None else holder.current()   # ONE read per fire
```

**Single-snapshot-per-fire** (RESEARCH Pattern 2 / Discretion #2 — bind once, thread the SAME object through the whole delivery). The two existing in-body `config.*` reads to repoint at `snapshot`:
- Reliability budget read — current lines 182-187:
```python
retrying = build_retrying(
    stop,
    attempts_per_burst=snapshot.reliability.attempts_per_burst,   # was config.reliability.*
    burst_spread_s=snapshot.reliability.burst_spread_seconds,
    mid_pause_s=snapshot.reliability.mid_pause_seconds,
)
```
- `send_now` forward — current lines 193-201 (the SAME `snapshot` object, never a re-read):
```python
return send_now(location.name, config=snapshot, db_path=db_path, settings=settings,
                client=client, channel=channel, schedule_ctx=ctx)
```
> The whole-body `try/except Exception` isolation (lines 138/284-311), `claim_slot`/`release_claim`/`record_alert` flow, and the lazy `from weatherbot.cli import send_now` import (line 165) are UNTOUCHED — the refactor changes only WHERE config comes from, not the delivery/recovery logic.

**`_register_jobs` — drop the captured `config` kwarg** (current lines 330-377). Take `holder`, read `holder.current()` once to enumerate jobs, put `holder` (not `config`) in `add_job(kwargs=...)`:
```python
def _register_jobs(scheduler, holder, *, db_path, settings, client=None,
                   channel=None, stop_event=None):
    config = holder.current()                 # read ONCE to build the current job set
    for location in config.locations:
        for slot in location.schedule:
            if not slot.enabled:
                continue
            hh, mm = slot.parsed_time()
            scheduler.add_job(
                fire_slot,
                trigger=CronTrigger(hour=hh, minute=mm, day_of_week=slot.day_of_week,
                                    timezone=location.timezone),
                kwargs={
                    "holder": holder,          # NEW — replaces "config": config
                    "db_path": db_path, "settings": settings,
                    "client": client, "channel": channel, "stop_event": stop_event,
                },
                args=[location, slot],
                id=f"{location.name}|{slot.time}|{slot.days}",   # UNCHANGED stable id (D-06)
                misfire_grace_time=None, coalesce=True,
            )
```
> CRITICAL — the job `id=f"{location.name}|{slot.time}|{slot.days}"` (line 374) is UNCHANGED. Phase 9's job-diff keys on it; do not disturb it.

**`_announce_schedule`** (current lines 380-413) and **`_run_catchup`** (current lines 416-449): take `holder`, read `holder.current()` once at the top (D-03 — all daemon readers go through the holder). `_run_catchup` passes the live `holder` into each `fire_slot(...)` (current line 438-449):
```python
def _run_catchup(holder, *, db_path, settings, client=None, channel=None, stop_event=None):
    config = holder.current()                            # resolve once at the call site
    missed = plan_catchup(config, lambda n, t, d: was_sent(db_path, n, t, d))
    for ms in missed:
        fire_slot(ms.location, ms.slot, holder=holder, db_path=db_path,   # live holder
                  settings=settings, client=client, channel=channel,
                  scheduled_dt=ms.scheduled_dt, late=True, stop_event=stop_event)
```

**`run_daemon` — construct + thread the holder** (current lines 576-612). Build `holder` alongside `stop` (the construct-once pattern is the named analog), thread it into the three registrars; `_heartbeat_tick` job (lines 596-603) UNTOUCHED (reads no config):
```python
scheduler = BackgroundScheduler()
stop = threading.Event()
holder = ConfigHolder(config)            # NEW — single construction point (mirrors `stop`)

_register_jobs(scheduler, holder, db_path=db_path, settings=settings,
               client=client, channel=channel, stop_event=stop)
# _heartbeat_tick add_job: UNCHANGED (no config)
_announce_schedule(scheduler, holder)
_run_catchup(holder, db_path=db_path, settings=settings,
             client=client, channel=channel, stop_event=stop)
```
> `gate_until_healthy` (lines 631-637) keeps taking `config=config` — it runs the startup self-check on the loaded config; it is NOT a per-fire reader, so it is not required to go through the holder (the loaded `config` and `holder.current()` are identical at startup). Planner may optionally route it through the holder for uniformity, but it is out of D-03's named set (`_register_jobs`/`_run_catchup`/`_announce_schedule`).

**Import for `ConfigHolder`:** add under the existing `TYPE_CHECKING` block (lines 74-77, which already imports `Config`/`Location`/`Schedule`) for the annotation; the runtime construction in `run_daemon` needs a real import — follow the module's lazy-in-function import convention (e.g. `send_now`/`build_channel` at lines 165/572) ONLY if a top-level import would cycle. `weatherbot.config.holder` has no scheduler dependency, so a top-level `from weatherbot.config.holder import ConfigHolder` is cycle-free and preferred for the runtime use.

---

### `weatherbot/config/models.py` (MODIFY — model, transform)

**Analog:** itself — all five models already carry `model_config = ConfigDict(extra="forbid")`. Adding `frozen=True` is a one-field append to each existing block (D-02). Exact current lines:

| Model | Current `model_config` line |
|-------|------------------------------|
| `Schedule` | line 45 |
| `Location` | line 93 |
| `WebhookIdentity` | line 126 |
| `Reliability` | line 154 |
| `Config` | line 219 |

**Pattern to copy** (apply to all five):
```python
# CURRENT:
model_config = ConfigDict(extra="forbid")
# REFACTOR (D-02):
model_config = ConfigDict(extra="forbid", frozen=True)
```
> Verified low-risk (RESEARCH): a grep found NOTHING that mutates a loaded config, and NOTHING that hashes/sets/dict-keys a Config or nested model. `frozen=True` makes these list-bearing models unhashable (`Config.locations`, `Location.schedule`) — harmless today (Pitfall 1). Field/property methods (`parsed_time`, `day_of_week`, `worst_case_seconds`, validators) are read-only and unaffected.

---

### `weatherbot/scheduler/catchup.py` (MODIFY? — pure planner, transform)

**Analog:** itself — `plan_catchup` (lines 101-173) is documented PURE (`now_utc` + `was_sent` injected; no I/O, no global state; "intentionally APScheduler-free").

**Recommendation: NO change** (RESEARCH Assumption A3). Keep `plan_catchup(config, was_sent, now_utc=None)` taking a `Config`, not a holder. The daemon (`_run_catchup`) resolves `holder.current()` at the call site and passes the resolved `Config` in — preserving the purity contract. Listed as MODIFY-candidate in CONTEXT only to confirm the decision; the confirmed decision is that it stays pure-input.

---

### `tests/test_config_holder.py` (NEW — test, request-response + concurrency)

**Analog:** `tests/test_reliability.py` — the `fire_slot` integration tests (lines 427-499) plus the reusable helpers `_patch_send_now` (lines 410-414), `_RecordingStop` (lines 355-377), `_Channel` (lines 380-390), `_config` (lines 393-402), `_slot` (lines 405-407), `_connect`/`_alerts`/`_heartbeat` (lines 54-58, 417-424). Reuse `tmp_db` from `tests/conftest.py` (lines 26-33).

**Helper-reuse pattern** (`_patch_send_now` — lines 410-414, the seam that lets a holder test prove what config `fire_slot` rendered without touching the network):
```python
def _patch_send_now(monkeypatch, fn):
    import weatherbot.cli as cli
    monkeypatch.setattr(cli, "send_now", fn)
```

**`fire_slot` call pattern** (existing lines 442-444, 464-466) — the holder tests register/call `fire_slot` the same way, swapping `config=config` for `holder=holder`:
```python
result = daemon_mod.fire_slot(loc, slot, holder=holder, db_path=tmp_db,
                              channel=channel, stop_event=stop)
```

**Recording-fake `send_now` pattern** (existing lines 435-439) — the mid-job/override/unchanged-job tests inject a `send_now` that records the `config=` it received:
```python
def fake_send_now(*args, **kwargs):
    recorded.append(kwargs["config"])        # the snapshot fire_slot threaded in
    return DeliveryResult(ok=True)
_patch_send_now(monkeypatch, fake_send_now)
```

**Tests to write (RESEARCH Test Map — all Wave 0):**
- `test_current_returns_held` / `test_replace_rebinds` — unit (SC#1a/b)
- `test_concurrent_read_swap_safe` — ~8 reader threads + 1 writer looping `replace`, `is`-identity assert each read is `config_a or config_b`, bounded iterations, `join()` all, fail on any caught exception (SC#1c, matches `max_workers=10` context)
- `test_inflight_job_keeps_snapshot` — `send_now` records the config on first call, blocks on an event; test calls `holder.replace(config_b)`, releases, asserts recorded `is config_a` (SC#2 / Discretion #2, the `_patch_send_now` + recording-fake technique)
- `test_unchanged_job_renders_after_replace` — register/run a `fire_slot` reading the holder; `replace(config_b)`; assert it now renders `config_b` (D-04, the phase's core proof)
- `test_config_override_wins` — pass explicit `config=config_a` while `holder` holds `config_b`; assert `config_a` is used (D-01)

**Build "config B" via `model_copy`** (RESEARCH Pitfall 5 — never hand-build, never mutate the frozen original):
```python
config_b = config_a.model_copy(update={"template": "other.txt"})
```

---

### `tests/test_models.py` (EXTEND — test, transform)

**Analog:** itself — existing tests construct models directly (e.g. `LOC = Location(...)` line 18). Add a frozen-mutation guard asserting on the CORRECT exception type.

**Pattern to add** (RESEARCH Pitfall 2 — pydantic v2 raises `pydantic.ValidationError` type `frozen_instance`, NOT `dataclasses.FrozenInstanceError`):
```python
import pydantic, pytest

def test_frozen_rejects_mutation():
    config = Config(locations=[LOC])     # reuse the module-level LOC analog (line 18)
    with pytest.raises(pydantic.ValidationError):   # NOT FrozenInstanceError
        config.template = "other.txt"
```
> D-02 wants all five models proven — parametrize over `Schedule`/`Location`/`WebhookIdentity`/`Reliability`/`Config`, asserting each rejects a field rebind.

## Shared Patterns

### Construct-once-thread-everywhere (in-process state ownership)
**Source:** `weatherbot/scheduler/daemon.py` `run_daemon` lines 576-612 — `stop = threading.Event()` is built once and threaded into `_register_jobs`/`_run_catchup`.
**Apply to:** `ConfigHolder` construction in `run_daemon`; threading `holder` into all three registrars.
```python
stop = threading.Event()
holder = ConfigHolder(config)   # NEW — exact same construct-once shape as `stop`
```

### `ConfigDict` config block (one source of truth per model)
**Source:** `weatherbot/config/models.py` — every model's `model_config = ConfigDict(extra="forbid")` (lines 45, 93, 126, 154, 219).
**Apply to:** all five models — append `frozen=True` to the existing block (never an inner `class Config:`/pydantic-v1 idiom).

### `TYPE_CHECKING`-gated config imports (no new import edge)
**Source:** `weatherbot/scheduler/daemon.py` lines 74-77; `weatherbot/scheduler/catchup.py` lines 29-30 — both import `Config`/`Location`/`Schedule` under `TYPE_CHECKING`.
**Apply to:** `holder.py` (gate `Config`); `daemon.py` (gate `ConfigHolder` annotation; runtime construction uses a real top-level import since `config.holder` is cycle-free).

### Lazy in-function import to break cycles
**Source:** `weatherbot/scheduler/daemon.py` line 165 (`from weatherbot.cli import send_now`) and line 572 (`from weatherbot.channels import build_channel`).
**Apply to:** ONLY if `ConfigHolder`'s runtime use in `run_daemon` would cycle (it won't — prefer a top-level import). Pattern documented for completeness.

### Test fixture + helper reuse (no new fixtures)
**Source:** `tests/conftest.py` (`tmp_db` lines 26-33, `load_fixture` lines 20-23); `tests/test_reliability.py` (`_patch_send_now`, `_RecordingStop`, `_Channel`, `_config`, `_slot`, `_connect`/`_alerts`/`_heartbeat`).
**Apply to:** `tests/test_config_holder.py` — import/reuse these rather than re-inventing. RESEARCH confirms no new fixtures are needed.

## No Analog Found

None. This is a code-only refactor using stdlib `threading` and the already-pinned pydantic; every file has an in-repo analog (mostly itself). No file falls back to RESEARCH-only patterns.

## Metadata

**Analog search scope:** `weatherbot/scheduler/`, `weatherbot/config/`, `tests/`
**Files scanned:** `daemon.py`, `models.py`, `catchup.py`, `loader.py` (refs), `tests/conftest.py`, `tests/test_reliability.py`, `tests/test_scheduler.py`, `tests/test_models.py`, `tests/test_cli.py` (helper grounding)
**Pattern extraction date:** 2026-06-15
</content>
</invoke>
