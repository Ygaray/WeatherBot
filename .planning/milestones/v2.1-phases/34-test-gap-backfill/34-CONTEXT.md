# Phase 34: Test-Gap Backfill - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Backfill the test coverage that let the v2.1 audit bugs hide. Two things only:

1. **Correct the false-green tests** — tests that pass against a broken implementation
   (the "concurrent" test that runs sequentially, weak/never-failing heartbeat, loose
   bounds, id==name shortcuts, missing ordering assertions).
2. **Add regression tests on the exact high-risk paths the fixed bugs lived in** —
   retry-then-alert exhaustion, catch-up across local midnight, rename-safe `Location.id
   != name`, dt-based imperial/metric daily pairing, weekend-block roll-forward, and the
   store atomicity / data-loss path.

Every correctness fix from Phases 29–33 must end this phase with **at least one test that
fails against the pre-fix behavior and passes against the fix** (SC-3).

**This is a tests-only phase.** The production fixes already shipped in Phases 29–33. No
new features. The one allowed exception: if a backfill test reveals a *still-latent* bug
(a fix that was incomplete or never landed), fold the minimal correctness fix in here
(see D-07) rather than shipping a red or watered-down test.
</domain>

<decisions>
## Implementation Decisions

### Test Organization & Traceability
- **D-01:** Extend the **existing per-module test files** next to the related tests —
  `tests/test_scheduler.py`, `tests/test_reliability.py`, `tests/test_models.py`,
  `tests/test_multiday.py`, `tests/test_cache.py`, `tests/test_reload_engine.py`. Do **not**
  create a new consolidated `test_test_gap_backfill.py` / `test_regression_v21.py` module.
  Matches the repo's one-file-per-module convention.
- **D-02:** Each new or corrected test **names its audit finding id and requirement** in the
  test name or docstring (e.g. `# F106 / HARD-TEST-01`) so the fix↔test↔finding chain is
  auditable from the test source alone.

### Concurrency Proof Mechanism (F106)
- **D-03:** Make `test_concurrent_double_fire_delivers_once` (`tests/test_scheduler.py:817`)
  **actually concurrent** by reusing the repo's established real-thread pattern from
  `tests/test_config_holder.py:89` (`test_concurrent_read_swap_safe`): spawn two worker
  threads that both call `fire_slot(...)` on the **same slot key**, synchronized with a
  `threading.Barrier` so both hit `claim_slot` simultaneously against the **shared
  file-backed `tmp_db`**; collect exceptions in a shared list (never swallow); assert
  **exactly one delivery** (one POST / one `sent_log` row) and no error. Deterministic
  *outcome* assertion — **no real `sleep`s**.
- **D-04:** Prove the test actually exercises atomicity (not decoration): include a
  co-located **meta-guard** showing a weakened `SELECT-then-INSERT` `claim_slot` variant
  (local monkeypatched shim) makes the concurrent test **fail**. The real atomicity lives
  in `store.py` `INSERT OR IGNORE` + `UNIQUE` — the test must break if that guarantee is
  removed.

### "Fails-Pre-Fix" Demonstration (SC-3)
- **D-05:** Default to **assertion-by-construction** — write the exact assertion the bug
  violated, so the test is red against pre-fix behavior by design.
- **D-06:** For the **highest-risk corrections** (F106 concurrency, F114 heartbeat
  tick/success separation, F112 loose-bound tightening), additionally record a **documented
  mutation spot-check in the Gate-1 self-UAT log**: temporarily revert/weaken the fix
  (`git stash` or a local shim), show the new test goes **red**, then restore and show
  **green**. Do **not** add a mutation-testing dependency (mutmut / cosmic-ray) to the
  project.

### Latent-Bug Escape Handling
- **D-07:** If a backfill test goes **red against current (post-fix) code**, treat it as a
  **real escape**, not a test bug. Correctness-first: fold the **minimal** fix into this
  phase (consistent with the milestone's no-backlog norm) and keep the pinning test.
  Escalate to the user only if the required fix is large or clearly out of this phase's
  scope.

### Coverage Ledger (SC-3 is broader than the F106–F116 cluster)
- **D-08:** F106–F116 are the **explicit** false-green + missing-coverage findings (see
  mapping in Specific Ideas). But SC-3 requires **every** Phase 29–33 correctness fix to
  have ≥1 pinning test. The planner/researcher must walk the Phase 29–33 fix ledger
  (`audit-raw.json` findings + each phase's `*-PLAN.md`) and confirm coverage. The roadmap
  **names two paths by id-less description** that must be covered even though they sit
  outside the F106–F116 test-quality cluster:
  - **Catch-up across local midnight** → the **F14** fix (Phase 32).
  - **Store atomicity / data-loss path** → the **F37** (no `UNIQUE` on `weather_onecall`) /
    **F63** (`executescript` force-commit) / **F01** (post-send bookkeeping re-fire) fixes
    (Phase 31).

### Claude's Discretion
- Exact test function names, whether to extract a shared threading/barrier helper into
  `conftest.py`, and the precise per-finding assertion wording are left to the
  planner/executor.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §"Phase 34: Test-Gap Backfill" — goal, success criteria (SC-1/2/3).
- `.planning/REQUIREMENTS.md` — `HARD-TEST-01` (correct false-greens), `HARD-TEST-02`
  (missing high-risk coverage).

### Audit findings (the source of truth for every gap this phase closes)
- `.planning/audit-raw.json` — v2.1 hardening audit, 116 findings. Test-gap cluster:
  **F106** (sequential "concurrent" test), **F107** (dt metric pairing untested),
  **F108** (id!=name path untested), **F109** (daily[0]==today unasserted), **F110**
  (Retry-After on mid-pause attempt untested), **F111** (weekend roll-forward untested),
  **F112** (loose burst-wait bound), **F113** (null `dt` in date-index untested), **F114**
  (heartbeat tick/success separation unpinned), **F115** (cache id==name shortcut),
  **F116** (reconcile register-before-remove ordering unpinned). Underlying bug findings
  the roadmap names by description: **F01/F14/F37/F63**.

### Fix ledger (fixes these tests pin — read to satisfy SC-3)
- `.planning/phases/31-send-atomicity-exactly-once-persistence-robustness/31-CONTEXT.md`
  (+ `31-*-PLAN.md`) — store atomicity / exactly-once / data-loss fixes (F01/F37/F63).
- `.planning/phases/32-timezone-date-boundary-correctness/32-CONTEXT.md`
  (+ `32-*-PLAN.md`) — midnight catch-up / date-boundary fixes (F14).
- `.planning/phases/33-interactive-panel-robustness/33-CONTEXT.md` — most recent fixes.

### Test assets & patterns
- `tests/test_config_holder.py:89` `test_concurrent_read_swap_safe` — the **canonical
  real-thread, error-collecting, no-sleep concurrency pattern** to reuse for F106 (D-03).
- `tests/conftest.py` — `tmp_db` (file-backed, line 53) and `load_fixture` (line 27)
  fixtures; the concurrency test needs the file-backed DB so both threads share one file.
- Target files for edits: `tests/test_scheduler.py`, `tests/test_reliability.py`,
  `tests/test_models.py`, `tests/test_multiday.py`, `tests/test_cache.py`,
  `tests/test_reload_engine.py`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`test_config_holder.py` threading harness**: `threading.Event` + shared `errors` list +
  bounded iterations + "no real sleeps, deterministic by construction" — copy this shape for
  the F106 concurrency test, swapping the reader/writer for two `fire_slot` racers gated by a
  `threading.Barrier`.
- **`conftest.py` fixtures**: `tmp_db` is file-backed (real sqlite file), so two threads see
  the same DB and `claim_slot`'s `INSERT OR IGNORE`/`UNIQUE` is genuinely raced. `load_fixture`
  loads recorded OpenWeather JSON for the models/multiday tests.

### Established Patterns
- Repo already uses real threads in 9 test files (`test_scheduler.py`, `test_reliability.py`,
  `test_reload.py`, …) — concurrency-via-threads is an accepted, in-house convention, not new.
- Atomicity guarantee under test lives at `weatherbot/weather/store.py` `claim_slot`
  (`INSERT OR IGNORE INTO sent_log` + `UNIQUE`) — the F106 test must fail if this degrades to
  SELECT-then-INSERT.

### Integration Points
- New tests attach to existing per-module files; no new package, fixture module, or CI wiring.
- SC-3 ties each test back to a Phase 29–33 fix — the fix code is already merged; this phase
  only adds/repairs the tests around it.

</code_context>

<specifics>
## Specific Ideas

**Finding → correction → target file (the explicit F106–F116 cluster):**

| Finding | Requirement | What the test must now do | File |
|---|---|---|---|
| F106 | HARD-TEST-01 | Real concurrent double-fire (barrier threads) → exactly-once; meta-guard fails on weakened claim_slot | `tests/test_scheduler.py` |
| F114 | HARD-TEST-01 | Assert `last_success_utc` **stays None** on a bare heartbeat tick (tick/success separation) | `tests/test_reliability.py` |
| F112 | HARD-TEST-01 | Tighten within-burst wait bound from `<150.0` to the real jittered ceiling `≈128.6s` | `tests/test_reliability.py` |
| F115 | HARD-TEST-01 | Use a **distinct** `id != name` so the cache-key collapse claim is actually proven | `tests/test_cache.py` |
| F116 | HARD-TEST-01 | Assert ReloadEngine reconcile does **register-before-remove** (no-gap-in-jobs) | `tests/test_reload_engine.py` |
| F108 | HARD-TEST-02 | Drive rename-safe `Location.id != name` through `fire_slot` / `plan_catchup` / alert-dedup | `tests/test_scheduler.py` |
| F110 | HARD-TEST-02 | Retry-After 429 landing on the mid-pause attempt (`attempt==BURST_SIZE`) collapse case | `tests/test_reliability.py` |
| F107 | HARD-TEST-02 | `from_payloads` dt-based imperial/metric daily **pairing** (not just forecast path) | `tests/test_models.py` |
| F109 | HARD-TEST-02 | Assert `from_payloads` `daily[0]` is the location-local **TODAY** | `tests/test_models.py` |
| F111 | HARD-TEST-02 | Weekend-block roll-forward (`kind='weekend'` whole-block-past branch) | `tests/test_multiday.py` |
| F113 | HARD-TEST-02 | Null `dt` in the date-index map that `select_days` indexes on | `tests/test_multiday.py` |

**Plus (roadmap-named, id-less — see D-08):** a regression test for **catch-up across local
midnight** (F14, Phase 32) and the **store atomicity / data-loss path** (F37/F63/F01, Phase 31).

**Known quirk to expect during UAT:** the suite prints "N snapshots failed" but exits 0 —
pre-existing syrupy report noise, not a golden diff. Trust the exit code + `.ambr` diff.

</specifics>

<deferred>
## Deferred Ideas

- **Mutation-testing tooling** (mutmut / cosmic-ray) as a permanent dependency — rejected for
  this phase (D-06 uses a manual, documented spot-check instead). Could be revisited as its
  own tooling decision if the milestone wants automated mutation coverage.
- **Cleanup-sweep findings** (dead code, docstring fixes, low-severity latent nits) — belong to
  **Phase 35: Cleanup Sweep**, not here.
- **Hub findings** (the 17 routed to `YahirReusableBot`, e.g. F40/F94) — out of this milestone;
  see `.planning/HUB-FINDINGS-HANDOFF.md`.

None else — discussion stayed within phase scope.

</deferred>

---

*Phase: 34-test-gap-backfill*
*Context gathered: 2026-07-13*
