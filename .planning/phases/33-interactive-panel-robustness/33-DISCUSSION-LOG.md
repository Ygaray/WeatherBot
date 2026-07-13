# Phase 33: Interactive & Panel Robustness — Discussion Log

**Date:** 2026-07-12
**Mode:** advisor (interactive)

> Human-reference audit trail only — not consumed by downstream agents.
> Canonical decisions live in `33-CONTEXT.md`.

## Area selection

Presented three forking decisions (the rest of the phase is pure bugs with one
correct answer, fixed + regression-tested without a choice). User selected
**all three** to weigh in on.

## Area 1 — F02 default-location fix location

- **Options:** App-side only (recommended) · Add `takes_location` signal to the hub.
- **Selected:** App-side only.
- **Notes:** Hub guard skips the fetch, but default resolution
  (`resolve_location(None)`) is weather-domain and app-side — a hub signal would
  still need an injected resolver + a human-gated repin. App-side ships now and
  keeps the hub domain-free. Verify the Discord crash first. → D-01, D-02.

## Area 2 — Panel stale-repopulate race (F13)

- **Options:** Generation/epoch guard (recommended) · Lock-around-fetch.
- **Selected:** Generation/epoch guard.
- **Notes:** Keeps the off-loop-fetch design; lock-around-fetch would serialize
  lookups and risk blocking the gateway. Framed to user that the other cache
  items (F17 reorder, F22 reconcile, F23/F24 ack/empty, cache bounding) are
  fixed regardless — not forks. → D-03, D-04.

## Area 3 — Render formatting (user-visible)

Three sub-choices, presented with rendered previews:

| Sub-choice | Options | Selected |
|---|---|---|
| Default-location marker | 📍 + "(default)" suffix (rec) · 📍 only · footer note | **📍 + "(default)" suffix** (also restores 📍 on inbound / F27) |
| Out-of-today date labels | `Thu 7/17` (rec) · `Thu Jul 17` · `Thursday` | **`Thu Jul 17`** (weekday + month name) |
| ISO timestamps | `9:00 AM` local 12h (rec) · `09:00` local 24h · `Jul 12, 9:00 AM` | **`09:00`** local 24h |

→ D-05, D-06, D-07. Pure-bug render fixes (dup header F28, empty-token blanks,
dt-pairing F11/F107) captured as D-08 — no choice.

## Deferred / redirected

- F25/F26/F29/F78/F162 → Phase 35 Cleanup Sweep (kept out of this phase's scope).
- F16 cached-timestamp staleness → deferred cosmetic.
- No scope creep raised by the user.
