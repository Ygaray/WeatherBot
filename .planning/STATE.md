---
gsd_state_version: 1.0
milestone: v2.1
milestone_name: Hardening
status: Awaiting next milestone
stopped_at: Completed 35-09-PLAN.md
last_updated: "2026-07-17T21:52:33.061Z"
last_activity: 2026-07-17
last_activity_desc: Milestone v2.1 completed and archived
progress:
  total_phases: 7
  completed_phases: 7
  total_plans: 37
  completed_plans: 37
  percent: 100
current_phase: 35
current_phase_name: Cleanup Sweep
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-17 — v2.1 Hardening shipped)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Planning next milestone (v2.2 candidate: 15 deferred findings + hub v0.1.2 repin)

## Current Position

Phase: Milestone v2.1 complete
Plan: —
Status: Awaiting next milestone
Last activity: 2026-07-17 — Milestone v2.1 completed and archived

## v2.1 Roadmap at a Glance

| Phase | Goal (short) | Requirements |
|-------|--------------|--------------|
| 29 | Daemon `run` boot validates config/templates like `check-config`; permanent config/template errors alert instead of warn-looping forever as fake network faults | HARD-STARTUP-01/02/03 |
| 30 | The OpenWeather `appid` never rides in an exception/traceback/log line; the Discord inbound error path stops dumping the key | HARD-SEC-01 |
| 31 | Post-send bookkeeping can't release a delivered claim (no dup briefing), send failures detected + correctly classified, retry doesn't re-fetch, store atomic under `WAL`/`busy_timeout` | HARD-DELIV-01/02/03/04, HARD-STORE-01/02 |
| 32 | Catch-up survives local-midnight, UV all-clear has hysteresis, `daily[0]` anchored to configured IANA tz, duplicated `_local_date_iso` unified | HARD-TZ-01/02/03/04 |
| 33 | Bare location commands resolve the default instead of crashing, panel cache/interaction races closed, rendering defects fixed | HARD-UI-01/02/03 |
| 34 | False-green tests corrected; highest-risk uncovered paths (retry-exhaustion, midnight catch-up, rename-safe id, store atomicity) get real regression tests | HARD-TEST-01/02 |
| 35 | Dead/divergent code + inaccurate docs removed; remaining low-severity latent findings resolved or accepted-with-rationale — no silent debt | HARD-CLEAN-01/02 |

**Dependency notes:** Correctness-first, cleanup-last. Startup validation (29) is the highest real-world-impact class (a boot-green misconfig drops every briefing) and gates the rest — everything downstream assumes a validated boot. Secret hygiene (30) is cheap/high-value, sequenced second. Send atomicity + persistence (31) are paired because SQLite `WAL`/`busy_timeout` de-risks the very `database is locked`-after-delivery race that makes the F01 duplicate-briefing critical reachable. Timezone/date-boundary (32) then panel robustness (33) — 33 shares 32's render/tz formatting fixes. Test backfill (34) closes over the paths 29–33 fixed, so each fix ships with a regression test. Cleanup (35) is strictly last, sweeping residue in files the correctness phases already opened. **Verify-first criticals:** F01 (`daemon.py:335`, Phase 31) and F02 (`dispatch.py:119`, Phase 33) are `SWEEP-NEW` — reproduce/confirm the finding before landing the fix.

**Verification posture:** Two-Gate UAT applies. This is a backend/daemon milestone (no new frontend) — treat the UI gate as skip; Phase 33 is Discord-command correctness, not visual design. Gate-1 agent self-UAT gates each phase; Gate-2 live `yahir-mint` restart UAT is a deferred milestone-close obligation (the live systemd service is editable-installed; a deploy + `systemctl restart weatherbot` is needed to exercise the daemon on-host).

**Scope + handoff:** 99 WeatherBot findings in scope (88 WB + 11 shared). The **17 hub findings route upstream** — captured in `.planning/HUB-FINDINGS-HANDOFF.md` for a separate `YahirReusableBot` milestone (human-gated tag cut); WeatherBot repins after the hub ships `v0.1.2`. Full ranked detail: `.planning/WHOLE-PROJECT-REVIEW.md` + `.planning/audit-raw.json`. Requirements + traceability: `.planning/REQUIREMENTS.md`.

## Performance Metrics

**Velocity (shipped):** v1.0 — 47 plans / Phases 1–5 / 11 days / 186 tests. v1.1 — 22 plans / Phases 6–11 / ~4 days / 291 tests. v1.2 — 15 plans / Phases 12–15 / 575 tests. v1.3 — 11 plans / Phases 16–20 / ~4 days / 649 tests / 18 feat commits. v2.0 — 26 plans / Phases 21–28 / 15/15 reqs / 776 tests / shipped 2026-07-07.

**v2.1:** roadmap created 2026-07-08 (7 phases, 21 requirements, 100% coverage). No plans yet.

## Accumulated Context

### Decisions

Full decision log lives in **PROJECT.md → Key Decisions** (v2.1 governing decisions folded in there at milestone close: audit-driven hardening, correctness-first/cleanup-last sequencing, paired DELIV+STORE, verify-first on the F01/F02 criticals, RED-first-test-per-fix, human-gated hub findings, no-defer-low-findings). The v2.1 per-plan decision detail is archived in `.planning/milestones/v2.1-phases/*/*-SUMMARY.md`.

**v2.1 disposition ledger (final):** 99 WB/BOTH findings reconciled — 65 FIXED / 19 ACCEPTED-with-rationale / 15 DEFERRED(v2.2); 17 HUB findings routed to `HUB-FINDINGS-HANDOFF.md` (out of scope, human-gated).

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

- ✅ **[v2.1 Gate-2 — RESOLVED 2026-07-17] Live milestone-close restart UAT on host `yahir-mint`:** verified — clean v2.1 boot (no green-boot misconfig), a real briefing fired exactly once (no duplicate), no key in the journal, correct timezone/date on-host, panel/commands confirmed. No deferred Gate-2 obligation remains.

### Blockers/Concerns

[Issues that affect future work]

- **[v2.1 ops watch-item] Unexplained 14:12 fatal-config alert (2026-07-17):** a foreground `weatherbot run` (NOT the systemd service, NOT operator-triggered, source unidentified from host yahir-mint) hit a FileNotFoundError and posted the v2.1 fatal-config alert (reason=config_invalid) to the real Discord channel, then exited. Production daemon unaffected (clean v2.1 boot, check-config passes, templates present — cannot reproduce). Hypotheses: an older dev-run message, or a second WeatherBot instance sharing the webhook. **Tailnet checked 2026-07-17:** no second Linux daemon exists — `chimuelo-blackcat` (tailscale node, 100.84.55.28) IS this same box (tailscale name ≠ hostname `yahir-mint`); only other WeatherBot-capable host is `yahir-carbon` (Windows laptop). Narrowed to: (a) a manual run of a dev checkout on `yahir-carbon`, or (b) an older dev-run message (e.g. Phase 29 execution ~Jul 8) mis-read as today — decisive check is the DATE on the Discord message. Follow-up: consider routing operator alerts to a separate channel so dev fatals never hit the briefing channel (v2.2 candidate).
- **Hub-finding dependency:** WeatherBot cannot fully close some shared-surface findings until the hub ships `v0.1.2` and WeatherBot repins. In-scope WeatherBot fixes proceed independently; hub-rooted items stay handed off.
- **Carry-forward `[bot]` read-once-at-startup tech debt:** `[bot] operator_id` / `[reload] watch` / `panel_channel_id` are read once at startup (restart boundary) — pre-existing, not a v2.1 target unless a finding touches it.
- **DATA-03 delivered-only persistence semantics** (open since v1.0): confirm when v2 analysis (ANLY-V2-01) reads the store — deferred beyond v2.1.

## Deferred Items

Items acknowledged and carried forward:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Cross-repo | 17 hub findings routed upstream (`HUB-FINDINGS-HANDOFF.md`) — require a human-gated `YahirReusableBot` tag cut; WeatherBot repins after hub `v0.1.2`. | Handed off | v2.1 scope |
| Data semantics | DATA-03 delivered-only persistence — confirm when v2 analysis (ANLY-V2-01) reads the store. | Open (post-v2.0) | v1.0 close |
| Extension point | Durable/dynamic `JobStore` impl (JOBSTORE-V2-01) — seam designed in v2.0, impl deferred to a reminder-style consumer. | Deferred (designed in Phase 23) | v2.0 scope |
| Extension point | 2nd `Channel` adapter (Telegram/SMS/Slack — CHAN-V2-01/02/03) — abstraction shipped, impls deferred to their own milestones. | Deferred | v2.0 scope |

_All v1.0–v2.0 host UATs were resolved at their milestone Gate-2 closes; see milestones/*-MILESTONE-AUDIT.md._
| Phase 29 P01 | 10m | 2 tasks | 2 files |
| Phase 29 P02 | 24min | 3 tasks | 3 files |
| Phase 29 P03 | 4min | 2 tasks | 4 files |
| Phase 29 P06 | 3 | 2 tasks | 3 files |
| Phase 29 P04 | 14min | 2 tasks | 2 files |
| Phase 29 P05 | 20min | 3 tasks | 4 files |
| Phase 30 P01 | 20 | 3 tasks | 4 files |
| Phase 31 P01 | 20min | 3 tasks | 5 files |
| Phase 31 P02 | ~5min | 3 tasks | 2 files |
| Phase 31 P03 | ~20min | 4 tasks | 6 files |
| Phase 32 P01 | 25 | 3 tasks | 5 files |
| Phase 32 P02 | 4 | 2 tasks | 3 files |
| Phase 32 P03 | 12m | 2 tasks | 2 files |
| Phase 32 P04 | 9m | 2 tasks | 4 files |
| Phase 32 P05 | 6 | 2 tasks | 1 files |
| Phase 33 P01 | 9min | 2 tasks | 4 files |
| Phase 33 P02 | 3m | 2 tasks | 2 files |
| Phase 33 P03 | 4m | 2 tasks | 4 files |
| Phase 33 P04 | 10min | 2 tasks | 2 files |
| Phase 33 P05 | 4m | 2 tasks | 4 files |
| Phase 33 P06 | 35min | 2 tasks | 12 files |
| Phase 34 P01 | 3m | 2 tasks | 1 files |
| Phase 34 P02 | 2min | 3 tasks | 1 files |
| Phase 34 P03 | 8m | 2 tasks | 2 files |
| Phase 34 P04 | 4m | 2 tasks | 1 files |
| Phase 34 P05 | 12min | 2 tasks | 1 files |
| Phase 34 P06 | 3min | 2 tasks | 2 files |
| Phase 34 P07 | ~4 min | 2 tasks | 1 files |
| Phase 35 P01 | 12min | 1 tasks | 1 files |
| Phase 35 P04 | ~3min | 2 tasks | 3 files |
| Phase 35 P05 | 7min | 3 tasks | 5 files |
| Phase 35 P06 | 7min | 3 tasks | 9 files |
| Phase 35 P07 | 4min | 2 tasks | 2 files |
| Phase 35 P02 | 2min | 2 tasks | 3 files |
| Phase 35 P03 | 5min | 2 tasks | 2 files |
| Phase 35 P08 | 18min | 2 tasks | 7 files |
| Phase 35 P09 | 22m | 2 tasks | 2 files |

## Session Continuity

Last session: 2026-07-13T19:40:14.992Z
Stopped at: Completed 35-09-PLAN.md
Resume file: None

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
