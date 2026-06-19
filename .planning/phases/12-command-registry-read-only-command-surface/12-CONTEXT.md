# Phase 12: Command Registry & Read-Only Command Surface - Context

**Gathered:** 2026-06-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Generalize the single-command surface (`!weather`) into a **self-describing command registry** that both the Discord bot and the CLI read from, and add a set of read-only command views over already-available One Call 3.0 data: `help`, `alerts`, `locations`, `status`, `sun`, `wind`, `next-cloudy`. Every command routes through the shared read-only lookup core and the existing operator-id / command-only guard ladder, fully isolated from the briefing path. No new OpenWeather endpoints; no writes to the SQLite time series.

Covers: **CMD-09, CMD-10, CMD-11, CMD-12, CMD-13, CMD-14, CMD-15, CMD-16.**
</domain>

<decisions>
## Implementation Decisions

### Command naming & invocation (D-01)
- **Short names**, Discord-triggered with the existing `!` prefix and mirrored as CLI subcommands: `!uv`, `!wind`, `!alerts`, `!sun`, `!status`, `!locations`, `!help`, `!next-cloudy`.
- A location-taking command invoked with **no location argument defaults to the default (first configured) location** — mirroring bare `!weather`. (Applies to `uv`/`wind`/`alerts`/`sun`/`next-cloudy`. `locations`/`status`/`help` take no location.)
- Unknown location → same `UnknownLocationError` corrective-hint path already used by `weather` (lists valid names).

### `status` content (D-02) — report all of:
- **Next scheduled send per location** (next fire time for each location, read from the live scheduler — includes briefing and, post-Phase-13, forecast slots).
- **Alive + uptime** (daemon running + how long).
- **Bot + UV-monitor state** (whether the Discord inbound bot and — once Phase 15 lands — the UV monitor are active).
- **Last briefing result** (when the last briefing was sent and success/failure).
- NOTE: `status` is read-only — it reports state, never mutates config (reaffirms project-level "no two-way config editing" decision).

### `next-cloudy` semantics (D-03)
- **Hybrid lookahead**: use **hourly** cloud cover for the near term (next ~48h, daytime hours only) for precision, then fall back to **daytime-weighted daily** cloud cover for days 3–8. Return the first day/time meeting the bar.
- "Cloudy" = cloud cover **≥ a configurable threshold, default 60%**. Threshold is global config (a single knob), editable via the existing reload path.
- Judge cloudiness over **daytime hours only** (ignore overnight cloud) so the answer matches lived experience.
- Empty result (no cloudy day in range) → a clear "no cloudy day in the next N days" reply.

### `help` output (D-04)
- **Auto-generated from the registry** so it never drifts as commands are added (this is the core reason a registry exists).
- **Grouped by area** (e.g. Weather / Forecasts / UV / Info), **one-line description per command**.
- **Same content on both surfaces**: Discord renders it as an embed, CLI prints plain text.

### Cross-cutting (D-05, CMD-16)
- All new commands go through the **same guard ladder** as `!weather` (`author.bot` drop → operator-id check → `!` prefix → registry dispatch) and the **whole handler stays in the non-propagating try/except** so a command failure can never affect the scheduled briefing path.
- All command work runs **off the event loop** (`run_in_executor`) like the current `!weather` path, and reuses / extends the short-TTL `ForecastCache` so repeated commands don't refetch.

### Claude's Discretion
- Exact registry data structure (a dict/list of command specs with name, group, help-line, handler, takes-location flag) and how the CLI argparse subparsers are generated/kept in sync with the Discord dispatch — planner/researcher decides. Recommended: one registry module that the bot dispatch and the CLI subparser-builder both consume, so `help`, Discord dispatch, and CLI subcommands derive from one source.
- Whether `next-cloudy`'s daytime window reuses the Phase 14/15 sunrise/sunset derivation (likely yes once those land; for Phase 12 a simple fixed daytime window or `daily.clouds` is acceptable).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §Commands — CMD-09..16 definitions
- `.planning/ROADMAP.md` §"Phase 12" — goal + 5 success criteria

### Existing seams to extend (read before planning)
- `weatherbot/interactive/command.py` — the current single-keyword `parse_weather_command` (parse-don't-validate); the registry generalizes this.
- `weatherbot/interactive/bot.py` — `build_on_message` guard ladder (ORDER is load-bearing), off-loop `run_in_executor`, embed reply, non-propagating try/except. New dispatch plugs in after the prefix check.
- `weatherbot/interactive/lookup.py` — `lookup_weather` read-only core + `UnknownLocationError`. New commands reuse the resolve/fetch path; read-only (zero store writes) is a HARD constraint.
- `weatherbot/interactive/cache.py` — `ForecastCache` (short-TTL) reused/extended for new commands.
- `weatherbot/cli.py` — argparse `add_subparsers` surface (~line 593); the CLI half of the registry.
- `weatherbot/weather/models.py` — `Forecast` (current/`daily[0]` fields incl. `wind`, `uvi_max`, `alert`); `alerts`/`sun`/`wind` read from One Call payloads already fetched here.
- `weatherbot/scheduler/daemon.py` — `_announce_schedule` / job introspection for `status` next-send-times.

No external specs — requirements fully captured in decisions above.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `lookup_weather` + `Forecast`: already fetch `current` + `daily[0]` + `alerts[]` for both unit systems; `alerts`, `wind`, `sun` (sunrise/sunset live in the raw payload), and `next-cloudy` (daily `clouds`, hourly `clouds`) all read from this single fetch.
- `ForecastCache.lookup(name, config)`: the off-loop, TTL-cached entry the bot already uses — new commands ride the same cache.
- Guard ladder in `build_on_message`: reuse verbatim; only the dispatch step (currently `parse_weather_command`) becomes registry-driven.

### Established Patterns
- Read-only discipline (D-06 from Phase 6): on-demand surfaces must not write the store — every new command inherits this.
- Failure isolation: the whole inbound handler is wrapped so it can never stop a briefing (CMD-08/D-11). CMD-16 extends this guarantee to every new command.
- One shared core for CLI + Discord (Phase 6 decision) — the registry is the natural next step of that principle.

### Integration Points
- Discord: new dispatch inside `build_on_message` after the `!` prefix check.
- CLI: new subparsers in `cli.py`, generated from the same registry.
- `status` needs the live `BackgroundScheduler` + daemon health/last-briefing state surfaced to the command layer — planner to define how the command reaches scheduler/daemon state (likely via the holder/daemon context).
</code_context>

<specifics>
## Specific Ideas

- Hourly One Call data (`hourly[].clouds`, 48h) is available for the precise near-term `next-cloudy`; `daily[].clouds` covers days 3–8.
- `next-cloudy` and the UV features (Phases 14/15) share a "daytime window" concept (sunrise/sunset) — keep the derivation reusable.
</specifics>

<deferred>
## Deferred Ideas

- Geocoded-anywhere location lookup for these commands (CMD-V2-02) — out of scope; commands operate on configured names only.
- An "all locations" broadcast variant of weather/forecast commands — not requested; revisit if desired later.

None blocking — discussion stayed within phase scope.
</deferred>

---

*Phase: 12-command-registry-read-only-command-surface*
*Context gathered: 2026-06-18*
