---
phase: 35-cleanup-sweep
plan: 04
subsystem: config
tags: [hardening, cleanup, validation, resolve-location, regression-test]
status: complete
requires: []
provides:
  - "Canonical-only HH:MM schedule-time validation (job-id / sent-log key safety)"
  - "id-then-name resolve_location lookup (--send-now <id> when id != name)"
affects:
  - weatherbot/config/models.py
  - weatherbot/config/loader.py
tech-stack:
  added: []
  patterns:
    - "all-digit component check (hh.isdigit() and mm.isdigit()) before int-parse — closes the int()-parseable non-canonical hole"
    - "two-pass additive lookup: match stable id (casefold) first, then fall back to name (casefold)"
key-files:
  created: []
  modified:
    - weatherbot/config/models.py
    - weatherbot/config/loader.py
    - tests/test_config.py
decisions:
  - "F74 fix applied to BOTH Schedule and ForecastSchedule _hhmm to preserve the 'one source of truth' HH:MM contract (Rule 2)"
  - "F75 id match is case-insensitive, mirroring the existing name-match casefold semantics"
metrics:
  duration: ~3min
  completed: 2026-07-13
  tasks: 2
  files: 3
---

# Phase 35 Plan 04: Config Cleanup Sweep (F74 + F75) Summary

Tightened the HH:MM schedule-time validator to reject non-canonical int-parseable strings (F74) and widened `resolve_location` to match by stable `id` first then `name` (F75), each pinned by a finding-tagged D-06 regression test — both TDD RED→GREEN, suite green at 884 passed.

## What Was Built

**Task 1 — F74: canonical-only HH:MM validator.** The raw `time` string is used verbatim as an APScheduler job-id and a `sent_log` key, so it must be strictly canonical `[0-9][0-9]:[0-9][0-9]`. The pre-fix `_hhmm` int-parsed each component behind a bare `len==2` check, which let 2-char oddities slip through: `int("+9")==9` and `int(" 9")==9`, so `"+9:30"` and `" 9:30"` were wrongly ACCEPTED (confirmed by reproduction before the fix). Added an `hh.isdigit() and mm.isdigit()` gate before int-parse so only all-digit two-char components survive. Applied to BOTH `Schedule._hhmm` and `ForecastSchedule._hhmm` to keep the "one source of truth" HH:MM contract intact.

**Task 2 — F75: id-then-name resolve_location.** `resolve_location` matched only on case-insensitive `name`, so `--send-now <id>` raised `UnknownLocationError` when a renamed location's stable `id` differed from its display `name` (confirmed by reproduction: `resolve_location(cfg, "loc-7")` raised). Added a first pass matching `loc.id.casefold() == target` before the existing name pass. Strictly additive: the name match and the `UnknownLocationError` contract are untouched, so every existing `except ValueError` caller stays green (Pitfall 5).

## Tasks Completed

| Task | Name | Commits | Files |
|------|------|---------|-------|
| 1 | F74 tighten HH:MM validator | `1ae9925` (RED test), `8b32c69` (fix) | weatherbot/config/models.py, tests/test_config.py |
| 2 | F75 id-then-name resolve_location | `30093ab` (RED test), `858674c` (fix) | weatherbot/config/loader.py, tests/test_config.py |

Both tasks were TDD (`tdd="true"`): each fix ships a regression test that fails against pre-fix behavior (RED, verified) and passes against the fix (GREEN, verified) — satisfying the D-06 behavior-changing → regression-test-required must_have.

## Regression Tests (D-06)

- `test_hhmm_rejects_non_canonical_int_parseable` — `# HARD-CLEAN-02 / F74`. Asserts canonical times (`00:00`, `07:00`, `09:30`, `23:59`) validate on both schedule models, that `+9:30`/` 9:30`/`09:+0`/`09: 0`/`-1:30`/`9:30` raise `ValidationError`, and that the rejection fires at config-load time (the job-id/key path). RED-verified against the pre-fix validator.
- `test_resolve_location_matches_id_then_name` — `# HARD-CLEAN-02 / F75`. Uses the rename-safe `Location(name="Beach House", id="loc-7", ...)` shape (34-PATTERNS). Asserts id lookup (`loc-7`, `LOC-7`) returns the location, name lookup (`Beach House`, `beach house`) still returns it, `None` returns the default, and an unknown token still raises `UnknownLocationError`. RED-verified against the pre-fix name-only lookup.

## Verification

- `uv run pytest tests/test_config.py -q` → 49 passed, exit 0.
- `uv run pytest -q` → 884 passed, exit 0 (the "2 snapshots failed" line is the known pre-existing syrupy report quirk on this repo — exit code is authoritative and is 0).
- Diff touches only `tests/test_config.py`, `weatherbot/config/models.py`, `weatherbot/config/loader.py` — no `yahir_reusable_bot/` or `../Reusable/` hub-path file (prohibition honored).

## Threat Model

- **T-35-04-01 (Tampering, config/models.py HH:MM validator, mitigate):** F74 strictly tightens an existing pydantic input validator (V5, ASVS L1) — canonicalization only, no new attack surface. Regression test pins both acceptance (canonical) and rejection (non-canonical).
- **T-35-04-02 (config/loader.py resolve_location, accept):** F75 widens a lookup additively over trusted config input; no trust-boundary change. Regression test pins the new id path and the preserved name/error paths.

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] Applied the F74 tightening to `ForecastSchedule._hhmm` as well as `Schedule._hhmm`.**
- **Found during:** Task 1.
- **Issue:** The plan `<action>` names only `Schedule`, but `ForecastSchedule._hhmm` is documented as reusing the Schedule HH:MM contract "VERBATIM (one source of truth)". Tightening only one would silently split the contract, leaving forecast job-id keys still accepting `+9:30`/` 9:30`.
- **Fix:** Added the identical `hh.isdigit() and mm.isdigit()` gate to `ForecastSchedule._hhmm`; the F74 regression test asserts both models reject the oddities and accept canonical times.
- **Files modified:** weatherbot/config/models.py.
- **Commit:** `8b32c69`.

No other deviations. No authentication gates. No architectural changes.

## Known Stubs

None.

## Self-Check: PASSED

- weatherbot/config/models.py — FOUND
- weatherbot/config/loader.py — FOUND
- tests/test_config.py — FOUND
- Commit `1ae9925` (F74 RED) — FOUND
- Commit `8b32c69` (F74 fix) — FOUND
- Commit `30093ab` (F75 RED) — FOUND
- Commit `858674c` (F75 fix) — FOUND
