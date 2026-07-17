---
phase: 31-send-atomicity-exactly-once-persistence-robustness
plan: 02
subsystem: scheduler
tags: [daemon, fire_slot, fire_forecast_slot, exactly-once, delivery-result, bookkeeping, isolation]

# Dependency graph
requires:
  - phase: 31-send-atomicity-exactly-once-persistence-robustness
    plan: 01
    provides: "store WAL + busy_timeout + read/write split (de-risks the post-delivery lock contention that makes F01 reachable)"
  - phase: 30-auth-and-http-status-contract
    provides: "the httpx.HTTPStatusError auth-classification contract fire_slot's HTTP arms consume (untouched here)"
provides:
  - "fire_slot post-send bookkeeping (resolve_alert + stamp_success) is a local log-and-swallow: a post-delivery DB error keeps the won claim (no duplicate, no false internal_error) — F01/HARD-DELIV-01"
  - "fire_forecast_slot inspects channel.send()'s DeliveryResult: an ok=False routes to _note_forecast_failure (WR-05 dead-slot escalation) — only a clean delivery resets the streak — F08/HARD-DELIV-02"
  - "reproduce-first regression tests: test_post_send_db_error_keeps_claim (F01) + test_forecast_delivery_failure_escalates (F08)"
affects: [31-03, send-atomicity, exactly-once]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "swallow-on-committed for the post-delivery bookkeeping tail (mirrors the daemon.py cache-invalidate idiom): once result.ok, no path may reach release_claim"
    - "DeliveryResult inspection on the forecast path (mirrors fire_slot's sibling `if not result.ok:` arm): ok=False is a failure, not a silent success"

key-files:
  created: []
  modified:
    - weatherbot/scheduler/daemon.py
    - tests/test_scheduler.py

key-decisions:
  - "F01 fix is the minimal local swallow (D-01): wrap resolve_alert+stamp_success in one try/except that logs an outcome-only warning and KEEPS the claim; the pre-delivery release arms and the outer isolation envelope are untouched, so release_claim stays reachable ONLY for pre-delivery failures."
  - "F08 reuses _note_forecast_failure verbatim (D-02, Don't-Hand-Roll): the ok=False branch routes to the existing WR-05 escalation helper rather than duplicating the streak/CRITICAL/operator-alert logic; it returns None and never re-raises (isolation preserved)."
  - "F01 verify-first mandate satisfied (D-01a): both regression tests were RED against pre-fix daemon.py before the fixes landed (evidence recorded below)."

patterns-established:
  - "Pattern: post-commit bookkeeping is best-effort log-and-swallow — a committed side effect (delivered briefing) is the source of truth; downstream bookkeeping errors can never un-commit it."
  - "Pattern: a channel's DeliveryResult.ok is the ONLY delivery signal — never discard it (the channel never-raise contract means ok=False, not an exception)."

requirements-completed: [HARD-DELIV-01, HARD-DELIV-02]

coverage:
  - id: D1
    description: "A post-DELIVERY bookkeeping DB error (OperationalError in stamp_success/resolve_alert after result.ok) keeps the won claim: was_sent stays True (no re-fire) and no internal_error alert is recorded (F01)."
    requirement: "HARD-DELIV-01"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py#test_post_send_db_error_keeps_claim"
        status: pass
    human_judgment: false
  - id: D2
    description: "The F01 duplicate-send scenario is reproduced FIRST — test_post_send_db_error_keeps_claim FAILS against pre-fix daemon.py (release_claim runs → was_sent flips False), then PASSES after the swallow-wrap."
    requirement: "HARD-DELIV-01"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py#test_post_send_db_error_keeps_claim (RED evidence recorded)"
        status: pass
    human_judgment: false
  - id: D3
    description: "fire_forecast_slot inspects the DeliveryResult: an ok=False forecast delivery advances the dead-slot streak and crosses the CRITICAL/_note_forecast_failure threshold; _note_forecast_success is NOT called on ok=False — only a clean delivery resets the streak (F08)."
    requirement: "HARD-DELIV-02"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py#test_forecast_delivery_failure_escalates"
        status: pass
    human_judgment: false
  - id: D4
    description: "Both fire paths retain their one-bad-slot isolation envelope (the new branches return None, never re-raise); no regression in the existing pre-delivery-failure / clean-delivery scheduler tests; full project suite green."
    requirement: "HARD-DELIV-01"
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_scheduler.py -q (57 passed)"
        status: pass
      - kind: integration
        ref: "uv run pytest -q (817 passed, exit 0 — 815 baseline + 2 new)"
        status: pass
    human_judgment: false

# Metrics
duration: ~5min
completed: 2026-07-10
status: complete
---

# Phase 31 Plan 02: Send-Detection Seams (F01 duplicate-send + F08 forecast ok=False) Summary

**Closed the two send-detection seams in `daemon.py`, F01 verify-first: the post-send bookkeeping tail is now a log-and-swallow so a `database is locked` error after a delivered briefing keeps the won claim (no duplicate, no false `internal_error`), and `fire_forecast_slot` now inspects `channel.send()`'s `DeliveryResult` so a Discord `ok=False` routes to the WR-05 dead-slot escalation instead of silently resetting the streak.**

## Performance

- **Duration:** ~5 min
- **Completed:** 2026-07-10
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- **F01 (HARD-DELIV-01, D-01):** Wrapped `resolve_alert` + `stamp_success` in `fire_slot`'s success tail (daemon.py ~:339-340) in a single local `try/except` that logs an outcome-only warning and does NOT release the claim — mirroring the daemon.py cache-invalidate swallow-on-committed idiom. Once `result.ok`, the exactly-once claim is the source of truth for "delivered": a post-delivery bookkeeping error can no longer fall to the broad `except` (which, because `claimed=True`, would `release_claim` → delete the `sent_log` row → duplicate on catch-up/restart, plus a false `internal_error` alert). No code path after `result.ok` reaches `release_claim`.
- **F08 (HARD-DELIV-02, D-02):** `fire_forecast_slot` now captures `fc_result = channel.send(reply.text)` and, on `fc_result is not None and not fc_result.ok`, routes to the existing `_note_forecast_failure` (WR-05 dead-slot streak/CRITICAL/throttled operator alert) and returns `None` — mirroring `fire_slot`'s sibling `if not result.ok:` arm. Only a clean delivery (`ok`, or no channel wired) reaches `_note_forecast_success`, so only a clean delivery resets the streak. The failure helper is reused verbatim (no duplicated escalation) and the branch never re-raises — the outer `except`-return-`None` isolation envelope is untouched.
- **Verify-first (D-01a):** Authored both regression tests FIRST and recorded RED evidence against pre-fix `daemon.py` before either fix landed.

## Task Commits

Each task was committed atomically (with hooks — no `--no-verify`):

1. **Task 1: reproduce-first F01 + F08 regression tests (RED)** — `6e064e2` (test)
2. **Task 2: F01 fix — log-and-swallow post-send bookkeeping** — `9307117` (fix)
3. **Task 3: F08 fix — inspect forecast DeliveryResult; route ok=False to escalation** — `6589cf1` (fix)

**Plan metadata:** (see final docs commit)

## RED evidence (verify-first gate, Task 1 — D-01a mandate)

Both tests ran RED against the pre-fix `daemon.py` (before Tasks 2-3), proving the seams:

- **`test_post_send_db_error_keeps_claim` (F01)** — FAILED at `assert was_sent(tmp_db, "Home", "07:00", "2026-06-10") is True` with `AssertionError: assert False is True`. Root cause: the injected `sqlite3.OperationalError("database is locked")` in `stamp_success` (a post-delivery raise) fell to the broad `except`, which — because `claimed=True` — ran `release_claim`, deleting the `sent_log` row (`was_sent` → False) and recording a false `internal_error`. This is the exact F01 duplicate-send seam.
- **`test_forecast_delivery_failure_escalates` (F08)** — FAILED at `assert daemon_mod._forecast_failure_streaks.get(job_id, 0) == i + 1` with `AssertionError: assert 0 == 1`. Root cause: the pre-fix `fire_forecast_slot` discarded `channel.send()`'s return value and unconditionally called `_note_forecast_success`, so an `ok=False` delivery never advanced the streak (it was reset every fire) and the dead-slot escalation could never fire.

After the fixes both are GREEN.

## Files Created/Modified
- `weatherbot/scheduler/daemon.py` — F01: wrapped the `fire_slot` success-tail bookkeeping in a log-and-swallow `try/except` (keeps the claim). F08: `fire_forecast_slot` captures the `DeliveryResult` and branches on `.ok` (routes `ok=False` to `_note_forecast_failure` + `return None`) before `_note_forecast_success`.
- `tests/test_scheduler.py` — added `test_post_send_db_error_keeps_claim` (F01 reproduce-first) and `test_forecast_delivery_failure_escalates` (F08), plus a `_FailingSendChannel` stub whose `send()` returns `DeliveryResult(ok=False)`.

## Decisions Made
- **F01 minimal local swallow (D-01):** Chose the local `try/except` over restructuring the outer envelope — smallest diff, keeps `return result` in place, and leaves the pre-delivery release arms (`:266/:289/:315`) and the outer isolation `except` (`:349-379`) reachable ONLY for pre-delivery failures. The warning string is plain prose (does not embed the literal `internal_error` token, per plan note).
- **F08 reuse over re-implement (D-02):** The `ok=False` branch calls the existing `_note_forecast_failure` verbatim — it already self-guards its channel post and owns the WR-05 streak/CRITICAL/operator-alert logic — rather than duplicating the escalation. `return None` (never raise) preserves the one-bad-slot isolation invariant (T-03-07 / Pitfall 4).

## Deviations from Plan

None — plan executed exactly as written (F01 sequenced verify-first; both fixes mirror their named in-repo analogs).

## Issues Encountered
- None. The two new tests reuse the existing scheduler fixtures (`_FakeClient`, `_home_config`, `_forecast_config`, the `_PlainSendChannel` pattern) with only the new `_FailingSendChannel` (an `ok=False`-returning variant) added.

## Deferred Issues
- The 3 pre-existing ruff findings in `weatherbot/scheduler/daemon.py` (`PID_FILE` unused import :69/:71; `notifier` unused local :1456) are OUT OF SCOPE — they predate this plan (already logged in 31-01-SUMMARY.md's deferred items) and are not in any region this plan touched. `uv run ruff check` flags them but the pre-commit hooks passed on all three task commits. Left on the deferred list.

## Threat Surface
No new security-relevant surface introduced. The plan's `<threat_model>` (T-31-04 tampering / T-31-05 repudiation / T-31-06 DoS) is fully mitigated by the two fixes; the new warning logs are outcome-only (location.name + slot/kind/variant/time — never a secret/appid/webhook).

## Next Phase Readiness
- The two send-detection seams are closed on a hardened store (31-01's WAL + non-blocking reads). Plan 31-03 (fetch/deliver split + Discord 401/403 → auth) can proceed.
- **Deferred Gate-2 (milestone-close) obligation:** on the live systemd host `yahir-mint`, these are code-only fixes (no schema/data change) — a routine `sudo systemctl restart weatherbot` after deploy applies them; no special migration step.
- No blockers for 31-03.

## Self-Check: PASSED

All modified files exist on disk; all three task commits (`6e064e2`, `9307117`, `6589cf1`) are present in git history. Full suite green (817 passed, exit 0).

---
*Phase: 31-send-atomicity-exactly-once-persistence-robustness*
*Completed: 2026-07-10*
