# Phase 8: ConfigHolder & `fire_slot` Reads-From-Holder Refactor - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 8-configholder-fire-slot-reads-from-holder-refactor
**Areas discussed:** Config seam, Snapshot immutability, Holder read scope, Swap API

---

## Config seam (how fire_slot gets config)

| Option | Description | Selected |
|--------|-------------|----------|
| holder param + config override | fire_slot takes `holder`, reads holder.current() at fire time; optional `config=` override wins when passed (tests/standalone fires) | ✓ |
| holder param only | Replace `config` kwarg entirely with required `holder`; every caller + test builds a ConfigHolder | |
| Keep config kwarg, read holder inside | fire_slot reads a module/process-level holder singleton directly (global state) | |

**User's choice:** holder param + optional config override
**Notes:** Live jobs read live config; tests stay simple without constructing a holder; avoids global state.

---

## Snapshot immutability

| Option | Description | Selected |
|--------|-------------|----------|
| frozen=True on Config models | pydantic `frozen=True` on Config + nested models; mutation raises | ✓ |
| Immutable by convention | Leave mutable; rely on holder only swapping whole objects | |
| frozen only on top-level Config | Freeze top-level only; nested mutation still slips through | |

**User's choice:** frozen=True on Config models (applied to all nested models)
**Notes:** Source grep confirmed nothing mutates a loaded config today, so freezing breaks no existing code — low risk, type-enforced guarantee.

---

## Holder read scope

| Option | Description | Selected |
|--------|-------------|----------|
| All daemon readers | fire_slot + catch-up + _announce_schedule all read holder.current(); heartbeat untouched | ✓ |
| fire_slot only (minimal) | Only live cron jobs read the holder; catch-up/announce keep captured config | |
| fire_slot + catch-up | Both fire paths read holder; announce stays on captured config | |

**User's choice:** All daemon readers
**Notes:** One source of truth in the daemon; catch-up/announce run once at startup so behavior is identical today but the seam is uniform for Phase 9.

---

## Swap API now vs P9

| Option | Description | Selected |
|--------|-------------|----------|
| Define replace() now | Ship current() + lock-guarded replace() now, plus a test proving a swap reaches an unchanged fire_slot job | ✓ |
| current() only now | Ship only current(); add replace()/swap in Phase 9 | |
| Define replace() + check-config seam | replace() now AND stub validate-before-swap (risks scope creep) | |

**User's choice:** Define replace() now (with the swap-reaches-unchanged-job test)
**Notes:** Proves the core promise of the refactor in Phase 8 and hands Phase 9 a ready seam. Validate-before-swap explicitly excluded as Phase 9 scope.

---

## Claude's Discretion

- Lock type (`Lock` vs `RLock`) and whether `current()` reads under the lock — holder must be thread-safe under APScheduler's `max_workers=10` threadpool.
- Read-consistency-per-fire (recommend a single `holder.current()` read at the top of `fire_slot`, threaded through delivery + `send_now`).
- Module location / naming of `ConfigHolder`.
- Where the holder is constructed/owned (recommend `run_daemon`, mirroring `stop_event`/`channel` threading).

## Deferred Ideas

- Validate-before-swap boundary → Phase 9 (CFG-04).
- Reload engine, SIGHUP / `weatherbot reload`, job diff, `--check-config` → Phase 9.
- `settings`/`.env` reloadability → permanently out of scope (restart boundary, Pitfall #12); holder owns `Config` only.
