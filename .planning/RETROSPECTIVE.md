# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — WeatherBot MVP

**Shipped:** 2026-06-15
**Phases:** 5 | **Plans:** 21 | **Tasks:** 36

### What Was Built
- End-to-end briefing pipeline (config+secrets → OpenWeather → SQLite → render → Discord) behind a pluggable `Channel.send(text)` seam.
- Real multi-location config (per-location IANA tz + units override), feels-like/hints/severe-weather, safe editable templates, `--check`/`--geocode`/`--send-now`.
- Always-on APScheduler daemon: per-location wall-clock firing, DST exactly-once, 90-min catch-up, atomic `claim_slot` idempotency.
- Retry-then-alert reliability: two-burst tenacity backoff, out-of-band log+DB alert, heartbeat, exception isolation.
- Reboot survival: self-check gate + `sd_notify` READY=1 under a systemd `Type=notify`/`Restart=always` unit, confirmed live on host `yahir-mint`.

### What Worked
- **Vertical-slice Phase 1** proved the whole pipeline live (real API + webhook) before any scheduling complexity — de-risked everything downstream.
- **Foundational concerns baked in from Phase 1** (IANA tz in the model, secrets-from-env, the channel interface, analysis-ready SQLite schema) avoided retrofits/migrations later.
- **Single composition root (`send_now`)** reused by both `--send-now` and the daemon's `fire_slot` — the integration audit confirmed zero drift between manual and scheduled paths.
- **Gap-closure discipline:** verification caught real gaps (units override 02-05, DST + exactly-once 03-04/03-05, online-ping 05-03) and closed them inline rather than shipping silently.

### What Was Inefficient
- **Human-verify deferral churn:** OPS-01 SC#1 (live reboot) stayed open across the audit and milestone-close because it power-cycles the operator's primary workstation — required two extra doc-update passes once confirmed.
- **SUMMARY `one_liner` hygiene:** several plans' one-liner field captured a code-review finding instead of the deliverable, so the auto-generated MILESTONES.md accomplishments were noisy and had to be hand-rewritten.
- **Missing `requirements-completed` frontmatter** on 11 plan SUMMARYs surfaced only at audit time (resolved via quick task 260615-fac).
- **gsd-tools CLI not installed in the exec environment** for some phases → STATE/ROADMAP updated manually (noted in Phase 4 SUMMARYs).

### Patterns Established
- Atomic `claim_slot` (INSERT OR IGNORE + rowcount==1) as the single idempotency primitive — check-then-act (`was_sent`+`record_sent`) retired.
- Out-of-band alerting = conspicuous structlog CRITICAL + dedup'd DB row (a second Discord webhook is not independent of a Discord outage).
- systemd `Type=notify` with READY=1 gated behind the startup self-check — "active" never reported on a bad key/network.
- Worktree isolation disabled (`use_worktrees=false`) — sequential-on-main, per the parallel-execution wrong-base issue in this repo.

### Key Lessons
1. For human-only UAT that's expensive to run (reboot, destructive), decide the close policy up front — accept-as-deferred vs block — so it doesn't create repeated re-documentation passes.
2. Enforce SUMMARY frontmatter hygiene (`one_liner` = deliverable, `requirements-completed` present) at plan-execution time; it's far cheaper than backfilling at milestone close.
3. A clean single composition root pays off at integration-audit time: there were no manual-vs-daemon seam bugs to chase.

### Cost Observations
- Model mix: predominantly Opus for orchestration/planning/execution (exact split not instrumented this milestone).
- Notable: re-verification + gap-closure cycles (3 phases) added passes but caught real correctness gaps (DST, exactly-once, units, online-ping) before ship.

---

## Milestone: v1.1 — Interactive & Live-Config

**Shipped:** 2026-06-19
**Phases:** 6 (6–11) | **Plans:** 22 | **Tasks:** 29

### What Was Built
- One shared read-only fetch→render core (`interactive/lookup.py`) + pure three-state `weather <loc>` parser, called identically by both new surfaces.
- Standalone `weatherbot weather [location]` CLI one-shot (real console-script entry, argparse subcommands, 0/1/2/3 exit contract, no daemon).
- Lock-guarded `ConfigHolder` of immutable (`frozen=True`) snapshots; `fire_slot` reads `holder.current()` once per job.
- Reload engine: validate → atomic swap → diff-reconcile by stable id, keep-old on failure, exactly-once preserved (sent-log key moved name→`location.id`); SIGHUP / `weatherbot reload` / `check-config` dry-run.
- Debounced `watchfiles` auto-reload funneling into the same `_do_reload`; isolated Discord `!weather` gateway bot (off-loop fetch, TTL cache, guard ladder, started after systemd READY, torn down in `finally`) + reload-outcome Discord posts.

### What Worked
- **Shared-core-first (Phase 6) before either surface** — the same vertical-slice discipline as v1.0; CLI and bot inherited identical fetch/render/error semantics with zero duplication, confirmed at the integration audit.
- **Prerequisite refactor as its own phase (Phase 8 ConfigHolder before Phase 9 reload)** — landing the correctness seam first made the load-bearing "unchanged job renders new config after replace" and exactly-once-across-reload behaviors testable in isolation before the feature depended on them.
- **Nyquist Wave-0 RED scaffolds** (phases 8/9/10/11) pinned each behavioral contract before implementation — the SC#4 name/tz exactly-once guard existed as a failing test before the engine.
- **Re-verification + code-review caught real blockers before ship:** Phase 9 cross-process-sender bugs (os.kill TOCTOU CR-01, substring PID-guard CR-02) and Phase 10's live-re-watch dead-code (regression-proven by removing the fix) were closed inline, not shipped.
- **Single reload funnel:** three trigger sources (SIGHUP, CLI, file-watch) converging on one `reload_requested` Event kept the engine path singular and the file-watch layer thin.

### What Was Inefficient
- **SUMMARY `one_liner` hygiene regressed again** — several plans' one-liner captured a "[Rule 3 - Blocking]" code-review deviation instead of the deliverable, so the auto-generated MILESTONES.md accomplishments were noisy and needed a full hand-rewrite. This was a flagged v1.0 lesson that wasn't enforced.
- **Stale tracking status at close:** Phase 11's verification frontmatter stayed `human_needed` after its UAT passed, and two completed quick-task SUMMARYs lacked `status: complete` — so all three tripped the pre-close audit despite being done-and-verified. Required status corrections before tagging.
- **A production-only ops bug surfaced at live deploy, not in tests:** the non-root daemon's PID-file write crash-looped under systemd (fixed via quick-260617-idm with `RuntimeDirectory=`/`/run/weatherbot/`). The offline suite can't see a `/run` write-permission failure.

### Patterns Established
- **Nyquist Wave-0 RED scaffold per phase** — pin the behavioral contract as failing tests before any implementation plan runs.
- **Sequence the correctness prerequisite as its own phase** before the feature that depends on it (holder before reload).
- **Flag-set-only handlers + single main-thread reload funnel** — signal/observer threads only `.set()` an Event; the actual validate/swap/reconcile runs on one main-thread path shared by every trigger.
- **Thread-isolated side-surface started after the READY gate, torn down in `finally`** — an inbound bot can never gate the systemd ready signal or stop the core briefing path.
- **Stable durable key decoupled from mutable display name** (`location.id` vs `location.name`) so renames/tz edits don't disturb exactly-once.

### Key Lessons
1. **Enforce SUMMARY frontmatter hygiene at execution time** (one_liner = deliverable, `status`/`requirements-completed` present) — the v1.0 lesson recurred and re-cost a milestone-close hand-rewrite. Worth a lint/hook rather than another resolution to "remember."
2. **Flip verification/quick-task status when UAT resolves the work** — the pre-close audit only reflects reality if `human_needed`→`passed` and `status: complete` are written when the live items actually close.
3. **Live-host UAT stays essential for ops/runtime concerns** — environment-specific failures (non-root `/run` writes, privileged Discord intents) are structurally invisible to an offline suite; budget a real deploy pass.
4. **Landing the correctness seam (holder) a phase early** made the highest-risk behavior (exactly-once across reload) provable in isolation — repeat for future risky features.

### Cost Observations
- Model mix: predominantly Opus for orchestration/planning/execution (split not instrumented).
- Notable: re-verification (Phase 9) and code-review (Phase 10) cycles added passes but caught genuine correctness/safety blockers before ship; one live UAT bug required a follow-up quick task.

---

## Milestone: v1.2 — Forecasts, Commands & UV

**Shipped:** 2026-06-20
**Phases:** 4 (12–15) | **Plans:** 15 | **Tasks:** 34

### What Was Built
- A self-describing command registry (`registry.COMMANDS`) that auto-derives the CLI subparsers, Discord dispatch, and `help` from one list — plus seven read-only commands (`help`/`locations`/`status`/`sun`/`wind`/`alerts`/`next-cloudy`), and the One Call `exclude` widened to retain `hourly[]` as the shared data seam.
- Multi-day weekday/weekend forecast templates (detailed/compact, additive day flags), on demand (CLI + Discord) and per-location scheduled, reusing the already-fetched `daily[]` with no extra fetch.
- End-to-end UV: a pure interactive-layer-free `compute_uv()`/`UvSummary`, the `uv <loc>` command on both surfaces, a UV section in the daily briefing, and a configurable `[uv]` threshold + pre-warn lead.
- A proactive `__uvmonitor__` IntervalTrigger watching today's active location(s) during daylight, firing pre-warn/crossing/all-clear once per day per location (durable `uv_alerts` dedup), failure-isolated from the briefing spine.

### What Worked
- **Front-loaded batch discuss + research → execution-only chain:** every phase had CONTEXT.md + RESEARCH.md ready, so the autonomous run was plan→execute with no mid-chain research stalls. Dependency-aware research flagged the cross-phase contracts (hourly seam, compute_uv reuse) before they were built.
- **Registry-as-single-source-of-truth (Phase 12) before the commands that plug into it** — Phases 13 (forecast) and 14 (uv) registered into one list with zero dispatch drift, confirmed at the integration audit.
- **Code review caught a genuine CRITICAL before ship:** Phase 14's UV math could crash a daily briefing on a malformed (present-but-non-numeric) payload — fixed at two layers (coerce-and-skip + call-site try/except). The per-phase review→fix loop closed 1 critical + 21 warnings across the milestone.
- **Structural enforcement of the high-risk monitor invariants (Phase 15):** failure isolation / no-time-series-pollution / dedup durability were grep-asserted in the plans and proven on a live BackgroundScheduler, not just claimed in prose.
- **The milestone integration audit found a real wiring gap** (`status` never reported the UV monitor as running) — fixed inline before tagging.

### What Was Inefficient
- **SUMMARY `one_liner` hygiene regressed a THIRD time** — the auto-generated MILESTONES.md accomplishments again captured "[Rule 3 - Blocking]" code-review deviation lines instead of deliverables, needing a full hand-rewrite at close. Flagged in v1.0 and v1.1; still not automated.
- **All four phases closed `human_needed`** because every user-facing surface needs a live-daemon UAT on `yahir-mint` (new Python modules don't hot-reload). Reasonable for this codebase, but it means the milestone ships code-complete with a standing UAT backlog rather than fully signed off.
- **A late doc-resolved `[uv]` knob (`pre_warn_lead_minutes`) was stored-and-validated in Phase 14 but only given behavior in Phase 15** — correct sequencing, but the split needs careful tracking so an "implemented" config field isn't mistaken for a working feature mid-milestone.

### Patterns Established
- **Self-describing registry as the single source of truth** for every command surface (CLI + chat + help), with anti-drift locked by test.
- **One pure, framework-free compute helper reused by N consumers** (`compute_uv` across briefing + command + monitor) — keep the math out of the interactive/scheduler layers so it's trivially reusable and testable.
- **Grep-asserted structural invariants in plans** for high-risk surfaces (isolation, no-persist, dedup) — the checker verifies the guarantee is enforced in code, not asserted in prose.
- **Degrade-not-raise + outer envelope as a two-layer isolation contract** for anything feeding the briefing spine.

### Key Lessons
1. **SUMMARY `one_liner` hygiene is now a three-milestone recurring tax** — automate it (lint/hook rejecting a one-liner that matches a deviation-rule pattern) instead of hand-rewriting MILESTONES.md every close.
2. **An autonomous chain over a live-service codebase accumulates deferred host UATs** — that's acceptable, but the close should consolidate them into one explicit operator backlog (done here via STATE.md Deferred Items + per-phase UAT files) rather than leaving four `human_needed` phases looking unfinished.
3. **The milestone integration audit earns its keep** — a cross-phase wiring gap (`status` ↔ monitor liveness) was invisible to every green per-phase suite and only surfaced when tracing seams end-to-end.
4. **Front-loaded batch research makes a long autonomous run smooth** — pre-resolving cross-phase contracts (the shared hourly seam, `compute_uv` reuse) avoided rework across four dependent phases.

### Cost Observations
- Model mix: Opus throughout (orchestration + all subagents); split not instrumented.
- Sessions: one continuous autonomous `/gsd-autonomous` run across all 4 phases + lifecycle.
- Notable: per-phase pattern-map → plan → plan-check → execute → verify → review → fix was consistent; the review→fix loop caught a briefing-crashing critical that all unit suites passed green around.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 5 | 21 | Initial MVP — vertical-slice first, foundations baked in from Phase 1 |
| v1.1 | 6 | 22 | Interactive + live-config — shared-core-first, Nyquist Wave-0 RED scaffolds, prerequisite-refactor-as-its-own-phase |
| v1.2 | 4 | 15 | Forecasts/commands/UV — front-loaded batch discuss+research → execution-only autonomous chain; registry-as-single-source-of-truth; grep-asserted structural invariants |

### Cumulative Quality

| Milestone | Tests | Requirements | Notable Dependency Additions |
|-----------|-------|--------------|--------------------|
| v1.0 | 186 passing | 37/37 satisfied | `sd_notify` (stdlib), `parse_days` (dep-free) |
| v1.1 | 291 passing | 16/16 satisfied | `discord.py` (inbound bot), `watchfiles` (file-watch), `cachetools` (TTL cache) |
| v1.2 | 575 passing | 18/18 code-verified (4 live UATs deferred) | none — reused existing One Call payload, APScheduler spine, registry, config-reload |

### Top Lessons (Verified Across Milestones)

1. (v1.0) Single composition root prevents manual-vs-scheduled path drift — re-verify across milestones.
2. (v1.0 → recurred v1.1 → recurred v1.2) SUMMARY `one_liner`/`status` frontmatter hygiene must be enforced at execution time — it has now cost **three** milestone-close hand-rewrites. Automate it (lint/hook) — repeating the lesson clearly isn't enough.
3. (v1.0, v1.1, v1.2) Live-host UAT catches what the offline suite structurally can't (reboot survival; non-root `/run` PID writes; live Discord/scheduler delivery) — budget a real deploy pass every milestone; an autonomous chain will accumulate these as deferred host UATs.
4. (v1.1, v1.2) Land the reusable seam first — shared core / prerequisite refactor / registry / pure compute helper — so the highest-risk behavior is provable in isolation before dependents exist.
5. (v1.2) The milestone integration audit catches cross-phase wiring gaps invisible to every green per-phase suite (e.g. a `status` line never wired to the monitor it reports on) — trace seams end-to-end, don't trust per-phase greens alone.
