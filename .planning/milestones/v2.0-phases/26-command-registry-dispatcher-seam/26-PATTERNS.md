# Phase 26: Command Registry + Dispatcher Seam - Pattern Map

**Mapped:** 2026-06-28
**Files analyzed:** 7 new/modified module + app pieces (+ 5 oracle/consumer files held byte-identical)
**Analogs found:** 7 / 7 (every new piece has a real in-repo analog — this is a relocation, not a greenfield seam)

> **Reading note for the planner:** every "new" module symbol here is a *verbatim or near-verbatim lift* of an existing app symbol, re-shaped to the module's constructor-injection / opaque-callable idiom. Behavior must stay **byte-identical** (Phase-21 CLI + `help` goldens + the ~649-test suite are the oracle). Prefer copying the named analog lines over inventing a new shape.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `yahir_reusable_bot/registry/spec.py` — generic `CommandSpec` (4 fields + `bind` + neutral fetch signal) | model (frozen dataclass) | transform | `weatherbot/interactive/registry.py` `CommandSpec` L27-42 | exact (same dataclass, fields shrunk) |
| `yahir_reusable_bot/registry/registry.py` — `CommandRegistry` + `build_registry(specs)` (computes `by_name` / keyword-len-desc / `render_help`, frozen) | service (registrar) | transform | `yahir_reusable_bot/scheduler/engine.py` `SchedulerEngine` (ctor-injection) + `registry.py` assembly L120-155 | role-match + assembly-exact |
| `yahir_reusable_bot/registry/match.py` — `match_command(text, specs)` free function | utility (parser) | transform | `weatherbot/interactive/command.py` `parse_command` L91-114 | exact (pure-plumbing lift) |
| `yahir_reusable_bot/registry/dispatch.py` — module dispatcher shell (`spec.bind(ctx)` inside `run_in_executor`) | service (dispatcher) | event-driven / request-response | `weatherbot/interactive/dispatch.py` `dispatch_spec` L105-186 | exact control-flow, weather branches removed |
| `yahir_reusable_bot/registry/__init__.py` — subpackage export surface | config (barrel) | — | `yahir_reusable_bot/config/__init__.py` / `scheduler/__init__.py` | exact idiom |
| `weatherbot/interactive/registry.py` — thin re-exporting singleton (`build_registry(_SPECS)` + re-export 4 globals byte-for-byte) | config (composition glue) | transform | itself, today (L120-155 globals are preserved verbatim) | exact (globals unchanged) |
| `weatherbot/scheduler/wiring.py` — author the per-command `bind` closures (verbatim lift of each `dispatch_reply` arm) | service (composition root) | transform | `wiring.py` `build_runtime` reload-engine closures L208-260 | exact idiom |
| `tests/test_import_hygiene.py` + `tests/test_injection_registry.py` — extend gates with registry/dispatch edges + positive command-injection assertion | test | — | both files, today (additive only) | exact idiom |

**Held byte-identical (NOT modified — they are the oracle / consumers that pin D-03):**
`tests/test_registry.py`, `tests/test_command_views.py`, `weatherbot/interactive/bot.py` (sole `parse_command` consumer), `weatherbot/interactive/panel.py` (import-time `registry.BY_NAME` assert), `weatherbot/cli.py` (`registry.COMMANDS` / `BY_NAME` reads). All keep their exact `registry.X` access against the re-exported globals.

---

## Pattern Assignments

### `yahir_reusable_bot/registry/spec.py` (model — generic `CommandSpec`)

**Analog:** `weatherbot/interactive/registry.py` `CommandSpec` L27-42 (frozen dataclass) + the opaque-callable precedent on the engines (`SchedulerEngine.register(callback)`, `ReloadEngine(validate=…)`).

**Shape to copy** (today's spec, L27-42 — the 5-field app version):
```python
@dataclass(frozen=True)
class CommandSpec:
    name: str
    group: str
    summary: str
    takes_location: bool
    handler: Callable | None = None
```

**Genericize to (D-02 + D-01):** drop `takes_location` and `handler`; add the opaque `bind` callable and the **neutral fetch signal** (D-01 follow-through — name it WITHOUT "Forecast", e.g. `fetch_kind: str | None` or `needs_flags: bool`, planner's discretion per CONTEXT D-01/Discretion):
```python
@dataclass(frozen=True)
class CommandSpec:
    name: str
    group: str          # generic help-header string; app fills "Weather"/"Forecast"/"Info"
    summary: str
    bind: Callable[["DispatchContext"], "CommandReply"]   # opaque, app-authored at the root
    # + ONE neutral pre-dispatch signal (replaces spec.group == "Forecast" at dispatch.py:153)
    # e.g. needs_flags: bool = False   OR   fetch_kind: str | None = None
```

**Why this shape (from CONTEXT):** `bind` mirrors the module's established "engines drive opaque app callables" precedent — exactly like `SchedulerEngine` never inspecting its `callback` (`engine.py` L44-70) and `ReloadEngine` never inspecting `validate`/`register_jobs` (`reload.py` L74-95). The module never reads the closure's body, so the litmus stays clean by construction.

**Litmus note:** `name`/`group`/`summary`/`bind` are all generic — pass the AST signature litmus. The `_SPECS` *content* (the strings `"weather"`, `"uv"`, `"Forecast"`) stays app-side in `weatherbot/interactive/registry.py`, never in the module.

---

### `yahir_reusable_bot/registry/registry.py` (service — `CommandRegistry` + `build_registry`)

**Analog (idiom):** `yahir_reusable_bot/scheduler/engine.py` `SchedulerEngine.__init__(self, scheduler)` L41-42 — constructor-injection of the app's collaborators, computed/frozen once. Also `ConfigHolder.__init__(self, config)` (holder.py L52-54). **Analog (the assembly being lifted):** `weatherbot/interactive/registry.py` L120-155.

**Constructor-injection idiom to copy** (engine.py L41-42):
```python
class SchedulerEngine:
    def __init__(self, scheduler: Any) -> None:
        self._scheduler = scheduler
```

**The three frozen views to compute once** — lift verbatim from `registry.py` L124-155, moving the *computation* into `CommandRegistry.__init__` (the app still owns the spec list it passes in):
```python
# BY_NAME — registry.py L124
BY_NAME: dict[str, CommandSpec] = {c.name: c for c in COMMANDS}

# Longest-keyword-first ordering — registry.py L128-130 (Pitfall 4: next-cloudy before any prefix)
COMMANDS_BY_KEYWORD_LEN_DESC: tuple[CommandSpec, ...] = tuple(
    sorted(COMMANDS, key=lambda c: len(c.name), reverse=True)
)
```

**`render_help` — lift verbatim** (registry.py L133-155): groups by `.group` first-appearance order, emits `  {name} \N{EM DASH} {summary}`. This is surface-agnostic and names no weather concept (`group` is generic) — moves into the module unchanged. **The EM DASH and two-space indent are golden-sensitive — copy the f-string byte-for-byte:**
```python
lines.append(f"  {spec.name} \N{EM DASH} {spec.summary}")
```

**Module API shape (D-02):** `CommandRegistry(specs)` exposes `.by_name`, `.commands`, `.by_keyword_len_desc`, `.render_help()`; `build_registry(specs)` is the thin constructor entry the app calls. Mirror the `__init__.py` barrel idiom (`config/__init__.py` L13-16: `from .reload import ReloadEngine` + `__all__`).

---

### `yahir_reusable_bot/registry/match.py` (utility — `match_command`)

**Analog:** `weatherbot/interactive/command.py` `parse_command` L91-114 — a pure, pitfall-dense longest-first + word-boundary matcher reading ONLY `spec.name`.

**Lift verbatim, parameterizing the spec source** (today it reads the module global `registry.COMMANDS_BY_KEYWORD_LEN_DESC` at L104; the module free function takes the ordered specs as an arg, D-04):
```python
def parse_command(text: str) -> ParsedCommand:
    stripped = text.strip()
    folded = stripped.casefold()
    for spec in registry.COMMANDS_BY_KEYWORD_LEN_DESC:      # → param: specs
        if not folded.startswith(spec.name):
            continue
        rest = stripped[len(spec.name) :]
        # Word-boundary guard: "sunny" never matches "sun" (T-06-02)
        if rest and not rest[0].isspace():
            continue
        arg = rest.strip() or None
        return ParsedCommand(spec=spec, arg=arg)
    return ParsedCommand(spec=None, arg=None)
```

**Load-bearing invariants (do NOT alter — proven by goldens/anti-drift):**
- Longest-keyword-first iteration (Pitfall 4 — `next-cloudy` before any shorter prefix).
- Word-boundary guard (whitespace must follow the keyword — `"sunny"` ≠ `"sun"`, `"status:"` ≠ `"status"`, T-06-02).
- Security (T-06-01): only `str.strip`/`str.casefold`/slicing — never `str.format`/`eval`/`exec`.

**Stays app-side (litmus-tripping — do NOT move):** `parse_forecast_flags` (command.py L138-186), `forecast_cache_suffix` (L189-200), `ForecastFlags` (L117-135), `_day_token` (L203-207). These trip `forecast`/`\buv\b`/day-token.

**Consumer note:** `match_command` has exactly ONE consumer — the Discord text path (`bot.py:489`). CLI (argparse already split the name) + panel (`custom_id → BY_NAME[name]`) resolve without it. So the matcher is opt-in module plumbing — a free function, NOT a registry method (D-04).

---

### `yahir_reusable_bot/registry/dispatch.py` (service — dispatcher shell)

**Analog:** `weatherbot/interactive/dispatch.py` `dispatch_spec` L105-186 (the off-loop `run_in_executor` control-flow shell) + `dispatch_reply` L88-102 (the weather arm ladder that LEAVES — it becomes the app's `bind` closures).

**The off-loop tail to copy verbatim** (dispatch.py L177-186) — this is the module's generic control flow; only the inner call collapses to `spec.bind(ctx)`:
```python
return await loop.run_in_executor(
    None,
    lambda: dispatch_reply(spec, result=result, config=config, flags=flags, daemon_state=daemon_state),
)
# → becomes, in the module shell:
return await loop.run_in_executor(None, lambda: spec.bind(ctx))
```

**Two coupling sites that BOTH must de-weather** (Specific Ideas — missing either leaves a weather noun in the module):

1. **The arm ladder → `bind` closures (D-01).** Today's `dispatch_reply` L88-102 branches on weather names + the group string `"Forecast"` + reads `config.cloud_threshold` / `config.uv.threshold`. Each arm becomes one app-authored `bind` closure (see wiring.py assignment below). The module shell calls `spec.bind(ctx)` and never sees the ladder:
```python
# dispatch.py L88-102 — the ladder that LEAVES the module (each arm → a bind closure):
if spec.takes_location:
    if spec.group == "Forecast":
        return spec.handler(result, flags)
    elif spec.name == "next-cloudy":
        return spec.handler(result, config.cloud_threshold)
    elif spec.name == "uv":
        return spec.handler(result, config.uv.threshold)
    else:
        return spec.handler(result)
elif spec.name == "status":
    return spec.handler(daemon_state)
elif spec.name == "locations":
    return spec.handler(config)
else:  # help
    return spec.handler()
```

2. **The fetch branch → a neutral signal (D-01 follow-through, MANDATORY).** `dispatch_spec` keys on `spec.group == "Forecast"` at L153 to choose the flags-parse + 3-arg cache-suffix branch. This is a SECOND coupling site. Replace `is_forecast = spec.group == "Forecast"` with the neutral spec field (`spec.needs_flags` / `spec.fetch_kind`) so the module's async wrapper stops naming a weather group:
```python
# dispatch.py L152-170 — the fetch branch (group=="Forecast" → neutral signal):
if spec.takes_location:
    is_forecast = spec.group == "Forecast"     # ← de-weather: read spec.needs_flags / fetch_kind
    lookup_name = arg
    suffix = None
    if is_forecast:
        if flags is None:
            flags = parse_forecast_flags(arg)   # ← app-side hook; module names no forecast
        lookup_name = flags.location
        suffix = forecast_cache_suffix(spec.name, flags)
    if is_forecast:
        result = await loop.run_in_executor(None, cache.lookup, lookup_name, config, suffix)
    else:
        result = await loop.run_in_executor(None, cache.lookup, lookup_name, config)
```
The forecast-flags parse + cache-suffix are litmus-tripping — they STAY app-side, reached via an app-supplied `prepare`/`fetch` hook on the spec OR via the neutral signal driving an app-injected fetch step (planner's discretion, CONTEXT D-01 follow-through + Discretion).

**Off-loop discipline to preserve (WR-02, dispatch.py L130-137 / L172-176):** the WHOLE ladder runs off-loop via `run_in_executor` because `status`'s `read_heartbeat` touches SQLite and must never block the gateway loop. Keep the uniform off-loop tail — replies stay byte-identical (the contractual suite proves it).

**`UnknownLocationError` BUBBLES (D-06):** not caught in the dispatcher — the bot/panel catch it at the call site (`bot.py:520`, `panel.py:505`). The module shell must NOT swallow it.

---

### `weatherbot/interactive/registry.py` (app — thin re-exporting singleton, D-03)

**Analog:** itself, today. The DECISIVE constraint (CONTEXT D-03 + Specific Ideas): `tests/test_registry.py` and `tests/test_command_views.py` do `from weatherbot.interactive.registry import COMMANDS, BY_NAME, COMMANDS_BY_KEYWORD_LEN_DESC, render_help`. The panel asserts `registry.BY_NAME` at **import time** (panel.py:98). So these four globals + `_SPECS` + `_wire_handlers` stay app-side; only the registry TYPE relocates.

**What this file keeps (byte-for-byte):**
- `_SPECS` (L50-82) — the actual weather command set + groups. **Stays app-side** ("WeatherBot owns the actual command set"). Note: under D-01 the per-spec `takes_location` + `handler` get absorbed into the app's `bind` closures (authored in wiring.py); whether the app's `CommandSpec` re-adds `takes_location` via a subclass/`meta` field for any code still reading it is Discretion (CONTEXT last bullet).
- `_wire_handlers` (L85-117) — the **lazy handler import** inside the function keeps `command.py`/`panel.py` registry imports acyclic (Established Patterns + Reusable Assets). The `replace(spec, handler=…)` pattern (L117) must survive the move.
- The four re-exported globals — build via the module: `_registry = build_registry(_SPECS)`, then re-export `COMMANDS = _registry.commands`, `BY_NAME = _registry.by_name`, `COMMANDS_BY_KEYWORD_LEN_DESC = _registry.by_keyword_len_desc`, `render_help = _registry.render_help` (exact names — all 6 consumers + the oracle pass by construction, not re-baselining).

**Lazy-import pattern to preserve** (registry.py L97-117):
```python
def _wire_handlers(specs):
    from weatherbot.interactive.commands import forecast, info, status, weather_views
    handlers = { "weather": weather_views.weather, ... "status": status.status }
    return tuple(replace(spec, handler=handlers[spec.name]) for spec in specs)
```

**Documented divergence (accepted, D-03):** the single composition root for the *registry* is **import-time** (this module's load), not call-time (`build_runtime`) — a conscious lowest-risk exception forced by the panel's import-time `BY_NAME` assert. Reusability stays real: a reminder bot calls `build_registry(its_own_specs)`.

---

### `weatherbot/scheduler/wiring.py` (app — author the `bind` closures)

**Analog:** the EXISTING `build_runtime` closure-injection block, `wiring.py` L208-260 — where every WeatherBot specific is injected as a closure into a reusable engine (`validate=`, `desired_jobs=`, `register_jobs=`, `restore=`, `on_applied=`). The `bind` closures follow this exact idiom: weather names + threshold reads are *allowed* to live here (the composition root).

**Closure-injection idiom to copy** (wiring.py L229-260, the ReloadEngine block):
```python
reload_engine: ReloadEngine[Config] = ReloadEngine(
    holder,
    SchedulerEngine(scheduler),
    validate=lambda p: validate_config_and_templates(p),
    desired_jobs=lambda cfg: daemon._desired_job_ids(ConfigHolder(cfg)),
    register_jobs=lambda cfg: daemon._register_jobs(scheduler, ConfigHolder(cfg), ...),
    ...
)
```

**Author each `bind` closure as a verbatim lift of one `dispatch_reply` arm** (D-01). The closure reads LIVE config from the dispatch context per-tap (NOT a value curried at build time — D-01 rejects Option d because thresholds are read per-tap via `holder.current()` so a SIGHUP reload isn't frozen stale). Shape, mirroring the arms in dispatch.py L88-102:
```python
# next-cloudy arm → its bind closure (reads config LIVE from ctx, not curried):
bind=lambda ctx: weather_views.next_cloudy(ctx.result, ctx.config.cloud_threshold)
# uv arm:
bind=lambda ctx: weather_views.uv(ctx.result, ctx.config.uv.threshold)
# forecast arm:
bind=lambda ctx: forecast.weekday_forecast(ctx.result, ctx.flags)
# status arm:
bind=lambda ctx: status.status(ctx.daemon_state)
# locations / help arms: ctx.config / ()
```

**Discretion (CONTEXT):** where the `bind` closures are authored (inline at `build_runtime` vs a small app-side factory beside `_SPECS`) and how `result`/`config`/`flags`/`daemon_state` are bundled into the `DispatchContext` the module hands them. Keep the call sites byte-identical (CLI: `dispatch_reply(...)` cli.py L624-630; bot: `dispatch_spec(...)` bot.py L512-519; panel: panel.py L522/L592).

---

### `tests/test_import_hygiene.py` + `tests/test_injection_registry.py` (extend the gates)

**Analog (negative litmus):** `tests/test_import_hygiene.py` — the mature 3-gate APP-02 litmus. **Additive only** — the gates auto-scale:
- The grimp gate (`test_module_imports_zero_app_code` L148-179) scans `startswith(MODULE + ".")` — the new `yahir_reusable_bot/registry/` package is covered with **no edit**.
- The isolated-import gate (`test_module_imports_with_app_blocked` L253-289) uses `pkgutil.walk_packages` — auto-covers the new package.
- The AST litmus (`test_litmus_clean` L361-391) does `_MODULE_ROOT.rglob("*.py")` — auto-covers it. **Add the registry files to the `scanned` coverage-gap assertion** (the L382 `{...} <= scanned` pattern) so a future relocation can't silently drop them.

The locked litmus term set `weather|forecast|location|openweather|\buv\b|briefing` (L61) is **D-13-locked — do NOT broaden**. Generic seam names (`CommandRegistry`/`CommandSpec`/`match_command`/`group`/`bind`/`needs_flags`/`fetch_kind`) are allowed and pass the AST signature scan.

**Analog (positive injection-registry assertion, D-05 extended to commands):** `tests/test_injection_registry.py`. Add an assertion proving the **command set is app-supplied, not baked** — mirroring the existing four leak-point checks. Copy the two introspection helpers + the self-proof discipline:
- `_required_params_without_default(func)` (L59-77) — assert `CommandRegistry.__init__` / `build_registry` REQUIRE the specs (no module-side baked default command set), exactly as `test_health_check_is_injected_no_module_default_probe` (L142-169) asserts `ReadyGate` requires `health_check`.
- `_module_public_symbols()` (L126-134) + the "no weather-named symbol" pattern (L241-245, L282-286) — assert NO module symbol bakes a weather command name/handler.
- **Pair every positive assertion with a deliberately-broken self-proof** (a stub that BAKES a default → proven to trip the same check), exactly the `_BakedGate` / `_BakedReload` discipline (L162-169, L210-216).

---

## Shared Patterns

### Constructor-injection of opaque app collaborators
**Source:** `yahir_reusable_bot/scheduler/engine.py` L41-42 (`SchedulerEngine(scheduler)`), `config/holder.py` L52-54 (`ConfigHolder(config)`), `config/reload.py` L74-95 (`ReloadEngine(holder, …, validate=, desired_jobs=, register_jobs=)`).
**Apply to:** `CommandRegistry(specs)` (D-02) + the `CommandSpec.bind` closure (D-01).
**The discipline:** the module STORES each collaborator and invokes it OPAQUELY — never inspecting its body, its return, or its args. `engine.py` L60-70 forwards `callback`/`args`/`kwargs` untouched; `reload.py` L132/L184 calls `self._validate`/`self._register_jobs` without inspecting. The `bind` closure is the per-command instance of this — the module calls `spec.bind(ctx)` and learns nothing about weather.

### App injects specifics; the module never assembles the app
**Source:** `weatherbot/scheduler/wiring.py` L208-260 — the single composition root where every weather concept arrives as an injected closure into a generic engine.
**Apply to:** the `bind` closures (weather names + `cloud_threshold`/`uv.threshold` reads live HERE, never in the module) and the app-side `_SPECS` content.

### Module-mechanism + app-side thin singleton re-export (D-03)
**Source:** the re-export pattern this phase introduces in `weatherbot/interactive/registry.py`; the barrel idiom in `yahir_reusable_bot/config/__init__.py` L13-16 / `scheduler/__init__.py` L11-13.
**Apply to:** the app's `registry.py` keeping `COMMANDS`/`BY_NAME`/`COMMANDS_BY_KEYWORD_LEN_DESC`/`render_help` byte-for-byte so the import-time-global consumers (`parse_command` call-time read; panel import-time assert) + the oracle stay byte-identical.

### Lazy handler imports keep registry imports acyclic
**Source:** `weatherbot/interactive/registry.py` `_wire_handlers` L97-117 (import inside the function, not at module top).
**Apply to:** preserve through the relocation — `command.py`/`panel.py` import the registry for the parser/allow-list without dragging the handler modules' `lookup`/`models` imports into the module-top graph (Pitfall 5). Mirrors the watch-backend lazy import in `reload.py` L272 and the daemon-resolution in `wiring.py` L135.

### Self-proof discipline on every gate
**Source:** `tests/test_import_hygiene.py` `_injected_app_leak` L121-141 + the `test_selfproof_*` pairs; `tests/test_injection_registry.py` `_BakedGate`/`_BakedReload` (L162-169, L210-216).
**Apply to:** every new registry/dispatch gate assertion — pair it with a deliberately-broken variant proven to trip the SAME helper, so a green run proves the gate bites (not a no-op).

---

## No Analog Found

None. Every new module piece is a relocation of an existing app symbol — `CommandSpec` (registry.py L27-42), the assembly/`render_help` (registry.py L120-155), `parse_command` (command.py L91-114), `dispatch_spec`/`dispatch_reply` (dispatch.py L88-186) — re-shaped to the module's already-shipped constructor-injection / opaque-callable idiom (`SchedulerEngine`/`ReloadEngine`/`ConfigHolder`). The one genuinely-new artifact is the `DispatchContext` DTO the `bind` closure receives, and even that is a trivial bundle of the four params `dispatch_reply` already takes (`result`/`config`/`flags`/`daemon_state`, dispatch.py L60-67).

---

## Metadata

**Analog search scope:** `weatherbot/interactive/{registry,command,dispatch,bot,panel}.py`, `weatherbot/cli.py`, `weatherbot/scheduler/wiring.py`, `yahir_reusable_bot/{scheduler,config,lifecycle}/`, `tests/test_import_hygiene.py`, `tests/test_injection_registry.py`.
**Files scanned:** 13 read in full + targeted reads of cli.py (L600-639) and bot.py (L505-529).
**Pattern extraction date:** 2026-06-28
