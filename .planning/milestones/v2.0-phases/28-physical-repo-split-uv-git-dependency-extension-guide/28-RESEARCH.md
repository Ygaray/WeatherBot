# Phase 28: Physical Repo Split + uv Git Dependency + EXTENSION-GUIDE - Research

**Researched:** 2026-06-29
**Domain:** Python packaging (uv git dependencies, hatchling), repo extraction (git), runtime version introspection (PEP 610 / importlib.metadata), systemd deploy/UAT
**Confidence:** HIGH (uv/git/packaging mechanics verified against official docs + the live venv; one MEDIUM area — the dev-override pattern, where uv has no shipped first-class feature)

## Summary

Phase 28 is a **physical relocation + re-point + docs** phase, not a refactor. Phases 22–27 already
un-braided the module in place: `yahir_reusable_bot/**` imports zero app code (grimp-clean), its only
third-party imports are `discord`, `httpx`, `structlog`, `tenacity` (grep-confirmed this session), and
the Phase-21 goldens are the byte-identical oracle. The work is: `git mv` the clean tree to a fresh
`YahirReusableBot` repo, re-point WeatherBot at it via a uv git dependency, ship the EXTENSION-GUIDE,
and prove it all still runs on the live `yahir-mint` host.

The single highest-risk surface is the **dev-vs-deploy source mechanism (D-05)**. uv's documented model
is: a committed `[tool.uv.sources]` git pin is the deploy default, `uv.lock` captures the resolved
commit sha, and `uv sync --frozen` reproduces it byte-for-byte on a clean host. The "edit both repos
locally without a push→repin round-trip" override has **no shipped first-class uv feature** — the
`UV_SOURCES` env var is an open feature request (#15895, not shipped), and `sources` cannot live in a
gitignored `uv.toml`. The canonical, leak-proof pattern is therefore: keep the committed git pin
untouched and overlay a local editable install (`uv pip install -e ../YahirReusableBot`) into the venv
for co-dev, reverting with `uv sync` — so the *committed* artifact always installs from the pin. The
`uv build --no-sources` gate is what proves no path ever leaked into the wheel.

The runtime "which sha is deployed" question (D-06) has a clean answer that survives a clean-venv git
install: PEP 610 `direct_url.json` (written into the installed dist-info) carries
`vcs_info.commit_id` — the exact resolved sha — readable via `importlib.metadata`. An editable install
instead writes `dir_info.editable=true`, which *distinguishes a dev tree from a real deploy* for free.

**Primary recommendation:** Do the split as a fresh `git init` + single clean import commit (D-01).
Commit the git **tag** pin in `pyproject.toml`; let `uv.lock` hold the sha; gate the phase on a
clean-venv `uv sync --frozen` + full suite + Phase-21 goldens + `uv build --no-sources` (Gate-1,
autonomous), then the live `yahir-mint` `systemctl restart` (Gate-2, deferred). Read the deployed sha
at startup from `direct_url.json` via `importlib.metadata`. Never loosen `discord.py==2.7.1` or the
`wb:` custom_ids — they are the live-panel wire contract.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Repo creation + history:** fresh `git init` in `YahirReusableBot` with a single clean import
  commit; the WeatherBot repo retains the full Phase 22–27 extraction history. (Planner discretion to use
  a history-preserving `git subtree split`/`filter-repo` *only* if trivially cheap; default is fresh-init.)
- **D-02 — Module package identity:** PyPI-normalized name `yahir-reusable-bot`, import root
  `yahir_reusable_bot`, **NO `[project.scripts]` console script**, `hatchling` build backend,
  `requires-python >=3.12`, version `0.1.0`. The module's `[tool.hatch.build.targets.wheel] packages`
  lists just `yahir_reusable_bot`. The app's two-package wheel collapses to a single `weatherbot` package.
- **D-03 — Dependency partition:** the module's pyproject declares exactly its imported deps —
  `discord.py==2.7.1`, `httpx`, `structlog`, `tenacity`; the exact `discord.py` pin **moves out of the app
  pyproject into the module's**. WeatherBot keeps its app-only deps + gains `yahir-reusable-bot` (which
  transitively pins discord.py). grimp gate + `uv build --no-sources` leak gate together prove the cut.
- **D-04 — uv git dep + pin granularity:** `[tool.uv.sources]` git entry **tag-pinned** for deploy
  (e.g. `tag = "v0.1.0"`); `uv.lock` captures the exact resolved commit sha so `uv sync --frozen` is
  byte-reproducible host-side. The tag is the promotion unit; the sha is the reproducibility anchor.
- **D-05 — Local co-dev override:** committed default is the deploy git pin; local co-dev uses an
  **uncommitted / env-gated editable path override** pointing at the sibling `../YahirReusableBot`
  checkout. The override is **never committed**, so the deploy artifact always installs from the pin. The
  exact uv mechanism is a **primary research target** (see Architecture Patterns below). NOT a workspace.
- **D-06 — Repin ritual + startup-version-log + promotion ledger:** a durable, documented
  commit→push→tag→`uv lock --upgrade-package`→deploy ritual; a startup-version-log line reporting the
  resolved module version + git sha; a promotion ledger doc tracking sha promotions. (Planner discretion
  on the runtime sha source and where the ritual/ledger docs live — likely WeatherBot-side.)
- **D-07 — EXTENSION-GUIDE + module GSD-project init:** `EXTENSION-GUIDE.md` at the `YahirReusableBot`
  repo root documenting each plug point (`JobStore`, command registration, config-schema extension,
  `Channel`, panel `SelectedContext`, health-check) with implemented-vs-deferred status; the module
  initialized as its own GSD project (`.planning/`) recording durable-`JobStore` (+ serialization
  contract) and a 2nd `Channel` adapter as deferred extension points.
- **D-08 — Live UAT (Two-Gate):** Gate-1 self-UAT = clean-venv `uv sync --frozen` from the git pin +
  `weatherbot check` / `--help` + full suite + Phase-21 goldens byte-identical against the pinned module +
  `uv build --no-sources` leak gate. Gate-2 = the live `yahir-mint` `systemctl restart` UAT. The
  clone-path / custom_id / persistent-view re-bind invariants are byte-identical-critical.

### Claude's Discretion

- The exact uv "git-pin-for-deploy + path-for-dev" mechanism (D-05) — **PRIMARY research target.**
- The runtime source of the module sha for the startup-version-log (D-06).
- Whether to preserve module file history via `git subtree split`/`filter-repo` (D-01) — only if trivially cheap.
- Where the repin-ritual + promotion-ledger docs live (WeatherBot vs module vs both) and their format.
- The mechanical pyproject details of both repos post-split (app wheel collapse, module metadata,
  dev-tooling duplication, both `uv.lock` shapes).
- How the live `yahir-mint` deploy is driven and the exact repin→push→host-pull→`uv sync --frozen`→restart ordering.
- The exact form of the `uv build --no-sources` leak gate and its integration with the grimp/litmus gates across the repo boundary.

### Deferred Ideas (OUT OF SCOPE)

- Durable/dynamic `JobStore` implementation (+ serialization contract) — only *documented* here.
- Second `Channel` adapter (Telegram/SMS/Slack) — documented + recorded, not built.
- Publishing `yahir-reusable-bot` to PyPI / a private index — git dependency is the v2.0 distribution mechanism.
- History-preserving repo split — default is clean fresh-init (extraction history is durable in WeatherBot).
- Slash-command / non-text adapter, weather-pattern analysis — out of the v2.0 extraction milestone.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PKG-02 | Module extracted to its own repo `YahirReusableBot` (import root `yahir_reusable_bot`, no console script); WeatherBot depends via a uv git dependency tag-pinned for deploy + editable path override for dev + reproducible `uv.lock` + `uv build --no-sources` leak gate; clean-venv install + live `yahir-mint` restart UAT. | Standard Stack (uv git source syntax, hatchling); Architecture Patterns 1–4 (git pin, dev override, leak gate, two-repo pyproject mechanics); Common Pitfalls 1–7; Code Examples (pyproject for both repos, lock/sync commands). |
| DOCS-01 | Module ships an `EXTENSION-GUIDE` per plug point with implemented-vs-deferred status; module initialized as its own GSD project recording durable-`JobStore` + 2nd `Channel` as deferred. | Architecture Pattern 6 (EXTENSION-GUIDE structure + the six plug points enumerated from Phases 22–27); the deferred extension-point list from REQUIREMENTS.md Future section. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reusable bot mechanism (Channel, scheduler, config-reload, lifecycle, registry, Discord adapter) | Module repo `YahirReusableBot` (library) | — | Generic, weather-free core; ships as a library with no console script (D-02). |
| Weather specifics + composition + `weatherbot` console entry | App repo `WeatherBot` | — | All app injection stays at `weatherbot/scheduler/wiring.py build_runtime(...)` (Phase-25 D-04); the only console script. |
| Dependency resolution / pin / lock | App `pyproject.toml` + `uv.lock` | uv tooling | The consuming app owns the git pin + frozen lock; the module declares only its own runtime deps. |
| `discord.py==2.7.1` exact pin (live-panel wire contract) | Module `pyproject.toml` | — | Moves out of the app; WeatherBot inherits it transitively (D-03). |
| Build-leak / boundary verification | App + module test suites | uv build --no-sources, grimp | grimp proves import-graph cleanliness; `--no-sources` proves the wheel resolves without path leakage. |
| Runtime deployed-sha reporting | App startup (`weatherbot/cli.py`) | importlib.metadata / direct_url.json | The app reads the installed module's PEP 610 record and logs it (D-06). |
| Deploy / restart / live-panel re-bind | systemd on `yahir-mint` (host) | — | Editable install + `systemctl restart` picks up the repin; Gate-2 obligation (D-08). |

## Standard Stack

### Core
| Library / Tool | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| uv | 0.11.19 (installed, verified this session) | Git dependency, lock, sync, build-no-sources gate | The project's locked packaging tool (CLAUDE.md). `[tool.uv.sources]` git pin + `uv.lock` sha + `uv sync --frozen` is the documented reproducible-install path. [CITED: docs.astral.sh/uv/concepts/projects/dependencies] |
| hatchling | (build-system requires, already in use) | Build backend for both repos | Mirrors WeatherBot's existing toolchain so the split is mechanical (D-02). [VERIFIED: pyproject.toml] |
| git | 2.43.0 (verified this session) | `git init` fresh module repo; `git mv` the clean tree | Fresh-init + clean import commit is D-01's chosen path. |
| importlib.metadata | stdlib (Python 3.12) | Read installed module version + PEP 610 `direct_url.json` for the deployed sha | Survives a clean-venv git install; reports the *deployed* sha, not a dev value (D-06). [CITED: docs.python.org/3/library/importlib.metadata] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| grimp | >=3.14 (dev-dep, in use) | Import-graph hygiene gate, now across the repo boundary | Re-run in BOTH repos; the module's own suite proves it imports zero `weatherbot`; the app's suite no longer needs the cross-package build (the boundary is now a package boundary). [VERIFIED: pyproject.toml] |
| pytest / pytest-cov / syrupy / time-machine / ruff | as locked | Test + golden oracle + lint, duplicated into the module's own GSD project | The module ships its own test/hygiene suite as a GSD project (D-07 / D-03 planner discretion). [VERIFIED: pyproject.toml] |
| hatch-vcs | (optional, NOT recommended for v1) | Build-time git-tag → version embedding | Only if a build-embedded version string is wanted. Unnecessary: a clean `v0.1.0` tag + `direct_url.json` already reports the deployed sha. [CITED: pypi.org/project/hatch-vcs] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Fresh `git init` (D-01) | `git filter-repo` / `git subtree split` | History-preserving but more machinery for a single-dev module whose history is already durable in WeatherBot. Default fresh-init unless trivially cheap. |
| `direct_url.json` for the deployed sha | `uv.lock` read at runtime / `hatch-vcs` embedded version | `uv.lock` isn't shipped inside the installed package (not reliable at runtime on host); hatch-vcs needs a build plugin + a git checkout at build time. `direct_url.json` is written by the install itself and is always present. |
| uncommitted editable overlay (D-05) | uv workspace | Workspaces assume one shared tree; these are deliberately two repos — wrong seam (locked rejection). |
| git tag pin | git `rev` (sha) pin | Tag is human-readable for the promotion ledger; `uv.lock` already holds the sha for reproducibility — best of both (D-04). |

**Installation (no NEW external packages are introduced):** the module's deps (`discord.py==2.7.1`,
`httpx`, `structlog`, `tenacity`) are **already installed and running in production** — Phase 28 only
*relocates the declarations*. No package is being added to the system for the first time.

**Version verification (this session):**
- `uv --version` → **0.11.19** [VERIFIED]
- `python3 --version` → **3.12.3** [VERIFIED]
- `git --version` → **2.43.0** [VERIFIED]
- Module third-party imports (grep of `yahir_reusable_bot/`): `discord`, `httpx`, `structlog`,
  `tenacity` only — no pydantic/apscheduler/cachetools/watchfiles [VERIFIED: grep this session]

## Package Legitimacy Audit

> The four "packages" the module declares are pre-existing production dependencies being **relocated**,
> not newly installed. No package is added to the system for the first time in this phase.

| Package | Registry | Verdict (seam) | True status | Disposition |
|---------|----------|----------------|-------------|-------------|
| `discord.py==2.7.1` | PyPI | SUS (unknown-downloads, no-repository) | False-positive: the seam's SUS is driven by PyPI not exposing download counts + a missing repo-URL field. This is the canonical discord.py, **already running in production** and the version the live panel was registered against. | Keep, EXACT pin (do not loosen) — moves to module pyproject. |
| `httpx` | PyPI | SUS (unknown-downloads) | False-positive: established package (repo github.com/encode/httpx), already in production. | Keep, range pin in module. |
| `structlog` | PyPI | SUS (unknown-downloads) | False-positive: established, already in production. | Keep, range pin in module. |
| `tenacity` | PyPI | (SUS — same metadata-gap pattern) | False-positive: established, already in production. | Keep, range pin in module. |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none requiring a checkpoint — all four are pre-existing
production deps; the seam's SUS verdict is a known PyPI-metadata-gap false-positive (no weekly-download
API + missing repo-URL field), not a slopsquat signal. The planner does **not** need a
`checkpoint:human-verify` install task — these are relocations of running code, and the clean-venv
`uv sync --frozen` install gate (D-08) + the existing live-panel UAT are the real proof.

## Architecture Patterns

### System Architecture Diagram

```
  ┌─────────────────────────── BEFORE (one repo, two-package wheel) ──────────────────────────┐
  │  WeatherBot repo                                                                            │
  │    pyproject.toml  packages = ["weatherbot", "yahir_reusable_bot"]                          │
  │    discord.py==2.7.1 pinned app-side                                                        │
  │    weatherbot/  ──build_runtime()──▶  yahir_reusable_bot/   (in-tree import)                │
  └────────────────────────────────────────────────────────────────────────────────────────────┘
                                          │  git mv + re-point
                                          ▼
  ┌──────────────── AFTER (two repos, uv git dependency) ───────────────────────────────────────┐
  │                                                                                              │
  │  YahirReusableBot repo (fresh git init, D-01)        WeatherBot repo                          │
  │    pyproject.toml                                      pyproject.toml                          │
  │      name = yahir-reusable-bot                           packages = ["weatherbot"]  (collapsed)│
  │      packages = ["yahir_reusable_bot"]                   dependencies += yahir-reusable-bot     │
  │      deps: discord.py==2.7.1, httpx,                     [tool.uv.sources]                      │
  │            structlog, tenacity                            yahir-reusable-bot =                  │
  │      NO [project.scripts]                                   { git=..., tag="v0.1.0" }           │
  │      EXTENSION-GUIDE.md + .planning/ (own GSD)           [project.scripts] weatherbot=...       │
  │      grimp/litmus suite (imports zero app)              uv.lock  ← resolved module SHA          │
  │                  ▲                                                                              │
  │   tag v0.1.0  ───┘                          weatherbot/cli.py main                              │
  │   (promotion unit; sha in app's uv.lock)      └─ build_runtime() ─▶ installed yahir_reusable_bot │
  │                                               └─ startup-version-log: reads direct_url.json sha  │
  └──────────────────────────────────────────────────────────────────────────────────────────────┘
                                          │  deploy
                                          ▼
  ┌──────────── DEPLOY (host yahir-mint, editable install under systemd) ───────────────────────┐
  │   git pull → uv sync --frozen (installs module from pinned sha) → systemctl restart weatherbot│
  │     → startup-version-log announces the deployed sha                                          │
  │     → persistent-view re-bind: every wb: custom_id still routes on the live pinned panel       │
  └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure (post-split)
```
WeatherBot/                        # consuming app repo (unchanged location)
├── pyproject.toml                 # packages=["weatherbot"]; +yahir-reusable-bot dep; [tool.uv.sources] git pin
├── uv.lock                        # captures the resolved module commit sha
├── weatherbot/                    # app package (+ cli.py startup-version-log line)
├── tests/                         # app suite + Phase-21 goldens (re-run against the pinned module)
├── deploy/                        # systemd unit + README (repin ritual + promotion ledger likely here)
└── .planning/                     # WeatherBot's GSD project

../YahirReusableBot/               # NEW sibling repo (fresh git init)
├── pyproject.toml                 # name=yahir-reusable-bot; packages=["yahir_reusable_bot"]; NO scripts
├── uv.lock                        # module's own lock
├── yahir_reusable_bot/            # the git-mv'd clean tree (docstrings scrubbed)
├── tests/                         # the relocated grimp/litmus/import-hygiene suite
├── EXTENSION-GUIDE.md             # DOCS-01 plug-point doc
└── .planning/                     # module's own GSD project (records deferred JobStore/Channel)
```

### Pattern 1: uv git dependency, tag-pinned for deploy (D-04)
**What:** Commit a human-readable tag pin in `pyproject.toml`; let `uv.lock` hold the resolved sha.
**When to use:** The committed deploy default.
```toml
# WeatherBot/pyproject.toml
[project]
dependencies = [
    # ... app-only deps (apscheduler, cachetools, discord-webhook, pydantic, ...) ...
    "yahir-reusable-bot",          # NOTE: discord.py==2.7.1 is gone — inherited transitively
]

[tool.uv.sources]
yahir-reusable-bot = { git = "https://github.com/<owner>/YahirReusableBot", tag = "v0.1.0" }
```
- `uv lock` resolves `tag = "v0.1.0"` to its commit sha and records it in `uv.lock`.
- `uv sync --frozen` installs **exactly** from `uv.lock` with no re-resolution — byte-reproducible on a
  clean host. [CITED: docs.astral.sh/uv/concepts/projects/sync]
- Repin command: `uv lock --upgrade-package yahir-reusable-bot` re-resolves only that package to the
  tag's current sha (after the module repo pushes a new tag). [CITED: docs.astral.sh/uv/concepts/projects/sync]

### Pattern 2: Local co-development override — the leak-proof seam (D-05, PRIMARY TARGET)
**What:** Edit both repos locally without a push→repin round-trip, WITHOUT the path ever reaching the
committed deploy artifact.
**Key finding (MEDIUM confidence — uv has no shipped first-class feature for this):**
- `UV_SOURCES` env-var override is an **OPEN feature request (#15895), NOT shipped** in 0.11.x.
  [CITED: github.com/astral-sh/uv/issues/15895]
- `sources` **cannot** live in a gitignored `uv.toml` — `[tool.uv.sources]` is only honored in
  `pyproject.toml`. So a "separate gitignored override file" is not available either. [CITED: uv docs]

**Recommended mechanism (cleanest, never touches a committed file): an editable venv overlay.**
```bash
# Day-to-day co-dev: overlay the sibling checkout as an editable install into the existing venv.
uv pip install -e ../YahirReusableBot
# ...edit both repos freely; the import resolves to the sibling working tree...
# Return to the pinned deploy state at any time (re-installs the module from uv.lock's sha):
uv sync --frozen
```
This never edits `pyproject.toml`/`uv.lock`, so the committed artifact is *always* the git pin — the
"accidentally shipped a local path" failure class is structurally eliminated.

**Alternative mechanism (if a pyproject-level toggle is preferred): an uncommitted source edit.**
```toml
# UNCOMMITTED local edit (revert before commit; consider a git pre-commit guard, see Pitfall 1):
[tool.uv.sources]
yahir-reusable-bot = { path = "../YahirReusableBot", editable = true }
```
Riskier (it *does* touch a committed file), so pair it with a guard (Pitfall 1). **Recommend the venv
overlay** as the default; document the uncommitted-edit form as the fallback.

### Pattern 3: The `uv build --no-sources` leak gate (D-03 / SC#2)
**What:** Build the wheel with `[tool.uv.sources]` ignored, simulating how another build tool / an
end-user install sees the package — proving the package resolves from its **published metadata** with no
path/source leakage.
```bash
# In WeatherBot: prove the app wheel doesn't depend on a path source for the module.
uv build --no-sources
# Failure looks like: a resolution error / "no source" for yahir-reusable-bot if a path source
# had leaked into the committed pyproject (e.g. a forgotten Pattern-2 edit).
```
[CITED: docs.astral.sh/uv/concepts/projects/dependencies — "run `uv build --no-sources` to ensure the
package builds correctly when `tool.uv.sources` is disabled"]

**Composition with the grimp/litmus gates across the repo boundary:**
- **In the module repo:** the relocated `tests/test_import_hygiene.py` runs `grimp.build_graph(MODULE)`
  and proves `yahir_reusable_bot` imports zero `weatherbot` — but note: post-split the `weatherbot`
  package is no longer in the module repo, so the **two-package build idiom and the self-proofs that
  inject a `weatherbot` leak must be revisited** (see Pitfall 6). The litmus AST noun-scan and the
  isolated-import smoke carry over unchanged.
- **`--no-sources`** is the *new* gate: grimp proves the import graph; `--no-sources` proves the
  *dependency/build* graph carries no path leak. They are complementary — keep both.
- **Dependency-partition proof:** `grep -rhoE '^(import|from) (discord|httpx|structlog|tenacity|...)' yahir_reusable_bot/`
  confirms the module imports exactly its four declared third-party deps (done this session: only
  `discord`, `httpx`, `structlog`, `tenacity`). The clean-venv `uv sync --frozen` install + full suite is
  the proof that no app dep was orphaned (a missing module dep would fail import at install/test time).

### Pattern 4: Runtime deployed-sha for the startup-version-log (D-06)
**What:** Log the *deployed* module sha at startup, auditable against the promotion ledger.
**Mechanism — PEP 610 `direct_url.json`** (written into the installed dist-info by the git install):
```python
# weatherbot/cli.py — near the existing _log.info startup line
import json
from importlib.metadata import Distribution, version

def _module_provenance() -> dict[str, str]:
    dist = Distribution.from_name("yahir-reusable-bot")
    raw = dist.read_text("direct_url.json")  # PEP 610; present for git/path installs
    info = json.loads(raw) if raw else {}
    vcs = info.get("vcs_info", {})
    return {
        "module_version": version("yahir-reusable-bot"),
        "module_sha": vcs.get("commit_id", ""),            # exact resolved sha (deploy)
        "module_ref": vcs.get("requested_revision", ""),   # the tag, e.g. v0.1.0
        "editable": str(info.get("dir_info", {}).get("editable", False)),  # True ⇒ a DEV tree, not a deploy
    }

_log.info("module provenance", **_module_provenance())
```
- A **git install** writes `vcs_info.commit_id` = the exact sha and `requested_revision` = the tag —
  this is the deployed value off a clean-venv `uv sync --frozen`. [VERIFIED: PEP 610 + the live venv's
  `direct_url.json` confirms the format this session — the current editable install shows
  `{"url":"file://.../WeatherBot","dir_info":{"editable":true}}`, proving the editable-vs-git distinction works.]
- The `editable: true` flag is a free **"you're running a dev tree, not the pinned deploy" tripwire** —
  the startup log will visibly differ between a co-dev overlay and a real host deploy.
- **Why not `uv.lock` at runtime:** `uv.lock` is not shipped inside the installed package, so reading it
  on the host is fragile. **Why not hatch-vcs:** needs a build plugin + a git checkout at build time; a
  clean `v0.1.0` tag already yields a clean version, and `direct_url.json` already has the sha.

### Pattern 5: Two-package-wheel → two-repo pyproject mechanics (D-02 / D-03)
**WeatherBot `pyproject.toml` edits:**
1. `[tool.hatch.build.targets.wheel] packages = ["weatherbot", "yahir_reusable_bot"]` → `["weatherbot"]`
   (collapse to single package — **the comment warns hatchling silently drops a package if mis-set;
   verify the built wheel contains exactly `weatherbot/`**, Pitfall 7).
2. Remove the `discord.py==2.7.1` line from `dependencies` (the inline comment already flags it as the
   Phase-28 destination); add `"yahir-reusable-bot"`.
3. Add `[tool.uv.sources] yahir-reusable-bot = { git = ..., tag = "v0.1.0" }`.
4. Keep `[project.scripts] weatherbot = "weatherbot.cli:main"` (the only console script).
5. `[tool.coverage.run] source` currently lists `yahir_reusable_bot` — **remove it** (the module is now
   external; coverage stays app-side only, Pitfall 5).
**New `YahirReusableBot/pyproject.toml`:** `name = "yahir-reusable-bot"`, `version = "0.1.0"`,
`requires-python = ">=3.12"`, `dependencies = ["discord.py==2.7.1", "httpx>=0.28.1", "structlog>=26.1.0",
"tenacity>=9.1.4"]`, `[build-system] hatchling`, `[tool.hatch.build.targets.wheel] packages = ["yahir_reusable_bot"]`,
**NO `[project.scripts]`**, its own `[dependency-groups] dev` (pytest/grimp/ruff/syrupy/time-machine —
planner discretion on duplication, D-03).

### Pattern 6: EXTENSION-GUIDE structure (DOCS-01 / D-07)
The guide enumerates exactly the six injection seams established across Phases 22–27, each marked
implemented-vs-deferred:

| Plug point | Seam (from) | Implemented? | Deferred entry |
|------------|-------------|-------------|----------------|
| `Channel` | SEAM-01 (Phase 22) | ✅ one adapter (Discord-side delivery) | 2nd adapter (Telegram/SMS/Slack) deferred |
| `JobStore` Protocol | SEAM-03 (Phase 23) | ✅ in-memory / config-rederive impl | **durable impl + its serialization contract** — highest-value deferred entry |
| Config-schema extension (`validate`/`desired_jobs` hooks) | SEAM-04 (Phase 24) | ✅ injected over an app-defined schema | — |
| Health-check (READY-gate callback) | SEAM-05 (Phase 25) | ✅ app-provided callback | — |
| Command registration (registry/`bind`) | SEAM-06 (Phase 26) | ✅ app registers; CLI/Discord/help derive | — |
| Panel `SelectedContext[I]` | SEAM-07 (Phase 27) | ✅ generic holder + injected `render` | — |

The module's own `.planning/` (GSD project init) records the durable-`JobStore` impl and the 2nd
`Channel` adapter as deferred extension points under build-in-consumer-then-promote / rule-of-three.

### Anti-Patterns to Avoid
- **Loosening `discord.py` to a range:** the live panel registered persistent views against `==2.7.1`;
  a different resolved version can break custom_id routing → "interaction failed." Keep the EXACT pin.
- **Re-namespacing the `wb:` custom_ids:** they are a frozen wire contract; changing them kills the live
  pinned panel (a `!panel` re-summon migration would be required — out of scope here).
- **Using a uv workspace for the two repos:** workspaces assume a shared tree (locked rejection, D-05).
- **Committing the dev path override:** the entire D-05 design exists to prevent this.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reproducible install of a git-pinned dep | A custom "git clone + pip install" script | `[tool.uv.sources]` git pin + `uv.lock` + `uv sync --frozen` | uv resolves the tag→sha once and freezes it; `--frozen` reinstalls byte-identically with no re-resolve. |
| Reading the deployed commit sha at runtime | Shelling out to `git rev-parse` (no git checkout on host) or parsing `uv.lock` | `importlib.metadata` + PEP 610 `direct_url.json` | The install itself writes the resolved sha into dist-info; always present, no git/uv at runtime. |
| Proving the wheel carries no path leak | A custom wheel-introspection script | `uv build --no-sources` | Purpose-built to simulate a no-sources build; the documented publishing gate. |
| Detecting a leaked dev-path before commit | Manual diff review | A git pre-commit hook grepping for `path =` under `[tool.uv.sources]` (Pitfall 1) | Mechanical, can't be forgotten. |

**Key insight:** every "works locally, breaks on host" failure in this phase reduces to *the dev
environment diverging from the committed artifact*. uv's frozen lock + `--no-sources` + `direct_url.json`
together make that divergence detectable and prevent it from shipping — don't reinvent any of them.

## Runtime State Inventory

> This is a rename/relocation-adjacent phase (a module moves repos and the live panel must keep routing).
> The grep audit finds files; this inventory covers what a grep misses.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | SQLite store (`data/weatherbot.db`) stays app-side, untouched — the module move does not touch any datastore. The persisted DB rows are pinned by the Phase-21 DB-row golden, re-run post-split as the oracle. | None (verified: module imports no SQLite/store code; store stays in `weatherbot/weather/`). |
| Live service config | The **live Discord panel** is registered state living in Discord (persistent views keyed by `wb:` custom_ids), NOT in git. After `systemctl restart`, the bot must **re-bind its persistent views** so every button/dropdown still routes. This is the byte-identical-critical invariant (D-08). | Verify post-restart via the live UAT (Gate-2): every button/dropdown routes; correct default location. The custom_id freeze test + Phase-21 custom_id golden are the automatable oracle. |
| OS-registered state | systemd unit `weatherbot.service` on `yahir-mint` (`Type=notify`, `Restart=always`, editable install, `ExecStart=/usr/bin/uv run weatherbot run`). The unit references the repo path + `.env`, not the module — **no unit edit needed** for the split. | None to the unit; the repin lands via `git pull → uv sync --frozen → systemctl restart`. |
| Secrets/env vars | `.env` (`OPENWEATHER_API_KEY`, `DISCORD_WEBHOOK_URL`, Discord bot token) — git-ignored, host-only, **unchanged** by the split. | None — no secret name references the module. |
| Build artifacts / installed packages | The host runs an **editable install** of WeatherBot; after the split, the module installs from the git pin into the same venv. A stale `yahir_reusable_bot` in the editable WeatherBot wheel must not shadow the git-installed module. `uv sync --frozen` rebuilds the venv from the lock — verify no two `yahir_reusable_bot` on `sys.path`. | `uv sync --frozen` on host resolves this; the startup-version-log `editable` flag + sha confirm the right module is loaded. |

**The canonical question — after every file is updated, what runtime systems still have the old layout
cached?** Answer: (1) the host venv (resolved by `uv sync --frozen`), and (2) the live Discord panel's
persistent-view registration (resolved by the restart re-bind + verified by the UAT). Nothing else.

## Common Pitfalls

### Pitfall 1: The dev-path override leaks into the committed deploy artifact
**What goes wrong:** A Pattern-2 uncommitted `path = "../YahirReusableBot"` edit gets committed; the host
`uv sync` then tries to install from a path that doesn't exist on the host → deploy breaks.
**Why it happens:** uv has no shipped env-var/separate-file override (#15895 open), so the override often
*is* an edit to a committed file.
**How to avoid:** Prefer the **venv editable overlay** (Pattern 2 default — never touches a committed
file). If using the uncommitted-edit form, add a git **pre-commit hook** that greps `[tool.uv.sources]`
for `path =` and rejects the commit; and rely on the **`uv build --no-sources` gate** to catch it.
**Warning signs:** `uv build --no-sources` errors; the startup-version-log shows `editable: true` on the host.

### Pitfall 2: `uv.lock` non-reproducibility / drift
**What goes wrong:** A tag is re-pointed (force-pushed) or the lock is stale vs pyproject; `uv sync` on
the host re-resolves to a different sha than tested.
**Why it happens:** Using `--frozen` only ignores the up-to-date *check*; if the lock was never
regenerated after the repin, it's stale. Tags are mutable.
**How to avoid:** Treat tags as immutable (never force-push a deploy tag); after a repin run
`uv lock --upgrade-package yahir-reusable-bot`, commit the new `uv.lock`, THEN deploy. Use `--locked` in
CI to *fail* on drift; `--frozen` only after the lock is validated.
**Warning signs:** the deployed sha (startup-version-log) ≠ the sha in the committed `uv.lock`.

### Pitfall 3: `discord.py` version drift breaks the live panel
**What goes wrong:** The module declares a range instead of `==2.7.1`; the host resolves a newer discord.py;
the persistent panel registered against 2.7.1 throws "interaction failed."
**How to avoid:** Keep the EXACT `discord.py==2.7.1` pin in the module pyproject; the app inherits it
transitively. The live UAT (Gate-2) + the custom_id golden are the oracle.
**Warning signs:** `uv.lock` shows a discord.py ≠ 2.7.1; a panel button errors after restart.

### Pitfall 4: The two stale `weatherbot.*` docstring references ride into the standalone repo
**What goes wrong:** `yahir_reusable_bot/channels/__init__.py` (line ~6) and `yahir_reusable_bot/ports/alerts.py`
(line ~15) contain prose `weatherbot.*` references — harmless in-tree, but embarrassing/misleading in a
standalone "generic bot core" repo.
**How to avoid:** Scrub both during the move (D-03 scope guardrail explicitly allows this). They are
PROSE, so the litmus (which ignores docstrings by construction) won't catch them — this is a manual scrub.
**Warning signs:** `grep -rn weatherbot yahir_reusable_bot/` returns the two lines (confirmed this session).

### Pitfall 5: Coverage/grimp config references a now-external package
**What goes wrong:** `[tool.coverage.run] source` in WeatherBot's pyproject still lists `yahir_reusable_bot`
(verified present, line 57); coverage tooling errors or silently mis-measures an external package.
**How to avoid:** Remove `yahir_reusable_bot` from the app's coverage source list (it's now external);
the module's own GSD project carries its own coverage config.
**Warning signs:** coverage "module not measured" / "no data" warnings on the now-external package.

### Pitfall 6: The import-hygiene self-proofs assume `weatherbot` is in-tree (CR-01/CR-02)
**What goes wrong:** The relocated `test_import_hygiene.py` builds `grimp.build_graph(MODULE, APP)` and
injects a real `import weatherbot.config.models` leak into the module to self-prove the gate bites. In the
standalone module repo there is **no `weatherbot` package**, so `build_graph(MODULE, APP)` and the
`_injected_app_leak()` self-proofs (which write `import weatherbot.config.models`) cannot resolve.
**How to avoid:** When relocating the suite, **re-scope the self-proofs**: the module repo's gate proves
"imports zero app code" against a *synthetic* app name (the `_scan_app_leaks` synthetic-dict self-proof
still works; the real-`grimp`-build self-proofs that import `weatherbot` must be dropped or retargeted to
a throwaway sibling package). The litmus AST noun-scan + isolated-import smoke carry over unchanged. This
is the single most intricate test-relocation step — flag it for a dedicated task.
**Warning signs:** `ModuleNotFoundError: weatherbot` when running the module suite in its own repo.

### Pitfall 7: Hatchling silently drops a package on the wheel-packages edit
**What goes wrong:** Editing `[tool.hatch.build.targets.wheel] packages` wrong → hatchling silently
builds a wheel missing the intended package (the existing pyproject comment explicitly warns about this).
**How to avoid:** After each pyproject edit, build and inspect: `uv build && python -m zipfile -l dist/*.whl`
(or `tar tzf dist/*.tar.gz`) — confirm the app wheel contains `weatherbot/` and ONLY it, and the module
wheel contains `yahir_reusable_bot/` and ONLY it.
**Warning signs:** `import yahir_reusable_bot` fails after install; `weatherbot check` ImportErrors.

### Pitfall 8: The "works locally" trap — a dev overlay masks a broken git pin
**What goes wrong:** Co-dev runs against the editable overlay; the committed git pin is actually broken
(bad tag, missing dep) but nobody notices because the overlay shadows it.
**How to avoid:** The **clean-venv `uv sync --frozen` install gate (D-08 Gate-1)** is exactly this guard
— it installs purely from the pin in a fresh venv, with no overlay, and runs the full suite + goldens.
Run it in CI / before every deploy.
**Warning signs:** `uv sync --frozen` in a fresh venv fails where the dev tree passed.

## Code Examples

### Repo creation + clean import commit (D-01)
```bash
# From the WeatherBot repo (clean working tree, suite green):
mkdir ../YahirReusableBot && cd ../YahirReusableBot && git init
# Copy the clean tree (fresh-init keeps WeatherBot's extraction history; module starts clean):
cp -r ../WeatherBot/yahir_reusable_bot ./yahir_reusable_bot
# ... scrub the two stale weatherbot.* docstrings (Pitfall 4); add pyproject.toml, EXTENSION-GUIDE.md,
#     relocated tests, .gitignore, .planning/ (GSD init) ...
git add -A && git commit -m "feat: initial import of yahir_reusable_bot reusable bot core"
git tag v0.1.0
git remote add origin <url> && git push -u origin main --tags
```

### Re-point WeatherBot + lock + verify (D-04 / D-08 Gate-1)
```bash
# In WeatherBot, after editing pyproject.toml (Pattern 5):
uv lock                                   # resolves tag v0.1.0 -> sha, writes uv.lock
uv sync --frozen                          # install exactly from the lock
weatherbot check && weatherbot --help     # console script resolves through stable public names
uv run pytest                             # full suite + Phase-21 goldens, byte-identical
uv build --no-sources                     # leak gate: no path/source leakage
# Repin later (after the module pushes a new tag):
uv lock --upgrade-package yahir-reusable-bot && uv sync --frozen
```

### Clean-venv install gate (the "works on host" proof, D-08 Gate-1)
```bash
# Simulate the host: a pristine venv, install only from the pin + lock.
rm -rf .venv && uv venv && uv sync --frozen
uv run weatherbot check && uv run pytest    # must pass with no dev overlay present
```

### Live host deploy + restart (D-08 Gate-2 — deferred, secure host action)
```bash
# On yahir-mint (after repin pushed + uv.lock committed):
cd ~/Projects/WeatherBot && git pull
uv sync --frozen                            # picks up the new pinned module sha
sudo systemctl restart weatherbot           # Type=notify; READY=1 re-sent after re-bind
journalctl -u weatherbot -n 30 --no-pager   # confirm the startup-version-log: module_sha == promoted sha
# Then the device step: tap every panel button/dropdown — all route; correct default location.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Editable two-package wheel in one repo | Two repos + uv git dependency, tag-pinned + frozen lock | This phase | The boundary becomes a package boundary; reproducibility shifts to `uv.lock` + `--frozen`. |
| `discord.py` pinned app-side | Pinned in the module, inherited transitively | This phase (SEAM-07 D-05 destination) | The app no longer names discord.py; the module owns the wire contract. |
| Reading version via in-tree path | `importlib.metadata` + PEP 610 `direct_url.json` | This phase | Survives a clean-venv git install; reports the deployed sha. |

**Deprecated/outdated:**
- `setup.py`/Poetry for this project — uv + hatchling is the locked toolchain (CLAUDE.md).
- `UV_SOURCES` env override — **does not exist yet** (open FR #15895); do not design around it.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `uv pip install -e ../sibling` venv-overlay is the cleanest D-05 dev mechanism. | Pattern 2 | LOW — it's a documented uv command; worst case the team prefers the uncommitted-edit form (also documented). Either way the committed artifact stays the git pin. |
| A2 | `direct_url.json` `vcs_info.commit_id` is populated for a uv git install (not just pip). | Pattern 4 | LOW-MEDIUM — PEP 610 is the standard and uv implements it; the editable-install format was VERIFIED in the live venv this session, but the *git-install* variant should be confirmed empirically during planning (install from a real tag and cat the file). |
| A3 | The repin ritual + promotion ledger docs live WeatherBot-side. | D-06 / Pattern 1 | LOW — planner discretion; placement is cosmetic. |
| A4 | Removing `yahir_reusable_bot` from the app's `[tool.coverage.run] source` is the right call. | Pitfall 5 | LOW — it's now external; if app-side coverage of the boundary is wanted, it belongs in the module's own suite. |
| A5 | The discord.py/httpx/structlog/tenacity "SUS" verdicts are PyPI-metadata-gap false-positives, not real risk. | Package Legitimacy Audit | LOW — these are pre-existing production deps already running on the live host; the verdict is driven by `unknown-downloads`/`no-repository`, not by newness or a postinstall script. |

## Open Questions

1. **Does a uv git install populate `direct_url.json` with `vcs_info.commit_id`?**
   - What we know: PEP 610 specifies it; uv implements PEP 610; the editable-install variant is confirmed
     in the live venv (shows `dir_info.editable`).
   - What's unclear: the exact git-install JSON shape on this uv version (0.11.19).
   - Recommendation: a Wave-0 task installs the module from a throwaway tag into a scratch venv and
     `cat`s `direct_url.json` to lock the field names BEFORE wiring the startup-version-log.

2. **Where does the relocated `test_import_hygiene.py` get its "app" target for the self-proofs?**
   - What we know: the standalone module repo has no `weatherbot` package; the real-grimp self-proofs
     import `weatherbot.config.models`.
   - What's unclear: whether to drop those CR-01/CR-02 self-proofs or retarget them to a throwaway
     sibling package fixture.
   - Recommendation: dedicated task (Pitfall 6) — keep the synthetic-dict + litmus + isolated-import
     self-proofs; retarget or drop the two real-import self-proofs with a documented reason.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | git dep, lock, sync, build-no-sources | ✓ | 0.11.19 | — |
| Python | runtime / requires-python >=3.12 | ✓ | 3.12.3 | — |
| git | fresh-init repo + git mv | ✓ | 2.43.0 | — |
| grimp | import-hygiene gate (both repos) | ✓ (dev-dep) | >=3.14 | — |
| discord.py / httpx / structlog / tenacity | module runtime (relocated, already in prod) | ✓ | 2.7.1 / 0.28.x / 26.x / 9.x | — |
| GitHub remote for `YahirReusableBot` | the git pin URL | ✗ (must be created) | — | A local bare repo / file:// git URL works for Gate-1; a real remote is needed before the host can `git pull`-resolve the pin. |
| yahir-mint host access | live Gate-2 restart UAT | (host-only; secure action) | — | Gate-2 is a deferred human/device obligation per the Two-Gate policy. |

**Missing dependencies with no fallback:** none blocking Gate-1.
**Missing dependencies with fallback:** the `YahirReusableBot` GitHub remote must be created before the
host can resolve the git pin (Gate-1 can validate against a local/file:// git URL first).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-cov 7.x + syrupy 5.x (golden snapshots) + time-machine 2.16 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=["tests"], pythonpath=["."]) |
| Quick run command | `uv run pytest -x -q` |
| Full suite command | `uv run pytest` (754 test funcs across `tests/`; "732 tests green" baseline per STATE.md; the suite prints "2 snapshots failed" but **exits 0** — known syrupy noise, trust the exit code + `.ambr` diff) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PKG-02 | Module installs from the git pin in a clean venv | integration | `rm -rf .venv && uv venv && uv sync --frozen && uv run weatherbot check` | ❌ Wave 0 (new clean-venv gate task) |
| PKG-02 | Full suite + Phase-21 goldens byte-identical against the pinned module | golden | `uv run pytest` (existing `tests/test_golden_*.py`) | ✅ |
| PKG-02 | `custom_id` wire contract unchanged (live panel routes) | golden | `uv run pytest tests/test_golden_custom_ids.py` | ✅ |
| PKG-02 | Wheel carries no path/source leak | build-gate | `uv build --no-sources` | ❌ Wave 0 (new gate task / CI step) |
| PKG-02 | App wheel contains only `weatherbot/`; module wheel only `yahir_reusable_bot/` | build-inspect | `uv build && python -m zipfile -l dist/*.whl` | ❌ Wave 0 |
| PKG-02 | Module imports zero app code (across the new boundary) | import-hygiene | `uv run pytest tests/test_import_hygiene.py` (relocated; self-proofs re-scoped — Pitfall 6) | ✅ (needs relocation/retarget) |
| PKG-02 | Startup-version-log reports the deployed sha | unit | new test asserting `_module_provenance()` reads `direct_url.json` | ❌ Wave 0 |
| DOCS-01 | EXTENSION-GUIDE documents each plug point w/ status | manual/doc | doc-presence assertion (the six seams + deferred entries) | ❌ Wave 0 (doc) |

### Sampling Rate
- **Per task commit:** `uv run pytest -x -q` (fast feedback)
- **Per wave merge:** `uv run pytest` (full suite + goldens)
- **Phase gate:** clean-venv `uv sync --frozen` + full suite + goldens + `uv build --no-sources` green
  (Gate-1) before `/gsd-verify-work`; live `yahir-mint` restart UAT recorded as the deferred Gate-2.

### Wave 0 Gaps
- [ ] A clean-venv `uv sync --frozen` install gate (script/test) — the "works on host" proof (D-08).
- [ ] A `uv build --no-sources` leak-gate step (CI/test).
- [ ] A wheel-contents inspection check (Pitfall 7).
- [ ] A `direct_url.json` field-shape spike (Open Question 1) before wiring the startup-version-log.
- [ ] Relocate + **re-scope** `test_import_hygiene.py` for the standalone module repo (Pitfall 6).
- [ ] A unit test for `_module_provenance()` (startup-version-log).
- [ ] EXTENSION-GUIDE.md authoring (DOCS-01).

## Security Domain

> `security_enforcement: true`, ASVS level 1, block-on: high.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | The split must not widen the trust boundary; the module imports zero app code (grimp) and ships no secrets/config. |
| V2 Authentication | no | No auth surface changes (the Discord bot token + webhook are unchanged, host-only `.env`). |
| V5 Input Validation | no (unchanged) | Config validation stays app-side (injected `validate`); the module never parses config (existing grimp gate `test_config_module_never_imports_pydantic`). |
| V6 Cryptography | no | No crypto introduced. |
| V10 Malicious Code / Supply Chain | **yes** | The new git-dependency supply chain: pin by tag→sha in `uv.lock` (`--frozen`), never force-push a deploy tag, `uv build --no-sources` proves no path leak, and the package-legitimacy verdicts are accounted for (pre-existing prod deps). |
| V14 Configuration | yes | `.env` secrets stay git-ignored & host-only; the split touches no secret; the systemd unit's `EnvironmentFile=.env` (chmod 600) is unchanged. |

### Known Threat Patterns for the two-repo / git-dependency stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Mutable git tag re-pointed to malicious/broken sha | Tampering | Pin sha in `uv.lock`, install `--frozen`; treat deploy tags as immutable; startup-version-log audits the deployed sha against the promotion ledger. |
| Dev path-source leaks into deploy artifact | Tampering / DoS (host install break) | venv-overlay dev pattern (no committed-file edit) + `uv build --no-sources` gate + optional pre-commit grep (Pitfall 1). |
| Secret leak into the relocated module repo | Information Disclosure | Module ships code only — no `.env`, no config; verify the fresh-init import contains no secret (the move copies `yahir_reusable_bot/` only, which has no secrets). |
| Dependency confusion (slopsquat of `yahir-reusable-bot`) | Spoofing | The dep is a **git URL pin**, not a registry name — there is no PyPI package to confuse with; `--no-sources` would fail (no published metadata), which is expected and not a deploy path. |
| discord.py drift breaking the authenticated panel | Tampering (wire-contract) | EXACT `==2.7.1` pin in the module; custom_id golden + live UAT. |

## Sources

### Primary (HIGH confidence)
- docs.astral.sh/uv/concepts/projects/dependencies — `[tool.uv.sources]` git tag/rev/branch syntax,
  path sources, editable, `--no-sources` semantics, workspaces-vs-path. [CITED]
- docs.astral.sh/uv/concepts/projects/sync — `uv sync --frozen` / `--locked`, `uv lock --upgrade-package`. [CITED]
- docs.python.org/3/library/importlib.metadata + PEP 610 — `direct_url.json` runtime version/sha read. [CITED]
- Live venv inspection (this session) — confirmed `direct_url.json` format (editable variant) and the
  module's third-party import surface (grep). [VERIFIED]
- Tool versions (this session): uv 0.11.19, Python 3.12.3, git 2.43.0. [VERIFIED]

### Secondary (MEDIUM confidence)
- github.com/astral-sh/uv/issues/15895 — `UV_SOURCES` env override is an OPEN feature request, NOT shipped. [CITED]
- WebSearch (cross-checked w/ uv docs) — dev-override patterns, `--frozen` vs `--locked`, `--no-sources` CI gate. [MEDIUM]
- pypi.org/project/hatch-vcs — build-time git-tag versioning (considered, not recommended for v1). [CITED]

### Tertiary (LOW confidence)
- None relied upon.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — uv/git/python versions verified live; syntax cited from official docs.
- Architecture (git pin / lock / build-no-sources / runtime sha): HIGH — cited from uv docs + PEP 610;
  the `direct_url.json` git-install field shape is the one MEDIUM (Open Question 1, easily spiked).
- Dev-override mechanism (D-05): MEDIUM — uv has no shipped first-class feature; the recommended
  venv-overlay is sound and documented, but the "no leak" guarantee rests on workflow discipline + the
  `--no-sources` gate rather than a uv feature.
- Pitfalls: HIGH — grounded in this session's grep/file inspection (stale docstrings, coverage source,
  the import-hygiene self-proof coupling to `weatherbot`).

**Research date:** 2026-06-29
**Valid until:** 2026-07-29 (uv is fast-moving — re-check the `UV_SOURCES` FR status and `--frozen`/`--no-sources`
flags if planning slips >2 weeks, since a shipped `UV_SOURCES` would change the D-05 recommendation).
