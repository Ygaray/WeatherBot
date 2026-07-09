# Phase 30: Secret Hygiene - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 30-secret-hygiene
**Areas discussed:** Redaction depth, Error display

---

## Redaction depth

| Option | Description | Selected |
|--------|-------------|----------|
| Source scrub + log backstop | Fix at root in client.py so the exception is clean everywhere, PLUS a global logging filter scrubbing `appid=…` as a future-proof safety net. | ✓ |
| Source scrub only | Fix client.py only; simplest, satisfies criteria, relies on no future code stringifying the raw URL. | |
| Per-call-site scrub | Leave exception dirty, patch each logging site (mainly Discord `_log.exception`). Most fragile. | |

**User's choice:** Source scrub + log backstop
**Notes:** Belt-and-suspenders chosen for a security requirement; aligns with the
v1.2 milestone's correctness-first / no-backlog posture (fold the defense-in-depth
in now rather than defer). Source fix at `client.py` is primary; backstop is the net.

---

## Error display

| Option | Description | Selected |
|--------|-------------|----------|
| Placeholder `appid=***` | Keep failing URL + HTTP status visible; mask only the key value. Preserves live-daemon diagnosability. | ✓ |
| Strip whole query string | Show only endpoint path + status, no params. Maximally paranoid, less diagnosable. | |

**User's choice:** Placeholder `appid=***`
**Notes:** Diagnosability on the live daemon matters — you still want to see which
endpoint/status failed.

---

## Claude's Discretion

- Backstop insertion mechanism (`_LiveStderr.write` choke point vs. a structlog
  processor) — leaning toward the `_LiveStderr.write` choke point as renderer-agnostic.
- Redaction helper shape/location and the exact regression-test construction.
- Locked constraint (not a discretion item): the re-raised error stays
  `httpx.HTTPStatusError` with `.response` intact — 6+ call sites depend on it.

## Deferred Ideas

- Promote the log-redaction backstop to the `yahir_reusable_bot` hub in a future
  ecosystem cycle (human-gated tag cut; out of scope for this "cheap, high-value" phase).
- Scrubbing non-secret params (lat/lon/location names) — not secrets, out of scope.
