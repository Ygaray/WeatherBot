---
phase: 10-file-watch-auto-reload
plan: 02
subsystem: config
tags: [dependency, config, file-watch, pydantic, reload-toggle]
requirements-completed: [CFG-03]
dependency-graph:
  requires: ["10-01"]
  provides:
    - "watchfiles>=1.2.0 runtime dependency (importable)"
    - "ReloadConfig frozen model (extra=forbid, watch: bool = True)"
    - "Config.reload default-factory field (D-03 toggle, ON by default)"
  affects: ["10-03"]
tech-stack:
  added:
    - "watchfiles 1.2.0 (Rust notify-backed file watcher, D-01)"
  patterns:
    - "frozen extra=forbid pydantic config model mirroring Reliability"
    - "Field(default_factory=...) optional config sub-table"
key-files:
  created: []
  modified:
    - "pyproject.toml"
    - "uv.lock"
    - "weatherbot/config/models.py"
decisions:
  - "D-01: watchfiles>=1.2.0 added as a runtime dep (not dev) via uv add, alphabetical after tenacity."
  - "D-03: [reload] watch toggle defaults ON; ReloadConfig is frozen+extra=forbid so unknown keys fail loud (T-10-03)."
metrics:
  duration: "~1 min"
  completed: "2026-06-16"
  tasks: 2
  files: 3
---

# Phase 10 Plan 02: watchfiles dep + ReloadConfig toggle Summary

Added the two foundation pieces Plan 10-03's observer wiring depends on: the `watchfiles>=1.2.0` runtime dependency and a frozen, ON-by-default `[reload] watch` config toggle (`ReloadConfig` + `Config.reload`), structurally identical to the existing `Reliability` / `Config.reliability` pattern.

## What Was Built

- **`watchfiles>=1.2.0` runtime dependency (Task 1)** — added via `uv add watchfiles>=1.2.0` (NOT pip, NOT `--dev`). Landed in `[project.dependencies]` alphabetically after `tenacity`; `uv.lock` regenerated with `watchfiles==1.2.0`. Importable (`watchfiles.__version__ == "1.2.0"`) and the daemon import smoke (`import weatherbot.scheduler.daemon`) stays green.
- **`ReloadConfig` model + `Config.reload` field (Task 2)** — new `ReloadConfig(BaseModel)` beside `Reliability` with `model_config = ConfigDict(extra="forbid", frozen=True)` and a single `watch: bool = True` field. Added `reload: ReloadConfig = Field(default_factory=ReloadConfig)` to `Config`, mirroring the `reliability` field exactly. No new imports. The debounce window stays a module constant in daemon.py (D-05), not config.

## Checkpoint Resolution

The plan's first task (10-02-CK, `checkpoint:human-verify` gate=blocking-human) was **PRE-APPROVED** by the orchestrator before this execution (auto/chain mode). `watchfiles` legitimacy was confirmed via Phase 10 research: PyPI `watchfiles` 1.2.0 (published 2026-05-18), `Requires-Python >=3.10` (satisfies project `>=3.12`), maintainer `samuelcolvin` (pydantic author), Rust `notify` backend, official source github.com/samuelcolvin/watchfiles — not a typosquat. The executor proceeded straight to `uv add` per the pre-authorization; no human pause was required.

## Verification

- `uv run python -c "import watchfiles; print(watchfiles.__version__)"` → `1.2.0`.
- `grep -c 'watchfiles>=1.2.0' pyproject.toml` → `1` (in `[project.dependencies]`, not `[dependency-groups].dev`).
- `uv run python -c "import weatherbot.scheduler.daemon"` → exit 0.
- `uv run pytest tests/test_models.py` → 27 passed (no regression).
- `Config(locations=[]).reload.watch is True` (default ON); `ReloadConfig(watch=False).watch is False`.
- `ReloadConfig(foo=1)` raises `pydantic.ValidationError` (extra forbidden).
- Rebinding `cfg.reload = ...` raises `pydantic.ValidationError` of type `frozen_instance` (NOT `dataclasses.FrozenInstanceError`).
- `tests/test_filewatch.py::test_watch_toggle_off_no_observer` → passed (the `Config.reload` AttributeError is resolved; observer-dependent nodes remain RED for Plan 10-03 as planned).

## Deviations from Plan

None - plan executed exactly as written.

## Threat Mitigations Applied

- **T-10-SC (supply chain):** watchfiles legitimacy verified before install (pre-approved checkpoint; PyPI author/version/source/non-typosquat confirmed).
- **T-10-03 (unknown config key):** `extra="forbid"` on `ReloadConfig` rejects unknown `[reload]` keys at load (fail-loud) — verified.
- **T-10-04 (secrets in toggle):** `ReloadConfig` carries only a bool `watch`; no secret field (CONF-02 preserved).

## For the Next Plan (10-03)

`watchfiles` is importable and `Config.reload.watch` exists ON-by-default. Plan 10-03 wires the observer (`_run_watch_observer` / `_derive_watch_dirs` / `_make_watch_filter`) that reads `config.reload.watch` to decide whether to start, with the debounce window as a daemon.py module constant (D-05). The remaining `tests/test_filewatch.py` nodes stay RED until that observer lands.

## Self-Check: PASSED
