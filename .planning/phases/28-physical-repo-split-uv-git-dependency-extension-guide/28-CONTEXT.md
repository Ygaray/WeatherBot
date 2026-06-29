# Phase 28: Physical Repo Split + uv Git Dependency + EXTENSION-GUIDE - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning
**Mode:** `--auto` (single-pass; decisions auto-selected on the reusable-module + byte-identical-lowest-risk axis — see DISCUSSION-LOG for the per-question log)

<domain>
## Phase Boundary

**The strictly-last phase of v2.0.** With the in-place boundary clean (all of `yahir_reusable_bot/**`
imports zero app code, litmus-grep clean) and the full 649-suite + Phase-21 goldens green, this phase
**physically splits** the module out of the WeatherBot repo into its own repo **`YahirReusableBot`**
(import root `yahir_reusable_bot`, shipping **no** console script) and **re-points WeatherBot at it
through a uv git dependency**.

**What moves (verbatim, no behavior change):** the entire flat-sibling `yahir_reusable_bot/` tree —
`channels/`, `config/`, `discord/` (gateway + panelkit + selection, Phase 27), `lifecycle/`, `ports/`,
`registry/`, `reliability/`, `scheduler/` — to the new repo. Its only third-party imports are
`discord.py`, `httpx`, `structlog`, `tenacity` (confirmed by grep); everything else it uses is stdlib.

**What stays app-side:** the `weatherbot` package + the `weatherbot` **console entry point**
(`[project.scripts] weatherbot = "weatherbot.cli:main"`), which crosses into the module **only through
stable public names**. All the app-specific injection (`render`, panel cosmetics, the `wb:` marker,
`operator_id`/`panel_channel_id`, config schema, `validate`/`desired_jobs` hooks) stays at the
`weatherbot/scheduler/wiring.py build_runtime(...)` composition root (Phase-25 D-04).

**The re-point mechanics (the research-flagged surface — "works locally, breaks on host"):**
- WeatherBot depends on `yahir-reusable-bot` via a **uv git dependency** (`[tool.uv.sources]` git pin),
  **tag-pinned for deploy**, with a reproducible `uv.lock` (the resolved commit sha) so
  `uv sync --frozen` is byte-reproducible host-side.
- An **editable path override** for local co-development (sibling checkout), so day-to-day work edits
  both repos without a push→repin round-trip — but the *committed* default stays the deploy git pin.
- A **`uv build --no-sources` leak gate** proving the module wheel carries no app code and resolves
  with no path/source leakage.
- The `discord.py==2.7.1` **exact pin moves out of the app pyproject into the module's own pyproject**
  (the pyproject comment already flags this as the Phase-28 destination, SEAM-07 D-05). WeatherBot
  inherits the pinned Discord transitively through the module dep.

**The ship deliverables (DOCS-01 + process artifacts):**
- The **`EXTENSION-GUIDE`** in the module repo, documenting every plug point (`JobStore`, command
  registration, config-schema extension, `Channel`, panel `SelectedContext`, health-check) with
  **implemented-vs-deferred status**, including the durable-`JobStore` **serialization contract**.
- The module **initialized as its own GSD project** (its own `.planning/`), recording the
  **durable-`JobStore` impl** and a **second `Channel` adapter** as deferred extension points
  (build-in-consumer-then-promote, rule of three).
- The durable **commit→push→tag→repin→deploy ritual**, a **startup-version-log** line announcing the
  pinned module sha, and a **promotion ledger** tracking sha promotions.

**The acceptance gate (turns "works locally" into "works on host"):** a clean-venv
`uv sync --frozen` install + `weatherbot check` / `--help` + the full suite + goldens pass against the
pinned module; then the **live `yahir-mint` UAT** — deploy → `sudo systemctl restart weatherbot` → the
bot runs against the pinned sha (announced by the startup-version-log line) and **every button/dropdown
on the already-pinned live panel still routes** (custom_id contract + persistent-view re-bind intact),
with the correct default location.

**Scope guardrail:** this is **pure relocation + re-point + docs** — no source edits to module logic
beyond what the physical move mechanically requires (e.g. scrubbing the two stale `weatherbot.*`
docstring/comment references in `channels/__init__.py` and `ports/alerts.py`). Behavior stays
byte-identical; the Phase-21 goldens are the oracle, re-run from the consuming app against the pinned
module. No new user-facing feature.

</domain>

<decisions>
## Implementation Decisions

The ROADMAP Phase-28 detail block + PKG-02 + DOCS-01 **pre-lock the headline** (own repo
`YahirReusableBot`, import root `yahir_reusable_bot`, no console script; uv git dep tag-pinned for
deploy + editable path override for dev + reproducible `uv.lock` + `uv build --no-sources` leak gate;
EXTENSION-GUIDE with implemented-vs-deferred status; module as its own GSD project; repin ritual +
startup-version-log + promotion ledger; clean-venv install + live `yahir-mint` restart UAT). This is a
**research-flagged phase** — the packaging / namespace / entry-point / dev-vs-deploy mechanics + the
live-host UAT carry the most "works locally, breaks on host" risk. The decisions below lock the **HOW
shape** on the reusable-module + lowest-byte-identical-risk axis; the **intricate uv/packaging mechanics
are explicitly handed to the researcher/planner** (see Claude's Discretion).

### Repo creation + history (PKG-02 / SC#1)
- **D-01 [chosen: fresh `git init` in `YahirReusableBot` with a single clean import commit; the
  WeatherBot repo retains the full Phase 22–27 extraction history]:** the new repo starts from a clean
  baseline (the module tree as-is at the split commit). The rich in-place extraction history (Phases
  22–27) **already lives durably in the WeatherBot repo** and is not lost. The ROADMAP's "initialize
  the module as its own GSD project" (D-07) implies a fresh project baseline, which a clean import
  commit gives directly.
  - **Why not `git filter-repo` / `git subtree split` to carry the module's per-file history into the
    new repo (rejected as default):** more machinery for a single-dev personal module whose history is
    preserved in WeatherBot anyway; it complicates the "own GSD project from a clean baseline" intent.
    **Planner's discretion** to use a history-preserving split *if* it proves trivially cheap and the
    clean import commit is otherwise unaffected — but the default is fresh-init.

### Module package identity (PKG-02 / SC#1, SC#2)
- **D-02 [chosen: PyPI-normalized name `yahir-reusable-bot`, import root `yahir_reusable_bot`, **no**
  `[project.scripts]` console script, `hatchling` build backend, `requires-python >=3.12`]:** mirror
  WeatherBot's build toolchain (hatchling) so the split is mechanical. The module ships a library only —
  **no console script** (ROADMAP/PKG-02-locked); the `weatherbot` entry point stays app-side and is the
  *only* console script in the two-repo system. The module's `[tool.hatch.build.targets.wheel]` packages
  just `yahir_reusable_bot` (the app's current two-package wheel collapses back to one package once the
  module leaves).
  - **Locked by ROADMAP/PKG-02** — the only open detail is the exact pyproject metadata (classifiers,
    description, version `0.1.0`), which is mechanical.

### Dependency partition (PKG-02 / SC#2 leak gate)
- **D-03 [chosen: the module's pyproject declares exactly the deps its code imports —
  `discord.py==2.7.1`, `httpx`, `structlog`, `tenacity`; the exact `discord.py` pin **moves out of the
  app pyproject into the module's**; WeatherBot keeps its app-only deps + the module via git dep]:** the
  partition follows actual imports (grep-confirmed: module imports only `discord`, `httpx`, `structlog`,
  `tenacity` + stdlib). WeatherBot retains `apscheduler`, `cachetools`, `discord-webhook`,
  `pydantic`/`pydantic-settings`, `watchfiles`, + the OpenWeather/template stack, and gains
  `yahir-reusable-bot` (which transitively pins `discord.py==2.7.1`). The `grimp` import-hygiene gate +
  the `uv build --no-sources` leak gate together prove the cut is clean (no app code in the module wheel,
  no module dep orphaned app-side).
  - **Why not over-declare the module's deps to "be safe" (rejected):** dead deps bloat the wheel and
    muddy the litmus; declare exactly what's imported and let the leak gate + a clean-venv install prove
    completeness.
  - **Planner's discretion:** whether `grimp` (and the rest of the dev-tooling) is duplicated into the
    module repo's own `[dependency-groups] dev` (it ships its own test/hygiene suite as a GSD project) vs
    pared down — pick what keeps each repo's `uv.lock` clean.

### uv git dependency + pin granularity (PKG-02 / SC#1, SC#2)
- **D-04 [chosen: `[tool.uv.sources]` git entry **tag-pinned** for deploy (e.g. `tag = "v0.1.0"`);
  `uv.lock` captures the exact resolved commit sha so `uv sync --frozen` is byte-reproducible host-side]:**
  best-of-both — a human-readable tag in `pyproject.toml` for the promotion ledger + the exact sha
  locked in `uv.lock` for reproducibility. The host installs from the frozen lock; the tag is the
  promotion unit.
  - **ROADMAP-locked** (tag-pinned for deploy + reproducible `uv.lock`). The startup-version-log line
    (D-06) reports the resolved sha so deploys are auditable against the ledger.

### Local co-development override (PKG-02)
- **D-05 [chosen: the committed default is the deploy git pin; local co-dev uses an **uncommitted /
  env-gated editable path override** pointing at the sibling `../YahirReusableBot` checkout]:** day-to-day
  work edits both repos without a push→repin round-trip, but the override is **never committed**, so the
  deploy artifact always installs from the git pin — eliminating the "accidentally shipped a local path"
  failure class. The exact uv mechanism (a path `tool.uv.sources` override toggled via a local
  `uv.toml`/`UV_*` env vs an editable install layered over the pin vs another uv-sanctioned pattern) is a
  **primary research target** — pick the one uv documents as the canonical "git-pin-for-deploy,
  path-for-dev" workflow.
  - **Why not a uv workspace (rejected as default):** workspaces assume both packages share one tree;
    these are deliberately **separate repos**, so a path/source override is the right seam, not a
    workspace.

### Repin ritual + startup-version-log + promotion ledger (PKG-02 / SC#3, SC#4)
- **D-06 [chosen: a durable, documented commit→push→tag→`uv lock --upgrade-package`→deploy ritual; a
  startup-version-log line reporting the resolved module version + git sha; a promotion ledger doc
  tracking sha promotions]:** these are the **durable process artifacts** that make the two-repo deploy
  auditable. The startup-version-log line is what SC#3 verifies on the live host ("runs against the
  pinned module sha"); the ledger is the human record of which sha is promoted to deploy.
  - **Planner's discretion** on the **source of the sha at runtime** — `importlib.metadata` on the
    installed package + a build-embedded commit, vs reading the resolved sha from `uv.lock`, vs a uv/git
    introspection at startup. Shaped by what survives a clean-venv install and reports the *deployed*
    sha, not a dev value. Where the ritual + ledger docs live (module repo vs WeatherBot repo vs both) is
    planner's call — likely WeatherBot-side, since it owns the consume/deploy.

### EXTENSION-GUIDE + module GSD-project init (DOCS-01 / SC#4)
- **D-07 [chosen: `EXTENSION-GUIDE.md` at the `YahirReusableBot` repo root documenting each plug point
  with implemented-vs-deferred status; the module initialized as its own GSD project (`.planning/`)
  recording the durable-`JobStore` impl + a second `Channel` adapter as deferred extension points]:** the
  guide enumerates every documented seam — `JobStore` (Protocol; in-memory impl shipped, durable impl +
  its **serialization contract** deferred), command registration (registry/`bind`), config-schema
  extension (`validate`/`desired_jobs` hooks), `Channel` (one adapter shipped, 2nd deferred), panel
  `SelectedContext[I]`, health-check (READY-gate callback) — each marked implemented vs deferred. The
  module becomes its own GSD project so future bots (e.g. the reminder-bot litmus) extend it under
  proper planning discipline.
  - **Locked by DOCS-01.** The guide's plug points are exactly the injection seams established across
    Phases 22–27; the durable-`JobStore` serialization contract is the highest-value deferred entry.

### Live UAT (SC#2, SC#3 — Two-Gate UAT)
- **D-08 [chosen: Gate-1 self-UAT = clean-venv `uv sync --frozen` from the git pin + `weatherbot check`
  / `--help` + full suite + Phase-21 goldens byte-identical against the pinned module + `uv build
  --no-sources` leak gate; Gate-2 = the live `yahir-mint` `systemctl restart` restart UAT]:** the
  clean-venv install gate is the autonomous Gate-1 proof that the pinned artifact works off a fresh
  checkout (not just in the dev tree). The **live `yahir-mint` restart** (deploy → `sudo systemctl
  restart weatherbot` → startup-version-log announces the pinned sha → every panel button/dropdown still
  routes, correct default location) is the device-verifiable Gate-2 obligation. Per the live-service
  reality, the host runs an **editable install** and needs a restart to pick up the repin.
  - **The clone-path / custom_id / persistent-view re-bind invariants are byte-identical-critical** —
    the live panel was registered against `discord.py==2.7.1` and the frozen `wb:` `custom_id`s; the
    split must not perturb either, or the live panel throws "interaction failed." The Phase-21 goldens +
    the byte-string `custom_id` freeze test are the oracle; any non-empty diff is investigated, never
    rubber-stamped.

### Claude's Discretion
- **The exact uv "git-pin-for-deploy + path-for-dev" mechanism (D-05)** — the canonical uv pattern for
  toggling an editable path override over a committed git pin without leaking the path into the deploy
  artifact. **Primary research target.**
- **The runtime source of the module sha for the startup-version-log (D-06)** —
  `importlib.metadata` + build-embedded commit vs `uv.lock` read vs git/uv introspection; must report the
  *deployed* sha off a clean-venv install.
- **Whether to preserve module file history via `git subtree split`/`filter-repo` (D-01)** — only if
  trivially cheap; default is fresh-init clean import.
- **Where the repin-ritual + promotion-ledger docs live** (WeatherBot repo vs module repo vs both) and
  their exact format.
- **The mechanical pyproject details** of both repos post-split — the app's wheel collapsing to a single
  `weatherbot` package, the module's metadata/classifiers, dev-tooling duplication into the module's GSD
  project, and the shape of both `uv.lock`s.
- **How the live `yahir-mint` deploy is driven** (the existing editable-install + restart workflow) and
  the exact ordering of the repin → push → host-pull → `uv sync --frozen` → restart sequence.
- **The exact form of the `uv build --no-sources` leak gate** and how it integrates with the existing
  `grimp` import-hygiene + litmus gates as the standing "boundary is clean" proof, now across a repo
  boundary.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase & milestone contract
- `.planning/ROADMAP.md` § "Phase 28: Physical Repo Split + uv Git Dependency + EXTENSION-GUIDE" — the
  **pre-locked design** (own repo `YahirReusableBot`, import root `yahir_reusable_bot`, no console
  script; uv git dep tag-pinned for deploy + editable path override + reproducible `uv.lock` + `uv build
  --no-sources` leak gate; `discord.py==2.7.1` pin moves to the module; EXTENSION-GUIDE; module as its
  own GSD project; repin ritual + startup-version-log + promotion ledger; clean-venv install + live
  `yahir-mint` restart UAT) + the **4 locked success criteria** + the **Research flag: Yes** note
  ("consider `/gsd-plan-phase --research-phase 28`").
- `.planning/ROADMAP.md` § "v2.0 Bot Module Extraction" milestone header + phase spine ("split-last") —
  why the physical split is strictly last (every seam extracted + in-place boundary clean + suite/goldens
  green first); PKG-01 (clean in-place boundary) and BHV-01/BHV-02 (suite + goldens green) are the
  cross-cutting acceptances this phase inherits and re-runs across the new repo boundary.
- `.planning/REQUIREMENTS.md` § **PKG-02** (module extracted to `YahirReusableBot`, import root
  `yahir_reusable_bot`, no console script; uv git dep tag-pinned for deploy + editable path override +
  reproducible `uv.lock` + `uv build --no-sources` leak gate; clean-venv install + live `yahir-mint`
  restart UAT) and § **DOCS-01** (EXTENSION-GUIDE per plug point with implemented-vs-deferred status;
  module as its own GSD project recording durable-`JobStore` + 2nd `Channel` as deferred). Traceability:
  PKG-02 → Phase 28, DOCS-01 → Phase 28.
- `.planning/REQUIREMENTS.md` § "Future Requirements / Module extension points (designed in v2.0, built
  later)" — the deferred extension points the EXTENSION-GUIDE must enumerate (durable `JobStore` +
  serialization contract, 2nd `Channel` adapter), under the build-in-consumer-then-promote / rule-of-three
  discipline.

### Prior-phase contracts this phase must honor
- `.planning/phases/27-discord-adapter-panelkit-render-cycle-fix/27-CONTEXT.md` — **D-05** the exact
  `discord.py==2.7.1` pin now living in the Discord adapter package (moves to the module pyproject here),
  and the frozen `custom_id` / persistent-view-rebind / clone-path invariants the live-panel UAT (D-08)
  must preserve byte-identically across the split.
- `.planning/phases/25-lifecycle-ready-gate-composition-root/25-CONTEXT.md` — **D-04** the single
  app-side `weatherbot/scheduler/wiring.py build_runtime(...)` composition root that stays app-side and
  is the only place the module is assembled (the stable public-name boundary the `weatherbot` console
  entry crosses through).
- `.planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-CONTEXT.md` — the
  **flat-sibling `yahir_reusable_bot/` layout**, the Ports & Adapters / DI template, and the
  `grimp`-in-pytest import gate + isolated-import smoke + signatures-only litmus (the basis for the
  cross-repo leak gate + the `uv build --no-sources` proof).
- `.planning/phases/21-characterization-golden-test-harness/21-CONTEXT.md` + `21-PATTERNS.md` — the
  byte-identical golden oracle (embeds, CLI stdout/exit, schedule plan, DB rows, `custom_id` byte
  snapshots, exception-identity) re-run from the consuming app **against the pinned module** as the SC#1
  acceptance; the discipline rule (any non-empty snapshot diff is a failure to investigate, never
  rubber-stamped). **Note:** the suite prints "2 snapshots failed" but exits 0 — pre-existing syrupy
  noise, trust the exit code + `.ambr` diff.

### Source surfaces this phase moves / touches
- `yahir_reusable_bot/**` — the entire flat-sibling tree (`channels/`, `config/`, `discord/`,
  `lifecycle/`, `ports/`, `registry/`, `reliability/`, `scheduler/`) that `git`-moves to the new repo;
  third-party imports are only `discord`, `httpx`, `structlog`, `tenacity` (+ stdlib). **Scrub the two
  stale `weatherbot.*` references** in `yahir_reusable_bot/channels/__init__.py` (docstring) and
  `yahir_reusable_bot/ports/alerts.py` (docstring) during the move — they are comments, not imports, but
  should not ride into the standalone repo.
- `pyproject.toml` — the consuming app's project file: remove `yahir_reusable_bot` from
  `[tool.hatch.build.targets.wheel] packages` (collapse to single `weatherbot` package), **remove the
  `discord.py==2.7.1` line** (the comment already flags it as moving to the module, SEAM-07 D-05), **add**
  `yahir-reusable-bot` to `dependencies` + a `[tool.uv.sources]` git pin, keep `[project.scripts]
  weatherbot = "weatherbot.cli:main"`, and keep `[tool.coverage]` covering the now-external module only
  where it still applies app-side. The new `YahirReusableBot/pyproject.toml` mirrors hatchling + declares
  `discord.py==2.7.1` + `httpx` + `structlog` + `tenacity`.
- `uv.lock` — regenerated both sides; the app's lock captures the resolved module commit sha
  (reproducible `uv sync --frozen`).
- `tests/test_import_hygiene.py` — the mature 3-gate APP-02 litmus (`grimp` graph + isolated-import + AST
  noun scan, D-13-locked term set `weather|forecast|location|openweather|\buv\b|briefing`) — re-run
  across the repo boundary; extend/relocate as needed so the clean-cut proof survives the split, and pair
  with the new `uv build --no-sources` leak gate.
- `weatherbot/cli.py` (`main`) + `weatherbot/scheduler/wiring.py` (`build_runtime`) — the stable public
  boundary the app crosses into the module through; verified by `weatherbot check` / `--help` post-split.

### Tooling docs (for the planner — research targets)
- `uv` — git dependencies (`[tool.uv.sources]` git, `tag`/`rev` pinning), editable/path source overrides
  for local dev, `uv sync --frozen`, `uv lock --upgrade-package`, `uv build --no-sources` —
  https://docs.astral.sh/uv/concepts/projects/dependencies/ and https://docs.astral.sh/uv/concepts/projects/sync/
- `hatchling` build backend (wheel `packages`, metadata) — https://hatch.pypa.io/latest/config/build/
- `importlib.metadata` (runtime package version/sha for the startup-version-log) —
  https://docs.python.org/3/library/importlib.metadata.html
- `git subtree split` / `git filter-repo` (only if D-01 history-preservation is chosen) —
  https://git-scm.com/docs/git-subtree

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `yahir_reusable_bot/**` — already a complete, import-clean flat-sibling package (Phases 22–27); the
  split is a **physical move**, not a refactor. Its third-party surface is just `discord`, `httpx`,
  `structlog`, `tenacity`.
- `pyproject.toml` — already a two-package wheel (`packages = ["weatherbot", "yahir_reusable_bot"]`) with
  the `discord.py==2.7.1` exact pin **already commented as moving to the module at Phase 28** — the split
  destination is pre-marked.
- `tests/test_import_hygiene.py` + the `grimp` dev-dep — the standing clean-boundary proof to carry across
  the repo boundary and pair with `uv build --no-sources`.
- The Phase-21 golden suite (embeds/CLI/schedule/DB-rows/`custom_id`/exception-identity) — the
  byte-identical oracle, re-run from the consuming app against the pinned module.

### Established Patterns
- **App injects all WeatherBot specifics into generic module mechanisms at one composition root**
  (`wiring.py build_runtime`, Phase-25 D-04) — the only crossing point; the split must keep it the stable
  public-name boundary.
- **Litmus is a negative grep over `yahir_reusable_bot/**`; the D-13-locked term set stays
  weather-specific and is NOT broadened** — now enforced across a repo boundary plus the wheel leak gate.
- **Byte-identical-or-fail discipline** — the Phase-21 goldens are re-run after the split exactly as after
  every seam phase; the suite's "2 snapshots failed / exit 0" is known syrupy noise (trust exit code).

### Integration Points
- WeatherBot → module: `weatherbot/cli.py main` + `weatherbot/scheduler/wiring.py build_runtime` cross
  into `yahir_reusable_bot` through stable public names only; post-split this crossing resolves through
  the installed git-pinned wheel.
- Deploy: the live `yahir-mint` systemd `weatherbot` service (editable install) — the repin lands via
  push → host pull → `uv sync --frozen` → `sudo systemctl restart weatherbot`, with the startup-version-log
  line announcing the deployed sha and the already-pinned live panel re-binding its persistent views.

</code_context>

<specifics>
## Specific Ideas

- **The split is physical, not logical** — the in-place boundary did all the un-braiding (Phases 22–27);
  Phase 28 is `git`-move + re-point + docs + UAT. No module *logic* changes beyond scrubbing two stale
  `weatherbot.*` docstring references.
- **`discord.py==2.7.1` moves to the module's pyproject** — the pin's destination is already marked in
  the app pyproject comment; WeatherBot inherits it transitively. The live panel was registered against
  this exact version — do not loosen it, or the live panel throws "interaction failed."
- **Git pin for deploy, editable path for dev, never leak the path** — the committed default is the tag
  pin; the local path override is uncommitted, so the deploy artifact always installs from the pin.
- **The clean-venv `uv sync --frozen` gate is what makes the host trustworthy** — it proves the pinned
  artifact works off a fresh checkout, not just in the dev tree (the "works locally → works on host"
  conversion).
- **The live `yahir-mint` restart is the real acceptance** — startup-version-log announces the pinned
  sha; every panel button/dropdown must still route (custom_id contract + persistent-view re-bind);
  correct default location. The host runs an editable install and needs the restart to pick up the repin.
- **The module becomes its own GSD project** — its `.planning/` records durable-`JobStore` (+ its
  serialization contract) and a 2nd `Channel` adapter as deferred extension points, ready for the
  reminder-bot litmus under build-in-consumer-then-promote / rule-of-three.

</specifics>

<deferred>
## Deferred Ideas

- **Durable/dynamic `JobStore` implementation** (+ its serialization contract) — designed-but-deferred
  v2.0 extension point; this phase only *documents* it in the EXTENSION-GUIDE and records it in the
  module's GSD project. Build it in a consumer first, then promote (rule of three).
- **Second `Channel` adapter** (Telegram/SMS/Slack) — designed-but-deferred extension point; documented +
  recorded, not built here.
- **Publishing `yahir-reusable-bot` to PyPI / a private index** — out of scope; the git dependency is the
  v2.0 distribution mechanism. Revisit only if a second consumer wants versioned releases.
- **History-preserving repo split (`git subtree split`/`filter-repo`)** — default is a clean fresh-init
  import commit (D-01); a history-preserving split is an option only if trivially cheap, since the
  extraction history is already durable in the WeatherBot repo.
- **Slash-command / non-text adapter, weather-pattern analysis** — explicitly out of the v2.0 extraction
  milestone.

None of these are scope creep — they are extension points consciously deferred per the v2.0
build-in-consumer-then-promote discipline, or distribution choices beyond the milestone.

</deferred>

---

*Phase: 28-physical-repo-split-uv-git-dependency-extension-guide*
*Context gathered: 2026-06-29*
