# Phase 31: Send Atomicity, Exactly-Once & Persistence Robustness - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-10
**Phase:** 31-send-atomicity-exactly-once-persistence-robustness
**Mode:** `--auto` (autonomous — recommended defaults selected, no interactive prompts)
**Areas discussed:** F01 send atomicity, F08 forecast-slot failure detection, DELIV-03 retry payload reuse, DELIV-04 auth-vs-transient classification, HARD-STORE SQLite hardening

---

## F01 — Send atomicity (never release a delivered claim)

| Option | Description | Selected |
|--------|-------------|----------|
| Move bookkeeping out of the release-on-failure path | Once `result.ok`, claim is source-of-truth; `resolve_alert`/`stamp_success` become best-effort log-and-swallow, `release_claim` unreachable post-delivery (mirrors `daemon.py:1029`) | ✓ |
| Wrap whole send+bookkeeping in a savepoint/2PC | Heavier transactional coupling of delivery and DB bookkeeping | |
| Only add busy_timeout and hope contention disappears | Reduces likelihood but leaves the release-on-post-delivery-error logic bug intact | |

**Auto-selected:** Restructure so `release_claim` is only reachable before delivery success (D-01). Reproduce first (D-01a) — SWEEP-NEW critical.
**Notes:** WAL + busy_timeout (HARD-STORE) is the root de-risker but does NOT by itself fix the logic bug; both are needed.

---

## F08 — Forecast-slot delivery failure detection

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror `fire_slot`: inspect `result.ok` | Branch on the `DeliveryResult`; `ok=False` → `_note_forecast_failure` + WR-05 dead-slot escalation | ✓ |
| Make `channel.send` raise on non-2xx for forecasts | Breaks the never-raise `DeliveryResult` channel contract | |
| Leave as-is (accept silent forecast dead-slot) | Violates "retry then alert rather than silently miss" | |

**Auto-selected:** Inspect `result.ok`, only a clean delivery resets the streak (D-02).
**Notes:** Preserve isolation — a forecast failure still never touches a briefing.

---

## DELIV-03 — Retry reuses the fetched payload

| Option | Description | Selected |
|--------|-------------|----------|
| Fetch once, retry only the delivery | Retry/backoff wraps only `send`, reuses in-memory payload | ✓ |
| Re-fetch each retry attempt | Extra OpenWeather calls; content can change mid-retry (status quo bug) | |

**Auto-selected:** Fetch once, retry only delivery (D-03). Same principle as FCAST-07 payload reuse.

---

## DELIV-04 — Auth vs transient classification

| Option | Description | Selected |
|--------|-------------|----------|
| Classify 401/403 → auth_failed, short-circuit retry | Send path reaches parity with fetch path; no full ~65-min burn | ✓ |
| Keep all non-2xx as transient | Burns full retry schedule, wrong alert reason (status quo bug) | |

**Auto-selected:** 401/403 → `auth_failed`, short-circuit (D-04). Carrier (typed result vs raised auth error) left to planner; Phase-30 `httpx.HTTPStatusError` type contract must not regress.

---

## HARD-STORE — SQLite hardening

| Option | Description | Selected |
|--------|-------------|----------|
| WAL + busy_timeout + non-writing reads + atomic writes (full) | Shared `_connect` helper, schema-init split, transactional multi-step writes | ✓ |
| WAL + busy_timeout only | Leaves reads taking a write lock (F10) and truncate-then-write window | |
| busy_timeout only | Minimal; does not decouple readers/writer | |

**Auto-selected:** Full hardening (D-05..D-08), no-backlog posture folds the read-lock cleanup in now.
**Notes:** Live systemd SQLite file — plan for a clean restart when changing journal_mode.

---

## Claude's Discretion

- Shared `_connect(...)` helper vs. per-site pragmas (lean: one helper).
- Auth-classification carrier form (typed `DeliveryResult` field vs. raised auth error).
- Exact `busy_timeout` ms; WAL via PRAGMA-on-connect vs. one-time migration.
- Retry-scope refactor shape (fetch/deliver boundary in `send_now`/`fire_slot`).

## Deferred Ideas

- F94 `is_transient` gap (hub, upstream/human-gated) — related to DELIV-04 but not fixed here.
- F04 SIGTERM-drain (hub, upstream).
- F91 DST fall-back fold math → Phase 32.
- F13 cache-invalidation race, F02 bare-command crash → Phase 33.
- Full regression-test backfill → Phase 34.
