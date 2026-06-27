---
phase: 19-forecast-two-tier-sub-options
plan: 01
subsystem: interactive-dispatch
status: complete
tags: [dispatch, forecast, panel, additive-seam, byte-identical]
requirements-completed: [PANEL-07]
dependency-graph:
  requires:
    - "weatherbot/interactive/dispatch.py::dispatch_spec (Phase 16 shared seam)"
    - "weatherbot/interactive/command.py::ForecastFlags (frozen dataclass, read-only reuse)"
    - "weatherbot/interactive/command.py::forecast_cache_suffix"
  provides:
    - "dispatch_spec(flags=ForecastFlags|None) — additive pre-built-flags path (D-01)"
  affects:
    - "Plan 02 panel on_forecast → dispatch_spec(spec, None, ..., flags=flags)"
tech-stack:
  added: []
  patterns:
    - "Additive keyword-only param with byte-identical default path (behavior-preserving extension, not refactor)"
    - "if-guard around parse: caller-provided value short-circuits the parser"
key-files:
  created: []
  modified:
    - "weatherbot/interactive/dispatch.py"
    - "tests/test_dispatch.py"
decisions:
  - "D-01: dispatch_spec gains flags=None; non-None skips parse_forecast_flags and uses flags.location + forecast_cache_suffix(spec.name, flags) directly"
  - "D-02: flags=None path byte-identical — the ONLY diff inside the is_forecast block is the 'if flags is None:' guard; dispatch_reply untouched"
metrics:
  duration: "~1 min"
  completed: "2026-06-26"
  tasks: 2
  files: 2
---

# Phase 19 Plan 01: Additive `flags=` Seam on `dispatch_spec` Summary

Extended `dispatch_spec` with a strictly-additive keyword-only `flags: ForecastFlags | None = None` param so the Phase-19 panel can pass a pre-built `ForecastFlags` (skipping `parse_forecast_flags`) while every existing `flags=None` caller stays byte-identical (D-01/D-02).

## What Was Built

- **`dispatch_spec` (`weatherbot/interactive/dispatch.py`)** — added `flags: ForecastFlags | None = None` as the last keyword-only param. Removed the local `flags` initializer (the param default now supplies it) and wrapped the forecast parse in `if flags is None: flags = parse_forecast_flags(arg)`. When a caller supplies flags, the parse is skipped and `lookup_name = flags.location` + `suffix = forecast_cache_suffix(spec.name, flags)` run on the passed dataclass. Docstring gained a Phase-19 additive-seam note. `ForecastFlags` stays under `TYPE_CHECKING` (type-only in the annotation).
- **`tests/test_dispatch.py`** — module-top import of `ForecastFlags`, plus two new nodes:
  - `test_dispatch_spec_flags_passthrough_skips_parse` — a pre-built `ForecastFlags(variant="compact", location="travel")` with a deliberately different `arg="ignored-arg"`; asserts the recorded lookup name is `"travel"` (from `flags.location`, not the arg), the 3-arg suffix is still applied, and the *same* flags object reaches the handler (`is flags`) — proving the parse was bypassed (D-01).
  - `test_dispatch_spec_flags_none_is_byte_identical` — drives `"home +sat"` through both `flags=None` and the no-kwarg call; asserts identical lookup name, identical 3-arg suffix, and equal parsed handler flags (D-02).

## How It Works

`dispatch_reply` already threads `flags` down to `handler(result, flags)` for the `Forecast` group and the tail `run_in_executor` already passes `flags=flags` — so no edit was needed there. The seam is entirely contained in the `dispatch_spec` forecast branch: the new `if flags is None:` guard is the single behavioral fork. On the existing path (`flags=None`) the guard immediately calls `parse_forecast_flags(arg)`, reproducing the prior behavior exactly; on the panel path the guard is skipped and the caller's dataclass drives the lookup. This makes the panel immune to location names containing flag-like tokens (the D-01 rationale for passing a real `ForecastFlags` instead of a re-stringified arg).

## Deviations from Plan

None — plan executed exactly as written. TDD order honored: the two RED nodes (commit `d492168`) failed with `TypeError: unexpected keyword argument 'flags'` before the seam landed, then went GREEN after Task 2 (commit `3a46bcb`).

## Verification

- `uv run pytest tests/test_dispatch.py::test_dispatch_spec_flags_passthrough_skips_parse tests/test_dispatch.py::test_dispatch_spec_flags_none_is_byte_identical -q` → 2 passed.
- `uv run pytest tests/test_dispatch.py tests/test_bot.py tests/test_command.py tests/test_command_views.py tests/test_registry.py -q` → **107 passed** (the contractual anti-drift / byte-identical suite, D-02 guarantee).
- `git diff weatherbot/interactive/dispatch.py` → the ONLY change inside the `is_forecast` block is the `if flags is None:` guard; `dispatch_reply` body unchanged.
- `uv run python -c "import weatherbot.interactive.dispatch"` → exit 0 (no import cycle).
- `uv run ruff check weatherbot/interactive/dispatch.py tests/test_dispatch.py` → All checks passed.

## Threat Mitigations Applied

- **T-19-01-01 (Tampering — seam weakening the parse path):** mitigated — the single guard is the only diff; byte-identical proven by `test_dispatch_spec_flags_none_is_byte_identical` + the full anti-drift suite.
- **T-19-01-02 (cache-key collision):** mitigated — `forecast_cache_suffix(spec.name, flags)` applies identically on both the flags-provided and parsed paths.
- **T-19-01-03 / T-19-01-SC:** accepted per plan (no user-typed string reaches the flags= path; no package install).

No new threat surface introduced (the change is signature-additive, no new endpoint/auth/file/schema).

## Known Stubs

None.

## What This Unblocks

Plan 02's panel forecast path: `dispatch_spec(spec, None, ..., flags=flags)` where the panel builds `ForecastFlags(variant=<"detailed"|"compact">, location=self._selected_location)` directly (PANEL-07 criterion 2).

## Commits

- `d492168` test(19-01): add failing flags= passthrough + flags=None byte-identical nodes
- `3a46bcb` feat(19-01): add additive flags=None param to dispatch_spec (PANEL-07)

## Self-Check: PASSED

- FOUND: weatherbot/interactive/dispatch.py (modified — `flags: ForecastFlags | None = None`)
- FOUND: tests/test_dispatch.py (modified — 2 new nodes + ForecastFlags import)
- FOUND commit: d492168
- FOUND commit: 3a46bcb
