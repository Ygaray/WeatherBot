# Phase 22 Plan 01 — Self-UAT Log

**Plan:** 22-01 (Wave-0 scaffold: `yahir_reusable_bot/` package + import-hygiene gates)
**Run date:** 2026-06-27
**Verifier:** autonomous executor (Gate-1, per CLAUDE.md Two-Gate UAT policy)
**Oracle:** full pytest suite + Phase-21 golden snapshots (byte-identical relocation contract)

This is the autonomous Gate-1 self-UAT. A fully passing Gate-1 completes the work and lets the
phase proceed with no per-phase human pause. The single deferred host obligation (Gate-2,
milestone-close) is recorded at the bottom — it is NOT a phase blocker.

---

## Success Criteria → Evidence

| # | Criterion | Command | Observed | Verdict |
|---|-----------|---------|----------|---------|
| 1 | `yahir_reusable_bot` + 3 subpackages import cleanly | `uv run python -c "import yahir_reusable_bot, yahir_reusable_bot.channels, yahir_reusable_bot.reliability, yahir_reusable_bot.ports"` | imported, no error | PASS |
| 2 | `grimp >= 3.14` installed + importable | `uv run python -c "import grimp; assert tuple(int(x) for x in grimp.__version__.split('.')[:2]) >= (3,14)"` | `grimp 3.14`, assertion holds | PASS |
| 3 | wheel target lists BOTH packages | `grep -A1 'tool.hatch.build.targets.wheel' pyproject.toml` | `packages = ["weatherbot", "yahir_reusable_bot"]` | PASS |
| 4 | coverage source extended | `grep yahir_reusable_bot pyproject.toml` (under `[tool.coverage.run] source`) | `"yahir_reusable_bot"` present | PASS |
| 5 | `[project.scripts]` still only `weatherbot` (module ships none) | `grep -A1 '\[project.scripts\]' pyproject.toml` | only `weatherbot = "weatherbot.cli:main"` | PASS |
| 6 | three gates + three self-proofs green | `uv run pytest tests/test_import_hygiene.py -x` | 6 passed | PASS |
| 7 | grimp gate keeps TYPE_CHECKING default (no `=True`) | `grep -n 'exclude_type_checking_imports' tests/test_import_hygiene.py` | only in docstring prose; no `=True` call arg | PASS |
| 8 | full suite green | `uv run pytest` | **738 passed**, exit 0 (up from 732 baseline: +6 hygiene tests) | PASS |
| 9 | ZERO golden snapshot diff | `git status --porcelain tests/__snapshots__/` | empty (no snapshot changes anywhere) | PASS |

---

## Notes on observed output

- **"2 snapshots failed" in the syrupy summary line is PRE-EXISTING and cosmetic.** Verified by
  moving `tests/test_import_hygiene.py` out of the tree and re-running: the baseline (732 tests,
  no new file) shows the identical `2 snapshots failed. 27 snapshots passed.` line and **exits 0**.
  It is syrupy's unused-snapshot accounting, not a test failure, and is unrelated to this plan. No
  `tests/__snapshots__/` file is modified or untracked (criterion 9).
- **Self-proof test-ordering bug found + fixed (Rule 1).** `test_selfproof_isolated_import_catches_app_import`
  passed in isolation but failed in the full suite: `sys.meta_path` finders are only consulted on a
  `sys.modules` cache MISS, and a prior test had already cached `weatherbot.weather.models`, so the
  import returned the cached object without consulting the `_AppBlocker` (a test-ordering
  false-negative that ALSO left `sys.modules` polluted, breaking two later golden tests). Fix: the
  self-proof now evicts `weatherbot.weather.models` / `weatherbot` from `sys.modules` before
  importing under the blocker, and restores the originals in `finally:` so the cache is left
  byte-identical. Full suite is now 738 passed, exit 0, zero golden diff.

---

## Deferred Gate-2 (milestone-close) — host obligation, NOT a phase blocker

The bot runs as a live editable install on host `yahir-mint` (systemd `weatherbot`). Adding a 2nd
top-level package + the `[tool.hatch.build.targets.wheel]` block changes the editable/wheel
contents, so the host must re-sync for `import yahir_reusable_bot` to resolve at runtime:

```
# on yahir-mint, at milestone close:
uv sync
systemctl restart weatherbot
# confirm: `import yahir_reusable_bot` resolves + daemon comes online (weatherbot online / READY)
```

Pure relocation → no behavior change expected. Tracked as a deferred milestone obligation.

**Gate-1 verdict: PASS** — scaffold + gates land with the full oracle suite green and zero golden diff.
