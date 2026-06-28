# Phase 25: Lifecycle READY-Gate + Composition Root - Pattern Map

**Mapped:** 2026-06-28
**Files analyzed:** 13 (4 new module/app files, 9 modified)
**Analogs found:** 13 / 13 (every new file has a strong in-repo precedent)

This is a **move-heavy code-extraction phase**, not greenfield. Every new module surface clones a
precedent already living in `yahir_reusable_bot/`. The lifecycle logic to lift already exists verbatim
in `weatherbot/scheduler/daemon.py` + `weatherbot/ops/`; the work is **relocate + parameterize +
lift weather/DB/Discord touches behind injected hooks**, keeping behavior byte-identical (Phase-21
goldens + ~649-test suite are the oracle).

---

## File Classification

| New/Modified File | New? | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|------|-----------|----------------|---------------|
| `yahir_reusable_bot/lifecycle/ready_gate.py` (`ReadyGate`) | NEW | engine | event-driven (re-probe loop + READY emit + heartbeat tick) | `yahir_reusable_bot/config/reload.py` (`ReloadEngine`) | exact (constructor-injection + symmetric best-effort hooks + interruptible loop) |
| `yahir_reusable_bot/lifecycle/sdnotify.py` (`SystemdNotifier`) | NEW (moved) | utility | request-response (one datagram) | `weatherbot/ops/sdnotify.py` (the same file, moved verbatim) | exact (pure move — already weather-clean) |
| `yahir_reusable_bot/lifecycle/identity.py` (`LifecycleIdentity` + pid/proc helpers) | NEW | model + utility | file-I/O (PID write/read) + transform (proc guard) | `weatherbot/ops/pidfile.py` + `yahir_reusable_bot/config/holder.py` (the module-constant-with-override + dataclass idioms) | role-match (parameterizing an existing helper) |
| `yahir_reusable_bot/lifecycle/health.py` (`HealthResult`) | NEW | model | transform (DTO) | `weatherbot/ops/selfcheck.py` (`CheckResult`) | exact (1:1 generic mapping of an existing dataclass) |
| `yahir_reusable_bot/lifecycle/__init__.py` | NEW | config (barrel) | n/a | `yahir_reusable_bot/scheduler/__init__.py` / `config/__init__.py` | exact |
| `weatherbot/.../wiring.py` (`build_runtime(...)`) | NEW | composition root | request-response (constructs + returns wired parts) | the `run_daemon` wiring block itself (`daemon.py` L1376–1612) | exact (lift-in-place, not redesign) |
| `weatherbot/scheduler/daemon.py` (`run_daemon`, `gate_until_healthy`, `emit_online`, `_heartbeat_tick`) | MOD | controller / orchestrator | event-driven | (own prior structure; keeps lifecycle ordering) | self |
| `weatherbot/ops/sdnotify.py` | MOD (delete/re-export) | utility | — | moves to module; app re-exports for back-compat | self |
| `weatherbot/ops/pidfile.py` | MOD | utility | file-I/O | generalized guard now takes `proc_marker`; default reproduces `weatherbot` | self |
| `weatherbot/ops/selfcheck.py` | MOD (boundary adapter) | service | request-response (probe) | stays app-side; `CheckResult` → adapt to `HealthResult` at the seam | self |
| `weatherbot/ops/__init__.py` + `weatherbot/cli.py` (`do_reload`) | MOD | re-exports / sender | — | byte-identical exit codes under the generalized guard | self |
| `deploy/bot.service.template` (+ `deploy/README.md`) | NEW (from `weatherbot.service`) | config | — | `deploy/weatherbot.service` (extend `<REPO>`/`<USER>` sed convention) | exact |
| `tests/test_import_hygiene.py` | MOD | test | — | itself (add positive injection-registry assertion; new `lifecycle` edges) | self |

---

## Pattern Assignments

### `yahir_reusable_bot/lifecycle/ready_gate.py` — `ReadyGate` (engine, event-driven)

**Analog:** `yahir_reusable_bot/config/reload.py` (`ReloadEngine`) — the constructor-injection +
opaque-passthrough + symmetric best-effort hook precedent (D-01). The interruptible loop body to lift
lives in `weatherbot/scheduler/daemon.py:gate_until_healthy` (L1108–1156) and `emit_online`
(L1159–1189); the heartbeat tick registration is `daemon.py` L1446–1451.

**Constructor + injection pattern** — clone `ReloadEngine.__init__` (`reload.py` L74–104): collaborators
positionally, hooks keyword-only with `| None = None`, store every collaborator by reference, never inspect.

```python
# reload.py L74-95 — the shape ReadyGate mirrors
def __init__(
    self,
    holder: ConfigHolder[T],
    scheduler_engine: Any,
    *,
    validate: Callable[[Any], T],
    ...
    on_applied: Callable[[str], None] | None = None,
    on_rejected: Callable[[Exception], None] | None = None,
) -> None:
    self._holder = holder
    ...
    self._on_applied = on_applied
    self._on_rejected = on_rejected
```

ReadyGate constructor becomes (names are planner discretion per CONTEXT): a `health_check: Callable[[], HealthResult]`,
a `notifier: SystemdNotifier`, `re_probe_interval: float` (default `RE_PROBE_INTERVAL_S = 120`, lifted
from `daemon.py` L133), and the symmetric hooks `on_online: Callable[..., None] | None` (the five-part
bundle) and `on_fail`/`on_probe: Callable[[HealthResult], None] | None` (the per-outcome `stamp_health`
row). Optionally a `scheduler_engine` handle for the heartbeat (D-01 option (a)) — or omit it and let
the app re-register the tick (sanctioned option (d)).

**Interruptible re-probe loop** — lift `gate_until_healthy` body VERBATIM, replacing the three weather
touches. The `stop.wait(...)`-not-`time.sleep` interruptibility is load-bearing (Pitfall 2) and goldens
pin it:

```python
# daemon.py L1134-1156 — lift verbatim; weather/DB touches go behind hooks
while not stop.is_set():
    result = run_self_check(config=config, settings=settings)   # -> self._health_check()  (injected)
    stamp_health(db_path, reason=result.reason, detail=result.detail)  # -> on_fail/on_probe hook (app)
    if result.ok:
        return True
    if result.reason == AUTH_FAILED:        # <-- MUST become a NEUTRAL severity field, NOT a weather string
        _log.critical("startup self-check auth failure", reason=result.reason, detail=result.detail)
    else:
        _log.warning("startup self-check not ready", reason=result.reason, detail=result.detail)
    if stop.wait(RE_PROBE_INTERVAL_S):   # interruptible — NEVER time.sleep (Pitfall 2)
        break
return False
```

**CRITICAL parameterize delta (D-02):** the `result.reason == AUTH_FAILED` branch names a weather
concept and would trip the litmus. The module must branch on a **neutral `HealthResult.severity`/`level`
field** (or the app pre-selects the log level in the hook). The module logs `reason`/`detail` opaquely
only — never compares to `"auth_failed"`.

**Five-part online emit** — lift `emit_online` (L1179–1189). The emit ORDERING is the real byte-identical
risk; preserve it exactly. Parts (1) `stamp_health(reason="online")`, (2) `stamp_tick`, (3) Discord ping
ride the **`on_online` hook** (app-side, D-02a — weather/DB); the module owns only part (4) `notifier.ready()`
and the structured online log:

```python
# daemon.py L1179-1189 — split: module keeps notifier.ready() + log; (1)(2)(5) -> on_online hook
stamp_health(db_path, reason="online")        # -> on_online (app)
stamp_tick(db_path)                           # -> on_online (app)
_log.info("weatherbot online", jobs=jobs)     # module log (rename the event key — "weatherbot" is a noun)
notifier.ready()                              # module owns this (READY=1)
if channel is not None:                        # -> on_online (app)
    result = channel.send("WeatherBot online — startup self-check passed.")
```

**Best-effort hook guard** — copy `ReloadEngine._best_effort_hook` (`reload.py` L312–326) verbatim: a
`None` hook is a no-op, a raise is logged + swallowed, never masks the gate result.

```python
# reload.py L312-326 — copy verbatim for the on_online / on_fail invocations
@staticmethod
def _best_effort_hook(hook, arg, *, label):
    if hook is None:
        return
    try:
        hook(arg)
    except Exception:  # noqa: BLE001 — best-effort; never mask the engine result
        _log.warning(f"{label} hook failed; engine result unaffected")
```

**Heartbeat tick** — the `__heartbeat__` IntervalTrigger registration to own/relocate:

```python
# daemon.py L1446-1451 — the gate registers this (option a) OR app re-registers (option d)
SchedulerEngine(scheduler).register(
    "__heartbeat__",
    IntervalTrigger(seconds=HEARTBEAT_INTERVAL_S),   # 600s, daemon.py L108
    _heartbeat_tick,                                 # stamp_tick + log -> stays an injected callable (DB touch)
    kwargs={"db_path": db_path},
)
```

---

### `yahir_reusable_bot/lifecycle/sdnotify.py` — `SystemdNotifier` (utility, request-response)

**Analog:** `weatherbot/ops/sdnotify.py` — **this is a pure move**. The file is stdlib-only
(`socket`/`os`), names no weather noun, and already mirrors the never-raise posture the module wants.
Move it verbatim (the whole 56-line file). The app keeps a re-export in `weatherbot/ops/__init__.py`
(`from yahir_reusable_bot.lifecycle import SystemdNotifier`) so `daemon.py`'s import stays stable, OR
`daemon.py`/`wiring.py` import from the new module path directly.

No parameterize delta. The litmus is clean (no weather names in its public surface).

---

### `yahir_reusable_bot/lifecycle/identity.py` — `LifecycleIdentity` + pid/proc helpers (model + utility, file-I/O)

**Analogs:** `weatherbot/ops/pidfile.py` (the helpers to generalize) + `yahir_reusable_bot/config/holder.py`
(the immutable-dataclass / module-constant-with-override idiom).

**Dataclass shape (D-03)** — an immutable `LifecycleIdentity` with **independent fields** (the four
identity facts are NOT one string — see CONTEXT specifics): `name`, `pid_file: Path`, `runtime_dir`,
`console_name`, `proc_marker: bytes`. Use `@dataclass(frozen=True)` mirroring `CheckResult`/`HealthResult`.

**Path parameterize delta** — `pidfile.py` already threads a per-callsite override (L40, L68), so the
seam is pre-drawn. Drop the hardcoded constant; the path comes from `identity.pid_file`:

```python
# pidfile.py L37 — the weatherbot literal to REMOVE (path becomes identity.pid_file)
PID_FILE: Path = Path("/run/weatherbot/weatherbot.pid")
```

**Proc-guard generalize delta** — `is_weatherbot_pid` → a marker-parameterized predicate
(e.g. `is_running_process(pid, *, proc_marker)`), keeping the argv0-basename + `-m`-module match logic.
The `b"weatherbot"` literal becomes the injected `proc_marker`:

```python
# pidfile.py L106-125 — generalize: b"weatherbot" -> proc_marker (keep the argv0 / -m logic byte-identical)
def _argv_is_weatherbot(cmdline: bytes) -> bool:
    argv = [part for part in cmdline.split(b"\x00") if part]
    if not argv:
        return False
    prog = Path(argv[0].decode("utf-8", "replace")).name
    if prog == "weatherbot":                       # -> prog == marker_str
        return True
    return b"-m" in argv[1:3] and b"weatherbot" in argv[1:4]   # -> proc_marker in argv[1:4]
```

**CRITICAL byte-identical constraint:** the default `LifecycleIdentity` the app constructs MUST reproduce
`/run/weatherbot/weatherbot.pid` + the `b"weatherbot"` marker EXACTLY, so `cli.py:do_reload`
(`cli.py` L489–509, exit codes) and the PID-recycling defense stay byte-identical. Keep the
`write_pid_atomic` temp+`os.replace` body (L49–65) and the `_read_proc_cmdline` /proc-degrade
(L128–139) unchanged.

**Note on litmus:** `_argv_is_weatherbot` and `is_weatherbot_pid` carry `weatherbot` in their NAMES — if
these helpers move into the module they MUST be renamed (generic), or they trip Gate 3. If they stay
app-side and only the struct + a generic guard move, the app keeps a thin wrapper. Planner's call on the
split; the module side must be noun-free.

---

### `yahir_reusable_bot/lifecycle/health.py` — `HealthResult` (model, transform)

**Analog:** `weatherbot/ops/selfcheck.py:CheckResult` (L48–59) — maps 1:1. Clone the dataclass,
strip the weather-reason vocabulary, ADD the neutral severity field D-02 mandates:

```python
# selfcheck.py L48-59 — the dataclass to generalize (drop PASS/NETWORK_NOT_READY/AUTH_FAILED constants)
@dataclass
class CheckResult:
    ok: bool
    reason: str       # opaque string the module logs but never compares
    detail: str = ""
```

`HealthResult(ok, reason, detail, severity)` — `reason`/`detail` stay opaque passthrough; `severity`
(neutral, e.g. an int or a `Level` enum the module owns) is what the gate branches CRITICAL/WARNING on
instead of `reason == AUTH_FAILED`. The app-side `run_self_check` STAYS in `weatherbot/ops/selfcheck.py`
(D-02a) and an adapter at the boundary maps `CheckResult.reason` → `HealthResult.severity` (e.g.
`AUTH_FAILED` → CRITICAL, else WARNING) so today's per-attempt severity log is preserved.

---

### `yahir_reusable_bot/lifecycle/__init__.py` — barrel

**Analog:** `yahir_reusable_bot/scheduler/__init__.py` / `config/__init__.py`. Copy the docstring +
explicit re-export shape exactly:

```python
# scheduler/__init__.py — the barrel shape to clone
from .engine import SchedulerEngine
__all__ = ["SchedulerEngine"]
```

Export `ReadyGate`, `SystemdNotifier`, `HealthResult`, `LifecycleIdentity` (+ the generic proc guard).

---

### `weatherbot/.../wiring.py` — `build_runtime(...)` (composition root, request-response)

**Analog:** the `run_daemon` wiring block ITSELF (`daemon.py` L1376–1612). D-04 chose option (d): a
**move, not a redesign**. Lift the ~230-line wiring block into one app-side `build_runtime(...)` that
constructs holder + `SchedulerEngine` + `ReloadEngine` + the new `ReadyGate` + channel + the four
injected leak points, and RETURNS the wired parts. `run_daemon` KEEPS the load-bearing lifecycle ordering.

**What MOVES into `build_runtime` (constructors, no order-sensitive lifecycle):**

```python
# daemon.py L1387-1393  channel-build-once
if channel is None and settings is not None:
    from weatherbot.channels import build_channel
    channel = build_channel(config, settings)
# daemon.py L1402-1427  scheduler + stop + holder + cache construction
scheduler = BackgroundScheduler(); stop = threading.Event(); holder = ConfigHolder(config); ...
# daemon.py L1429-1465  _register_jobs + __heartbeat__ + _register_uvmonitor_job
# daemon.py L1504-1561  the ReloadEngine + its _on_applied / on_rejected injection block
# (NEW) the ReadyGate construction wiring health_check=run_self_check-adapter, on_online, on_fail, LifecycleIdentity
```

The existing `ReloadEngine` construction (`daemon.py` L1530–1561) is the EXACT template for how
`build_runtime` injects the app specifics into the new `ReadyGate` — note how every WeatherBot specific
(`validate`, `desired_jobs`, `register_jobs`, `restore`, `excluded_ids`, `on_applied`, `on_rejected`)
arrives as a closure/lambda at the single site:

```python
# daemon.py L1530-1561 — the injection-at-root template ReadyGate follows
reload_engine: ReloadEngine[Config] = ReloadEngine(
    holder,
    SchedulerEngine(scheduler),
    validate=lambda p: validate_config_and_templates(p),
    ...
    excluded_ids=frozenset({"__heartbeat__", "__uvmonitor__"}),
    on_rejected=(... if channel is not None else None),
    on_applied=_on_applied,
)
```

**What STAYS in `run_daemon` (LOAD-BEARING ORDERING — do NOT split these):**

```python
# daemon.py L1476-1485  SIGTERM handler installed BEFORE the gate (Pitfall 2)
signal.signal(signal.SIGTERM, _handle)
# daemon.py L1569       SIGHUP -> reload_engine.request_reload()
# daemon.py L1576       write_pid_atomic(PID_FILE)  -> write_pid_atomic(identity.pid_file)
# daemon.py L1598-1610  reload_engine.start_watching(...)  (observer armed)
# daemon.py L1614-1639  the gate -> scheduler.start() -> emit_online ORDERING (READY strictly after both)
# daemon.py L1729-1761  finally: scheduler.shutdown / reload_engine.stop / bot.stop / PID_FILE.unlink
```

The single most golden-sensitive invariant (CONTEXT specifics): `READY=1` reaches systemd ONLY after the
gate returns True AND `scheduler.start()` — `daemon.py` L1619/L1628/L1634. `build_runtime` must NOT
emit READY; the gate's `on_online` first-pass does, at the same call site.

**Fallback (D-04 floor):** if any reload-golden perturbs under (d), keep procedural `run_daemon` and just
make the four injections explicit + documented (option a).

---

### Modified: `weatherbot/ops/selfcheck.py`, `ops/__init__.py`, `cli.py`

`run_self_check`/`CheckResult` STAY app-side (D-02a) — the litmus path is a weather path. Only a thin
boundary adapter (`CheckResult` → `HealthResult`) is added. `ops/__init__.py` updates its re-exports for
the moved `SystemdNotifier` + generalized guard. `cli.py:do_reload` (L465–509) must keep byte-identical
exit codes under the generalized `proc_marker` guard — the app constructs the default identity whose
marker is `b"weatherbot"`, so `is_weatherbot_pid(pid)` behavior is unchanged.

---

### `deploy/bot.service.template` (+ `deploy/README.md`) — D-03a

**Analog:** `deploy/weatherbot.service` — extend its existing `<REPO>`/`<USER>` sed-placeholder convention
(header L4–11, README L39–41) with `<NAME>`/`<RUNTIME_DIR>`. Parameterize the three identity-bearing lines:

```ini
# weatherbot.service L14 / L29 / L44 — the lines that parameterize
Description=WeatherBot — personal morning weather briefing daemon   # -> Description=<NAME> — ...
ExecStart=/usr/bin/uv run weatherbot run                            # -> ... run <NAME> run  (or keep app ExecStart)
RuntimeDirectory=weatherbot                                         # -> RuntimeDirectory=<RUNTIME_DIR>
# (PIDFile= if added) -> PIDFile=/run/<RUNTIME_DIR>/<NAME>.pid
```

Keep `Type=notify` / `NotifyAccess=main` / `TimeoutStartSec=infinity` / `Restart=always` (the supervised-
restart contract) byte-identical. The rendered unit after substitution must be byte-identical to today's
`weatherbot.service`. Document the new placeholders in `deploy/README.md` alongside `<REPO>`/`<USER>`.

---

### `tests/test_import_hygiene.py` — extend (D-05)

**Analog:** itself — the mature 3-gate litmus. Two additive changes, NO production behavior change:

1. The grimp + isolated-import gates auto-scale (`_scan_app_leaks` prefix check, L83) — they pick up the
   new `lifecycle` edges with no per-module edit. Just confirm the new module imports stay weather-noun-free
   (rename `is_weatherbot_pid`/`_argv_is_weatherbot`/the `"weatherbot online"` event key if they move).
2. ADD a **positive injection-registry test**: assert each of the four leak points — selected-location
   context (`panel.py:_selected_location` L323), the config id-deriver / exactly-once key
   (`store.py UNIQUE(...)` + `_desired_job_ids`), the health-check (`run_self_check`), and `render_embed`
   (`bot.py` L194) — is supplied **as an injected arg at the single root** (`build_runtime`) with **no
   module-side baked default**. Do NOT broaden the locked `_LITMUS` term set (L61) — generic seam names
   (`SelectedContext`/`health`/`embed`-render) are exactly what the module is meant to expose.

Mirror the existing self-proof discipline (every gate paired with a deliberately-injected violation that
must trip it — the `_injected_app_leak` pattern at L121–140).

---

## Shared Patterns

### Constructor-injection + opaque passthrough
**Source:** `yahir_reusable_bot/scheduler/engine.py` (`SchedulerEngine.__init__` L41) + `config/reload.py`
(`ReloadEngine.__init__` L74–104).
**Apply to:** `ReadyGate`. Collaborators positional, hooks keyword-only `| None = None`, store by reference,
never inspect the injected callable's return beyond the documented contract.

### Symmetric best-effort hooks (the Phase-24 D-09 precedent D-02 mirrors)
**Source:** `config/reload.py` — `_best_effort_hook` (L312–326) + the `on_applied`/`on_rejected`
invocation sites (L138, L163).
**Apply to:** `ReadyGate`'s `on_online` / `on_fail` hooks. A hook that raises is logged + swallowed and
NEVER masks the gate result. Invoke at today's EXACT call points to preserve emit ordering.

### Weather side-effects + durable I/O ride injected hooks (D-02a)
**Source:** the `_on_applied` closure in `daemon.py` (L1504–1528) — `channel.send` / `cache.invalidate` /
watch re-derive all best-effort, app-side, behind the engine hook.
**Apply to:** `stamp_health` / `stamp_tick` / the Discord online ping. They live in
`weatherbot/weather/store.py` (a literal weather path — the decisive finding) and stay app-side closures
the gate invokes. The module owns ZERO durable I/O.

### Module-constant-with-per-callsite-override → app-supplied identity (D-03)
**Source:** `weatherbot/ops/pidfile.py` (`PID_FILE` default + `pid_file=` override, L37/L40/L68).
**Apply to:** `LifecycleIdentity` — the per-callsite override generalizes to a struct the app constructs
once at the composition root and threads in.

### Immutable result DTO
**Source:** `weatherbot/ops/selfcheck.py:CheckResult` (`@dataclass`, L48–59).
**Apply to:** `HealthResult` — same shape + a neutral `severity`/`level` field, weather-reason constants
dropped.

### Subpackage barrel
**Source:** `yahir_reusable_bot/scheduler/__init__.py` / `config/__init__.py`.
**Apply to:** `lifecycle/__init__.py` — module docstring + explicit `from .x import Y` + `__all__`.

### App injects into module; module never assembles app (D-04)
**Source:** the `ReloadEngine(...)` construction at `daemon.py` L1530–1561 — every WeatherBot specific is a
closure passed at the single site.
**Apply to:** `build_runtime` is app-side; rules out a module-side `compose()`. The `ReloadEngine` block is
the literal template for wiring the new `ReadyGate`.

---

## No Analog Found

None. Every new surface has a strong in-repo precedent — this phase is extraction + parameterization, so
the analogs are unusually exact (the lifted code already exists and runs).

---

## Metadata

**Analog search scope:** `yahir_reusable_bot/` (scheduler, config, ports, channels), `weatherbot/ops/`,
`weatherbot/scheduler/daemon.py`, `weatherbot/interactive/panel.py`, `weatherbot/cli.py`,
`tests/test_import_hygiene.py`, `deploy/`.
**Files scanned:** 14
**Pattern extraction date:** 2026-06-28
