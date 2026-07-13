---
phase: 35-cleanup-sweep
reviewed: 2026-07-13T00:00:00Z
depth: standard
files_reviewed: 28
files_reviewed_list:
  - weatherbot/cli.py
  - weatherbot/config/loader.py
  - weatherbot/config/models.py
  - weatherbot/interactive/bot.py
  - weatherbot/interactive/commands/info.py
  - weatherbot/interactive/commands/weather_views.py
  - weatherbot/interactive/lookup.py
  - weatherbot/ops/pidfile.py
  - weatherbot/ops/selfcheck.py
  - weatherbot/scheduler/context.py
  - weatherbot/scheduler/daemon.py
  - weatherbot/scheduler/uvmonitor.py
  - weatherbot/scheduler/wiring.py
  - weatherbot/weather/client.py
  - weatherbot/weather/models.py
  - weatherbot/weather/multiday.py
  - weatherbot/weather/uv.py
  - tests/test_bot.py
  - tests/test_client.py
  - tests/test_cli.py
  - tests/test_command_views.py
  - tests/test_config.py
  - tests/test_dead_code_removed.py
  - tests/test_filewatch.py
  - tests/test_golden_coverage_fill.py
  - tests/test_multiday.py
  - tests/test_reload.py
  - tests/test_scheduler.py
  - tests/test_uv_monitor.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 35: Code Review Report

**Reviewed:** 2026-07-13
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

Adversarial review of the v2.1 cleanup-sweep phase, focused on the four dead-code removals
(F16 `emit_online`/`_do_reload`, F46 `_argv_is_weatherbot`, F76 `run_weather` verbose param,
F92 discarded `is_transient` call) and the ~48 accepted/fixed low-severity findings, hunting
specifically for (a) orphaned references to removed symbols, (b) rounding/boundary fixes that
are actually wrong, (c) regression tests that don't test what they claim, and (d) any behavior
change to the briefing spine.

**Removals verified clean.** All four dead symbols are gone from live code
(`grep` over `weatherbot/` + `tests/` finds only comment/docstring mentions). No orphaned
callers: `run_self_check`/`AUTH_FAILED`/`CONFIG_INVALID`/`SystemdNotifier`/`stamp_health` are
still correctly re-exported from `daemon.py` for `wiring.py`; `selfcheck.py` correctly dropped
the `is_transient` *import* (F92) while keeping `is_auth_failure`; `pidfile.py` cleanly
delegates to the hub `is_running_process`. The relevant test subset (112 tests across the 5
phase-central suites) runs green. The briefing-spine exactly-once invariant is intact — no
removal touched `fire_slot`'s claim/release path.

The findings below are all pre-existing-quality or test-strength concerns surfaced during the
sweep, not regressions introduced by it. No blockers.

## Warnings

### WR-01: `test_dead_code_removed.py` gates are non-enforcing — they pass whether the symbol was removed or not

**File:** `tests/test_dead_code_removed.py:87,125,152,174-180`
**Issue:** Every assertion in this "drift-back gate" is `count <= 1` (or `<= 1` per file),
explicitly documented as "start-state-green" so it is GREEN both when the symbol still exists
(count 1) AND when removed (count 0). That means the suite that is supposed to *prove the F16/F46/F76/F92
removals landed and never drift back* cannot actually detect a removal that silently *didn't
happen* — a plan that forgot to delete `emit_online` would leave this test green. The gate only
catches the narrow "reappears at a SECOND site" drift, not "was never removed" or "was
re-added at the same site." For a cleanup phase whose entire deliverable is these removals, the
regression net has a hole exactly where the risk is.

Note this is confirmed empirically: the removals *did* land (verified by direct grep), so the
tests are green for the right reason today — but they would stay green for the wrong reason if a
future edit reintroduced any of the four at its original site.

**Fix:** Split each into a post-removal enforcing assertion now that the removals are in.
For the symbols that must be absent from production source, assert `== 0`:
```python
# F16 — after Plan 08 landed, the dead defs must be GONE, not merely "<= 1".
assert emit_hits == 0, f"F16: {emit_def!r} must be removed; found {emit_hits}"
assert reload_hits == 0, f"F16: {reload_def!r} must be removed; found {reload_hits}"
```
Apply the same `== 0` tightening to the F46 pidfile count, the F76 signature-region count,
and the F92 discarded-call count. Keep the docstring's "drift-back" framing but make the
budget enforce the end state, not the transitional one.

### WR-02: `select_days` recomputes `upcoming` identically in the else branch — dead-ish duplication that obscures the roll-forward logic

**File:** `weatherbot/weather/multiday.py:108-115`
**Issue:** `upcoming` is computed on line 108, then in the `else` branch (line 114-115) it is
recomputed with the byte-identical list comprehension `[delta for delta in base_deltas if delta >= 0]`.
The `if base_tokens and not upcoming:` branch reassigns `base_deltas` and `upcoming`; the `else`
re-derives the same value line 108 already holds. It is not a correctness bug (the value is
identical), but it is confusing dead computation in the one module whose entire job is the
window/roll-forward rule — a reader cannot tell whether the else-branch recomputation is
load-bearing or redundant, which is exactly the kind of ambiguity a cleanup sweep should retire.

**Fix:** Drop the redundant recomputation; the `else` branch can be removed entirely since
`upcoming` already holds the still-upcoming set from line 108:
```python
base_deltas = [(_WD_INDEX[d] - today_wd) for d in base_tokens]
upcoming = [delta for delta in base_deltas if delta >= 0]
if base_tokens and not upcoming:
    # Whole block is in the past → roll the entire block to next week.
    base_deltas = [delta + 7 for delta in base_deltas]
    upcoming = base_deltas
```

## Info

### IN-01: `_hints` uses truthy `or 0.0` coalesce on display temps while claiming None-safety — inconsistent with the WR-01 hint guard it sits beside

**File:** `weatherbot/weather/models.py:345-348`
**Issue:** `feels_imp = feels_imp_raw or 0.0` and `wind_imp = wind_imp_raw or 0.0` coerce a
legitimate `0.0` (or `0`) reading to `0.0` via truthiness — harmless for these display fields
(0 displays as 0), and the code comment correctly notes the *hints* read the None-preserving
`_raw` values instead. This is already an accepted pattern (F62 annotation on line 334 covers
the sibling `uvi_max` coalesce). Flagged only because the `or`-coalesce idiom appears repeatedly
across `from_payloads` (temp_imp, humidity, etc.) and a future reader may copy it into a field
where a real `0` matters. Not a bug today.

**Fix:** No change required; if touched later, prefer explicit `x if x is not None else 0.0`
for any field where `0` is a meaningful reading, to make the None-vs-zero distinction local.

### IN-02: `ScheduleContext` is documented as "frozen-ish" but is a mutable `@dataclass`

**File:** `weatherbot/scheduler/context.py:29-42`
**Issue:** The module docstring (line 12) calls the value object "a frozen-ish dataclass that
travels through the pipeline," and it mirrors `DeliveryResult`, but the class is a plain
`@dataclass` (not `frozen=True`) — so `ctx.late = True` mutation is silently allowed. Every
other config/value model in the codebase (`Schedule`, `Location`, `UvSummary`, etc.) is
`frozen=True`. The "frozen-ish" wording invites a false safety assumption. Threading a mutable
context through fetch→render→persist is a latent footgun if any future code mutates it mid-fire.

**Fix:** Make the invariant real: `@dataclass(frozen=True)`. It carries only immutable fields
(`datetime | None`, `ZoneInfo`, `bool`), so freezing is free and matches the house style.

### IN-03: `worst_case_seconds` jitter-ceiling arithmetic is duplicated between the method and the error-message branch

**File:** `weatherbot/config/models.py:329-330,338-340`
**Issue:** `_budget_under_grace` recomputes `per_retry = max((burst_spread/(n-1))*1.5, RETRY_AFTER_CAP_S)`
(lines 338-340) for its error message — the same expression `worst_case_seconds` already
computed via `within_max`/`per_retry` (lines 329-330). The docstring for `worst_case_seconds`
explicitly says it is the "single source of truth," but the validator re-derives the inner term
instead of reusing it, so a future change to the jitter model must be edited in two places or
the error message silently drifts from the enforced value.

**Fix:** Have `worst_case_seconds` return (or expose) the `per_retry` term, or recompute the
message string from the already-computed `worst` rather than re-deriving `per_retry`, so the
"single source of truth" claim holds literally.

## Structural Findings (fallow)

None provided for this review (no `<structural_findings>` block in the prompt).

## Notes on Known / Accepted Items (not re-reported)

- The 3 pre-existing ruff nits in `daemon.py` (F401 unused `ReloadEngine` L67 + `PID_FILE` L68,
  F841 unused `notifier` L1373) are in the disposition ledger and pre-date this phase — confirmed
  present, deliberately not re-reported per review scope.
- The `# ACCEPTED (F##, v2.1): ...` annotations (F51/F52/F53/F56/F57/F58/F59/F62/F67/F71/F72/F73/F77/F83/F103)
  were each read; their rationales are sound and were not flagged.
- The `name="​"` (zero-width-space) embed-field label in `bot.py:304` is a legitimate documented
  Discord idiom (empty left-aligned field), not an injection — the injection-scan LOW hit is a
  false positive.

---

_Reviewed: 2026-07-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
