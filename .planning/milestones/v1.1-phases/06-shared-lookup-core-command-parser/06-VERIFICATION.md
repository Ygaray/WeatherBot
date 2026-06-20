---
phase: 06-shared-lookup-core-command-parser
verified: 2026-06-15T21:10:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 6: Shared Lookup Core & Command Parser Verification Report

**Phase Goal:** One read-only fetch→render core (`interactive/lookup.py`) and one `weather <loc>` parser (`interactive/command.py`) exist and are unit-tested, so the CLI and the Discord bot can both call identical code with identical semantics.
**Verified:** 2026-06-15T21:10:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `lookup_weather(name, *, config, settings, …)` resolves a configured location, fetches via the existing One Call client, renders via the v1 template, returns briefing text — unit-tested against recorded payloads | ✓ VERIFIED | `weatherbot/interactive/lookup.py:78-147` implements resolve→dual-fetch→`Forecast.from_payloads`→`load_template`/`validate_template`→`render`→`LookupResult`. `tests/test_lookup.py::test_lookup_imperial_happy_path` and `::test_lookup_metric_primary` pass against `onecall_imperial_clear.json`/`onecall_metric_clear.json` fixtures. Dual-fetch order `["imperial","metric"]` asserted. |
| 2 | `lookup_weather` writes NO sent-log, alert, or heartbeat rows (verified by test) | ✓ VERIFIED | Grep gate: 0 imports of `weatherbot.weather.store`, 0 `db_path` references in `lookup.py`. `tests/test_lookup.py::test_lookup_writes_nothing_to_store` monkeypatches all 7 store write functions (`persist`, `claim_slot`, `record_alert`, `resolve_alert`, `stamp_tick`, `stamp_success`, `stamp_health`) to raise; lookup completes. Belt-and-suspenders fresh-DB row-count assertion. Passes. |
| 3 | `parse_weather_command()` turns `weather`, `weather <loc>`, and unknown/garbage into a stable three-state result (location \| default \| None), unit-tested independently | ✓ VERIFIED | `weatherbot/interactive/command.py:50-70` pure three-state parser. Live spot-check of 7 representative inputs all PASS (DEFAULT/LOCATED/NOT_A_COMMAND incl. word-boundary `weatherman`/`weather:` guard, raw-case preservation). `tests/test_command.py` 12-row matrix passes. Config-free (0 `weatherbot.config` imports), no `eval`/`str.format`. |
| 4 | `send_now` still produces byte-identical scheduled briefings after the extraction (existing tests stay green) | ✓ VERIFIED | `weatherbot/cli.py:141-170` delegates read-only HEAD to `lookup_weather` via `extra_placeholders` seam; deliver→`if result.ok: persist`→log→return TAIL preserved verbatim. `git diff tests/test_send_now.py` empty (byte-identical gate). `tests/test_send_now.py` passes unmodified. Full suite 206 passed. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `weatherbot/interactive/command.py` | `parse_weather_command` + `Command` + `CommandKind` (pure, config-free) | ✓ VERIFIED | All three symbols present; frozen `Command` dataclass; `CommandKind` enum NOT_A_COMMAND/DEFAULT/LOCATED. Imported+used by tests and barrel. |
| `weatherbot/interactive/lookup.py` | `lookup_weather` + `LookupResult` + `UnknownLocationError(ValueError)` | ✓ VERIFIED | All three present; `UnknownLocationError` subclasses `ValueError`, carries `.requested`+`.valid_names`; lazy `build_client` import inside `client is None` branch. Wired into `cli.py` and barrel. |
| `weatherbot/interactive/__init__.py` | Barrel re-exporting all 6 symbols with `__all__` | ✓ VERIFIED | Re-exports all six; explicit `__all__`. Import smoke check succeeds. |
| `weatherbot/config/loader.py` | `resolve_location` raises `UnknownLocationError` (backward-compatible) | ✓ VERIFIED | `loader.py:64` raises `UnknownLocationError(name, [loc.name …])` via lazy import; `assert_unique_names` unchanged; match/default logic unchanged. |
| `tests/test_command.py` | Input-matrix tests | ✓ VERIFIED | 12 tests; direct submodule import; no config import. |
| `tests/test_lookup.py` | Happy-path + zero-store-writes + typed-error tests | ✓ VERIFIED | 5 substantive tests; real monkeypatch spy + DB row-count assertion. |
| `tests/test_interactive_package.py` | Barrel + no-import-cycle smoke test | ✓ VERIFIED | 3 tests; barrel import, ValueError-subclass, cli+interactive co-import. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `cli.py` send_now | `lookup_weather` | delegation call | ✓ WIRED | `cli.py:141` calls `lookup_weather(...)`; `cli.py:147` passes `extra_placeholders`. |
| `cli.py` | `schedule_placeholders` | `extra_placeholders=` | ✓ WIRED | `cli.py:137` `extra_placeholders = schedule_placeholders(...)` (scheduled path); None for manual path. |
| `lookup.py` | `Forecast.from_payloads` | dual-payload build | ✓ WIRED | `lookup.py:121`. |
| `lookup.py` | `templates.renderer.render` | single render site | ✓ WIRED | `lookup.py:144`. |
| `loader.py` | `UnknownLocationError` | lazy guarded import at raise | ✓ WIRED | `loader.py:62-64`. |
| `tests/test_command.py` | `parse_weather_command` | direct import | ✓ WIRED | Import + 12 assertions. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Parser three-state matrix (7 inputs) | `python -c parse_weather_command(...)` | ALL PASS (DEFAULT/LOCATED/NOT_A_COMMAND, word-boundary, raw-case) | ✓ PASS |
| Barrel imports + no cycle | `python -c import weatherbot.cli, weatherbot.interactive, …` | barrel ok; UnknownLocationError is-a ValueError: True | ✓ PASS |
| Phase test files | `pytest test_command test_lookup test_interactive_package test_send_now` | 24 passed | ✓ PASS |
| Full suite (regression) | `uv run pytest -q` | 206 passed | ✓ PASS |
| Lint | `ruff check` on phase files | All checks passed | ✓ PASS |

### Probe Execution

No probes declared or discovered (`scripts/*/tests/probe-*.sh` absent). Phase is library extraction, not a migration/tooling phase. Step 7c: N/A.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| (none — foundation) | 06-01/02/03 (all `requirements: foundation`) | No v1.1 requirement closes in Phase 6 | ✓ CONSISTENT | REQUIREMENTS.md:92 explicitly lists Phase 6 as a foundation/prerequisite phase without a closing requirement. Traceability table (REQUIREMENTS.md:75-81) maps CMD-01..07 to Phase 7/11, never Phase 6. All 3 summaries declare `requirements-completed: []`. No orphaned requirements. |

The empty `requirements-completed` is **correct and consistent**, not a gap — confirmed against the REQUIREMENTS.md foundation-phase note and traceability table.

### Anti-Patterns Found

None. Scanned `command.py`, `lookup.py`, `__init__.py` for TODO/FIXME/XXX/TBD/HACK/PLACEHOLDER/not-yet-implemented — zero matches. The single `str.format`/`eval` grep hit in `command.py:11` is a docstring describing what the parser does NOT do, not a usage.

### Human Verification Required

None. All four success criteria are programmatically verifiable (parser semantics, store-write absence, byte-identical regression via unmodified test_send_now.py) and were verified by live execution + the existing test suite. No visual/real-time/external-service behavior is in scope for this library-extraction phase.

### Gaps Summary

No gaps. All four ROADMAP success criteria are observably true in the codebase:
1. `lookup_weather` resolves→fetches→renders→returns `LookupResult` (tested against fixtures).
2. It is provably read-only (no store import, no db_path, spy test green).
3. `parse_weather_command` is a pure, config-free three-state parser (live matrix all pass).
4. `send_now` delegates to the shared core with the deliver+persist tail byte-identical (test_send_now.py unmodified and green; full suite 206 passed).

The package barrel re-exports all six public symbols with no import cycle, giving Phase 7 (CLI) and Phase 11 (Discord) a single shared import surface — the phase goal. Requirement traceability is consistent with this being a foundation phase.

---

_Verified: 2026-06-15T21:10:00Z_
_Verifier: Claude (gsd-verifier)_
