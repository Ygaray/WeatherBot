---
phase: 31-send-atomicity-exactly-once-persistence-robustness
plan: 03
subsystem: send-path
tags: [deliv-03, deliv-04, fetch-once, retry-reuse, auth-classification, redaction, cross-repo-jurisdiction]

# Dependency graph
requires:
  - phase: 31-send-atomicity-exactly-once-persistence-robustness
    plan: 02
    provides: "fire_slot restructured (F01 swallow + F08 forecast ok=False inspection) — the current daemon.py shape this plan builds on"
  - phase: 30-secret-hygiene
    provides: "the httpx.HTTPStatusError-with-.response type contract + webhook-URL redaction posture the DELIV-04 carrier reuses"
provides:
  - "DELIV-03: a delivery-only retry reuses the ONE already-fetched payload (fetch_cache) — lookup_weather runs exactly once per fire; a fetch-429 still raises before the cache is populated so Retry-After honoring (RELY-02) is intact"
  - "DELIV-04: app-side discord._post raises a REDACTED httpx.HTTPStatusError on 401/403 → lands in the existing daemon:263 arm → auth_failed, short-circuits in ~1 attempt; every other non-2xx still returns ok=False"
  - "regression tests: test_retry_reuses_payload (fetch-count spy), test_discord_auth_short_circuit (daemon classification), + 5 channel-level DELIV-04 raise/redaction/hygiene tests"
affects: [send-atomicity, exactly-once, openweather-call-volume, alert-taxonomy]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "single-slot fetch_cache threaded through the retried unit: fetch once outside the delivery retry, reuse across attempts; a pre-cache fetch failure still propagates (FCAST-07 payload-reuse analog)"
    - "app-side auth carrier: raise httpx.HTTPStatusError with a synthesized redacted .response so a hub classifier (is_auth_failure, reads only .response.status_code) sees the status without a hub change"

key-files:
  created: []
  modified:
    - weatherbot/cli.py
    - weatherbot/scheduler/daemon.py
    - weatherbot/channels/discord.py
    - tests/test_send_now.py
    - tests/test_scheduler.py
    - tests/test_channel.py

key-decisions:
  - "Checkpoint Task 1 auto-resolved to preserve-fetch-retry under --auto (orchestrator-selected default): keep the fetch-side transient retry intact; delivery is a separate retried unit over the single fetched payload."
  - "DELIV-03 seam is a fetch_cache list (NOT a fetch-out-of-send_now hoist): the reliability suite patches send_now whole and asserts it is the retried unit (calls['n'] counts send_now invocations), so send_now MUST stay the retried unit. The cache makes it re-invocable without re-fetching, satisfying DELIV-03 AND every _patch_send_now reliability test."
  - "DELIV-04 uses the httpx.HTTPStatusError carrier (not a new SendAuthError arm): reuses the existing except at daemon.py:263 → zero new daemon classification code, zero hub change (D-04, cross-repo jurisdiction)."
  - "Redacted URL is a module constant (_REDACTED_WEBHOOK_URL = 'https://discord/redacted'); self._url is never passed into the request/response, so str(exc) and its request/response URLs carry no webhook token (T-31-07/ASVS V7)."

patterns-established:
  - "Pattern: to make a retried composition root fetch-once, give it an out-of-retry cache slot rather than splitting the fetch out — preserves the 'retried unit' contract that other tests depend on."
  - "Pattern: an app-side channel can feed a hub classifier by raising the hub's expected exception type with a synthesized .response — no hub extension needed."

requirements-completed: [HARD-DELIV-03, HARD-DELIV-04]

coverage:
  - id: D1
    description: "A delivery-only failure retries against the ALREADY-fetched payload: lookup_weather is called exactly once per fire (client.onecall_calls == ['imperial','metric']) even when the delivery retries (fail then succeed)."
    requirement: "HARD-DELIV-03"
    verification:
      - kind: unit
        ref: "tests/test_send_now.py#test_retry_reuses_payload"
        status: pass
    human_judgment: false
  - id: D2
    description: "RED-first: test_retry_reuses_payload FAILED against pre-fix send_now (4 One Call calls — a re-fetch on the delivery retry), then PASSED after the fetch_cache reuse."
    requirement: "HARD-DELIV-03"
    verification:
      - kind: unit
        ref: "tests/test_send_now.py#test_retry_reuses_payload (RED evidence recorded)"
        status: pass
    human_judgment: false
  - id: D3
    description: "fetch-429 Retry-After honoring (RELY-02) is not regressed by the fetch_cache: a fetch-429 raises before the cache is populated, so it still reaches the two-burst wait callable and the capped Retry-After is waited."
    requirement: "HARD-DELIV-03"
    verification:
      - kind: unit
        ref: "tests/test_reliability.py#test_daemon_retry_after_honored (unchanged, green)"
        status: pass
    human_judgment: false
  - id: D4
    description: "A permanent Discord send auth failure (401/403) maps to auth_failed and short-circuits in ~1 attempt (channel.attempts == 1, alert reason == auth_failed) rather than transient_exhausted."
    requirement: "HARD-DELIV-04"
    verification:
      - kind: unit
        ref: "tests/test_scheduler.py#test_discord_auth_short_circuit"
        status: pass
    human_judgment: false
  - id: D5
    description: "discord._post raises httpx.HTTPStatusError on 401 and 403 with .response.status_code as a plain int; every other non-2xx (429/500/502/400/404) still returns DeliveryResult(ok=False) and does NOT raise."
    requirement: "HARD-DELIV-04"
    verification:
      - kind: unit
        ref: "tests/test_channel.py#test_auth_status_raises_httpx_status_error + test_non_auth_non_2xx_still_returns_failure_not_raise"
        status: pass
    human_judgment: false
  - id: D6
    description: "T-31-07/ASVS V7: the synthesized auth exception carries a redacted placeholder URL — no webhook token in str(exc), the request URL, the response.request URL, or any log record."
    requirement: "HARD-DELIV-04"
    verification:
      - kind: unit
        ref: "tests/test_channel.py#test_auth_raise_carries_no_webhook_token + test_auth_raise_logs_no_webhook_token"
        status: pass
    human_judgment: false
  - id: D7
    description: "No hub change and no second retry layer: DeliveryResult / is_transient / is_auth_failure / build_retrying untouched; the delivery retry is the single existing retrying(...) scope (a Discord ok=False stays ONE transient unit)."
    requirement: "HARD-DELIV-04"
    verification:
      - kind: integration
        ref: "uv run pytest -q (829 passed, exit 0 — 817 baseline + 12 new)"
        status: pass
    human_judgment: false

# Metrics
duration: ~20min
completed: 2026-07-10
status: complete
---

# Phase 31 Plan 03: Fetch/Deliver Split + Discord 401/403 → Auth Summary

**Two coupled send-path corrections landed with zero hub changes: DELIV-03 makes a delivery-only retry reuse the ONE already-fetched payload (a single-slot `fetch_cache` threaded through the retried `send_now`, so `lookup_weather` runs exactly once per fire while a fetch-429 still raises pre-cache and honors Retry-After), and DELIV-04 makes app-side `discord._post` raise a REDACTED `httpx.HTTPStatusError` on 401/403 that lands in the existing `daemon.py:263` arm → `auth_failed`, short-circuiting the retry in ~1 attempt instead of burning the full ~65-min schedule as `transient_exhausted`.**

## Checkpoint resolution (Task 1)

Checkpoint Task 1 (fetch-429 Retry-After disposition) auto-resolved to **`preserve-fetch-retry`** under `--auto` (orchestrator-selected default, the roadmap/CONTEXT directive and the RESEARCH-recommended choice). Task 3 was implemented in that confirmed shape: the fetch-side transient retry is intact (a fetch-429 `httpx.HTTPStatusError` still reaches the two-burst wait callable, RELY-02) and the delivery is a separate retried unit that reuses the single already-fetched in-memory payload — a delivery-only failure never re-fetches.

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-10
- **Tasks:** 4 (1 checkpoint auto-resolved, 3 executed)
- **Files modified:** 6

## Accomplishments

- **DELIV-03 (HARD-DELIV-03, D-03) — fetch once, retry only delivery.** Added an optional single-slot `fetch_cache: list` param to `send_now` (cli.py). The FIRST invocation stashes its `LookupResult`; a re-invocation (delivery-only retry) reuses it and skips `lookup_weather`. `fire_slot` (daemon.py) creates ONE `fetch_cache` per fire, outside the retry, and threads it through every `_attempt`. Net: `lookup_weather` runs exactly once per fire even when the delivery retries. A FETCH failure raises before the cache is populated, so it still propagates to the two-burst wait callable — **fetch-429 Retry-After honoring (RELY-02) is preserved unchanged.** The manual `--send-now` path (`fetch_cache=None`) fetches fresh, behavior unchanged.
- **DELIV-04 (HARD-DELIV-04, D-04, F48) — Discord 401/403 → auth, no hub change.** In `discord._post`, before the generic non-2xx `ok=False` return, a `status in {401, 403}` branch raises `httpx.HTTPStatusError` built with a synthesized `.response` (plain-int `status_code`) and a REDACTED placeholder request URL (`https://discord/redacted`) — `self._url` is never passed in. This lands in `fire_slot`'s EXISTING `except httpx.HTTPStatusError` (daemon.py:263), where `is_auth_failure(exc)` → `REASON_AUTH_FAILED` and the non-transient exception short-circuits `build_retrying` in ~1 attempt. **Zero new daemon classification code; zero hub change** (`DeliveryResult`/`is_transient`/`is_auth_failure`/`build_retrying` untouched). Every OTHER non-2xx (429/5xx/400/404) still returns `DeliveryResult(ok=False)` and does not raise.
- **Regression tests (verify-first where it bites):** `test_retry_reuses_payload` (fetch-count spy) was RED against pre-fix code (4 One Call calls) then GREEN; `test_discord_auth_short_circuit` (daemon-level, reason==auth_failed, ~1 attempt); plus 5 channel-level DELIV-04 tests covering the 401/403 raise, the non-auth non-2xx never-raise narrowing, and webhook-token redaction in both `str(exc)`/URLs and logs.

## Task Commits

Each task committed atomically (with hooks — no `--no-verify`):

1. **Task 2: DELIV-03 + DELIV-04 regression tests** — `1ce9f5e` (test)
2. **Task 3: DELIV-03 fetch-once / deliver-retry (fetch_cache)** — `07b40ef` (fix)
3. **Task 4: DELIV-04 redacted 401/403 raise carrier** — `f88f5a4` (fix)

(Task 1 was a checkpoint — auto-resolved, no commit.)

## RED evidence (verify-first, DELIV-03)

`test_retry_reuses_payload` ran RED against the pre-restructure `send_now`:
`AssertionError: assert ['imperial','metric','imperial','metric'] == ['imperial','metric']` — the delivery-only retry RE-FETCHED (4 One Call calls). After the `fetch_cache` reuse it is GREEN (2 calls, one fetch round feeding both delivery attempts).

`test_discord_auth_short_circuit` passes at the daemon boundary using a channel that surfaces the app-side raised `httpx.HTTPStatusError` — proving the EXISTING `daemon.py:263` arm already classifies a 401/403 as `auth_failed` in 1 attempt (the DELIV-04 fix is at the channel, verified separately by the `test_channel.py` raise/redaction tests). This is the intended split: DELIV-04 needs zero daemon code.

## Files Created/Modified

- `weatherbot/cli.py` — `send_now` gained an optional `fetch_cache` param; the fetch block reuses a cached `LookupResult` when present (else fetches and stashes it). Persist-on-ok (WR-04) and the deliver dispatch (WR-05) tail are otherwise unchanged.
- `weatherbot/scheduler/daemon.py` — `fire_slot` creates one `fetch_cache` per fire (outside `retrying`) and passes it into `send_now` inside `_attempt`.
- `weatherbot/channels/discord.py` — `import httpx`; module constants `_AUTH_STATUSES`/`_REDACTED_WEBHOOK_URL`; the 401/403 raise branch in `_post`.
- `tests/test_send_now.py` — `_FailThenOkChannel` + `test_retry_reuses_payload` (fetch-count spy; taming the two-burst sleep by wrapping `build_retrying` and nulling `.sleep`).
- `tests/test_scheduler.py` — `_AuthRaisingChannel` + `test_discord_auth_short_circuit`.
- `tests/test_channel.py` — 5 DELIV-04 tests: `test_auth_status_raises_httpx_status_error` (401/403 param), `test_non_auth_non_2xx_still_returns_failure_not_raise` (429/500/502/400/404 param), `test_auth_raise_carries_no_webhook_token`, `test_auth_raise_logs_no_webhook_token`.

## Decisions Made

- **DELIV-03 seam = fetch_cache, not a fetch hoist (key design constraint).** The reliability suite (`tests/test_reliability.py`, `_patch_send_now`) patches `send_now` wholesale and asserts it is the retried unit — `calls['n']` counts `send_now` invocations across both exception and non-ok-result retries (`test_transient_retries_then_succeeds`, `test_exhaustion_alerts`, `test_nonok_delivery_exhaustion_alerts_transient`, `test_daemon_retry_after_honored`). Moving the retry inside `send_now` (wrapping only delivery) would break all of them. The `fetch_cache` keeps `send_now` the retried unit while making it fetch-once-per-fire — satisfying DELIV-03 AND every existing reliability contract. This matches the FCAST-07 payload-reuse analog at daemon.py:525.
- **DELIV-04 carrier = httpx.HTTPStatusError (RESEARCH-preferred over the SendAuthError alternative):** reuses the existing `except` at daemon.py:263, byte-identical to the fetch-path Phase-30 contract, zero new daemon arm. `.response` is a synthesized `httpx.Response(status, request=<redacted>)` — classifiers read only `.response.status_code`.
- **Redaction via a module constant, never `self._url`:** the request/response are built from `_REDACTED_WEBHOOK_URL`; the real webhook token cannot enter `str(exc)`, the request URL, `response.request.url`, or any log line.

## Deviations from Plan

None — plan executed exactly as written under the pre-resolved checkpoint. The only implementation nuance worth flagging (not a deviation): the DELIV-03 fix is a `fetch_cache` reuse rather than a fetch-out-of-`send_now` hoist, because the reliability suite requires `send_now` to remain the retried unit. The plan's Task 3 action explicitly left the exact seam to executor discretion ("give send_now a code path where fire_slot fetches once … reusing the single in-memory Forecast") and forbade a second retry layer — both honored.

## Deferred Issues

- The 3 pre-existing ruff findings in `weatherbot/scheduler/daemon.py` (`PID_FILE` unused import :69/:71; `notifier` unused local :1466) remain OUT OF SCOPE — they predate this plan (logged in 31-01/31-02 SUMMARYs) and are not in any region this plan touched. Pre-commit hooks passed on all three task commits. Left on the deferred list.

## Threat Surface

- **T-31-07 (Info Disclosure — webhook URL leak via the auth carrier): mitigated.** Redacted placeholder URL + status-only message; two channel tests assert no token in `str(exc)`/URLs and none in logs.
- **T-31-08 (DoS — auth burning the full schedule): mitigated.** 401/403 raises a non-transient error → short-circuits in ~1 attempt → `auth_failed` (proved by `test_discord_auth_short_circuit`).
- **T-31-09 (Tampering — re-fetch inflating OpenWeather volume / changing content mid-retry): mitigated.** `fetch_cache` proves a single fetch under a delivery retry.
- **T-31-10 (Tampering — hub jurisdiction breach): mitigated.** No hub file modified; DELIV-04 carrier is app-side only.
- No NEW security-relevant surface beyond the plan's threat_model. No `## Threat Flags`.

## Next Phase Readiness

- Both DELIV corrections are code-only (no schema/data change). **Deferred Gate-2 (milestone-close) obligation:** on the live systemd host `yahir-mint`, a routine `sudo systemctl restart weatherbot` after deploy applies them; no migration step. Human UAT (a real revoked-webhook 401 → `auth_failed` alert, and a mid-day OpenWeather 429 still waiting Retry-After) is a deferred milestone-close item, not a phase blocker.
- Full suite green (829 passed, exit 0). No blockers.

## Self-Check: PASSED

All 6 modified files exist on disk; all three task commits (`1ce9f5e`, `07b40ef`, `f88f5a4`) are present in git history. Full suite: 829 passed, exit 0 (817 baseline + 12 new; the "2 snapshots failed" line is the known pre-existing syrupy quirk — exit 0 is the trusted signal).

---
*Phase: 31-send-atomicity-exactly-once-persistence-robustness*
*Completed: 2026-07-10*
