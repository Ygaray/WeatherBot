# Project Research Summary

**Project:** WeatherBot — v2.0 "The Great Decoupling" (Bot Module Extraction)
**Domain:** Brownfield extraction of a reusable, channel-agnostic Python bot framework out of a working app, consumed back via a `uv` git dependency
**Researched:** 2026-06-27
**Confidence:** HIGH

## Executive Summary

This milestone is a **pure-extraction refactor**, not a greenfield build. The runtime stack (httpx, APScheduler 3.x, tenacity, structlog, discord.py 2.7.1, watchfiles, cachetools, pydantic, SQLite) is already chosen and stays put; the only *new* mechanics are packaging (carve a `botkit` module into its own repo, depend on it from WeatherBot via a uv git pin) and the seam discipline that un-braids reusable **mechanism** from weather **content**. The acceptance contract is byte-identical behavior, enforced by the existing 649-test suite plus new golden/characterization snapshots. The single litmus test governing every decision: *"could a reminder bot use this with zero weather assumptions?"*

The decided module shape is a **layered channel-agnostic core + per-channel adapters**. The core owns `SchedulerEngine` (`register(job_id, trigger, callback)` + generic exactly-once + an `OccurrenceStore`/`JobStore` Protocol seam), `ConfigHolder[T]` + `ReloadEngine` (validate→swap→reconcile with injected `validate`/`desired_jobs` hooks), the `Channel` abstraction + delivery reliability, and a `Lifecycle` READY-gate that calls an app-provided health-check. The Discord *adapter* (one layer up — SMS/Slack have no buttons) owns the gateway `BotThread` and `PanelKit` (registry→panel builder + `SelectedContext`). The inviolable rule: **dependencies point downward and inward only** — the core imports neither app nor adapter; every app behavior arrives through an injected Protocol or callable defined in `core/seams.py`. WeatherBot becomes the composition root that wires its content (AppConfig schema, weather fetch/render, command registry, panel cosmetics) into the core+adapter.

The build proceeds **leaf-seams-first**: lay golden/characterization tests first, extract the seams with no app callback (Channel, OccurrenceStore) before the seams that consume them (SchedulerEngine, then ReloadEngine), do the Discord adapter near-last (it consumes both the dispatcher and a relocated renderer), and **physically split the repo strictly last**. The dominant risks are all extraction-specific: weather nouns leaking into the "generic" core, behavior drift that green-but-not-byte-exact tests miss, the latent `render_embed↔PanelView` import cycle hardening into a cross-package break, the `custom_id` wire-contract and discord.py pin breaking the live pinned panel on host `yahir-mint`, the APScheduler serialization constraint that the JobStore seam must be shaped for *now* (even though only the in-memory impl ships), and the dev-editable-vs-host-git-pin "works locally, breaks on host" trap. Each maps to a concrete guardrail and target phase below.

## Key Findings

### Recommended Stack

This is a packaging study, not a runtime-library study (see STACK.md). Use a **uv git dependency for deploy + a uv editable path override for dev**, switched with a one-line `tool.uv.sources` edit. Do NOT publish to PyPI, do NOT introduce Poetry or monorepo tooling, do NOT add a console script to the module.

**Core technologies:**
- **uv 0.11.19** (installed): the single tool for git deps (`tag`/`rev`), editable path deps, and `uv.lock` reproducibility — `tool.uv.sources` is uv-only and never leaks into a consumer.
- **hatchling** (already in use): keep the identical build backend in the module repo; auto-discovers `src/botkit/` with no extra config.
- **Git tags `vX.Y.Z`**: the tag *is* the release and the pin contract for a single-consumer personal module — `uv.lock` freezes the tag→commit so the host (`uv sync --frozen`) is byte-reproducible. Commit-SHA `rev=` is the between-tags fallback; `branch=main` is dev-only (never the deploy pin).
- **Dev↔deploy switch (load-bearing):** lay the two repos side-by-side (`~/Projects/WeatherBot` + `~/Projects/botkit`); deploy commits `botkit = { git=..., tag="vX.Y.Z" }`; dev toggles to `botkit = { path="../botkit", editable=true }` (live edits, no reinstall) and simply does not commit that line.

What shapes the work **now** vs. defers to the split: pick the **module package name + import root** and decide the **generic-vs-weather dependency line** during the in-place refactor (so the split is a `git mv`, not a rename). Everything uv-sources/tag/two-repo defers to the physical-split phase.

### Expected Features

This is a *capability-surface* study (see FEATURES.md). Every capability is tagged GENERIC (module) or APP-COUPLED (consumer), with the extension mechanism it exposes. The consistent framework line (discord.py/hikari/interactions.py/APScheduler): the library owns **transport + plumbing + a registration mechanism**; the app owns **the command set + content + schema**.

**Must have (table stakes — all GENERIC, in this milestone):**
- `Channel.send(text)` ABC + Discord webhook impl + reliability wrapper — *the* defining seam.
- Generic scheduler engine + `JobStore` ABC (in-memory impl only) — exactly-once/DST/catch-up travel with it.
- Config hot-reload engine (schema injected) — the high-effort seam; app keeps its Pydantic schema + `validate()`.
- Command registry + `dispatch_spec` + CLI/help derivation — the Cog/Extension equivalent (already un-braided, Phase 16); explicit registration, no discovery.
- Process lifecycle READY-gate (health-check callback injected) — generic supervision; app supplies the probe.
- Discord adapter: gateway `BotThread` + persistent-panel plumbing + `registry→panel` builder + `SelectedContext` slot — cosmetics stay app-side.
- Extension-guide doc recording implemented-vs-deferred seams.

**Should have (differentiators — why *this* extraction beats a cold start):**
- `registry → panel` auto-builder (register a command, get a button) — genuinely differentiating plumbing.
- `SelectedContext` abstraction (a panel carries "currently selected X" without the core knowing what X is).
- Battle-tested exactly-once + DST + catch-up + validate→swap→reconcile-with-keep-old, shipped pre-solved with the test contract.

**Defer (documented seams, NOT built this milestone):**
- Durable `JobStore` impl — ship the interface + in-memory impl; durable is the headline deferred extension point (no consumer creates jobs yet).
- 2nd `Channel` impl (Telegram/SMS/Slack) — `Channel.send(text)` is the only committed surface; build-in-consumer-then-promote.
- Anti-features to *not* drift into: plugin discovery/dynamic loading, multi-tenant config, event bus, generic templating in core, async-rewrite of the scheduler spine, abstracting channel #2 before it exists.

### Architecture Approach

Layered **core → adapters → app** with one-way inward/downward dependencies (see ARCHITECTURE.md). Each core↔app boundary is a **PEP 544 Protocol or bare callable** the core defines and the app satisfies by shape — never an import back. `core/seams.py` collects every Protocol in one file; that file *is* the extension-guide surface.

**Major components:**
1. **SchedulerEngine** (`core/scheduler/`) — `register(job_id, trigger, callback)` over APScheduler; generic exactly-once via an injected `OccurrenceStore.claim(job_id, occurrence)`; `JobStore` Protocol (in-memory now); `occurrence_of` is app-supplied (WeatherBot's per-tz `local_date`).
2. **ConfigHolder[T] + ReloadEngine** (`core/config/`) — generic holder over an app `BaseConfig`; reload runs `validate→swap→reconcile` with app-injected `validate(path)→BaseConfig` and `desired_jobs(cfg)→set[JobSpec]`; all-or-nothing rollback. **Gotcha:** do NOT validate through an unparametrized pydantic generic (silently drops subclass fields) — use the app validator callable.
3. **Channel + reliability** (`core/delivery/`) — `Channel` ABC/Protocol + retry/backoff/Retry-After/alert/heartbeat.
4. **Lifecycle** (`core/lifecycle.py`) — systemd `Type=notify` READY-gate + `HealthCheck` callable (app probe; core never imports weather).
5. **PanelKit + SelectedContext** (`adapters/discord/`) — registry→view builder + persistent-view plumbing; resolves the `render_embed↔PanelView` cycle *by ownership* (move `render_embed` to the app content layer, inject it as `render:` into PanelKit — one-way, no deferred import).

**Dependency-aware build order** (the deliverable the roadmapper needs): (1) Channel+reliability → (2) OccurrenceStore un-braid from `fire_slot` → (3) SchedulerEngine + JobStore Protocol → (4) ConfigHolder[T] (parallel to 1–3) → (5) ReloadEngine (needs 3+4) → (6) Lifecycle READY-gate → (7) PanelKit + cycle fix (needs 3+5) → (8) physical split + uv git dep + EXTENSION-GUIDE.md (needs 1–7 green). **Characterization/golden tests come before step 1.**

### Critical Pitfalls

1. **Leaky abstractions (weather nouns in the "generic" core)** — `render_embed(location=…)`, the `location`/`forecast`/`uv` braid in `scheduler/`+`config/`, `[uv]` config. *Avoid:* reminder-bot litmus on every seam as a written gate + a per-seam-phase grep gate (`grep -rniE 'weather|forecast|location|openweather|\buv\b|briefing'` returns only incidental hits); un-braid mechanism from content in place; app extends the schema, framework owns the holder.
2. **Behavior drift in a "pure" refactor** — green tests ≠ byte-identical (import-order side effects, exception *identity* changes, embed byte/field-order diffs, idempotency-key reshaping). *Avoid:* lay **golden/characterization snapshots first** (full rendered embeds, CLI stdout/exit, registered-job schedule plan, DB rows), freeze clock+fixture, refactor in micro-steps running the full suite each, never edit a test to make a "pure" refactor pass.
3. **Circular imports surfaced by the split** — the real `panel.py`→`render_embed` / `bot.py`→`PanelView` cycle (today deferred-imported). *Avoid:* invert via DI (PanelKit takes `render` as a param), enforce a strict layering DAG, stand up an import-linter / core-in-isolation test early; resolve the deferred import at the boundary, don't port it across.
4. **Packaging / import-path breakage on the split ("works locally, breaks on host")** — import-path churn, namespace shadowing, console-entry-point chain, editable-dev-vs-git-pin-host divergence. *Avoid:* distinct dist+import name (`botkit`, never `weatherbot`); one mechanical import sweep + grep gate; keep the `weatherbot` console script in the app; **clean-venv `uv sync` from the git pin + `weatherbot check`/`--help` + full suite** as the gate; commit→push→repin→deploy ritual + a startup log line printing the resolved module sha.
5. **APScheduler serialization coupling baked into the JobStore seam** — register with a closure/bound-method/live-object kwargs works with `MemoryJobStore` but a durable backend later requires a globally-importable callable + picklable args, turning the deferred impl into a redesign. *Avoid:* shape `register()` for an importable callable + identity-style picklable args (look up live collaborators at fire time, like today's `holder.current()`); add a guard test asserting registered callbacks are importable + args picklable *even for the in-memory impl*; record the constraint in the extension-guide.
6. **discord.py pin + `custom_id` stability** — a loose `discord.py>=2.7` lets the host resolve an unverified version; re-namespacing `custom_id`s kills the already-pinned live panel's button routing. *Avoid:* pin `discord.py==2.7.1` in the module (one authority); treat `custom_id`s as a frozen wire contract asserted by a byte-string test (incl. the `wb:` marker); if they *must* change, ship a `!panel` re-summon migration as a documented deploy step; re-run the live restart UAT on `yahir-mint`.

(See PITFALLS.md for the full nine, plus the systemd-lifecycle-assumptions pitfall, the two-repo promotion-ledger/anemic-module trap, the "Looks Done But Isn't" checklist, and recovery strategies.)

## Implications for Roadmap

The architecture's **dependency-aware build order is the recommended phase spine**, with a characterization phase prepended and the split appended. Phases are extraction seams; each carries the reminder-bot-litmus grep gate + the relevant golden suite as standing success criteria.

### Phase A: Characterization / Golden-Test Lay-Down
**Rationale:** A 649-test suite proves *intent*, not *every byte*. Byte-identical is the milestone contract, so the goldens must exist before any code moves (Pitfall 3).
**Delivers:** Golden snapshots — full rendered embeds (per command × `📍`/`Updated` states, frozen forecast + frozen clock), CLI stdout/exit-code, the registered-job schedule plan, the `weather_onecall`/`alerts`/sent-log DB rows; an exception-identity pin; a coverage audit filling any uncovered branch on the move paths.
**Addresses:** the byte-identical acceptance mechanism for every later phase.
**Avoids:** Pitfall 3 (behavior drift shipped as "pure").

### Phase B: Channel + Delivery Reliability seam
**Rationale:** Lowest-risk warm-up — already a clean ABC + `retry.py`, no app callback to leak content.
**Delivers:** `Channel` Protocol/ABC + reliability wrapper extracted into the core package boundary (in place).
**Uses:** existing `test_channels`/`reliability` suites as the oracle.
**Implements:** ARCHITECTURE component #3.

### Phase C: OccurrenceStore seam (un-braid `claim_slot` from `fire_slot`)
**Rationale:** Exactly-once is the highest-stakes correctness property; un-braid it before the engine wraps it. No app callback → can't leak content.
**Delivers:** `OccurrenceStore` Protocol + `occurrence_of` callable; `fire_slot` delegates to them while still calling them (wrap, don't rewrite).
**Avoids:** Pitfall 3 (idempotency-key reshaping double-send/skip) — guarded by exactly-once/DST/catch-up + exactly-once-across-reload goldens.

### Phase D: SchedulerEngine + JobStore Protocol (in-memory impl)
**Rationale:** Must exist before the ReloadEngine (reload reconciles *jobs*). Highest over-abstraction + serialization risk.
**Delivers:** `SchedulerEngine.register(job_id, trigger, callback)` wrapping APScheduler (keeping `misfire_grace_time=None`/`coalesce=True`/`max_instances=1`); `JobStore` Protocol + in-memory impl; every job type (briefing/forecast/uvmonitor/heartbeat) re-registered through it.
**Avoids:** Pitfall 5 (serialization) — importable-callback + picklable-args guard test, constraint recorded; Pitfall 2 (durable impl deferred, documented).

### Phase E: ConfigHolder[T] + ReloadEngine
**Rationale:** The high-effort seam; reconcile touches the scheduler, so it follows D. ConfigHolder generalization is parallelizable earlier.
**Delivers:** `ConfigHolder[T]` generalized off `Config`; `ReloadEngine` (validate→swap→reconcile + watch + SIGHUP) with injected `validate`/`desired_jobs`; all-or-nothing rollback.
**Avoids:** the pydantic unparametrized-generic field-drop gotcha (validate via app callable); Pitfall 1 (schema stays app-side, `[uv]` never enters the module).

### Phase F: Lifecycle READY-gate + HealthCheck callable
**Rationale:** Generic supervision; depends on the config holder; isolates the weather probe.
**Delivers:** systemd `Type=notify` READY-gate engine + `HealthCheck` Protocol; the probe (`run_self_check`) stays app-side; identity (PID path/runtime dir/unit name) parameterized.
**Avoids:** Pitfall 9 (no `weatherbot` literal / weather probe in the module; template `.service`).

### Phase G: PanelKit + SelectedContext (resolve the render cycle)
**Rationale:** Near-last — consumes the dispatcher *and* the relocated renderer.
**Delivers:** `PanelKit` (registry→view builder, persistent-view plumbing, defer-then-edit ack, operator gate, isolation envelope) in the Discord adapter; `SelectedContext[I]`; `render_embed` moved app-side and injected; all v1.3 persistent-view rules preserved byte-identically.
**Avoids:** Pitfall 4 (DI inversion, not deferred import); Pitfall 6 (freeze `custom_id`s with a byte-string test); the v1.3 clone-path regression class (WR-01/WR-02) re-guarded by clone-render goldens.

### Phase H: Physical repo split + uv git dependency + EXTENSION-GUIDE.md
**Rationale:** Strictly last — in-place-then-split is a hard decision; only split once the boundary is clean and green.
**Delivers:** the `botkit` repo (`git mv` of the clean boundary), WeatherBot re-pointed via `tool.uv.sources` git pin (+ dev path override), exact `discord.py==2.7.1` pin in the module, `EXTENSION-GUIDE.md` recording implemented-vs-deferred seams + the durable-jobstore serialization contract + the promotion ledger, and the deploy ritual + startup-version-log.
**Avoids:** Pitfall 5 (clean-venv install test as the gate), Pitfall 6 (pin + custom_id + live restart UAT on `yahir-mint`), Pitfall 8 (promotion ledger / repin ritual).

### Phase Ordering Rationale
- **Goldens first** because byte-identical can't be proven for a line no test pins; the goldens are the continuous oracle for every move.
- **Leaf seams (no app callback) before consuming seams** — Channel and OccurrenceStore can't leak content; SchedulerEngine must precede ReloadEngine (reload reconciles jobs); PanelKit is last in-place (it consumes dispatch + the relocated renderer).
- **Split strictly last** — the milestone's in-place-then-split decision; the split re-runs the same goldens against the git-pinned module.
- **ConfigHolder (Phase E's first half) parallelizes** with the early scheduler work (it's independent of the OccurrenceStore/engine chain).

### Research Flags

Phases likely needing deeper research/design during planning:
- **Phase D (SchedulerEngine/JobStore):** the APScheduler serialization-clean seam shape is subtle (importable callable + picklable args + fire-time lookup) and is a *deferred-impl-but-design-now* contract — worth a focused design pass.
- **Phase E (ConfigHolder/ReloadEngine):** the pydantic-v2 generic-validation pitfall + the `validate`/`desired_jobs`/rollback hook shapes are the highest-effort, highest-coupling seam.
- **Phase G (PanelKit):** resolving the cycle by ownership + preserving every v1.3 persistent-view/clone-path/custom_id invariant byte-identically is intricate.
- **Phase H (split):** packaging/namespace/entry-point/dev-deploy mechanics + the live-host UAT have the most "works locally, breaks on host" surface.

Phases with standard patterns (lighter research):
- **Phase A (goldens):** established characterization-test technique; the suite already uses frozen fixtures + clock seams.
- **Phase B (Channel):** already a clean ABC + `retry.py`; lowest-risk move.
- **Phase F (Lifecycle):** small, well-understood seam (gate + injected callback + parameterized identity).

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | uv mechanics verified against current Astral docs + the installed uv 0.11.19 + WeatherBot's own `pyproject.toml`; packaging is well-trodden. |
| Features | MEDIUM | Framework comparisons cross-checked against official docs; the GENERIC-vs-APP-COUPLED line and anti-feature calls are opinionated synthesis (sound, but a judgment, not a fact). |
| Architecture | HIGH | Grounded in the *actual* current code read directly, plus current pydantic-v2/PEP 544/APScheduler/discord.py guidance; the build order is concretely tied to named functions. |
| Pitfalls | HIGH | Codebase-grounded (exact coupling points and line numbers), with APScheduler-serialization and discord.py-view claims cross-checked against upstream docs. |

**Overall confidence:** HIGH

### Gaps to Address (open decisions the requirements author must pin)

- **Module NAME** — research uses the placeholder `botkit`. The name must be chosen *before the in-place refactor* (the boundary subpackage should already be named what the extracted package will be, so the split is a `git mv` not a rename). Pin this in requirements.
- **Composition-root location post-split** — research names `main.py` as the wiring root, but where the composition root lives once `botkit` is external (and how the `weatherbot` console-script import chain crosses the boundary through stable public names) needs an explicit decision in the split phase.
- **Test partition (module tests vs app tests)** — deliberately deferred to the split phase: keep all 649 green in place during the refactor; only sort mechanism/generic tests into the module repo and weather-specific tests into the app when the second repo is created. Flag as a split-phase decision.
- **The four "secretly app-coupled" leak points** (from FEATURES.md) need explicit review-gates: the `SelectedContext` slot (must not hardcode "location"), the config-schema reconcile id-deriver (injected, not weather-aware), the health-check (injected, not OpenWeather), and the panel cosmetics (`registry→panel` must not bake the forecast grid / 📍 / emoji).

## Sources

### Primary (HIGH confidence)
- `.planning/PROJECT.md` — v2.0 milestone charter, guardrails, Key Decisions, existing seams (project ground truth).
- Current WeatherBot source read directly 2026-06-27 — `scheduler/daemon.py` (`fire_slot`/`_register_jobs`/`_reconcile_jobs`/`_do_reload`), `config/holder.py`+`models.py`, `channels/base.py`, `interactive/dispatch.py`/`panel.py`/`bot.py` (`render_embed` + deferred-import cycle), `ops/selfcheck.py`, `pyproject.toml`.
- https://docs.astral.sh/uv/concepts/projects/dependencies/ + /workspaces/ — git deps, editable path deps, `tool.uv.sources` not-published, `uv build --no-sources`, workspace limits.
- https://apscheduler.readthedocs.io/en/3.x/userguide.html + /faq.html — persistent-jobstore serialization constraint (globally-importable callable + picklable kwargs; `MemoryJobStore` doesn't serialize).
- https://peps.python.org/pep-0544/ + https://pydantic.dev/docs/ — Protocol/`@runtime_checkable` (presence-only), pydantic-v2 generic-model unparametrized-fallback-drops-fields pitfall.
- https://github.com/Rapptz/discord.py persistent.py + API docs — `timeout=None` + stable `custom_id` + `add_view` in `setup_hook` re-bind contract.
- `.planning/STATE.md` — dispatch_spec/persistent-view/panel-isolation accumulated context, `[bot]` read-once debt, deferred durable-jobstore framing, live restart UAT obligation on `yahir-mint`.

### Secondary (MEDIUM confidence)
- discord.py / hikari / interactions.py / APScheduler framework-line comparisons (library owns transport+plumbing+registration; app owns commands+content+schema) — official docs of each.
- https://pydevtools.com/handbook/how-to/how-to-manage-cross-repo-python-dependencies-with-uv/ — cross-repo dev-vs-deploy pattern, "don't commit the dev override."
- YAGNI / rule-of-three / plugin-discovery-as-over-engineering — established practice mapped to the milestone guardrails.

### Tertiary (LOW confidence)
- https://github.com/astral-sh/uv/issues/15895 + #11632 — proposed env-var override of `tool.uv.sources` is **open, not shipped** as of uv 0.11.19; do not design around it.

---
*Research completed: 2026-06-27*
*Ready for roadmap: yes*
