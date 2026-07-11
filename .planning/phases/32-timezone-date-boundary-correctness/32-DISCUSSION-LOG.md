# Phase 32: Timezone & Date-Boundary Correctness - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-11
**Phase:** 32-timezone-date-boundary-correctness
**Mode:** `--auto` (gray areas auto-selected; recommended defaults locked in a single pass, no interactive prompts)
**Areas discussed:** Catch-up across local midnight, UV all-clear hysteresis, daily[0] tz-anchoring, _local_date_iso unification

---

## Catch-up across local midnight (HARD-TZ-01 · F14/F91)

| Option | Description | Selected |
|--------|-------------|----------|
| Prior-day candidate + fold-correct grace | Also compose yesterday-local instant, run same gates; align fold with live CronTrigger | ✓ |
| Widen GRACE window only | Increase the 90-min grace so a just-after-midnight recovery still lands | |
| Persist "missed" markers at slot time | Record misses proactively so recovery doesn't recompute dates | |

**User's choice:** Prior-day candidate + fold-correct grace (recommended, `--auto`).
**Notes:** F14 CONFIRMED — today-only compose skips yesterday's 23:45 slot as "future". `local_date` must key on the candidate day, not `now`. F91 DST fall-back fold folded in (Phase 31 punted it here). Fold mechanism = planner discretion.

---

## UV all-clear hysteresis (HARD-TZ-02 · F15)

| Option | Description | Selected |
|--------|-------------|----------|
| Predicted window-end + persistence fallback | Anchor all-clear to forecast peak/window; fall back to N-consecutive-tick counter | ✓ |
| Consecutive-tick persistence only | Require N sub-threshold ticks before claiming allclear | |
| Sub-threshold margin only | Require current < threshold − margin | |

**User's choice:** Predicted window-end + persistence fallback (recommended, `--auto`).
**Notes:** F15 CONFIRMED — one passing cloud latches "protect window over" durably. compute_uv already computes peak/window → reuse it. Also close the pre-warn↔crossing↔all-clear never-fire lifecycle gap. N/margin = planner discretion.

---

## daily[0] tz-anchoring (HARD-TZ-03 · F31/F32/F33/F35/F109)

| Option | Description | Selected |
|--------|-------------|----------|
| Select today's entry via WR-05 / _date_index_map | Verify chosen daily[i] local date == configured-tz today; degrade if none | ✓ |
| Cross-validate configured tz against payload tz | Compare Location.timezone to the API timezone field and warn on drift | |
| Trust daily[0], add a logging assertion only | Keep positional index, log when it looks stale | |

**User's choice:** Select today's entry via existing WR-05 / _date_index_map pattern (recommended, `--auto`).
**Notes:** Applies to both models.from_payloads AND uv.compute_uv (F31 morning false stays_below). Folded siblings: F32 hourly time-sort, F33 naive-now_utc→UTC hardening. Defensive degrade reuses existing empty/None path. F109 test → Phase 34.

---

## _local_date_iso unification (HARD-TZ-04 · F69)

| Option | Description | Selected |
|--------|-------------|----------|
| One pure dependency-free helper module (3 copies) | New pure tz helper imported by models, store, AND uvmonitor | ✓ |
| Put canonical copy in models.py | Store & uvmonitor import from models | |
| Put canonical copy in store.py | Models & uvmonitor import from store | |

**User's choice:** One pure dependency-free helper module (recommended, `--auto`).
**Notes:** Requirement says "two call sites" but there are THREE (uvmonitor.py:84 has a `(now_utc, tz)` variant) — surfaced. Home mirrors days.py/multiday.py acyclic precedent. Signature reconciliation (core primitive + Location wrapper) = planner discretion. D-06 naive-now_utc fix folds in here.

---

## Claude's Discretion

- D-02 catch-up fold mechanism (which fold / union-of-both, matched to live CronTrigger).
- D-03 hysteresis shape and exact N / margin values.
- D-05 whether to extract one shared "today entry" selector vs guard-at-each-site.
- D-08 unified helper home, module name, and signature (primitive + wrapper vs single fn).
- Defensive-degrade wording when no daily[] entry matches today (reuse existing collapse).

## Deferred Ideas

- F02 bare-command crash & F13 cache-invalidation race → Phase 33.
- Full regression-test backfill (F109 daily[0]-is-today, F106 real-concurrency) → Phase 34.
- F36/F37 weather_onecall rename-safety / missing UNIQUE → store data-model, not this phase.
- All HUB findings → route UPSTREAM to yahir_reusable_bot, human-gated.
