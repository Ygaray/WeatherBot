---
gsd_state_version: 1.0
milestone: v2.1
milestone_name: Hardening
current_phase: 29
current_phase_name: startup-validation-honest-alerting
status: executing
stopped_at: Phase 29 context gathered
last_updated: "2026-07-08T05:22:06.345Z"
last_activity: 2026-07-08
last_activity_desc: Phase 29 execution started
progress:
  total_phases: 7
  completed_phases: 0
  total_plans: 6
  completed_plans: 3
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-07 — v2.0 "The Great Decoupling" shipped; v2.1 Hardening active)

**Core value:** Every morning, the user reliably receives a clear, correctly-located weather briefing for the place they'll actually be that day — without lifting a finger.
**Current focus:** Phase 29 — startup-validation-honest-alerting

## Current Position

Phase: 29 (startup-validation-honest-alerting) — EXECUTING
Plan: 4 of 6
Status: Ready to execute
Last activity: 2026-07-08 — Phase 29 execution started

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

Full decision log lives in PROJECT.md Key Decisions. v2.1-specific governing decisions:

- **Audit-driven, no new user features:** every requirement is a testable *hardening outcome* traced to a finding id in `.planning/WHOLE-PROJECT-REVIEW.md`; the milestone hardens the existing One Call 3.0 daemon rather than adding surface.
- **Correctness-first, cleanup-last sequencing:** startup-validation → secret-hygiene → send-atomicity+persistence → timezone/date → panel-robustness → test-backfill → cleanup. The point is to stop the briefing spine failing silently before touching latent debt.
- **Pair DELIV + STORE (Phase 31):** the persistence hardening (`WAL`/`busy_timeout`, atomic writes) is the root de-risker of the F01 duplicate-briefing critical, so they land together in one phase.
- **Verify-first on the two SWEEP-NEW criticals:** F01 (`daemon.py:335`) and F02 (`dispatch.py:119`) are unverified sweep findings — the phase reproduces/confirms the finding before landing the fix.
- **Each fix ships with a regression test:** Phase 34 formalizes it, but every correctness fix in 29–33 must have a test that fails against pre-fix behavior — "tests green" alone doesn't prove a false-green wasn't left in place.
- **Hub findings are human-gated:** the 17 `yahir_reusable_bot/…` findings are NOT fixed in this milestone; they route to `HUB-FINDINGS-HANDOFF.md` and a separate hub tag cut, then WeatherBot repins.
- [Phase ?]: 29-02: wrapped the two red service-unit directive tests in xfail(strict=False) to hold the execution-chain suite at exit 0 (29-01 invariant) per the Wave-0 RED contract escape hatch — assertion bodies unchanged, flips to XPASS when 29-06 lands
- [Phase ?]: CONFIG_INVALID (29-03): split pre-probe config faults into their own CRITICAL classifier before the network probe; re-exported to daemon namespace for 29-05 _on_fail

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

- **[v2.1 Gate-2] Live milestone-close restart UAT on host `yahir-mint`:** after the correctness fixes land, deploy → `sudo systemctl restart weatherbot` → confirm a validated boot (no green-boot misconfig), a real briefing fires exactly once (no duplicate), no key in the journal, and correct timezone/date on-host. Deferred milestone-close obligation.

### Blockers/Concerns

[Issues that affect future work]

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

## Session Continuity

Last session: 2026-07-08T05:21:46.073Z
Stopped at: Phase 29 context gathered
Resume file: .planning/phases/29-startup-validation-honest-alerting/29-CONTEXT.md

## Operator Next Steps

- Plan the first phase: `/gsd-plan-phase 29`
