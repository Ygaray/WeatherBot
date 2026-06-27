---
phase: 21-characterization-golden-test-harness
plan: 01
subsystem: testing
tags: [syrupy, pytest-cov, coverage, time-machine, golden-snapshot, characterization, branch-coverage, discord.py, apscheduler]

# Dependency graph
requires:
  - phase: 20-* (v1.3 close)
    provides: 652-test gateway-free suite + conftest fakes (load_fixture, tmp_db, fake_interaction, holder_scheduler) the goldens reuse verbatim
provides:
  - syrupy>=5.3.4 + pytest-cov>=7.1.0 dev deps (uv.lock pinned) — the locked snapshot + branch-coverage tools
  - "[tool.coverage.run] branch-mode config scoped to the 6 move-path packages (channels/scheduler/config/reliability/ops/interactive); weatherbot/weather excluded (D-07); no standing gate (D-08)"
  - "tests/conftest.py shared harness: FROZEN instant + json_snapshot/bytes_snapshot fixtures + embed_to_golden / schedule_plan_golden / onecall_rows_golden serializers"
  - Three discharged Wave-0 smoke confirms (A1/A3/A7) as standing regression tests in tests/test_golden_harness.py
affects: [21-02, 21-03, 21-04, 21-05, 22-channel-extraction, 23-scheduler-seam, 24-config-reload, 25-lifecycle, 26-registry, 27-discord-adapter, 28-physical-split]

# Tech tracking
tech-stack:
  added: [syrupy 5.3.4, pytest-cov 7.1.0, coverage 7.14.3 (transitive)]
  patterns: ["syrupy use_extension(<ExtensionClass>) per-test serializer selection (JSON for structured, SingleFile for raw bytes)", "time_machine.travel(FROZEN, tick=False) one-instant freeze (freeze, don't scrub — D-11)", "order-preserving embed/row/schedule serializer helpers feeding JSONSnapshotExtension", "branch-coverage one-time audit config (no fail_under standing gate)"]

key-files:
  created: [tests/test_golden_harness.py, "tests/__snapshots__/test_golden_harness/test_json_snapshot_roundtrips.json"]
  modified: [pyproject.toml, uv.lock, tests/conftest.py]

key-decisions:
  - "FROZEN = 2026-06-20 13:00 UTC (epoch 1781960400) — one shared instant for the whole harness (D-11 discretion); the RESEARCH/PATTERNS illustration epoch 1750424400 was a 2025 placeholder, recomputed to the real 2026 value."
  - "Wave-0 smoke test lives in a collectable tests/test_golden_harness.py module, NOT in conftest.py — pytest never collects tests defined in conftest.py (it is a fixtures file), so the plan's `-k frozen_epoch_reaches_render` acceptance command would have matched 0 tests."
  - "A3 confirmed TRUE: time_machine.travel(FROZEN) DOES freeze discord.utils.utcnow() — the documented monkeypatch fallback is NOT in force."

patterns-established:
  - "Per-test syrupy extension selection via snapshot.use_extension(JSONSnapshotExtension|SingleFileSnapshotExtension) (D-02)"
  - "embed_to_golden(embed) -> ordered dict {title, description, color, fields:[{name,value,inline}]} excluding embed.timestamp (D-11)"
  - "schedule_plan_golden(scheduler) -> [{job_id, trigger:str(job.trigger), next_run_time}] sorted by job_id (explicit ORDER, D-11)"
  - "onecall_rows_golden(db_path) -> byte-contract columns only, explicit ORDER BY units,location_name; scrub id + fetched_at_utc (D-11)"

requirements-completed: [BHV-01]

# Metrics
duration: ~18min
completed: 2026-06-27
status: complete
---

# Phase 21 Plan 01: Characterization / Golden-Test Harness (Wave 0) Summary

**Stood up the byte-identical golden-test harness — syrupy 5.3.4 + pytest-cov 7.1.0, a branch-coverage config scoped to the 6 move-path packages, and the shared conftest serializers (FROZEN instant, JSON/bytes syrupy fixtures, embed/schedule/DB-row golden helpers) — and discharged all three open Wave-0 smoke assumptions (A1/A3/A7) so Wave 1 builds on confirmed mechanics.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-27 (Task 2, post Task-1 human approval)
- **Completed:** 2026-06-27
- **Tasks:** 2 executed (Task 1 was a pre-cleared blocking-human legitimacy gate — human typed "approved")
- **Files modified:** 3 (pyproject.toml, uv.lock, tests/conftest.py) + 2 created (tests/test_golden_harness.py, 1 snapshot)

## Wave-0 Smoke Confirms (RECORDED for Wave 1)

These three `[ASSUMED]` items were discharged empirically at execution time and are now standing regression tests in `tests/test_golden_harness.py`. **Wave 1 (Plans 21-02..21-05) can rely on them:**

| # | Assumption | Result | Detail |
|---|-----------|--------|--------|
| **A1** | syrupy `use_extension` call shape on 5.3.4 | ✅ CONFIRMED | `snapshot.use_extension(<ExtensionClass>)` — pass the extension **class** (not an instance). Verified sig: `use_extension(self, extension_class: type[AbstractSyrupyExtension] | None = None) -> SnapshotAssertion`. A trivial structured `assert {...} == json_snapshot` round-trips and writes an order-preserving `.json` golden. **(syrupy has no `__version__` attr — use `importlib.metadata.version('syrupy')` → `5.3.4` if you need it.)** |
| **A3** | `time_machine.travel(FROZEN)` reaches `discord.utils.utcnow()` (the embed `Updated <t:…>` epoch) | ✅ CONFIRMED — **freeze works, NO fallback needed** | Inside `time_machine.travel(FROZEN, tick=False)`, a real `render_embed(...).description` contains `Updated <t:1781960400:t> (<t:1781960400:R>)` (the FROZEN epoch). The documented `monkeypatch.setattr("weatherbot.interactive.bot.discord.utils.utcnow", lambda: FROZEN)` fallback is **NOT in force** — Wave-1 embed goldens just wrap the render in `time_machine.travel(FROZEN, tick=False)`. |
| **A7** | `str(job.trigger)` (CronTrigger `__str__`) is stable/deterministic | ✅ CONFIRMED | Two identically-constructed `CronTrigger(hour=9, minute=0, day_of_week='mon-fri', timezone='America/New_York')` both render exactly `cron[day_of_week='mon-fri', hour='9', minute='0']`. Safe as the schedule golden's byte-exact primary. |

**FROZEN epoch note for Wave 1:** `FROZEN = datetime(2026, 6, 20, 13, 0, 0, tzinfo=timezone.utc)` → epoch **1781960400**. Embed goldens will contain the literal `Updated <t:1781960400:t> (<t:1781960400:R>)` (epoch frozen, `:t`/`:R` format string preserved — over-scrubbing trap avoided).

## Accomplishments
- Installed the two CONTEXT-locked tools at their exact pinned versions: `syrupy==5.3.4`, `pytest-cov==7.1.0` (+ transitive `coverage==7.14.3`), `uv.lock` updated.
- Added `[tool.coverage.run]` (branch mode, 6 move-path package source list, `weatherbot/weather` excluded per D-07) + `[tool.coverage.report]` (`show_missing`, `exclude_also` for `if TYPE_CHECKING:` / `raise NotImplementedError` / bare ellipsis). **No `fail_under` standing gate (D-08), no `--cov` in pytest `addopts`** — the audit is invoked explicitly in Plan 05.
- Added the shared conftest harness every Wave-1 golden consumes: `FROZEN`, `json_snapshot`/`bytes_snapshot` fixtures, and the `embed_to_golden` / `schedule_plan_golden` / `onecall_rows_golden` serializers.
- Discharged + locked in the three Wave-0 smokes (A1/A3/A7) as standing tests.
- **BHV-01 held:** full suite **656 passed** (652 pre-existing + 4 new harness smokes, 1 snapshot) — zero regression. `git diff --name-only weatherbot/` is **empty** (zero production-source change).

## Task Commits

1. **Task 1: Legitimacy checkpoint (syrupy + pytest-cov)** — pre-cleared blocking-human gate; human typed "approved" (orchestrator verified both on pypi.org: canonical repos github.com/syrupy-project/syrupy + github.com/pytest-dev/pytest-cov, CONTEXT-locked D-01/D-05). No code committed for this gate.
2. **Task 2: Install + branch-coverage config** — `8409503` (chore)
3. **Task 3: Conftest helpers + Wave-0 smokes** — `adcbc51` (test, TDD: smoke recorded via deliberate `--snapshot-update` per D-04)

## Files Created/Modified
- `pyproject.toml` — added syrupy + pytest-cov to `[dependency-groups] dev`; added `[tool.coverage.run]` (branch=true, 6 move-path source entries) + `[tool.coverage.report]`.
- `uv.lock` — pinned resolved hashes for syrupy 5.3.4, pytest-cov 7.1.0, coverage 7.14.3.
- `tests/conftest.py` — added `FROZEN`, `json_snapshot`/`bytes_snapshot` fixtures, `embed_to_golden` / `schedule_plan_golden` / `onecall_rows_golden` helpers (additive; existing fixtures untouched).
- `tests/test_golden_harness.py` (new) — 4 standing Wave-0 smokes (A1/A3/A7 + an `embed_to_golden` projection-contract test).
- `tests/__snapshots__/test_golden_harness/test_json_snapshot_roundtrips.json` (new) — the A1 round-trip golden.

## Decisions Made
- **FROZEN epoch corrected to the real 2026 value (1781960400).** RESEARCH/PATTERNS illustrated `1750424400`, which is the 2025-06-20 epoch; the constant `datetime(2026,6,20,13,0,0,UTC)` resolves to `1781960400` and the harness uses that. Wave-1 embed goldens must expect `1781960400`.
- **Coverage `source` uses package directory paths** (`weatherbot/channels`, …) exactly as specified in RESEARCH § coverage config (D-07).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Wave-0 smoke test moved from conftest.py to a collectable test module**
- **Found during:** Task 3 (conftest helpers + Wave-0 smoke)
- **Issue:** The plan's Task 3 action says "Add a Wave-0 smoke test `test_frozen_epoch_reaches_render`" to `tests/conftest.py`, and the acceptance command is `uv run pytest tests/ -k frozen_epoch_reaches_render`. But pytest does **not collect test functions defined in `conftest.py`** (it is a fixtures/plugin module, never a test module), so the test was reported as `652 deselected` — the acceptance command matched 0 tests.
- **Fix:** Kept the shared helpers/fixtures (FROZEN, json_snapshot/bytes_snapshot, the three serializers) in `conftest.py` where Wave-1 imports them, and moved the smoke **tests** into a new collectable module `tests/test_golden_harness.py` (which imports the helpers from conftest). Added 3 more standing smokes there (A1 json round-trip, A7 CronTrigger stability, an `embed_to_golden` projection-contract test) to lock all three Wave-0 confirms, not just A3.
- **Files modified:** tests/conftest.py (smoke removed), tests/test_golden_harness.py (new)
- **Verification:** `uv run pytest tests/ -k frozen_epoch_reaches_render` → **1 passed**; `uv run pytest tests/test_golden_harness.py` → **4 passed, 1 snapshot passed**.
- **Committed in:** `adcbc51` (Task 3 commit)

**2. [Rule 1 - Bug] Corrected the FROZEN-epoch comment literal**
- **Found during:** Task 3
- **Issue:** A copied comment claimed `2026-06-20 13:00 UTC → epoch 1750424400`; the real epoch is `1781960400` (1750424400 is the 2025 date). A wrong epoch literal in a shared comment would mislead every Wave-1 golden author.
- **Fix:** Recomputed and corrected the comment to `1781960400`. The `FROZEN` constant itself was already correct.
- **Files modified:** tests/conftest.py
- **Verification:** `int(FROZEN.timestamp())` == 1781960400; the smoke asserts this epoch appears in a real render.
- **Committed in:** `adcbc51` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug)
**Impact on plan:** Both were necessary for the plan's own acceptance command to pass and for Wave-1 correctness. No scope creep — the harness surface is exactly as specified (same helpers, same config, same FROZEN instant). Also applied `ruff format` to the new conftest block (project lint convention) — no behavior change.

## Issues Encountered
None beyond the two deviations above. The `syrupy.__version__` attribute does not exist (cosmetic — the smoke uses `importlib.metadata.version` where a version string is needed); all three assumptions discharged on first empirical check.

## User Setup Required
None - no external service configuration required. (Task 1's pypi.org legitimacy verification was completed by the human before execution.)

## Next Phase Readiness
- **Wave 1 (Plans 21-02..21-05) is unblocked.** Every shared helper and fixture it consumes is committed and import-tested: `from tests.conftest import FROZEN, embed_to_golden, schedule_plan_golden, onecall_rows_golden` and the `json_snapshot`/`bytes_snapshot` fixtures.
- All three `[ASSUMED]` Wave-0 mechanics are confirmed (see table above) — no fallback paths in force.
- The branch-coverage audit config is in place but **not yet run** — that one-time audit (D-08) is Plan 21-05's job (`uv run pytest --cov --cov-branch --cov-report=term-missing`).
- Exception-identity tuples for D-13 (Plan 21-04) were pre-verified in PATTERNS.md (note the `pydantic.ValidationError.__module__ == "pydantic_core._pydantic_core"` correction).

## Self-Check: PASSED

- Created files verified on disk: `tests/test_golden_harness.py`, `tests/__snapshots__/test_golden_harness/test_json_snapshot_roundtrips.json`, `21-01-SUMMARY.md`.
- Modified files verified: `pyproject.toml`, `uv.lock`, `tests/conftest.py`.
- Commits verified in git log: `8409503` (Task 2), `adcbc51` (Task 3).

---
*Phase: 21-characterization-golden-test-harness*
*Completed: 2026-06-27*
