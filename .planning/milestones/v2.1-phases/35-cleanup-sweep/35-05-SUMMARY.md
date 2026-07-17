---
phase: 35-cleanup-sweep
plan: 05
subsystem: weather/uv/client
tags: [hardening, cleanup, HARD-CLEAN-02, uv-monitor, openweather-client]
requires:
  - Phase-30 redaction (_redact.py + test_redact_hygiene.py) — the control F67 is measured against
  - reliability.is_transient — the retryable/transient contract F68 maps into
provides:
  - Honest UV pre-warn countdown (round, not truncate) — F60
  - Reconciling UV tick counters (fetched+skipped+errored == len(locations)) — F61
  - Non-JSON 2xx classified as transient (httpx.ReadError, redacted) — F68
  - In-code ACCEPTED annotations for F59, F58, F73, F72, F67
affects:
  - weatherbot/scheduler/uvmonitor.py
  - weatherbot/weather/client.py
  - weatherbot/weather/uv.py
tech-stack:
  added: []
  patterns:
    - "Map an unclassified upstream degradation (non-JSON 2xx) onto the existing transient contract (httpx.ReadError) rather than inventing a new exception type"
    - "ACCEPT-with-rationale via in-code `# ACCEPTED (F##, v2.1): ...` at the finding site (D-02)"
key-files:
  created: []
  modified:
    - weatherbot/scheduler/uvmonitor.py
    - weatherbot/weather/client.py
    - weatherbot/weather/uv.py
    - tests/test_uv_monitor.py
    - tests/test_client.py
decisions:
  - "F67 ACCEPTED (not removed): the _LiveStderr redaction backstop scrubs structlog output only; httpx emits its request-URL INFO line via STDLIB logging → routed to raw sys.stderr by cli._configure_logging's basicConfig, bypassing the backstop. So the setLevel(WARNING) is NOT superseded by redaction — it stays as defense-in-depth. test_redact_hygiene.py green either way."
  - "F68 mapped to httpx.ReadError (a TransportError): is_transient(exc) True → tenacity retries → daemon's except (TimeoutException, ConnectError, ReadError) → REASON_TRANSIENT_EXHAUSTED. Matches the caller's retryable/classified contract exactly; URL redacted at the raise site."
  - "F58 ACCEPT-annotated here: the Phase-32 F21 lifecycle audit addressed the daily0-date-mismatch all-clear gap (WR-01), but F58's missing-sun-fields schema-drift skip is a distinct trigger still open — RESEARCH lists it under ACCEPT-with-annotation."
metrics:
  duration: 7min
  completed: 2026-07-13
  tasks: 3
  files: 5
status: complete
---

# Phase 35 Plan 05: uv/weather/client Cleanup Sweep Summary

Swept the weather/uv/client low-severity finding cluster (HARD-CLEAN-02): fixed the UV pre-warn countdown truncation (F60) and the lossy tick counters (F61) with a regression test; classified a captive-portal non-JSON 2xx as a redacted transient error (F68) with two regression tests; and accept-annotated the genuinely-cosmetic/latent findings F59, F58, F73, F72, and F67 with in-code `# ACCEPTED (F##, v2.1):` rationale at each site. Suite green (887 passed, exit 0); no hub-path file touched.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | F60 rounding + F61 counter reconcile + accept F59/F58 | `2414d31` | weatherbot/scheduler/uvmonitor.py, tests/test_uv_monitor.py |
| 2 | F68 non-JSON 2xx classified + resolve F67 vs redaction | `f969e18` | weatherbot/weather/client.py, tests/test_client.py |
| 3 | Accept-annotate cosmetic uv.py findings F73/F72 | `fde74eb` | weatherbot/weather/uv.py |

## What Changed

### F60 — honest pre-warn countdown (fix + regression test)
`int(delta_min)` truncated the "~N min" countdown (28.9 → "~28 min", under-reporting the lead by up to ~59s). Replaced with `round(delta_min)`. TDD RED test `test_prewarn_countdown_rounds_not_truncates` drives crossing 10:20:00 with now 09:51:06 (delta exactly 28.9) and asserts "~29 min" (RED against `int()`, GREEN on `round()`). `time_close` already bounds `delta_min` to `[0, lead]`.

### F61 — reconciling tick counters (log-only, behavior-preserving)
A location raising inside the fetch loop was counted as neither `fetched` nor `skipped` (silently lost from the tick log). Added an `errored` counter incremented in the per-location `except` arm and included it in the `uv_monitor_tick` log line, so `fetched + skipped + errored == len(snapshot.locations)`. The per-location isolation is unchanged (each raise is still swallowed + logged). Verified: `_evaluate_location` returns `True` in every non-raising path, so each location increments exactly one counter.

### F68 — non-JSON 2xx classified as transient (fix + 2 regression tests)
A captive-portal / proxy HTTP 200 with an HTML body made `response.json()` raise a bare `json.JSONDecodeError` — an unclassified type the send-path transient/auth handlers never catch, degrading to an "unexpected" outcome. Added `_parse_json_or_transient(response)` that catches `JSONDecodeError` and re-raises `httpx.ReadError` (a `TransportError`) with a `redact_appid`-scrubbed message and `from None`. Both `fetch_onecall` and `geocode` route their JSON parse through it. `reliability.is_transient(ReadError)` is `True` → tenacity retries → the daemon's `except (TimeoutException, ConnectError, ReadError)` maps it to `REASON_TRANSIENT_EXHAUSTED`. Two regression tests (`fetch_onecall` + `geocode`) assert the raised error is a `TransportError` (not `JSONDecodeError`), satisfies `is_transient`, and carries no appid.

### Accepted-with-rationale (annotation only, no behavior change)
- **F59** (`uvmonitor.py` `_is_daylight` return): inclusive `[sunrise,sunset]` is intentional; an exact-instant sunset trigger with UV≈0 is unreachable.
- **F58** (`uvmonitor.py` missing-sun-fields skip): a missed courtesy all-clear (schema-drift only), not a missed warning.
- **F73** (`uv.py` peak_uvi derivation): WR-02 peak-clock coherence chosen over peak/max agreement; both rounded.
- **F72** (`uv.py` fixed 06:00-20:00 fallback): fires only on missing sun fields; mid-latitude deployment.
- **F67** (`client.py` httpx setLevel): intentional URL-log suppression retained; redaction is the primary control but does NOT cover the httpx stdlib-logging path (see F67 decision above).

## F67 Resolution Detail (remove-or-accept → ACCEPT)

The plan required verifying whether Phase-30 redaction supersedes the `getLogger("httpx").setLevel(WARNING)` before removing it. Investigation:
- The `_LiveStderr.write` backstop (`__init__.py`, D-02) unconditionally scrubs `appid=` from every line — but only for structlog output (`PrintLoggerFactory(file=_LiveStderr())`).
- httpx has `logger = logging.getLogger("httpx")` and `logger.info(<request URL>)` — this is **stdlib logging**, not structlog.
- `cli._configure_logging` calls `logging.basicConfig(level=level)`, installing a root StreamHandler on **raw `sys.stderr`** (not `_LiveStderr`). httpx's INFO URL line propagates to that handler, bypassing the redaction backstop.

Therefore redaction does NOT cover the httpx stdlib-INFO URL-log path → per rule A4, ACCEPT-annotate and keep the setLevel. `test_redact_hygiene.py` stays green (10 tests) either way.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Recursion in the F68 helper (self-inflicted during implementation)**
- **Found during:** Task 2
- **Issue:** A `replace_all` on `return response.json()` also rewrote the line inside the new `_parse_json_or_transient` helper, making it call itself → `RecursionError` on every client test.
- **Fix:** Restored the helper body to `return response.json()`; only the two call sites in `fetch_onecall`/`geocode` route through the helper.
- **Files modified:** weatherbot/weather/client.py
- **Commit:** `f969e18` (fixed before the commit; RED→GREEN sequence preserved)

No plan-level deviations otherwise — F59/F72/F73/F58 were ACCEPT-only (no runtime change), F62's models.py annotation stays owned by Plan 06, and no hub-path file was touched.

## Verification

- `uv run pytest tests/test_uv_monitor.py tests/test_client.py tests/test_redact_hygiene.py tests/test_uv.py -q` → 92 passed.
- `uv run pytest -q` → 887 passed, exit 0 (the "2 snapshots failed" line is the known pre-existing syrupy quirk; trust the exit code).
- All accepted findings carry `# ACCEPTED (F##, v2.1):` at their sites: F59, F58 (uvmonitor.py); F73, F72 (uv.py); F67 (client.py).
- No hub-path (`yahir_reusable_bot/` / `../Reusable/`) file in the diff.

## Known Stubs

None.

## Threat Flags

None — the F68 change hardens an existing trust boundary (OpenWeather→client) already in the plan's threat model; no new surface introduced.

## Self-Check: PASSED

- SUMMARY.md present at `.planning/phases/35-cleanup-sweep/35-05-SUMMARY.md`.
- All three task commits present: `2414d31`, `f969e18`, `fde74eb`.
- Annotations verified in source: F59/F58 (uvmonitor.py), F73/F72 (uv.py), F67 (client.py).
