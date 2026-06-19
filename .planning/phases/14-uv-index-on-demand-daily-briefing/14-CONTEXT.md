# Phase 14: UV Index — On-Demand & Daily Briefing - Context

**Gathered:** 2026-06-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver UV/sunscreen awareness on demand and in the daily briefing: an on-demand `uv <loc>` command (Phase 12 registry) plus current UV, today's max UV, and the **predicted local time UV first crosses a configurable sunscreen threshold** added to the daily briefing template — with the threshold editable in config (no code change), reusing already-fetched One Call data. Establishes the UV computation + config that Phase 15's monitor consumes.

Covers: **UV-01, UV-02, UV-03.**
</domain>

<decisions>
## Implementation Decisions

### Threshold (D-01, UV-03)
- **Single global threshold, default 6** (matches today's hardcoded `uvi_max >= 6` sunscreen hint). **No per-location override.**
- The configured threshold **unifies** three consumers: the existing "Wear sunscreen" hint (now reads config instead of the literal 6), the new briefing UV line, and the Phase 15 monitor.
- Editable via the existing reload path; lives in global config (a small `[uv]`-style table — planner decides exact shape).

### UV info set (D-02, UV-01/02) — compute and show:
Locked baseline: **current UV**, **today's max UV**, **predicted threshold-crossing time**. Plus all of:
- **Protect window (start–end)** — the time UV crosses ABOVE and when it drops back BELOW the threshold (e.g. "sunscreen ~10:00–16:00").
- **Time of peak UV** — clock time of the max (e.g. "peak 8 at 13:00").
- **Category word** — Low / Moderate / High / Very High / Extreme alongside the number (standard WHO UVI bands).
- "Stays below threshold today" → a clear single line instead of a crossing time/window.

### Crossing-time precision (D-03)
- **Interpolated (~minute)** between hourly UV points, not just the whole-hour bucket (e.g. "~9:40"). Applies to both the crossing time and the protect-window edges.

### `uv <loc>` command output (D-04, UV-01)
- Shows the full summary set above **plus a compact today-hourly UV line** (daytime hours with their UV values) — richer than the briefing line.
- The **daily briefing** carries the summary fields only (current/max/crossing/window/peak/category), no hourly line.

### `hourly[]` fetch dependency (D-05) — code change is Phase-12-owned
> UV crossing/window/peak interpolation needs `hourly[].uvi`. The One Call `exclude` widening (`"minutely,hourly"` → `"minutely"`) that makes `hourly[]` available is **owned by Phase 12** (D-06 in `12-CONTEXT.md`), which executes first and needs `hourly` for `next-cloudy`. So by the time Phase 14 runs the code change is already in place — **Phase 14 does NOT re-do the `exclude` edit.**
> Phase 14 STILL owns: (a) adding `hourly[].uvi` to the **UV test fixtures** (a new "uv crossing" fixture + a "stays below" fixture; the existing 8 fixtures lack `hourly`), and (b) a **Wave-0 verification** that `client.fetch_onecall` actually returns a non-empty `hourly[]` with `uvi` before building any interpolation logic — if Phase 12's change ever regressed, fail loudly here rather than shipping a UV helper that silently returns "stays below" for everything.

### Claude's Discretion
- Exact config table/field names for the threshold (and any UV display knobs) — planner decides; must be `frozen=True` snapshot-compatible.
- New placeholder tokens for the briefing template (e.g. `{uv_now}`, `{uv_max}`, `{uv_cross}`, `{uv_window}`, `{uv_peak}`, `{uv_category}`) and how they extend the renderer `CANONICAL` set with fail-loud validation.
- Interpolation method (linear between hourly `uvi` points) and how the daytime window is bounded (sunrise/sunset from One Call `daily[0]`/`current`).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §UV — UV-01, UV-02, UV-03 (UV-04..06 are Phase 15)
- `.planning/ROADMAP.md` §"Phase 14" — goal + 4 success criteria

### Existing seams to extend
- `weatherbot/weather/models.py` — `Forecast`: `uvi_max` (`daily[0].uvi`) already parsed; the `_hints` sunscreen line hardcodes `uvi_max >= 6` (line ~76) → switch to the configured threshold. Hourly `uvi` (One Call `hourly[]`, 48h) is in the raw payload for crossing-time/window/peak computation.
- `templates/renderer.py` — `CANONICAL` token set + `validate_template`; add UV tokens.
- `templates/briefing-*.txt` — where the new UV line(s) get added (editable).
- `weatherbot/config/models.py` — global config model for the new threshold field (`frozen=True`).
- `weatherbot/interactive/lookup.py` — read-only core; `uv` command rides it (no store writes).
- Phase 12 registry (`12-CONTEXT.md`) — `uv` command registration.

No external specs — requirements fully captured in decisions above. (WHO UV Index category bands are standard: 0–2 Low, 3–5 Moderate, 6–7 High, 8–10 Very High, 11+ Extreme.)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- One Call `hourly[].uvi` (48h) + `daily[0].uvi` + `current.uvi` are all in the already-fetched payloads — no new API call for any UV feature.
- `daily[0].sunrise`/`sunset` (epoch) for the daytime window, already present in the raw payload.
- Existing sunscreen hint is the natural place to unify on the configured threshold.

### Established Patterns
- Code-computed derived fields → placeholder tokens (the project's "no logic in templates" rule). UV summary fields follow this exactly.
- Fail-loud `validate_template` on unknown tokens — new UV tokens must be registered.
- Config validated on load, hot-reloaded via `ConfigHolder` — the threshold is just another validated field.

### Integration Points
- A UV computation helper (current/max/peak/crossing/window/category from imperial+metric payloads) feeding both the briefing placeholders and the `uv` command — **Phase 15's monitor reuses this same helper** (design it for reuse).
- Briefing template gains UV tokens; `uv` command handler in the Phase 12 registry adds the hourly line.
</code_context>

<specifics>
## Specific Ideas

- User's exact ask: "current and the maximum forecasted … the forecasted time the uv index will climb above this threshold … so in the morning I want to see the forecasted time the UV index will climb above this threshold." → current + max + interpolated crossing time are the non-negotiable briefing fields; protect window makes "wear sunscreen efficiently" actionable.
</specifics>

<deferred>
## Deferred Ideas

- Per-location UV thresholds — deliberately deferred (global-only chosen); revisit only if the two-city split needs different sensitivities.
- The proactive intraday UV monitor + alerts (UV-04/05/06) — that's Phase 15; this phase only computes/render + config, no background loop.

None blocking — discussion stayed within phase scope.
</deferred>

---

*Phase: 14-uv-index-on-demand-daily-briefing*
*Context gathered: 2026-06-18*
