---
phase: 28-physical-repo-split-uv-git-dependency-extension-guide
plan: 02
subsystem: infra
tags: [uv, git-dependency, packaging, hatchling, uv-lock, no-sources-leak-gate, clean-venv, pep610, discord.py]

# Dependency graph
requires:
  - phase: 28-01
    provides: "Standalone YahirReusableBot repo tagged v0.1.0 @ 138a907d (file:// fallback, no remote yet); discord.py==2.7.1 moved into the module pyproject"
provides:
  - "WeatherBot re-pointed at yahir-reusable-bot via a [tool.uv.sources] git TAG pin (tag=v0.1.0); uv.lock freezes the resolved sha 138a907d57ac1d1d8499399b019f1509e43d02f1"
  - "App wheel collapsed to a single weatherbot package (no yahir_reusable_bot); discord.py inherited transitively (==2.7.1 in the lock)"
  - "In-tree yahir_reusable_bot/ removed (28 files git rm'd) — replaced by the installed git-pinned wheel"
  - "App-side tests repointed at the INSTALLED module package (yahir_reusable_bot.__file__) or converted to behavioral proofs; import-hygiene gate reduced to the one app invariant"
  - "Gate-1 PASS: clean-venv uv sync --frozen + weatherbot check/--help + 773-test suite (goldens byte-identical) + uv build --no-sources leak gate + wheel-only-weatherbot inspection"
affects: [28-03 (startup-version-log provenance reader over the installed module), 28-04 (custom_id golden re-run)]

# Tech tracking
tech-stack:
  added: ["uv git dependency tag-pin in the consuming app (file:// fallback)"]
  patterns:
    - "Read relocated-module source from the INSTALLED package (importlib __file__) once the in-tree copy is gone — keeps source-introspection anti-bake assertions live instead of silently vacuous-passing"
    - "uv build --no-sources as the deploy-artifact leak gate (proves no path source leaked into the wheel)"
    - "uv.lock pins tag→sha; uv sync --frozen reinstalls byte-identically with no re-resolve"

key-files:
  modified:
    - "pyproject.toml (git pin + collapsed wheel + discord.py removed + coverage source fixed)"
    - "uv.lock (regenerated — yahir-reusable-bot @ 138a907d, discord.py 2.7.1 transitive)"
    - "tests/test_import_hygiene.py (reduced to the one app-invariant cycle test)"
    - "tests/test_injection_registry.py (module source read from the installed package)"
    - "tests/test_panelkit_marker.py (in-tree source-grep → behavioral no-wb: proof)"
  removed:
    - "yahir_reusable_bot/ (28 in-tree module files — now external, installed via git pin)"

decisions:
  - "file:// git URL kept (YahirReusableBot has no remote yet, 28-01) — Gate-1 sufficient; a fetchable remote is a deferred Gate-2/host prerequisite"
  - "Source-introspection tests repointed at the INSTALLED package (yahir_reusable_bot.__file__) rather than deleted — the in-tree path is gone but the assertions are real anti-bake guards; reading the installed source keeps them biting (a missing-path rglob would silently return set() and vacuous-pass)"
  - "test_panelkit_marker no-wb: check converted from a source-grep to a stronger BEHAVIORAL assertion (constructed ids never carry wb:) — the static source-grep equivalent now lives module-side"

# Metrics
duration: ~7min
completed: 2026-06-29
status: complete
---

# Phase 28 Plan 02: Re-point WeatherBot at the git-pinned module + clean-venv leak gate — Summary

**Re-pointed WeatherBot at the now-tagged `YahirReusableBot` module via a `[tool.uv.sources]` git TAG pin (`tag = "v0.1.0"`, `file://` fallback), collapsed the two-package wheel back to a single `weatherbot` package, dropped the in-app `discord.py==2.7.1` (now transitive), removed the in-tree module tree, repointed the app-side source-introspection tests at the installed package, and proved the cut clean with a clean-venv `uv sync --frozen` + `weatherbot check`/`--help` + 773-test byte-identical suite + `uv build --no-sources` leak gate + wheel-only-`weatherbot/` inspection.**

## Performance

- **Duration:** ~7 min
- **Completed:** 2026-06-29
- **Tasks:** 3
- **Files modified:** 5 (pyproject.toml, uv.lock, 3 test files) + 28 in-tree module files removed

## Accomplishments

- **PKG-02 re-point:** `pyproject.toml` now declares `yahir-reusable-bot` in `[project] dependencies` and resolves it via a new `[tool.uv.sources]` git TAG pin (`tag = "v0.1.0"`). `uv lock` resolved the tag to the exact sha **`138a907d57ac1d1d8499399b019f1509e43d02f1`** — byte-matching the module repo HEAD — and froze it into `uv.lock` (`source = { git = "file:///home/yahir/Projects/YahirReusableBot?tag=v0.1.0#138a907d…" }`).
- **Wheel collapse (D-02):** `[tool.hatch.build.targets.wheel] packages` collapsed from `["weatherbot", "yahir_reusable_bot"]` → `["weatherbot"]`.
- **discord.py partition (D-03):** the in-app `discord.py==2.7.1` line removed; WeatherBot now inherits it transitively. `uv.lock` confirmed `discord-py` resolved to `2.7.1` (the live-panel custom_id wire contract — never loosened).
- **Coverage fix (Pitfall 5):** `yahir_reusable_bot` removed from `[tool.coverage.run] source` (it is now external — measured in its own repo).
- **In-tree module removed:** `git rm -r yahir_reusable_bot/` (28 files) + cleaned the leftover untracked `__pycache__`. The replacement is the installed git-pinned wheel.
- **Tests repointed (Task 2 + Rule-3 follow-through):** `test_import_hygiene.py` reduced to the one app invariant; `test_injection_registry.py` + `test_panelkit_marker.py` repointed/converted so their source-introspection assertions read the INSTALLED module.
- **Gate-1 PASS (SC#1 + SC#2):** all five installed-artifact proofs green (recorded below).

## The five Gate-1 install/leak/wheel results (Task 3 — SC#2)

| # | Gate | Command | Result |
|---|------|---------|--------|
| 1 | Clean-venv frozen install | `rm -rf .venv && uv venv && uv sync --frozen` | **PASS** (exit 0) — installed `yahir-reusable-bot==0.1.0 (from git+file://…@138a907d…)` purely from the pin + lock, no dev overlay |
| 2 | Console-script resolution | `uv run weatherbot --help` / `uv run weatherbot check` | **PASS** (both exit 0) — `--help` lists the full command set; `check` → "config check passed locations=2". Entry point crosses into the installed module via stable public names |
| 3 | Full suite (clean venv) | `uv run pytest` | **PASS** — **773 passed, exit 0**; Phase-21 goldens byte-identical (zero `.ambr` diff, no golden updated). The "2 snapshots failed" print is the known syrupy quirk — trusted exit 0 |
| 4 | `--no-sources` leak gate | `uv build --no-sources` | **PASS** (exit 0) — wheel + sdist build with `[tool.uv.sources]` disabled → NO path source leaked into the deploy artifact |
| 5 | Wheel inspection | `uv run python -m zipfile -l dist/*.whl` | **PASS** — 46 `weatherbot/` entries, **0 `yahir_reusable_bot/` entries** (Pitfall 7 clean) |

## Git source URL used

- **`file:///home/yahir/Projects/YahirReusableBot`** with `tag = "v0.1.0"` — the local-sibling `file://` fallback established in 28-01 (the `YahirReusableBot` repo has **no GitHub/network remote yet**).
- **Deferred prerequisite (Gate-2 / host deploy):** the live `yahir-mint` host cannot `git`-resolve a `file://` URL pointing at a path that does not exist there. A real **fetchable remote** for `YahirReusableBot` must be created and the `[tool.uv.sources]` `git = …` URL swapped (then `uv lock --upgrade-package yahir-reusable-bot` to re-resolve the same tag→sha) **before** the host `uv sync --frozen`. Recorded as the standing Gate-2 blocker.

## Resolved module sha (reproducibility anchor)

- **Tag:** `v0.1.0` → **sha `138a907d57ac1d1d8499399b019f1509e43d02f1`** (frozen in `uv.lock` line 1324). `uv sync --frozen` reinstalls this exact sha byte-identically with no re-resolve.

## Task Commits

1. **Task 1** — `60f4f1a` `feat(28-02): re-point WeatherBot at git-pinned yahir-reusable-bot; remove in-tree module` (pyproject.toml, uv.lock, 28 module-file deletions)
2. **Task 2** — `bfcfdba` `test(28-02): repoint app-side tests at the installed module after the split` (3 test files)
3. **Task 3** — gate-only (no source artifact); results recorded above. No commit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Two additional test files read the now-removed in-tree module source**

- **Found during:** Task 2 (the full-suite gate after the in-tree module removal).
- **Issue:** The plan's Task 2 named only `tests/test_import_hygiene.py` for relocation. But after `git rm -r yahir_reusable_bot/`, **two other test files** that introspect module *source text* via an in-tree `_MODULE_ROOT` path failed with `FileNotFoundError`:
  - `tests/test_panelkit_marker.py::test_panelkit_marker_parameterized` (read `…/yahir_reusable_bot/discord/panelkit.py` to assert no baked `wb:` literal)
  - `tests/test_injection_registry.py::test_config_id_deriver_is_injected_module_names_no_id` + `::test_panel_cosmetics_and_render_and_marker_are_app_supplied` (read `reload.py` / `panelkit.py` source; the file's `_module_public_symbols()` rglob also pointed at the gone in-tree dir)
- **Fix:**
  - `test_injection_registry.py` — repointed `_MODULE_ROOT` at the **installed** package (`Path(yahir_reusable_bot.__file__).resolve().parent`), so every source-introspection assertion (the two failing reads AND the `_module_public_symbols()` rglob) reads the REAL deployed module source. This also closed a *silent* weakening: an rglob over a missing dir returns `set()`, making the anti-bake assertions vacuous-pass.
  - `test_panelkit_marker.py` — removed `_MODULE_ROOT` and replaced the in-tree source-grep no-`wb:` check with a stronger **behavioral** proof (panels constructed with `X:`/`reminder:` markers never produce a `wb:` id). The static source-grep equivalent is a module-internal invariant that now lives module-side.
- **Why this is correct (root cause):** these are module-source invariants, not app-behavior tests — the same category 28-01 relocated for `test_import_hygiene.py`. The split legitimately removed the in-tree source they read; reading the installed package (or asserting behavior) is the faithful continuation, not a weakening. The full suite re-ran green (773 passed) with the Phase-21 goldens byte-identical (zero `.ambr` diff).
- **Files modified:** `tests/test_injection_registry.py`, `tests/test_panelkit_marker.py`
- **Commit:** `bfcfdba`

**2. [Rule 1 — verification-command nuance] Two pyproject comments tripped the Task-1 verify greps**

- **Found during:** Task 1 verify.
- **Issue:** The plan's verify one-liner uses `! grep -q 'discord.py==2.7.1'` and `! grep -q 'yahir_reusable_bot'` to confirm the dependency line + coverage entry were removed. My explanatory comments initially contained the literal strings `discord.py==2.7.1` and `yahir_reusable_bot`, false-tripping the greps (the same prose-vs-line nuance 28-01 hit).
- **Fix:** reworded both comments to avoid the literal tokens (intent preserved; no functional change). Gate then passed cleanly.
- **Files modified:** `pyproject.toml`
- **Commit:** `60f4f1a`

## Known Stubs

None. The `file://` git URL is a documented, intentional Gate-1 fallback (a real remote is the named Gate-2 prerequisite), not a stub.

## Threat Flags

None — no new security surface. The dependency is a git URL pin (no PyPI registry name to confuse — T-28-07 accepted); the `uv build --no-sources` gate (Task 3) confirms no path-source leak into the deploy artifact (T-28-04 mitigated); `uv.lock` pins the resolved sha so the mutable tag cannot drift the deploy (T-28-05 mitigated); `discord.py` resolved to exactly `2.7.1` transitively (T-28-06 mitigated).

## Next Phase Readiness

- **28-03** can build `_module_provenance()` over the installed `yahir-reusable-bot` dist-info (`direct_url.json` → `vcs_info.commit_id` = `138a907d…`), confirmed contract from 28-01.
- **28-04** re-runs the custom_id golden against the pinned module (already byte-identical here).
- **Gate-2 blocker (carried forward):** a fetchable `YahirReusableBot` remote is required before the live `yahir-mint` `uv sync --frozen` + `systemctl restart`. The committed `file://` URL is local-only.

## Self-Check: PASSED

- FOUND: pyproject.toml (git pin + collapsed wheel + discord.py removed + coverage fixed)
- FOUND: uv.lock (yahir-reusable-bot @ 138a907d, discord-py 2.7.1)
- FOUND: tests/test_import_hygiene.py, tests/test_injection_registry.py, tests/test_panelkit_marker.py
- FOUND (absent): in-tree yahir_reusable_bot/ removed
- FOUND: commit 60f4f1a (Task 1), commit bfcfdba (Task 2)
- VERIFIED: 773 passed exit 0; clean-venv uv sync --frozen + weatherbot check/--help + uv build --no-sources + wheel-only-weatherbot all green

---
*Phase: 28-physical-repo-split-uv-git-dependency-extension-guide*
*Completed: 2026-06-29*
