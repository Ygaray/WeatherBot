---
phase: 31-send-atomicity-exactly-once-persistence-robustness
fixed_at: 2026-07-10
review_path: .planning/phases/31-send-atomicity-exactly-once-persistence-robustness/31-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
test_baseline: 829
test_after: 833
---

# Phase 31: Code Review Fix Report

**Fixed at:** 2026-07-10
**Source review:** 31-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (CR-01, WR-01, WR-02, WR-03, IN-01, IN-02)
- Fixed: 6
- Skipped: 0
- Test suite: 829 → 833 passing, exit 0 (4 new RED-before/GREEN-after tests). The
  "2 snapshots failed" line is the known pre-existing syrupy quirk (trust exit 0).
- No hub (`yahir_reusable_bot`) files edited — `is_auth_failure` was called via the
  existing import, not modified.

All 6 findings are new silent-failure seams in this hardening phase's own work, so
they were closed before the phase seals. Each fix is an atomic commit made with
hooks on the main working tree (no branch/worktree).

## Fixed Issues

### CR-01 + IN-01: F01 swallow didn't cover the post-success log/return

**Files modified:** `weatherbot/scheduler/daemon.py`, `tests/test_scheduler.py`
**Commit:** 5ddec50
**Applied fix:** Moved `_log.info("slot fired", ...)` INSIDE the post-send
log-and-swallow `try/except` so no statement after `result.ok` can reach the broad
`except` that calls `release_claim`. The custom `_LiveStderr` stderr sink can raise
`BrokenPipeError`/`OSError` on a broken pipe / closed console; pre-fix that raise
released a delivered claim → duplicate briefing on catch-up/restart. Belt-and-
suspenders: the recovery warning log inside the `except` is itself wrapped in
`try/except ...: pass`, so the claim is inviolable once `result.ok`.
**Test (IN-01):** Added `test_post_send_success_log_raise_keeps_claim` — patches the
daemon logger so the "slot fired" event raises `BrokenPipeError` and asserts
`was_sent(...) is True` with no `internal_error` alert. Verified RED against pre-fix
daemon.py, GREEN after.

### WR-01 + IN-02: read-only `_connect` URI truncated on a `?`/`#` in db_path

**Files modified:** `weatherbot/weather/store.py`, `tests/test_store.py`
**Commit:** 268f578
**Applied fix:** The read-only branch built `file:{db_path}?mode=ro` by raw f-string,
so SQLite parsed the first `?` in the path as the URI query delimiter and silently
opened a different, empty DB than the plain `sqlite3.connect(db_path)` write path
(a `was_sent` False for an already-sent slot → duplicate briefing). Now resolves to
an absolute path and percent-encodes it: `f"file:{quote(str(Path(db_path).resolve()))}?mode=ro"`
(added `from urllib.parse import quote`). Reads and writes always resolve to the
same file. Updated the `_connect` docstring (IN-02) to document the percent-encoding
and why it closes the URI-metacharacter hole.
**Test:** Added `test_read_only_path_metacharacter_reads_same_file_as_write` — writes
via the write path and asserts the read-only path sees the rows, using db paths
containing `?` and `#`. Verified RED before, GREEN after. Full store suite (31 tests)
passes; production `data/weatherbot.db` path is unaffected (no metacharacter).

### WR-02: broad-except recovery path in `fire_slot` was unguarded

**Files modified:** `weatherbot/scheduler/daemon.py`, `tests/test_scheduler.py`
**Commit:** 0c396ff
**Applied fix:** Wrapped the recovery side effects (`release_claim`, `record_alert`,
`_log.critical`) in an inner `try/except Exception` that logs a warning and never
re-raises, plus guarded the trailing `_log.exception`. A `database is locked` in the
recovery path can no longer escape the isolation envelope. Additionally wrapped each
`fire_slot` call inside `_run_catchup`'s loop in a `try/except` so one slot's escape
can never abort the remaining catch-up scan.
**Test:** Added `test_broad_except_recovery_db_error_does_not_escape` — a raising
channel drives the broad except while `release_claim` is patched to raise
`sqlite3.OperationalError("database is locked")`; asserts `fire_slot` returns None
instead of propagating. Verified RED before, GREEN after.

### WR-03: `fire_forecast_slot` treated a delivery-auth 401/403 as transient

**Files modified:** `weatherbot/scheduler/daemon.py`, `tests/test_scheduler.py`
**Commit:** d495815
**Applied fix:** The DELIV-04 carrier makes forecast `channel.send()` RAISE
`httpx.HTTPStatusError` on a 401/403, which pre-fix skipped the `ok=False` arm and
folded into the generic broad-except transient streak (3 missed forecasts before
signal). Now catches `httpx.HTTPStatusError` around the forecast send: on
`is_auth_failure(exc)` emits the immediate CRITICAL `forecast_slot_dead`
(reason `auth_failed`) and returns, bypassing the streak; re-raises non-auth
HTTPStatusErrors so existing transient handling is unchanged. Mirrors `fire_slot`'s
auth/transient split. `is_auth_failure` and `httpx` were already imported.
**Test:** Added `test_forecast_auth_failure_escalates_immediately` (with an
`_AuthRaisingSendChannel`) — one forecast 401 fire returns None and does NOT advance
the transient streak (immediate escalation, not after `_FORECAST_DEAD_AFTER`).
Verified RED before, GREEN after.

## Skipped Issues

None — all 6 findings fixed.

## Verification

- `uv run pytest -q` → 833 passed, exit 0 (baseline 829 + 4 new tests). The
  "2 snapshots failed" line is the pre-existing syrupy report quirk (exit 0).
- `uv run ruff check` on all touched files → clean, except three PRE-EXISTING
  out-of-scope findings in `daemon.py` (lines 69, 71 unused-import re-exports; line
  1483 unused `notifier`) that predate this work and are outside every changed
  region. Left untouched.
- Each of CR-01/WR-01/WR-02/WR-03 tests confirmed RED against pre-fix source and
  GREEN after (per-file `git stash` isolation).

---

_Fixed: 2026-07-10_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
