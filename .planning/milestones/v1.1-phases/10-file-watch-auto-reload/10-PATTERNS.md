# Phase 10: File-Watch Auto-Reload - Pattern Map

**Mapped:** 2026-06-16
**Files analyzed:** 5 (1 new test, 1 dependency manifest, 3 modified source) + observer wiring in daemon.py
**Analogs found:** 5 / 5 (all in-repo)

This phase is almost entirely *wiring*: a `watchfiles` observer thread sets the
existing `reload_requested` Event, funneling into Phase 9's untouched `_do_reload`.
Every new symbol has a direct in-repo analog. The planner should copy the established
seams below verbatim rather than invent new structure.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `weatherbot/scheduler/daemon.py` — `_run_watch_observer()` (new fn) | middleware (observer loop) | event-driven (fs → flag) | `_install_reload_signal()` (same file, ~793) | exact (flag-set-then-service-on-main-thread) |
| `weatherbot/scheduler/daemon.py` — `request_reload` closure (new) | utility (trigger seam) | event-driven | `_handle_hup` inner fn (same file, ~809) | exact |
| `weatherbot/scheduler/daemon.py` — `_derive_watch_dirs()` (new fn) | utility (watch-set derivation) | transform | `validate_config_and_templates` `{cfg.template}` set (`loader.py` ~131) | exact (reuse same contract) |
| `weatherbot/scheduler/daemon.py` — `run_daemon` observer start/stop (modified) | service (lifecycle) | request-response | `run_daemon` SIGTERM `try/finally` (same file, ~926/991) | exact |
| `weatherbot/scheduler/daemon.py` — `_do_reload` watch-set re-derive (modified) | service (reload) | event-driven | `_do_reload` success summary block (same file, ~618) | exact |
| `weatherbot/scheduler/daemon.py` — `WATCH_*` constants (new) | config (module const) | n/a | `HEARTBEAT_INTERVAL_S` (same file, ~103) | exact |
| `weatherbot/config/models.py` — `ReloadConfig` + `Config.reload` (new) | model | CRUD (validated field) | `Reliability` model + `Config.reliability` (~150/242) | exact |
| `weatherbot/config/loader.py` — watch-set source (read-only reference) | loader | transform | `validate_config_and_templates` (~99) | exact (no change; derivation reuses its `{cfg.template}` contract) |
| `pyproject.toml` — add `watchfiles>=1.2.0` | config (manifest) | n/a | existing `[project].dependencies` (~6) | exact |
| `tests/test_filewatch.py` (new) | test | event-driven | `tests/test_reload.py` (Wave-0 RED scaffold) | exact |

## Pattern Assignments

### `weatherbot/scheduler/daemon.py` — `_run_watch_observer()` + `request_reload` (middleware, event-driven)

**Analog:** `_install_reload_signal()` / `_handle_hup` — `weatherbot/scheduler/daemon.py` lines 793-814.

This is the canonical "flag-set-only, service-on-main-thread" pattern the observer must mirror exactly. The SIGHUP handler does NOTHING but `.set()` the Event; the main poll loop runs the work. D-02 funnels file-watch through the SAME Event.

**Flag-set-only seam to copy** (lines 807-814):
```python
reload_requested = threading.Event()

def _handle_hup(signum, frame):  # noqa: ANN001 — signal handler signature
    # FLAG-SET ONLY: never do reload work here (Pitfall 6 / signal-docs blessed).
    reload_requested.set()

signal.signal(signal.SIGHUP, _handle_hup)
return reload_requested
```
The new `request_reload` is the file-watch analog of `_handle_hup`: a zero-arg closure built in `run_daemon` that ONLY does `reload_requested.set()`. The observer thread is the analog of the signal-delivery context — it must never touch reload work, only set the flag (RESEARCH Pattern 1).

**Import idiom for `from watchfiles import watch`:** use the in-function lazy-import idiom already established for `build_channel` (lines 850-856) — keeps `watchfiles`' transitive Rust-binary imports off the module's import-time graph:
```python
if channel is None and settings is not None:
    from weatherbot.channels import build_channel   # lazy in-function import
    channel = build_channel(config, settings)
```

**`watch()` parameters (RESEARCH Pattern 2, locked D-05):** `step=400` (quiet window), `debounce=1600` (max grouping), `rust_timeout=500` (sub-second teardown — Pitfall #2), `stop_event=stop`, `yield_on_timeout=True`, `watch_filter=<config+templates only, never .env>`.

---

### `weatherbot/scheduler/daemon.py` — `WATCH_*` module constants (config)

**Analog:** `HEARTBEAT_INTERVAL_S = 600` — `weatherbot/scheduler/daemon.py` line 103.

Place the new constants at module level beside `HEARTBEAT_INTERVAL_S`:
```python
HEARTBEAT_INTERVAL_S = 600
```
New (D-05, RESEARCH Pattern 2):
```python
WATCH_QUIET_MS = 400         # D-05 quiet window (step)
WATCH_DEBOUNCE_MS = 1600     # max grouping (watchfiles default)
WATCH_RUST_TIMEOUT_MS = 500  # Pitfall #2: bounds stop_event teardown latency
```

---

### `weatherbot/scheduler/daemon.py` — `_derive_watch_dirs()` (utility, transform)

**Analog:** `validate_config_and_templates` referenced-template set — `weatherbot/config/loader.py` lines 128-137.

The watch-set derivation MUST reuse the same `{cfg.template}` contract so the watched set and the validated set never drift (RESEARCH Pattern 4, Assumption A3). Copy the build-over-a-SET idiom:
```python
# loader.py:128-137 — the contract to mirror
referenced_templates = {cfg.template}
for template_name in referenced_templates:
    if templates_dir is not None:
        text = load_template(template_name, templates_dir)
    else:
        text = load_template(template_name)
    validate_template(text)
```
`TEMPLATES_DIR` source for the directory — `templates/renderer.py` line 26:
```python
TEMPLATES_DIR = Path(__file__).resolve().parent
```
New helper (derive DIRECTORIES, not files — Pitfall #11c inode-swap safety):
```python
def _derive_watch_dirs(config: Config, config_path: Path) -> set[Path]:
    from templates.renderer import TEMPLATES_DIR  # lazy import, mirrors loader idiom
    dirs = {Path(config_path).resolve().parent}
    for _template_name in {config.template}:   # SET → future per-location templates extend free
        dirs.add(Path(TEMPLATES_DIR).resolve())
    return dirs
```

---

### `weatherbot/scheduler/daemon.py` — `run_daemon` observer start/stop (service, lifecycle)

**Analog:** `run_daemon` SIGTERM/SIGHUP setup (lines 858-922) + the `try/finally` shutdown (lines 926-1003), same file.

**Start point** — after `holder`/`scheduler`/`stop` are built and BEFORE the poll loop, gated on `config.reload.watch and config_path is not None`. Mirror the existing `stop = threading.Event()` / `reload_requested = _install_reload_signal()` wiring (lines 862-915) — the observer's `request_reload` closure captures the SAME `reload_requested` returned by `_install_reload_signal`.

**Existing finally to extend** (lines 991-1003) — add observer teardown ALONGSIDE `scheduler.shutdown`, never a new path:
```python
finally:
    if getattr(scheduler, "running", True):
        scheduler.shutdown(wait=False)
    # NEW (SC#3): stop.set() is idempotent (SIGTERM already set it); join within ~rust_timeout
    #   if watch_thread is not None:
    #       stop.set()
    #       watch_thread.join(timeout=2.0)
    PID_FILE.unlink(missing_ok=True)
    _log.info("daemon stopped")
```
Thread construction mirrors the daemon's existing threading posture (`threading.Event`, `BackgroundScheduler`): `threading.Thread(target=_run_watch_observer, name="weatherbot-filewatch", daemon=True)`.

**`config_path is None` gate** — reuse the exact guard the poll loop already applies (lines 966-971): file-watch only runs when a real config PATH exists.

---

### `weatherbot/scheduler/daemon.py` — `_do_reload` watch-set re-derive (service, event-driven)

**Analog:** `_do_reload` success summary block — `weatherbot/scheduler/daemon.py` lines 618-627.

D-04 re-derives the watch set AFTER a successful swap. Add the mutation right after the existing success-summary log:
```python
# daemon.py:618-627 — the success point to hook AFTER
summary = f"+{added} -{removed} ~{changed} ={unchanged}"
_log.info("reload applied", added=added, removed=removed, changed=changed,
          unchanged=unchanged, summary=summary)
_stdlog.info("reload applied %s", summary)
# NEW (D-04): after this success block —
#   if watch_dirs_ref is not None and config_path is not None:
#       watch_dirs_ref[0] = _derive_watch_dirs(new_cfg, Path(config_path))
```
**Signature compatibility:** thread `watch_dirs_ref` into `_do_reload` as an OPTIONAL kwarg defaulting to `None` (mirror how `config`/`settings`/`client`/`channel` are already optional keyword params, lines 531-542) so the SIGHUP/CLI-only callers and the Phase-9 `test_reload.py` callers stay unaffected.

---

### `weatherbot/config/models.py` — `ReloadConfig` + `Config.reload` (model, CRUD)

**Analog:** `Reliability` model + `Config.reliability` field — `weatherbot/config/models.py` lines 150-227 and line 242.

D-03's `[reload] watch` toggle is structurally identical to the existing optional `[reliability]` section: a frozen `BaseModel` with `extra="forbid"`, added as a `default_factory` field on `Config` so existing configs (no `[reload]` table) load unchanged.

**Frozen model header to copy** (line 172):
```python
model_config = ConfigDict(extra="forbid", frozen=True)
```
**Default-factory field idiom to copy** (`Config`, lines 237-242):
```python
class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    locations: list[Location]
    template: str = DEFAULT_TEMPLATE
    webhook: WebhookIdentity = Field(default_factory=WebhookIdentity)
    reliability: Reliability = Field(default_factory=Reliability)
```
New (RESEARCH Pattern 3):
```python
class ReloadConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    watch: bool = True            # D-03: ON by default; [reload] watch = false disables

# on Config:
    reload: ReloadConfig = Field(default_factory=ReloadConfig)
```
`Field`, `ConfigDict`, `BaseModel` are already imported at line 12 — no new imports needed.

---

### `pyproject.toml` — add `watchfiles>=1.2.0` (config, manifest)

**Analog:** existing `[project].dependencies` block — `pyproject.toml` lines 6-14.

Add into the sorted runtime deps list (NOT dev-group):
```toml
dependencies = [
    "apscheduler>=3.11.2,<4",
    "discord-webhook>=1.4.1",
    "httpx>=0.28.1",
    "pydantic>=2.13.4",
    "pydantic-settings>=2.14.1",
    "structlog>=26.1.0",
    "tenacity>=9.1.4",
    "watchfiles>=1.2.0",   # NEW (D-01) — alphabetical position
]
```
Apply via `uv add watchfiles` (updates `uv.lock`). **Note:** CLAUDE.md's stack table does NOT list `watchfiles`; RESEARCH verified `1.2.0` (2026-05-18, `requires-python >=3.10`, satisfies project `>=3.12`) as `[VERIFIED: PyPI]`. This is a blocking install task BEFORE the observer module imports.

---

### `tests/test_filewatch.py` (test, event-driven) — NEW

**Analog:** `tests/test_reload.py` (Phase 9 Wave-0 RED scaffold), lines 1-120.

Mirror the Wave-0 lazy-import idiom EXACTLY: reference the not-yet-built observer/derivation symbols through PER-TEST deferred imports (NOT module-top) so every node ID collects RED instead of crashing collection.

**Deferred-import helper to copy** (`test_reload.py` lines 52-62):
```python
def _do_reload(*args, **kwargs):
    from weatherbot.scheduler.daemon import _do_reload as engine
    return engine(*args, **kwargs)
```
New equivalents: `_run_watch_observer`, `_derive_watch_dirs`, `_make_watch_filter` each behind their own deferred-import wrapper.

**Local config builders to copy verbatim** (`test_reload.py` lines 83-95) — no new shared fixtures:
```python
def _loc(name, *, id=None, tz="America/New_York", schedule=None, lat=40.7128, lon=-74.006): ...
def _cfg(*locations): return Config(locations=list(locations))
def _slot(time="07:00", days="daily", enabled=True): ...
```
**Imports block to mirror** (`test_reload.py` lines 35-40): `from weatherbot.config import Config, Location`, `from weatherbot.config.holder import ConfigHolder`, `from weatherbot.config.models import Schedule`.

**Test coverage required** (RESEARCH Validation Architecture → Test Map):
- `test_save_triggers_reload` (SC#1)
- `test_editor_save_patterns_one_reload` (SC#2 — truncate-write / temp-then-rename / multi-event burst → exactly ONE reload)
- `test_fd_stable_and_clean_teardown` (SC#3 — fd delta within a small fixed tolerance via stdlib `len(os.listdir(f"/proc/{os.getpid()}/fd"))` (NO `psutil` — not installed), sampled after a bounded settle window across ≥50 inode-swapping saves incl. a watch-set-changing reload (A4); SIGTERM → `thread.join(timeout=2.0)` returns, `is_alive()` False)
- `test_invalid_save_keeps_old_config` (SC#4 — assert keep-old THROUGH the file-watch trigger; reuse `test_reload.py` builders + real `_do_reload`)
- `test_identical_save_zero_job_changes` (idempotence — `+0 -0 ~0 =N`)
- `test_watch_toggle_off_no_observer` (D-03 — observer not started; SIGHUP still works)
- `test_env_save_never_reloads` (Pitfall #12 — `.env` edit → ZERO reloads)
- `test_watch_set_rederived_on_reload` (D-04 — new template dir becomes watched)

**Test seam:** inject `request_reload` as a `Mock`/counter so SC#1/SC#2 assert the trigger fires WITHOUT standing up the whole `_do_reload` (which has Phase-9 coverage). Drive real temp dirs via `tmp_path`; use bounded `reload_requested.wait(timeout=2.0)` over `sleep` for flake control, with `rust_timeout=500` so no test blocks 5s.

## Shared Patterns

### Flag-set-then-service-on-main-thread
**Source:** `_install_reload_signal` / `_handle_hup` — `weatherbot/scheduler/daemon.py` lines 807-814.
**Apply to:** the observer thread + `request_reload` closure.
The observer thread (like the signal handler) ONLY `.set()`s `reload_requested`; the reload itself ALWAYS runs on the main poll-loop thread via `_do_reload` (lines 961-988). Never run reload work off the main thread (Pitfall #6/#9).
```python
def _handle_hup(signum, frame):
    reload_requested.set()   # FLAG-SET ONLY
```

### Lazy in-function import (heavy/transitive deps)
**Source:** `build_channel` import (lines 850-856) and `validate_config_and_templates`'s `from templates.renderer import ...` (`loader.py` line 123).
**Apply to:** `from watchfiles import watch` inside `_run_watch_observer`, and `from templates.renderer import TEMPLATES_DIR` inside `_derive_watch_dirs`.
Keeps the Rust-binary / renderer transitive graph off the daemon module's import-time path and avoids partial-init cycles.

### Optional-keyword-param signature extension (non-breaking)
**Source:** `_do_reload` keyword-only optional params — `weatherbot/scheduler/daemon.py` lines 531-542.
**Apply to:** threading `watch_dirs_ref=None` into `_do_reload`.
New optional kwargs default to `None` so every existing caller (SIGHUP path, CLI `reload`, Phase-9 `test_reload.py`) stays green.

### Frozen `extra="forbid"` config model + default-factory field
**Source:** `Reliability` + `Config.reliability` — `weatherbot/config/models.py` lines 172, 242.
**Apply to:** `ReloadConfig` + `Config.reload`.
A new validated section that an existing `[reload]`-less config loads unchanged.

### Wave-0 deferred-import RED test scaffold
**Source:** `tests/test_reload.py` lines 46-72.
**Apply to:** `tests/test_filewatch.py`.
Reference not-yet-built symbols through per-test lazy-import wrappers so all node IDs COLLECT (fail RED individually) rather than crashing collection.

## No Analog Found

None. Every new file/symbol maps to a concrete in-repo analog. The only genuinely
new mechanism — the `watchfiles.watch()` generator itself — is an external library
call whose parameters are fully specified in RESEARCH Pattern 1/2 (no local analog
needed; the surrounding wiring all has analogs above).

## Metadata

**Analog search scope:** `weatherbot/scheduler/daemon.py`, `weatherbot/config/models.py`, `weatherbot/config/loader.py`, `templates/renderer.py`, `tests/test_reload.py`, `pyproject.toml`.
**Files scanned:** 6 (all read directly; no Glob fan-out needed — RESEARCH already pinned the exact analog line numbers).
**Pattern extraction date:** 2026-06-16
