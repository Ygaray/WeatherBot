---
phase: 28-physical-repo-split-uv-git-dependency-extension-guide
plan: 01
subsystem: infra
tags: [uv, hatchling, git-dependency, packaging, grimp, discord.py, pep610, direct_url, extension-guide]

# Dependency graph
requires:
  - phase: 22-27 (in-place boundary extraction)
    provides: the import-clean yahir_reusable_bot/ flat-sibling tree + the 3-gate import-hygiene suite
provides:
  - "Standalone YahirReusableBot repo at /home/yahir/Projects/YahirReusableBot (fresh git init, one clean import commit tagged v0.1.0, sha 138a907d57ac1d1d8499399b019f1509e43d02f1)"
  - "Module pyproject (name=yahir-reusable-bot, hatchling, requires-python>=3.12, NO console script, discord.py==2.7.1 exact pin moved here)"
  - "Re-scoped standalone import-hygiene suite (single-package grimp build; real-import self-proofs dropped/retargeted)"
  - "EXTENSION-GUIDE.md documenting all six plug points with implemented-vs-deferred status"
  - "Module's own GSD .planning/ recording EXT-01 (durable JobStore) + EXT-02 (2nd Channel) deferred"
  - "EMPIRICALLY CONFIRMED direct_url.json contract: a uv git install writes vcs_info.commit_id + vcs_info.requested_revision (the contract 28-03's _module_provenance() reads)"
affects: [28-02 (WeatherBot re-point to the git pin), 28-03 (startup-version-log provenance reader), 28-04 (custom_id golden)]

# Tech tracking
tech-stack:
  added: ["uv git dependency (file:// fallback)", "hatchling wheel packaging for the module repo"]
  patterns: ["single clean import commit (fresh git init, history stays in WeatherBot)", "PEP 610 direct_url.json as the deployed-sha source", "single-package grimp build in the standalone repo"]

key-files:
  created:
    - "/home/yahir/Projects/YahirReusableBot/pyproject.toml"
    - "/home/yahir/Projects/YahirReusableBot/tests/test_import_hygiene.py"
    - "/home/yahir/Projects/YahirReusableBot/EXTENSION-GUIDE.md"
    - "/home/yahir/Projects/YahirReusableBot/.planning/ (PROJECT.md, ROADMAP.md, REQUIREMENTS.md, config.json)"
    - "/home/yahir/Projects/YahirReusableBot/.gitignore"
    - "/home/yahir/Projects/YahirReusableBot/yahir_reusable_bot/ (28 .py files, copied + scrubbed)"
  modified:
    - "yahir_reusable_bot/channels/__init__.py:6 (scrubbed weatherbot.channels prose)"
    - "yahir_reusable_bot/ports/alerts.py:15 (scrubbed weatherbot.weather.store prose)"

key-decisions:
  - "Used the file:// local-git-URL fallback for the v0.1.0 pin — no GitHub remote for YahirReusableBot yet (a real remote is a deploy prerequisite for the deferred Gate-2 host pin)"
  - "Retargeted (not just dropped) the isolated-import blocker self-proof to a synthetic blocked name so it survives the loss of the real weatherbot package, asserting the ImportError comes from _AppBlocker"

patterns-established:
  - "Pattern: PEP 610 direct_url.json contract empirically confirmed before any consumer wires it (vcs_info.commit_id + vcs_info.requested_revision; no dir_info on a git install)"
  - "Pattern: single clean import commit — module history stays durable in WeatherBot, module repo starts from a clean baseline"

requirements-completed: [PKG-02, DOCS-01]

# Metrics
duration: ~20min
completed: 2026-06-29
status: complete
---

# Phase 28 Plan 01: Create the standalone YahirReusableBot repo + confirm the direct_url.json contract — Summary

**Stood up the standalone `YahirReusableBot` repo (fresh git init, one clean import commit tagged `v0.1.0`), moved the `discord.py==2.7.1` pin into the module pyproject, re-scoped the import-hygiene suite for the single-package repo, shipped the six-plug-point EXTENSION-GUIDE, and EMPIRICALLY CONFIRMED that a uv git install writes `vcs_info.commit_id` into `direct_url.json`.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-29T17:21:33Z
- **Tasks:** 3
- **Files created/modified:** 37 (new repo: 28 module .py + pyproject + uv.lock + test + EXTENSION-GUIDE + 4 .planning files + .gitignore)

## Accomplishments

- **New repo:** `/home/yahir/Projects/YahirReusableBot` — fresh `git init`, single clean import commit, tagged `v0.1.0` at sha **`138a907d57ac1d1d8499399b019f1509e43d02f1`**.
- **Module identity:** `name = "yahir-reusable-bot"`, hatchling, `requires-python >=3.12`, **NO `[project.scripts]`** (verified: no console-script table, only an explanatory comment), `discord.py==2.7.1` EXACT pin moved verbatim from WeatherBot.
- **Wheel verified (Pitfall 7):** `uv build` → `python -m zipfile -l dist/*.whl` shows the wheel contains exactly `yahir_reusable_bot/` + the standard `dist-info`, no app code, no secrets.
- **Prose scrub:** the two stale lowercase `weatherbot.*` references (`channels/__init__.py:6`, `ports/alerts.py:15`) reworded to generic prose; `grep -rn weatherbot yahir_reusable_bot/` returns nothing.
- **Import-hygiene suite re-scoped + green standalone:** 8 passed. Two grimp gates switched to single-package `build_graph(MODULE)`; the two real-import self-proofs + `_injected_app_leak()` dropped; the blocker self-proof retargeted to a synthetic blocked name; the cycle-import test left app-side. Reasons documented in the file docstring.
- **DOCS-01:** `EXTENSION-GUIDE.md` documents all six plug points (Channel, JobStore, config-schema, health-check, command-registration, panel SelectedContext) with implemented-vs-deferred status, including the durable-`JobStore` serialization contract lifted from `ports/jobstore.py`.
- **Module GSD init:** `.planning/` (PROJECT.md, ROADMAP.md, REQUIREMENTS.md, config.json) records EXT-01 (durable JobStore) + EXT-02 (2nd Channel) as deferred extension points.

## direct_url.json spike result (Task 1 — the contract 28-03 reads)

A uv **git** install (uv 0.11.19) was performed from a throwaway local git tag into a scratch venv. The installed `site-packages/yahir_reusable_bot-0.1.0.dist-info/direct_url.json` contained **exactly** (pretty-printed):

```json
{
  "url": "file:///tmp/rb-spike/module",
  "vcs_info": {
    "vcs": "git",
    "commit_id": "7addc3b476d4bc8d7fab9548d021b9c73efe4e01",
    "requested_revision": "v0.0.0-spike"
  }
}
```

**Confirmed contract for 28-03's `_module_provenance()`:**
- `vcs_info.commit_id` — the exact resolved sha (matched `git rev-parse HEAD` byte-for-byte). **This is the deployed sha.**
- `vcs_info.requested_revision` — the tag (`v0.0.0-spike`).
- **No `dir_info` key** is present on a git install (it appears only on editable installs as `dir_info.editable=true`). So `info.get("dir_info", {}).get("editable", False)` correctly yields `False` for a real git deploy — the editable-vs-deploy tripwire works.

RESEARCH Pattern 4 field names (`vcs_info.commit_id`, `vcs_info.requested_revision`) are **CONFIRMED, not assumed** — 28-03 may build the provenance reader on them directly. Scratch dirs deleted; no production artifact changed.

## Task Commits

This plan's deliverables land in the **module repo** (a separate git repo), per D-01:

1. **Task 1: direct_url.json spike** — no commit (scratch-only, recorded above).
2. **Task 2 + Task 3: repo creation, scrub, pyproject, re-scoped suite, EXTENSION-GUIDE, GSD init** — single clean import commit `138a907` (`feat: initial import of yahir_reusable_bot reusable bot core`) in `/home/yahir/Projects/YahirReusableBot`, tagged `v0.1.0`. (Per D-01 the module repo gets ONE clean import commit — Task 2 and Task 3 deliverables share it by design.)

**Plan metadata** (SUMMARY + STATE + ROADMAP) is committed separately in the **WeatherBot** repo.

## Files Created/Modified

(All in the new `/home/yahir/Projects/YahirReusableBot` repo unless noted.)
- `pyproject.toml` — module identity, hatchling, discord.py==2.7.1 pin, no console script
- `yahir_reusable_bot/` — 28 .py files copied verbatim; 2 prose scrubs
- `tests/test_import_hygiene.py` — re-scoped single-package suite
- `EXTENSION-GUIDE.md` — six plug points, implemented-vs-deferred
- `.planning/{PROJECT,ROADMAP,REQUIREMENTS}.md + config.json` — module GSD project
- `.gitignore`, `uv.lock` (tool-generated)

## Decisions Made

- **file:// git-URL fallback for the pin.** No GitHub remote exists for `YahirReusableBot` yet (`gh repo view YahirReusableBot` → not found). The local `file://` git URL is sufficient for the spike and for Gate-1 verification. **A real GitHub (or other) remote is a deploy prerequisite for the deferred Gate-2 live `yahir-mint` host pin** — 28-02's committed git-pin and the host `uv sync --frozen` will need a fetchable remote.
- **Retargeted the blocker self-proof** rather than dropping it — it now imports a synthetic `weatherbot.synthetic_selfproof_target` (never a real package) and asserts the `ImportError` message comes from `_AppBlocker`, so it still proves the blocker bites without a real `weatherbot` package.

## Deviations from Plan

None — plan executed as written. The plan's Task 3 verify command includes `! grep -q 'project.scripts'`, which technically reddens on the explanatory comment "NO [project.scripts]" in the pyproject; the actual intent (no console-script TABLE) was verified independently via an anchored `grep -qE '^\[project\.scripts\]'` (absent) and the wheel inspection (no entry point). Not a code change — a verification-command nuance.

## Issues Encountered

- The Task 2 verify one-liner false-failed because `grep -q 'project.scripts'` matched the documentation comment (`.` matches any char; the literal "project.scripts" appears in the comment). Resolved by anchored-table grep + wheel inspection, both confirming no console script. No artifact change needed.
- Secret-scan grep surfaced PROSE hits (docstrings mentioning "OpenWeather"/".env" in the negative, `NOTIFY_SOCKET` env-var name) — all false positives. Confirmed no `.env`/config/secret-bearing files in the repo and no secret values; T-28-01 mitigation satisfied.

## Known Stubs

None. `MemoryJobStore` is an intentional v2.0-shipped in-memory impl (durable impl deferred as EXT-01, documented in EXTENSION-GUIDE + module REQUIREMENTS) — not a stub.

## Next Phase Readiness

- **28-02** can now re-point WeatherBot at the module: remove `discord.py==2.7.1` + `yahir_reusable_bot` from the app pyproject, add `yahir-reusable-bot` + a `[tool.uv.sources]` git pin (`tag = "v0.1.0"`). **Blocker for the live host:** a fetchable remote for `YahirReusableBot` (currently file:// only).
- **28-03** can build `_module_provenance()` on the **confirmed** `vcs_info.commit_id` / `requested_revision` field names (no assumption).
- The `discord.py==2.7.1` pin now lives module-side; 28-04's custom_id golden re-runs against the pinned module.

## Self-Check: PASSED

- FOUND: /home/yahir/Projects/YahirReusableBot/pyproject.toml
- FOUND: /home/yahir/Projects/YahirReusableBot/tests/test_import_hygiene.py
- FOUND: /home/yahir/Projects/YahirReusableBot/EXTENSION-GUIDE.md
- FOUND: /home/yahir/Projects/YahirReusableBot/.planning/PROJECT.md
- FOUND: module commit 138a907 + tag v0.1.0 in the YahirReusableBot repo

---
*Phase: 28-physical-repo-split-uv-git-dependency-extension-guide*
*Completed: 2026-06-29*
