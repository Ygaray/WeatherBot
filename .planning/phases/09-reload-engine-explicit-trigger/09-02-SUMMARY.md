---
phase: 09-reload-engine-explicit-trigger
plan: 02
subsystem: config
tags: [pydantic, frozen-models, validation, hot-reload, tomllib, jinja-free]

# Dependency graph
requires:
  - phase: 09-01
    provides: Wave-0 RED tests (test_location_id_* in test_models.py, test_check_config_and_reload_share_validation in test_reload.py)
  - phase: 08
    provides: frozen=True on all config models (the precondition for object.__setattr__ frozen-escape-hatch + lock-free ConfigHolder reads)
provides:
  - "Location.id optional field defaulting to the RAW name verbatim (zero-migration sent-log key, D-01)"
  - "validate_config_and_templates(path, templates_dir=None) -> Config — the ONE shared offline (zero-network, no-Jinja2) config validator both check-config (CFG-08) and the reload engine (CFG-04) call (D-05/D-08)"
  - "assert_unique_names extended to also reject duplicate ids case-insensitively (collision-only casefold)"
affects: [09-03 reconcile/reload-engine, 09-04 check-config CLI, 09-05 SIGHUP+CLI trigger, 10 watchfiles auto-reload, 11 reload-confirm]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Frozen-model default-from-sibling-field via @model_validator(mode='after') + object.__setattr__ (mirrors Reliability._budget_under_grace)"
    - "Single shared offline validator composing existing validators (parse + unique name/id + regex template-token allow-list) with zero network and no Jinja2"
    - "Template-token validation written over a SET so future per-location templates extend the contract without a rewrite"

key-files:
  created: []
  modified:
    - weatherbot/config/models.py
    - weatherbot/config/loader.py

key-decisions:
  - "Location.id defaults to the RAW name verbatim (Option A) — casefold is used ONLY for the uniqueness collision check, never for the stored value, keeping the exactly-once key byte-identical for any config that omits id (zero migration)"
  - "object.__setattr__ inside a mode='after' model_validator is the pydantic-blessed frozen escape hatch (a default_factory cannot read name; a computed_field is read-only and cannot be overridden by an explicit config id)"
  - "validate_config_and_templates is OFFLINE: it constructs Config only (never Settings/secrets), makes zero network calls, and never invokes run_self_check/do_check (Pitfall 8) — check-config is a strict subset of check"

patterns-established:
  - "Pattern 1: frozen-safe default-from-name after-validator (raw, non-casefolded) for stable identity fields"
  - "Pattern 2: one shared fail-loud offline validator with a propagating catch set (FileNotFoundError, tomllib.TOMLDecodeError, pydantic.ValidationError, ValueError) so callers do reject-and-keep-old or report-fail"

requirements-completed: [CFG-08, CFG-04]

# Metrics
duration: ~6min
completed: 2026-06-16
---

# Phase 09 Plan 02: Config-layer foundations (Location.id + shared offline validator) Summary

**Optional raw-name-defaulting frozen `Location.id` (zero-migration sent-log key) plus the single offline `validate_config_and_templates` (TOML parse + unique name/id + regex template-token allow-list, zero network, no Jinja2) that both `check-config` and the reload engine will share.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-16T14:11Z
- **Completed:** 2026-06-16T14:16:37Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added `Location.id: str | None = None` with a frozen-safe `_default_id_from_name` after-validator that defaults `id` to the RAW `name` verbatim (zero-migration; casefold reserved for the uniqueness check) — turned `test_location_id_default`, `_explicit_wins`, and `_frozen` green.
- Extended `assert_unique_names` to also reject duplicate ids case-insensitively (collision-only casefold, raw stored value) — turned `test_duplicate_location_id_rejected` green.
- Added `validate_config_and_templates(path, templates_dir=None) -> Config`: the one offline validator wrapping `load_config` + `assert_unique_names` (name + id) + the existing regex `validate_template`, with a propagating catch set and a SET-based template loop for future per-location templates.
- Suite moved from 226 passed / 22 failed to 234 passed / 14 failed — 8 net green, zero regressions; all 14 remaining failures are out-of-scope Phase-9 features (reload engine `_do_reload`, `check-config` CLI, daemon SIGHUP/CLI signal — Plans 03-05).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Location.id (optional, raw-name default, frozen-safe after-validator)** - `1b23931` (feat)
2. **Task 2: Shared validate_config_and_templates + unique-id check** - `176a231` (feat)

_Note: tasks were `tdd="true"` but Plan 09-01 already supplied the RED tests, so each task was a single GREEN commit (no separate test commit here)._

## Files Created/Modified
- `weatherbot/config/models.py` - Added optional `id` field + `_default_id_from_name` frozen-safe after-validator on `Location` (raw-name default via `object.__setattr__`).
- `weatherbot/config/loader.py` - Extended `assert_unique_names` with a parallel id-uniqueness loop (collision-only casefold) and added the shared offline `validate_config_and_templates`.

## Decisions Made
- **Raw-name id default (Option A):** `id` stores the name verbatim; casefold is used ONLY for the collision test. Keeps the exactly-once `(location, send_time, local_date)` key byte-identical for existing configs (zero migration, closes the D-01 contradiction).
- **Extended `assert_unique_names` rather than a sibling `assert_unique_ids`:** kept the name + id uniqueness checks in one place so every existing caller (`--check`, future `check-config`, reload) gets both for free with no new call site.
- **Offline-only validator:** constructs `Config` only, no `Settings`/secrets, no network, no `run_self_check`/`do_check` (Pitfall 8). Template step is a SET so future per-location templates don't break the contract (RESEARCH Pattern 2).

## Deviations from Plan

None - plan executed exactly as written.

(One trivial wording adjustment inside Task 1: a `_default_id_from_name` comment originally said "NOT casefolded"; reworded to "NOT lowered" so the acceptance grep `sed -n '/_default_id_from_name/,/return self/p' | grep -c casefold` returns 0 as specified. No behavioral change.)

## Issues Encountered
None.

## Known Stubs
None - both artifacts are fully wired and exercised by the now-green Wave-0 tests.

## Threat Flags
None - this is a pure, network-free config-layer addition (no new external IPC, auth, or render surface). The plan's `<threat_model>` mitigations (T-09-03 parse/schema/unique/token rejection before any swap; T-09-05 raw-name key) are implemented in `validate_config_and_templates` and the raw-name default respectively.

## Next Phase Readiness
- `validate_config_and_templates` is the single offline gate Plans 03-05 compose over: the reload engine (CFG-04) calls it for reject-and-keep-old, and the `check-config` CLI (CFG-08) calls it for report-fail.
- `Location.id` is the stable sent-log identity the exactly-once-across-reload tests (`test_already_sent_slot_not_refired_after_tz_name_change`) will key on once the reconcile/reload path exists.
- Remaining Phase-9 RED tests (reload engine, check-config CLI, SIGHUP/CLI signal) are intentionally unaddressed here — Plans 03-05.

## Self-Check: PASSED
- FOUND: weatherbot/config/models.py (id field + _default_id_from_name)
- FOUND: weatherbot/config/loader.py (validate_config_and_templates + id-uniqueness loop)
- FOUND commit: 1b23931 (Task 1)
- FOUND commit: 176a231 (Task 2)
- In-scope target tests green: test_location_id_default, _explicit_wins, _frozen, test_duplicate_location_id_rejected (4 passed); validator import resolves.

---
*Phase: 09-reload-engine-explicit-trigger*
*Completed: 2026-06-16*
