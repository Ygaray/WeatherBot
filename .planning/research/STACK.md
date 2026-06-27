# Stack Research

**Domain:** Python multi-repo packaging — extracting a reusable bot module out of an app, consumed back via a uv git dependency
**Researched:** 2026-06-27
**Confidence:** HIGH

> Scope note: This is a **pure-extraction / packaging** research pass. The runtime libraries
> (httpx, APScheduler 3.x, tenacity, structlog, discord.py, watchfiles, cachetools, pydantic,
> SQLite stdlib) are already chosen and **stay** — they are not re-researched here. This doc
> answers only: *how do we carve the module into its own installable package and depend on it
> from WeatherBot via uv, with a smooth two-repo dev loop?* Versions verified against uv 0.11.19
> (installed on this host) and current Astral docs.

---

## Executive Recommendation

**Use a uv git dependency for deploy, a uv `tool.uv.sources` local-path editable override for dev, and switch between them with a one-line edit (or `uv add` toggle). Do NOT publish to PyPI. Do NOT introduce Poetry or monorepo tooling.**

Concretely:

1. The new module repo is a normal **src-layout** uv package: `src/<module>/`, `hatchling` build backend (same as WeatherBot today), a `[project]` table, **no console script** (the `weatherbot` CLI stays in the app — see "Entry-point implications").
2. WeatherBot declares the module in `[project].dependencies` by **name only**, and pins the *source* to git in `[tool.uv.sources]`:
   - **Deploy:** `botkit = { git = "...", tag = "v0.3.0" }` → reproducible, recorded in `uv.lock`.
   - **Dev:** `botkit = { path = "../botkit", editable = true }` → live edits in the sibling checkout, no reinstall.
3. **Versioning:** lightweight **git tags `vMAJOR.MINOR.PATCH`** that the app pins to. Tags are the contract; you don't need a registry, a changelog ceremony, or `__version__` plumbing for a single consumer. Commit-SHA pins are the fallback when you want to pin something untagged.
4. Most of this is **deferrable to the physical-split phase.** The in-place refactor only needs to land a *clean package boundary* (one importable subpackage with no weather imports leaking in). Nothing about uv sources, tags, or the second repo shapes the in-place refactor except: **pick the module's package name and the import root now**, because the in-place package directory should already be named what the extracted package will be (avoids a rename diff at split time).

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| uv | 0.11.19 (installed) | Dependency + venv + lock manager for both repos | Already the project's tool. Native first-class support for **git dependencies** (`tag`/`rev`/`branch`), **editable path** dependencies, and **workspaces** — exactly the three mechanics this split needs, in one tool, no plugins. `tool.uv.sources` is uv-only metadata that is **never** published, so dev overrides can't leak into a consumer. |
| hatchling | (current; already in use) | Build backend for the module repo | WeatherBot already builds with `hatchling` + `[build-system] requires = ["hatchling"]`. Keep it identical in the module repo — zero new backend to learn, and hatchling auto-discovers a `src/<pkg>/` layout with no extra config. Avoids introducing setuptools/Poetry-core. |
| Git tags (`vX.Y.Z`) | n/a | Versioning + the pin contract | For a single-consumer personal module, an annotated git tag *is* the release. uv pins `tag = "v0.3.0"` and records the resolved commit in `uv.lock`, so deploys are reproducible without a package index. No PyPI account, no `twine`, no trusted-publishing setup. |
| uv.lock | n/a | Reproducibility across dev machine ↔ host | `uv lock` resolves the git tag to an exact commit hash and stores it. `uv sync --frozen` (or `--locked`) on the host installs that exact commit — the deployed bot is byte-reproducible even though the dependency lives in git, not a registry. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| uv **workspace** (`tool.uv.workspace`) | uv 0.11.x | Single-lockfile co-development of app + module in one checkout | Optional alternative to the path-override (see "Co-development", Option B). Use it **only if** you decide to keep both packages under one git checkout during development. For a true two-repo layout it is the *wrong* tool — workspaces assume members share one repo, one lockfile, one venv. |
| (stdlib) `tomllib` | 3.12+ | n/a — already available | No new config tooling needed; nothing here requires reading/writing TOML programmatically. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| ruff | Lint + format both repos | Already in WeatherBot's `[dependency-groups] dev`. Copy the same ruff config into the module repo so style stays uniform across the split. |
| pytest | The 649-test acceptance suite | The suite is the extraction contract. **Decide test placement at split time:** mechanism/generic tests move *with* the module repo; weather-specific tests stay in the app. During the in-place phase, keep all tests where they are and green. |
| `uv build --no-sources` | Pre-split sanity check | Run in the module repo before the first tag to prove it builds as a standalone wheel with **no** `tool.uv.sources` help — catches accidental reliance on a local path or sibling import. |

---

## Installation

### A. The new module repo (`botkit/` — rename to taste)

`pyproject.toml`:

```toml
[project]
name = "botkit"                  # the *distribution* name the app depends on
version = "0.1.0"                # bump on each tag; or use a dynamic/hatch-vcs scheme (optional)
description = "Channel-agnostic, reusable bot infrastructure (scheduler/config-reload/channel/lifecycle/Discord-panel)."
requires-python = ">=3.12"
dependencies = [
    # ONLY the libs the generic core actually needs — NOT weather/OpenWeather libs.
    "apscheduler>=3.11.2,<4",
    "discord.py>=2.7.1,<3",
    "structlog>=26.1.0",
    "tenacity>=9.1.4",
    "watchfiles>=1.2.0",
    "pydantic>=2.13.4",
    "pydantic-settings>=2.14.1",
    # httpx / cachetools / discord-webhook: include ONLY if the generic Channel/delivery
    # layer uses them; leave weather-only deps in the app.
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

# NO [project.scripts] here — see "Entry-point implications".
```

Layout (src layout — recommended):

```
botkit/
├── pyproject.toml
├── uv.lock
├── README.md
├── src/
│   └── botkit/
│       ├── __init__.py
│       ├── scheduler/        # generic register(job_id, trigger, callback) engine
│       ├── config/           # holder + validate→swap→reconcile + file-watch + SIGHUP
│       ├── channel/          # Channel abstraction + retry/backoff/alert/heartbeat
│       ├── lifecycle/        # systemd Type=notify READY-gate / supervised restart
│       └── discord/          # gateway bot + persistent-view panel plumbing + registry→panel
└── tests/                    # mechanism/generic tests (moved from the app at split time)
```

Scaffold:

```bash
uv init --package botkit        # creates src-layout package + pyproject + build-system
# then edit dependencies as above, and:
uv lock
uv build --no-sources           # sanity: builds standalone, no source overrides
git tag -a v0.1.0 -m "botkit v0.1.0"
git push --tags
```

### B. WeatherBot (the consumer) — declare + pin

In WeatherBot's `pyproject.toml`, add the dependency by **name**, then choose a source:

```toml
[project]
dependencies = [
    "botkit",                  # name only — the SOURCE decides where it comes from
    # ... existing weather-only deps stay (discord-webhook, httpx, cachetools, etc.)
]

# DEPLOY pin (committed on main / the deploy branch):
[tool.uv.sources]
botkit = { git = "https://github.com/<you>/botkit", tag = "v0.1.0" }
```

```bash
# easiest: let uv write the source for you
uv add git+https://github.com/<you>/botkit --tag v0.1.0
uv lock                         # resolves the tag → exact commit, stored in uv.lock
```

On the host (`yahir-mint`):

```bash
uv sync --frozen                # installs the exact locked commit; reproducible
sudo systemctl restart weatherbot
```

---

## Co-development: the dev ↔ deploy switch (the load-bearing part)

You want: **deployed bot pulls the git pin; local dev edits a sibling checkout live.** uv gives two clean ways. **Option A (path-override) is the recommended default** for a true two-repo personal setup.

### Option A — git pin for deploy, local editable path for dev  ✅ recommended

Lay the repos out side by side:

```
~/Projects/
├── WeatherBot/        # the app
└── botkit/            # the extracted module
```

Committed (deploy) source in WeatherBot's `pyproject.toml`:

```toml
[tool.uv.sources]
botkit = { git = "https://github.com/<you>/botkit", tag = "v0.1.0" }
```

To work locally, **override the source to the sibling checkout, editable**:

```toml
[tool.uv.sources]
botkit = { path = "../botkit", editable = true }
```

`editable = true` writes a `.pth` link into WeatherBot's venv, so every edit in `../botkit/src/botkit/` is picked up with **no reinstall** — ideal for the test-driven extraction loop (edit module → rerun the 649-test suite).

**How to switch cleanly (copy-pasteable):**

```bash
# --- enter dev mode (point at the local editable checkout) ---
uv add --editable ../botkit            # rewrites [tool.uv.sources] to the path + re-syncs

# --- return to deploy mode (re-pin to the tag) ---
uv add git+https://github.com/<you>/botkit --tag v0.2.0
```

Either command rewrites the single `[tool.uv.sources]` line and re-syncs. The dependency line in `[project].dependencies` never changes — only the *source* does.

**Keep the dev override from polluting deploy.** Two equally-fine tactics for a solo dev:
- **Just don't commit the dev edit** — toggle the source line locally, and only ever commit the `git`+`tag` form. Simple; relies on you not `git add`-ing the path line. *(Recommended — least machinery.)*
- **Or** keep the committed source as the git tag and, when developing, gate the dev override with a PEP 508 marker so it only activates on your machine. uv supports a `marker` on a source, e.g. `botkit = { path = "../botkit", editable = true, marker = "sys_platform == 'linux'" }`. This is more ceremony than a solo two-repo flow needs — prefer the don't-commit tactic.

> Note (2026): there is an **open** uv proposal (astral-sh/uv #15895 / #11632) for an env-var / CLI override of `tool.uv.sources` for exactly this dev-vs-deploy case. As of uv 0.11.19 it is **not shipped** — so don't design around `UV_SOURCES`; use the path-override toggle above.

### Option B — uv workspace (only if you keep both packages in ONE checkout)

If you'd rather develop both packages inside a single git checkout (e.g. a `packages/` monorepo *during development*, split out later), use a uv workspace:

```toml
# root pyproject.toml
[tool.uv.workspace]
members = ["packages/*"]

# the app member depends on the module member:
[project]
dependencies = ["botkit"]
[tool.uv.sources]
botkit = { workspace = true }     # installed editable, one shared uv.lock, one venv
```

Workspace members are auto-installed **editable** and share **one lockfile + one venv**. That's great for a single-repo monorepo, but it is the **wrong fit for the stated two-repo goal** — a workspace assumes the members live together. Use Option A for the real split; reach for B only if you decide the module should *not* actually become a separate repo. **Recommendation: Option A.**

---

## Entry-point implications (the `weatherbot` CLI)

WeatherBot currently owns the console script:

```toml
[project.scripts]
weatherbot = "weatherbot.cli:main"
```

**Keep this in the app, not the module.** The `weatherbot` command is weather-specific (subcommands `weather`/`run`/`check`/`send-now`/`geocode`, the briefing daemon). A reusable bot module must not ship a `weatherbot` entry point — that would violate the "zero weather assumptions" litmus.

What the module *may* expose instead (optional, deferrable): a small **library API** the app's `cli:main` calls into — e.g. `botkit.lifecycle.run_supervised(...)`, `botkit.scheduler.Scheduler`, `botkit.discord.build_panel(registry)`. The `[project.scripts]` block stays entirely in WeatherBot; the module is import-only. If a *future* reminder bot wants its own CLI, it declares its own `[project.scripts]` pointing at its own glue — the module never presumes a command name.

---

## Versioning approach (single-consumer personal module)

| Option | Verdict | Why |
|--------|---------|-----|
| **Git tags `vX.Y.Z` (semver-ish)** | ✅ **Use this** | The tag is the release and the pin. Bump PATCH for fixes, MINOR for new seams, MAJOR if you break the app's import contract. uv pins the tag and locks the commit. No registry needed. Keep `version` in `pyproject.toml` in step with the tag (or let hatch derive it from the tag later if you want — optional). |
| **Commit-SHA pins (`rev = "..."`)** | ✅ fallback | Use when you want to pin something *between* tags (e.g. test an unreleased fix on the host). Fully reproducible, just less readable than a tag. `uv add git+... --rev <sha>`. |
| **Branch pins (`branch = "main"`)** | ⚠️ dev-only | Convenient but **not reproducible across time** (the branch moves). Fine for a throwaway "track main" dev loop; never for the deployed pin. `uv.lock` still snapshots a commit, but `uv lock --upgrade` will drift it. |
| **Date-based versions** | ❌ skip | No benefit over semver tags for a single consumer; semver communicates "did this break my app?" which is the only signal you care about. |
| **Just commit pins, no tags** | ❌ skip | Works, but tags cost nothing and make "which version is the bot running?" legible at a glance. |

---

## What NOT to add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| **Publishing the module to PyPI** | Pure ceremony for a single private consumer: account, `twine`/trusted-publishing, name-squatting risk, release cadence. uv git deps give reproducibility without any of it. | `git` source + `tag` pin; `uv.lock` for reproducibility. |
| **Poetry / poetry-core** | WeatherBot already uses `hatchling` + uv. Adding Poetry means two packaging models, a `poetry.lock` vs `uv.lock` split, and re-learning sources. | Keep `hatchling` + uv in **both** repos. |
| **Monorepo tooling (Pants, Bazel, Nx, Lerna-style)** | Two personal Python packages do not need a build graph engine. Massive setup/maintenance for zero payoff at this scale. | uv git dep (two repos) or a uv workspace (one repo). |
| **A uv workspace for the *two-repo* split** | Workspaces assume members share one repo/lockfile/venv; using one across two repos fights the tool. | `tool.uv.sources` git pin + path override (Option A). |
| **`branch = "main"` as the deployed pin** | The deployed bot would silently change whenever you push to the module — the opposite of "survive across days without surprises." | Pin a `tag` (or `rev`) for deploy; reserve branch pins for local dev. |
| **A `[project.scripts]` console entry point in the module** | Bakes the `weatherbot` name (a weather assumption) into a "channel-agnostic" module — fails the reuse litmus. | Module is import-only; the app keeps `[project.scripts]`. |
| **`__version__` plumbing / version-bump automation** | Over-engineering for one consumer; the git tag already answers "what's deployed." | Hand-bump `version` on tag, or adopt hatch-vcs later **only if** it becomes annoying. |
| **A `requirements.txt` export step** | uv reads `pyproject.toml` + `uv.lock` directly on the host; an exported requirements file is a second source of truth to drift. | `uv sync --frozen` on `yahir-mint`. |

---

## Stack Patterns by Variant

**If you want the deployed host to never rebuild from a moving target:**
- Commit `[tool.uv.sources] botkit = { git = ..., tag = "vX.Y.Z" }` and run `uv sync --frozen` on the host.
- Because the tag → commit resolution is frozen in `uv.lock`; the bot reinstalls the *same* commit on every deploy until you bump the tag and re-lock.

**If you're mid-extraction and iterating on the module against the 649-test suite:**
- Use `uv add --editable ../botkit` so the app's venv links the sibling checkout.
- Because edits in `../botkit/src/botkit/` are live (no reinstall), so the red→green loop is instant and the suite drives the extraction.

**If you decide NOT to actually split into two repos (keep one repo):**
- Use a uv **workspace** (`tool.uv.workspace.members`, `botkit = { workspace = true }`).
- Because a single lockfile + editable members is the lowest-friction way to keep two packages honest in one checkout — but you lose the "module is independently reusable from its own repo" property the milestone wants.

**If you need to pin an un-tagged fix on the host quickly:**
- `uv add git+<url> --rev <sha>` then `uv lock && uv sync --frozen`.
- Because a `rev` pin is as reproducible as a tag without forcing a release tag for a hotfix.

---

## What this shapes now vs. what defers to the physical-split phase

| Decision | When it must be made | Why |
|----------|----------------------|-----|
| **Module package name + import root** (`botkit/` and `src/botkit/`) | **In-place refactor (now)** | The in-place clean-boundary subpackage should already be named what the extracted package will be, so the physical split is a `git mv` of a directory, not a rename across 10k LOC. Pick the name before the refactor. |
| **Which deps are "generic" vs "weather"** | **In-place refactor (now)** | The boundary refactor must not let weather/OpenWeather imports leak into the generic subpackage; that import-hygiene line *is* the future module's `dependencies` list. Decide it while drawing the seam. |
| **Test partition (module tests vs app tests)** | **Physical-split phase (defer)** | Keep all 649 tests green in place during the refactor; only sort them into two repos when you actually create the second repo. |
| **`hatchling` config in the module repo** | **Physical-split phase (defer)** | `uv init --package` generates it; trivial. No need before the split. |
| **git tag scheme / first `v0.1.0` tag** | **Physical-split phase (defer)** | There's nothing to tag until the repo exists. |
| **`tool.uv.sources` git pin + dev path override in WeatherBot** | **Physical-split phase (defer)** | Only meaningful once `botkit` is a separate repo. During the in-place phase the code is just a local subpackage. |

---

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| uv 0.11.19 | git deps `tag`/`rev`/`branch`, editable `path`, workspaces | All three mechanics confirmed in current Astral docs; `tool.uv.sources` is uv-only and never published. |
| hatchling (current) | src-layout `src/<pkg>/` | Auto-discovers the package; no extra `[tool.hatch.build]` config needed for a single top-level package. |
| module `requires-python = ">=3.12"` | WeatherBot `requires-python = ">=3.12"` | Must match (or the module's must be ≤ the app's). Keep both at `>=3.12` to avoid resolver intersection surprises. |
| APScheduler `>=3.11.2,<4` | both repos | Keep the **identical** constraint in both `pyproject.toml`s so the resolver never has to reconcile divergent pins for a shared transitive lib. |

---

## Sources

- https://docs.astral.sh/uv/concepts/projects/dependencies/ — git deps (`tag`/`rev`/`branch`), editable `path` deps, `package=false`, and the rule that `tool.uv.sources` is uv-only / not published (`uv build --no-sources`). HIGH
- https://docs.astral.sh/uv/concepts/projects/workspaces/ — `tool.uv.workspace` members/exclude, `workspace = true` sources, single-lockfile/single-venv limitations, when NOT to use a workspace. HIGH
- https://pydevtools.com/handbook/how-to/how-to-manage-cross-repo-python-dependencies-with-uv/ — cross-repo dev-vs-deploy pattern, PEP 508 `marker` on a source, "don't commit the dev override" guidance. MEDIUM
- https://github.com/astral-sh/uv/issues/15895 + #11632 — proposed env-var/CLI override of `tool.uv.sources` for dev is **open, not shipped** as of uv 0.11.19; use the path-override toggle instead. MEDIUM
- Installed `uv 0.11.19` (this host) + WeatherBot `pyproject.toml` (`hatchling` build backend, `[project.scripts] weatherbot`). HIGH

---
*Stack research for: multi-repo Python packaging — extracting a reusable bot module consumed via a uv git dependency*
*Researched: 2026-06-27*
