# Pitfalls Research

**Domain:** Brownfield extraction of a reusable, channel-agnostic bot framework out of a working app (WeatherBot) into its own repo, consumed back via a `uv` git dependency. Pure extraction — behavior byte-identical, the 649-test suite is the acceptance contract.
**Researched:** 2026-06-27
**Confidence:** HIGH (codebase-grounded; the specific coupling points named below were read directly from `weatherbot/interactive/`, `weatherbot/scheduler/`, `weatherbot/config/`, `pyproject.toml`. APScheduler-serialization and discord.py persistent-view claims cross-checked against current upstream docs.)

> **Framing for the requirements/roadmap author:** these are pitfalls *specific to framework-extraction and a two-repo split*, not generic coding mistakes. Each carries a concrete warning sign, an actionable prevention, and a **target phase shape** (in-place-seam phases vs. the physical-split phase vs. every-seam phases). The milestone's own guardrails — "pure extraction," the reminder-bot litmus test, build-in-consumer-then-promote, rule-of-three — are the antidotes; this file makes the failure modes those guardrails defend against concrete.

---

## Critical Pitfalls

### Pitfall 1: Leaky abstractions — weather concepts bleed into the "generic" module

**What goes wrong:**
The module is *meant* to be channel-agnostic and domain-agnostic, but app concepts ride along into the supposedly generic core. Concrete leaks already visible in this codebase:
- **`render_embed(reply, *, location=...)`** (`bot.py:194`) — `location` is a *weather* concept (a configured city). A generic Discord adapter has no notion of "location." If `render_embed` moves into the module's Discord adapter, that `location` kwarg drags a weather assumption with it.
- **The scheduler/config braid** — `weatherbot/scheduler/` (`context.py`, `catchup.py`, `uvmonitor.py`, `days.py`) and `weatherbot/config/models.py` are saturated with `location`, `forecast`, `uv`, `openweather`. The generic scheduler engine (`register(job_id, trigger, callback)`) must come out *without* `Location`, `send_time`, or `local_date` in its signatures.
- **`fire_slot` weather-braiding** — the scheduled callback reads `holder.current()`, picks a `Location`, fetches a forecast, renders a weather template, and persists a `weather_onecall` row in one body. Mechanism (schedule → fire exactly-once → deliver → retry/alert) is braided with content (which location, which forecast, which template).
- **`[bot]` and `[uv]` config tables** — `[uv]` is pure weather; `[bot] operator_id`/`panel_channel_id` are generic-bot concerns. A naive "lift the whole config model" carries `[uv]` into the framework.

**Why it happens:**
The code grew app-first; the seams were never drawn. During extraction it's faster to move a whole module than to bisect it, so weather nouns hitch a ride. Leaks are invisible from inside the weather app (everything *is* weather) — you only notice when a second consumer needs the module.

**How to avoid:**
- **The reminder-bot litmus test on every seam, as a written gate:** for each symbol crossing into the module, ask *"could a reminder bot use this with zero weather assumptions?"* If the signature names `location`, `forecast`, `uv`, `briefing`, `OpenWeather`, or `send_time` → it has not been un-braided. Generalize the noun (`location` → `job_id`/`context`/opaque `arg`) or leave that piece in the app.
- **Un-braid mechanism from content first, in place** (the milestone's "in-place seam first" deliverable): split `fire_slot` into a generic `run_job(job_id, occurrence, callback)` (exactly-once claim, isolation, retry/alert) and an app-supplied `callback` closure that does the weather. The framework calls `callback(occurrence)` and never looks inside.
- **App extends the schema, framework owns the holder** (already the chosen pattern for config hot-reload): the generic module owns the `ConfigHolder` + validate→swap→reconcile mechanism; the *app* owns `Config`, `Location`, `UvConfig`. `[uv]` never enters the module.
- **Grep gate per seam phase:** `grep -rniE 'weather|forecast|location|openweather|\buv\b|briefing' <module-path>/` must return only generic/incidental hits (docstrings, "uv" the packaging tool). Wire it as a test or CI check so a leak fails loud.

**Warning signs:**
- A module function signature contains a weather noun.
- The module imports anything from `weatherbot.weather.*` or `weatherbot.config.models` (`Location`, `UvConfig`).
- You cannot describe a module class without saying "weather" / "forecast" / "location."
- A test in the *module's* suite needs a forecast fixture.

**Phase to address:** **Every in-place seam phase** (scheduler-engine, config-holder, delivery/Channel, lifecycle, Discord-adapter). Make the litmus test + the grep gate a standing success criterion on each of those phases, not a one-time check at the split.

---

### Pitfall 2: Over-abstraction / premature generality — extension points no consumer exercises

**What goes wrong:**
Because the module is "for future bots," the temptation is to build a fully general plugin system — abstract `Trigger` hierarchies, a `Channel` ABC with capability negotiation, middleware hooks, a `JobStore` with three backends — none of which the only consumer (WeatherBot) actually uses. Untested generality is liability: it's dead code that constrains the API, can't be verified (no second caller), and is usually wrong when the real second consumer (reminder bot) finally arrives and needs something the speculative design didn't anticipate.

**Why it happens:**
"Make it reusable" is read as "make it maximally general." Designing for an imagined reminder bot feels like diligence. APScheduler/discord.py themselves model rich abstraction, inviting mimicry.

**How to avoid:**
- **Pure extraction is itself the guardrail.** The rule for v2.0 is byte-identical behavior — so the *only* abstractions allowed are the ones needed to make the *existing* behavior come out cleanly. If WeatherBot doesn't exercise a code path, it doesn't get built. This is why the milestone explicitly defers the **durable jobstore impl** (in-memory only ships) and Telegram/SMS/Slack channels.
- **Rule of three, enforced as build-in-consumer-then-promote:** don't promote a seam to the framework until a *real* second use exists. For v2.0 that means: ship the in-memory `JobStore` seam *shape* (so a durable impl can slot in) but do **not** write the durable impl — there's no consumer. The `Channel` abstraction is justified because WeatherBot already has two channels in tension (webhook + the inbound gateway) and SMS/Telegram are named future consumers; a `Trigger` plugin system is *not* justified (one trigger type — cron — is used).
- **Seam ≠ impl.** Designing a clean extension point (a documented `JobStore` interface) is cheap and correct; *implementing* the speculative backend is the trap. Document the gap as a deferred extension point (the milestone already plans an extension-guide doc recording implemented-vs-extension-point status).

**Warning signs:**
- A module abstraction has exactly one implementation and no test that swaps it.
- An interface method is never called by WeatherBot.
- You're writing a `RedisJobStore`/`SQLJobStore` "while you're in here."
- A `Channel` capability flag (`supports_embeds`, `supports_buttons`) exists but only Discord reads it.
- Config or constructor params exist "so future bots can override" with no current override.

**Phase to address:** **Every seam-design phase**, but flag the **scheduler-engine phase** (the `JobStore` seam is the highest over-abstraction risk) and the **Discord-adapter phase** (panel/`Channel` capability creep) for explicit "seam shipped, impl deferred, documented" success criteria. The extraction-guide/documented-seams phase records the deferred points.

---

### Pitfall 3: Behavior drift during a "pure" refactor — subtle changes slip past the test suite

**What goes wrong:**
A "behavior-preserving" extraction silently changes behavior in a way the 649-test suite doesn't cover, and it ships as "pure." Drift vectors that tests commonly miss:
- **Import-time side effects / ordering** — moving code across module boundaries changes when a module is imported, when a logger is configured, when a registry is populated (lazy `_wire_handlers` already exists *because* of import-cycle fragility — re-layering can re-break it).
- **Exception *type/identity* changes** — re-homing `UnknownLocationError` into the module changes its fully-qualified name; an `except weatherbot.X` elsewhere silently stops catching it. Tests that assert on *message text* but not *type* won't catch it.
- **Embed/text byte differences** — field order, whitespace, the `📍` line, the `Updated <t:…>` stamp, emoji on buttons. The clone-path render already had two regressions (WR-01 `label`, WR-02 `min/max_values`) that *first-construction* tests passed but *clone-path* tests caught.
- **Timezone / exactly-once key** — the sent-log key is stable `location.id`; any reshaping of the idempotency tuple `(location.id, send_time, local_date)` during un-braiding can double-send or skip with zero unit-test signal if no exactly-once-across-reload test exercises the new path.
- **Coverage gaps in the 649 suite:** a large suite is not a *characterization* suite. If embeds/replies are asserted field-by-field but not as a whole rendered byte string, a field-order change passes. If the scheduler is tested for "a job fires" but not "fires at the exact wall-clock instant with exactly-once across a restart+DST boundary," the un-braid can drift timing.

**Why it happens:**
"All tests green" is mistaken for "behavior unchanged." Tests assert *intended* behavior, not *every observable byte*; refactors change incidental behavior the tests never pinned.

**How to avoid:**
- **Characterization / golden tests before touching code** (the highest-leverage prevention for a pure extraction). Capture the *current* observable outputs as golden artifacts and assert byte-equality after each move:
  - **Golden embeds/replies:** snapshot the full rendered embed (title + description + every field, in order) for each command × the `📍`/`Updated` polish states, for a frozen forecast fixture and frozen clock. Diff is the proof of "byte-identical."
  - **Golden CLI output:** capture stdout/exit-code for `weather`, `check`, `send-now`, `help`, each forecast variant.
  - **Golden schedule plan:** for a fixed config, snapshot the registered jobs `(job_id, trigger spec, next_run_time)` and assert the un-braided scheduler produces the identical plan.
  - **Golden DB rows:** snapshot the `weather_onecall` / `alerts` / sent-log rows a briefing writes; assert byte-identical after the `fire_slot` un-braid.
- **Pin exception identity:** add a test asserting `isinstance(err, UnknownLocationError)` *via the import path other code uses*, so a re-home that changes identity fails.
- **Freeze the clock and the fixture** (the suite already uses frozen forecast fixtures + `discord.utils.utcnow()` seams — extend to every golden).
- **Refactor in micro-steps, run the full suite between each** — never a big-bang move. The v1.3 cadence (3–9 min plans, full suite each) is the right granularity.
- **Coverage audit before the refactor:** run coverage over the modules being moved; any un-covered branch in the move path gets a characterization test *first* (you cannot prove byte-identical for an untested line).

**Warning signs:**
- A test was *edited* (not just moved) to make it pass after a "pure" refactor — that edit is drift made invisible.
- Coverage drops on a moved module.
- A golden snapshot diff is "just whitespace" / "just field order" (it isn't — it's drift; the contract is *byte-identical*).
- A new `# behavior unchanged` comment with no golden test backing it.

**Phase to address:** **A characterization-test phase *before* the in-place seam phases** (lay the goldens first), then enforced on **every in-place refactor phase** and **re-run unchanged on the split phase** (same goldens must pass post-split against the git-pinned module). This is the load-bearing acceptance mechanism of the whole milestone.

---

### Pitfall 4: Circular imports — extraction surfaces the latent ones

**What goes wrong:**
A real cycle already exists and is worked around: `panel.py` imports `render_embed` *from* `bot.py` (`panel.py:54`), while `bot.py` needs `PanelView` *from* `panel.py` — resolved today by a **deferred (in-function) import of `PanelView` inside `bot.py`** (`bot.py:304`, `:581`, with explicit comments). Extraction makes this worse: drawing a hard module/package boundary turns soft intra-package cycles into hard cross-package cycles. If `render_embed` moves into the module's Discord adapter but `PanelView` (app-supplied location dropdown / 2×2 grid) stays in the app, the app→module→? edges can re-form a cycle, and a deferred-import workaround that worked *within* one package may not survive a package split (import timing, partially-initialized modules).

**Why it happens:**
Cycles accrete when two units genuinely collaborate (a view renders via a builder; the builder mounts the view). They're tolerated with lazy imports until a boundary forces the question. The `_wire_handlers` lazy registry wiring is a second existing tell that this codebase already fights import order.

**How to avoid:**
- **Establish a strict layering DAG and forbid up-edges** (the module's stated layering: *channel-agnostic core → per-channel adapters → app*). Concretely:
  - `core` (scheduler, config-holder, delivery, lifecycle) imports nothing from adapters or app.
  - `discord adapter` (gateway plumbing, persistent-view base, `render_embed`/embed primitives, registry→panel builder) imports `core`, never the app.
  - `app` (WeatherBot: `Location`, `UvConfig`, the location dropdown, the forecast 2×2 grid, the weather templates) imports the adapter + core, and **the adapter never imports back**.
- **Invert the `render_embed`↔`PanelView` cycle via dependency injection.** The reusable panel builder should take a *render callback* / reply→embed function as a parameter, not import a concrete `render_embed`. Then the app passes its renderer in; the module's panel base has zero edge to any concrete embed builder. This kills the cycle structurally instead of deferring it.
- **Treat the existing deferred imports as debt to *resolve at the boundary*, not copy across it.** When `render_embed`/`PanelView` straddle the module/app line, re-do the relationship as DI; do not port the in-function import.
- **Add an import-linter / layering check** (e.g. `import-linter` contracts, or a test that imports the core package in isolation and asserts it pulls in no adapter/app module). Fails loud if an up-edge sneaks in.

**Warning signs:**
- A new in-function / `TYPE_CHECKING`-only import added "to break a cycle" during extraction (it's a symptom — fix the layering).
- `ImportError: cannot import name X (most likely due to a circular import)` or a partially-initialized-module `AttributeError` at import time, *only* after the split.
- The core package can't be imported without dragging in the Discord adapter.
- `_wire_handlers`-style lazy registration multiplying.

**Phase to address:** The **Discord-adapter phase** (where `render_embed`/`PanelView` get re-homed — apply DI there) and a **layering-enforcement check** stood up early (ideally in the first in-place seam phase) so every subsequent phase is guarded. The **split phase** must re-verify the DAG holds across the package boundary.

---

### Pitfall 5: Packaging / import-path breakage on the split — "works locally, breaks on host"

**What goes wrong:**
The physical split changes import paths and install topology, and the daemon breaks on host `yahir-mint` (live systemd service) in ways green local tests didn't catch:
- **Import-path churn:** code under `weatherbot.interactive.bot` moves to e.g. `botkit.discord.embeds`; every `from weatherbot.interactive...` in the app and in tests must repoint. Miss one and it's an `ImportError` at *startup*, not at test time (if the missed import is in a lazily-loaded path).
- **Namespace collision / shadowing:** the module's distribution name vs. its import package. The app is `weatherbot` (dist + import package, `pyproject.toml:2`) with the `weatherbot = weatherbot.cli:main` console script. If the new module also exposes a top-level package that collides, or if the module is named `weatherbot-core` (dist) but imports as `weatherbot` (package), two distributions claiming the `weatherbot` import namespace shadow each other unpredictably.
- **Console entry point:** `[project.scripts] weatherbot = weatherbot.cli:main` must keep resolving. If `cli` or anything it imports moved to the module, the entry point's import chain now spans both packages — fine if the git dep is installed, broken if the dev env has the module editable but the host installs from a stale pin.
- **Editable-vs-git-pin dev/deploy mismatch (the classic "works locally"):** the developer uses an editable/path install of the module (`uv add --editable ../botkit` or a path source), so local picks up uncommitted module changes instantly. The host installs the module from a **git pin** (`uv add 'botkit @ git+…@<sha>'`). Any change not committed+pushed+repinned is present locally and **absent on the host** → the daemon runs old module code. Symptom: "I fixed it, tests pass, but the live bot still misbehaves."

**Why it happens:**
Editable installs paper over the publish boundary; the two-repo seam only bites at deploy time. Console scripts and namespace rules are invisible until something resolves to the wrong package.

**How to avoid:**
- **Pick distinct, non-shadowing names up front:** distribution `botkit` *and* import package `botkit` (not `weatherbot`). Never let two installed distributions own the same top-level import package. If you ever want a shared namespace, use an explicit PEP 420 namespace package deliberately — don't collide by accident.
- **Single source of truth for the import rename:** do the `from weatherbot... → from botkit...` repoint as one mechanical sweep with a grep gate (`grep -rn 'weatherbot.interactive' | grep -v <expected>` must be empty), then run the full suite *and* a real `import weatherbot; import botkit` smoke test.
- **Keep the `weatherbot` console entry point in the app** and ensure its import chain only crosses into the module through stable public names (re-exported from the module's top-level `__init__`), so a future internal module reshuffle doesn't break the script.
- **Test the *installed* artifact, not just the source tree:** in CI and before host deploy, do a clean `uv sync` from the git pin into a throwaway venv and run `weatherbot --help` / `weatherbot check` + the suite. This catches "missing import only in the installed layout."
- **Make the dev↔host install mode explicit and documented:** local editable is fine for iteration, but a **commit→push→`uv lock`/repin→deploy** ritual is mandatory; the host always installs the pinned sha. Add a deploy checklist item: "module sha in `uv.lock` matches the intended module commit." Consider a startup log line printing the resolved module version/sha so the live daemon *announces* which module it's running.

**Warning signs:**
- `pip list`/`uv pip list` shows two distributions and you're unsure which owns `import weatherbot`.
- The bot works in `uv run` from the source tree but fails after `uv sync` in a clean venv.
- A module fix is live locally but the host shows old behavior (→ unpushed/un-repinned).
- `weatherbot: command not found` or the script imports fail after the split.

**Phase to address:** **The physical-split phase** (naming, import sweep, entry-point, installed-artifact test) and a **deploy-ritual / startup-version-log** item folded into that phase's success criteria. The clean-venv install test is the gate that turns "works locally" into "works on host."

---

### Pitfall 6: APScheduler callback-serialization coupling baked into the seam

**What goes wrong:**
The generic scheduler engine ships with an **in-memory `JobStore` only**, and the `JobStore` seam is designed casually — `register(job_id, trigger, callback)` stores the `callback` as a live Python object (a bound method / closure over the app's config holder, channel, etc.). This works forever with `MemoryJobStore` because it does **not serialize jobs**. But the milestone explicitly designs the seam *for a future durable jobstore*. The moment a durable jobstore (SQLAlchemy/Redis/etc.) is added, APScheduler **serializes the job**, which imposes two hard requirements the in-memory design quietly violated:
1. the target callable must be **globally importable** (a closure / bound method / nested function fails with `ValueError: This Job cannot be serialized since the reference to its callable … could not be determined. Consider giving a textual reference (module:function name) instead.`), and
2. all job **arguments must be picklable** (passing the live `ConfigHolder`, an `httpx.Client`, or a Discord client as a job arg breaks serialization).

If the seam is designed today around closures/live objects, the deferred durable jobstore becomes a *redesign*, not a drop-in — defeating the whole point of "design the seam now."

**Why it happens:**
`MemoryJobStore` is forgiving — closures and rich live args "just work," so the design never feels the constraint. The serialization requirement is invisible until the durable backend is plugged in, which is *exactly* the deferred future the seam is supposed to anticipate.

**How to avoid (design the seam now to be serialization-ready, even though only the in-memory impl ships):**
- **Make the registered callable globally importable** — a module-level function `module:function_name`, not a nested closure or a bound method on a per-run instance. APScheduler accepts a *textual reference*; design `register(...)` so the callback is (or can be expressed as) an importable top-level function.
- **Pass only picklable, identity-style arguments** — schedule jobs with `(job_id, occurrence_key)` and have the callback **look up** live collaborators (config holder, channel, client) from a module-level/app-level registry *at fire time*, rather than capturing them as job args. This mirrors the existing healthy pattern where `fire_slot` reads `holder.current()` at fire time instead of closing over a snapshot — keep that discipline in the generic seam.
- **Document the constraint in the seam contract:** the `JobStore` extension-point doc states "callbacks registered through `register()` must be importable and args must be picklable for any durable backend" — so a future implementer (and the reminder bot) doesn't design closures that can't migrate.
- **Add a guard test even for the in-memory impl:** assert each registered callback is a module-level function (has a real `__module__:__qualname__` that re-imports) and that its args are picklable — so the in-memory bot can't accidentally bake in an un-serializable shape that the durable jobstore would later reject.

**Warning signs:**
- `register()` is called with a `lambda`, a nested `def`, or `self.method`.
- Job args include a `ConfigHolder`, an open client/connection, a Discord/gateway object, or anything holding a socket/lock.
- The seam doc doesn't mention serialization/pickling at all.

**Phase to address:** **The scheduler-engine seam phase** (design `register()` + the `JobStore` interface to be serialization-clean; ship in-memory impl; add the importable-callback/picklable-args guard test; record the durable-jobstore constraint in the extension-guide). The durable *impl* stays deferred.

---

### Pitfall 7: discord.py version pin & persistent-view `custom_id` stability across the split

**What goes wrong:**
Two coupled traps the split can introduce:
- **Version drift on the pin.** discord.py is pinned at **2.7.1** for a reason (the whole v1.3 panel was verified against it: ack semantics, `pin_messages` vs `manage_messages` permission split, `add_view` in `setup_hook`). If the module declares a loose dependency (`discord.py>=2.7`) and the app another, `uv` can resolve the host to a *different* discord.py than was verified — silently changing persistent-view, permission, or interaction-response behavior the panel depends on. "Works locally" (resolved 2.7.1) vs. "breaks on host" (resolved 2.8.x) is the same dev/deploy mismatch as Pitfall 5, now in a transitive dep.
- **`custom_id` instability across the move.** Persistent views re-bind buttons **by `custom_id` across restarts** (`timeout=None` + every child has a stable `custom_id` + `add_view` in `setup_hook`). The live host has a **pinned panel message already in Discord** carrying the *current* `custom_id`s (the `wb:` marker prefix `_is_owned_panel` checks). If extraction **changes any `custom_id` string** (e.g. a refactor namespaces them `botkit:` or regenerates them), the already-pinned panel's buttons stop routing after deploy → "This interaction failed" on every tap, and `_is_owned_panel` may no longer recognize its own panel (orphaning the pin / failing the find-or-recreate-one invariant).

**Why it happens:**
Pins are loosened "to be flexible" during a library extraction. `custom_id`s look like internal strings, so a rename feels safe — but they're a **persisted external contract** baked into a live Discord message, not just code.

**How to avoid:**
- **Pin discord.py exactly (`==2.7.1`) in the module** (the package that owns the Discord adapter), and let the app inherit that pin — one authority for the verified version. Re-verify deliberately before any bump; never let resolution float it.
- **Treat `custom_id` strings as a frozen wire contract.** Centralize them as constants (already the pattern) and add a test asserting the exact `custom_id` byte strings (and the `wb:` ownership marker) are unchanged. Any extraction that *must* re-namespace them is **not** pure — it requires a re-summon migration on the host and should be called out, not slipped in.
- **If `custom_id`s genuinely must change,** ship a one-time `!panel` re-summon as the migration (the codebase already re-summons a fresh panel and deletes the old — 260626-uqp), and document it as a deploy step; do not assume the old pinned panel will keep working.
- **Re-run the live persistent-view restart UAT** (already a tracked obligation) after the split, on host `yahir-mint`: deploy → `systemctl restart` → tap every button/dropdown on the pinned panel → confirm routing + correct default location.

**Warning signs:**
- The module's dependency on discord.py is a range, not `==2.7.1`.
- `uv.lock` on the host resolves a discord.py other than 2.7.1.
- A diff touches any `custom_id` constant or the `wb:` marker.
- After deploy, the pinned panel taps return "This interaction failed" (custom_id contract broken).

**Phase to address:** **The Discord-adapter phase** (centralize + freeze `custom_id`s, assert them in a test) and **the split phase** (exact discord.py pin in the module, clean-venv resolution check, re-run the live restart UAT). The `custom_id`-byte test guards drift on every phase in between.

---

### Pitfall 8: Two-repo churn — pin lag and the "anemic module / duplicated infra" promotion failure

**What goes wrong:**
- **Pin/version lag:** with two repos, every module change needs commit → push → repin in the app → `uv lock` → deploy. It's easy to (a) develop against an editable module and forget to repin (Pitfall 5), or (b) leave the app on a stale module sha so module fixes never reach the host. Inverse risk: the app's `uv.lock` drifts ahead of a module commit that wasn't pushed.
- **The promotion failure (the *strategic* two-repo trap):** the milestone mandates **build-in-consumer-then-promote** + rule-of-three. The failure mode is the two halves of that rule getting *unbalanced*:
  - **Anemic shared module:** so afraid of premature generality that genuinely reusable infra (the next bot needs it too) is built *only* in WeatherBot and **never promoted back** to the module. The reminder bot then re-implements scheduling/config-reload/delivery from scratch → **duplicated infra**, two divergent copies, double the bugs. The module slowly becomes a hollow shell while the real infra lives (twice) in the consumers.
  - **Premature promotion:** the opposite — pushing a one-consumer abstraction up to the module before a second consumer validates it (Pitfall 2).

**Why it happens:**
Promotion is friction (two PRs, a repin, a release) so it's deferred; "I'll promote it later" becomes "the reminder bot copied it." The discipline only works if someone actually runs the rule-of-three ledger.

**How to avoid:**
- **A written promotion ledger / contributing rule in the module repo:** "infra used by ≥2 bots (or clearly bot-generic and exercised once with a second named consumer) gets promoted to the module within N." Make the extraction-guide doc track *what's in the consumer that should be promoted* as a standing list, not tribal memory.
- **Tighten the repin ritual:** a single documented deploy step (`uv lock --upgrade-package botkit` to the intended sha) + the startup-version-log line (Pitfall 5) so the live daemon announces its module sha; a mismatch is visible, not silent.
- **Default new bot-generic code to the module when a second consumer is already named** (reminder bot is named in the milestone) — but only after rule-of-three evidence; otherwise build it in WeatherBot and *log it in the ledger* for promotion.
- **Periodic duplication audit:** grep both repos for parallel implementations of the same concern (a second `ConfigHolder`, a second retry/backoff) — duplication is the smell that promotion was skipped.

**Warning signs:**
- A module fix is committed but the app's pin (and host) still points at the old sha.
- The reminder bot (when it arrives) copy-pastes a WeatherBot module instead of importing it.
- Two repos contain near-identical scheduler/config/delivery code.
- The module's `__init__` exports shrink over releases while consumers grow.

**Phase to address:** **The physical-split + extension-guide phase** (stand up the repin ritual, the startup-version-log, and the promotion ledger as artifacts). It's then a *process* obligation carried into future milestones (the reminder-bot project), not a one-phase fix.

---

### Pitfall 9: systemd / process-lifecycle assumptions baked into the module a non-weather bot wouldn't share

**What goes wrong:**
The module ships a "process lifecycle" piece (systemd `Type=notify` READY-gate / supervised restart). It's easy to bake **WeatherBot-specific** assumptions into that generic lifecycle:
- **Health-check coupling:** WeatherBot gates `READY=1` only after a *weather/OpenWeather* startup self-check (`gate_until_healthy` blocks `emit_online` until a key/network check passes). A reminder bot has no OpenWeather to check. If the module's lifecycle *calls weather code* to decide readiness, it's not generic.
- **Hardcoded paths/unit assumptions:** `PID_FILE=/run/weatherbot/weatherbot.pid`, `RuntimeDirectory=weatherbot`, the unit name `weatherbot`, `EnvironmentFile`, the `weatherbot` console name — all weather-named. A module that hardcodes `weatherbot` in the PID path or sd_notify socket handling forces the reminder bot to inherit WeatherBot's filesystem identity.
- **Scheduler/thread-topology assumptions:** the inbound bot runs in its own thread, started *after* READY, torn down in `finally`; the briefing spine is a sync `BackgroundScheduler`. If the module's lifecycle assumes "there is a BackgroundScheduler and a BotThread and they relate *this* way," a bot with a different topology can't use it.
- **Read-once-at-startup config items** (`[bot] operator_id`, `[reload] watch`, and now `panel_channel_id`) are a known restart-boundary debt. Baking "these specific keys are restart-only" into the generic config/lifecycle leaks weather-app policy into the framework.

**Why it happens:**
The lifecycle was written for one bot, so its only health check, paths, and topology are that bot's. "Generic process supervision" and "WeatherBot's supervision" look identical from inside WeatherBot.

**How to avoid:**
- **Invert the health check** (the milestone already specifies this: lifecycle takes an **app-provided health-check callback**). The module owns *when* it gates READY and *how* it talks to systemd (`sd_notify`, READY=1, watchdog); the **app supplies the predicate** (WeatherBot → OpenWeather/key check; reminder bot → its own check, or a trivial always-healthy default). The module must never import weather code to decide readiness.
- **Parameterize all identity:** PID path, runtime dir, unit/service name, env-file location, console-script name are **app inputs** (constructor args / a `ProcessConfig`), with no `weatherbot` literal in the module. The reminder bot passes its own.
- **Don't bake topology:** the module exposes lifecycle hooks (start-after-ready, teardown-in-finally) but doesn't assume a specific scheduler/thread arrangement; the app wires its own components into those hooks.
- **Keep restart-boundary *policy* in the app:** "these config keys need a restart" is a WeatherBot decision (documented debt) — the generic config-holder shouldn't enshrine a specific key list; it offers the validate→swap→reconcile mechanism and the app declares which fields are live vs restart-only.
- **Apply the litmus test (Pitfall 1) to the systemd unit too:** ship the unit as a *template* with `{{name}}`/`{{exec}}` placeholders, not a `weatherbot.service` with hardcoded paths, so a reminder bot generates its own.

**Warning signs:**
- The module's lifecycle imports anything weather/OpenWeather to decide readiness.
- The string `weatherbot` (or a weather path) appears in the module's lifecycle/systemd code or shipped unit.
- The module assumes a `BackgroundScheduler` + `BotThread` exist and relate a fixed way.
- A generic config/holder hardcodes which keys are restart-only.

**Phase to address:** **The process-lifecycle seam phase** (health-check callback inversion, identity parameterization, template unit) and **the config-holder phase** (keep restart-boundary policy app-side). Verified by the reminder-bot litmus test on every lifecycle symbol.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Port the existing **deferred (in-function) import** across the module/app boundary instead of inverting via DI | Fast — keeps the cycle "working" | Hard cross-package cycle / partially-initialized-module bugs only on the split; fragile import order forever | Never — resolve at the boundary with DI (Pitfall 4) |
| **Editable/path install** of the module for dev | Instant local iteration, no repin churn | "Works locally, breaks on host" — host runs the stale git pin (Pitfall 5/8) | OK for iteration *with* a strict commit→push→repin ritual + startup-version-log so drift is visible |
| Loose `discord.py>=2.7` (or any range) in the module | Flexible resolution | Host resolves an unverified version → silent panel/permission/ack behavior change (Pitfall 7) | Never for the verified-critical dep — pin `==2.7.1` |
| Register scheduler callbacks as **closures / bound methods** with live-object args | Works perfectly with the shipped in-memory jobstore | Durable jobstore later becomes a redesign, not a drop-in (Pitfall 6) | Never if the `JobStore` seam claims to be "designed for durable" — use importable callables + picklable args now |
| Move whole modules wholesale ("lift `interactive/` into the module") | Less bisection effort | Weather nouns leak into the generic core (Pitfall 1); over-abstraction creeps (Pitfall 2) | Never — un-braid mechanism/content per the litmus test |
| Edit a test to make a "pure" refactor pass | Green suite now | Drift made invisible — the byte-identical contract silently broken (Pitfall 3) | Never — if a test must change, the refactor isn't pure; add a golden instead |
| Re-namespace `custom_id`s during cleanup | Tidier strings | Live pinned panel's buttons stop routing after deploy (Pitfall 7) | Only with an explicit `!panel` re-summon migration documented as a deploy step |
| Bake `weatherbot` paths/health-check into the generic lifecycle | Lifecycle "just works" for WeatherBot | A non-weather bot can't reuse it (Pitfall 9) | Never — parameterize identity, inject the health check |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **APScheduler (durable jobstore, future)** | Registering closures/bound methods with live-object args (fine in-memory) | Importable `module:function` callables + picklable `(job_id, occurrence)` args; look up collaborators at fire time (Pitfall 6) |
| **discord.py persistent views** | Changing `custom_id` strings or floating the version during the split | Freeze `custom_id`s as an asserted wire contract; pin `==2.7.1`; re-summon migration if they must change (Pitfall 7) |
| **systemd `Type=notify`** | Generic lifecycle gates READY on a weather-specific self-check / hardcodes `weatherbot` paths | App-provided health-check callback; parameterized PID/runtime/unit names; template `.service` (Pitfall 9) |
| **`uv` git dependency** | Editable local + stale git pin on host → divergent code | Commit→push→`uv lock --upgrade-package`→deploy ritual; clean-venv install test; startup log of resolved module sha (Pitfall 5/8) |
| **Module import namespace** | Two distributions both owning the `weatherbot` import package | Distinct dist+import name (`botkit`); deliberate PEP 420 only if a shared namespace is truly wanted (Pitfall 5) |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Durable jobstore re-serializes/re-loads every job each fire if mis-seamed | Latency/CPU per tick once a durable backend is added | Keep the seam shaped for cheap serialization (small picklable args, importable callables); don't pass heavy live objects | Only if/when the deferred durable jobstore is implemented |
| Import-time side effects fan out across the new package boundary | Slow / order-dependent startup after the split | Keep module-top imports light; no heavy work at import; layering DAG (Pitfall 4) | At process start on the host (not in fast unit tests) |
| Clean-venv `uv sync` from git pin is slow / flaky in CI | Long deploys | Pin exact shas; cache; but always run the installed-artifact smoke test before host deploy | Every deploy — acceptable cost for catching "works locally" |

*(Scale is not a concern here — single-user personal bot. These traps are about the extraction mechanics, not load.)*

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Secrets cross the module boundary as args or get logged by generic module code | `DISCORD_BOT_TOKEN` / OpenWeather key leak into module logs or pickled job args | Module never logs secret-bearing args; secrets stay app-side in git-ignored `.env`; don't pass tokens as scheduler job args (also breaks serialization — Pitfall 6) |
| Generic operator/interaction gate weakened during extraction | Non-operator can drive the panel; identity echoed in a reject | Preserve `interaction_check` operator gate + identity-free ephemeral reject byte-for-byte (golden test the reject text); litmus-test that the *gate* is generic but the *operator_id* is app config |
| Permission preflight regressed (the `pin_messages` vs `manage_messages` split) | Orphan panel write / `Forbidden` at runtime | Keep the eager `permissions_for` preflight using `pin_messages` (2026-01-12 split) + per-write `discord.Forbidden` backstop; golden the preflight path |
| Module repo published with the app's secrets/config committed | Key leak in a now-separate repo's history | Module repo carries no `.env`, no real config, no fixtures with live keys — audit before the first push |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Panel polish (`📍`, emoji, `Updated <t:…>` stamp) lost in the clone path after extraction | Operator sees a degraded panel after taps/restart | Carry the v1.3 clone-path fix into the module's panel base; golden the clone-render embed across ack/collapse states (the WR-01/WR-02 class of bug) |
| `!panel` re-summon (channel-bottom, exactly-one, delete-strays) broken by the split | Buried/duplicate panels on mobile | Preserve the 260626-uqp create-before-delete re-summon; live restart UAT post-split |
| "This interaction failed" after deploy due to a changed `custom_id` | Every tap on the pinned panel fails | Freeze `custom_id`s (Pitfall 7); if changed, force a re-summon migration |

## "Looks Done But Isn't" Checklist

- [ ] **"Pure extraction":** all 649 tests green — but verify with **golden/byte-identical** snapshots (embeds, CLI output, schedule plan, DB rows), not just intent-level assertions (Pitfall 3).
- [ ] **"Module is generic":** compiles and WeatherBot works — but run the **reminder-bot litmus grep** (`weather|forecast|location|uv|openweather|briefing` returns only incidental hits) over the module (Pitfall 1).
- [ ] **"Seam designed for durable jobstore":** the `JobStore` interface exists — but assert registered callbacks are **importable** and args **picklable** (Pitfall 6).
- [ ] **"Works after the split":** local `uv run` works — but do a **clean-venv `uv sync` from the git pin** + `weatherbot check`/`--help` + full suite (Pitfall 5).
- [ ] **"Panel still works":** code unchanged — but the **live pinned panel** on host `yahir-mint` still routes after `systemctl restart` (custom_id contract + persistent-view re-bind) (Pitfall 7).
- [ ] **"No cycles":** imports work — but the **core package imports in isolation** with zero adapter/app edges (import-linter / isolation test) (Pitfall 4).
- [ ] **"Lifecycle is reusable":** READY-gate works — but it gates on an **app-provided callback**, not weather code, with no `weatherbot` literal in the module (Pitfall 9).
- [ ] **"Host runs the new code":** deployed — but the **startup log prints the resolved module sha** and it matches the intended commit (Pitfall 5/8).

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Behavior drift shipped as "pure" (Pitfall 3) | MEDIUM | Bisect against the golden snapshots; the golden that flips localizes the drifting move; revert that micro-step, add the missing characterization test, redo |
| `custom_id` changed → live panel dead (Pitfall 7) | LOW | Run `!panel` to re-summon a fresh panel (delete-strays already implemented); document the migration; freeze the new `custom_id`s with a test |
| "Works locally, breaks on host" — stale pin (Pitfall 5/8) | LOW | Commit+push the module, `uv lock --upgrade-package botkit @ <sha>`, redeploy; add the startup-version-log so it can't recur silently |
| Durable jobstore won't serialize closures (Pitfall 6) | HIGH | Rewrite the registered callbacks as importable functions + picklable args — a redesign; **avoid** by shaping the seam now |
| Weather noun leaked into the module (Pitfall 1) | MEDIUM | Generalize the signature (location→opaque arg/context) or push that piece back to the app; re-run the litmus grep; the golden suite proves byte-identical after the move |
| Cross-package cycle on the split (Pitfall 4) | MEDIUM | Invert via DI (pass the renderer/collaborator in) rather than a deferred import; add the import-isolation test |

## Pitfall-to-Phase Mapping

> Phase *names* are indicative of the milestone's stated deliverables (in-place seam first → physical split). The roadmap author should attach each prevention as a success criterion on the matching phase.

| Pitfall | Prevention Phase(s) | Verification |
|---------|---------------------|--------------|
| 1 — Leaky abstractions | **Every in-place seam phase** (scheduler, config-holder, delivery/Channel, lifecycle, Discord-adapter) | Reminder-bot litmus grep returns only incidental weather hits; no module signature names a weather noun |
| 2 — Over-abstraction | **Every seam phase**; flagged on scheduler-engine + Discord-adapter | Each module abstraction has a real consumer/test; durable jobstore impl absent + documented deferred |
| 3 — Behavior drift | **Characterization-test phase (first)**, enforced on every in-place refactor phase, re-run on the split | Golden embeds/CLI/schedule-plan/DB-rows byte-identical; no test was edited to pass; coverage didn't drop |
| 4 — Circular imports | **First seam phase** (stand up layering check) + **Discord-adapter phase** (DI invert `render_embed`↔`PanelView`) | Core package imports in isolation; import-linter contract green; no new deferred import added |
| 5 — Packaging/import breakage | **Physical-split phase** | Clean-venv `uv sync` from git pin + `weatherbot check`/`--help` + full suite pass; distinct dist+import names; startup-version-log present |
| 6 — APScheduler serialization seam | **Scheduler-engine seam phase** | Guard test: registered callbacks importable + args picklable; constraint recorded in extension-guide |
| 7 — discord.py pin / custom_id | **Discord-adapter phase** (freeze custom_id) + **split phase** (pin `==2.7.1`) | custom_id byte-string test; lock resolves 2.7.1; live restart UAT on yahir-mint re-passes |
| 8 — Two-repo churn / promotion | **Split + extension-guide phase** (process artifacts) | Promotion ledger exists; repin ritual + startup-version-log documented; no duplicated infra across repos |
| 9 — systemd/lifecycle assumptions | **Process-lifecycle seam phase** + **config-holder phase** | Lifecycle gates on app-provided callback; no `weatherbot` literal in module; template `.service`; restart-boundary policy stays app-side |

## Sources

- WeatherBot codebase (read 2026-06-27): `weatherbot/interactive/bot.py` (`render_embed` at :194, deferred `PanelView` import at :304/:581), `weatherbot/interactive/panel.py` (`render_embed` import at :54, custom_id/`wb:` marker discipline), `weatherbot/scheduler/*` + `weatherbot/config/*` (weather/location/uv braid), `pyproject.toml` (dist+import name `weatherbot`, `[project.scripts] weatherbot = weatherbot.cli:main`, hatchling). HIGH
- `.planning/PROJECT.md` (v2.0 milestone goal/guardrails, Known tech debt, Key Decisions — `fire_slot`/`holder.current()`, `gate_until_healthy` READY-gate, persistent-views-by-custom_id, `pin_messages` split, the panel↔render relationship). HIGH
- `.planning/STATE.md` (Blockers/Concerns — `[bot]` read-once-at-startup debt; reuse anchors; deferred durable-jobstore framing; live persistent-view restart UAT obligation on host `yahir-mint`). HIGH
- APScheduler 3.x User Guide & FAQ — persistent jobstores serialize jobs → target callable must be globally importable, args must be picklable; `MemoryJobStore` does not serialize. https://apscheduler.readthedocs.io/en/3.x/userguide.html , https://apscheduler.readthedocs.io/en/3.x/faq.html . HIGH
- discord.py persistent views — `timeout=None` + every child has a stable `custom_id` + `add_view` in `setup_hook`; re-bind across restarts depends on consistent `custom_id` values. https://github.com/Rapptz/discord.py/blob/master/examples/views/persistent.py , https://discordpy.readthedocs.io/en/stable/api.html . HIGH
- General framework-extraction discipline (rule of three / build-in-consumer-then-promote / leaky abstractions): established software-engineering practice, mapped here to the milestone's explicit guardrails. MEDIUM

---
*Pitfalls research for: brownfield framework-extraction + two-repo split (WeatherBot v2.0 "The Great Decoupling")*
*Researched: 2026-06-27*
