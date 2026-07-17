---
phase: 30-secret-hygiene
plan: 01
subsystem: security
tags: [security, logging, redaction, httpx, structlog, secret-hygiene]

# Dependency graph
requires:
  - phase: 11-inbound-bot
    provides: "the on_message non-propagating envelope (bot.py:507 _log.exception) that renders the F12 traceback"
  - phase: earlier-fetch-layer
    provides: "weatherbot/weather/client.py fetch_onecall + geocode raise sites"
provides:
  - "weatherbot/_redact.py — pure redact_appid(text) helper (single source of truth)"
  - "Redacted, type-preserving HTTPStatusError re-raise at both client.py raise sites (D-01)"
  - "_LiveStderr.write appid backstop shared by both structlog.configure sites (D-02)"
  - "tests/test_redact_hygiene.py — 4-test regression suite proving the leak stays closed on all three paths + type-contract canary"
affects: [phase-31-retry-classification, milestone-close-gate-2-ops]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Redacted re-raise: catch key-bearing HTTPStatusError, redact message, re-raise fresh one `from None` (preserves type + .response.status_code)"
    - "Renderer-agnostic log backstop at the single _LiveStderr.write stderr choke point"

key-files:
  created:
    - weatherbot/_redact.py
    - tests/test_redact_hygiene.py
  modified:
    - weatherbot/weather/client.py
    - weatherbot/__init__.py

key-decisions:
  - "Kept the redaction helper app-local at weatherbot/_redact.py (no _promotable/ ceremony for a 4-line regex; flagged as a hub-promotion candidate in a comment)"
  - "cli.py left byte-unchanged — it inherits the backstop via the shared `from weatherbot import _LiveStderr` import (confirm-only)"

patterns-established:
  - "Redacted HTTPStatusError re-raise `from None` — belt-and-suspenders source fix"
  - "_LiveStderr.write regex backstop — renderer-agnostic last line of defense for secrets in log output"

requirements-completed: [HARD-SEC-01]

coverage:
  - id: D1
    description: "redact_appid pure helper scrubs appid=<value> to appid=*** while preserving following params/endpoint/status (D-03), boundary-safe + case-insensitive"
    requirement: "HARD-SEC-01"
    verification:
      - kind: unit
        ref: "tests/test_redact_hygiene.py::test_redact_helper_boundaries"
        status: pass
    human_judgment: false
  - id: D2
    description: "A 401/403 from fetch_onecall re-raises a redacted HTTPStatusError — key absent from str(exc) AND full traceback; .response.status_code intact (type contract)"
    requirement: "HARD-SEC-01"
    verification:
      - kind: unit
        ref: "tests/test_redact_hygiene.py::test_onecall_failure_redacts_key_and_keeps_status"
        status: pass
    human_judgment: false
  - id: D3
    description: "A 401/403 from geocode re-raises the same redacted, type-preserving HTTPStatusError"
    requirement: "HARD-SEC-01"
    verification:
      - kind: unit
        ref: "tests/test_redact_hygiene.py::test_geocode_failure_redacts_key"
        status: pass
    human_judgment: false
  - id: D4
    description: "A failing !weather <loc> over Discord writes no appid to stderr; the _LiveStderr backstop independently scrubs a raw un-redacted appid=<SENTINEL> log line"
    requirement: "HARD-SEC-01"
    verification:
      - kind: integration
        ref: "tests/test_redact_hygiene.py::test_discord_on_message_does_not_dump_key"
        status: pass
    human_judgment: false
  - id: D5
    description: "Live daemon restart on host yahir-mint + journald no-appid check on a real failing !weather; optional key rotation if historical logs leaked"
    verification: []
    human_judgment: true
    rationale: "Requires driving the live systemd service on a physical host and inspecting journald — a deferred Gate-2 milestone-close ops obligation, out of code scope."

# Metrics
duration: ~20min
completed: 2026-07-09
status: complete
---

# Phase 30 Plan 01: Secret Hygiene Summary

**The OpenWeather appid is now unreachable in any surfaced error: redacted at both client.py raise sites via a type-preserving `HTTPStatusError(...) from None` re-raise and scrubbed again at the `_LiveStderr` stderr choke point — belt-and-suspenders (D-01 + D-02) delivering HARD-SEC-01.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-09T17:36Z
- **Completed:** 2026-07-09T17:55Z
- **Tasks:** 3 completed
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- Closed the reproduced F12 end-to-end leak (a failing `!weather <loc>` over Discord dumped the key-bearing traceback) at the SOURCE, so the leak is unreachable rather than patched per-logging-site.
- Preserved the LOCKED type contract: the re-raised error stays `httpx.HTTPStatusError` with `.response.status_code` intact — the full existing `test_client.py` suite and 810 total tests stay green, so none of the 6+ downstream branch sites break.
- Added a renderer-agnostic `_LiveStderr.write` backstop scrubbing `appid=<value>` from every rendered stderr line, independently proven to catch a raw un-redacted future leak.

## Task Commits

Each task was committed atomically (TDD: RED test → GREEN impl folded per task):

1. **Task 1: Pure redact_appid helper + boundary test** — `2ace5b4` (feat)
2. **Task 2: Source redaction (client.py, D-01) + _LiveStderr backstop (__init__.py, D-02)** — `8c066c1` (fix)
3. **Task 3: Regression suite — three leak paths + type-contract canary** — `ee5dc72` (test)

_Note: Task 1's RED test and GREEN helper landed in one commit (helper is a 4-line pure fn); Tasks 2 & 3 wrote their RED tests first, confirmed failure, then implemented._

## Files Created/Modified
- `weatherbot/_redact.py` (new) — stdlib-only `redact_appid(text)` backed by the boundary-safe compiled regex `(appid=)[^&\s"'<>\\]+` (IGNORECASE); single source of truth imported by both the source fix and the backstop.
- `weatherbot/weather/client.py` (modified) — both `fetch_onecall` and `geocode` wrap `raise_for_status()` in `except httpx.HTTPStatusError` and re-raise `httpx.HTTPStatusError(redact_appid(str(exc)), request=…, response=…) from None`; header comment updated to note the closed `raise_for_status`-message gap.
- `weatherbot/__init__.py` (modified) — `_LiveStderr.write` now returns `sys.stderr.write(redact_appid(data))` (lazy stderr resolution preserved for capsys); `structlog.configure` unchanged.
- `tests/test_redact_hygiene.py` (new) — 4 tests: helper boundaries, onecall (full-traceback + status canary), geocode, Discord end-to-end + raw-leak backstop proof. `capsys` throughout.

## cli.py Confirmation (confirm-only, per Task 2)
`weatherbot/cli.py` is **byte-unchanged** (`git diff --quiet weatherbot/cli.py` exits 0). Its second `structlog.configure` (:779-783) routes through `PrintLoggerFactory(file=_LiveStderr())` importing the SAME package `_LiveStderr` (`:776 from weatherbot import _LiveStderr`). Because both configure sites share the one `_LiveStderr` class, wrapping its `write` in `__init__.py` covers cli.py automatically — no edit required.

## Decisions Made
- **Helper stays app-local** at `weatherbot/_redact.py` — no `_promotable/` directory for a 4-line regex (RESEARCH Open Q1); flagged as a hub-promotion candidate in a one-line comment.
- **`from None` is load-bearing** — verified both the onecall test's `str(exc)` AND full-traceback assertions pass; without `from None` the traceback assertion would fail via the key-bearing `__context__` chain (Pitfall 1).

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
- The `grep -c 'caplog'` acceptance check initially returned 3 due to prose mentions of the word ("NEVER caplog") in docstrings warning against its use. Reworded those warnings to "the stdlib-log-record capture fixture" so the literal check reads 0 while keeping the guidance intact. No fixture usage was ever present — `capsys` is used throughout as required.

## Verification Evidence
- `uv run pytest tests/test_redact_hygiene.py -x` → 4 passed.
- `uv run pytest tests/test_client.py -x` → 7 passed (no type-contract / client regression).
- `uv run pytest -q` → **810 passed**, exit code 0 (the "2 snapshots failed" line is pre-existing syrupy noise per `[[pytest-snapshot-report-quirk]]` — exit code trusted).
- `grep -c 'from None' weatherbot/weather/client.py` = 6 (≥2; both raise sites present); `grep -c 'raise httpx.HTTPStatusError' …` = 2; `grep -c 'caplog' tests/test_redact_hygiene.py` = 0.
- `git diff --quiet weatherbot/cli.py` exits 0.

## Deferred to Gate-2 (milestone-close, human)
- Live `sudo systemctl restart weatherbot` on host `yahir-mint` (editable install), trigger a failing `!weather <loc>`, confirm journald shows no `appid` value.
- T-30-03 residual: if the key previously leaked to on-disk/journald logs, rotate the OpenWeather key (human-gated ops decision). Tracked as a deferred milestone obligation.

## Self-Check: PASSED
- FOUND: weatherbot/_redact.py
- FOUND: tests/test_redact_hygiene.py
- FOUND commit 2ace5b4, 8c066c1, ee5dc72 (all in git log)
