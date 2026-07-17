---
phase: 31-send-atomicity-exactly-once-persistence-robustness
verified: 2026-07-10T00:00:00Z
status: passed
score: 16/16 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 31: Send Atomicity, Exactly-Once & Persistence Robustness — Verification Report

**Phase Goal:** Close the send-spine edge seams and the persistence-concurrency defect that feeds them. Post-send bookkeeping can no longer release an already-delivered claim (the F01 duplicate-briefing critical), forecast-slot delivery failures are detected and alerted, retry reuses the fetched payload instead of re-fetching on a delivery-only failure, and send failures are classified correctly (auth vs transient). SQLite runs in WAL with a busy_timeout and store writes are atomic.
**Verified:** 2026-07-10
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

Every must-have was verified against the ACTUAL source (not SUMMARY claims). The
phase's own code-review round (CR-01 Critical + WR-01/02/03) was independently
re-verified in source — all four fixes are real and present. Each behavior-dependent
truth (state transition / cancellation-cleanup invariant) is backed by a passing
named behavioral test, so no truth rests on symbol presence alone.

### Observable Truths — Roadmap Success Criteria

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | A DB error in post-send bookkeeping after delivery never releases the won claim — slot stays sent, catch-up/restart does not re-deliver, no false internal_error (F01, verified first) | ✓ VERIFIED | `daemon.py:370-393` — `resolve_alert`+`stamp_success`+`_log.info("slot fired")` all INSIDE one log-and-swallow `try/except` (368); the `except` (380) never calls `release_claim`, its warning is itself guarded (384-392); `return result` (393) reached before the broad `except` (394) whose `release_claim` is at 410. Tests `test_post_send_db_error_keeps_claim` + `test_post_send_success_log_raise_keeps_claim` (BrokenPipeError on "slot fired") PASS. |
| SC2 | A forecast-slot delivery that fails (Discord non-2xx / ok=False) is detected — failure streak + dead-slot CRITICAL fire instead of counting as success | ✓ VERIFIED | `daemon.py:614-649` — `fc_result = channel.send(...)` captured (626); `if not fc_result.ok:` routes to `_note_forecast_failure` + returns None (640-649); `_note_forecast_success` (653) only on clean delivery. Test `test_forecast_delivery_failure_escalates` PASS. |
| SC3 | Delivery-only failure retries the already-fetched payload (no re-fetch); Discord 401/403 maps to auth_failed rather than burning the full transient schedule | ✓ VERIFIED | `cli.py:213-225` — `fetch_cache[0]` reused on retry, `lookup_weather` runs once per fire; fetch-429 raises pre-cache (RELY-02). `discord.py:132-138` raises redacted `httpx.HTTPStatusError` on 401/403 → `daemon.py:273-282` `is_auth_failure` → `REASON_AUTH_FAILED`. Tests `test_retry_reuses_payload` + `test_discord_auth_short_circuit` PASS; 24 `test_reliability.py` Retry-After tests green. |
| SC4 | Concurrent status reads + daemon writes no longer raise database is locked — WAL + busy_timeout, reads take no write lock, multi-step writes transactional | ✓ VERIFIED | `store.py:205` WAL set once in `init_db`; `:189` `busy_timeout=5000` on every connect; 4 read fns open `read_only=True` (281/439/534/552), `executescript(_SCHEMA)` count == 1 (init_db only); `persist` (243-264) both variant INSERTs + one commit in a single `with _connect` transaction. `wiring.py:143` calls `init_db(db_path)` once at startup. Tests `test_wal_and_busy_timeout_are_set`, `test_reads_take_no_write_lock`, `test_onecall_write_atomic` PASS. |

### Observable Truths — Plan must_haves

| # | Truth (plan) | Status | Evidence |
|---|-------|--------|----------|
| 1 | HARD-DELIV-01: no code path after result.ok reaches release_claim; post-send bookkeeping is log-and-swallow (CR-01 landed) | ✓ VERIFIED | daemon.py:370-393 (see SC1). CR-01 gap (`_log.info` outside swallow) is genuinely closed — success log is inside the swallow; `test_post_send_success_log_raise_keeps_claim` exercises exactly that raise site and passes. |
| 2 | HARD-DELIV-02: fire_forecast_slot inspects ok AND (WR-03) escalates auth 401/403 immediately | ✓ VERIFIED | daemon.py:625-639 — `except httpx.HTTPStatusError` → `is_auth_failure` → immediate CRITICAL `forecast_slot_dead`, bypasses streak; non-auth re-raised. Test `test_forecast_auth_failure_escalates_immediately` PASS. |
| 3 | HARD-DELIV-03: send_now reuses single fetched payload on delivery-only retry (fetch_cache); fetch-429 Retry-After preserved | ✓ VERIFIED | cli.py:207-225; daemon.py:247-269 (single-slot `fetch_cache` threaded through `_attempt`). test_retry_reuses_payload + test_reliability.py green. |
| 4 | HARD-DELIV-04: discord._post raises redacted-URL httpx.HTTPStatusError on 401/403 only → auth_failed; token never in str(exc)/logs | ✓ VERIFIED | discord.py:132-144 — `_AUTH_STATUSES={401,403}` raises with `_REDACTED_WEBHOOK_URL="https://discord/redacted"`, status-only message; all other non-2xx return ok=False. `self._url` never passed into the exc/request/response. test_discord_auth_short_circuit + test_channel.py green. |
| 5 | HARD-STORE-01: store writes atomic (single-transaction persist); reads take no write lock | ✓ VERIFIED | store.py:243-264 single `with _connect` + one commit; reads open read_only, no executescript. test_onecall_write_atomic + test_reads_take_no_write_lock PASS. |
| 6 | HARD-STORE-02: SQLite WAL + busy_timeout; reads mode=ro (WR-01 percent-encoded URI) | ✓ VERIFIED | store.py:185 `f"file:{quote(str(Path(db_path).resolve()))}?mode=ro"` (WR-01 fix); :205 WAL; :189 busy_timeout. test_wal_and_busy_timeout_are_set + test_read_only_path_metacharacter_reads_same_file_as_write PASS. |
| 7 | Idempotent init_db; local_date byte-for-byte round-trip; empty/single-variant atomic (backstop) | ✓ VERIFIED | init_db all `IF NOT EXISTS` / `INSERT OR IGNORE` (:201-206); local_date bound as parameter, no normalization; test_onecall_write_atomic asserts round-trip. |
| 8 | Reads use mode=ro so accidental write raises readonly-db error (backstop) | ✓ VERIFIED | store.py:181-186 read-only branch uses `mode=ro` URI with `uri=True`; docstring documents the guarantee (IN-02 fix). |
| 9 | One bad slot never kills the APScheduler worker — both fire paths keep except-return-None isolation; WR-02 recovery guarded | ✓ VERIFIED | daemon.py:394-445 broad `except` with all recovery bookkeeping wrapped in inner guarded try (428-436) + guarded `_log.exception` (437-444); `_run_catchup` wraps each fire_slot (1256-1274). test_broad_except_recovery_db_error_does_not_escape PASS. |
| 10 | Forecast ok=False on first fire increments streak toward dead-slot threshold (backstop) | ✓ VERIFIED | daemon.py:640-649 routes ok=False to `_note_forecast_failure` (streak advance); only clean delivery resets. test_forecast_delivery_failure_escalates PASS. |
| 11 | Retried delivery treats Discord ok=False as ONE transient unit — no second retry layer (backstop) | ✓ VERIFIED | daemon.py:319-343 single `retrying(_attempt)` scope; channel owns its own within-attempt 429 wait; no nested retry added. |

**Score:** 16/16 truths verified (0 present-behavior-unverified). All behavior-dependent truths carry passing behavioral tests.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `weatherbot/weather/store.py` | `_connect` helper (WAL/busy_timeout/read-only), init_db owns schema, 4 read fns read-only, atomic persist | ✓ VERIFIED | `_connect` (158), init_db WAL+schema (193-207), executescript count == 1, 4 read_only sites, persist atomic. |
| `weatherbot/scheduler/daemon.py` | F01 log-and-swallow (incl. success log), F08 ok=False inspection, WR-02/WR-03 guards | ✓ VERIFIED | Lines 370-445 (F01+WR-02), 614-649 (F08+WR-03), 1256-1274 (catchup guard). |
| `weatherbot/channels/discord.py` | 401/403 raises redacted httpx.HTTPStatusError; other non-2xx ok=False | ✓ VERIFIED | Lines 42-43, 132-144. |
| `weatherbot/cli.py` | send_now fetch-once / deliver-retry via fetch_cache | ✓ VERIFIED | Lines 142-238. |
| `weatherbot/scheduler/wiring.py` | init_db called once at startup (reads no longer self-create schema) | ✓ VERIFIED | `build_runtime` calls `init_db(db_path)` at :143 — closes the wiring gap. |
| Named tests (11) | All present in tests/test_scheduler.py, test_store.py, test_send_now.py | ✓ VERIFIED | All 11 test defs found and passing. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| discord._post 401/403 raise | daemon fire_slot classifier | `except httpx.HTTPStatusError` → `is_auth_failure` → REASON_AUTH_FAILED | ✓ WIRED | daemon.py:273-282 reads the raised exc; zero new daemon classification code. |
| fire_slot `_attempt` | send_now fetch_cache | single-slot list threaded through kwarg | ✓ WIRED | daemon.py:252,268 → cli.py:152,213-225. |
| wiring.build_runtime | store.init_db | `init_db(db_path)` at composition root | ✓ WIRED | wiring.py:143 — required now that reads open read-only. |
| store read fns | `_connect(read_only=True)` | mode=ro percent-encoded URI | ✓ WIRED | 4 sites; no executescript on read path. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| F01 duplicate-send both branches | `pytest test_scheduler.py -k post_send...` | 2 passed | ✓ PASS |
| F08 forecast ok=False + WR-03 auth | `pytest -k forecast_delivery_failure/forecast_auth_failure` | 2 passed | ✓ PASS |
| WR-02 recovery isolation | `pytest -k broad_except_recovery` | 1 passed | ✓ PASS |
| DELIV-04 auth short-circuit | `pytest -k discord_auth_short_circuit` | 1 passed | ✓ PASS |
| Store WAL/busy_timeout/no-write-lock/atomic/URI | `pytest test_store.py -k wal.../reads.../onecall.../read_only_path...` | 4 passed | ✓ PASS |
| DELIV-03 retry reuses payload | `pytest test_send_now.py -k retry_reuses_payload` | 1 passed | ✓ PASS |
| fetch-429 Retry-After not regressed | `pytest test_reliability.py` | 24 passed | ✓ PASS |
| Full suite (baseline gate) | `uv run pytest -q` | 833 passed, exit 0 | ✓ PASS |

Note: the "2 snapshots failed" line is the known pre-existing syrupy report quirk (exit 0 — trusted per project memory `pytest-snapshot-report-quirk`).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| HARD-DELIV-01 | 31-02 | Post-send bookkeeping can't release a delivered claim | ✓ SATISFIED | SC1/Truth 1 |
| HARD-DELIV-02 | 31-02 | Forecast-slot delivery failures detected + alerted | ✓ SATISFIED | SC2/Truth 2 |
| HARD-DELIV-03 | 31-03 | Delivery-only retry reuses fetched payload (no re-fetch) | ✓ SATISFIED | SC3/Truth 3 |
| HARD-DELIV-04 | 31-03 | Auth vs transient not conflated | ✓ SATISFIED | SC3/Truth 4 |
| HARD-STORE-01 | 31-01 | Atomic multi-step store writes; race-guarded reads | ✓ SATISFIED | SC4/Truth 5 |
| HARD-STORE-02 | 31-01 | WAL + busy_timeout; reads take no write lock | ✓ SATISFIED | SC4/Truth 6 |

All 6 declared requirement IDs are mapped in REQUIREMENTS.md to Phase 31 (marked Complete) and satisfied in source. No orphaned requirements.

### Cross-Repo Jurisdiction

| Check | Status | Evidence |
|-------|--------|----------|
| No `yahir_reusable_bot` hub files edited | ✓ VERIFIED | All 20 changed files across the full phase 31 commit range are under `weatherbot/`, `tests/`, `.planning/`. `is_auth_failure` used via existing import, not modified. DeliveryResult / retry predicate / classifiers untouched. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TBD/FIXME/XXX debt markers in any modified source file | — | None |

The webhook token (`self._url`) is used only to construct the webhook (discord.py:91) and is never passed into the synthesized exception, request, response, or any log — secret hygiene (ASVS V7 / T-31-07) holds.

### Human Verification Required

None for phase completion. One deferred Gate-2 (milestone-close) obligation, per the plan `user_setup` and project two-gate UAT policy:

- On host `yahir-mint`, after `sudo systemctl restart weatherbot`, confirm `PRAGMA journal_mode` on the live `data/weatherbot.db` returns `wal` and `-wal`/`-shm` sidecars appear. This touches the live systemd daemon (editable install) and is a deferred milestone-close obligation, not a phase blocker — the WAL mechanism and its persistence are proven by `test_wal_and_busy_timeout_are_set` and init_db is wired at the composition root.

### Deferred Items (informational)

`deferred-items.md` logs four PRE-EXISTING lint-only ruff findings (test_golden_cli.py:33, test_reload.py:626, daemon.py:69/71/1418) in files not touched by this phase — explicitly routed to the Phase 35 Cleanup Sweep. Not gaps for this phase.

### Gaps Summary

None. All 16 must-haves verified against actual source with passing behavioral
tests. The verification focus items were confirmed closed in the CURRENT code:

- **F01 (CR-01):** the success `_log.info("slot fired")` is genuinely INSIDE the
  log-and-swallow (daemon.py:373-379), the swallow's own warning is guarded, and
  `return result` precedes the broad `except` — no statement after `result.ok` can
  reach `release_claim`. `test_post_send_success_log_raise_keeps_claim` exercises the
  exact CR-01 raise site (BrokenPipeError on the success log) and passes.
- **WR-01:** read-only `_connect` percent-encodes the resolved absolute path.
- **WR-02:** broad-except recovery bookkeeping is guarded; `_run_catchup` wraps each fire.
- **WR-03:** forecast auth 401/403 escalates immediately, bypassing the streak.
- **HARD-STORE:** WAL once, busy_timeout per-connect, 4 reads read-only, single
  executescript in init_db, atomic persist, init_db wired at startup in wiring.py.
- **Jurisdiction:** zero hub files touched.

Full suite green (833 passed, exit 0).

---

_Verified: 2026-07-10_
_Verifier: Claude (gsd-verifier)_
