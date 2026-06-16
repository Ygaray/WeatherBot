---
phase: 08-configholder-fire-slot-reads-from-holder-refactor
verified: 2026-06-15T00:00:00Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: none
---

# Phase 8: ConfigHolder & `fire_slot` Reads-From-Holder Refactor Verification Report

**Phase Goal:** The live config is owned by a lock-guarded `ConfigHolder` that hands out immutable snapshots, and `fire_slot` reads `holder.current()` instead of a captured `config` kwarg — the mandatory correctness prerequisite so a later reload actually changes what unchanged jobs render.
**Verified:** 2026-06-15
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC#1: `ConfigHolder` exposes `current()` (lock-free read) and `replace()` (lock-guarded atomic rebind) | ✓ VERIFIED | `weatherbot/config/holder.py:50` `current()` returns `self._config` with no lock; `:59-66` `replace()` rebinds under `with self._lock`. `threading.Lock()` at `:48`. |
| 2 | SC#1c: concurrent read/swap is safe (no torn/None read) | ✓ VERIFIED | `tests/test_config_holder.py:89` `test_concurrent_read_swap_safe` — 8 reader threads × 1 writer × 5000 swaps, errors collected, `assert not errors`. PASSES. |
| 3 | SC#2: `fire_slot` reads `holder.current()` ONCE at top, threads one snapshot through whole lifecycle | ✓ VERIFIED | `daemon.py:148-153` resolves `snapshot` once; reliability budget read at `:200-202` uses `snapshot.reliability.*`; `send_now(config=snapshot)` at `:209-211`. Single object, never re-read. |
| 4 | SC#2a: in-flight job keeps its original snapshot across a mid-job `replace()` | ✓ VERIFIED | `tests/test_config_holder.py:143` `test_inflight_job_keeps_snapshot` — blocks fire mid-send, calls `replace(config_b)`, asserts `seen[0] is config_a`. PASSES. |
| 5 | SC#2b/D-04: an UNCHANGED job renders the NEW config after `replace()` (phase core proof) | ✓ VERIFIED | `tests/test_config_holder.py:185` `test_unchanged_job_renders_after_replace` — `replace(config_b)` then fire, asserts `seen[0] is config_b`. PASSES. |
| 6 | SC#3: full existing suite stays green; daemon behaves identically (no reload wired) | ✓ VERIFIED | `.venv/bin/python -m pytest -q` → **226 passed, 0 failed** (215 baseline + 11 new Phase 8 tests). Matches SC#3's ~226 expectation exactly. |
| 7 | D-01: explicit `config=` override WINS over the holder | ✓ VERIFIED | `daemon.py:148` checks `config is not None` BEFORE `holder is not None`. `tests/test_config_holder.py:214` `test_config_override_wins` PASSES. |
| 8 | D-02: all 5 config models `frozen=True`; mutation raises `pydantic.ValidationError` | ✓ VERIFIED | `models.py` lines 45/93/126/154/219 — 5× `ConfigDict(extra="forbid", frozen=True)`. `tests/test_models.py:272` `test_frozen_rejects_mutation` (5 parametrized, asserts `pydantic.ValidationError`, not `FrozenInstanceError`). PASSES. |
| 9 | D-03: `_register_jobs`/`_run_catchup`/`_announce_schedule` source config from holder; stable job id + `_heartbeat_tick` untouched | ✓ VERIFIED | `daemon.py:348/402/440` all take `holder: ConfigHolder` and call `holder.current()` (`:370/414/461`); `add_job(kwargs={"holder": holder})` at `:385`; stable id `f"{location.name}|{slot.time}|{slot.days}"` unchanged at `:396`; `_heartbeat_tick(db_path)` unchanged at `:330`; no `"config": config` capture remains. |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `weatherbot/config/holder.py` | `ConfigHolder` with `current()` + `replace()` | ✓ VERIFIED | 67 lines, `class ConfigHolder`, lock-free `current()`, lock-guarded `replace()`, no validation/logging/deepcopy/RLock/Settings; `Config` import TYPE_CHECKING-gated. |
| `weatherbot/config/models.py` | 5× `frozen=True` | ✓ VERIFIED | Exactly 5 occurrences; no v1 `class Config:` / `allow_mutation` idiom; field validators/properties unchanged. |
| `weatherbot/scheduler/daemon.py` | holder-reading `fire_slot` + 3 holder-threaded readers + `run_daemon` constructs holder | ✓ VERIFIED | `holder.current()` in fire_slot + all 3 readers; `ConfigHolder(config)` at `:614`; top-level cycle-free import at `:61`. |
| `tests/test_config_holder.py` | 6 named holder/fire_slot tests | ✓ VERIFIED | 238 lines; all 6 node IDs present and passing. |
| `tests/test_models.py` | parametrized frozen guard | ✓ VERIFIED | `test_frozen_rejects_mutation`, 5 cases, asserts `pydantic.ValidationError`. |
| `tests/test_scheduler.py` | `_register_jobs` callsite wraps cfg in `ConfigHolder` | ✓ VERIFIED | `ConfigHolder(cfg)` at `:551`; import at `:20`. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `daemon.py fire_slot` | `ConfigHolder.current()` | `snapshot = config if config is not None else holder.current()` | ✓ WIRED | `daemon.py:148-153`. |
| `daemon.py _register_jobs` | fire_slot job kwargs | `add_job(kwargs={"holder": holder})` | ✓ WIRED | `daemon.py:385`; no `"config": config` remains. |
| `daemon.py run_daemon` | `ConfigHolder` | `holder = ConfigHolder(config)` | ✓ WIRED | `daemon.py:614`. |
| `daemon.py _run_catchup` | fire_slot | `fire_slot(..., holder=holder, ...)` | ✓ WIRED | `daemon.py:467-470`; catchup.py PURE-INPUT, unchanged (`git diff --stat` empty). |
| `models.py` | pydantic ConfigDict | `ConfigDict(extra="forbid", frozen=True)` ×5 | ✓ WIRED | 5 occurrences. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `fire_slot` | `snapshot` | `holder.current()` (live `Config`) → `send_now(config=snapshot)` + `snapshot.reliability.*` | Yes — real `Config` flows through delivery; proven by `test_unchanged_job_renders_after_replace` showing a post-`replace()` `config_b` reaching `send_now` | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite green (SC#3) | `.venv/bin/python -m pytest -q` | 226 passed, 0 failed | ✓ PASS |
| Phase 8 tests isolated | `pytest test_config_holder.py + test_frozen_rejects_mutation + test_jobs_registered_per_location_tz -q` | 12 passed | ✓ PASS |
| frozen models reject mutation | `test_frozen_rejects_mutation` (5 cases) | 5 passed | ✓ PASS |
| concurrent read/swap safe | `test_concurrent_read_swap_safe` (8r×1w×5000) | passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| (none) | All 4 plans declare `requirements: none (prerequisite — unblocks CFG-01/CFG-05 in Phase 9)` | Prerequisite refactor | ✓ CONSISTENT | ROADMAP Phase 8 entry: "no v1.1 requirement closes here; unblocks CFG-01/05 in Phase 9". REQUIREMENTS.md `:92` explicitly lists Phase 8 as a foundation/prerequisite phase without a closing requirement. CFG-01 (`:83`) and CFG-05 (`:87`) both map to **Phase 9**, status Pending. No orphaned or dropped REQ-ID. |

The `requirements: none` declaration is correct by design and consistent across PLAN frontmatter, ROADMAP, and REQUIREMENTS.md. Per task instructions, "no requirements closed" is NOT flagged as a gap.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No `TBD`/`FIXME`/`XXX` debt markers in any modified file | — | None |
| `models.py` | 100, 221 | `frozen=True` does not deep-freeze `locations`/`schedule` list containers (WR-01) | ℹ️ Info (accepted boundary) | Documented and ACCEPTED per CONTEXT D-02 (Pitfall 3: guard targets field rebinding only; no production code mutates lists in place — verified by grep). NOT a phase-goal gap. |

WR-02 (contract-validation guard inside the broad `try`) and WR-03 (lock docstring overstatement) from 08-REVIEW.md are latent/documentation-clarity warnings on inactive paths (both production callers always pass an argument). Neither blocks the phase goal; both are correctness-neutral today.

### Human Verification Required

None. All success criteria are programmatically verifiable (holder concurrency, single-read-per-fire, frozen immutability, and the full suite) and pass. No visual/real-time/external-service surface was introduced.

### Gaps Summary

No gaps. All three ROADMAP Success Criteria (SC#1 holder API + concurrency safety; SC#2 single-read-per-fire with mid-job-swap and unchanged-job-renders-after-replace proofs; SC#3 full suite green at 226) are verified against the codebase, not merely claimed. All four locked decisions hold: D-01 (override-wins), D-02 (5 frozen models), D-03 (three holder-threaded readers, stable job id and heartbeat untouched), D-04 (`replace()` ships, non-validating). The `requirements: none` prerequisite declaration is consistent — CFG-01/CFG-05 correctly defer to Phase 9 with no orphaned IDs. The single known weakness (WR-01 frozen-list shallowness) is an explicitly accepted boundary per CONTEXT D-02, with no in-place list mutation anywhere in production code.

---

_Verified: 2026-06-15_
_Verifier: Claude (gsd-verifier)_
