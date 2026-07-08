---
phase: 22-channel-delivery-reliability-seam-in-place-boundary
reviewed: 2026-06-27T00:00:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - pyproject.toml
  - tests/test_import_hygiene.py
  - weatherbot/channels/base.py
  - weatherbot/reliability/__init__.py
  - weatherbot/reliability/retry.py
  - yahir_reusable_bot/__init__.py
  - yahir_reusable_bot/channels/__init__.py
  - yahir_reusable_bot/channels/base.py
  - yahir_reusable_bot/ports/__init__.py
  - yahir_reusable_bot/ports/alerts.py
  - yahir_reusable_bot/reliability/__init__.py
  - yahir_reusable_bot/reliability/retry.py
findings:
  critical: 2
  warning: 2
  info: 2
  total: 6
status: resolved
---

# Phase 22: Code Review Report

> **Resolution (2026-06-27, commit `9d0fe21`):** Both BLOCKERs FIXED and independently proven.
> CR-01 — grimp gate now builds `build_graph(MODULE, APP, cache_dir=None)` and scans
> module-owned importers; CR-02 — isolated-import gate now evicts the `weatherbot.*` namespace
> from `sys.modules` before the blocked walk. A third defect surfaced while fixing: grimp's
> default on-disk cache (`.grimp_cache/`) served a stale leaky graph — disabled via
> `cache_dir=None` (a correctness gate must read source fresh) and the cache dir is now
> gitignored. Two REAL-gate self-proofs were added (`test_selfproof_*_real_app_edge`) that inject
> a genuine module-level `import weatherbot.*` and assert the actual gate wiring reddens. Verified
> by independent injection: with a real leak in `channels/base.py`, BOTH main gates FAIL (grimp +
> isolated-import-in-full-suite); reverted → all green. Full suite 740 passed, zero golden diff.
> WR-01 resolved as a consequence (litmus is again a complementary third layer). WR-02
> intentionally NOT changed — `retry.py` is a verbatim move (D-06); preserving the original import
> order is correct and ruff is not a gate here.

**Reviewed:** 2026-06-27
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

This phase relocates the channel-agnostic `Channel` seam and the two-burst retry
primitives into the new `yahir_reusable_bot/` package, leaving byte-identical re-export
shims in `weatherbot/`. The **relocation and shimming themselves are correct** — I
verified every identity/structural contract at runtime:

- `weatherbot.channels.Channel IS weatherbot.channels.base.Channel`, is a *subclass*
  of the module `Channel`, and carries the app-side `send_briefing`. `DiscordWebhookChannel`
  is a subclass of both, so there is exactly ONE `Channel` identity for `isinstance`.
- `weatherbot.reliability(.retry)` re-exports the IDENTICAL objects from the module
  (`is_transient is is_transient`, `RETRY_AFTER_CAP_S` and `PERMANENT` identical), so
  the Phase-21 exception-identity pins and `config.models`'s `RETRY_AFTER_CAP_S` import
  stay valid.
- `AlertSink` is `runtime_checkable`, weather-clean (neutral `target`/`db_path` names),
  and the real `weatherbot.weather.store` module *structurally satisfies it* at runtime
  (`isinstance(store, AlertSink) is True`); its signatures match the daemon call sites
  positionally.
- `pyproject.toml` wheel `packages` lists BOTH `weatherbot` and `yahir_reusable_bot`;
  coverage `source` includes `yahir_reusable_bot`.
- `retry.py` is byte-identical to the pre-move original (same import block, same logic).

**However, the import-hygiene GATES — the entire point of this phase's "standing boundary"
— are NOT sound.** Both the grimp gate and the dynamic isolated-import gate **false-pass
on a real `import weatherbot.*` leak** in the normal full-suite run. I proved this by
injecting a genuine module-level `import weatherbot.config.models` into
`yahir_reusable_bot/channels/base.py` and watching both gates stay green. The litmus gate
(Gate 3) is sound. The self-proofs are green but prove only that the *helpers* work on
*synthetic* inputs — they do not exercise the real gate's wiring, which is where both bugs
live. These are BLOCKERs because the phase ships a guard that does not guard.

## Critical Issues

### CR-01: grimp gate (`test_module_imports_zero_app_code`) cannot detect a real app leak — single-package build

**File:** `tests/test_import_hygiene.py:133`
**Issue:**
The gate builds the graph with only the module package:

```python
graph = grimp.build_graph(MODULE)  # MODULE == "yahir_reusable_bot"
```

`grimp.build_graph("yahir_reusable_bot")` only graphs edges *between modules inside that
package*. An import that points at `weatherbot.*` (a different top-level package, not in the
build set) is **not graphed at all** — `find_modules_directly_imported_by` returns an empty
set for the leaking module, so `_scan_app_leaks` sees nothing and the gate passes.

Proven directly: I prepended `import weatherbot.config.models` to
`yahir_reusable_bot/channels/base.py` and ran the exact gate logic:

```
Gate1 leaks with single-pkg build: []          # FALSE PASS — real leak undetected
With both pkgs:  [('yahir_reusable_bot.channels.base', 'weatherbot.config.models')]  # caught
```

The self-proof (`test_selfproof_import_gate_catches_injected_app_edge`) passes only because
it feeds `_scan_app_leaks` a hand-built dict that *already contains* a `weatherbot.*` edge —
it never builds a real grimp graph, so it cannot reveal that the real graph never produces
such an edge. The docstring's claim that this gate "catches a type-only app import (e.g. the
historic `Forecast` leak)" is false as written.

**Fix:** Build the graph over BOTH packages so internal `weatherbot.*` edges are graphed, and
restrict the leak scan to module-owned importers:

```python
graph = grimp.build_graph(MODULE, APP)  # graph internal weatherbot.* targets too
edges = {
    module: graph.find_modules_directly_imported_by(module)
    for module in graph.modules
    if module == MODULE or module.startswith(MODULE + ".")
}
leaks = _scan_app_leaks(edges)
```

(Alternatively `grimp.build_graph(MODULE, include_external_packages=True)`, which graphs the
top-level `weatherbot` edge — but the two-package build also preserves the submodule-level
detail the failure message relies on.) Then ADD a regression self-proof that injects a real
leak into a temp module and asserts the *full gate* (real `build_graph`) goes red — the
current synthetic-dict self-proof would not have caught this bug.

### CR-02: isolated-import gate (`test_module_imports_with_app_blocked`) false-passes in the full suite — no `sys.modules` eviction

**File:** `tests/test_import_hygiene.py:172-190`
**Issue:**
The dynamic gate installs an `_AppBlocker` on `sys.meta_path` and then imports every module
under `yahir_reusable_bot`. But `sys.meta_path` finders are consulted **only on a
`sys.modules` cache MISS**. By the time this test runs in the full suite, earlier alphabetical
tests (`test_cache.py`, `test_channel.py`, `test_cli.py`, …) have already imported
`weatherbot` and many `weatherbot.config.*`/`weatherbot.weather.*` submodules into
`sys.modules`. So a real module-level `import weatherbot.config.models` inside the module
resolves straight from cache — the blocker is never consulted — and the gate passes.

Proven directly:

- Injected `import weatherbot.config.models` into `yahir_reusable_bot/channels/base.py`, ran
  the full `test_import_hygiene.py` →
  `test_module_imports_with_app_blocked` **PASSED** (leak undetected).
- The SAME gate logic in a *fresh* interpreter (clean cache) correctly raised
  `ImportError: BLOCKED weatherbot` — confirming the only reason it passes in-suite is cache
  pollution.

This is exactly the "test-ordering false-negative" the *self-proof*
(`test_selfproof_isolated_import_catches_app_import`, lines 193-222) goes to great lengths to
avoid — it evicts `weatherbot`/target from `sys.modules` before importing under the blocker.
But the **real gate does not do that eviction**, so the self-proof proves the mechanism on a
clean cache while the real gate runs on a polluted one and is defeated. The self-proof's own
docstring describes this trap and then the real gate falls into it.

**Fix:** Evict the app namespace from `sys.modules` *before* walking under the blocker, and
restore it in `finally` (mirror the self-proof's save/restore so other tests re-import the
real app cleanly):

```python
blocker = _AppBlocker()
saved_app = {k: sys.modules[k] for k in list(sys.modules)
             if k == APP or k.startswith(APP + ".")}
for k in saved_app:
    del sys.modules[k]
sys.meta_path.insert(0, blocker)
try:
    pkg = importlib.import_module(MODULE)
    for info in pkgutil.walk_packages(pkg.__path__, prefix=MODULE + "."):
        importlib.import_module(info.name)
finally:
    sys.meta_path.remove(blocker)
    for key in [k for k in sys.modules if k.startswith(MODULE)]:
        del sys.modules[key]
    # drop any partial app entry the blocked import may have left, then restore
    for key in [k for k in sys.modules if k == APP or k.startswith(APP + ".")]:
        del sys.modules[key]
    sys.modules.update(saved_app)
```

Also extend the gate's own self-proof to inject a real module-level app import and assert the
*full gate* (not just the bare blocker) goes red under realistic (pre-populated) cache
conditions.

## Warnings

### WR-01: Module-level app leaks rely entirely on the litmus gate, which only scans NAMES

**File:** `tests/test_import_hygiene.py:230-243`
**Issue:**
With CR-01 and CR-02 both blind to a real leak, Gate 3 (AST litmus) is the *only* gate that
could trip on, e.g., `import weatherbot.config.models` — and it would only trip if the import
introduced a weather *noun* into a public signature name. A leak like
`from weatherbot.ops.paths import db_path` (neutral names) would pass ALL THREE gates today.
This is a direct consequence of CR-01/CR-02; once those are fixed the litmus is correctly a
*complementary* third layer rather than the accidental sole survivor. Flagging so the fix for
CR-01/CR-02 is treated as restoring real coverage, not a nicety.
**Fix:** Fix CR-01 and CR-02; after that, the litmus stays as-is (it is sound for its stated
name-scan purpose).

### WR-02: `parse_retry_after` import ordering is non-standard (cosmetic, but flagged by ruff config)

**File:** `yahir_reusable_bot/reliability/retry.py:42-43`
**Issue:**
```python
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
```
`datetime` (d) sorts before `email` (e); the stdlib import block is out of isort order. This
is byte-identical to the pre-move original (so the relocation faithfully preserved it), but
the repo declares `ruff>=0.15.16` as a dev tool and ruff's isort rule (`I001`) would flag this.
Not a correctness issue.
**Fix:** Reorder to `from datetime import datetime, timezone` then
`from email.utils import parsedate_to_datetime`, or run `ruff check --fix`. Confirm it does not
break any byte-identity snapshot first (it is import order only, no behavior change).

## Info

### IN-01: `pragma: no cover` guard documents a branch that the coverage config also excludes

**File:** `yahir_reusable_bot/reliability/retry.py:125`
**Issue:**
The `if dt is None:` guard carries `# pragma: no cover` AND the prose says CPython 3.12
`parsedate_to_datetime` never returns `None`. The branch is genuinely unreachable on the
pinned runtime (defensive cross-version guard). Harmless; noted only because it is dead on
this interpreter.
**Fix:** None required — keep as a documented cross-version guard.

### IN-02: Litmus `\buv\b` gap is documented but worth a tracking note for later phases

**File:** `tests/test_import_hygiene.py:55-60`
**Issue:**
The litmus pattern's `\buv\b` will not match `uv_index` (underscore is a `\w`, so no word
boundary). The code documents this as an intentional limitation of the D-13 locked literal,
and the currently-moving surface has no `uv` names — so the gate is clean today. But phases
23-27 move more surface; a `uv_index`-named param could slip through. This is correctly a
documented known-gap, not a phase-22 bug.
**Fix:** None for phase 22. Track for the phase that relocates UV-monitor surface — consider
broadening to `(?<![\w])uv(?![\w])` semantics or an explicit `uv_` prefix alternation if/when
UV names enter the module.

---

_Reviewed: 2026-06-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
