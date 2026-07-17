# Phase 32: Timezone & Date-Boundary Correctness - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning
**Mode:** `--auto` — gray areas auto-selected, recommended defaults locked in a single pass. These are audit-driven correctness fixes whose "correct" target is already fixed by the ROADMAP success criteria and the WHOLE-PROJECT-REVIEW findings, so the decisions below encode the audit's diagnosis rather than open product choices. Planner/researcher retain the mechanism-level discretion flagged inline. See `[[decide-for-me-on-deep-technical-phases]]`.

<domain>
## Phase Boundary

Clean up the residual timezone/date-boundary defects left by the One Call 3.0
migration — everything that answers "which local day is *today*, and is
`daily[0]` actually today?" relative to the configured IANA timezone. Four
correctness surfaces plus one de-duplication are in scope:

1. **HARD-TZ-01 — catch-up across local midnight (F14, `catchup.py:155`, CONFIRMED).**
   `plan_catchup` composes ONLY today's local date. A 23:45 slot that fails and is
   recovered at 00:15 the next local day builds `naive=datetime(now_local.y,m,d,23,45)`
   with *today's* date, so the recomputed instant is ~23.5h in the FUTURE and is
   skipped as "not due yet" (`scheduled > now_utc`, :170). Yesterday's genuinely-missed
   slot is never a candidate → silently lost. **Adjacent: F91 (`catchup.py:170`) DST
   fall-back fold math** — a fall-back repeated-hour slot is composed at `fold=0` only,
   so `now_utc - scheduled` can inflate by up to 60 min and push a slot minutes-late
   past the 90-min GRACE. Phase 31 explicitly deferred F91 here.
2. **HARD-TZ-02 — UV all-clear hysteresis (F15, `uvmonitor.py:318`, CONFIRMED).**
   Branch 3 (all-clear) gates only on instantaneous `summary.current`. One passing
   cloud at solar noon (UV 5.8 vs threshold 6.0) claims `allclear` durably (once/day
   INSERT OR IGNORE) and posts "✅ protect window over" while UV is still peaking and
   climbs back to 8 minutes later — the window can never re-open. No persistence /
   window-end gate exists. Also in scope: the **pre-warn↔crossing lifecycle must leave
   no never-fire gap** (every daylight × current-vs-threshold × prior-claims state must
   have a reachable transition; the moot-pre-warn suppression must not orphan).
3. **HARD-TZ-03 — `daily[0]` anchored to the configured tz (F31, F35, F109 + sibling
   tz findings).** `models.from_payloads` (:302) and `uv.compute_uv` (:133) hard-index
   `daily[0]` / trust its sunrise-sunset without verifying its OWN local date equals the
   configured-tz today. Near a tz/DST/midnight boundary `daily[0]` can be YESTERDAY, so
   the briefing ships yesterday's high/low/rain/UV labelled as today's, or silently
   reports `stays_below=True` (F31) because every "today" hourly bucket is filtered out
   against a stale sunset. F109 is the missing test that would have caught it. **Siblings
   folded in:** F33 (`models.py:84`) naive-`now_utc` silently interpreted in HOST tz;
   F32 (`uv.py:159`) hourly points not time-sorted before crossing/window interpolation.
4. **HARD-TZ-04 — unify `_local_date_iso` (F69).** The tz→local-date helper is
   duplicated so the two (actually **THREE**, see D-08) copies can silently diverge and
   mis-key persisted rows against the rendered briefing.

**In scope:** catch-up prior-local-day candidate + DST fold-correct grace math; UV
all-clear hysteresis + lifecycle-gap closure; `daily[0]`/positional indexing anchored
to configured-tz today in BOTH the briefing (`models`) and UV (`compute_uv`) paths,
with defensive degrade when no entry matches today; naive-`now_utc` hardening; hourly
time-sort before interpolation; one shared tz-correct `_local_date_iso` across
`models.py`, `store.py`, AND `uvmonitor.py`. Fixes must be test-shaped (regression
hooks land here; the comprehensive suite is Phase 34).

**Out of scope:** interactive/panel + bare-command crash F02 and cache-race F13
(Phase 33); the full test backfill F106/F109-suite (Phase 34, though fixes here must be
test-shaped); persistence data-model findings F36/F37 (`weather_onecall` rename-safety
& missing UNIQUE — store/analysis concern, not tz); all HUB findings (route UPSTREAM to
`yahir_reusable_bot`, human-gated — do NOT fix here). No new user features.
</domain>

<decisions>
## Implementation Decisions

### HARD-TZ-01 — Catch-up survives local midnight (D-01, D-02)
- **D-01 — Also test the PRIOR local day's instant.** `plan_catchup` must, for each
  slot, evaluate candidate dates {today, yesterday-local} — compose each candidate's
  naive wall-clock instant, attach the location zone, and run the SAME gates
  (gap-skip, `scheduled <= now_utc`, `now_utc - scheduled <= GRACE`, `was_sent`
  dedup). A slot missed at 23:45 and recovered at 00:15 becomes a valid yesterday
  candidate within GRACE. Dedupe so a single slot never emits twice; keep the existing
  "bounded to slots within GRACE / recovery burst is a quota rounding error" guarantee.
  The `local_date` recorded for `was_sent`/`MissedSlot` MUST be the candidate day's
  local date (yesterday's), not `now_local.date()`, so exactly-once keying stays correct.
- **D-02 — Fold-correct grace math on DST fall-back (F91).** The dueness/grace
  comparison must not be inflated by the `fold=0` default across a fall-back repeated
  hour. Align catch-up's fold choice with what the live APScheduler `CronTrigger`
  actually fires (so planner and live trigger agree), OR evaluate both folds and keep
  the slot due if EITHER fold lands within GRACE. **Mechanism (which fold, or
  both-folds-union) is planner/researcher discretion** — the invariant: a slot only
  minutes late inside the repeated hour is NOT dropped by a spurious 60-min inflation,
  and the existing spring-forward GAP skip (:161-168, never-existed wall-clock) is
  preserved unchanged.

### HARD-TZ-02 — UV all-clear hysteresis + lifecycle (D-03, D-04)
- **D-03 — All-clear needs persistence, not a single instantaneous dip.** Replace the
  "current < threshold" one-tick latch with a hysteresis gate. **Recommended primary:**
  anchor all-clear to the day's PREDICTED end-of-window — declare "protect window over"
  only once the forecast curve shows UV has passed its peak and will not climb back
  above threshold today (`compute_uv` already computes the peak/window, so reuse it),
  rather than trusting one momentary `current.uvi`. **Fallback when the predicted
  window is unavailable:** a persistence counter — require N consecutive sub-threshold
  ticks (and/or a sub-threshold margin) before claiming `allclear`. Exact N / margin /
  whether-primary-or-fallback-only is planner discretion; the invariant: a single
  passing-cloud dip while UV is still at/above threshold must NOT end the window.
- **D-04 — No never-fire gap in the pre-warn↔crossing↔all-clear lifecycle.** Enumerate
  the branch state machine (in_daylight × current-vs-threshold × prior-claims) and prove
  every state has a reachable transition for the day: the already-high/crossing branch,
  the pre-warn branch, and all-clear must jointly cover the day with no combination
  where none can fire. The moot-pre-warn suppression (WR-02, :268-272) must never
  orphan a state or block a legitimate later crossing/all-clear. Ship a test that walks
  a full-day tick sequence and asserts the expected posts fire exactly once each.

### HARD-TZ-03 — daily[0] anchored to configured-tz today (D-05, D-06, D-07)
- **D-05 — Select today's daily entry by its OWN local date, never by position.** Both
  `models.from_payloads` (:302 `daily[0]`) and `uv.compute_uv` (:133) must verify the
  chosen `daily[i]`'s local date (derived from its `dt`/`sunrise` in the CONFIGURED tz)
  equals today's configured-tz local date — reusing the existing WR-05 guard
  (`uvmonitor._daily0_matches_today`) and the multiday `_date_index_map` /
  `_resolve_tz` "no positional math" pattern. If NO entry matches today, degrade
  defensively down the existing empty / `stays_below` / `None` high-low path — NEVER
  ship a non-today entry labelled as today. `compute_uv` gains the same daily0-is-today
  guard the monitor already has (closes F31's morning-briefing false `stays_below`).
- **D-06 — `now_utc` must be treated as UTC-aware (F33).** The unified helper (D-08)
  and its callers must not let a naive `now_utc` be interpreted in the HOST tz by
  `astimezone()`. Attach `timezone.utc` when naive (or assert aware) so a naive
  injection near midnight can't shift the computed local_date by a day. Reconcile the
  now-dead UTC-fallback branches (F: `Location.timezone` is required/IANA-validated at
  load) — either keep them as an explicit belt-and-suspenders invariant or assert;
  planner discretion, but don't let dead fallback silently store a WRONG date.
- **D-07 — Sort today's hourly points before interpolation (F32, folded-in sibling).**
  `uv._today_daytime_points` (:159) appends in raw payload order; crossing/window
  interpolation assumes time-sorted points. Sort by timestamp before interpolating so
  an out-of-order payload or a DST fall-back duplicate hour can't straddle the wrong
  pair and emit a bogus crossing_time/window. Folded in under no-backlog posture
  because it corrupts the same UV window HARD-TZ-02/03 depend on; see
  `[[no-backlog-fold-cleanup-in]]`.

### HARD-TZ-04 — One `_local_date_iso` implementation (D-08)
- **D-08 — Unify into ONE tz-correct helper (note: THREE copies, not two).** The
  requirement/F69 name `models.py:69` and `store.py:210`, but a third,
  differently-signed copy lives in `uvmonitor.py:84` (`(now_utc, tz)`). Collapse all
  three onto one source of truth so the rendered `{date}`/UV-day and the persisted
  `local_date` can never diverge. **Recommended home:** a small pure, dependency-free
  tz helper module (mirroring the acyclic `scheduler/days.py` and `weather/multiday.py`
  precedents — no config/apscheduler/store imports) that `models.py`, `store.py`, and
  `uvmonitor.py` all import. Reconcile the two signatures (`(Location, now_utc)` vs
  `(now_utc, tz)`) — e.g. a core `(now_utc, tz)` primitive plus a thin
  `Location`-resolving wrapper — planner discretion. Fold the D-06 naive-`now_utc`
  hardening into this single helper so it's fixed once.

### Claude's Discretion (mechanism-level, for researcher/planner)
These are sub-mechanism notes on decisions already locked above (not separate trackable
decisions — the id in parens points back to the parent D-NN):
- **Fold mechanism** (re D-02) — which fold to compose for grace math, or union-of-both;
  match the live CronTrigger's actual firing so planner and trigger never disagree.
- **Hysteresis shape** (re D-03) — predicted-window-end vs consecutive-tick persistence
  vs sub-threshold margin (or a combination), and the exact N / margin values.
- **Shared "today entry" selector** (re D-05) — whether to extract one shared helper used
  by `models`, `compute_uv`, and the multiday path, or apply the WR-05 guard at each site.
  Lean toward one shared selector given three sites now do date-vs-position reasoning.
- **Helper home & signature** (re D-08) — new `weatherbot/weather/dates.py` (or similar)
  vs promoting into an existing pure module; core-primitive-plus-wrapper vs single fn.
- **Defensive-degrade wording** — what the briefing/UV line shows when no `daily[]`
  entry matches today (reuse the existing empty/`stays_below` collapse; don't invent a
  new user-facing string).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirement & roadmap
- `.planning/REQUIREMENTS.md` §Timezone/Date-Boundary — HARD-TZ-01, HARD-TZ-02,
  HARD-TZ-03, HARD-TZ-04 (lines 39–42; status table 96–99).
- `.planning/ROADMAP.md` §"Phase 32: Timezone & Date-Boundary Correctness" — goal,
  depends-on, and the 4 success criteria that are the locked acceptance target.

### Findings (source of truth — F14 & F15 are CONFIRMED)
- `.planning/WHOLE-PROJECT-REVIEW.md` §High → **F14** (`catchup.py:155`, catch-up only
  composes today) and **F15** (`uvmonitor.py:318`, all-clear no hysteresis) — the exact
  scenarios to reproduce/fix.
- `.planning/WHOLE-PROJECT-REVIEW.md` §SWEEP-NEW → **F31** (`uv.py:133`, compute_uv
  lacks daily0-is-today guard), **F32** (`uv.py:159`, hourly not sorted), **F33**
  (`models.py:84`, naive now_utc→host tz), **F91** (`catchup.py:170`, DST fall-back
  fold), **F69** (`models.py:69`+`store.py:210` `_local_date_iso` duplication), **F109**
  (`tests/test_models.py:156`, missing daily[0]-is-today coverage).
- `.planning/WHOLE-PROJECT-REVIEW.md` §PLAUSIBLE → **F35** (`models.py:302`, daily[0]
  hard-indexed as today).

### Source sites
- `weatherbot/scheduler/catchup.py` — `plan_catchup` (~138–178): today-only compose at
  :155, gap/fold roundtrip :156–168, dueness/grace gates :170–173, `was_sent` dedup :175.
- `weatherbot/scheduler/uvmonitor.py` — `_local_date_iso` (:84, 3rd copy),
  `_daily0_matches_today` WR-05 guard (:93–110, REUSE), decide branches (already-high/
  crossing :256–283, pre-warn :285–315, all-clear :317–323).
- `weatherbot/weather/models.py` — `_local_date_iso` (:69), `from_payloads` (:266–392),
  `daily[0]` hard-index (:302–303), local_date write (:388).
- `weatherbot/weather/store.py` — `_local_date_iso` (:210), `persist` target_local_date
  (:236).
- `weatherbot/weather/uv.py` — `compute_uv` (:133), `_today_daytime_points` (:159).
- `weatherbot/weather/multiday.py` — `_resolve_tz` (:38) + `_date_index_map` (:50), the
  "no positional math / match by local date" precedent (REUSE for D-05).
- `weatherbot/scheduler/days.py` — the acyclic, dependency-free pure-helper precedent
  (home-model for the unified tz helper, D-08).

### Prior-phase constraints that bind this phase
- `.planning/phases/31-send-atomicity-exactly-once-persistence-robustness/31-CONTEXT.md`
  §Deferred — explicitly punts **F91 DST fall-back fold** to this phase; also the
  `store.py` WAL/`_connect` refactor that just landed (any store-side tz change must not
  regress it).
- `.planning/phases/29-startup-validation-honest-alerting/29-CONTEXT.md` — validated
  boot + ready-gate/catch-up ordering is the dependency for catch-up correctness.

### Ecosystem guardrail
- `../Reusable/YahirReusableBot/ECOSYSTEM.md` — cross-repo jurisdiction: any HUB finding
  is human-gated and does NOT land here. See `[[multi-bot-ecosystem-extraction]]`.

### Codebase maps (context)
- `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/CONCERNS.md` — tz/D-03
  "configured IANA tz is authoritative" convention that all fixes must honor.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`uvmonitor._daily0_matches_today` (WR-05, :93–110)** — an existing guard that
  derives `daily[0]`'s own local date from its sunrise in the configured tz and
  requires it to equal today. D-05 extends this exact idea to `models.from_payloads`
  and `uv.compute_uv`, which currently lack it.
- **`multiday._date_index_map` (:50) + `_resolve_tz` (:38)** — the "map each `daily[i]`
  local date → index, NEVER positional math" pattern (Pitfall 1). The single-day path
  should borrow this instead of trusting `daily[0]`.
- **`catchup.py` gap/fold roundtrip (:156–168)** — the DST-safe compose (spring-forward
  never-existed skip via `off0!=off1 && roundtrip!=naive`). D-01 reuses this compose for
  the prior-day candidate; D-02 refines the fall-back fold choice within it.
- **Three `_local_date_iso` copies** — `models:69`, `store:210` (verbatim twins),
  `uvmonitor:84` (`(now_utc, tz)` variant). D-08 collapses all three.

### Established Patterns
- **D-03 "configured IANA tz is authoritative" (not the API `timezone` field, Pitfall 3)**
  — every date decision in this phase resolves through the configured `Location.timezone`.
- **Pure, acyclic helper modules** (`scheduler/days.py`, `weather/multiday.py`: no
  config/apscheduler/store imports, unit-testable in isolation) — the shape for the
  unified tz helper (D-08).
- **Fail-safe degrade** — UV fields collapse to "" / `stays_below`, high/low to `None`,
  on missing/mismatched data rather than raising (briefing-spine isolation). D-05's
  "no today entry" path reuses this, never a new error path.
- **Durable once-per-day claim** (`claim_uv_alert` INSERT OR IGNORE; `was_sent`) — D-01
  and D-03/D-04 must keep exactly-once keying correct (D-01: key on the candidate day,
  not `now`; D-03: don't let a premature all-clear claim burn the day's slot).

### Integration Points
- HARD-TZ-01: `plan_catchup` candidate-date loop + fold-correct grace; `MissedSlot`/
  `was_sent` keyed on the candidate local date.
- HARD-TZ-02: `uvmonitor` decide branches — all-clear hysteresis gate + lifecycle
  state-machine audit.
- HARD-TZ-03: `models.from_payloads` daily-entry selection, `uv.compute_uv` daily0 guard
  + hourly sort, naive-`now_utc` hardening.
- HARD-TZ-04: one shared helper imported by `models.py`, `store.py`, `uvmonitor.py`.

</code_context>

<specifics>
## Specific Ideas

- **F14 & F15 are CONFIRMED (not just plausible)** — the catch-up-across-midnight loss
  and the UV all-clear latch have concrete reproduction scenarios in the review; land
  each fix with a failing-first regression test that encodes that scenario.
- **The requirement undercounts the duplication** — HARD-TZ-04/F69 say "two call sites"
  but `uvmonitor.py:84` is a third `_local_date_iso`. Unify all three; call this out so
  the planner doesn't leave the monitor copy behind.
- **No-backlog posture (this milestone):** fold the sibling tz findings (F32 hourly
  sort, F33 naive-now_utc, the dead UTC-fallback cleanup) in now rather than deferring —
  they share the same date-boundary blast radius. See `[[no-backlog-fold-cleanup-in]]`.
- **Live daemon caveat:** WeatherBot runs as a live systemd service on `yahir-mint`
  (editable install). A catch-up / tz-boundary change is behaviorally verifiable across
  a local-midnight boundary; the plan should note a clean restart and how to exercise the
  midnight/DST paths deterministically (inject `now_utc`). See
  `[[weatherbot-live-systemd-service]]`.
- **Fixes must be test-shaped** — regression hooks land in this phase; the comprehensive
  suite (incl. F109's daily[0]-is-today test, F106's real-concurrency test) is Phase 34.

</specifics>

<deferred>
## Deferred Ideas

- **F02 bare-command crash & F13 cache-invalidation race** — interactive/panel surface,
  Phase 33 (which depends on this phase's render/tz formatting fixes).
- **Full regression-test backfill** (F109 daily[0]-is-today assertion, F106
  actually-concurrent double-fire) — Phase 34. Fixes here are test-shaped but the
  comprehensive suite is Phase 34's job.
- **F36 / F37 persistence data-model** (`weather_onecall` not rename-safe / no UNIQUE
  constraint → duplicate-row/analysis-join concerns) — store/analysis data-model, not a
  tz/date-boundary defect; not this phase.
- **All HUB findings** (F42/F43/F45/F98 etc.) — route UPSTREAM to `yahir_reusable_bot`,
  human-gated. Do NOT fix here.

None of the above are new capabilities — all are already-roadmapped later phases or
upstream/human-gated items. Discussion stayed within phase scope.

</deferred>

---

*Phase: 32-timezone-date-boundary-correctness*
*Context gathered: 2026-07-11*
