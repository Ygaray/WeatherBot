---
phase: 30-secret-hygiene
verified: 2026-07-09T00:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 30: Secret Hygiene Verification Report

**Phase Goal:** The OpenWeather API key never escapes into logs. `raise_for_status()` output (which embeds `appid=<key>` in the failing URL) is sanitized at every call site, and the Discord inbound error path stops dumping the key-bearing traceback to stderr.
**Verified:** 2026-07-09
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | HARD-SEC-01 / D-01: on a 401/403 from `fetch_onecall`, `str(exc)` and the full traceback contain no appid value; redacted re-raise `from None` | ✓ VERIFIED | `client.py:77-84` wraps `raise_for_status()` in `except httpx.HTTPStatusError`, re-raises `redact_appid(str(exc))` `from None`. Behavioral test `test_onecall_failure_redacts_key_and_keeps_status` PASSED — asserts SENTINEL absent from `str(exc)` AND from `traceback.format_exception(...)` (the guard that fails if `from None` were dropped). |
| 2 | HARD-SEC-01 / D-01: on a 401/403 from `geocode`, same redacted re-raise | ✓ VERIFIED | `client.py:104-111` identical wrapper. Test `test_geocode_failure_redacts_key` PASSED — SENTINEL absent from `str(exc)`, `.response.status_code == 401`. |
| 3 | HARD-SEC-01 / D-02: a failing `!weather` over Discord (bot.py:507 `_log.exception`) writes no appid to stderr; `_LiveStderr.write` backstop scrubs even a raw un-redacted line | ✓ VERIFIED | `__init__.py:43` — `_LiveStderr.write` returns `sys.stderr.write(redact_appid(data))`, lazy stderr preserved. End-to-end test `test_discord_on_message_does_not_dump_key` PASSED — drives `on_message`, asserts SENTINEL absent from `capsys.err`, AND independently proves the backstop scrubs a raw `appid=<SENTINEL>` log line to `appid=***`. |
| 4 | HARD-SEC-01 / D-03: redacted text keeps endpoint URL + HTTP status visible (`appid=***`), daemon stays diagnosable | ✓ VERIFIED | `_redact.py:23` regex `(appid=)[^&\s\"'<>\\]+` → `\1***` — boundary-safe, non-greedy. `test_redact_helper_boundaries` PASSED — 5 cases confirm `units=imperial`, `&next=1`, trailing `'`, URL-encoded `%XX`, and case-insensitive `APPID=` all preserved/handled. |
| 5 | HARD constraint (LOCKED): re-raised exception stays `httpx.HTTPStatusError` with `.response.status_code` intact — 6+ downstream sites branch on it unchanged | ✓ VERIFIED | Type-contract canary in onecall test: `type(exc).__name__ == "HTTPStatusError"`, `.response.status_code == 401` PASSED. Downstream dependents confirmed still branching: `cli.py:291/367/421/692`, `selfcheck.py:127`, `daemon.py:263` all read `exc.response.status_code`. Full suite **810 passed** (exit 0); `test_client.py` 7 passed — no regression. |

**Score:** 5/5 truths verified (0 present, behavior-unverified)

Truths 1, 3, and 5 are behavior-dependent (cleanup/ordering invariant — `from None` traceback scrub; stderr choke-point scrub; type preservation). Each is upgraded to VERIFIED by a passing named behavioral test, not presence alone.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `weatherbot/_redact.py` | pure `redact_appid` + `_APPID_RX`, stdlib-only | ✓ VERIFIED | Imports only `re`; exposes `redact_appid` + `_APPID_RX`; boundary-safe non-greedy regex (greedy-check = 0). Imported by both client.py and __init__.py. |
| `weatherbot/weather/client.py` | redacted re-raise at both raise sites | ✓ VERIFIED | `raise httpx.HTTPStatusError` count = 2; `from None` at lines 84 & 111. Header comment updated to note the closed `raise_for_status` gap. |
| `weatherbot/__init__.py` | `_LiveStderr.write` backstop | ✓ VERIFIED | `write` passes through `redact_appid`; `structlog.configure` unchanged; lazy stderr resolution preserved. |
| `tests/test_redact_hygiene.py` | 4-test regression suite, capsys | ✓ VERIFIED | 4 tests present & passing; `caplog` count = 0 (capsys only, Pitfall 2). |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `client.py` | `_redact.py` | `from weatherbot._redact import redact_appid` (line 31) | ✓ WIRED | Used at :81, :108. |
| `__init__.py` | `_redact.py` | `from weatherbot._redact import redact_appid` (line 23) | ✓ WIRED | Used at :43 in `_LiveStderr.write`. |
| client.py re-raise | bot.py:507 traceback | `from None` suppresses key-bearing `__context__` | ✓ WIRED | Proven by onecall test's full-traceback assertion. |
| `cli.py` | `_LiveStderr` | `from weatherbot import _LiveStderr` (:776) → shared class | ✓ WIRED | cli.py byte-unchanged (`git diff --quiet` exit 0); inherits backstop via shared class. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Regression suite | `uv run pytest tests/test_redact_hygiene.py -v` | 4 passed | ✓ PASS |
| Type-contract (no client regression) | `uv run pytest tests/test_client.py -q` | 7 passed | ✓ PASS |
| Full suite (810-test claim) | `uv run pytest -q` | 810 passed, exit 0 | ✓ PASS |
| Source assertions | grep from-None=6(2 raises+4 docs), raise-count=2, greedy=0, caplog=0 | all match | ✓ PASS |
| cli.py confirm-only | `git diff --quiet weatherbot/cli.py` | exit 0 | ✓ PASS |

Note: full suite prints "2 snapshots failed" but exits 0 — pre-existing syrupy noise per `[[pytest-snapshot-report-quirk]]`, exit code trusted.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| HARD-SEC-01 | 30-01-PLAN | appid never in exception/traceback/log line; sanitized `raise_for_status`; Discord path not dumping key | ✓ SATISFIED | All 3 ROADMAP success criteria proven by passing behavioral tests; REQUIREMENTS.md traceability table already marks it Complete/Phase 30. No orphaned requirements. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| (none) | — | No TBD/FIXME/XXX/TODO/HACK/stub markers in any of the 4 modified files | — | The one "placeholder" grep hit (`test_redact_hygiene.py:191`) is a legitimate assertion `appid=***` in err2 — the redaction placeholder, not a stub. |

### Human Verification Required

None for phase completion. One deferred Gate-2 (milestone-close) ops obligation, out of code scope, already tracked in the SUMMARY and plan:
- Live `sudo systemctl restart weatherbot` on host `yahir-mint`, trigger a failing `!weather <loc>`, confirm journald shows no `appid` value; optional OpenWeather key rotation if historical logs leaked (T-30-03 residual). This is a deferred milestone obligation, not a phase blocker.

### Gaps Summary

None. All 3 ROADMAP success criteria are proven against the shipped code with passing behavioral tests (not inferred from plan text): (1) onecall + geocode 401 paths redact the key from `str(exc)` and the full traceback; (2) the Discord `on_message` end-to-end path logs an outcome with no key, and the `_LiveStderr` backstop independently scrubs raw leaks; (3) the regression suite is non-tautological (full-traceback + capsys assertions) with a `.response.status_code` type-contract canary. The LOCKED type contract holds — the re-raised error stays `httpx.HTTPStatusError` with `.response.status_code` intact, and all 6+ downstream branch sites plus the 810-test suite stay green.

---

_Verified: 2026-07-09_
_Verifier: Claude (gsd-verifier)_
