# Phase 34: Test-Gap Backfill - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 34-test-gap-backfill
**Mode:** `--auto` (autonomous — Claude selected the recommended option for every area; no user prompts)
**Areas discussed:** Test organization & traceability, Concurrency proof mechanism (F106), "Fails-pre-fix" demonstration (SC-3), Latent-bug escape handling

---

## Test Organization & Traceability

| Option | Description | Selected |
|--------|-------------|----------|
| Extend existing per-module files, tag each test with its finding id | Add/repair tests in `test_scheduler.py`, `test_reliability.py`, `test_models.py`, `test_multiday.py`, `test_cache.py`, `test_reload_engine.py`; docstring the F-id + requirement | ✓ |
| New consolidated `test_regression_v21.py` module | One file gathering all backfill tests | |

**Auto-selected:** Extend existing per-module files (recommended default).
**Notes:** Matches the repo's one-file-per-module convention; keeps each test next to the code it pins. (→ D-01, D-02)

---

## Concurrency Proof Mechanism (F106)

| Option | Description | Selected |
|--------|-------------|----------|
| Real threads + `threading.Barrier` on shared file-backed `tmp_db`, assert exactly-once, reuse `test_config_holder.py` pattern; add meta-guard | Two `fire_slot` racers gated by a barrier hit `claim_slot` simultaneously; collect errors; assert one delivery; prove a weakened SELECT-then-INSERT fails it | ✓ |
| Monkeypatch an artificial delay into `claim_slot` to force interleave | Inject a sleep/hook to widen the race window | |
| Leave sequential, add a comment acknowledging the limitation | No real concurrency | |

**Auto-selected:** Real barrier-synchronized threads (recommended).
**Notes:** The repo already uses real threads in 9 test files; assertion is on *outcome* (exactly-once) not timing, so it stays deterministic with no sleeps. (→ D-03, D-04)

---

## "Fails-Pre-Fix" Demonstration (SC-3)

| Option | Description | Selected |
|--------|-------------|----------|
| Assertion-by-construction for all; documented git-stash mutation spot-check in Gate-1 UAT for the highest-risk few; no mutation-testing dependency | Write the assertion the bug violated; for F106/F114/F112 also show red→green by reverting the fix and record it in the SELF-UAT log | ✓ |
| Add mutmut / cosmic-ray as a project dependency and run automated mutation testing | Tooling-driven proof | |
| Trust-by-construction only, no red-run demonstration | No mutation check | |

**Auto-selected:** Construction + documented manual spot-check (recommended).
**Notes:** Avoids adding a heavyweight mutation-testing dependency for a personal bot while still proving the highest-risk tests actually bite. (→ D-05, D-06; mutation tooling → Deferred)

---

## Latent-Bug Escape Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Treat a red test against current code as a real escape; fold the minimal fix into this phase (correctness-first) | Keep the pinning test, add the small fix here; escalate only if large/out-of-scope | ✓ |
| Water down the test to green | Loosen the assertion | |
| Defer the fix to a backlog / later phase | Ship the gap | |

**Auto-selected:** Fold minimal fix in, correctness-first (recommended).
**Notes:** Consistent with the milestone's no-backlog norm — hardening milestones don't defer newly-found correctness gaps. (→ D-07)

---

## Claude's Discretion

- Exact test function names.
- Whether to extract a shared threading/barrier helper into `conftest.py`.
- Precise per-finding assertion wording.

## Deferred Ideas

- Mutation-testing tooling (mutmut / cosmic-ray) as a permanent dependency — rejected here.
- Cleanup-sweep findings (dead code, docstrings, low-severity nits) → Phase 35.
- Hub findings (17 routed to `YahirReusableBot`) → out of milestone; `HUB-FINDINGS-HANDOFF.md`.
