# Phase 28: Physical Repo Split + uv Git Dependency + EXTENSION-GUIDE - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-29
**Phase:** 28-physical-repo-split-uv-git-dependency-extension-guide
**Areas discussed:** Repo creation + history, Module package identity, Dependency partition, uv git dependency + pin granularity, Local co-development override, Repin ritual + version-log + ledger, EXTENSION-GUIDE + module GSD-project init, Live UAT
**Mode:** `--auto` — single-pass; every gray area auto-selected on the reusable-module + byte-identical-lowest-risk axis (no interactive prompts). The ROADMAP Phase-28 block + PKG-02 + DOCS-01 pre-lock the headline; intricate uv/packaging mechanics handed to the researcher/planner.

---

## Repo creation + history (D-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Fresh `git init` + clean import commit | New repo starts from a clean baseline; extraction history stays in WeatherBot repo | ✓ |
| `git subtree split` / `filter-repo` | Carry the module's per-file history into the new repo | |

**Auto-selected:** Fresh-init clean import commit (recommended default).
**Notes:** Phase 22–27 extraction history already lives durably in the WeatherBot repo; "initialize the module as its own GSD project" implies a fresh baseline. History-preserving split allowed only if trivially cheap (planner discretion).

---

## Module package identity (D-02)

| Option | Description | Selected |
|--------|-------------|----------|
| `yahir-reusable-bot` / `yahir_reusable_bot`, no console script, hatchling, py>=3.12 | Mirror WeatherBot's build toolchain; library-only | ✓ |

**Auto-selected:** ROADMAP/PKG-02-locked identity; mechanical pyproject metadata.
**Notes:** No `[project.scripts]` in the module — the `weatherbot` entry point stays the only console script, app-side.

---

## Dependency partition (D-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Declare exactly the imported deps | Module: `discord.py==2.7.1`, `httpx`, `structlog`, `tenacity`; pin moves out of app | ✓ |
| Over-declare "to be safe" | Carry extra deps into the module wheel | |

**Auto-selected:** Partition by actual imports (grep-confirmed), proven by `uv build --no-sources` leak gate + clean-venv install.
**Notes:** `discord.py==2.7.1` exact pin moves to the module pyproject (already flagged in the app pyproject comment); WeatherBot inherits it transitively.

---

## uv git dependency + pin granularity (D-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Tag pin in `tool.uv.sources` + sha in `uv.lock` | Human-readable tag for promotion; exact sha for reproducible `uv sync --frozen` | ✓ |
| Bare commit-rev pin | Pin only by sha, no tag | |
| Branch/floating ref | Non-reproducible | |

**Auto-selected:** Tag-pinned for deploy + reproducible lock (ROADMAP-locked).

---

## Local co-development override (D-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Uncommitted/env-gated editable path override over the committed git pin | Edit both repos without push→repin; never leak the path into the deploy artifact | ✓ |
| uv workspace | Assumes one shared tree — wrong for separate repos | |

**Auto-selected:** Path override toggled locally; committed default stays the git pin. Exact uv mechanism = primary research target.

---

## Repin ritual + startup-version-log + promotion ledger (D-06)

| Option | Description | Selected |
|--------|-------------|----------|
| Documented commit→push→tag→repin→deploy ritual + startup-version-log sha line + promotion ledger | Durable, auditable two-repo deploy process | ✓ |

**Auto-selected:** ROADMAP-locked process artifacts. Runtime source of the sha (importlib.metadata vs uv.lock vs introspection) and doc location = planner discretion.

---

## EXTENSION-GUIDE + module GSD-project init (D-07)

| Option | Description | Selected |
|--------|-------------|----------|
| `EXTENSION-GUIDE.md` at module repo root + module as its own GSD project | Each plug point with implemented-vs-deferred status; durable-`JobStore` + 2nd `Channel` recorded deferred | ✓ |

**Auto-selected:** DOCS-01-locked. Plug points = the injection seams from Phases 22–27; durable-`JobStore` serialization contract is the key deferred entry.

---

## Live UAT (D-08)

| Option | Description | Selected |
|--------|-------------|----------|
| Gate-1 clean-venv `uv sync --frozen` + check/suite/goldens + leak gate; Gate-2 live `yahir-mint` restart | Installed-artifact gate + device-verifiable live restart with panel-routing proof | ✓ |

**Auto-selected:** Two-Gate UAT. Live host runs an editable install; restart picks up the repin; panel custom_id/persistent-view re-bind must stay byte-identical (`discord.py==2.7.1` + frozen `wb:` ids).

---

## Claude's Discretion

- The exact uv "git-pin-for-deploy + path-for-dev" mechanism (D-05) — **primary research target**.
- Runtime source of the module sha for the startup-version-log (D-06).
- Whether to preserve module file history via subtree/filter-repo (D-01) — only if trivially cheap.
- Where the repin-ritual + promotion-ledger docs live and their format.
- Mechanical pyproject details of both repos post-split (app wheel collapses to one package; module metadata; dev-tooling duplication; both `uv.lock`s).
- How the live `yahir-mint` deploy is driven and the repin → push → pull → sync → restart ordering.
- The exact form of the `uv build --no-sources` leak gate and its integration with the `grimp`/litmus gates across the repo boundary.

## Deferred Ideas

- Durable/dynamic `JobStore` impl (+ serialization contract) — documented + recorded only.
- Second `Channel` adapter (Telegram/SMS/Slack) — documented + recorded only.
- Publishing `yahir-reusable-bot` to PyPI / private index — git dep is the v2.0 mechanism.
- History-preserving repo split — default is fresh-init.
- Slash-command adapter, weather-pattern analysis — out of v2.0.
