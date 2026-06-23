---
phase: 16-extract-shared-dispatch-spec
verified: 2026-06-23T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
---

# Phase 16: Extract Shared dispatch_spec Verification Report

**Phase Goal:** Lift the heterogeneous arg-adaptation if/elif ladder out of `on_message` and its identical twin in the CLI `_run_registry_command` into ONE shared dispatcher — `dispatch_reply(...)` (sync ladder) + `dispatch_spec(...)` (async off-loop-fetch wrapper) — in a new module `weatherbot/interactive/dispatch.py`, so the bot, CLI, and (later) panel call the same code with no duplicated dispatch table. Pure groundwork, behavior-preserving.
**Verified:** 2026-06-23
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP success criteria = must_haves)

| # | Truth | Status | Evidence |
| - | ----- | ------ | -------- |
| 1 | A single shared dispatcher resolves every registry command and returns the same CommandReply the command produces today | ✓ VERIFIED | `dispatch_reply` (dispatch.py:60-102) implements all 7 binding branches; registry has 10 commands (alerts/sun/wind/next-cloudy/uv/weekday-forecast/weekend-forecast/help/locations/status) all covered by the branch ladder + catch-all. `uv run pytest` 583 passed. CLI `help` renders real output via dispatch_reply (exit 0). |
| 2 | `on_message` produces byte-identical replies — proven by anti-drift / registry tests staying green | ✓ VERIFIED | **[BLOCKING gate]** `uv run pytest -q` → 583 passed, exit 0 (matches SUMMARY's claim of 575 prior + 8 new). test_bot.py / test_cli.py / test_registry.py / test_command.py contractual suites green. |
| 3 | Exactly ONE dispatch path — no second hardcoded command list or parallel arg-adaptation ladder | ✓ VERIFIED | `grep -nE 'spec.name == "next-cloudy"\|spec.name == "locations"\|spec.handler(result, config.cloud_threshold)' bot.py cli.py` → empty (exit 1). Ladder lives ONLY in dispatch.py. Both surfaces import & route through shared symbols (identity check: `dispatch.dispatch_spec is bot.dispatch_spec` True; `dispatch.dispatch_reply is cli.dispatch_reply` True). cli.py does NOT call dispatch_spec (sync-only, exit 1). |
| 4 | Shared dispatcher only drives read-only paths and writes nothing to store, sent-log, or scheduler | ✓ VERIFIED | `dispatch_reply` body: no fetch/render (grep `cache.lookup\|lookup_weather\|render_embed\|render_text` matches ONLY lines 149/153 inside `dispatch_spec`'s off-loop fetch, by design — not in the ladder). No `holder.replace\|record_sent\|claim_slot\|.write\|.commit\|add_job\|remove_job\|store.` anywhere in dispatch.py (exit 1). Dispatcher only invokes the registry handler + reads DaemonState. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `weatherbot/interactive/dispatch.py` | dispatch_reply (sync ladder) + dispatch_spec (async off-loop wrapper) | ✓ VERIFIED | 168 lines; both functions present with documented 7-branch verbatim order; module-top `from weatherbot.interactive.command import` (acyclic); heavy types under TYPE_CHECKING. Substantive, not a stub. |
| `tests/test_dispatch.py` | Shared-dispatcher resolution test | ✓ VERIFIED | 8 tests, one per binding branch (forecast/next-cloudy/uv/plain-location/status/locations/help) + read-only assertion (sentinel CommandReply returns unchanged, no fetch/render). 8 passed. |
| `weatherbot/interactive/bot.py` (modified) | on_message routes through dispatch_spec | ✓ VERIFIED | `await dispatch_spec(...)` at bot.py:284 inside the existing typing() block + non-propagating envelope; `render_embed(reply)`+send (296-297) and `except UnknownLocationError → channel.send(str(exc))` (292-295) stay at call site; outer `except Exception → _ERROR_REPLY` envelope (298) intact. |
| `weatherbot/cli.py` (modified) | _run_registry_command routes through dispatch_reply | ✓ VERIFIED | `dispatch_reply(...)` at cli.py:624 inside the handler-failure try/except; `lookup_weather` fetch + UnknownLocationError/httpx exit-code handling (599-609), `_cli_daemon_state(config)`, exit codes 0/1/2/3, `render_text`+`print` all stay at call site. |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| bot.py | dispatch.dispatch_spec | `await dispatch_spec(...)` inside typing block | ✓ WIRED | Import at bot.py:47; awaited call at :284; UnknownLocationError caught at call site; symbol-identity confirmed. |
| cli.py | dispatch.dispatch_reply | sync `dispatch_reply(...)` in handler try/except | ✓ WIRED | Import at cli.py:48; call at :624 inside failure envelope; symbol-identity confirmed; does NOT call dispatch_spec. |
| dispatch.py | command.parse_forecast_flags / forecast_cache_suffix | module-top import | ✓ WIRED | Top-level import (dispatch.py:43-46), acyclic; `import weatherbot.interactive.dispatch` succeeds. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| CLI argless command routes through dispatch_reply | `uv run weatherbot help` | Renders full command list, exit 0 | ✓ PASS |
| Both surfaces share identical dispatcher symbols | `python -c "dispatch.X is bot.X / cli.X"` | True / True | ✓ PASS |
| Import cycle absence | `python -c "import weatherbot.interactive.dispatch"` | import OK | ✓ PASS |
| Full contractual suite (byte-identical) | `uv run pytest -q` | 583 passed, exit 0 | ✓ PASS |
| Lint | `uv run ruff check` (4 touched files) | All checks passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| PANEL-10 | 16-01-PLAN | Panel command set derived from the v1.2 registry (single source of truth, no parallel hardcoded list; a new registry command surfaces without drift) | ✓ SATISFIED (groundwork portion) | The drift-prevention groundwork is complete: the arg-adaptation ladder now exists exactly once (dispatch.py); bot + CLI route through it; no parallel list. The "surfaces on the panel" half is forward-looking — Phase 17 introduces the panel as the third caller of the same shared code. REQUIREMENTS.md maps PANEL-10 → Phase 16 → Complete. No orphaned IDs. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER in any touched file | — | Clean. Debt-marker BLOCKER gate not triggered. |

Non-blocking review notes (from 16-REVIEW.md, carried as quality observations, NOT goal failures):
- **WR-01 (warning):** `dispatch_spec` (async wrapper) has no direct unit test — covered only transitively via test_bot.py. The drift-prone half (forecast-flags parse, suffix widening, 2-arg vs 3-arg lookup) is untested in isolation. Does not break the phase goal (behavior is green via the contractual suite) but reduces regression safety for Phase 17's reuse.
- **WR-02 (warning):** `dispatch_spec` now runs the WHOLE ladder off-loop (not just `status`), so weather-view/locations/help handlers moved from on-loop to off-loop in the bot. Benign (handlers are pure in-memory reads of an already-fetched payload) and tests stay green, but it is an undocumented divergence from the old on-loop behavior; the off-loop guard test only asserts "at least one executor dispatch."
- IN-01/IN-02/IN-03 (info): unused `cache` arg for argless specs, unused `_log`, two sequential executor hops — all cosmetic.

### Human Verification Required

None for this phase. This is a pure behavior-preserving internal refactor with no new user-visible behavior; the device-verifiable acceptance ("replies and exit codes unchanged") is fully encoded by the contractual test suite staying byte-identical green (583 passed). Per CLAUDE.md two-gate policy and SUMMARY, a `systemctl restart weatherbot` to pick up the refactor in production is a deferred Gate-2 milestone-close item, not a phase blocker — behavior is identical, no restart required for correctness.

### Gaps Summary

No gaps. All four ROADMAP success criteria are verified against actual source, not SUMMARY claims:
1. Single dispatcher resolving all 10 registry commands — confirmed in dispatch.py + full suite.
2. Byte-identical replies — confirmed by the BLOCKING `uv run pytest` gate (583 passed, exit 0).
3. Exactly one dispatch path — confirmed: grep gates empty in bot.py/cli.py, shared-symbol identity True, ladder lives only in dispatch.py.
4. Read-only discipline — confirmed: no fetch/render in `dispatch_reply`; no store/sent-log/scheduler writes anywhere in dispatch.py.

The Dimension-8 validation note in the verification request is honored: this phase has no RESEARCH.md/VALIDATION.md by design — its validation IS the existing contractual test suite staying byte-identical green, which it does. The two review warnings (WR-01, WR-02) are test-coverage / documentation quality notes that do not block goal achievement; they are surfaced here so they can be addressed when Phase 17 makes the panel the third caller of this shared code.

---

_Verified: 2026-06-23_
_Verifier: Claude (gsd-verifier)_
