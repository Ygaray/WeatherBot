---
phase: 22-channel-delivery-reliability-seam-in-place-boundary
plan: 03
subsystem: reliability
tags: [reliability-seam, retry-engine, alertsink-port, relocation, import-hygiene, shim, byte-identical, grimp, ast-litmus, protocol]

# Dependency graph
requires:
  - phase: 22-channel-delivery-reliability-seam-in-place-boundary
    plan: 01
    provides: yahir_reusable_bot/ skeleton (reliability/ + ports/ subpackages) + three standing import-hygiene gates (grimp graph, isolated-import smoke, AST litmus) + the Phase-21 byte-identical oracle
  - phase: 22-channel-delivery-reliability-seam-in-place-boundary
    plan: 02
    provides: the channels seam + the re-export-shim pattern this plan mirrors for reliability
provides:
  - "yahir_reusable_bot/reliability/retry.py — the two-burst retry engine moved VERBATIM (build_retrying, is_transient/is_auth_failure, parse_retry_after, two_burst_wait, the BURST_*/MID_PAUSE_S/RETRY_AFTER_CAP_S constants, PERMANENT/TRANSIENT frozensets, REASON_* taxonomy), zero weather coupling (D-06)"
  - "yahir_reusable_bot/reliability/__init__.py — the 7-name public re-export surface (identical to the original app __init__)"
  - "yahir_reusable_bot/ports/alerts.py — the AlertSink typing.Protocol (record_alert/resolve_alert) with weather-clean param names (location_name -> target), no briefing_missed/heartbeat (D-07/D-08)"
  - "yahir_reusable_bot/ports/__init__.py — exports AlertSink"
  - "weatherbot/reliability/__init__.py + retry.py — app-side re-export shims (retry.py re-exports the FULL surface incl. constants so config.models + test_reliability + Phase-21 pins stay byte-identical)"
  - "reliability + ports seams of the grimp/litmus/isolated-import gate are now green (zero yahir_reusable_bot.{reliability,ports}.* -> weatherbot.* edges)"
affects: [23, 24, 25, 26, 27, 28]

# Tech tracking
tech-stack:
  added: []
  patterns: [re-export shim keeps importers byte-identical, app-side shim re-exports the FULL surface (constants + functions) so direct-by-name importers resolve to IDENTICAL objects, typing.Protocol port with renamed weather-clean param names while the app impl keeps its noun, fire_slot ADAPTED not rewritten (orchestration byte-identical)]

key-files:
  created:
    - yahir_reusable_bot/reliability/retry.py
    - yahir_reusable_bot/ports/alerts.py
    - .planning/phases/22-channel-delivery-reliability-seam-in-place-boundary/22-03-SELFUAT.md
  modified:
    - yahir_reusable_bot/reliability/__init__.py
    - yahir_reusable_bot/ports/__init__.py
    - weatherbot/reliability/__init__.py
    - weatherbot/reliability/retry.py

key-decisions:
  - "App-side weatherbot/reliability/retry.py shim re-exports the FULL surface (BURST_SIZE/BURST_SPREAD_S/MID_PAUSE_S/RETRY_AFTER_CAP_S/PERMANENT/TRANSIENT/two_burst_wait + the 7 public names), not just the 7 public names, because config/models.py imports RETRY_AFTER_CAP_S and test_reliability.py imports the constants + two_burst_wait directly from weatherbot.reliability.retry — all must resolve to the IDENTICAL module objects"
  - "AlertSink port param renamed location_name -> 'target' (NOT 'location_id') because the D-13 litmus pattern matches 'location' as a substring — 'location_id' would trip the gate; the app store impl keeps location_name unchanged"
  - "AlertSink made runtime_checkable so the existing weatherbot.weather.store functions satisfy it structurally with zero subclassing/registration; fire_slot keeps importing record_alert/resolve_alert directly from the store (D-07 — the port documents the module's contract, full composition-root injection is Phase 25/APP-02)"
  - "fire_slot ADAPTED not rewritten: zero source change at the build_retrying call, the four record_alert calls, the resolve_alert call, or the reason-taxonomy except branches — build_retrying/is_auth_failure now resolve through the weatherbot.reliability shim with no call-site edit"

requirements-completed: [SEAM-01, PKG-01]

# Metrics
duration: 8min
completed: 2026-06-27
status: complete
---

# Phase 22 Plan 03: Reliability Seam — Retry Engine + AlertSink Port (byte-identical extraction) Summary

**Moved the entire two-burst retry engine VERBATIM into `yahir_reusable_bot.reliability` (it was already 100% weather-clean — zero `weatherbot.*` edges, pure tenacity/httpx/structlog/stdlib), defined the weather-clean `AlertSink` Protocol in `yahir_reusable_bot.ports`, and re-exported the moved surface through byte-identical `weatherbot.reliability` shims so the daemon/CLI imports and the Phase-21 exception-identity pins stay unchanged — full 738-test oracle green, zero golden diff, all three import-hygiene gates green over the complete moved module (channels + reliability + ports).**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-06-27T23:40:29Z
- **Tasks:** 3
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments
- Moved `weatherbot/reliability/retry.py` VERBATIM into `yahir_reusable_bot/reliability/retry.py` (D-06) — the import block, all constants (`BURST_SIZE`/`BURST_SPREAD_S`/`MID_PAUSE_S`/`RETRY_AFTER_CAP_S`), the `PERMANENT`/`TRANSIENT` frozensets, the `REASON_*` taxonomy, and every function (`is_transient`, `is_auth_failure`, `parse_retry_after`, `_within_burst_wait`, `two_burst_wait`, `build_retrying`) carried unchanged, INCLUDING the `# pragma: no cover - <reason>` comment (Phase-21 D-09 convention). The module source contains no `weatherbot` reference.
- Copied the 7-name re-export body into `yahir_reusable_bot/reliability/__init__.py` (identical to the original).
- Converted `weatherbot/reliability/__init__.py` into a re-export shim (same `__all__`) and made `weatherbot/reliability/retry.py` re-export the FULL surface from the module so the direct-by-name importers (`config/models.py` → `RETRY_AFTER_CAP_S`; `test_reliability.py` → the constants + `two_burst_wait`; the Phase-21 `is_transient` identity pin) all resolve to the IDENTICAL objects with zero call-site churn.
- Defined `yahir_reusable_bot/ports/alerts.py`: an `AlertSink` `typing.Protocol` exposing exactly `record_alert(...) -> bool` and `resolve_alert(...) -> None`, with the store's `location_name` renamed to the litmus-clean `target` in the PORT signature (D-11), arg types `str | os.PathLike[str]` / `str` / `bool` only — NO `briefing_missed`, NO heartbeat (D-08). Made it `runtime_checkable` so the app store satisfies it structurally.
- Left `fire_slot` byte-identical (D-07 — ADAPT not rewrite): the `build_retrying` call, the four `record_alert` calls, the `resolve_alert` call, and the reason-taxonomy except branches are unchanged; `build_retrying`/`is_auth_failure` now resolve through the shim with no source edit. Heartbeat (`_heartbeat_tick`/`__heartbeat__`/`stamp_tick`) untouched (D-08 — Phase 25).
- Full oracle suite **738 passed** (exit 0) with **zero golden snapshot diff** (`git status --porcelain tests/__snapshots__/` = 0 bytes). All three import-hygiene gates + their self-proofs + the oracle self-proof green over the complete moved surface; the grimp graph now includes `reliability.retry` + `ports.alerts` with **zero app leaks**.

## Task Commits

Each task was committed atomically:

1. **Task 1: Move the retry engine verbatim + shim weatherbot.reliability** — `25cfdc0` (feat)
2. **Task 2: Define the weather-clean AlertSink port; fire_slot byte-identical** — `050a3a4` (feat)
3. **Task 3: Self-UAT — full oracle suite byte-identical green over the extraction** — `07657c9` (test)

## Files Created/Modified
- `yahir_reusable_bot/reliability/retry.py` (created) — verbatim move of the two-burst retry engine (weather-clean, D-06)
- `yahir_reusable_bot/reliability/__init__.py` (modified) — the 7-name public re-export surface
- `yahir_reusable_bot/ports/alerts.py` (created) — the `AlertSink` Protocol (record_alert/resolve_alert, weather-clean param names, D-07)
- `yahir_reusable_bot/ports/__init__.py` (modified) — exports `AlertSink`
- `weatherbot/reliability/__init__.py` (modified) — app-side re-export shim (same `__all__`)
- `weatherbot/reliability/retry.py` (modified) — app-side re-export shim of the FULL surface (constants + functions) → identical objects
- `.planning/.../22-03-SELFUAT.md` (created) — Gate-1 self-UAT log + standing-gate status (D-13) + deferred Gate-2 host obligation

## Decisions Made
- **The app-side `weatherbot/reliability/retry.py` shim re-exports the FULL surface, not just the 7 public names.** A grep of the consumers showed three direct-by-name importers of `weatherbot.reliability.retry`: `weatherbot/config/models.py:14` (`RETRY_AFTER_CAP_S`), `tests/test_reliability.py:42` (`BURST_SIZE`, `BURST_SPREAD_S`, `MID_PAUSE_S`, `RETRY_AFTER_CAP_S`, `two_burst_wait`, the `REASON_*`), and `tests/test_exception_identity.py:172` (`is_transient`). A 7-name shim would have broken those imports. Re-exporting the constants + `two_burst_wait` + `PERMANENT`/`TRANSIENT` keeps every byte-identical and resolves them to the SAME objects (verified via `is`).
- **`target`, not `location_id`, for the renamed port param.** The D-13 litmus is a substring regex including `location`, so `location_id` would itself trip the gate. `target` is the neutral name; the app store keeps `location_name`.
- **`AlertSink` is `runtime_checkable` and structurally satisfied by the existing store.** No injection forced at `fire_slot` (D-07 — that is Phase 25/APP-02). The port documents the MODULE's out-of-band alert contract; the app's `record_alert`/`resolve_alert` free functions match its shape (arg counts verified), so `fire_slot` keeps importing them directly with zero body change.

## Deviations from Plan

None — plan executed exactly as written. The retry engine moved verbatim, the port matches the planned shape, the shims keep every importer byte-identical, and `fire_slot` was not touched. No bugs, no missing critical functionality, no blocking issues, no architectural changes required.

## Issues Encountered
- **Pre-existing cosmetic "2 snapshots failed" syrupy line.** `uv run pytest` prints `2 snapshots failed. 27 snapshots passed.` while reporting `738 passed` and exiting 0 — syrupy's unused-snapshot accounting, identical to the 738 baseline (documented in 22-01/22-02). Not a test failure and not a golden diff: `git status --porcelain tests/__snapshots__/` is 0 bytes.
- **Plan's `(! grep .)` snapshot-gate one-liner is inverted** (same as noted in 22-01/22-02). The substantive criterion — empty `git status --porcelain tests/__snapshots__/` — is definitively met (verified via `wc -c` = 0 + `od -c` empty). Documented, not a real failure.

## Known Stubs
None. The `AlertSink` Protocol's `...` stub bodies are the canonical Protocol shape (covered by `exclude_also` in `pyproject.toml`), not unimplemented behavior — the real implementation is the app's `weatherbot.weather.store` functions, which satisfy the port structurally today.

## Threat Flags
None. Pure relocation — no new network endpoint, auth path, or trust-boundary surface. The `parse_retry_after` `Retry-After` cap (T-22-07), the outcome-only `before_sleep` log hygiene (T-22-08), and the no-retry-on-401/403 classifier (T-22-10) all moved VERBATIM, behavior byte-identical (`test_reliability.py` + the DB golden arbitrate). The standing grimp/litmus/isolated-import gates (T-22-09) are the boundary-integrity control and are green over the now-larger surface.

## Next Phase Readiness
- The reliability seam is byte-identical and gate-green; the retry engine + `AlertSink` port live in `yahir_reusable_bot/` with the standing-gate validation intact. Channel (22-02) + reliability + ports are all extracted and clean.
- Phase 23 (`SchedulerEngine.register(...)` + `OccurrenceStore` + the serialization-clean `JobStore` Protocol) can build on the now-established port idiom — `AlertSink` is the first `typing.Protocol` port in the module and the template for the scheduler's hooks.
- No blockers. The deferred Gate-2 host obligation (yahir-mint `uv sync` → restart → confirm `import yahir_reusable_bot` resolves) is a milestone-close item, not a phase blocker.

## Self-Check: PASSED

All created/modified files exist on disk and all three task commits are present in git history (verified below in the self-check step).

---
*Phase: 22-channel-delivery-reliability-seam-in-place-boundary*
*Completed: 2026-06-27*
