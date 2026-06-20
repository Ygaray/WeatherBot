# Phase 15: Proactive UV Sunscreen Monitor - Context

**Gathered:** 2026-06-18
**Status:** Ready for planning

<domain>
## Phase Boundary

A new **background intraday monitor** that polls forecast data on a configurable interval (default ~15 min, well under API limits) for **today's active location(s)** during **daylight only**, and proactively posts UV/sunscreen alerts to Discord — a **pre-warning**, a **threshold-reached** alert, and an **all-clear** when UV drops back below — each **at most once per day per location**. Runs **failure-isolated** from the briefing spine.

Covers: **UV-04, UV-05, UV-06.**

> Scope refinement (within UV-05): the monitor sends **three** once/day alert types — pre-warn, crossing (or "already-high"), and all-clear. The all-clear was added during discussion; it stays inside "notify me about the UV threshold so I can wear sunscreen efficiently" and adds no new data source.
</domain>

<decisions>
## Implementation Decisions

### Mechanism (D-01)
- Implement as a **new APScheduler `IntervalTrigger` job on the existing scheduler** (like the heartbeat `_heartbeat_tick`), **not** a separate asyncio thread. APScheduler jobs are already exception-isolated and the heartbeat precedent exists — this satisfies UV-06 (failure-isolated; an error never gates/stops a briefing) while reusing the scheduler spine. (UV-06's "same discipline as the v1.1 bot thread" is about the isolation guarantee, met here without a new thread.)

### "Today's active location(s)" (D-02, UV-04)
- A location is **active today** if it has **at least one enabled briefing slot whose days include today** in its own timezone. Only active locations are polled. A location you won't be at today (no scheduled send) is not monitored.
- Polling is **daylight-only**, bounded by that location's **sunrise/sunset** (from One Call) in its local tz.

### Pre-warning trigger (D-03, UV-05)
- **Both, whichever fires first**: (a) within **N minutes of the predicted (interpolated) crossing time**, default **30 min** (configurable); OR (b) current UV reaches **within ~1 of the threshold**. Whichever condition is met first sends the pre-warn. Catches fast climbs the morning forecast underestimated.

### Start-already-above (D-04)
- If the monitor's first daylight poll finds UV **already at/above threshold** (e.g. a midday daemon restart), send **one "already high" threshold-reached alert immediately** (still capped once/day/location) and **skip** the now-moot pre-warn.

### Cadence & all-clear (D-05)
- Default **15-minute interval, configurable**, well under API limits (daylight-only × active locations × 15 min ≪ One Call cap).
- **Keep polling through daylight even after pre-warn + crossing fire**, so the monitor can send an **all-clear** when UV drops back below the threshold (end of the protect window).
- **Each of the three alert types fires at most once per day per location** (no per-cycle spam).

### Alert tone (D-06)
- **Actionable + window.** Examples:
  - Pre-warn: "☀️ UV hits {threshold} in ~30 min in {loc} — sunscreen soon."
  - Crossing: "☀️ UV now ≥{threshold} in {loc} — sunscreen on. Protect ~10:00–16:00."
  - Already-high: same as crossing, phrased "UV already ≥{threshold} …".
  - All-clear: "✅ UV back below {threshold} in {loc} — protect window over."
- Delivered via the **same Discord webhook** as briefings (best-effort; a failed post never affects the briefing path).

### Claude's Discretion
- Exact once/day/location **dedup store**: reuse the existing `alerts` table / sent-log idempotency discipline keyed by `(location.id, local_date, alert_kind)`, vs an in-memory per-day set rebuilt at startup. Planner/researcher decides; must survive restarts sensibly and not re-spam after a reload.
- Config field names/shape for interval, pre-warn lead minutes, and value-proximity margin — `frozen=True` snapshot-compatible; hot-reloadable where it fits CFG-01 (interval may be restart-deferred like `[reload] watch` — acceptable, note it).
- How the monitor reuses Phase 14's UV computation helper (crossing/window/peak from hourly `uvi`) — it MUST reuse it, not re-derive.

### `hourly[]` fetch dependency (D-07)
> The monitor reuses Phase 14's UV helper, which interpolates over `hourly[].uvi`. The One Call `exclude` widening that exposes `hourly[]` is **owned by Phase 12** (D-06 in `12-CONTEXT.md`), and the UV helper + UV fixtures are owned by Phase 14 (D-05 in `14-CONTEXT.md`). Phase 15 owns neither — it **verifies** them: keep the Phase-14 Dependency Contract Wave-0 check (`fetch_onecall` returns non-empty `hourly[].uvi`; the `compute_uv` helper exists with the expected signature) so the monitor fails loudly at build time if either upstream piece regressed or never landed.

### RESEARCH CANDIDATE
This is the milestone's only genuinely new architectural element. Consider `/gsd-plan-phase 15 --research-phase`: the new poll loop, interpolated crossing prediction vs live readings, daylight windowing, three-state once/day dedup across restarts/reloads, and API-budget math are the risk areas.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §UV — UV-04, UV-05, UV-06
- `.planning/ROADMAP.md` §"Phase 15" — goal + 4 success criteria
- `.planning/phases/14-uv-index-on-demand-daily-briefing/14-CONTEXT.md` — the UV computation helper + threshold config this phase REUSES (read first)

### Existing seams to extend
- `weatherbot/scheduler/daemon.py` — `_heartbeat_tick` + its `IntervalTrigger` registration (~line 1078) is the precedent for the monitor job; `fire_slot` shows per-job isolation; `run_daemon` wiring. The monitor registers here.
- `weatherbot/weather/store.py` + the `alerts` table — candidate dedup/idempotency store (reuse the `INSERT OR IGNORE` no-loop discipline already used for alerts).
- `weatherbot/channels/discord.py` — outbound webhook for posting alerts (best-effort).
- `weatherbot/weather/models.py` — One Call `hourly[].uvi` + `daily[0].sunrise/sunset`; threshold currently hardcoded at `uvi_max >= 6` (Phase 14 makes it config-driven — reuse that).
- `weatherbot/config/models.py` / `weatherbot/config/holder.py` — config for interval/lead/margin; `ConfigHolder` snapshot reads.

No external specs — requirements fully captured in decisions above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_heartbeat_tick` on an `IntervalTrigger`: the exact shape the UV monitor copies (periodic, isolated, daemon-owned).
- `alerts` table + `INSERT OR IGNORE` dedup (Phase 4): a restart-safe once/day/location dedup primitive already in the codebase.
- Phase 14's UV helper (crossing/window/peak/category) + the unified threshold: the monitor consumes these, never re-derives.
- Best-effort Discord posting pattern (reload-outcome posts in `_do_reload`): a failed alert post must not abort anything.

### Established Patterns
- Failure isolation: APScheduler jobs don't crash the scheduler; the heartbeat already proves a periodic isolated job. UV-06 met without a new thread.
- Exactly-once / once-per-day idempotency keyed by stable `location.id` + local date (the sent-log/alerts discipline) — extend with an `alert_kind` dimension for the three UV alert types.
- API-budget consciousness (One Call card-on-file subscription): daylight-only × active-locations × 15 min keeps well under the daily cap; stop logic / active-only scoping keeps it lean.

### Integration Points
- Register the monitor `IntervalTrigger` job in `run_daemon` alongside the heartbeat; gate it behind a config enable (default on) and the daylight/active-location checks.
- Dedup keyed `(location.id, local_date, alert_kind ∈ {prewarn, crossing, allclear})`.
- Alerts posted via the existing Discord channel.
</code_context>

<specifics>
## Specific Ideas

- User's framing: "check the weather through the day, something sensible well below the API limit maybe every 15 minutes, and update me when the UV index threshold has been met (or is close to being met) … to be able to wear sunscreen efficiently." → pre-warn (close) + crossing (met) + all-clear (can stop), actionable wording with the protect window.
</specifics>

<deferred>
## Deferred Ideas

- Generalizing this intraday loop into real-time **severe-weather** push alerts (ENH-V2-03) — explicitly a future milestone; this phase establishes the pattern only for UV.
- Monitoring locations you'll be at but didn't schedule a briefing for — out of scope; "active = scheduled today" is the rule.

None blocking — discussion stayed within phase scope.
</deferred>

---

*Phase: 15-proactive-uv-sunscreen-monitor*
*Context gathered: 2026-06-18*
