---
phase: 21-characterization-golden-test-harness
plan: 05
subsystem: testing
tags: [pytest-cov, branch-coverage, characterization, coverage-audit, pragma-no-cover, zero-flake, golden-snapshot]

# Dependency graph
requires:
  - phase: 21-01
    provides: "[tool.coverage.run] branch-mode config (6 move-path packages, weatherbot/weather excluded, no fail_under) + conftest serializers"
  - phase: 21-02/21-03/21-04
    provides: "Wave-1 goldens (embeds, schedule, DB rows, CLI, custom-ids, exception-identity) that the audit measures WITH-present"
provides:
  - "21-COVERAGE-AUDIT.md — the recorded one-time branch audit (89% -> 93%, 80 -> 48 partials), every uncovered move-path branch filled or excused with a named reason"
  - "tests/test_golden_coverage_fill.py — 39 characterization tests pinning the untaken move-path branch sides"
  - "Final zero-flake gate: full 732-test suite green on two consecutive runs; --snapshot-update an empty diff (oracle proven trustworthy for the extraction phases)"
affects: [22-channel-extraction, 23-scheduler-seam, 24-config-reload, 25-lifecycle, 26-registry, 27-discord-adapter, 28-physical-split]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One-time branch-coverage audit recorded in a phase log (NOT a standing fail_under gate, D-08)"
    - "Characterization fills: pin the CURRENT output of an untaken except/else/false-path; never aspirational (extraction risk lives on the untaken side)"
    - "Reason-bearing # pragma: no cover - <reason> for genuinely-unreachable branches; comment-only diff, zero behavior change (D-09)"
    - "Runtime-lifecycle / defensive-payload branches excused as NAMED documented categories in the audit log rather than sprayed inline pragmas (D-09 'config/doc over scattered pragmas')"

key-files:
  created:
    - tests/test_golden_coverage_fill.py
    - .planning/phases/21-characterization-golden-test-harness/21-COVERAGE-AUDIT.md
  modified:
    - weatherbot/reliability/retry.py
    - weatherbot/interactive/lookup.py
    - weatherbot/ops/selfcheck.py
    - weatherbot/scheduler/uvmonitor.py
    - .gitignore

key-decisions:
  - "retry.py:125-126 `if dt is None` is unreachable on CPython 3.12 (parsedate_to_datetime always RAISES on malformed input, never returns None) — excused with a cross-version reason-bearing pragma, not a fill."
  - "The three lazy `build_client` blocks (lookup/selfcheck/uvmonitor) are production-only (tests always inject a client) — excused with reason-bearing pragmas, comment-only source diff."
  - "Runtime-lifecycle branches (daemon signal/watchfiles/shutdown, bot thread teardown, panel discord callbacks, state next_fires over a live APScheduler store) and defensive malformed-payload skips are excused as NAMED categories in 21-COVERAGE-AUDIT.md §3 — they are stdlib threading/asyncio/discord glue and fail-safe degradation, not move-path logic whose untaken side could diverge after extraction."
  - "No fail_under standing gate added (D-08); weatherbot/weather kept out of audit scope (D-07)."

patterns-established:
  - "Move-path branch audit: classify each uncovered partial as FILLABLE (observable, pin it) vs EXCUSED (runtime/defensive/production-only, name why)"
  - "Generated .coverage artifact is gitignored (never committed)"

requirements-completed: [BHV-01, BHV-02]

# Metrics
duration: ~40min
completed: 2026-06-27
status: complete
---

# Phase 21 Plan 05: One-Time Branch-Coverage Audit + Zero-Flake Gate Summary

**Ran the one-time move-path branch audit (89% → 93%, 80 → 48 partial branches), filled every tractable uncovered branch with 39 characterization tests, excused the genuinely-unreachable runtime-lifecycle / defensive / production-only branches with named reasons, and closed the phase with a 732-test zero-flake gate (two identical green runs, empty `--snapshot-update` diff).**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-06-27T19:23:48Z
- **Completed:** 2026-06-27
- **Tasks:** 2 (Task 1: audit + fill; Task 2: zero-flake gate — recorded in audit-log §5)
- **Files modified:** 5 (4 source pragma-only + .gitignore) + 2 created (fill tests, audit log)

## Accomplishments

- **One-time branch audit (D-06/D-08):** ran `uv run pytest --cov --cov-branch --cov-report=term-missing` over the 6 move-path packages. Before: 162 missed stmts / 80 partials / 89%. After: 104 missed / 48 partials / 93%. Recorded the full before/after term-missing tables and per-branch resolutions in `21-COVERAGE-AUDIT.md`.
- **39 characterization fills** in `tests/test_golden_coverage_fill.py` pinning the untaken sides of: factory unknown-type error, settings/loader/models validators, retry malformed-header fallback, catchup weekday/empty-part skips + plan_catchup, scheduler lazy `__getattr__`, command edge replies (info/status/forecast/weather_views), pidfile recycling defense + write-failure cleanup, sdnotify abstract socket + watchdog, uvmonitor pure helpers, and bot `_split_body` hard-split + embed overflow marker. **Fills touch NO `weatherbot/` source.** Brought 20+ move-path files to 100% branch coverage.
- **Excused the remainder with named reasons (D-09):** 4 inline reason-bearing pragmas (the cross-version `dt is None` guard + three production-only lazy-`build_client` blocks — comment-only diff, zero behavior change); runtime-lifecycle + defensive-payload branches documented as NAMED categories in the audit log (daemon/bot/panel/state runtime glue; forecast/weather_views/uvmonitor fail-safe payload skips). No branch was excused merely to make the number green.
- **No `fail_under` standing gate (D-08)**; `weatherbot/weather` kept out of scope (D-07).
- **Final zero-flake gate (BHV-01/SC1):** 732 tests passed on two consecutive runs (byte-identical), and `uv run pytest --snapshot-update` produced an EMPTY snapshot diff (D-04 — goldens already canonical), proving the oracle trustworthy for every later extraction phase. Recorded in audit-log §5.

## Task Commits

1. **Task 1: Branch-coverage audit + fills + pragmas** — `312387c` (test)
2. **Task 2: Full-suite zero-flake gate** — no new file changes; the gate is a verification step whose results are recorded in `21-COVERAGE-AUDIT.md` §5 (committed as part of Task 1). 732 passed ×2 + empty `--snapshot-update`.

**Plan metadata:** (this commit — docs)

## Files Created/Modified

- `tests/test_golden_coverage_fill.py` (new) — 39 characterization tests for the uncovered move-path branches.
- `.planning/phases/21-characterization-golden-test-harness/21-COVERAGE-AUDIT.md` (new) — the recorded audit: before/after tables, every fill, every excused branch + named reason, and the §5 zero-flake gate result.
- `weatherbot/reliability/retry.py` — added one reason-bearing pragma on the cross-version `if dt is None` guard (comment-only).
- `weatherbot/interactive/lookup.py`, `weatherbot/ops/selfcheck.py`, `weatherbot/scheduler/uvmonitor.py` — added reason-bearing pragmas on the production-only lazy-`build_client` blocks (comment-only).
- `.gitignore` — ignore the generated `.coverage` artifact.

## Decisions Made

- **`retry.py:125-126` excused, not filled:** on CPython 3.12 `parsedate_to_datetime` ALWAYS raises `ValueError` on malformed input (verified empirically — `'not-a-date'`, `''`, `'Mon'`, `'0'` all raise), so the `if dt is None: return None` guard is unreachable on this Python. Excused with a cross-version reason-bearing pragma; the reachable `except` parse-failure path IS filled.
- **Lazy `build_client` blocks excused as production-only:** the shared documented pattern "tests always inject a client so this never runs offline" — three blocks (lookup/selfcheck/uvmonitor) excused with reason-bearing pragmas. The fillable raise-on-no-client-and-no-settings sides ARE filled.
- **Runtime-lifecycle + defensive branches excused as documented categories, not inline pragmas:** spraying ~50 inline pragmas across daemon/bot/panel runtime lines would add noise and risk masking a real future regression on those same lines. The audit log §3 names each category and branch instead (D-09's "documentation over scattered pragmas" spirit).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Gitignored the generated `.coverage` artifact**
- **Found during:** Task 1 (running the audit)
- **Issue:** `uv run pytest --cov` writes a `.coverage` SQLite file to the repo root; it was untracked and `git check-ignore` confirmed it was NOT ignored — it would have leaked into the commit / history.
- **Fix:** Added `.coverage` / `.coverage.*` / `htmlcov/` / `coverage.xml` to `.gitignore`. Generated coverage data must never be committed.
- **Files modified:** `.gitignore`
- **Verification:** `git status --short | grep .coverage` → empty after the change.
- **Committed in:** `312387c` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking). Also applied `ruff format` + `ruff check` to the new fill file (project lint convention — passed clean, no behavior change).
**Impact on plan:** Necessary to keep a generated artifact out of git history. No scope creep — the audit surface is exactly as specified (same 6 packages, branch mode, no fail_under, weather out of scope).

## Issues Encountered

- **Several first-draft fills used wrong call signatures** (the retry parser takes an `httpx.Response` not a `str`; `WebhookIdentity` has no `url` field; `openweather_api_key` is a plain `str` not a `SecretStr`). Corrected each by reading the actual source/model fields and the existing `tests/test_command_views.py` / `tests/test_ops_selfcheck.py` builder conventions, then re-running. All 39 fills pass.
- **A few targeted branches needed a second fill pass** (the valid-`return v` side of the models validator at 302, the `if current` false-sides of `_split_body` at 177->180 / 189->191, the empty-`daily` vs non-empty phrasing in `next_cloudy`) — each driven by a precise additional case rather than a broad test.

## User Setup Required

None - no external service configuration required. The audit runs the existing offline suite; it adds no handler, sink, secret path, or package install.

## Next Phase Readiness

- **Phase 21 (characterization golden harness) is COMPLETE.** The full 732-test suite is green and zero-flake on `main`; the move-path branch audit is clean (every uncovered branch filled or excused with a named reason); the goldens are canonical (`--snapshot-update` is an empty diff). The byte-identical oracle is ready to guard the v2.0 bot-module extraction phases (22-28).
- **Extraction guidance carried forward:** before each later phase moves a package, re-running this audit's fill tests + the goldens will catch any untaken-branch behavior drift. The runtime-lifecycle branches excused in §3b are stdlib glue (identical post-move); the defensive-payload skips in §3c are fail-safe (identical post-move) — neither is a move-path divergence risk.
- No blockers.

## Self-Check: PASSED

- Created files verified on disk: `tests/test_golden_coverage_fill.py`, `21-COVERAGE-AUDIT.md`, `21-05-SUMMARY.md`.
- Modified source verified (pragma-only): `retry.py`, `lookup.py`, `selfcheck.py`, `uvmonitor.py`, `.gitignore`.
- Commit verified in git log: `312387c` (Task 1).
- Acceptance commands re-run green: no `fail_under`; every `weatherbot/` pragma names a reason; 732 passed ×2; `--snapshot-update` empty diff.

---
*Phase: 21-characterization-golden-test-harness*
*Completed: 2026-06-27*
