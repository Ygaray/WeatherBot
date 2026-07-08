---
phase: 22-channel-delivery-reliability-seam-in-place-boundary
plan: 01
subsystem: infra
tags: [packaging, hatchling, grimp, import-hygiene, ast, pytest, uv]

# Dependency graph
requires:
  - phase: 21-characterization-golden-test-harness
    provides: 732-test characterization suite + Phase-21 golden snapshots (the byte-identical oracle) and the test_oracle_selfproof.py self-proof structure
provides:
  - "yahir_reusable_bot/ flat-sibling package skeleton (final name, D-01) with channels/, reliability/, ports/ subpackages"
  - "[tool.hatch.build.targets.wheel] packages block listing both weatherbot and yahir_reusable_bot (D-02)"
  - "grimp>=3.14 dev dependency + extended coverage source"
  - "tests/test_import_hygiene.py: three standing import-hygiene gates (grimp graph, isolated-import smoke, AST litmus) + three self-proofs"
affects: [22-02, 22-03, 23, 24, 25, 26, 27, 28]

# Tech tracking
tech-stack:
  added: [grimp>=3.14 (dev-only)]
  patterns: [grimp-in-pytest import-graph gate, sys.meta_path isolated-import blocker, AST signature-only litmus, perturbation-must-fail self-proof reusing shared gate helpers]

key-files:
  created:
    - yahir_reusable_bot/__init__.py
    - yahir_reusable_bot/channels/__init__.py
    - yahir_reusable_bot/reliability/__init__.py
    - yahir_reusable_bot/ports/__init__.py
    - tests/test_import_hygiene.py
    - .planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-01-SELFUAT.md
  modified:
    - pyproject.toml

key-decisions:
  - "Kept grimp build_graph at its default exclude_type_checking_imports=False so the gate catches TYPE_CHECKING app edges (D-09)"
  - "Self-proofs call the SAME module-level helpers (_scan_app_leaks/_public_names/_AppBlocker) the gates use, not a copy, so a green self-proof proves the real gate logic bites"
  - "Self-proof isolated-import test evicts weatherbot.weather.models from sys.modules before importing under the blocker (meta_path finders only fire on cache miss)"

patterns-established:
  - "grimp-in-pytest one-way dependency gate with prefix check that auto-scales as the module grows across 23-27"
  - "sys.meta_path _AppBlocker for dynamic isolated-import smoke with finally: sys.modules purge"
  - "AST public-name extractor (def/class/arg/annotation/returns, prose-immune) for the D-13 weather-noun litmus"

requirements-completed: [PKG-01]

# Metrics
duration: 9min
completed: 2026-06-27
status: complete
---

# Phase 22 Plan 01: Channel + Delivery-Reliability Seam (in-place boundary scaffold) Summary

**Stood up the final-named `yahir_reusable_bot/` package skeleton, wired hatchling/coverage/grimp config, and landed three standing import-hygiene gates (grimp graph + isolated-import smoke + AST litmus) each proven by a self-proof — full suite 738 green, zero golden diff.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-06-27T23:19:42Z
- **Completed:** 2026-06-27T23:28:xx Z
- **Tasks:** 3
- **Files modified:** 7 (6 created, 1 modified)

## Accomplishments
- Created the flat-sibling `yahir_reusable_bot/` package with its FINAL name in place from day one (D-01 — so Phase 28 is a `git mv`, not a rename) plus the `channels/`, `reliability/`, `ports/` subpackage markers.
- Made three additive `pyproject.toml` edits: a new `[tool.hatch.build.targets.wheel] packages = ["weatherbot", "yahir_reusable_bot"]` block (D-02), `grimp>=3.14` in the dev group (D-09), and `yahir_reusable_bot` appended to `[tool.coverage.run] source` (Pitfall 5) — leaving `requires-python`, `[build-system]`, `[project.scripts]`, `[tool.pytest.ini_options]`, and `[tool.coverage.report] exclude_also` byte-undisturbed.
- Wrote `tests/test_import_hygiene.py` with three standing gates + three self-proofs, all green against the empty scaffold; each self-proof drives the SAME shared helper the gate uses, proving the gate trips on a deliberately-injected leak/noun.
- Full oracle suite is **738 passed** (up from 732: +6 hygiene tests), exit 0, with **zero golden snapshot diff**.

## Task Commits

Each task was committed atomically:

1. **Task 1: Package skeleton + pyproject build/coverage/dev-dep wiring** - `b5edd5d` (feat)
2. **Task 2: Three import-hygiene gates + self-proofs** - `d01c6a4` (test)
3. **Task 3: Self-proof cache-miss fix + self-UAT log** - `1ebac50` (test)

_Task 3 folds in a Rule 1 fix to the Task 2 self-proof (see Deviations) plus the self-UAT artifact._

## Files Created/Modified
- `yahir_reusable_bot/__init__.py` - Package marker + module-boundary docstring (final import root, D-01)
- `yahir_reusable_bot/channels/__init__.py` - Channel-agnostic delivery subpackage marker (scaffold)
- `yahir_reusable_bot/reliability/__init__.py` - Reliability-primitives subpackage marker (scaffold)
- `yahir_reusable_bot/ports/__init__.py` - Host-adapter-seam subpackage marker (scaffold)
- `tests/test_import_hygiene.py` - 3 standing gates (grimp graph / meta_path smoke / AST litmus) + 3 self-proofs sharing the gate helpers
- `pyproject.toml` - hatchling wheel `packages`, grimp dev-dep, coverage source extension (all additive)
- `.planning/.../22-01-SELFUAT.md` - Gate-1 self-UAT log + deferred Gate-2 host obligation

## Decisions Made
- **Kept `exclude_type_checking_imports` at grimp's default (False).** Passing `True` would HIDE the very TYPE_CHECKING app edge the gate exists to catch (RESEARCH Pitfall 1 / Anti-pattern). The `grep` acceptance check confirms no `=True` call argument exists.
- **Self-proofs reuse the gates' own helpers, not copies.** `_scan_app_leaks`, `_public_names`, and `_AppBlocker` are module-level functions/classes that BOTH the gate and its self-proof call — so a green self-proof proves the real gate logic bites, not a parallel reimplementation (mirrors the Phase-21 oracle self-proof discipline).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Self-proof isolated-import test had a sys.modules cache-miss false-negative**
- **Found during:** Task 3 (full-suite self-UAT)
- **Issue:** `test_selfproof_isolated_import_catches_app_import` passed in isolation but failed in the full suite. `sys.meta_path` finders are only consulted on a `sys.modules` cache MISS; a prior test had already cached `weatherbot.weather.models`, so `importlib.import_module` returned the cached object without ever consulting the `_AppBlocker` → the `pytest.raises(ImportError)` went unsatisfied. The aborted import also left `sys.modules` polluted, which broke two later golden tests (the "2 snapshots failed → 1 failed" full-suite state).
- **Fix:** The self-proof now evicts `weatherbot.weather.models` / `weatherbot` from `sys.modules` before importing under the blocker, then restores the originals in `finally:` so the cache is left byte-identical.
- **Files modified:** tests/test_import_hygiene.py
- **Verification:** Full suite now 738 passed, exit 0, zero golden diff; the self-proof passes both in isolation and in full-suite context.
- **Committed in:** 1ebac50 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The fix was necessary for the gate's own correctness (a self-proof that silently passes for the wrong reason defeats its purpose) and to keep the oracle suite green. No scope creep — the gate behavior and scaffold are exactly as planned.

## Issues Encountered
- **Pre-existing cosmetic "2 snapshots failed" syrupy summary line.** Verified by removing the new test file and re-running: the 732-test baseline shows the identical `2 snapshots failed. 27 snapshots passed.` line and exits 0. It is syrupy's unused-snapshot accounting, not a test failure, and is unrelated to this plan (no `tests/__snapshots__/` file is modified or untracked).
- **Plan's `(! grep .)` snapshot-gate idiom is inverted.** With the desired empty input it returns exit 1, with content exit 0 — backwards as a pass-gate. The substantive criterion ("`git status --porcelain tests/__snapshots__/` is EMPTY") is definitively met (verified via `od -c` empty, `wc -l` = 0, no snapshot changes anywhere). Documented, not a real failure.

## Known Stubs
The three subpackages (`channels/`, `reliability/`, `ports/`) are intentionally empty markers this plan — the real relocated `Channel`/`DeliveryResult`, retry engine, and `AlertSink` port land in Plans 22-02 and 22-03. This is by design (Wave-0 scaffold; gates proven against an empty-but-real package first) and documented in the package docstrings.

## User Setup Required
None for the phase. **Deferred Gate-2 (milestone-close, not a phase blocker):** on host `yahir-mint`, `uv sync` → `systemctl restart weatherbot` → confirm `import yahir_reusable_bot` resolves + daemon comes online. Recorded in 22-01-SELFUAT.md.

## Next Phase Readiness
- The boundary + gates are live; Plans 22-02 (channel seam) and 22-03 (reliability seam) can now land real code into `yahir_reusable_bot/` and have each move validated by a standing gate the instant it happens.
- No blockers. The grimp gate's prefix check auto-scales as the module grows across phases 23–27 with no per-module edit.

## Self-Check: PASSED

All created files exist on disk (4 package markers, `tests/test_import_hygiene.py`, `22-01-SELFUAT.md`) and all three task commits (`b5edd5d`, `d01c6a4`, `1ebac50`) are present in git history.

---
*Phase: 22-channel-delivery-reliability-seam-in-place-boundary*
*Completed: 2026-06-27*
