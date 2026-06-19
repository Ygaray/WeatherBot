# Phase 15 — Discussion Log

**Date:** 2026-06-18 · batch-discussed alongside phases 12, 13, 14.

| Gray area | Options presented | Decision |
|-----------|-------------------|----------|
| Pre-warn trigger | time-before-crossing (30m) / both-whichever-first / value-proximity | **Both, whichever first** (≤30 min to crossing OR within ~1 of threshold) |
| Start already-above | send one 'already high' / stay silent | **Send one 'already high' alert** (skip pre-warn) |
| Poll cadence & stop | 15m stop-after-both / 15m poll-till-sunset + all-clear | **15m, poll till sunset + send all-clear** |
| Alert tone | actionable + window / minimal | **Actionable + window** |

Notes (Claude's-discretion captured for planner): mechanism = APScheduler `IntervalTrigger` job like the heartbeat (isolation satisfies UV-06, no new thread); "active = location with an enabled briefing slot today"; dedup keyed `(location.id, local_date, alert_kind ∈ {prewarn,crossing,allclear})`. **Scope refinement:** three once/day alert types (added all-clear). **Research candidate** — plan with `--research-phase`.
