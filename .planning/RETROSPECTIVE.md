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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 5 | 21 | Initial MVP — vertical-slice first, foundations baked in from Phase 1 |

### Cumulative Quality

| Milestone | Tests | Requirements | Zero-Dep Additions |
|-----------|-------|--------------|--------------------|
| v1.0 | 186 passing | 37/37 satisfied | `sd_notify` (stdlib), `parse_days` (dep-free) |

### Top Lessons (Verified Across Milestones)

1. (v1.0) Single composition root prevents manual-vs-scheduled path drift — re-verify across milestones.
