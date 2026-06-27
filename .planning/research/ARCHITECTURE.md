# Architecture Research

**Domain:** Brownfield extraction — decoupling a reusable, channel-agnostic Python bot framework out of a single-purpose weather app (v2.0 "The Great Decoupling")
**Researched:** 2026-06-27
**Confidence:** HIGH

> Scope: this is a **pure-extraction architecture study**, not a greenfield design. The 649-test suite is the behavior contract; every pattern below is chosen to preserve byte-identical behavior while un-braiding *mechanism* (goes to the module) from *content* (stays in the WeatherBot app). All findings are grounded in the **actual current code** (`weatherbot/` read directly) plus current (2026) pydantic v2 / PEP 544 / APScheduler 3.x / discord.py 2.7 guidance.

---

## Standard Architecture

### Target System Overview — layered core + per-channel adapters

```
┌──────────────────────────────────────────────────────────────────────┐
│  APP LAYER  (WeatherBot — the "content")                               │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │
│  │ AppConfig     │ │ weather/*     │ │ registry      │ │ Discord       │  │
│  │ (locations,   │ │ fetch+render  │ │ COMMANDS      │ │ panel content │  │
│  │ [uv],templates)│ │ → CommandReply│ │ (weather/uv…) │ │ (loc dropdown,│  │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ │ 2×2 grid)     │  │
│         │ extends         │ supplies         │ registers └──────┬───────┘  │
├─────────┼─────────────────┼──────────────────┼──────────────────┼─────────┤
│  ADAPTER LAYER  (per-channel — Discord now; SMS/Telegram/Slack later)    │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ DiscordAdapter: gateway BotThread + persistent-view PANEL builder    │ │
│  │   (registry→buttons, SelectedContext, defer-then-edit, operator gate)│ │
│  │ DiscordChannel: Channel.send(text) webhook impl                      │ │
│  └────────────────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────────────┤
│  CORE LAYER  (channel-agnostic "mechanism" — the reusable module)        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐        │
│  │ SchedulerEng │ │ ConfigReload │ │ Channel ABC/ │ │ Lifecycle/   │        │
│  │ register(    │ │ Holder[T] +  │ │ Protocol +   │ │ health-check │        │
│  │ id,trigger,  │ │ validate→swap│ │ Delivery     │ │ READY gate   │        │
│  │ callback) +  │ │ →reconcile + │ │ reliability  │ │ (app cb)     │        │
│  │ JobStore seam│ │ watch+SIGHUP │ │ (retry/alert)│ │              │        │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘        │
│        ▲ DI: Protocols / callables — CORE NEVER IMPORTS APP OR ADAPTER ▲  │
└──────────────────────────────────────────────────────────────────────────┘
```

The single inviolable rule (the litmus test "could a reminder bot use this with zero weather assumptions?"): **dependencies point downward and inward only.** App imports Adapter imports Core. Core imports neither. Every place Core needs app behavior, it receives it through an injected **Protocol** or **callable**, never an import.

### Component Responsibilities

| Component | Owns (mechanism) | Does NOT own (content) | Current code it's extracted from |
|-----------|------------------|------------------------|----------------------------------|
| **SchedulerEngine** | `register(job_id, trigger, callback)`, arbitrary triggers, generic exactly-once `(job_id, occurrence)` keying, DST, restart catch-up, JobStore seam | What a job *does*, what "occurrence" means semantically, the weather fetch | `scheduler/daemon.py` `_register_jobs` / `fire_slot` / `claim_slot` / `_reconcile_jobs` |
| **ConfigReloadEngine** | generic `Holder`, validate→atomic-swap→reconcile, file-watch (`watchfiles`), SIGHUP | the config *schema* (locations/`[uv]`/templates), the *desired-job-id* derivation | `config/holder.py` + `daemon.py` `_do_reload`/`_reconcile_jobs` |
| **Channel + reliability** | `Channel` interface, retry/backoff/Retry-After/alert/heartbeat | embed look, webhook URL, weather text | `channels/base.py`, `reliability/retry.py` |
| **Lifecycle** | systemd `Type=notify` READY-gate, supervised restart | what "healthy" means | `ops/sdnotify.py`, `ops/selfcheck.py` (the *engine*; the probe stays app-side) |
| **PanelKit** (Discord adapter) | registry→control-surface builder, persistent-view plumbing, `SelectedContext`, ack/operator-gate/isolation envelope | the location dropdown, forecast grid, 📍/emoji polish | `interactive/panel.py`, `interactive/dispatch.py` |

---

## Recommended Project Structure

Two repos at the end. **In-place package boundary first** (still inside `weatherbot/`), then physical split.

```
# END STATE — the module repo (own GSD project)
botkit/                          # the channel-agnostic core + adapters
├── core/
│   ├── scheduler/
│   │   ├── engine.py            # SchedulerEngine.register(job_id,trigger,callback)
│   │   ├── triggers.py          # Trigger value-objects (cron/interval/date) — adapter to APScheduler
│   │   ├── occurrence.py        # generic exactly-once: OccurrenceStore Protocol + claim(key)
│   │   └── jobstore.py          # JobStore Protocol (in-memory impl; durable = deferred ext point)
│   ├── config/
│   │   ├── holder.py            # ConfigHolder[T] — generic over an app BaseConfig
│   │   └── reload.py            # ReloadEngine: validate→swap→reconcile + watch + SIGHUP
│   ├── delivery/
│   │   ├── channel.py           # Channel Protocol/ABC + DeliveryResult
│   │   └── reliability.py       # retry/backoff/Retry-After/alert/heartbeat
│   ├── lifecycle.py             # READY-gate + HealthCheck Protocol (app cb)
│   └── seams.py                 # ALL Protocols collected (the documented plug points)
├── adapters/
│   └── discord/
│       ├── channel.py           # DiscordChannel(Channel)
│       ├── botthread.py         # gateway thread, started after READY, torn down in finally
│       └── panel.py             # PanelKit: registry→view builder + SelectedContext
└── docs/EXTENSION-GUIDE.md      # documented seams: implemented vs deferred (durable jobstore)

# END STATE — the WeatherBot app repo (consumes botkit via uv git dep)
weatherbot/
├── config_schema.py             # AppConfig(BaseConfig) — locations/[uv]/templates + reconcile hook
├── weather/                     # UNCHANGED — pure content
├── commands/                    # registry COMMANDS (weather/uv/next-cloudy/sun/wind/forecast…)
├── panel_content.py             # location dropdown + 2×2 forecast grid + 📍/emoji + render_embed
└── main.py                      # composition root: wires app content INTO botkit core+adapter
```

### Structure Rationale

- **`core/seams.py` collects every Protocol in one file.** This *is* the extension-guide surface. A future reminder bot reads this file to know exactly what it must supply. It is the structural enforcement of "could a reminder bot use this?"
- **`scheduler/occurrence.py` separated from `scheduler/engine.py`.** Today exactly-once (`claim_slot`) is braided into `fire_slot` *and* SQLite. The generic engine keys exactly-once on an opaque `(job_id, occurrence)` and delegates the *storage* to an `OccurrenceStore` Protocol — WeatherBot's SQLite `claim_slot` becomes one impl; a reminder bot could use an in-memory or its own store.
- **`config/holder.py` generic, `config_schema.py` app-side.** The reload mechanism must validate-and-swap a model whose fields it does not know. The split is the whole "generic config over an app-defined schema" seam.
- **`render_embed` moves app-side** (into `panel_content.py`) — this is the proper resolution of the panel↔render cycle (see Pattern 4), not a cosmetic move.

---

## Architectural Patterns

### Pattern 1: Protocol-based DI seams (PEP 544) — keep Core from importing app code

**What:** Each thing Core needs from the app is a `Protocol` (structural type) Core defines and the app satisfies by *shape*, with no inheritance or import back into Core. This is the load-bearing pattern for the whole milestone.

**When to use:** every Core↔App / Core↔Adapter boundary: `JobStore`, `OccurrenceStore`, `Channel`, `HealthCheck`, and the reconcile/validate hooks.

**Trade-offs:** Protocols give zero-coupling structural typing (the reminder-bot litmus passes for free) but `@runtime_checkable` only verifies *member presence*, not signatures — so keep them small and lean on the test suite + a static checker (mypy/pyright). Use an **ABC** only when you also want a shared base *implementation* to inherit *within one codebase* (the current `Channel(ABC)` with its `send_briefing` default is a legitimate ABC; a *cross-repo* seam like `JobStore` should be a Protocol).

**Decision rule (Protocol vs ABC vs bare callable):**
- **Bare callable** for a single-method, stateless hook (`HealthCheck = Callable[[], CheckResult]`, the reconcile `desired_ids` hook). Simplest; no class needed.
- **Protocol** for a multi-method seam crossing the repo boundary (`JobStore`, `OccurrenceStore`). No import of app code, app impl needs no base class.
- **ABC** only when Core ships a reusable partial implementation subclasses extend *inside the module* (keep `Channel` ABC for its `send_briefing`→`send` default; optionally also expose a `Channel` Protocol alias for adapters that don't want the base).

```python
# core/seams.py — Core defines the shapes; it imports NOTHING from app/adapter.
from typing import Protocol, runtime_checkable

@runtime_checkable
class OccurrenceStore(Protocol):
    """Generic exactly-once claim store. WeatherBot's SQLite claim_slot satisfies this."""
    def claim(self, job_id: str, occurrence: str) -> bool: ...   # True = this caller won
    def release(self, job_id: str, occurrence: str) -> None: ...

@runtime_checkable
class JobStore(Protocol):
    """In-memory impl now; durable impl is the deferred extension point."""
    def add(self, job_id: str, spec: "JobSpec") -> None: ...
    def all(self) -> "list[JobSpec]": ...
    def remove(self, job_id: str) -> None: ...

class HealthCheck(Protocol):                 # app-provided startup self-check
    def __call__(self) -> "CheckResult": ...
```

### Pattern 2: Generic config holder over an app-defined schema (pydantic v2)

**What:** `ConfigHolder` and the reload engine operate on a `BaseConfig` (or a `TypeVar` bound to it) without knowing the app's fields. WeatherBot's `AppConfig(BaseConfig)` adds `locations`/`[uv]`/templates; a reminder bot's `AppConfig` has none of those.

**When to use:** the config hot-reload seam — the high-effort one.

**Trade-offs / the pydantic v2 gotcha (verified):** pydantic v2 *does* support `class Holder(BaseModel, Generic[T])`, **but** an **unparametrized** generic falls back to the `TypeVar`'s bound and **silently drops subclass fields** on validation. So do **not** route validation through an unparametrized `Holder[T]`. Two safe shapes:

1. **Preferred — the holder is a plain (non-pydantic) container; the app model is concrete.** The reload engine receives a *validator callable* `validate: Callable[[Path], BaseConfig]` (app-provided, closes over the concrete `AppConfig`) and a `BaseConfig` instance. The holder just rebinds the reference (exactly today's `ConfigHolder`, generalized off `Config`). No generic-validation pitfall at all. **This is the recommended path** — it matches the current `_do_reload(config_path)` → `validate_config_and_templates(config_path)` shape, which already delegates validation to an app-shaped function.
2. If you want static typing on the held value, use `TypeVar('T', bound=BaseConfig)` on the *holder's read API only* (`current() -> T`), and have the app **explicitly parametrize** `ConfigHolder[AppConfig]` at the composition root — never let Core construct an unparametrized `Holder[T]` for validation.

```python
# core/config/holder.py
from typing import Generic, TypeVar
T = TypeVar("T", bound="BaseConfig")

class ConfigHolder(Generic[T]):
    """Lock-free current() / locked replace() — generalized from weatherbot today.
    Holds an app-defined frozen BaseConfig subclass; never validates it itself."""
    def __init__(self, config: T) -> None: self._config = config; self._lock = Lock()
    def current(self) -> T: return self._config              # one atomic LOAD_ATTR
    def replace(self, new: T) -> None:
        with self._lock: self._config = new
```

**The reconcile "diff old vs new" hook (the part Core cannot know):** Core's reload engine runs `validate → swap → reconcile`, but *what jobs the new config wants* is app knowledge. Inject it as a **callable seam**, exactly mirroring today's `_desired_job_ids(holder)`:

```python
# Core's reload engine signature — app supplies desired_jobs + register/remove
def reload(self, holder, *, validate, desired_jobs, engine) -> ReloadStats:
    new = validate(self.path)              # app-shaped validator; raises → keep-old
    old = holder.current(); holder.replace(new)
    try:
        return engine.reconcile(desired_jobs(new))   # desired_jobs: app callable → set[JobSpec]
    except Exception:
        holder.replace(old); engine.reconcile(desired_jobs(old)); raise   # all-or-nothing rollback
```

`desired_jobs` is WeatherBot's per-location/weekday-weekend enumeration (today's `_register_jobs` loop + `_desired_job_ids`); Core only sees a `set[JobSpec]` to diff.

### Pattern 3: Scheduler engine generalization — one `register()` surface over APScheduler

**What:** Wrap APScheduler so `register(job_id, trigger, callback)` is the only surface. `trigger` is a Core value-object (`Cron(...)`, `Interval(...)`, `Date(...)`) the engine maps onto APScheduler's `CronTrigger`/`IntervalTrigger`/`DateTrigger`. Exactly-once is generic: the engine wraps every callback so it `claim(job_id, occurrence)`s via the injected `OccurrenceStore` *before* invoking the app callback, returning early on a lost claim.

**When to use:** the scheduler seam. Everything WeatherBot does today (briefing slots, forecast slots, UV monitor interval, heartbeat) becomes `engine.register(...)` calls.

**Trade-offs & the load-bearing constraint (verified):**
- Keep WeatherBot's proven choices as the engine defaults: `misfire_grace_time=None`, `coalesce=True`, `max_instances=1`, per-location timezone on the trigger. Cross-restart recovery stays owned by the sent-log + catch-up scan, **not** APScheduler (today's explicit anti-pattern note).
- **The durable-JobStore serialization constraint is the reason the JobStore seam is *designed now, built later*.** APScheduler persists a job by serializing its callable; a persistent jobstore requires the callable to be a **globally importable top-level function** (`module:function` textual reference) with only picklable kwargs — lambdas, bound methods, and closures raise *"reference to its callable could not be determined."* WeatherBot today registers `fire_slot` (a top-level function) but threads **non-picklable kwargs** (`holder`, `client`, `channel`, `stop_event`) — fine for the in-memory `MemoryJobStore`, fatal for a durable one. So:
  - **Now:** in-memory engine, callbacks may be any callable, kwargs may be live objects.
  - **Deferred (documented):** for the durable path, the seam must take a **registered-callable key** (the engine resolves a key→top-level function at fire time) and **picklable params only** (ids/strings, re-hydrated from the holder at fire time, never the live object). Record this as the durable-jobstore extension-point's contract so a reminder bot adding runtime-dynamic durable jobs knows the rules up front.

```python
# core/scheduler/engine.py
class SchedulerEngine:
    def __init__(self, store: OccurrenceStore, jobstore: JobStore | None = None): ...
    def register(self, job_id: str, trigger: Trigger, callback: Callback, *,
                 occurrence_of: Callable[[datetime], str]) -> None:
        def _guarded(occurrence: str, **kw):
            if not self._store.claim(job_id, occurrence):   # generic exactly-once
                return None
            return callback(**kw)                           # app's work
        self._aps.add_job(_guarded, trigger.to_aps(), id=job_id,
                          misfire_grace_time=None, coalesce=True, max_instances=1)
```

`occurrence_of` is the app's mapping from a fire time to the dedup key — WeatherBot's `local_date.isoformat()` (per-tz), a reminder bot's per-reminder occurrence. Core never hard-codes "local_date."

### Pattern 4: discord.py panel reuse — registry-driven persistent view + `SelectedContext`, cycle resolved

**What:** A `PanelKit` in the Discord adapter builds a persistent `discord.ui.View` from the app's command registry plus an app-supplied content spec (rows/labels/emoji). The "panel holds a selected context that commands act on" idea is generalized into a `SelectedContext[I]` (WeatherBot's selected *location* is `SelectedContext[str]`).

**When to use:** the Discord adapter only — SMS/Slack have no buttons, so this lives **below** the channel-agnostic core, inside the Discord adapter (correct per the milestone's layering).

**Resolving the `panel ↔ render_embed` import cycle PROPERLY (not via deferred import):** today `panel.py` does `from weatherbot.interactive.bot import render_embed`, and `bot.py` in turn references the panel — broken only by a deferred (in-function) import. That cycle exists because **`render_embed` (the content→embed renderer) and the panel (the control surface) live in the same layer and point at each other.** The clean fix is to **break the cycle by ownership, not by import timing:**

1. **`render_embed` is content rendering → it belongs with the app's command/reply layer, not in the panel kit.** Move it (and `build_inbound_embed`) out of `bot.py` into an app-side `panel_content.py` / renderer module. The panel kit takes the renderer as an **injected callable** `render: Callable[[CommandReply, SelectedContext], Embed]` — a one-line DI seam.
2. Now the direction is one-way: app `panel_content` *provides* `render` → adapter `PanelKit` *consumes* it. Neither imports the other at module top; no deferred import survives.
3. The persistent-view rules stay exactly as v1.3 proved them (and must be preserved byte-identically): `timeout=None`, centralized static `custom_id` constants, `add_view` in `setup_hook` (NOT `on_ready` — reconnect duplicates), selected context held in-memory on the view instance (never packed into `custom_id`), defer-then-edit single-ack, `interaction_check` operator gate, per-callback non-propagating envelope + `View.on_error`.

```python
# adapters/discord/panel.py — kit takes content + renderer by injection
class PanelKit(discord.ui.View):
    def __init__(self, spec: PanelSpec, *, render: RenderFn, dispatch: DispatchFn,
                 ctx: SelectedContext, gate: Callable[[int], bool]): ...
    async def interaction_check(self, itx): return self._gate(itx.user.id)  # operator gate
    # buttons/select built from spec (app content) → dispatch(spec) → render(reply, ctx)
```

`SelectedContext` generalizes the `_selected_location` / `📍`/`SelectOption(default=)` machinery: it holds the current selection, supplies the default after restart, and re-derives the highlight on every clone render (closing the v1.3 "THE TRAP" — the clone path must re-mark the default from the held context, never from `Select.values`).

### Pattern 5: In-place-then-split refactor sequence (extract mechanism from a braided function)

**What:** `fire_slot` is the canonical braided function — it computes the per-location/weekday-weekend schedule key, *and* claims exactly-once, *and* fetches weather, *and* delivers, *and* retries. The extraction technique: **wrap, don't rewrite.** Introduce the Core seam as a thin layer the existing function delegates into, keep the old function calling the new seam, prove green, then move the file across the repo boundary last.

**Behavior-preservation strategy (per seam):**
- **Characterization / contract tests are already in hand** — the 649-test suite *is* the contract. Before touching a seam, identify the tests that pin it (e.g. `test_scheduler.py` exactly-once/DST/catch-up, the hanging-callback isolation test, the reload reconcile diff tests, the panel clone-path tests) and treat them as the red/green oracle.
- **Byte-identical guard:** for renderers (`render_embed`) and replies, the suite already asserts byte-identical output across surfaces — keep those assertions as the move's gate.
- **Un-braid in place:** extract the schedule-key + claim logic out of `fire_slot` into `OccurrenceStore.claim(job_id, occurrence)` + an `occurrence_of` callable *while `fire_slot` still calls them*; the weather fetch stays in the app callback. Tests stay green at every step.
- **Split last:** only after the internal package boundary is clean and green do you physically move `core/` to its own repo and re-point WeatherBot at it via a `uv` git dependency.

**Trade-offs:** slower than a big-bang rewrite, but the milestone's entire premise (pure extraction, byte-identical) forbids big-bang. The wrap-then-move discipline keeps the suite as a continuous oracle.

---

## Data Flow

### Briefing fire flow (after extraction — mechanism vs content separated)

```
APScheduler tick (Core trigger, per-location tz)
    ↓
SchedulerEngine._guarded(job_id, occurrence)         [CORE: mechanism]
    ↓  claim(job_id, occurrence) via OccurrenceStore  →  lost? return None (exactly-once)
    ↓  won
app briefing callback(holder.current())              [APP: content]
    ↓  weather fetch → render → CommandReply
Channel.send(text) wrapped in reliability             [CORE: retry/Retry-After/alert]
    ↓
DiscordChannel webhook  (or SMS/Telegram later)       [ADAPTER]
```

### Config reload flow (generic engine, app-shaped hooks)

```
SIGHUP / weatherbot reload / watchfiles save
    ↓
ReloadEngine.reload(validate=app_validator, desired_jobs=app_enum)   [CORE]
    ↓  validate(path) → BaseConfig    (raises → keep-old, holder untouched)
    ↓  holder.replace(new)            (atomic swap)
    ↓  engine.reconcile(desired_jobs(new))   [CORE diffs set[JobSpec]; APP supplies the set]
    ↓  on throw → holder.replace(old) + reconcile(desired_jobs(old))  (all-or-nothing rollback)
```

### Key Data Flows

1. **Exactly-once:** the *key* is opaque to Core (`(job_id, occurrence)`); the *occurrence string* and the *store* are app-injected — WeatherBot keeps its SQLite `claim_slot` + per-tz `local_date`.
2. **Config liveness:** jobs carry the *holder*, not a baked config, so one `replace()` changes what every unchanged job renders — preserved verbatim from today's design.

---

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1 bot, single operator (today) | In-memory jobstore, SQLite occurrence store, one process — exactly the current shape; extraction adds zero runtime cost. |
| 2nd consumer bot (reminder bot) | Reuses Core unchanged; supplies its own `AppConfig`, registry, occurrence semantics. **First real test of the seams** — promotion discipline (build-in-consumer-then-promote, rule of three) applies. |
| Runtime-dynamic durable jobs (reminder bot adds jobs that survive restart) | Triggers the **deferred durable-JobStore** extension point: callbacks become registered-callable keys, kwargs become picklable ids; this is exactly the constraint the JobStore seam is *designed* (not built) for now. |

### Scaling Priorities

1. **First bottleneck = the seams themselves, not performance.** A single-user bot has no throughput problem; the risk is a seam that leaked a weather assumption. Mitigate with the reminder-bot litmus on every Protocol.
2. **Second = durable jobstore serialization.** When the first consumer needs durable dynamic jobs, the picklable-callback constraint bites. It's documented now so it's a known cost, not a surprise.

---

## Anti-Patterns

### Anti-Pattern 1: Core importing app/adapter code "just this once"

**What people do:** a Core module does `from weatherbot... import` to grab a helper, or type-checks against a concrete `Config`.
**Why it's wrong:** instantly fails the reminder-bot litmus and re-couples the module to weather.
**Do this instead:** define a Protocol/callable in `core/seams.py`; the app satisfies it structurally. `TYPE_CHECKING`-only imports are acceptable for type hints, never for runtime.

### Anti-Pattern 2: Routing config validation through an unparametrized pydantic generic

**What people do:** `Holder[T]` validates the incoming dict against `T`.
**Why it's wrong (verified):** pydantic v2 falls back to the `TypeVar` bound and **silently drops the app subclass's fields** — `locations`/`[uv]` would vanish.
**Do this instead:** validate via an app-provided concrete validator callable (today's `validate_config_and_templates`); let the holder be a plain reference cell, or parametrize `ConfigHolder[AppConfig]` explicitly at the composition root.

### Anti-Pattern 3: Putting arbitrary closures/live objects into a (future) durable job

**What people do:** register a job with a lambda or with live `holder`/`client` kwargs, then switch on a persistent jobstore.
**Why it's wrong (verified):** APScheduler can't serialize it — *"reference to its callable could not be determined."*
**Do this instead:** for the durable path, register top-level functions (or a key the engine resolves) with picklable kwargs only, re-hydrating live objects from the holder at fire time. (The in-memory path today is fine; this is the documented rule for the deferred extension.)

### Anti-Pattern 4: Breaking the panel↔render cycle with a deferred (in-function) import

**What people do:** keep `render_embed` in the panel's neighbor module and `import` it inside the callback to dodge the cycle (today's state).
**Why it's wrong:** it hides a layering violation — content rendering and the control surface point at each other.
**Do this instead:** move `render_embed` to the app content layer and inject it into `PanelKit` as a callable. One-way dependency; no deferred import needed.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Discord gateway | discord.py 2.7 `BotThread`, persistent views via `add_view` in `setup_hook` | Adapter layer only; started after READY, torn down in `finally` — preserved verbatim. |
| Discord webhook | `DiscordChannel(Channel)` | Channel impl; `send(text)` text-only seam unchanged. |
| OpenWeather | app callback only | Core never sees it — the cleanest proof the scheduler seam is weather-free. |
| systemd | `Type=notify` READY-gate; app-provided `HealthCheck` callable gates `emit_online` | Core owns the gate mechanism; "what is healthy" stays app-side (today's `run_self_check` is the probe). |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| App ↔ Core | Protocols + callables (`validate`, `desired_jobs`, `occurrence_of`, `HealthCheck`, `OccurrenceStore`) | one-way; Core defines shapes in `core/seams.py`. |
| App ↔ Adapter | registry + `PanelSpec` + injected `render`/`dispatch` | resolves the panel↔render cycle by ownership. |
| Adapter ↔ Core | `Channel` impl, `SchedulerEngine` consumption | adapter depends on Core, never the reverse. |

---

## Dependency-Aware Build Order (for the requirements/roadmap author)

Extract **leaf seams (no app callbacks) first**, then the seams that *consume* them, then the cross-cutting reload, then the adapter, then split. New-vs-modified marked per step.

| # | Seam to extract | New / Modified | Depends on | Byte-identical verification |
|---|-----------------|----------------|------------|------------------------------|
| 1 | **`Channel` + reliability** | MODIFIED (already clean ABC + `retry.py`) | — | existing `test_channels`/`reliability` suites; lowest-risk warm-up. |
| 2 | **`OccurrenceStore` seam** (un-braid `claim_slot` out of `fire_slot`) | NEW Protocol, MODIFIED `fire_slot` | 1 | `test_scheduler` exactly-once/DST/catch-up + overlapping-fire tests stay green. |
| 3 | **`SchedulerEngine.register(...)`** wrapping APScheduler + `JobStore` Protocol (in-mem impl) | NEW engine, MODIFIED `_register_jobs`/`fire_slot`/uvmonitor/heartbeat to call it | 2 | every job type re-registered via engine; hanging-callback isolation test (Phase 20) + heartbeat/uvmonitor tests green. |
| 4 | **`ConfigHolder[T]`** generalized off `Config` | MODIFIED `holder.py` | — (parallel to 1–3) | `test_concurrent_read_swap_safe` + mid-job snapshot tests. |
| 5 | **`ReloadEngine`** (validate→swap→reconcile + watch + SIGHUP) with `validate`/`desired_jobs` callables | NEW engine, MODIFIED `_do_reload`/`_reconcile_jobs` | 3,4 | reload reconcile diff tests + keep-old/rollback + exactly-once-across-reload (SC#4). |
| 6 | **Lifecycle READY-gate + `HealthCheck` callable** | MODIFIED `sdnotify`/`selfcheck` (split engine vs probe) | 4 | startup-gate tests; probe stays app-side. |
| 7 | **PanelKit + `SelectedContext`**, resolve panel↔render cycle (move `render_embed` to app, inject) | NEW kit, MODIFIED `panel.py`/`bot.py` | 3,5 | panel clone-path / emoji-survives-render / operator-gate / restart-routing tests. |
| 8 | **Physical repo split** + `uv` git dependency + EXTENSION-GUIDE.md | NEW repo | 1–7 green | full 649-suite green from the consuming app against the published module. |

**Ordering rationale:** seams with **no app callback** (Channel, OccurrenceStore) come first because they can't leak content; the **SchedulerEngine** must exist before the **ReloadEngine** (reload reconciles *jobs*); the **panel** comes near-last because it consumes both dispatch and the now-relocated renderer; **split is strictly last** (in-place-then-split is a hard decision). Steps 1 and 4 are parallelizable with the early scheduler work.

---

## Sources

- pydantic v2 generic models — `BaseModel, Generic[T]`, `TypeVar(bound=)`, and the **unparametrized-fallback-drops-fields** pitfall — https://pydantic.dev/docs/validation/latest/concepts/models/ — HIGH
- PEP 544 Protocols / structural typing, `@runtime_checkable` (presence-only), Protocol-vs-ABC for DI seams — https://peps.python.org/pep-0544/ , https://typing.python.org/en/latest/spec/protocol.html , https://pybit.es/articles/typing-protocol-abc-alternative/ — HIGH
- APScheduler 3.x persistent-jobstore serialization constraint (globally importable `module:function`, picklable kwargs; lambdas/bound-methods/closures fail) — https://apscheduler.readthedocs.io/en/3.x/userguide.html , https://apscheduler.readthedocs.io/en/3.x/faq.html — HIGH
- Current WeatherBot source (read directly 2026-06-27): `scheduler/daemon.py` (`fire_slot`/`_register_jobs`/`_reconcile_jobs`/`_do_reload`), `config/holder.py`, `config/models.py`, `channels/base.py`, `interactive/dispatch.py`, `interactive/panel.py`, `interactive/bot.py` (`render_embed` + deferred-import cycle), `ops/selfcheck.py` — HIGH
- Project decisions: `.planning/PROJECT.md` (Key Decisions), `.planning/STATE.md` (Accumulated Context — dispatch_spec, persistent-view, panel isolation) — HIGH

---
*Architecture research for: brownfield bot-framework extraction (mechanism-from-content seams, layered core + adapters)*
*Researched: 2026-06-27*
