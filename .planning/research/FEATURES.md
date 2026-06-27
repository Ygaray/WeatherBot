# Feature Research

**Domain:** Reusable, channel-agnostic bot infrastructure module (single-operator, library-not-framework) — extracted from WeatherBot for future bots (e.g. a reminder bot) to import
**Researched:** 2026-06-27
**Confidence:** MEDIUM (framework comparisons cross-checked against official docs; "table stakes vs anti-feature" judgments are opinionated synthesis grounded in those frameworks)

> **Reading note for the requirements/roadmap author.** This is a *capability-surface* study, not a user-feature study. "Feature" here = a module capability or extension point. Every row is tagged **[GENERIC]** (belongs in the module) or **[APP-COUPLED]** (stays in WeatherBot / the consumer), names the **extension mechanism** the module exposes for it, and notes complexity/deferral. The single litmus test throughout: **"could a reminder bot use this with ZERO weather assumptions?"** If no, it's app-coupled and must stay on the app side of the seam.

---

## The framework-vs-app line: how comparable libraries draw it

Grounding the categories below in real, current libraries (all cross-checked against official docs):

| Library | What the LIBRARY owns | What the APP owns | Registration style | Lesson for our module |
|---------|----------------------|-------------------|--------------------|-----------------------|
| **discord.py `ext.commands`** | Gateway/transport, Cog *mechanism*, persistent-view plumbing (`View(timeout=None)` + `add_view` in `setup_hook`), `DynamicItem` custom_id encoding | The Cogs themselves, the command set, the content | Explicit (`bot.add_cog`, `load_extension`) | Library = transport + component plumbing + *a* registration mechanism. App = the commands. This is exactly our `dispatch_spec` + panel-builder split. |
| **hikari** | *Only* events/listeners + REST; deliberately minimal | Everything above transport (commands, prefixes) — typically via a separate framework (**Tanjun**) | `.set_listener` only | A core can legitimately stop at "transport + plumbing" and let a command framework sit on top. Validates a thin core. |
| **interactions.py** | Extension *mechanism* | The Extensions (== Cogs) | **Self-registration** (`MyExt(bot)`, no `add_cog`) | The one real divergence is explicit-vs-self registration. For a single app, explicit wins (no import-order magic). |
| **APScheduler 3.x** | `BaseScheduler/Executor/JobStore/Trigger` interfaces; in-memory jobstore default | The jobs + the durable store *if wanted* | Direct (`MyTrigger(...)`) or named entry-point plugin | The canonical "interface designed, durable impl deferred" split — our scheduler's `JobStore` seam should copy this exactly. |

**The consistent line every framework draws:** the library owns **transport + plumbing + a registration *mechanism***; the app owns **the command set + the content + the schema**. Where our candidate capabilities sit relative to that line is the whole question, answered per-row below.

---

## Feature Landscape

### Table Stakes (a reusable bot module is incomplete without these)

These are the capabilities that make the thing a *module* rather than a copy-paste. All are **[GENERIC]** by construction — each passes the reminder-bot litmus.

| Capability | Why it's table-stakes (litmus: reminder bot reuses it) | Extension mechanism the module exposes | Complexity | Notes |
|------------|--------------------------------------------------------|----------------------------------------|------------|-------|
| **Pluggable `Channel.send(text)` abstraction** | A reminder bot delivers reminders over the same Discord/SMS/Telegram surface with zero change. This is *the* defining seam. | `Channel` ABC; consumer registers a concrete channel by name (registry dict) | LOW | Mirrors hikari's "transport only" core. Discord webhook impl ships; SMS/Slack/Telegram are documented extension points (deferred). |
| **Generic scheduler engine** | "Fire callback X at trigger Y, exactly once per occurrence" is content-free. A reminder bot schedules reminders; weather schedules briefings. Identical mechanism. | `register(job_id, trigger, callback)`; arbitrary `trigger`; exactly-once on generic `(job_id, occurrence)` key | MEDIUM | Directly models APScheduler's `BaseTrigger`/`add_job` split. DST-safe + restart catch-up are part of the engine. |
| **`JobStore` seam (in-memory impl, durable deferred)** | Exactly the APScheduler pattern: durable/dynamic jobs are an *interface*, not a default. Reminder bots that need user-created reminders subclass it later. | `JobStore` ABC subclassed; in-memory impl is the only one shipped | LOW (interface) | **Designed now, durable impl deferred** — recorded as the headline documented extension point. Do NOT build a DB-backed store in this milestone. |
| **Config hot-reload engine (generic holder + validate→swap→reconcile)** | Reload-without-restart of an immutable snapshot is schema-agnostic. The *schema* is app-coupled (next section); the *engine* is not. | `ConfigHolder` of immutable snapshots; `validate→atomic-swap→job-reconcile`; file-watch + SIGHUP; keep-old-on-failure | MEDIUM-HIGH | The high-effort seam: the engine is generic, the consumer supplies the Pydantic schema and a `validate()` callback. |
| **Self-describing command registry → CLI + dispatch + auto-`help`** | The *mechanism* (one registry auto-derives every command surface) is pure plumbing. The reminder bot registers `snooze`/`list`; weather registers `weather`/`uv`. | `registry.COMMANDS` + `dispatch_spec`; consumer adds command specs (name, handler, args) | MEDIUM | This is our Cog/Extension equivalent. **Explicit** registration (a dict), not self-registration — correct for a single app (no import-order magic). |
| **Shared dispatcher (`dispatch_spec`) — single source of truth** | Anti-drift across CLI/Discord/panel is a structural property of the dispatcher, not of weather. Any bot with >1 command surface needs it. | One `dispatch_spec` all surfaces route through; `flags=`-style additive param for variants | MEDIUM | The structural guarantee ("parallel command list impossible") is the reusable value. |
| **Delivery reliability (retry/backoff/Retry-After + out-of-band alert + heartbeat)** | "Don't silently drop a scheduled send; retry then alert" is content-free reliability. A dropped reminder is as bad as a dropped briefing. | Reliability wrapper around `Channel.send`; alert sink is an injected callback/row-writer | MEDIUM | tenacity-based. The *alert destination* (DB row vs log) is a small app/config choice, not a fork. |
| **Process lifecycle (systemd `Type=notify` READY-gate after a startup self-check)** | "Don't report healthy until a self-check passes" is generic supervision. The *self-check contents* are app-coupled (next section). | READY-gate that calls an **app-provided health-check callback** before `emit_online` | LOW-MEDIUM | Clean seam: engine owns the gate + systemd notify; app owns "is my API key valid?". |
| **Discord gateway bot in an isolated, failure-isolated thread** | "Run the inbound bot off the critical path so it can never stop the scheduled spine" is a reusability *guarantee*, weather-free. | `BotThread` started after READY, torn down in `finally`, swallows failures; off-loop work via executor | MEDIUM | Failure-isolation from the briefing/reminder spine is the load-bearing reusable property. |
| **Reusable persistent control-panel plumbing (Discord adapter)** | Persistent views by `custom_id`, defer-then-edit 3s ack, operator-gate, per-callback isolation envelope, `registry→panel` builder are all *mechanism*. The reminder bot gets a panel of *its* commands for free. | `PanelView(timeout=None)` + `add_view` in `setup_hook`; `registry→panel` builder; `selected-context` abstraction | HIGH | Lives in the **Discord adapter**, not the core (SMS/Slack have no buttons). Mirrors discord.py's persistent-view + `DynamicItem` patterns exactly. |

### Differentiators (above baseline; this is where the extraction earns its keep)

Not strictly required for "a reusable module," but they're the reason *this* extraction is worth doing rather than starting a generic library cold.

| Capability | Value proposition | Extension mechanism | Complexity | Notes |
|------------|-------------------|---------------------|------------|-------|
| **`registry → panel` auto-builder** | The panel UI is *derived* from the command registry — register a command, get a button. Most bot stacks make you wire the panel by hand. This is genuinely differentiating plumbing. | Panel builder consumes `dispatch_spec`; app supplies button labels/emoji/layout | HIGH (already built) | **[GENERIC]** core builder + **[APP-COUPLED]** cosmetics (the 2×2 forecast grid, 📍 indicator, emoji set live app-side). Clean split already exists. |
| **`selected-context` abstraction for panels** | A panel that carries a "currently selected X" (location for weather; could be a reminder list/category) without the core knowing what X is. | Generic "selected context" slot; app supplies the dropdown options + meaning | MEDIUM | **[GENERIC]** slot, **[APP-COUPLED]** that it's a *location*. Reminder bot puts a category there. |
| **Battle-tested exactly-once + DST + catch-up semantics** | These are the bugs everyone gets wrong. Shipping them pre-solved (and test-proven, 649-test contract) is the differentiator over a from-scratch scheduler. | Part of the scheduler engine; opaque to the consumer | (already built) | The *tests* travel with the module as the behavior contract. |
| **Validate→swap→reconcile with keep-old-on-failure** | "A bad config edit never half-applies or breaks a live daemon" is a property most hot-reload hacks lack. | Config engine; app supplies `validate()` + the schema | (already built) | The reconcile-by-stable-id discipline is reusable; the *id derivation* is app-coupled. |

### Anti-Features (the litmus test says "don't generalize yet")

These are the over-engineering traps for a **single-operator** module. Each is something a *public framework* would build that *this* module must NOT — flagged explicitly so the roadmap doesn't drift into framework-building.

| Anti-feature | Why it's tempting | Why it's wrong here (single-operator) | What to do instead |
|--------------|-------------------|----------------------------------------|--------------------|
| **Plugin discovery / dynamic loading** (entry-points, namespace-package scanning, `importlib` directory scan, stevedore/yapsy) | "A real module should auto-discover commands/channels!" | Canonical YAGNI violation. There is exactly one consumer. Discovery adds import-order hazards, setup.py entry-points, and runtime failure modes for zero benefit. interactions.py self-registration is the *most* magic any comparable lib does, and even that is overkill for one app. | **Static registry dict, import-time, in-repo.** Explicit `register(...)` calls (discord.py's explicit style). Add discovery only if/when a *second* independent consumer exists (rule of three). |
| **Durable/dynamic JobStore *implementation*** | "User-created jobs need a DB!" | No user creates jobs — schedules are config-file driven. Building a DB jobstore now is solving a problem no consumer has. | **Ship the `JobStore` interface + in-memory impl only.** Document durable as the headline deferred extension point (this is the explicit PROJECT.md plan, and exactly APScheduler's own posture). |
| **Multi-tenant config / per-user namespaces** | "Make config generic across users!" | Out of scope by project charter — single personal user. Multi-tenancy poisons every seam (config holder, scheduler keys, operator gate) with tenant-id plumbing. | Single immutable config snapshot. Operator-id gate stays a single id, not a user table. |
| **Event bus / pub-sub between subsystems** | "Decouple scheduler↔channel↔panel with events!" | Three subsystems, one process, direct calls. An event bus adds indirection, ordering ambiguity, and debugging pain with no decoupling benefit at this scale. | Direct function calls across the named seams. The seams ARE the decoupling. |
| **Generic templating/rendering engine in the core** | "Bots render messages — put rendering in the module!" | Rendering is *content*. A briefing 2×2 grid / embed / 📍 indicator is weather-shaped; a reminder renders differently. Pulling it into the core couples the core to a render model. | Keep `render_embed`/templates **app-side**. Core passes `text`/structured payload to `Channel.send`; the app owns formatting. |
| **Abstracting the second/third channel before it exists** | "Design the SMS + Telegram + Slack adapters now while extracting!" | You can't design the right `Channel` interface from one impl + imagination. discord.py's component API took multiple iterations. | `Channel.send(text)` is the *only* committed surface. Adapters are documented extension points; build-in-consumer-then-promote when a real second channel lands. |
| **Config-schema plugin/merge system** | "Let plugins contribute config sections!" | The schema is owned by exactly one app. A schema-merge system is plugin-discovery's cousin — same YAGNI failure. | App **subclasses/composes** the Pydantic config and passes it in. The engine is a schema-shaped hole, not a schema registry. |
| **Async-everywhere rewrite of the scheduler spine** | "A modern library should be async!" | The verified *sync* `BackgroundScheduler` spine is the 649-test contract. Going async is a behavior-changing rewrite that violates the pure-extraction guardrail. | Keep the sync spine; the inbound bot already runs in its own thread (existing decision). Async is not an extraction concern. |

---

## Generic-vs-app-coupled: the seam map (the deliverable the roadmap author needs)

Where each candidate capability splits across the module boundary. **Bold = lives in module.** Plain = stays in WeatherBot/consumer.

| Candidate capability | Module side (GENERIC) | App side (APP-COUPLED) | Litmus verdict |
|----------------------|-----------------------|-------------------------|----------------|
| Channel abstraction | **`Channel.send(text)` ABC, registry, reliability wrapper, Discord webhook impl** | Choosing Discord; the message text | PASS — fully generic |
| Scheduler engine | **`register(job_id,trigger,callback)`, exactly-once, DST, catch-up, `JobStore` ABC + in-mem impl** | Which jobs, the briefing callback body, the schedule config | PASS — fully generic |
| Config hot-reload | **Holder, validate→swap→reconcile, file-watch, SIGHUP, keep-old** | The Pydantic **schema**, the `validate()` rules, stable-id derivation | PASS (engine) / app supplies schema |
| Command registry + dispatcher | **Registry mechanism, `dispatch_spec`, CLI subparser derivation, `help` rendering, additive `flags=` seam** | The actual commands (`weather`/`uv`/…), handler bodies, arg meanings | PASS (mechanism) / app supplies commands |
| Process lifecycle | **systemd `Type=notify` READY-gate, supervised-restart wiring** | The **health-check callback** body (API-key/network probe) | PASS (gate) / app supplies the check |
| Gateway bot thread | **`BotThread`, READY-ordered start, `finally` teardown, failure-swallow, off-loop executor** | Bot token source, which commands the bot answers | PASS — generic isolation |
| Control panel | **Persistent-view plumbing, 3s defer-then-edit ack, operator-gate, isolation envelope, `registry→panel` builder, selected-context slot** | Location dropdown, forecast 2×2 grid, 📍/emoji polish, button labels | PASS (plumbing) / app supplies cosmetics + options |
| Delivery reliability | **Retry/backoff/Retry-After, heartbeat, out-of-band alert mechanism** | Alert destination choice (DB row vs log) — config, not fork | PASS — generic |
| Rendering/templates | *(nothing)* | **All of it** — embeds, templates, `render_embed` | FAIL — content; stays app-side |

**Secretly app-coupled — watch for leaks through the seam.** These four are where the extraction is most likely to leak a weather assumption; call them out as explicit review-gates in the roadmap:
1. **`selected-context` slot** — must not hardcode "location" (reminder bot puts a category/list there).
2. **Config schema** — the engine must not know weather field names; reconcile-by-id must take an injected id-deriver.
3. **Health-check** — the READY-gate must not probe OpenWeather; it calls an injected callback.
4. **Panel cosmetics** — the `registry→panel` builder must not bake in the forecast grid / 📍 / emoji set.

---

## Feature Dependencies

```
Channel.send (the defining seam)
    └──used by──> Delivery reliability wrapper
                       └──used by──> Scheduler engine (fires callback that delivers)

Command registry
    └──feeds──> Shared dispatcher (dispatch_spec)
                    └──feeds──> CLI subparser derivation
                    └──feeds──> auto-help rendering
                    └──feeds──> registry→panel builder (Discord adapter only)
                                     └──requires──> Gateway bot thread
                                     └──requires──> persistent-view plumbing

Config hot-reload engine
    └──reconciles──> Scheduler engine (jobs by stable id)
    └──requires──> app-supplied schema + validate()

Process lifecycle (READY-gate)
    └──gates──> Gateway bot thread start  (bot starts AFTER READY)
    └──requires──> app-supplied health-check callback

JobStore ABC ──extension-point──> (durable impl: DEFERRED, not built)
Channel ABC  ──extension-point──> (SMS/Telegram/Slack: DEFERRED, not built)
```

### Dependency notes (roadmap-ordering implications)

- **Channel + reliability before scheduler wiring:** the scheduler's callback ultimately delivers, so the delivery seam should be clean before the engine is finalized. (Both already exist; this matters for *extraction order* — un-braid the channel seam early.)
- **Registry/dispatcher before the panel builder:** the panel is *derived* from the registry. Extracting `dispatch_spec` first (already done, Phase 16) is the correct order and makes the panel builder a pure consumer.
- **READY-gate before gateway-bot start:** existing lifecycle ordering — preserve it across the extraction; the gate is in the core, the bot in the Discord adapter, so the seam crosses a package boundary.
- **Config engine is the high-effort seam** because reconcile touches the scheduler. Extract the engine generically but keep the schema injected — do NOT let scheduler reconcile logic learn weather field names.

---

## MVP Definition (for the extraction milestone)

### Extract now (v2.0 — the module's launch surface)

- [ ] **`Channel.send(text)` ABC + Discord webhook impl + reliability wrapper** — the defining seam; nothing reuses without it.
- [ ] **Generic scheduler engine + `JobStore` ABC (in-memory impl only)** — exactly-once/DST/catch-up travel with it; durable store deferred.
- [ ] **Config hot-reload engine (schema injected)** — the high-effort seam; app keeps its Pydantic schema.
- [ ] **Command registry + `dispatch_spec` + CLI/help derivation** — the Cog/Extension equivalent; explicit registration.
- [ ] **Process lifecycle READY-gate (health-check callback injected)** — generic supervision.
- [ ] **Discord adapter: gateway-bot thread + persistent-panel plumbing + `registry→panel` builder + selected-context slot** — the reusable UI plumbing; cosmetics stay app-side.
- [ ] **Extension-guide doc** — the plug points + implemented-vs-deferred status (durable jobstore, extra channels).
- [ ] **Physical repo split + uv git dependency.**

### Add after validation (post-extraction, when a real second consumer appears)

- [ ] **Second `Channel` impl (Telegram — free, validates the abstraction)** — trigger: the reminder bot or a real desire for a non-Discord channel. Build-in-consumer-then-promote.
- [ ] **Durable `JobStore` impl** — trigger: a consumer needs user-created/dynamic jobs (the reminder bot's natural pull).

### Explicitly NOT in this milestone (anti-features above)

- [ ] Plugin discovery / dynamic loading — never, for a single-operator module.
- [ ] Multi-tenant config, event bus, generic templating in core, async rewrite — out of scope by charter.
- [ ] SMS/Slack adapters, weather-pattern analysis — deferred backlog, behind the extraction.

## Capability Prioritization Matrix

| Capability | Reuse value (to a 2nd bot) | Extraction cost | Priority |
|------------|----------------------------|-----------------|----------|
| `Channel.send` ABC + Discord impl | HIGH | LOW (seam already clean) | P1 |
| Scheduler engine + `JobStore` ABC | HIGH | MEDIUM | P1 |
| Command registry + `dispatch_spec` | HIGH | MEDIUM (already un-braided, Phase 16) | P1 |
| Config hot-reload engine | HIGH | HIGH (reconcile↔scheduler coupling) | P1 |
| Process lifecycle READY-gate | MEDIUM | LOW-MEDIUM | P1 |
| Gateway-bot thread isolation | HIGH | MEDIUM | P1 |
| Panel plumbing + `registry→panel` builder | HIGH | HIGH | P1 (Discord adapter) |
| Delivery reliability wrapper | HIGH | LOW-MEDIUM | P1 |
| Second channel (Telegram) | MEDIUM | MEDIUM | P3 (deferred) |
| Durable JobStore impl | MEDIUM | HIGH | P3 (deferred extension point) |

**Priority key:** P1 = in the extraction milestone · P2 = next module milestone · P3 = deferred extension point.

## Competitor Feature Analysis

How analogous frameworks handle each seam, and our chosen approach.

| Seam | discord.py ext.commands | hikari (+Tanjun) | interactions.py | APScheduler 3.x | Our approach |
|------|-------------------------|------------------|-----------------|-----------------|--------------|
| Command registration | Explicit `add_cog`/`load_extension` | None in core (Tanjun on top) | Self-registering Extensions | n/a | **Explicit registry dict** (discord.py-style; no self-reg magic for one app) |
| Persistent components | `View(timeout=None)` + `add_view` in `setup_hook`; `DynamicItem` custom_id | n/a (manual) | similar to d.py | n/a | **Same as discord.py** (already implemented this way) — `wb:`-prefixed stable custom_ids |
| Scheduler triggers | n/a | n/a | n/a | `BaseTrigger.get_next_fire_time` | **`register(job_id, trigger, callback)`** mirroring APScheduler's trigger seam |
| Durable persistence | n/a | n/a | n/a | `BaseJobStore`, in-mem default, DB optional | **`JobStore` ABC + in-mem impl; durable deferred** (identical posture) |
| Plugin discovery | Optional (`load_extension` by path) | n/a | optional | entry-points | **None** — static registry; discovery is an anti-feature here |
| Core minimalism | Medium (batteries) | Maximal (transport-only) | Medium | n/a | **Layered**: channel-agnostic core + Discord adapter (panel in adapter) — closer to hikari's thin-core line |

## Sources

- discord.py extensions / Cogs / persistent views — explicit `add_cog`/`load_extension`, `View(timeout=None)` + `add_view` in `setup_hook`, `DynamicItem` (2.4.0+) custom_id encoding (<=100 chars). [discord.py persistent views example](https://github.com/Rapptz/discord.py/blob/master/examples/views/persistent.py), [persistent views tutorial](https://thegamecracks.github.io/discord.py/persistent_views.html), [DynamicItem discussion](https://github.com/Rapptz/discord.py/discussions/9851) — MEDIUM
- hikari minimal core (`.set_listener`, no command/prefix system) + Tanjun as the separate command framework. [hikari GitHub](https://github.com/hikari-py/hikari), [hikari docs](https://docs.hikari-py.dev/en/stable/), [Patchwork hikari intro](https://patchwork.systems/programming/hikari-discord-bot/introduction-and-basic-bot.html) — MEDIUM
- interactions.py Extensions (== Cogs) with self-registration (`MyExt(bot)`, no `add_cog`). [interactions.py migration guide](https://interactions-py.github.io/interactions.py/Guides/97%20Migration%20From%20D.py/) — MEDIUM
- APScheduler 3.x pluggable architecture — `BaseScheduler/Executor/JobStore/Trigger`; `BaseTrigger.get_next_fire_time`; `BaseJobStore` (in-mem default, DB optional, serialized); custom triggers via direct use or entry-point plugin. [Extending APScheduler](https://apscheduler.readthedocs.io/en/3.x/extending.html), [BaseTrigger](https://apscheduler.readthedocs.io/en/3.x/modules/triggers/base.html), [scheduler base](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/base.html) — MEDIUM
- YAGNI / plugin-discovery over-engineering — generic plugin system "in case we need it later" is the canonical YAGNI violation; add architecture only when a second plugin exists (rule of three); Python discovery flavors (naming, namespace packages, entry-points) + stevedore/yapsy are framework-scale. [Python plugin systems](https://oneuptime.com/blog/post/2026-01-30-python-plugin-systems/view), [Python Packaging: discovering plugins](https://packaging.python.org/guides/creating-and-discovering-plugins/), [YAGNI explained](https://read.thecoder.cafe/p/yagni), [stevedore](https://docs.openstack.org/stevedore/ocata/) — MEDIUM
- WeatherBot `.planning/PROJECT.md` — v2.0 milestone charter, candidate capabilities, existing seams, deferral decisions, single-operator scope — HIGH (project ground truth)

---
*Feature research for: reusable channel-agnostic bot infrastructure module (single-operator extraction)*
*Researched: 2026-06-27*
