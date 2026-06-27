---
phase: 21-characterization-golden-test-harness
plan: 04
subsystem: test-harness
status: complete
tags: [characterization, exception-identity, D-13, SC3, BHV-02]
requires:
  - "21-01 (golden harness scaffold + conftest)"
provides:
  - "D-13 exception-identity pins for every move-path error type (is-identity + frozen tuple)"
  - "Phase-26 re-home tripwire on UnknownLocationError"
affects:
  - "Phase 22-27 seam moves (exception catch contracts now fail loud on re-home/rename)"
tech-stack:
  added: []
  patterns:
    - "Two-assert exception pin (is-identity through caller import path + frozen (__module__, __qualname__))"
    - "isinstance avoided as identity pin (permits except-broadening — D-13)"
key-files:
  created:
    - "tests/test_exception_identity.py"
  modified: []
decisions:
  - "Included the optional D-13 behavioral backstop (real httpx.HTTPStatusError(429) → is_transient) — low-cost, pins the catch contract end-to-end alongside the identity pins."
  - "Reworded docstring to avoid the literal token 'isinstance' so the acceptance grep (count == 0) holds while preserving the D-13 rationale."
metrics:
  duration: "~10min"
  completed: 2026-06-27
  tasks: 1
  files: 1
---

# Phase 21 Plan 04: Move-Path Exception-Identity Pins Summary

Pinned the exception identity of every move-path error type with the D-13 two-assert
pattern (`is`-identity through the caller's import path + a frozen
`(__module__, __qualname__)` tuple) in a purely additive `tests/test_exception_identity.py`,
so a later re-home/rename fails loud rather than silently broadening an `except`.

## What Was Built

`tests/test_exception_identity.py` — 10 tests, pure type introspection (no I/O, no
snapshot file):

- **9 identity pins**, two asserts each:
  - `httpx.HTTPStatusError` / `TimeoutException` / `ConnectError` / `ReadError` → `("httpx", …)`
  - `discord.LoginFailure` / `discord.Forbidden` → `("discord.errors", …)`
  - `tenacity.RetryError` → `("tenacity", "RetryError")`
  - `pydantic.ValidationError` → `("pydantic_core._pydantic_core", "ValidationError")` (the corrected v2-re-export home, NOT `"pydantic"`)
  - `UnknownLocationError` → `("weatherbot.interactive.lookup", "UnknownLocationError")` (load-bearing — re-homes in Phase 26)
- **1 behavioral backstop**: a real `httpx.HTTPStatusError(429)` driven through
  `reliability.retry.is_transient`, asserting transient classification.

Each frozen tuple was confirmed empirically with a one-line `python -c` against the
installed dependency versions before writing — all 9 matched the PATTERNS VERIFIED table
exactly, including the `pydantic_core._pydantic_core` correction (discharges the residual
`[ASSUMED]` rows from RESEARCH).

## Verification Evidence

| Acceptance criterion | Result |
|----------------------|--------|
| `uv run pytest tests/test_exception_identity.py -q` | 10 passed |
| `grep -c '__qualname__'` ≥ 8 | 11 |
| `grep -c 'isinstance'` == 0 | 0 |
| `grep -q 'pydantic_core._pydantic_core'` | present |
| `grep -q 'weatherbot.interactive.lookup'` | present |
| `git diff --name-only weatherbot/` empty (no source change) | empty |
| `uv run ruff check` + `format --check` | clean |
| Full suite `uv run pytest -q` | 693 passed, 25 snapshots passed |

## Deviations from Plan

None — plan executed as written. The optional D-13 backstop was included (Claude's
discretion, as the plan permitted) because constructing the 429 was low-cost and verified
working before commit.

One in-flight self-correction (not a plan deviation): the acceptance criterion requires
`grep -c 'isinstance' == 0`, but an explanatory docstring sentence used the literal token.
Reworded to "subclass/instance check" so the grep holds while the D-13 rationale stays
intact. Caught and fixed before the only commit.

## Known Stubs

None.

## Threat Flags

None — pure type-object introspection; no data sink, no secret, no I/O (matches the plan's
accepted T-21-04 disposition).

## Self-Check: PASSED

- FOUND: tests/test_exception_identity.py
- FOUND: commit a8a1e35
