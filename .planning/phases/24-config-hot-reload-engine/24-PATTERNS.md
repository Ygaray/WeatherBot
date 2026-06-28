# Phase 24: Config Hot-Reload Engine - Pattern Map

**Mapped:** 2026-06-27
**Files analyzed:** 6 (2 new module files, 1 new shim, 1 modified daemon, 1 modified module barrel, 1 modified test)
**Analogs found:** 6 / 6 (every surface this phase touches already exists and is golden-pinned)

> This phase is a **relocation along seams already drawn**, not a redesign. Every "new" file has a
> direct in-repo analog to copy from verbatim (the module-side `SchedulerEngine`/barrel/shim
> precedents) or to lift line-for-line (the app-side `daemon.py` reload machinery). The two
> [DEVIATION] decisions (D-01 `set[str]`+`register_jobs`, D-02 unbound `TypeVar`) are LOCKED — do
> not "correct" them to the roadmap's `set[JobSpec]` / bound-base wording.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `yahir_reusable_bot/config/holder.py` (NEW) | model / storage-cell | request-response (lock-free read / locked swap) | `weatherbot/config/holder.py` | exact (generalize annotations only) |
| `yahir_reusable_bot/config/reload.py` (NEW) | service / engine | event-driven (validate→swap→reconcile→rollback + watch + flag-service) | `weatherbot/scheduler/daemon.py` `_do_reload`/`_reconcile_jobs`/`_restore_jobs`/`_run_watch_observer` + `yahir_reusable_bot/scheduler/engine.py` (engine shape) | exact-lift + role-match |
| `yahir_reusable_bot/config/__init__.py` (NEW) | config / barrel | n/a (re-export) | `yahir_reusable_bot/scheduler/__init__.py` | exact |
| `weatherbot/config/holder.py` (MODIFY → shim) | config / re-export shim | n/a | `weatherbot/reliability/__init__.py` (22-02 shim) | exact |
| `weatherbot/scheduler/daemon.py` (MODIFY) | controller / composition-root | event-driven (wires + drives the engine) | itself (current `run_daemon` wiring + main poll loop) | in-place adaptation |
| `tests/test_import_hygiene.py` (MODIFY) | test / gate | batch (static scan) | itself (existing grimp/litmus/isolated-import gates) | exact (auto-scales) + 1 NEW assertion |

**Optional new test files** (Wave-0 gaps, planner discretion): `tests/test_reload_engine.py` (mirrors
`tests/test_scheduler_engine.py` direct-engine pattern), `tests/test_config_holder_generic.py` (proves
`ConfigHolder[T]` carries a non-weather `T`).

---

## Pattern Assignments

### `yahir_reusable_bot/config/holder.py` (model, storage-cell) — D-02 / D-03a

**Analog:** `weatherbot/config/holder.py` (the whole 67-line file). **Mechanism byte-identical; only
the two `Config` annotations become an unbound `TypeVar`.** `test_concurrent_read_swap_safe` is the
oracle and must stay green unchanged.

**Imports pattern** — replace the `TYPE_CHECKING` `Config` import with `Generic`/`TypeVar`:
```python
from __future__ import annotations
import threading
from typing import Generic, TypeVar

T = TypeVar("T")  # UNBOUND (D-02) — NO module BaseConfig; any bot passes its own frozen config type
```

**Core pattern** (copy verbatim from analog L46-67, swap `Config` → `T`):
```python
class ConfigHolder(Generic[T]):
    def __init__(self, config: T) -> None:
        self._config = config
        self._lock = threading.Lock()

    def current(self) -> T:
        return self._config            # lock-free LOAD_ATTR (atomic under the GIL)

    def replace(self, new_config: T) -> None:
        with self._lock:               # locked STORE_ATTR — serializes writers
            self._config = new_config
```

**Load-bearing invariants to preserve from the analog docstring (L8-27):**
- `current()` is **lock-free** (one `LOAD_ATTR`, atomic vs. the single `STORE_ATTR` under the GIL).
- `replace()` takes a plain non-reentrant lock and does **NO** checking / copy / clone / record.
- Holds the app's frozen config **ONLY** — secrets / `.env` never enter (Pitfall #12, holder.py L25-26).

**Anti-pattern (D-03 / Pitfall 1):** the holder must NEVER call pydantic — no `import pydantic`,
`TypeAdapter`, `model_validate`, or `Generic[T]` self-parametrization. `TypeVar` is erased at runtime
(`get_args()` is empty inside `__init__`); validating on a base drops fields or raises.

---

### `yahir_reusable_bot/config/reload.py` (service, engine) — D-04 / D-05 / D-07 / D-08 / D-09

**Primary analog (control flow + reconcile + restore + watch):** `weatherbot/scheduler/daemon.py`
`_do_reload` (L879-1027), `_reconcile_jobs` (L775-845), `_restore_jobs` (L848-876),
`_run_watch_observer` (L1266-1328), `_install_reload_signal` (L1330-1351), main poll loop (L1625-1654).
**Secondary analog (engine shape — constructor injection + opaque passthrough):**
`yahir_reusable_bot/scheduler/engine.py` (the whole file).

**Engine-shape pattern to clone** (from `SchedulerEngine`, engine.py L41-43 + module docstring L1-25):
constructor takes collaborators by reference and stores them; thin verbs forward to opaque callables;
the engine **owns NO lifecycle the host owns** (`SchedulerEngine` owns no `start`/`shutdown`; here the
engine owns no SIGHUP install / main loop — D-05). Native objects (trigger, callback, here `T`/the
validator/registrar) **pass through untouched** — "the engine never constructs or inspects" them.

**Constructor (D-07)** — mirror `SchedulerEngine.__init__`'s store-by-reference, add the injected hooks:
```python
class ReloadEngine(Generic[T]):
    def __init__(
        self,
        holder: ConfigHolder[T],
        scheduler_engine: Any,                        # the Phase-23 SchedulerEngine (remove + list_live_ids)
        *,
        validate: Callable[[str | Path], T],          # app: validate_config_and_templates → concrete Config
        desired_jobs: Callable[[T], set[str]],        # app: _desired_job_ids → set[str]
        register_jobs: Callable[[T], None],           # app: _register_jobs(replace_existing=True) — FULL desired set
        restore: Callable[[T], None],                 # app: _restore_jobs(old_cfg) (D-08)
        excluded_ids: frozenset[str] = frozenset(),   # app: {"__heartbeat__","__uvmonitor__"} (Pitfall 2)
        on_applied: Callable[[str], None] | None = None,
        on_rejected: Callable[[Exception], None] | None = None,
    ) -> None: ...
```

**`reload()` two-phase skeleton — lift verbatim from `_do_reload` L944-1027.** The exact ordering is
load-bearing (keep-old + all-or-nothing rollback are Phase-21 goldens). Copy the control flow,
replacing the inlined `validate_config_and_templates`/`_reconcile_jobs`/`_restore_jobs` calls with the
injected callables and the two `channel.send(...)` blocks with `on_rejected`/`on_applied`:
```python
# PHASE 1 — validate-or-keep-old (analog L913-938)
try:
    new_cfg = self._validate(path)
except Exception as exc:                       # app validator owns the concrete catch set
    self._best_effort(self._on_rejected, exc)  # post "⛔ rejected" BEFORE re-raise (D-09 / analog L931-938)
    raise                                       # holder + jobs UNTOUCHED (keep-old)
# PHASE 2 — atomic swap + diff-reconcile, all-or-nothing rollback (analog L944-978)
old_cfg = self._holder.current()
self._holder.replace(new_cfg)
try:
    summary = self._reconcile()
except Exception:
    self._holder.replace(old_cfg)
    self._best_effort_restore(old_cfg)          # _restore_jobs(old) — best-effort, never masks cause (analog L964-975)
    raise
self._best_effort(self._on_applied, summary)    # post "✅ summary" + cache.invalidate (D-09 / analog L997-1015)
```

**`_reconcile()` — lift from `_reconcile_jobs` L811-845.** The diff already keys on `set[str]` and
delegates ADD to a separate `register_jobs` call — this is D-01's near-verbatim seam line:
```python
desired = self._desired_jobs(self._holder.current())          # injected → set[str]
live = self._scheduler_engine.list_live_ids() - self._excluded_ids   # Pitfall 2 — engine subtracts, never NAMES the ids
added = len(desired - live)
unchanged = len(desired & live)
changed = 0                                                   # content edits ride the holder swap (analog L823)
self._register_jobs(self._holder.current())                  # injected ADD — FULL desired set, replace_existing=True (D-01a)
removed = 0
for job_id in live - desired:
    self._scheduler_engine.remove(job_id)                    # engine owns REMOVE (analog L841-843)
    removed += 1
return f"+{added} -{removed} ~{changed} ={unchanged}"
```
> **CRITICAL (Pitfall 2):** the live `_reconcile_jobs` (L814-818) hard-codes the
> `("__heartbeat__", "__uvmonitor__")` exclusion inline. That naming **cannot** move into the
> weather-noun-free module. Inject it as `excluded_ids: frozenset[str]` and subtract from `live`
> BEFORE diffing. A naive lift (full `list_live_ids()` as `live`) puts those ids in `live - desired`
> and **removes them on every reload** — a `-2` reconcile-diff golden break that tears down the
> heartbeat + UV monitor live.

**Trigger machinery (D-04 / D-05)** — lift the flag pair + observer from the analog:
```python
def request_reload(self) -> None:        # FLAG-SET ONLY — safe from SIGHUP handler AND watch thread (analog L1346-1348)
    self._reload_requested.set()

def service_pending(self, path) -> bool: # runs reload() on the CALLER's (main) thread (analog L1626-1648)
    if not self._reload_requested.is_set():
        return False
    self._reload_requested.clear()
    self.reload(path)
    return True

def check(self, path) -> T:              # D-06 — validate-only, no swap/reconcile/scheduler touch
    return self._validate(path)
```
`start_watching(...)` body = `_run_watch_observer` verbatim (analog L1294-1327), calling
`self.request_reload()` on each settled non-empty change-set; the engine owns the thread + the
`watch_dirs_ref` box; `stop()` joins it (the app's `finally` calls it — analog L1671-1679).

**Watch re-derive (Pitfall 4):** the engine owns the `watch_dirs_ref` box and the thread; the app owns
the re-derive function (`_derive_watch_dirs` — it knows `config.template` + `TEMPLATES_DIR`). Route the
post-swap re-derive through `on_applied` (or a tiny `engine.update_watch_dirs(new_dirs)` the closure
calls), mirroring analog L1017-1026. Recommend `on_applied` (keeps `start_watching` minimal — A4).

**Restore (Pitfall 3 / D-08):** keep `_restore_jobs` (analog L867-876) app-side and inject it verbatim
— it wraps `old_cfg` in a **transient `ConfigHolder`** and re-runs the full reconcile (re-add old via
`replace_existing=True`, remove any half-applied new id). Do NOT make the engine's own `_reconcile`
serve double duty.

**Logging:** the `_log`/`_stdlog` "reload applied"/"reload rejected"/"reconcile failed" calls
(analog L924-989) need a home in the engine — keep them generic ("reload" events, no weather noun;
prose is litmus-immune but signatures/keys should stay clean).

---

### `yahir_reusable_bot/config/__init__.py` (config, barrel)

**Analog:** `yahir_reusable_bot/scheduler/__init__.py` (the whole file). Copy its shape exactly:
```python
"""<one-line subpackage purpose — generic, no weather noun>."""
from __future__ import annotations
from .holder import ConfigHolder
from .reload import ReloadEngine
__all__ = ["ConfigHolder", "ReloadEngine"]
```

---

### `weatherbot/config/holder.py` → re-export shim (MODIFY) — Pattern 22-02

**Analog:** `weatherbot/reliability/__init__.py` (the Phase-22 re-export shim). Replace the holder body
with a re-export so every existing `from weatherbot.config.holder import ConfigHolder` importer (daemon
L65, plus ~6 readers + `test_config_holder.py`) resolves to the **identical class object**:
```python
"""App-side re-export shim — ConfigHolder now lives in yahir_reusable_bot.config (D-02)."""
from yahir_reusable_bot.config import ConfigHolder

__all__ = ["ConfigHolder"]
```
> The 22-02 shim docstring (reliability/__init__.py L1-8) is the template: state where the code moved,
> why (the D-number), and that importers resolve to the identical object so behavior stays
> byte-identical.

---

### `weatherbot/scheduler/daemon.py` (controller, composition-root) — MODIFY

**Analog:** itself — `run_daemon` already constructs the holder, installs SIGHUP, and runs the main
poll loop. **Adapt-don't-rewrite** (the rule that kept `fire_slot` put in 22/23). `run_daemon` keeps
all current call sites and only GAINS the `ReloadEngine` construction (full wiring consolidation is
Phase-25). `_register_jobs` (L600-686), `_desired_job_ids` (L689-713), `_derive_watch_dirs` (L1214),
`_make_watch_filter` (L1242), `validate_config_and_templates`, the SIGHUP install, and the main loop
all STAY app-side and are injected/kept.

**Wiring pattern (NEW in `run_daemon`, replacing the inlined `_do_reload` at L1636-1648):**
```python
from yahir_reusable_bot.config import ConfigHolder, ReloadEngine   # holder import moves to the barrel
# SchedulerEngine already imported (daemon.py L73)

reload_engine = ReloadEngine(
    holder, SchedulerEngine(scheduler),
    validate=lambda p: validate_config_and_templates(p),
    desired_jobs=lambda cfg: _desired_job_ids(ConfigHolder(cfg)),        # transient-holder closure (A2)
    register_jobs=lambda cfg: _register_jobs(
        scheduler, ConfigHolder(cfg), db_path=db_path, settings=settings,
        client=client, channel=channel, stop_event=stop, replace_existing=True),
    restore=lambda old: _restore_jobs(
        scheduler, old, db_path=db_path, settings=settings,
        client=client, channel=channel, stop_event=stop),
    excluded_ids=frozenset({"__heartbeat__", "__uvmonitor__"}),          # Pitfall 2 — app supplies the ids
    on_rejected=lambda exc: channel.send(f"⛔ config reload rejected: {exc}") if channel else None,
    on_applied=lambda summary: (
        channel.send(f"✅ config reloaded: {summary}") if channel else None,
        cache.invalidate() if cache else None),
)
```
> The `desired_jobs`/`register_jobs`/`restore` closures wrap a transient `ConfigHolder(cfg)` because the
> existing helpers take a `holder`, not a bare `cfg` — the thinnest adapter that preserves
> byte-identical behavior (A2; a helper-signature refactor is deferrable to Phase-25).

**SIGHUP handler** — `_install_reload_signal._handle_hup` now calls `reload_engine.request_reload()`
instead of `.set()`ing its own Event (the engine owns the `reload_requested` Event now). Keep the
before-`scheduler.start()` install position (analog L1486-1490).

**Main poll loop** — replace the inlined `_do_reload` (L1636-1648) with `service_pending`, keeping the
SIGTERM-wins re-check and the `except`-swallow (CFG-04 keep-old end-to-end, L1649-1654):
```python
while not stop.wait(timeout=1.0):
    if stop.is_set():
        break
    try:
        reload_engine.service_pending(config_path)
    except Exception:                                  # a bad reload must NEVER crash the daemon
        _log.exception("reload failed; live config left intact")
```

**`finally`** — call `reload_engine.stop()` to join the (now engine-owned) observer thread, replacing
the `watch_thread.join` block (analog L1671-1679).

**`check-config` (D-06):** `run_self_check`/the `weatherbot check` CLI path (daemon.py L1135, cli.py
L421) stays an app-side ~3-line wrapper that calls `engine.check(path)` and maps the structured result
to an exit code.

---

### `tests/test_import_hygiene.py` (test, gate) — MODIFY (additive)

**Analog:** itself. The three standing gates **auto-scale** to the new `config` subpackage with NO edit
to their bodies:
- **grimp leak scan** (`test_module_imports_zero_app_code`, L165-179): builds over both packages, scans
  every module-owned importer via the `MODULE`-prefix filter — `config/reload.py` + `holder.py` are
  covered the instant they exist (`_scan_app_leaks` prefix check, L80-85).
- **isolated-import smoke** (`test_module_imports_with_app_blocked`, L255-257): walks
  `pkgutil.walk_packages` — the `config` subpackage is auto-included.
- **AST litmus** (`test_litmus_clean`, L343-348): walks `_MODULE_ROOT.rglob("*.py")` — `config/*.py`
  auto-included; asserts no `weather|forecast|location|openweather|\buv\b|briefing` NAME in any
  `def`/`class`/param/annotation (prose-immune).

**REQUIRED NEW assertion (Pitfall 1 / D-03)** — the grimp gate won't catch a third-party `pydantic`
import, so add an explicit gate (mirrors the existing grimp-graph idiom, L165-171):
```python
def test_config_module_never_imports_pydantic():
    graph = grimp.build_graph("yahir_reusable_bot", cache_dir=None)
    for mod in graph.modules:
        if mod.startswith("yahir_reusable_bot.config"):
            imported = graph.find_modules_directly_imported_by(mod)
            assert not any(t == "pydantic" or t.startswith("pydantic.") for t in imported), \
                f"{mod} must NOT import pydantic — validation is injected (D-03)"
```

---

## Shared Patterns

### Engine = constructor injection + opaque passthrough + thin verbs (D-07/D-08)
**Source:** `yahir_reusable_bot/scheduler/engine.py` (`SchedulerEngine`, L32-78 + docstring L1-25).
**Apply to:** `ReloadEngine`. Store collaborators by reference in `__init__`; expose thin verbs
(`reload`/`check`/`request_reload`/`service_pending`/`start_watching`/`stop`); invoke injected callables
opaquely (never inspect `T`, the validator's return, or the registrar's jobs); own **no lifecycle the
host owns** (no SIGHUP install, no main loop — D-05, mirroring `SchedulerEngine` owning no
`start`/`shutdown`).

### Subpackage barrel
**Source:** `yahir_reusable_bot/scheduler/__init__.py` (L1-13); also `ports/__init__.py`,
`channels/__init__.py`. **Apply to:** `yahir_reusable_bot/config/__init__.py` — module docstring +
`from .x import Y` + explicit `__all__`.

### App-side re-export shim (22-02)
**Source:** `weatherbot/reliability/__init__.py` (L1-28). **Apply to:** `weatherbot/config/holder.py`
— docstring states the move + D-number, re-exports from the module barrel, declares `__all__`; every
importer + the Phase-21 pins resolve to the identical object.

### Best-effort side-effect guard (post-then-raise timing, D-09)
**Source:** `_do_reload` L931-938 (reject) + L997-1015 (applied), and the daemon's `emit_online` idiom.
**Apply to:** `on_rejected`/`on_applied` invocation. Wrap each hook in its own `try/except`, log +
swallow on failure, NEVER let a hook failure mask the engine's own result. `on_rejected` fires inside
the `except` **before** `raise`; `on_applied` fires only in the committed-success branch.

### Validation routes through the injected concrete validator ONLY (D-03)
**Source:** `weatherbot/config/loader.py` `validate_config_and_templates` (L99-138) — validates the
concrete `Config` (`extra="forbid"`, all field validators, template-token allow-list) and returns the
full object. **Apply to:** the engine's `validate` hook + `check`. The module never validates; the
injected validator is typed `-> T` but returns the concrete `Config` (covariant; `isinstance` holds).

---

## No Analog Found

None. Every surface this phase creates or modifies has a direct in-repo analog — the module-side
`SchedulerEngine`/barrel/shim precedents (Phases 22-23) for the new files, and the app-side `daemon.py`
reload machinery for the lifted logic. This is the defining property of the phase: it draws a module
boundary around code that already exists and is golden-pinned.

---

## Metadata

**Analog search scope:** `yahir_reusable_bot/` (scheduler, ports, channels, reliability), `weatherbot/`
(config/holder.py, config/loader.py, scheduler/daemon.py, reliability/__init__.py, cli.py),
`tests/test_import_hygiene.py`.
**Files scanned:** 11 source/test files read (holder.py, loader.py, daemon.py [L600-714, 775-1027,
1214-1352, 1485-1696], engine.py, scheduler/ports/channels/reliability `__init__.py`,
test_import_hygiene.py).
**Pattern extraction date:** 2026-06-27
