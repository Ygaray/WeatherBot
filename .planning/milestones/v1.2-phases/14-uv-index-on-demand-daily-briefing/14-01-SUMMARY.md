---
phase: 14-uv-index-on-demand-daily-briefing
plan: 01
subsystem: config
tags: [uv, pydantic, config, fixtures, openweather, onecall, hourly]

# Dependency graph
requires:
  - phase: 12-shared-command-registry
    provides: One Call exclude widened to "minutely" (keeps hourly[]) — the D-06 change this plan's regression canary guards
provides:
  - "UvConfig frozen [uv] table (threshold + pre_warn_lead_minutes) with fail-loud validators"
  - "Config.uv field via default_factory=UvConfig (absent table = defaults, zero migration, hot-reloadable)"
  - "Three deterministic hourly[].uvi fixtures (uvcross / uvbelow / highuv) anchored to 2024-06-14 NY"
  - "client hourly[]-carries-uvi regression canary (D-05 Wave-0)"
affects: [14-02-compute-uv, 14-03-briefing-uv-line, 14-04-uv-command, 15-uv-monitor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Frozen extra=forbid config table with default_factory field on Config (UvConfig mirrors WebhookIdentity/Reliability/cloud_threshold)"
    - "Deterministic hourly[].uvi fixtures anchored to a fixed reference date so downstream interpolation can pin now= and assert exact minutes"

key-files:
  created:
    - tests/test_config_uv.py
    - tests/fixtures/onecall_imperial_uvcross.json
    - tests/fixtures/onecall_imperial_uvbelow.json
  modified:
    - weatherbot/config/models.py
    - weatherbot/config/__init__.py
    - tests/fixtures/onecall_imperial_highuv.json
    - tests/test_client.py

key-decisions:
  - "threshold default 6.0 preserves the hardcoded sunscreen-hint behavior verbatim (A5, zero migration)"
  - "Config.uv uses default_factory=UvConfig (NOT | None) so an absent [uv] table means defaults, never 'no UV' (D-01)"
  - "pre_warn_lead_minutes stored+validated in Phase 14 but no behavior yet — Phase 15 gives it meaning (Open Q1/A4)"
  - "threshold range bound 0..20 (generous WHO ceiling); negative lead rejected"
  - "All fixtures anchored to 2024-06-14 NY (sunrise 04:40 / sunset 19:40) matching the pre-existing highuv timestamps so Plan 14-02 can pin now="

patterns-established:
  - "UvConfig frozen-table-with-defaulted-field-on-Config pattern (free hot-reload via whole-Config re-read)"
  - "hourly[].uvi fixture anchoring for deterministic sub-hour interpolation tests"

requirements-completed: [UV-03]

# Metrics
duration: ~9min
completed: 2026-06-19
---

# Phase 14 Plan 01: UV Config Table + Wave-0 hourly[] Fixtures Summary

**A frozen, fail-loud, hot-reloadable `[uv]` config table (threshold 6.0 + pre_warn_lead_minutes 30) plus three deterministic `hourly[].uvi` One Call fixtures and a client regression canary proving Phase 12's `exclude` widening still returns `hourly[]` carrying `uvi`.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-19T17:40:00Z (approx)
- **Completed:** 2026-06-19T17:49:32Z
- **Tasks:** 2
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments
- `UvConfig` frozen `extra="forbid"` model with `threshold: float = 6.0` + `pre_warn_lead_minutes: int = 30`, plus `_threshold_in_range` (0..20) and `_lead_non_negative` validators (fail-loud at load, T-14-01).
- `Config.uv = Field(default_factory=UvConfig)` — an absent `[uv]` table loads as defaults under `extra="forbid"` (zero migration), and the existing whole-`Config` reload picks up edits with no reload-wiring change.
- Three deterministic UV fixtures carrying a populated `hourly[].uvi` + `daily[0]` sunrise/sunset/uvi, exercising every Plan 14-02 branch: up-cross/peak/down-cross (`uvcross`), stays-below-all-day (`uvbelow`), already-above-at-first-daytime-point (`highuv`).
- Strengthened the client regression canary to assert the retained `hourly[]` carries `uvi` (the UV-specific D-05 concern); `client.py` itself is VERIFY-ONLY and unchanged.

## Task Commits

Each task was committed atomically (Task 1 followed TDD RED → GREEN):

1. **Task 1 (RED): failing UV config tests** — `0683638` (test)
2. **Task 1 (GREEN): UvConfig + Config.uv field** — `92350f6` (feat)
3. **Task 2: hourly[] UV fixtures + uvi regression canary** — `48c53a2` (test)

**Plan metadata:** see final docs commit.

## Files Created/Modified
- `weatherbot/config/models.py` — added `UvConfig` (frozen, validated) + `Config.uv` field.
- `weatherbot/config/__init__.py` — export `UvConfig`.
- `tests/test_config_uv.py` — defaults / explicit-load / range-fail / negative-lead-fail / unknown-key-fail / reload-pickup.
- `tests/fixtures/onecall_imperial_uvcross.json` — UV 0→9.6→0.2 across daytime, crosses 6 between 10:00 and 11:00, drops below 6 between 15:00 and 16:00.
- `tests/fixtures/onecall_imperial_uvbelow.json` — UV peaks 4.5, never reaches 6.
- `tests/fixtures/onecall_imperial_highuv.json` — extended with `hourly[]` starting at 6.2 (already-above branch); `daily[0].uvi 9.6` preserved.
- `tests/test_client.py` — canary now asserts retained `hourly[]` carries `uvi`.

## Decisions Made
- Kept `current.uvi` independent of the hourly curve in each fixture (Pitfall 6: `current.uvi` is "now" verbatim; `hourly[]` is for crossing/window/peak only).
- Rewrote (not appended) `onecall_imperial_highuv.json` to add `hourly[]` while preserving the two fields `test_models.py::test_hints_sunscreen_on_high_uv` depends on (`daily[0].uvi == 9.6`) and `current.uvi == 8.2`.

## Deviations from Plan

None - plan executed exactly as written.

(Note on acceptance criteria: the literal check `grep -c "default_factory=UvConfig" → 1` reports 3 because two of the matches are explanatory docstring/comment references; there is exactly ONE actual field declaration `uv: UvConfig = Field(default_factory=UvConfig)` (models.py:456), so the functional intent of the criterion — a single `Config.uv` field using the factory — is satisfied. All behavior tests and the other three acceptance checks pass exactly.)

## Issues Encountered
None. Baseline suite was green (52 config/client tests), full suite green before and after (453 passed). `ruff check` clean on all changed files.

## User Setup Required
None - threshold/lead are non-secret config. The live host can adopt a `[uv]` table (or rely on defaults) via the existing hot-reload; **no daemon restart needed for config**, but the downstream Phase-14 code (uv.py, model/template/registry edits in later plans) will require a daemon restart when shipped.

## Next Phase Readiness
- Plan 14-02 (`compute_uv`/`UvSummary`) has its threshold source (`config.uv.threshold`) and its three deterministic `hourly[].uvi` fixtures ready to pin `now=` against.
- The regression canary confirms `hourly[].uvi` is actually delivered — no risk of building interpolation against an empty `hourly[]`.

## Self-Check: PASSED

All created files present on disk; all three task commits (`0683638`, `92350f6`, `48c53a2`) found in git history; `class UvConfig` present in `weatherbot/config/models.py`.

---
*Phase: 14-uv-index-on-demand-daily-briefing*
*Completed: 2026-06-19*
